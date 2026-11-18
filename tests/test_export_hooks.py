"""Format hooks: the native hook is the default, and a config can replace or wrap it."""

from __future__ import annotations

import pytest
from django.contrib.contenttypes.models import ContentType

from django_importexport_flow.engine.core.formats import get_export_config
from django_importexport_flow.engine.hooks import native_csv_export, native_json_export
from django_importexport_flow.models import Definition
from django_importexport_flow.utils.process import process_export
from tests.sample.models import Book
from tests.support import attach_tabular_export


def wrap_json(dataset, category_config, format_config, payload):
    body, content_type, extension = native_json_export(
        dataset, category_config, format_config, payload
    )
    return b"wrapped:" + body, content_type, extension


def replace_export(dataset, category_config, format_config, payload):
    return b"replaced", "text/plain", ".txt"


def stamp(dataset, category_config, format_config, payload):
    dataset.payload["stamped"] = True
    return dataset


def finish(dataset, category_config, format_config, payload):
    assert dataset.payload["stamped"] is True
    return b"chained", "text/plain", ".txt"


def boom(dataset, category_config, format_config, payload):
    raise RuntimeError("hook failed")


@pytest.mark.django_db
def test_empty_hook_uses_the_native_generator():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export", name="Native hook", target=ct, manager="objects"
    )
    attach_tabular_export(export=definition, columns=["title"], configuration={})
    Book.objects.create(title="Row", pages=1)
    config = get_export_config(definition, "json")
    assert config.hook == []
    assert config.get_effective_hooks() == [
        "django_importexport_flow.engine.hooks.native_json_export"
    ]
    body, content_type, extension = process_export(
        export_definition=definition,
        export_format="json",
    )
    assert b"Row" in body
    assert content_type.startswith("application/json")
    assert extension == ".json"


@pytest.mark.django_db
def test_hook_list_runs_in_order():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export", name="Chain", target=ct, manager="objects"
    )
    attach_tabular_export(export=definition, columns=["title"], configuration={})
    Book.objects.create(title="Row", pages=1)
    config = get_export_config(definition, "csv")
    config.hook = [
        "tests.test_export_hooks.stamp",
        "tests.test_export_hooks.finish",
    ]
    config.save()
    body, content_type, extension = process_export(
        export_definition=definition,
        export_format="csv",
    )
    assert body == b"chained"
    assert content_type == "text/plain"
    assert extension == ".txt"


@pytest.mark.django_db
def test_hook_override_replaces_only_that_format():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export", name="Categories", target=ct, manager="objects"
    )
    attach_tabular_export(export=definition, columns=["title"], configuration={})
    Book.objects.create(title="Row", pages=1)
    excel = get_export_config(definition, "excel")
    excel.hook = "tests.test_export_hooks.replace_export"
    excel.save()
    replaced, content_type, extension = process_export(
        export_definition=definition,
        export_format="xlsx",
    )
    body, _content_type, json_ext = process_export(
        export_definition=definition,
        export_format="json",
    )
    assert replaced == b"replaced"
    assert content_type == "text/plain"
    assert extension == ".txt"
    assert b"Row" in body
    assert json_ext == ".json"


@pytest.mark.django_db
def test_export_hook_can_wrap_the_native_generator():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export", name="Hooked", target=ct, manager="objects"
    )
    attach_tabular_export(export=definition, columns=["title"], configuration={})
    Book.objects.create(title="Hooked title", pages=1)
    config = get_export_config(definition, "json")
    config.hook = "tests.test_export_hooks.wrap_json"
    config.save()
    definition = Definition.objects.get(pk=definition.pk)
    body, content_type, extension = process_export(
        export_definition=definition,
        export_format="json",
    )
    assert body.startswith(b"wrapped:")
    assert b"Hooked title" in body
    assert content_type.startswith("application/json")
    assert extension == ".json"


_CAPTURED: dict = {}


def capture(dataset, category_config, format_config, payload):
    _CAPTURED["titles"] = list(dataset.queryset.values_list("title", flat=True))
    _CAPTURED["labels"] = list(dataset.labels)
    return native_csv_export(dataset, category_config, format_config, payload)


