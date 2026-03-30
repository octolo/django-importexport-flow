"""Table export runtime: filter payload, synthetic request, :func:`run_table_export`."""

from __future__ import annotations

import json
from typing import Any

from django.http import HttpRequest, QueryDict

from ...apps import DjangoImportExportFlowConfig
from ...models import ExportConfigTable, ExportDefinition
from .table import TableEngine
from .validation import parse_filter_maps_from_definition


def snapshot_export_filter_payload(cleaned_data: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe subset for audit storage: ``export_format`` and ``fr_*`` keys only."""
    subset = {k: v for k, v in cleaned_data.items() if k == "export_format" or k.startswith("fr_")}
    return json.loads(json.dumps(subset, default=str))


class DefinitionFilterProxy:
    """Same as a stored definition but with merged ``filter_config`` for one export."""

    __slots__ = ("_definition", "filter_config")

    def __init__(self, definition: Any, filter_config: dict[str, Any]) -> None:
        object.__setattr__(self, "_definition", definition)
        object.__setattr__(self, "filter_config", filter_config)

    def __getattr__(self, name: str) -> Any:
        if name == "filter_config":
            return object.__getattribute__(self, "filter_config")
        return getattr(object.__getattribute__(self, "_definition"), name)


def build_request_with_get(get_params: dict[str, str]) -> HttpRequest:
    request = HttpRequest()
    request.method = "GET"
    q = QueryDict(mutable=True)
    for k, v in get_params.items():
        q[k] = v
    request.GET = q
    return request


def attach_export_url_kwargs(request: HttpRequest, url_kwargs: dict[str, Any]) -> None:
    """Inject path kwargs for :attr:`filter_mandatory` when the request has no ``resolver_match``."""
    request._django_importexport_flow_url_kwargs = url_kwargs


def form_field_name_for_query_param(param_name: str, *args: Any, **kwargs: Any) -> str:
    """
    Key for a GET query param in the export filter payload
    (``filter_request`` and/or ``filter_mandatory.get``). Uses the ``fr_get_`` prefix so
    names never collide with :func:`form_field_name_for_url_kwarg` (``fr_kw_``).
    Extra positional/keyword args are ignored (backward compatibility).
    """
    return f"fr_get_{param_name}"


def form_field_name_for_url_kwarg(kw_name: str) -> str:
    """Key in the filter payload for ``filter_mandatory.kwargs`` (path parameters)."""
    return f"fr_kw_{kw_name}"


def run_table_export(
    definition: Any,
    filter_payload: dict[str, Any],
) -> tuple[bytes, str, str]:
    """
    Build queryset from ``filter_request`` / ``filter_mandatory`` (GET + URL kwargs).
    ``filter_config`` is taken from the report only (no export-time override).

    ``filter_payload`` uses the same keys as a validated export form (``export_format``,
    ``fr_get_*``, ``fr_kw_*``) or any equivalent dict (e.g. from a management command).

    Returns ``(body_bytes, content_type, file_extension)`` — e.g. ``(".csv")``.
    The download filename (with timestamp) is set in the admin view.
    """
    fr, _mandatory, get_m, kw_map = parse_filter_maps_from_definition(definition)
    all_get_params = set(fr) | set(get_m)
    get_params: dict[str, str] = {}
    for param_name in all_get_params:
        form_key = form_field_name_for_query_param(param_name)
        if form_key not in filter_payload:
            raise ValueError(f"Missing filter payload key for request param {param_name!r}")
        get_params[param_name] = str(filter_payload[form_key])

    url_kw: dict[str, str] = {}
    for kw_name in kw_map:
        fkey = form_field_name_for_url_kwarg(kw_name)
        if fkey not in filter_payload:
            raise ValueError(f"Missing filter payload key for URL kwarg {kw_name!r}")
        url_kw[kw_name] = str(filter_payload[fkey])

    merged = dict(getattr(definition, "filter_config", None) or {})
    proxy = DefinitionFilterProxy(definition, merged)
    request = build_request_with_get(get_params)
    attach_export_url_kwargs(request, url_kw)
    engine = TableEngine(proxy, request=request)

    fmt = filter_payload["export_format"]
    dispatch = DjangoImportExportFlowConfig.export_format_dispatch
    spec = dispatch.get(fmt)
    if spec is None:
        raise ValueError(f"Unknown export format {fmt!r}")
    method_name, content_type, ext = spec
    body: bytes = getattr(engine, method_name)()
    return body, content_type, ext


def build_http_request_from_filter_payload(
    definition: Any,
    filter_payload: dict[str, Any],
) -> HttpRequest:
    """Build a GET request + URL kwargs from the same keys as :func:`run_table_export`."""
    fr, _mandatory, get_m, kw_map = parse_filter_maps_from_definition(definition)
    all_get_params = set(fr) | set(get_m)
    get_params: dict[str, str] = {}
    for param_name in all_get_params:
        form_key = form_field_name_for_query_param(param_name)
        get_params[param_name] = str(filter_payload.get(form_key, ""))
    url_kw: dict[str, str] = {}
    for kw_name in kw_map:
        fkey = form_field_name_for_url_kwarg(kw_name)
        url_kw[kw_name] = str(filter_payload.get(fkey, ""))
    request = build_request_with_get(get_params)
    attach_export_url_kwargs(request, url_kw)
    return request


def collect_dynamic_filter_kwargs(
    definition: Any, filter_payload: dict[str, Any]
) -> dict[str, Any]:
    """
    ORM filter kwargs from ``filter_request`` / ``filter_mandatory`` (same rules as
    :class:`~django_importexport_flow.engine.core.CoreEngine` ``_filter_request``).
    """
    from .engine import CoreEngine

    merged = dict(getattr(definition, "filter_config", None) or {})
    proxy = DefinitionFilterProxy(definition, merged)
    request = build_http_request_from_filter_payload(definition, filter_payload)
    return CoreEngine(proxy, request=request)._filter_request()


def definition_has_table_config(definition: Any) -> bool:
    """True only when ``definition`` is an :class:`~django_importexport_flow.models.ExportDefinition` with a non-empty table column list."""
    if not isinstance(definition, ExportDefinition):
        return False
    try:
        ct = definition.config_table
    except ExportConfigTable.DoesNotExist:
        return False
    cols = ct.columns or []
    return len(cols) > 0
