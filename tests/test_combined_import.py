import pytest
from django.contrib.admin.widgets import (
    FilteredSelectMultiple,
    ForeignKeyRawIdWidget,
)
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from django_importexport_flow.engine.core.processor import ImportProcessorResult
from django_importexport_flow.engine.core.run import relaunch_import_request
from django_importexport_flow.models import (
    Definition,
    ExportDefinition,
    ImportDefinition,
    ImportRequest,
    Step,
)
from django_importexport_flow.utils.process import process_import
from django_importexport_flow.tasks import execute_import_request_by_uuid
from django_importexport_flow.utils.serialization import (
    import_import_definition,
    serialize_import_definition,
)
from tests.sample.models import Author
from tests.support import attach_import_spreadsheet


def _processor(file, context):
    content = file.read().decode()
    if content != 'name\nFirst\n':
        return ImportProcessorResult(errors=['Unexpected upload'])
    if (
        not context.preview_only
        and not Author.objects.filter(name='First').exists()
    ):
        return ImportProcessorResult(errors=['Missing previous step'])
    Author.objects.create(name=context.definition.name)
    if context.filter_payload.get('reject'):
        return ImportProcessorResult(errors=['Rejected'])
    if context.filter_payload.get('raise'):
        raise ValueError('Processor failed')
    return ImportProcessorResult(imported_row_count=1)


