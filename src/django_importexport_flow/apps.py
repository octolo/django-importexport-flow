from __future__ import annotations

from typing import Any

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class DjangoImportExportFlowConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "django_importexport_flow"
    verbose_name = _("Django import export flow")

    #: Defaults for :func:`~django_importexport_flow.utils.helpers.get_setting`.
    #: Override via ``settings.DJANGO_IMPORTEXPORT_FLOW`` (dict) or
    #: ``DJANGO_IMPORTEXPORT_FLOW_<NAME>`` attributes.
    default_settings: dict[str, Any] = {
        "IMPORT_COLUMN_PATHS_KEY": "_django_importexport_flow_import_column_paths",
        "DEFAULT_M2M_IMPORT_SLOTS": 2,
        "DEFAULT_IMPORT_MAX_RELATION_HOPS": 100,
        "MAX_IMPORT_BYTES": 2 * 1024 * 1024,
        "MAX_TABULAR_IMPORT_BYTES": 10 * 1024 * 1024,
        "TABULAR_IMPORT_BATCH_SIZE": 500,
        "IMPORT_TASK_BACKEND": "sync",
        "IMPORT_ADMIN_OFFER_ASYNC": True,
        "IMPORT_ADMIN_ASYNC_DEFAULT": False,
        "IMPORT_PREVIEW_ROW_LIMIT": 30,
        "SERIALIZATION_FORMAT_VERSION": 1,
    }

    #: Tabular export formats: ``export_format`` value → ``(TableEngine method, content-type, file extension)``.
    #: Used by :func:`django_importexport_flow.utils.process.process_export` / :func:`django_importexport_flow.engine.core.export.run_table_export`.
    export_format_dispatch: dict[str, tuple[str, str, str]] = {
        "csv": ("get_csv", "text/csv; charset=utf-8", ".csv"),
        "excel": (
            "get_excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".xlsx",
        ),
        "json": ("get_json_bytes", "application/json; charset=utf-8", ".json"),
    }
