import json

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from django_importexport_flow.models import (
    ColumnTranslation,
    Definition,
)
from django_importexport_flow.utils.serialization import (
    import_export_configuration,
    import_import_definition,
    serialize_export_configuration,
    serialize_import_definition,
)
from tests.sample.models import Author, Book
from tests.support import attach_pdf_export, attach_tabular_export


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("direction", "serialize", "load"),
    [
        ("export", serialize_export_configuration, import_export_configuration),
        ("import", serialize_import_definition, import_import_definition),
    ],
)
def test_column_translations_roundtrip(direction, serialize, load):
    target = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(direction=direction, name="Books", target=target)
    ColumnTranslation.objects.create(
        content_type=target, path="title", language="fr", label="Titre"
    )
    ColumnTranslation.objects.create(
        content_type=ContentType.objects.get_for_model(Author),
        path="name",
        language="fr",
        label="Nom",
    )

    payload = serialize(definition, include_column_translations=True)
    assert "column_translations" not in serialize(definition)
    assert payload["objects"][0]["fields"]["target"] == list(target.natural_key())
    assert payload["column_translations"] == [{"path": "title", "language": "fr", "label": "Titre"}]
    definition.delete()
    ColumnTranslation.objects.filter(content_type=target).delete()

    restored = load(payload)
    load(payload)

    assert restored.target == target
    assert ColumnTranslation.objects.get(content_type=target, path="title").label == "Titre"


@pytest.mark.django_db
def test_column_translation_conflict_rolls_back_configuration_import():
    target = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(direction="import", name="Books", target=target)
    ColumnTranslation.objects.create(
        content_type=target, path="title", language="fr", label="Titre local"
    )
    payload = serialize_import_definition(definition, include_column_translations=True)
    payload["objects"][0]["fields"]["description"] = "Incoming description"
    payload["column_translations"] = [
        {"path": "pages", "language": "fr", "label": "Pages"},
        {"path": "title", "language": " FR ", "label": "Titre distant"},
    ]

    with pytest.raises(ValueError, match=r"title \[fr\]"):
        import_import_definition(payload)

    definition.refresh_from_db()
    assert definition.description != "Incoming description"
    assert list(
        ColumnTranslation.objects.filter(content_type=target).values_list("path", "label")
    ) == [("title", "Titre local")]


@pytest.mark.django_db
def test_configuration_admin_download_and_translation_import_permission(client):
    user_model = get_user_model()
    admin = user_model.objects.create_superuser("admin", "admin@test.local", "secret")
    editor = user_model.objects.create_user("editor", is_staff=True)
    editor.user_permissions.add(
        Permission.objects.get(
            content_type__app_label="django_importexport_flow", codename="change_exportdefinition"
        )
    )
    target = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(direction="export", name="Books", target=target)
    ColumnTranslation.objects.create(
        content_type=target, path="title", language="fr", label="Titre"
    )
    download = reverse(
        "admin:django_importexport_flow_exportdefinition_export_configuration_with_translations_json",
        args=[definition.pk],
    )
    client.force_login(admin)

    response = client.get(download)

    assert response.status_code == 200
    payload = response.content
    assert json.loads(payload)["column_translations"][0]["label"] == "Titre"
    ColumnTranslation.objects.all().delete()
    client.force_login(editor)
    upload = reverse("admin:django_importexport_flow_exportdefinition_import_configuration_json")

    response = client.post(upload, {"file": SimpleUploadedFile("cfg.json", payload)})

    assert response.status_code == 403
    assert not ColumnTranslation.objects.exists()
    editor.user_permissions.add(
        Permission.objects.get(
            content_type__app_label="django_importexport_flow", codename="add_columntranslation"
        )
    )

    response = client.post(upload, {"file": SimpleUploadedFile("cfg.json", payload)})

    assert response.status_code == 302
    assert ColumnTranslation.objects.get(content_type=target).label == "Titre"


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
