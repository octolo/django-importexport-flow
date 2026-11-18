"""Changelist columns for export and import definitions."""

from __future__ import annotations

from typing import Any

from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext_lazy as _

from ..engine.core.formats import (
    CATEGORY_LABELS,
    CATEGORY_ORDER,
    DOCUMENT,
    SPREADSHEET,
    STRUCTURED_DATA,
    formats_for_definition,
)

_EMPTY = "—"
_ICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 16 16" '
    'fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" '
    'aria-hidden="true" style="vertical-align:-2px;margin-right:3px">{}</svg>'
)
_CATEGORY_ICONS = {
    DOCUMENT: format_html(
        _ICON,
        format_html('<path d="M4 1.5h5.1L13 5.3V14.5H4z"/><path d="M9 1.7V5.4h3.5"/>{}', ""),
    ),
    SPREADSHEET: format_html(
        _ICON,
        format_html(
            '<rect x="2.2" y="2.2" width="11.6" height="11.6" rx="1"/>'
            '<path d="M2.2 6.2h11.6M2.2 10.2h11.6M6.2 2.2v11.6M10.2 2.2v11.6"/>{}',
            "",
        ),
    ),
    STRUCTURED_DATA: format_html(
        _ICON,
        format_html(
            '<path d="M6.2 2.4c-1.7 0-2.1 1.3-2.1 2.3v1.3C4.1 7.4 2.4 7.6 2.4 8'
            's1.7.6 1.7 2v1.3c0 1 .4 2.3 2.1 2.3"/>'
            '<path d="M9.8 2.4c1.7 0 2.1 1.3 2.1 2.3v1.3c0 1.4 1.7 1.6 1.7 2'
            's-1.7.6-1.7 2v1.3c0 1-.4 2.3-2.1 2.3"/>{}',
            "",
        ),
    ),
}


def _filled(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (dict, list, str)):
        return bool(value)
    return True


def _target_label(obj: Any) -> str:
    target = getattr(obj, "target", None)
    if target is None:
        return _EMPTY
    return f"{target.app_label}.{target.model}"


def _badges(model_admin: Any, items: list[tuple[str, str]]) -> str:
    labels = [
        model_admin.format_label(str(text), kind, size="small") for text, kind in items if text
    ]
    if not labels:
        return _EMPTY
    return format_html_join(" ", "{}", ((label,) for label in labels))


def definition_heading(model_admin: Any, obj: Any) -> str:
    """``named_id`` on the first line, human name underneath."""
    return model_admin.format_with_help_text(
        model_admin.format_label(obj.named_id or _EMPTY, "primary", size="small"),
        obj.name,
    )


def model_column(model_admin: Any, obj: Any, *, detail: str = "") -> str:
    """Content type, with an optional detail on the second line."""
    label = model_admin.format_label(_target_label(obj), "info", size="small")
    if not detail:
        return label
    return model_admin.format_with_help_text(label, detail)


def _format_category_badge(category: str, formats: str) -> str:
    return format_html(
        '<span class="boost-label success small" title="{}">{}{}</span>',
        CATEGORY_LABELS.get(category, category),
        _CATEGORY_ICONS.get(category, ""),
        formats,
    )


def output_column(model_admin: Any, obj: Any) -> str:
    direction = getattr(obj, "direction", None) or "export"
    grouped: dict[str, list[str]] = {}
    for spec in formats_for_definition(obj, direction=direction):
        grouped.setdefault(spec.category, []).append(spec.short_label)
    parts = [
        _format_category_badge(category, "/".join(grouped[category]))
        for category in CATEGORY_ORDER
        if category in grouped
    ]
    if not parts:
        return _EMPTY
    return format_html_join(" ", "{}", ((part,) for part in parts))


def filter_column(model_admin: Any, obj: Any) -> str:
    badges: list[tuple[str, str]] = []
    if _filled(getattr(obj, "filter_config", None)):
        badges.append((str(_("Config")), "default"))
    if _filled(getattr(obj, "filter_request", None)):
        badges.append((str(_("Request")), "default"))
    if _filled(getattr(obj, "filter_mandatory", None)):
        badges.append((str(_("Mandatory")), "warning"))
    if _filled(getattr(obj, "order_by", None)):
        badges.append((str(_("Order")), "info"))
    return _badges(model_admin, badges)


def manager_filter_column(model_admin: Any, obj: Any) -> str:
    badges: list[tuple[str, str]] = []
    if _filled(getattr(obj, "manager_kwargs_config", None)):
        badges.append((str(_("Config")), "secondary"))
    if _filled(getattr(obj, "manager_kwargs_request", None)):
        badges.append((str(_("Request")), "secondary"))
    if _filled(getattr(obj, "manager_kwargs_mandatory", None)):
        badges.append((str(_("Mandatory")), "warning"))
    return _badges(model_admin, badges)


def match_column(model_admin: Any, obj: Any) -> str:
    badges: list[tuple[str, str]] = []
    match_fields = obj.match_fields if isinstance(obj.match_fields, list) else []
    if match_fields:
        joined = ", ".join(str(item) for item in match_fields)
        badges.append((f"{_('Match')} {joined}", "success"))
    if obj.exclude_primary_key:
        badges.append((str(_("PK excluded")), "default"))
    else:
        badges.append((str(_("PK included")), "warning"))
    return _badges(model_admin, badges)


def columns_column(model_admin: Any, obj: Any) -> str:
    badges: list[tuple[str, str]] = []
    excluded = obj.columns_exclude if isinstance(obj.columns_exclude, list) else []
    if excluded:
        badges.append((f"{_('Excluded')} {len(excluded)}", "default"))
    if obj.max_relation_hops is not None:
        badges.append((f"{_('Hops')} {obj.max_relation_hops}", "info"))
    return _badges(model_admin, badges)


"""Shared admin logic for JSON report configuration import."""


import logging
from collections.abc import Callable

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.serializers.base import DeserializationError
from django.db import IntegrityError
from django.http import HttpRequest

logger = logging.getLogger(__name__)


def run_json_configuration_import(
    request: HttpRequest,
    form: Any,
    import_fn: Callable[[dict[str, Any]], Any],
    *,
    log_label: str,
) -> Any | None:
    """
    Call ``import_fn(form.import_data)`` and surface errors via messages.

    Returns the imported instance on success, or ``None`` on failure (the view
    should then return ``{"form": form}``).
    """
    try:
        return import_fn(form.import_data)
    except (ValueError, ValidationError) as exc:
        messages.error(request, str(exc))
        return None
    except DeserializationError as exc:
        logger.warning("%s JSON deserialize failed: %s", log_label, exc)
        messages.error(
            request,
            _("Could not read the configuration from this file."),
        )
        return None
    except IntegrityError as exc:
        logger.warning("%s import integrity error: %s", log_label, exc)
        messages.error(
            request,
            _("Import failed: this configuration conflicts with existing data."),
        )
        return None
    except Exception:
        logger.exception("%s failed", log_label)
        messages.error(
            request,
            _("Import failed. Check the file format and try again."),
        )
        return None
