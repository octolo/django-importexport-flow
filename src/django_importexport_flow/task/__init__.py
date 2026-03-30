"""Configurable task backend for tabular imports (sync, thread, Celery, RQ)."""

from __future__ import annotations

from typing import Any

from django.db import transaction

from ..utils.helpers import get_setting


def get_import_task_backend() -> Any:
    """
    Backend name from ``IMPORT_TASK_BACKEND`` in package settings
    (``default_settings`` / ``DJANGO_IMPORTEXPORT_FLOW``): ``sync`` (default),
    ``thread``, ``celery``, ``rq``.
    """
    backend = get_setting("IMPORT_TASK_BACKEND", "sync")

    if backend == "celery":
        from .celery import CeleryBackend

        return CeleryBackend()
    if backend == "rq":
        from .django_rq import RQBackend

        return RQBackend()
    if backend == "thread":
        from .thread import ThreadBackend

        return ThreadBackend()

    from .sync import SyncBackend

    return SyncBackend()


def dispatch_import_request(ask: Any, *, asynchronous: bool = False) -> None:
    """
    Run :func:`~django_importexport_flow.engine.core.run.run_import_request` inline,
    or mark the row ``processing`` and enqueue it for the configured backend.

    * ``asynchronous=False`` or ``IMPORT_TASK_BACKEND=sync``: always inline (status
      goes ``pending`` → ``success`` / ``failure``).
    * ``asynchronous=True`` with a non-sync backend: ``pending`` → ``processing``, then
      the worker runs the import and sets the final status. Enqueue runs inside
      :func:`django.db.transaction.on_commit`.

    Idempotent if the request is no longer ``pending`` (e.g. double submit): no-op.
    """
    from ..engine.core.run import run_import_request
    from ..models import ImportRequest

    backend_name = get_setting("IMPORT_TASK_BACKEND", "sync")
    if not asynchronous or backend_name == "sync":
        run_import_request(ask)
        return

    uuid_str = str(ask.uuid)

    def _enqueue() -> None:
        get_import_task_backend().enqueue(uuid_str)

    with transaction.atomic():
        locked = (
            ImportRequest.objects.select_for_update()
            .filter(
                pk=ask.pk,
                status=ImportRequest.Status.PENDING,
            )
            .first()
        )
        if locked is None:
            ask.refresh_from_db()
            return
        locked.status = ImportRequest.Status.PROCESSING
        locked.save(update_fields=["status"])

    transaction.on_commit(_enqueue)
    ask.refresh_from_db()
