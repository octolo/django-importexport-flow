"""Model field paths and header mapping (tabular columns, JSON keys, same path strings)."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.utils.translation import gettext_lazy as _

from ...utils.helpers import (
    get_setting,
    normalize_table_column,
    parse_reverse_expand_spec,
    resolve_column_header,
    resolve_expand_relation,
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


def _exclude_relation_field(model: type[models.Model], name: str) -> Any | None:
    if "." in str(name):
        return None
    try:
        return model._meta.get_field(name)
    except FieldDoesNotExist:
        return None


def _relation_exclude_expands(field: Any) -> bool:
    from django.db.models import ManyToManyField

    if isinstance(field, ManyToManyField):
        return True
    if getattr(field, "one_to_many", False) and not getattr(field, "many_to_many", False):
        fk = getattr(field, "remote_field", None)
        return fk is not None and bool(getattr(fk, "many_to_one", False))
    return _is_forward_fk_or_o2o_field(field)


def _paths_covered_by_name(base: list[str], name: str) -> list[str]:
    prefix = f"{name}."
    return [path for path in base if path == name or path.startswith(prefix)]


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
    out = set(exclude)
    for name in list(exclude):
        field = _exclude_relation_field(model, name)
        if field is None or not _relation_exclude_expands(field):
            continue
        out.update(_paths_covered_by_name(base, name))
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
    out: list[str] = []
    for field in model._meta.get_fields():
        out.extend(_reverse_o2m_slots_for_field(model, field, slots))
    return out


def _reverse_o2m_slots_for_field(model: type[models.Model], field: Any, slots: int) -> list[str]:
    from django.db.models import ManyToManyField

    if not getattr(field, "one_to_many", False) or getattr(field, "many_to_many", False):
        return []
    fk = getattr(field, "remote_field", None)
    child_model = getattr(field, "related_model", None)
    if fk is None or not getattr(fk, "many_to_one", False) or child_model is None:
        return []
    rel_name = _reverse_o2m_accessor_name(field)
    pk_name = getattr(child_model._meta.pk, "name", None) if child_model._meta.pk else None
    names = [
        sub.name
        for sub in child_model._meta.get_fields()
        if _is_reverse_slot_scalar(sub, pk_name, model, ManyToManyField)
    ]
    return [f"{rel_name}.{slot}.{name}" for name in names for slot in range(slots)]


def _is_reverse_slot_scalar(field: Any, pk_name: str | None, parent: Any, m2m_type: type) -> bool:
    if not getattr(field, "concrete", False) or isinstance(field, m2m_type):
        return False
    if getattr(field, "one_to_many", False):
        return False
    if getattr(field, "auto_created", False) and not getattr(field, "concrete", True):
        return False
    if getattr(field, "is_relation", False) or (pk_name and field.name == pk_name):
        return False
    if getattr(field, "many_to_one", False) or getattr(field, "one_to_one", False):
        remote = getattr(field, "remote_field", None)
        if remote is not None and getattr(remote, "model", None) == parent:
            return False
    return True


def _drop_implied_relation_roots(
    model: type[models.Model],
    seen: list[str],
    *,
    include_primary_key: bool,
) -> list[str]:
    nested_roots = {path.split(".", 1)[0] for path in seen if "." in path}
    pk_name = getattr(model._meta.pk, "name", None) if model._meta.pk else None
    out: list[str] = []
    for path in seen:
        if not include_primary_key and pk_name and path == pk_name:
            continue
        if "." not in path and path in nested_roots and _implied_forward_relation(model, path):
            continue
        out.append(path)
    return out


def _implied_forward_relation(model: type[models.Model], path: str) -> bool:
    try:
        field = model._meta.get_field(path)
    except FieldDoesNotExist:
        return False
    return field is not None and _is_forward_fk_or_o2o_field(field)


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
    out = _drop_implied_relation_roots(model, seen, include_primary_key=include_primary_key)
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
    pk_name = getattr(related_model._meta.pk, "name", None) if related_model._meta.pk else None
    out = _concrete_paths_under(
        related_model, prefix, depth, max_depth, m2m_type, ancestors, pk_name
    )
    out.extend(
        _reverse_o2o_paths_under(related_model, prefix, depth, max_depth, m2m_type, ancestors)
    )
    return out


def _concrete_paths_under(
    related_model: type[models.Model],
    prefix: str,
    depth: int,
    max_depth: int,
    m2m_type: type,
    ancestors: frozenset[type[models.Model]],
    pk_name: str | None,
) -> list[str]:
    out: list[str] = []
    for field in related_model._meta.get_fields():
        if not _include_concrete_field(field, m2m_type):
            continue
        if not field.is_relation:
            if not (pk_name and field.name == pk_name):
                out.append(f"{prefix}.{field.name}")
            continue
        out.extend(_nested_relation_paths(field, prefix, depth, max_depth, m2m_type, ancestors))
    return out


def _include_concrete_field(field: Any, m2m_type: type) -> bool:
    if not getattr(field, "concrete", False) or isinstance(field, m2m_type):
        return False
    if getattr(field, "one_to_many", False):
        return False
    return not (getattr(field, "auto_created", False) and not getattr(field, "concrete", True))


def _nested_relation_paths(
    field: Any,
    prefix: str,
    depth: int,
    max_depth: int,
    m2m_type: type,
    ancestors: frozenset[type[models.Model]],
) -> list[str]:
    if field.many_to_many or field.one_to_many:
        return []
    if not (getattr(field, "many_to_one", False) or getattr(field, "one_to_one", False)):
        return []
    remote = getattr(field, "remote_field", None)
    if remote is None or remote.model in ancestors:
        return []
    return _recursive_paths_under(
        remote.model,
        f"{prefix}.{field.name}",
        depth + 1,
        max_depth,
        m2m_type,
        ancestor_models=ancestors,
    )


def _reverse_o2o_paths_under(
    related_model: type[models.Model],
    prefix: str,
    depth: int,
    max_depth: int,
    m2m_type: type,
    ancestors: frozenset[type[models.Model]],
) -> list[str]:
    out: list[str] = []
    for field in related_model._meta.get_fields():
        remote = field.related_model
        if not _is_reverse_o2o(field) or remote is None or remote in ancestors:
            continue
        out.extend(
            _recursive_paths_under(
                remote,
                f"{prefix}.{field.name}",
                depth + 1,
                max_depth,
                m2m_type,
                ancestor_models=ancestors,
            )
        )
    return out


def _is_reverse_o2o(field: Any) -> bool:
    if not getattr(field, "is_relation", False):
        return False
    if getattr(field, "many_to_many", False) or getattr(field, "one_to_many", False):
        return False
    if not getattr(field, "one_to_one", False):
        return False
    return not getattr(field, "concrete", False)


def infer_column_paths_from_headers(
    model: type[models.Model],
    headers: list[str],
    *,
    max_relation_hops: int | None = None,
) -> list[str] | None:
    """
    Map each file header to a column path by matching
    :func:`~django_importexport_flow.utils.helpers.resolve_column_header` for that path
    (same labels as the example export). Uses the same recursive path set as
    :func:`default_importable_column_paths` (e.g. ``author.name``,
    ``author.profile.bio``).

    ``max_relation_hops`` matches :func:`default_importable_column_paths` (e.g. pass
    ``import_definition.max_relation_hops``).

    Returns ``None`` if any header is unknown, ambiguous, or maps to a duplicate path.
    """
    stripped = [str(h).strip() for h in headers]
    seen_paths = default_importable_column_paths(model, max_relation_hops=max_relation_hops)

    from ...utils.translations import catalogs_for_paths, import_header_aliases

    catalogs = catalogs_for_paths(model, seen_paths)
    label_to_paths: dict[str, list[str]] = {}
    for path in seen_paths:
        for label in import_header_aliases(model, path, catalogs=catalogs):
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
            out.append(resolve_column_header(model, spec))
            continue
        rel_name, subfields = parsed
        try:
            related_model, _accessor = resolve_expand_relation(model, rel_name)
        except (FieldDoesNotExist, ValueError) as exc:
            logger.warning(
                "resolve_expand_relation failed for column %r: %s",
                spec,
                exc,
            )
            out.append(spec)
            continue
        for sf in subfields:
            vn = resolve_column_header(related_model, sf) or sf
            out.append(f"{vn} 1")
    return out
