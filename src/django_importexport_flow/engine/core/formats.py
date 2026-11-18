"""Registry of import and export formats, and lookup of the config that activates one."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from django.utils.translation import gettext_lazy as _

DOCUMENT = "document"
SPREADSHEET = "spreadsheet"
STRUCTURED_DATA = "structured_data"
STRUCTURED = STRUCTURED_DATA

CATEGORY_LABELS = {
    DOCUMENT: _("Document"),
    SPREADSHEET: _("Spreadsheet"),
    STRUCTURED_DATA: _("Structured data"),
}
CATEGORY_ORDER = (DOCUMENT, SPREADSHEET, STRUCTURED_DATA)

_EXTENSIONS = {
    ".csv": "csv",
    ".xlsx": "excel",
    ".xls": "excel",
    ".json": "json",
    ".xml": "xml",
    ".ods": "ods",
    ".pdf": "pdf",
    ".docx": "docx",
}
_MIME = {
    "text/csv": "csv",
    "application/json": "json",
    "application/xml": "xml",
    "text/xml": "xml",
    "application/pdf": "pdf",
    "application/vnd.ms-excel": "excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "excel",
    "application/vnd.oasis.opendocument.spreadsheet": "ods",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}
_UNTYPED_SUFFIXES = {"", ".dat", ".txt", ".bin"}


@dataclass(frozen=True)
class ExportFormat:
    """One file format: category, media type, native hooks, and where its config lives."""

    key: str
    category: str
    label: Any
    short_label: str
    content_type: str
    extension: str
    generator: str
    default_export_hook: str
    default_import_hook: str

    def generate(self, dataset: Any) -> bytes:
        from django.utils.module_loading import import_string

        if not self.generator:
            raise ValueError(f"Format {self.key!r} has no generator.")
        return import_string(self.generator)(dataset)


def _export_hook(name: str) -> str:
    return f"django_importexport_flow.engine.hooks.{name}"


def _import_hook(name: str) -> str:
    return f"django_importexport_flow.engine.hooks.{name}"


_FORMATS: dict[str, ExportFormat] = {
    spec.key: spec
    for spec in (
        ExportFormat(
            key="pdf",
            category=DOCUMENT,
            label=_("PDF"),
            short_label="PDF",
            content_type="application/pdf",
            extension=".pdf",
            generator="django_importexport_flow.engine.hooks.generate_pdf",
            default_export_hook=_export_hook("native_pdf_export"),
            default_import_hook="",
        ),
        ExportFormat(
            key="csv",
            category=SPREADSHEET,
            label="CSV",
            short_label="CSV",
            content_type="text/csv; charset=utf-8",
            extension=".csv",
            generator="django_importexport_flow.engine.hooks.generate_csv",
            default_export_hook=_export_hook("native_csv_export"),
            default_import_hook=_import_hook("native_csv_import"),
        ),
        ExportFormat(
            key="excel",
            category=SPREADSHEET,
            label=_("Excel (.xlsx)"),
            short_label="XLSX",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            extension=".xlsx",
            generator="django_importexport_flow.engine.hooks.generate_excel",
            default_export_hook=_export_hook("native_excel_export"),
            default_import_hook=_import_hook("native_excel_import"),
        ),
        ExportFormat(
            key="json",
            category=STRUCTURED_DATA,
            label="JSON",
            short_label="JSON",
            content_type="application/json; charset=utf-8",
            extension=".json",
            generator="django_importexport_flow.engine.hooks.generate_json",
            default_export_hook=_export_hook("native_json_export"),
            default_import_hook="",
        ),
    )
}
_ALIASES = {"xlsx": "excel"}


class TabularEngineConfig:
    """Columns plus a merged configuration dict consumed by :class:`TableEngine`."""

    def __init__(self, columns: list[Any], configuration: dict[str, Any]) -> None:
        self.columns = columns
        self.configuration = configuration


def canonical_format_key(key: str) -> str:
    cleaned = (key or "").strip().lower()
    return _ALIASES.get(cleaned, cleaned)


def get_format(key: str) -> ExportFormat | None:
    return _FORMATS.get(canonical_format_key(key))


def require_format(key: str) -> ExportFormat:
    spec = get_format(key)
    if spec is None:
        raise ValueError(f"Unknown format {key!r}.")
    return spec


def registered_formats() -> list[ExportFormat]:
    return list(_FORMATS.values())


def media_for_format(key: str) -> tuple[str, str]:
    spec = require_format(key)
    return spec.content_type, spec.extension


def _cached_related(obj: Any, name: str) -> list[Any]:
    cache = getattr(obj, "_prefetched_objects_cache", None)
    if isinstance(cache, dict) and name in cache:
        return [item for item in cache[name] if getattr(item, "pk", None)]
    related = getattr(obj, name, None)
    if related is None:
        return []
    return [item for item in related.all() if getattr(item, "pk", None)]


def _require_direction(definition: Any, direction: str) -> None:
    actual = getattr(definition, "direction", None)
    if actual != direction:
        raise ValueError(f"Definition is not an {direction} definition.")


def _category_for(definition: Any, category_key: str) -> Any | None:
    for category in _cached_related(definition, "category_configs"):
        if category.category_key == category_key:
            return category
    return None


def _format_for(category: Any, format_key: str) -> Any | None:
    for config in _cached_related(category, "format_configs"):
        if config.format_key == format_key:
            return config
    return None


def enabled_format_keys() -> list[str]:
    """Format keys that have a native export hook."""
    return [spec.key for spec in _FORMATS.values() if spec.default_export_hook]


def _disabled(direction: str, format_key: str) -> ValueError:
    return ValueError(
        f"{direction.capitalize()} format {format_key!r} is not enabled for this definition."
    )


def get_export_category(definition: Any, format_key: str) -> Any:
    spec = require_format(format_key)
    if not spec.default_export_hook:
        raise ValueError(f"Format {spec.key!r} cannot be used for export.")
    _require_direction(definition, "export")
    category = _category_for(definition, spec.category)
    if category is None:
        raise _disabled("export", spec.key)
    return category


def get_export_config(definition: Any, format_key: str) -> Any:
    spec = require_format(format_key)
    category = get_export_category(definition, format_key)
    config = _format_for(category, spec.key)
    if config is None:
        raise _disabled("export", spec.key)
    return config


def get_import_category(definition: Any, format_key: str) -> Any:
    spec = require_format(format_key)
    if not spec.default_import_hook:
        raise ValueError(f"Format {spec.key!r} cannot be used for import.")
    _require_direction(definition, "import")
    category = _category_for(definition, spec.category)
    if category is None:
        raise _disabled("import", spec.key)
    return category


def get_import_config(definition: Any, format_key: str) -> Any:
    spec = require_format(format_key)
    category = get_import_category(definition, format_key)
    config = _format_for(category, spec.key)
    if config is None:
        raise _disabled("import", spec.key)
    return config


def formats_for_definition(definition: Any, *, direction: str = "export") -> list[ExportFormat]:
    """Formats whose concrete config exists on ``definition``."""
    found: list[ExportFormat] = []
    getter = get_export_config if direction == "export" else get_import_config
    for spec in _FORMATS.values():
        if direction == "export" and not spec.default_export_hook:
            continue
        if direction == "import" and not spec.default_import_hook:
            continue
        try:
            getter(definition, spec.key)
        except ValueError:
            continue
        found.append(spec)
    return found


def grouped_format_choices(
    definition: Any, *, direction: str = "export"
) -> list[tuple[Any, list[tuple[str, Any]]]]:
    """Optgroups ``(category label, [(format key, format label), ...])``."""
    groups: dict[str, list[tuple[str, Any]]] = {}
    for spec in formats_for_definition(definition, direction=direction):
        groups.setdefault(spec.category, []).append((spec.key, spec.label))
    return [
        (CATEGORY_LABELS[category], groups[category])
        for category in CATEGORY_ORDER
        if category in groups
    ]


def categories_for_definition(definition: Any) -> list[str]:
    return list(dict.fromkeys(spec.category for spec in formats_for_definition(definition)))


def active_format_labels(definition: Any, *, direction: str = "export") -> list[tuple[str, str]]:
    """``(category label, "PDF")`` or ``(category label, "CSV/XLSX")`` for active formats."""
    grouped: dict[str, list[str]] = {}
    for spec in formats_for_definition(definition, direction=direction):
        grouped.setdefault(spec.category, []).append(spec.short_label)
    return [
        (str(CATEGORY_LABELS[category]), "/".join(grouped[category]))
        for category in CATEGORY_ORDER
        if category in grouped
    ]


def iter_active_format_configs(definition: Any) -> list[Any]:
    configs: list[Any] = []
    direction = getattr(definition, "direction", None) or "export"
    getter = get_import_config if direction == "import" else get_export_config
    for spec in formats_for_definition(definition, direction=direction):
        try:
            configs.append(getter(definition, spec.key))
        except ValueError:
            continue
    return configs


def detect_import_format(name: str, content_type: str = "") -> ExportFormat:
    """Pick the import format from the file extension, then the MIME type."""
    base = os.path.basename(name or "")
    ext = ""
    if "." in base:
        ext = "." + base.rsplit(".", 1)[-1].lower()
    key = _EXTENSIONS.get(ext)
    if key is None and content_type:
        mime = content_type.split(";", 1)[0].strip().lower()
        key = _MIME.get(mime)
    if key is None and ext in _UNTYPED_SUFFIXES:
        key = "csv"
    if key is None:
        raise ValueError(f"Unsupported import file {name or ''!r}.")
    spec = get_format(key)
    if spec is None or not spec.default_import_hook:
        raise ValueError(f"Import format {key!r} is not available.")
    return spec


def _merge_format_configuration(config: Any, merged: dict[str, Any]) -> None:
    format_key = getattr(config, "format_key", "") or ""
    specific = config.configuration if isinstance(config.configuration, dict) else {}
    specific = dict(specific)
    if format_key:
        merged[format_key] = specific
    if format_key == "excel" and "split_by" in specific:
        merged["split_by"] = specific["split_by"]


def tabular_engine_config(definition: Any) -> TabularEngineConfig | None:
    """Columns and format options for a :class:`TableEngine` built from the definition alone."""
    columns: list[Any] | None = None
    configuration: dict[str, Any] = {}
    for category_key in (SPREADSHEET, STRUCTURED_DATA):
        category = _category_for(definition, category_key)
        if category is None:
            continue
        if columns is None:
            raw_columns = getattr(category, "columns", None) or []
            columns = list(raw_columns) if isinstance(raw_columns, list) else []
        common = category.configuration if isinstance(category.configuration, dict) else {}
        for key, value in common.items():
            configuration.setdefault(key, value)
        for config in _cached_related(category, "format_configs"):
            _merge_format_configuration(config, configuration)
    if columns is None:
        return None
    return TabularEngineConfig(columns, configuration)
