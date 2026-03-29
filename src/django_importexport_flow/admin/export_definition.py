from __future__ import annotations

from django.contrib import admin
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from django_boosted import AdminBoostModel, admin_boost_view

from ..forms import ExportConfigurationImportForm
from ..models import ExportConfigPdf, ExportConfigTable, ExportDefinition
from ..utils.serialization import import_export_configuration, serialize_export_configuration
from .generate_export import GenerateExportMixin
from .import_config import run_json_configuration_import


class ExportConfigPdfInline(admin.StackedInline):
    model = ExportConfigPdf
    extra = 0
    classes = ("collapse",)
    fields = ("template", "configuration")


class ExportConfigTableInline(admin.StackedInline):
    model = ExportConfigTable
    extra = 0
    classes = ("collapse",)
    fields = ("columns", "configuration")


@admin.register(ExportDefinition)
class ExportDefinitionAdmin(GenerateExportMixin, AdminBoostModel):
    list_display = ("name", "target", "manager", "uuid")
    search_fields = ("name", "description", "uuid")
    readonly_fields = (
        "uuid",
        "created_by",
        "updated_by",
        "created_at",
        "updated_at",
    )
    inlines = (ExportConfigPdfInline, ExportConfigTableInline)
    fieldsets = (
        (None, {"fields": ("name", "uuid", "description")}),
        (
            _("Model and queryset"),
            {"fields": ("target", "manager", "order_by")},
        ),
        (
            _("Filters"),
            {"fields": ("filter_config", "filter_request", "filter_mandatory")},
        ),
        (
            _("Audit"),
            {"fields": ("created_by", "updated_by", "created_at", "updated_at")},
        ),
    )

    @admin_boost_view("json", _("Export configuration (JSON)"))
    def export_configuration_json(self, request, obj):
        return serialize_export_configuration(obj)

    @admin_boost_view("adminform", _("Import configuration (JSON)"))
    def import_configuration_json(self, request, form=None):
        if not self.has_add_permission(request) and not self.has_change_permission(
            request
        ):
            raise PermissionDenied
        if form is None:
            return {"form": ExportConfigurationImportForm()}
        imported = run_json_configuration_import(
            request,
            form,
            import_export_configuration,
            log_label="import_export_configuration",
        )
        if imported is None:
            return {"form": form}
        messages.success(
            request,
            _("Imported export “%(name)s”.") % {"name": imported.name},
        )
        opts = self.model._meta
        url = reverse(
            f"admin:{opts.app_label}_{opts.model_name}_change",
            args=[imported.pk],
            current_app=self.admin_site.name,
        )
        return {"redirect_url": url}
