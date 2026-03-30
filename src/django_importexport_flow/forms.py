"""Admin forms for django-importexport-flow."""

from __future__ import annotations

import json
import uuid
from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _

from .engine.core.filters import (
    attach_filter_context_fields,
    clean_filter_context_data,
    reorder_filter_fields_first,
)
from .utils.helpers import get_setting
from .utils.upload_validation import validate_configuration_json_payload

MAX_IMPORT_BYTES = get_setting("MAX_IMPORT_BYTES")
MAX_TABULAR_IMPORT_BYTES = get_setting("MAX_TABULAR_IMPORT_BYTES")

# CSV / Excel / JSON — shared by export, example download, and tabular import hints.
EXPORT_FORMAT_CHOICES = (
    ("csv", "CSV"),
    ("excel", _("Excel (.xlsx)")),
    ("json", "JSON"),
)


class ExportGenerateForm(forms.Form):
    """
    One input per GET query param (``fr_get_<name>``), same for ``filter_request`` and
    ``filter_mandatory.get``; one per URL kwarg (``fr_kw_<name>``); then export format.
    ``filter_mandatory`` fields are required; ``filter_request``-only GET fields are optional.
    ``filter_config`` is not editable here (uses the report only).
    """

    export_format = forms.ChoiceField(
        label=_("Format"),
        choices=EXPORT_FORMAT_CHOICES,
    )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        definition = getattr(self.__class__, "_filter_context_source", None)
        self.definition = definition
        if definition is None:
            return
        attach_filter_context_fields(self, definition, for_import=False)
        reorder_filter_fields_first(self, (), ("export_format",))

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        definition = getattr(self.__class__, "_filter_context_source", None)
        if definition is None:
            return cleaned
        clean_filter_context_data(self, cleaned, definition)
        return cleaned


def make_export_form_class(definition: Any):
    """Bind a report instance to :class:`ExportGenerateForm` (required by admin POST)."""
    return type(
        f"ReportExportForm_{id(definition)}",
        (ExportGenerateForm,),
        {"_filter_context_source": definition},
    )


class ImportExampleFileForm(forms.Form):
    """Choose CSV, Excel, or JSON for the empty import template (admin download)."""

    example_format = forms.ChoiceField(
        label=_("Format"),
        choices=EXPORT_FORMAT_CHOICES,
        initial="csv",
    )


class TabularImportForm(forms.Form):
    """
    Tabular data import: file + same filter context as export (``fr_get_*`` / ``fr_kw_*``).
    Two steps: ``upload`` (file + filters) then ``confirm`` (preview token only).
    """

    STEP_UPLOAD = "upload"
    STEP_CONFIRM = "confirm"

    step = forms.CharField(widget=forms.HiddenInput, initial=STEP_UPLOAD)
    import_request_uuid = forms.UUIDField(required=False, widget=forms.HiddenInput)
    file = forms.FileField(
        label=_("Data file"),
        help_text=_("CSV or Excel (.xlsx). Tabular JSON uploads are not supported."),
        required=False,
        widget=forms.ClearableFileInput(
            attrs={
                "accept": ".csv,.xlsx,.xls,text/csv,"
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            }
        ),
    )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        source = getattr(self.__class__, "_filter_context_source", None)
        self.definition = source
        if source is None:
            return
        attach_filter_context_fields(self, source, for_import=True)
        reorder_filter_fields_first(self, ("step", "import_request_uuid", "file"), ())
        if get_setting("IMPORT_TASK_BACKEND", "sync") != "sync" and get_setting(
            "IMPORT_ADMIN_OFFER_ASYNC", True
        ):
            self.fields["defer_to_task"] = forms.BooleanField(
                label=_("Process import in background"),
                required=False,
                initial=bool(get_setting("IMPORT_ADMIN_ASYNC_DEFAULT", False)),
                help_text=_("Uses IMPORT_TASK_BACKEND (thread, Celery, or RQ)."),
            )
            reorder_filter_fields_first(
                self,
                ("step", "import_request_uuid", "file"),
                ("defer_to_task",),
            )

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        source = getattr(self.__class__, "_filter_context_source", None)
        step = cleaned.get("step") or self.STEP_UPLOAD

        if step == self.STEP_UPLOAD:
            f = cleaned.get("file")
            if not f:
                self.add_error("file", _("This field is required."))
            elif hasattr(f, "size") and f.size > MAX_TABULAR_IMPORT_BYTES:
                self.add_error(
                    "file",
                    _("File is too large (max %(max)s MB).")
                    % {"max": MAX_TABULAR_IMPORT_BYTES // (1024 * 1024)},
                )
        else:
            uid = cleaned.get("import_request_uuid")
            if not uid:
                self.add_error(
                    "import_request_uuid",
                    _("Missing import request id; start again."),
                )
            elif not isinstance(uid, uuid.UUID):
                try:
                    cleaned["import_request_uuid"] = uuid.UUID(str(uid))
                except ValueError:
                    self.add_error("import_request_uuid", _("Invalid import request id."))

        if source is not None and step == self.STEP_UPLOAD and not self.errors:
            clean_filter_context_data(self, cleaned, source)
        return cleaned


def make_tabular_import_form_class(import_definition: Any):
    """Bind a :class:`~django_importexport_flow.models.ImportDefinition` for the tabular import wizard."""
    return type(
        f"TabularImportForm_{id(import_definition)}",
        (TabularImportForm,),
        {"_filter_context_source": import_definition},
    )


# Backward-compatible names (django-reporting era); prefer Import* / Tabular* symbols.
ReportImportExampleFileForm = ImportExampleFileForm
ReportImportDataForm = TabularImportForm
make_report_import_data_form_class = make_tabular_import_form_class


class ExportConfigurationImportForm(forms.Form):
    """Upload a JSON file produced by *Export configuration (JSON)*."""

    file = forms.FileField(
        label=_("JSON file"),
        help_text=_(
            "Same format as the export. If a report with the same name already "
            "exists, it is replaced; otherwise a new report is created. "
            "Only upload files you trust (same privilege as loaddata)."
        ),
        widget=forms.ClearableFileInput(attrs={"accept": "application/json,.json"}),
    )

    def clean_file(self):
        f = self.cleaned_data["file"]
        data = f.read()
        if len(data) > MAX_IMPORT_BYTES:
            raise forms.ValidationError(_("File is too large."))
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise forms.ValidationError(_("File must be UTF-8.")) from exc
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError(_("Invalid JSON.")) from exc
        try:
            validate_configuration_json_payload(payload)
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc
        self.import_data = payload
        return f
