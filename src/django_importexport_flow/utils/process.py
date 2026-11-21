"""Public entry points: process table export and process tabular import."""

from __future__ import annotations

import logging
import traceback
from io import BytesIO, StringIO
from typing import Any, cast

import pandas as pd
from django.http import HttpResponse

from ..engine.core.export import (
    snapshot_export_filter_payload,
    snapshot_export_manager_kwargs_payload,
)
from ..engine.core.hooks import run_export_hooks, run_import_hook
from ..engine.core.import_ import (
    create_import_request,
    effective_import_column_paths,
    sample_headers_for_import_definition,
    validate_import_preview,
)
from ..engine.core.processor import run_import_processor
from ..forms import MAX_TABULAR_IMPORT_BYTES
from ..models import Definition, ExportRequest, ImportRequest
from .helpers import (
    dated_export_filename,
    get_setting,
    normalize_table_column,
    resolve_column_header,
    safe_download_stem,
)
from .http import content_disposition_attachment
from .lookup import (
    get_export_definition_by_uuid_or_named_id,
    get_import_definition_by_uuid_or_named_id,
)
from .translations import language_candidates

logger = logging.getLogger(__name__)


def _resolve_import_definition(
    *,
    import_definition: Definition | None = None,
    import_definition_uuid: str | None = None,
    import_definition_key: str | None = None,
) -> Definition:
    if import_definition is not None:
        return import_definition
    ref = import_definition_key or import_definition_uuid
    if not ref:
        raise ValueError(
            "import_definition or import_definition_key (or import_definition_uuid) is required."
        )
    return get_import_definition_by_uuid_or_named_id(ref)


def _cell_jsonable(value: Any) -> Any:
    if pd.isna(value):
        return ""
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        return iso()
    try:
        import numpy as np

        if isinstance(value, np.generic):
            return value.item()
    except ImportError:
        pass
    return value


def resolved_headers_for_import(definition: Definition, column_paths: list[str]) -> list[str]:
    """Human-readable header labels for import paths (same logic as import preview)."""
    preview_labels = sample_headers_for_import_definition(definition, column_paths=column_paths)
    if len(preview_labels) != len(column_paths):
        target = definition.target
        tgt = target.model_class() if definition.target_id and target is not None else None
        if tgt is not None:
            return [
                resolve_column_header(tgt, normalize_table_column(str(p))) for p in column_paths
            ]
        return [str(p) for p in column_paths]
    return preview_labels


def _validation_dataset(
    df_norm: pd.DataFrame | None,
    column_paths: list[str],
    column_labels: list[str],
    *,
    row_limit: int,
) -> dict[str, Any]:
    labels = column_labels
    if len(labels) != len(column_paths):
        labels = [
            column_labels[i] if i < len(column_labels) else str(column_paths[i])
            for i in range(len(column_paths))
        ]
    columns_meta = [
        {"path": str(p), "label": str(lbl)} for p, lbl in zip(column_paths, labels, strict=False)
    ]
    if df_norm is None or df_norm.empty:
        return {
            "column_paths": list(column_paths),
            "column_labels": labels,
            "columns": columns_meta,
            "rows": [],
            "row_count": 0,
            "preview_row_count": 0,
        }
    row_count = len(df_norm)
    head = df_norm.head(row_limit)
    rows: list[dict[str, Any]] = []
    for _, row in head.iterrows():
        rec: dict[str, Any] = {}
        for p in column_paths:
            key = str(p)
            if key in row.index:
                rec[key] = _cell_jsonable(row[key])
            elif p in row.index:
                rec[key] = _cell_jsonable(row[p])
            else:
                rec[key] = ""
        rows.append(rec)
    return {
        "column_paths": list(column_paths),
        "column_labels": labels,
        "columns": columns_meta,
        "rows": rows,
        "row_count": row_count,
        "preview_row_count": len(rows),
    }


