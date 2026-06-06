"""Tests for processing_backend resolution on import/export requests."""

from __future__ import annotations

from io import BytesIO

import pytest
from django.contrib.contenttypes.models import ContentType

from django_importexport_flow.engine.core.processing import process_import_request
from django_importexport_flow.engine.core.run import create_import_request, run_import_request
from django_importexport_flow.models import (
    ExportConfigTable,
    ExportDefinition,
    ExportRequest,
    ImportDefinition,
    ImportRequest,
)
from django_importexport_flow.utils.process import run_export_with_audit
from tests.sample.models import Book


def _book_columns_exclude_all_but(*keep: str) -> list[str]:
    from django_importexport_flow.engine.core.import_ import default_importable_column_paths

    full = default_importable_column_paths(Book)
    return [p for p in full if p not in keep]


@pytest.mark.django_db
def test_import_processing_backend_import_path(auditor_user):
    ct = ContentType.objects.get_for_model(Book)
    definition = ImportDefinition.objects.create(
        name="Custom import path",
        target=ct,
        filter_config={},
        columns_exclude=_book_columns_exclude_all_but("title", "pages"),
        processing_backend="tests.sample.processing_backends.mark_import_success",
        processing_backend_kwargs={"rows": 3},
    )
    raw = b"title,pages\nX,1\n"
    ask = create_import_request(definition, BytesIO(raw), {}, auditor_user)
    ask.save(trigger_processing=True)
    ask.refresh_from_db()
    assert ask.status == ImportRequest.Status.SUCCESS
    assert ask.imported_row_count == 3


@pytest.mark.django_db
def test_import_processing_backend_model_method(auditor_user):
    ct = ContentType.objects.get_for_model(Book)
    definition = ImportDefinition.objects.create(
        name="Custom import model method",
        target=ct,
        filter_config={},
        columns_exclude=_book_columns_exclude_all_but("title", "pages"),
        processing_backend="mark_import_success",
        processing_backend_kwargs={"rows": 5},
    )
    raw = b"title,pages\nY,2\n"
    ask = create_import_request(definition, BytesIO(raw), {}, auditor_user)
    ask.save(trigger_processing=True)
    ask.refresh_from_db()
    assert ask.status == ImportRequest.Status.SUCCESS
    assert ask.imported_row_count == 5


@pytest.mark.django_db
def test_import_processing_backend_failure_when_unresolvable(auditor_user):
    ct = ContentType.objects.get_for_model(Book)
    definition = ImportDefinition.objects.create(
        name="Broken backend",
        target=ct,
        filter_config={},
        columns_exclude=_book_columns_exclude_all_but("title", "pages"),
        processing_backend="does.not.exist.anywhere",
    )
    raw = b"title,pages\nZ,3\n"
    ask = create_import_request(definition, BytesIO(raw), {}, auditor_user)
    ask.save(trigger_processing=True)
    ask.refresh_from_db()
    assert ask.status == ImportRequest.Status.FAILURE
    assert "import path" in ask.error_trace
    assert "model method" in ask.error_trace


@pytest.mark.django_db
def test_import_without_processing_backend_uses_native(auditor_user):
    ct = ContentType.objects.get_for_model(Book)
    definition = ImportDefinition.objects.create(
        name="Native import",
        target=ct,
        filter_config={},
        columns_exclude=_book_columns_exclude_all_but("title", "pages"),
    )
    t_v = str(Book._meta.get_field("title").verbose_name)
    p_v = str(Book._meta.get_field("pages").verbose_name)
    raw = f"{t_v},{p_v}\nNative,7\n".encode()
    ask = create_import_request(definition, BytesIO(raw), {}, auditor_user)
    ask.save(trigger_processing=True)
    ask.refresh_from_db()
    assert ask.status == ImportRequest.Status.SUCCESS
    assert Book.objects.filter(title="Native", pages=7).exists()


@pytest.mark.django_db
def test_run_import_request_idempotent_still_native(auditor_user):
    ct = ContentType.objects.get_for_model(Book)
    definition = ImportDefinition.objects.create(
        name="Idempotent native",
        target=ct,
        filter_config={},
        columns_exclude=_book_columns_exclude_all_but("title", "pages"),
    )
    t_v = str(Book._meta.get_field("title").verbose_name)
    p_v = str(Book._meta.get_field("pages").verbose_name)
    raw = f"{t_v},{p_v}\nB2,2\n".encode()
    ask = create_import_request(definition, BytesIO(raw), {}, auditor_user)
    process_import_request(ask)
    ask.refresh_from_db()
    assert ask.status == ImportRequest.Status.SUCCESS
    n_before = Book.objects.filter(title="B2").count()
    run_import_request(ask)
    assert Book.objects.filter(title="B2").count() == n_before


@pytest.mark.django_db
def test_export_processing_backend_import_path(auditor_user):
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition.objects.create(
        name="Custom export path",
        target=ct,
        manager="objects",
        filter_config={},
    )
    ExportConfigTable.objects.create(
        export=definition,
        columns=["title"],
        configuration={},
        processing_backend="tests.sample.processing_backends.mark_export_success",
        processing_backend_kwargs={"byte_size": 42},
    )
    content, _ct, _ext = run_export_with_audit(
        export_definition=definition,
        filter_payload={"export_format": "json"},
        user=auditor_user,
    )
    assert content == b"x" * 42
    er = ExportRequest.objects.get(export_definition=definition)
    assert er.status == ExportRequest.Status.SUCCESS
    assert er.output_bytes == 42


@pytest.mark.django_db
def test_export_processing_backend_model_method(auditor_user):
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition.objects.create(
        name="Custom export model method",
        target=ct,
        manager="objects",
        filter_config={},
    )
    ExportConfigTable.objects.create(
        export=definition,
        columns=["title"],
        configuration={},
        processing_backend="mark_export_success",
        processing_backend_kwargs={"byte_size": 7},
    )
    content, _ct, _ext = run_export_with_audit(
        export_definition=definition,
        filter_payload={"export_format": "json"},
        user=auditor_user,
    )
    assert content == b"x" * 7
    er = ExportRequest.objects.get(export_definition=definition)
    assert er.status == ExportRequest.Status.SUCCESS
    assert er.output_bytes == 7


@pytest.mark.django_db
def test_export_without_processing_backend_uses_native(auditor_user):
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition.objects.create(
        name="Native export",
        target=ct,
        manager="objects",
        filter_config={},
    )
    ExportConfigTable.objects.create(
        export=definition,
        columns=["title"],
        configuration={},
    )
    Book.objects.create(title="NativeExport", pages=0)
    content, _ct, _ext = run_export_with_audit(
        export_definition=definition,
        filter_payload={"export_format": "json"},
        user=auditor_user,
    )
    assert b"NativeExport" in content
    er = ExportRequest.objects.get(export_definition=definition)
    assert er.status == ExportRequest.Status.SUCCESS
    # Native path now also persists output_file.
    assert er.output_file


@pytest.mark.django_db
def test_export_processing_backend_failure_when_unresolvable(auditor_user):
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition.objects.create(
        name="Broken export backend",
        target=ct,
        manager="objects",
        filter_config={},
    )
    ExportConfigTable.objects.create(
        export=definition,
        columns=["title"],
        configuration={},
        processing_backend="missing.backend.callable",
    )
    with pytest.raises(RuntimeError):
        run_export_with_audit(
            export_definition=definition,
            filter_payload={"export_format": "json"},
            user=auditor_user,
        )
    er = ExportRequest.objects.get(export_definition=definition)
    assert er.status == ExportRequest.Status.FAILURE
    assert er.error_trace
