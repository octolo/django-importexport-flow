"""Integration tests for management commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from django_importexport_flow.models import ExportConfigTable, ExportDefinition, ImportDefinition
from tests.sample.models import Book


@pytest.mark.django_db
def test_process_export_json_writes_file(tmp_path):
    from django.contrib.contenttypes.models import ContentType

    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition.objects.create(
        name="Mgmt export",
        target=ct,
        manager="objects",
        filter_config={},
    )
    ExportConfigTable.objects.create(
        export=definition,
        columns=["title"],
        configuration={},
    )
    Book.objects.create(title="CLI Book", pages=1)
    out = tmp_path / "out.json"
    call_command(
        "process_export",
        str(definition.uuid),
        format="json",
        output=str(out),
    )
    assert out.exists()
    data = json.loads(out.read_text())
    assert len(data) == 1
    assert "CLI Book" in json.dumps(data)


@pytest.mark.django_db
def test_process_export_requires_format_or_json(tmp_path):
    from django.contrib.contenttypes.models import ContentType

    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition.objects.create(
        name="No fmt",
        target=ct,
        manager="objects",
        filter_config={},
    )
    ExportConfigTable.objects.create(
        export=definition,
        columns=["title"],
        configuration={},
    )
    with pytest.raises(CommandError, match="export_format"):
        call_command(
            "process_export",
            str(definition.uuid),
            output=str(tmp_path / "unused.json"),
        )


@pytest.mark.django_db
def test_process_export_unknown_definition(tmp_path):
    with pytest.raises(CommandError):
        call_command(
            "process_export",
            "00000000-0000-0000-0000-000000000099",
            format="json",
            output=str(tmp_path / "out.json"),
        )


@pytest.mark.django_db
def test_process_import_preview_no_db_write(tmp_path):
    from django.contrib.contenttypes.models import ContentType

    from django_importexport_flow.models import ImportRequest

    ct = ContentType.objects.get_for_model(Book)
    definition = ImportDefinition.objects.create(
        name="Mgmt import",
        target=ct,
        filter_config={},
    )
    fixture = Path(__file__).resolve().parent / "fixtures" / "import_book.csv"
    assert fixture.exists()
    dest = tmp_path / "b.csv"
    dest.write_bytes(fixture.read_bytes())
    before = ImportRequest.objects.count()
    call_command(
        "process_import",
        str(definition.uuid),
        str(dest),
        preview=True,
    )
    assert ImportRequest.objects.count() == before


@pytest.mark.django_db
def test_generate_example_file_csv(tmp_path):
    from django.contrib.contenttypes.models import ContentType

    ct = ContentType.objects.get_for_model(Book)
    definition = ImportDefinition.objects.create(
        name="Example def",
        target=ct,
        filter_config={},
    )
    out = tmp_path / "ex.csv"
    call_command(
        "generate_example_file",
        str(definition.uuid),
        format="csv",
        output=str(out),
    )
    text = out.read_text(encoding="utf-8")
    assert "title" in text or "Book" in text


@pytest.mark.django_db
def test_generate_example_file_unknown_definition():
    with pytest.raises(CommandError):
        call_command(
            "generate_example_file",
            "00000000-0000-0000-0000-000000000099",
            format="csv",
        )
