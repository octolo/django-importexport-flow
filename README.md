# django-importexport-flow

Declarative **export** and **import** for Django. A **`Definition`** (`direction`, `ContentType`, filters) owns **`CategoryConfig`** rows (spreadsheet, document, structured data) and each category owns the **`FormatConfig`** rows that activate CSV, Excel, JSON, or PDF. **`ExportRequest`** and **`ImportRequest`** keep their own audit cycles. CSV and Excel text that a spreadsheet could execute as a formula is prefixed with `'` unless `ESCAPE_SPREADSHEET_FORMULAS` is turned off.

**Documentation:** [docs/README.md](docs/README.md)

## Install

```bash
pip install django-importexport-flow
```

```python
INSTALLED_APPS = [
    # ...
    "django.contrib.admin",
    "django.contrib.contenttypes",
    "django_boosted",
    "django_importexport_flow",
]
```

```bash
python manage.py migrate django_importexport_flow
```

## Documentation index

| Topic | Doc |
|-------|-----|
| Install & settings | [docs/installation.md](docs/installation.md) |
| Purpose | [docs/purpose.md](docs/purpose.md) |
| Repository layout | [docs/structure.md](docs/structure.md) |
| Filters & admin export | [docs/filters-and-export.md](docs/filters-and-export.md) |
| Import wizard | [docs/import-data.md](docs/import-data.md) |
| Development | [docs/development.md](docs/development.md) |
| Current-state audit | [docs/current-state-audit.md](docs/current-state-audit.md) |
| AI / tooling notes | [docs/AI.md](docs/AI.md) |

## License

MIT
