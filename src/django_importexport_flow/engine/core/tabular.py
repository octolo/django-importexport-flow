"""Load tabular import files into a :class:`pandas.DataFrame` (CSV and Excel only)."""

from __future__ import annotations

from io import BytesIO

import pandas as pd
from django.utils.translation import gettext_lazy as _

from ...utils.upload_validation import validate_tabular_upload_bytes

_EXCEL_SUFFIXES = (".xlsx", ".xls")


def _looks_like_json_payload(raw: bytes) -> bool:
    if not raw:
        return False
    first = raw.lstrip()[:1]
    return first in (b"[", b"{")


def read_tabular_dataframe_from_bytes(raw: bytes, name: str, max_bytes: int) -> pd.DataFrame:
    """
    Parse **CSV** (UTF-8) or **Excel** (``.xlsx`` / ``.xls``) bytes into a dataframe.

    JSON (``.json`` or content that looks like JSON) is not supported for tabular import.
    """
    if len(raw) > max_bytes:
        raise ValueError(_("File is too large."))
    validate_tabular_upload_bytes(raw, name)
    lowered = (name or "").lower()

    if lowered.endswith(".json"):
        raise ValueError(_("JSON import is not supported yet; use CSV or Excel."))

    buf = BytesIO(raw)
    if lowered.endswith(_EXCEL_SUFFIXES):
        return pd.read_excel(buf)

    if _looks_like_json_payload(raw):
        raise ValueError(_("JSON import is not supported yet; use CSV or Excel."))

    try:
        return pd.read_csv(BytesIO(raw), encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(_("The CSV file must be UTF-8 encoded.")) from exc
