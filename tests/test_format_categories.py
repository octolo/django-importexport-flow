"""Category configs activate formats, and hooks run around the shared trunks."""

from __future__ import annotations

import uuid
from io import BytesIO

import pandas as pd
import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from django_importexport_flow.engine.core.formats import (
    get_export_config,
    get_format,
    get_import_config,
)
from django_importexport_flow.engine.hooks import native_csv_import
from django_importexport_flow.models import CategoryConfig, Definition, FormatConfig
from django_importexport_flow.utils.process import process_export, process_import
from django_importexport_flow.utils.serialization import (
    import_export_configuration,
    serialize_export_configuration,
)
from tests.sample.models import Book
from tests.support import attach_import_spreadsheet, attach_pdf_export, attach_tabular_export


def _books():
    return ContentType.objects.get_for_model(Book)


@pytest.mark.django_db
def test_format_is_enabled_only_while_its_config_exists():
    definition = Definition_create()
    attach_tabular_export(export=definition, columns=["title"], formats=("csv",))
    Book.objects.create(title="Enabled", pages=1)
    body, _content_type, extension = process_export(
        export_definition=definition, export_format="csv"
    )
    assert extension == ".csv"
    assert b"Enabled" in body
    get_export_config(definition, "csv").delete()
    with pytest.raises(ValueError, match="not enabled"):
        process_export(export_definition=definition, export_format="csv")


def Definition_create(**extra):
    from django_importexport_flow.models import Definition

    fields = {"name": "Formats", "target": _books(), "manager": "objects"}
    fields.update(extra)
    return Definition.objects.create(direction="export", **fields)


@pytest.mark.django_db
def test_xlsx_uses_the_excel_hook_and_csv_does_not():
    excel = get_format("xlsx")
    csv = get_format("csv")
    assert excel.key == "excel"
    assert excel.default_export_hook.endswith("native_excel_export")
    assert excel.default_import_hook.endswith("native_excel_import")
    assert csv.default_export_hook.endswith("native_csv_export")
    assert excel.default_export_hook != csv.default_export_hook
    assert excel.default_import_hook != csv.default_import_hook


@pytest.mark.django_db
def test_common_options_merge_with_format_options():
    definition = Definition_create(name="Merged options")
    sheet = CategoryConfig.objects.create(
        definition=definition,
        category_key="spreadsheet",
        columns=["title"],
        configuration={"title_len_label": "Length"},
    )
    csv = FormatConfig.objects.create(
        category_config=sheet, format_key="csv", configuration={"delimiter": "|"}
    )
    merged = sheet.get_effective_configuration(csv)
    assert merged["title_len_label"] == "Length"
    assert merged["format"]["delimiter"] == "|"
    assert merged["csv"]["delimiter"] == "|"
    assert sheet.configuration == {"title_len_label": "Length"}
    with pytest.raises(ValidationError):
        sheet.configuration = {"csv": {"delimiter": ","}}
        sheet.full_clean()


def tiny_pdf(dataset, category, format_config, payload):
    return b"xxxx", "application/pdf", ".pdf"


@pytest.mark.django_db
def test_pdf_hook_replaces_only_pdf(auditor_user):
    from django_importexport_flow.utils.process import run_export_with_audit

    definition = Definition_create(name="Separate hooks")
    attach_tabular_export(export=definition, columns=["title"])
    attach_pdf_export(export=definition, template="<p>{{ object_list }}</p>")
    pdf_format = get_export_config(definition, "pdf")
    pdf_format.hook = ["tests.test_format_categories.tiny_pdf"]
    pdf_format.save()
    Book.objects.create(title="Csv row", pages=1)
    content, content_type, extension = run_export_with_audit(
        export_definition=definition,
        filter_payload={"export_format": "csv"},
        user=auditor_user,
    )
    assert extension == ".csv"
    assert b"Csv row" in content
    assert content_type.startswith("text/csv")
    pdf, pdf_type, pdf_ext = run_export_with_audit(
        export_definition=definition,
        filter_payload={"export_format": "pdf"},
        user=auditor_user,
    )
    assert pdf == b"xxxx"
    assert pdf_type == "application/pdf"
    assert pdf_ext == ".pdf"


def retitle(file, category, format_config, context):
    dataset = native_csv_import(file, category, format_config, context)
    dataset.dataframe.iloc[0, 0] = "From hook"
    return dataset


