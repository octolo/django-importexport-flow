"""Sample processing backends for tests."""

from __future__ import annotations

from django.utils import timezone

from django_importexport_flow.models import ExportRequest, ImportRequest


def mark_import_success(request: ImportRequest, *, rows: int = 0) -> None:
    request.status = ImportRequest.Status.SUCCESS
    request.imported_row_count = rows
    request.error_trace = ""
    request.completed_at = timezone.now()
    request.save(
        update_fields=["status", "imported_row_count", "error_trace", "completed_at"]
    )


def mark_export_success(request: ExportRequest, *, byte_size: int = 1) -> None:
    from django.core.files.base import ContentFile

    content = b"x" * byte_size
    request.status = ExportRequest.Status.SUCCESS
    request.output_bytes = byte_size
    request.error_trace = ""
    request.completed_at = timezone.now()
    request.output_file.save("export.bin", ContentFile(content), save=False)
    request.save(
        update_fields=[
            "status",
            "output_bytes",
            "error_trace",
            "completed_at",
            "output_file",
        ]
    )
