from typing import Any

from django.http import HttpRequest

from .validation import (
    annotation_aliases_for_definition,
    coerce_request_filter_value,
    resolve_manager_to_queryset,
    split_filter_mandatory,
    validate_export_filter_fields,
    validate_filter_kwargs_for_model,
)


def _normalize_order_by(raw: Any) -> list[str]:
    if not raw:
        return []
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if isinstance(x, str) and str(x).strip()]


class CoreEngine:
    def __init__(self, definition, request=None, config=None):
        self.definition = definition
        self.request = request or HttpRequest()
        self.config = config
        self._cached_queryset: Any = None

    def get_model(self):
        return self.definition.target.model_class()

    @staticmethod
    def _mandatory_dict(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return {}
        return raw

    def _url_kwargs_from_request(self) -> dict[str, Any]:
        request = self.request
        out: dict[str, Any] = {}
        rm = getattr(request, "resolver_match", None)
        if rm is not None:
            out.update(rm.kwargs or {})
        extra = getattr(request, "_django_importexport_flow_url_kwargs", None)
        if isinstance(extra, dict):
            out.update(extra)
        return out

    def get_queryset(self):
        if self._cached_queryset is not None:
            return self._cached_queryset
        model_cls = self.get_model()
        if model_cls is None:
            raise ValueError("Export has no target model (content type unset).")
        # Same rules as ExportDefinition / ImportDefinition clean(): reject bad ORM keys,
        # order_by, and manager path before building SQL (also safe if engine is used
        # without going through model.save()).
        ann_aliases = annotation_aliases_for_definition(self.definition)
        validate_export_filter_fields(
            model_cls,
            getattr(self.definition, "filter_config", None) or {},
            getattr(self.definition, "filter_request", None) or {},
            getattr(self.definition, "filter_mandatory", None) or {},
            getattr(self.definition, "order_by", None) or [],
            annotation_aliases=ann_aliases,
        )
        manager_path = (getattr(self.definition, "manager", None) or "").strip() or "objects.all"
        qs: Any = resolve_manager_to_queryset(model_cls, manager_path)
        filter_config = getattr(self.definition, "filter_config", None) or {}
        req_filters = self._filter_request()
        validate_filter_kwargs_for_model(
            model_cls, req_filters, annotation_aliases=ann_aliases
        )
        self._cached_queryset = qs.filter(**filter_config, **req_filters)
        order_by = _normalize_order_by(getattr(self.definition, "order_by", None))
        if order_by:
            self._cached_queryset = self._cached_queryset.order_by(*order_by)
        return self._cached_queryset

    def _filter_request(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        model_cls = self.get_model()
        if model_cls is None:
            return out
        mandatory = self._mandatory_dict(getattr(self.definition, "filter_mandatory", None))
        fr = getattr(self.definition, "filter_request", None) or {}
        if not isinstance(fr, dict):
            fr = {}
        get_mandatory, kw_map = split_filter_mandatory(mandatory)
        # Mandatory GET (filter_mandatory.get or shorthand): required.
        for param_name, orm_key in get_mandatory.items():
            val = self.request.GET.get(param_name)
            if val in (None, ""):
                raise ValueError(f"Mandatory GET parameter {param_name!r} is required")
            out[orm_key] = coerce_request_filter_value(model_cls, orm_key, val)
        # Optional GET (filter_request only): omit when absent or empty.
        for param_name, orm_key in fr.items():
            if param_name in get_mandatory:
                continue
            val = self.request.GET.get(param_name)
            if val in (None, ""):
                continue
            out[orm_key] = coerce_request_filter_value(model_cls, orm_key, val)
        url_kwargs = self._url_kwargs_from_request()
        for kw_name, orm_key in kw_map.items():
            if kw_name not in url_kwargs or url_kwargs[kw_name] in (None, ""):
                raise ValueError(f"URL kwarg {kw_name!r} is required")
            raw = str(url_kwargs[kw_name])
            out[orm_key] = coerce_request_filter_value(model_cls, orm_key, raw)
        return out
