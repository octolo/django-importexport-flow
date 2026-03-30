"""Content sniffing for uploads (no extra dependencies beyond Django)."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _

_ZIP_MAGIC = b"PK\x03\x04"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _is_zip_head(raw: bytes) -> bool:
    return len(raw) >= 4 and raw[:4] == _ZIP_MAGIC


def _is_ole_head(raw: bytes) -> bool:
    return len(raw) >= 8 and raw[:8] == _OLE_MAGIC


def _looks_like_json_start(raw: bytes) -> bool:
    if not raw:
        return False
    first = raw.lstrip()[:1]
    return first in (b"[", b"{")


def validate_tabular_upload_bytes(raw: bytes, filename: str) -> None:
    """
    Ensure bytes match the declared (or implied) tabular type: Excel magic for ``.xlsx`` /
    ``.xls``, UTF-8 text for CSV paths; reject obvious type/extension mismatches.
    """
    if not raw:
        raise ValueError(str(_("The file is empty.")))
    lowered = (filename or "").lower()

    if lowered.endswith(".json"):
        return

    if lowered.endswith(".xlsx"):
        if not _is_zip_head(raw):
            raise ValueError(
                str(_("File content is not a valid Excel .xlsx document (expected a ZIP archive)."))
            )
        return

    if lowered.endswith(".xls"):
        if not _is_ole_head(raw):
            raise ValueError(
                str(
                    _(
                        "File content is not a valid Excel .xls document (expected OLE compound file)."
                    )
                )
            )
        return

    if lowered.endswith(".csv"):
        if _is_zip_head(raw):
            raise ValueError(
                str(
                    _(
                        "This file looks like Excel (.xlsx), not CSV. Upload it as .xlsx or export as CSV."
                    )
                )
            )
        if _is_ole_head(raw):
            raise ValueError(
                str(
                    _(
                        "This file looks like Excel (.xls), not CSV. Upload it as .xls or export as CSV."
                    )
                )
            )
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(str(_("The CSV file must be UTF-8 encoded."))) from exc
        return

    if _is_zip_head(raw):
        raise ValueError(
            str(
                _(
                    "Content looks like an Excel .xlsx file. Use a ``.xlsx`` filename, or export as CSV."
                )
            )
        )
    if _is_ole_head(raw):
        raise ValueError(
            str(
                _(
                    "Content looks like an Excel .xls file. Use a ``.xls`` filename, or export as CSV."
                )
            )
        )
    if _looks_like_json_start(raw):
        return

    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(str(_("The file must be UTF-8 encoded text (CSV)."))) from exc


def validate_configuration_json_payload(payload: Any) -> None:
    """
    Structural checks for JSON produced by *Export / Import configuration (JSON)*.

    Does not replace ``django.core.serializers`` validation; narrows surface for random uploads.
    """
    if not isinstance(payload, dict):
        raise ValueError(str(_("Configuration JSON must be a JSON object.")))
    if "objects" not in payload:
        raise ValueError(str(_("Configuration JSON must contain an ``objects`` array.")))
    objects = payload["objects"]
    if not isinstance(objects, list):
        raise ValueError(str(_("``objects`` must be a JSON array.")))
    fmt = payload.get("format_version")
    if fmt is not None and not isinstance(fmt, int):
        raise ValueError(str(_("``format_version``, if present, must be an integer.")))
    for i, obj in enumerate(objects):
        if not isinstance(obj, dict):
            raise ValueError(str(_("``objects[%(i)s]`` must be an object.") % {"i": i}))
        if "model" not in obj:
            raise ValueError(str(_("``objects[%(i)s]`` must include a ``model`` key.") % {"i": i}))
        if not isinstance(obj.get("model"), str):
            raise ValueError(str(_("``objects[%(i)s].model`` must be a string.") % {"i": i}))
        fields = obj.get("fields")
        if fields is not None and not isinstance(fields, dict):
            raise ValueError(str(_("``objects[%(i)s].fields`` must be an object.") % {"i": i}))
