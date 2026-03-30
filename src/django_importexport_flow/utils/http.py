"""HTTP helpers for downloads (``Content-Disposition``)."""

from __future__ import annotations

from urllib.parse import quote


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
