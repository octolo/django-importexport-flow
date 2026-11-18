import json

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from django_importexport_flow.models import (
    Definition,
)
from django_importexport_flow.utils.serialization import (
    import_export_configuration,
    serialize_export_configuration,
)
from tests.sample.models import Book
from tests.support import attach_pdf_export, attach_tabular_export


@pytest.mark.django_db
def test_import_export_configuration_roundtrip():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export",
        name="Roundtrip",
        target=ct,
        manager="objects",
        filter_config={},
    )
    attach_pdf_export(
        export=definition,
        template="<html>a</html>",
        configuration={"x": 1},
    )
    attach_tabular_export(
        export=definition,
        columns=["title"],
        configuration={"json": {"indent": 4}},
    )
    payload = serialize_export_configuration(definition)
    Definition.objects.all().delete()
    assert Definition.objects.count() == 0

    loaded = import_export_configuration(payload)
    assert loaded.name == "Roundtrip"
    assert loaded.target_id == ct.id
    from django_importexport_flow.engine.core.formats import get_export_category, get_export_config

    assert get_export_config(loaded, "pdf").template == "<html>a</html>"
    assert get_export_category(loaded, "json").columns[0] == "title"
    assert get_export_config(loaded, "json").configuration["indent"] == 4


@pytest.mark.django_db
def test_import_export_configuration_replaces_when_name_exists():
    ct = ContentType.objects.get_for_model(Book)
    source = Definition.objects.create(
        direction="export",
        name="Match",
        target=ct,
        manager="objects",
        filter_config={},
    )
    attach_pdf_export(export=source, template="<p>s</p>", configuration={"k": 1})
    payload = serialize_export_configuration(source)
    source.delete()
    existing = Definition.objects.create(
        direction="export",
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
    from django_importexport_flow.engine.core.formats import get_export_config

    assert get_export_config(loaded, "pdf").template == "<p>s</p>"
    assert Definition.objects.count() == 1


@pytest.mark.django_db
def test_import_json_admin_post_changelist(client):
    User = get_user_model()
    User.objects.create_superuser("admin", "admin@test.local", "secret")
    ct = ContentType.objects.get_for_model(Book)
    source = Definition.objects.create(
        direction="export",
        name="From file",
        target=ct,
        manager="objects",
        filter_config={},
    )
    attach_pdf_export(export=source, template="", configuration={})
    payload = serialize_export_configuration(source)
    source.delete()
    target = Definition.objects.create(
        direction="export",
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
    assert Definition.objects.count() == 1


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
