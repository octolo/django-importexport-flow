"""Admin action that loads or reloads the sample catalog and report definitions."""

from __future__ import annotations

import json
from pathlib import Path

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django_boosted import admin_boost_global_view

from django_importexport_flow.models import ColumnTranslation, Definition
from django_importexport_flow.utils.serialization import (
    import_export_configuration,
    import_import_definition,
)

from .models import (
    Author,
    AuthorProfile,
    Book,
    Category,
    FieldShowcase,
    FieldShowcaseDetail,
    GenericBookmark,
    Tag,
)

SAMPLE_FIXTURE_PREFIX = "Sample fixture —"
_FIXTURES = Path(__file__).resolve().parent / "report_fixtures"
_SAMPLE_MODELS = (
    GenericBookmark,
    FieldShowcaseDetail,
    FieldShowcase,
    Book,
    AuthorProfile,
    Tag,
    Category,
    Author,
)
_BUTTONS = (
    {"name": "_load", "label": _("Load"), "class": "default"},
    {"name": "_reload", "label": _("Reload"), "class": "danger"},
)


class LoadSampleFixturesForm(forms.Form):
    summary = forms.CharField(
        required=False,
        label=_("Fixtures"),
        help_text=_(
            "Load inserts or updates the catalog and the report definitions. "
            "Reload deletes sample rows and sample definitions first."
        ),
        widget=forms.Textarea(attrs={"rows": 3}),
        initial=(
            "sample_catalog, the report_export_*.json definitions, "
            "and the report_import_*.json definitions."
        ),
    )


def _clear_sample_fixtures() -> None:
    for model in _SAMPLE_MODELS:
        model.objects.all().delete()
    ColumnTranslation.objects.filter(content_type__app_label="sample").delete()
    Definition.objects.filter(name__startswith=SAMPLE_FIXTURE_PREFIX).delete()
    Definition.objects.filter(name__startswith=SAMPLE_FIXTURE_PREFIX).delete()


def _load_definition_files() -> tuple[int, int]:
    exports = 0
    imports = 0
    for path in sorted(_FIXTURES.glob("report_export_*.json")):
        import_export_configuration(json.loads(path.read_text(encoding="utf-8")))
        exports += 1
    for path in sorted(_FIXTURES.glob("report_import_*.json")):
        import_import_definition(json.loads(path.read_text(encoding="utf-8")))
        imports += 1
    return exports, imports


def load_sample_fixtures(*, replace: bool) -> str:
    """Load the sample catalog and report definitions. ``replace`` wipes them first."""
    with transaction.atomic():
        if replace:
            _clear_sample_fixtures()
        call_command("loaddata", "sample_catalog", verbosity=0)
        exports, imports = _load_definition_files()
    verb = _("Reloaded") if replace else _("Loaded")
    return f"{verb} sample fixtures: {exports} exports, {imports} imports."


def _form_payload() -> dict:
    return {
        "form": LoadSampleFixturesForm(),
        "readonly_fields": ["summary"],
        "save_buttons": list(_BUTTONS),
    }


@admin_boost_global_view("adminform", _("Load sample fixtures"))
def load_sample_fixtures_view(request, form=None):
    if form is None:
        return _form_payload()
    try:
        summary = load_sample_fixtures(replace="_reload" in request.POST)
    except (CommandError, IntegrityError, ValidationError, ValueError) as exc:
        messages.error(request, str(exc))
        return _form_payload()
    messages.success(request, summary)
    return {"redirect_url": reverse("admin:index")}
