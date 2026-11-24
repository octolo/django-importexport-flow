# django-importexport-flow — documentation

Declarative exports and imports. A **`Definition`** stores the direction, target model, filters, and ordering. Each **`CategoryConfig`** stores the columns shared by one category, and each **`FormatConfig`** activates CSV, Excel, JSON, or PDF. **`ExportRequest`** and **`ImportRequest`** keep the audit rows.

## Contents

| Document | Description |
|----------|-------------|
| [Installation](installation.md) | Package, `INSTALLED_APPS`, migrations, optional `[pdf]` extra |
| [Purpose](purpose.md) | What the app is for |
| [Structure](structure.md) | Source layout and import submodules (`paths`, `io`, …) |
| [Filters and export](filters-and-export.md) | `filter_request` / `filter_mandatory`, admin form fields, engine |
| [Import data (wizard)](import-data.md) | **`ImportDefinition`** wizard, **`ImportRequest`** audit, relaunch |
| [Development](development.md) | Local setup, tests, tooling |
| [Current-state audit](current-state-audit.md) | Measured architecture, quality, security, and remaining debt |
| [AI](AI.md) | Short notes for assistants working in this repo |

## API summary

- **`CoreEngine`** (`engine/core/engine.py`): manager → queryset, merges `filter_config` with `request.GET` and URL kwargs, applies `order_by`.
- **`TableEngine`** / **`PdfEngine`** (`engine/core/table.py`, `engine/core/pdf.py`; short aliases in `engine/csv.py`, …): headers, rows, CSV / Excel / JSON / PDF. Public names **`ExportTableEngine`**, **`ExportPdfEngine`** (see `engine/__init__.py`).
- **`process_export`** (`utils.process`): table export entry point; delegates to **`run_table_export`** (`engine/core/export.py`).
- **Validation** (`engine/core/validation.py`): export filter fields, column specs, manager path, **`coerce_request_filter_value`** for GET filters.
- **Import** (`engine/core/import_.py`): re-exports **`validate_import_preview`**, **`run_import_request`**, path helpers, etc. Implementation split into **`paths`**, **`io`**, **`preview`**, **`items`**, **`run`** (see [structure.md](structure.md)).

## Quick start

```bash
pip install django-importexport-flow
# PDF exports also need: pip install 'django-importexport-flow[pdf]'  # or weasyprint
```

```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.contenttypes",
    "django_boosted",
    "django_importexport_flow",
]
```

```bash
python manage.py migrate django_importexport_flow
```

## Configuration JSON with column translations

Use **Export configuration and translations (JSON)** on an import or export definition
in the admin, or pass `include_column_translations=True` to
`serialize_import_definition()` or `serialize_export_configuration()`. Ordinary JSON
downloads are unchanged. The optional `column_translations` array contains `path`,
`language`, and `label` for the target model's catalog. The JSON identifies that model
by its Django app and model names rather than by a database-specific content type ID.

Import the file through the normal configuration import. Admin users also need the
**Can add column translation** permission. Missing translations are created, identical
ones are reused, and a conflicting label aborts the whole import. Translations are
shared by all definitions targeting that model.

For examples, see the sample [Books export](../tests/sample/importexport_fixtures/report_export_books.json)
and [Books import](../tests/sample/importexport_fixtures/report_import_books_match.json). Both
bundle the Book translations from the [sample catalog](../tests/sample/fixtures/sample_catalog.json).

The [combined Books import](../tests/sample/importexport_fixtures/report_import_books_combined.json)
first runs the Books import above, then the [price step](../tests/sample/importexport_fixtures/report_import_books_price.json).
Import both child definitions before the combined definition. Use the sample
[CSV](../tests/sample/importexport_fixtures/tabular/import_books_match.csv): the second
step sets the price to one cent per page. Its sample processor must be allowed by
`ALLOWED_HOOK_MODULE_PREFIXES` if the allowlist is configured. The preview validates
steps independently and does not simulate writes from earlier steps.

## License

MIT (repository root).
