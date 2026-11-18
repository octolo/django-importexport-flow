# Installation

## Requirements

- Python 3.11+
- Django 5.x
- **django-boosted** — used by the bundled admin (`AdminBoostModel`, `admin_boost_view`, `NestedStackedInline`)

## Install the package

```bash
pip install django-importexport-flow
```

Editable install for development:

```bash
pip install -e ".[dev]"
```

PDF export requires **WeasyPrint**. The package exposes an optional extra:

```bash
pip install "django-importexport-flow[pdf]"
```

(`[dev]` already includes `weasyprint` for running PDF-related tests locally.)

## Django settings

Register apps **after** `django.contrib.contenttypes`:

```python
INSTALLED_APPS = [
    # ...
    "django.contrib.admin",
    "django.contrib.contenttypes",
    "django_boosted",
    "django_importexport_flow",
]
```

Optional keys live in ``settings.DJANGO_IMPORTEXPORT_FLOW``:

| Key | Default | Meaning |
|-----|---------|---------|
| ``ESCAPE_SPREADSHEET_FORMULAS`` | ``True`` | Prefix dangerous CSV/Excel text with ``'``. |
| ``ALLOWED_HOOK_MODULE_PREFIXES`` | ``None`` | ``None`` allows any importable hook. A list allows those module prefixes. ``[]`` allows native hooks only. |
| ``MAX_XLSX_ARCHIVE_MEMBERS`` | ``1000`` | Maximum entries in an ``.xlsx`` ZIP. |
| ``MAX_XLSX_UNCOMPRESSED_BYTES`` | 50 MiB | Maximum declared uncompressed size. |
| ``MAX_XLSX_COMPRESSION_RATIO`` | ``100`` | Maximum ``file_size / compress_size`` for one entry. |
| ``EXPORT_OUTPUT_STORAGE`` / ``IMPORT_FILE_STORAGE`` | ``None`` | Resolved in this order: storage instance or callable, then a ``STORAGES`` alias, then a dotted storage class, otherwise a configuration error. ``None`` uses the default storage. Keep the same storage for the life of stored files. |
| ``EXPORT_OUTPUT_UPLOAD_TO`` / ``IMPORT_FILE_UPLOAD_TO`` | ``None`` | A callable, a dotted callable, or a relative directory/strftime template such as ``uploads`` or ``exports/%Y/%m/``. A dotted name that cannot be imported is a configuration error. |

For a hardened deployment, set `ALLOWED_HOOK_MODULE_PREFIXES` to an explicit
prefix list or `[]`, keep `ESCAPE_SPREADSHEET_FORMULAS` enabled, and grant
`change_formatconfig` only to trusted users. Store sensitive exports in a
private storage and keep that storage for the life of the files. Schedule
`purge_export_requests` to delete completed export rows and their files.

## Migrations

```bash
python manage.py migrate django_importexport_flow
```

## Admin (optional)

The package registers proxy admins: `ExportDefinitionAdmin`, `ImportDefinitionAdmin`, category and format proxy admins, plus `ExportRequestAdmin` and `ImportRequestAdmin`. `CategoryConfigAdmin` and `FormatConfigAdmin` are the base classes used by those proxy admins.

## Production hardening

These choices belong to the Django project that deploys the library. The package defaults stay compatible with existing installations.

### Private export storage

`EXPORT_OUTPUT_STORAGE` accepts a storage instance or callable, a `STORAGES` alias, or a dotted storage class. For sensitive exports, point it at a backend that refuses anonymous access:

```python
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "private_exports": {
        "BACKEND": "myproject.storage.PrivateExportStorage",
    },
}

DJANGO_IMPORTEXPORT_FLOW = {
    "EXPORT_OUTPUT_STORAGE": "private_exports",
}
```

Keep that same storage available for as long as the files must be read or purged. Changing the alias later does not move files already written. The library cannot make a caller-supplied backend private by itself.

### Scheduled purge

Preview the deletion, then run it with the retention required by the project:

```bash
python manage.py purge_export_requests --days 30 --dry-run
python manage.py purge_export_requests --days 30
```

Schedule the command with the deployment platform, cron, or the project's task scheduler. Watch its exit code and reported storage errors. Back up files before purging only when the project's retention policy requires it.

### Hook allowlist

Keep `ESCAPE_SPREADSHEET_FORMULAS` enabled. Native hooks remain available with every allowlist. An empty list rejects every custom hook:

```python
DJANGO_IMPORTEXPORT_FLOW = {
    "ALLOWED_HOOK_MODULE_PREFIXES": [],
}
```

A prefix list also permits hooks below those module prefixes:

```python
DJANGO_IMPORTEXPORT_FLOW = {
    "ALLOWED_HOOK_MODULE_PREFIXES": [
        "myproject.importexport_hooks",
    ],
}
```

`None` permits any importable hook, so use it only in a trusted environment. Grant configuration and `change_formatconfig` permissions only to trusted users.

### Task backend and broker

`IMPORT_TASK_BACKEND` selects `sync`, `thread`, `celery`, or `rq` for both imports and exports. `sync` needs no broker. `thread` runs inside the web process and does not provide a durable queue. Celery and django-rq need their workers and broker to stay available.

When either external backend is used, monitor active workers, queue depth and age, failures and retries, task duration, broker capacity, and requests left in `pending` or `processing`.

Next: [Purpose](purpose.md) or [Structure](structure.md).
