# Import data (admin wizard)

On an import **`Definition`** change page, **Import data** opens a wizard:

1. **Upload** — choose a **CSV** or **Excel (.xlsx)** file whose **headers** match the example for this definition (technical field paths or the same human-readable labels as in the example). **Tabular JSON upload is not supported** (JSON remains available for *example template* download and for **definition** import/export). Fill **filter** fields (`fr_get_*`, `fr_kw_*`) the same way as **Process export** on exports. An **`ImportRequest`** is created in **pending** status: uploaded file + filter payload are stored for audit.
2. **Preview** — first rows are shown. Validation checks headers and the **first data row** (required scalar fields on the target model).
3. **Confirm** — POST runs the import and updates the same **`ImportRequest`**: **success** or **failure**, `imported_row_count`, `error_trace`, `completed_at`. If **`IMPORT_TASK_BACKEND`** is not **`sync`** and **`IMPORT_ADMIN_OFFER_ASYNC`** is true, the form can show **Process import in background**; when checked, status becomes **`processing`** first, then the configured backend (**`thread`**, **Celery**, **django-rq**) runs **`run_import_request`**.

Settings (defaults in **`DjangoImportExportFlowConfig.default_settings`**, overridable via **`DJANGO_IMPORTEXPORT_FLOW`**): **`IMPORT_TASK_BACKEND`** (`sync` \| `thread` \| `celery` \| `rq`), **`IMPORT_ADMIN_OFFER_ASYNC`**, **`IMPORT_ADMIN_ASYNC_DEFAULT`**, **`PERSIST_IMPORT_REQUEST_FILES`** and **`PERSIST_EXPORT_REQUEST_FILES`** (both default **true**; when **false**, a synchronous call keeps that file in memory and leaves the request file field empty). **`IMPORT_FILE_STORAGE`** and **`EXPORT_OUTPUT_STORAGE`** are dotted storage classes; empty uses Django's default storage. **`IMPORT_FILE_UPLOAD_TO`** and **`EXPORT_OUTPUT_UPLOAD_TO`** are either a relative path template (`report_import_asks/%Y/%m/`, `export_outputs/%Y/%m/`) or a dotted `callable(instance, filename)`. A template must contain `/` or `%`. API: **`process_import(..., run_async=True)`** returns **`queued=True`** when the row is deferred; CLI: **`process_import ... --async`**. The admin wizard, relaunch, and async workers require **`PERSIST_IMPORT_REQUEST_FILES`**.

Implementation: **`django_importexport_flow.task.get_import_task_backend`**, **`dispatch_import_request`**; workers call **`django_importexport_flow.tasks.execute_import_request_by_uuid`** (Celery task name **`django_importexport_flow.run_import_request`**). Those backends only control execution. In the standard pipeline, the file is read by the format hook list on **`FormatConfig`**: empty uses the native hook, and a non-empty list replaces it. Hook options stay in **`configuration`**.

### Business import processors

Set `{"import_processor": "myapp.imports.process_register"}` on an import
**`CategoryConfig.configuration`** to replace generic validation and row persistence
for that category. Keep its file formats enabled on `FormatConfig`. The processor
receives `(file, context)` instead of running the format hook chain and may reuse
the normal readers itself. Use a filename with the enabled format's extension.
The dotted path uses the same `ALLOWED_HOOK_MODULE_PREFIXES` setting as custom
format hooks.

Import `ImportProcessorContext` and `ImportProcessorResult` from
`django_importexport_flow.engine.core.processor`. The context exposes the
definition, format key, initiating user, a copy of the saved `filter_payload`,
and `preview_only`. Put business options needed on relaunch in `filter_payload`;
for example, `process_import(..., filter_payload={"fr_get_company_id": "42", "reset": True})`.
The result uses `errors` to signal failure and `imported_row_count` to report
the number of committed rows. It can also provide `warnings`, a preview
`dataframe`, corresponding `column_paths`, and an optional total `row_count`.

The API and admin call the processor in preview mode without committing any
writes on Django's default database. Processors must also avoid external
side effects during preview. Confirmed imports run atomically on that database:
exceptions or returned errors roll back the processor's writes. Flow retains
ownership of the uploaded file and audit row, and a relaunch reuses the saved
file and filter payload with the current definition. Imports without a
processor keep the standard pipeline and its partial-import behavior.

### Combined imports

Enable the input format on an import definition and add ordered **Import
steps** in its admin page. A definition with steps is a combined import; one
without steps runs as a normal import. Each step references an existing import
definition. Positions and definitions must be unique within the combined
import. Nested combined imports are not supported. The import definitions
admin list displays and allows sorting by the number of steps.
Use the step lookup to select an existing import definition by ID; excluded
relation types can be selected with the dual-list widget.

The same file, user and filter payload are passed to each step in order.
The combined import accepts both standard imports and business processors;
each step must accept the same file format and headers. The parent definition
reads the file for the single preview. Each step is validated independently
without writes, so this preview cannot simulate dependencies on earlier steps.
For example, a later step cannot preview an object that an earlier step would
create during confirmation.

