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
radon mi src/django_importexport_flow -s -e '*/migrations/*'
radon raw src/django_importexport_flow -s -e '*/migrations/*'
xenon src/django_importexport_flow --exclude '*/migrations/*' --max-absolute C --max-modules B --max-average A
mypy src/django_importexport_flow
```

To run a full local audit (check, Ruff, pytest with coverage and strict
warnings, Bandit, pip-audit, Vulture, Radon, Xenon, mypy, build, Twine, and
the wheel contents check):

```bash
make audit
make audit PYTHON=/path/to/python
python scripts/audit.py > audit-report.txt 2>&1
```

With the development environment active, run `python scripts/audit.py` directly
on Windows, macOS, or Linux without Make or Bash. The audit requires Python
3.11+, the `dev` dependencies, and Git for the whitespace check.
`makemigrations` is not part of the audit script.
Radon reports complexity, maintainability, and code size without applying
thresholds. Xenon enforces the existing complexity thresholds.
CI also runs this audit in a separate non-blocking job; the existing quality,
test, and build jobs retain their current blocking checks.

The coverage gate is **72%** branch-aware coverage (`fail_under` in `pyproject.toml`). The measured result on 18 November 2026 is **77.24%** across **231** tests. The same run stays clean when resource warnings, unraisable exceptions, and unordered pagination warnings are treated as errors. Mypy covers the whole package, migrations excluded. See [current-state audit](current-state-audit.md).

## Package layout

- **`src/django_importexport_flow/`** — application code and migrations.
- **`engine/core/`** — export/import engines; import logic split into `paths.py`, `io.py`, `preview.py`, `items.py`, `run.py` (see [structure.md](structure.md)).
- **`tests/`** — pytest suite and sample app models.

Back to [documentation index](README.md).
