"""Build one import item: a row (or record) → ``create`` kwargs, nested FK trees, M2M/reverse slots."""

from __future__ import annotations

from typing import Any, cast

import pandas as pd
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.db import models

from ...utils.helpers import (
    M2M_SLOT_PATH_PATTERN,
    _next_model_for_rel_field,
    get_field_or_accessor,
    normalize_table_column,
    parse_reverse_expand_spec,
)


def _model_objects(model: type[models.Model]) -> models.Manager:
    return cast("models.Manager[Any]", model.objects)  # type: ignore[attr-defined]


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
        lookup: dict[str, Any] = {str(fk_to_parent): inst}
        _model_objects(child_model).update_or_create(**lookup, defaults=defaults)
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


def _nested_m2m_scalars(rel_model: type[models.Model], tree: dict[str, Any]) -> dict[str, Any]:
    scalars: dict[str, Any] = {}
    forward_nested: dict[str, dict[str, Any]] = {}
    for key, value in tree.items():
        if isinstance(value, dict):
            forward_nested[key] = value
        else:
            scalars[key] = value
    for fk_name, sub_tree in forward_nested.items():
        fk_field = get_field_or_accessor(rel_model, fk_name)
        if fk_field is None:
            continue
        if getattr(fk_field, "many_to_one", False) or getattr(fk_field, "one_to_one", False):
            remote = fk_field.remote_field.model
            scalars[fk_name] = _save_related_from_tree(remote, sub_tree)
    return _coerce_m2m_scalars(rel_model, scalars)


def _coerce_m2m_scalars(rel_model: type[models.Model], scalars: dict[str, Any]) -> dict[str, Any]:
    for key in list(scalars):
        field = get_field_or_accessor(rel_model, key)
        if field is None:
            scalars.pop(key, None)
            continue
        if getattr(field, "is_relation", False):
            if not isinstance(scalars[key], models.Model):
                scalars.pop(key, None)
            continue
        scalars[key] = _coerce_cell_to_field(field, scalars[key])
    return scalars


def _existing_m2m_match(rel_model: type[models.Model], scalars: dict[str, Any]) -> Any:
    for fname, val in list(scalars.items()):
        field = get_field_or_accessor(rel_model, fname)
        if field is not None and getattr(field, "unique", False):
            others = {key: value for key, value in scalars.items() if key != fname}
            obj, _created = _model_objects(rel_model).get_or_create(**{fname: val}, defaults=others)
            return obj
    if len(scalars) == 1:
        key, value = next(iter(scalars.items()))
        existing = _model_objects(rel_model).filter(**{key: value}).first()
        if existing:
            return existing
        return _model_objects(rel_model).create(**scalars)
    existing = _model_objects(rel_model).filter(**scalars).first()
    if existing:
        return existing
    return _model_objects(rel_model).create(**scalars)


def _resolve_or_create_m2m_related(
    rel_model: type[models.Model],
    tree: dict[str, Any],
) -> Any:
    scalars = _nested_m2m_scalars(rel_model, tree)
    if not scalars:
        return None
    return _existing_m2m_match(rel_model, scalars)


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
                _model_objects(child_model).create(**{parent_fk_name: instance, **scalars})


def _scalar_model_kwargs(
    model: type[models.Model],
    _import_definition: Any,
    row: pd.Series,
    column_paths: list[str],
) -> tuple[dict[str, Any], dict[str, dict[int, dict[str, Any]]]]:
    kwargs: dict[str, Any] = {}
    nested_by_root: dict[str, list[str]] = {}
    m2m_slots: dict[str, dict[int, dict[str, Any]]] = {}

    for index, spec in enumerate(column_paths):
        _collect_scalar_column(model, row, spec, index, kwargs, nested_by_root, m2m_slots)
    _apply_nested_relations(model, row, column_paths, nested_by_root, kwargs)
    return kwargs, m2m_slots


def _collect_scalar_column(
    model: type[models.Model],
    row: pd.Series,
    spec: str,
    index: int,
    kwargs: dict[str, Any],
    nested_by_root: dict[str, list[str]],
    m2m_slots: dict[str, dict[int, dict[str, Any]]],
) -> None:
    if parse_reverse_expand_spec(str(spec)):
        return
    path = normalize_table_column(str(spec))
    slot = M2M_SLOT_PATH_PATTERN.match(path)
    if slot:
        rel_name, slot_s, rest = slot.groups()
        _tree_set_dotted(
            m2m_slots.setdefault(rel_name, {}).setdefault(int(slot_s), {}),
            rest,
            _row_cell_at(row, index),
        )
        return
    if "." in path:
        nested_by_root.setdefault(path.split(".", 1)[0], []).append(path)
        return
    try:
        field = model._meta.get_field(path)
    except FieldDoesNotExist:
        return
    _assign_scalar_value(kwargs, path, field, _row_cell_at(row, index))


def _assign_scalar_value(kwargs: dict[str, Any], path: str, field: Any, raw: Any) -> None:
    if pd.isna(raw):
        if field.null:
            kwargs[path] = None
        return
    if isinstance(raw, str) and not raw.strip() and field.null:
        kwargs[path] = None
        return
    try:
        if hasattr(field, "to_python"):
            kwargs[path] = field.to_python(str(raw).strip() if raw is not None else raw)
        else:
            kwargs[path] = raw
    except (TypeError, ValueError, ValidationError):
        kwargs[path] = raw


def _apply_nested_relations(
    model: type[models.Model],
    row: pd.Series,
    column_paths: list[str],
    nested_by_root: dict[str, list[str]],
    kwargs: dict[str, Any],
) -> None:
    path_to_index = {
        normalize_table_column(str(path)): index for index, path in enumerate(column_paths)
    }
    for root, paths in nested_by_root.items():
        related = _forward_relation_model(model, root)
        if related is None:
            continue
        tree: dict[str, Any] = {}
        for full_path in paths:
            index = path_to_index.get(normalize_table_column(str(full_path)))
            if index is None:
                continue
            _tree_set_dotted(tree, full_path.split(".", 1)[1], _row_cell_at(row, index))
        kwargs[root] = _save_related_from_tree(related, tree)


def _forward_relation_model(model: type[models.Model], root: str) -> type[models.Model] | None:
    field = get_field_or_accessor(model, root)
    if field is None or not getattr(field, "is_relation", False):
        return None
    if not (getattr(field, "many_to_one", False) or getattr(field, "one_to_one", False)):
        return None
    return _next_model_for_rel_field(field)
