"""Validate report filters and column specs against the target model."""

from __future__ import annotations

from collections.abc import Collection
from decimal import Decimal
from inspect import Parameter, signature
from functools import cached_property as functools_cached_property
from typing import Any

from django.core.exceptions import FieldDoesNotExist, ObjectDoesNotExist, ValidationError
from django.db import models
from django.db.models import ManyToManyField
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.translation import gettext_lazy as _

from ...utils.helpers import get_field_or_accessor


def first_lookup_segment(lookup: str) -> str:
    return lookup.split("__", 1)[0]


def normalized_annotation_name_list(raw: Any) -> list[str]:
    """Normalize a JSON list of annotation / alias names to non-empty strings."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if isinstance(x, str) and str(x).strip()]


def annotation_column_aliases_from_config(configuration: Any) -> frozenset[str]:
    """
    Column names supplied by ``QuerySet.annotate()`` (or alias/extra output) that
    are not ``Meta`` fields and not detectable on the model class. Declared on
    a category ``configuration`` or ``ImportDefinition.configuration``
    under ``annotation_columns``, ``annotated_columns``, or ``annotations``:
    each value is a JSON list of strings (merged).

    Used for ``order_by`` / filter validation together with
    :func:`annotation_aliases_for_definition`.
    """
    if not isinstance(configuration, dict):
        return frozenset()
    names: list[str] = []
    for key in ("annotation_columns", "annotated_columns", "annotations"):
        block = configuration.get(key)
        if isinstance(block, list):
            names.extend(normalized_annotation_name_list(block))
    return frozenset(names)


def _category_configurations(definition: Any) -> list[dict[str, Any]]:
    """Common configuration dicts of the tabular categories attached to ``definition``."""
    found: list[dict[str, Any]] = []
    related = getattr(definition, "category_configs", None)
    if related is None:
        return found
    try:
        categories = related.all()
    except (ObjectDoesNotExist, AttributeError):
        return found
    for category in categories:
        if getattr(category, "category_key", None) not in {"spreadsheet", "structured_data"}:
            continue
        configuration = getattr(category, "configuration", None)
        if isinstance(configuration, dict):
            found.append(configuration)
    return found


def annotation_aliases_for_definition(definition: Any) -> frozenset[str]:
    """
    Annotation / alias names for filter and ``order_by`` validation.

    Import definitions declare them on ``configuration``. Export definitions declare
    them on the spreadsheet and structured-data category configurations.
    """
    merged = annotation_column_aliases_from_config(getattr(definition, "configuration", None))
    for configuration in _category_configurations(definition):
        merged = merged | annotation_column_aliases_from_config(configuration)
    return merged


def is_non_field_reader_on_model(model_cls: type[models.Model], name: str) -> bool:
    """
    True when ``name`` is a ``@property`` or ``cached_property`` on the model class
    (readable on instances) but not a concrete/relational ORM field.
    Used so export paths like ``author.name_upper`` or ``payload_preview`` validate
    without listing them in table ``configuration`` / ``annotation_columns``.
    """
    if get_field_or_accessor(model_cls, name) is not None:
        return False
    cached_property_type: type | None
    try:
        from django.utils.functional import cached_property as imported_cached_property
    except ImportError:  # pragma: no cover
        cached_property_type = None
    else:
        cached_property_type = imported_cached_property
    for cls in model_cls.__mro__:
        if name not in cls.__dict__:
            continue
        val = cls.__dict__[name]
        if isinstance(val, property):
            return True
        if isinstance(val, functools_cached_property):
            return True
        if cached_property_type is not None and isinstance(val, cached_property_type):
            return True
    return False


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
    if get_m is None or not isinstance(get_m, dict):
        get_m = {}
    kw_map = mandatory.get("kwargs")
    if kw_map is None or not isinstance(kw_map, dict):
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


def parse_manager_kwargs_maps_from_definition(
    definition: Any,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Like :func:`parse_filter_maps_from_definition` for ``manager_kwargs_*`` on exports."""
    return parse_filter_maps(
        getattr(definition, "manager_kwargs_request", None),
        getattr(definition, "manager_kwargs_mandatory", None),
    )


def parse_manager_method_kwargs_request_from_definition(definition: Any) -> dict[str, Any]:
    """Return optional GET-to-method-argument mappings from an export definition."""
    raw = getattr(definition, "manager_method_kwargs_request", None)
    return raw if isinstance(raw, dict) else {}