@pytest.mark.django_db
def test_export_hook_runs_after_the_dataset_is_loaded():
    _CAPTURED.clear()
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export", name="Loaded", target=ct, manager="objects"
    )
    attach_tabular_export(export=definition, columns=["title"], configuration={})
    Book.objects.create(title="Already loaded", pages=1)
    config = get_export_config(definition, "csv")
    config.hook = "tests.test_export_hooks.capture"
    config.save()
    definition = Definition.objects.get(pk=definition.pk)
    body, _content_type, extension = process_export(
        export_definition=definition,
        export_format="csv",
    )
    assert _CAPTURED["titles"] == ["Already loaded"]
    assert _CAPTURED["labels"]
    assert b"Already loaded" in body
    assert extension == ".csv"


@pytest.mark.django_db
def test_missing_format_config_disables_that_format():
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export", name="Csv only", target=ct, manager="objects"
    )
    attach_tabular_export(
        export=definition,
        columns=["title"],
        configuration={},
        formats=("csv",),
    )
    with pytest.raises(ValueError, match="not enabled"):
        process_export(export_definition=definition, export_format="json")


@pytest.mark.django_db
def test_persisted_export_records_the_hook_result(auditor_user):
    from django_importexport_flow.models import ExportRequest
    from django_importexport_flow.utils.process import run_export_with_audit

    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export", name="Audited hook", target=ct, manager="objects"
    )
    attach_tabular_export(export=definition, columns=["title"], formats=("csv",))
    Book.objects.create(title="Audited", pages=1)
    config = get_export_config(definition, "csv")
    config.hook = ["tests.test_export_hooks.replace_export"]
    config.save()

    content, content_type, extension = run_export_with_audit(
        export_definition=definition,
        filter_payload={"export_format": "csv"},
        user=auditor_user,
    )
    request = ExportRequest.objects.get()
    assert content == b"replaced"
    assert content_type == "text/plain"
    assert extension == ".txt"
    assert request.status == ExportRequest.Status.SUCCESS
    assert request.output_bytes == len(b"replaced")
    assert request.output_file


@pytest.mark.django_db
def test_persisted_export_records_hook_failure(auditor_user):
    from django_importexport_flow.models import ExportRequest
    from django_importexport_flow.utils.process import run_export_with_audit

    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export", name="Failing hook", target=ct, manager="objects"
    )
    attach_tabular_export(export=definition, columns=["title"], formats=("csv",))
    config = get_export_config(definition, "csv")
    config.hook = ["tests.test_export_hooks.boom"]
    config.save()

    with pytest.raises(RuntimeError, match="hook failed"):
        run_export_with_audit(
            export_definition=definition,
            filter_payload={"export_format": "csv"},
            user=auditor_user,
        )
    request = ExportRequest.objects.get()
    assert request.status == ExportRequest.Status.FAILURE
    assert "hook failed" in request.error_trace
    assert request.output_bytes in (None, 0)


def capture_request_options(dataset, category_config, format_config, payload):
    _CAPTURED["template"] = dataset.engine.get_template()
    _CAPTURED["template_override"] = payload["template_override"]
    _CAPTURED["hook"] = dict(payload["configuration_overrides"]["hook"])
    payload["configuration_overrides"]["hook"]["mutated"] = True
    return b"captured", "text/plain", ".txt"


@pytest.mark.django_db
def test_request_options_reach_the_hook_without_changing_stored_configuration():
    from django.core.exceptions import ValidationError

    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export", name="Request options", target=ct, manager="objects"
    )
    attach_tabular_export(
        export=definition,
        columns=["title", "pages"],
        configuration={"delimiter": ","},
        formats=("csv", "excel", "json"),
    )
    Book.objects.create(title="Row", pages=2)
    csv_config = get_export_config(definition, "csv")
    stored = dict(csv_config.configuration)

    body, _content_type, extension = process_export(
        export_definition=definition,
        export_format="csv",
        configuration_overrides={"format": {"delimiter": ";"}, "hook": {"company_id": 42}},
    )
    assert extension == ".csv"
    assert b"Book title;Nb. of pages" in body
    csv_config.refresh_from_db()
    assert csv_config.configuration == stored

    excel, _excel_type, excel_ext = process_export(
        export_definition=definition,
        export_format="excel",
        configuration_overrides={"format": {"sheet": "Company"}},
    )
    from io import BytesIO

    from openpyxl import load_workbook

    workbook = load_workbook(BytesIO(excel))
    assert excel_ext == ".xlsx"
    assert workbook.sheetnames == ["Company"]

    raw, _json_type, json_ext = process_export(
        export_definition=definition,
        export_format="json",
        configuration_overrides={"format": {"indent": 2, "force_ascii": False}},
    )
    assert json_ext == ".json"
    assert b"\n" in raw

    with pytest.raises(ValidationError, match="not allowed"):
        process_export(
            export_definition=definition,
            export_format="csv",
            configuration_overrides={"format": {"sheet": "Nope"}},
        )
    with pytest.raises(ValidationError, match="Unknown configuration"):
        process_export(
            export_definition=definition,
            export_format="csv",
            configuration_overrides={"columns": ["title"]},
        )


