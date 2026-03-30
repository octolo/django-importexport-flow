"""Sample JSON report fixtures under tests/sample/report_fixtures/."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "sample" / "report_fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_sample_report_export_books_fixture():
    data = _load("report_export_books.json")
    assert data["format_version"] == 1
    cols = None
    for o in data["objects"]:
        if o["model"] == "django_importexport_flow.exportconfigtable":
            cols = o["fields"]["columns"]
            break
    assert cols == ["title", "pages", "price", "metadata", "author.name"]


def test_sample_report_export_authors_fixture():
    data = _load("report_export_authors.json")
    assert data["format_version"] == 1
    cols = None
    for o in data["objects"]:
        if o["model"] == "django_importexport_flow.exportconfigtable":
            cols = o["fields"]["columns"]
            break
    assert cols[0] == "name"
    assert cols[1].endswith(".*[title:pages:price]")
    assert "title:pages:price" in cols[1]


@pytest.mark.django_db
def test_sample_fixtures_import_roundtrip():
    """Hand-maintained fixtures use target=null; import still deserializes."""
    from django_importexport_flow.models import ExportDefinition
    from django_importexport_flow.utils.serialization import import_export_configuration

    for name in ("report_export_books.json", "report_export_authors.json"):
        data = _load(name)
        ExportDefinition.objects.filter(name__startswith="Sample fixture —").delete()
        obj = import_export_configuration(data)
        assert obj.name.startswith("Sample fixture —")
        ExportDefinition.objects.filter(pk=obj.pk).delete()
