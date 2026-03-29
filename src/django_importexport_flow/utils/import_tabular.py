"""Tabular file import for :class:`~django_importexport_flow.models.ImportDefinition` (admin wizard)."""

from __future__ import annotations

import logging
import os
import traceback
from io import BytesIO
from typing import Any

import pandas as pd
from django.core.files.base import ContentFile
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .export import collect_dynamic_filter_kwargs
from .helpers import (
    M2M_SLOT_PATH_PATTERN,
    _next_model_for_rel_field,
    get_field_or_accessor,
    normalize_table_column,
    parse_reverse_expand_spec,
    resolve_expand_relation,
    resolve_table_column_label,
    verbose_name_for_field_path,
)
from .helpers import dataframe_preview_table  # noqa: F401 - re-export for callers

logger = logging.getLogger(__name__)

# Stored on ImportRequest.filter_payload when resolved column paths are saved with the upload.
IMPORT_COLUMN_PATHS_KEY = "_django_importexport_flow_import_column_paths"

# Number of repeated columns per M2M (e.g. ``tags.0.name``, ``tags.1.name``).
DEFAULT_M2M_IMPORT_SLOTS = 2

# When :attr:`~django_importexport_flow.models.ImportDefinition.import_max_relation_hops`
# is unset, nested import paths use this cap (effectively “no limit” for normal models).
DEFAULT_IMPORT_MAX_RELATION_HOPS = 100


def _resolve_import_max_depth(max_relation_hops: int | None) -> int:
    """
    Map optional hop limit to ``max_depth`` for :func:`_recursive_paths_under`.

    * ``None`` → use :data:`DEFAULT_IMPORT_MAX_RELATION_HOPS` (no user limit).
    * ``0`` → no nested FK, M2M slot, or reverse-O2M slot paths (top-level columns only).
    * ``n >= 1`` → at most ``n`` relation hops in those paths.
    """
    if max_relation_hops is None:
        return DEFAULT_IMPORT_MAX_RELATION_HOPS
    return int(max_relation_hops)


def _iter_top_level_import_paths(model: type[models.Model]) -> list[str]:
    """Scalar / FK top-level field names (same rules as tabular import row mapping)."""
    from django.db.models import ManyToManyField

    paths: list[str] = []
    for field in model._meta.get_fields():
        if not getattr(field, "concrete", False):
            continue
        if isinstance(field, ManyToManyField):
            continue
        if getattr(field, "one_to_many", False):
            continue
        if getattr(field, "auto_created", False) and not getattr(field, "concrete", True):
            continue
        paths.append(field.name)
    return paths


def _is_forward_fk_or_o2o_field(field: Any) -> bool:
    """True for concrete forward ForeignKey / OneToOneField (not M2M or reverse)."""
    if not getattr(field, "is_relation", False):
        return False
    if getattr(field, "many_to_many", False) or getattr(field, "one_to_many", False):
        return False
    return bool(
        getattr(field, "many_to_one", False) or getattr(field, "one_to_one", False)
    )


def _expand_exclude_for_forward_relations(
    model: type[models.Model],
    exclude: set[str],
    base: list[str],
) -> set[str]:
    """
    If ``exclude`` contains a top-level forward FK/O2O name (e.g. ``author``),
    also exclude that relation’s nested paths from ``base`` (``author.name``, …).
    Same for a many-to-many name (e.g. ``tags`` → ``tags.0.name``, …).
    Same for a reverse FK accessor (e.g. ``book_set`` → ``book_set.0.title``, …).
    Dotted entries (e.g. ``author.name``) are left as single-path exclusions.
    """
    from django.db.models import ManyToManyField

    out = set(exclude)
    for name in list(exclude):
        if "." in str(name):
            continue
        try:
            field = model._meta.get_field(name)
        except Exception:
            continue
        if isinstance(field, ManyToManyField):
            for p in base:
                if p == name or p.startswith(f"{name}."):
                    out.add(p)
            continue
        if getattr(field, "one_to_many", False) and not getattr(field, "many_to_many", False):
            fk = getattr(field, "remote_field", None)
            if fk is not None and getattr(fk, "many_to_one", False):
                for p in base:
                    if p == name or p.startswith(f"{name}."):
                        out.add(p)
                continue
        if not _is_forward_fk_or_o2o_field(field):
            continue
        for p in base:
            if p == name or p.startswith(f"{name}."):
                out.add(p)
    return out


