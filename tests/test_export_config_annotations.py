"""Export definitions: annotation_columns validate order_by; table columns are not schema-checked."""

from __future__ import annotations

import pytest
from django.contrib.contenttypes.models import ContentType

from django_importexport_flow.engine import ExportTableEngine
from django_importexport_flow.models import ExportConfigTable, ExportDefinition
from django_importexport_flow.utils.helpers import resolve_table_column_label
from tests.sample.models import Author, Book


@pytest.mark.django_db
def test_table_columns_allow_unknown_paths_without_validation():
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition.objects.create(
        name="Any column paths",
        target=ct,
        manager="objects",
        filter_config={},
    )
    cfg = ExportConfigTable(
        export=definition,
        columns=["totally_fake_field", "title"],
        configuration={},
    )
    cfg.full_clean()
    cfg.save()


@pytest.mark.django_db
def test_export_configuration_column_label_in_config_json():
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition.objects.create(
        name="Label overrides",
        target=ct,
        manager="objects",
        filter_config={},
    )
    ExportConfigTable.objects.create(
        export=definition,
        columns=["totally_fake_field", "title"],
        configuration={"totally_fake_field_label": "Libellé personnalisé"},
    )
    Book.objects.create(title="T", pages=1)
    engine = ExportTableEngine(definition)
    title_v = str(Book._meta.get_field("title").verbose_name)
    assert engine.get_headers() == ["Libellé personnalisé", title_v]


def test_resolve_table_column_label_uses_configuration_override():
    assert (
        resolve_table_column_label(
            Book,
            "my_annotation",
            configuration={"my_annotation_label": "Ann display"},
        )
        == "Ann display"
    )


@pytest.mark.django_db
def test_export_definition_order_by_accepts_annotation_columns_field():
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition(
        name="Order by ann",
        target=ct,
        manager="objects",
        filter_config={},
        order_by=["-book_count"],
        annotation_columns=["book_count"],
    )
    definition.full_clean()


@pytest.mark.django_db
def test_table_columns_allow_property_on_target_model():
    ct = ContentType.objects.get_for_model(Author)
    definition = ExportDefinition.objects.create(
        name="Author props",
        target=ct,
        manager="objects",
        filter_config={},
    )
    cfg = ExportConfigTable(
        export=definition,
        columns=["name", "name_upper"],
        configuration={},
    )
    cfg.full_clean()


@pytest.mark.django_db
def test_table_columns_allow_property_on_related_model():
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition.objects.create(
        name="Book author prop",
        target=ct,
        manager="objects",
        filter_config={},
    )
    cfg = ExportConfigTable(
        export=definition,
        columns=["title", "author.name_upper"],
        configuration={},
    )
    cfg.full_clean()


@pytest.mark.django_db
def test_table_columns_allow_jsonfield_subpath():
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition.objects.create(
        name="Book json subpath",
        target=ct,
        manager="objects",
        filter_config={},
    )
    cfg = ExportConfigTable(
        export=definition,
        columns=["title", "metadata.lang"],
        configuration={},
    )
    cfg.full_clean()
