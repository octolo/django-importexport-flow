"""Normalize uploaded tables and validate before commit."""

from __future__ import annotations

from typing import Any

import pandas as pd
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.utils.translation import gettext_lazy as _

from ...utils.helpers import (
    normalize_table_column,
    parse_reverse_expand_spec,
)
from .paths import (
    resolve_import_column_paths,
    sample_headers_for_import_definition,
)


def _expected_headers(import_definition: Any, column_paths: list[str] | None = None) -> list[str]:
    return sample_headers_for_import_definition(import_definition, column_paths=column_paths)


def _columns_match_paths(df: pd.DataFrame, col_paths: list[str]) -> bool:
    for i, p in enumerate(col_paths):
        if str(df.columns[i]).strip() != normalize_table_column(str(p)):
            return False
    return True


def _maybe_strip_label_data_row(
    df: pd.DataFrame,
    import_definition: Any,
    model: type[models.Model],
    col_paths: list[str],
) -> pd.DataFrame:
    if df.empty:
        return df
    expected_labels = sample_headers_for_import_definition(
        import_definition, column_paths=col_paths
    )
    first = df.iloc[0]
    if not all(
        _header_matches_expected_import(
            str(first.iloc[i]).strip(),
            str(expected_labels[i]).strip(),
            model,
            col_paths[i],
        )
        for i in range(len(col_paths))
    ):
        return df
    return df.iloc[1:].reset_index(drop=True)


def normalize_import_dataframe(
    df: pd.DataFrame,
    import_definition: Any,
    col_paths: list[str],
) -> tuple[pd.DataFrame, list[str], dict[str, Any]]:
    """
    Align ``df`` to ``col_paths`` and strip an optional human-label row.

    Returns ``(dataframe, errors, meta)``; ``meta`` may include ``first_data_line`` (1-based).
    """
    meta: dict[str, Any] = {"first_data_line": 2}
    if not col_paths:
        return df, [str(_("No columns for import."))], meta
    model = import_definition.target.model_class() if import_definition.target_id else None
    if model is None:
        return df, [str(_("Target model is not set."))], meta

    if len(df.columns) != len(col_paths):
        return (
            df,
            [str(_("File columns must match the definition (column count)."))],
            meta,
        )

    if _columns_match_paths(df, col_paths):
        out = df.copy()
        out.columns = list(col_paths)
        before = len(out)
        out = _maybe_strip_label_data_row(out, import_definition, model, col_paths)
        if len(out) < before:
            meta["first_data_line"] = 3
        return out, [], meta

    expected_labels = sample_headers_for_import_definition(
        import_definition, column_paths=col_paths
    )
    if all(
        _header_matches_expected_import(
            str(list(df.columns)[i]).strip(),
            str(expected_labels[i]).strip(),
            model,
            col_paths[i],
        )
        for i in range(len(col_paths))
    ):
        out = df.copy()
        out.columns = list(col_paths)
        return out, [], meta

    return (
        df,
        [
            str(
                _(
                    "Could not match file columns to import paths "
                    "(technical paths or legacy label headers)."
                )
            )
        ],
        meta,
    )


def _header_matches_expected_import(
    actual: str,
    expected: str,
    model: type[models.Model],
    path: str,
) -> bool:
    from ...utils.translations import import_header_aliases

    a = actual.strip()
    aliases = import_header_aliases(model, path)
    if a == expected.strip() or a in aliases:
        return True
    return any(base and a.startswith(base) for base in aliases)


def _reverse_expand_warnings(column_paths: list[str]) -> list[str]:
    warnings: list[str] = []
    for spec in column_paths:
        label = str(spec)
        if parse_reverse_expand_spec(label):
            warnings.append(
                str(_("“%(col)s”: reverse-expand columns are not imported.") % {"col": label})
            )
    return warnings


def _field_requires_first_row(field: Any) -> bool:
    if field is None:
        return False
    if not field.many_to_one and not field.concrete:
        return False
    if getattr(field, "auto_created", False) and not getattr(field, "concrete", True):
        return False
    if field.blank or getattr(field, "auto_now", False) or getattr(field, "auto_now_add", False):
        return False
    return not field.has_default()


def _missing_required_first_row(
    model: type[models.Model],
    column_paths: list[str],
    expected: list[str],
    first: pd.Series,
) -> list[str]:
    errors: list[str] = []
    headers = [str(header).strip() for header in expected]
    for index, spec in enumerate(column_paths):
        if parse_reverse_expand_spec(str(spec)):
            continue
        path = normalize_table_column(str(spec))
        if "." in path:
            continue
        try:
            field = model._meta.get_field(path)
        except FieldDoesNotExist:
            continue
        if not _field_requires_first_row(field):
            continue
        header = headers[index] if index < len(headers) else ""
        raw = first.iloc[index] if index < len(first.index) else None
        if pd.isna(raw) or (isinstance(raw, str) and not raw.strip()):
            errors.append(
                str(
                    _("First row: “%(header)s” is required for field %(field)s.")
                    % {"header": header, "field": path}
                )
            )
    return errors


def validate_import_preview(
    df: pd.DataFrame,
    import_definition: Any,
) -> tuple[list[str], list[str], list[str], pd.DataFrame | None]:
    path_errs, col_paths = resolve_import_column_paths(import_definition, df)
    if path_errs:
        return path_errs, [], [], None

    model = import_definition.target.model_class() if import_definition.target_id else None
    if model is None:
        return [str(_("Target model is not set."))], [], col_paths, None

    expected = _expected_headers(import_definition, column_paths=col_paths)
    if not expected:
        return [str(_("Could not resolve column headers for this import."))], [], col_paths, None

    df_norm, norm_errs, _meta = normalize_import_dataframe(df, import_definition, col_paths)
    if norm_errs:
        return norm_errs, [], col_paths, None

    warnings = _reverse_expand_warnings(col_paths)
    if df_norm.empty:
        return [str(_("The file contains no data rows."))], warnings, col_paths, None
    errors = _missing_required_first_row(model, col_paths, expected, df_norm.iloc[0])
    return errors, warnings, col_paths, df_norm
