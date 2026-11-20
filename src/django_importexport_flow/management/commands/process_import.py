"""Process or preview a tabular import using :func:`django_importexport_flow.utils.process.process_import`."""

from __future__ import annotations

import json
import sys
from io import BytesIO
from pathlib import Path
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from django_importexport_flow.forms import MAX_TABULAR_IMPORT_BYTES
from django_importexport_flow.models import Definition
from django_importexport_flow.utils.process import process_import, validate_import
from django_importexport_flow.utils.recoverable_errors import TABULAR_ENGINE_RECOVERABLE

from ._filter_cli import load_filter_payload_dict

# Expected failures for CLI: translate to CommandError; everything else propagates (use --traceback).
_RECOVERABLE_IMPORT_ERRORS: tuple[type[BaseException], ...] = TABULAR_ENGINE_RECOVERABLE + (
    Definition.DoesNotExist,
)


def _upload_buffer_from_path(path_str: str, max_bytes: int | None) -> BytesIO:
    """
    Read the import file once into memory (respecting size limit) for reuse after ``--validate``.
    Sets ``name`` on the buffer so format detection (CSV vs Excel) matches a path upload.
    """
    limit = max_bytes if max_bytes is not None else MAX_TABULAR_IMPORT_BYTES
    path = Path(path_str)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise CommandError(str(exc)) from exc
    if size > limit:
        raise CommandError(f"File size ({size} bytes) exceeds max_bytes limit ({limit}).")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CommandError(str(exc)) from exc
    if len(raw) > limit:
        raise CommandError(f"File size ({len(raw)} bytes) exceeds max_bytes limit ({limit}).")
    buf = BytesIO(raw)
    buf.name = str(path)
    return buf


def _filter_payload_from_options(options: dict[str, Any]) -> dict[str, Any]:
    if options["validate"] and options["preview"]:
        raise CommandError("Use either --preview or --validate, not both.")

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
    return payload


def _initiated_by_user(username: str | None, *, preview: bool):
    if not username or preview:
        return None
    User = get_user_model()
    user = User.objects.filter(username=username).first()
    if user is None:
        raise CommandError(f"No user with username {username!r}.")
    return user


def _call_import(operation, *, memory_message: str):
    try:
        return operation()
    except CommandError:
        raise
    except MemoryError as exc:
        raise CommandError(memory_message) from exc
    except _RECOVERABLE_IMPORT_ERRORS as exc:
        raise CommandError(str(exc)) from exc


