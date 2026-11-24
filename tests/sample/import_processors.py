"""Business import processors used by the sample definitions."""

import csv
from decimal import Decimal
from io import StringIO

from django_importexport_flow.engine.core.processor import (
    ImportProcessorContext,
    ImportProcessorResult,
)

from .models import Book


def set_book_price(file, context: ImportProcessorContext) -> ImportProcessorResult:
    """Set each book's price to one cent per page."""
    reader = csv.DictReader(StringIO(file.read().decode("utf-8-sig")))
    if not {"title", "pages"}.issubset(reader.fieldnames or []):
        return ImportProcessorResult(errors=["Expected title and pages columns."])

    count = 0
    for line, row in enumerate(reader, start=2):
        title = (row.get("title") or "").strip()
        try:
            pages = int(row.get("pages") or "")
        except ValueError:
            return ImportProcessorResult(errors=[f"Row {line}: invalid pages."])
        if not title or pages < 0:
            return ImportProcessorResult(errors=[f"Row {line}: invalid book."])
        if not context.preview_only:
            updated = Book.objects.filter(title=title).update(
                price=Decimal(pages) / 100,
            )
            if updated != 1:
                return ImportProcessorResult(
                    errors=[f"Row {line}: expected exactly one matching book."],
                )
        count += 1
    return ImportProcessorResult(imported_row_count=count, row_count=count)
