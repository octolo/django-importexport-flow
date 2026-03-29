import copy
import json

import pandas as pd
import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from django_importexport_flow.engine import ExportTableEngine
from django_importexport_flow.utils.import_tabular import (
    IMPORT_COLUMN_PATHS_KEY,
    default_importable_column_paths,
    effective_import_column_paths,
    resolve_import_column_paths,
    sample_headers_for_import_definition,
    validate_import_preview,
)
from django_importexport_flow.utils import resolve_table_column_label
from django_importexport_flow.models import ImportDefinition
from django_importexport_flow.utils.serialization import import_import_definition, serialize_import_definition
from tests.sample.models import Author, Book


def _book_columns_exclude_all_but(*keep: str) -> list[str]:
    full = default_importable_column_paths(Book)
    return [p for p in full if p not in keep]


@pytest.mark.django_db
def test_default_import_paths_author_includes_reverse_fk_slots():
    """Reverse FK accessors use ``book_set.N.field`` like M2M slots (not forward ``author.*``)."""
    paths = default_importable_column_paths(Author)
    assert "name" in paths
    assert "book_set.0.title" in paths
    assert "book_set.1.title" in paths
    assert "book_set.0.pages" in paths


@pytest.mark.django_db
def test_resolve_table_column_label_book_set_slot():
    from django_importexport_flow.utils import resolve_table_column_label

    assert "Book title" in resolve_table_column_label(Author, "book_set.0.title")


@pytest.mark.django_db
def test_effective_import_paths_respects_import_max_relation_hops():
    """Hop limit trims nested paths (author.profile.bio, tags.0.category.name)."""
    ct = ContentType.objects.get_for_model(Book)
    ri = ImportDefinition.objects.create(
        name="Hop cap",
        target=ct,
        import_max_relation_hops=1,
        columns_exclude=[],
        filter_config={},
    )
    paths = effective_import_column_paths(ri)
    assert "title" in paths
    assert "author.name" in paths
    assert "author.profile.bio" not in paths
    assert "tags.0.name" in paths
    assert "tags.0.category.name" not in paths


@pytest.mark.django_db
def test_effective_import_paths_zero_hops_excludes_nested_and_slots():
    """0 hops: no nested FK, M2M slots, or reverse-O2M slot columns."""
    ct = ContentType.objects.get_for_model(Book)
    ri = ImportDefinition.objects.create(
        name="Zero hops",
        target=ct,
        import_max_relation_hops=0,
        columns_exclude=[],
        filter_config={},
    )
    paths = effective_import_column_paths(ri)
    assert "title" in paths
    assert "author.name" not in paths
    assert "tags.0.name" not in paths

    ct_a = ContentType.objects.get_for_model(Author)
    ri_a = ImportDefinition.objects.create(
        name="Zero hops author",
        target=ct_a,
        import_max_relation_hops=0,
        columns_exclude=[],
        filter_config={},
    )
    paths_a = effective_import_column_paths(ri_a)
    assert "name" in paths_a
    assert "book_set.0.title" not in paths_a


@pytest.mark.django_db
def test_default_import_paths_book_no_id_bare_author_or_author_pk():
    """Import set uses nested author scalars only: no ``id``, ``author``, or ``author.id``."""
    paths = default_importable_column_paths(Book)
    assert "id" not in paths
    assert "author" not in paths
    assert "author.id" not in paths
    assert "author.name" in paths
    assert "author.profile.bio" in paths
    assert "tags.0.name" in paths
    assert "tags.1.name" in paths
    assert "tags.0.importance" in paths
    assert "tags.1.importance" in paths
    assert "tags.0.category.name" in paths
    assert "tags.1.category.name" in paths


@pytest.mark.django_db
def test_resolve_table_column_label_author_profile_bio():
    from django_importexport_flow.utils import resolve_table_column_label

    assert resolve_table_column_label(Book, "author.profile.bio") == "Biography"


@pytest.mark.django_db
def test_table_engine_with_report_import():
    ct = ContentType.objects.get_for_model(Book)
    book = Book.objects.create(title="Guide", pages=42)
    ri = ImportDefinition.objects.create(
        name="Books import",
        target=ct,
        columns_exclude=_book_columns_exclude_all_but("title", "pages"),
        configuration={"csv": {"delimiter": ";"}, "excel": {"sheet": "Data"}},
    )
    engine = ExportTableEngine(ri)
    title_v = str(Book._meta.get_field("title").verbose_name)
    pages_v = str(Book._meta.get_field("pages").verbose_name)
    assert engine.get_headers() == [title_v, pages_v]
    assert engine.get_rows() == [["Guide", 42]]
    assert list(engine.get_queryset()) == [book]
    assert engine.config is ri
    assert engine.get_configuration()["csv"]["delimiter"] == ";"


