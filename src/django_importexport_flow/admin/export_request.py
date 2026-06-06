"""Admin for :class:`~django_importexport_flow.models.ExportRequest` (export audit)."""

from __future__ import annotations

from django import forms
from django.contrib import admin, messages
from django.utils.translation import gettext_lazy as _

from ..models import ExportRequest, ExportRequestRelatedObject
from ..utils.helpers import get_setting


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
        fields = ["export_definition", "export_format", "filter_payload", "manager_kwargs_payload"]


class ExportRequestRelatedObjectInline(admin.TabularInline):
    model = ExportRequestRelatedObject
    extra = 0
    fields = ("content_type", "object_id", "object_str")
    readonly_fields = ("object_str",)


@admin.register(ExportRequest)
class ExportRequestAdmin(admin.ModelAdmin):
    inlines = (ExportRequestRelatedObjectInline,)

    _add_fields_base = ("export_definition", "export_format", "filter_payload", "manager_kwargs_payload")

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
                    _("Export queued for background processing. Refresh this page to see the result."),
                    level=messages.INFO,
                )
