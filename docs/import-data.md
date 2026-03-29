# Import data (admin wizard)

On a **ReportImport** change page, **Import data (preview)** opens a wizard:

1. **Upload** — choose a CSV, Excel (.xlsx), or JSON (array of records) file whose **column headers match exactly** the headers from *Example CSV / Excel / JSON* for this import. Fill **filter** fields (`fr_get_*`, `fr_kw_*`) the same way as *Generate export* on definitions. A **`ReportImportAsk`** row is created (**pending**): uploaded file + filter payload are persisted for audit.
2. **Preview** — the first rows are shown in a table. Validation runs on headers and the **first data row** (required scalar fields on the target model).
3. **Confirm** — POST runs the import and updates the same **`ReportImportAsk`**: **success** or **failure**, `imported_row_count`, `error_trace` (traceback or per-row errors), `completed_at`.

### `ReportImportAsk` (admin)

- **List / change**: read-only trace for support (status, file, filters, errors).
- **Relaunch** (admin action): creates a **new** pending `ReportImportAsk` with the same file and `filter_payload`, linked via **`relaunched_from`** to the previous row. Each attempt stays in history; failed rows keep **`error_trace`**.

Manual add of `ReportImportAsk` in the admin is disabled; rows come from the wizard or **Relaunch**.

Back to [documentation index](README.md).
