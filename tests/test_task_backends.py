"""Celery and django-rq adapters, without a broker."""

from __future__ import annotations

import sys
import types

import pytest

from django_importexport_flow import tasks
from django_importexport_flow.task.celery import CeleryBackend
from django_importexport_flow.task.django_rq import RQBackend


def test_celery_backend_delays_the_optional_tasks(monkeypatch):
    calls: list[tuple[str, str]] = []

    class _Task:
        def __init__(self, label: str):
            self.label = label

        def delay(self, request_uuid: str) -> None:
            calls.append((self.label, request_uuid))

    monkeypatch.setattr(tasks, "run_import_request_task", _Task("import"))
    monkeypatch.setattr(tasks, "run_export_request_task", _Task("export"))
    CeleryBackend().enqueue("import-1")
    CeleryBackend().enqueue_export("export-1")
    assert calls == [("import", "import-1"), ("export", "export-1")]


def test_celery_backend_reports_a_missing_task(monkeypatch):
    monkeypatch.setattr(tasks, "run_import_request_task", None)
    monkeypatch.setattr(tasks, "run_export_request_task", None)
    with pytest.raises(ImportError, match="Celery is not installed"):
        CeleryBackend().enqueue("import-1")
    with pytest.raises(ImportError, match="Celery is not installed"):
        CeleryBackend().enqueue_export("export-1")


def test_rq_backend_enqueues_on_the_default_queue(monkeypatch):
    queued: list[tuple[str, str]] = []

    class _Queue:
        def enqueue(self, callback, request_uuid: str) -> None:
            queued.append((callback.__name__, request_uuid))

    module = types.ModuleType("django_rq")
    module.get_queue = lambda: _Queue()
    monkeypatch.setitem(sys.modules, "django_rq", module)
    RQBackend().enqueue("import-1")
    RQBackend().enqueue_export("export-1")
    assert queued == [
        ("execute_import_request_by_uuid", "import-1"),
        ("execute_export_request_by_uuid", "export-1"),
    ]


def test_rq_backend_reports_a_missing_package(monkeypatch):
    monkeypatch.setitem(sys.modules, "django_rq", None)
    with pytest.raises(ImportError, match="django-rq is not installed"):
        RQBackend().enqueue("import-1")
    with pytest.raises(ImportError, match="django-rq is not installed"):
        RQBackend().enqueue_export("export-1")
