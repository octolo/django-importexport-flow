from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from .export_definition import ExportDefinition


class ExportConfigPdf(models.Model):
    export = models.OneToOneField(
        ExportDefinition,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="config_pdf",
        verbose_name=_("Export"),
    )
    template = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("Template"),
        help_text=_("HTML template."),
    )
    configuration = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        verbose_name=_("Configuration"),
        help_text=_("Renderer options."),
    )

    class Meta:
        verbose_name = _("Export PDF configuration")
        verbose_name_plural = _("Export PDF configurations")
        db_table = "django_reportimport_reportconfigpdf"

    def __str__(self) -> str:
        return _("PDF config for %(name)s") % {"name": self.export.name}
