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


@dataclass
class ImportTemplateDataset:
    """Canonical columns and localized labels, before a template is rendered."""

    columns: list[str]
    labels: list[str]

    def validate(self) -> None:
        """Reject malformed hook results before rendering or combining them."""
        self._validate_columns()
        self._validate_labels()
        if len({column.strip() for column in self.columns}) != len(self.columns):
            raise ValueError("Template column keys must be unique.")

    def _validate_columns(self) -> None:
        if not isinstance(self.columns, list) or not all(
            isinstance(column, str) and column.strip() for column in self.columns
        ):
            raise ValueError("Template columns must be a list of non-empty strings.")

    def _validate_labels(self) -> None:
        if (
            not isinstance(self.labels, list)
            or len(self.labels) != len(self.columns)
            or not all(isinstance(label, str) for label in self.labels)
        ):
            raise ValueError("Template labels must provide one string per template column.")
