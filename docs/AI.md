# AI assistant notes — django-importexport

Short conventions for this repository (does not override your global Cursor rules unless the project configures it).

- **Language**: public code, docstrings, and user-facing strings follow the project’s existing style (English in source and docs here).
- **Migrations**: do not create or run migrations unless the user explicitly asks; model/schema edits are fine, migrations are the user’s responsibility.
- **Scope**: prefer minimal diffs; avoid drive-by refactors unrelated to the task.
- **Tests**: run `pytest` from the package root after behavioural changes; tests use `tests.settings` and the sample app under `tests/`.

For architecture and layout, see [structure.md](structure.md) and [filters-and-export.md](filters-and-export.md).