def _iter_m2m_slot_paths(
    model: type[models.Model],
    slots: int,
    *,
    max_depth: int = DEFAULT_IMPORT_MAX_RELATION_HOPS,
) -> list[str]:
    """
    Paths ``m2m.N.*`` for scalars and nested forward FK/O2O paths on the related model
    (same depth rules as :func:`_iter_nested_fk_paths`).
    """
    from django.db.models import ManyToManyField

    out: list[str] = []
    for field in model._meta.local_many_to_many:
        if not isinstance(field, ManyToManyField):
            continue
        related = field.remote_field.model
        for slot in range(slots):
            prefix = f"{field.name}.{slot}"
            out.extend(
                _recursive_paths_under(
                    related,
                    prefix,
                    1,
                    max_depth,
                    ManyToManyField,
                    ancestor_models=frozenset({model}),
                )
            )
    return out


def _reverse_o2m_accessor_name(field: Any) -> str:
    ga = getattr(field, "get_accessor_name", None)
    if callable(ga):
        return ga()
    return field.name


def _iter_reverse_o2m_slot_paths(
    model: type[models.Model],
    slots: int,
) -> list[str]:
    """
    Paths ``reverse_fk_accessor.N.field`` for each scalar on the child model
    (e.g. ``book_set.0.title`` for ``Author`` ← ``Book.author``).
    """
    from django.db.models import ManyToManyField

    out: list[str] = []
    for field in model._meta.get_fields():
        if not getattr(field, "one_to_many", False):
            continue
        if getattr(field, "many_to_many", False):
            continue
        fk = getattr(field, "remote_field", None)
        if fk is None or not getattr(fk, "many_to_one", False):
            continue
        child_model = field.related_model
        if child_model is None:
            continue
        rel_name = _reverse_o2m_accessor_name(field)
        pk_name = getattr(child_model._meta.pk, "name", None) if child_model._meta.pk else None
        for sub in child_model._meta.get_fields():
            if not getattr(sub, "concrete", False):
                continue
            if isinstance(sub, ManyToManyField):
                continue
            if getattr(sub, "one_to_many", False):
                continue
            if getattr(sub, "auto_created", False) and not getattr(sub, "concrete", True):
                continue
            if getattr(sub, "is_relation", False):
                continue
            if pk_name and sub.name == pk_name:
                continue
            if getattr(sub, "many_to_one", False) or getattr(sub, "one_to_one", False):
                rf = getattr(sub, "remote_field", None)
                if rf is not None and getattr(rf, "model", None) == model:
                    continue
            for slot in range(slots):
                out.append(f"{rel_name}.{slot}.{sub.name}")
    return out


