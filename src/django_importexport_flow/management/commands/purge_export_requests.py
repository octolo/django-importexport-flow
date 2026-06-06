"""Delete old :class:`~django_importexport_flow.models.ExportRequest` records and their output files."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = (
        "Delete ExportRequest records whose completed_at is older than --days days. "
        "Output files stored in output_file are deleted from storage as well. "
        "Only terminal rows (success / failure) are considered; pending/processing rows are skipped."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Retain rows completed within this many days (default: 30).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Print how many rows would be deleted without touching the database.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        from django_importexport_flow.models import ExportRequest

        days: int = options["days"]
        dry_run: bool = options["dry_run"]
        cutoff = timezone.now() - timedelta(days=days)

        qs = ExportRequest.objects.filter(
            status__in=(ExportRequest.Status.SUCCESS, ExportRequest.Status.FAILURE),
            completed_at__lt=cutoff,
        )

        count = qs.count()
        if dry_run:
            self.stdout.write(
                f"[dry-run] Would delete {count} ExportRequest row(s) "
                f"completed before {cutoff.date()}."
            )
            return

        deleted = 0
        for er in qs.iterator():
            if er.output_file:
                try:
                    er.output_file.delete(save=False)
                except Exception as exc:
                    self.stderr.write(
                        f"Could not delete file for ExportRequest pk={er.pk}: {exc}"
                    )
            er.delete()
            deleted += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {deleted} ExportRequest row(s) completed before {cutoff.date()}."
            )
        )
