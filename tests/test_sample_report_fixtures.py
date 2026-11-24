"""Sample JSON definitions under tests/sample/importexport_fixtures/."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "sample" / "importexport_fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_sample_report_export_books_fixture():
    data = _load("report_export_books.json")
    assert data["format_version"] == 2
    cols = None
    for o in data["objects"]:
        if (
            o["model"] == "django_importexport_flow.categoryconfig"
            and o["fields"]["category_key"] == "spreadsheet"
        ):
            cols = o["fields"]["columns"]
            break
    assert cols == ["title", "pages", "price", "metadata", "author.name"]


def test_sample_report_export_authors_fixture():
    data = _load("report_export_authors.json")
    assert data["format_version"] == 2
    cols = None
    for o in data["objects"]:
        if (
            o["model"] == "django_importexport_flow.categoryconfig"
            and o["fields"]["category_key"] == "spreadsheet"
        ):
            cols = o["fields"]["columns"]
            break
    assert cols[0] == "name"
    assert cols[1].endswith(".*[title:pages:price]")
    assert "title:pages:price" in cols[1]


@pytest.mark.django_db
def test_sample_fixtures_import_roundtrip():
    """Definition JSON uses natural content-type keys and still deserializes."""
    from django_importexport_flow.models import Definition
    from django_importexport_flow.utils.serialization import import_export_configuration

    for name in ("report_export_books.json", "report_export_authors.json"):
        data = _load(name)
        Definition.objects.filter(name__startswith="Sample fixture —").delete()
        obj = import_export_configuration(data)
        assert obj.name.startswith("Sample fixture —")
        Definition.objects.filter(pk=obj.pk).delete()


@pytest.mark.django_db
def test_generator_preserves_combined_steps(monkeypatch, tmp_path):
    from django_importexport_flow.utils.serialization import import_import_definition
    from tests.sample.boosted_views import load_sample_fixtures
    from tests.sample.importexport_fixtures import build_fixtures

    load_sample_fixtures(replace=False)
    monkeypatch.setattr(build_fixtures, "OUT_DIR", tmp_path)
    build_fixtures.main()

    def generated(name):
        return json.loads((tmp_path / name).read_text(encoding="utf-8"))

    first = import_import_definition(generated("report_import_books_match.json"))
    second = import_import_definition(generated("report_import_books_price.json"))
    combined = import_import_definition(
        generated("report_import_books_combined.json"),
    )
    assert list(combined.steps.values_list("definition_id", flat=True)) == [
        first.pk,
        second.pk,
    ]


@pytest.mark.django_db
def test_generator_rolls_back_cleanup_for_external_references(monkeypatch, tmp_path):
    from django.db.models.deletion import ProtectedError

    from django_importexport_flow.models import Definition, Step
    from tests.sample.boosted_views import load_sample_fixtures
    from tests.sample.importexport_fixtures import build_fixtures

    load_sample_fixtures(replace=False)
    child = Definition.objects.get(
        named_id="sample-fixture-import-books-match-title",
    )
    external = Definition.objects.create(
        direction="import",
        name="External combined import",
        target=child.target,
    )
    Step.objects.create(parent=external, definition=child, position=1)
    monkeypatch.setattr(build_fixtures, "OUT_DIR", tmp_path)

    with pytest.raises(ProtectedError):
        build_fixtures.main()

    assert (
        Step.objects.filter(
            parent__named_id="sample-fixture-import-books-combined",
        ).count()
        == 2
    )
    assert Step.objects.filter(parent=external, definition=child).exists()
