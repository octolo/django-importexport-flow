"""Retention behavior of the purge_export_requests command."""

from __future__ import annotations

from datetime import timedelta
from io import StringIO

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.utils import timezone

from django_importexport_flow.models import Definition, ExportRequest
from tests.sample.models import Book


def _definition() -> Definition:
    return Definition.objects.create(
        direction="export",
        name="Purge export",
        target=ContentType.objects.get_for_model(Book),
        manager="objects",
        filter_config={},
    )


def _request(
    definition: Definition,
    status: str,
    *,
    age: timedelta,
    content: bytes | None = None,
) -> ExportRequest:
    request = ExportRequest.objects.create(
        export_definition=definition,
        export_format="csv",
        status=status,
        completed_at=timezone.now() - age,
    )
    if content is not None:
        request.output_file.save("export.csv", ContentFile(content), save=True)
    return request


@pytest.mark.django_db
def test_dry_run_keeps_old_success_rows_and_files():
    definition = _definition()
    request = _request(
        definition,
        ExportRequest.Status.SUCCESS,
        age=timedelta(days=40),
        content=b"title\nkept\n",
    )
    stored_name = request.output_file.name
    output = StringIO()

    call_command("purge_export_requests", days=30, dry_run=True, stdout=output)

    request.refresh_from_db()
    assert request.output_file.storage.exists(stored_name)
    assert "Would delete 1 ExportRequest row" in output.getvalue()


@pytest.mark.django_db
def test_purge_deletes_old_terminal_requests_and_their_files():
    definition = _definition()
    success = _request(
        definition,
        ExportRequest.Status.SUCCESS,
        age=timedelta(days=40),
        content=b"title\nold\n",
    )
    failure = _request(
        definition,
        ExportRequest.Status.FAILURE,
        age=timedelta(days=45),
    )
    stored_name = success.output_file.name
    storage = success.output_file.storage
    output = StringIO()

    call_command("purge_export_requests", days=30, stdout=output)

    assert not ExportRequest.objects.filter(pk__in=(success.pk, failure.pk)).exists()
    assert not storage.exists(stored_name)
    assert "Deleted 2 ExportRequest row" in output.getvalue()


@pytest.mark.django_db
def test_purge_keeps_recent_and_non_terminal_requests():
    definition = _definition()
    recent = _request(
        definition,
        ExportRequest.Status.SUCCESS,
        age=timedelta(days=1),
        content=b"title\nrecent\n",
    )
    pending = _request(
        definition,
        ExportRequest.Status.PENDING,
        age=timedelta(days=90),
    )
    processing = _request(
        definition,
        ExportRequest.Status.PROCESSING,
        age=timedelta(days=90),
    )

    call_command("purge_export_requests", days=30)

    remaining = set(ExportRequest.objects.values_list("pk", flat=True))
    assert remaining == {recent.pk, pending.pk, processing.pk}
    assert recent.output_file.storage.exists(recent.output_file.name)


@pytest.mark.django_db
def test_days_changes_the_retention_cutoff():
    definition = _definition()
    request = _request(
        definition,
        ExportRequest.Status.SUCCESS,
        age=timedelta(days=10),
    )
    dry_run = StringIO()

    call_command("purge_export_requests", days=30, dry_run=True, stdout=dry_run)
    assert ExportRequest.objects.filter(pk=request.pk).exists()
    assert "Would delete 0 ExportRequest row" in dry_run.getvalue()

    call_command("purge_export_requests", days=5)
    assert not ExportRequest.objects.filter(pk=request.pk).exists()
