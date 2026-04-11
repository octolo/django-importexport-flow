from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

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
            "List of strings: each is a field path (e.g. author.name), keys inside "
            "a ``JSONField`` (e.g. metadata.lang), an ``@property`` / ``cached_property`` "
            "on the model or a related model (e.g. author.name_upper), an expand spec: "
            "relation.*[field1:field2] for one-to-many relations, or a queryset annotation "
            "name declared in ``configuration`` (``annotation_columns``, ``annotations``)."
        ),
    )
    configuration = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        verbose_name=_("Configuration"),
        help_text=_(
            "Export options passed to pandas: keys ``csv``, ``excel``, ``json`` "
            "(see DataFrame.to_csv, to_excel, to_json). Default JSON uses orient=records. "
            "Optional ``annotation_columns``: list of names added only by "
            "``QuerySet.annotate()`` (not ORM fields, JSON subpaths, or properties) so "
            "they may appear in ``columns``. For any column path in ``columns`` with no "
            "ORM verbose name (annotations, unknown paths, …), you may set "
            "``<path>_label`` to the header text, e.g. "
            "``author.total_books_label`` for path ``author.total_books``; for expand "
            "subfields, use ``<subfield>_label`` (e.g. ``pages_label``)."
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

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)
