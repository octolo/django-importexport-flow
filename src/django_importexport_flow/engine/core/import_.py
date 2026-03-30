"""
Public import pipeline for :class:`~django_importexport_flow.models.ImportDefinition`.

Implementation: :mod:`~django_importexport_flow.engine.core.paths` (field paths / header mapping),
:mod:`~django_importexport_flow.engine.core.io`, :mod:`~django_importexport_flow.engine.core.preview`,
:mod:`~django_importexport_flow.engine.core.items` (per-record construction), :mod:`~django_importexport_flow.engine.core.run`.

The package name ``import_`` avoids the ``import`` keyword.

**Legacy aliases** (same callables; prefer the primary name in new code):
``sample_headers_for_report_import`` → ``sample_headers_for_import_definition``;
``create_import_ask`` → ``create_import_request``;
``relaunch_import_ask`` → ``relaunch_import_request``;
``run_tabular_import_for_ask`` / ``run_tabular_import_for_request`` → ``run_import_request``;
``read_tabular_*`` / ``normalize_tabular_*`` mirror ``read_import_*`` / ``normalize_import_*``.
See ``docs/purpose.md`` (Legacy naming).
"""

from __future__ import annotations

from ...utils.helpers import dataframe_preview_table  # noqa: F401

from .io import (
    read_import_bytes,
    read_import_filefield,
    read_uploaded_file,
)
from .paths import (
    DEFAULT_IMPORT_MAX_RELATION_HOPS,
    DEFAULT_M2M_IMPORT_SLOTS,
    IMPORT_COLUMN_PATHS_KEY,
    default_importable_column_paths,
    effective_import_column_paths,
    infer_column_paths_from_headers,
    resolve_import_column_paths,
    sample_headers_for_import_definition,
)
from .preview import (
    normalize_import_dataframe,
    validate_import_preview,
)
from ...task import dispatch_import_request
from .run import (
    create_import_request,
    relaunch_import_request,
    run_import_request,
)

sample_headers_for_report_import = sample_headers_for_import_definition
create_import_ask = create_import_request
relaunch_import_ask = relaunch_import_request
run_tabular_import_for_ask = run_import_request
run_tabular_import_for_request = run_import_request
read_tabular_from_bytes = read_import_bytes
read_uploaded_tabular = read_uploaded_file
read_tabular_from_storage_filefield = read_import_filefield
normalize_tabular_import_dataframe = normalize_import_dataframe

__all__ = [
    "DEFAULT_IMPORT_MAX_RELATION_HOPS",
    "DEFAULT_M2M_IMPORT_SLOTS",
    "IMPORT_COLUMN_PATHS_KEY",
    "dispatch_import_request",
    "create_import_ask",
    "create_import_request",
    "dataframe_preview_table",
    "default_importable_column_paths",
    "effective_import_column_paths",
    "infer_column_paths_from_headers",
    "normalize_import_dataframe",
    "normalize_tabular_import_dataframe",
    "read_import_bytes",
    "read_import_filefield",
    "read_uploaded_file",
    "read_tabular_from_bytes",
    "read_tabular_from_storage_filefield",
    "read_uploaded_tabular",
    "relaunch_import_ask",
    "relaunch_import_request",
    "resolve_import_column_paths",
    "run_import_request",
    "run_tabular_import_for_ask",
    "run_tabular_import_for_request",
    "sample_headers_for_import_definition",
    "sample_headers_for_report_import",
    "validate_import_preview",
]
