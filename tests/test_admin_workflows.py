"""Admin client coverage for the export form and the import wizard."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from django_importexport_flow.engine.core.import_ import default_importable_column_paths
from django_importexport_flow.models import (
    Definition,
    ExportDefinition,
    ExportRequest,
    FormatConfig,
    ImportDefinition,
    ImportRequest,
)
from tests.sample.models import Book
from tests.support import attach_import_spreadsheet, attach_pdf_export, attach_tabular_export

User = get_user_model()
SEEN: dict[str, str] = {}


def see_template(dataset, _category, _format_config, payload):
    SEEN["template"] = dataset.engine.get_template()
    SEEN["override"] = payload["template_override"]
    return b"captured", "text/plain", ".txt"


def _perm(model, codename: str) -> Permission:
    return Permission.objects.get(
        codename=codename,
        content_type=ContentType.objects.get_for_model(model, for_concrete_model=False),
    )


def _staff(*permissions: Permission):
    user = User.objects.create_user("staff", "staff@test.local", "secret", is_staff=True)
    user.user_permissions.add(*permissions)
    return user


def _export_definition():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export", name="Admin export", target=ct, manager="objects"
    )
    attach_tabular_export(export=definition, columns=["title"], configuration={}, formats=("csv",))
    pdf = attach_pdf_export(export=definition, template="<p>stored</p>")
    pdf.hook = ["tests.test_admin_workflows.see_template"]
    pdf.save()
    Book.objects.create(title="Shelf", pages=2)
    return definition


def _import_definition():
    ct = ContentType.objects.get_for_model(Book)
    excluded = [
        path for path in default_importable_column_paths(Book) if path not in {"title", "pages"}
    ]
    definition = Definition.objects.create(
        direction="import",
        name="Admin import",
        target=ct,
        columns_exclude=excluded,
    )
    attach_import_spreadsheet(definition)
    return definition


@pytest.mark.django_db
def test_export_admin_download_and_invalid_post(client):
    User.objects.create_superuser("admin", "admin@test.local", "secret")
    definition = _export_definition()
    client.login(username="admin", password="secret")
    url = reverse(
        "admin:django_importexport_flow_exportdefinition_process_export",
        args=[definition.pk],
    )
    page = client.get(url)
    assert page.status_code == 200
    assert b"export_format" in page.content

    invalid = client.post(url, {"export_format": "missing"})
    assert invalid.status_code == 200
    assert b"attachment" not in invalid.get("Content-Disposition", "").encode()

    downloaded = client.post(url, {"export_format": "csv"})
    assert downloaded.status_code == 200
    assert "attachment" in downloaded["Content-Disposition"]
    assert (
        downloaded["Content-Disposition"].endswith('.csv"')
        or ".csv" in downloaded["Content-Disposition"]
    )
    assert b"Shelf" in downloaded.content


@pytest.mark.django_db
def test_pdf_template_override_follows_the_format_permission(client):
    definition = _export_definition()
    url = reverse(
        "admin:django_importexport_flow_exportdefinition_process_export",
        args=[definition.pk],
    )
    User.objects.create_superuser("root", "root@test.local", "secret")
    client.login(username="root", password="secret")
    visible = client.get(url)
    assert b'name="template_override"' in visible.content
    SEEN.clear()
    applied = client.post(
        url,
        {"export_format": "pdf", "template_override": "<p>company</p>"},
    )
    assert applied.status_code == 200
    assert applied.content == b"captured"
    assert SEEN["template"] == "<p>company</p>"
    assert ExportRequest.objects.get().template_override == "<p>company</p>"

    client.logout()
    _staff(_perm(ExportDefinition, "change_exportdefinition"))
    client.login(username="staff", password="secret")
    hidden = client.get(url)
    assert hidden.status_code == 200
    assert b'name="template_override"' not in hidden.content
    SEEN.clear()
    ExportRequest.objects.all().delete()
    forged = client.post(
        url,
        {"export_format": "pdf", "template_override": "<p>forged</p>"},
    )
    assert forged.status_code == 200
    assert b"permission" in forged.content
    assert forged.content != b"captured"
    assert SEEN == {}
    assert not ExportRequest.objects.exists()

    client.logout()
    User.objects.filter(username="staff").delete()
    _staff(
        _perm(ExportDefinition, "change_exportdefinition"),
        _perm(FormatConfig, "change_formatconfig"),
    )
    client.login(username="staff", password="secret")
    allowed = client.get(url)
    assert b'name="template_override"' in allowed.content
    SEEN.clear()
    empty = client.post(url, {"export_format": "pdf", "template_override": ""})
    assert empty.content == b"captured"
    assert SEEN["template"] == "<p>stored</p>"
    assert SEEN["override"] == ""
    assert "attachment" in empty["Content-Disposition"]


@pytest.mark.django_db
def test_export_admin_requires_change_permission(client):
    definition = _export_definition()
    url = reverse(
        "admin:django_importexport_flow_exportdefinition_process_export",
        args=[definition.pk],
    )
    anonymous = client.get(url)
    assert anonymous.status_code == 302
    _staff()
    client.login(username="staff", password="secret")
    denied = client.get(url)
    assert denied.status_code == 403


@pytest.mark.django_db
def test_import_admin_wizard_uploads_previews_and_confirms(client):
    User.objects.create_superuser("admin", "admin@test.local", "secret")
    definition = _import_definition()
    client.login(username="admin", password="secret")
    url = reverse(
        "admin:django_importexport_flow_importdefinition_import_tabular_data",
        args=[definition.pk],
    )
    page = client.get(url)
    assert page.status_code == 200
    assert b"multipart/form-data" in page.content

    invalid = client.post(url, {"step": "upload"})
    assert invalid.status_code == 200
    assert b"required" in invalid.content.lower()

    broken = client.post(
        url,
        {
            "step": "upload",
            "file": SimpleUploadedFile("books.xlsx", b"not-a-workbook"),
        },
    )
    assert broken.status_code == 200
    assert b"Excel" in broken.content
    assert ImportRequest.objects.count() == 0

    uploaded = client.post(
        url,
        {
            "step": "upload",
            "file": SimpleUploadedFile("books.csv", b"title,pages\nOriginal,3\n"),
        },
    )
    assert uploaded.status_code == 302
    assert "import-tabular-preview" in uploaded["Location"]
    preview = client.get(uploaded["Location"])
    assert preview.status_code == 200
    assert b"Original" in preview.content

    ask = ImportRequest.objects.get()
    confirmed = client.post(
        url,
        {"step": "confirm", "import_request_uuid": str(ask.uuid)},
    )
    assert confirmed.status_code == 302
    ask.refresh_from_db()
    assert ask.status == ImportRequest.Status.SUCCESS
    assert Book.objects.filter(title="Original", pages=3).exists()


@pytest.mark.django_db(transaction=True)
def test_import_confirm_can_enqueue_without_running_inline(client, settings, monkeypatch):
    User.objects.create_superuser("admin", "admin@test.local", "secret")
    definition = _import_definition()
    client.login(username="admin", password="secret")
    url = reverse(
        "admin:django_importexport_flow_importdefinition_import_tabular_data",
        args=[definition.pk],
    )
    settings.DJANGO_IMPORTEXPORT_FLOW = {"IMPORT_TASK_BACKEND": "thread"}
    queued: list[str] = []
    monkeypatch.setattr(
        "django_importexport_flow.task.thread.ThreadBackend.enqueue",
        lambda _self, request_uuid: queued.append(request_uuid),
    )
    uploaded = client.post(
        url,
        {
            "step": "upload",
            "file": SimpleUploadedFile("books.csv", b"title,pages\nLater,8\n"),
        },
    )
    assert uploaded.status_code == 302
    ask = ImportRequest.objects.get()
    response = client.post(
        url,
        {
            "step": "confirm",
            "import_request_uuid": str(ask.uuid),
            "defer_to_task": "on",
        },
    )
    assert response.status_code == 302
    ask.refresh_from_db()
    assert ask.status == ImportRequest.Status.PROCESSING
    assert queued == [str(ask.uuid)]
    assert not Book.objects.filter(title="Later").exists()


@pytest.mark.django_db
def test_import_admin_requires_change_permission(client):
    definition = _import_definition()
    url = reverse(
        "admin:django_importexport_flow_importdefinition_import_tabular_data",
        args=[definition.pk],
    )
    assert client.get(url).status_code == 302
    _staff(_perm(ImportDefinition, "change_importdefinition"))
    client.login(username="staff", password="secret")
    assert client.get(url).status_code == 200
    client.logout()
    User.objects.filter(username="staff").delete()
    _staff()
    client.login(username="staff", password="secret")
    assert client.get(url).status_code == 403
