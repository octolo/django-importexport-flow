import pytest
from django.contrib.contenttypes.models import ContentType

from django_importexport_flow.engine import ExportTableEngine
from django_importexport_flow.utils.export import attach_export_url_kwargs, build_request_with_get
from django_importexport_flow.models import ExportConfigTable, ExportDefinition
from tests.sample.models import Book


@pytest.mark.django_db
def test_filter_mandatory_kwargs_from_attach():
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition.objects.create(
        name="URL kw",
        target=ct,
        manager="objects",
        filter_config={},
        filter_mandatory={"kwargs": {"n": "pages"}},
    )
    ExportConfigTable.objects.create(
        export=definition,
        columns=["title"],
        configuration={},
    )
    b = Book.objects.create(title="Match", pages=99)
    Book.objects.create(title="Other", pages=1)
    request = build_request_with_get({})
    attach_export_url_kwargs(request, {"n": "99"})
    engine = ExportTableEngine(definition, request=request)
    assert list(engine.get_queryset()) == [b]


@pytest.mark.django_db
def test_filter_mandatory_kwargs_missing_raises():
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition.objects.create(
        name="URL kw missing",
        target=ct,
        manager="objects",
        filter_config={},
        filter_mandatory={"kwargs": {"n": "pages"}},
    )
    ExportConfigTable.objects.create(
        export=definition,
        columns=["title"],
        configuration={},
    )
    request = build_request_with_get({})
    attach_export_url_kwargs(request, {})
    engine = ExportTableEngine(definition, request=request)
    with pytest.raises(ValueError, match="URL kwarg"):
        list(engine.get_queryset())
