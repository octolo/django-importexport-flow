"""Tabular export to Excel (:meth:`~django_importexport_flow.engine.core.table.TableEngine.get_excel`)."""

from __future__ import annotations

from .core.table import ExportTableEngine, TableEngine

ExcelTableEngine = TableEngine

__all__ = ["ExcelTableEngine", "ExportTableEngine", "TableEngine"]
