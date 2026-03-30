"""Background import execution (thread, Celery, RQ). Sync path uses :func:`engine.core.run.run_import_request` directly."""

from __future__ import annotations

from django.db import close_old_connections


def execute_import_request_by_uuid(import_request_uuid: str) -> None:
    """
    Load :class:`~django_importexport_flow.models.ImportRequest` by UUID and run
    :func:`~django_importexport_flow.engine.core.run.run_import_request`.

    Callers should invoke :func:`django.db.close_old_connections` before ORM use when
    running off the main thread; this function does it at start.
    """
    close_old_connections()
    from django_importexport_flow.engine.core.run import run_import_request
    from django_importexport_flow.models import ImportRequest

    ask = ImportRequest.objects.get(uuid=import_request_uuid)
    run_import_request(ask)


try:
    from celery import shared_task
except ImportError:
    run_import_request_task = None  # type: ignore[misc, assignment]
else:

    @shared_task(name="django_importexport_flow.run_import_request")
    def run_import_request_task(import_request_uuid: str) -> None:
        execute_import_request_by_uuid(import_request_uuid)
