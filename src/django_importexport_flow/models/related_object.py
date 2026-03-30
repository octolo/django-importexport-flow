"""Optional generic links from import / export audit rows to any model (tenant, project, …)."""

from __future__ import annotations

from typing import Any

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _


class BaseRequestRelatedObject(models.Model):
    """Abstract: ContentType + object id + GenericFK + stored ``str`` for deleted targets."""

    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        verbose_name=_("Content type"),
        help_text=_("Model of the related instance."),
    )
    object_id = models.CharField(
        max_length=64,
        verbose_name=_("Object id"),
        help_text=_("Primary key as string (integer or UUID)."),
    )
    content_object = GenericForeignKey("content_type", "object_id")
    object_str = models.CharField(
        max_length=500,
        blank=True,
        default="",
        editable=False,
        verbose_name=_("Object representation"),
        help_text=_("Snapshot when saved; kept if the related row is deleted."),
    )

    class Meta:
        abstract = True
        ordering = ("pk",)

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.content_type_id and self.object_id:
            try:
                obj = self.content_object
                if obj is not None:
                    self.object_str = str(obj)[:500]
            except Exception:
                pass
        super().save(*args, **kwargs)


class ImportRequestRelatedObject(BaseRequestRelatedObject):
    import_request = models.ForeignKey(
        "ImportRequest",
        on_delete=models.CASCADE,
        related_name="related_object_links",
        verbose_name=_("Import request"),
    )

    class Meta:
        verbose_name = _("Import request related object")
        verbose_name_plural = _("Import request related objects")


class ExportRequestRelatedObject(BaseRequestRelatedObject):
    export_request = models.ForeignKey(
        "ExportRequest",
        on_delete=models.CASCADE,
        related_name="related_object_links",
        verbose_name=_("Export request"),
    )

    class Meta:
        verbose_name = _("Export request related object")
        verbose_name_plural = _("Export request related objects")