def process_export(
    *,
    filter_payload: dict[str, Any] | None = None,
    export_definition: Definition | None = None,
    export_definition_uuid: str | None = None,
    export_definition_key: str | None = None,
    export_format: str | None = None,
    template_override: str = "",
    configuration_overrides: dict[str, Any] | None = None,
) -> tuple[bytes, str, str]:
    """
    Process a table export (CSV / Excel / JSON) for an :class:`~django_importexport_flow.models.Definition`.

    Pass ``export_definition``, or a lookup string: ``export_definition_key`` (UUID or ``named_id``), or
    ``export_definition_uuid`` (same as ``export_definition_key``, kept for backward compatibility).

    ``filter_payload`` is the export filter dict (``export_format``, ``fr_get_*``, ``fr_kw_*``), e.g. from
    a validated admin form or built by a management command.
    You may set ``export_format`` here or pass it separately as ``export_format``.
    """
    definition = export_definition
    if definition is None:
        ref = export_definition_key or export_definition_uuid
        if not ref:
            raise ValueError(
                "export_definition or export_definition_key (or export_definition_uuid) is required."
            )
        definition = get_export_definition_by_uuid_or_named_id(ref)
    data = dict(filter_payload or {})
    if export_format is not None:
        data["export_format"] = export_format
    if "export_format" not in data:
        raise ValueError("export_format must be set in filter_payload or as export_format=…")
    from ..engine.core.overrides import (
        normalize_configuration_overrides,
        validate_template_override,
    )

    selected_format = str(data.get("export_format") or "")
    return run_export_hooks(
        definition,
        data,
        template_override=validate_template_override(
            template_override,
            export_format=selected_format,
        ),
        configuration_overrides=normalize_configuration_overrides(
            configuration_overrides,
            export_format=selected_format,
        ),
    )


def process_import(
    *,
    file: Any,
    import_definition: Definition | None = None,
    import_definition_uuid: str | None = None,
    import_definition_key: str | None = None,
    user: Any | None = None,
    filter_payload: dict[str, Any] | None = None,
    inferred_column_paths: list[str] | None = None,
    preview_only: bool = False,
    max_bytes: int | None = None,
    preview_row_limit: int | None = None,
    run_async: bool = False,
    related_object: Any | None = None,
) -> dict[str, Any]:
    """
    Validate and optionally process a tabular import for an :class:`~django_importexport_flow.models.Definition`.

    Pass ``import_definition``, or ``import_definition_key`` (UUID or ``named_id``), or
    ``import_definition_uuid`` (same as ``import_definition_key``, backward compatible).

    * ``preview_only=True``: same pipeline as :func:`validate_import` — returns ``errors``,
      ``warnings``, ``column_paths``, ``dataframe``, and ``validation_dataset``.
    * ``preview_only=False``: create an :class:`~django_importexport_flow.models.ImportRequest`,
      store the upload, run the import; returns ``import_request``, ``success`` (bool), and
      ``queued`` (bool) when ``run_async=True`` and ``IMPORT_TASK_BACKEND`` is not ``sync``.
    * Optional ``related_object``: bound on the :class:`~django_importexport_flow.models.ImportRequest`
      generic FK for scoping (tenant, etc.); see :meth:`ImportRequest.active_imports_for_object`.
    """
    definition = _resolve_import_definition(
        import_definition=import_definition,
        import_definition_uuid=import_definition_uuid,
        import_definition_key=import_definition_key,
    )

    limit = max_bytes if max_bytes is not None else MAX_TABULAR_IMPORT_BYTES

    if preview_only:
        return validate_import(
            file=file,
            import_definition=definition,
            max_bytes=limit,
            row_limit=preview_row_limit,
            user=user,
            filter_payload=filter_payload,
        )

    ask = create_import_request(
        definition,
        file,
        dict(filter_payload or {}),
        user,
        inferred_column_paths=inferred_column_paths,
        related_object=related_object,
        trigger_processing=True,
        asynchronous=run_async,
    )
    ask.refresh_from_db()
    queued = ask.status == ImportRequest.Status.PROCESSING
    return {
        "import_request": ask,
        "success": ask.status == ImportRequest.Status.SUCCESS,
        "queued": queued,
    }


