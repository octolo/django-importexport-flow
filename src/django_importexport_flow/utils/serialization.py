"""JSON export for export definitions."""

from __future__ import annotations

import copy
import json
from itertools import chain
from typing import Any

from django.core import serializers
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from ..models import ExportConfigPdf, ExportConfigTable, ExportDefinition, ImportDefinition

FORMAT_VERSION = 1

_EXPORT_DEFINITION_MODEL = "django_importexport_flow.exportdefinition"
_IMPORT_DEFINITION_MODEL = "django_importexport_flow.importdefinition"

_LEGACY_REPORTING_SUFFIX_TO_EXPORT = {
    "reportdefinition": "exportdefinition",
    "reportconfigpdf": "exportconfigpdf",
    "reportconfigtable": "exportconfigtable",
    "reportrequest": "exportrequest",
}

_LEGACY_REPORTIMPORT_SUFFIX_TO_EXPORT = {
    "reportdefinition": "exportdefinition",
    "reportconfigpdf": "exportconfigpdf",
    "reportconfigtable": "exportconfigtable",
    "reportrequest": "exportrequest",
}


def _normalize_legacy_django_reporting_app_labels(objects: list[dict[str, Any]]) -> None:
    """Rewrite pickled model paths from the old ``django_reporting`` app label."""
    for o in objects:
        m = o.get("model")
        if not isinstance(m, str) or not m.startswith("django_reporting."):
            continue
        suffix = m[len("django_reporting.") :]
        if suffix == "reportimport":
            o["model"] = _IMPORT_DEFINITION_MODEL
            continue
        mapped = _LEGACY_REPORTING_SUFFIX_TO_EXPORT.get(suffix)
        if mapped is not None:
            o["model"] = f"django_importexport_flow.{mapped}"
        else:
            o["model"] = f"django_importexport_flow.{suffix}"


def _normalize_legacy_django_reportimport_app_labels(objects: list[dict[str, Any]]) -> None:
    """Rewrite model paths from ``django_reportimport`` (pre-rename) to ``django_importexport_flow``."""
    for o in objects:
        m = o.get("model")
        if not isinstance(m, str) or not m.startswith("django_reportimport."):
            continue
        suffix = m[len("django_reportimport.") :]
        mapped = _LEGACY_REPORTIMPORT_SUFFIX_TO_EXPORT.get(suffix)
        if mapped is not None:
            o["model"] = f"django_importexport_flow.{mapped}"
        else:
            o["model"] = f"django_importexport_flow.{suffix}"


def _normalize_legacy_django_exportimport_app_labels(objects: list[dict[str, Any]]) -> None:
    """Rewrite pickled model paths from ``django_exportimport`` to ``django_importexport_flow``."""
    for o in objects:
        m = o.get("model")
        if not isinstance(m, str) or not m.startswith("django_exportimport."):
            continue
        suffix = m[len("django_exportimport.") :]
        o["model"] = f"django_importexport_flow.{suffix}"


def _normalize_legacy_django_importexport_app_labels(objects: list[dict[str, Any]]) -> None:
    """Rewrite ``django_importexport.*`` (before ``-flow`` package rename) to ``django_importexport_flow``."""
    prefix_old = "django_importexport."
    prefix_new = "django_importexport_flow."
    for o in objects:
        m = o.get("model")
        if not isinstance(m, str) or not m.startswith(prefix_old):
            continue
        if m.startswith(prefix_new):
            continue
        suffix = m[len(prefix_old) :]
        o["model"] = prefix_new + suffix


def _normalize_legacy_export_json_fk_fields(objects: list[dict[str, Any]]) -> None:
    """Rename ``report`` → ``export`` in serialized config rows (legacy JSON)."""
    legacy_models = {
        "django_importexport_flow.exportconfigpdf",
        "django_importexport_flow.exportconfigtable",
        "django_importexport.exportconfigpdf",
        "django_importexport.exportconfigtable",
        "django_exportimport.exportconfigpdf",
        "django_exportimport.exportconfigtable",
        "django_reportimport.reportconfigpdf",
        "django_reportimport.reportconfigtable",
    }
    for o in objects:
        m = o.get("model")
        fields = o.get("fields")
        if m not in legacy_models or not isinstance(fields, dict):
            continue
        if "report" in fields and "export" not in fields:
            fields["export"] = fields.pop("report")


