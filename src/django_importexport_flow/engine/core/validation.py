"""Validate report filters and column specs against the target model."""

from __future__ import annotations

from functools import cached_property as functools_cached_property
from typing import Any, Collection

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import ManyToManyField
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
    ``ExportConfigTable.configuration`` or ``ImportDefinition.configuration``
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


def _export_table_configuration_for_aliases(definition: Any) -> dict[str, Any] | None:
    """``ExportConfigTable.configuration`` when ``definition`` is an export with a table row."""
    try:
        ct = definition.config_table
    except Exception:
        return None
    cfg = getattr(ct, "configuration", None)
    return cfg if isinstance(cfg, dict) else None


def annotation_aliases_for_definition(definition: Any) -> frozenset[str]:
    """
    Annotation / alias names for filter and ``order_by`` validation:

    * **Import** — lists under :attr:`~django_importexport_flow.models.ImportDefinition.configuration`
      (``annotation_columns``, ``annotated_columns``, ``annotations``).
    * **Export** — same keys under :class:`~django_importexport_flow.models.ExportConfigTable`
      ``configuration`` only (queryset shape stays on :class:`~django_importexport_flow.models.ExportDefinition`).
    """
    merged = annotation_column_aliases_from_config(getattr(definition, "configuration", None))
    merged = merged | annotation_column_aliases_from_config(
        _export_table_configuration_for_aliases(definition)
    )
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
    try:
        from django.utils.functional import cached_property as django_cached_property_cls
    except ImportError:  # pragma: no cover
        django_cached_property_cls = None
    for cls in model_cls.__mro__:
        if name not in cls.__dict__:
            continue
        val = cls.__dict__[name]
        if isinstance(val, property):
            return True
        if isinstance(val, functools_cached_property):
            return True
        if django_cached_property_cls is not None and isinstance(
            val, django_cached_property_cls
        ):
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


def parse_manager_kwargs_maps_from_definition(
    definition: Any,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Like :func:`parse_filter_maps_from_definition` for ``manager_kwargs_*`` on exports."""
    return parse_filter_maps(
        getattr(definition, "manager_kwargs_request", None),
        getattr(definition, "manager_kwargs_mandatory", None),
    )


def validate_export_filter_manager_disjoint(definition: Any) -> None:
    """
    Query param and URL kwarg names must not overlap between ``filter_*`` and
    ``manager_kwargs_*`` (distinct ``fr_get_*`` vs ``mg_get_*`` form keys).
    """
    fr, _f_mand, fget, fkw = parse_filter_maps_from_definition(definition)
    mr, _m_mand, mget, mkw = parse_manager_kwargs_maps_from_definition(definition)
    g_overlap = (set(fr) | set(fget)) & (set(mr) | set(mget))
    kw_overlap = set(fkw) & set(mkw)
    if g_overlap or kw_overlap:
        names = sorted(g_overlap | kw_overlap)
        raise ValidationError(
            _(
                "filter_request / filter_mandatory and manager_kwargs_* must use distinct "
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
        raise ValidationError(
            {"match_fields": _("Must be a list of field name strings.")}
        )
    seen: set[str] = set()
    for raw in names:
        if not isinstance(raw, str) or not raw.strip():
            raise ValidationError(
                {"match_fields": _("Each entry must be a non-empty field name.")}
            )
        name = raw.strip()
        if name in seen:
            raise ValidationError(
                {
                    "match_fields": _(
                        "Duplicate field %(name)s in match keys."
                    )
                    % {"name": name}
                }
            )
        seen.add(name)
        if "." in name:
            raise ValidationError(
                {
                    "match_fields": _(
                        "%(name)s: use a single model field name, not a path."
                    )
                    % {"name": name}
                }
            )
        try:
            field = model._meta.get_field(name)
        except Exception:
            raise ValidationError(
                {
                    "match_fields": _(
                        "%(name)s is not a field on %(model)s."
                    )
                    % {"name": name, "model": model.__name__}
                }
            )
        if isinstance(field, ManyToManyField) or getattr(field, "many_to_many", False):
            raise ValidationError(
                {
                    "match_fields": _(
                        "%(name)s: many-to-many fields cannot be used as match keys."
                    )
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
    except Exception as exc:
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
    if not strict_orm_keys:
        if "get" not in mandatory and "kwargs" not in mandatory:
            return
        get_map = mandatory.get("get")
        if get_map is not None and not isinstance(get_map, dict):
            raise ValidationError(_("filter_mandatory.get must be an object."))
        kw_map = mandatory.get("kwargs")
        if kw_map is not None and not isinstance(kw_map, dict):
            raise ValidationError(_("filter_mandatory.kwargs must be an object."))
        return
    if "get" not in mandatory and "kwargs" not in mandatory:
        for _param, orm_key in mandatory.items():
            validate_filter_kwargs_for_model(
                model, {orm_key: 1}, annotation_aliases=annotation_aliases
            )
        return
    get_map = mandatory.get("get")
    if get_map is not None:
        if not isinstance(get_map, dict):
            raise ValidationError(_("filter_mandatory.get must be an object."))
        for _param, orm_key in get_map.items():
            validate_filter_kwargs_for_model(
                model, {orm_key: 1}, annotation_aliases=annotation_aliases
            )
    kw_map = mandatory.get("kwargs")
    if kw_map is not None:
        if not isinstance(kw_map, dict):
            raise ValidationError(_("filter_mandatory.kwargs must be an object."))
        for _url_name, orm_key in kw_map.items():
            validate_filter_kwargs_for_model(
                model, {orm_key: 1}, annotation_aliases=annotation_aliases
            )


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
        for _param, orm_key in fr.items():
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
    if (
        manager_kwargs_config is not None
        or manager_kwargs_request is not None
        or manager_kwargs_mandatory is not None
    ):
        if strict_orm_keys_for_filters:
            validate_filter_kwargs_for_model(
                model, manager_kwargs_config or {}, annotation_aliases=annotation_aliases
            )
        elif manager_kwargs_config not in (None, {}) and not isinstance(
            manager_kwargs_config, dict
        ):
            raise ValidationError(_("manager_kwargs_config must be a JSON object."))
        if not strict_orm_keys_for_filters and manager_kwargs_request not in (
            None,
            {},
        ) and not isinstance(manager_kwargs_request, dict):
            raise ValidationError(_("manager_kwargs_request must be a JSON object."))
        mgr_fr, _mgr_mand, _mgr_get, _mgr_kw = parse_filter_maps(
            manager_kwargs_request, manager_kwargs_mandatory
        )
        if strict_orm_keys_for_filters:
            for _param, orm_key in mgr_fr.items():
                validate_filter_kwargs_for_model(
                    model, {orm_key: 1}, annotation_aliases=annotation_aliases
                )
        validate_filter_request_mandatory_get_overlap(
            manager_kwargs_request, manager_kwargs_mandatory
        )
        validate_filter_mandatory_for_model(
            model,
            manager_kwargs_mandatory,
            annotation_aliases=annotation_aliases,
            strict_orm_keys=strict_orm_keys_for_filters,
        )


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
