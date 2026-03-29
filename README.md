# django-importexport-flow

Declarative reporting for Django: **target model** (`ContentType`), **manager** path, **`filter_config` / `filter_request` / `filter_mandatory`**, **`order_by`**, and **columns** on **`ExportConfigTable`**. Optional **PDF** (`ExportConfigPdf`) and **CSV / XLSX / JSON** export from the admin.

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
| Development | [docs/development.md](docs/development.md) |
| AI / tooling notes | [docs/AI.md](docs/AI.md) |

## License

MIT
