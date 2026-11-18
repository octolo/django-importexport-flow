"""Regression tests for formula escaping, bounded reads, archives, hooks, and paths."""

from __future__ import annotations

import zipfile
from io import BytesIO

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from openpyxl import load_workbook

from django_importexport_flow.engine.core.hooks import assert_custom_hook_allowed
from django_importexport_flow.engine.core.table import _escape_spreadsheet_formula
from django_importexport_flow.engine.hooks import _read_limited
from django_importexport_flow.forms import make_export_form_class
from django_importexport_flow.models import Definition
from django_importexport_flow.models.request import import_file_upload_to
from django_importexport_flow.utils.upload_validation import validate_tabular_upload_bytes
from tests.sample.models import Book
from tests.support import attach_pdf_export, attach_tabular_export


def test_formula_prefixes_cover_text_and_leave_safe_values():
    assert _escape_spreadsheet_formula("=1+1") == "'=1+1"
    assert _escape_spreadsheet_formula("+1") == "'+1"
    assert _escape_spreadsheet_formula("-1") == "'-1"
    assert _escape_spreadsheet_formula("@cmd") == "'@cmd"
    assert _escape_spreadsheet_formula("  =1") == "'  =1"
    assert _escape_spreadsheet_formula("'=1") == "'=1"
    assert _escape_spreadsheet_formula("plain") == "plain"
    assert _escape_spreadsheet_formula("") == ""
    assert _escape_spreadsheet_formula(12) == 12
    assert _escape_spreadsheet_formula(None) is None
    assert _escape_spreadsheet_formula(True) is True


@pytest.mark.django_db
def test_csv_and_excel_escape_formulas_and_json_does_not(settings):
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export", name="Formula books", target=ct, manager="objects"
    )
    attach_tabular_export(export=definition, columns=["title", "pages"], configuration={})
    Book.objects.create(title="=cmd|calc", pages=3)
    from django_importexport_flow.engine.core.table import TableEngine

    engine = TableEngine(definition)
    csv_text = engine.get_csv().decode("utf-8")
    assert "'=cmd|calc" in csv_text
    workbook = load_workbook(BytesIO(engine.get_excel()))
    cell = workbook.active["A2"]
    assert cell.data_type != "f"
    assert str(cell.value).startswith("'")
    assert "=cmd|calc" in engine.get_json()

    settings.DJANGO_IMPORTEXPORT_FLOW = {"ESCAPE_SPREADSHEET_FORMULAS": False}
    raw = engine.get_csv().decode("utf-8")
    assert "'=cmd|calc" not in raw
    assert "=cmd|calc" in raw


@pytest.mark.django_db
def test_template_override_requires_an_explicit_permission():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export", name="Template gate", target=ct, manager="objects"
    )
    attach_tabular_export(export=definition, columns=["title"], configuration={})
    attach_pdf_export(export=definition, template="<p>stored</p>")
    definition = Definition.objects.get(pk=definition.pk)
    hidden = make_export_form_class(definition)(
        {"export_format": "pdf", "template_override": "<p>forged</p>"}
    )
    assert "template_override" not in hidden.fields
    assert not hidden.is_valid()
    assert "export_format" in hidden.errors

    allowed = make_export_form_class(definition, allow_template_override=True)(
        {"export_format": "pdf", "template_override": "<p>company</p>"}
    )
    assert allowed.is_valid(), allowed.errors
    assert allowed.cleaned_data["template_override"] == "<p>company</p>"


def test_read_limited_stops_before_buffering_the_whole_file():
    class Limited:
        def read(self, size=-1):
            if size < 0:
                raise AssertionError("unlimited read")
            return b"x" * size

    with pytest.raises(ValueError, match="too large"):
        _read_limited(Limited(), 4)

    class Exact:
        def read(self, size=-1):
            return b"abcd"[:size]

    assert _read_limited(Exact(), 4) == b"abcd"

    class Chunked:
        def chunks(self):
            yield b"ab"
            yield b"cd"

    assert _read_limited(Chunked(), 4) == b"abcd"
    with pytest.raises(ValueError, match="too large"):
        _read_limited(Chunked(), 3)


def test_read_limited_restores_a_seekable_stream_and_leaves_it_open():
    stream = BytesIO(b"abcdef")
    stream.seek(2)
    assert _read_limited(stream, 6) == b"abcdef"
    assert stream.tell() == 2
    assert not stream.closed
    with pytest.raises(ValueError, match="File is too large."):
        _read_limited(BytesIO(b"abcdefg"), 6)


def test_read_limited_uses_uploaded_file_chunks():
    from django.core.files.uploadedfile import SimpleUploadedFile

    exact = SimpleUploadedFile("books.csv", b"abcd")
    assert _read_limited(exact, 4) == b"abcd"
    larger = SimpleUploadedFile("books.csv", b"abcde")
    with pytest.raises(ValueError, match="File is too large."):
        _read_limited(larger, 4)


class _StoredFile:
    def __init__(self, payload: bytes, *, closed: bool):
        self._raw = BytesIO(payload)
        self.closed = closed
        self.opened = 0
        self.closes = 0

    def open(self, mode="rb"):
        self.opened += 1
        self.closed = False
        self._raw.seek(0)

    def close(self):
        self.closes += 1
        self.closed = True

    def read(self, size=-1):
        return self._raw.read(size)

    def tell(self):
        return self._raw.tell()

    def seek(self, position):
        return self._raw.seek(position)