_MANAGER_METHOD_ARGUMENT_TYPES = {
    "str",
    "date",
    "datetime",
    "int",
    "float",
    "decimal",
    "bool",
}


def normalize_manager_method_kwargs_request(request_map: Any) -> dict[str, tuple[str, str]]:
    """Normalize query-param mappings to ``{param: (method_kwarg, value_type)}``."""
    if request_map in (None, {}):
        return {}
    if not isinstance(request_map, dict):
        raise ValidationError(_("manager_method_kwargs_request must be a JSON object."))

    normalized: dict[str, tuple[str, str]] = {}
    for query_param, raw_spec in request_map.items():
        if not isinstance(query_param, str) or not query_param.strip():
            raise ValidationError(
                _("manager_method_kwargs_request keys must be non-empty query parameter names.")
            )
        if isinstance(raw_spec, str):
            method_kwarg = raw_spec
            value_type = "str"
        elif isinstance(raw_spec, dict):
            method_kwarg = raw_spec.get("kwarg")
            value_type = raw_spec.get("type", "str")
            if set(raw_spec) - {"kwarg", "type"}:
                raise ValidationError(
                    _("Manager method mapping for %(param)s has unsupported keys.")
                    % {"param": query_param}
                )
        else:
            raise ValidationError(
                _("Manager method mapping for %(param)s must be a string or object.")
                % {"param": query_param}
            )
        if not isinstance(method_kwarg, str) or not method_kwarg.strip():
            raise ValidationError(
                _("Manager method mapping for %(param)s needs a non-empty kwarg.")
                % {"param": query_param}
            )
        if not isinstance(value_type, str):
            raise ValidationError(
                _("Manager method mapping for %(param)s has an invalid type.")
                % {"param": query_param}
            )
        if value_type not in _MANAGER_METHOD_ARGUMENT_TYPES:
            raise ValidationError(
                _("Unsupported manager method argument type %(type)s.") % {"type": value_type}
            )
        normalized[query_param] = (method_kwarg, value_type)
    return normalized


def validate_manager_method_kwargs_request(
    model: type[models.Model],
    manager_path: str,
    request_map: Any,
) -> None:
    """Validate optional GET parameters mapped to a manager method's keyword arguments."""
    normalized = normalize_manager_method_kwargs_request(request_map)
    if not normalized:
        return

    method = resolve_manager_method(model, manager_path)
    try:
        method_parameters = signature(method).parameters
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            _("Cannot inspect manager method %(path)s: %(error)s")
            % {"path": manager_path, "error": str(exc)}
        ) from exc
    accepts_arbitrary_kwargs = any(
        parameter.kind == Parameter.VAR_KEYWORD for parameter in method_parameters.values()
    )
    mapped_kwargs: set[str] = set()
    for query_param, (method_kwarg, _value_type) in normalized.items():
        if method_kwarg in mapped_kwargs:
            raise ValidationError(
                _("A manager method argument can only be mapped from one query parameter.")
            )
        mapped_kwargs.add(method_kwarg)
        parameter = method_parameters.get(method_kwarg)
        if parameter is None and not accepts_arbitrary_kwargs:
            raise ValidationError(
                _("Manager method %(path)s has no argument %(name)s.")
                % {"path": manager_path, "name": method_kwarg}
            )
        if parameter is not None and parameter.kind in (
            Parameter.POSITIONAL_ONLY,
            Parameter.VAR_POSITIONAL,
        ):
            raise ValidationError(
                _("Manager method argument %(name)s must accept a keyword value.")
                % {"name": method_kwarg}
            )
        if parameter is not None and parameter.default is Parameter.empty:
            raise ValidationError(
                _(
                    "Manager method argument %(name)s must have a default because "
                    "request values are optional (%(param)s)."
                )
                % {"name": method_kwarg, "param": query_param}
            )


