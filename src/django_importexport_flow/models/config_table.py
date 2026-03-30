from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from ..engine.core.validation import validate_export_column_specs
from .export_definition import ExportDefinition


class ExportConfigTable(models.Model):
    export = models.OneToOneField(
        ExportDefinition,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="config_table",
        verbose_name=_("Export"),
    )
    columns = models.JSONField(
        default=list,
        blank=True,
        null=True,
        verbose_name=_("Columns"),
        help_text=_(
            "List of strings: each is a field path (e.g. author.name) or an "
            "expand spec: relation.*[field1:field2] for one-to-many relations."
        ),
    )
    configuration = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        verbose_name=_("Configuration"),
        help_text=_(
            "Export options passed to pandas: keys ``csv``, ``excel``, ``json`` "
            "(see DataFrame.to_csv, to_excel, to_json). Default JSON uses orient=records."
        ),
    )

    class Meta:
        verbose_name = _("Export table configuration")
        verbose_name_plural = _("Export table configurations")
        db_table = "django_reportimport_reportconfigtable"

    def __str__(self) -> str:
        return _("Table config for %(name)s") % {"name": self.export.name}

    def clean(self) -> None:
        super().clean()
        cols = self.columns or []
        if not cols:
            return
        export = getattr(self, "export", None)
        if export is None or export.target_id is None:
            return
        model = export.target.model_class()
        if model is None:
            return
        validate_export_column_specs(model, cols)

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)
