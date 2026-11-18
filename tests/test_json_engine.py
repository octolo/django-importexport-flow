import json

import pytest
from django.contrib.contenttypes.models import ContentType

from django_importexport_flow.engine import ExportTableEngine, TableEngine
from django_importexport_flow.models import Definition
from tests.sample.models import Book
from tests.support import attach_tabular_export


@pytest.mark.django_db
def test_table_engine_json_and_pandas_exports():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export",
        name="JSON books",
        target=ct,
        manager="objects",
        filter_config={},
    )
    attach_tabular_export(
        export=definition,
        columns=["title", "pages"],
        configuration={"json": {"indent": 2}},
    )
    Book.objects.create(title="Guide", pages=99)
    engine = TableEngine(definition)
    title_v = str(Book._meta.get_field("title").verbose_name)
    pages_v = str(Book._meta.get_field("pages").verbose_name)
    payload = engine.get_json_payload()
    assert payload["headers"] == [title_v, pages_v]
    assert payload["records"][0][title_v] == "Guide"
    assert payload["records"][0][pages_v] == 99
    rows = json.loads(engine.get_json())
    assert rows[0][title_v] == "Guide"
    assert rows[0][pages_v] == 99


@pytest.mark.django_db
def test_table_engine_alias():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export",
        name="Alias",
        target=ct,
        manager="objects",
        filter_config={},
    )
    attach_tabular_export(
        export=definition,
        columns=["title"],
        configuration={},
    )
    Book.objects.create(title="A", pages=1)
    engine = ExportTableEngine(definition)
    vn = str(Book._meta.get_field("title").verbose_name)
    assert engine.get_json_payload()["records"][0][vn] == "A"


@pytest.mark.django_db
def test_table_engine_csv_pandas_uses_configuration_delimiter():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export",
        name="CSV",
        target=ct,
        manager="objects",
        filter_config={},
    )
    attach_tabular_export(
        export=definition,
        columns=["title", "pages"],
        configuration={"csv": {"delimiter": ";"}},
    )
    Book.objects.create(title="Hi", pages=1)
    raw = TableEngine(definition).get_csv().decode("utf-8")
    header = raw.splitlines()[0]
    assert ";" in header
    parts = header.split(";")
    assert parts[0] == str(Book._meta.get_field("title").verbose_name)
    assert parts[1] == str(Book._meta.get_field("pages").verbose_name)