@pytest.mark.django_db
def test_pdf_template_override_replaces_only_the_request_template():
    from django.core.exceptions import ValidationError

    from django_importexport_flow.engine.core.formats import get_export_config as pdf_config
    from tests.support import attach_pdf_export

    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export", name="PDF override", target=ct, manager="objects"
    )
    attach_pdf_export(export=definition, template="<p>stored</p>")
    config = pdf_config(definition, "pdf")
    config.hook = ["tests.test_export_hooks.capture_request_options"]
    config.save()

    process_export(export_definition=definition, export_format="pdf")
    assert _CAPTURED["template"] == "<p>stored</p>"
    assert _CAPTURED["template_override"] == ""

    _CAPTURED.clear()
    process_export(
        export_definition=definition,
        export_format="pdf",
        template_override="<p>{{ company }}</p>",
        configuration_overrides={"hook": {"company_id": 7}},
    )
    assert _CAPTURED["template"] == "<p>{{ company }}</p>"
    assert _CAPTURED["hook"] == {"company_id": 7}
    config.refresh_from_db()
    assert config.template == "<p>stored</p>"

    with pytest.raises(ValidationError, match="only valid for PDF"):
        process_export(
            export_definition=definition,
            export_format="csv",
            template_override="<p>nope</p>",
        )


def _csv_definition(name: str):
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="export", name=name, target=ct, manager="objects"
    )
    attach_tabular_export(export=definition, columns=["title"], configuration={}, formats=("csv",))
    Book.objects.create(title="Row", pages=1)
    return definition


@pytest.mark.django_db
def test_format_config_full_clean_honors_the_hook_allowlist(settings):
    from django.core.exceptions import ValidationError

    definition = _csv_definition("Allowlist clean")
    config = get_export_config(definition, "csv")
    config.hook = ["tests.test_export_hooks.stamp", "tests.test_export_hooks.finish"]
    settings.DJANGO_IMPORTEXPORT_FLOW = {"ALLOWED_HOOK_MODULE_PREFIXES": None}
    config.full_clean()
    settings.DJANGO_IMPORTEXPORT_FLOW = {
        "ALLOWED_HOOK_MODULE_PREFIXES": ["tests.test_export_hooks"]
    }
    config.full_clean()
    config.save()
    body, _content_type, extension = process_export(
        export_definition=definition, export_format="csv"
    )
    assert body == b"chained"
    assert extension == ".txt"
    settings.DJANGO_IMPORTEXPORT_FLOW = {"ALLOWED_HOOK_MODULE_PREFIXES": []}
    with pytest.raises(ValidationError):
        config.full_clean()


@pytest.mark.django_db
def test_saved_hook_is_rejected_at_runtime_when_the_allowlist_changes(settings):
    from django.core.exceptions import ValidationError

    from django_importexport_flow.models import FormatConfig

    definition = _csv_definition("Stale hook")
    config = get_export_config(definition, "csv")
    config.hook = ["tests.test_export_hooks.replace_export"]
    config.save()
    settings.DJANGO_IMPORTEXPORT_FLOW = {"ALLOWED_HOOK_MODULE_PREFIXES": []}
    FormatConfig.objects.filter(pk=config.pk).update(
        hook=["tests.test_export_hooks.replace_export"]
    )
    with pytest.raises(ValidationError, match="outside the allowed"):
        process_export(export_definition=definition, export_format="csv")


@pytest.mark.django_db
def test_empty_allowlist_still_runs_the_native_hook(settings):
    definition = _csv_definition("Native under empty list")
    settings.DJANGO_IMPORTEXPORT_FLOW = {"ALLOWED_HOOK_MODULE_PREFIXES": []}
    body, content_type, extension = process_export(
        export_definition=definition, export_format="csv"
    )
    assert b"Row" in body
    assert content_type.startswith("text/csv")
    assert extension == ".csv"
