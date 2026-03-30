"""Queue import via Celery."""

from __future__ import annotations


class CeleryBackend:
    def enqueue(self, import_request_uuid: str) -> None:
        from django_importexport_flow import tasks

        if tasks.run_import_request_task is None:
            raise ImportError(
                "Celery is not installed. Install celery or set IMPORT_TASK_BACKEND to sync/thread/rq."
            )
        tasks.run_import_request_task.delay(import_request_uuid)
