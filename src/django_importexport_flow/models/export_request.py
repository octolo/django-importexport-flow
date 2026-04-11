"""Audit rows for admin table exports tied to :class:`~django_importexport_flow.models.ExportDefinition`."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from django_boosted.models import AuditMixin


class ExportRequest(AuditMixin, models.Model):
    """
    One **Generate export** action in the admin: format + filter snapshot (``fr_*``)
    and optional output size on success, or ``error_trace`` on failure.
    """

    class Status(models.TextChoices):
        SUCCESS = "success", _("Success")
        FAILURE = "failure", _("Failure")

    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        verbose_name=_("UUID"),
    )
    export_definition = models.ForeignKey(
        "ExportDefinition",
        on_delete=models.CASCADE,
        related_name="export_requests",
        verbose_name=_("Export definition"),
    )
    export_format = models.CharField(
        max_length=16,
        blank=True,
        verbose_name=_("Export format"),
        help_text=_("csv, excel, or json."),
    )
    filter_payload = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Filter form payload"),
        help_text=_("export_format plus fr_get_* / fr_kw_* from the export form."),
    )
    manager_kwargs_payload = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Manager kwargs form payload"),
        help_text=_("mg_get_* / mg_kw_* from the export form (manager_kwargs_* on the definition)."),
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        verbose_name=_("Status"),
    )
    output_bytes = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Output size (bytes)"),
        help_text=_("Set when export completed successfully."),
    )
    error_trace = models.TextField(
        blank=True,
        verbose_name=_("Error trace"),
        help_text=_("Message or traceback when status is failure."),
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
        related_name="initiated_export_requests",
        verbose_name=_("Initiated by"),
        help_text=_("User who ran the export in the admin."),
    )

    class Meta:
        ordering = ("-created_at",)
        verbose_name = _("Export request")
        verbose_name_plural = _("Export requests")
        db_table = "django_reportimport_reportrequest"

    def __str__(self) -> str:
        return f"{self.export_definition_id} · {self.get_status_display()} · {self.uuid}"
