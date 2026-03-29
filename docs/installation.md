# Installation

## Requirements

- Django 4.2+ (tested with Django 6.x)
- **django-boosted** — used by the bundled admin (`AdminBoostModel`, `admin_boost_view`)

## Install the package

```bash
pip install django-importexport-flow
```

Editable install for development:

```bash
pip install -e ".[dev]"
```

## Django settings

Register apps **after** `django.contrib.contenttypes`:

```python
INSTALLED_APPS = [
    # ...
    "django.contrib.contenttypes",
    "django_boosted",
    "django_importexport_flow",
]
```

## Migrations

```bash
python manage.py migrate django_importexport_flow
```

## Admin (optional)

The package ships `django_importexport_flow.admin` with `ExportDefinitionAdmin` and inlines. Subclass or replace with your own `ModelAdmin` if you do not use django-boosted patterns.

Next: [Purpose](purpose.md) or [Structure](structure.md).
