#!/usr/bin/env python3
"""
Regenerate the sample definition fixtures (one file per capability).

Content-type foreign keys are written as natural keys (``["sample", "book"]``)
so the JSON does not depend on local ContentType primary keys.

Usage (from the project root):

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
from django.core import serializers

from django_importexport_flow.engine.core.paths import default_importable_column_paths
from django_importexport_flow.models import Definition
from django_importexport_flow.utils.serialization import _iter_tree
from tests.sample.models import Author, AuthorProfile, Book, FieldShowcase, GenericBookmark
from tests.support import attach_import_spreadsheet, attach_pdf_export, attach_tabular_export

OUT_DIR = Path(__file__).resolve().parent
CATALOG = OUT_DIR.parent / "fixtures" / "sample_catalog.json"
PREFIX = "Sample fixture —"
TRANSLATED_FIXTURES = {"report_export_books.json", "report_import_books_match.json"}


def _dump(objects) -> dict:
    raw = serializers.serialize(
        "json",
        list(objects),
        use_natural_foreign_keys=True,
    )
    return {"format_version": 2, "objects": json.loads(raw)}


def _write(name: str, definition: Definition) -> None:
    payload = _dump(_iter_tree(definition))
    if name in TRANSLATED_FIXTURES:
        target = payload["objects"][0]["fields"]["target"]
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        rows = [
            {key: obj["fields"][key] for key in ("path", "language", "label")}
            for obj in catalog
            if obj["model"] == "django_importexport_flow.columntranslation"
            and obj["fields"]["content_type"] == target
        ]
        payload["column_translations"] = sorted(
            rows, key=lambda row: (row["path"], row["language"])
        )
    path = OUT_DIR / name
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Wrote", path.name)


def _exclude_except(model, keep: list[str], **path_kwargs) -> list[str]:
    paths = default_importable_column_paths(model, **path_kwargs)
    missing = [item for item in keep if item not in paths]
    if missing:
        raise SystemExit(f"{model.__name__}: paths not in the default set: {missing}\n{paths}")
    kept = set(keep)
    return [path for path in paths if path not in kept]


def _export(name: str, description: str, model, **fields) -> Definition:
    return Definition.objects.create(
        direction="export",
        name=name,
        description=description,
        target=ContentType.objects.get_for_model(model),
        manager=fields.pop("manager", "objects"),
        **fields,
    )


def _table(definition: Definition, columns: list[str], configuration: dict | None = None, **extra):
    attach_tabular_export(
        export=definition,
        columns=columns,
        configuration=configuration or {},
        **extra,
    )


def _pdf(definition: Definition, template: str, configuration: dict | None = None):
    attach_pdf_export(
        export=definition,
        template=template,
        configuration=configuration or {},
    )


def main() -> None:
    Definition.objects.filter(name__startswith=PREFIX).delete()
    Definition.objects.filter(name__startswith=PREFIX).delete()

    rev = next(
        field.get_accessor_name()
        for field in Author._meta.get_fields()
        if getattr(field, "related_model", None) is Book and getattr(field, "one_to_many", False)
    )

    books = _export(
        "Sample fixture — Books (all rows)",
        "Columns, static filter_config, optional filter_request, mandatory GET, and a PDF template.",
        Book,
        filter_config={"price__gte": 0},
        filter_request={"before": "recorded_at__lt"},
        filter_mandatory={"get": {"min_pages": "pages__gte"}},
    )
    _table(
        books,
        ["title", "pages", "price", "metadata", "author.name"],
        {"csv": {"delimiter": ";"}, "excel": {"sheet": "Books"}},
    )
    _pdf(
        books,
        "<ul>{% for obj in object_list %}<li>{{ obj.title }}</li>{% endfor %}</ul>",
    )

    authors = _export(
        "Sample fixture — Authors (books as columns)",
        "Reverse one-to-many expand: each related book becomes title / pages / price columns.",
        Author,
    )
    _table(
        authors,
        ["name", f"{rev}.*[title:pages:price]"],
        {"csv": {"delimiter": ";"}, "excel": {"sheet": "Authors"}},
    )

    filtered = _export(
        "Sample fixture — Books (filters)",
        "Static filter_config, optional filter_request, and mandatory GET plus URL kwargs.",
        Book,
        order_by=["-pages", "title"],
        filter_config={"price__gte": 1},
        filter_request={"before": "recorded_at__lt"},
        filter_mandatory={
            "get": {"min_pages": "pages__gte"},
            "kwargs": {"author_id": "author_id"},
        },
    )
    _table(filtered, ["title", "pages", "price"])

    managed = _export(
        "Sample fixture — Books (manager kwargs)",
        "Static manager_kwargs_config, optional manager_kwargs_request, and mandatory manager GET.",
        Book,
        manager_kwargs_config={"pages__gte": 200},
        manager_kwargs_request={"q": "title__icontains"},
        manager_kwargs_mandatory={"get": {"min_price": "price__gte"}},
    )
    _table(managed, ["title", "pages"])

    split = _export(
        "Sample fixture — Books (excel split)",
        "Excel split_by writes one worksheet per author name.",
        Book,
    )
    _table(
        split,
        ["title", "author.name"],
        {"excel": {"sheet": "Books"}, "split_by": "author.name"},
    )

    relations = _export(
        "Sample fixture — Books (relations and json)",
        "FK, reverse O2O, M2M slots, JSON subpaths, a property, and a callable column.",
        Book,
    )
    _table(
        relations,
        [
            "title",
            "author.name",
            "author.name_upper",
            "author.get_display_name",
            "author.profile.bio",
            "tags.0.name",
            "tags.1.name",
            "metadata.lang",
            "metadata.tags.0",
        ],
    )

    annotated = _export(
        "Sample fixture — Books (annotation)",
        "Manager path objects.with_title_len adds title_len, usable as a column and in order_by.",
        Book,
        manager="objects.with_title_len",
    )
    _table(
        annotated,
        ["title", "title_len"],
        {"annotation_columns": ["title_len"], "title_len_label": "Title length"},
    )
    annotated.order_by = ["-title_len"]
    annotated.save()

    pdf = _export(
        "Sample fixture — Books (pdf)",
        "HTML template rendered with object_list.",
        Book,
        order_by=["title"],
    )
    _table(pdf, ["title"])
    _pdf(
        pdf,
        "<ul>{% for obj in object_list %}<li>{{ obj.title }}</li>{% endfor %}</ul>",
        {"orientation": "landscape"},
    )

    delegated = _export(
        "Sample fixture — Books (delegate export)",
        "CSV export of book titles.",
        Book,
    )
    _table(delegated, ["title"])

    showcase = _export(
        "Sample fixture — Showcase (field types)",
        "One column per common Django field, plus FK and M2M.",
        FieldShowcase,
    )
    _table(
        showcase,
        [
            "char_f",
            "text_f",
            "slug_f",
            "email_f",
            "url_f",
            "int_f",
            "bigint_f",
            "smallint_f",
            "posint_f",
            "possmall_f",
            "posbigint_f",
            "float_f",
            "decimal_f",
            "bool_f",
            "bool_null_f",
            "date_f",
            "datetime_f",
            "time_f",
            "duration_f",
            "uuid_f",
            "json_f",
            "ip_f",
            "fk_author.name",
            "tags_m2m.0.name",
        ],
    )

    bookmarks = _export(
        "Sample fixture — Bookmarks (generic fk)",
        "GenericForeignKey stored as content type plus object id.",
        GenericBookmark,
    )
    _table(bookmarks, ["label", "object_id", "content_type.model"])

    for definition, filename in (
        (books, "report_export_books.json"),
        (authors, "report_export_authors.json"),
        (filtered, "report_export_books_filters.json"),
        (managed, "report_export_books_manager.json"),
        (split, "report_export_books_split_by.json"),
        (relations, "report_export_books_relations.json"),
        (annotated, "report_export_books_annotations.json"),
        (pdf, "report_export_books_pdf.json"),
        (delegated, "report_export_books_delegate.json"),
        (showcase, "report_export_showcase.json"),
        (bookmarks, "report_export_bookmarks.json"),
    ):
        _write(filename, definition)

    def _import(name: str, description: str, model, **fields) -> Definition:
        return Definition.objects.create(
            direction="import",
            name=name,
            description=description,
            target=ContentType.objects.get_for_model(model),
            **fields,
        )

    imports = [
        (
            "report_import_books_match.json",
            _import(
                "Sample fixture — Import books (match title)",
                "match_fields updates the existing book instead of inserting a second row.",
                Book,
                match_fields=["title"],
                columns_exclude=_exclude_except(Book, ["title", "pages"]),
            ),
        ),
        (
            "report_import_books_m2m.json",
            _import(
                "Sample fixture — Import books (m2m slots)",
                "M2M slot paths, including a nested FK on the related tag.",
                Book,
                max_relation_hops=2,
                columns_exclude=_exclude_except(
                    Book,
                    ["title", "tags.0.name", "tags.0.category.name", "tags.1.name"],
                    max_relation_hops=2,
                ),
            ),
        ),
        (
            "report_import_author_profiles.json",
            _import(
                "Sample fixture — Import author profiles",
                "Forward one-to-one: profile row plus author.name.",
                AuthorProfile,
                columns_exclude=_exclude_except(AuthorProfile, ["bio", "author.name"]),
            ),
        ),
        (
            "report_import_showcase.json",
            _import(
                "Sample fixture — Import showcase scalars",
                "Representative scalar field types (text, int, bool, date, uuid, json, ip).",
                FieldShowcase,
                max_relation_hops=0,
                columns_exclude=_exclude_except(
                    FieldShowcase,
                    ["char_f", "email_f", "int_f", "bool_f", "date_f", "uuid_f", "json_f", "ip_f"],
                    max_relation_hops=0,
                ),
            ),
        ),
        (
            "report_import_books_backend.json",
            _import(
                "Sample fixture — Import books (processing backend)",
                "CSV import of book title and pages.",
                Book,
                columns_exclude=_exclude_except(Book, ["title", "pages"]),
            ),
        ),
        (
            "report_import_books_delegate.json",
            _import(
                "Sample fixture — Import books (delegate)",
                "CSV import of book titles.",
                Book,
                columns_exclude=_exclude_except(Book, ["title"]),
            ),
        ),
    ]
    for filename, definition in imports:
        attach_import_spreadsheet(definition)
        _write(filename, definition)

    Definition.objects.filter(name__startswith=PREFIX).delete()
    Definition.objects.filter(name__startswith=PREFIX).delete()
    print("Reverse accessor on Author for Book:", rev)


if __name__ == "__main__":
    main()
