"""Run the effective export or import hook for one format config."""

from __future__ import annotations

import copy
from typing import Any

from django.utils.module_loading import import_string
from django.utils.translation import gettext_lazy as _

from .dataset import ExportDataset, ImportDataset
from .formats import (
    detect_import_format,
    get_export_config,
    get_import_category,
    get_import_config,
    require_format,
)
from .overrides import merge_format_overrides

ExportResult = tuple[bytes, str, str]


def _native_hook_paths() -> set[str]:
    from .formats import registered_formats

    paths: set[str] = set()
    for spec in registered_formats():
        paths.add(spec.default_export_hook)
        paths.add(spec.default_import_hook)
    return paths


def assert_custom_hook_allowed(path: str) -> None:
    """Reject custom hooks outside ``ALLOWED_HOOK_MODULE_PREFIXES`` when that list is set."""
    from django.core.exceptions import ValidationError

    from ...utils.helpers import get_setting

    if path in _native_hook_paths():
        return
    prefixes = get_setting("ALLOWED_HOOK_MODULE_PREFIXES", None)
    if prefixes is None:
        return
    allowed = [str(item) for item in prefixes] if isinstance(prefixes, (list, tuple)) else []
    if any(path == prefix or path.startswith(f"{prefix}.") for prefix in allowed if prefix):
        return
    raise ValidationError(_("Hook %(hook)s is outside the allowed hook modules.") % {"hook": path})


def _load_hook(path: str) -> Any:
    assert_custom_hook_allowed(path)
    hook = import_string(path)
    if not callable(hook):
        raise TypeError(f"Hook {path!r} is not callable.")
    return hook


def build_export_dataset(
    definition: Any,
    filter_payload: dict[str, Any],
    *,
    template_override: str = "",
    configuration_overrides: dict[str, Any] | None = None,
) -> ExportDataset:
    """Load the queryset, columns, and labels once, before the format hook runs."""
    from .export import _bound_export
    from .pdf import PdfEngine
    from .table import TableEngine

    spec = require_format(str(filter_payload.get("export_format") or ""))
    format_config = get_export_config(definition, spec.key)
    category = format_config.get_category()
    proxy, request = _bound_export(definition, filter_payload)
    overrides = copy.deepcopy(configuration_overrides or {"format": {}, "hook": {}})
    payload = dict(filter_payload)
    payload["template_override"] = template_override or ""
    payload["configuration_overrides"] = overrides
    engine: PdfEngine | TableEngine
    if spec.category == "document":
        engine = PdfEngine(
            proxy,
            request=request,
            config=format_config,
            template_override=template_override,
        )
        queryset = engine.get_queryset()
        columns: list[Any] = []
        labels: list[str] = []
    else:
        from .formats import TabularEngineConfig

        effective = merge_format_overrides(
            category.get_effective_configuration(format_config),
            spec.key,
            overrides,
        )
        columns_raw = getattr(category, "columns", None) or []
        view = TabularEngineConfig(
            list(columns_raw) if isinstance(columns_raw, list) else [],
            effective,
        )
        engine = TableEngine(proxy, request=request, config=view)
        queryset = engine.get_queryset()
        columns = engine.get_columns()
        labels = list(engine.get_headers())
    return ExportDataset(
        definition=definition,
        queryset=queryset,
        columns=columns,
        labels=labels,
        category_config=category,
        format_config=format_config,
        payload=payload,
        engine=engine,
    )


def _run_chain(paths: list[str], value: Any, *args: Any) -> Any:
    """Call each hook with the previous return value. ``None`` keeps that value."""
    if not paths:
        raise TypeError("No hook is configured for this format.")
    for path in paths:
        result = _load_hook(path)(value, *args)
        if result is not None:
            value = result
    return value


def run_export_hooks(
    definition: Any,
    filter_payload: dict[str, Any],
    *,
    template_override: str = "",
    configuration_overrides: dict[str, Any] | None = None,
) -> ExportResult:
    """Build the shared export dataset, then run the format's hooks in order."""
    dataset = build_export_dataset(
        definition,
        filter_payload,
        template_override=template_override,
        configuration_overrides=configuration_overrides,
    )
    result = _run_chain(
        dataset.format_config.get_effective_hooks(),
        dataset,
        dataset.category_config,
        dataset.format_config,
        dataset.payload,
    )
    if not isinstance(result, tuple) or len(result) != 3:
        raise TypeError("Export hook must return (bytes, content_type, extension).")
    body, content_type, extension = result
    return body, content_type, extension


def run_import_hook(
    definition: Any,
    file: Any,
    context: dict[str, Any] | None = None,
) -> ImportDataset:
    """Read ``file`` with the format hook selected by extension or MIME type."""
    name = str(context.get("name") or "") if context else ""
    if not name:
        name = getattr(file, "name", "") or ""
    content_type = str(context.get("content_type") or "") if context else ""
    if not content_type:
        content_type = getattr(file, "content_type", "") or ""
    spec = detect_import_format(name, content_type)
    format_config = get_import_config(definition, spec.key)
    category = get_import_category(definition, spec.key)
    dataset = _run_chain(
        format_config.get_effective_hooks(),
        file,
        category,
        format_config,
        dict(context or {}),
    )
    if not isinstance(dataset, ImportDataset):
        raise TypeError("Import hook must return an ImportDataset.")
    return dataset
