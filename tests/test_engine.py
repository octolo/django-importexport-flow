import json

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from django_importexport_flow.engine import ExportPdfEngine, ExportTableEngine
from django_importexport_flow.engine.core import CoreEngine
from django_importexport_flow.models import (
    ExportConfigPdf,
    ExportConfigTable,
    ExportDefinition,
)
from tests.sample.models import Author, Book


@pytest.mark.django_db
def test_table_engine_rows_and_headers():
    ct = ContentType.objects.get_for_model(Book)
    book = Book.objects.create(title="Guide", pages=42)
    definition = ExportDefinition.objects.create(
        name="Books",
        target=ct,
        manager="objects",
        filter_config={},
    )
    ExportConfigTable.objects.create(
        export=definition,
        columns=["title", "pages"],
        configuration={"csv": {"delimiter": ";"}, "excel": {"sheet": "Data"}},
    )
    engine = ExportTableEngine(definition)
    title_v = str(Book._meta.get_field("title").verbose_name)
    pages_v = str(Book._meta.get_field("pages").verbose_name)
    assert engine.get_headers() == [title_v, pages_v]
    assert engine.get_rows() == [["Guide", 42]]
    assert list(engine.get_queryset()) == [book]
    assert engine.config is not None
    assert engine.get_configuration()["csv"]["delimiter"] == ";"


@pytest.mark.django_db
def test_table_engine_order_by():
    ct = ContentType.objects.get_for_model(Book)
    Book.objects.create(title="A", pages=1)
    Book.objects.create(title="Z", pages=2)
    definition = ExportDefinition.objects.create(
        name="Books ordered",
        target=ct,
        manager="objects",
        filter_config={},
        order_by=["-title"],
    )
    ExportConfigTable.objects.create(
        export=definition,
        columns=["title"],
        configuration={},
    )
    engine = ExportTableEngine(definition)
    assert [r[0] for r in engine.get_rows()] == ["Z", "A"]


@pytest.mark.django_db
def test_table_engine_string_columns_verbose_and_nested_path():
    ct = ContentType.objects.get_for_model(Book)
    author = Author.objects.create(name="Ada")
    Book.objects.create(title="Guide", pages=42, author=author)
    definition = ExportDefinition.objects.create(
        name="Books nested",
        target=ct,
        manager="objects",
        filter_config={},
    )
    ExportConfigTable.objects.create(
        export=definition,
        columns=["title", "pages", "author.name", "metadata.nope"],
        configuration={},
    )
    engine = ExportTableEngine(definition)
    title_v = str(Book._meta.get_field("title").verbose_name)
    pages_v = str(Book._meta.get_field("pages").verbose_name)
    author_name_v = str(Author._meta.get_field("name").verbose_name)
    meta_v = str(Book._meta.get_field("metadata").verbose_name)
    assert engine.get_headers() == [
        title_v,
        pages_v,
        author_name_v,
        f"{meta_v} (nope)",
    ]
    assert engine.get_rows() == [["Guide", 42, "Ada", None]]


@pytest.mark.django_db
def test_table_engine_reverse_expand_columns():
    rev_name = next(
        f.get_accessor_name()
        for f in Author._meta.get_fields()
        if getattr(f, "related_model", None) is Book and getattr(f, "one_to_many", False)
    )
    ct = ContentType.objects.get_for_model(Author)
    a1 = Author.objects.create(name="A1")
    a2 = Author.objects.create(name="A2")
    Book.objects.create(title="B1", pages=10, author=a1)
    Book.objects.create(title="B2", pages=20, author=a1)
    Book.objects.create(title="B3", pages=30, author=a2)
    title_v = str(Book._meta.get_field("title").verbose_name)
    pages_v = str(Book._meta.get_field("pages").verbose_name)
    author_name_v = str(Author._meta.get_field("name").verbose_name)
    definition = ExportDefinition.objects.create(
        name="Authors",
        target=ct,
        manager="objects",
        filter_config={},
    )
    ExportConfigTable.objects.create(
        export=definition,
        columns=["name", f"{rev_name}.*[title:pages]"],
        configuration={},
    )
    engine = ExportTableEngine(definition)
    assert engine.get_headers() == [
        author_name_v,
        f"{title_v} 1",
        f"{pages_v} 1",
        f"{title_v} 2",
        f"{pages_v} 2",
    ]
    assert engine.get_rows() == [
        ["A1", "B1", 10, "B2", 20],
        ["A2", "B3", 30, None, None],
    ]