class Command(BaseCommand):
    help = (
        "Validate and process a tabular import for an ImportDefinition, or --preview only. "
        "Use --filter-json / --filter-json-file for fr_get_* / fr_kw_* (same as the admin wizard). "
        "With --validate, run a full validation pass first and prompt y/n before importing."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "definition",
            type=str,
            help="ImportDefinition UUID or named_id slug.",
        )
        parser.add_argument(
            "file",
            type=str,
            help="Path to a CSV or Excel file.",
        )
        parser.add_argument(
            "--preview",
            action="store_true",
            help="Read and validate the file only; do not create an ImportRequest or write to the DB.",
        )
        parser.add_argument(
            "--validate",
            action="store_true",
            help=(
                "Before importing: run validate_import, show errors/warnings and a data summary, "
                "then prompt for y/N to continue (requires an interactive terminal; not with --preview)."
            ),
        )
        parser.add_argument(
            "--max-bytes",
            type=int,
            default=None,
            help="Max file size in bytes (default: MAX_TABULAR_IMPORT_BYTES from settings).",
        )
        parser.add_argument(
            "--username",
            default=None,
            help="If set, record this user as initiated_by on the ImportRequest (ignored with --preview).",
        )
        parser.add_argument(
            "--column",
            action="append",
            dest="columns",
            default=None,
            metavar="PATH",
            help="Inferred import column path (repeatable). Passed as inferred_column_paths.",
        )
        parser.add_argument(
            "--filter-json",
            dest="filter_json",
            default=None,
            help="JSON object with filter keys (fr_get_*, fr_kw_*).",
        )
        parser.add_argument(
            "--filter-json-file",
            dest="filter_json_file",
            default=None,
            help="Path to a UTF-8 JSON file with the same keys as --filter-json.",
        )
        parser.add_argument(
            "--async",
            action="store_true",
            dest="run_async",
            help=(
                "After creating the ImportRequest, enqueue processing via IMPORT_TASK_BACKEND "
                "(ignored when backend is sync)."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        payload = _filter_payload_from_options(options)
        user = _initiated_by_user(options["username"], preview=bool(options["preview"]))
        path = options["file"]
        cols = options["columns"]
        inferred = list(cols) if cols else None
        max_bytes = options["max_bytes"]
        definition_key = options["definition"]
        run_async = bool(options.get("run_async"))

        if options["validate"]:
            self._import_after_prompt(
                path=path,
                max_bytes=max_bytes,
                definition_key=definition_key,
                user=user,
                payload=payload,
                inferred=inferred,
                run_async=run_async,
            )
            return

        def _run_from_path():
            with open(path, "rb") as upload:
                return process_import(
                    file=upload,
                    import_definition_key=definition_key,
                    user=user,
                    filter_payload=payload,
                    inferred_column_paths=inferred,
                    preview_only=bool(options["preview"]),
                    max_bytes=max_bytes,
                    run_async=run_async,
                )

        result = _call_import(
            _run_from_path,
            memory_message="Not enough memory to complete the import.",
        )
        if options["preview"]:
            self._print_import_validation(result)
            return
        self._write_import_request_outcome(result)

    def _import_after_prompt(
        self,
        *,
        path: str,
        max_bytes: int | None,
        definition_key: str,
        user: Any,
        payload: dict[str, Any],
        inferred: list[str] | None,
        run_async: bool,
    ) -> None:
        if not sys.stdin.isatty():
            raise CommandError("--validate requires an interactive terminal (stdin must be a TTY).")

        def _validate():
            upload_buf = _upload_buffer_from_path(path, max_bytes)
            report = validate_import(
                file=upload_buf,
                import_definition_key=definition_key,
                max_bytes=max_bytes,
                user=user,
                filter_payload=payload,
            )
            return upload_buf, report

        upload_buf, report = _call_import(
            _validate,
            memory_message="Not enough memory to read or validate the import file.",
        )
        self._print_import_validation(report)
        if report.get("errors"):
            raise CommandError("Validation failed; fix errors above before importing.")
        answer = input("Continue with import? [y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            self.stdout.write("Aborted.")
            return
        upload_buf.seek(0)
        result = _call_import(
            lambda: process_import(
                file=upload_buf,
                import_definition_key=definition_key,
                user=user,
                filter_payload=payload,
                inferred_column_paths=inferred,
                preview_only=False,
                max_bytes=max_bytes,
                run_async=run_async,
            ),
            memory_message="Not enough memory to complete the import.",
        )
        self._write_import_request_outcome(result)

    def _write_import_request_outcome(self, result: dict[str, Any]) -> None:
        ask = result["import_request"]
        ok = result["success"]
        queued = result.get("queued")
        line = f"ImportRequest {ask.uuid} status={ask.status!r} success={ok}"
        if queued:
            line += " queued=True"
            self.stdout.write(self.style.WARNING(line))
            return
        self.stdout.write((self.style.SUCCESS if ok else self.style.WARNING)(line))

    def _print_import_validation(self, result: dict[str, Any]) -> None:
        """Shared output for validate_import and process_import(..., preview_only=True)."""
        self._write_import_validation_messages(result)
        self._write_import_dataframe_preview(result)

    def _write_import_validation_messages(self, result: dict[str, Any]) -> None:
        for err in result.get("errors") or []:
            self.stderr.write(self.style.ERROR(err))
        for warn in result.get("warnings") or []:
            self.stdout.write(self.style.WARNING(warn))
        ds = result.get("validation_dataset") or {}
        rc = ds.get("row_count")
        pr = ds.get("preview_row_count")
        paths = result.get("column_paths") or []
        if rc is not None:
            self.stdout.write(f"Rows (validated): {rc} (preview sample: {pr})")
        elif paths and result.get("dataframe") is not None:
            df = result["dataframe"]
            self.stdout.write(f"Rows: {len(df)}")
        if paths:
            self.stdout.write("Column paths: " + ", ".join(paths))

    def _write_import_dataframe_preview(self, result: dict[str, Any]) -> None:
        df = result.get("dataframe")
        if df is None:
            self.stdout.write("Normalized dataframe: (none — fix errors above)")
            return
        self.stdout.write(f"Columns: {list(df.columns)}")
        preview = df.head(10)
        self.stdout.write(preview.to_string())
