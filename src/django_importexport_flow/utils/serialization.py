"""JSON export and import for export and import definitions."""

from __future__ import annotations

import copy
import json
from typing import Any

from django.core import serializers
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from ..models import Definition
from .helpers import get_setting

FORMAT_VERSION = get_setting("SERIALIZATION_FORMAT_VERSION")

_DEFINITION_MODEL = "django_importexport_flow.definition"

_RETIRED_SUFFIXES = frozenset(
    {
        "exportconfigtable",
        "exportconfigpdf",
        "reportconfigtable",
        "reportconfigpdf",
        "reportimport",
        "reportdefinition",
        "exportdefinition",
        "importdefinition",
        "exportspreadsheet",
        "exportdocument",
        "exportstructureddata",
        "importspreadsheet",
        "importstructureddata",
        "configcsv",
        "configexcel",
        "configjson",
        "configpdf",
        "configods",
        "configword",
        "configxml",
        "importconfigcsv",
        "importconfigexcel",
        "exportcategoryconfig",
        "importcategoryconfig",
        "exportspreadsheetconfig",
        "exportdocumentconfig",
        "exportstructureddataconfig",
        "importspreadsheetconfig",
        "importstructureddataconfig",
        "exportformatconfig",
        "importformatconfig",
        "exportcsvformat",
        "exportexcelformat",
        "exportjsonformat",
        "exportpdfformat",
        "importcsvformat",
        "importexcelformat",
        "columnlabel",
    }
)

_PARENT_FK_FIELDS = ("definition", "category_config")
_IGNORED_V2_FIELDS = {
    "django_importexport_flow.definition": ("delegate_method",),
    "django_importexport_flow.formatconfig": (
        "processing_backend",
        "processing_backend_kwargs",
    ),
}


def _reject_old_payload(objects: list[dict[str, Any]]) -> None:
    for obj in objects:
        model = obj.get("model")
        if not isinstance(model, str):
            continue
        suffix = model.rsplit(".", 1)[-1]
        if suffix in _RETIRED_SUFFIXES or model.startswith(
            ("django_reporting.", "django_reportimport.", "django_exportimport.")
        ):
            raise ValueError(_("Old payloads are not accepted."))


def _require_current_payload(data: dict[str, Any]) -> list[dict[str, Any]]:
    if data.get("format_version") != FORMAT_VERSION:
        raise ValueError(
            _("Unsupported format_version (expected %(exp)s). Old payloads are not accepted.")
            % {"exp": FORMAT_VERSION}
        )
    objects = data.get("objects")
    if not isinstance(objects, list):
        raise ValueError(_("Invalid payload: 'objects' must be a list."))
    objects = copy.deepcopy(objects)
    _reject_old_payload(objects)
    _drop_retired_fields(objects)
    return objects


def _drop_retired_fields(objects: list[dict[str, Any]]) -> None:
    for obj in objects:
        fields = obj.get("fields")
        if not isinstance(fields, dict):
            continue
        for name in _IGNORED_V2_FIELDS.get(str(obj.get("model")), ()):
            fields.pop(name, None)


def _iter_tree(root: Definition) -> list[Any]:
    if root._meta.proxy:
        root = Definition.objects.get(pk=root.pk)
    found: list[Any] = [root]
    for category in root.category_configs.all():
        found.append(category)
        found.extend(category.format_configs.all())
    return found


def _definition_name(objects: list[dict[str, Any]], model: str) -> str | None:
    for obj in objects:
        if obj.get("model") != model:
            continue
        fields = obj.get("fields")
        if not isinstance(fields, dict):
            return None
        name = fields.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
        return None
    return None


def _rewrite_definition_pk(objects: list[dict[str, Any]], model: str, target: Any) -> None:
    new_pk = str(target.pk)
    old_pk = None
    for obj in objects:
        if obj.get("model") != model:
            continue
        old_pk = obj.get("pk")
        obj["pk"] = new_pk
        fields = obj.get("fields")
        if isinstance(fields, dict):
            fields["uuid"] = str(target.uuid)
        break
    if old_pk is None:
        raise ValueError(_("No definition entry found in file."))
    for obj in objects:
        if obj.get("pk") == old_pk:
            obj["pk"] = new_pk
        fields = obj.get("fields")
        if not isinstance(fields, dict):
            continue
        for key in _PARENT_FK_FIELDS:
            if fields.get(key) == old_pk:
                fields[key] = new_pk


def _serialize_definition(definition: Definition) -> dict[str, Any]:
    raw = serializers.serialize("json", _iter_tree(definition))
    return {"format_version": FORMAT_VERSION, "objects": json.loads(raw)}


def _import_definition(data: dict[str, Any], direction: str) -> Definition:
    objects = _require_current_payload(data)
    incoming_name = _definition_name(objects, _DEFINITION_MODEL)
    if incoming_name:
        existing = (
            Definition.objects.filter(direction=direction, name=incoming_name)
            .order_by("pk")
            .first()
        )
        if existing is not None:
            _rewrite_definition_pk(objects, _DEFINITION_MODEL, existing)
    definition: Definition | None = None
    with transaction.atomic():
        for item in serializers.deserialize("json", json.dumps(objects)):
            item.save()
            if isinstance(item.object, Definition):
                definition = item.object
    if definition is None or definition.direction != direction:
        raise ValueError(
            _("No %(direction)s definition entry found in file.") % {"direction": direction}
        )
    return definition


def serialize_export_configuration(definition: Definition) -> dict[str, Any]:
    """Dump an export definition with its categories and format configs."""
    return _serialize_definition(definition)


def _direction_value(direction: Any) -> str:
    value = getattr(direction, "value", direction)
    if isinstance(value, str):
        return value
    raise TypeError("Import direction must be a string.")


def import_export_configuration(data: dict[str, Any]) -> Definition:
    """Load an export definition from a current payload. Old payloads are rejected."""
    return _import_definition(data, _direction_value(Definition.Direction.EXPORT))


def serialize_import_definition(import_definition: Definition) -> dict[str, Any]:
    """Dump an import definition with its categories and format configs."""
    return _serialize_definition(import_definition)


def import_import_definition(data: dict[str, Any]) -> Definition:
    """Load an import definition from a current payload. Old payloads are rejected."""
    return _import_definition(data, _direction_value(Definition.Direction.IMPORT))


serialize_report_import = serialize_import_definition
import_report_import = import_import_definition
