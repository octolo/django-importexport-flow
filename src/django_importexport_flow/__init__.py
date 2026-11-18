"""
django-importexport-flow package.

``serialize_report_import`` / ``import_report_import`` are aliases of
``serialize_import_definition`` / ``import_import_definition`` (legacy names).
See ``docs/purpose.md`` (Legacy naming).
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("django-importexport-flow")
except PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = [
    "CategoryConfig",
    "ColumnTranslation",
    "Definition",
    "ExportCategoryConfig",
    "ExportCsvFormat",
    "ExportDefinition",
    "ExportDocumentConfig",
    "ExportExcelFormat",
    "ExportFormatConfig",
    "ExportJsonFormat",
    "ExportManager",
    "ExportPdfFormat",
    "ExportRequest",
    "ExportSpreadsheetConfig",
    "ExportStructuredDataConfig",
    "FormatConfig",
    "ImportCategoryConfig",
    "ImportCsvFormat",
    "ImportDefinition",
    "ImportExcelFormat",
    "ImportFormatConfig",
    "ImportRequest",
    "ImportSpreadsheetConfig",
    "ImportStructuredDataConfig",
    "__version__",
    "get_export_category",
    "get_export_config",
    "get_export_definitions",
    "get_import_category",
    "get_import_config",
    "import_import_definition",
    "import_report_import",
    "serialize_export_configuration",
    "serialize_import_definition",
    "serialize_report_import",
]


def _load_export_manager():
    from .managers import ExportManager

    return ExportManager


def _load_serialization(attr: str):
    from .utils import serialization

    return getattr(serialization, attr)


def _load_export_definitions():
    from .utils.helpers import get_export_definitions

    return get_export_definitions


def _load_model(attr: str):
    from . import models

    return getattr(models, attr)


def _load_format_helper(attr: str):
    from .engine.core import formats

    return getattr(formats, attr)


_LAZY_EXPORTS = {
    "ExportManager": _load_export_manager,
    "serialize_export_configuration": lambda: _load_serialization("serialize_export_configuration"),
    "serialize_import_definition": lambda: _load_serialization("serialize_import_definition"),
    "import_import_definition": lambda: _load_serialization("import_import_definition"),
    "serialize_report_import": lambda: _load_serialization("serialize_report_import"),
    "import_report_import": lambda: _load_serialization("import_report_import"),
    "get_export_definitions": _load_export_definitions,
    "ImportRequest": lambda: _load_model("ImportRequest"),
    "ExportRequest": lambda: _load_model("ExportRequest"),
}

_MODEL_EXPORTS = {
    "Definition",
    "ExportDefinition",
    "ImportDefinition",
    "CategoryConfig",
    "ExportCategoryConfig",
    "ImportCategoryConfig",
    "ExportSpreadsheetConfig",
    "ExportDocumentConfig",
    "ExportStructuredDataConfig",
    "ImportSpreadsheetConfig",
    "ImportStructuredDataConfig",
    "FormatConfig",
    "ExportFormatConfig",
    "ImportFormatConfig",
    "ExportCsvFormat",
    "ExportExcelFormat",
    "ExportJsonFormat",
    "ExportPdfFormat",
    "ImportCsvFormat",
    "ImportExcelFormat",
    "ColumnTranslation",
}

_FORMAT_EXPORTS = {
    "get_export_category",
    "get_export_config",
    "get_import_category",
    "get_import_config",
}


def __getattr__(name: str):
    if name in _MODEL_EXPORTS:
        return _load_model(name)
    if name in _FORMAT_EXPORTS:
        return _load_format_helper(name)
    loader = _LAZY_EXPORTS.get(name)
    if loader is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return loader()
