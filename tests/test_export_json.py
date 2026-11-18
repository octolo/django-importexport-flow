import json

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from django_importexport_flow.models import (
    Definition,
)
from django_importexport_flow.utils.helpers import configuration_json_download_filename
from django_importexport_flow.utils.serialization import serialize_export_configuration
from tests.sample.models import Book
from tests.support import attach_pdf_export, attach_tabular_export


def _models_in_export(data: dict) -> set[str]:
    return {o["model"] for o in data["objects"]}


def _by_format(data: dict, format_key: str) -> dict:
    return next(
        obj
        for obj in data["objects"]
        if obj["model"] == "django_importexport_flow.formatconfig"
        and obj["fields"]["format_key"] == format_key
    )


def _by_category(data: dict, category_key: str) -> dict:
    return next(
        obj
        for obj in data["objects"]
        if obj["model"] == "django_importexport_flow.categoryconfig"
        and obj["fields"]["category_key"] == category_key
    )


@pytest.mark.django_db
def test_export_json_admin_boost_view(client):
    User = get_user_model()
    User.objects.create_superuser("admin", "admin@test.local", "secret")

    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export",
        name="Export test",
        target=ct,
        manager="objects",
        filter_config={},
    )
    attach_pdf_export(
        export=definition,
        template="<html></html>",
        configuration={"a": 1},
    )
    attach_tabular_export(
        export=definition,
        columns=["title"],
        configuration={"csv": {"delimiter": ";"}},
    )

    client.login(username="admin", password="secret")

    url = reverse(
        "admin:django_importexport_flow_exportdefinition_export_configuration_json",
        args=[definition.pk],
    )
    r = client.get(url)
    assert r.status_code == 200
    assert r["Content-Type"].startswith("application/json")
    definition.refresh_from_db()
    assert configuration_json_download_filename(definition) in (r.get("Content-Disposition") or "")
    data = json.loads(r.content)
    assert data["format_version"] == 2
    objs = data["objects"]
    defn = next(o for o in objs if o["model"] == "django_importexport_flow.definition")
    assert defn["fields"]["name"] == "Export test"
    assert defn["fields"]["target"] == ct.pk
    pdf = _by_format(data, "pdf")
    assert pdf["fields"]["template"] == "<html></html>"
    sheet = _by_category(data, "spreadsheet")
    assert sheet["fields"]["columns"][0] == "title"
    csv = _by_format(data, "csv")
    assert csv["fields"]["configuration"]["delimiter"] == ";"


@pytest.mark.django_db
def test_serialize_export_configuration_includes_pdf_and_table():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export",
        name="Full",
        target=ct,
        manager="objects",
        filter_config={},
    )
    attach_pdf_export(
        export=definition,
        template="<p>x</p>",
        configuration={"pdf": True},
    )
    attach_tabular_export(
        export=definition,
        columns=["id"],
        configuration={"csv": {"delimiter": ","}, "json": {"indent": None}},
    )
    data = serialize_export_configuration(definition)
    assert data["format_version"] == 2
    assert _models_in_export(data) == {
        "django_importexport_flow.definition",
        "django_importexport_flow.categoryconfig",
        "django_importexport_flow.formatconfig",
    }
    pdf = _by_format(data, "pdf")
    assert pdf["fields"]["template"] == "<p>x</p>"
    assert pdf["fields"]["configuration"] == {"pdf": True}
    sheet = _by_category(data, "spreadsheet")
    assert sheet["fields"]["columns"][0] == "id"
    csv = _by_format(data, "csv")
    assert csv["fields"]["configuration"]["delimiter"] == ","
    exported_json = _by_format(data, "json")
    assert exported_json["fields"]["configuration"]["indent"] is None


@pytest.mark.django_db
def test_serialize_export_configuration_pdf_only():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export",
        name="Pdf only",
        target=ct,
        manager="objects",
        filter_config={},
    )
    attach_pdf_export(
        export=definition,
        template="",
        configuration={},
    )
    data = serialize_export_configuration(definition)
    assert _models_in_export(data) == {
        "django_importexport_flow.definition",
        "django_importexport_flow.categoryconfig",
        "django_importexport_flow.formatconfig",
    }


@pytest.mark.django_db
def test_serialize_export_configuration_table_only():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export",
        name="Table only",
        target=ct,
        manager="objects",
        filter_config={},
    )
    attach_tabular_export(
        export=definition,
        columns=[],
        configuration={},
    )
    data = serialize_export_configuration(definition)
    assert _models_in_export(data) == {
        "django_importexport_flow.definition",
        "django_importexport_flow.categoryconfig",
        "django_importexport_flow.formatconfig",
    }


@pytest.mark.django_db
def test_serialize_export_configuration_definition_only():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export",
        name="Bare",
        target=ct,
        manager="objects",
        filter_config={},
    )
    data = serialize_export_configuration(definition)
    assert _models_in_export(data) == {"django_importexport_flow.definition"}


@pytest.mark.django_db
def test_export_json_admin_forbidden_for_anonymous(client):
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export",
        name="X",
        target=ct,
        manager="objects",
        filter_config={},
    )
    url = reverse(
        "admin:django_importexport_flow_exportdefinition_export_configuration_json",
        args=[definition.pk],
    )
    r = client.get(url)
    assert r.status_code == 302
