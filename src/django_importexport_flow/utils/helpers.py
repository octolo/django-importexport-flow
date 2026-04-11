"""ORM/path helpers (column labels, relation accessors, JSON paths, export/download filenames)."""

from __future__ import annotations

import re
from typing import Any

from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.db.models import JSONField, ManyToManyField

__all__ = [
    "M2M_SLOT_PATH_PATTERN",
    "dataframe_preview_table",
    "get_expanded_related_value",
    "get_field_or_accessor",
    "get_export_definitions",
    "get_related_model_for_accessor",
    "get_value_from_path",
    "label_for_m2m_slot_path",
    "label_for_slot_path",
    "max_relation_count",
    "max_relation_counts",
    "normalize_table_column",
    "parse_reverse_expand_spec",
    "resolve_expand_relation",
    "column_label_override_from_configuration",
    "resolve_table_column_label",
    "verbose_name_for_field_path",
    "get_setting",
    "safe_download_stem",
    "export_timestamp_for_filename",
    "dated_export_filename",
    "configuration_json_download_filename",
]

# ``book_set.*[title:pages]`` — reverse manager, repeated columns per related row
REVERSE_EXPAND_PATTERN = re.compile(
    r"^([a-zA-Z_][a-zA-Z0-9_]*)\.\*\[(.+)\]\s*$",
)
# ``tags.0.name`` / ``tags.0.category.name`` — slot index + path on the related model
M2M_SLOT_PATH_PATTERN = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*)\.(\d+)\.(.+)$")


def _get_path_segment(current: Any, part: str) -> Any:
    """One step: model attribute, ``dict`` key, or ``list`` / ``tuple`` index."""
    if current is None:
        return None
    if isinstance(current, dict):
        return current.get(part)
    if isinstance(current, (list, tuple)):
        if part.isdigit():
            idx = int(part)
            if 0 <= idx < len(current):
                return current[idx]
        return None
    return getattr(current, part, None)


def get_value_from_path(obj: Any, path: str) -> Any:
    """
    Walk a dotted path: ORM fields and relations (``author.name``), then
    ``dict`` / ``list`` segments for ``JSONField`` (``metadata.lang``,
    ``metadata.items.0``).

    Many-to-many slot paths (``tags.0.name``): ``N``-th related row by primary key
    order, then the field on that instance.
    """
    m = M2M_SLOT_PATH_PATTERN.match(path.strip())
    if m and obj is not None:
        rel_name, slot_s, rest = m.groups()
        mgr = getattr(obj, rel_name, None)
        if mgr is not None and hasattr(mgr, "all"):
            idx = int(slot_s)
            items = list(mgr.all().order_by("pk"))
            if 0 <= idx < len(items):
                return get_value_from_path(items[idx], rest)
            return None
    current = obj
    for part in path.split("."):
        if current is None:
            return None
        current = _get_path_segment(current, part)
    return current


def _next_model_for_rel_field(field: Any) -> type[models.Model] | None:
    """Model reached after following a relation field (forward FK/O2O or reverse O2O)."""
    if getattr(field, "concrete", False):
        rf = getattr(field, "remote_field", None)
        if rf is not None and getattr(rf, "model", None) is not None:
            return rf.model
    return getattr(field, "related_model", None)


def _field_by_meta_or_accessor(model: type[models.Model], name: str) -> Any:
    try:
        return model._meta.get_field(name)
    except FieldDoesNotExist:
        pass
    for candidate in model._meta.get_fields():
        if not candidate.is_relation:
            continue
        ga = getattr(candidate, "get_accessor_name", None)
        if ga is not None and ga() == name:
            return candidate
    return None


def get_field_or_accessor(model: type[models.Model], name: str) -> Any:
    """Forward field or reverse accessor (``related_name`` / ``_set``), or ``None``."""
    return _field_by_meta_or_accessor(model, name)


