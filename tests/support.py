"""Helpers that attach category and format configs."""

from __future__ import annotations

from typing import Any

from django_importexport_flow.models import CategoryConfig, Definition, FormatConfig


def split_legacy_table_configuration(
    configuration: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    raw = dict(configuration or {})
    csv_options = dict(raw.pop("csv", {}) or {})
    excel_options = dict(raw.pop("excel", {}) or {})
    json_options = dict(raw.pop("json", {}) or {})
    for key in ("xml", "pdf", "xls", "xlsx", "ods", "docx", "word"):
        raw.pop(key, None)
    if "split_by" in raw:
        excel_options["split_by"] = raw.pop("split_by")
    return raw, csv_options, excel_options, json_options


def _category(definition: Definition, category_key: str, **fields: Any) -> CategoryConfig:
    return CategoryConfig.objects.create(
        definition=definition,
        category_key=category_key,
        **fields,
    )


def _format(category: CategoryConfig, format_key: str, **fields: Any) -> FormatConfig:
    return FormatConfig.objects.create(
        category_config=category,
        format_key=format_key,
        **fields,
    )


def attach_tabular_export(
    export,
    columns: list[Any] | None = None,
    configuration: dict[str, Any] | None = None,
    *,
    formats: tuple[str, ...] = ("csv", "excel", "json"),
):
    """Create spreadsheet and/or structured-data configs."""
    common, csv_options, excel_options, json_options = split_legacy_table_configuration(
        configuration
    )
    selected = set(formats)
    sheet = None
    if selected & {"csv", "excel"}:
        sheet = _category(
            export,
            "spreadsheet",
            columns=list(columns or []),
            configuration=common,
        )
        if "csv" in selected:
            _format(sheet, "csv", configuration=csv_options)
        if "excel" in selected:
            _format(sheet, "excel", configuration=excel_options)
    if "json" in selected:
        data = _category(
            export,
            "structured_data",
            columns=list(columns or []),
            configuration=dict(common),
        )
        _format(data, "json", configuration=json_options)
    return sheet


def attach_pdf_export(
    export,
    template: str | None = "",
    configuration: dict[str, Any] | None = None,
):
    document = _category(export, "document", columns=[], configuration={})
    return _format(
        document,
        "pdf",
        template=template or "",
        configuration=dict(configuration or {}),
    )


def attach_import_spreadsheet(
    definition,
    configuration: dict[str, Any] | None = None,
):
    """Activate CSV and Excel import. ``configuration`` is the legacy combined dict."""
    common, csv_options, excel_options, _json = split_legacy_table_configuration(configuration)
    sheet = _category(definition, "spreadsheet", columns=[], configuration=common)
    _format(sheet, "csv", configuration=csv_options)
    _format(sheet, "excel", configuration=excel_options)
    return sheet
