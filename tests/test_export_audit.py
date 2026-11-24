"""Tests for :func:`~django_importexport_flow.utils.process.run_export_with_audit`."""

from __future__ import annotations

import json
from datetime import date
from pathlib import PurePosixPath

import pytest
from django.contrib.contenttypes.models import ContentType
from django.test import override_settings

from django_importexport_flow.models import Definition, ExportRequest
from django_importexport_flow.utils.process import run_export_with_audit
from tests.sample.models import Book
from tests.support import attach_tabular_export


def custom_export_filename(export_request, extension):
    return f"books-{export_request.pk}{extension}"


def invalid_export_filename(_export_request, extension):
    return f"../books{extension}"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("hook_name", "success"),
    [("custom_export_filename", True), ("invalid_export_filename", False)],
)
def test_export_request_applies_filename_hook(settings, tmp_path, hook_name, success):
    settings.MEDIA_ROOT = tmp_path
    definition = Definition.objects.create(
        direction="export",
        name="Filename hook",
        target=ContentType.objects.get_for_model(Book),
        filename_hook=f"tests.test_export_audit.{hook_name}",
    )
    attach_tabular_export(export=definition, columns=["title"], configuration={})
    Book.objects.create(title="Filename hook")
    export_request = ExportRequest(export_definition=definition, export_format="json")
    export_request.save(trigger_processing=True, asynchronous=False)
    export_request.refresh_from_db()

    if success:
        assert export_request.status == ExportRequest.Status.SUCCESS
        assert (
            PurePosixPath(export_request.output_file.name).name == f"books-{export_request.pk}.json"
        )
    else:
        assert export_request.status == ExportRequest.Status.FAILURE
        assert "valid basename" in export_request.error_trace
        assert not export_request.output_file


@pytest.mark.django_db
def test_run_export_with_audit_persists_manager_method_arguments(auditor_user):
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export",
        name="Audit manager method args",
        target=ct,
        manager="objects.published_on_or_before",
        manager_method_kwargs_request={
            "published_before": {"kwarg": "cutoff", "type": "date"},
        },
    )
    attach_tabular_export(export=definition, columns=["title"], configuration={})
    Book.objects.create(title="Before", publication_date=date(2020, 1, 1))
    Book.objects.create(title="After", publication_date=date(2022, 1, 1))

    content, _content_type, _extension = run_export_with_audit(
        export_definition=definition,
        filter_payload={
            "export_format": "json",
            "mm_get_published_before": "2021-01-01",
        },
        user=auditor_user,
    )

    request = ExportRequest.objects.get(export_definition=definition)
    assert request.manager_kwargs_payload == {
        "mm_get_published_before": "2021-01-01",
    }
    assert len(json.loads(content.decode("utf-8"))) == 1


@pytest.mark.django_db
def test_run_export_with_audit_success_creates_export_request(auditor_user):
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export",
        name="Audit ok",
        target=ct,
        manager="objects",
        filter_config={},
    )
    attach_tabular_export(
        export=definition,
        columns=["title"],
        configuration={},
    )
    Book.objects.create(title="Audited", pages=0)
    payload = {"export_format": "json"}
    content, _ct, _ext = run_export_with_audit(
        export_definition=definition,
        filter_payload=payload,
        user=auditor_user,
    )
    assert len(content) > 0
    er = ExportRequest.objects.get(export_definition=definition)
    assert er.status == ExportRequest.Status.SUCCESS
    assert er.output_bytes == len(content)
    assert er.initiated_by_id == auditor_user.pk
    assert er.filter_payload.get("export_format") == "json"
    assert not er.error_trace
    assert er.output_file


@pytest.mark.django_db
@override_settings(DJANGO_IMPORTEXPORT_FLOW={"PERSIST_EXPORT_REQUEST_FILES": False})
def test_run_export_with_audit_can_skip_the_stored_file(auditor_user):
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export",
        name="Audit memory",
        target=ct,
        manager="objects",
        filter_config={},
    )
    attach_tabular_export(export=definition, columns=["title"], configuration={})
    Book.objects.create(title="Memory", pages=0)
    content, _content_type, _ext = run_export_with_audit(
        export_definition=definition,
        filter_payload={"export_format": "json"},
        user=auditor_user,
    )
    assert b"Memory" in content
    er = ExportRequest.objects.get(export_definition=definition)
    assert er.status == ExportRequest.Status.SUCCESS
    assert er.output_bytes == len(content)
    assert not er.output_file


