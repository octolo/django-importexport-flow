"""Queue import via django-rq."""

from __future__ import annotations


class RQBackend:
    def enqueue(self, import_request_uuid: str) -> None:
        try:
            from django_rq import get_queue
        except ImportError as exc:
            raise ImportError(
                "django-rq is not installed. Install django-rq or set IMPORT_TASK_BACKEND to sync/thread/celery."
            ) from exc

        from django_importexport_flow.tasks import execute_import_request_by_uuid

        get_queue().enqueue(execute_import_request_by_uuid, import_request_uuid)