@pytest.mark.django_db
def test_report_import_filter_config_limits_queryset():
    ct = ContentType.objects.get_for_model(Book)
    Book.objects.create(title="A", pages=1)
    b2 = Book.objects.create(title="B", pages=2)
    ri = ImportDefinition.objects.create(
        name="Scoped",
        target=ct,
        filter_config={"pages": 2},
        columns_exclude=_book_columns_exclude_all_but("title"),
    )
    engine = ExportTableEngine(ri)
    assert list(engine.get_queryset()) == [b2]


@pytest.mark.django_db
def test_serialize_import_roundtrip():
    ct = ContentType.objects.get_for_model(Book)
    ImportDefinition.objects.create(
        name="Roundtrip",
        target=ct,
        columns_exclude=["title"],
        configuration={"csv": {"delimiter": "|"}},
    )
    data = serialize_import_definition(ImportDefinition.objects.get(name="Roundtrip"))
    assert data["format_version"] == 1
    assert len(data["objects"]) == 1
    assert data["objects"][0]["model"] == "django_importexport_flow.importdefinition"

    payload = copy.deepcopy(data)
    payload["objects"][0]["pk"] = "00000000-0000-0000-0000-000000009999"
    loaded = import_import_definition(payload)
    assert str(loaded.pk) != "00000000-0000-0000-0000-000000009999"
    assert loaded.name == "Roundtrip"
    assert loaded.columns_exclude == ["title"]
    assert loaded.configuration["csv"]["delimiter"] == "|"

    again = import_import_definition(serialize_import_definition(loaded))
    assert again.pk == loaded.pk
    assert again.name == "Roundtrip"


@pytest.mark.django_db
def test_import_definition_legacy_json_label_still_loads():
    """Exports saved with the old ``django_reporting.reportimport`` label deserialize."""
    ct = ContentType.objects.get_for_model(Book)
    payload = {
        "format_version": 1,
        "objects": [
            {
                "model": "django_reporting.reportimport",
                "pk": 1,
                "fields": {
                    "uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "name": "Legacy label",
                    "description": None,
                    "target": ct.pk,
                    "order_by": [],
                    "filter_config": {},
                    "filter_request": {},
                    "filter_mandatory": {},
                    "columns": ["title"],
                    "configuration": {},
                },
            }
        ],
    }
    loaded = import_import_definition(payload)
    assert loaded.name == "Legacy label"
    assert loaded.columns_exclude == []


@pytest.mark.django_db
def test_report_import_admin_sample_downloads(client):
    User = get_user_model()
    User.objects.create_superuser("admin", "admin@test.local", "secret")
    ct = ContentType.objects.get_for_model(Book)
    ri = ImportDefinition.objects.create(
        name="Sample / books",
        target=ct,
        columns_exclude=_book_columns_exclude_all_but("title", "pages"),
        configuration={"csv": {"delimiter": ";"}},
    )
    client.login(username="admin", password="secret")
    base = "admin:django_importexport_flow_importdefinition"
    title_v = str(Book._meta.get_field("title").verbose_name)
    pages_v = str(Book._meta.get_field("pages").verbose_name)
    paths = effective_import_column_paths(ri)

    url = reverse(f"{base}_download_example_file", args=[ri.pk])
    response = client.post(url, {"example_format": "json"})
    assert response.status_code == 200
    rows = json.loads(response.content.decode("utf-8"))
    assert isinstance(rows, list) and len(rows) == 1
    assert list(rows[0].keys()) == paths
    assert rows[0]["title"] == "" and rows[0]["pages"] == ""

    response = client.post(url, {"example_format": "csv"})
    assert response.status_code == 200
    csv_lines = response.content.decode("utf-8").strip().splitlines()
    assert csv_lines[0].split(";") == paths
    assert csv_lines[1].split(";") == [title_v, pages_v]

    response = client.post(url, {"example_format": "excel"})
    assert response.status_code == 200
    assert "spreadsheet" in response["Content-Type"]
    assert len(response.content) > 32


@pytest.mark.django_db
def test_import_data_admin_form_uses_multipart_enctype(client):
    """File uploads require enctype=multipart (see admin change_form has_file_field)."""
    User = get_user_model()
    User.objects.create_superuser("admin", "admin@test.local", "secret")
    ct = ContentType.objects.get_for_model(Book)
    ri = ImportDefinition.objects.create(
        name="CSV import",
        target=ct,
        columns_exclude=_book_columns_exclude_all_but("title", "pages"),
        configuration={"csv": {"delimiter": ","}},
    )
    client.login(username="admin", password="secret")
    url = reverse(
        "admin:django_importexport_flow_importdefinition_import_tabular_data",
        args=[ri.pk],
    )
    response = client.get(url)
    assert response.status_code == 200
    assert b"multipart/form-data" in response.content


