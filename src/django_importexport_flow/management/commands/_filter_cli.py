"""Parse ``--filter-json`` / ``--filter-json-file`` for management commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_filter_payload_dict(
    *,
    filter_json: str | None,
    filter_json_file: str | None,
) -> dict[str, Any]:
    """Return a dict from inline JSON or a UTF-8 file; both absent → ``{}``."""
    if filter_json_file:
        raw = Path(filter_json_file).read_text(encoding="utf-8")
        return json.loads(raw) if raw.strip() else {}
    if filter_json is not None and str(filter_json).strip():
        return json.loads(filter_json)
    return {}
