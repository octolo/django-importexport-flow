"""Import preview rows built from a validated dataframe."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar

import pandas as pd
from django.contrib.admin import ModelAdmin
from django.contrib.admin.options import ShowFacets
from django.db import models
from django.http import HttpRequest
from virtualqueryset import VirtualQuerySet  # type: ignore[import-untyped]

from ..models.preview import DataPreviewRow
from ..utils.helpers import get_setting, preview_scalar


def _filter_keys_from_cleaned(cleaned: dict) -> dict:
    return {k: v for k, v in cleaned.items() if k.startswith("fr_")}


_PREVIEW_ROW_LIMIT = get_setting("IMPORT_PREVIEW_ROW_LIMIT")


def _sanitize_path_to_field_name(path: str, used: set[str]) -> str:
    base = path.replace(".", "_").replace("-", "_")
    if not base.isidentifier():
        base = f"f_{abs(hash(path)) % (10**9)}"
    name = base
    n = 0
    while name in used:
        n += 1
        name = f"{base}_{n}"
    used.add(name)
    return name


def build_import_preview_model_class(
    column_paths: list[str],
    column_labels: list[str],
) -> tuple[type[models.Model], list[str]]:
    """
    Return a concrete unmanaged model class and ``list_display`` field names (same order as paths).

    Field ``verbose_name`` is the human label; technical paths are not stored as DB columns
    (Django field names cannot contain dots).
    """
    if len(column_labels) != len(column_paths):
        raise ValueError("column_labels and column_paths must have the same length.")
    used: set[str] = {"id"}
    fields: dict[str, models.Field] = {
        "id": models.BigAutoField(primary_key=True),
    }
    display_fields: list[str] = []
    for path, label in zip(column_paths, column_labels, strict=True):
        fname = _sanitize_path_to_field_name(path, used)
        fields[fname] = models.CharField(
            max_length=4096,
            verbose_name=label,
            blank=True,
        )
        display_fields.append(fname)

    meta = type(
        "Meta",
        (),
        {
            "managed": False,
            "ordering": ("id",),
            "app_label": "django_importexport_flow",
            "verbose_name": "Import preview row",
            "verbose_name_plural": "Import preview rows",
        },
    )
    attrs = {
        "Meta": meta,
        "__module__": "django_importexport_flow.models.preview",
        **fields,
    }
    cls = type("ImportPreviewDynamic", (DataPreviewRow,), attrs)
    return cls, display_fields


def dataframe_to_preview_rows(
    df: Any,
    column_paths: list[str],
    list_display_fields: list[str],
    *,
    limit: int = _PREVIEW_ROW_LIMIT,
) -> list[dict[str, Any]]:
    """Map dataframe columns (same order as paths) to model field names; include ``id``."""
    if not isinstance(df, pd.DataFrame):
        raise TypeError("dataframe_to_preview_rows expects a pandas DataFrame.")
    if len(df.columns) != len(list_display_fields) or len(column_paths) != len(list_display_fields):
        raise ValueError("DataFrame columns and import paths are out of sync.")
    rows: list[dict[str, Any]] = []
    for i, (_ix, row) in enumerate(df.head(limit).iterrows(), start=1):
        d: dict[str, Any] = {"id": i}
        for col, fn in zip(df.columns, list_display_fields, strict=True):
            d[fn] = str(preview_scalar(row[col]))
        rows.append(d)
    return rows


def _preview_column(field_name: str, label: str) -> Callable[[Any], str]:
    """Read a preview row without looking the column up on the parent admin model."""

    def column(obj: Any) -> str:
        return str(getattr(obj, field_name, ""))

    column.short_description = label  # type: ignore[attr-defined]
    return column


def build_import_preview_list_payload(
    parent_model_admin: ModelAdmin,
    df: Any,
    column_paths: list[str],
    column_labels: list[str],
) -> dict[str, Any]:
    """
    Payload for ``admin_boost_view("list", ...)``: ``VirtualQuerySet`` + ephemeral ``ModelAdmin``.

    ``list_display`` is a list of callables. django-boosted builds the ChangeList
    from the parent admin model, which does not have the preview columns.
    """
    model_class, list_display_fields = build_import_preview_model_class(column_paths, column_labels)
    rows = dataframe_to_preview_rows(df, column_paths, list_display_fields)
    preview_columns = [
        _preview_column(field_name, label)
        for field_name, label in zip(list_display_fields, column_labels, strict=True)
    ]
    vqs = VirtualQuerySet(model=model_class, data=rows)

    site = parent_model_admin.admin_site

    class ImportPreviewModelAdmin(ModelAdmin):
        model = model_class
        list_display: list[str | Callable[[Any], str | bool]] = list(  # noqa: RUF012
            list_display_fields
        )
        list_display_links: tuple[str, ...] | None = None
        list_filter: ClassVar[tuple[Any, ...]] = ()
        search_fields: ClassVar[tuple[str, ...]] = ()
        ordering: ClassVar[tuple[str, ...]] = ()
        list_per_page = _PREVIEW_ROW_LIMIT
        list_max_show_all = 200
        sortable_by: ClassVar[tuple[str, ...]] = ()
        actions: tuple[Any, ...] = ()
        show_full_result_count = False
        show_facets = ShowFacets.NEVER

        def get_queryset(self, request: HttpRequest):
            return vqs

    preview_admin = ImportPreviewModelAdmin(model_class, site)

    return {
        "queryset": vqs,
        "list_display": preview_columns,
        "list_filter": (),
        "search_fields": (),
        "model_admin": preview_admin,
        "can_change": False,
        "has_change_permission": False,
        "has_create": False,
        "has_add_permission": False,
    }
