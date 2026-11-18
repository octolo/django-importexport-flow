"""Neutral datasets exchanged between the shared trunks and the format hooks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExportDataset:
    """Rows already loaded for one export, before a format hook writes the file."""

    definition: Any
    queryset: Any
    columns: list[Any]
    labels: list[str]
    category_config: Any
    format_config: Any
    payload: dict[str, Any]
    engine: Any = None

    def document_context(self) -> dict[str, Any]:
        return {"object_list": self.queryset}


@dataclass
class ImportDataset:
    """Decoded file contents, before the shared import trunk validates and writes rows."""

    dataframe: Any
    headers: list[str]
    format_key: str
    metadata: dict[str, Any] = field(default_factory=dict)
