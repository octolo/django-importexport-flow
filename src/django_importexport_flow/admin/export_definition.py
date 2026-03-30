from __future__ import annotations

import logging

from django.contrib import admin
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from django_boosted import AdminBoostModel, admin_boost_view
from django_boosted.decorators import AdminBoostViewConfig

from ..engine.core.export import definition_has_table_config
from ..forms import ExportConfigurationImportForm, make_export_form_class
from ..models import ExportConfigPdf, ExportConfigTable, ExportDefinition
from ..utils.helpers import dated_export_filename, safe_download_stem
from ..utils.process import run_export_with_audit
from ..utils.http import content_disposition_attachment
from ..utils.serialization import import_export_configuration, serialize_export_configuration
from .import_config import run_json_configuration_import

logger = logging.getLogger(__name__)


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
class ExportDefinitionAdmin(AdminBoostModel):
    list_display = ("name", "named_id", "target", "manager", "uuid")
    search_fields = ("name", "named_id", "description", "uuid")
    readonly_fields = (
        "uuid",
        "named_id",
        "created_by",
        "updated_by",
        "created_at",
        "updated_at",
    )
    inlines = (ExportConfigPdfInline, ExportConfigTableInline)
    fieldsets = (
        (None, {"fields": ("name", "named_id", "uuid", "description")}),
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

    @admin_boost_view(
        "adminform",
        _("Process export"),
        config=AdminBoostViewConfig(permission="change"),
    )
    def process_export(self, request, obj, form=None):
        if not self.has_change_permission(request, obj):
            raise PermissionDenied
        FormClass = make_export_form_class(obj)
        if form is None:
            return {"form": FormClass()}
        if not form.is_valid():
            return {"form": form}
        if not definition_has_table_config(obj):
            messages.error(
                request,
                _("Add a table configuration (columns) before exporting."),
            )
            return {"form": form}
        cleaned = form.cleaned_data
        user = request.user if getattr(request.user, "is_authenticated", False) else None
        try:
            content, content_type, ext = run_export_with_audit(
                export_definition=obj,
                filter_payload=cleaned,
                user=user,
            )
        except (ValidationError, ValueError, TypeError) as exc:
            logger.warning(
                "Export validation failed for export definition pk=%s: %s",
                obj.pk,
                exc,
            )
            messages.error(request, str(exc))
            return {"form": form}
        except OSError:
            logger.exception(
                "Export failed (could not build file) for export definition pk=%s",
                obj.pk,
            )
            messages.error(
                request,
                _("Export failed (could not build the file)."),
            )
            return {"form": form}
        except MemoryError:
            logger.exception(
                "Not enough memory to complete export for export definition pk=%s",
                obj.pk,
            )
            messages.error(
                request,
                _("Not enough memory to complete this export."),
            )
            return {"form": form}
        except Exception:
            logger.exception(
                "Unexpected export failure for export definition pk=%s",
                obj.pk,
            )
            messages.error(request, _("Export failed."))
            return {"form": form}
        filename = dated_export_filename(safe_download_stem(obj.name, fallback="export"), ext)
        response = HttpResponse(content, content_type=content_type)
        response["Content-Disposition"] = content_disposition_attachment(filename)
        return response

    @admin_boost_view("json", _("Export configuration (JSON)"))
    def export_configuration_json(self, request, obj):
        return serialize_export_configuration(obj)

    @admin_boost_view("adminform", _("Import configuration (JSON)"))
    def import_configuration_json(self, request, form=None):
        if not self.has_add_permission(request) and not self.has_change_permission(request):
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
