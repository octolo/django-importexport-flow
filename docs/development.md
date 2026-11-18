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

## Lint and quality

```bash
ruff check src tests
ruff format --check src tests
python manage.py check
python manage.py makemigrations --check
pytest --cov=django_importexport_flow --cov-branch --cov-report=term-missing
bandit -r src/django_importexport_flow -x src/django_importexport_flow/migrations -ll -ii
pip-audit .
vulture src/django_importexport_flow --min-confidence 90 --exclude '*/migrations/*'
radon cc src/django_importexport_flow -s -a -e '*/migrations/*'
xenon src/django_importexport_flow --exclude '*/migrations/*' --max-absolute C --max-modules B --max-average A
mypy src/django_importexport_flow
```

To run a full local audit (check, Ruff, pytest with coverage and strict
warnings, Bandit, pip-audit, Vulture, Radon, Xenon, mypy, build, Twine):

```bash
./audit.sh
./audit.sh > audit-report.txt 2>&1
```

`makemigrations` is not part of the audit script.

The coverage gate is **72%** branch-aware coverage (`fail_under` in `pyproject.toml`). The measured result on 18 November 2026 is **77.24%** across **231** tests. The same run stays clean when resource warnings, unraisable exceptions, and unordered pagination warnings are treated as errors. Mypy covers the whole package, migrations excluded. See [current-state audit](current-state-audit.md).

## Package layout

- **`src/django_importexport_flow/`** — application code and migrations.
- **`engine/core/`** — export/import engines; import logic split into `paths.py`, `io.py`, `preview.py`, `items.py`, `run.py` (see [structure.md](structure.md)).
- **`tests/`** — pytest suite and sample app models.

Back to [documentation index](README.md).
