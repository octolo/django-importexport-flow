"""Direction, category, and format rules for the generic definition models."""

from __future__ import annotations

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from django_importexport_flow.engine.core.formats import get_export_config, get_import_config
from django_importexport_flow.models import (
    CategoryConfig,
    Definition,
    ExportRequest,
    FormatConfig,
    ImportRequest,
)
from tests.sample.models import Book
from tests.support import attach_import_spreadsheet, attach_tabular_export


def _definition(direction: str, name: str, **extra) -> Definition:
    return Definition.objects.create(
        direction=direction,
        name=name,
        target=ContentType.objects.get_for_model(Book),
        manager="objects",
        **extra,
    )


@pytest.mark.django_db
def test_named_id_can_be_shared_across_directions():
    export_definition = _definition("export", "Shared")
    import_definition = _definition("import", "Other")
    Definition.objects.filter(pk=export_definition.pk).update(named_id="shared")
    Definition.objects.filter(pk=import_definition.pk).update(named_id="shared")
    assert Definition.objects.filter(named_id="shared").count() == 2


@pytest.mark.django_db
def test_named_id_is_unique_within_one_direction():
    first = _definition("export", "First")
    second = _definition("export", "Second")
    Definition.objects.filter(pk=first.pk).update(named_id="same")
    second.named_id = "same"
    with pytest.raises(ValidationError):
        second.save()


@pytest.mark.django_db
def test_document_category_is_rejected_for_import():
    definition = _definition("import", "No document")
    category = CategoryConfig(definition=definition, category_key="document")
    with pytest.raises(ValidationError):
        category.full_clean()


@pytest.mark.django_db
def test_format_must_match_its_category_and_direction():
    definition = _definition("import", "Spreadsheet only")
    sheet = attach_import_spreadsheet(definition)
    pdf = FormatConfig(category_config=sheet, format_key="pdf", template="<p>x</p>")
    with pytest.raises(ValidationError):
        pdf.full_clean()
    json_format = FormatConfig(category_config=sheet, format_key="json")
    with pytest.raises(ValidationError):
        json_format.full_clean()


@pytest.mark.django_db
def test_template_is_rejected_outside_document_formats():
    definition = _definition("export", "Csv template")
    sheet = attach_tabular_export(export=definition, columns=["title"], formats=("csv",))
    csv = get_export_config(definition, "csv")
    csv.template = "<p>no</p>"
    with pytest.raises(ValidationError):
        csv.full_clean()
    assert sheet.category_key == "spreadsheet"


@pytest.mark.django_db
def test_resolution_rejects_the_wrong_direction():
    definition = _definition("import", "Import only")
    attach_import_spreadsheet(definition)
    with pytest.raises(ValueError, match="not an export"):
        get_export_config(definition, "csv")
    export_definition = _definition("export", "Export only")
    attach_tabular_export(export=export_definition, columns=["title"], formats=("csv",))
    with pytest.raises(ValueError, match="not an import"):
        get_import_config(export_definition, "csv")


@pytest.mark.django_db
def test_requests_reject_the_wrong_direction():
    export_definition = _definition("export", "Export request")
    import_definition = _definition("import", "Import request")
    with pytest.raises(ValidationError):
        ExportRequest(export_definition=import_definition).save()
    with pytest.raises(ValidationError):
        ImportRequest(import_definition=export_definition).save()
