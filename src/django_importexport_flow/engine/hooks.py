"""Native format hooks. A custom hook may call these or return a file itself."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.core.files.uploadedfile import UploadedFile
from django.utils.translation import gettext_lazy as _

from .core.dataset import ImportDataset, ImportTemplateDataset
from .core.formats import get_format
from .core.tabular import read_tabular_dataframe_from_bytes

if TYPE_CHECKING:
    from ..models import Definition

ExportResult = tuple[bytes, str, str]


def native_import_template(
    definition: Definition, _context: dict[str, Any]
) -> ImportTemplateDataset:
    """Build a simple import schema using configured columns and translated labels.

    Args:
        definition: Import definition providing columns and the target model.
        _context: Generation context, unused by the native simple hook.

    Returns:
        Canonical columns and labels resolved for the active Django language.

    Raises:
        ValueError: If the template configuration is invalid.
    """
    from ..utils.process import _single_import_template

    return _single_import_template(definition)


def native_combined_import_template(
    definition: Definition, context: dict[str, Any]
) -> ImportTemplateDataset:
    """Merge child template hooks in step order, retaining the first label per key.

    Args:
        definition: Parent import definition providing the ordered steps.
        context: Generation context passed to each child's effective hook.

    Returns:
        The ordered union of child schemas, or the explicit parent schema.

    Raises:
        ValueError: If a child schema is invalid or steps are nested.
        TypeError: If a child hook returns the wrong dataset type.
    """
    from ..utils.process import _combined_import_template

    return _combined_import_template(definition, context)


def _native_export(dataset: Any, format_config: Any) -> ExportResult:
    spec = get_format(format_config.format_key)
    if spec is None:
        raise ValueError(f"Unknown format {format_config.format_key!r}.")
    return spec.generate(dataset), spec.content_type, spec.extension


def generate_csv(dataset: Any) -> bytes:
    return dataset.engine.get_csv()


def generate_excel(dataset: Any) -> bytes:
    return dataset.engine.get_excel()


def generate_json(dataset: Any) -> bytes:
    return dataset.engine.get_json_bytes()


def generate_pdf(dataset: Any) -> bytes:
    return dataset.engine.get_report()


def native_csv_export(
    dataset: Any, _category: Any, format_config: Any, _payload: dict
) -> ExportResult:
    return _native_export(dataset, format_config)


def native_excel_export(
    dataset: Any, _category: Any, format_config: Any, _payload: dict
) -> ExportResult:
    """Shared by Excel formats (``.xlsx`` today; ``.xls`` uses this hook when it is registered)."""
    return _native_export(dataset, format_config)


def native_json_export(
    dataset: Any, _category: Any, format_config: Any, _payload: dict
) -> ExportResult:
    return _native_export(dataset, format_config)


def native_pdf_export(
    dataset: Any, _category: Any, format_config: Any, _payload: dict
) -> ExportResult:
    return _native_export(dataset, format_config)


def _read_chunked(file: Any, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in file.chunks():
        total += len(chunk)
        if total > max_bytes:
            raise ValueError(str(_("File is too large.")))
        chunks.append(chunk)
    return b"".join(chunks)


def _stream_position(file: Any) -> int | None:
    tell = getattr(file, "tell", None)
    if not callable(tell):
        return None
    try:
        return int(tell())
    except (OSError, ValueError, TypeError):
        return None


def _restore_stream(file: Any, position: int | None) -> None:
    if position is None:
        return
    seek = getattr(file, "seek", None)
    if not callable(seek):
        return
    try:
        seek(position)
    except (OSError, ValueError):
        return


def _read_capped(file: Any, max_bytes: int) -> bytes:
    """Read from the start, then put a seekable stream back where it was."""
    position = _stream_position(file)
    try:
        seek = getattr(file, "seek", None)
        if callable(seek):
            try:
                seek(0)
            except (OSError, ValueError):
                pass
        raw = file.read(max_bytes + 1)
    finally:
        _restore_stream(file, position)
    if len(raw) > max_bytes:
        raise ValueError(str(_("File is too large.")))
    return raw


def _prefers_chunks(file: Any, *, opened_here: bool) -> bool:
    """Uploaded files are read in chunks. An already-open file keeps its position."""
    if isinstance(file, UploadedFile):
        return True
    if not hasattr(file, "chunks"):
        return False
    if opened_here:
        return True
    return not hasattr(file, "open")


def _read_limited(file: Any, max_bytes: int) -> bytes:
    """Read at most ``max_bytes`` and reject anything larger before buffering it."""
    opened_here = False
    if hasattr(file, "open") and getattr(file, "closed", True):
        file.open("rb")
        opened_here = True
    try:
        if _prefers_chunks(file, opened_here=opened_here):
            return _read_chunked(file, max_bytes)
        return _read_capped(file, max_bytes)
    finally:
        if opened_here:
            file.close()


def _file_bytes(file: Any, max_bytes: int) -> tuple[bytes, str]:
    from ..utils.helpers import get_setting

    if max_bytes <= 0:
        max_bytes = int(get_setting("MAX_TABULAR_IMPORT_BYTES"))
    name = getattr(file, "name", "") or ""
    return _read_limited(file, max_bytes), name


def _import_dataset(raw: bytes, name: str, format_key: str, max_bytes: int) -> ImportDataset:
    frame = read_tabular_dataframe_from_bytes(raw, name, max_bytes)
    headers = [str(column) for column in frame.columns]
    return ImportDataset(
        dataframe=frame,
        headers=headers,
        format_key=format_key,
        metadata={"name": name},
    )


def native_csv_import(
    file: Any, _category: Any, format_config: Any, context: dict[str, Any]
) -> ImportDataset:
    max_bytes = int(context.get("max_bytes") or 0)
    raw, name = _file_bytes(file, max_bytes)
    read_name = name if str(name).lower().endswith(".csv") else "upload.csv"
    delimiter = (format_config.configuration or {}).get("delimiter")
    if isinstance(delimiter, str) and len(delimiter) == 1 and delimiter != ",":
        from io import BytesIO

        import pandas as pd

        from ..utils.upload_validation import validate_tabular_upload_bytes

        validate_tabular_upload_bytes(raw, read_name)
        frame = pd.read_csv(BytesIO(raw), encoding="utf-8", sep=delimiter)
        headers = [str(column) for column in frame.columns]
        return ImportDataset(
            dataframe=frame,
            headers=headers,
            format_key="csv",
            metadata={"name": name},
        )
    return _import_dataset(raw, read_name, "csv", max_bytes)


def native_excel_import(
    file: Any, _category: Any, _format_config: Any, context: dict[str, Any]
) -> ImportDataset:
    """Shared by Excel readers (``.xlsx`` and ``.xls``)."""
    max_bytes = int(context.get("max_bytes") or 0)
    raw, name = _file_bytes(file, max_bytes)
    lowered = str(name).lower()
    if not lowered.endswith((".xlsx", ".xls")):
        name = f"{name or 'upload'}.xlsx"
    return _import_dataset(raw, name, "excel", max_bytes)