def coerce_manager_method_argument(argument_name: str, value: str, value_type: str) -> Any:
    """Coerce a request string using its declared manager method argument type."""
    if value_type == "str":
        return value
    if value_type == "date":
        coerced = parse_date(value)
    elif value_type == "datetime":
        coerced = parse_datetime(value)
    elif value_type == "int":
        try:
            return int(value)
        except ValueError as exc:
            raise ValidationError(
                _("Manager method argument %(name)s must be an integer.") % {"name": argument_name}
            ) from exc
    elif value_type == "float":
        try:
            return float(value)
        except ValueError as exc:
            raise ValidationError(
                _("Manager method argument %(name)s must be a number.") % {"name": argument_name}
            ) from exc
    elif value_type == "decimal":
        try:
            return Decimal(value)
        except (ValueError, ArithmeticError) as exc:
            raise ValidationError(
                _("Manager method argument %(name)s must be a decimal.") % {"name": argument_name}
            ) from exc
    elif value_type == "bool":
        normalized = value.strip().lower()
        if normalized in {"true", "1"}:
            return True
        if normalized in {"false", "0"}:
            return False
        raise ValidationError(
            _("Manager method argument %(name)s must be true or false.") % {"name": argument_name}
        )
    else:
        raise ValidationError(
            _("Unsupported manager method argument type %(type)s.") % {"type": value_type}
        )
    if coerced is None:
        raise ValidationError(
            _("Invalid value for manager method argument %(name)s.") % {"name": argument_name}
        )
    return coerced


def validate_export_filter_manager_disjoint(definition: Any) -> None:
    """
    Query param and URL kwarg names must not overlap between filter mappings and
    manager mappings (distinct payload keys do not make duplicate GET names safe).
    """
    fr, _f_mand, fget, fkw = parse_filter_maps_from_definition(definition)
    mr, _m_mand, mget, mkw = parse_manager_kwargs_maps_from_definition(definition)
    method_get = set(parse_manager_method_kwargs_request_from_definition(definition))
    g_overlap = (set(fr) | set(fget)) & (set(mr) | set(mget) | method_get)
    g_overlap |= (set(mr) | set(mget)) & method_get
    kw_overlap = set(fkw) & set(mkw)
    if g_overlap or kw_overlap:
        names = sorted(g_overlap | kw_overlap)
        raise ValidationError(
            _(
                "filter_* and manager request mappings must use distinct "
                "query param and URL kwarg names (overlap: %(overlap)s)."
            )
            % {"overlap": ", ".join(names)}
        )


def validate_import_match_fields(
    model: type[models.Model],
    names: Any,
) -> None:
    """
    Ensure ``match_fields`` is a list of distinct top-level ORM field names
    suitable for :meth:`~django.db.models.QuerySet.update_or_create` lookups.
    """
    if names in (None, []):
        return
    if not isinstance(names, list):
        raise ValidationError({"match_fields": _("Must be a list of field name strings.")})
    seen: set[str] = set()
    for raw in names:
        if not isinstance(raw, str) or not raw.strip():
            raise ValidationError({"match_fields": _("Each entry must be a non-empty field name.")})
        name = raw.strip()
        if name in seen:
            raise ValidationError(
                {"match_fields": _("Duplicate field %(name)s in match keys.") % {"name": name}}
            )
        seen.add(name)
        if "." in name:
            raise ValidationError(
                {
                    "match_fields": _("%(name)s: use a single model field name, not a path.")
                    % {"name": name}
                }
            )
        try:
            field = model._meta.get_field(name)
        except FieldDoesNotExist as exc:
            raise ValidationError(
                {
                    "match_fields": _("%(name)s is not a field on %(model)s.")
                    % {"name": name, "model": model.__name__}
                }
            ) from exc
        if isinstance(field, ManyToManyField) or getattr(field, "many_to_many", False):
            raise ValidationError(
                {
                    "match_fields": _("%(name)s: many-to-many fields cannot be used as match keys.")
                    % {"name": name}
                }
            )
        if field.is_relation and not (
            getattr(field, "many_to_one", False) or getattr(field, "one_to_one", False)
        ):
            raise ValidationError(
                {
                    "match_fields": _(
                        "%(name)s: only forward scalar, foreign key, and one-to-one "
                        "fields can be used as match keys."
                    )
                    % {"name": name}
                }
            )


