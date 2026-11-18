"""Write a table export (CSV / Excel / JSON) using :func:`django_importexport_flow.utils.process.process_export`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from django_importexport_flow.engine.core.formats import enabled_format_keys
from django_importexport_flow.models import Definition
from django_importexport_flow.utils.process import process_export
from django_importexport_flow.utils.recoverable_errors import TABULAR_ENGINE_RECOVERABLE

from ._filter_cli import load_filter_payload_dict

_RECOVERABLE_EXPORT_ERRORS: tuple[type[BaseException], ...] = TABULAR_ENGINE_RECOVERABLE + (
    Definition.DoesNotExist,
)


def _filter_payload_from_options(options: dict[str, Any]) -> dict[str, Any]:
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
    return payload


def _configuration_overrides_from_options(options: dict[str, Any]) -> dict[str, Any]:
    overrides_json = options["configuration_overrides"]
    overrides_file = options["configuration_overrides_file"]
    if overrides_file and overrides_json is not None and str(overrides_json).strip():
        raise CommandError(
            "Use only one of --configuration-overrides and --configuration-overrides-file."
        )
    try:
        return _load_configuration_overrides(overrides_json, overrides_file)
    except (json.JSONDecodeError, OSError, CommandError) as exc:
        raise CommandError(str(exc)) from exc


def _export_output_path(
    options: dict[str, Any],
    definition_id: str,
    export_format: str,
    ext: str,
) -> Path:
    out = options["output"]
    if not out:
        short = str(definition_id).replace("-", "")[:8]
        out = f"export_{short}_{export_format}{ext}"
    return Path(out)


def _load_configuration_overrides(raw_json: str | None, raw_file: str | None) -> dict[str, Any]:
    if raw_file:
        raw = Path(raw_file).read_text(encoding="utf-8")
    elif raw_json is not None and str(raw_json).strip():
        raw = str(raw_json)
    else:
        return {}
    parsed = json.loads(raw) if raw.strip() else {}
    if not isinstance(parsed, dict):
        raise CommandError("Configuration overrides must be a JSON object.")
    return parsed


class Command(BaseCommand):
    help = (
        "Process a table export for an ExportDefinition. "
        "Use --filter-json or --filter-json-file for fr_get_* / fr_kw_* and optional "
        "mg_get_* / mg_kw_* keys (same as the admin form)."
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
            choices=enabled_format_keys(),
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
            help="JSON object with export_format, fr_get_*, fr_kw_*, optional mg_get_*, mg_kw_*.",
        )
        parser.add_argument(
            "--filter-json-file",
            dest="filter_json_file",
            default=None,
            help="Path to a UTF-8 JSON file with the same keys as --filter-json.",
        )
        parser.add_argument(
            "--template-override",
            dest="template_override",
            default="",
            help="PDF template for this export. Empty uses the template stored on the format.",
        )
        parser.add_argument(
            "--configuration-overrides",
            dest="configuration_overrides",
            default=None,
            help='JSON object {"format": {...}, "hook": {...}} for this export only.',
        )
        parser.add_argument(
            "--configuration-overrides-file",
            dest="configuration_overrides_file",
            default=None,
            help="UTF-8 JSON file with the same object as --configuration-overrides.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        definition_id = options["definition"]
        payload = _filter_payload_from_options(options)
        overrides = _configuration_overrides_from_options(options)
        try:
            body, _content_type, ext = process_export(
                export_definition_key=definition_id,
                filter_payload=payload,
                template_override=options["template_override"] or "",
                configuration_overrides=overrides,
            )
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        except MemoryError as exc:
            raise CommandError("Not enough memory to complete the export.") from exc
        except _RECOVERABLE_EXPORT_ERRORS as exc:
            raise CommandError(str(exc)) from exc

        path = _export_output_path(options, definition_id, payload["export_format"], ext)
        path.write_bytes(body)
        self.stdout.write(self.style.SUCCESS(f"Wrote {len(body)} bytes to {path.resolve()}"))
