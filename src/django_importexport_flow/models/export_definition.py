from __future__ import annotations

import uuid

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _
from django_boosted.models import AuditMixin
from namedid import NamedIDField
from ..managers import ExportManager
from ..engine.core.delegate import resolve_delegate_method
from ..engine.core.validation import (
    annotation_aliases_for_definition,
    resolve_manager_to_queryset,
    validate_export_filter_fields,
    validate_export_filter_manager_disjoint,
)


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
    delegate_method = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Delegate method"),
        help_text=_(
            "Optional dotted path resolved on the target model (e.g. "
            '"objects.run_export" for Model.objects.run_export). When set, the '
            "definition fully delegates to this callable, which receives every "
            "concrete definition field plus the filter payload as keyword arguments "
            "and must return (bytes, content_type, extension)."
        ),
    )
    manager_kwargs_config = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        verbose_name=_("Manager filter (static)"),
        help_text=_(
            "Static ORM kwargs merged via QuerySet.filter() immediately after the "
            "manager path resolves, before filter_config / filter_request."
        ),
    )
    manager_kwargs_request = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        verbose_name=_("Manager request filters"),
        help_text=_(
            "Same shape as request filters: {query_param: orm_lookup}. Values come from "
            "the export form as mg_get_<param> (optional unless listed in manager_kwargs_mandatory)."
        ),
    )
    manager_kwargs_mandatory = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        verbose_name=_("Manager mandatory filters"),
        help_text=_(
            "Same shape as mandatory filters (GET and/or kwargs). Form keys mg_get_* / mg_kw_*."
        ),
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
    max_relation_hops = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Max relation hops"),
        help_text=_(
            "Maximum depth when traversing relations for table columns. "
            "Use 0 for top-level fields only. Leave empty for no limit."
        ),
    )
    exclude_relations = models.ManyToManyField(
        ContentType,
        blank=True,
        related_name="excluded_from_exports",
        verbose_name=_("Exclude relations"),
        help_text=_(
            "Content types whose relations should never be traversed "
            "when building export or import column paths (e.g. auth.User)."
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
        delegate_path = (self.delegate_method or "").strip()
        if delegate_path:
            try:
                resolve_delegate_method(model, delegate_path)
            except ValidationError as exc:
                raise ValidationError({"delegate_method": exc.messages})
            return
        validate_export_filter_manager_disjoint(self)
        validate_export_filter_fields(
            model,
            self.filter_config,
            self.filter_request,
            self.filter_mandatory,
            self.order_by,
            annotation_aliases=annotation_aliases_for_definition(self),
            manager_kwargs_config=self.manager_kwargs_config,
            manager_kwargs_request=self.manager_kwargs_request,
            manager_kwargs_mandatory=self.manager_kwargs_mandatory,
            strict_orm_keys_for_filters=False,
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
