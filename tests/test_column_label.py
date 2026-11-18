"""Dynamic column-header catalog."""

from __future__ import annotations

import pandas as pd
import pytest
from django.contrib.contenttypes.models import ContentType
from django.utils import translation

from django_importexport_flow.engine import ExportTableEngine
from django_importexport_flow.engine.core.paths import default_importable_column_paths
from django_importexport_flow.engine.core.preview import validate_import_preview
from django_importexport_flow.models import (
    ColumnTranslation,
    Definition,
)
from django_importexport_flow.utils.helpers import resolve_column_header
from tests.sample.models import Author, Book
from tests.support import attach_tabular_export


def _label(model, path: str, language: str, label: str) -> None:
    ColumnTranslation.objects.create(
        content_type=ContentType.objects.get_for_model(model),
        path=path,
        language=language,
        label=label,
    )


@pytest.mark.django_db
def test_catalog_uses_active_language():
    _label(Book, "title", "fr", "Titre")
    _label(Book, "title", "en", "Title")
    with translation.override("fr"):
        assert resolve_column_header(Book, "title") == "Titre"
    with translation.override("en"):
        assert resolve_column_header(Book, "title") == "Title"


@pytest.mark.django_db
def test_configuration_override_takes_priority_over_translation():
    _label(Book, "title", "fr", "Titre")
    with translation.override("fr"):
        assert (
            resolve_column_header(
                Book,
                "title",
                configuration={"title_label": "Titre personnalisé"},
            )
            == "Titre personnalisé"
        )


@pytest.mark.django_db
def test_catalog_falls_back_to_default_language():
    _label(Book, "title", "en", "Title")
    with translation.override("de"):
        assert resolve_column_header(Book, "title") == "Title"


@pytest.mark.django_db
def test_related_path_uses_the_model_that_owns_the_field():
    _label(Author, "name", "fr", "Nom")
    with translation.override("fr"):
        assert resolve_column_header(Book, "author.name") == "Nom"


@pytest.mark.django_db
def test_slot_header_reuses_one_catalog_row():
    _label(Book, "tags.name", "fr", "Étiquette")
    with translation.override("fr"):
        assert resolve_column_header(Book, "tags.0.name") == "Étiquette 1"
        assert resolve_column_header(Book, "tags.1.name") == "Étiquette 2"


@pytest.mark.django_db
def test_export_headers_follow_the_catalog():
    _label(Book, "title", "fr", "Titre")
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export", name="FR books", target=ct, manager="objects"
    )
    attach_tabular_export(export=definition, columns=["title"], configuration={})
    Book.objects.create(title="Guide", pages=1)
    with translation.override("fr"):
        assert ExportTableEngine(definition).get_headers() == ["Titre"]


@pytest.mark.django_db
def test_import_accepts_a_header_from_another_language():
    _label(Book, "title", "fr", "Titre")
    ct = ContentType.objects.get_for_model(Book)
    paths = default_importable_column_paths(Book)
    definition = Definition.objects.create(
        direction="import",
        name="FR import",
        target=ct,
        columns_exclude=[path for path in paths if path != "title"],
        filter_config={},
    )
    frame = pd.DataFrame([{"Titre": "Guide"}])
    with translation.override("en"):
        errors, _warnings, resolved, _df = validate_import_preview(frame, definition)
    assert errors == []
    assert resolved == ["title"]
