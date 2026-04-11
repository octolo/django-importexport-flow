import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from django_importexport_flow.models import (
    ExportConfigTable,
    ExportDefinition,
    ImportDefinition,
)
from tests.sample.models import Book


@pytest.mark.django_db
def test_export_definition_allows_unknown_filter_config_keys():
    """Exports may filter on annotations / manager fields not visible on the model class."""
    ct = ContentType.objects.get_for_model(Book)
    ExportDefinition.objects.create(
        name="Annotation filter ok",
        target=ct,
        manager="objects",
        filter_config={"not_a_field": 1},
    )


@pytest.mark.django_db
def test_import_definition_rejects_invalid_filter_config():
    ct = ContentType.objects.get_for_model(Book)
    with pytest.raises(ValidationError):
        ImportDefinition.objects.create(
            name="Bad filter",
            target=ct,
            filter_config={"not_a_field": 1},
        )


@pytest.mark.django_db
def test_report_definition_accepts_overlapping_filter_request_and_mandatory_same_lookup():
    ct = ContentType.objects.get_for_model(Book)
    ExportDefinition.objects.create(
        name="Overlap ok",
        target=ct,
        manager="objects",
        filter_config={},
        filter_request={"p": "title"},
        filter_mandatory={"get": {"p": "title"}},
    )


@pytest.mark.django_db
def test_report_definition_rejects_overlapping_filter_request_mandatory_get_mismatch():
    ct = ContentType.objects.get_for_model(Book)
    with pytest.raises(ValidationError) as exc:
        ExportDefinition.objects.create(
            name="Mismatch",
            target=ct,
            manager="objects",
            filter_config={},
            filter_request={"p": "title"},
            filter_mandatory={"get": {"p": "pages"}},
        )
    assert "disagree" in " ".join(exc.value.messages).lower()


@pytest.mark.django_db
def test_export_definition_rejects_overlapping_filter_and_manager_kwargs_param():
    ct = ContentType.objects.get_for_model(Book)
    d = ExportDefinition(
        name="Overlap mgr",
        target=ct,
        manager="objects.all",
        filter_request={"tenant": "id"},
        filter_mandatory={},
        manager_kwargs_request={"tenant": "pages"},
        filter_config={},
    )
    with pytest.raises(ValidationError):
        d.full_clean()


@pytest.mark.django_db
def test_report_config_table_accepts_unknown_column():
    ct = ContentType.objects.get_for_model(Book)
    d = ExportDefinition.objects.create(
        name="Unknown path ok",
        target=ct,
        manager="objects",
        filter_config={},
    )
    ExportConfigTable.objects.create(
        export=d,
        columns=["not_a_field"],
        configuration={},
    )


@pytest.mark.django_db
def test_content_disposition_attachment_non_ascii():
    from django_importexport_flow.utils.http import content_disposition_attachment

    h = content_disposition_attachment("rapport_2026_€.csv")
    assert "filename*=" in h
    assert "attachment" in h
