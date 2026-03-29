#!/usr/bin/env python3
"""
Regenerate report_export_books.json and report_export_authors.json with valid
ContentType IDs for this database.

Usage (from the django-importexport project root):

  DJANGO_SETTINGS_MODULE=tests.settings python tests/sample/report_fixtures/build_fixtures.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")

import django

django.setup()

from django.contrib.contenttypes.models import ContentType

from django_importexport_flow.models import ExportConfigPdf, ExportDefinition, ExportConfigTable
from django_importexport_flow.utils.serialization import serialize_export_configuration
from tests.sample.models import Author, Book


def main() -> None:
    ct_book = ContentType.objects.get_for_model(Book)
    ct_author = ContentType.objects.get_for_model(Author)

    rev = next(
        f.get_accessor_name()
        for f in Author._meta.get_fields()
        if getattr(f, "related_model", None) is Book and getattr(f, "one_to_many", False)
    )

    ExportDefinition.objects.filter(name__startswith="Sample fixture —").delete()

    def_b = ExportDefinition.objects.create(
        name="Sample fixture — Books (all rows)",
        description="Lists every Book with title, pages, price, metadata, and author.name.",
        target=ct_book,
        manager="objects",
        filter_config={},
        filter_request={},
    )
    ExportConfigTable.objects.create(
        export=def_b,
        columns=[
            "title",
            "pages",
            "price",
            "metadata",
            "author.name",
        ],
        configuration={"csv": {"delimiter": ";"}, "excel": {"sheet": "Books"}},
    )
    ExportConfigPdf.objects.create(export=def_b, template="", configuration={})

    def_a = ExportDefinition.objects.create(
        name="Sample fixture — Authors (books as columns)",
        description="Each author row; related books expanded as title / pages / price columns.",
        target=ct_author,
        manager="objects",
        filter_config={},
        filter_request={},
    )
    ExportConfigTable.objects.create(
        export=def_a,
        columns=[
            "name",
            f"{rev}.*[title:pages:price]",
        ],
        configuration={"csv": {"delimiter": ";"}, "excel": {"sheet": "Authors"}},
    )
    ExportConfigPdf.objects.create(export=def_a, template="", configuration={})

    out_dir = Path(__file__).resolve().parent
    for d, name in [
        (def_b, "report_export_books.json"),
        (def_a, "report_export_authors.json"),
    ]:
        data = serialize_export_configuration(d)
        (out_dir / name).write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print("Wrote", out_dir / name)

    ExportDefinition.objects.filter(name__startswith="Sample fixture —").delete()
    print("Reverse accessor on Author for Book:", rev)


if __name__ == "__main__":
    main()
