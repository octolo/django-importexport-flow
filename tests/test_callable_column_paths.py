"""Column paths that resolve to no-arg callables are called automatically."""

from __future__ import annotations

import pytest
from django.contrib.contenttypes.models import ContentType

from django_importexport_flow.engine import ExportTableEngine
from django_importexport_flow.models import ExportConfigTable, ExportDefinition
from django_importexport_flow.utils.helpers import get_value_from_path
from tests.sample.models import Author, Book


# ---------------------------------------------------------------------------
# Unit tests for get_value_from_path
# ---------------------------------------------------------------------------


def test_get_value_from_path_calls_no_arg_method():
    author = Author(name="Zola")
    assert get_value_from_path(author, "get_display_name") == "[Zola]"


def test_get_value_from_path_calls_method_on_related():
    author = Author(name="Hugo")
    book = Book(title="Les Misérables", author=author)
    assert get_value_from_path(book, "author.get_display_name") == "[Hugo]"


def test_get_value_from_path_calls_nested_method():
    author = Author(name="Stendhal")
    # name_upper is a property, also callable-path test
    assert get_value_from_path(author, "name_upper") == "STENDHAL"


def test_get_value_from_path_plain_attribute_unchanged():
    author = Author(name="Balzac")
    assert get_value_from_path(author, "name") == "Balzac"


def test_get_value_from_path_none_object_returns_none():
    assert get_value_from_path(None, "get_display_name") is None


def test_get_value_from_path_missing_attribute_returns_none():
    author = Author(name="Dumas")
    assert get_value_from_path(author, "nonexistent_method") is None


@pytest.mark.django_db
def test_get_value_from_path_does_not_call_manager():
    """RelatedManager (has .all) must NOT be called as a plain callable."""
    author = Author.objects.create(name="Verne")
    # book_set is a RelatedManager — should not be called, just returned as-is
    result = get_value_from_path(author, "book_set")
    assert hasattr(result, "all")


# ---------------------------------------------------------------------------
# Integration tests: ExportTableEngine with callable column paths
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_export_engine_callable_column_on_target_model():
    author = Author.objects.create(name="Proust")
    ct = ContentType.objects.get_for_model(Author)
    definition = ExportDefinition.objects.create(
        name="Authors callable",
        target=ct,
        manager="objects",
    )
    ExportConfigTable.objects.create(
        export=definition,
        columns=["name", "get_display_name"],
        configuration={},
    )
    engine = ExportTableEngine(definition)
    rows = engine.get_rows()
    assert rows == [["Proust", "[Proust]"]]


@pytest.mark.django_db
def test_export_engine_callable_column_on_related_model():
    author = Author.objects.create(name="Flaubert")
    Book.objects.create(title="Madame Bovary", author=author)
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition.objects.create(
        name="Books callable",
        target=ct,
        manager="objects",
    )
    ExportConfigTable.objects.create(
        export=definition,
        columns=["title", "author.get_display_name"],
        configuration={},
    )
    engine = ExportTableEngine(definition)
    rows = engine.get_rows()
    assert rows == [["Madame Bovary", "[Flaubert]"]]


@pytest.mark.django_db
def test_export_engine_callable_column_null_relation():
    """No author set — callable on related model should not crash, returns empty string."""
    Book.objects.create(title="Orphan Book", author=None)
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition.objects.create(
        name="Books null author callable",
        target=ct,
        manager="objects",
    )
    ExportConfigTable.objects.create(
        export=definition,
        columns=["title", "author.get_display_name"],
        configuration={},
    )
    engine = ExportTableEngine(definition)
    rows = engine.get_rows()
    # author is None so the path resolves to None, serialized as None in get_rows
    assert rows == [["Orphan Book", None]]
