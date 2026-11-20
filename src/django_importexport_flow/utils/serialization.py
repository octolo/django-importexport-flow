"""JSON export and import for export and import definitions."""

from __future__ import annotations

import copy
import json
from typing import Any

from django.core import serializers
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from ..models import ColumnTranslation, Definition
from .helpers import get_setting

FORMAT_VERSION = get_setting("SERIALIZATION_FORMAT_VERSION")

_DEFINITION_MODEL = "django_importexport_flow.definition"
COLUMN_TRANSLATIONS_KEY = "column_translations"

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
        if model.lower() == ColumnTranslation._meta.label_lower:
            raise ValueError(_("Column translations must be in the column_translations array."))
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


def _serialize_definition(
    definition: Definition, *, include_column_translations: bool
) -> dict[str, Any]:
    objects = json.loads(serializers.serialize("json", _iter_tree(definition)))
    payload: dict[str, Any] = {"format_version": FORMAT_VERSION, "objects": objects}
    if include_column_translations and (target := definition.target) is not None:
        objects[0]["fields"]["target"] = list(target.natural_key())
        payload[COLUMN_TRANSLATIONS_KEY] = list(
            ColumnTranslation.objects.filter(content_type=target).values(
                "path", "language", "label"
            )
        )
    return payload


def _import_column_translation(definition: Definition, entry: Any) -> None:
    if not isinstance(entry, dict) or not all(
        isinstance(entry.get(field), str) and entry[field].strip()
        for field in ("path", "language", "label")
    ):
        raise ValueError(_("Each column translation requires a path, language, and label."))
    incoming = ColumnTranslation(
        content_type_id=definition.target_id,
        path=entry["path"],
        language=entry["language"],
        label=entry["label"],
    )
    incoming.clean()
    existing, _created = ColumnTranslation.objects.get_or_create(
        content_type_id=incoming.content_type_id,
        path=incoming.path,
        language=incoming.language,
        defaults={"label": incoming.label},
    )
    if existing.label != incoming.label:
        raise ValueError(
            _("A different column translation already exists for %(path)s [%(language)s].")
            % {"path": incoming.path, "language": incoming.language}
        )


def _import_definition(data: dict[str, Any], direction: str) -> Definition:
    objects = _require_current_payload(data)
    translations = data.get(COLUMN_TRANSLATIONS_KEY, [])
    if not isinstance(translations, list):
        raise ValueError(_("column_translations must be a JSON array."))
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
        if translations and definition.target_id is None:
            raise ValueError(_("Column translations require a definition target model."))
        for entry in translations:
            _import_column_translation(definition, entry)
    return definition


def serialize_export_configuration(
    definition: Definition, *, include_column_translations: bool = False
) -> dict[str, Any]:
    """Dump an export definition as a JSON-compatible dictionary.

    Args:
        definition: Export definition to serialize.
        include_column_translations: Include the target model's translation catalog.

    Returns:
        The versioned payload with the definition, categories, and format configs.
    """
    return _serialize_definition(
        definition, include_column_translations=include_column_translations
    )


def _direction_value(direction: Any) -> str:
    value = getattr(direction, "value", direction)
    if isinstance(value, str):
        return value
    raise TypeError("Import direction must be a string.")


def import_export_configuration(data: dict[str, Any]) -> Definition:
    """Load an export definition from a current payload. Old payloads are rejected."""
    return _import_definition(data, _direction_value(Definition.Direction.EXPORT))


def serialize_import_definition(
    import_definition: Definition, *, include_column_translations: bool = False
) -> dict[str, Any]:
    """Dump an import definition as a JSON-compatible dictionary.

    Args:
        import_definition: Import definition to serialize.
        include_column_translations: Include the target model's translation catalog.

    Returns:
        The versioned payload with the definition, categories, and format configs.
    """
    return _serialize_definition(
        import_definition, include_column_translations=include_column_translations
    )


def import_import_definition(data: dict[str, Any]) -> Definition:
    """Load an import definition from a current payload. Old payloads are rejected."""
    return _import_definition(data, _direction_value(Definition.Direction.IMPORT))


serialize_report_import = serialize_import_definition
import_report_import = import_import_definition
