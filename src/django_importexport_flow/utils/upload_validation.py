"""Content sniffing for uploads (no extra dependencies beyond Django)."""

from __future__ import annotations

import posixpath
import zipfile
from io import BytesIO
from typing import Any

from django.utils.translation import gettext_lazy as _

_ZIP_MAGIC = b"PK\x03\x04"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _is_zip_head(raw: bytes) -> bool:
    return len(raw) >= 4 and raw[:4] == _ZIP_MAGIC


def _is_ole_head(raw: bytes) -> bool:
    return len(raw) >= 8 and raw[:8] == _OLE_MAGIC


def looks_like_json_start(raw: bytes) -> bool:
    if not raw:
        return False
    first = raw.lstrip()[:1]
    return first in (b"[", b"{")


def _require_xlsx_bytes(raw: bytes) -> None:
    if not _is_zip_head(raw):
        raise ValueError(
            str(_("File content is not a valid Excel .xlsx document (expected a ZIP archive)."))
        )
    _validate_xlsx_archive(raw)


def _require_xls_bytes(raw: bytes) -> None:
    if _is_ole_head(raw):
        return
    raise ValueError(
        str(_("File content is not a valid Excel .xls document (expected OLE compound file)."))
    )


def _require_csv_bytes(raw: bytes) -> None:
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
                _("This file looks like Excel (.xls), not CSV. Upload it as .xls or export as CSV.")
            )
        )
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(str(_("The CSV file must be UTF-8 encoded."))) from exc


def _require_undeclared_tabular_bytes(raw: bytes) -> None:
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
    if looks_like_json_start(raw):
        return
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(str(_("The file must be UTF-8 encoded text (CSV)."))) from exc


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
        _require_xlsx_bytes(raw)
        return
    if lowered.endswith(".xls"):
        _require_xls_bytes(raw)
        return
    if lowered.endswith(".csv"):
        _require_csv_bytes(raw)
        return
    _require_undeclared_tabular_bytes(raw)


def _validate_xlsx_archive(raw: bytes) -> None:
    """Reject oversized, highly compressed, or path-traversing spreadsheet archives."""
    from .helpers import get_setting

    max_members = int(get_setting("MAX_XLSX_ARCHIVE_MEMBERS"))
    max_uncompressed = int(get_setting("MAX_XLSX_UNCOMPRESSED_BYTES"))
    max_ratio = int(get_setting("MAX_XLSX_COMPRESSION_RATIO"))
    try:
        archive = zipfile.ZipFile(BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise ValueError(str(_("File content is not a valid Excel .xlsx document."))) from exc
    with archive:
        _validate_xlsx_members(archive, max_members, max_uncompressed, max_ratio)


def _validate_xlsx_members(
    archive, max_members: int, max_uncompressed: int, max_ratio: int
) -> None:
    infos = archive.infolist()
    if len(infos) > max_members:
        raise ValueError(str(_("The Excel file contains too many archive entries.")))
    total = 0
    for info in infos:
        name = info.filename.replace("\\", "/")
        if posixpath.isabs(name) or ".." in posixpath.normpath(name).split("/"):
            raise ValueError(str(_("The Excel file contains an unsafe archive path.")))
        total += info.file_size
        if total > max_uncompressed:
            raise ValueError(str(_("The Excel file expands beyond the allowed size.")))
        if info.file_size > max_ratio * max(info.compress_size, 1):
            raise ValueError(str(_("The Excel file exceeds the allowed compression ratio.")))


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
