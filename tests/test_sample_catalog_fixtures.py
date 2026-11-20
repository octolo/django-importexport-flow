"""Load the sample catalog and exercise one definition fixture per capability."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import openpyxl
import pytest
from django.core.management import call_command
from django.utils import translation

from django_importexport_flow.engine import ExportPdfEngine, ExportTableEngine
from django_importexport_flow.engine.core.export import (
    attach_export_url_kwargs,
    build_request_with_get,
)
from django_importexport_flow.engine.core.run import create_import_request
from django_importexport_flow.models import ImportRequest
from django_importexport_flow.utils.process import process_export, process_import
from django_importexport_flow.utils.serialization import (
    import_export_configuration,
    import_import_definition,
)
from tests.sample.models import AuthorProfile, Book, FieldShowcase

FIXTURES = Path(__file__).resolve().parent / "sample" / "report_fixtures"
TABULAR = FIXTURES / "tabular"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _catalog() -> None:
    call_command("loaddata", "sample_catalog", verbosity=0)


def _export(name: str):
    return import_export_configuration(_load(name))


def _import(name: str):
    return import_import_definition(_load(name))


def _csv(name: str) -> BytesIO:
    raw = (TABULAR / name).read_bytes()
    buf = BytesIO(raw)
    buf.name = name
    return buf


@pytest.mark.django_db
def test_fixture_books_lists_catalog_rows():
    _catalog()
    definition = _export("report_export_books.json")
    request = build_request_with_get({"min_pages": "0"})
    engine = ExportTableEngine(definition, request=request)
    rows = engine.get_rows()
    assert [row[0] for row in rows] == [
        "The Habit of Excellence",
        "Notes de cours",
        "Orphan",
    ]
    assert rows[0][4] == "Ada Lovelace"
    assert '"lang": "en"' in rows[0][3]


@pytest.mark.django_db
def test_fixture_authors_expand_related_books():
    _catalog()
    engine = ExportTableEngine(_export("report_export_authors.json"))
    assert engine.get_rows()[0][0] == "Ada Lovelace"
    assert "The Habit of Excellence" in engine.get_rows()[0]
    assert engine.get_rows()[1][0] == "Marie Curie"


@pytest.mark.django_db
def test_fixture_filters_keep_one_book():
    _catalog()
    definition = _export("report_export_books_filters.json")
    request = build_request_with_get({"min_pages": "200"})
    attach_export_url_kwargs(request, {"author_id": "1"})
    engine = ExportTableEngine(definition, request=request)
    assert [row[0] for row in engine.get_rows()] == ["The Habit of Excellence"]


@pytest.mark.django_db
def test_fixture_manager_kwargs_keep_long_books():
    _catalog()
    definition = _export("report_export_books_manager.json")
    request = build_request_with_get({"min_price": "0"})
    engine = ExportTableEngine(definition, request=request)
    assert [row[0] for row in engine.get_rows()] == ["The Habit of Excellence"]


@pytest.mark.django_db
def test_fixture_excel_split_by_author():
    _catalog()
    engine = ExportTableEngine(_export("report_export_books_split_by.json"))
    workbook = openpyxl.load_workbook(BytesIO(engine.get_excel()))
    assert "Ada Lovelace" in workbook.sheetnames
    assert "Marie Curie" in workbook.sheetnames


@pytest.mark.django_db
def test_fixture_relations_json_callable_and_m2m():
    _catalog()
    engine = ExportTableEngine(_export("report_export_books_relations.json"))
    row = engine.get_rows()[0]
    assert row[0] == "The Habit of Excellence"
    assert row[1] == "Ada Lovelace"
    assert row[2] == "ADA LOVELACE"
    assert row[3] == "[Ada Lovelace]"
    assert row[4] == "First programmer"
    assert {row[5], row[6]} == {"physics", "novel"}
    assert row[7] == "en"
    assert row[8] == "alpha"


@pytest.mark.django_db
def test_fixture_annotation_orders_by_title_length():
    _catalog()
    engine = ExportTableEngine(_export("report_export_books_annotations.json"))
    titles = [row[0] for row in engine.get_rows()]
    assert titles[0] == "The Habit of Excellence"
    assert engine.get_rows()[0][1] == len("The Habit of Excellence")


@pytest.mark.django_db
def test_fixture_pdf_template_lists_titles():
    _catalog()
    pdf = ExportPdfEngine(_export("report_export_books_pdf.json"))
    html = pdf.render()
    assert "<li>Notes de cours</li>" in html
    assert "<li>Orphan</li>" in html
    assert "<li>The Habit of Excellence</li>" in html


@pytest.mark.django_db
def test_fixture_export_delegate_uses_the_csv_hook():
    definition = _export("report_export_books_delegate.json")
    content, content_type, extension = process_export(
        export_definition=definition,
        export_format="csv",
    )
    assert content_type.startswith("text/csv")
    assert extension == ".csv"
    assert b"Book title" in content


@pytest.mark.django_db
def test_fixture_showcase_and_bookmark_columns():
    _catalog()
    showcase = ExportTableEngine(_export("report_export_showcase.json"))
    row = showcase.get_rows()[0]
    assert row[0] == "hello"
    assert "ada@example.com" in row
    assert "127.0.0.1" in row
    assert "Ada Lovelace" in row
    assert "physics" in row
    bookmark = ExportTableEngine(_export("report_export_bookmarks.json"))
    assert bookmark.get_rows() == [["Loved book", 1, "book"]]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("language", "expected_headers"),
    [
        ("fr", ["Titre", "Pages", "Prix", "Métadonnées"]),
        ("en", ["Title"]),
    ],
)
def test_fixture_export_restores_translated_headers_without_catalog(language, expected_headers):
    definition = _export("report_export_books.json")

    with translation.override(language):
        engine = ExportTableEngine(definition, request=build_request_with_get({"min_pages": "0"}))
        headers = engine.get_headers()

    assert headers[: len(expected_headers)] == expected_headers


@pytest.mark.django_db
def test_fixture_import_accepts_translated_headers_without_catalog():
    definition = _import("report_import_books_match.json")

    with translation.override("en"):
        result = process_import(file=_csv("import_books_labels.csv"), import_definition=definition)

    assert result["success"] is True
    assert Book.objects.get(title="The Habit of Excellence").pages == 322


@pytest.mark.django_db
def test_fixture_column_labels_translate_headers_and_import():
    _catalog()
    with translation.override("fr"):
        books = ExportTableEngine(
            _export("report_export_books.json"),
            request=build_request_with_get({"min_pages": "0"}),
        )
        assert books.get_headers() == ["Titre", "Pages", "Prix", "Métadonnées", "Nom"]
        relations = ExportTableEngine(_export("report_export_books_relations.json"))
        headers = relations.get_headers()
        assert headers[4] == "Biographie"
        assert headers[5:7] == ["Étiquette 1", "Étiquette 2"]
        assert headers[7] == "Langue"
        annotated = ExportTableEngine(_export("report_export_books_annotations.json"))
        assert annotated.get_headers() == ["Titre", "Title length"]
    definition = _import("report_import_books_match.json")
    result = process_import(file=_csv("import_books_labels.csv"), import_definition=definition)
    assert result["success"] is True
    assert Book.objects.get(title="The Habit of Excellence").pages == 322


@pytest.mark.django_db
def test_fixture_import_match_updates_pages():
    _catalog()
    definition = _import("report_import_books_match.json")
    result = process_import(file=_csv("import_books_match.csv"), import_definition=definition)
    assert result["success"] is True
    assert Book.objects.filter(title="The Habit of Excellence").count() == 1
    assert Book.objects.get(title="The Habit of Excellence").pages == 321


@pytest.mark.django_db
def test_fixture_import_m2m_slots():
    _catalog()
    definition = _import("report_import_books_m2m.json")
    result = process_import(file=_csv("import_books_m2m.csv"), import_definition=definition)
    assert result["success"] is True
    book = Book.objects.get(title="New Tagged Book")
    assert set(book.tags.values_list("name", flat=True)) == {"physics", "essay"}
    assert book.tags.get(name="physics").category.name == "Science"


@pytest.mark.django_db
def test_fixture_import_author_profile_one_to_one():
    _catalog()
    definition = _import("report_import_author_profiles.json")
    result = process_import(file=_csv("import_author_profiles.csv"), import_definition=definition)
    assert result["success"] is True
    profile = AuthorProfile.objects.get(bio="Lab notes")
    assert profile.author.name == "Marie Curie"


@pytest.mark.django_db
def test_fixture_import_showcase_scalars():
    _catalog()
    definition = _import("report_import_showcase.json")
    result = process_import(file=_csv("import_showcase.csv"), import_definition=definition)
    assert result["success"] is True
    row = FieldShowcase.objects.get(char_f="showcase")
    assert row.email_f == "ada2@example.com"
    assert row.int_f == 7
    assert row.bool_f is True
    assert str(row.date_f) == "2024-05-01"
    assert str(row.uuid_f) == "12345678-1234-5678-1234-567812345679"
    payload = row.json_f
    if isinstance(payload, str):
        payload = json.loads(payload)
    assert payload == {"k": 1}
    assert row.ip_f == "10.0.0.1"


@pytest.mark.django_db
def test_fixture_import_request_runs_the_native_hook(auditor_user):
    definition = _import("report_import_books_backend.json")
    ask = create_import_request(
        definition,
        _csv("import_books_match.csv"),
        {},
        auditor_user,
    )
    ask.save(trigger_processing=True)
    ask.refresh_from_db()
    assert ask.status == ImportRequest.Status.SUCCESS
    assert ask.imported_row_count >= 1


@pytest.mark.django_db
def test_fixture_import_delegate_uses_the_native_hook():
    definition = _import("report_import_books_delegate.json")
    upload = BytesIO(b"title\nDelegated row\n")
    upload.name = "title.csv"
    result = process_import(file=upload, import_definition=definition)
    assert result["success"] is True
    assert result["queued"] is False
    assert Book.objects.filter(title="Delegated row").exists()