def default_importable_column_paths(
    model: type[models.Model],
    *,
    include_primary_key: bool = False,
    max_relation_hops: int | None = None,
) -> list[str]:
    """
    Paths used for tabular import and example headers (stable order).

    ``max_relation_hops`` limits how many relation hops appear in nested paths (FK/O2O
    chains and M2M slot subtrees). ``None`` uses :data:`DEFAULT_IMPORT_MAX_RELATION_HOPS`
    (effectively no limit for typical models). ``0`` means no such nested paths (only
    top-level columns on the target model).

    By default omits:

    * the target model’s primary key (use ``include_primary_key=True`` to include it);
    * the bare forward FK/O2O field (e.g. ``author``) when nested paths exist
      (e.g. ``author.name``), since the FK is implied by nested scalars;
    * nested ``relation.<pk>`` on related models (e.g. ``author.id``), same idea as
      excluding primary keys on the main model;
    * reverse ForeignKey accessors with slot columns (e.g. ``book_set.0.title``);
    * many-to-many slot columns including nested FK paths on the related model
      (e.g. ``tags.0.category.name`` when ``Tag`` has ``category`` → ``Category``).
    """
    depth = _resolve_import_max_depth(max_relation_hops)
    seen: list[str] = []
    for p in _iter_top_level_import_paths(model):
        if p not in seen:
            seen.append(p)
    for p in _iter_nested_fk_paths(model, max_depth=depth):
        if p not in seen:
            seen.append(p)
    nested_roots = {p.split(".", 1)[0] for p in seen if "." in p}
    pk_name = getattr(model._meta.pk, "name", None) if model._meta.pk else None
    out: list[str] = []
    for p in seen:
        if not include_primary_key and pk_name and p == pk_name:
            continue
        if "." not in p and p in nested_roots:
            try:
                field = model._meta.get_field(p)
            except Exception:
                out.append(p)
                continue
            if _is_forward_fk_or_o2o_field(field):
                continue
        out.append(p)
    for p in _iter_m2m_slot_paths(model, DEFAULT_M2M_IMPORT_SLOTS, max_depth=depth):
        if p not in out:
            out.append(p)
    if depth > 0:
        for p in _iter_reverse_o2m_slot_paths(model, DEFAULT_M2M_IMPORT_SLOTS):
            if p not in out:
                out.append(p)
    return out


def effective_import_column_paths(import_definition: Any) -> list[str]:
    """
    Importable paths for the definition’s target model: default set minus
    ``columns_exclude`` and optionally the target model’s primary key field name.

    Excluding a **relation** field name (forward FK/O2O) also excludes every
    nested path under it (e.g. ``author`` → ``author.name``, ``author.id``, …).
    """
    if not import_definition.target_id:
        return []
    model = import_definition.target.model_class()
    if model is None:
        return []
    include_pk = not getattr(import_definition, "exclude_primary_key", True)
    hops = getattr(import_definition, "import_max_relation_hops", None)
    base = default_importable_column_paths(
        model,
        include_primary_key=include_pk,
        max_relation_hops=hops,
    )
    exclude = set(import_definition.columns_exclude or [])
    exclude = _expand_exclude_for_forward_relations(model, exclude, base)
    if getattr(import_definition, "exclude_primary_key", True):
        pk = model._meta.pk
        if pk is not None and getattr(pk, "name", None):
            exclude.add(pk.name)
    return [p for p in base if p not in exclude]


def _iter_nested_fk_paths(
    model: type[models.Model],
    *,
    max_depth: int = DEFAULT_IMPORT_MAX_RELATION_HOPS,
) -> list[str]:
    """
    Paths under forward FK/O2O from ``model``, recursively (scalars + nested relations).

    Omits related primary keys at each level. Includes reverse OneToOne children
    (e.g. ``author.profile.bio``). ``max_depth`` limits relation hops from the root model.
    """
    from django.db.models import ManyToManyField

    out: list[str] = []
    for field in model._meta.get_fields():
        if not getattr(field, "concrete", False):
            continue
        if not field.is_relation:
            continue
        if field.many_to_many or field.one_to_many:
            continue
        if not (getattr(field, "many_to_one", False) or getattr(field, "one_to_one", False)):
            continue
        remote = getattr(field, "remote_field", None)
        if remote is None:
            continue
        related = remote.model
        prefix = field.name
        out.extend(
            _recursive_paths_under(
                related,
                prefix,
                1,
                max_depth,
                ManyToManyField,
                ancestor_models=frozenset({model}),
            )
        )
    return out


