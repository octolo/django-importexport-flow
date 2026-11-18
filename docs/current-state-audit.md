# Current state: architecture, quality, and security

Snapshot of the repository on 18 November 2026. Migrations are excluded from the
static measurements. The figures below come from commands run locally with
Python 3.14.10 and `django-importexport-flow` 1.2.0.

## Summary

- 231 tests pass, including when resource warnings, unraisable exceptions, and
  unordered pagination warnings are treated as errors.
- Line and branch coverage: 77.24%. The threshold remains 72%.
- Django `check`, Ruff, and `ruff format --check` pass.
- mypy passes on the whole package, migrations excluded. That is also the CI scope.
- Bandit (`-ll -ii`), pip-audit, Vulture (confidence 90), and Xenon pass.
- Xenon requires absolute rank C, module rank B, and average rank A.
- `python -m build` and `twine check` pass for version 1.2.0.
- No open critical risk was found during this pass.

## Architecture

A `Definition` stores the `export` or `import` direction, the target model, the
filters, and the ordering. It owns `CategoryConfig` rows (`spreadsheet`,
`document`, `structured_data`). Each category owns the `FormatConfig` rows that
enable CSV, Excel, JSON, or PDF.

`ExportDefinition` and `ImportDefinition` are directional proxies of
`Definition`. Categories and formats have proxies as well. Audit cycles are
stored by `ExportRequest` and `ImportRequest`.

Export goes through `CoreEngine`, then `TableEngine` or `PdfEngine`, then the
hook chain. Request-specific options are `template_override` and
`configuration_overrides`. An empty hook list keeps the native hook; a non-empty
list replaces it and runs in order.

Import is split across `paths`, `io`, `preview`, `items`, `run`, and
`validation`. `engine/core/import_.py` keeps the public facade and the public
aliases.

The `sync`, `thread`, `celery`, and `rq` backends choose only the execution
mode. Admin code is grouped in `admin/definition.py`, `admin/category.py`,
`admin/format.py`, `admin/request.py`, `admin/translation.py`,
`admin/preview.py`, and `admin/mixins.py`.

## Security controls

The following controls are covered by the code and tests:

- CSV and Excel text that could be executed as a formula is prefixed with `'`;
- JSON is left unchanged;
- import reads are bounded, restore a seekable stream, and close only files
  opened by the function;
- an XLSX archive is limited by entry count, declared size, and compression
  ratio, and a real workbook is accepted;
- the hook allowlist is enforced during validation and execution;
- an empty allowlist still leaves the native hooks available;
- a PDF template submitted in the admin requires `change_formatconfig`;
- a POST containing a template without that permission is rejected;
- storage resolves in this order: instance or callable, `STORAGES` alias,
  dotted path, then an error;
- `upload_to` accepts a callable, a dotted callable, or a relative directory;
- an absolute path or a `..` traversal is rejected;
- the Celery and django-rq adapters are tested without a broker;
- admin SVG icons go through `format_html`.

## Trust boundaries

These choices are intentional and must be configured for the environment:

- `ALLOWED_HOOK_MODULE_PREFIXES=None` allows every importable hook;
- a PDF template remains a Django template, reserved for users with
  `change_formatconfig`;
- a persisted export can contain sensitive data;
- the selected storage must stay available for the life of the files;
- `purge_export_requests` deletes completed exports and their files, but running
  it regularly belongs to the deployment;
- `pip-audit .` resolves compatible versions; the repository has no lockfile.

## Quality and CI

The matrix tests Python 3.10, 3.11, and 3.12 with Django 5.0, 5.1, and 5.2. It
runs `manage.py check` and pytest.

The quality job, on Python 3.12 and Django 5.2, adds Ruff, the CI migration
check, `git diff --check`, coverage, Bandit, pip-audit, Vulture, Xenon, and
mypy. The CodeQL workflow is separate: its syntax was checked locally, but its
result is known only after the next GitHub Actions run. The build job, after
the matrix, builds the package and runs `twine check`.

CI mypy covers `src/django_importexport_flow`, migrations excluded.

## Representative tests

- `tests/test_security_hardening.py`: formulas, bounded reads, archives, and a
  real XLSX workbook;
- `tests/test_admin_workflows.py`: export, template permission, import wizard,
  and queueing;
- `tests/test_export_hooks.py` and `tests/test_export_generate.py`: hooks and
  per-request options;
- `tests/test_request_files.py`: storages, `upload_to`, and rejected paths;
- `tests/test_task_backends.py`: Celery and django-rq;
- `tests/test_purge_export_requests.py`: dry run, retention, statuses, and file
  deletion;
- `tests/test_proxies.py` and `tests/test_format_categories.py`: proxies and the
  historical configuration migration.

## Remaining debt

Xenon still accepts rank-C functions. The highest are now
`resolve_import_column_paths` and `CoreEngine.get_queryset` (15), followed by
`FormatConfigAdminForm.__init__`, `FormatConfigurationMixin.clean`,
`TableEngine._build_flat_columns`, `_save_related_from_tree`,
`_apply_slot_relations`, and `validate_import_match_fields` (14). No rank-D
block is allowed.

The repository has no lockfile: a library publishes compatible version ranges,
and each deployed project must pin its own environment. Semgrep is not
installed. CodeQL is added in `.github/workflows/codeql.yml`; that GitHub check
has not run yet. The coverage threshold stays intentionally at 72%, below the
measured 77.24%.

## Deployment

Keep `ESCAPE_SPREADSHEET_FORMULAS=True`. In a hardened environment, replace the
`None` allowlist with a prefix list or `[]`. Reserve `change_formatconfig` for
trusted users. Put sensitive exports in private storage, keep that storage for
files already written, and schedule `purge_export_requests`. Monitor the broker
used by Celery or django-rq.

## Reference commands

```bash
python manage.py check
ruff check src tests
ruff format --check src tests
pytest --cov=django_importexport_flow --cov-branch --cov-report=term-missing
bandit -r src/django_importexport_flow -x src/django_importexport_flow/migrations -ll -ii
pip-audit .
vulture src/django_importexport_flow --min-confidence 90 --exclude '*/migrations/*'
xenon src/django_importexport_flow --exclude '*/migrations/*' --max-absolute C --max-modules B --max-average A
mypy src/django_importexport_flow
python -m build
python -m twine check dist/*
```

Development command details are in [Development](development.md).

## Conclusion

The local blocking checks pass, including package typing. No open critical risk
is known. CodeQL still needs to be confirmed on GitHub. Deployment choices —
the allowlist, private storage, purge, and task monitoring — belong to the
consuming project. Rank-C complexity remains accepted by Xenon.
