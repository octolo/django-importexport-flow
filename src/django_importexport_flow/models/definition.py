from __future__ import annotations

import uuid
from typing import ClassVar

from django import VERSION as DJANGO_VERSION
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from django_boosted.models import AuditMixin
from namedid import NamedIDField

from ..engine.core.validation import (
    annotation_aliases_for_definition,
    resolve_manager_to_queryset,
    validate_export_filter_fields,
    validate_export_filter_manager_disjoint,
    validate_import_match_fields,
)
from ..managers import DefinitionManager, ExportDefinitionManager, ImportDefinitionManager


def _filled(value: object) -> bool:
    return isinstance(value, (dict, list)) and bool(value)


def _direction_valid_constraint() -> models.CheckConstraint:
    """Django 5.0 only accepts ``check=``; 5.1+ prefer ``condition=``."""
    expression = Q(direction__in=["export", "import"])
    name = "definition_direction_valid"
    if DJANGO_VERSION >= (5, 1):
        return models.CheckConstraint(condition=expression, name=name)
    return models.CheckConstraint(check=expression, name=name)  # type: ignore[call-arg]


class Definition(AuditMixin, models.Model):
    """One import or export definition. Direction selects which policies apply."""

    class Direction(models.TextChoices):
        EXPORT = "export", _("Export")
        IMPORT = "import", _("Import")

    uuid = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name=_("UUID"),
    )
    direction = models.CharField(
        max_length=16,
        choices=Direction.choices,
        verbose_name=_("Direction"),
    )
    name = models.CharField(max_length=255, verbose_name=_("Name"))
    named_id = NamedIDField(
        source_fields=["name"],
        max_length=255,
        unique=False,
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
        related_name="django_importexport_flow_definitions",
        verbose_name=_("Target content type"),
        help_text=_("Listed model."),
    )
    manager = models.CharField(
        max_length=255,
        default="objects.all",
        verbose_name=_("Manager"),
        help_text=_("Export only. Default: objects.all"),
    )
    manager_kwargs_config = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        verbose_name=_("Manager filter (static)"),
        help_text=_("Export only. Static ORM kwargs applied after the manager resolves."),
    )
    manager_kwargs_request = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        verbose_name=_("Manager request filters"),
        help_text=_("Export only. {query_param: orm_lookup} read from mg_get_<param>."),
    )
    manager_kwargs_mandatory = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        verbose_name=_("Manager mandatory filters"),
        help_text=_("Export only. Required manager filters (mg_get_* / mg_kw_*)."),
    )
    order_by = models.JSONField(
        default=list,
        blank=True,
        null=True,
        verbose_name=_("Order by"),
        help_text=_('List of field names for QuerySet.order_by, e.g. ["title", "-pages"].'),
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
        help_text=_("JSON object {query_param: orm_lookup}."),
    )
    filter_mandatory = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        verbose_name=_("Mandatory filters"),
        help_text=_("Required GET parameters and URL kwargs mapped to ORM lookups."),
    )
    columns_exclude = models.JSONField(
        default=list,
        blank=True,
        null=True,
        verbose_name=_("Columns exclude"),
        help_text=_("Import only. Field paths omitted from import and the example file."),
    )
    exclude_primary_key = models.BooleanField(
        default=True,
        verbose_name=_("Exclude primary key"),
        help_text=_("Import only. Omit the target primary key from the default column set."),
    )
    match_fields = models.JSONField(
        default=list,
        blank=True,
        null=True,
        verbose_name=_("Match fields"),
        help_text=_("Import only. Fields used to find an existing row before update."),
    )
    max_relation_hops = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Max relation hops"),
        help_text=_("Maximum relation depth for column paths. Empty means no limit."),
    )
    exclude_relations = models.ManyToManyField(
        ContentType,
        blank=True,
        related_name="excluded_from_definitions",
        verbose_name=_("Exclude relations"),
        help_text=_("Content types whose relations are never traversed."),
    )

    objects = DefinitionManager()

    class Meta:
        ordering = ("direction", "name", "target")
        verbose_name = _("Definition")
        verbose_name_plural = _("Definitions")
        constraints = (
            _direction_valid_constraint(),
            models.UniqueConstraint(
                fields=["direction", "named_id"],
                name="definition_direction_named_id_uniq",
            ),
        )

    def __str__(self) -> str:
        return str(self.name)

    def clean(self) -> None:
        super().clean()
        self._clean_unused_direction_fields()
        target = self.target
        if target is None:
            return
        model = target.model_class()
        if model is None:
            return
        if self.direction == self.Direction.EXPORT:
            self._clean_export(model)
        elif self.direction == self.Direction.IMPORT:
            self._clean_import(model)

    def _clean_unused_direction_fields(self) -> None:
        if self.direction == self.Direction.EXPORT and (
            _filled(self.columns_exclude) or _filled(self.match_fields)
        ):
            raise ValidationError(_("Import policies cannot be set on an export definition."))
        if self.direction == self.Direction.IMPORT and any(
            _filled(getattr(self, name))
            for name in (
                "manager_kwargs_config",
                "manager_kwargs_request",
                "manager_kwargs_mandatory",
            )
        ):
            raise ValidationError(
                _("Export manager filters cannot be set on an import definition.")
            )

    def _clean_export(self, model: type[models.Model]) -> None:
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

    def _clean_import(self, model: type[models.Model]) -> None:
        validate_export_filter_fields(
            model,
            self.filter_config,
            self.filter_request,
            self.filter_mandatory,
            self.order_by,
            annotation_aliases=annotation_aliases_for_definition(self),
        )
        validate_import_match_fields(model, self.match_fields)

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


class _DirectionProxyMixin:
    direction_value = ""
    direction: str

    def full_clean(self, *args, **kwargs) -> None:
        self.direction = self.direction_value
        super().full_clean(*args, **kwargs)  # type: ignore[misc]

    def clean(self) -> None:
        self.direction = self.direction_value
        super().clean()  # type: ignore[misc]


class ExportDefinition(_DirectionProxyMixin, Definition):
    direction_value = str(Definition.Direction.EXPORT)
    objects: ClassVar[ExportDefinitionManager] = ExportDefinitionManager()

    class Meta:
        proxy = True
        verbose_name = _("Export definition")
        verbose_name_plural = _("Export definitions")


class ImportDefinition(_DirectionProxyMixin, Definition):
    direction_value = str(Definition.Direction.IMPORT)
    objects: ClassVar[ImportDefinitionManager] = ImportDefinitionManager()

    class Meta:
        proxy = True
        verbose_name = _("Import definition")
        verbose_name_plural = _("Import definitions")
