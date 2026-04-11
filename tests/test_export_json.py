import json

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from django_importexport_flow.models import (
    ExportConfigPdf,
    ExportConfigTable,
    ExportDefinition,
)
from django_importexport_flow.utils.helpers import configuration_json_download_filename
from django_importexport_flow.utils.serialization import serialize_export_configuration
from tests.sample.models import Book


def _models_in_export(data: dict) -> set[str]:
    return {o["model"] for o in data["objects"]}


@pytest.mark.django_db
def test_export_json_admin_boost_view(client):
    User = get_user_model()
    User.objects.create_superuser("admin", "admin@test.local", "secret")

    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition.objects.create(
        name="Export test",
        target=ct,
        manager="objects",
        filter_config={},
    )
    ExportConfigPdf.objects.create(
        export=definition,
        template="<html></html>",
        configuration={"a": 1},
    )
    ExportConfigTable.objects.create(
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
    assert data["format_version"] == 1
    objs = data["objects"]
    defn = next(o for o in objs if o["model"] == "django_importexport_flow.exportdefinition")
    assert defn["fields"]["name"] == "Export test"
    assert defn["fields"]["target"] == ct.pk
    pdf = next(o for o in objs if o["model"] == "django_importexport_flow.exportconfigpdf")
    assert pdf["fields"]["template"] == "<html></html>"
    table = next(o for o in objs if o["model"] == "django_importexport_flow.exportconfigtable")
    assert table["fields"]["columns"][0] == "title"
    assert table["fields"]["configuration"]["csv"]["delimiter"] == ";"


@pytest.mark.django_db
def test_serialize_export_configuration_includes_pdf_and_table():
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition.objects.create(
        name="Full",
        target=ct,
        manager="objects",
        filter_config={},
    )
    ExportConfigPdf.objects.create(
        export=definition,
        template="<p>x</p>",
        configuration={"pdf": True},
    )
    ExportConfigTable.objects.create(
        export=definition,
        columns=["id"],
        configuration={"csv": {"delimiter": ","}, "json": {"indent": None}},
    )
    data = serialize_export_configuration(definition)
    assert data["format_version"] == 1
    assert _models_in_export(data) == {
        "django_importexport_flow.exportdefinition",
        "django_importexport_flow.exportconfigpdf",
        "django_importexport_flow.exportconfigtable",
    }
    pdf = next(
        o for o in data["objects"] if o["model"] == "django_importexport_flow.exportconfigpdf"
    )
    assert pdf["fields"]["template"] == "<p>x</p>"
    assert pdf["fields"]["configuration"] == {"pdf": True}
    table = next(
        o for o in data["objects"] if o["model"] == "django_importexport_flow.exportconfigtable"
    )
    assert table["fields"]["columns"][0] == "id"
    assert table["fields"]["configuration"]["csv"]["delimiter"] == ","
    assert table["fields"]["configuration"]["json"]["indent"] is None


@pytest.mark.django_db
def test_serialize_export_configuration_pdf_only():
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition.objects.create(
        name="Pdf only",
        target=ct,
        manager="objects",
        filter_config={},
    )
    ExportConfigPdf.objects.create(
        export=definition,
        template="",
        configuration={},
    )
    data = serialize_export_configuration(definition)
    assert _models_in_export(data) == {
        "django_importexport_flow.exportdefinition",
        "django_importexport_flow.exportconfigpdf",
    }


@pytest.mark.django_db
def test_serialize_export_configuration_table_only():
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition.objects.create(
        name="Table only",
        target=ct,
        manager="objects",
        filter_config={},
    )
    ExportConfigTable.objects.create(
        export=definition,
        columns=[],
        configuration={},
    )
    data = serialize_export_configuration(definition)
    assert _models_in_export(data) == {
        "django_importexport_flow.exportdefinition",
        "django_importexport_flow.exportconfigtable",
    }


@pytest.mark.django_db
def test_serialize_export_configuration_definition_only():
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition.objects.create(
        name="Bare",
        target=ct,
        manager="objects",
        filter_config={},
    )
    data = serialize_export_configuration(definition)
    assert _models_in_export(data) == {"django_importexport_flow.exportdefinition"}


@pytest.mark.django_db
def test_export_json_admin_forbidden_for_anonymous(client):
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition.objects.create(
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
