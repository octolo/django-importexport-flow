"""Admin for persistent import and export requests."""

from __future__ import annotations

from typing import Any

from django import forms
from django.contrib import admin, messages
from django.utils.translation import gettext_lazy as _

from ..engine.core.import_ import relaunch_import_request


def _related_scope_summary(obj: Any, limit: int = 5) -> str:
    all_links = list(obj.related_object_links.all())
    if not all_links:
        return "—"
    parts = [
        link.object_str or f"{link.content_type_id}:{link.object_id}" for link in all_links[:limit]
    ]
    out = "; ".join(parts)
    if len(all_links) > limit:
        out += "…"
    return out


from ..models import (
    ExportDefinition,
    ExportRequest,
    ExportRequestRelatedObject,
    ImportDefinition,
    ImportRequest,
    ImportRequestRelatedObject,
)
from ..utils.helpers import get_setting
from .format import category_list_filter, format_list_filter


class ExportRequestAddForm(forms.ModelForm):
    """
    Form used only on the admin Add view.

    Adds an optional ``run_async`` checkbox whose visibility and default value
    are controlled by the ``EXPORT_ADMIN_OFFER_ASYNC`` /
    ``EXPORT_ADMIN_ASYNC_DEFAULT`` settings.
    """

    run_async = forms.BooleanField(
        label=_("Run asynchronously"),
        required=False,
        help_text=_(
            "Enqueue the export task instead of running it inside this HTTP request. "
            "Only effective when IMPORT_TASK_BACKEND is thread, celery, or rq "
            "(with sync, the export always runs inline in this request)."
        ),
    )

    class Meta:
        model = ExportRequest
        fields = (
            "export_definition",
            "export_format",
            "filter_payload",
            "manager_kwargs_payload",
            "template_override",
            "configuration_overrides",
        )


class ExportRequestRelatedObjectInline(admin.TabularInline):
    model = ExportRequestRelatedObject
    extra = 0
    fields = ("content_type", "object_id", "object_str")
    readonly_fields = ("object_str",)