def validate_filter_kwargs_for_model(
    model: type[models.Model],
    kwargs: dict[str, Any] | None,
    *,
    annotation_aliases: Collection[str] | None = None,
) -> None:
    """Reject unknown field names in ``filter()`` kwargs (first segment of each key)."""
    if not kwargs:
        return
    aliases = frozenset(annotation_aliases) if annotation_aliases else frozenset()
    for key in kwargs:
        if not isinstance(key, str):
            raise ValidationError(_("Filter keys must be strings."))
        base = first_lookup_segment(key)
        if base in aliases:
            continue
        if is_non_field_reader_on_model(model, base):
            continue
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
    except (TypeError, ValueError, ValidationError) as exc:
        raise ValidationError(
            _("Invalid filter value %(value)r for %(lookup)s: %(err)s")
            % {"value": raw, "lookup": orm_key, "err": exc}
        ) from exc


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


def _require_optional_map(value: Any, message: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValidationError(message)
    return value


def _validate_orm_lookup_values(
    model: type[models.Model],
    values: Any,
    annotation_aliases: Collection[str] | None,
) -> None:
    for orm_key in values:
        validate_filter_kwargs_for_model(model, {orm_key: 1}, annotation_aliases=annotation_aliases)


def validate_filter_mandatory_for_model(
    model: type[models.Model],
    mandatory: Any,
    *,
    annotation_aliases: Collection[str] | None = None,
    strict_orm_keys: bool = True,
) -> None:
    """
    ``filter_mandatory``: ``{"get": {...}, "kwargs": {...}}``, or shorthand
    ``{query_param: orm_key}`` (all GET) when ``get`` / ``kwargs`` keys are absent.

    When ``strict_orm_keys`` is False (exports only), only JSON shape is checked so
    annotation / manager-provided lookup names are allowed without resolving on the model.
    """
    if not mandatory:
        return
    if not isinstance(mandatory, dict):
        raise ValidationError(_("filter_mandatory must be a JSON object."))
    shorthand = "get" not in mandatory and "kwargs" not in mandatory
    if not strict_orm_keys:
        if shorthand:
            return
        _require_optional_map(mandatory.get("get"), _("filter_mandatory.get must be an object."))
        _require_optional_map(
            mandatory.get("kwargs"), _("filter_mandatory.kwargs must be an object.")
        )
        return
    if shorthand:
        _validate_orm_lookup_values(model, mandatory.values(), annotation_aliases)
        return
    get_map = _require_optional_map(
        mandatory.get("get"), _("filter_mandatory.get must be an object.")
    )
    if get_map is not None:
        _validate_orm_lookup_values(model, get_map.values(), annotation_aliases)
    kw_map = _require_optional_map(
        mandatory.get("kwargs"), _("filter_mandatory.kwargs must be an object.")
    )
    if kw_map is not None:
        _validate_orm_lookup_values(model, kw_map.values(), annotation_aliases)


def validate_order_by_for_model(
    model: type[models.Model],
    order_by: Any,
    *,
    annotation_aliases: Collection[str] | None = None,
) -> None:
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
        aliases = frozenset(annotation_aliases) if annotation_aliases else frozenset()
        if base in aliases:
            continue
        if is_non_field_reader_on_model(model, base):
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
    *,
    annotation_aliases: Collection[str] | None = None,
    manager_kwargs_config: Any = None,
    manager_kwargs_request: Any = None,
    manager_kwargs_mandatory: Any = None,
    strict_orm_keys_for_filters: bool = True,
) -> None:
    """
    Shared filter / ordering validation for export and import definitions.

    ``strict_orm_keys_for_filters`` is True for imports: every filter / mandatory ORM
    lookup must match a model field (or listed annotation alias). For exports it is
    False so lookups may target queryset annotations or manager-only fields that are
    not introspectable on the model class.
    """
    if strict_orm_keys_for_filters:
        validate_filter_kwargs_for_model(
            model, filter_config or {}, annotation_aliases=annotation_aliases
        )
    else:
        if filter_config not in (None, {}) and not isinstance(filter_config, dict):
            raise ValidationError(_("filter_config must be a JSON object."))
        if filter_request not in (None, {}) and not isinstance(filter_request, dict):
            raise ValidationError(_("filter_request must be a JSON object."))
    fr, _fr_mand, _fr_get, _fr_kw = parse_filter_maps(filter_request, filter_mandatory)
    if strict_orm_keys_for_filters:
        for orm_key in fr.values():
            validate_filter_kwargs_for_model(
                model, {orm_key: 1}, annotation_aliases=annotation_aliases
            )
    validate_filter_request_mandatory_get_overlap(filter_request, filter_mandatory)
    validate_filter_mandatory_for_model(
        model,
        filter_mandatory,
        annotation_aliases=annotation_aliases,
        strict_orm_keys=strict_orm_keys_for_filters,
    )
    validate_order_by_for_model(model, order_by, annotation_aliases=annotation_aliases)
    _validate_manager_kwargs(
        model,
        annotation_aliases=annotation_aliases,
        manager_kwargs_config=manager_kwargs_config,
        manager_kwargs_request=manager_kwargs_request,
        manager_kwargs_mandatory=manager_kwargs_mandatory,
        strict_orm_keys_for_filters=strict_orm_keys_for_filters,
    )


