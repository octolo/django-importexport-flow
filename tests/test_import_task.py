"""IMPORT_TASK_BACKEND and dispatch_import_request behaviour."""

from __future__ import annotations

import time
from io import BytesIO

import pytest
from django.contrib.contenttypes.models import ContentType

from django_importexport_flow.engine.core.import_ import default_importable_column_paths
from django_importexport_flow.models import ImportDefinition, ImportRequest
from django_importexport_flow.utils.process import process_import
from tests.sample.models import Book


def _book_columns_exclude_all_but(*keep: str) -> list[str]:
    full = default_importable_column_paths(Book)
    return [p for p in full if p not in keep]


@pytest.mark.django_db(transaction=True)
def test_dispatch_thread_backend_sets_processing_then_success(settings, auditor_user):
    settings.DJANGO_IMPORTEXPORT_FLOW = {"IMPORT_TASK_BACKEND": "thread"}
    ct = ContentType.objects.get_for_model(Book)
    definition = ImportDefinition.objects.create(
        name="Async thread import",
        target=ct,
        filter_config={},
        columns_exclude=_book_columns_exclude_all_but("title", "pages"),
    )
    t_v = str(Book._meta.get_field("title").verbose_name)
    p_v = str(Book._meta.get_field("pages").verbose_name)
    raw = f"{t_v},{p_v}\nB1,1\n".encode("utf-8")
    buf = BytesIO(raw)
    buf.name = "one.csv"
    out = process_import(
        file=buf,
        import_definition=definition,
        user=auditor_user,
        filter_payload={},
        preview_only=False,
        run_async=True,
    )
    ask: ImportRequest = out["import_request"]
    assert out["queued"] is True
    assert ask.status == ImportRequest.Status.PROCESSING
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        ask.refresh_from_db()
        if ask.status != ImportRequest.Status.PROCESSING:
            break
        time.sleep(0.05)
    assert ask.status == ImportRequest.Status.SUCCESS
    assert ask.imported_row_count == 1
    assert Book.objects.filter(title="B1").exists()


@pytest.mark.django_db
def test_match_fields_updates_existing_row(settings, auditor_user):
    """Rows keyed by match_fields use update_or_create instead of always inserting."""
    settings.DJANGO_IMPORTEXPORT_FLOW = {"IMPORT_TASK_BACKEND": "sync"}
    ct = ContentType.objects.get_for_model(Book)
    Book.objects.create(title="MatchKey", pages=1)
    definition = ImportDefinition.objects.create(
        name="Upsert by title",
        target=ct,
        filter_config={},
        match_fields=["title"],
        columns_exclude=_book_columns_exclude_all_but("title", "pages"),
    )
    t_v = str(Book._meta.get_field("title").verbose_name)
    p_v = str(Book._meta.get_field("pages").verbose_name)
    raw = f"{t_v},{p_v}\nMatchKey,99\n".encode("utf-8")
    buf = BytesIO(raw)
    buf.name = "upsert.csv"
    out = process_import(
        file=buf,
        import_definition=definition,
        user=auditor_user,
        filter_payload={},
        preview_only=False,
        run_async=False,
    )
    ask = out["import_request"]
    assert ask.status == ImportRequest.Status.SUCCESS
    assert Book.objects.filter(title="MatchKey").count() == 1
    assert Book.objects.get(title="MatchKey").pages == 99


@pytest.mark.django_db
def test_run_import_request_idempotent_after_success(settings, auditor_user):
    settings.DJANGO_IMPORTEXPORT_FLOW = {"IMPORT_TASK_BACKEND": "sync"}
    ct = ContentType.objects.get_for_model(Book)
    definition = ImportDefinition.objects.create(
        name="Idempotent",
        target=ct,
        filter_config={},
        columns_exclude=_book_columns_exclude_all_but("title", "pages"),
    )
    t_v = str(Book._meta.get_field("title").verbose_name)
    p_v = str(Book._meta.get_field("pages").verbose_name)
    raw = f"{t_v},{p_v}\nB2,2\n".encode("utf-8")
    buf = BytesIO(raw)
    buf.name = "t.csv"
    out = process_import(
        file=buf,
        import_definition=definition,
        user=auditor_user,
        filter_payload={},
        preview_only=False,
        run_async=False,
    )
    ask = out["import_request"]
    assert ask.status == ImportRequest.Status.SUCCESS
    from django_importexport_flow.engine.core.run import run_import_request

    n_before = Book.objects.filter(title="B2").count()
    run_import_request(ask)
    ask.refresh_from_db()
    assert ask.status == ImportRequest.Status.SUCCESS
    assert Book.objects.filter(title="B2").count() == n_before


@pytest.mark.django_db
def test_dispatch_inline_when_run_async_but_sync_backend(settings, auditor_user):
    settings.DJANGO_IMPORTEXPORT_FLOW = {"IMPORT_TASK_BACKEND": "sync"}
    ct = ContentType.objects.get_for_model(Book)
    definition = ImportDefinition.objects.create(
        name="Sync only",
        target=ct,
        filter_config={},
        columns_exclude=_book_columns_exclude_all_but("title", "pages"),
    )
    t_v = str(Book._meta.get_field("title").verbose_name)
    p_v = str(Book._meta.get_field("pages").verbose_name)
    raw = f"{t_v},{p_v}\nB3,3\n".encode("utf-8")
    buf = BytesIO(raw)
    buf.name = "s.csv"
    out = process_import(
        file=buf,
        import_definition=definition,
        user=auditor_user,
        filter_payload={},
        preview_only=False,
        run_async=True,
    )
    ask = out["import_request"]
    assert out["queued"] is False
    assert ask.status == ImportRequest.Status.SUCCESS
