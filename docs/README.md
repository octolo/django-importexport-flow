# django-importexport-flow — documentation

Declarative exports and imports: **target model** (`ContentType`), **manager**, **filters** (`filter_config`, optional `filter_request`, optional `filter_mandatory`), **`order_by`**, and **columns** on **`ExportConfigTable`**. Optional **PDF** via **`ExportConfigPdf`**.

## Contents

| Document | Description |
|----------|-------------|
| [Installation](installation.md) | Package, `INSTALLED_APPS`, migrations, optional `[pdf]` extra |
| [Purpose](purpose.md) | What the app is for |
| [Structure](structure.md) | Source layout and import submodules (`paths`, `io`, …) |
| [Filters and export](filters-and-export.md) | `filter_request` / `filter_mandatory`, admin form fields, engine |
| [Import data (wizard)](import-data.md) | **`ImportDefinition`** wizard, **`ImportRequest`** audit, relaunch |
| [Development](development.md) | Local setup, tests, tooling |
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
    "django.contrib.contenttypes",
    "django_boosted",
    "django_importexport_flow",
]
```

```bash
python manage.py migrate django_importexport_flow
```

## License

MIT (repository root).
