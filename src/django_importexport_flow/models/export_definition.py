from __future__ import annotations

import uuid

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _
from django_boosted.models import AuditMixin
from namedid import NamedIDField
from ..managers import ExportManager
from ..engine.core.validation import resolve_manager_to_queryset, validate_export_filter_fields


class ExportDefinition(AuditMixin, models.Model):
    uuid = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name=_("UUID"),
    )
    name = models.CharField(max_length=255, verbose_name=_("Name"))
    named_id = NamedIDField(
        source_fields=["name"],
        max_length=255,
    )
    description = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("Description"),
        help_text=_("Optional."),
    )
    target = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="django_importexport_flow_targeted",
        verbose_name=_("Target content type"),
        help_text=_("Listed model."),
    )
    manager = models.CharField(
        max_length=255,
        default="objects.all",
        verbose_name=_("Manager"),
        help_text=_("Default: objects.all"),
    )
    order_by = models.JSONField(
        default=list,
        blank=True,
        null=True,
        verbose_name=_("Order by"),
        help_text=_(
            "List of field names for QuerySet.order_by, e.g. "
            '["title", "-pages"]. Use a leading minus for descending. Empty = model default.'
        ),
    )
    filter_config = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        verbose_name=_("Filter configuration"),
        help_text=_("Static filters. example: {'id': 1}"),
    )
    filter_request = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        verbose_name=_("Request filters"),
        help_text=_(
            "JSON object {query_param: orm_lookup}. Left: name in request.GET (e.g. ?before=…). "
            "Right: Django filter kwarg for the target model (field or field__lookup). "
            'Example: {"before": "recorded_at__lt", "max_id": "id__lt"}. '
            "Do not put ORM lookups on the left or a short alias like “date” on the right."
        ),
    )
    filter_mandatory = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        verbose_name=_("Mandatory filters"),
        help_text=_(
            'Either shorthand GET-only mapping, e.g. {"author_id": "author__id"}, or an '
            "object with “get” and/or “kwargs”: query param names or URL path names → "
            "ORM filter keys. All listed values must be present (request.GET and url "
            'kwargs). Example: {"kwargs": {"group_id": "group_id"}} for …/group/<group_id>/'
        ),
    )

    objects = ExportManager()

    class Meta:
        ordering = ("name", "target")
        verbose_name = _("Export definition")
        verbose_name_plural = _("Export definitions")
        db_table = "django_reportimport_reportdefinition"

    def __str__(self) -> str:
        return str(self.name)

    def clean(self) -> None:
        super().clean()
        if self.target_id is None:
            return
        model = self.target.model_class()
        if model is None:
            return
        validate_export_filter_fields(
            model,
            self.filter_config,
            self.filter_request,
            self.filter_mandatory,
            self.order_by,
        )
        path = (self.manager or "").strip() or "objects.all"
        try:
            resolve_manager_to_queryset(model, path)
        except ValidationError:
            raise
        except Exception as exc:
            raise ValidationError(str(exc)) from exc

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)