@pytest.mark.django_db
def test_run_export_with_audit_failure_records_export_request(auditor_user):
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export",
        name="Audit fail",
        target=ct,
        manager="objects",
        filter_config={},
        filter_mandatory={"get": {"mid": "id"}},
    )
    attach_tabular_export(
        export=definition,
        columns=["title"],
        configuration={},
    )
    with pytest.raises(ValueError, match="mid|Mandatory"):
        run_export_with_audit(
            export_definition=definition,
            filter_payload={"export_format": "json"},
            user=auditor_user,
        )
    er = ExportRequest.objects.get(export_definition=definition)
    assert er.status == ExportRequest.Status.FAILURE
    assert er.initiated_by_id == auditor_user.pk
    assert er.error_trace
    assert er.output_bytes is None


@pytest.mark.django_db
def test_run_export_with_audit_sequential_creates_two_rows(auditor_user):
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export",
        name="Audit twice",
        target=ct,
        manager="objects",
        filter_config={},
    )
    attach_tabular_export(
        export=definition,
        columns=["title"],
        configuration={},
    )
    Book.objects.create(title="T", pages=0)
    payload = {"export_format": "json"}
    run_export_with_audit(export_definition=definition, filter_payload=payload, user=auditor_user)
    run_export_with_audit(export_definition=definition, filter_payload=payload, user=auditor_user)
    assert ExportRequest.objects.filter(export_definition=definition).count() == 2
    assert all(
        r.status == ExportRequest.Status.SUCCESS
        for r in ExportRequest.objects.filter(export_definition=definition)
    )


@pytest.mark.django_db
def test_audit_persists_request_overrides(auditor_user):
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export",
        name="Audit overrides",
        target=ct,
        manager="objects",
        filter_config={},
    )
    attach_tabular_export(
        export=definition, columns=["title", "pages"], configuration={"delimiter": ","}
    )
    Book.objects.create(title="Audited", pages=4)
    content, _content_type, extension = run_export_with_audit(
        export_definition=definition,
        filter_payload={"export_format": "csv"},
        user=auditor_user,
        configuration_overrides={"format": {"delimiter": "|"}, "hook": {"locale": "fr"}},
    )
    er = ExportRequest.objects.get(export_definition=definition)
    assert extension == ".csv"
    assert b"Book title|Nb. of pages" in content
    assert er.template_override == ""
    assert er.configuration_overrides == {"format": {"delimiter": "|"}, "hook": {"locale": "fr"}}
    assert er.filter_payload == {"export_format": "csv"}
    assert "delimiter" not in er.filter_payload


@pytest.mark.django_db(transaction=True)
def test_background_export_uses_persisted_overrides(settings, auditor_user):
    import threading
    import time

    settings.DJANGO_IMPORTEXPORT_FLOW = {"IMPORT_TASK_BACKEND": "thread"}
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export",
        name="Async overrides",
        target=ct,
        manager="objects",
        filter_config={},
    )
    attach_tabular_export(export=definition, columns=["title", "pages"], configuration={})
    Book.objects.create(title="Queued", pages=8)
    er = ExportRequest.objects.create(
        export_definition=definition,
        export_format="csv",
        filter_payload={"export_format": "csv"},
        configuration_overrides={"format": {"delimiter": ";"}, "hook": {"company_id": 3}},
        status=ExportRequest.Status.PENDING,
        initiated_by=auditor_user,
    )
    er.save(trigger_processing=True, asynchronous=True)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        er.refresh_from_db()
        if er.status != ExportRequest.Status.PROCESSING:
            break
        time.sleep(0.05)
    for worker in threading.enumerate():
        if worker.name == f"export-{str(er.uuid)[:8]}":
            worker.join(timeout=5)
            assert not worker.is_alive()
            break
    assert er.status == ExportRequest.Status.SUCCESS
    with er.output_file.open("rb") as output:
        assert b";" in output.read()