Confirmation executes all steps sequentially in one transaction on the
default database. An error or exception stops execution and rolls back all
database writes from the steps. External side effects and writes to other
databases cannot be rolled back; processors must defer side effects until
commit. Asynchronous processing queues the combined request as a whole, not
individual steps. Its audit row records the total imported count or the failing
step and error. Relaunch uses the current step configuration.

The `Step` model stores ordered definition references. Currently, only import
definitions may use steps; export orchestration is not implemented.
Definitions fetched through the standard managers have an annotated
`step_count`: a count greater than zero indicates a combined import. Like any
query annotation, it is a snapshot; execution checks the current count again.

The JSON configuration for a combined import includes its ordered step
references by import `named_id`; referenced definitions must already exist when
the configuration is imported. Importing that JSON in admin requires add,
change and delete permissions for import steps.

### Custom import templates

Set these optional keys on the spreadsheet **`CategoryConfig.configuration`**:

```json
{
  "template_columns": ["holder", "quantity"],
  "template_labels": ["Titulaire", "Quantité"],
  "template_labels_by_language": {"en": ["Holder", "Quantity"]},
  "template_filename": {"fr": "Modèle de registre", "en": "Register template"}
}
```

`template_columns` overrides the example file's technical headers without changing
which columns the import engine accepts. A processor can define its own keys.
CSV and Excel templates keep those keys on the first row, followed by the labels
and an empty row. JSON examples use only the technical keys. Each label list must
contain one entry per column. Without an explicit column list, Flow derives the
headers from the target model as before.

Flow uses the active Django language (including regional and project-default
fallbacks) for localized values. Without a matching label list it uses
`template_labels`, then `ColumnTranslation` for the definition's target and each
column path (including custom processor keys), then model verbose names or the
technical keys. Explicit label lists keep priority over the catalog.
Use `import_example_download_response`
from `django_importexport_flow.utils.process` in your own views to share the
admin's template generator and filename resolution. Without a matching filename,
it uses the caller's fallback or the definition name.

For a custom processor, set `"template_header_mode": "localized"` to generate
CSV and Excel templates with only the translated header row. The processor
must call `normalize_template_headers(definition, dataframe)` from
`django_importexport_flow.utils.process` after reading the file. It maps labels
from all configured languages and the `ColumnTranslation` catalog back to the
technical keys, regardless of the active language or column order. Technical
headers remain valid, and unrelated
headers are left unchanged. Ambiguous aliases and multiple headers mapping to
the same key are rejected. JSON still uses technical keys.

#### Simple and combined template hooks

Template generation has two native hooks, separate from the business import
processor:

- `django_importexport_flow.engine.hooks.native_import_template` builds the
  existing simple template schema.
- `django_importexport_flow.engine.hooks.native_combined_import_template` calls
  each child's effective template hook in `(position, pk)` order and merges its
  schema. A shared **technical path** appears only once, with the first child's
  label retained even if later children use another label. Identical labels on
  different paths do not merge the columns.

The choice uses the current database steps, not a cached `step_count`.
Child labels use their own targets and `ColumnTranslation` catalogs; the parent
does not replace them with labels derived from its own model. Parent
`template_columns` retains its existing behavior and replaces the automatic
merge with an explicit simple schema. Without it, parent label lists may override
the merged labels if they provide one label per merged column.
The parent still controls the CSV delimiter, filename and header mode.
`template_header_mode: "localized"` works for an automatically merged schema
without parent `template_columns`. Duplicate or ambiguous localized headers
are rejected; the default technical headers can retain identical display labels.

Set `template_hook` on the spreadsheet `CategoryConfig.configuration` to replace
the selected hook for either a child or the parent:

```json
{
  "template_hook": "myapp.import_templates.custom_combined_template"
}
```

Hooks receive `(definition, context)` and must return an `ImportTemplateDataset`
from `django_importexport_flow.engine.core.dataset`. Its `columns` are unique,
non-empty technical paths and its `labels` contains one string per column.
During file generation, `context["example_format"]` is `csv`, `excel`, or `json`;
header normalization calls hooks with an empty context. A custom hook can delegate
to either native hook and modify the returned schema:

```python
from django_importexport_flow.engine.core.dataset import ImportTemplateDataset
from django_importexport_flow.engine.hooks import native_combined_import_template
from django_importexport_flow.models import Definition


def custom_combined_template(
    definition: Definition, context: dict[str, object]
) -> ImportTemplateDataset:
    template = native_combined_import_template(definition, context)
    template.columns.append("comment")
    template.labels.append("Comment")
    return template
```

Flow renders this schema into CSV, Excel or JSON using the existing layouts.
For localized custom labels, provide catalog entries or
`template_labels_by_language` when headers must be recognized in other languages.
Template generation never runs business processors or creates import requests.
Nested combined imports remain unsupported. Native hooks are always allowed;
custom paths follow `ALLOWED_HOOK_MODULE_PREFIXES`. Invalid hook results and hook
exceptions propagate rather than falling back to another template.

