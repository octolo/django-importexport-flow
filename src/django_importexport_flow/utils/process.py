"""Public entry points: process table export and process tabular import."""

from __future__ import annotations

import logging
import traceback
from io import BytesIO, StringIO
from typing import Any

import pandas as pd
from django.core.exceptions import ValidationError
from django.utils import timezone

from ..engine.core.export import (
    run_table_export,
    snapshot_export_filter_payload,
    snapshot_export_manager_kwargs_payload,
)
from ..engine.core.import_ import (
    create_import_request,
    effective_import_column_paths,
    read_uploaded_file,
    sample_headers_for_import_definition,
    validate_import_preview,
)
from ..task import dispatch_import_request
from ..forms import MAX_TABULAR_IMPORT_BYTES
from ..models import ExportDefinition, ExportRequest, ImportDefinition, ImportRequest
from ..utils.helpers import get_setting, normalize_table_column, resolve_table_column_label
from .lookup import (
    get_export_definition_by_uuid_or_named_id,
    get_import_definition_by_uuid_or_named_id,
)

logger = logging.getLogger(__name__)


def _resolve_import_definition(
    *,
    import_definition: ImportDefinition | None = None,
    import_definition_uuid: str | None = None,
    import_definition_key: str | None = None,
) -> ImportDefinition:
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


def column_labels_for_import_definition(
    definition: ImportDefinition, column_paths: list[str]
) -> list[str]:
    """Human-readable header labels for import paths (same logic as import preview)."""
    preview_labels = sample_headers_for_import_definition(definition, column_paths=column_paths)
    if len(preview_labels) != len(column_paths):
        tgt = definition.target.model_class() if definition.target_id else None
        if tgt is not None:
            return [
                resolve_table_column_label(tgt, normalize_table_column(str(p)))
                for p in column_paths
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
    export_definition: ExportDefinition | None = None,
    export_definition_uuid: str | None = None,
    export_definition_key: str | None = None,
    export_format: str | None = None,
) -> tuple[bytes, str, str]:
    """
    Process a table export (CSV / Excel / JSON) for an :class:`~django_importexport_flow.models.ExportDefinition`.

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
    return run_table_export(definition, data)


def process_import(
    *,
    file: Any,
    import_definition: ImportDefinition | None = None,
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
    Validate and optionally process a tabular import for an :class:`~django_importexport_flow.models.ImportDefinition`.

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
        )

    ask = create_import_request(
        definition,
        file,
        dict(filter_payload or {}),
        user,
        inferred_column_paths=inferred_column_paths,
        related_object=related_object,
    )
    dispatch_import_request(ask, asynchronous=run_async)
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
    import_definition: ImportDefinition | None = None,
    import_definition_uuid: str | None = None,
    import_definition_key: str | None = None,
    max_bytes: int | None = None,
    row_limit: int | None = None,
) -> dict[str, Any]:
    """
    Validate tabular data against an :class:`~django_importexport_flow.models.ImportDefinition`,
    and build a **validation dataset**: column paths, human labels, and preview rows.

    Pass either ``file`` (uploaded file / file-like) or ``dataframe`` (already parsed).

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
        df = read_uploaded_file(file, limit)
    else:
        raise ValueError("validate_import requires file= or dataframe=.")

    errs, warns, paths, df_norm = validate_import_preview(df, definition)
    labels = column_labels_for_import_definition(definition, paths) if paths else []
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
    export_definition: ExportDefinition,
    filter_payload: dict[str, Any],
    user: Any | None,
) -> tuple[bytes, str, str]:
    """
    Run :func:`process_export` with the same ``filter_payload``, and persist an
    :class:`~django_importexport_flow.models.ExportRequest` (success or failure).

    Re-raises :exc:`~django.core.exceptions.ValidationError`, :exc:`ValueError`, or any
    exception after recording the failure.
    """
    payload = snapshot_export_filter_payload(filter_payload)
    mgr_payload = snapshot_export_manager_kwargs_payload(filter_payload)
    export_fmt = str(filter_payload.get("export_format") or "")
    try:
        content, content_type, ext = process_export(
            export_definition=export_definition,
            filter_payload=filter_payload,
        )
    except (ValidationError, ValueError) as exc:
        logger.warning(
            "Table export validation failed for export definition %r: %s",
            getattr(export_definition, "pk", None),
            exc,
        )
        ExportRequest.objects.create(
            export_definition=export_definition,
            export_format=export_fmt,
            filter_payload=payload,
            manager_kwargs_payload=mgr_payload,
            status=ExportRequest.Status.FAILURE,
            error_trace=str(exc),
            completed_at=timezone.now(),
            initiated_by=user,
        )
        raise
    except Exception:
        logger.exception(
            "Table export failed for export definition %r",
            getattr(export_definition, "pk", None),
        )
        ExportRequest.objects.create(
            export_definition=export_definition,
            export_format=export_fmt,
            filter_payload=payload,
            manager_kwargs_payload=mgr_payload,
            status=ExportRequest.Status.FAILURE,
            error_trace=traceback.format_exc(),
            completed_at=timezone.now(),
            initiated_by=user,
        )
        raise
    ExportRequest.objects.create(
        export_definition=export_definition,
        export_format=export_fmt,
        filter_payload=payload,
        manager_kwargs_payload=mgr_payload,
        status=ExportRequest.Status.SUCCESS,
        output_bytes=len(content),
        completed_at=timezone.now(),
        initiated_by=user,
    )
    return content, content_type, ext


def generate_example_file(
    import_definition: ImportDefinition,
    *,
    example_format: str,
) -> tuple[bytes, str, str]:
    """
    Build an empty **example** import file (headers + blank row) for a definition.

    ``example_format`` is ``"csv"``, ``"excel"``, or ``"json"`` (same as admin export format choices).

    Returns ``(body_bytes, content_type, extension)`` where ``extension`` includes the leading dot
    (e.g. ``".csv"``).
    """
    paths = effective_import_column_paths(import_definition)
    labels = sample_headers_for_import_definition(import_definition, column_paths=paths)

    if example_format == "json":
        df = pd.DataFrame([{p: "" for p in paths}])
        body = df.to_json(orient="records", indent=2, force_ascii=False).encode("utf-8")
        return (
            body,
            "application/json; charset=utf-8",
            ".json",
        )

    if example_format == "csv":
        delim = (import_definition.configuration or {}).get("csv", {}).get("delimiter", ",")
        if not isinstance(delim, str) or len(delim) != 1:
            delim = ","
        buffer = StringIO()
        df_csv = (
            pd.DataFrame([labels, [""] * len(paths)], columns=paths)
            if paths
            else pd.DataFrame(columns=paths)
        )
        df_csv.to_csv(buffer, index=False, sep=delim)
        return (
            buffer.getvalue().encode("utf-8"),
            "text/csv; charset=utf-8",
            ".csv",
        )

    if example_format == "excel":
        stream = BytesIO()
        df_xlsx = (
            pd.DataFrame([labels, [""] * len(paths)], columns=paths)
            if paths
            else pd.DataFrame(columns=paths)
        )
        df_xlsx.to_excel(stream, index=False, sheet_name="Sheet1", engine="openpyxl")
        return (
            stream.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".xlsx",
        )

    raise ValueError(f"example_format must be csv, excel, or json; got {example_format!r}.")
