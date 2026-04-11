"""Model field paths and header mapping (tabular columns, JSON keys, same path strings)."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
from django.db import models
from django.utils.translation import gettext_lazy as _

from ...utils.helpers import (
    get_setting,
    normalize_table_column,
    parse_reverse_expand_spec,
    resolve_expand_relation,
    resolve_table_column_label,
    verbose_name_for_field_path,
)

logger = logging.getLogger(__name__)

IMPORT_COLUMN_PATHS_KEY = get_setting("IMPORT_COLUMN_PATHS_KEY")
DEFAULT_M2M_IMPORT_SLOTS = get_setting("DEFAULT_M2M_IMPORT_SLOTS")
DEFAULT_IMPORT_MAX_RELATION_HOPS = get_setting("DEFAULT_IMPORT_MAX_RELATION_HOPS")


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
    return bool(getattr(field, "many_to_one", False) or getattr(field, "one_to_one", False))


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
    hops = getattr(import_definition, "max_relation_hops", None)
    if hops is None:
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
    ``import_definition.max_relation_hops``).

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
    Return ``(errors, column_paths)``.

    When the file has the **same column count** as the effective definition, paths
    are the full effective list (technical path headers or human labels resolved in
    :func:`normalize_import_dataframe`).

    When the count **differs**:

    * If every column name is a **technical path** (subset of the allowed paths),
      that subset is used (same idea as the example CSV’s header row).
    * Otherwise headers are treated as the **example’s human labels** (subset):
      each must map one-to-one via :func:`infer_column_paths_from_headers`.
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
    full_paths = effective_import_column_paths(import_definition)
    if not full_paths:
        return [str(_("No importable columns after exclusions."))], []
    if df.shape[1] == 0:
        return [str(_("The file has no columns."))], []

    if len(df.columns) == len(full_paths):
        return [], full_paths

    allowed = set(full_paths)
    normalized_headers = [normalize_table_column(str(c)) for c in df.columns]
    if len(normalized_headers) == len(set(normalized_headers)) and all(
        p in allowed for p in normalized_headers
    ):
        return [], normalized_headers

    hops = getattr(import_definition, "max_relation_hops", None)
    if hops is None:
        hops = getattr(import_definition, "import_max_relation_hops", None)
    inferred = infer_column_paths_from_headers(
        model,
        [str(c) for c in df.columns],
        max_relation_hops=hops,
    )
    if inferred is None:
        return [
            str(
                _(
                    "This file has %(got)s columns but the definition’s example has "
                    "%(exp)s (full set). Either use that many columns, or use a "
                    "subset whose headers are exactly the same human-readable labels "
                    "as in the example (one column per allowed field, no duplicates)."
                )
                % {"got": len(df.columns), "exp": len(full_paths)}
            )
        ], []

    if not all(p in allowed for p in inferred):
        return [
            str(
                _(
                    "Each column must match an allowed import path for this definition "
                    "(see the example export labels or technical paths)."
                )
            )
        ], []
    return [], inferred


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
