"""In-memory import preview rows (used with :class:`virtualqueryset.queryset.VirtualQuerySet`)."""

from __future__ import annotations

from django.db import models


class DataPreviewRow(models.Model):
    """
    Abstract base for dynamic preview model classes built from import column paths.

    Not stored in the database; concrete subclasses are created at runtime with
    :func:`~django_importexport_flow.admin.import_definition.build_import_preview_model_class`.
    """

    class Meta:
        abstract = True
