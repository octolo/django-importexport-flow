"""Create, execute, and relaunch :class:`~django_importexport_flow.models.ImportRequest`."""

from __future__ import annotations

import os
import traceback
from typing import Any

import pandas as pd
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from ...utils.helpers import get_setting
from .export import collect_dynamic_filter_kwargs
from .io import read_import_filefield
from .items import (
    _apply_slot_relations,
    _scalar_model_kwargs,
    import_row_slots_need_post_create,
)
from .paths import IMPORT_COLUMN_PATHS_KEY, effective_import_column_paths
from .preview import normalize_import_dataframe


def create_import_request(
    import_definition: Any,
    uploaded_file: Any,
    filter_payload: dict[str, Any],
    user: Any,
    *,
    relaunched_from: Any = None,
    inferred_column_paths: list[str] | None = None,
    related_object: Any | None = None,
) -> Any:
    from django_importexport_flow.models import ImportRequest, ImportRequestRelatedObject

    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    raw = uploaded_file.read()
    name = getattr(uploaded_file, "name", "upload.dat") or "upload.dat"
    fp = dict(filter_payload or {})
    if inferred_column_paths is not None:
        fp[IMPORT_COLUMN_PATHS_KEY] = list(inferred_column_paths)
    ask = ImportRequest(
        import_definition=import_definition,
        filter_payload=fp,
        initiated_by=user,
        status=ImportRequest.Status.PENDING,
        relaunched_from=relaunched_from,
    )
    ask.save()
    ask.data_file.save(name, ContentFile(raw), save=True)
    if related_object is not None:
        ImportRequestRelatedObject.objects.create(
            import_request=ask,
            content_object=related_object,
        )
    return ask


def _append_row_error(
    errors: list[str],
    *,
    first_data_line_number: int,
    row_idx: int,
    exc: BaseException,
) -> None:
    line_no = first_data_line_number + row_idx
    errors.append(str(_("Row %(i)s: %(err)s") % {"i": line_no, "err": exc}))


