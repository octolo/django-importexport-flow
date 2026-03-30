"""Tests for :func:`~django_importexport_flow.utils.process.run_export_with_audit`."""

from __future__ import annotations

import pytest
from django.contrib.contenttypes.models import ContentType

from django_importexport_flow.models import ExportConfigTable, ExportDefinition, ExportRequest
from django_importexport_flow.utils.process import run_export_with_audit
from tests.sample.models import Book


@pytest.mark.django_db
def test_run_export_with_audit_success_creates_export_request(auditor_user):
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition.objects.create(
        name="Audit ok",
        target=ct,
        manager="objects",
        filter_config={},
    )
    ExportConfigTable.objects.create(
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


@pytest.mark.django_db
def test_run_export_with_audit_failure_records_export_request(auditor_user):
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition.objects.create(
        name="Audit fail",
        target=ct,
        manager="objects",
        filter_config={},
        filter_mandatory={"get": {"mid": "id"}},
    )
    ExportConfigTable.objects.create(
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
    definition = ExportDefinition.objects.create(
        name="Audit twice",
        target=ct,
        manager="objects",
        filter_config={},
    )
    ExportConfigTable.objects.create(
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
