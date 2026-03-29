import json

import pytest
from django.contrib.contenttypes.models import ContentType

from django_importexport_flow.utils.export import DefinitionFilterProxy, run_table_export
from django_importexport_flow.forms import make_export_form_class
from django_importexport_flow.models import ExportConfigTable, ExportDefinition
from tests.sample.models import Book


@pytest.mark.django_db
def test_export_form_filter_request_and_queryset():
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition.objects.create(
        name="Exp",
        target=ct,
        manager="objects",
        filter_config={"pages": 0},
        filter_request={"p": "title"},
    )
    ExportConfigTable.objects.create(
        export=definition,
        columns=["title"],
        configuration={},
    )
    Book.objects.create(title="X", pages=0)
    FormClass = make_export_form_class(definition)
    form = FormClass(
        {
            "export_format": "json",
            "fr_get_p": "X",
        }
    )
    assert form.is_valid(), form.errors
    raw, _ct, _ext = run_table_export(definition, form.cleaned_data)
    data = json.loads(raw.decode("utf-8"))
    assert len(data) == 1
    assert data[0][str(Book._meta.get_field("title").verbose_name)] == "X"


@pytest.mark.django_db
def test_export_form_filter_request_only_is_optional():
    """filter_request GET params are optional; empty skips that filter in the engine."""
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition.objects.create(
        name="Exp opt",
        target=ct,
        manager="objects",
        filter_config={"pages": 0},
        filter_request={"p": "title"},
    )
    ExportConfigTable.objects.create(
        export=definition,
        columns=["title"],
        configuration={},
    )
    Book.objects.create(title="A", pages=0)
    Book.objects.create(title="B", pages=0)
    FormClass = make_export_form_class(definition)
    form = FormClass({"export_format": "json", "fr_get_p": ""})
    assert form.is_valid(), form.errors
    raw, _ct, _ext = run_table_export(definition, form.cleaned_data)
    data = json.loads(raw.decode("utf-8"))
    assert len(data) == 2


@pytest.mark.django_db
def test_export_form_accepts_filter_mandatory_shorthand_flat_get_map():
    """filter_mandatory without get/kwargs keys: whole dict is mandatory GET params."""
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition.objects.create(
        name="Shorthand man",
        target=ct,
        manager="objects",
        filter_config={},
        filter_request={},
        filter_mandatory={"author_id": "pages"},
    )
    ExportConfigTable.objects.create(
        export=definition,
        columns=["title"],
        configuration={},
    )
    FormClass = make_export_form_class(definition)
    assert "fr_get_author_id" in FormClass().fields


@pytest.mark.django_db
def test_export_form_mandatory_get_same_field_name_as_request():
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition.objects.create(
        name="Man only",
        target=ct,
        manager="objects",
        filter_config={},
        filter_request={},
        filter_mandatory={"get": {"n": "pages"}},
    )
    ExportConfigTable.objects.create(
        export=definition,
        columns=["title"],
        configuration={},
    )
    Book.objects.create(title="A", pages=3)
    FormClass = make_export_form_class(definition)
    assert "fr_get_n" in FormClass().fields
    form = FormClass({"export_format": "json", "fr_get_n": "3"})
    assert form.is_valid(), form.errors


@pytest.mark.django_db
def test_definition_filter_proxy_merges_config():
    ct = ContentType.objects.get_for_model(Book)
    d = ExportDefinition.objects.create(
        name="P",
        target=ct,
        manager="objects",
        filter_config={"pages": 1},
        filter_request={},
    )
    p = DefinitionFilterProxy(d, {"pages": 1, "title": "x"})
    assert p.filter_config == {"pages": 1, "title": "x"}
    assert p.name == "P"
