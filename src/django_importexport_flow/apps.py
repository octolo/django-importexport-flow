from __future__ import annotations

from typing import Any, ClassVar

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class DjangoImportExportFlowConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "django_importexport_flow"
    verbose_name = _("Django import export flow")

    #: Defaults for :func:`~django_importexport_flow.utils.helpers.get_setting`.
    #: Override via ``settings.DJANGO_IMPORTEXPORT_FLOW`` (dict) or
    #: ``DJANGO_IMPORTEXPORT_FLOW_<NAME>`` attributes.
    default_settings: ClassVar[dict[str, Any]] = {
        "IMPORT_COLUMN_PATHS_KEY": "_django_importexport_flow_import_column_paths",
        "DEFAULT_M2M_IMPORT_SLOTS": 2,
        "DEFAULT_IMPORT_MAX_RELATION_HOPS": 100,
        "MAX_IMPORT_BYTES": 2 * 1024 * 1024,
        "MAX_TABULAR_IMPORT_BYTES": 10 * 1024 * 1024,
        "TABULAR_IMPORT_BATCH_SIZE": 500,
        "IMPORT_TASK_BACKEND": "sync",
        "IMPORT_ADMIN_OFFER_ASYNC": True,
        "IMPORT_ADMIN_ASYNC_DEFAULT": False,
        "EXPORT_ADMIN_OFFER_ASYNC": True,
        "EXPORT_ADMIN_ASYNC_DEFAULT": False,
        "IMPORT_PREVIEW_ROW_LIMIT": 30,
        "SERIALIZATION_FORMAT_VERSION": 2,
        # Dotted path to a Django storage class. None uses Django's default storage.
        # Example: "storages.backends.s3boto3.S3Boto3Storage"
        "EXPORT_OUTPUT_STORAGE": None,
        "IMPORT_FILE_STORAGE": None,
        # Path template containing "/" or "%", or a dotted callable(instance, filename).
        # None keeps the built-in dated directory.
        "EXPORT_OUTPUT_UPLOAD_TO": None,
        "IMPORT_FILE_UPLOAD_TO": None,
        # When False, a synchronous import keeps the upload in memory and leaves
        # ImportRequest.data_file empty. Leave this enabled for the admin wizard,
        # relaunch, and async workers.
        "PERSIST_IMPORT_REQUEST_FILES": True,
        # When False, a synchronous export keeps the generated file in memory and
        # leaves ExportRequest.output_file empty.
        "PERSIST_EXPORT_REQUEST_FILES": True,
        # Prefix spreadsheet text so Excel and CSV clients do not execute formulas.
        "ESCAPE_SPREADSHEET_FORMULAS": True,
        # None allows every importable hook. An empty list allows native hooks only.
        "ALLOWED_HOOK_MODULE_PREFIXES": None,
        "MAX_XLSX_ARCHIVE_MEMBERS": 1000,
        "MAX_XLSX_UNCOMPRESSED_BYTES": 50 * 1024 * 1024,
        "MAX_XLSX_COMPRESSION_RATIO": 100,
    }
