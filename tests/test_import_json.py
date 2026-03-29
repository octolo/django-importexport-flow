import json

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from django_importexport_flow.models import (
    ExportConfigPdf,
    ExportConfigTable,
    ExportDefinition,
)
from django_importexport_flow.utils.serialization import import_export_configuration, serialize_export_configuration
from tests.sample.models import Book


@pytest.mark.django_db
def test_import_export_configuration_roundtrip():
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition.objects.create(
        name="Roundtrip",
        target=ct,
        manager="objects",
        filter_config={},
    )
    ExportConfigPdf.objects.create(
        export=definition,
        template="<html>a</html>",
        configuration={"x": 1},
    )
    ExportConfigTable.objects.create(
        export=definition,
        columns=["title"],
        configuration={"json": {"indent": 4}},
    )
    payload = serialize_export_configuration(definition)
    ExportDefinition.objects.all().delete()
    assert ExportDefinition.objects.count() == 0

    loaded = import_export_configuration(payload)
    assert loaded.name == "Roundtrip"
    assert loaded.target_id == ct.id
    assert loaded.config_pdf.template == "<html>a</html>"
    assert loaded.config_table.columns[0] == "title"
    assert loaded.config_table.configuration["json"]["indent"] == 4


@pytest.mark.django_db
def test_import_export_configuration_replaces_when_name_exists():
    ct = ContentType.objects.get_for_model(Book)
    source = ExportDefinition.objects.create(
        name="Match",
        target=ct,
        manager="objects",
        filter_config={},
    )
    ExportConfigPdf.objects.create(
        export=source, template="<p>s</p>", configuration={"k": 1}
    )
    payload = serialize_export_configuration(source)
    source.delete()
    existing = ExportDefinition.objects.create(
        name="Match",
        target=ct,
        manager="objects.all",
        filter_config={"pages": 1},
    )
    loaded = import_export_configuration(payload)
    assert loaded.pk == existing.pk
    assert loaded.name == "Match"
    assert loaded.manager == "objects"
    assert loaded.filter_config == {}
    assert loaded.config_pdf.template == "<p>s</p>"
    assert ExportDefinition.objects.count() == 1


@pytest.mark.django_db
def test_import_json_admin_post_changelist(client):
    User = get_user_model()
    User.objects.create_superuser("admin", "admin@test.local", "secret")
    ct = ContentType.objects.get_for_model(Book)
    source = ExportDefinition.objects.create(
        name="From file",
        target=ct,
        manager="objects",
        filter_config={},
    )
    ExportConfigPdf.objects.create(export=source, template="", configuration={})
    payload = serialize_export_configuration(source)
    source.delete()
    target = ExportDefinition.objects.create(
        name="From file",
        target=ct,
        manager="objects",
        filter_config={},
    )

    client.login(username="admin", password="secret")
    url = reverse("admin:django_importexport_flow_exportdefinition_import_configuration_json")
    response = client.post(
        url,
        {"file": SimpleUploadedFile("cfg.json", json.dumps(payload).encode("utf-8"))},
        follow=True,
    )
    assert response.status_code == 200
    target.refresh_from_db()
    assert target.name == "From file"
    assert ExportDefinition.objects.count() == 1


@pytest.mark.django_db
def test_import_json_admin_invalid_json(client):
    User = get_user_model()
    User.objects.create_superuser("admin", "admin@test.local", "secret")
    client.login(username="admin", password="secret")
    url = reverse("admin:django_importexport_flow_exportdefinition_import_configuration_json")
    response = client.post(
        url,
        {"file": SimpleUploadedFile("bad.json", b"not json")},
    )
    assert response.status_code == 200
    assert b"Invalid JSON" in response.content or b"JSON" in response.content