@pytest.mark.django_db
def test_resolve_columns_use_effective_paths_matching_example():
    """Resolved paths equal :func:`effective_import_column_paths` (same order as example file)."""
    ct = ContentType.objects.get_for_model(Book)
    ri = ImportDefinition.objects.create(
        name="Effective cols",
        target=ct,
        columns_exclude=[],
        filter_config={},
    )
    expected = effective_import_column_paths(ri)
    headers = sample_headers_for_import_definition(ri)
    df = pd.DataFrame([{h: "" for h in headers}])
    errs, paths = resolve_import_column_paths(ri, df)
    assert errs == []
    assert paths == expected


@pytest.mark.django_db
def test_resolve_columns_respects_columns_exclude_for_subset():
    """Only title, pages, and price when other paths are excluded."""
    ct = ContentType.objects.get_for_model(Book)
    ri = ImportDefinition.objects.create(
        name="Subset nested",
        target=ct,
        columns_exclude=_book_columns_exclude_all_but("title", "pages", "price"),
        filter_config={},
    )
    headers = sample_headers_for_import_definition(ri)
    df = pd.DataFrame([{h: "" for h in headers}])
    errs, paths = resolve_import_column_paths(ri, df)
    assert errs == []
    assert paths == ["title", "pages", "price"]


@pytest.mark.django_db
def test_exclude_relation_excludes_all_nested_paths():
    """Excluding a FK field name drops the relation column and every ``relation.*`` path."""
    ct = ContentType.objects.get_for_model(Book)
    ri = ImportDefinition.objects.create(
        name="No author relation",
        target=ct,
        columns_exclude=["author"],
        filter_config={},
    )
    paths = effective_import_column_paths(ri)
    assert "author" not in paths
    assert not any(p.startswith("author.") for p in paths)
    assert "title" in paths


@pytest.mark.django_db
def test_exclude_m2m_excludes_all_slot_paths():
    """Excluding an M2M field name drops every ``tags.N.*`` slot column."""
    ct = ContentType.objects.get_for_model(Book)
    ri = ImportDefinition.objects.create(
        name="No tags",
        target=ct,
        columns_exclude=["tags"],
        filter_config={},
    )
    paths = effective_import_column_paths(ri)
    assert "tags" not in paths
    assert not any(p.startswith("tags.") for p in paths)


@pytest.mark.django_db
def test_validate_import_preview_accepts_m2m_header_prefix():
    """M2M slot headers may extend the subfield verbose name (e.g. ``Tag label`` prefix)."""
    ct = ContentType.objects.get_for_model(Book)
    ri = ImportDefinition.objects.create(
        name="M2M headers",
        target=ct,
        columns_exclude=_book_columns_exclude_all_but("title", "tags.0.name", "tags.1.name"),
        filter_config={},
    )
    h0 = resolve_table_column_label(Book, "tags.0.name")
    h1 = resolve_table_column_label(Book, "tags.1.name")
    title_v = str(Book._meta.get_field("title").verbose_name)
    df = pd.DataFrame(
        [
            {
                title_v: "T",
                h0 + " (optional)": "alpha",
                h1: "beta",
            }
        ]
    )
    errs, _warnings, _paths, _dfn = validate_import_preview(df, ri)
    assert errs == []


@pytest.mark.django_db
def test_validate_import_preview_path_headers_strip_label_row():
    """CSV line 1 = paths, line 2 = translations: second row is skipped as data."""
    ct = ContentType.objects.get_for_model(Book)
    ri = ImportDefinition.objects.create(
        name="Two-line header",
        target=ct,
        columns_exclude=_book_columns_exclude_all_but("title", "tags.0.name", "tags.1.name"),
        filter_config={},
    )
    paths = effective_import_column_paths(ri)
    labels = sample_headers_for_import_definition(ri, column_paths=paths)
    df = pd.DataFrame(
        [labels, ["Imported title", "one", "two"]],
        columns=paths,
    )
    errs, _w, _p, df_norm = validate_import_preview(df, ri)
    assert errs == []
    assert df_norm is not None
    assert len(df_norm) == 1
    assert str(df_norm.iloc[0]["title"]).strip() == "Imported title"


@pytest.mark.django_db
def test_create_import_ask_stores_inferred_column_paths():
    User = get_user_model()
    user = User.objects.create_user("u2", "u2@example.com", "x")
    ct = ContentType.objects.get_for_model(Book)
    ri = ImportDefinition.objects.create(
        name="RI2",
        target=ct,
        filter_config={},
        columns_exclude=[],
    )
    from django.core.files.uploadedfile import SimpleUploadedFile

    from django_importexport_flow.utils.import_tabular import create_import_request

    f = SimpleUploadedFile("t.csv", b"Book title,Nb. of pages\nx,1\n", content_type="text/csv")
    ask = create_import_request(
        ri,
        f,
        {},
        user,
        inferred_column_paths=["title", "pages"],
    )
    assert ask.filter_payload[IMPORT_COLUMN_PATHS_KEY] == ["title", "pages"]
