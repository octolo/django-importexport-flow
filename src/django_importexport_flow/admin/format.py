"""Admin for category and format configs."""

from __future__ import annotations

from django import forms
from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from django_boosted import NestedStackedInline

from ..engine.core.formats import CATEGORY_LABELS, DOCUMENT, get_format, registered_formats
from ..models import (
    CategoryConfig,
    ExportCategoryConfig,
    ExportFormatConfig,
    FormatConfig,
    ImportCategoryConfig,
    ImportFormatConfig,
)
from ..models.mixins import normalize_hook_paths


class HookListField(forms.CharField):
    """One dotted path per line, stored as a list."""

    widget = forms.Textarea(attrs={"rows": 3})

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("required", False)
        super().__init__(*args, **kwargs)

    def prepare_value(self, value: object) -> str:
        if isinstance(value, (list, tuple)):
            return "\n".join(str(item) for item in value if str(item).strip())
        if value in (None, ""):
            return ""
        return str(value)

    def to_python(self, value: object) -> list[str]:  # type: ignore[override]
        try:
            return normalize_hook_paths(value)
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc


class FormatConfigAdminForm(forms.ModelForm):
    hook = HookListField(label=_("Hooks"))

    class Meta:
        model = FormatConfig
        fields = (
            "category_config",
            "format_key",
            "configuration",
            "hook",
            "template",
        )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        category = self._category()
        if "format_key" in self.fields and category is not None:
            direction = category.direction
            choices = [("", "---------")]
            for spec in registered_formats():
                if spec.category != category.category_key:
                    continue
                hook = (
                    spec.default_export_hook if direction == "export" else spec.default_import_hook
                )
                if not hook:
                    continue
                choices.append((spec.key, spec.label))
            self.fields["format_key"].widget = forms.Select(choices=choices)
        selected = get_format(getattr(self.instance, "format_key", "") or "")
        if selected is not None and "hook" in self.fields:
            native = (
                selected.default_import_hook
                if self.instance.direction == "import"
                else selected.default_export_hook
            )
            self.fields["hook"].help_text = _(
                "One dotted path per line. A list replaces the native hook. "
                "Leave empty to use %(hook)s."
            ) % {"hook": native}
        if "template" in self.fields and (selected is None or selected.category != DOCUMENT):
            self.fields["template"].widget = forms.HiddenInput()

    def _category(self) -> CategoryConfig | None:
        if getattr(self.instance, "category_config_id", None):
            return self.instance.category_config
        raw = None
        if self.data:
            raw = self.data.get(self.add_prefix("category_config"))
        if not raw and self.initial:
            raw = self.initial.get("category_config")
        if not raw:
            return None
        return CategoryConfig.objects.filter(pk=raw).first()


class FormatConfigInline(admin.StackedInline):
    model = FormatConfig
    form = FormatConfigAdminForm
    extra = 0
    fields = (
        "format_key",
        "configuration",
        "hook",
        "template",
    )


class CategoryConfigInline(NestedStackedInline):
    model = CategoryConfig
    extra = 0
    show_change_link = True
    fields = ("category_key", "columns", "configuration")
    inlines = (FormatConfigInline,)


def _specs_for(direction: str):
    for spec in registered_formats():
        hook = spec.default_export_hook if direction == "export" else spec.default_import_hook
        if hook:
            yield spec


def category_list_filter(lookup: str, direction: str, *, format_field: str = ""):
    class CategoryListFilter(admin.SimpleListFilter):
        title = _("Category")
        parameter_name = "category"

        def lookups(self, request, model_admin):
            keys: list[str] = []
            for spec in _specs_for(direction):
                if spec.category not in keys:
                    keys.append(spec.category)
            return [(key, CATEGORY_LABELS[key]) for key in keys]

        def queryset(self, request, queryset):
            if not self.value():
                return queryset
            if format_field:
                keys = [spec.key for spec in _specs_for(direction) if spec.category == self.value()]
                return queryset.filter(**{f"{format_field}__in": keys})
            return queryset.filter(**{lookup: self.value()}).distinct()

    CategoryListFilter.__name__ = f"{direction.title()}CategoryListFilter"
    return CategoryListFilter


def format_list_filter(lookup: str, direction: str):
    class FormatListFilter(admin.SimpleListFilter):
        title = _("Format")
        parameter_name = "format"

        def lookups(self, request, model_admin):
            return [(spec.key, spec.label) for spec in _specs_for(direction)]

        def queryset(self, request, queryset):
            if not self.value():
                return queryset
            return queryset.filter(**{lookup: self.value()}).distinct()

    FormatListFilter.__name__ = f"{direction.title()}FormatListFilter"
    return FormatListFilter


class FormatConfigAdmin(admin.ModelAdmin):
    form = FormatConfigAdminForm
    list_display = (
        "definition_label",
        "category_label",
        "format_label",
        "hook",
    )
    list_filter = ("category_config__category_key", "format_key")
    search_fields = (
        "category_config__definition__name",
        "category_config__definition__named_id",
        "format_key",
        "hook",
    )

    @admin.display(description=_("Definition"))
    def definition_label(self, obj: FormatConfig) -> str:
        return obj.category_config.definition.name

    @admin.display(description=_("Category"))
    def category_label(self, obj: FormatConfig) -> str:
        return str(CATEGORY_LABELS.get(obj.category_key, obj.category_key))

    @admin.display(description=_("Format"))
    def format_label(self, obj: FormatConfig) -> str:
        spec = get_format(obj.format_key)
        return str(spec.label if spec is not None else obj.format_key)


def _format_admin(model, direction: str):
    category_model = ExportCategoryConfig if direction == "export" else ImportCategoryConfig

    class Admin(FormatConfigAdmin):
        list_filter = (
            category_list_filter("category_config__category_key", direction),
            format_list_filter("format_key", direction),
        )

        def get_queryset(self, request):
            return (
                super()
                .get_queryset(request)
                .filter(category_config__definition__direction=direction)
            )

        def formfield_for_foreignkey(self, db_field, request, **kwargs):
            if db_field.name == "category_config":
                kwargs["queryset"] = category_model.objects.all()
            return super().formfield_for_foreignkey(db_field, request, **kwargs)

    Admin.__name__ = f"{model.__name__}Admin"
    return Admin


admin.site.register(ExportFormatConfig, _format_admin(ExportFormatConfig, "export"))
admin.site.register(ImportFormatConfig, _format_admin(ImportFormatConfig, "import"))
