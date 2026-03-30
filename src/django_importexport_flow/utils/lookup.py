"""Resolve :class:`~django_importexport_flow.models.ExportDefinition` / ``ImportDefinition`` by UUID or ``named_id``."""

from __future__ import annotations

import uuid
from typing import TypeVar

from django.db import models

from ..models import ExportDefinition, ImportDefinition

T = TypeVar("T", bound=models.Model)


def _get_definition_by_uuid_or_named_id(model: type[T], key: str) -> T:
    """
    ``key`` is either the primary key UUID (string) or a non-empty ``named_id`` slug.
    UUID is tried first when the string parses as a UUID.
    """
    s = (key or "").strip()
    if not s:
        raise ValueError(f"{model.__name__} key is empty.")
    try:
        u = uuid.UUID(s)
    except ValueError:
        return model.objects.get(named_id=s)
    return model.objects.get(pk=u)


def get_export_definition_by_uuid_or_named_id(key: str) -> ExportDefinition:
    """Load :class:`~django_importexport_flow.models.ExportDefinition` by ``uuid`` or ``named_id``."""
    return _get_definition_by_uuid_or_named_id(ExportDefinition, key)


def get_import_definition_by_uuid_or_named_id(key: str) -> ImportDefinition:
    """Load :class:`~django_importexport_flow.models.ImportDefinition` by ``uuid`` or ``named_id``."""
    return _get_definition_by_uuid_or_named_id(ImportDefinition, key)