def validate_import(
    *,
    file: Any | None = None,
    dataframe: pd.DataFrame | None = None,
    import_definition: Definition | None = None,
    import_definition_uuid: str | None = None,
    import_definition_key: str | None = None,
    max_bytes: int | None = None,
    row_limit: int | None = None,
    user: Any | None = None,
    filter_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Validate tabular data against an :class:`~django_importexport_flow.models.Definition`,
    and build a **validation dataset**: column paths, human labels, and preview rows.

    Pass either ``file`` (uploaded file / file-like) or ``dataframe`` (already parsed).
    When using a file, ``user`` and ``filter_payload`` are passed to an optional
    category processor. Passing a dataframe always uses generic validation.

    This wraps :func:`~django_importexport_flow.engine.core.import_.validate_import_preview` and adds
    ``validation_dataset`` with ``rows`` (up to ``row_limit``, default from setting
    ``IMPORT_PREVIEW_ROW_LIMIT``), ``row_count``, and ``preview_row_count``.

    Returns ``errors``, ``warnings``, ``column_paths``, ``dataframe`` (normalized or ``None``),
    and ``validation_dataset``. When validation fails before normalization, ``dataframe`` is
    ``None`` and ``validation_dataset`` has empty ``rows``.
    """
    definition = _resolve_import_definition(
        import_definition=import_definition,
        import_definition_uuid=import_definition_uuid,
        import_definition_key=import_definition_key,
    )
    limit = max_bytes if max_bytes is not None else MAX_TABULAR_IMPORT_BYTES
    preview_cap = (
        row_limit if row_limit is not None else int(get_setting("IMPORT_PREVIEW_ROW_LIMIT"))
    )

    if dataframe is not None:
        df = dataframe
    elif file is not None:
        result = run_import_processor(
            definition,
            file,
            user=user,
            filter_payload=filter_payload,
            preview_only=True,
            max_bytes=limit,
        )
        if result is not None:
            frame = result.dataframe
            paths = result.column_paths or (
                [str(column) for column in frame.columns] if frame is not None else []
            )
            if frame is None:
                frame = pd.DataFrame(columns=paths)
            preview = _validation_dataset(
                frame, paths, resolved_headers_for_import(definition, paths), row_limit=preview_cap
            )
            if result.row_count is not None:
                preview["row_count"] = result.row_count
            return {
                "errors": result.errors,
                "warnings": result.warnings,
                "column_paths": paths,
                "dataframe": frame,
                "row_count": preview["row_count"],
                "validation_dataset": preview,
            }
        dataset = run_import_hook(
            definition,
            file,
            {
                "max_bytes": limit,
                "name": getattr(file, "name", "") or "",
                "content_type": getattr(file, "content_type", "") or "",
            },
        )
        df = dataset.dataframe
    else:
        raise ValueError("validate_import requires file= or dataframe=.")

    errs, warns, paths, df_norm = validate_import_preview(df, definition)
    labels = resolved_headers_for_import(definition, paths) if paths else []
    vds = _validation_dataset(df_norm, paths, labels, row_limit=preview_cap)
    return {
        "errors": errs,
        "warnings": warns,
        "column_paths": paths,
        "dataframe": df_norm,
        "validation_dataset": vds,
    }


def run_export_with_audit(
    *,
    export_definition: Definition,
    filter_payload: dict[str, Any],
    user: Any | None,
    template_override: str = "",
    configuration_overrides: dict[str, Any] | None = None,
) -> tuple[bytes, str, str]:
    """
    Run a table export and persist an :class:`~django_importexport_flow.models.ExportRequest`
    audit row (success or failure).

    The export hooks produce the file. This function persists the result in
    ``ExportRequest.output_file`` on success and preserves the original exception
    type so callers (e.g. the admin) can distinguish
    :exc:`~django.core.exceptions.ValidationError`, :exc:`ValueError`,
    :exc:`OSError`, :exc:`MemoryError`, etc.
    """
    from ..engine.core.overrides import (
        normalize_configuration_overrides,
        validate_template_override,
    )
    from ..engine.core.processing import (
        _build_er_filter_payload,
        _finalize_native_export,
        _mark_request_failure,
    )

    payload = snapshot_export_filter_payload(filter_payload)
    mgr_payload = snapshot_export_manager_kwargs_payload(filter_payload)
    export_fmt = str(filter_payload.get("export_format") or "")
    template_override = validate_template_override(template_override, export_format=export_fmt)
    configuration_overrides = normalize_configuration_overrides(
        configuration_overrides,
        export_format=export_fmt,
    )

    er = ExportRequest(
        export_definition=export_definition,
        export_format=export_fmt,
        filter_payload=payload,
        manager_kwargs_payload=mgr_payload,
        template_override=template_override,
        configuration_overrides=configuration_overrides,
        status=cast("str", ExportRequest.Status.PROCESSING),
        initiated_by=user,
    )
    er.save()

    try:
        content, content_type, ext = run_export_hooks(
            export_definition,
            _build_er_filter_payload(er),
            template_override=er.template_override,
            configuration_overrides=er.configuration_overrides,
        )
    except Exception:
        _mark_request_failure(er, traceback.format_exc())
        raise
    _finalize_native_export(er, content, ext)
    return content, content_type, ext


def _import_csv_delimiter(import_definition: Definition) -> str:
    from ..engine.core.formats import get_import_config

    try:
        config = get_import_config(import_definition, "csv")
    except ValueError:
        config = None
    raw = (
        config.configuration
        if config is not None and isinstance(config.configuration, dict)
        else {}
    )
    delim = raw.get("delimiter", ",")
    if not isinstance(delim, str) or len(delim) != 1:
        return ","
    return delim


def _example_configuration(definition: Definition) -> dict[str, Any]:
    category = definition.category_configs.filter(category_key="spreadsheet").first()
    configuration = category.configuration if category else None
    return configuration if isinstance(configuration, dict) else {}


def _localized_example_value(values: object) -> object | None:
    if isinstance(values, dict):
        for language in language_candidates():
            if values.get(language):
                return values[language]
    return None


def _configured_example_columns(configuration: dict[str, Any]) -> list[str]:
    columns = configuration.get("template_columns")
    if columns is None or columns == []:
        return []
    if not isinstance(columns, list) or not all(
        isinstance(column, str) and column.strip() for column in columns
    ):
        raise ValueError("template_columns must be a list of non-empty strings.")
    return columns


def _validate_example_labels(labels: object, columns: list[str]) -> list[str]:
    if (
        not isinstance(labels, list)
        or len(labels) != len(columns)
        or not all(isinstance(label, str) for label in labels)
    ):
        raise ValueError("Template labels must provide one string per template column.")
    return labels


def _template_header_aliases(configuration: dict[str, Any], columns: list[str]) -> dict[str, str]:
    aliases = {column.strip(): column for column in columns}
    if len(aliases) != len(columns):
        raise ValueError("Template column keys must be unique.")
    translated = configuration.get("template_labels_by_language", {})
    if not isinstance(translated, dict):
        raise ValueError(  # noqa: TRY004 - invalid template configuration is a ValueError
            "template_labels_by_language must map languages to label lists."
        )
    for labels in (configuration.get("template_labels") or columns, *translated.values()):
        for label, column in zip(_validate_example_labels(labels, columns), columns, strict=True):
            key = label.strip()
            if not key or aliases.setdefault(key, column) != column:
                raise ValueError(f"Empty or ambiguous template header: {label!r}.")
    return aliases


def normalize_template_headers(definition: Definition, frame: pd.DataFrame) -> pd.DataFrame:
    """Map template aliases to processor keys in any configured language.

    Args:
        definition: Import definition providing template columns and aliases.
        frame: Parsed spreadsheet, with headers taken from its first row.

    Returns:
        A dataframe with canonical template keys and unrecognized headers unchanged.

    Raises:
        ValueError: If configured aliases or matched spreadsheet headers are ambiguous.
    """
    configuration = _example_configuration(definition)
    columns = _configured_example_columns(configuration)
    if not columns:
        return frame
    aliases = _template_header_aliases(configuration, columns)
    header_keys = {str(header).strip() for header in frame.columns}
    seen: set[str] = set()
    headers: list[Any] = []
    for header in frame.columns:
        key = str(header).strip()
        column = aliases.get(key)
        if column is None:
            # Pandas appends numeric suffixes when a physical header is repeated.
            base, _, suffix = key.rpartition(".")
            base = base.strip()
            if suffix.isdecimal() and base in aliases and base in header_keys:
                raise ValueError(f"Duplicate template header: {header!r}.")
            headers.append(header)
            continue
        if column in seen:
            raise ValueError(f"Multiple headers map to template column {column!r}.")
        seen.add(column)
        headers.append(column)
    return frame.set_axis(headers, axis="columns")


def _example_spreadsheet(
    definition: Definition,
    configuration: dict[str, Any],
    paths: list[str],
    configured_paths: list[str],
) -> pd.DataFrame:
    localized = configuration.get("template_header_mode") == "localized"
    if localized:
        if not configured_paths:
            raise ValueError("Localized template headers require template_columns.")
        _template_header_aliases(configuration, paths)
    if configured_paths:
        raw_labels = _localized_example_value(configuration.get("template_labels_by_language"))
        if raw_labels is None:
            raw_labels = configuration.get("template_labels") or paths
        labels = _validate_example_labels(raw_labels, paths)
    else:
        labels = sample_headers_for_import_definition(definition, column_paths=paths)
    blank = [""] * len(paths)
    rows = [blank] if localized else [labels, blank]
    return pd.DataFrame(rows if paths else [], columns=labels if localized else paths)


def generate_example_file(
    import_definition: Definition,
    *,
    example_format: str,
) -> tuple[bytes, str, str]:
    """Build an example import file from configured columns or model paths.

    Args:
        import_definition: Definition providing the template configuration.
        example_format: One of ``csv``, ``excel``, or ``json``.

    Returns:
        File bytes, MIME type, and extension including the leading dot.

    Raises:
        ValueError: If the format or template columns and labels are invalid.
    """
    configuration = _example_configuration(import_definition)
    configured_paths = _configured_example_columns(configuration)
    paths = configured_paths or effective_import_column_paths(import_definition)

    if example_format == "json":
        df = pd.DataFrame([{p: "" for p in paths}])
        body = df.to_json(orient="records", indent=2, force_ascii=False).encode("utf-8")
        return (
            body,
            "application/json; charset=utf-8",
            ".json",
        )

    frame = _example_spreadsheet(import_definition, configuration, paths, configured_paths)

    if example_format == "csv":
        delim = _import_csv_delimiter(import_definition)
        buffer = StringIO()
        frame.to_csv(buffer, index=False, sep=delim)
        return (
            buffer.getvalue().encode("utf-8"),
            "text/csv; charset=utf-8",
            ".csv",
        )

    if example_format == "excel":
        stream = BytesIO()
        frame.to_excel(stream, index=False, sheet_name="Sheet1", engine="openpyxl")
        return (
            stream.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".xlsx",
        )

    raise ValueError(f"example_format must be csv, excel, or json; got {example_format!r}.")


def import_example_download_response(
    definition: Definition,
    *,
    example_format: str,
    fallback_name: str | None = None,
    dated: bool = False,
) -> HttpResponse:
    """Generate a template attachment using the active language.

    Args:
        definition: Definition providing the template and filename configuration.
        example_format: One of ``csv``, ``excel``, or ``json``.
        fallback_name: Filename stem to use instead of the definition name.
        dated: Whether to append a timestamp before the extension.

    Returns:
        A downloadable HTTP response with a safe filename.

    Raises:
        ValueError: If the format or template configuration is invalid.
    """
    body, content_type, ext = generate_example_file(definition, example_format=example_format)
    names = _example_configuration(definition).get("template_filename")
    name = _localized_example_value(names)
    if name is not None and not isinstance(name, str):
        raise ValueError("A localized template filename must be a string.")
    stem = safe_download_stem(name or fallback_name or definition.name, fallback="example")
    filename = dated_export_filename(stem, ext) if dated else f"{stem}{ext}"
    response = HttpResponse(body, content_type=content_type)
    response["Content-Disposition"] = content_disposition_attachment(filename)
    return response
