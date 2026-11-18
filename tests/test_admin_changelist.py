"""Changelist columns for export and import definitions."""

from __future__ import annotations

import pytest
from django.contrib.contenttypes.models import ContentType

from django_importexport_flow.admin.definition import ExportDefinitionAdmin
from django_importexport_flow.admin.mixins import (
    columns_column,
    definition_heading,
    filter_column,
    manager_filter_column,
    match_column,
    model_column,
    output_column,
)
from django_importexport_flow.models import Definition
from tests.sample.models import Book
from tests.support import attach_pdf_export, attach_tabular_export


@pytest.mark.django_db
def test_export_changelist_splits_model_output_and_filters():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export",
        name="Shelf",
        target=ct,
        manager="objects",
        filter_config={"price__gte": 0},
        filter_mandatory={"get": {"min_pages": "pages__gte"}},
        manager_kwargs_config={"pages__gte": 1},
    )
    attach_tabular_export(export=definition, columns=["title"], configuration={})
    attach_pdf_export(export=definition, template="<p>{{ object_list }}</p>")
    definition = Definition.objects.select_related("target").get(pk=definition.pk)
    admin = ExportDefinitionAdmin
    heading = definition_heading(admin, definition)
    model = model_column(admin, definition, detail="objects")
    output = output_column(admin, definition)
    filters = filter_column(admin, definition)
    manager_filters = manager_filter_column(admin, definition)
    assert definition.named_id in heading
    assert heading.index(definition.named_id) < heading.index("Shelf")
    assert "sample.book" in model
    assert "objects" in model
    assert "Document" in output
    assert "Spreadsheet" in output
    assert "Structured data" in output
    assert "Spreadsheet:" not in output
    assert "Document:" not in output
    assert "<svg" in output
    assert "CSV/XLSX" in output
    assert "PDF" in output
    assert "Config" in filters
    assert "Mandatory" in filters
    assert "Config" in manager_filters
    assert str(definition.uuid) not in heading


@pytest.mark.django_db
def test_import_changelist_splits_match_and_columns():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="import",
        name="Update pages",
        target=ct,
        match_fields=["title"],
        filter_request={"before": "recorded_at__lt"},
        columns_exclude=["price"],
        max_relation_hops=2,
        exclude_primary_key=True,
    )
    admin = ExportDefinitionAdmin
    heading = definition_heading(admin, definition)
    model = model_column(admin, definition)
    match = match_column(admin, definition)
    filters = filter_column(admin, definition)
    columns = columns_column(admin, definition)
    assert definition.named_id in heading
    assert "Update pages" in heading
    assert "sample.book" in model
    assert "title" in match
    assert "PK excluded" in match
    assert "Request" in filters
    assert "Excluded 1" in columns
    assert "Hops 2" in columns