def _export_definition_name_from_payload(objects: list[dict[str, Any]]) -> str | None:
    for o in objects:
        if o.get("model") != _EXPORT_DEFINITION_MODEL:
            continue
        fields = o.get("fields")
        if not isinstance(fields, dict):
            return None
        name = fields.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
        return None
    return None


def _import_definition_name_from_payload(objects: list[dict[str, Any]]) -> str | None:
    for o in objects:
        model = o.get("model")
        if model != _IMPORT_DEFINITION_MODEL:
            continue
        fields = o.get("fields")
        if not isinstance(fields, dict):
            return None
        name = fields.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
        return None
    return None


def _normalize_legacy_import_definition_columns_field(objects: list[dict[str, Any]]) -> None:
    """Older exports used ``columns`` (include list); imports now use ``columns_exclude``."""
    for o in objects:
        if o.get("model") != _IMPORT_DEFINITION_MODEL:
            continue
        fields = o.get("fields")
        if not isinstance(fields, dict):
            continue
        if "columns" in fields and "columns_exclude" not in fields:
            fields.pop("columns")
            fields.setdefault("columns_exclude", [])
        if "exclude_primary_key" not in fields:
            fields.setdefault("exclude_primary_key", True)


def _normalize_legacy_import_definition_integer_pk(objects: list[dict[str, Any]]) -> None:
    """Older exports used integer ``pk`` plus ``uuid`` in ``fields``; PK is now ``uuid``."""
    for o in objects:
        if o.get("model") != _IMPORT_DEFINITION_MODEL:
            continue
        pk = o.get("pk")
        fields = o.get("fields")
        if isinstance(pk, int) and isinstance(fields, dict) and fields.get("uuid"):
            o["pk"] = str(fields["uuid"])
        break


def _normalize_legacy_export_definition_integer_pks(objects: list[dict[str, Any]]) -> None:
    """Older exports used integer ``pk`` plus ``uuid`` in ``fields``; PK is now ``uuid``."""
    old_pk = None
    uid_str = None
    for o in objects:
        if o.get("model") != _EXPORT_DEFINITION_MODEL:
            continue
        pk = o.get("pk")
        fields = o.get("fields")
        if not isinstance(fields, dict):
            break
        uuid_val = fields.get("uuid")
        if isinstance(pk, int) and uuid_val:
            old_pk = pk
            uid_str = str(uuid_val)
            o["pk"] = uid_str
            break
        break
    if old_pk is None or uid_str is None:
        return
    for o in objects:
        if o.get("pk") == old_pk:
            o["pk"] = uid_str
        f = o.get("fields")
        if not isinstance(f, dict):
            continue
        for key in ("export", "report"):
            if f.get(key) == old_pk:
                f[key] = uid_str


def _rewrite_import_payload_to_target_import_definition(
    objects: list[dict[str, Any]],
    target: ImportDefinition,
) -> None:
    """Point serialized rows at ``target`` (PK); align ``uuid`` in ``fields`` for re-import."""
    new_pk = str(target.pk)
    old_pk = None
    for o in objects:
        if o.get("model") == _IMPORT_DEFINITION_MODEL:
            old_pk = o.get("pk")
            o["pk"] = new_pk
            fields = o.get("fields")
            if isinstance(fields, dict):
                fields["uuid"] = str(target.uuid)
            break
    if old_pk is None:
        raise ValueError(_("No ImportDefinition entry found in file."))
    for o in objects:
        if o.get("pk") == old_pk:
            o["pk"] = new_pk


def _rewrite_import_payload_to_target(
    objects: list[dict[str, Any]],
    target: ExportDefinition,
) -> None:
    """Point serialized rows at ``target`` (PK + related configs); align ``uuid`` in ``fields``."""
    new_pk = str(target.pk)
    old_pk = None
    for o in objects:
        if o.get("model") == _EXPORT_DEFINITION_MODEL:
            old_pk = o.get("pk")
            o["pk"] = new_pk
            fields = o.get("fields")
            if isinstance(fields, dict):
                fields["uuid"] = str(target.uuid)
            break
    if old_pk is None:
        raise ValueError(_("No ExportDefinition entry found in file."))
    for o in objects:
        if o.get("pk") == old_pk:
            o["pk"] = new_pk


def _chain_export_objects(definition: ExportDefinition):
    pdf: list[ExportConfigPdf] = []
    try:
        pdf = [definition.config_pdf]
    except ExportConfigPdf.DoesNotExist:
        pass
    table: list[ExportConfigTable] = []
    try:
        table = [definition.config_table]
    except ExportConfigTable.DoesNotExist:
        pass
    return chain([definition], pdf, table)


