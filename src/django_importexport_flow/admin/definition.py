from __future__ import annotations

import logging

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django_boosted import AdminBoostModel, admin_boost_link, admin_boost_view
from django_boosted.decorators import AdminBoostViewConfig

from ..engine.core.import_ import create_import_request
from ..forms import (
    MAX_TABULAR_IMPORT_BYTES,
    ExportConfigurationImportForm,
    ImportExampleFileForm,
    TabularImportForm,
    make_export_form_class,
    make_tabular_import_form_class,
)
from ..models import (
    Definition,
    ExportCategoryConfig,
    ExportDefinition,
    ImportCategoryConfig,
    ImportDefinition,
    ImportRequest,
    Step,
)
from ..utils.helpers import get_setting
from ..utils.http import configuration_json_download_response, content_disposition_attachment
from ..utils.process import (
    _run_export_with_audit_and_filename,
    import_example_download_response,
    validate_import,
)
from ..utils.recoverable_errors import TABULAR_ENGINE_RECOVERABLE
from ..utils.serialization import (
    import_export_configuration,
    import_import_definition,
    serialize_export_configuration,
    serialize_import_definition,
)
from .format import CategoryConfigInline, category_list_filter, format_list_filter
from .mixins import (
    columns_column,
    definition_heading,
    filter_column,
    manager_filter_column,
    match_column,
    model_column,
    output_column,
    proxy_raw_id_widget,
    run_json_configuration_import,
)
from .preview import _filter_keys_from_cleaned, build_import_preview_list_payload

logger = logging.getLogger(__name__)

_UPLOAD_FORM_CONTEXT = {"import_preview": False, "has_file_field": True}


