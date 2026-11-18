## Project purpose

**django-importexport-flow** is a Django app for **declarative tabular and PDF exports** and **scoped tabular imports**. A **`Definition`** points at a model (via **`ContentType`**) and stores the shared filters, ordering, and direction. **`CategoryConfig`** holds the columns and options shared by one category. **`FormatConfig`** activates one format (CSV, Excel, JSON, or PDF) and stores its hook list, template, and options. An empty hook list uses the format's native hook; a non-empty list replaces it. Task backends only choose synchronous or asynchronous execution.

**Imports** use a definition with `direction="import"`: default **field paths** on the target model, optional **`columns_exclude`**, wizard → **`ImportRequest`** audit rows. **Exports** use `direction="export"`, a **manager** path, and **`ExportRequest`** audit rows.

Typical uses:

- Admin or staff **CSV / Excel / JSON** **exports** driven by configuration in the database.
- **JSON import/export** of **export** definitions for staging or backups.
- **Scoped tabular imports** (CSV/Excel) via **`ImportDefinition`** + **`ImportRequest`**.

See [Structure](structure.md), [Filters and export](filters-and-export.md), and [Import data](import-data.md).

## Legacy naming (django-reporting / report-import)

Request models stay **`ImportRequest`** and **`ExportRequest`**. **`ExportDefinition`** and
**`ImportDefinition`** are directional proxies of **`Definition`**; category and format proxies
likewise narrow the concrete configuration models. Serialization version 2 stores `definition`,
`categoryconfig`, and `formatconfig`.

| Area | Legacy / stable name | Notes |
|------|----------------------|--------|
| **Upload storage** | `report_import_asks/%Y/%m/`, `export_outputs/%Y/%m/` | Default paths. Override the storage and path callable with `IMPORT_FILE_STORAGE`, `EXPORT_OUTPUT_STORAGE`, `IMPORT_FILE_UPLOAD_TO`, and `EXPORT_OUTPUT_UPLOAD_TO`. |
| **Admin templates** | `report_import_import_data.html`, `report_import_import_confirm.html` | Under `templates/django_importexport_flow/admin/`. |
| **Serialization** | `definition`, `categoryconfig`, `formatconfig` | Version 2. Version 1 and unpublished intermediate model names are rejected. |
| **Public aliases** | `serialize_report_import` / `import_report_import`, `sample_headers_for_report_import`, `create_import_ask`, `run_tabular_import_for_*`, **ReportImport\*** forms | Same objects as the `*_import_definition` / **TabularImport\*** names; kept for backward compatibility. Defined in `utils/serialization.py`, `engine/core/import_.py`, `.forms`, and lazy exports on the package root. |

Prefer **`Definition`**, **`CategoryConfig`**, and **`FormatConfig`** in new code. The proxy
classes are the supported admin and queryset entry points for one direction, category, or format.

Tests for import paths and **ImportRequest** are in **`tests/test_import_definition.py`** and
**`tests/test_import_request.py`** (previously `test_report_import*.py`).
