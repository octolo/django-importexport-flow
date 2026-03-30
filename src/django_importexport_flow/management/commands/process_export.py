"""Write a table export (CSV / Excel / JSON) using :func:`django_importexport_flow.utils.process.process_export`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from django_importexport_flow.models import ExportDefinition
from django_importexport_flow.utils.process import process_export
from django_importexport_flow.utils.recoverable_errors import TABULAR_ENGINE_RECOVERABLE

from ._filter_cli import load_filter_payload_dict

_RECOVERABLE_EXPORT_ERRORS: tuple[type[BaseException], ...] = TABULAR_ENGINE_RECOVERABLE + (
    ExportDefinition.DoesNotExist,
)


class Command(BaseCommand):
    help = (
        "Process a table export for an ExportDefinition. "
        "Use --filter-json or --filter-json-file for fr_get_* / fr_kw_* keys (same as the admin form)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "definition",
            type=str,
            help="ExportDefinition UUID or named_id slug.",
        )
        parser.add_argument(
            "-f",
            "--format",
            choices=["csv", "excel", "json"],
            default=None,
            help="Output format. Overrides export_format in the filter JSON when set.",
        )
        parser.add_argument(
            "-o",
            "--output",
            dest="output",
            default=None,
            help="Output file path. If omitted, writes export_<first8>_<format><ext> in the current directory.",
        )
        parser.add_argument(
            "--filter-json",
            dest="filter_json",
            default=None,
            help="JSON object with filter keys (export_format, fr_get_*, fr_kw_*).",
        )
        parser.add_argument(
            "--filter-json-file",
            dest="filter_json_file",
            default=None,
            help="Path to a UTF-8 JSON file with the same keys as --filter-json.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        definition_id = options["definition"]
        filter_json = options["filter_json"]
        filter_json_file = options["filter_json_file"]
        if filter_json_file and filter_json is not None and str(filter_json).strip():
            raise CommandError("Use only one of --filter-json and --filter-json-file.")

        try:
            payload = load_filter_payload_dict(
                filter_json=filter_json,
                filter_json_file=filter_json_file,
            )
        except (json.JSONDecodeError, OSError) as exc:
            raise CommandError(str(exc)) from exc

        if not isinstance(payload, dict):
            raise CommandError("Filter JSON must be a JSON object.")

        fmt = options["format"]
        if fmt:
            payload["export_format"] = fmt
        elif "export_format" not in payload:
            raise CommandError(
                "export_format is required: pass -f/--format or include it in --filter-json."
            )

        try:
            body, _content_type, ext = process_export(
                export_definition_key=definition_id,
                filter_payload=payload,
            )
        except MemoryError as exc:
            raise CommandError("Not enough memory to complete the export.") from exc
        except _RECOVERABLE_EXPORT_ERRORS as exc:
            raise CommandError(str(exc)) from exc

        out = options["output"]
        if not out:
            short = str(definition_id).replace("-", "")[:8]
            out = f"export_{short}_{payload['export_format']}{ext}"

        path = Path(out)
        path.write_bytes(body)
        self.stdout.write(self.style.SUCCESS(f"Wrote {len(body)} bytes to {path.resolve()}"))
