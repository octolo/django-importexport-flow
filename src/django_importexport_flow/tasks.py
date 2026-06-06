"""Background import/export execution (thread, Celery, RQ). Sync path calls processing directly."""

from __future__ import annotations

from django.db import close_old_connections


def execute_import_request_by_uuid(import_request_uuid: str) -> None:
    """
    Load :class:`~django_importexport_flow.models.ImportRequest` by UUID and run
    :func:`~django_importexport_flow.engine.core.processing.process_import_request`.

    Callers should invoke :func:`django.db.close_old_connections` before ORM use when
    running off the main thread; this function does it at start.
    """
    close_old_connections()
    from django_importexport_flow.engine.core.processing import process_import_request
    from django_importexport_flow.models import ImportRequest

    ask = ImportRequest.objects.get(uuid=import_request_uuid)
    process_import_request(ask)


def execute_export_request_by_uuid(export_request_uuid: str) -> None:
    """
    Load :class:`~django_importexport_flow.models.ExportRequest` by UUID and run
    :func:`~django_importexport_flow.engine.core.processing.process_export_request`.

    Callers should invoke :func:`django.db.close_old_connections` before ORM use when
    running off the main thread; this function does it at start.
    """
    close_old_connections()
    from django_importexport_flow.engine.core.processing import process_export_request
    from django_importexport_flow.models import ExportRequest

    er = ExportRequest.objects.get(uuid=export_request_uuid)
    process_export_request(er)


try:
    from celery import shared_task
except ImportError:
    run_import_request_task = None  # type: ignore[misc, assignment]
    run_export_request_task = None  # type: ignore[misc, assignment]
else:

    @shared_task(name="django_importexport_flow.run_import_request")
    def run_import_request_task(import_request_uuid: str) -> None:
        execute_import_request_by_uuid(import_request_uuid)

    @shared_task(name="django_importexport_flow.run_export_request")
    def run_export_request_task(export_request_uuid: str) -> None:
        execute_export_request_by_uuid(export_request_uuid)
