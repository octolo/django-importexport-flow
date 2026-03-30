"""Multi-row import behaviour: partial success and error aggregation."""

from __future__ import annotations

from io import BytesIO

import pytest
from django.contrib.contenttypes.models import ContentType

from django_importexport_flow.engine.core.import_ import default_importable_column_paths
from django_importexport_flow.models import ImportDefinition, ImportRequest
from django_importexport_flow.utils.process import process_import, validate_import
from tests.sample.models import Book


def _book_columns_exclude_all_but(*keep: str) -> list[str]:
    full = default_importable_column_paths(Book)
    return [p for p in full if p not in keep]


@pytest.mark.django_db
def test_import_partial_failure_keeps_earlier_rows_and_multiline_trace(auditor_user):
    """Row 3 has an invalid date; rows 1–2 remain committed."""
    ct = ContentType.objects.get_for_model(Book)
    definition = ImportDefinition.objects.create(
        name="Mass err",
        target=ct,
        filter_config={},
        columns_exclude=_book_columns_exclude_all_but("title", "pages", "publication_date"),
    )
    t_v = str(Book._meta.get_field("title").verbose_name)
    p_v = str(Book._meta.get_field("pages").verbose_name)
    d_v = str(Book._meta.get_field("publication_date").verbose_name)
    csv_lines = [
        "title,pages,publication_date",
        f"{t_v},{p_v},{d_v}",
        "First,10,2020-01-01",
        "Second,20,2020-01-02",
        "Third,30,not-a-valid-date",
    ]
    raw = "\n".join(csv_lines).encode("utf-8")
    buf = BytesIO(raw)
    buf.name = "three.csv"

    result = process_import(
        file=buf,
        import_definition=definition,
        user=auditor_user,
        filter_payload={},
        preview_only=False,
    )
    assert result["success"] is False
    ask: ImportRequest = result["import_request"]
    ask.refresh_from_db()
    assert ask.status == ImportRequest.Status.FAILURE
    assert ask.imported_row_count == 2
    assert "Row" in (ask.error_trace or "")
    assert Book.objects.filter(title="First").exists()
    assert Book.objects.filter(title="Second").exists()
    assert not Book.objects.filter(title="Third").exists()


@pytest.mark.django_db
def test_import_many_rows_with_tabular_batch_size(settings, auditor_user):
    """TABULAR_IMPORT_BATCH_SIZE triggers batched bulk_create when no M2M slots."""
    settings.DJANGO_IMPORTEXPORT_FLOW = {"TABULAR_IMPORT_BATCH_SIZE": 8}
    ct = ContentType.objects.get_for_model(Book)
    definition = ImportDefinition.objects.create(
        name="Batch bulk",
        target=ct,
        filter_config={},
        columns_exclude=_book_columns_exclude_all_but("title", "pages"),
    )
    t_v = str(Book._meta.get_field("title").verbose_name)
    p_v = str(Book._meta.get_field("pages").verbose_name)
    lines = [f"{t_v},{p_v}"] + [f"Batch{i:02d},{i}" for i in range(20)]
    raw = "\n".join(lines).encode("utf-8")
    buf = BytesIO(raw)
    buf.name = "batch.csv"
    result = process_import(
        file=buf,
        import_definition=definition,
        user=auditor_user,
        filter_payload={},
        preview_only=False,
    )
    assert result["success"] is True
    ask: ImportRequest = result["import_request"]
    ask.refresh_from_db()
    assert ask.status == ImportRequest.Status.SUCCESS
    assert ask.imported_row_count == 20
    assert Book.objects.filter(title__startswith="Batch").count() == 20


@pytest.mark.django_db
def test_import_preview_reports_many_rows_without_db_writes():
    ct = ContentType.objects.get_for_model(Book)
    definition = ImportDefinition.objects.create(
        name="Preview many",
        target=ct,
        filter_config={},
        columns_exclude=_book_columns_exclude_all_but("title", "pages"),
    )
    lines = ["title,pages"] + [f"R{i},{i}" for i in range(50)]
    raw = "\n".join(lines).encode("utf-8")
    buf = BytesIO(raw)
    buf.name = "many.csv"
    out = validate_import(file=buf, import_definition=definition, row_limit=5)
    assert not out["errors"]
    ds = out["validation_dataset"]
    assert ds["row_count"] == 50
    assert ds["preview_row_count"] <= 5
