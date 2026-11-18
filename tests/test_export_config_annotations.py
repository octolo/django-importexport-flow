"""Export: annotation names in table ``configuration`` validate order_by; columns are not schema-checked."""

from __future__ import annotations

import pytest
from django.contrib.contenttypes.models import ContentType

from django_importexport_flow.engine import ExportTableEngine
from django_importexport_flow.models import Definition
from django_importexport_flow.utils.helpers import resolve_column_header
from tests.sample.models import Author, Book
from tests.support import attach_tabular_export


@pytest.mark.django_db
def test_table_columns_allow_unknown_paths_without_validation():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export",
        name="Any column paths",
        target=ct,
        manager="objects",
        filter_config={},
    )
    attach_tabular_export(
        export=definition,
        columns=["totally_fake_field", "title"],
        configuration={},
    )


@pytest.mark.django_db
def test_export_configuration_column_label_in_config_json():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export",
        name="Label overrides",
        target=ct,
        manager="objects",
        filter_config={},
    )
    attach_tabular_export(
        export=definition,
        columns=["totally_fake_field", "title"],
        configuration={"totally_fake_field_label": "Libellé personnalisé"},
    )
    Book.objects.create(title="T", pages=1)
    engine = ExportTableEngine(definition)
    title_v = str(Book._meta.get_field("title").verbose_name)
    assert engine.get_headers() == ["Libellé personnalisé", title_v]


@pytest.mark.django_db
def test_resolve_column_header_uses_configuration_override():
    assert (
        resolve_column_header(
            Book,
            "my_annotation",
            configuration={"my_annotation_label": "Ann display"},
        )
        == "Ann display"
    )


@pytest.mark.django_db
def test_export_definition_order_by_accepts_annotation_from_table_configuration():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export",
        name="Order by ann",
        target=ct,
        manager="objects",
        filter_config={},
        order_by=[],
    )
    attach_tabular_export(
        export=definition,
        columns=["title"],
        configuration={"annotation_columns": ["book_count"]},
    )
    definition.order_by = ["-book_count"]
    definition.full_clean()
    definition.save(update_fields=["order_by"])


@pytest.mark.django_db
def test_table_columns_allow_property_on_target_model():
    ct = ContentType.objects.get_for_model(Author)
    definition = Definition.objects.create(
        direction="export",
        name="Author props",
        target=ct,
        manager="objects",
        filter_config={},
    )
    attach_tabular_export(
        export=definition,
        columns=["name", "name_upper"],
        configuration={},
    )


@pytest.mark.django_db
def test_table_columns_allow_property_on_related_model():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export",
        name="Book author prop",
        target=ct,
        manager="objects",
        filter_config={},
    )
    attach_tabular_export(
        export=definition,
        columns=["title", "author.name_upper"],
        configuration={},
    )


@pytest.mark.django_db
def test_table_columns_allow_jsonfield_subpath():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export",
        name="Book json subpath",
        target=ct,
        manager="objects",
        filter_config={},
    )
    attach_tabular_export(
        export=definition,
        columns=["title", "metadata.lang"],
        configuration={},
    )
