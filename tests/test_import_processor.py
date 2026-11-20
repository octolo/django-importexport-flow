import pandas as pd
import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from django_importexport_flow.engine.core.processor import ImportProcessorResult
from django_importexport_flow.engine.core.run import relaunch_import_request
from django_importexport_flow.models import CategoryConfig, Definition, FormatConfig, ImportRequest
from django_importexport_flow.tasks import execute_import_request_by_uuid
from django_importexport_flow.utils.process import process_import
from tests.sample.models import Author


def _processor(file, context):
    name = file.read().decode().strip()
    scope = context.filter_payload["fr_get_scope"]
    if context.filter_payload.get("reset"):
        Author.objects.filter(name__startswith=f"{scope}:").delete()
    # Deliberately write in preview to verify Flow rolls back database changes.
    Author.objects.create(name=f"{scope}:{name}")
    if context.filter_payload.get("reject"):
        return ImportProcessorResult(errors=["Rejected by processor"], imported_row_count=1)
    if context.preview_only:
        return ImportProcessorResult(
            dataframe=pd.DataFrame({"name": [name]}), warnings=["Preview only"]
        )
    return ImportProcessorResult(imported_row_count=1)


@pytest.fixture
def definition(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    settings.DJANGO_IMPORTEXPORT_FLOW = {
        "ALLOWED_HOOK_MODULE_PREFIXES": ["tests.test_import_processor"],
    }
    definition = Definition.objects.create(
        direction="import",
        name="Business import",
        target=ContentType.objects.get_for_model(Author),
        filter_request={"scope": "name"},
    )
    category = CategoryConfig.objects.create(
        definition=definition,
        category_key="spreadsheet",
        configuration={"import_processor": "tests.test_import_processor._processor"},
    )
    FormatConfig.objects.create(category_config=category, format_key="csv")
    return definition


def _upload():
    return SimpleUploadedFile("business.csv", b"Business row\n")


@pytest.mark.django_db(transaction=True)
def test_processor_preview_confirm_and_relaunch(definition, auditor_user):
    payload = {"fr_get_scope": "A", "reset": True}
    Author.objects.create(name="A:old")
    Author.objects.create(name="B:keep")

    preview = process_import(
        file=_upload(),
        import_definition=definition,
        user=auditor_user,
        filter_payload=payload,
        preview_only=True,
    )
    assert preview["column_paths"] == ["name"]
    assert preview["validation_dataset"]["rows"] == [{"name": "Business row"}]
    assert not ImportRequest.objects.exists()
    assert set(Author.objects.values_list("name", flat=True)) == {"A:old", "B:keep"}

    result = process_import(
        file=_upload(), import_definition=definition, user=auditor_user, filter_payload=payload
    )
    ask = result["import_request"]
    assert result["success"]
    assert ask.initiated_by == auditor_user
    assert ask.imported_row_count == 1
    assert ask.completed_at is not None
    assert ask.data_file

    Author.objects.create(name="A:added after import")
    retry = relaunch_import_request(ask, auditor_user)
    execute_import_request_by_uuid(str(retry.uuid))
    retry.refresh_from_db()
    assert retry.relaunched_from == ask
    assert retry.filter_payload == payload
    assert retry.status == ImportRequest.Status.SUCCESS
    assert set(Author.objects.values_list("name", flat=True)) == {"A:Business row", "B:keep"}


@pytest.mark.django_db
def test_processor_errors_rollback_the_import(definition):
    result = process_import(
        file=_upload(),
        import_definition=definition,
        filter_payload={"fr_get_scope": "A", "reject": True},
    )
    ask = result["import_request"]
    assert ask.status == ImportRequest.Status.FAILURE
    assert ask.error_trace == "Rejected by processor"
    assert ask.imported_row_count == 0
    assert not Author.objects.exists()


@pytest.mark.django_db
def test_admin_previews_and_confirms_through_processor(client, definition, django_user_model):
    user = django_user_model.objects.create_superuser("admin", password="secret")
    client.force_login(user)
    url = reverse(
        "admin:django_importexport_flow_importdefinition_import_tabular_data",
        args=[definition.pk],
    )
    uploaded = client.post(url, {"step": "upload", "file": _upload(), "fr_get_scope": "Admin"})
    assert uploaded.status_code == 302
    preview = client.get(uploaded["Location"])
    assert preview.status_code == 200
    assert b"Business row" in preview.content
    assert not Author.objects.exists()

    ask = ImportRequest.objects.get()
    confirmed = client.post(url, {"step": "confirm", "import_request_uuid": str(ask.uuid)})
    assert confirmed.status_code == 302
    ask.refresh_from_db()
    assert ask.status == ImportRequest.Status.SUCCESS
    assert Author.objects.get().name == "Admin:Business row"
