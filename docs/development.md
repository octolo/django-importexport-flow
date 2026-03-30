# Development

## Environment

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"     # includes weasyprint for PDF tests; or add ".[pdf]" in prod
```

## Tests

```bash
pytest
```

Tests use **`tests.settings`** (SQLite file in the repo) and **`django_boosted`** as an installed app.

## Lint

```bash
ruff check src tests
```

## Package layout

- **`src/django_importexport_flow/`** — application code and migrations.
- **`engine/core/`** — export/import engines; import logic split into `paths.py`, `io.py`, `preview.py`, `items.py`, `run.py` (see [structure.md](structure.md)).
- **`tests/`** — pytest suite and sample app models.

Back to [documentation index](README.md).
