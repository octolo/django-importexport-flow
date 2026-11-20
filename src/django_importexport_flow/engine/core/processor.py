"""Extension contract for business imports that own validation and writes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from django.core.files.base import ContentFile
from django.db import transaction

from ...utils.helpers import get_setting
from ...utils.upload_validation import validate_tabular_upload_bytes
from ..hooks import _read_limited
from .formats import detect_import_format, get_import_config
from .hooks import _load_hook

if TYPE_CHECKING:
    import pandas as pd

    from ...models import Definition


@dataclass(frozen=True)
class ImportProcessorContext:
    """Provide the definition and saved inputs to a business import."""

    definition: Definition
    format_key: str
    user: Any
    filter_payload: dict[str, Any]
    preview_only: bool


@dataclass
class ImportProcessorResult:
    """Describe business import errors, warnings, and rows for the preview."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    imported_row_count: int = 0
    dataframe: pd.DataFrame | None = None
    column_paths: list[str] = field(default_factory=list)
    row_count: int | None = None


def run_import_processor(
    definition: Definition,
    file: Any,
    *,
    user: Any,
    filter_payload: dict[str, Any] | None,
    preview_only: bool,
    max_bytes: int,
) -> ImportProcessorResult | None:
    """Run the category processor, if configured for the file format.

    Args:
        definition: The import definition selecting the processor.
        file: An upload or stored file with an importable filename.
        user: The initiating user, if any.
        filter_payload: Persistable filters and business options.
        preview_only: Whether to validate without committing database writes.
        max_bytes: Maximum size of the input file.

    Returns:
        The processor result, or None if the format uses the standard pipeline.

    Raises:
        TypeError: If the configured processor or its result is invalid.
        ValueError: If a configured processor cannot read the input.
    """
    name = getattr(file, "name", "") or ""
    try:
        spec = detect_import_format(name, getattr(file, "content_type", "") or "")
        config = get_import_config(definition, spec.key)
    except ValueError:
        # Preserve the standard hook's MIME detection and format errors.
        return None

    path = (config.get_category().configuration or {}).get("import_processor")
    if path is None:
        return None
    if not name.lower().endswith(spec.extension):
        raise ValueError(f"An import processor for {spec.key} requires a {spec.extension} file.")
    if not isinstance(path, str) or not path.strip():
        raise TypeError("import_processor must be a dotted callable path.")
    processor = _load_hook(path)
    limit = max_bytes if max_bytes > 0 else int(get_setting("MAX_TABULAR_IMPORT_BYTES"))
    raw = _read_limited(file, limit)
    if spec.category == "spreadsheet":
        validate_tabular_upload_bytes(raw, name)
    context = ImportProcessorContext(
        definition=definition,
        format_key=spec.key,
        user=user,
        filter_payload=dict(filter_payload or {}),
        preview_only=preview_only,
    )
    with ContentFile(raw, name=name) as source, transaction.atomic():
        result = processor(source, context)
        if not isinstance(result, ImportProcessorResult):
            raise TypeError("Import processor must return an ImportProcessorResult.")
        if result.imported_row_count < 0:
            raise ValueError("An import processor cannot report a negative row count.")
        if preview_only or result.errors:
            transaction.set_rollback(True)
    return result
