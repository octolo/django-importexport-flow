"""Validate report filters and column specs against the target model."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import JSONField, ManyToManyField
from django.utils.translation import gettext_lazy as _

from ...utils.helpers import (
    M2M_SLOT_PATH_PATTERN,
    _next_model_for_rel_field,
    get_field_or_accessor,
    normalize_table_column,
    parse_reverse_expand_spec,
    resolve_expand_relation,
)


def first_lookup_segment(lookup: str) -> str:
    return lookup.split("__", 1)[0]


def split_filter_mandatory(mandatory: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Return ``(get_map, kwargs_map)`` for ``filter_mandatory``.

    Canonical: ``{"get": {query_param: orm_lookup}, "kwargs": {url_name: orm_lookup}}``.

    **Shorthand:** if neither ``"get"`` nor ``"kwargs"`` is a top-level key, the whole
    object is treated as the GET map (same as ``{"get": {...}}``).
    """
    if not mandatory:
        return {}, {}
    if "get" not in mandatory and "kwargs" not in mandatory:
        return dict(mandatory), {}
    get_m = mandatory.get("get")
    if get_m is None:
        get_m = {}
    elif not isinstance(get_m, dict):
        get_m = {}
    kw_map = mandatory.get("kwargs")
    if kw_map is None:
        kw_map = {}
    elif not isinstance(kw_map, dict):
        kw_map = {}
    return get_m, kw_map