@pytest.mark.django_db
def test_import_hook_runs_before_the_shared_write(auditor_user):
    definition = Definition.objects.create(
        direction="import",
        name="Hook then write",
        target=_books(),
        columns_exclude=_exclude_but("title", "pages"),
    )
    attach_import_spreadsheet(definition)
    config = get_import_config(definition, "csv")
    config.hook = "tests.test_format_categories.retitle"
    config.save()
    raw = b"title,pages\nOriginal,3\n"
    upload = BytesIO(raw)
    upload.name = "books.csv"
    result = process_import(file=upload, import_definition=definition, user=auditor_user)
    assert result["success"] is True
    assert Book.objects.filter(title="From hook", pages=3).exists()
    assert not Book.objects.filter(title="Original").exists()


@pytest.mark.django_db
def test_old_v2_payload_drops_removed_fields():
    definition = Definition_create(name="Legacy payload")
    attach_tabular_export(export=definition, columns=["title"], formats=("csv",))
    payload = serialize_export_configuration(definition)
    for obj in payload["objects"]:
        model = obj["model"]
        if model.endswith("definition"):
            obj["fields"]["delegate_method"] = "sample_export_delegate"
        if model.endswith("formatconfig"):
            obj["fields"]["processing_backend"] = "mark_export_success"
            obj["fields"]["processing_backend_kwargs"] = {"byte_size": 1}
    loaded = import_export_configuration(payload)
    loaded = Definition.objects.get(pk=loaded.pk)
    assert loaded.name == "Legacy payload"
    assert loaded.category_configs.get().format_configs.get(format_key="csv").hook == []


@pytest.mark.django_db
def test_csv_and_excel_imports_write_the_same_rows(auditor_user):
    created = []
    for fmt, payload in (("csv", None), ("excel", None)):
        Book.objects.all().delete()
        definition = Definition.objects.create(
            direction="import",
            name=f"Same rows {fmt}",
            target=_books(),
            columns_exclude=_exclude_but("title", "pages"),
        )
        attach_import_spreadsheet(definition)
        frame = pd.DataFrame([{"title": "Shared", "pages": 8}])
        if fmt == "csv":
            upload = BytesIO(frame.to_csv(index=False).encode("utf-8"))
            upload.name = "books.csv"
        else:
            upload = BytesIO()
            frame.to_excel(upload, index=False, engine="openpyxl")
            upload.seek(0)
            upload.name = "books.xlsx"
        result = process_import(file=upload, import_definition=definition, user=auditor_user)
        assert result["success"] is True
        row = Book.objects.get()
        created.append((row.title, row.pages))
    assert created[0] == created[1] == ("Shared", 8)


@pytest.mark.django_db
def test_old_export_payload_is_rejected():
    payload = {
        "format_version": 1,
        "objects": [
            {
                "model": "django_importexport_flow.exportconfigtable",
                "pk": "1",
                "fields": {"columns": ["title"]},
            }
        ],
    }
    with pytest.raises(ValueError, match="Old payloads"):
        import_export_configuration(payload)


@pytest.mark.django_db
def test_category_configuration_rejects_format_options():
    definition = Definition_create(name="No format keys")
    document = CategoryConfig(
        definition=definition,
        category_key="document",
        configuration={"pdf": {"margin": 1}},
    )
    with pytest.raises(ValidationError):
        document.full_clean()


def _exclude_but(*keep: str) -> list[str]:
    from django_importexport_flow.engine.core.import_ import default_importable_column_paths

    full = default_importable_column_paths(Book)
    return [path for path in full if path not in keep]


def _migrate(executor: MigrationExecutor, target: str) -> None:
    executor.loader.build_graph()
    executor.migrate([("django_importexport_flow", target)])


