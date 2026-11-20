import json
from datetime import date

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from django_importexport_flow.engine.core.export import (
    DefinitionFilterProxy,
    run_pdf_export,
    run_table_export,
)
from django_importexport_flow.forms import export_format_choices, make_export_form_class
from django_importexport_flow.models import Definition
from tests.sample.models import Book
from tests.support import attach_pdf_export, attach_tabular_export


def _format_keys(choices) -> list[str]:
    keys: list[str] = []
    for item in choices:
        group = item[1]
        if isinstance(group, (list, tuple)) and group and isinstance(group[0], (list, tuple)):
            keys.extend(key for key, _label in group)
        else:
            keys.append(item[0])
    return keys


@pytest.mark.django_db
def test_export_form_filter_request_and_queryset():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export",
        name="Exp",
        target=ct,
        manager="objects",
        filter_config={"pages": 0},
        filter_request={"p": "title"},
    )
    attach_tabular_export(
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
def test_export_passes_typed_request_value_to_manager_method():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export",
        name="Date-aware manager",
        target=ct,
        manager="objects.published_on_or_before",
        manager_method_kwargs_request={
            "published_before": {"kwarg": "cutoff", "type": "date"},
        },
    )
    attach_tabular_export(export=definition, columns=["title"], configuration={})
    Book.objects.create(
        title="Before",
        publication_date=date(2020, 1, 1),
    )
    Book.objects.create(
        title="After",
        publication_date=date(2022, 1, 1),
    )

    FormClass = make_export_form_class(definition)
    form = FormClass(
        {
            "export_format": "json",
            "mm_get_published_before": "2021-01-01",
        }
    )
    assert form.is_valid(), form.errors
    raw, _ct, _ext = run_table_export(definition, form.cleaned_data)
    data = json.loads(raw.decode("utf-8"))

    assert len(data) == 1
    assert data[0][str(Book._meta.get_field("title").verbose_name)] == "Before"

    invalid_form = FormClass(
        {
            "export_format": "json",
            "mm_get_published_before": "not-a-date",
        }
    )
    assert invalid_form.is_valid(), invalid_form.errors
    with pytest.raises(ValidationError):
        run_table_export(definition, invalid_form.cleaned_data)


@pytest.mark.django_db
def test_export_form_filter_request_only_is_optional():
    """filter_request GET params are optional; empty skips that filter in the engine."""
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export",
        name="Exp opt",
        target=ct,
        manager="objects",
        filter_config={"pages": 0},
        filter_request={"p": "title"},
    )
    attach_tabular_export(
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
    definition = Definition.objects.create(
        direction="export",
        name="Shorthand man",
        target=ct,
        manager="objects",
        filter_config={},
        filter_request={},
        filter_mandatory={"author_id": "pages"},
    )
    attach_tabular_export(
        export=definition,
        columns=["title"],
        configuration={},
    )
    FormClass = make_export_form_class(definition)
    assert "fr_get_author_id" in FormClass().fields


@pytest.mark.django_db
def test_export_form_mandatory_get_same_field_name_as_request():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export",
        name="Man only",
        target=ct,
        manager="objects",
        filter_config={},
        filter_request={},
        filter_mandatory={"get": {"n": "pages"}},
    )
    attach_tabular_export(
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
    d = Definition.objects.create(
        direction="export",
        name="P",
        target=ct,
        manager="objects",
        filter_config={"pages": 1},
        filter_request={},
    )
    p = DefinitionFilterProxy(d, {"pages": 1, "title": "x"})
    assert p.filter_config == {"pages": 1, "title": "x"}
    assert p.name == "P"


@pytest.mark.django_db
def test_export_form_offers_pdf_when_a_template_is_set():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export",
        name="PDF choice",
        target=ct,
        manager="objects",
    )
    attach_tabular_export(export=definition, columns=["title"], configuration={})
    assert _format_keys(export_format_choices(definition)) == ["csv", "excel", "json"]
    attach_pdf_export(
        export=definition,
        template="<p>{{ object_list|length }}</p>",
    )
    definition = Definition.objects.get(pk=definition.pk)
    FormClass = make_export_form_class(definition)
    assert _format_keys(FormClass().fields["export_format"].choices) == [
        "pdf",
        "csv",
        "excel",
        "json",
    ]
    Book.objects.create(title="A", pages=1)
    form = FormClass({"export_format": "pdf"})
    assert form.is_valid(), form.errors
    body, content_type, ext = run_pdf_export(definition, form.cleaned_data)
    assert content_type == "application/pdf"
    assert ext == ".pdf"
    assert body.startswith(b"%PDF")


@pytest.mark.django_db
def test_export_form_hides_template_until_pdf_is_enabled():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export", name="No PDF", target=ct, manager="objects"
    )
    attach_tabular_export(export=definition, columns=["title"], configuration={})
    form = make_export_form_class(definition)()
    assert "template_override" not in form.fields
    assert "configuration_overrides" in form.fields


@pytest.mark.django_db
def test_export_form_validates_request_overrides():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export", name="Override form", target=ct, manager="objects"
    )
    attach_tabular_export(export=definition, columns=["title"], configuration={})
    attach_pdf_export(export=definition, template="<p>stored</p>")
    FormClass = make_export_form_class(definition, allow_template_override=True)
    rejected = FormClass(
        {
            "export_format": "csv",
            "template_override": "<p>company</p>",
            "configuration_overrides": '{"format": {"delimiter": ";"}}',
        }
    )
    assert not rejected.is_valid()
    assert "template_override" in rejected.errors

    accepted = FormClass(
        {
            "export_format": "csv",
            "template_override": "",
            "configuration_overrides": '{"format": {"delimiter": ";"}, "hook": {"company_id": 1}}',
        }
    )
    assert accepted.is_valid(), accepted.errors
    assert accepted.cleaned_data["configuration_overrides"]["format"] == {"delimiter": ";"}
    assert accepted.cleaned_data["template_override"] == ""
