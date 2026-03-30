"""Synchronous import (default): run in the current process."""

from __future__ import annotations

from django_importexport_flow.tasks import execute_import_request_by_uuid


class SyncBackend:
    def enqueue(self, import_request_uuid: str) -> None:
        execute_import_request_by_uuid(import_request_uuid)