@admin.register(ExportRequest)
class ExportRequestAdmin(admin.ModelAdmin):
    inlines = (ExportRequestRelatedObjectInline,)

    _add_fields_base = (
        "export_definition",
        "export_format",
        "filter_payload",
        "manager_kwargs_payload",
        "template_override",
        "configuration_overrides",
    )

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
    list_filter = (
        "status",
        category_list_filter("", "export", format_field="export_format"),
        format_list_filter("export_format", "export"),
        "created_at",
    )
    search_fields = ("uuid",)
    readonly_fields = (
        "uuid",
        "export_definition",
        "export_format",
        "filter_payload",
        "manager_kwargs_payload",
        "template_override",
        "configuration_overrides",
        "status",
        "output_bytes",
        "output_file",
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

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "export_definition":
            kwargs["queryset"] = ExportDefinition.objects.all()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    @admin.display(description=_("Related scope"))
    def related_scope_summary(self, obj: ExportRequest) -> str:
        return _related_scope_summary(obj)

    def has_add_permission(self, request):
        return request.user.is_superuser

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            return ExportRequestAddForm
        return super().get_form(request, obj, **kwargs)

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        initial["run_async"] = get_setting("EXPORT_ADMIN_ASYNC_DEFAULT", False)
        return initial

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            fields = list(self._add_fields_base)
            if get_setting("EXPORT_ADMIN_OFFER_ASYNC", True):
                fields.append("run_async")
            return ((None, {"fields": fields}),)
        return super().get_fieldsets(request, obj)

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return (
                "uuid",
                "status",
                "output_bytes",
                "output_file",
                "error_trace",
                "completed_at",
                "initiated_by",
                "created_at",
                "created_by",
                "updated_by",
                "updated_at",
            )
        return self.readonly_fields

    def save_model(self, request, obj, form, change):
        if not change:
            obj.status = ExportRequest.Status.PENDING
            if request.user.is_authenticated:
                obj.initiated_by = request.user
            # Flags consumed by save_related() after inlines are saved.
            obj._trigger_processing_after_related = True
            obj._run_async = bool(form.cleaned_data.get("run_async", False))
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        obj = form.instance
        if not change and getattr(obj, "_trigger_processing_after_related", False):
            obj._trigger_processing_after_related = False
            run_async = getattr(obj, "_run_async", False)
            obj.save(trigger_processing=True, asynchronous=run_async)
            obj.refresh_from_db()
            if obj.status == ExportRequest.Status.FAILURE:
                self.message_user(
                    request,
                    _("Export failed: %(trace)s") % {"trace": (obj.error_trace or "")[:2000]},
                    level=messages.ERROR,
                )
            elif obj.status == ExportRequest.Status.SUCCESS:
                self.message_user(
                    request,
                    _("Export completed: %(n)s bytes.") % {"n": obj.output_bytes or 0},
                )
            elif obj.status == ExportRequest.Status.PROCESSING:
                self.message_user(
                    request,
                    _(
                        "Export queued for background processing. Refresh this page to see the result."
                    ),
                    level=messages.INFO,
                )


class ImportRequestAddForm(forms.ModelForm):
    """
    Form used only on the admin Add view.

    Adds an optional ``run_async`` checkbox whose visibility and default value
    are controlled by the ``IMPORT_ADMIN_OFFER_ASYNC`` /
    ``IMPORT_ADMIN_ASYNC_DEFAULT`` settings.
    """

    run_async = forms.BooleanField(
        label=_("Run asynchronously"),
        required=False,
        help_text=_(
            "Enqueue the import task instead of running it inside this HTTP request. "
            "Only effective when IMPORT_TASK_BACKEND is thread, celery, or rq "
            "(with sync, the import always runs inline in this request)."
        ),
    )

    class Meta:
        model = ImportRequest
        fields = ("import_definition", "data_file", "filter_payload")


class ImportRequestRelatedObjectInline(admin.TabularInline):
    model = ImportRequestRelatedObject
    extra = 0
    fields = ("content_type", "object_id", "object_str")
    readonly_fields = ("object_str",)


@admin.register(ImportRequest)
class ImportRequestAdmin(admin.ModelAdmin):
    actions = ("relaunch_selected",)
    inlines = (ImportRequestRelatedObjectInline,)

    _add_fields_base = ("import_definition", "data_file", "filter_payload")

    list_display = (
        "uuid",
        "import_definition",
        "related_scope_summary",
        "status",
        "imported_row_count",
        "created_at",
        "completed_at",
        "initiated_by",
        "created_by",
        "updated_by",
        "updated_at",
        "relaunched_from",
    )
    list_filter = (
        "status",
        category_list_filter("import_definition__category_configs__category_key", "import"),
        format_list_filter(
            "import_definition__category_configs__format_configs__format_key",
            "import",
        ),
        "created_at",
    )
    search_fields = ("uuid",)
    readonly_fields = (
        "uuid",
        "import_definition",
        "relaunched_from",
        "data_file",
        "filter_payload",
        "status",
        "imported_row_count",
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

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "import_definition":
            kwargs["queryset"] = ImportDefinition.objects.all()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    @admin.display(description=_("Related scope"))
    def related_scope_summary(self, obj: ImportRequest) -> str:
        return _related_scope_summary(obj)

    def has_add_permission(self, request):
        return request.user.is_superuser

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            return ImportRequestAddForm
        return super().get_form(request, obj, **kwargs)

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        initial["run_async"] = get_setting("IMPORT_ADMIN_ASYNC_DEFAULT", False)
        return initial

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            fields = list(self._add_fields_base)
            if get_setting("IMPORT_ADMIN_OFFER_ASYNC", True):
                fields.append("run_async")
            return ((None, {"fields": fields}),)
        return super().get_fieldsets(request, obj)

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return (
                "uuid",
                "status",
                "imported_row_count",
                "error_trace",
                "completed_at",
                "initiated_by",
                "relaunched_from",
                "created_at",
                "created_by",
                "updated_by",
                "updated_at",
            )
        return self.readonly_fields

    def save_model(self, request, obj, form, change):
        if not change:
            obj.status = ImportRequest.Status.PENDING
            if request.user.is_authenticated:
                obj.initiated_by = request.user
            # Flags consumed by save_related() after inlines are saved.
            obj._trigger_processing_after_related = True
            obj._run_async = bool(form.cleaned_data.get("run_async", False))
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        obj = form.instance
        if not change and getattr(obj, "_trigger_processing_after_related", False):
            obj._trigger_processing_after_related = False
            run_async = getattr(obj, "_run_async", False)
            obj.save(trigger_processing=True, asynchronous=run_async)
            obj.refresh_from_db()
            if obj.status == ImportRequest.Status.FAILURE:
                self.message_user(
                    request,
                    _("Import failed: %(trace)s") % {"trace": (obj.error_trace or "")[:2000]},
                    level=messages.ERROR,
                )
            elif obj.status == ImportRequest.Status.SUCCESS:
                self.message_user(
                    request,
                    _("Imported %(n)s row(s) successfully.") % {"n": obj.imported_row_count or 0},
                )
            elif obj.status == ImportRequest.Status.PROCESSING:
                self.message_user(
                    request,
                    _(
                        "Import queued for background processing. Refresh this page to see the result."
                    ),
                    level=messages.INFO,
                )

    @admin.action(description=_("Relaunch selected requests (new row, same file)"))
    def relaunch_selected(self, request, queryset):
        n = 0
        for ask in queryset:
            try:
                relaunch_import_request(ask, request.user)
                n += 1
            except Exception as exc:  # noqa: BLE001 — one failed relaunch must not abort the rest
                self.message_user(
                    request,
                    _("Relaunch failed for %(uuid)s: %(err)s") % {"uuid": ask.uuid, "err": exc},
                    level=messages.ERROR,
                )
        if n:
            self.message_user(
                request,
                _("Created %(n)s new pending import request(s).") % {"n": n},
            )
