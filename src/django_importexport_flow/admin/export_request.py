"""Admin for :class:`~django_importexport_flow.models.ExportRequest` (export audit)."""

from __future__ import annotations

from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from ..models import ExportRequest


@admin.register(ExportRequest)
class ExportRequestAdmin(admin.ModelAdmin):
    list_display = (
        "uuid",
        "export_definition",
        "export_format",
        "status",
        "output_bytes",
        "created_at",
        "completed_at",
        "initiated_by",
        "created_by",
        "updated_by",
        "updated_at",
    )
    list_filter = ("status", "export_format", "created_at")
    search_fields = ("uuid",)
    readonly_fields = (
        "uuid",
        "export_definition",
        "export_format",
        "filter_payload",
        "status",
        "output_bytes",
        "error_trace",
        "created_at",
        "completed_at",
        "initiated_by",
        "created_by",
        "updated_by",
        "updated_at",
    )
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        """Rows are created by *Generate export* only."""
        return False
