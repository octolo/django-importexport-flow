# Project structure

```
django-importexport-flow/
├── src/django_importexport_flow/
│   ├── engine/
│   │   ├── core/
│   │   │   ├── engine.py      # CoreEngine — queryset, filters, order_by
│   │   │   ├── table.py       # TableEngine — CSV / Excel / JSON rows
│   │   │   ├── pdf.py         # PdfEngine — HTML → PDF (WeasyPrint)
│   │   │   ├── export.py      # run_table_export, filter payload helpers
│   │   │   ├── hooks.py       # Format hook chain (native or configured list)
│   │   │   ├── overrides.py   # Request template and allowed configuration overrides
│   │   │   ├── processing.py  # ImportRequest / ExportRequest through that chain
│   │   │   ├── filters.py     # Dynamic filter fields for forms / CLI
│   │   │   ├── validation.py  # Filter maps, column specs, manager path
│   │   │   ├── tabular.py     # CSV/Excel bytes → pandas DataFrame
│   │   │   ├── import_.py     # Public import API (re-exports)
│   │   │   ├── paths.py       # Import field paths & header mapping
│   │   │   ├── io.py          # Upload / FileField → DataFrame
│   │   │   ├── preview.py     # Normalize & validate before save
│   │   │   ├── items.py       # One record → model kwargs & M2M slots
│   │   │   └── run.py         # ImportRequest create / run / relaunch
│   │   ├── csv.py | excel.py | json.py | pdf.py   # Thin aliases to core.table / core.pdf
│   │   └── __init__.py        # Lazy exports (CoreEngine, TableEngine, …)
│   ├── models/
│   │   ├── definition.py        # Definition + export/import proxies
│   │   ├── category.py          # CategoryConfig + category proxies
│   │   ├── format.py            # FormatConfig + format proxies
│   │   ├── request.py           # ImportRequest, ExportRequest, related objects
│   │   ├── translation.py       # ColumnTranslation
│   │   ├── mixins.py
│   │   └── preview.py           # abstract in-memory preview rows
│   ├── admin/                 # definition, category, format, request, translation, mixins, preview
│   ├── task/                  # IMPORT_TASK_BACKEND (sync, thread, celery, rq)
│   ├── tasks.py               # execute_import_request_by_uuid (+ optional Celery task)
│   ├── management/commands/   # process_export, process_import, generate_example_file
│   ├── utils/                 # process, helpers, serialization, lookup, upload_validation, …
│   ├── forms.py
│   ├── apps.py
│   ├── managers.py
│   └── migrations/
├── tests/
├── docs/
├── pyproject.toml
└── README.md
```

## Import pipeline (`engine.core.import_`)

The module **`import_.py`** (keyword-safe name) is the **stable public entry**: functions and constants used by admin, `utils.process`, and tests.

Implementation lives in short modules next to it:

| Module | Role |
|--------|------|
| **`paths`** | “Horizontal” mapping: Django field path strings (`author.name`, M2M slots, …), default paths for a model, resolving file headers to paths. |
| **`io`** | Read bytes or uploaded files into a **tabular** DataFrame (CSV / Excel — not JSON arrays for tabular import). |
| **`preview`** | Align columns, strip optional label row, **`validate_import_preview`**. |
| **`items`** | “Vertical” mapping: one DataFrame row → `create` kwargs, nested FK trees, slot relations. |
| **`run`** | **`create_import_request`**, **`run_import_request`**, **`relaunch_import_request`**. |

## Export side

- **`CategoryConfig.columns`**: list of column strings (JSON), same path vocabulary as imports where applicable.
- **Engines**: **`CoreEngine`** builds the queryset; **`TableEngine`** / **`PdfEngine`** add tabular or PDF output.
- **Hooks**: each format runs its native hook, or the ordered list stored on **`FormatConfig.hook`** when that list is not empty. Stored options live in **`FormatConfig.configuration`**. An **`ExportRequest`** may supply `template_override` and `configuration_overrides` for that run only: request values win over the stored format configuration. Sync, thread, Celery, and RQ backends only decide when the same pipeline runs.

See [filters-and-export.md](filters-and-export.md) and [import-data.md](import-data.md).

Back to [documentation index](README.md).
