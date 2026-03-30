# Import data (admin wizard)

On an **`ImportDefinition`** change page, **Import data** opens a wizard:

1. **Upload** — choose a **CSV** or **Excel (.xlsx)** file whose **headers** match the example for this definition (technical field paths or the same human-readable labels as in the example). **Tabular JSON upload is not supported** (JSON remains available for *example template* download and for **definition** import/export). Fill **filter** fields (`fr_get_*`, `fr_kw_*`) the same way as **Process export** on exports. An **`ImportRequest`** is created in **pending** status: uploaded file + filter payload are stored for audit.
2. **Preview** — first rows are shown. Validation checks headers and the **first data row** (required scalar fields on the target model).
3. **Confirm** — POST runs the import and updates the same **`ImportRequest`**: **success** or **failure**, `imported_row_count`, `error_trace`, `completed_at`. If **`IMPORT_TASK_BACKEND`** is not **`sync`** and **`IMPORT_ADMIN_OFFER_ASYNC`** is true, the form can show **Process import in background**; when checked, status becomes **`processing`** first, then the configured backend (**`thread`**, **Celery**, **django-rq**) runs **`run_import_request`**.

Settings (defaults in **`DjangoImportExportFlowConfig.default_settings`**, overridable via **`DJANGO_IMPORTEXPORT_FLOW`**): **`IMPORT_TASK_BACKEND`** (`sync` \| `thread` \| `celery` \| `rq`), **`IMPORT_ADMIN_OFFER_ASYNC`**, **`IMPORT_ADMIN_ASYNC_DEFAULT`**. API: **`process_import(..., run_async=True)`** returns **`queued=True`** when the row is deferred; CLI: **`process_import ... --async`**.

Implementation: **`django_importexport_flow.task.get_import_task_backend`**, **`dispatch_import_request`**; workers call **`django_importexport_flow.tasks.execute_import_request_by_uuid`** (Celery task name **`django_importexport_flow.run_import_request`**).

### Partial import

Imports use batches of up to **`TABULAR_IMPORT_BATCH_SIZE`** (default **500**, from
`django_importexport_flow.apps.DjangoImportExportFlowConfig.default_settings` or
`settings.DJANGO_IMPORTEXPORT_FLOW`). Rows that only need scalar / FK columns share a
 **`bulk_create`** in one transaction per batch. Rows with M2M or reverse-O2M **slot**
 paths still use **`create`** + relation hooks per row.

Set **`TABULAR_IMPORT_BATCH_SIZE`** to **`1`** to match the old behaviour (one
transaction per row, always).

If a **batch** fails (for example a bad value mid-file), that batch is **retried row by
row**, so earlier rows can still commit and **`ImportRequest`** error traces stay
 **per line**—same partial-success semantics as before. See **`_execute_rows`** in
 **`engine/core/run.py`**.

Batched **`bulk_create`** does not invoke **`save()`** per instance (no per-row
**`pre_save`** / **`post_save`** signals). Use **`TABULAR_IMPORT_BATCH_SIZE: 1`** if you
rely on those for every row.

### `ImportRequest` (admin)

- **Related scope** (optional): rows on **`ImportRequestRelatedObject`** (content type + object id + generic FK + snapshot string), editable as an **inline** on the import request admin. Programmatic: **`create_import_request(..., related_object=instance)`** or **`process_import(..., related_object=…)`** creates one link. Query in-flight imports with **`ImportRequest.active_imports_for_object(obj)`** (`pending` / `processing`). **Relaunch** duplicates all links.

- **Export audit**: same pattern with **`ExportRequestRelatedObject`** and an inline on **`ExportRequest`** (optional links only; export code can be extended to attach scope when needed).

- **List / change**: read-only trace (status, file, filters, related scope summary, errors).
- **Relaunch** (admin action): creates a **new** pending **`ImportRequest`** with the same file and `filter_payload`, linked via **`relaunched_from`**. Each attempt is kept in history.

Manual add of **`ImportRequest`** in the admin is disabled; rows come from the wizard or **Relaunch**.

### Code layout

- **Paths & headers**: `engine/core/paths.py` (`effective_import_column_paths`, `resolve_import_column_paths`, …).
- **Normalize / validate**: `engine/core/preview.py`.
- **Per-row persist**: `engine/core/items.py` and `engine/core/run.py`.

Public imports should keep using **`django_importexport_flow.engine.core.import_`** (stable façade).

### Upload checks (tabular)

Before parsing, **`utils.upload_validation.validate_tabular_upload_bytes`** checks that content matches the type implied by the filename (ZIP header for ``.xlsx``, OLE header for ``.xls``, UTF-8 text for ``.csv``) and rejects obvious extension/content mismatches. This complements (does not replace) safe operational practices (staff-only admin, size limits).

### Configuration JSON (export / import definitions)

Uploaded definition JSON is structurally validated (**`validate_configuration_json_payload`**: top-level object, ``objects`` array, ``model`` strings, etc.) before ``django.core.deserializers`` runs. Only import files from **trusted** sources—same risk profile as ``loaddata``.

Back to [documentation index](README.md).

