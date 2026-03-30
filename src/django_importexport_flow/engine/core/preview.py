"""Normalize uploaded tables and validate before commit."""

from __future__ import annotations

from typing import Any

import pandas as pd
from django.db import models
from django.utils.translation import gettext_lazy as _

from ...utils.helpers import (
    M2M_SLOT_PATH_PATTERN,
    get_field_or_accessor,
    normalize_table_column,
    parse_reverse_expand_spec,
    verbose_name_for_field_path,
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
    a = actual.strip()
    e = expected.strip()
    if a == e:
        return True
    m = M2M_SLOT_PATH_PATTERN.match(path.strip())
    if not m:
        return False
    rel_name, _slot_s, sub = m.groups()
    field = get_field_or_accessor(model, rel_name)
    if isinstance(field, models.ManyToManyField):
        rm = field.remote_field.model
    elif getattr(field, "one_to_many", False) and not getattr(field, "many_to_many", False):
        rm = field.related_model
    else:
        return False

    vn = verbose_name_for_field_path(rm, sub)
    if vn is None:
        return False
    base = str(vn).strip()
    return a.startswith(base)


def validate_import_preview(
    df: pd.DataFrame,
    import_definition: Any,
) -> tuple[list[str], list[str], list[str], pd.DataFrame | None]:
    errors: list[str] = []
    warnings: list[str] = []
    path_errs, col_paths = resolve_import_column_paths(import_definition, df)
    if path_errs:
        return path_errs, [], [], None

    model = import_definition.target.model_class() if import_definition.target_id else None
    if model is None:
        return [str(_("Target model is not set."))], [], col_paths, None

    expected = _expected_headers(import_definition, column_paths=col_paths)
    if not expected:
        errors.append(str(_("Could not resolve column headers for this import.")))
        return errors, warnings, col_paths, None

    df_norm, norm_errs, _meta = normalize_import_dataframe(df, import_definition, col_paths)
    if norm_errs:
        errors.extend(norm_errs)
        return errors, warnings, col_paths, None

    for spec in col_paths:
        s = str(spec)
        if parse_reverse_expand_spec(s):
            warnings.append(
                str(_("“%(col)s”: reverse-expand columns are not imported.") % {"col": s})
            )

    if df_norm.empty:
        errors.append(str(_("The file contains no data rows.")))
        return errors, warnings, col_paths, None

    exp = [str(h).strip() for h in expected]
    first = df_norm.iloc[0]
    for i, spec in enumerate(col_paths):
        if parse_reverse_expand_spec(str(spec)):
            continue
        path = normalize_table_column(str(spec))
        if "." in path:
            continue
        try:
            field = model._meta.get_field(path)
        except Exception:
            continue
        if not field.many_to_one and not field.concrete:
            continue
        if getattr(field, "auto_created", False) and not getattr(field, "concrete", True):
            continue
        if (
            field.blank
            or getattr(field, "auto_now", False)
            or getattr(field, "auto_now_add", False)
        ):
            continue
        if field.has_default():
            continue
        header = exp[i] if i < len(exp) else ""
        raw = first.iloc[i] if i < len(first.index) else None
        if pd.isna(raw) or (isinstance(raw, str) and not raw.strip()):
            errors.append(
                str(
                    _("First row: “%(header)s” is required for field %(field)s.")
                    % {"header": header, "field": path}
                )
            )

    return errors, warnings, col_paths, df_norm
