"""Run the effective export or import hook for one format config."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

from django.core.exceptions import SuspiciousFileOperation, ValidationError
from django.core.files.utils import validate_file_name
from django.utils.module_loading import import_string
from django.utils.translation import gettext_lazy as _

from .dataset import ExportDataset, ImportDataset, ImportTemplateDataset
from .formats import (
    detect_import_format,
    get_export_config,
    get_import_category,
    get_import_config,
    require_format,
)
from .overrides import merge_format_overrides

if TYPE_CHECKING:
    from ...models import Definition, ExportRequest

ExportResult = tuple[bytes, str, str]


def _native_hook_paths() -> set[str]:
    from .formats import registered_formats

    paths: set[str] = {
        "django_importexport_flow.engine.hooks.native_import_template",
        "django_importexport_flow.engine.hooks.native_combined_import_template",
    }
    for spec in registered_formats():
        paths.add(spec.default_export_hook)
        paths.add(spec.default_import_hook)
    return paths


def assert_custom_hook_allowed(path: str) -> None:
    """Reject custom hooks outside ``ALLOWED_HOOK_MODULE_PREFIXES`` when that list is set."""
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


def _import_template_hook_path(definition: Definition) -> str:
    from ...models import Definition
    from ...utils.process import _example_configuration

    path = _example_configuration(definition).get("template_hook")
    if path is None:
        combined = Definition.objects.has_steps(definition.pk)
        name = "native_combined_import_template" if combined else "native_import_template"
        return f"django_importexport_flow.engine.hooks.{name}"
    if not isinstance(path, str) or not path.strip():
        raise ValueError("template_hook must be a non-empty dotted callable path.")
    return path


def run_import_template_hook(
    definition: Definition,
    context: dict[str, Any] | None = None,
) -> ImportTemplateDataset:
    """Select a template hook using the current steps and validate its schema.

    Args:
        definition: Import definition providing the hook configuration and steps.
        context: Optional generation context passed to the selected hook.

    Returns:
        A validated schema containing canonical columns and localized labels.

    Raises:
        ValueError: If the hook path or returned schema is invalid.
        TypeError: If the hook is not callable or returns the wrong dataset type.
        ValidationError: If a custom hook is outside the configured allowlist.
    """
    result = _load_hook(_import_template_hook_path(definition))(definition, dict(context or {}))
    if not isinstance(result, ImportTemplateDataset):
        raise TypeError("Template hook must return an ImportTemplateDataset.")
    result.validate()
    return result


def default_export_filenames(export_request: ExportRequest, extension: str) -> tuple[str, str]:
    """Return the historical storage and download filenames, respectively."""
    from ...utils.helpers import dated_export_filename, safe_download_stem

    stem = safe_download_stem(export_request.export_definition.name, fallback="export")
    return f"export{extension}", dated_export_filename(stem, extension)


def resolve_export_filenames(export_request: ExportRequest, extension: str) -> tuple[str, str]:
    """Resolve the storage and download names, using a custom hook only once."""
    path = export_request.export_definition.filename_hook
    if not path:
        return default_export_filenames(export_request, extension)

    filename = _load_hook(path)(export_request, extension)
    if (
        not isinstance(filename, str)
        or not filename.strip()
        or "\\" in filename
        or '"' in filename
        or any(ord(char) < 32 or ord(char) == 127 for char in filename)
    ):
        raise ValidationError(_("The filename hook must return a valid basename."))
    try:
        validate_file_name(filename)
    except SuspiciousFileOperation as exc:
        raise ValidationError(_("The filename hook must return a valid basename.")) from exc
    return filename, filename


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
