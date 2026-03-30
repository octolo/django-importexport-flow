"""Tests for uuid / named_id resolution helpers."""

import uuid

import pytest
from django.contrib.contenttypes.models import ContentType

from django_importexport_flow.models import ExportDefinition, ImportDefinition
from django_importexport_flow.utils.lookup import (
    get_export_definition_by_uuid_or_named_id,
    get_import_definition_by_uuid_or_named_id,
)
from tests.sample.models import Author, Book


@pytest.mark.django_db
def test_export_definition_by_uuid_and_named_id():
    ct = ContentType.objects.get_for_model(Book)
    obj = ExportDefinition.objects.create(
        name="Books Export",
        target=ct,
        manager="objects",
        filter_config={},
    )
    assert get_export_definition_by_uuid_or_named_id(str(obj.uuid)).pk == obj.pk
    assert get_export_definition_by_uuid_or_named_id("  books-export  ").pk == obj.pk


@pytest.mark.django_db
def test_import_definition_by_uuid_and_named_id():
    ct = ContentType.objects.get_for_model(Author)
    obj = ImportDefinition.objects.create(
        name="Authors Import",
        target=ct,
        filter_config={},
    )
    assert get_import_definition_by_uuid_or_named_id(str(obj.uuid)).pk == obj.pk
    assert get_import_definition_by_uuid_or_named_id("authors-import").pk == obj.pk


@pytest.mark.django_db
def test_export_empty_key_raises():
    with pytest.raises(ValueError, match="empty"):
        get_export_definition_by_uuid_or_named_id("   ")


@pytest.mark.django_db
def test_export_uuid_string_resolves_even_if_named_id_collision_unlikely():
    ct = ContentType.objects.get_for_model(Book)
    u = uuid.uuid4()
    obj = ExportDefinition.objects.create(
        name="By UUID",
        target=ct,
        manager="objects",
        filter_config={},
        pk=u,
    )
    assert get_export_definition_by_uuid_or_named_id(str(u)).pk == obj.pk
