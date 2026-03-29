from __future__ import annotations

from io import BytesIO, StringIO

import pandas as pd
from django.contrib import admin
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from django_boosted import AdminBoostModel, admin_boost_view

from ..forms import ImportExampleFileForm, ExportConfigurationImportForm
from ..models import ImportDefinition
from ..utils.http import content_disposition_attachment
from ..utils.import_tabular import (
    effective_import_column_paths,
    sample_headers_for_import_definition,
)
from ..utils.serialization import import_import_definition, serialize_import_definition
from .generate_export import dated_export_filename, safe_download_stem
from .import_config import run_json_configuration_import
from .import_data import ImportDataPreviewMixin


@admin.register(ImportDefinition)
class ImportDefinitionAdmin(ImportDataPreviewMixin, AdminBoostModel):
    list_display = ("name", "target", "uuid")
    search_fields = ("name", "description", "uuid")
    readonly_fields = (
        "uuid",
        "created_by",
        "updated_by",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (None, {"fields": ("name", "uuid", "description")}),
        (
            _("Model"),
            {"fields": ("target", "order_by")},
        ),
        (
            _("Filters"),
            {"fields": ("filter_config", "filter_request", "filter_mandatory")},
        ),
        (
            _("Table export"),
            {
                "fields": (
                    "columns_exclude",
                    "exclude_primary_key",
                    "import_max_relation_hops",
                    "configuration",
                )
            },
        ),
        (
            _("Audit"),
            {"fields": ("created_by", "updated_by", "created_at", "updated_at")},
        ),
    )

    @admin_boost_view("json", _("Export configuration (JSON)"))
    def export_configuration_json(self, request, obj):
        return serialize_import_definition(obj)

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
            import_import_definition,
            log_label="import_import_definition",
        )
        if imported is None:
            return {"form": form}
        messages.success(
            request,
            _("Imported import definition “%(name)s”.") % {"name": imported.name},
        )
        opts = self.model._meta
        url = reverse(
            f"admin:{opts.app_label}_{opts.model_name}_change",
            args=[imported.pk],
            current_app=self.admin_site.name,
        )
        return {"redirect_url": url}

    @admin_boost_view("adminform", _("Example import file"))
    def download_example_file(self, request, obj, form=None):
        if form is None:
            return {"form": ImportExampleFileForm()}
        fmt = form.cleaned_data["example_format"]
        paths = effective_import_column_paths(obj)
        labels = sample_headers_for_import_definition(obj, column_paths=paths)
        basename = safe_download_stem(obj.name, fallback="example")
        if fmt == "json":
            df = pd.DataFrame([{p: "" for p in paths}])
            body = df.to_json(orient="records", indent=2, force_ascii=False)
            response = HttpResponse(
                body,
                content_type="application/json; charset=utf-8",
            )
            response["Content-Disposition"] = content_disposition_attachment(
                dated_export_filename(basename, ".json")
            )
            return response
        if fmt == "csv":
            delim = (obj.configuration or {}).get("csv", {}).get("delimiter", ",")
            if not isinstance(delim, str) or len(delim) != 1:
                delim = ","
            buffer = StringIO()
            df_csv = (
                pd.DataFrame([labels, [""] * len(paths)], columns=paths)
                if paths
                else pd.DataFrame(columns=paths)
            )
            df_csv.to_csv(buffer, index=False, sep=delim)
            response = HttpResponse(
                buffer.getvalue().encode("utf-8"),
                content_type="text/csv; charset=utf-8",
            )
            response["Content-Disposition"] = content_disposition_attachment(
                dated_export_filename(basename, ".csv")
            )
            return response
        stream = BytesIO()
        df_xlsx = (
            pd.DataFrame([labels, [""] * len(paths)], columns=paths)
            if paths
            else pd.DataFrame(columns=paths)
        )
        df_xlsx.to_excel(
            stream, index=False, sheet_name="Sheet1", engine="openpyxl"
        )
        response = HttpResponse(
            stream.getvalue(),
            content_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )
        response["Content-Disposition"] = content_disposition_attachment(
            dated_export_filename(basename, ".xlsx")
        )
        return response
