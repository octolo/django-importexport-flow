"""Execution helpers for ordered combined imports."""

from __future__ import annotations

from typing import Any

from django.core.files.base import ContentFile
from django.db import transaction

from ...utils.helpers import get_setting
from ..hooks import _read_limited
from .hooks import run_import_hook
from .paths import IMPORT_COLUMN_PATHS_KEY


def _steps(definition: Any) -> list[Any]:
    steps = list(definition.steps.select_related("parent", "definition"))
    for step in steps:
        step.clean()
    return steps


def _upload(file: Any, max_bytes: int) -> tuple[bytes, str]:
    name = getattr(file, "name", "") or ""
    limit = max_bytes if max_bytes > 0 else int(get_setting("MAX_TABULAR_IMPORT_BYTES"))
    return _read_limited(file, limit), name


def run_combined_import(
    definition: Any,
    file: Any,
    *,
    user: Any,
    filter_payload: dict[str, Any],
    max_bytes: int,
) -> tuple[int, list[str]]:
    """Run steps sequentially with one transaction on the default database."""
    from .run import _run_single_import

    steps = _steps(definition)
    if not steps:
        raise ValueError("A combined import requires at least one step.")
    raw, name = _upload(file, max_bytes)
    payload = dict(filter_payload)
    payload.pop(IMPORT_COLUMN_PATHS_KEY, None)
    imported = 0
    with transaction.atomic():
        for step in steps:
            try:
                with ContentFile(raw, name=name) as source:
                    count, errors = _run_single_import(
                        step.definition,
                        source,
                        user=user,
                        filter_payload=payload,
                        max_bytes=max_bytes,
                        infer_column_paths=True,
                    )
            except Exception as exc:
                raise RuntimeError(f"Import step failed: {step.definition.name}") from exc
            if errors:
                transaction.set_rollback(True)
                return 0, [f"{step.definition.name}: {error}" for error in errors]
            imported += count
    return imported, []


def preview_combined_import(
    definition: Any,
    file: Any,
    *,
    user: Any,
    filter_payload: dict[str, Any] | None,
    max_bytes: int,
    row_limit: int,
) -> dict[str, Any]:
    """Validate each step and return one preview of the source file."""
    from ...utils.process import _validation_dataset, validate_import

    steps = _steps(definition)
    if not steps:
        raise ValueError("A combined import requires at least one step.")
    raw, name = _upload(file, max_bytes)
    with ContentFile(raw, name=name) as source:
        dataset = run_import_hook(
            definition,
            source,
            {"max_bytes": max_bytes, "name": name},
        )
    frame = dataset.dataframe
    columns = [str(column) for column in frame.columns]
    preview = _validation_dataset(frame, columns, columns, row_limit=row_limit)
    errors: list[str] = []
    warnings = ["Each step is validated independently; earlier steps are not simulated."]
    reports = []
    for step in steps:
        try:
            with ContentFile(raw, name=name) as source:
                result = validate_import(
                    file=source,
                    import_definition=step.definition,
                    user=user,
                    filter_payload=filter_payload,
                    max_bytes=max_bytes,
                    row_limit=row_limit,
                )
        except Exception as exc:
            raise RuntimeError(f"Preview failed: {step.definition.name}") from exc
        step_errors = [str(item) for item in result["errors"]]
        step_warnings = [str(item) for item in result["warnings"]]
        errors.extend(f"{step.definition.name}: {item}" for item in step_errors)
        warnings.extend(f"{step.definition.name}: {item}" for item in step_warnings)
        reports.append(
            {
                "definition": step.definition.named_id,
                "position": step.position,
                "errors": step_errors,
                "warnings": step_warnings,
            }
        )
    return {
        "errors": errors,
        "warnings": warnings,
        "column_paths": columns,
        "dataframe": frame,
        "row_count": preview["row_count"],
        "validation_dataset": preview,
        "steps": reports,
    }
