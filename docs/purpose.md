## Project purpose

**django-importexport-flow** is a Django app for **declarative tabular and PDF exports** and **scoped tabular imports**: you point an **`ExportDefinition`** at a model (via **`ContentType`**), choose a **manager** path, optional **filters** (static, request GET, mandatory GET/URL), **ordering**, and **columns** on **`ExportConfigTable`**. Optional **`ExportConfigPdf`** adds HTML→PDF rendering.

**Imports** use **`ImportDefinition`** (same filter vocabulary, no separate table config): default **field paths** on the target model, optional **`columns_exclude`**, wizard → **`ImportRequest`** audit rows.

Typical uses:

- Admin or staff **CSV / Excel / JSON** **exports** driven by configuration in the database.
- **JSON import/export** of **export** definitions for staging or backups.
- **Scoped tabular imports** (CSV/Excel) via **`ImportDefinition`** + **`ImportRequest`**.

See [Structure](structure.md), [Filters and export](filters-and-export.md), and [Import data](import-data.md).

## Legacy naming (django-reporting / report-import)

The Python API and model class names use **ImportDefinition**, **ImportRequest**,
**ExportDefinition**, etc. Several physical names stayed from older package splits so
existing databases and JSON fixtures keep working **without table renames**:

| Area | Legacy / stable name | Notes |
|------|----------------------|--------|
| **DB** (`Meta.db_table`) | `django_reporting_reportimport`, `django_reporting_reportimportask` | Import-side tables. |
| | `django_reportimport_reportdefinition`, `django_reportimport_reportconfig*`, `django_reportimport_reportrequest` | Export / shared config tables. |
| **Upload storage** | `report_import_asks/%Y/%m/` | `FileField.upload_to` on **ImportRequest**. |
| **Admin templates** | `report_import_import_data.html`, `report_import_import_confirm.html` | Under `templates/django_importexport_flow/admin/`. |
| **Serialization** | JSON may still contain `django_reporting.reportimport`; loaders rewrite to **ImportDefinition** (see `utils/serialization.py`). |
| **Public aliases** | `serialize_report_import` / `import_report_import`, `sample_headers_for_report_import`, `create_import_ask`, `run_tabular_import_for_*`, **ReportImport\*** forms | Same objects as the `*_import_definition` / **TabularImport\*** names; kept for backward compatibility. Defined in `utils/serialization.py`, `engine/core/import_.py`, `.forms`, and lazy exports on the package root. |

Prefer the **ImportDefinition** / **import_** names in new code. Do not rename `db_table`
values in models without a deliberate migration strategy.

Tests for import paths and **ImportRequest** are in **`tests/test_import_definition.py`** and
**`tests/test_import_request.py`** (previously `test_report_import*.py`).
