"""Resolve a :class:`~django_importexport_flow.models.Definition` by UUID or ``named_id``."""

from __future__ import annotations

import uuid

from django.db.models import QuerySet

from ..models import Definition


def _get_definition_by_uuid_or_named_id(queryset: QuerySet, key: str) -> Definition:
    """
    ``key`` is either the primary key UUID (string) or a non-empty ``named_id`` slug.
    UUID is tried first when the string parses as a UUID.
    """
    s = (key or "").strip()
    if not s:
        raise ValueError("Definition key is empty.")
    try:
        parsed = uuid.UUID(s)
    except ValueError:
        return queryset.get(named_id=s)
    return queryset.get(pk=parsed)


def get_export_definition_by_uuid_or_named_id(key: str) -> Definition:
    """Load an export definition by ``uuid`` or ``named_id``."""
    return _get_definition_by_uuid_or_named_id(Definition.objects.exports(), key)


def get_import_definition_by_uuid_or_named_id(key: str) -> Definition:
    """Load an import definition by ``uuid`` or ``named_id``."""
    return _get_definition_by_uuid_or_named_id(Definition.objects.imports(), key)
