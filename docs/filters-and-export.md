# Filters and table export

## Stored filters on `Definition`

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

The form can also send two request-scoped values, stored on **`ExportRequest`** and applied only to that export:

| Field | Empty value | Priority |
|--------|-------------|----------|
| **`template_override`** | Use **`FormatConfig.template`** | Shown only when PDF is enabled. A non-empty value replaces the PDF template for that request. It is rejected for CSV, Excel, and JSON. |
| **`configuration_overrides`** | `{}` | `format` replaces allowed native options; `hook` is passed to the hooks through `payload["configuration_overrides"]`. |

```json
{"format": {"delimiter": ";"}, "hook": {"company_id": 42, "locale": "fr"}}
```

Allowed `format` keys: CSV `delimiter`; Excel `sheet`, `sheet_name`, `split_by`; JSON `orient`, `indent`, `force_ascii`. PDF has no native key here because its template is the dedicated field. Unknown keys and options for another format are rejected. These values never change the stored category or format configuration, the columns, the target, or the hook paths.

A template supplied on the request is trusted content with the same rendering capabilities as the template stored on the format. In the admin, the field is shown only to users who can change a format configuration (`django_importexport_flow.change_formatconfig`). A posted value is ignored for everyone else. `process_export`, the management command, and async workers still accept `template_override` directly, because those callers are already trusted code.

CSV and Excel exports prefix text that a spreadsheet could execute. A value whose first non-space character is `=`, `+`, `-`, or `@` is written with a leading `'`. Numbers, dates, booleans, empty values, and text that already starts with `'` are left unchanged. JSON exports are not rewritten. Set `ESCAPE_SPREADSHEET_FORMULAS` to `False` to keep the historical text.

## Shared helpers (for integrators)

- **`parse_filter_maps` / `parse_filter_maps_from_definition`** (`engine/core/validation.py`) — normalized dicts for forms and `run_table_export`.
- **`validate_export_filter_fields`** — same filter + `order_by` checks as model `clean()` for definitions/imports.
- **`process_export`** (`utils.process`) — public entry; builds the filter payload and runs the format hook chain.
- **`FormatConfig.hook`** — empty uses the native hook for that format; a non-empty list replaces it and runs in order. Stored options stay in **`FormatConfig.configuration`**. A request may override the allowed native options and pass extra `hook` data without changing that stored configuration.
- **`ExportRequest.template_override`** — optional PDF template. Empty falls back to **`FormatConfig.template`**. Hooks still use `(dataset, category_config, format_config, payload)`; `payload["template_override"]` and `payload["configuration_overrides"]` expose the request values.
- **`run_table_export`** — builds a synthetic `HttpRequest` from the filter payload and runs the table engine. The native CSV, Excel, and JSON hooks call it.

Back to [documentation index](README.md).
