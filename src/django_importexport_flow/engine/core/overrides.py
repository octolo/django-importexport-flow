"""Request-scoped export options, kept separate from stored format configuration."""

from __future__ import annotations

import copy
from typing import Any

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from .formats import canonical_format_key

ALLOWED_FORMAT_OPTIONS: dict[str, frozenset[str]] = {
    "csv": frozenset({"delimiter"}),
    "excel": frozenset({"sheet", "sheet_name", "split_by"}),
    "json": frozenset({"orient", "indent", "force_ascii"}),
    "pdf": frozenset(),
}


def _option_is_valid(name: str, value: Any) -> bool:
    if name == "delimiter":
        return isinstance(value, str) and len(value) == 1
    if name in {"sheet", "sheet_name", "split_by", "orient"}:
        return isinstance(value, str) and bool(value.strip())
    if name == "indent":
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0
    if name == "force_ascii":
        return isinstance(value, bool)
    return False


def normalize_configuration_overrides(
    value: Any, *, export_format: str
) -> dict[str, dict[str, Any]]:
    """Return ``{"format": ..., "hook": ...}`` or raise ``ValidationError``."""
    if value in (None, ""):
        value = {}
    if not isinstance(value, dict):
        raise ValidationError(_("Configuration overrides must be a JSON object."))
    unknown = sorted(set(value) - {"format", "hook"})
    if unknown:
        raise ValidationError(
            _("Unknown configuration override keys: %(keys)s.") % {"keys": ", ".join(unknown)}
        )
    format_options = value.get("format", {})
    hook_options = value.get("hook", {})
    if not isinstance(format_options, dict) or not isinstance(hook_options, dict):
        raise ValidationError(_("Both 'format' and 'hook' must be JSON objects."))

    key = canonical_format_key(str(export_format or ""))
    allowed = ALLOWED_FORMAT_OPTIONS.get(key, frozenset())
    rejected = sorted(set(format_options) - allowed)
    if rejected:
        raise ValidationError(
            _("Options are not allowed for %(format)s: %(keys)s.")
            % {"format": key or _("an empty format"), "keys": ", ".join(rejected)}
        )
    invalid = sorted(
        name for name, item in format_options.items() if not _option_is_valid(name, item)
    )
    if invalid:
        raise ValidationError(
            _("Invalid values for configuration overrides: %(keys)s.")
            % {"keys": ", ".join(invalid)}
        )
    return {"format": dict(format_options), "hook": dict(hook_options)}


def validate_template_override(value: Any, *, export_format: str) -> str:
    """Return the template text. Blank means the format configuration template."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValidationError(_("Template override must be a string."))
    if not value.strip():
        return ""
    if canonical_format_key(str(export_format or "")) != "pdf":
        raise ValidationError(_("A template override is only valid for PDF exports."))
    return value


def merge_format_overrides(
    effective: dict[str, Any],
    export_format: str,
    overrides: dict[str, Any] | None,
) -> dict[str, Any]:
    """Copy the effective configuration and replace allowed options for one format."""
    merged = copy.deepcopy(effective or {})
    key = canonical_format_key(str(export_format or ""))
    specific = dict(merged.get(key) or {})
    specific.update(dict((overrides or {}).get("format") or {}))
    merged["format"] = dict(specific)
    if key:
        merged[key] = dict(specific)
    if key == "excel" and "split_by" in specific:
        merged["split_by"] = specific["split_by"]
    return merged