def _row_match_value_unusable(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _upsert_lookups_for_row(
    merged: dict[str, Any],
    scope_base: dict[str, Any],
    scope_dyn: dict[str, Any],
    match_fields: list[str],
) -> dict[str, Any]:
    """
    Build ``update_or_create`` lookup kwargs: scope (static + dynamic filters) plus
    row match fields. Raises ``ValueError`` when a declared match field is missing
    or empty for this row.
    """
    lookups: dict[str, Any] = {}
    for key in scope_base:
        if key in merged:
            lookups[key] = merged[key]
    for key in scope_dyn:
        if key in merged:
            lookups[key] = merged[key]
    for key in match_fields:
        if key not in merged or _row_match_value_unusable(merged[key]):
            raise ValueError(
                str(
                    _("Match field %(field)s is missing or empty in this row.")
                    % {"field": key}
                )
            )
        lookups[key] = merged[key]
    return lookups


def _persist_one_row(
    model: type,
    merged: dict[str, Any],
    m2m_slots: dict[str, dict[int, dict[str, Any]]],
    *,
    match_fields: list[str] | None = None,
    scope_base: dict[str, Any] | None = None,
    scope_dyn: dict[str, Any] | None = None,
) -> None:
    mfields = [str(x).strip() for x in (match_fields or []) if str(x).strip()]
    if mfields:
        lookups = _upsert_lookups_for_row(
            merged,
            scope_base or {},
            scope_dyn or {},
            mfields,
        )
        defaults = {k: v for k, v in merged.items() if k not in lookups}
        obj, _ = model.objects.update_or_create(**lookups, defaults=defaults)
    else:
        obj = model.objects.create(**merged)
    _apply_slot_relations(obj, model, m2m_slots)


def _execute_rows(
    import_definition: Any,
    df: pd.DataFrame,
    filter_cleaned: dict[str, Any],
    *,
    first_data_line_number: int = 2,
) -> tuple[int, list[str]]:
    """
    Rows are grouped into batches of at most ``TABULAR_IMPORT_BATCH_SIZE`` (default
    500, set ``1`` for legacy behaviour).

    * Rows without M2M / reverse O2M slot-derived writes use ``bulk_create`` inside
      one transaction per batch. If that batch fails (e.g. one bad cell), the batch
      is retried row-by-row with one ``transaction.atomic()`` per row so earlier
      rows still commit and errors stay per-line.
    * Rows that need :func:`~django_importexport_flow.engine.core.items._apply_slot_relations`
      stay on the per-row transactional path.
    """
    model = import_definition.target.model_class()
    if model is None:
        return 0, [str(_("No target model."))]

    fp = dict(filter_cleaned or {})
    stored = fp.pop(IMPORT_COLUMN_PATHS_KEY, None)
    if stored is not None:
        column_paths = list(stored)
    else:
        column_paths = list(effective_import_column_paths(import_definition))
    if not column_paths:
        return 0, [str(_("No columns for import."))]

    base = dict(import_definition.filter_config or {})
    try:
        dyn = collect_dynamic_filter_kwargs(import_definition, fp)
    except Exception as exc:
        return 0, [str(exc)]

    match_fields = [
        str(x).strip()
        for x in (import_definition.import_match_fields or [])
        if x is not None and str(x).strip()
    ]

    raw_batch = int(get_setting("TABULAR_IMPORT_BATCH_SIZE"))
    batch_size = raw_batch if raw_batch > 0 else 500

    prepared: list[tuple[int, dict[str, Any], dict[str, dict[int, dict[str, Any]]]]] = []
    errors: list[str] = []
    for row_idx, row_data in enumerate(df.iterrows()):
        row = row_data[1]
        try:
            row_kw, m2m_slots = _scalar_model_kwargs(model, import_definition, row, column_paths)
            merged = {**base, **dyn, **row_kw}
            prepared.append((row_idx, merged, m2m_slots))
        except Exception as exc:
            _append_row_error(
                errors,
                first_data_line_number=first_data_line_number,
                row_idx=row_idx,
                exc=exc,
            )

    n = 0
    offset = 0
    while offset < len(prepared):
        slice_rows = prepared[offset : offset + batch_size]
        offset += len(slice_rows)

        if (
            batch_size == 1
            or match_fields
            or any(
                import_row_slots_need_post_create(slots) for _, _, slots in slice_rows
            )
        ):
            for row_idx, merged, m2m_slots in slice_rows:
                try:
                    with transaction.atomic():
                        _persist_one_row(
                            model,
                            merged,
                            m2m_slots,
                            match_fields=match_fields,
                            scope_base=base,
                            scope_dyn=dyn,
                        )
                    n += 1
                except Exception as exc:
                    _append_row_error(
                        errors,
                        first_data_line_number=first_data_line_number,
                        row_idx=row_idx,
                        exc=exc,
                    )
            continue

        mergeds = [merged for _, merged, _ in slice_rows]
        try:
            with transaction.atomic():
                model.objects.bulk_create([model(**m) for m in mergeds], batch_size=len(mergeds))
            n += len(mergeds)
        except Exception:
            for row_idx, merged, m2m_slots in slice_rows:
                try:
                    with transaction.atomic():
                        _persist_one_row(
                            model,
                            merged,
                            m2m_slots,
                            match_fields=match_fields,
                            scope_base=base,
                            scope_dyn=dyn,
                        )
                    n += 1
                except Exception as exc:
                    _append_row_error(
                        errors,
                        first_data_line_number=first_data_line_number,
                        row_idx=row_idx,
                        exc=exc,
                    )

    return n, errors


def run_import_request(ask: Any) -> Any:
    from django_importexport_flow.models import ImportRequest

    if not isinstance(ask, ImportRequest):
        raise TypeError("Expected ImportRequest instance.")

    ask.refresh_from_db()
    if ask.status in (ImportRequest.Status.SUCCESS, ImportRequest.Status.FAILURE):
        return ask

    import_definition = ask.import_definition
    max_bytes = get_setting("MAX_TABULAR_IMPORT_BYTES")

    try:
        df = read_import_filefield(ask.data_file, max_bytes)
    except Exception:
        ask.status = ImportRequest.Status.FAILURE
        ask.error_trace = traceback.format_exc()
        ask.completed_at = timezone.now()
        ask.save(update_fields=["status", "error_trace", "completed_at"])
        return ask

    fp_payload = dict(ask.filter_payload or {})
    stored_paths = fp_payload.get(IMPORT_COLUMN_PATHS_KEY)
    if stored_paths is not None:
        column_paths = list(stored_paths)
    else:
        column_paths = list(effective_import_column_paths(import_definition))
    df_norm, norm_errs, meta = normalize_import_dataframe(df, import_definition, column_paths)
    if norm_errs:
        ask.status = ImportRequest.Status.FAILURE
        ask.error_trace = "\n".join(norm_errs)
        ask.completed_at = timezone.now()
        ask.save(update_fields=["status", "error_trace", "completed_at"])
        return ask

    first_line = int(meta.get("first_data_line", 2))

    try:
        n, row_errs = _execute_rows(
            import_definition,
            df_norm,
            dict(ask.filter_payload or {}),
            first_data_line_number=first_line,
        )
    except Exception:
        ask.status = ImportRequest.Status.FAILURE
        ask.error_trace = traceback.format_exc()
        ask.completed_at = timezone.now()
        ask.save(update_fields=["status", "error_trace", "completed_at"])
        return ask

    ask.imported_row_count = n
    ask.completed_at = timezone.now()
    if row_errs:
        ask.status = ImportRequest.Status.FAILURE
        ask.error_trace = "\n".join(row_errs)
    else:
        ask.status = ImportRequest.Status.SUCCESS
        ask.error_trace = ""
    ask.save(
        update_fields=[
            "status",
            "imported_row_count",
            "error_trace",
            "completed_at",
        ]
    )
    return ask


def relaunch_import_request(source_request: Any, user: Any) -> Any:
    from django_importexport_flow.models import ImportRequest

    if not source_request.data_file:
        raise ValueError("Source request has no file.")
    with source_request.data_file.open("rb") as f:
        content = f.read()
    base = os.path.basename(source_request.data_file.name) or "reimport.dat"
    new_request = ImportRequest(
        import_definition=source_request.import_definition,
        filter_payload=dict(source_request.filter_payload or {}),
        initiated_by=user,
        status=ImportRequest.Status.PENDING,
        relaunched_from=source_request,
    )
    new_request.save()
    new_request.data_file.save(base, ContentFile(content), save=True)
    from django_importexport_flow.models import ImportRequestRelatedObject

    for rel in source_request.related_object_links.all():
        ImportRequestRelatedObject.objects.create(
            import_request=new_request,
            content_type_id=rel.content_type_id,
            object_id=rel.object_id,
            object_str=rel.object_str or "",
        )
    return new_request