def label_for_slot_path(model: type[models.Model], path: str) -> str | None:
    """
    Human-readable header for ``relation.slot_index.field`` where ``relation`` is either a
    many-to-many field (``tags.0.name``) or a reverse FK accessor (``book_set.0.title``).
    """
    m = M2M_SLOT_PATH_PATTERN.match(path.strip())
    if not m:
        return None
    rel_name, slot_s, sub = m.groups()
    field = get_field_or_accessor(model, rel_name)
    if field is None:
        return None
    if isinstance(field, ManyToManyField):
        rm = field.remote_field.model
    elif getattr(field, "one_to_many", False) and not getattr(field, "many_to_many", False):
        rm = field.related_model
    else:
        return None
    vn = verbose_name_for_field_path(rm, sub)
    if vn is None:
        return None
    return f"{vn} {int(slot_s) + 1}"


def label_for_m2m_slot_path(model: type[models.Model], path: str) -> str | None:
    """Alias for :func:`label_for_slot_path` (covers M2M and reverse one-to-many slots)."""
    return label_for_slot_path(model, path)


def verbose_name_for_field_path(model: type[models.Model], path: str) -> str | None:
    """
    Verbose label for a column path: last ORM field, or JSONField + subpath in
    parentheses when the tail lives inside JSON (``metadata (lang)``).
    Uses :func:`get_field_or_accessor` so reverse relations (e.g. ``author.profile``) resolve.
    """
    parts = path.strip().split(".")
    if not parts or not path.strip():
        return None
    current_model = model
    last_field = None
    i = 0
    while i < len(parts):
        last_field = get_field_or_accessor(current_model, parts[i])
        if last_field is None:
            return None
        i += 1
        if i >= len(parts):
            break
        if isinstance(last_field, JSONField):
            return f"{str(last_field.verbose_name)} ({'.'.join(parts[i:])})"
        if isinstance(last_field, ManyToManyField):
            return None
        nxt = _next_model_for_rel_field(last_field)
        if nxt is None:
            return None
        current_model = nxt
    if last_field is None:
        return None
    return str(last_field.verbose_name)


def normalize_table_column(column: str) -> str:
    """
    A column is either a dotted path (``author.name``) or an expand spec
    (``book_set.*[title:pages:price]``). Dict / legacy formats are not supported.
    """
    if not isinstance(column, str):
        raise TypeError(f"Column must be str, not {type(column).__name__}.")
    spec = column.strip()
    if not spec:
        raise ValueError("Column spec must be non-empty.")
    return spec


def column_label_override_from_configuration(
    configuration: dict[str, Any] | None,
    field_key: str,
) -> str | None:
    """
    Human label from :class:`~django_importexport_flow.models.ExportConfigTable`
    ``configuration``: entry ``f\"{field_key}_label\"`` (non-empty string), e.g.
    ``my_ann_field_label`` for column path ``my_ann_field``.
    """
    if not isinstance(configuration, dict) or not field_key:
        return None
    raw = configuration.get(f"{field_key}_label")
    if raw is None:
        return None
    s = str(raw).strip()
    return s if s else None


def resolve_table_column_label(
    model: type[models.Model],
    data_path: str,
    *,
    configuration: dict[str, Any] | None = None,
) -> str:
    """
    Verbose name from model meta when possible; if missing or blank,
    ``configuration[``f\"{data_path}_label\"``]`` when ``configuration`` is the
    export table config dict; else ``data_path``.
    """
    slot = label_for_slot_path(model, data_path)
    if slot is not None:
        return slot
    vn = verbose_name_for_field_path(model, data_path)
    if vn is not None and str(vn).strip():
        return str(vn).strip()
    override = column_label_override_from_configuration(configuration, data_path)
    if override is not None:
        return override
    return data_path


def parse_reverse_expand_spec(path: str) -> tuple[str, list[str]] | None:
    """
    Parse ``relation.*[field_a:field_b]`` (subfields on the related model).

    Returns ``(relation_name, [field_a, field_b])`` or None if not an expand spec.
    """
    m = REVERSE_EXPAND_PATTERN.match(path.strip())
    if not m:
        return None
    relation_name, bracket = m.groups()
    subfields = [p.strip() for p in bracket.split(":") if p.strip()]
    if not subfields:
        return None
    return relation_name, subfields


