"""Shared engine internals: queryset, validation, tabular I/O, import/export pipeline.

Submodules (single responsibility):

- :mod:`django_importexport_flow.engine.core.engine` — ``CoreEngine``: queryset, filters, ``order_by``.
- :mod:`django_importexport_flow.engine.core.validation` — column specs, filter maps, manager paths.
- :mod:`django_importexport_flow.engine.core.table` — ``TableEngine``: tabular export (CSV/Excel/JSON).
- :mod:`django_importexport_flow.engine.core.pdf` — ``PdfEngine`` (HTML → PDF).
- :mod:`django_importexport_flow.engine.core.export` — export HTTP/filter helpers, ``run_table_export``.
- :mod:`django_importexport_flow.engine.core.filters` — filter payload keys for forms and CLI.
- :mod:`django_importexport_flow.engine.core.tabular` — CSV/Excel bytes → :class:`pandas.DataFrame`.
- :mod:`django_importexport_flow.engine.core.import_` — re-exports the import pipeline; implementation in
  ``paths``, ``io``, ``preview``, ``items``, ``run``.

The ``CoreEngine`` name is lazy-loaded via :func:`__getattr__` so importing validation alone does not pull
the full table stack.
"""

from __future__ import annotations

__all__ = ["CoreEngine"]


def __getattr__(name: str):
    if name == "CoreEngine":
        from .engine import CoreEngine

        return CoreEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(__all__)
