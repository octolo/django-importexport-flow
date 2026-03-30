"""Background import using a daemon thread (dev / light workloads)."""

from __future__ import annotations

import threading

from django.db import close_old_connections

from django_importexport_flow.tasks import execute_import_request_by_uuid


class ThreadBackend:
    def enqueue(self, import_request_uuid: str) -> None:
        def _run() -> None:
            close_old_connections()
            try:
                execute_import_request_by_uuid(import_request_uuid)
            finally:
                close_old_connections()

        t = threading.Thread(target=_run, name=f"import-{import_request_uuid[:8]}", daemon=True)
        t.start()
