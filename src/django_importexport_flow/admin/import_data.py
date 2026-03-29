"""Admin wizard: upload → preview table → confirm import."""

from __future__ import annotations

import logging
from typing import Any

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _

from django_boosted import admin_boost_view
from django_boosted.decorators import AdminBoostViewConfig

from ..forms import (
    MAX_TABULAR_IMPORT_BYTES,
    TabularImportForm,
    make_tabular_import_form_class,
)
from ..utils.import_tabular import (
    create_import_request,
    read_uploaded_tabular,
    run_tabular_import_for_request,
    validate_import_preview,
)
from ..utils import dataframe_preview_table
from ..models import ImportRequest

logger = logging.getLogger(__name__)

# ``admin/change_form.html`` only sets ``enctype="multipart/form-data"`` when
# ``has_file_field`` is true; otherwise POST drops uploaded files.
_UPLOAD_FORM_CONTEXT = {"import_preview": False, "has_file_field": True}


def _filter_keys_from_cleaned(cleaned: dict) -> dict:
    return {k: v for k, v in cleaned.items() if k.startswith("fr_")}


class ImportDataPreviewMixin:
    @admin_boost_view(
        "adminform",
        _("Import data (preview)"),
        config=AdminBoostViewConfig(
            permission="change",
            template_name="django_importexport_flow/admin/report_import_import_data.html",
        ),
    )
    def import_tabular_data(self, request, obj, form=None):
        if not self.has_change_permission(request, obj):
            raise PermissionDenied
        FormClass = make_tabular_import_form_class(obj)

        if form is None:
            return {
                "form": FormClass(initial={"step": TabularImportForm.STEP_UPLOAD}),
                **_UPLOAD_FORM_CONTEXT,
            }

        if not form.is_valid():
            return {"form": form, **_UPLOAD_FORM_CONTEXT}

        cleaned = form.cleaned_data
        step = cleaned.get("step") or TabularImportForm.STEP_UPLOAD

        if step == TabularImportForm.STEP_UPLOAD:
            upload = cleaned["file"]
            try:
                df = read_uploaded_tabular(upload, MAX_TABULAR_IMPORT_BYTES)
            except Exception as exc:
                messages.error(request, str(exc))
                return {"form": form, **_UPLOAD_FORM_CONTEXT}

            errs, warns, resolved_cols, df_norm = validate_import_preview(df, obj)
            for w in warns:
                messages.warning(request, w)
            if errs:
                for e in errs:
                    messages.error(request, e)
                return {"form": form, **_UPLOAD_FORM_CONTEXT}

            filter_subset = _filter_keys_from_cleaned(cleaned)
            ask_kw: dict[str, Any] = {"inferred_column_paths": resolved_cols}
            try:
                ask = create_import_request(
                    obj,
                    upload,
                    filter_subset,
                    request.user,
                    **ask_kw,
                )
            except Exception as exc:
                logger.exception("Creating ImportRequest failed")
                messages.error(request, str(exc))
                return {"form": form, **_UPLOAD_FORM_CONTEXT}

            preview_columns, preview_rows = dataframe_preview_table(
                df_norm if df_norm is not None else df,
                limit=30,
            )
            context = {
                **self.admin_site.each_context(request),
                "title": _("Confirm import"),
                "opts": self.model._meta,
                "original": obj,
                "preview_rows": preview_rows,
                "preview_columns": preview_columns,
                "import_request_uuid": str(ask.uuid),
            }
            return render(
                request,
                "django_importexport_flow/admin/report_import_import_confirm.html",
                context,
            )

        uid = cleaned.get("import_request_uuid")
        ask = (
            ImportRequest.objects.filter(
                uuid=uid,
                import_definition=obj,
                status=ImportRequest.Status.PENDING,
            )
            .first()
        )
        if ask is None:
            messages.error(request, _("Import request not found or already processed."))
            return {
                "form": FormClass(initial={"step": TabularImportForm.STEP_UPLOAD}),
                **_UPLOAD_FORM_CONTEXT,
            }

        run_tabular_import_for_request(ask)
        ask.refresh_from_db()

        if ask.status == ImportRequest.Status.SUCCESS:
            messages.success(
                request,
                _("Imported %(n)s row(s).") % {"n": ask.imported_row_count or 0},
            )
        else:
            messages.error(
                request,
                _("Import failed. See the import request record for details."),
            )
            if ask.error_trace:
                messages.error(request, ask.error_trace[:4000])

        opts = self.model._meta
        from django.urls import reverse

        url = reverse(
            f"admin:{opts.app_label}_{opts.model_name}_change",
            args=[obj.pk],
            current_app=self.admin_site.name,
        )
        return {"redirect_url": url}
