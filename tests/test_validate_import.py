"""Tests for :func:`django_importexport_flow.utils.process.validate_import` and helpers."""

from __future__ import annotations

import csv
import json
from io import BytesIO, StringIO
from pathlib import Path

import pandas as pd
import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models.deletion import ProtectedError
from django.urls import reverse
from django.utils.translation import override
from openpyxl import load_workbook

from django_importexport_flow.models import (
    ColumnTranslation,
    Definition,
    ExportRequest,
    ImportRequest,
)
from django_importexport_flow.utils.process import (
    generate_example_file,
    import_example_download_response,
    normalize_template_headers,
    process_import,
    validate_import,
)
from tests.sample.models import Book
from tests.support import attach_import_spreadsheet, attach_tabular_export

FIXTURES = Path(__file__).resolve().parent / "fixtures"
IMPORT_BOOK_CSV = FIXTURES / "import_book.csv"


@pytest.fixture
def prefilled_template():
    target = ContentType.objects.get_for_model(Book)
    export = Definition.objects.create(
        direction="export", name="Template source", target=target, order_by=["id"]
    )
    attach_tabular_export(export, ["id", "title"])
    definition = Definition.objects.create(
        direction="import",
        name="Prefilled import",
        target=target,
        template_export=export,
        exclude_primary_key=False,
        match_fields=["id"],
        max_relation_hops=0,
        columns_exclude=["price", "metadata", "publication_date", "recorded_at", "author"],
    )
    attach_import_spreadsheet(
        definition,
        {
            "template_columns": ["id", "title", "pages"],
            "template_hook": "not_allowed.must_not_run",
        },
    )
    return definition, export


@pytest.mark.django_db
@pytest.mark.parametrize("file_format", ["csv", "excel", "json"])
@pytest.mark.parametrize("localized", [False, True])
def test_export_prefills_native_template_with_translations(
    prefilled_template, file_format, localized
):
    definition, _export = prefilled_template
    category = definition.category_configs.get()
    if localized:
        category.configuration["template_header_mode"] = "localized"
        category.save()
    for path, label in (("id", "Identifiant"), ("title", "Titre"), ("pages", "Pages")):
        ColumnTranslation.objects.create(
            content_type=definition.target, path=path, language="fr", label=label
        )
    first = Book.objects.create(title="000123456", pages=12)
    second = Book.objects.create(title="Second", pages=20)

    with override("fr"):
        body, _, _ = generate_example_file(definition, example_format=file_format)

    values = [[first.pk, first.title, ""], [second.pk, second.title, ""]]
    if file_format == "json":
        assert json.loads(body) == [
            {"id": book.pk, "title": book.title, "pages": ""} for book in (first, second)
        ]
    else:
        if file_format == "csv":
            rows = list(csv.reader(StringIO(body.decode())))
            values = [[str(value) for value in row] for row in values]
        else:
            workbook = load_workbook(BytesIO(body))
            rows = [list(row) for row in workbook["Sheet1"].values]
            workbook.close()
            values = [[row[0], row[1], None] for row in values]
        labels = ["Identifiant", "Titre", "Pages"]
        assert rows == ([labels] if localized else [["id", "title", "pages"], labels]) + values
        with override("en"):
            normalized = normalize_template_headers(
                definition, pd.DataFrame([values[0]], columns=labels)
            )
        assert list(normalized.columns) == ["id", "title", "pages"]
    assert not ImportRequest.objects.exists()
    assert not ExportRequest.objects.exists()


