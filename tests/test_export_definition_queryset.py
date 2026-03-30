import pytest
from django.contrib.contenttypes.models import ContentType

from django_importexport_flow.models import ExportDefinition
from django_importexport_flow.utils.helpers import get_export_definitions
from tests.sample.models import Author, Book


@pytest.mark.django_db
def test_for_model_and_get_export_definitions():
    ct_book = ContentType.objects.get_for_model(Book)
    ct_author = ContentType.objects.get_for_model(Author)
    book_report = ExportDefinition.objects.create(
        name="Books",
        target=ct_book,
        manager="objects",
        filter_config={},
    )
    author_report = ExportDefinition.objects.create(
        name="Authors",
        target=ct_author,
        manager="objects",
        filter_config={},
    )
    assert list(ExportDefinition.objects.for_model(Book)) == [book_report]
    assert list(get_export_definitions(Book)) == [book_report]
    assert author_report not in get_export_definitions(Book)
