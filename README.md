# django-importexport-flow

Declarative **export** and **import** for Django: **`ExportDefinition`** (`ContentType`, manager, filters, **`ExportConfigTable`** columns, optional **`ExportConfigPdf`**); **`ImportDefinition`** with a tabular import wizard and **`ImportRequest`** audit. Admin **CSV / XLSX / JSON** table export.

**Documentation:** [docs/README.md](docs/README.md)

## Install

```bash
pip install django-importexport-flow
```

```python
INSTALLED_APPS = [
    # ...
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
| AI / tooling notes | [docs/AI.md](docs/AI.md) |

## License

MIT
