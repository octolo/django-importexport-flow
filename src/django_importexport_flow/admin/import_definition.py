from __future__ import annotations

import logging
from typing import Any

import pandas as pd
from django.contrib import admin, messages
from django.contrib.admin import ModelAdmin
from django.contrib.admin.options import ShowFacets
from django.core.exceptions import PermissionDenied
from django.db import models
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from virtualqueryset import VirtualQuerySet  # type: ignore[import-untyped]

from django_boosted import AdminBoostModel, admin_boost_view
from django_boosted.decorators import AdminBoostViewConfig

from ..forms import (
    ExportConfigurationImportForm,
    ImportExampleFileForm,
    MAX_TABULAR_IMPORT_BYTES,
    TabularImportForm,
    make_tabular_import_form_class,
)
from ..models import ImportDefinition, ImportRequest
from ..models.data_preview import DataPreviewRow
from ..utils.http import content_disposition_attachment
from ..utils.helpers import get_setting
from ..engine.core.import_ import (
    create_import_request,
    read_import_filefield,
)
from ..task import dispatch_import_request
from ..utils.process import generate_example_file, validate_import
from ..utils.recoverable_errors import TABULAR_ENGINE_RECOVERABLE
from ..utils.serialization import import_import_definition, serialize_import_definition
from ..utils.helpers import dated_export_filename, safe_download_stem
from .import_config import run_json_configuration_import

logger = logging.getLogger(__name__)

# ``admin/change_form.html`` only sets ``enctype="multipart/form-data"`` when
# ``has_file_field`` is true; otherwise POST drops uploaded files.
_UPLOAD_FORM_CONTEXT = {"import_preview": False, "has_file_field": True}


def _filter_keys_from_cleaned(cleaned: dict) -> dict:
    return {k: v for k, v in cleaned.items() if k.startswith("fr_")}


_PREVIEW_ROW_LIMIT = get_setting("IMPORT_PREVIEW_ROW_LIMIT")


def _sanitize_path_to_field_name(path: str, used: set[str]) -> str:
    base = path.replace(".", "_").replace("-", "_")
    if not base.isidentifier():
        base = f"f_{abs(hash(path)) % (10**9)}"
    name = base
    n = 0
    while name in used:
        n += 1
        name = f"{base}_{n}"
    used.add(name)
    return name


def build_import_preview_model_class(
    column_paths: list[str],
    column_labels: list[str],
) -> tuple[type[models.Model], list[str]]:
    """
    Return a concrete unmanaged model class and ``list_display`` field names (same order as paths).

    Field ``verbose_name`` is the human label; technical paths are not stored as DB columns
    (Django field names cannot contain dots).
    """
    if len(column_labels) != len(column_paths):
        raise ValueError("column_labels and column_paths must have the same length.")
    used: set[str] = {"id"}
    fields: dict[str, models.Field] = {
        "id": models.BigAutoField(primary_key=True),
    }
    display_fields: list[str] = []
    for path, label in zip(column_paths, column_labels):
        fname = _sanitize_path_to_field_name(path, used)
        fields[fname] = models.CharField(
            max_length=4096,
            verbose_name=label,
            blank=True,
        )
        display_fields.append(fname)

    meta = type(
        "Meta",
        (),
        {
            "managed": False,
            "app_label": "django_importexport_flow",
            "verbose_name": "Import preview row",
            "verbose_name_plural": "Import preview rows",
        },
    )
    attrs = {
        "Meta": meta,
        "__module__": "django_importexport_flow.models.data_preview",
        **fields,
    }
    cls = type("ImportPreviewDynamic", (DataPreviewRow,), attrs)
    return cls, display_fields


def _preview_scalar(v: Any) -> Any:
    if pd.isna(v):
        return ""
    iso = getattr(v, "isoformat", None)
    if callable(iso):
        return iso()
    try:
        import numpy as np

        if isinstance(v, np.generic):
            return v.item()
    except ImportError:
        pass
    return v


def dataframe_to_preview_rows(
    df: Any,
    column_paths: list[str],
    list_display_fields: list[str],
    *,
    limit: int = _PREVIEW_ROW_LIMIT,
) -> list[dict[str, Any]]:
    """Map dataframe columns (same order as paths) to model field names; include ``id``."""
    if not isinstance(df, pd.DataFrame):
        raise TypeError("dataframe_to_preview_rows expects a pandas DataFrame.")
    if len(df.columns) != len(list_display_fields) or len(column_paths) != len(list_display_fields):
        raise ValueError("DataFrame columns and import paths are out of sync.")
    rows: list[dict[str, Any]] = []
    for i, (_ix, row) in enumerate(df.head(limit).iterrows(), start=1):
        d: dict[str, Any] = {"id": i}
        for col, fn in zip(df.columns, list_display_fields, strict=True):
            d[fn] = str(_preview_scalar(row[col]))
        rows.append(d)
    return rows


