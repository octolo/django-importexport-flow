#!/usr/bin/env bash
set -eu

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -n "${PYTHON:-}" ]]; then
  exec "$PYTHON" "$root/scripts/audit.py" "$@"
elif [[ -x "$root/.venv/bin/python" ]]; then
  exec "$root/.venv/bin/python" "$root/scripts/audit.py" "$@"
elif command -v python >/dev/null 2>&1; then
  exec python "$root/scripts/audit.py" "$@"
else
  exec python3 "$root/scripts/audit.py" "$@"
fi
