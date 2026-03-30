"""Write an empty example import file (CSV / Excel / JSON) for an ImportDefinition."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from django_importexport_flow.models import ImportDefinition
from django_importexport_flow.utils.lookup import get_import_definition_by_uuid_or_named_id
from django_importexport_flow.utils.process import generate_example_file
from django_importexport_flow.utils.recoverable_errors import TABULAR_ENGINE_RECOVERABLE


class Command(BaseCommand):
    help = (
        "Generate an example tabular import template (header row + blank data row) "
        "for an ImportDefinition (UUID or named_id)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "definition",
            type=str,
            help="ImportDefinition UUID or named_id slug.",
        )
        parser.add_argument(
            "-f",
            "--format",
            choices=["csv", "excel", "json"],
            default="csv",
            help="Output format (default: csv).",
        )
        parser.add_argument(
            "-o",
            "--output",
            dest="output",
            default=None,
            help=(
                "Output file path. If omitted, writes example_<first8>_<format><ext> "
                "in the current directory."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        definition_id = options["definition"]
        fmt = options["format"]

        try:
            definition = get_import_definition_by_uuid_or_named_id(definition_id)
        except (ValueError, ImportDefinition.DoesNotExist) as exc:
            raise CommandError(str(exc)) from exc

        try:
            body, _content_type, ext = generate_example_file(
                definition,
                example_format=fmt,
            )
        except MemoryError as exc:
            raise CommandError("Not enough memory to build the example file.") from exc
        except ImportError as exc:
            raise CommandError(str(exc)) from exc
        except TABULAR_ENGINE_RECOVERABLE as exc:
            raise CommandError(str(exc)) from exc

        out = options["output"]
        if not out:
            short = str(definition_id).replace("-", "")[:8]
            out = f"example_{short}_{fmt}{ext}"

        path = Path(out)
        path.write_bytes(body)
        self.stdout.write(self.style.SUCCESS(f"Wrote {len(body)} bytes to {path.resolve()}"))