def serialize_export_configuration(definition: ExportDefinition) -> dict[str, Any]:
    """
    Dump ``ExportDefinition`` and, when present, ``ExportConfigPdf`` and
    ``ExportConfigTable``.
    """
    raw = serializers.serialize("json", _chain_export_objects(definition))
    return {
        "format_version": FORMAT_VERSION,
        "objects": json.loads(raw),
    }


def import_export_configuration(data: dict[str, Any]) -> ExportDefinition:
    """
    Load objects from an export payload.

    If an ``ExportDefinition`` with the same ``name`` as in the JSON already
    exists, serialized PKs are rewritten to that row (replace). Otherwise new
    rows are created from the file (by PK in the payload).

    Expects ``format_version`` ``1`` and an ``objects`` list in Django
    serialization format.
    """
    if data.get("format_version") != FORMAT_VERSION:
        raise ValueError(_("Unsupported format_version (expected %(exp)s).") % {"exp": FORMAT_VERSION})
    objects = data.get("objects")
    if not isinstance(objects, list):
        raise ValueError(_("Invalid payload: 'objects' must be a list."))
    objects = copy.deepcopy(objects)
    _normalize_legacy_django_reporting_app_labels(objects)
    _normalize_legacy_django_reportimport_app_labels(objects)
    _normalize_legacy_django_exportimport_app_labels(objects)
    _normalize_legacy_django_importexport_app_labels(objects)
    _normalize_legacy_export_json_fk_fields(objects)
    _normalize_legacy_export_definition_integer_pks(objects)
    incoming_name = _export_definition_name_from_payload(objects)
    if incoming_name:
        existing = (
            ExportDefinition.objects.filter(name=incoming_name).order_by("pk").first()
        )
        if existing is not None:
            _rewrite_import_payload_to_target(objects, existing)
    raw = json.dumps(objects)
    definition: ExportDefinition | None = None
    with transaction.atomic():
        for item in serializers.deserialize("json", raw):
            item.save()
            obj = item.object
            if isinstance(obj, ExportDefinition):
                definition = obj
    if definition is None:
        raise ValueError(_("No ExportDefinition entry found in file."))
    return definition


def serialize_import_definition(import_definition: ImportDefinition) -> dict[str, Any]:
    """Dump a single ``ImportDefinition`` row (columns and configuration included)."""
    raw = serializers.serialize("json", [import_definition])
    return {
        "format_version": FORMAT_VERSION,
        "objects": json.loads(raw),
    }


def import_import_definition(data: dict[str, Any]) -> ImportDefinition:
    """
    Load an ``ImportDefinition`` from an export payload (same ``format_version`` / ``objects`` shape).

    If a row with the same ``name`` already exists, it is replaced; otherwise a new
    row is created from the file.

    Payloads that still use the legacy model label ``django_reporting.reportimport``
    are accepted.
    """
    if data.get("format_version") != FORMAT_VERSION:
        raise ValueError(_("Unsupported format_version (expected %(exp)s).") % {"exp": FORMAT_VERSION})
    objects = data.get("objects")
    if not isinstance(objects, list):
        raise ValueError(_("Invalid payload: 'objects' must be a list."))
    objects = copy.deepcopy(objects)
    _normalize_legacy_django_reporting_app_labels(objects)
    _normalize_legacy_django_exportimport_app_labels(objects)
    _normalize_legacy_django_importexport_app_labels(objects)
    _normalize_legacy_import_definition_columns_field(objects)
    _normalize_legacy_import_definition_integer_pk(objects)
    incoming_name = _import_definition_name_from_payload(objects)
    if incoming_name:
        existing = ImportDefinition.objects.filter(name=incoming_name).order_by("pk").first()
        if existing is not None:
            _rewrite_import_payload_to_target_import_definition(objects, existing)
    raw = json.dumps(objects)
    import_definition: ImportDefinition | None = None
    with transaction.atomic():
        for item in serializers.deserialize("json", raw):
            item.save()
            obj = item.object
            if isinstance(obj, ImportDefinition):
                import_definition = obj
    if import_definition is None:
        raise ValueError(_("No ImportDefinition entry found in file."))
    return import_definition


serialize_report_import = serialize_import_definition
import_report_import = import_import_definition