def _recursive_paths_under(
    related_model: type[models.Model],
    prefix: str,
    depth: int,
    max_depth: int,
    m2m_type: type,
    *,
    ancestor_models: frozenset[type[models.Model]] | None = None,
) -> list[str]:
    if depth > max_depth:
        return []
    ancestors = frozenset(ancestor_models or ()) | {related_model}
    out: list[str] = []
    pk_name = getattr(related_model._meta.pk, "name", None) if related_model._meta.pk else None

    for field in related_model._meta.get_fields():
        if not getattr(field, "concrete", False):
            continue
        if isinstance(field, m2m_type):
            continue
        if getattr(field, "one_to_many", False):
            continue
        if getattr(field, "auto_created", False) and not getattr(field, "concrete", True):
            continue
        if not field.is_relation:
            if pk_name and field.name == pk_name:
                continue
            out.append(f"{prefix}.{field.name}")
            continue
        if field.many_to_many or field.one_to_many:
            continue
        if getattr(field, "many_to_one", False) or getattr(field, "one_to_one", False):
            remote = getattr(field, "remote_field", None)
            if remote is None:
                continue
            remote_model = remote.model
            if remote_model in ancestors:
                continue
            sub_prefix = f"{prefix}.{field.name}"
            out.extend(
                _recursive_paths_under(
                    remote_model,
                    sub_prefix,
                    depth + 1,
                    max_depth,
                    m2m_type,
                    ancestor_models=ancestors,
                )
            )

    for field in related_model._meta.get_fields():
        if not getattr(field, "is_relation", False):
            continue
        if getattr(field, "many_to_many", False) or getattr(field, "one_to_many", False):
            continue
        if not getattr(field, "one_to_one", False):
            continue
        if getattr(field, "concrete", False):
            continue
        child_model = field.related_model
        if child_model is None or child_model in ancestors:
            continue
        rel_name = field.name
        sub_prefix = f"{prefix}.{rel_name}"
        out.extend(
            _recursive_paths_under(
                child_model,
                sub_prefix,
                depth + 1,
                max_depth,
                m2m_type,
                ancestor_models=ancestors,
            )
        )

    return out


def infer_column_paths_from_headers(
    model: type[models.Model],
    headers: list[str],
    *,
    max_relation_hops: int | None = None,
) -> list[str] | None:
    """
    Map each file header to a column path by matching
    :func:`~django_importexport_flow.utils.helpers.resolve_table_column_label` for that path
    (same labels as the example export). Uses the same recursive path set as
    :func:`default_importable_column_paths` (e.g. ``author.name``,
    ``author.profile.bio``).

    ``max_relation_hops`` matches :func:`default_importable_column_paths` (e.g. pass
    ``import_definition.import_max_relation_hops``).

    Returns ``None`` if any header is unknown, ambiguous, or maps to a duplicate path.
    """
    stripped = [str(h).strip() for h in headers]
    seen_paths = default_importable_column_paths(model, max_relation_hops=max_relation_hops)

    label_to_paths: dict[str, list[str]] = {}
    for path in seen_paths:
        label = resolve_table_column_label(model, path)
        label_to_paths.setdefault(label, []).append(path)

    used: set[str] = set()
    out: list[str] = []
    for h in stripped:
        candidates = label_to_paths.get(h, [])
        if len(candidates) != 1:
            return None
        path = candidates[0]
        if path in used:
            return None
        used.add(path)
        out.append(path)
    return out


def resolve_import_column_paths(
    import_definition: Any,
    df: pd.DataFrame,
) -> tuple[list[str], list[str]]:
    """
    Return ``(errors, column_paths)``. Column paths are the effective importable
    set for the target model (all default paths minus ``columns_exclude`` and
    optionally the primary key), in a fixed order — same as the example export.
    """
    if not import_definition.target_id:
        return [
            str(
                _(
                    "Set a target model so import columns can be resolved "
                    "(see columns exclude and the example file)."
                )
            )
        ], []
    model = import_definition.target.model_class()
    if model is None:
        return [str(_("Target model is not set."))], []
    paths = effective_import_column_paths(import_definition)
    if not paths:
        return [str(_("No importable columns after exclusions."))], []
    if df.shape[1] == 0:
        return [str(_("The file has no columns."))], []
    return [], paths