@pytest.mark.django_db
def test_prefilled_contacts_can_be_modified_and_reimported(prefilled_template, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    definition, _export = prefilled_template
    book = Book.objects.create(title="Original", pages=1)
    body, _, _ = generate_example_file(definition, example_format="json")
    data = json.loads(body)
    data[0].update(title="Updated", pages=42)

    upload = SimpleUploadedFile("contacts.csv", pd.DataFrame(data).to_csv(index=False).encode())
    result = process_import(file=upload, import_definition=definition)

    assert result["success"], result["import_request"].error_trace
    book.refresh_from_db()
    assert (book.title, book.pages) == ("Updated", 42)
    assert Book.objects.count() == 1


@pytest.mark.django_db
def test_template_export_requires_filters_and_preserves_scoping(prefilled_template, admin_client):
    definition, export = prefilled_template
    export.filter_mandatory = {"get": {"name": "title"}}
    export.manager_kwargs_mandatory = {"kwargs": {"selected": "pk"}}
    export.save()
    book = Book.objects.create(title="Selected")
    Book.objects.create(title="Hidden")
    with pytest.raises(ValueError, match="Missing filter payload"):
        generate_example_file(definition, example_format="csv")
    filters = {"fr_get_name": book.title, "mg_kw_selected": str(book.pk)}
    response = import_example_download_response(
        definition, example_format="json", filter_payload=filters
    )
    assert json.loads(response.content) == [{"id": book.pk, "title": book.title, "pages": ""}]

    url = reverse(
        "admin:django_importexport_flow_importdefinition_download_example_file",
        args=[definition.pk],
    )
    missing = admin_client.post(url, {"example_format": "json"})
    assert missing.status_code == 200
    assert "fr_get_name" in missing.context["adminform"].form.errors
    assert "mg_kw_selected" in missing.context["adminform"].form.errors
    download = admin_client.post(url, {"example_format": "json", **filters})
    assert json.loads(download.content) == json.loads(response.content)


@pytest.mark.django_db
@pytest.mark.parametrize("columns", [["price"], ["id", "id"], ["tags.*[name]"]])
def test_template_export_rejects_incompatible_columns(prefilled_template, columns):
    definition, export = prefilled_template
    Book.objects.create(title="Expanded").tags.create(name="Tag")
    category = export.category_configs.get(category_key="spreadsheet")
    category.columns = columns
    category.save()
    with pytest.raises(ValueError, match="unique technical paths"):
        generate_example_file(definition, example_format="csv")


@pytest.mark.django_db
def test_template_export_validates_direction_and_protects_source(prefilled_template):
    definition, export = prefilled_template
    with pytest.raises(ProtectedError):
        export.delete()
    definition.template_export = definition
    with pytest.raises(ValidationError):
        definition.save()
    export.template_export = export
    with pytest.raises(ValidationError, match="Only imports"):
        export.save()


@pytest.mark.django_db
def test_empty_template_export_and_formula_values(prefilled_template):
    definition, _export = prefilled_template
    body, _, _ = generate_example_file(definition, example_format="json")
    assert json.loads(body) == []
    Book.objects.create(title="=DANGEROUS()")
    body, _, _ = generate_example_file(definition, example_format="csv")
    assert list(csv.reader(StringIO(body.decode())))[-1][1] == "'=DANGEROUS()"
    body, _, _ = generate_example_file(definition, example_format="json")
    assert json.loads(body)[0]["title"] == "=DANGEROUS()"


@pytest.mark.django_db
def test_json_template_keeps_exported_structured_values(prefilled_template):
    definition, export = prefilled_template
    category = definition.category_configs.get()
    category.configuration["template_columns"] = ["title", "metadata", "pages"]
    category.save()
    source = export.category_configs.get(category_key="structured_data")
    source.columns = ["title", "metadata"]
    source.save()
    metadata = {"contact": {"active": False}, "values": [0, "000123456"]}
    Book.objects.create(title="Structured", metadata=metadata)

    body, _, _ = generate_example_file(definition, example_format="json")

    assert json.loads(body) == [{"title": "Structured", "metadata": metadata, "pages": ""}]


@pytest.mark.django_db
def test_template_export_admin_requires_export_permission(
    prefilled_template, client, django_user_model
):
    from django.contrib.auth.models import Permission

    definition, _export = prefilled_template
    user = django_user_model.objects.create_user(username="import-viewer", is_staff=True)
    user.user_permissions.add(Permission.objects.get(codename="view_importdefinition"))
    client.force_login(user)
    url = reverse(
        "admin:django_importexport_flow_importdefinition_download_example_file",
        args=[definition.pk],
    )
    assert client.post(url, {"example_format": "csv"}).status_code == 403
    assert client.get(url).status_code == 403


@pytest.mark.django_db
def test_validate_import_builds_validation_dataset():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="import",
        name="Books import",
        target=ct,
        filter_config={},
    )
    attach_import_spreadsheet(definition)
    with IMPORT_BOOK_CSV.open("rb") as f:
        out = validate_import(file=f, import_definition=definition, row_limit=5)

    assert out["errors"] == []
    vds = out["validation_dataset"]
    assert vds["row_count"] >= 1
    assert vds["preview_row_count"] >= 1
    assert len(vds["rows"]) == vds["preview_row_count"]
    assert vds["column_paths"]
    assert len(vds["column_labels"]) == len(vds["column_paths"])
    assert len(vds["columns"]) == len(vds["column_paths"])
    first = vds["rows"][0]
    assert "title" in first
    assert first["title"]


@pytest.mark.django_db
def test_process_import_preview_only_includes_validation_dataset():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="import",
        name="Books import",
        target=ct,
        filter_config={},
    )
    attach_import_spreadsheet(definition)
    with IMPORT_BOOK_CSV.open("rb") as f:
        prev = process_import(
            file=f,
            import_definition=definition,
            preview_only=True,
            preview_row_limit=5,
        )
    assert prev["errors"] == []
    assert "validation_dataset" in prev
    assert prev["validation_dataset"]["row_count"] >= 1


@pytest.mark.django_db
def test_validate_import_accepts_dataframe():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="import",
        name="Books import",
        target=ct,
        filter_config={},
    )
    attach_import_spreadsheet(definition)
    df = pd.read_csv(IMPORT_BOOK_CSV)
    out = validate_import(dataframe=df, import_definition=definition, row_limit=5)
    assert out["errors"] == []
    assert out["validation_dataset"]["preview_row_count"] >= 1


