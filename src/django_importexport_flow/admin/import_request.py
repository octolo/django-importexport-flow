"""Admin for :class:`~django_importexport_flow.models.ImportRequest` (audit + relaunch)."""

from __future__ import annotations

from django.contrib import admin, messages
from django.utils.translation import gettext_lazy as _

from ..utils.import_tabular import relaunch_import_request
from ..models import ImportRequest


@admin.register(ImportRequest)
class ImportRequestAdmin(admin.ModelAdmin):
    actions = ("relaunch_selected",)

    list_display = (
        "uuid",
        "import_definition",
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
    list_filter = ("status", "created_at")
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

    def has_add_permission(self, request):
        """Rows are created by the import wizard or relaunch action only."""
        return False

    @admin.action(description=_("Relaunch selected requests (new row, same file)"))
    def relaunch_selected(self, request, queryset):
        n = 0
        for ask in queryset:
            try:
                relaunch_import_request(ask, request.user)
                n += 1
            except Exception as exc:
                self.message_user(
                    request,
                    _("Relaunch failed for %(uuid)s: %(err)s")
                    % {"uuid": ask.uuid, "err": exc},
                    level=messages.ERROR,
                )
        if n:
            self.message_user(
                request,
                _("Created %(n)s new pending import request(s). Confirm each from the wizard or add tooling.")
                % {"n": n},
            )
