# Filters and table export

## Stored filters on `ExportDefinition` and `ImportDefinition`

| Field | Role |
|--------|------|
| **`filter_config`** | Static `QuerySet.filter(**kwargs)` values (JSON object). |
| **`filter_request`** | Optional GET query parameters: JSON map `{query_param_name: orm_lookup}`. If a value is absent or empty at runtime, that filter is skipped. |
| **`filter_mandatory`** | Required dynamic filters: JSON object with optional keys **`get`** and **`kwargs`**. |

### `filter_mandatory`

**Canonical shape:**

- **`get`**: `{query_param_name: orm_lookup}` — values must be present in `request.GET` (non-empty) when the report/import context runs.
- **`kwargs`**: `{url_kwarg_name: orm_lookup}` — values must come from URL path kwargs (`resolver_match.kwargs` or `attach_export_url_kwargs`).

**Shorthand:** if the JSON object has **neither** a top-level `"get"` nor `"kwargs"` key, the **entire object** is treated as the GET map. For example `{"author_id": "author__id"}` is equivalent to `{"get": {"author_id": "author__id"}}`.

If the same query param name appears in both **`filter_request`** and **`filter_mandatory.get`** (including shorthand), the ORM lookup must be **identical** (validated on save).

Invalid GET values for typed fields raise **`ValidationError`** during coercion (no silent string pass-through to the ORM).

## Runtime behaviour (`CoreEngine`)

Mandatory GET filters are applied first, then optional `filter_request` keys (skipped when missing/empty), then mandatory URL kwargs.

## Admin “Process export” form

The export form builds one field per GET param and per URL kwarg:

| Source | Form field prefix | Required |
|--------|-------------------|----------|
| `filter_request` and/or `filter_mandatory.get` | `fr_get_<query_param>` | Yes only if the param is listed under `filter_mandatory.get` |
| `filter_mandatory.kwargs` | `fr_kw_<url_kwarg_name>` | Always |

`filter_config` is not editable on this form; it always comes from the stored definition.

## Shared helpers (for integrators)

- **`parse_filter_maps` / `parse_filter_maps_from_definition`** (`engine/core/validation.py`) — normalized dicts for forms and `run_table_export`.
- **`validate_export_filter_fields`** — same filter + `order_by` checks as model `clean()` for definitions/imports.
- **`process_export`** (`utils.process`) — public entry; builds filter payload and runs **`run_table_export`** (`engine/core/export.py`).
- **`run_table_export`** — builds a synthetic `HttpRequest` from the filter payload and runs the table engine.

Back to [documentation index](README.md).