def sample_headers_for_import_definition(
    import_definition: Any,
    column_paths: list[str] | None = None,
) -> list[str]:
    """
    Human-readable labels for each import column (translations / verbose names).

    For CSV and Excel **example** files, these are written as the **second** row
    (first data row), under a header row of real paths (``author.name``, ``tags.0.name``, …).
    JSON examples use path strings as keys instead, with no separate label row.
    """
    if column_paths is not None:
        raw = column_paths
    else:
        raw = effective_import_column_paths(import_definition)
    if not raw:
        return []
    if import_definition.target_id is None:
        return [str(c) for c in raw]
    model = import_definition.target.model_class()
    if model is None:
        return [str(c) for c in raw]
    out: list[str] = []
    for col in raw:
        spec = normalize_table_column(str(col))
        parsed = parse_reverse_expand_spec(spec)
        if not parsed:
            out.append(resolve_table_column_label(model, spec))
            continue
        rel_name, subfields = parsed
        try:
            related_model, _accessor = resolve_expand_relation(model, rel_name)
        except Exception as exc:
            logger.warning(
                "resolve_expand_relation failed for column %r: %s",
                spec,
                exc,
            )
            out.append(spec)
            continue
        for sf in subfields:
            vn = verbose_name_for_field_path(related_model, sf) or sf
            out.append(f"{vn} 1")
    return out