@pytest.mark.django_db(transaction=True)
def test_migration_copies_table_pdf_and_import_backends():
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes("django_importexport_flow")[0][1]
    try:
        _migrate(executor, "0004_column_translation")
        old = executor.loader.project_state(
            [("django_importexport_flow", "0004_column_translation")]
        ).apps
        translation = old.get_model("django_importexport_flow", "ColumnTranslation")
        assert not translation._meta.proxy
        with pytest.raises(LookupError):
            old.get_model("django_importexport_flow", "ColumnLabel")
        ExportDefinition = old.get_model("django_importexport_flow", "ExportDefinition")
        ImportDefinition = old.get_model("django_importexport_flow", "ImportDefinition")
        ExportConfigTable = old.get_model("django_importexport_flow", "ExportConfigTable")
        ExportConfigPdf = old.get_model("django_importexport_flow", "ExportConfigPdf")
        ExportRequest = old.get_model("django_importexport_flow", "ExportRequest")

        table_only = ExportDefinition.objects.create(name="Table only", manager="objects")
        ExportDefinition.objects.filter(pk=table_only.pk).update(
            created_by="auditor",
            named_id="shared-name",
        )
        ExportConfigTable.objects.create(
            export=table_only,
            columns=["title"],
            configuration={
                "csv": {"delimiter": ";"},
                "excel": {"sheet": "Books"},
                "json": {"indent": 2},
                "annotation_columns": ["title_len"],
                "split_by": "author.name",
            },
        )
        table_only.exclude_relations.add(ContentType.objects.get_for_model(Book).pk)
        pdf_only = ExportDefinition.objects.create(name="PDF only", manager="objects")
        ExportConfigPdf.objects.create(
            export=pdf_only,
            template="<p>pdf</p>",
            configuration={"orientation": "landscape"},
        )
        both = ExportDefinition.objects.create(name="Table and PDF", manager="objects")
        ExportConfigTable.objects.create(
            export=both,
            columns=["pages"],
            configuration={"csv": {"delimiter": "|"}},
        )
        ExportConfigPdf.objects.create(export=both, template="<p>both</p>", configuration={})
        imported = ImportDefinition.objects.create(
            name="Imported",
            configuration={"csv": {"delimiter": ";"}, "annotation_columns": ["kept"]},
        )
        ImportDefinition.objects.filter(pk=imported.pk).update(named_id="shared-name")
        ExportRequest.objects.create(export_definition=table_only)

        _migrate(executor, "0005_export_import_categories")
        new = executor.loader.project_state(
            [("django_importexport_flow", "0005_export_import_categories")]
        ).apps
        Definition = new.get_model("django_importexport_flow", "Definition")
        Category = new.get_model("django_importexport_flow", "CategoryConfig")
        Format = new.get_model("django_importexport_flow", "FormatConfig")
        NewRequest = new.get_model("django_importexport_flow", "ExportRequest")

        table = Definition.objects.get(name="Table only")
        assert table.direction == "export"
        assert table.created_by == "auditor"
        assert table.named_id == "shared-name"
        assert list(table.exclude_relations.values_list("model", flat=True)) == ["book"]
        sheet = Category.objects.get(definition=table, category_key="spreadsheet")
        assert sheet.columns == ["title"]
        assert sheet.configuration["annotation_columns"] == ["title_len"]
        assert "csv" not in sheet.configuration
        assert "split_by" not in sheet.configuration
        csv = Format.objects.get(category_config=sheet, format_key="csv")
        assert csv.configuration == {"delimiter": ";"}
        assert csv.hook == []
        excel = Format.objects.get(category_config=sheet, format_key="excel")
        assert excel.configuration["sheet"] == "Books"
        assert excel.configuration["split_by"] == "author.name"
        structured = Category.objects.get(definition=table, category_key="structured_data")
        assert structured.columns == ["title"]
        assert Format.objects.get(category_config=structured, format_key="json").configuration == {
            "indent": 2
        }
        assert not Category.objects.filter(definition=table, category_key="document").exists()
        assert NewRequest.objects.get().export_definition_id == table.pk

        pdf_definition = Definition.objects.get(name="PDF only")
        document = Category.objects.get(definition=pdf_definition, category_key="document")
        pdf = Format.objects.get(category_config=document, format_key="pdf")
        assert pdf.template == "<p>pdf</p>"
        assert pdf.configuration == {"orientation": "landscape"}
        assert pdf.hook == []
        assert not Category.objects.filter(
            definition=pdf_definition, category_key="spreadsheet"
        ).exists()

        combined = Definition.objects.get(name="Table and PDF")
        assert Category.objects.filter(definition=combined, category_key="spreadsheet").exists()
        combined_document = Category.objects.get(definition=combined, category_key="document")
        assert Format.objects.get(category_config=combined_document).template == "<p>both</p>"

        imported_definition = Definition.objects.get(name="Imported")
        assert imported_definition.direction == "import"
        assert imported_definition.named_id == "shared-name"
        imported_sheet = Category.objects.get(definition=imported_definition)
        imported_csv = Format.objects.get(category_config=imported_sheet, format_key="csv")
        assert imported_csv.configuration == {"delimiter": ";"}
        assert imported_csv.hook == []
        assert "delegate_method" not in {field.name for field in Definition._meta.fields}
        assert "processing_backend" not in {field.name for field in Format._meta.fields}
        assert imported_sheet.configuration["annotation_columns"] == ["kept"]
        assert "csv" not in imported_sheet.configuration

        export_proxy = new.get_model("django_importexport_flow", "ExportDefinition")
        spreadsheet_proxy = new.get_model("django_importexport_flow", "ExportSpreadsheetConfig")
        pdf_proxy = new.get_model("django_importexport_flow", "ExportPdfFormat")
        assert export_proxy._meta.proxy
        assert spreadsheet_proxy._meta.proxy
        assert pdf_proxy._meta.proxy
        assert export_proxy._meta.db_table == Definition._meta.db_table
        assert spreadsheet_proxy._meta.db_table == Category._meta.db_table
        assert pdf_proxy._meta.db_table == Format._meta.db_table
        with pytest.raises(LookupError):
            new.get_model("django_importexport_flow", "ImportDocumentConfig")
        tables = set(connection.introspection.table_names())
        assert "django_importexport_flow_exportdefinition" not in tables
        assert "django_importexport_flow_exportcsvformat" not in tables
        assert "django_importexport_flow_columntranslation" in tables
    finally:
        _migrate(executor, latest)
        connection.close()


