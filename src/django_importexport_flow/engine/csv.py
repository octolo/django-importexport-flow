"""Tabular export to CSV (:meth:`~django_importexport_flow.engine.core.table.TableEngine.get_csv`)."""

from __future__ import annotations

from .core.table import ExportTableEngine, TableEngine

CsvTableEngine = TableEngine

__all__ = ["CsvTableEngine", "ExportTableEngine", "TableEngine"]