def _validate_manager_kwargs(
    model: type[models.Model],
    *,
    annotation_aliases: Collection[str] | None,
    manager_kwargs_config: Any,
    manager_kwargs_request: Any,
    manager_kwargs_mandatory: Any,
    strict_orm_keys_for_filters: bool,
) -> None:
    if (
        manager_kwargs_config is None
        and manager_kwargs_request is None
        and manager_kwargs_mandatory is None
    ):
        return
    _require_loose_object(
        manager_kwargs_config,
        _("manager_kwargs_config must be a JSON object."),
        strict_orm_keys_for_filters,
    )
    _require_loose_object(
        manager_kwargs_request,
        _("manager_kwargs_request must be a JSON object."),
        strict_orm_keys_for_filters,
    )
    if strict_orm_keys_for_filters:
        validate_filter_kwargs_for_model(
            model, manager_kwargs_config or {}, annotation_aliases=annotation_aliases
        )
        mapped, _mandatory, _get, _kw = parse_filter_maps(
            manager_kwargs_request, manager_kwargs_mandatory
        )
        for orm_key in mapped.values():
            validate_filter_kwargs_for_model(
                model, {orm_key: 1}, annotation_aliases=annotation_aliases
            )
    validate_filter_request_mandatory_get_overlap(manager_kwargs_request, manager_kwargs_mandatory)
    validate_filter_mandatory_for_model(
        model,
        manager_kwargs_mandatory,
        annotation_aliases=annotation_aliases,
        strict_orm_keys=strict_orm_keys_for_filters,
    )


def _require_loose_object(value: Any, message: Any, strict: bool) -> None:
    if strict or value in (None, {}) or isinstance(value, dict):
        return
    raise ValidationError(message)


def resolve_manager_method(model: type[models.Model], manager_path: str) -> Any:
    """Resolve the callable at the end of a manager path without invoking it."""
    parts = manager_path.split(".")
    if len(parts) < 2:
        raise ValidationError(
            _("Manager path “%(path)s” does not identify a manager method.")
            % {"path": manager_path}
        )
    method_owner: Any = model
    for part in parts[:-1]:
        method_owner = getattr(method_owner, part)
        if callable(method_owner) and not isinstance(method_owner, models.Manager):
            method_owner = method_owner()
    method = getattr(method_owner, parts[-1])
    if not callable(method) or isinstance(method, models.Manager):
        raise ValidationError(
            _("Manager path “%(path)s” does not end in a callable method.") % {"path": manager_path}
        )
    return method


def resolve_manager_to_queryset(
    model: type[models.Model],
    manager_path: str,
    *,
    method_kwargs: dict[str, Any] | None = None,
) -> Any:
    """Walk ``objects`` / ``objects.all``-style path; result must support ``.filter()``."""
    qs: Any = model
    parts = manager_path.split(".")
    for index, part in enumerate(parts):
        qs = getattr(qs, part)
        if callable(qs) and not isinstance(qs, models.Manager):
            kwargs = (method_kwargs or {}) if index == len(parts) - 1 else {}
            if kwargs:
                try:
                    signature(qs).bind_partial(**kwargs)
                except (TypeError, ValueError) as exc:
                    raise ValidationError(
                        _("Invalid manager method arguments: %(error)s") % {"error": str(exc)}
                    ) from exc
            qs = qs(**kwargs)
    if not hasattr(qs, "filter"):
        raise ValidationError(
            _("Manager path “%(path)s” must resolve to a manager or queryset (got %(got)s).")
            % {"path": manager_path, "got": type(qs).__name__}
        )
    return qs