def test_read_limited_opens_only_a_closed_django_file():
    closed = _StoredFile(b"hello", closed=True)
    assert _read_limited(closed, 5) == b"hello"
    assert closed.opened == 1
    assert closed.closes == 1
    assert closed.closed is True

    owned = _StoredFile(b"hello", closed=False)
    owned.seek(1)
    assert _read_limited(owned, 5) == b"hello"
    assert owned.opened == 0
    assert owned.closes == 0
    assert owned.tell() == 1
    assert owned.closed is False


def _zip(members: list[tuple[str, bytes]]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members:
            archive.writestr(name, payload)
    return buffer.getvalue()


def test_xlsx_archive_guards(settings):
    settings.DJANGO_IMPORTEXPORT_FLOW = {
        "MAX_XLSX_ARCHIVE_MEMBERS": 2,
        "MAX_XLSX_UNCOMPRESSED_BYTES": 20,
        "MAX_XLSX_COMPRESSION_RATIO": 100,
    }
    validate_tabular_upload_bytes(_zip([("xl/workbook.xml", b"<ok/>")]), "book.xlsx")
    with pytest.raises(ValueError, match="not a valid Excel"):
        validate_tabular_upload_bytes(b"PK\x03\x04not-a-zip", "book.xlsx")
    with pytest.raises(ValueError, match="too many"):
        validate_tabular_upload_bytes(
            _zip([("a.xml", b"a"), ("b.xml", b"b"), ("c.xml", b"c")]),
            "book.xlsx",
        )
    with pytest.raises(ValueError, match="expands beyond"):
        validate_tabular_upload_bytes(_zip([("a.xml", b"x" * 30)]), "book.xlsx")
    with pytest.raises(ValueError, match="unsafe archive path"):
        validate_tabular_upload_bytes(_zip([("../evil.xml", b"x")]), "book.xlsx")
    settings.DJANGO_IMPORTEXPORT_FLOW = {
        "MAX_XLSX_ARCHIVE_MEMBERS": 5,
        "MAX_XLSX_UNCOMPRESSED_BYTES": 10_000,
        "MAX_XLSX_COMPRESSION_RATIO": 2,
    }
    with pytest.raises(ValueError, match="compression ratio"):
        validate_tabular_upload_bytes(_zip([("zeros.xml", b"\0" * 400)]), "book.xlsx")
    validate_tabular_upload_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 8, "legacy.xls")


def test_hook_prefixes_allow_natives_and_can_block_custom_modules(settings):
    native = "django_importexport_flow.engine.hooks.native_csv_export"
    custom = "tests.test_export_hooks.replace_export"
    assert_custom_hook_allowed(custom)
    settings.DJANGO_IMPORTEXPORT_FLOW = {
        "ALLOWED_HOOK_MODULE_PREFIXES": ["tests.test_export_hooks"]
    }
    assert_custom_hook_allowed(custom)
    assert_custom_hook_allowed(native)
    with pytest.raises(ValidationError):
        assert_custom_hook_allowed("tests.test_export_hooksstolen.escape")
    settings.DJANGO_IMPORTEXPORT_FLOW = {"ALLOWED_HOOK_MODULE_PREFIXES": []}
    with pytest.raises(ValidationError):
        assert_custom_hook_allowed(custom)
    assert_custom_hook_allowed(native)


def test_real_xlsx_workbook_passes_the_archive_guard():
    import pandas as pd

    buffer = BytesIO()
    pd.DataFrame({"title": ["Shelf"], "pages": [4]}).to_excel(
        buffer, index=False, engine="openpyxl"
    )
    raw = buffer.getvalue()
    validate_tabular_upload_bytes(raw, "books.xlsx")
    workbook = load_workbook(BytesIO(raw))
    assert workbook.active["A2"].value == "Shelf"


@pytest.mark.django_db
def test_read_limited_reopens_a_stored_file_without_closing_an_open_one():
    from django.contrib.contenttypes.models import ContentType

    from django_importexport_flow.models import Definition, ImportRequest
    from django_importexport_flow.models.request import attach_import_file
    from tests.sample.models import Book

    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(direction="import", name="Stored read", target=ct)
    ask = ImportRequest.objects.create(import_definition=definition)
    attach_import_file(ask, "books.csv", b"title\nA\n", keep_for_later=False)
    stored = ask.data_file
    stored.close()
    assert stored.closed
    assert _read_limited(stored, 64) == b"title\nA\n"
    assert stored.closed

    stored.open("rb")
    stored.seek(2)
    assert _read_limited(stored, 64) == b"title\nA\n"
    assert not stored.closed
    assert stored.tell() == 2
    stored.close()


def test_plain_directory_upload_to_is_not_imported(settings):
    settings.DJANGO_IMPORTEXPORT_FLOW = {"IMPORT_FILE_UPLOAD_TO": "uploads"}
    assert import_file_upload_to(object(), "books.csv") == "uploads/books.csv"
    settings.DJANGO_IMPORTEXPORT_FLOW = {"IMPORT_FILE_UPLOAD_TO": "missing.module.callback"}
    with pytest.raises(TypeError, match="not an importable callable"):
        import_file_upload_to(object(), "books.csv")
