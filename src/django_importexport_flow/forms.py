"""Admin forms for django-importexport-flow."""

from __future__ import annotations

import json
import uuid
from typing import Any

from django import forms
from django.core.exceptions import ValidationError
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

# Spreadsheet and structured formats used by the import example file (not documents).
EXPORT_FORMAT_CHOICES = (
    ("csv", "CSV"),
    ("excel", _("Excel (.xlsx)")),
    ("json", "JSON"),
)


def _definition_enables_pdf(definition: Any) -> bool:
    from .engine.core.formats import get_export_config

    try:
        get_export_config(definition, "pdf")
    except ValueError:
        return False
    return True


def export_format_choices(definition: Any):
    """Enabled formats grouped by category, limited to configs present on ``definition``."""
    from .engine.core.formats import grouped_format_choices

    return grouped_format_choices(definition)


class ExportGenerateForm(forms.Form):
    """
    One input per GET query param (``fr_get_<name>``), same for ``filter_request`` and
    ``filter_mandatory.get``; one per URL kwarg (``fr_kw_<name>``); optional
    ``mg_get_*`` / ``mg_kw_*`` for queryset filters and ``mm_get_*`` for manager
    method arguments; then export format.
    ``filter_mandatory`` fields are required; ``filter_request``-only GET fields are optional.
    ``filter_config`` is not editable here (uses the report only).
    """

    allow_template_override = False

    export_format = forms.ChoiceField(
        label=_("Format"),
        choices=EXPORT_FORMAT_CHOICES,
    )
    template_override = forms.CharField(
        label=_("Template override"),
        required=False,
        widget=forms.Textarea,
        help_text=_("PDF only. Leave empty to use the template stored on the format."),
    )
    configuration_overrides = forms.JSONField(
        label=_("Configuration overrides"),
        required=False,
        initial={},
        help_text=_(
            'Optional object {"format": {...}, "hook": {...}}. '
            "Native format options go in format; hook values are passed to the hooks."
        ),
    )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        definition = getattr(self.__class__, "_filter_context_source", None)
        self.definition = definition
        if definition is None:
            return
        attach_filter_context_fields(self, definition, for_import=False)
        export_format = self.fields["export_format"]
        if isinstance(export_format, forms.ChoiceField):
            export_format.choices = export_format_choices(definition)
        self.allow_template_override = bool(
            getattr(self.__class__, "_allow_template_override", False)
        )
        if not self.allow_template_override or not _definition_enables_pdf(definition):
            self.fields.pop("template_override", None)
        reorder_filter_fields_first(
            self,
            (),
            ("export_format", "template_override", "configuration_overrides"),
        )

    def clean(self) -> dict[str, Any]:
        from .engine.core.overrides import (
            normalize_configuration_overrides,
            validate_template_override,
        )

        cleaned = super().clean()
        if not isinstance(cleaned, dict):
            return {}
        definition = getattr(self.__class__, "_filter_context_source", None)
        if definition is None or self.errors:
            return cleaned
        clean_filter_context_data(self, cleaned, definition)
        export_format = str(cleaned.get("export_format") or "")
        try:
            cleaned["configuration_overrides"] = normalize_configuration_overrides(
                cleaned.get("configuration_overrides"),
                export_format=export_format,
            )
        except ValidationError as exc:
            self.add_error("configuration_overrides", exc)
        if "template_override" in self.fields:
            try:
                cleaned["template_override"] = validate_template_override(
                    cleaned.get("template_override") or "",
                    export_format=export_format,
                )
            except ValidationError as exc:
                self.add_error("template_override", exc)
        elif not self.allow_template_override and self._posted_template_override():
            self.add_error(
                "export_format",
                _("You do not have permission to override the PDF template."),
            )
        elif str(cleaned.get("template_override") or "").strip():
            self.add_error("export_format", _("A template override is only valid for PDF exports."))
        return cleaned

    def _posted_template_override(self) -> str:
        data = getattr(self, "data", None)
        if not data:
            return ""
        return str(data.get("template_override") or "").strip()


def make_export_form_class(definition: Any, *, allow_template_override: bool = False):
    """Bind a report instance to :class:`ExportGenerateForm` (required by admin POST)."""
    return type(
        f"ReportExportForm_{id(definition)}",
        (ExportGenerateForm,),
        {
            "_filter_context_source": definition,
            "_allow_template_override": allow_template_override,
        },
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
        if not isinstance(cleaned, dict):
            return {}
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