@pytest.mark.django_db
def test_table_engine_jsonfield_whole_dict_nested_and_list():
    """JSONField: whole value as JSON string; dotted keys; dict/list segments."""
    ct = ContentType.objects.get_for_model(Book)
    meta = {
        "lang": "fr",
        "extra": {"depth": 3},
        "tags": ["alpha", "beta"],
    }
    Book.objects.create(title="T", pages=1, metadata=meta)
    definition = ExportDefinition.objects.create(
        name="JSON columns",
        target=ct,
        manager="objects",
        filter_config={},
    )
    meta_v = str(Book._meta.get_field("metadata").verbose_name)
    ExportConfigTable.objects.create(
        export=definition,
        columns=[
            "metadata",
            "metadata.lang",
            "metadata.extra",
            "metadata.extra.depth",
            "metadata.tags",
            "metadata.tags.0",
        ],
        configuration={},
    )
    engine = ExportTableEngine(definition)
    assert engine.get_headers() == [
        meta_v,
        f"{meta_v} (lang)",
        f"{meta_v} (extra)",
        f"{meta_v} (extra.depth)",
        f"{meta_v} (tags)",
        f"{meta_v} (tags.0)",
    ]
    row = engine.get_rows()[0]
    assert row[0] == json.dumps(meta, ensure_ascii=False)
    assert row[1] == "fr"
    assert row[2] == json.dumps({"depth": 3}, ensure_ascii=False)
    assert row[3] == 3
    assert row[4] == json.dumps(["alpha", "beta"], ensure_ascii=False)
    assert row[5] == "alpha"


@pytest.mark.django_db
def test_table_engine_rejects_non_string_column():
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition.objects.create(
        name="Bad columns",
        target=ct,
        manager="objects",
        filter_config={},
    )
    cfg = ExportConfigTable.objects.create(
        export=definition,
        columns=["title"],
        configuration={},
    )
    # Bypass model validation (simulates legacy / raw DB data).
    ExportConfigTable.objects.filter(pk=cfg.pk).update(columns=[{"data": "title"}])
    definition.refresh_from_db()
    engine = ExportTableEngine(definition)
    with pytest.raises(TypeError, match="str"):
        engine.get_headers()


@pytest.mark.django_db
def test_table_engine_without_config_table():
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition.objects.create(
        name="Bare",
        target=ct,
        manager="objects",
        filter_config={},
    )
    engine = ExportTableEngine(definition)
    assert engine.config is None
    assert engine.get_configuration() == {}


@pytest.mark.django_db
def test_pdf_engine():
    ct = ContentType.objects.get_for_model(Book)
    Book.objects.create(title="X", pages=1)
    definition = ExportDefinition.objects.create(
        name="Books PDF",
        target=ct,
        manager="objects",
        filter_config={},
    )
    ExportConfigTable.objects.create(
        export=definition,
        columns=["title"],
        configuration={},
    )
    ExportConfigPdf.objects.create(
        export=definition,
        template="<html>{{ object_list }}</html>",
        configuration={"orientation": "landscape"},
    )
    pdf = ExportPdfEngine(definition)
    assert pdf.definition.config_pdf.configuration["orientation"] == "landscape"
    assert "<html>" in pdf.get_template()
    table = ExportTableEngine(definition)
    assert table.get_headers() == [str(Book._meta.get_field("title").verbose_name)]
    assert len(table.get_rows()) == 1


@pytest.mark.django_db
def test_core_engine_validates_filter_config_on_queryset_without_save():
    """Unsaved definitions still go through the same ORM-key validation as model.clean()."""
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition(
        name="Draft",
        target=ct,
        manager="objects",
        filter_config={"not_a_real_field": 1},
    )
    engine = CoreEngine(definition)
    with pytest.raises(ValidationError):
        engine.get_queryset()