@pytest.mark.django_db
def test_generate_example_file_csv_json_excel():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="import",
        name="Ex",
        target=ct,
        filter_config={},
    )
    attach_import_spreadsheet(definition)
    for fmt in ("csv", "json", "excel"):
        body, ct_hdr, ext = generate_example_file(definition, example_format=fmt)
        assert body
        assert ext in (".csv", ".json", ".xlsx")
        assert ct_hdr


@pytest.mark.django_db
@pytest.mark.parametrize("file_format", ["csv", "excel"])
@pytest.mark.parametrize("localized", [False, True])
def test_configured_template_localizes_download(file_format, localized):
    """Retain the technical row unless the definition opts into localized headers."""
    definition = Definition.objects.create(
        direction="import",
        name="Books import",
        target=ContentType.objects.get_for_model(Book),
    )
    category = attach_import_spreadsheet(definition)
    category.configuration = {
        "template_columns": ["holder", "quantity"],
        "template_labels": ["Titulaire", "Quantité"],
        "template_labels_by_language": {"en": ["Holder", "Quantity"]},
        "template_filename": {"en": "Register template"},
    }
    if localized:
        category.configuration["template_header_mode"] = "localized"
    category.save()

    with override("en-gb"):
        response = import_example_download_response(definition, example_format=file_format)

    if file_format == "csv":
        rows = list(csv.reader(StringIO(response.content.decode())))
        extension = "csv"
    else:
        workbook = load_workbook(BytesIO(response.content))
        rows = [list(row) for row in workbook["Sheet1"].values]
        workbook.close()
        extension = "xlsx"
    expected = [["Holder", "Quantity"]]
    if not localized:
        expected.insert(0, ["holder", "quantity"])
    assert rows[:-1] == expected
    assert all(not cell for cell in rows[-1])
    assert (
        response["Content-Disposition"] == f'attachment; filename="Register_template.{extension}"'
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "headers",
    [
        ["Quantity", "quantity"],
        ["Quantity", "Quantity.1"],
    ],
)
def test_normalize_template_headers_rejects_duplicate_keys(headers):
    """Reject both mixed aliases and duplicate headers suffixed by pandas."""
    definition = Definition.objects.create(direction="import", name="Example")
    category = attach_import_spreadsheet(definition)
    category.configuration = {
        "template_columns": ["quantity"],
        "template_labels": ["Quantity"],
    }
    category.save()

    with pytest.raises(ValueError, match="[Dd]uplicate|Multiple headers"):
        normalize_template_headers(definition, pd.DataFrame([[1, 2]], columns=headers))


@pytest.mark.django_db
def test_localized_template_rejects_ambiguous_aliases_across_languages():
    """Reject an alias shared by different keys even across languages."""
    definition = Definition.objects.create(direction="import", name="Example")
    category = attach_import_spreadsheet(definition)
    category.configuration = {
        "template_header_mode": "localized",
        "template_columns": ["holder", "quantity"],
        "template_labels": ["Titulaire", "Quantité"],
        "template_labels_by_language": {"en": ["Holder", "Titulaire"]},
    }
    category.save()

    with pytest.raises(ValueError, match="ambiguous template header"):
        generate_example_file(definition, example_format="csv")


@pytest.mark.django_db
def test_configured_template_rejects_misaligned_labels():
    definition = Definition.objects.create(direction="import", name="Example")
    category = attach_import_spreadsheet(definition)
    category.configuration = {
        "template_columns": ["holder", "quantity"],
        "template_labels": ["Holder"],
    }
    category.save()

    with pytest.raises(ValueError, match="one string per template column"):
        generate_example_file(definition, example_format="csv")


@pytest.mark.django_db
@pytest.mark.parametrize("language,label", [("fr", "Titulaire"), ("en-gb", "Holder")])
def test_configured_template_uses_column_translation_and_accepts_other_languages(language, label):
    """Use the catalog for processor keys as well as real model fields."""
    target = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(direction="import", name="Catalog", target=target)
    attach_import_spreadsheet(
        definition, {"template_columns": ["holder"], "template_header_mode": "localized"}
    )
    for code, text in (("fr", "Titulaire"), ("en", "Holder")):
        ColumnTranslation.objects.create(
            content_type=target, path="holder", language=code, label=text
        )

    with override(language):
        body, _, _ = generate_example_file(definition, example_format="csv")
        normalized = normalize_template_headers(definition, pd.DataFrame([{"Titulaire": "Ada"}]))

    assert list(csv.reader(StringIO(body.decode()))) == [[label], [""]]
    assert normalized.to_dict("records") == [{"holder": "Ada"}]


@pytest.mark.django_db
def test_validate_import_empty_rows_when_errors():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="import",
        name="Bad target",
        target=ct,
        columns_exclude=[
            "title",
            "pages",
            "price",
            "publication_date",
            "recorded_at",
            "author.name",
            "metadata",
        ],
        filter_config={},
    )
    attach_import_spreadsheet(definition)
    with IMPORT_BOOK_CSV.open("rb") as f:
        out = validate_import(file=f, import_definition=definition)

    assert out["errors"]
    assert out["validation_dataset"]["rows"] == []
    assert out["dataframe"] is None
