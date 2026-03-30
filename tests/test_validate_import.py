"""Tests for :func:`django_importexport_flow.utils.process.validate_import` and helpers."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from django.contrib.contenttypes.models import ContentType

from django_importexport_flow.models import ImportDefinition
from django_importexport_flow.utils.process import (
    generate_example_file,
    process_import,
    validate_import,
)
from tests.sample.models import Book

FIXTURES = Path(__file__).resolve().parent / "fixtures"
IMPORT_BOOK_CSV = FIXTURES / "import_book.csv"


@pytest.mark.django_db
def test_validate_import_builds_validation_dataset():
    ct = ContentType.objects.get_for_model(Book)
    definition = ImportDefinition.objects.create(
        name="Books import",
        target=ct,
        filter_config={},
    )
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
    definition = ImportDefinition.objects.create(
        name="Books import",
        target=ct,
        filter_config={},
    )
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
    definition = ImportDefinition.objects.create(
        name="Books import",
        target=ct,
        filter_config={},
    )
    df = pd.read_csv(IMPORT_BOOK_CSV)
    out = validate_import(dataframe=df, import_definition=definition, row_limit=5)
    assert out["errors"] == []
    assert out["validation_dataset"]["preview_row_count"] >= 1


@pytest.mark.django_db
def test_generate_example_file_csv_json_excel():
    ct = ContentType.objects.get_for_model(Book)
    definition = ImportDefinition.objects.create(
        name="Ex",
        target=ct,
        filter_config={},
    )
    for fmt in ("csv", "json", "excel"):
        body, ct_hdr, ext = generate_example_file(definition, example_format=fmt)
        assert body
        assert ext in (".csv", ".json", ".xlsx")
        assert ct_hdr


@pytest.mark.django_db
def test_validate_import_empty_rows_when_errors():
    ct = ContentType.objects.get_for_model(Book)
    definition = ImportDefinition.objects.create(
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
    with IMPORT_BOOK_CSV.open("rb") as f:
        out = validate_import(file=f, import_definition=definition)

    assert out["errors"]
    assert out["validation_dataset"]["rows"] == []
    assert out["dataframe"] is None
