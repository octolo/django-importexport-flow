# django-importexport-flow — documentation

Declarative reports: **target model**, **manager**, **filters** (`filter_config`, optional `filter_request`, optional `filter_mandatory`), **`order_by`**, and **columns** on `ExportConfigTable`. Optional **PDF** via `ExportConfigPdf`.

## Contents

| Document | Description |
|----------|-------------|
| [Installation](installation.md) | Package, `INSTALLED_APPS`, migrations |
| [Purpose](purpose.md) | What the app is for |
| [Structure](structure.md) | Source layout |
| [Filters and export](filters-and-export.md) | `filter_request` / `filter_mandatory`, admin form fields, engine |
| [Import data (wizard)](import-data.md) | ReportImport tabular import, `ReportImportAsk` audit, relaunch |
| [Development](development.md) | Local setup, tests, tooling |
| [AI](AI.md) | Short notes for assistants working in this repo |

## API summary

- **`CoreEngine`** (`engine/core.py`): resolves manager → queryset, merges `filter_config` with dynamic filters from `request.GET` and URL kwargs, applies `order_by`.
- **`TableEngine`** / **`PdfEngine`** (`engine/table.py`, `engine/pdf.py`): headers, rows, CSV / Excel / JSON / PDF. Public aliases **`ExportTableEngine`**, **`ExportPdfEngine`**.
- **`run_table_export`** (`export.py`): builds a synthetic request from admin form `cleaned_data` and runs the table engine.
- **Validation** (`validation.py`): `validate_export_filter_fields`, `parse_filter_maps_from_definition`, column specs, manager path.

## Quick start

```bash
pip install django-importexport-flow
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
