"""Bytes and upload objects → tabular DataFrame."""

from __future__ import annotations

from typing import Any

import pandas as pd
from django.db import models

from .tabular import read_tabular_dataframe_from_bytes


def read_import_bytes(raw: bytes, name: str, max_bytes: int) -> pd.DataFrame:
    return read_tabular_dataframe_from_bytes(raw, name, max_bytes)


def read_uploaded_file(uploaded_file: Any, max_bytes: int) -> pd.DataFrame:
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    raw = uploaded_file.read()
    name = getattr(uploaded_file, "name", "") or ""
    return read_import_bytes(raw, name, max_bytes)


def read_import_filefield(file_field: models.FileField, max_bytes: int) -> pd.DataFrame:
    with file_field.open("rb") as f:
        raw = f.read()
    name = getattr(file_field, "name", "") or ""
    return read_import_bytes(raw, name, max_bytes)