@pytest.fixture
def combined(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    settings.DJANGO_IMPORTEXPORT_FLOW = {
        'ALLOWED_HOOK_MODULE_PREFIXES': ['tests.test_combined_import'],
    }
    target = ContentType.objects.get_for_model(Author)
    parent = Definition.objects.create(
        direction='import', name='Combined', target=target
    )
    first = Definition.objects.create(
        direction='import', name='First step', target=target
    )
    second = Definition.objects.create(
        direction='import', name='Second step', target=target
    )
    attach_import_spreadsheet(parent)
    attach_import_spreadsheet(first)
    attach_import_spreadsheet(
        second,
        {'import_processor': 'tests.test_combined_import._processor'},
    )
    Step.objects.create(parent=parent, definition=second, position=20)
    Step.objects.create(parent=parent, definition=first, position=10)
    return parent, first, second


def _upload():
    return SimpleUploadedFile('import.csv', b'name\nFirst\n')


@pytest.mark.django_db
def test_combined_preview_is_single_and_does_not_write(combined):
    parent, _, _ = combined

    result = process_import(
        file=_upload(), import_definition=parent, preview_only=True
    )

    assert not result['errors']
    assert result['validation_dataset']['rows'] == [{'name': 'First'}]
    assert [step['position'] for step in result['steps']] == [10, 20]
    assert not Author.objects.exists()
    assert not ImportRequest.objects.exists()


@pytest.mark.django_db
def test_combined_runs_generic_and_processor_in_order(combined):
    parent, _, _ = combined

    result = process_import(file=_upload(), import_definition=parent)

    assert result['success'], result['import_request'].error_trace
    assert result['import_request'].imported_row_count == 2
    assert set(Author.objects.values_list('name', flat=True)) == {
        'First',
        'Second step',
    }


@pytest.mark.django_db
def test_definition_managers_annotate_current_step_count(combined):
    parent, first, _ = combined
    export = Definition.objects.create(direction='export', name='Export')

    for manager in (Definition.objects, ImportDefinition.objects):
        counts = {
            definition.pk: definition.step_count
            for definition in manager.filter(pk__in=[parent.pk, first.pk])
        }
        assert counts == {parent.pk: 2, first.pk: 0}
    filtered = Definition.objects.filter(
        pk=parent.pk,
        steps__position__gte=0,
    ).get()
    assert filtered.step_count == 2
    assert ExportDefinition.objects.get(pk=export.pk).step_count == 0


@pytest.mark.django_db
def test_admin_import_changelist_displays_and_orders_step_counts(
    combined, admin_client
):
    parent, first, second = combined
    url = reverse('admin:django_importexport_flow_importdefinition_changelist')
    response = admin_client.get(url)

    assert response.status_code == 200
    content = response.content.decode()
    assert 'class="field-steps_label">2</td>' in content
    assert content.count('class="field-steps_label">0</td>') == 2

    column = response.context['cl'].list_display.index('steps_label')
    sorted_response = admin_client.get(url, {'o': str(column)})
    ordered = [obj.pk for obj in sorted_response.context['cl'].result_list]
    assert set(ordered[:2]) == {first.pk, second.pk}
    assert ordered[2:] == [parent.pk]


@pytest.mark.django_db
def test_admin_step_raw_id_lookup_uses_import_definitions(combined, admin_client):
    parent, first, _ = combined
    export = ExportDefinition.objects.create(name='Export')
    url = reverse(
        'admin:django_importexport_flow_importdefinition_change',
        args=[parent.pk],
    )
    response = admin_client.get(url)
    assert response.status_code == 200
    assert isinstance(
        response.context['adminform']
        .form.fields['exclude_relations']
        .widget.widget,
        FilteredSelectMultiple,
    )
    inline = next(
        inline for inline in response.context['inline_admin_formsets']
        if inline.opts.model is Step
    )
    field = inline.formset.forms[0].fields['definition']
    assert isinstance(field.widget, ForeignKeyRawIdWidget)
    assert field.clean(first.pk).pk == first.pk
    context = field.widget.get_context('definition', first.pk, {})
    assert context['related_url'].startswith(
        reverse('admin:django_importexport_flow_importdefinition_changelist')
    )
    assert context['link_url'] == reverse(
        'admin:django_importexport_flow_importdefinition_change',
        args=[first.pk],
    )
    lookup = admin_client.get(context['related_url'] + '&_popup=1')
    assert lookup.status_code == 200
    assert first.pk in {obj.pk for obj in lookup.context['cl'].result_list}
    assert export.pk not in {obj.pk for obj in lookup.context['cl'].result_list}
    with pytest.raises(ValidationError):
        field.clean(export.pk)


@pytest.mark.django_db
def test_import_uses_current_step_count_when_annotation_is_stale(combined):
    parent, first, second = combined
    parent.steps.all().delete()
    stale = Definition.objects.get(pk=parent.pk)
    assert stale.step_count == 0
    Step.objects.create(parent=parent, definition=first, position=10)
    Step.objects.create(parent=parent, definition=second, position=20)

    preview = process_import(
        file=_upload(),
        import_definition=stale,
        preview_only=True,
    )
    result = process_import(file=_upload(), import_definition=stale)

    assert len(preview['steps']) == 2
    assert result['success'], result['import_request'].error_trace
    assert result['import_request'].imported_row_count == 2


@pytest.mark.django_db
@pytest.mark.parametrize('flag', ['reject', 'raise'])
def test_combined_rolls_back_all_steps_on_failure(combined, flag):
    parent, _, _ = combined

    result = process_import(
        file=_upload(),
        import_definition=parent,
        filter_payload={flag: True},
    )

    assert not result['success']
    assert result['import_request'].status == ImportRequest.Status.FAILURE
    assert result['import_request'].imported_row_count in (0, None)
    assert 'Second step' in result['import_request'].error_trace
    assert not Author.objects.exists()


@pytest.mark.django_db
def test_combined_import_rejects_nested_steps(combined):
    parent, first, _ = combined
    another = Definition.objects.create(direction='import', name='Another')

    with pytest.raises(ValidationError, match='Nested combined imports'):
        Step(parent=first, definition=another, position=1).clean()
    with pytest.raises(ValidationError, match='itself'):
        Step(parent=parent, definition=parent, position=1).clean()


@pytest.mark.django_db
def test_removing_all_steps_restores_single_import(combined):
    parent, _, _ = combined
    parent.steps.all().delete()

    result = process_import(
        file=_upload(),
        import_definition=parent,
        inferred_column_paths=['name'],
    )

    assert result['success']
    assert list(Author.objects.values_list('name', flat=True)) == ['First']


@pytest.mark.django_db
def test_combined_preview_reports_step_errors(combined):
    parent, _, _ = combined

    result = process_import(
        file=_upload(),
        import_definition=parent,
        preview_only=True,
        filter_payload={'reject': True},
    )

    assert result['errors'] == ['Second step: Rejected']
    assert result['steps'][1]['errors'] == ['Rejected']
    assert not Author.objects.exists()


@pytest.mark.django_db
def test_combined_configuration_roundtrip(combined):
    parent, first, second = combined
    payload = serialize_import_definition(parent)
    parent.steps.all().delete()

    restored = import_import_definition(payload)

    assert list(restored.steps.values_list('definition_id', 'position')) == [
        (first.pk, 10),
        (second.pk, 20),
    ]


@pytest.mark.django_db
def test_configuration_import_missing_step_preserves_existing_steps(combined):
    parent, first, second = combined
    payload = serialize_import_definition(parent)
    payload['steps'][1]['definition'] = 'missing-definition'

    with pytest.raises(ValueError, match='not found'):
        import_import_definition(payload)

    assert list(parent.steps.values_list('definition_id', 'position')) == [
        (first.pk, 10),
        (second.pk, 20),
    ]


@pytest.mark.django_db(transaction=True)
def test_combined_relaunch_uses_the_same_file_and_options(
    combined, auditor_user
):
    parent, _, _ = combined
    result = process_import(
        file=_upload(),
        import_definition=parent,
        user=auditor_user,
        filter_payload={'reject': True},
    )
    retry = relaunch_import_request(result['import_request'], auditor_user)

    execute_import_request_by_uuid(str(retry.uuid))

    retry.refresh_from_db()
    assert retry.status == ImportRequest.Status.FAILURE
    assert 'Second step: Rejected' in retry.error_trace
    assert not Author.objects.exists()


@pytest.mark.django_db
def test_combined_admin_has_one_preview_and_confirms(
    client, combined, django_user_model
):
    parent, _, _ = combined
    user = django_user_model.objects.create_superuser(
        'admin', password='secret'
    )
    client.force_login(user)
    url = reverse(
        'admin:django_importexport_flow_importdefinition_import_tabular_data',
        args=[parent.pk],
    )

    uploaded = client.post(url, {'step': 'upload', 'file': _upload()})
    preview = client.get(uploaded['Location'])

    assert preview.status_code == 200
    assert b'First' in preview.content
    assert not Author.objects.exists()
    request = ImportRequest.objects.get()
    confirmed = client.post(
        url,
        {'step': 'confirm', 'import_request_uuid': str(request.uuid)},
    )
    assert confirmed.status_code == 302
    request.refresh_from_db()
    assert request.status == ImportRequest.Status.SUCCESS
    assert request.imported_row_count == 2