def parse_filter_maps(
    filter_request: Any,
    filter_mandatory: Any,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """
    Normalize ``filter_request``, root ``filter_mandatory``, ``get``, and ``kwargs`` maps
    from JSON-like values (used by forms, export, and validation).
    """
    fr = filter_request if isinstance(filter_request, dict) else {}
    mandatory = filter_mandatory if isinstance(filter_mandatory, dict) else {}
    get_m, kw_map = split_filter_mandatory(mandatory)
    return fr, mandatory, get_m, kw_map


def parse_filter_maps_from_definition(
    definition: Any,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Same as :func:`parse_filter_maps` but reads attributes from a report-like object."""
    return parse_filter_maps(
        getattr(definition, "filter_request", None),
        getattr(definition, "filter_mandatory", None),
    )


def validate_filter_kwargs_for_model(
    model: type[models.Model], kwargs: dict[str, Any] | None
) -> None:
    """Reject unknown field names in ``filter()`` kwargs (first segment of each key)."""
    if not kwargs:
        return
    for key in kwargs:
        if not isinstance(key, str):
            raise ValidationError(_("Filter keys must be strings."))
        base = first_lookup_segment(key)
        if get_field_or_accessor(model, base) is None:
            raise ValidationError(
                _(
                    "Invalid filter field: %(name)s is not a field on %(model)s "
                    "(or a valid relation name)."
                )
                % {"name": base, "model": model.__name__}
            )


def coerce_request_filter_value(model: type[models.Model], orm_key: str, raw: str) -> Any:
    """
    Coerce GET string values for simple field names; leave text lookups and
    compound keys mostly unchanged.
    """
    base = first_lookup_segment(orm_key)
    field = get_field_or_accessor(model, base)
    if field is None or not hasattr(field, "to_python"):
        return raw
    if "__" in orm_key:
        lookup = orm_key.rsplit("__", 1)[-1]
        text_lookups = frozenset(
            {
                "icontains",
                "contains",
                "iexact",
                "exact",
                "istartswith",
                "startswith",
                "iendswith",
                "endswith",
                "regex",
                "iregex",
                "search",
            }
        )
        if lookup in text_lookups:
            return raw
    try:
        return field.to_python(raw)
    except Exception as exc:
        raise ValidationError(
            _("Invalid filter value %(value)r for %(lookup)s: %(err)s")
            % {"value": raw, "lookup": orm_key, "err": exc}
        ) from exc


def validate_export_column_spec(model: type[models.Model], spec: str) -> None:
    """One column string: scalar path or reverse expand spec."""
    spec = normalize_table_column(spec)
    parsed = parse_reverse_expand_spec(spec)
    if parsed:
        rel, _sub = parsed
        resolve_expand_relation(model, rel)
        return
    m = M2M_SLOT_PATH_PATTERN.match(spec)
    if m:
        rel_name, _slot_s, sub = m.groups()
        rel_field = get_field_or_accessor(model, rel_name)
        rm = None
        if isinstance(rel_field, ManyToManyField):
            rm = rel_field.remote_field.model
        elif getattr(rel_field, "one_to_many", False) and not getattr(
            rel_field, "many_to_many", False
        ):
            fk = getattr(rel_field, "remote_field", None)
            if fk is not None and getattr(fk, "many_to_one", False):
                rm = rel_field.related_model
        if rm is None:
            raise ValidationError(
                _(
                    "Invalid column: %(path)s — “%(seg)s” is not a many-to-many "
                    "or reverse foreign key accessor."
                )
                % {"path": spec, "seg": rel_name}
            )
        validate_export_column_spec(rm, sub)
        return
    parts = spec.split(".")
    current = model
    for i, part in enumerate(parts):
        field = get_field_or_accessor(current, part)
        if field is None:
            raise ValidationError(
                _("Invalid column: %(path)s — unknown segment “%(seg)s” on %(model)s.")
                % {"path": spec, "seg": part, "model": current.__name__}
            )
        if i == len(parts) - 1:
            return
        if isinstance(field, JSONField):
            return
        if isinstance(field, ManyToManyField):
            raise ValidationError(
                _("Invalid column: %(path)s — use slot form “field.0.subfield” for many-to-many.")
                % {"path": spec}
            )
        if not field.is_relation:
            raise ValidationError(
                _("Invalid column: %(path)s — segment “%(seg)s” is not a relation.")
                % {"path": spec, "seg": part}
            )
        nxt = _next_model_for_rel_field(field)
        if nxt is None:
            raise ValidationError(
                _("Invalid column: %(path)s — cannot traverse past “%(seg)s”.")
                % {"path": spec, "seg": part}
            )
        current = nxt


def validate_filter_request_mandatory_get_overlap(
    filter_request: Any,
    filter_mandatory: Any,
) -> None:
    """
    If the same query param appears in both ``filter_request`` and
    ``filter_mandatory.get``, the ORM lookup must be identical.
    """
    fr, _mandatory, get_m, _kw = parse_filter_maps(filter_request, filter_mandatory)
    for key in set(fr) & set(get_m):
        if fr[key] != get_m[key]:
            raise ValidationError(
                _(
                    "filter_request and filter_mandatory.get disagree on query param "
                    "%(param)s: %(a)r vs %(b)r — use the same ORM lookup for both."
                )
                % {"param": key, "a": fr[key], "b": get_m[key]}
            )


def validate_filter_mandatory_for_model(model: type[models.Model], mandatory: Any) -> None:
    """
    ``filter_mandatory``: ``{"get": {...}, "kwargs": {...}}``, or shorthand
    ``{query_param: orm_key}`` (all GET) when ``get`` / ``kwargs`` keys are absent.
    """
    if not mandatory:
        return
    if not isinstance(mandatory, dict):
        raise ValidationError(_("filter_mandatory must be a JSON object."))
    if "get" not in mandatory and "kwargs" not in mandatory:
        for _param, orm_key in mandatory.items():
            validate_filter_kwargs_for_model(model, {orm_key: 1})
        return
    get_map = mandatory.get("get")
    if get_map is not None:
        if not isinstance(get_map, dict):
            raise ValidationError(_("filter_mandatory.get must be an object."))
        for _param, orm_key in get_map.items():
            validate_filter_kwargs_for_model(model, {orm_key: 1})
    kw_map = mandatory.get("kwargs")
    if kw_map is not None:
        if not isinstance(kw_map, dict):
            raise ValidationError(_("filter_mandatory.kwargs must be an object."))
        for _url_name, orm_key in kw_map.items():
            validate_filter_kwargs_for_model(model, {orm_key: 1})


def validate_order_by_for_model(model: type[models.Model], order_by: Any) -> None:
    """
    ``order_by`` is a list of Django ordering strings (e.g. ``["title", "-pages"]``).
    ``"?"`` is allowed for random ordering.
    """
    if not order_by:
        return
    if not isinstance(order_by, list):
        raise ValidationError(_("order_by must be a list of strings."))
    for expr in order_by:
        if not isinstance(expr, str) or not expr.strip():
            raise ValidationError(_("Each order_by entry must be a non-empty string."))
        stripped = expr.strip()
        if stripped.startswith("-"):
            stripped = stripped[1:].strip()
        if stripped == "?":
            continue
        base = first_lookup_segment(stripped)
        if base == "pk":
            continue
        if get_field_or_accessor(model, base) is None:
            raise ValidationError(
                _("Invalid order_by: %(expr)r — %(base)r is not a field on %(model)s.")
                % {"expr": expr.strip(), "base": base, "model": model.__name__}
            )


def validate_export_filter_fields(
    model: type[models.Model],
    filter_config: Any,
    filter_request: Any,
    filter_mandatory: Any,
    order_by: Any,
) -> None:
    """Shared filter / ordering validation for report definitions and imports."""
    validate_filter_kwargs_for_model(model, filter_config or {})
    fr, _, _, _ = parse_filter_maps(filter_request, filter_mandatory)
    for _param, orm_key in fr.items():
        validate_filter_kwargs_for_model(model, {orm_key: 1})
    validate_filter_request_mandatory_get_overlap(filter_request, filter_mandatory)
    validate_filter_mandatory_for_model(model, filter_mandatory)
    validate_order_by_for_model(model, order_by)


def validate_export_column_specs(model: type[models.Model], columns: list[Any] | None) -> None:
    if not columns:
        return
    for col in columns:
        if not isinstance(col, str):
            raise ValidationError(_("Each column must be a string."))
        validate_export_column_spec(model, col)


def resolve_manager_to_queryset(model: type[models.Model], manager_path: str) -> Any:
    """Walk ``objects`` / ``objects.all``-style path; result must support ``.filter()``."""
    qs: Any = model
    for part in manager_path.split("."):
        qs = getattr(qs, part)
        if callable(qs) and not isinstance(qs, models.Manager):
            qs = qs()
    if not hasattr(qs, "filter"):
        raise ValidationError(
            _("Manager path “%(path)s” must resolve to a manager or queryset (got %(got)s).")
            % {"path": manager_path, "got": type(qs).__name__}
        )
    return qs
