"""Admin for :class:`~django_importexport_flow.models.ExportRequest` (export audit)."""

from __future__ import annotations

from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from ..models import ExportRequest, ExportRequestRelatedObject


class ExportRequestRelatedObjectInline(admin.TabularInline):
    model = ExportRequestRelatedObject
    extra = 0
    fields = ("content_type", "object_id", "object_str")
    readonly_fields = ("object_str",)


@admin.register(ExportRequest)
class ExportRequestAdmin(admin.ModelAdmin):
    inlines = (ExportRequestRelatedObjectInline,)

    list_display = (
        "uuid",
        "export_definition",
        "related_scope_summary",
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
        "manager_kwargs_payload",
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

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("related_object_links")

    @admin.display(description=_("Related scope"))
    def related_scope_summary(self, obj: ExportRequest) -> str:
        all_links = list(obj.related_object_links.all())
        if not all_links:
            return "—"
        parts = [
            link.object_str or f"{link.content_type_id}:{link.object_id}"
            for link in all_links[:5]
        ]
        out = "; ".join(parts)
        if len(all_links) > 5:
            out += "…"
        return out

    def has_add_permission(self, request):
        """Rows are created by *Generate export* only."""
        return False
