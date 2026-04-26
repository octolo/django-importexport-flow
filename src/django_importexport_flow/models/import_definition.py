from __future__ import annotations

import uuid

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _
from django_boosted.models import AuditMixin
from namedid import NamedIDField

from ..engine.core.delegate import resolve_delegate_method
from ..engine.core.validation import (
    annotation_aliases_for_definition,
    validate_export_filter_fields,
    validate_import_match_fields,
)


class ImportDefinition(AuditMixin, models.Model):
    """
    Table-only report: target model + column exclusions on one row (no ExportConfigTable /
    ExportConfigPdf). Uses the default manager chain ``objects`` (see
    ``ExportDefinition`` for a custom ``manager`` path). Optional ``filter_config``
    / ``filter_request`` narrow the queryset (e.g. tenant id for APIs and import
    scoping).
    """

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
        related_name="django_importexport_flow_import_targeted",
        verbose_name=_("Target content type"),
        help_text=_("Listed model."),
    )
    delegate_method = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Delegate method"),
        help_text=_(
            "Optional dotted path resolved on the target model (e.g. "
            '"objects.run_import" for Model.objects.run_import). When set, the '
            "definition fully delegates to this callable, which receives every "
            "concrete definition field plus the filter payload, the uploaded file "
            "and the user as keyword arguments and must return the same dict shape "
            "as process_import."
        ),
    )
    order_by = models.JSONField(
        default=list,
        blank=True,
        null=True,
        verbose_name=_("Order by"),
        help_text=_(
            "List of field names for QuerySet.order_by, e.g. "
            '["title", "-pages"]. Empty = model default ordering.'
        ),
    )
    filter_config = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        verbose_name=_("Filter configuration"),
        help_text=_("Static queryset filters (e.g. tenant or scope). example: {'tenant_id': 1}"),
    )
    filter_request = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        verbose_name=_("Request filters"),
        help_text=_(
            "JSON {query_param: orm_lookup}. Left = GET name (?before=…); right = filter key "
            'on the target model, e.g. "recorded_at__lt", "id__lt".'
        ),
    )
    filter_mandatory = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        verbose_name=_("Mandatory filters"),
        help_text=_(
            'Optional shorthand GET map, e.g. {"tenant_id": "tenant_id"}, or '
            '{"get": {...}, "kwargs": {...}} for required query params and URL path kwargs.'
        ),
    )
    columns_exclude = models.JSONField(
        default=list,
        blank=True,
        null=True,
        verbose_name=_("Columns exclude"),
        help_text=_(
            "Field paths to omit from import and from the example file. "
            "All other importable columns (top-level scalars and one FK level) "
            "are used. If a path is a forward relation (FK/O2O), all nested paths "
            "under that relation are excluded as well (e.g. author → author.name). "
            "Reverse-expand specs are not part of the default set."
        ),
    )
    exclude_primary_key = models.BooleanField(
        default=True,
        verbose_name=_("Exclude primary key"),
        help_text=_(
            "When enabled, the target model’s primary key field is omitted "
            "from the default column set (in addition to columns exclude)."
        ),
    )
    max_relation_hops = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Max relation hops"),
        help_text=_(
            "Maximum number of relation hops in generated import paths (nested FKs, "
            "M2M slot paths such as tags.0.category.name). Use 0 for no nested "
            "relation paths (top-level columns only). Leave empty for no limit "
            "(a high internal cap applies)."
        ),
        db_column="import_max_relation_hops",
    )
    match_fields = models.JSONField(
        default=list,
        blank=True,
        null=True,
        verbose_name=_("Match fields"),
        help_text=_(
            "Optional list of target model field names used to find existing rows before "
            "updating (e.g. [\"email\"] for users). Empty = always create new rows. "
            "Values from static filters (filter_config) and request filters are added to "
            "the lookup automatically so imports stay scoped. "
            "Each row must provide non-empty values for every match field."
        ),
        db_column="import_match_fields",
    )
    exclude_relations = models.ManyToManyField(
        ContentType,
        blank=True,
        related_name="excluded_from_imports",
        verbose_name=_("Exclude relations"),
        help_text=_(
            "Content types whose relations should never be traversed "
            "when building import column paths (e.g. auth.User)."
        ),
    )
    configuration = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        verbose_name=_("Configuration"),
        help_text=_("Export options."),
    )

    class Meta:
        # Historical table name (ex django-reporting); do not rename without a migration plan.
        db_table = "django_reporting_reportimport"
        ordering = ("name", "target")
        verbose_name = _("Import definition")
        verbose_name_plural = _("Import definitions")

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
        validate_export_filter_fields(
            model,
            self.filter_config,
            self.filter_request,
            self.filter_mandatory,
            self.order_by,
            annotation_aliases=annotation_aliases_for_definition(self),
        )
        validate_import_match_fields(model, self.match_fields)
        if self.max_relation_hops is not None and self.max_relation_hops < 0:
            raise ValidationError(
                {
                    "max_relation_hops": _(
                        "Must be 0 or greater, or leave empty for no limit."
                    )
                }
            )

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)
