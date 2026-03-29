# Development

## Environment

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Tests

```bash
pytest
```

Tests use **`tests.settings`** (SQLite in memory) and **`django_boosted`** as an installed app.

## Lint

```bash
ruff check src tests
```

## Package layout

- **`src/django_importexport_flow/`** — application code and migrations.
- **`tests/`** — pytest suite and sample app models.

Back to [documentation index](README.md).