def build_import_preview_list_payload(
    parent_model_admin: ModelAdmin,
    df: Any,
    column_paths: list[str],
    column_labels: list[str],
) -> dict[str, Any]:
    """
    Payload for ``admin_boost_view("list", ...)``: ``VirtualQuerySet`` + ephemeral ``ModelAdmin``.

    Pass ``model_admin`` in the payload so django-boosted's list view builds the
    ChangeList with the preview model, not the registered admin model (e.g. ``ImportDefinition``).
    """
    model_class, list_display_fields = build_import_preview_model_class(column_paths, column_labels)
    rows = dataframe_to_preview_rows(df, column_paths, list_display_fields)
    vqs = VirtualQuerySet(model=model_class, data=rows)

    site = parent_model_admin.admin_site

    class ImportPreviewModelAdmin(ModelAdmin):
        model = model_class
        list_display = list_display_fields
        list_display_links = None
        list_filter: tuple[Any, ...] = ()
        search_fields: tuple[str, ...] = ()
        ordering: tuple[str, ...] = ()
        list_per_page = _PREVIEW_ROW_LIMIT
        list_max_show_all = 200
        sortable_by: list[str] = []
        actions: list[Any] = []
        show_full_result_count = False
        show_facets = ShowFacets.NEVER

        def get_queryset(self, request: HttpRequest):
            return vqs

    preview_admin = ImportPreviewModelAdmin(model_class, site)

    return {
        "queryset": vqs,
        "list_display": list_display_fields,
        "list_filter": (),
        "search_fields": (),
        "model_admin": preview_admin,
        "can_change": False,
        "has_change_permission": False,
        "has_create": False,
        "has_add_permission": False,
    }