class StepInline(admin.TabularInline):
    model = Step
    fk_name = "parent"
    extra = 0
    fields = ("position", "definition")
    raw_id_fields = ("definition",)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "definition":
            kwargs["widget"] = proxy_raw_id_widget(
                db_field,
                self.admin_site,
                ImportDefinition,
                using=kwargs.get("using"),
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


def _category_change_url(request_admin, category, direction: str) -> str | None:
    if category is None:
        return None
    proxy = (
        ExportCategoryConfig if direction == Definition.Direction.EXPORT else ImportCategoryConfig
    )
    opts = proxy._meta
    return reverse(
        f"admin:{opts.app_label}_{opts.model_name}_change",
        args=[category.pk],
        current_app=request_admin.admin_site.name,
    )


def _enabled_export_spec(request, obj, form):
    from ..engine.core.formats import get_export_config, get_format

    spec = get_format(str(form.cleaned_data.get("export_format") or ""))
    if spec is None:
        messages.error(request, _("Unknown export format."))
        return None
    try:
        get_export_config(obj, spec.key)
    except ValueError:
        messages.error(request, _("This format is not enabled on the definition."))
        return None
    return spec


def _export_file_response(request, obj, form):
    cleaned = form.cleaned_data
    user = request.user if getattr(request.user, "is_authenticated", False) else None
    try:
        content, content_type, _ext, filename = _run_export_with_audit_and_filename(
            export_definition=obj,
            filter_payload=cleaned,
            user=user,
            template_override=cleaned.get("template_override") or "",
            configuration_overrides=cleaned.get("configuration_overrides") or {},
        )
    except (ValidationError, ValueError, TypeError) as exc:
        logger.warning("Export validation failed for export definition pk=%s: %s", obj.pk, exc)
        messages.error(request, str(exc))
        return {"form": form}
    except OSError:
        logger.exception("Export failed (could not build file) for export definition pk=%s", obj.pk)
        messages.error(request, _("Export failed (could not build the file)."))
        return {"form": form}
    except MemoryError:
        logger.exception("Not enough memory to complete export for export definition pk=%s", obj.pk)
        messages.error(request, _("Not enough memory to complete this export."))
        return {"form": form}
    except Exception:
        logger.exception("Unexpected export failure for export definition pk=%s", obj.pk)
        messages.error(request, _("Export failed."))
        return {"form": form}
    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = content_disposition_attachment(filename)
    return response


class ExportWorkflow:
    filter_horizontal = ("exclude_relations",)
    list_display = (
        "definition_label",
        "model_label",
        "output_label",
        "filters_label",
        "manager_filters_label",
    )
    list_display_links = ("definition_label",)
    list_select_related = ("target",)
    search_fields = ("name", "named_id", "description", "uuid")
    readonly_fields = (
        "uuid",
        "named_id",
        "created_by",
        "updated_by",
        "created_at",
        "updated_at",
    )
    inlines = (CategoryConfigInline,)
    fieldsets = (
        (None, {"fields": ("name", "named_id", "uuid", "description")}),
        (_("Output"), {"fields": ("filename_hook",)}),
        (
            _("Model and queryset"),
            {
                "fields": (
                    "target",
                    "manager",
                    "manager_kwargs_config",
                    "manager_kwargs_request",
                    "manager_kwargs_mandatory",
                    "order_by",
                )
            },
        ),
        (
            _("Filters"),
            {"fields": ("filter_config", "filter_request", "filter_mandatory")},
        ),
        (
            _("Column traversal"),
            {"fields": ("max_relation_hops", "exclude_relations")},
        ),
        (
            _("Audit"),
            {
                "classes": ("collapse",),
                "fields": ("created_by", "updated_by", "created_at", "updated_at"),
            },
        ),
    )

    @admin.display(description=_("Definition"), ordering="named_id")
    def definition_label(self, obj):
        return definition_heading(self, obj)

    @admin.display(description=_("Model"), ordering="target")
    def model_label(self, obj):
        return model_column(self, obj, detail=(obj.manager or "").strip() or "objects")

    @admin.display(description=_("Output"))
    def output_label(self, obj):
        return output_column(self, obj)

    @admin.display(description=_("Filters"))
    def filters_label(self, obj):
        return filter_column(self, obj)

    @admin.display(description=_("Manager filters"))
    def manager_filters_label(self, obj):
        return manager_filter_column(self, obj)

    def _category_link(self, obj, category_key: str) -> str | None:
        category = obj.category_configs.filter(category_key=category_key).first()
        return _category_change_url(self, category, obj.direction)

    @admin_boost_link(_("Config document"), permission="change")
    def document_formats(self, request, obj):
        if obj.direction != Definition.Direction.EXPORT:
            return None
        return self._category_link(obj, "document")

    @admin_boost_link(_("Config spreadsheet"), permission="change")
    def spreadsheet_formats(self, request, obj):
        return self._category_link(obj, "spreadsheet")

    @admin_boost_link(_("Config structured data"), permission="change")
    def structured_data_formats(self, request, obj):
        return self._category_link(obj, "structured_data")

    @admin_boost_view(
        "adminform",
        _("Process export"),
        config=AdminBoostViewConfig(permission="change"),
    )
    def process_export(self, request, obj, form=None):
        if not self.has_change_permission(request, obj):
            raise PermissionDenied
        FormClass = make_export_form_class(
            obj,
            allow_template_override=request.user.has_perm(
                "django_importexport_flow.change_formatconfig"
            ),
        )
        if form is None:
            return {"form": FormClass()}
        if not form.is_valid():
            return {"form": form}
        if _enabled_export_spec(request, obj, form) is None:
            return {"form": form}
        return _export_file_response(request, obj, form)

    @admin_boost_view("json", _("Export configuration (JSON)"))
    def export_configuration_json(self, request, obj):
        return configuration_json_download_response(obj, serialize_export_configuration(obj))

    @admin_boost_view("json", _("Export configuration and translations (JSON)"))
    def export_configuration_with_translations_json(self, request, obj):
        payload = serialize_export_configuration(obj, include_column_translations=True)
        return configuration_json_download_response(obj, payload)

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


def _build_import_upload_response(form_class, form):
    if form is None:
        return {
            "form": form_class(initial={"step": TabularImportForm.STEP_UPLOAD}),
            **_UPLOAD_FORM_CONTEXT,
        }
    return {"form": form, **_UPLOAD_FORM_CONTEXT}


def _call_import_step(request, obj, form, action, *, memory_message, log_label):
    try:
        return action()
    except MemoryError:
        logger.exception("%s failed for import definition pk=%s", log_label, obj.pk)
        messages.error(request, memory_message)
    except TABULAR_ENGINE_RECOVERABLE as exc:
        logger.warning("%s failed for import definition pk=%s: %s", log_label, obj.pk, exc)
        messages.error(request, str(exc))
    except Exception as exc:
        logger.exception(
            "Unexpected error during %s for import definition pk=%s", log_label, obj.pk
        )
        messages.error(request, str(exc))
    return {"form": form, **_UPLOAD_FORM_CONTEXT}


def _validate_stored_import(request, obj, ask):
    try:
        return validate_import(
            file=ask.data_file,
            import_definition=obj,
            max_bytes=MAX_TABULAR_IMPORT_BYTES,
            user=ask.initiated_by,
            filter_payload=ask.filter_payload,
        )
    except MemoryError:
        logger.exception(
            "Not enough memory reading import file for import definition pk=%s",
            obj.pk,
        )
        messages.error(request, _("Not enough memory to read the import file."))
    except TABULAR_ENGINE_RECOVERABLE as exc:
        logger.warning(
            "read_import_filefield failed for import definition pk=%s: %s",
            obj.pk,
            exc,
        )
        messages.error(request, str(exc))
    except Exception as exc:
        logger.exception(
            "Unexpected error reading import file for import definition pk=%s",
            obj.pk,
        )
        messages.error(request, str(exc))
    return None


def _load_pending_import_request(obj, uid):
    return ImportRequest.objects.filter(
        uuid=uid,
        import_definition=obj,
        status=ImportRequest.Status.PENDING,
    ).first()


def _import_result_message(request, ask) -> None:
    if ask.status == ImportRequest.Status.PROCESSING:
        messages.info(
            request,
            _(
                "Import is running in the background. Check the import request record for the final status."
            ),
        )
        return
    if ask.status == ImportRequest.Status.SUCCESS:
        messages.success(request, _("Imported %(n)s row(s).") % {"n": ask.imported_row_count or 0})
        return
    messages.error(request, _("Import failed. See the import request record for details."))
    if ask.error_trace:
        messages.error(request, ask.error_trace[:4000])


class ImportWorkflow:
    filter_horizontal = ("exclude_relations",)
    list_display = (
        "definition_label",
        "model_label",
        "steps_label",
        "match_label",
        "filters_label",
        "columns_label",
    )
    list_display_links = ("definition_label",)
    list_select_related = ("target",)
    search_fields = ("name", "named_id", "description", "uuid")
    readonly_fields = (
        "uuid",
        "named_id",
        "created_by",
        "updated_by",
        "created_at",
        "updated_at",
    )

    @admin.display(description=_("Definition"), ordering="named_id")
    def definition_label(self, obj):
        return definition_heading(self, obj)

    @admin.display(description=_("Model"), ordering="target")
    def model_label(self, obj):
        return model_column(self, obj)

    @admin.display(description=_("Steps"), ordering="step_count")
    def steps_label(self, obj):
        return obj.step_count

    @admin.display(description=_("Match"))
    def match_label(self, obj):
        return match_column(self, obj)

    @admin.display(description=_("Filters"))
    def filters_label(self, obj):
        return filter_column(self, obj)

    @admin.display(description=_("Columns"))
    def columns_label(self, obj):
        return columns_column(self, obj)

    def _category_link(self, obj, category_key: str) -> str | None:
        category = obj.category_configs.filter(category_key=category_key).first()
        if category is None:
            return None
        return _category_change_url(self, category, obj.direction)

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
            _("Import"),
            {
                "fields": (
                    "columns_exclude",
                    "exclude_primary_key",
                    "max_relation_hops",
                    "exclude_relations",
                    "match_fields",
                )
            },
        ),
        (
            _("Audit"),
            {
                "classes": ("collapse",),
                "fields": ("created_by", "updated_by", "created_at", "updated_at"),
            },
        ),
    )

    @admin_boost_view("json", _("Export configuration (JSON)"))
    def export_import_definition_json(self, request, obj):
        return configuration_json_download_response(obj, serialize_import_definition(obj))

    @admin_boost_view("json", _("Export configuration and translations (JSON)"))
    def export_import_definition_with_translations_json(self, request, obj):
        payload = serialize_import_definition(obj, include_column_translations=True)
        return configuration_json_download_response(obj, payload)

    @admin_boost_view("adminform", _("Import configuration (JSON)"))
    def import_import_definition_json(self, request, form=None):
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
        try:
            return import_example_download_response(obj, example_format=fmt, dated=True)
        except ValueError as exc:
            form.add_error("example_format", str(exc))
            return {"form": form}

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
        form_class = make_tabular_import_form_class(obj)
        if form is None or not form.is_valid():
            return _build_import_upload_response(form_class, form)
        cleaned = form.cleaned_data
        if (cleaned.get("step") or TabularImportForm.STEP_UPLOAD) == TabularImportForm.STEP_UPLOAD:
            return self._import_upload_step(request, obj, form, cleaned)
        return self._import_confirm_step(request, obj, form_class, cleaned)

    def _import_upload_step(self, request, obj, form, cleaned):
        upload = cleaned["file"]
        filter_payload = _filter_keys_from_cleaned(cleaned)
        validated = _call_import_step(
            request,
            obj,
            form,
            lambda: validate_import(
                file=upload,
                import_definition=obj,
                max_bytes=MAX_TABULAR_IMPORT_BYTES,
                user=request.user,
                filter_payload=filter_payload,
            ),
            memory_message=_("Not enough memory to validate this file."),
            log_label="validate_import",
        )
        if isinstance(validated, dict) and "column_paths" not in validated:
            return validated
        for warning in validated["warnings"]:
            messages.warning(request, warning)
        if validated["errors"]:
            for error in validated["errors"]:
                messages.error(request, error)
            return {"form": form, **_UPLOAD_FORM_CONTEXT}
        created = _call_import_step(
            request,
            obj,
            form,
            lambda: create_import_request(
                obj,
                upload,
                filter_payload,
                request.user,
                inferred_column_paths=validated["column_paths"],
            ),
            memory_message=_("Not enough memory to store the uploaded file."),
            log_label="Creating ImportRequest",
        )
        if isinstance(created, dict):
            return created
        opts = self.model._meta
        preview_url = reverse(
            f"admin:{opts.app_label}_{opts.model_name}_import_tabular_preview",
            args=[obj.pk],
            current_app=self.admin_site.name,
        )
        return HttpResponseRedirect(f"{preview_url}?import_request_uuid={created.uuid}")

    def _import_confirm_step(self, request, obj, form_class, cleaned):
        ask = _load_pending_import_request(obj, cleaned.get("import_request_uuid"))
        if ask is None:
            messages.error(request, _("Import request not found or already processed."))
            return _build_import_upload_response(form_class, None)
        async_ok = get_setting("IMPORT_TASK_BACKEND", "sync") != "sync" and bool(
            cleaned.get("defer_to_task")
        )
        ask.save(trigger_processing=True, asynchronous=async_ok)
        ask.refresh_from_db()
        _import_result_message(request, ask)
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

        ask = _load_pending_import_request(obj, uid)
        if ask is None:
            messages.error(
                request,
                _("Import request not found or already processed."),
            )
            return HttpResponseRedirect(change_url)

        out = _validate_stored_import(request, obj, ask)
        if out is None:
            return HttpResponseRedirect(change_url)

        for w in out["warnings"]:
            messages.warning(request, w)
        if out["errors"]:
            for e in out["errors"]:
                messages.error(request, e)
            return HttpResponseRedirect(change_url)

        preview_labels = out["validation_dataset"]["column_labels"]
        resolved_cols = out["column_paths"]
        payload = build_import_preview_list_payload(
            self,
            out["dataframe"],
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


@admin.register(ExportDefinition)
class ExportDefinitionAdmin(ExportWorkflow, AdminBoostModel):
    list_filter = (
        category_list_filter("category_configs__category_key", "export"),
        format_list_filter("category_configs__format_configs__format_key", "export"),
    )
    readonly_fields = ExportWorkflow.readonly_fields

    def get_queryset(self, request):
        return super().get_queryset(request).filter(direction=Definition.Direction.EXPORT)


@admin.register(ImportDefinition)
class ImportDefinitionAdmin(ImportWorkflow, AdminBoostModel):
    list_filter = (
        category_list_filter("category_configs__category_key", "import"),
        format_list_filter("category_configs__format_configs__format_key", "import"),
    )
    inlines = (CategoryConfigInline, StepInline)
    readonly_fields = ImportWorkflow.readonly_fields

    def get_queryset(self, request):
        return super().get_queryset(request).filter(direction=Definition.Direction.IMPORT)
