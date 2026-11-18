#!/usr/bin/env bash
# Run the local quality, security, typing, and packaging checks used by the
# current-state audit. Print everything to stdout/stderr. Redirect yourself if
# you want a file:
#
#   ./audit.sh
#   ./audit.sh > audit-report.txt 2>&1
#   PYTHON=/path/to/python ./audit.sh

set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

resolve_python() {
  if [[ -n "${PYTHON:-}" ]]; then
    printf '%s\n' "$PYTHON"
    return
  fi
  if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
    printf '%s\n' "$ROOT_DIR/.venv/bin/python"
    return
  fi
  # Shared Projects venv used by local development of this library.
  if [[ -x "/Users/charlesd./Projects/.venv/bin/python" ]]; then
    printf '%s\n' "/Users/charlesd./Projects/.venv/bin/python"
    return
  fi
  if command -v python >/dev/null 2>&1; then
    command -v python
    return
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return
  fi
  return 1
}

if ! PYTHON_BIN="$(resolve_python)"; then
  printf 'No usable Python interpreter found.\n' >&2
  exit 1
fi

PYTHON_DIR="$(cd "$(dirname "$PYTHON_BIN")" && pwd)"
export PATH="$PYTHON_DIR:$PATH"

PACKAGE_VERSION="$("$PYTHON_BIN" - <<'PY'
from pathlib import Path
import re

text = Path("pyproject.toml").read_text(encoding="utf-8")
match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
print(match.group(1) if match else "unknown")
PY
)"

failures=()
BUILD_DIR="$(mktemp -d "${TMPDIR:-/tmp}/django-importexport-flow-audit.XXXXXX")"
trap 'rm -rf "$BUILD_DIR"' EXIT

printf '# django-importexport-flow audit\n\n'
printf 'Generated: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
printf 'Package: %s\n' "$PACKAGE_VERSION"
printf 'Commit: %s\n' "$(git rev-parse --verify HEAD 2>/dev/null || printf 'unknown')"
printf 'Python: %s (%s)\n' "$("$PYTHON_BIN" --version 2>&1)" "$PYTHON_BIN"
printf 'Platform: %s\n' "$(uname -a)"
printf '\nThis report mirrors the local commands in docs/current-state-audit.md.\n'
printf 'makemigrations is intentionally not run.\n'

run_check() {
  local name="$1"
  shift

  printf '\n## %s\n\n' "$name"
  printf '$'
  printf ' %q' "$@"
  printf '\n\n'

  if "$@"; then
    printf '\nExit status: 0\n'
  else
    local status=$?
    printf '\nExit status: %d\n' "$status"
    failures+=("$name ($status)")
  fi
}

run_check "Django system check" "$PYTHON_BIN" manage.py check
run_check "Ruff lint" "$PYTHON_BIN" -m ruff check src tests
run_check "Ruff format" "$PYTHON_BIN" -m ruff format --check src tests
run_check "Git whitespace check" git diff --check
run_check \
  "Tests, branch coverage, and strict warnings" \
  "$PYTHON_BIN" -m pytest \
  -q \
  --tb=line \
  --cov=django_importexport_flow \
  --cov-branch \
  --cov-report=term:skip-covered \
  -W error::ResourceWarning \
  -W error::pytest.PytestUnraisableExceptionWarning \
  -W error::django.core.paginator.UnorderedObjectListWarning
run_check \
  "Bandit" \
  "$PYTHON_BIN" -m bandit \
  -r src/django_importexport_flow \
  -x src/django_importexport_flow/migrations \
  -ll -ii
run_check "Dependency audit" "$PYTHON_BIN" -m pip_audit .
run_check \
  "Dead code" \
  "$PYTHON_BIN" -m vulture \
  src/django_importexport_flow \
  --min-confidence 90 \
  --exclude '*/migrations/*'
run_check \
  "Cyclomatic complexity inventory" \
  "$PYTHON_BIN" -m radon cc \
  src/django_importexport_flow \
  -s -a \
  -e '*/migrations/*'
run_check \
  "Complexity thresholds" \
  "$PYTHON_BIN" -m xenon \
  src/django_importexport_flow \
  --exclude '*/migrations/*' \
  --max-absolute C \
  --max-modules B \
  --max-average A
run_check "Type checking" "$PYTHON_BIN" -m mypy src/django_importexport_flow
run_check "Package build" "$PYTHON_BIN" -m build --outdir "$BUILD_DIR"

distributions=("$BUILD_DIR"/*)
if [[ -e "${distributions[0]}" ]]; then
  run_check "Distribution validation" "$PYTHON_BIN" -m twine check "${distributions[@]}"
else
  failures+=("Distribution validation (package build produced no files)")
fi

wheels=("$BUILD_DIR"/*.whl)
if [[ -e "${wheels[0]}" ]]; then
  run_check \
    "Wheel contents" \
    "$PYTHON_BIN" \
    "$ROOT_DIR/.github/scripts/check-wheel-contents.py" \
    "${wheels[@]}"
else
  failures+=("Wheel contents (package build produced no wheel)")
fi

printf '\n## Summary\n\n'
if ((${#failures[@]} == 0)); then
  printf 'All checks passed.\n'
  exit 0
fi

printf '%d check(s) failed:\n' "${#failures[@]}"
printf -- '- %s\n' "${failures[@]}"
exit 1