def get_related_model_for_accessor(
    model: type[models.Model], relation_name: str
) -> type[models.Model]:
    """Resolve the related model for a forward or reverse relation name."""
    field = _field_by_meta_or_accessor(model, relation_name)
    if field is None:
        raise FieldDoesNotExist(
            f"{model.__name__} has no field or reverse accessor {relation_name!r}."
        )
    related = getattr(field, "related_model", None)
    if related is None:
        raise ValueError(f"Field {relation_name!r} on {model.__name__} has no related_model.")
    return related


def resolve_expand_relation(
    model: type[models.Model], user_name: str
) -> tuple[type[models.Model], str]:
    """
    Resolve a reverse one-to-many relation from config (meta name or Python accessor).

    Returns ``(related_model, python_accessor_name)`` for ``getattr``, ``prefetch_related``,
    and ``RelatedManager.all()``.
    """
    field = _field_by_meta_or_accessor(model, user_name)
    if field is None:
        raise FieldDoesNotExist(f"{model.__name__} has no field or reverse accessor {user_name!r}.")
    if not getattr(field, "one_to_many", False):
        raise ValueError(
            f"{user_name!r} must be a reverse relation (one-to-many), "
            f"e.g. book_set.*[title:pages] on Author."
        )
    related = getattr(field, "related_model", None)
    if related is None:
        raise ValueError(f"Cannot resolve related model for {user_name!r}.")
    accessor = field.get_accessor_name()
    return related, accessor


def _orm_count_lookup_for_reverse_accessor(model: type[models.Model], accessor: str) -> str:
    """
    Map reverse manager name (e.g. ``book_set`` for ``getattr`` / ``prefetch_related``) to the
    related object's :class:`~django.db.models.ManyToOneRel` ``name`` used by ``Count()`` (often
    the related model's ``model_name``).
    """
    for f in model._meta.get_fields():
        if getattr(f, "one_to_many", False) and f.get_accessor_name() == accessor:
            return f.name
    return accessor


def max_relation_count(queryset: models.QuerySet, relation_name: str) -> int:
    """Maximum number of related objects for ``relation_name`` across the queryset."""
    from django.db.models import Count, Max

    lookup = _orm_count_lookup_for_reverse_accessor(queryset.model, relation_name)
    key = "_djief_rc_0"
    row = queryset.annotate(**{key: Count(lookup)}).aggregate(m=Max(key))
    v = row.get("m")
    return int(v) if v is not None else 0


def max_relation_counts(queryset: models.QuerySet, relation_names: list[str]) -> dict[str, int]:
    """
    Max related-object count per reverse accessor (e.g. ``book_set``), across ``queryset``.

    Uses ``Count`` / ``Max`` on the queryset instead of loading related rows per parent row.
    """
    from django.db.models import Count, Max

    counts = {r: 0 for r in relation_names}
    if not relation_names:
        return counts
    model = queryset.model
    unique = list(dict.fromkeys(relation_names))
    lookups = [_orm_count_lookup_for_reverse_accessor(model, rel) for rel in unique]
    ann = {f"_djief_rc_{i}": Count(lookup) for i, lookup in enumerate(lookups)}
    agg = {f"_djief_mx_{i}": Max(f"_djief_rc_{i}") for i in range(len(unique))}
    row = queryset.annotate(**ann).aggregate(**agg)
    max_by_rel: dict[str, int] = {}
    for i, rel in enumerate(unique):
        v = row.get(f"_djief_mx_{i}")
        max_by_rel[rel] = int(v) if v is not None else 0
    return {r: max_by_rel.get(r, 0) for r in relation_names}


def get_expanded_related_value(
    obj: Any,
    relation_name: str,
    slot_index: int,
    field_path: str,
) -> Any:
    """
    ``slot_index`` 0-based index in ``relation_name.all().order_by('pk')``;
    ``field_path`` may be dotted on the related instance.
    """
    rel = getattr(obj, relation_name, None)
    if rel is None:
        return None
    if hasattr(rel, "all"):
        items = list(rel.order_by("pk"))
    else:
        if slot_index == 0:
            return get_value_from_path(rel, field_path)
        return None
    if slot_index >= len(items):
        return None
    return get_value_from_path(items[slot_index], field_path)