def read_tabular_from_bytes(raw: bytes, name: str, max_bytes: int) -> pd.DataFrame:
    if len(raw) > max_bytes:
        raise ValueError(_("File is too large."))
    name = (name or "").lower()
    buf = BytesIO(raw)
    if name.endswith(".json") or raw[:1] in (b"[", b"{"):
        return pd.read_json(buf, orient="records")
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(buf)
    try:
        return pd.read_csv(BytesIO(raw), encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(_("The CSV file must be UTF-8 encoded.")) from exc


def read_uploaded_tabular(uploaded_file: Any, max_bytes: int) -> pd.DataFrame:
    """Load CSV, Excel, or JSON (records) into a DataFrame."""
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    raw = uploaded_file.read()
    name = getattr(uploaded_file, "name", "") or ""
    return read_tabular_from_bytes(raw, name, max_bytes)


def read_tabular_from_storage_filefield(file_field: models.FileField, max_bytes: int) -> pd.DataFrame:
    """Load from a saved ``FileField`` (e.g. :class:`~django_importexport_flow.models.ImportRequest`)."""
    with file_field.open("rb") as f:
        raw = f.read()
    name = getattr(file_field, "name", "") or ""
    return read_tabular_from_bytes(raw, name, max_bytes)


def _expected_headers(
    import_definition: Any, column_paths: list[str] | None = None
) -> list[str]:
    return sample_headers_for_import_definition(import_definition, column_paths=column_paths)


def _columns_match_paths(df: pd.DataFrame, col_paths: list[str]) -> bool:
    """First file row is a header of dotted paths (``author.name``, …)."""
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
    """
    If the first data row matches the human label row (same as the example export),
    drop it so only real records are imported.
    """
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


def normalize_tabular_import_dataframe(
    df: pd.DataFrame,
    import_definition: Any,
    col_paths: list[str],
) -> tuple[pd.DataFrame, list[str], dict[str, Any]]:
    """
    Align the dataframe to ``col_paths`` and drop an optional label row.

    * **Preferred**: column headers are real paths (same strings as ``col_paths``).
      If the first data row matches the translated labels for those paths, it is removed.
    * **Legacy**: column headers are the human labels only; they are renamed to ``col_paths``.

    Returns ``(dataframe, errors, meta)``. ``meta`` may contain ``first_data_line`` (1-based
    line number of the first imported data row in the original file).
    """
    errors: list[str] = []
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
    """Strict equality, or relaxed match for M2M / reverse-O2M slot columns."""
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
    from .helpers import verbose_name_for_field_path

    vn = verbose_name_for_field_path(rm, sub)
    if vn is None:
        return False
    base = str(vn).strip()
    return a.startswith(base)


def validate_import_preview(
    df: pd.DataFrame,
    import_definition: Any,
) -> tuple[list[str], list[str], list[str], pd.DataFrame | None]:
    """
    Return ``(errors, warnings, resolved_column_paths, normalized_dataframe)``.

    The normalized dataframe uses real column paths and has no leading label-only row.
    ``normalized_dataframe`` is ``None`` when validation fails before normalization.
    """
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

    df_norm, norm_errs, _meta = normalize_tabular_import_dataframe(
        df, import_definition, col_paths
    )
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
        if field.blank or getattr(field, "auto_now", False) or getattr(field, "auto_now_add", False):
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


def _tree_set_dotted(tree: dict, dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    d = tree
    for p in parts[:-1]:
        d = d.setdefault(p, {})
    d[parts[-1]] = value


def _coerce_cell_to_field(field: Any, raw: Any) -> Any:
    if pd.isna(raw):
        return None
    if isinstance(raw, str) and not raw.strip() and getattr(field, "null", False):
        return None
    if hasattr(field, "to_python"):
        return field.to_python(str(raw).strip() if raw is not None else raw)
    return raw


def _save_related_from_tree(rel_model: type[models.Model], tree: dict) -> Any:
    """Create a related instance and nested reverse OneToOne rows from raw cell values."""
    scalars: dict[str, Any] = {}
    nested: dict[str, dict] = {}
    for k, v in tree.items():
        if isinstance(v, dict):
            nested[k] = v
        else:
            scalars[k] = v
    for k in list(scalars):
        f = get_field_or_accessor(rel_model, k)
        if f is None or getattr(f, "is_relation", False):
            scalars.pop(k, None)
            continue
        scalars[k] = _coerce_cell_to_field(f, scalars[k])
    inst = rel_model(**scalars)
    inst.save()
    for rel_name, sub_tree in nested.items():
        rel_f = get_field_or_accessor(rel_model, rel_name)
        if rel_f is None:
            continue
        if not (getattr(rel_f, "one_to_one", False) and not getattr(rel_f, "concrete", False)):
            continue
        child_model = rel_f.related_model
        fk_to_parent = rel_f.remote_field.name
        defaults: dict[str, Any] = {}
        for ck, cv in sub_tree.items():
            cf = get_field_or_accessor(child_model, ck)
            if cf is None or getattr(cf, "is_relation", False):
                continue
            defaults[ck] = _coerce_cell_to_field(cf, cv)
        if not defaults:
            continue
        child_model.objects.update_or_create(**{fk_to_parent: inst}, defaults=defaults)
    return inst


def _row_cell_at(row: pd.Series, i: int) -> Any:
    """Cell value by column index (matches validated preview order)."""
    if i < 0 or i >= len(row.index):
        return None
    return row.iloc[i]


def _m2m_raw_values_empty(tree: dict[str, Any]) -> bool:
    for v in tree.values():
        if pd.isna(v):
            continue
        if isinstance(v, str) and not v.strip():
            continue
        return False
    return True


def _resolve_or_create_m2m_related(
    rel_model: type[models.Model],
    tree: dict[str, Any],
) -> Any:
    """One related row for an M2M slot; reuses an existing row when lookup fields match."""
    scalars: dict[str, Any] = {}
    forward_nested: dict[str, dict[str, Any]] = {}
    for k, v in tree.items():
        if isinstance(v, dict):
            forward_nested[k] = v
        else:
            scalars[k] = v
    for fk_name, sub_tree in forward_nested.items():
        fk_field = get_field_or_accessor(rel_model, fk_name)
        if fk_field is None:
            continue
        if getattr(fk_field, "many_to_one", False) or getattr(fk_field, "one_to_one", False):
            remote = fk_field.remote_field.model
            scalars[fk_name] = _save_related_from_tree(remote, sub_tree)
    for k in list(scalars):
        f = get_field_or_accessor(rel_model, k)
        if f is None:
            scalars.pop(k, None)
            continue
        if getattr(f, "is_relation", False):
            if isinstance(scalars[k], models.Model):
                continue
            scalars.pop(k, None)
            continue
        scalars[k] = _coerce_cell_to_field(f, scalars[k])
    if not scalars:
        return None
    for fname, val in list(scalars.items()):
        f = get_field_or_accessor(rel_model, fname)
        if f is not None and getattr(f, "unique", False):
            others = {k: v for k, v in scalars.items() if k != fname}
            obj, _ = rel_model.objects.get_or_create(**{fname: val}, defaults=others)
            return obj
    if len(scalars) == 1:
        k, v = next(iter(scalars.items()))
        existing = rel_model.objects.filter(**{k: v}).first()
        if existing:
            return existing
        return rel_model.objects.create(**scalars)
    existing = rel_model.objects.filter(**scalars).first()
    if existing:
        return existing
    return rel_model.objects.create(**scalars)


def _coerce_scalars_for_child_create(
    child_model: type[models.Model],
    tree: dict[str, Any],
) -> dict[str, Any]:
    scalars: dict[str, Any] = {}
    for k, v in tree.items():
        if isinstance(v, dict):
            continue
        f = get_field_or_accessor(child_model, k)
        if f is None or getattr(f, "is_relation", False):
            continue
        scalars[k] = _coerce_cell_to_field(f, v)
    return scalars


def _apply_slot_relations(
    instance: models.Model,
    model: type[models.Model],
    slot_paths: dict[str, dict[int, dict[str, Any]]],
) -> None:
    """Apply many-to-many slot paths and reverse-FK slot paths (e.g. ``book_set.0.title``)."""
    for rel_name, slots in slot_paths.items():
        field = get_field_or_accessor(model, rel_name)
        if isinstance(field, models.ManyToManyField):
            rel_model = field.remote_field.model
            related: list[Any] = []
            for slot_idx in sorted(slots.keys()):
                tree = slots[slot_idx]
                if _m2m_raw_values_empty(tree):
                    continue
                rel_obj = _resolve_or_create_m2m_related(rel_model, tree)
                if rel_obj is not None:
                    related.append(rel_obj)
            if related:
                getattr(instance, rel_name).set(related)
            continue

        if getattr(field, "one_to_many", False) and not getattr(field, "many_to_many", False):
            fk_field = field.remote_field
            if fk_field is None or not getattr(fk_field, "many_to_one", False):
                continue
            child_model = fk_field.model
            parent_fk_name = fk_field.name
            for slot_idx in sorted(slots.keys()):
                tree = slots[slot_idx]
                if _m2m_raw_values_empty(tree):
                    continue
                scalars = _coerce_scalars_for_child_create(child_model, tree)
                if not scalars:
                    continue
                child_model.objects.create(**{parent_fk_name: instance, **scalars})


def _scalar_model_kwargs(
    model: type[models.Model],
    import_definition: Any,
    row: pd.Series,
    column_paths: list[str],
) -> tuple[dict[str, Any], dict[str, dict[int, dict[str, Any]]]]:
    kwargs: dict[str, Any] = {}
    nested_by_root: dict[str, list[str]] = {}
    m2m_slots: dict[str, dict[int, dict[str, Any]]] = {}

    for i, spec in enumerate(column_paths):
        if parse_reverse_expand_spec(str(spec)):
            continue
        path = normalize_table_column(str(spec))
        m = M2M_SLOT_PATH_PATTERN.match(path)
        if m:
            rel_name, slot_s, rest = m.groups()
            slot_i = int(slot_s)
            raw = _row_cell_at(row, i)
            _tree_set_dotted(
                m2m_slots.setdefault(rel_name, {}).setdefault(slot_i, {}),
                rest,
                raw,
            )
            continue
        if "." in path:
            root = path.split(".", 1)[0]
            nested_by_root.setdefault(root, []).append(path)
            continue
        try:
            field = model._meta.get_field(path)
        except Exception:
            continue
        raw = _row_cell_at(row, i)
        if pd.isna(raw):
            if field.null:
                kwargs[path] = None
            continue
        if isinstance(raw, str) and not raw.strip() and field.null:
            kwargs[path] = None
            continue
        try:
            if hasattr(field, "to_python"):
                kwargs[path] = field.to_python(str(raw).strip() if raw is not None else raw)
            else:
                kwargs[path] = raw
        except Exception:
            kwargs[path] = raw

    path_to_index = {normalize_table_column(str(p)): i for i, p in enumerate(column_paths)}
    for root, paths in nested_by_root.items():
        fk_field = get_field_or_accessor(model, root)
        if fk_field is None or not getattr(fk_field, "is_relation", False):
            continue
        if not (
            getattr(fk_field, "many_to_one", False) or getattr(fk_field, "one_to_one", False)
        ):
            continue
        rel_model = _next_model_for_rel_field(fk_field)
        if rel_model is None:
            continue
        tree: dict[str, Any] = {}
        for full_path in paths:
            rest = full_path.split(".", 1)[1]
            idx = path_to_index.get(normalize_table_column(str(full_path)))
            if idx is None:
                continue
            raw = _row_cell_at(row, idx)
            _tree_set_dotted(tree, rest, raw)
        kwargs[root] = _save_related_from_tree(rel_model, tree)

    return kwargs, m2m_slots


def create_import_request(
    import_definition: Any,
    uploaded_file: Any,
    filter_payload: dict[str, Any],
    user: Any,
    *,
    relaunched_from: Any = None,
    inferred_column_paths: list[str] | None = None,
) -> Any:
    """Create a pending :class:`~django_importexport_flow.models.ImportRequest` and store the file."""
    from django_importexport_flow.models import ImportRequest

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
    return ask


def _execute_rows(
    import_definition: Any,
    df: pd.DataFrame,
    filter_cleaned: dict[str, Any],
    *,
    first_data_line_number: int = 2,
) -> tuple[int, list[str]]:
    model = import_definition.target.model_class()
    if model is None:
        return 0, [str(_("No target model."))]

    fp = dict(filter_cleaned or {})
    fp.pop(IMPORT_COLUMN_PATHS_KEY, None)
    column_paths = list(effective_import_column_paths(import_definition))
    if not column_paths:
        return 0, [str(_("No columns for import."))]

    base = dict(import_definition.filter_config or {})
    try:
        dyn = collect_dynamic_filter_kwargs(import_definition, fp)
    except Exception as exc:
        return 0, [str(exc)]

    errors: list[str] = []
    n = 0
    for row_idx, (_, row) in enumerate(df.iterrows()):
        try:
            row_kw, m2m_slots = _scalar_model_kwargs(model, import_definition, row, column_paths)
            merged = {**base, **dyn, **row_kw}
            with transaction.atomic():
                obj = model.objects.create(**merged)
                _apply_slot_relations(obj, model, m2m_slots)
            n += 1
        except Exception as exc:
            line_no = first_data_line_number + row_idx
            errors.append(str(_("Row %(i)s: %(err)s") % {"i": line_no, "err": exc}))

    return n, errors


def run_tabular_import_for_request(ask: Any) -> Any:
    """
    Run import for a pending :class:`~django_importexport_flow.models.ImportRequest`.
    Updates ``status``, ``imported_row_count``, ``error_trace``, ``completed_at``.
    """
    from django_importexport_flow.models import ImportRequest

    if not isinstance(ask, ImportRequest):
        raise TypeError("Expected ImportRequest instance.")

    import_definition = ask.import_definition
    max_bytes = 10 * 1024 * 1024

    try:
        df = read_tabular_from_storage_filefield(ask.data_file, max_bytes)
    except Exception as exc:
        ask.status = ImportRequest.Status.FAILURE
        ask.error_trace = traceback.format_exc()
        ask.completed_at = timezone.now()
        ask.save(update_fields=["status", "error_trace", "completed_at"])
        return ask

    column_paths = list(effective_import_column_paths(import_definition))
    df_norm, norm_errs, meta = normalize_tabular_import_dataframe(
        df, import_definition, column_paths
    )
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
    """
    Create a **new** pending request with the same file and filter payload (audit trail).
    """
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
    return new_request


# Backward-compatible names
sample_headers_for_report_import = sample_headers_for_import_definition
create_import_ask = create_import_request
relaunch_import_ask = relaunch_import_request
run_tabular_import_for_ask = run_tabular_import_for_request
