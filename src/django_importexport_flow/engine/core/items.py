"""Build one import item: a row (or record) → ``create`` kwargs, nested FK trees, M2M/reverse slots."""

from __future__ import annotations

from typing import Any

import pandas as pd
from django.db import models

from ...utils.helpers import (
    M2M_SLOT_PATH_PATTERN,
    _next_model_for_rel_field,
    get_field_or_accessor,
    normalize_table_column,
    parse_reverse_expand_spec,
)


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


def import_row_slots_need_post_create(
    slot_paths: dict[str, dict[int, dict[str, Any]]],
) -> bool:
    """
    True when :func:`_apply_slot_relations` would issue writes (M2M / reverse O2M
    import paths with non-empty cell data).
    """
    for slots in slot_paths.values():
        for tree in slots.values():
            if not _m2m_raw_values_empty(tree):
                return True
    return False


def _resolve_or_create_m2m_related(
    rel_model: type[models.Model],
    tree: dict[str, Any],
) -> Any:
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
    _import_definition: Any,
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
        if not (getattr(fk_field, "many_to_one", False) or getattr(fk_field, "one_to_one", False)):
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
