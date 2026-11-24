"""Proxy querysets, forced keys, and separated admin workflows."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from django import forms
from django.contrib import admin
from django.contrib.admin.widgets import (
    FilteredSelectMultiple,
    ForeignKeyRawIdWidget,
)
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.forms.models import model_to_dict
from django.test.utils import CaptureQueriesContext
from django.urls import NoReverseMatch, reverse

from django_importexport_flow.engine.core.paths import default_importable_column_paths
from django_importexport_flow.models import (
    ExportCsvFormat,
    ExportDefinition,
    ExportDocumentConfig,
    ExportJsonFormat,
    ExportPdfFormat,
    ExportRequest,
    ExportSpreadsheetConfig,
    ExportStructuredDataConfig,
    ImportCsvFormat,
    ImportDefinition,
    ImportExcelFormat,
    ImportRequest,
    ImportSpreadsheetConfig,
)
from django_importexport_flow.utils.serialization import (
    import_export_configuration,
    serialize_export_configuration,
)
from django_importexport_flow.utils.translations import (
    catalogs_for_paths,
    import_header_aliases,
)
from tests.sample.models import Book
from tests.support import attach_import_spreadsheet, attach_tabular_export

_CONCRETE_MODELS = {
    "django_importexport_flow.definition",
    "django_importexport_flow.categoryconfig",
    "django_importexport_flow.formatconfig",
}


def _target():
    return ContentType.objects.get_for_model(Book)


@pytest.mark.django_db
def test_definition_proxies_isolate_direction_and_named_id():
    unsaved = ExportDefinition(name="Unsaved export", target=_target(), manager="objects")
    unsaved.full_clean()
    assert unsaved.direction == "export"

    export_row = ExportDefinition.objects.create(
        name="Proxy export",
        target=_target(),
        manager="objects",
        direction="import",
    )
    import_row = ImportDefinition.objects.create(
        name="Proxy import",
        target=_target(),
        direction="export",
    )
    assert export_row.direction == "export"
    assert import_row.direction == "import"
    assert export_row.pk not in ImportDefinition.objects.values_list("pk", flat=True)
    assert import_row.pk not in ExportDefinition.objects.values_list("pk", flat=True)

    export_row.direction = "import"
    export_row.save()
    export_row.refresh_from_db()
    assert export_row.direction == "export"

    ExportDefinition.objects.filter(pk=export_row.pk).update(named_id="shared-proxy")
    ImportDefinition.objects.filter(pk=import_row.pk).update(named_id="shared-proxy")
    assert ExportDefinition.objects.filter(named_id="shared-proxy").count() == 1
    assert ImportDefinition.objects.filter(named_id="shared-proxy").count() == 1

    other = ExportDefinition.objects.create(
        name="Other export", target=_target(), manager="objects"
    )
    other.named_id = "shared-proxy"
    with pytest.raises(ValidationError):
        other.save()


@pytest.mark.django_db
def test_category_and_format_proxies_force_keys_and_parents():
    export_row = ExportDefinition.objects.create(
        name="Export categories",
        target=_target(),
        manager="objects",
    )
    import_row = ImportDefinition.objects.create(name="Import categories", target=_target())
    sheet = ExportSpreadsheetConfig(definition=export_row)
    sheet.full_clean()
    assert sheet.category_key == "spreadsheet"
    sheet.save()
    document = ExportDocumentConfig.objects.create(definition=export_row)
    imported = ImportSpreadsheetConfig.objects.create(definition=import_row)
    assert sheet.category_key == "spreadsheet"
    assert document.category_key == "document"
    assert imported.category_key == "spreadsheet"
    assert ExportSpreadsheetConfig.objects.get().pk == sheet.pk
    assert not ExportDocumentConfig.objects.filter(pk=sheet.pk).exists()
    assert not ImportSpreadsheetConfig.objects.filter(pk=sheet.pk).exists()

    with pytest.raises(ValidationError):
        ImportSpreadsheetConfig.objects.create(definition=export_row)
    with pytest.raises(ValidationError):
        ExportPdfFormat.objects.create(category_config=sheet, template="<p>no</p>")
    with pytest.raises(ValidationError):
        ExportCsvFormat(category_config=sheet, template="<p>no</p>").save()

    structured = ExportStructuredDataConfig.objects.create(definition=export_row)
    csv_format = ExportCsvFormat(category_config=sheet)
    csv_format.full_clean()
    assert csv_format.format_key == "csv"
    csv_format.save()
    json_format = ExportJsonFormat.objects.create(category_config=structured)
    pdf_format = ExportPdfFormat.objects.create(category_config=document, template="<p>ok</p>")
    imported_csv = ImportCsvFormat.objects.create(category_config=imported)
    assert csv_format.format_key == "csv"
    assert json_format.format_key == "json"
    assert pdf_format.format_key == "pdf"
    assert imported_csv.format_key == "csv"
    assert ExportCsvFormat.objects.count() == 1
    assert ImportCsvFormat.objects.count() == 1
    assert not ExportJsonFormat.objects.filter(pk=imported_csv.pk).exists()
    assert csv_format.get_effective_hooks() == [
        "django_importexport_flow.engine.hooks.native_csv_export"
    ]
    csv_format.hook = ["django_importexport_flow.engine.hooks.native_json_export"]
    csv_format.save()
    assert csv_format.get_effective_hooks() == [
        "django_importexport_flow.engine.hooks.native_json_export"
    ]
    assert not hasattr(
        __import__("django_importexport_flow.models", fromlist=["models"]), "ImportDocumentConfig"
    )
    assert not hasattr(
        __import__("django_importexport_flow.models", fromlist=["models"]), "ImportJsonFormat"
    )


@pytest.mark.django_db
def test_request_admin_foreign_keys_follow_direction_proxies():
    export_row = ExportDefinition.objects.create(
        name="Request export",
        target=_target(),
        manager="objects",
    )
    import_row = ImportDefinition.objects.create(name="Request import", target=_target())
    export_admin = admin.site._registry[ExportRequest]
    import_admin = admin.site._registry[ImportRequest]
    request = type("Request", (), {"user": None})()
    export_field = export_admin.formfield_for_foreignkey(
        ExportRequest._meta.get_field("export_definition"),
        request,
    )
    import_field = import_admin.formfield_for_foreignkey(
        ImportRequest._meta.get_field("import_definition"),
        request,
    )
    assert list(export_field.queryset) == [export_row]
    assert list(import_field.queryset) == [import_row]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('direction', 'definition_model'),
    [('import', ImportDefinition), ('export', ExportDefinition)],
)
def test_request_admin_add_uses_proxy_raw_id(
    direction, definition_model, admin_client, settings
):
    settings.DJANGO_IMPORTEXPORT_FLOW = {
        f'{direction.upper()}_ADMIN_OFFER_ASYNC': False,
    }
    definition = definition_model.objects.create(name=f'{direction} definition')
    other_model = (
        ExportDefinition if direction == 'import' else ImportDefinition
    )
    other = other_model.objects.create(name='Other definition')
    url = reverse(f'admin:django_importexport_flow_{direction}request_add')
    response = admin_client.get(url)

    assert response.status_code == 200
    form = response.context['adminform'].form
    assert 'name="run_async"' not in response.content.decode()
    field = form.fields[f'{direction}_definition']
    assert isinstance(field.widget, ForeignKeyRawIdWidget)
    assert field.clean(definition.pk).pk == definition.pk
    with pytest.raises(ValidationError):
        field.clean(other.pk)

    context = field.widget.get_context(field.label, definition.pk, {})
    assert context['link_url'] == reverse(
        f'admin:django_importexport_flow_{direction}definition_change',
        args=[definition.pk],
    )
    lookup = admin_client.get(context['related_url'] + '&_popup=1')
    assert lookup.status_code == 200
    ids = {obj.pk for obj in lookup.context['cl'].result_list}
    assert definition.pk in ids
    assert other.pk not in ids


@pytest.mark.django_db
@pytest.mark.parametrize('direction', ['import', 'export'])
def test_request_admin_add_submits_raw_id(
    direction, admin_client, settings, tmp_path
):
    settings.MEDIA_ROOT = tmp_path
    model = ImportDefinition if direction == 'import' else ExportDefinition
    definition = model.objects.create(
        name=f'{direction} books',
        target=_target(),
    )
    if direction == 'import':
        definition.columns_exclude = [
            path for path in default_importable_column_paths(Book)
            if path != 'title'
        ]
        definition.save()
        attach_import_spreadsheet(definition)
    else:
        attach_tabular_export(export=definition, columns=['title'])
    url = reverse(f'admin:django_importexport_flow_{direction}request_add')
    page = admin_client.get(url)
    assert 'name="run_async"' in page.content.decode()
    inline = page.context['inline_admin_formsets'][0].formset.prefix
    data = {
        f'{direction}_definition': str(definition.pk),
        'filter_payload': '{}',
        f'{inline}-TOTAL_FORMS': '0',
        f'{inline}-INITIAL_FORMS': '0',
        f'{inline}-MIN_NUM_FORMS': '0',
        f'{inline}-MAX_NUM_FORMS': '1000',
    }
    if direction == 'import':
        data['data_file'] = SimpleUploadedFile(
            'books.csv', b'title\nNew book\n'
        )
    else:
        data.update(
            export_format='csv',
            manager_kwargs_payload='{}',
            configuration_overrides='{}',
        )

    response = admin_client.post(url, data)

    assert response.status_code == 302, (
        response.context['adminform'].form.errors
    )
    request_model = ImportRequest if direction == 'import' else ExportRequest
    result = request_model.objects.get()
    assert getattr(result, f'{direction}_definition_id') == definition.pk
    assert result.status == request_model.Status.SUCCESS, result.error_trace


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('direction', 'definition_model'),
    [('import', ImportDefinition), ('export', ExportDefinition)],
)
def test_admin_excluded_relations_dual_list_saves(
    direction, definition_model, admin_client
):
    definition = definition_model.objects.create(name='Definition')
    response = admin_client.get(
        reverse(
            f'admin:django_importexport_flow_{direction}definition_change',
            args=[definition.pk],
        ),
    )

    assert response.status_code == 200
    form = response.context['adminform'].form
    widget = form.fields['exclude_relations'].widget
    assert isinstance(widget.widget, FilteredSelectMultiple)
    data = model_to_dict(definition, fields=form.fields)
    for name, field in form.fields.items():
        if isinstance(field, forms.JSONField):
            data[name] = json.dumps(data.get(name))
    data['exclude_relations'] = [str(_target().pk)]
    bound = form.__class__(data=data, instance=definition)
    assert bound.is_valid(), bound.errors
    bound.save()
    assert list(definition.exclude_relations.all()) == [_target()]


@pytest.mark.django_db
def test_header_aliases_do_not_resolve_and_catalogs_are_batched():
    with patch("django_importexport_flow.utils.translations.resolve_column_header") as resolve:
        aliases = import_header_aliases(Book, "title")
        resolve.assert_not_called()
    assert "title" in aliases

    paths = default_importable_column_paths(Book)
    with CaptureQueriesContext(connection) as captured:
        catalogs_for_paths(Book, paths)
    assert captured.captured_queries
    assert len(captured) < len(paths)


@pytest.mark.django_db
def test_serialization_uses_concrete_models_and_rejects_proxy_names():
    definition = ExportDefinition.objects.create(
        name="Serialized export",
        target=_target(),
        manager="objects",
    )
    sheet = ExportSpreadsheetConfig.objects.create(definition=definition, columns=["title"])
    ExportCsvFormat.objects.create(category_config=sheet)
    payload = serialize_export_configuration(definition)
    assert {item["model"] for item in payload["objects"]} <= _CONCRETE_MODELS
    payload["objects"][0]["model"] = "django_importexport_flow.exportdefinition"
    with pytest.raises(ValueError, match="Old payloads"):
        import_export_configuration(payload)


@pytest.mark.django_db
def test_proxy_admins_are_filtered_and_workflows_stay_separate(admin_user, client):
    export_row = ExportDefinition.objects.create(
        name="Visible export",
        target=_target(),
        manager="objects",
    )
    import_row = ImportDefinition.objects.create(name="Visible import", target=_target())
    sheet = ExportSpreadsheetConfig.objects.create(definition=export_row, columns=["title"])
    imported = ImportSpreadsheetConfig.objects.create(definition=import_row)
    csv_format = ExportCsvFormat.objects.create(category_config=sheet)
    ImportExcelFormat.objects.create(category_config=imported)
    client.force_login(admin_user)

    index = client.get(reverse("admin:index")).content.decode()
    for label in (
        "Export definitions",
        "Import definitions",
        "Export configs",
        "Import configs",
        "Export formats",
        "Import formats",
        "Export requests",
        "Import requests",
        "Column translations",
    ):
        assert label in index
    assert "Config spreadsheets" not in index
    assert "Format CSV" not in index

    export_list = client.get(reverse("admin:django_importexport_flow_exportdefinition_changelist"))
    assert export_list.status_code == 200
    export_body = export_list.content.decode()
    assert "Visible export" in export_body
    assert "Visible import" not in export_body

    sheet_list = client.get(
        reverse("admin:django_importexport_flow_exportcategoryconfig_changelist")
    ).content.decode()
    assert "Visible export" in sheet_list
    assert "Visible import" not in sheet_list

    export_change = client.get(
        reverse("admin:django_importexport_flow_exportdefinition_change", args=[export_row.pk])
    ).content.decode()
    sheet_url = reverse(
        "admin:django_importexport_flow_exportcategoryconfig_change",
        args=[sheet.pk],
    )
    assert sheet_url in export_change
    assert 'name="direction"' not in export_change
    assert "module aligned collapse" in export_change
    assert "category_configs-0-format_configs-0-format_key" in export_change
    assert "import_tabular_data" not in export_change

    format_url = reverse(
        "admin:django_importexport_flow_exportformatconfig_change",
        args=[csv_format.pk],
    )
    assert format_url in sheet_list
    formats_url = reverse("admin:django_importexport_flow_exportformatconfig_changelist")
    assert "Visible export" in client.get(f"{formats_url}?category=spreadsheet").content.decode()
    assert "Visible export" not in client.get(f"{formats_url}?format=pdf").content.decode()
    definitions_url = reverse("admin:django_importexport_flow_exportdefinition_changelist")
    assert "Visible export" in client.get(f"{definitions_url}?format=csv").content.decode()
    assert (
        "Visible import"
        not in client.get(f"{definitions_url}?category=spreadsheet").content.decode()
    )

    with pytest.raises(NoReverseMatch):
        reverse("admin:django_importexport_flow_definition_change", args=[export_row.pk])
    with pytest.raises(NoReverseMatch):
        reverse("admin:django_importexport_flow_definition_process_export", args=[export_row.pk])
    with pytest.raises(NoReverseMatch):
        reverse(
            "admin:django_importexport_flow_importdefinition_process_export",
            args=[import_row.pk],
        )
    reverse(
        "admin:django_importexport_flow_importdefinition_download_example_file",
        args=[import_row.pk],
    )
    assert Permission.objects.filter(codename="change_exportdefinition").exists()
    assert Permission.objects.filter(codename="change_importcsvformat").exists()
