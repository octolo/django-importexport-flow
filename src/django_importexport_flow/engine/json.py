"""Tabular export to JSON (:meth:`~django_importexport_flow.engine.core.table.TableEngine.get_json` / ``get_json_bytes``)."""

from __future__ import annotations

from .core.table import ExportTableEngine, TableEngine

JsonTableEngine = TableEngine

__all__ = ["ExportTableEngine", "JsonTableEngine", "TableEngine"]
