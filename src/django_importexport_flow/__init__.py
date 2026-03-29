"""django-importexport-flow package."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("django-importexport-flow")
except PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = [
    "ExportConfigPdf",
    "ExportConfigTable",
    "ExportDefinition",
    "ImportDefinition",
    "ImportRequest",
    "ExportRequest",
    "ExportManager",
    "__version__",
    "get_export_definitions",
    "serialize_export_configuration",
    "serialize_import_definition",
    "import_import_definition",
    "serialize_report_import",
    "import_report_import",
]


def __getattr__(name: str):
    if name == "ExportManager":
        from .managers import ExportManager

        return ExportManager
    if name == "serialize_export_configuration":
        from .utils.serialization import serialize_export_configuration

        return serialize_export_configuration
    if name == "serialize_import_definition":
        from .utils.serialization import serialize_import_definition

        return serialize_import_definition
    if name == "import_import_definition":
        from .utils.serialization import import_import_definition

        return import_import_definition
    if name == "serialize_report_import":
        from .utils.serialization import serialize_report_import

        return serialize_report_import
    if name == "import_report_import":
        from .utils.serialization import import_report_import

        return import_report_import
    if name == "get_export_definitions":
        from .utils import get_export_definitions

        return get_export_definitions
    if name == "ExportDefinition":
        from .models import ExportDefinition

        return ExportDefinition
    if name == "ExportConfigPdf":
        from .models import ExportConfigPdf

        return ExportConfigPdf
    if name == "ExportConfigTable":
        from .models import ExportConfigTable

        return ExportConfigTable
    if name == "ImportDefinition":
        from .models import ImportDefinition

        return ImportDefinition
    if name == "ImportRequest":
        from .models import ImportRequest

        return ImportRequest
    if name == "ExportRequest":
        from .models import ExportRequest

        return ExportRequest
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