@admin.register(ImportDefinition)
class ImportDefinitionAdmin(AdminBoostModel):
    list_display = ("name", "named_id", "target", "uuid")
    search_fields = ("name", "named_id", "description", "uuid")
    readonly_fields = (
        "uuid",
        "named_id",
        "created_by",
        "updated_by",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (None, {"fields": ("name", "named_id", "uuid", "description")}),
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
                    "import_match_fields",
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
        if not self.has_add_permission(request) and not self.has_change_permission(request):
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
        body, content_type, ext = generate_example_file(obj, example_format=fmt)
        basename = safe_download_stem(obj.name, fallback="example")
        response = HttpResponse(body, content_type=content_type)
        response["Content-Disposition"] = content_disposition_attachment(
            dated_export_filename(basename, ext)
        )
        return response

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
                out = validate_import(
                    file=upload,
                    import_definition=obj,
                    max_bytes=MAX_TABULAR_IMPORT_BYTES,
                )
            except MemoryError:
                logger.exception(
                    "Not enough memory during validate_import for import definition pk=%s",
                    obj.pk,
                )
                messages.error(
                    request,
                    _("Not enough memory to validate this file."),
                )
                return {"form": form, **_UPLOAD_FORM_CONTEXT}
            except TABULAR_ENGINE_RECOVERABLE as exc:
                logger.warning(
                    "validate_import failed for import definition pk=%s: %s",
                    obj.pk,
                    exc,
                )
                messages.error(request, str(exc))
                return {"form": form, **_UPLOAD_FORM_CONTEXT}
            except Exception as exc:
                logger.exception(
                    "Unexpected error during validate_import for import definition pk=%s",
                    obj.pk,
                )
                messages.error(request, str(exc))
                return {"form": form, **_UPLOAD_FORM_CONTEXT}

            for w in out["warnings"]:
                messages.warning(request, w)
            if out["errors"]:
                for e in out["errors"]:
                    messages.error(request, e)
                return {"form": form, **_UPLOAD_FORM_CONTEXT}

            resolved_cols = out["column_paths"]
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
            except MemoryError:
                logger.exception(
                    "Not enough memory creating ImportRequest for import definition pk=%s",
                    obj.pk,
                )
                messages.error(
                    request,
                    _("Not enough memory to store the uploaded file."),
                )
                return {"form": form, **_UPLOAD_FORM_CONTEXT}
            except TABULAR_ENGINE_RECOVERABLE as exc:
                logger.warning(
                    "Creating ImportRequest failed for import definition pk=%s: %s",
                    obj.pk,
                    exc,
                )
                messages.error(request, str(exc))
                return {"form": form, **_UPLOAD_FORM_CONTEXT}
            except Exception as exc:
                logger.exception(
                    "Unexpected error creating ImportRequest for import definition pk=%s",
                    obj.pk,
                )
                messages.error(request, str(exc))
                return {"form": form, **_UPLOAD_FORM_CONTEXT}

            opts = self.model._meta
            preview_url = reverse(
                f"admin:{opts.app_label}_{opts.model_name}_import_tabular_preview",
                args=[obj.pk],
                current_app=self.admin_site.name,
            )
            return HttpResponseRedirect(f"{preview_url}?import_request_uuid={ask.uuid}")

        uid = cleaned.get("import_request_uuid")
        ask = ImportRequest.objects.filter(
            uuid=uid,
            import_definition=obj,
            status=ImportRequest.Status.PENDING,
        ).first()
        if ask is None:
            messages.error(request, _("Import request not found or already processed."))
            return {
                "form": FormClass(initial={"step": TabularImportForm.STEP_UPLOAD}),
                **_UPLOAD_FORM_CONTEXT,
            }

        async_ok = (
            get_setting("IMPORT_TASK_BACKEND", "sync") != "sync"
            and bool(cleaned.get("defer_to_task"))
        )
        dispatch_import_request(ask, asynchronous=async_ok)
        ask.refresh_from_db()

        if ask.status == ImportRequest.Status.PROCESSING:
            messages.info(
                request,
                _(
                    "Import is running in the background. Check the import request record for the final status."
                ),
            )
        elif ask.status == ImportRequest.Status.SUCCESS:
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
        url = reverse(
            f"admin:{opts.app_label}_{opts.model_name}_change",
            args=[obj.pk],
            current_app=self.admin_site.name,
        )
        return {"redirect_url": url}

    @admin_boost_view(
        "list",
        _("Confirm import"),
        config=AdminBoostViewConfig(
            permission="change",
            hidden=True,
            template_name="django_importexport_flow/admin/report_import_import_confirm.html",
        ),
    )
    def import_tabular_preview(self, request, obj):
        """
        Changelist preview: list payload with ``VirtualQuerySet`` and ephemeral ``ModelAdmin``
        (django-boosted ``model_admin`` payload key).
        """
        if not self.has_change_permission(request, obj):
            raise PermissionDenied

        opts = self.model._meta
        change_url = reverse(
            f"admin:{opts.app_label}_{opts.model_name}_change",
            args=[obj.pk],
            current_app=self.admin_site.name,
        )
        uid = request.GET.get("import_request_uuid")
        if not uid:
            messages.error(request, _("Missing import request."))
            return HttpResponseRedirect(change_url)

        ask = ImportRequest.objects.filter(
            uuid=uid,
            import_definition=obj,
            status=ImportRequest.Status.PENDING,
        ).first()
        if ask is None:
            messages.error(
                request,
                _("Import request not found or already processed."),
            )
            return HttpResponseRedirect(change_url)

        try:
            df = read_import_filefield(ask.data_file, MAX_TABULAR_IMPORT_BYTES)
        except MemoryError:
            logger.exception(
                "Not enough memory reading import file for import definition pk=%s",
                obj.pk,
            )
            messages.error(
                request,
                _("Not enough memory to read the import file."),
            )
            return HttpResponseRedirect(change_url)
        except TABULAR_ENGINE_RECOVERABLE as exc:
            logger.warning(
                "read_import_filefield failed for import definition pk=%s: %s",
                obj.pk,
                exc,
            )
            messages.error(request, str(exc))
            return HttpResponseRedirect(change_url)
        except Exception as exc:
            logger.exception(
                "Unexpected error reading import file for import definition pk=%s",
                obj.pk,
            )
            messages.error(request, str(exc))
            return HttpResponseRedirect(change_url)

        out = validate_import(dataframe=df, import_definition=obj)
        for w in out["warnings"]:
            messages.warning(request, w)
        if out["errors"]:
            for e in out["errors"]:
                messages.error(request, e)
            return HttpResponseRedirect(change_url)

        df_preview = out["dataframe"] if out["dataframe"] is not None else df
        preview_labels = out["validation_dataset"]["column_labels"]
        resolved_cols = out["column_paths"]
        payload = build_import_preview_list_payload(
            self,
            df_preview,
            resolved_cols,
            preview_labels,
        )
        FormClass = make_tabular_import_form_class(obj)
        payload.update(
            {
                "import_request_uuid": str(ask.uuid),
                "import_data_post_url": reverse(
                    f"admin:{opts.app_label}_{opts.model_name}_import_tabular_data",
                    args=[obj.pk],
                    current_app=self.admin_site.name,
                ),
                "form": FormClass(
                    initial={
                        "step": TabularImportForm.STEP_CONFIRM,
                        "import_request_uuid": ask.uuid,
                    },
                ),
            }
        )
        return payload
