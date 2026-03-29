import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from django_importexport_flow.models import ExportConfigTable, ExportDefinition
from tests.sample.models import Book


@pytest.mark.django_db
def test_report_definition_rejects_invalid_filter_config():
    ct = ContentType.objects.get_for_model(Book)
    with pytest.raises(ValidationError):
        ExportDefinition.objects.create(
            name="Bad filter",
            target=ct,
            manager="objects",
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
def test_report_config_table_rejects_unknown_column():
    ct = ContentType.objects.get_for_model(Book)
    d = ExportDefinition.objects.create(
        name="Bad cols",
        target=ct,
        manager="objects",
        filter_config={},
    )
    with pytest.raises(ValidationError):
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
