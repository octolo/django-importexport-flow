"""HTTP helpers for downloads (``Content-Disposition``)."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from django.http import HttpResponse


def content_disposition_attachment(filename: str) -> str:
    """
    ``Content-Disposition`` value with ASCII ``filename`` and RFC 5987 ``filename*``
    when the name is not ASCII-only.
    """
    try:
        filename.encode("ascii")
    except UnicodeEncodeError:
        pass
    else:
        return f'attachment; filename="{filename}"'
    ascii_fallback = filename.encode("ascii", "replace").decode("ascii").replace("?", "_")
    quoted = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quoted}"


def configuration_json_download_response(instance: Any, payload: dict[str, Any]) -> HttpResponse:
    """JSON body with ``Content-Disposition: attachment`` for configuration export admin views."""
    from .helpers import configuration_json_download_filename

    body = (
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
    response = HttpResponse(body, content_type="application/json; charset=utf-8")
    response["Content-Disposition"] = content_disposition_attachment(
        configuration_json_download_filename(instance)
    )
    return response
