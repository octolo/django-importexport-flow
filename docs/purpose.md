## Project purpose

**django-importexport** is a Django app for **declarative tabular and PDF reports**: you point a **`ExportDefinition`** at a model (via **`ContentType`**), choose a **manager** path, optional **filters** (static, request GET, mandatory GET/URL), **ordering**, and **columns** on **`ExportConfigTable`**. Optional **`ExportConfigPdf`** adds HTML→PDF rendering.

Typical uses:

- Admin or staff **CSV / Excel / JSON** exports driven by configuration stored in the database.
- **JSON import/export** of report definitions for staging or backups.
- **Scoped** imports via **`ReportImport`** (columns + filters on a single row, no separate config table).

See [Structure](structure.md) and [Filters and export](filters-and-export.md).