def get_export_definitions(model_class: type[models.Model]) -> models.QuerySet:
    from django_importexport_flow.models import ExportDefinition

    return ExportDefinition.objects.for_model(model_class)


def dataframe_preview_table(df: Any, *, limit: int = 30) -> tuple[list[str], list[list[Any]]]:
    """
    Build **column names** and **row values** from a pandas ``DataFrame`` for a tabular
    preview (HTML/API). Values are JSON-friendly (empty string for NaN, ISO for datetimes).

    Requires **pandas** to be installed (same as django-importexport-flow).

    :param df: Input frame.
    :param limit: Max number of data rows (default 30).
    :returns: ``(column_names, rows)`` where ``rows`` is a list of lists aligned with ``column_names``.
    """
    import pandas as pd

    if not isinstance(df, pd.DataFrame):
        raise TypeError(
            f"dataframe_preview_table expects pandas.DataFrame, got {type(df).__name__!r}."
        )

    def _preview_scalar(v: Any) -> Any:
        if pd.isna(v):
            return ""
        iso = getattr(v, "isoformat", None)
        if callable(iso):
            return iso()
        try:
            import numpy as np

            if isinstance(v, np.generic):
                return v.item()
        except ImportError:
            pass
        return v

    cols = [str(c) for c in df.columns]
    rows_out: list[list[Any]] = []
    for _, row in df.head(limit).iterrows():
        r: list[Any] = []
        for c in df.columns:
            r.append(_preview_scalar(row[c]))
        rows_out.append(r)
    return cols, rows_out


def safe_download_stem(
    raw_name: str | None,
    *,
    fallback: str = "export",
    max_len: int = 80,
) -> str:
    """Sanitize a title or name for use as a download filename stem (no extension)."""
    base = re.sub(r"[^\w\-.]+", "_", raw_name or "").strip("_") or fallback
    return base[:max_len]


def export_timestamp_for_filename() -> str:
    """Local time, second precision, safe for filenames (e.g. ``20260329_143045``)."""
    from django.utils import timezone

    return timezone.localtime(timezone.now()).strftime("%Y%m%d_%H%M%S")


def dated_export_filename(safe_stem: str, ext: str) -> str:
    """
    ``safe_stem`` = basename without extension (already sanitized).
    ``ext`` must include the leading dot (e.g. ``.csv``).
    """
    return f"{safe_stem}_{export_timestamp_for_filename()}{ext}"


def configuration_json_download_filename(instance: Any) -> str:
    """
    Basename for admin *Export configuration (JSON)* downloads:
    ``{named_id}-{updated_at_local}.json``.
    """
    from django.utils import timezone

    raw_id = getattr(instance, "named_id", None)
    stem = safe_download_stem(
        str(raw_id) if raw_id not in (None, "") else None,
        fallback="configuration",
    )
    updated = getattr(instance, "updated_at", None)
    if updated is not None:
        ts_part = timezone.localtime(updated).strftime("%Y%m%d_%H%M%S")
    else:
        ts_part = export_timestamp_for_filename()
    return f"{stem}-{ts_part}.json"


def get_setting(name: str, default: Any | None = None) -> Any:
    """
    Return a package setting: defaults from
    :attr:`django_importexport_flow.apps.DjangoImportExportFlowConfig.default_settings`,
    then optional Django overrides (``DJANGO_IMPORTEXPORT_FLOW`` dict or
    ``DJANGO_IMPORTEXPORT_FLOW_<NAME>``).
    """
    from django.conf import settings

    from ..apps import DjangoImportExportFlowConfig

    pkg_defaults = DjangoImportExportFlowConfig.default_settings
    if name not in pkg_defaults and default is None:
        raise KeyError(f"Unknown django-importexport-flow setting: {name!r}")
    fallback = pkg_defaults[name] if name in pkg_defaults else default
    if not settings.configured:
        return fallback
    flow = getattr(settings, "DJANGO_IMPORTEXPORT_FLOW", None)
    if isinstance(flow, dict) and name in flow:
        return flow[name]
    env_key = f"DJANGO_IMPORTEXPORT_FLOW_{name.upper()}"
    if hasattr(settings, env_key):
        return getattr(settings, env_key)
    return fallback
