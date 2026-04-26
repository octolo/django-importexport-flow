"""Tests for the ``delegate_method`` field on export and import definitions."""

from __future__ import annotations

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from django_importexport_flow.engine.core.delegate import (
    build_delegate_kwargs,
    call_delegate,
    has_delegate,
    resolve_delegate_method,
)
from django_importexport_flow.models import (
    ExportConfigTable,
    ExportDefinition,
    ImportDefinition,
)
from django_importexport_flow.utils.process import process_export, process_import
from tests.sample.models import Book


_LAST_EXPORT_KWARGS: dict | None = None
_LAST_IMPORT_KWARGS: dict | None = None


def _export_delegate(**kwargs):
    global _LAST_EXPORT_KWARGS
    _LAST_EXPORT_KWARGS = kwargs
    return b"DELEGATED", "text/plain", ".txt"


def _import_delegate(**kwargs):
    global _LAST_IMPORT_KWARGS
    _LAST_IMPORT_KWARGS = kwargs
    return {
        "delegated": True,
        "rows": kwargs.get("file"),
        "match_fields": kwargs.get("match_fields"),
    }


Book.export_via_delegate = staticmethod(_export_delegate)
Book.import_via_delegate = staticmethod(_import_delegate)


class _NestedNamespace:
    pass


_nested_export_ns = _NestedNamespace()
_nested_export_ns.inner = _NestedNamespace()
_nested_export_ns.inner.run = staticmethod(_export_delegate)
Book.nested_export = _nested_export_ns


@pytest.fixture(autouse=True)
def _reset_kwargs():
    global _LAST_EXPORT_KWARGS, _LAST_IMPORT_KWARGS
    _LAST_EXPORT_KWARGS = None
    _LAST_IMPORT_KWARGS = None
    yield


def test_resolve_delegate_method_resolves_dotted_path():
    method = resolve_delegate_method(Book, "export_via_delegate")
    assert method is _export_delegate


def test_resolve_delegate_method_walks_multiple_hops():
    method = resolve_delegate_method(Book, "nested_export.inner.run")
    assert callable(method)
    assert method() == (b"DELEGATED", "text/plain", ".txt")


@pytest.mark.django_db
def test_export_delegate_invokes_multi_hop_path():
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition.objects.create(
        name="DeepDelegate",
        target=ct,
        delegate_method="nested_export.inner.run",
    )
    body, content_type, ext = process_export(
        export_definition=definition,
        filter_payload={"export_format": "csv"},
    )
    assert (body, content_type, ext) == (b"DELEGATED", "text/plain", ".txt")
    assert _LAST_EXPORT_KWARGS is not None
    assert _LAST_EXPORT_KWARGS["delegate_method"] == "nested_export.inner.run"
    assert _LAST_EXPORT_KWARGS["export_format"] == "csv"


def test_resolve_delegate_method_rejects_unknown_path():
    with pytest.raises(ValidationError):
        resolve_delegate_method(Book, "does_not_exist")


def test_resolve_delegate_method_rejects_non_callable():
    with pytest.raises(ValidationError):
        resolve_delegate_method(Book, "_meta")


@pytest.mark.django_db
def test_has_delegate_reflects_field_value():
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition(
        name="x", target=ct, manager="objects", delegate_method="export_via_delegate"
    )
    assert has_delegate(definition) is True
    definition.delegate_method = ""
    assert has_delegate(definition) is False


@pytest.mark.django_db
def test_export_delegate_skips_orm_validation_and_forwards_kwargs():
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition.objects.create(
        name="DelegatedExport",
        target=ct,
        manager="not.a.valid.path",
        filter_request={"q": "ignored_unknown_lookup"},
        delegate_method="export_via_delegate",
    )

    body, content_type, ext = process_export(
        export_definition=definition,
        filter_payload={"export_format": "json", "fr_get_q": "abc"},
    )

    assert (body, content_type, ext) == (b"DELEGATED", "text/plain", ".txt")
    assert _LAST_EXPORT_KWARGS is not None
    assert _LAST_EXPORT_KWARGS["delegate_method"] == "export_via_delegate"
    assert _LAST_EXPORT_KWARGS["manager"] == "not.a.valid.path"
    assert _LAST_EXPORT_KWARGS["filter_request"] == {"q": "ignored_unknown_lookup"}
    assert _LAST_EXPORT_KWARGS["fr_get_q"] == "abc"
    assert _LAST_EXPORT_KWARGS["export_format"] == "json"


@pytest.mark.django_db
def test_import_delegate_skips_validation_and_forwards_kwargs():
    ct = ContentType.objects.get_for_model(Book)
    definition = ImportDefinition.objects.create(
        name="DelegatedImport",
        target=ct,
        match_fields=["title"],
        filter_request={"q": "ignored_unknown_lookup"},
        delegate_method="import_via_delegate",
    )

    out = process_import(
        import_definition=definition,
        file=b"FAKE",
        filter_payload={"fr_get_q": "abc"},
        user=None,
    )

    assert out == {
        "delegated": True,
        "rows": b"FAKE",
        "match_fields": ["title"],
    }
    assert _LAST_IMPORT_KWARGS is not None
    assert _LAST_IMPORT_KWARGS["fr_get_q"] == "abc"
    assert _LAST_IMPORT_KWARGS["preview_only"] is False


@pytest.mark.django_db
def test_export_clean_rejects_unresolvable_delegate():
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition(
        name="bad",
        target=ct,
        delegate_method="objects.does_not_exist",
    )
    with pytest.raises(ValidationError) as exc_info:
        definition.full_clean()
    assert "delegate_method" in exc_info.value.message_dict


@pytest.mark.django_db
def test_import_clean_rejects_unresolvable_delegate():
    ct = ContentType.objects.get_for_model(Book)
    definition = ImportDefinition(
        name="bad",
        target=ct,
        delegate_method="missing",
    )
    with pytest.raises(ValidationError) as exc_info:
        definition.full_clean()
    assert "delegate_method" in exc_info.value.message_dict


@pytest.mark.django_db
def test_build_delegate_kwargs_skips_audit_fields_and_includes_m2m():
    ct = ContentType.objects.get_for_model(Book)
    definition = ExportDefinition.objects.create(
        name="kw",
        target=ct,
        manager="objects",
    )
    ExportConfigTable.objects.create(export=definition, columns=["title"], configuration={})

    kwargs = build_delegate_kwargs(definition, {"export_format": "json"}, file=b"x")

    assert "uuid" not in kwargs
    assert "created_by" not in kwargs
    assert "updated_at" not in kwargs
    assert kwargs["name"] == "kw"
    assert kwargs["manager"] == "objects"
    assert kwargs["export_format"] == "json"
    assert kwargs["file"] == b"x"
    assert kwargs["exclude_relations"] == []


@pytest.mark.django_db
def test_call_delegate_requires_target_model():
    definition = ExportDefinition(name="no_target", delegate_method="anything")
    with pytest.raises(ValidationError):
        call_delegate(definition, None)
