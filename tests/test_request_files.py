"""Configurable storage and upload paths for request files."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.core.files.storage.base import Storage

from django_importexport_flow.models import Definition, ExportRequest, ImportRequest
from django_importexport_flow.models.request import (
    _SettingsStorage,
    attach_export_file,
    attach_import_file,
    export_output_upload_to,
    import_file_upload_to,
)
from tests.sample.models import Book


class MarkerStorage(FileSystemStorage):
    saved: ClassVar[list[str]] = []

    def __init__(self) -> None:
        super().__init__(location="/tmp/django-importexport-flow-storage")

    def save(self, name, content, max_length=None):
        stored = super().save(name, content, max_length=max_length)
        type(self).saved.append(stored)
        return stored


def export_upload_to(instance, filename):
    return f"companies/{instance.export_format}/{filename}"


def import_upload_to(instance, filename):
    return f"incoming/{instance.pk}/{filename}"


@pytest.fixture
def export_definition():
    ct = ContentType.objects.get_for_model(Book)
    return Definition.objects.create(
        direction="export", name="Stored export", target=ct, manager="objects"
    )


@pytest.fixture
def import_definition():
    ct = ContentType.objects.get_for_model(Book)
    return Definition.objects.create(direction="import", name="Stored import", target=ct)


@pytest.mark.django_db
def test_request_files_use_the_default_dated_directories(export_definition, import_definition):
    export_request = ExportRequest.objects.create(
        export_definition=export_definition,
        export_format="csv",
    )
    attach_export_file(export_request, "export.csv", b"a,b")
    export_request.save(update_fields=["output_file"])
    assert export_request.output_file.name.startswith(
        datetime.now().strftime("export_outputs/%Y/%m/")
    )

    import_request = ImportRequest.objects.create(import_definition=import_definition)
    attach_import_file(import_request, "books.csv", b"title\nA\n", keep_for_later=False)
    assert import_request.data_file.name.startswith(
        datetime.now().strftime("report_import_asks/%Y/%m/")
    )


@pytest.mark.django_db
def test_request_files_use_configured_storage_and_callable_paths(
    settings,
    export_definition,
    import_definition,
):
    MarkerStorage.saved = []
    settings.DJANGO_IMPORTEXPORT_FLOW = {
        "EXPORT_OUTPUT_STORAGE": "tests.test_request_files.MarkerStorage",
        "IMPORT_FILE_STORAGE": "tests.test_request_files.MarkerStorage",
        "EXPORT_OUTPUT_UPLOAD_TO": "tests.test_request_files.export_upload_to",
        "IMPORT_FILE_UPLOAD_TO": "tests.test_request_files.import_upload_to",
    }
    export_request = ExportRequest.objects.create(
        export_definition=export_definition,
        export_format="csv",
    )
    attach_export_file(export_request, "export.csv", b"a,b")
    assert export_request.output_file.name.startswith("companies/csv/export")
    assert export_request.output_file.name.endswith(".csv")

    import_request = ImportRequest.objects.create(import_definition=import_definition)
    attach_import_file(import_request, "books.csv", b"title\nA\n", keep_for_later=False)
    assert import_request.data_file.name.startswith(f"incoming/{import_request.pk}/books")
    assert import_request.data_file.name.endswith(".csv")
    assert MarkerStorage.saved == [
        export_request.output_file.name,
        import_request.data_file.name,
    ]


@pytest.mark.django_db
def test_upload_path_accepts_a_template(settings, export_definition):
    settings.DJANGO_IMPORTEXPORT_FLOW = {"EXPORT_OUTPUT_UPLOAD_TO": "external/%Y/reports/"}
    export_request = ExportRequest.objects.create(
        export_definition=export_definition,
        export_format="json",
    )
    attach_export_file(export_request, "export.json", b"[]")
    prefix = datetime.now().strftime("external/%Y/reports/export")
    assert export_request.output_file.name.startswith(prefix)
    assert export_request.output_file.name.endswith(".json")


def _direct_upload_to(_instance, filename):
    return f"direct/{filename}"


@pytest.mark.django_db
def test_storage_accepts_an_alias_an_instance_and_a_callable(settings, tmp_path, export_definition):
    alias_root = tmp_path / "alias"
    alias_root.mkdir()
    settings.STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "flow_exports": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": str(alias_root)},
        },
    }
    settings.DJANGO_IMPORTEXPORT_FLOW = {"EXPORT_OUTPUT_STORAGE": "flow_exports"}
    export_request = ExportRequest.objects.create(
        export_definition=export_definition, export_format="csv"
    )
    attach_export_file(export_request, "alias.csv", b"a,b")
    assert list(alias_root.rglob("alias*.csv"))

    direct = FileSystemStorage(location=str(tmp_path / "direct"))
    settings.DJANGO_IMPORTEXPORT_FLOW = {"EXPORT_OUTPUT_STORAGE": direct}
    export_request = ExportRequest.objects.create(
        export_definition=export_definition, export_format="csv"
    )
    attach_export_file(export_request, "direct.csv", b"a,b")
    assert (tmp_path / "direct").exists()
    assert list((tmp_path / "direct").rglob("direct*.csv"))

    settings.DJANGO_IMPORTEXPORT_FLOW = {"EXPORT_OUTPUT_STORAGE": lambda: direct}
    resolved = _SettingsStorage("EXPORT_OUTPUT_STORAGE")._current()
    assert resolved is direct


class PathlessStorage(Storage):
    """Storage whose ``path()`` is the base implementation."""

    def __init__(self) -> None:
        self._entries: dict[str, bytes] = {}

    def save(self, name, content, max_length=None):
        self._entries[name] = content.read()
        return name

    def open(self, name, mode="rb"):
        return ContentFile(self._entries[name])

    def delete(self, name):
        self._entries.pop(name, None)

    def exists(self, name):
        return name in self._entries

    def url(self, name):
        return name


@pytest.mark.django_db
def test_storage_without_path_raises_the_backend_error(settings, export_definition):
    memory = PathlessStorage()
    settings.DJANGO_IMPORTEXPORT_FLOW = {"EXPORT_OUTPUT_STORAGE": memory}
    export_request = ExportRequest.objects.create(
        export_definition=export_definition, export_format="csv"
    )
    attach_export_file(export_request, "memory.csv", b"a,b")
    with pytest.raises(NotImplementedError):
        export_request.output_file.storage.path(export_request.output_file.name)


@pytest.mark.django_db
def test_storage_delegates_time_methods(settings, tmp_path, export_definition):
    storage = FileSystemStorage(location=str(tmp_path))
    settings.DJANGO_IMPORTEXPORT_FLOW = {"EXPORT_OUTPUT_STORAGE": storage}
    export_request = ExportRequest.objects.create(
        export_definition=export_definition, export_format="csv"
    )
    attach_export_file(export_request, "times.csv", b"a,b")
    name = export_request.output_file.name
    wrapper = export_request.output_file.storage
    for method in ("get_accessed_time", "get_created_time", "get_modified_time"):
        assert getattr(wrapper, method)(name) == getattr(storage, method)(name)


def test_upload_to_directories_templates_and_callables(settings):
    settings.DJANGO_IMPORTEXPORT_FLOW = {"IMPORT_FILE_UPLOAD_TO": "uploads"}
    assert import_file_upload_to(object(), "a.csv") == "uploads/a.csv"
    settings.DJANGO_IMPORTEXPORT_FLOW = {"IMPORT_FILE_UPLOAD_TO": "uploads/"}
    assert import_file_upload_to(object(), "a.csv") == "uploads/a.csv"
    settings.DJANGO_IMPORTEXPORT_FLOW = {"EXPORT_OUTPUT_UPLOAD_TO": "uploads/%Y/%m/"}
    stored = export_output_upload_to(object(), "a.csv")
    assert stored.startswith(datetime.now().strftime("uploads/%Y/%m/"))
    settings.DJANGO_IMPORTEXPORT_FLOW = {"EXPORT_OUTPUT_UPLOAD_TO": _direct_upload_to}
    assert export_output_upload_to(object(), "a.csv") == "direct/a.csv"
    settings.DJANGO_IMPORTEXPORT_FLOW = {
        "IMPORT_FILE_UPLOAD_TO": "tests.test_request_files.import_upload_to"
    }
    assert import_file_upload_to(type("Row", (), {"pk": 7})(), "a.csv") == "incoming/7/a.csv"


@pytest.mark.django_db
def test_absolute_and_parent_upload_paths_are_rejected(settings, export_definition):
    export_request = ExportRequest.objects.create(
        export_definition=export_definition, export_format="csv"
    )
    settings.DJANGO_IMPORTEXPORT_FLOW = {"EXPORT_OUTPUT_UPLOAD_TO": "/tmp/%Y/"}
    with pytest.raises(SuspiciousFileOperation):
        attach_export_file(export_request, "export.csv", b"a,b")
    settings.DJANGO_IMPORTEXPORT_FLOW = {"EXPORT_OUTPUT_UPLOAD_TO": "../outside/%Y/"}
    with pytest.raises(SuspiciousFileOperation):
        attach_export_file(export_request, "export.csv", b"a,b")


@pytest.mark.django_db
def test_import_and_export_can_use_different_storages(
    settings, tmp_path, export_definition, import_definition
):
    export_root = tmp_path / "exports"
    import_root = tmp_path / "imports"
    settings.DJANGO_IMPORTEXPORT_FLOW = {
        "EXPORT_OUTPUT_STORAGE": FileSystemStorage(location=str(export_root)),
        "IMPORT_FILE_STORAGE": FileSystemStorage(location=str(import_root)),
    }
    export_request = ExportRequest.objects.create(
        export_definition=export_definition, export_format="csv"
    )
    attach_export_file(export_request, "out.csv", b"a,b")
    import_request = ImportRequest.objects.create(import_definition=import_definition)
    attach_import_file(import_request, "in.csv", b"title\nA\n", keep_for_later=False)
    assert list(export_root.rglob("out*.csv"))
    assert list(import_root.rglob("in*.csv"))
    assert not list(export_root.rglob("in*.csv"))
