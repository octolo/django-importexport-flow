"""Django admin registration for django-importexport-flow."""

from __future__ import annotations

# Load modules so @admin.register runs.
from . import export_definition  # noqa: F401
from . import import_definition  # noqa: F401
from . import import_request  # noqa: F401
from . import export_request  # noqa: F401

from .export_definition import (
    ExportConfigPdfInline,
    ExportConfigTableInline,
    ExportDefinitionAdmin,
)
from .import_definition import ImportDefinitionAdmin

__all__ = [
    "ExportConfigPdfInline",
    "ExportConfigTableInline",
    "ExportDefinitionAdmin",
    "ImportDefinitionAdmin",
]
