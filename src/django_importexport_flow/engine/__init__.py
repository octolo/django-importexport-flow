"""Export engines at package root: CSV / Excel / JSON (tabular), PDF; shared :class:`CoreEngine` in :mod:`django_importexport_flow.engine.core`.

Imports are **lazy** so submodules like :mod:`django_importexport_flow.engine.core.validation` can load
without pulling :class:`TableEngine` (avoids circular imports with ``models``).

**Import** pipeline: :mod:`django_importexport_flow.engine.core.import_`. CSV/Excel bytes → DataFrame:
:func:`read_tabular_dataframe_from_bytes` in :mod:`django_importexport_flow.engine.core.tabular`.
"""

from __future__ import annotations

__all__ = [
    "CoreEngine",
    "ExportPdfEngine",
    "ExportTableEngine",
    "PdfEngine",
    "TableEngine",
    "read_tabular_dataframe_from_bytes",
]


def __getattr__(name: str):
    if name == "CoreEngine":
        from .core import CoreEngine

        return CoreEngine
    if name == "PdfEngine":
        from .pdf import PdfEngine

        return PdfEngine
    if name == "ExportPdfEngine":
        from .pdf import PdfEngine

        return PdfEngine
    if name == "TableEngine":
        from .core.table import TableEngine

        return TableEngine
    if name == "ExportTableEngine":
        from .core.table import TableEngine

        return TableEngine
    if name == "read_tabular_dataframe_from_bytes":
        from .core.tabular import read_tabular_dataframe_from_bytes

        return read_tabular_dataframe_from_bytes
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(__all__)
