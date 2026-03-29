"""Shared admin form fields for ``filter_request`` / ``filter_mandatory`` (export + import)."""

from __future__ import annotations

from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _

from .export import form_field_name_for_query_param, form_field_name_for_url_kwarg
from .validation import parse_filter_maps_from_definition


def attach_filter_context_fields(
    form: forms.Form,
    source: Any,
    *,
    for_import: bool = False,
) -> None:
    """
    Add ``fr_get_*`` / ``fr_kw_*`` CharFields to ``form`` from a definition-like ``source``
    (``ExportDefinition`` or ``ImportDefinition`` with ``filter_request`` / ``filter_mandatory``).
    """
    req_label = _("Required for this import.") if for_import else _("Required for this export.")
    url_req = _("Required for this import.") if for_import else _("Required for this export.")
    fr, _mandatory, get_m, kw_map = parse_filter_maps_from_definition(source)
    all_get_params = set(fr) | set(get_m)
    for param_name in sorted(all_get_params):
        orm_field = get_m.get(param_name, fr.get(param_name))
        if orm_field is None:
            continue
        in_man = param_name in get_m
        fname = form_field_name_for_query_param(param_name)
        field_help = (
            req_label
            if in_man
            else _("Optional — leave empty to skip this filter.")
        )
        form.fields[fname] = forms.CharField(
            label=_("GET “%(param)s” → %(field)s")
            % {"param": param_name, "field": orm_field},
            required=False,
            help_text=field_help,
        )
    for kw_name, orm_field in sorted(kw_map.items()):
        form.fields[form_field_name_for_url_kwarg(kw_name)] = forms.CharField(
            label=_("URL “%(kw)s” → %(field)s")
            % {"kw": kw_name, "field": orm_field},
            required=False,
            help_text=url_req,
        )


def clean_filter_context_data(
    form: forms.Form,
    cleaned: dict[str, Any],
    source: Any,
) -> None:
    """Validate strip filter CharFields; mandatory GET and URL kwargs must be non-empty."""
    fr, _mandatory, get_m, kw_map = parse_filter_maps_from_definition(source)
    all_get_params = set(fr) | set(get_m)

    def _clean_fr_field(fname: str, *, required: bool) -> None:
        merged = (cleaned.get(fname) or "").strip()
        if required:
            if not merged:
                form.add_error(fname, _("This field is required."))
            else:
                cleaned[fname] = merged
        else:
            cleaned[fname] = merged

    for param_name in sorted(all_get_params):
        in_man = param_name in get_m
        fname = form_field_name_for_query_param(param_name)
        if fname not in form.fields:
            continue
        _clean_fr_field(fname, required=in_man)

    for kw_name in sorted(kw_map):
        fname = form_field_name_for_url_kwarg(kw_name)
        if fname not in form.fields:
            continue
        _clean_fr_field(fname, required=True)


def reorder_filter_fields_first(
    form: forms.Form,
    leading_field_names: tuple[str, ...],
    trailing_field_names: tuple[str, ...] = (),
) -> None:
    """Place ``leading`` then ``fr_*`` then ``trailing`` in field order."""
    reordered: dict[str, Any] = {}
    for name in leading_field_names:
        if name in form.fields:
            reordered[name] = form.fields[name]
    for name in sorted(form.fields):
        if name.startswith("fr_"):
            reordered[name] = form.fields[name]
    for name in trailing_field_names:
        if name in form.fields:
            reordered[name] = form.fields[name]
    form.fields = reordered