@pytest.mark.django_db(transaction=True)
def test_migration_rejects_shared_definition_uuids():
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes("django_importexport_flow")[0][1]
    try:
        _migrate(executor, "0004_column_translation")
        old = executor.loader.project_state(
            [("django_importexport_flow", "0004_column_translation")]
        ).apps
        ExportDefinition = old.get_model("django_importexport_flow", "ExportDefinition")
        ImportDefinition = old.get_model("django_importexport_flow", "ImportDefinition")
        shared = uuid.uuid4()
        export_row = ExportDefinition.objects.create(name="Export uuid", manager="objects")
        import_row = ImportDefinition.objects.create(name="Import uuid")
        ExportDefinition.objects.filter(pk=export_row.pk).update(uuid=shared)
        ImportDefinition.objects.filter(pk=import_row.pk).update(uuid=shared)
        with pytest.raises(ValueError, match="share UUIDs"):
            _migrate(executor, "0005_export_import_categories")
        ExportDefinition.objects.all().delete()
        ImportDefinition.objects.all().delete()
    finally:
        _migrate(executor, latest)
        connection.close()


@pytest.mark.django_db
def test_admin_lists_the_three_concrete_models(admin_user, client):
    from django.urls import reverse

    definition = Definition_create(name="Admin formats")
    attach_tabular_export(export=definition, columns=["title"], formats=("csv",))
    client.force_login(admin_user)
    index = client.get(reverse("admin:index"))
    assert index.status_code == 200
    page = index.content.decode()
    assert "Export definitions" in page
    assert "Export configs" in page
    assert "Export formats" in page
    change = client.get(
        reverse("admin:django_importexport_flow_exportdefinition_change", args=[definition.pk])
    )
    assert change.status_code == 200
    assert "spreadsheet" in change.content.decode()
    category = definition.category_configs.get(category_key="spreadsheet")
    category_page = client.get(
        reverse("admin:django_importexport_flow_exportcategoryconfig_change", args=[category.pk])
    )
    assert category_page.status_code == 200
    assert "csv" in category_page.content.decode()


@pytest.mark.django_db
def test_excel_config_is_selected_for_xlsx_not_csv():
    definition = Definition_create(name="Pick excel")
    attach_tabular_export(export=definition, columns=["title"])
    excel = get_export_config(definition, "xlsx")
    csv = get_export_config(definition, "csv")
    assert isinstance(excel, FormatConfig)
    assert isinstance(csv, FormatConfig)
    assert excel.format_key == "excel"
    assert csv.format_key == "csv"
    assert excel.pk != csv.pk
