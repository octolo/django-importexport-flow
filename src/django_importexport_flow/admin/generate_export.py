"""Admin mixin: generate table export with filter_request (GET) + filter_config merge."""

from __future__ import annotations

import json
import logging
import re
import traceback
from typing import Any

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from django_boosted import admin_boost_view
from django_boosted.decorators import AdminBoostViewConfig

from ..utils.export import definition_has_table_config, run_table_export
from ..forms import make_export_form_class
from ..models import ExportRequest
from ..utils.http import content_disposition_attachment

logger = logging.getLogger(__name__)


def safe_download_stem(
    raw_name: str | None,
    *,
    fallback: str = "export",
    max_len: int = 80,
) -> str:
    """Sanitize a title or name for use as a download filename stem (no extension)."""
    base = re.sub(r"[^\w\-.]+", "_", raw_name or "").strip("_") or fallback
    return base[:max_len]


def _safe_export_filename(name: str) -> str:
    return safe_download_stem(name, fallback="export")


def _export_timestamp_for_filename() -> str:
    """Local time, second precision, safe for filenames (e.g. ``20260329_143045``)."""
    return timezone.localtime(timezone.now()).strftime("%Y%m%d_%H%M%S")


def _filter_payload_snapshot(cleaned_data: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe subset: ``export_format`` and ``fr_*`` keys only."""
    subset = {
        k: v
        for k, v in cleaned_data.items()
        if k == "export_format" or k.startswith("fr_")
    }
    return json.loads(json.dumps(subset, default=str))


def dated_export_filename(safe_stem: str, ext: str) -> str:
    """
    ``safe_stem`` = basename without extension (already sanitized).
    ``ext`` must include the leading dot (e.g. ``.csv``).
    """
    return f"{safe_stem}_{_export_timestamp_for_filename()}{ext}"


class GenerateExportMixin:
    @admin_boost_view(
        "adminform",
        _("Generate export"),
        config=AdminBoostViewConfig(permission="change"),
    )
    def generate_export(self, request, obj, form=None):
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
        payload = _filter_payload_snapshot(cleaned)
        export_fmt = str(cleaned.get("export_format") or "")
        user = (
            request.user
            if getattr(request.user, "is_authenticated", False)
            else None
        )
        try:
            content, content_type, ext = run_table_export(obj, cleaned)
        except (ValidationError, ValueError) as exc:
            ExportRequest.objects.create(
                export_definition=obj,
                export_format=export_fmt,
                filter_payload=payload,
                status=ExportRequest.Status.FAILURE,
                error_trace=str(exc),
                completed_at=timezone.now(),
                initiated_by=user,
            )
            messages.error(request, str(exc))
            return {"form": form}
        except Exception:
            logger.exception("Table export failed for export definition %r", getattr(obj, "pk", None))
            ExportRequest.objects.create(
                export_definition=obj,
                export_format=export_fmt,
                filter_payload=payload,
                status=ExportRequest.Status.FAILURE,
                error_trace=traceback.format_exc(),
                completed_at=timezone.now(),
                initiated_by=user,
            )
            messages.error(request, _("Export failed."))
            return {"form": form}
        ExportRequest.objects.create(
            export_definition=obj,
            export_format=export_fmt,
            filter_payload=payload,
            status=ExportRequest.Status.SUCCESS,
            output_bytes=len(content),
            completed_at=timezone.now(),
            initiated_by=user,
        )
        filename = dated_export_filename(_safe_export_filename(obj.name), ext)
        response = HttpResponse(content, content_type=content_type)
        response["Content-Disposition"] = content_disposition_attachment(filename)
        return response
