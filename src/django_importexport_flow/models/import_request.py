"""Persisted import attempts for :class:`~django_importexport_flow.models.ImportDefinition` (audit + retry)."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from django_boosted.models import AuditMixin


class ImportRequest(AuditMixin, models.Model):
    """
    One user upload + filter snapshot for a tabular import. Each confirmation or
    relaunch creates a **new** row so history stays linear; failed rows keep
    ``error_trace`` for support.
    """

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        SUCCESS = "success", _("Success")
        FAILURE = "failure", _("Failure")

    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        verbose_name=_("UUID"),
    )
    import_definition = models.ForeignKey(
        "ImportDefinition",
        on_delete=models.CASCADE,
        related_name="import_requests",
        verbose_name=_("Import definition"),
    )
    relaunched_from = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="relaunches",
        verbose_name=_("Relaunched from"),
        help_text=_("Previous request when this row was created by “Relaunch”."),
    )
    data_file = models.FileField(
        upload_to="report_import_asks/%Y/%m/",
        verbose_name=_("Uploaded file"),
    )
    filter_payload = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Filter form payload"),
        help_text=_("Keys fr_get_* / fr_kw_* from the import wizard."),
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name=_("Status"),
    )
    imported_row_count = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Imported row count"),
    )
    error_trace = models.TextField(
        blank=True,
        verbose_name=_("Error trace"),
        help_text=_("Traceback or per-row errors when status is failure."),
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Completed at"),
    )
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="import_requests",
        verbose_name=_("Initiated by"),
        help_text=_("User who started the import (wizard or relaunch)."),
    )

    class Meta:
        db_table = "django_reporting_reportimportask"
        ordering = ("-created_at",)
        verbose_name = _("Import request")
        verbose_name_plural = _("Import requests")

    def __str__(self) -> str:
        return f"{self.import_definition_id} · {self.get_status_display()} · {self.uuid}"