#### Export-prefilled templates

Set the optional **Template export** (`Definition.template_export`) on an import
definition to prefill its template with existing records. The admin uses a raw-ID
lookup restricted to export definitions. Deleting a referenced export is
protected: remove the link explicitly first.

The export supplies rows using its native tabular dataset: manager, static
filters, request filters, ordering and technical column paths. Configure the
export for the requested format (CSV, Excel or JSON). Flow does not parse a
rendered export file or run export format/filename hooks. Import template hooks
are also bypassed, including child template hooks for a combined import.
Business import processors never run during template generation.

The import's **native template configuration remains the schema**:
`template_columns`, labels, `ColumnTranslation`, header mode, delimiter and
filename retain their normal behavior. Without explicit parent columns, a
combined import uses the ordered union of its children's native schemas. Link
the export on the combined parent; Flow does not join child exports.

Configure both definitions with compatible **technical keys**, not merely equal
display labels. Each exported key must occur exactly once and belong to the
import schema. Missing import columns are filled with empty values. Unknown,
duplicate or reverse-expanded export columns are rejected; there is no implicit
column renaming. For example, an export of only `company_siren` can prefill:

```csv
company_siren,meeting_date,meeting_time
000123456,,
987654321,,
```

This example assumes localized-only headers whose labels equal those keys.
With the default technical header mode, the descriptive labels row is retained.
An empty export produces no data rows. Spreadsheet formula protection applies
to exported values in CSV/Excel; JSON retains the values without that escaping.
Generation creates neither import nor export audit requests.

For editing contacts, include a stable identifier and configure the import's
`match_fields` (and `exclude_primary_key=False` when using the primary key).
The export/template link does **not** change create/update or blank-cell policies.

Custom views pass trusted scope/filter values through the normal export payload:

```python
response = import_example_download_response(
    import_definition,
    example_format="csv",
    filter_payload={"fr_kw_company_id": str(company.pk)},
)
```

`generate_example_file` accepts the same optional `filter_payload`. Configure
mandatory filters on the **export** to prevent an unscoped download; missing
filters raise an error instead of returning an empty template or all records.
API callers must enforce permissions and build this scope from trusted context;
Flow does not infer a user's row permissions. The admin checks view/change
permission on the associated export and displays its filter fields before
download. The CLI accepts `--filter-json` or `--filter-json-file`, using the same
`fr_*`, `mg_*` and `mm_*` keys as exports.

JSON configuration serialization stores this link by the export's `named_id`;
UUID references are also accepted on import. The referenced export must already
exist. Definitions without a template export keep their existing hooks and
empty-template behavior unchanged.

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
- **Add**: select the import or export definition using its raw-ID lookup.
- **Relaunch** (admin action): creates a **new** pending **`ImportRequest`** with the same file and `filter_payload`, linked via **`relaunched_from`**. Each attempt is kept in history.

Manual creation of **`ImportRequest`** and **`ExportRequest`** in the admin is
restricted to superusers. Requests can also come from the wizard or **Relaunch**.

### Code layout

- **Paths & headers**: `engine/core/paths.py` (`effective_import_column_paths`, `resolve_import_column_paths`, …).
- **Normalize / validate**: `engine/core/preview.py`.
- **Per-row persist**: `engine/core/items.py` and `engine/core/run.py`.

Public imports should keep using **`django_importexport_flow.engine.core.import_`** (stable facade).

### Upload checks (tabular)

Before parsing, **`utils.upload_validation.validate_tabular_upload_bytes`** checks that content matches the type implied by the filename (ZIP header for ``.xlsx``, OLE header for ``.xls``, UTF-8 text for ``.csv``) and rejects obvious extension/content mismatches. The reader stops once the file exceeds ``MAX_TABULAR_IMPORT_BYTES`` (default 10 MiB) instead of buffering the whole upload first. An ``.xlsx`` archive is also rejected when it is not a valid ZIP, contains more than ``MAX_XLSX_ARCHIVE_MEMBERS`` entries (default 1000), declares more than ``MAX_XLSX_UNCOMPRESSED_BYTES`` uncompressed bytes (default 50 MiB), exceeds ``MAX_XLSX_COMPRESSION_RATIO`` (default 100), or names an entry with an absolute path or ``..``. Nothing is extracted to disk. ``.xls`` stays an OLE check plus the raw byte limit. This complements (does not replace) safe operational practices (staff-only admin, size limits).

### Configuration JSON (export / import definitions)

Uploaded definition JSON is structurally validated (**`validate_configuration_json_payload`**: top-level object, ``objects`` array, ``model`` strings, etc.) before ``django.core.deserializers`` runs. Only import files from **trusted** sources—same risk profile as ``loaddata``.

Back to [documentation index](README.md).

