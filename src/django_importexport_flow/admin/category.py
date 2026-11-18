"""Admin for category configs and their direction or category proxies."""

from __future__ import annotations

from typing import Any

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html_join
from django.utils.translation import gettext_lazy as _
from django_boosted import AdminBoostModel

from ..engine.core.formats import CATEGORY_LABELS, DOCUMENT, get_format
from ..models import (
    CategoryConfig,
    ExportCategoryConfig,
    ExportDefinition,
    ExportFormatConfig,
    ImportCategoryConfig,
    ImportDefinition,
    ImportFormatConfig,
)
from .format import FormatConfigInline, category_list_filter, format_list_filter


class CategoryConfigAdmin(AdminBoostModel):
    list_display = ("definition", "category_label", "formats_label")
    list_filter = ("category_key",)
    search_fields = ("definition__name", "definition__named_id")
    inlines = (FormatConfigInline,)

    @admin.display(description=_("Category"))
    def category_label(self, obj: CategoryConfig) -> str:
        return str(CATEGORY_LABELS.get(obj.category_key, obj.category_key))

    @admin.display(description=_("Formats"))
    def formats_label(self, obj: CategoryConfig) -> str:
        links = []
        for config in obj.format_configs.all():
            spec = get_format(config.format_key)
            label = spec.short_label if spec is not None else config.format_key
            proxy = ExportFormatConfig if obj.direction == "export" else ImportFormatConfig
            url = reverse(
                f"admin:{proxy._meta.app_label}_{proxy._meta.model_name}_change",
                args=[config.pk],
            )
            links.append((url, label))
        return format_html_join(", ", '<a href="{}">{}</a>', links)


def _category_admin(model, direction: str = "", category_key: str = ""):
    definition_model = ExportDefinition if direction == "export" else ImportDefinition

    class Admin(CategoryConfigAdmin):
        list_filter: tuple[Any, ...] = (
            category_list_filter("category_key", direction),
            format_list_filter("format_configs__format_key", direction),
        )

        def get_queryset(self, request):
            queryset = super().get_queryset(request)
            if direction:
                queryset = queryset.filter(definition__direction=direction)
            if category_key:
                queryset = queryset.filter(category_key=category_key)
            return queryset

        def get_fields(self, request, obj=None):
            fields = list(super().get_fields(request, obj))
            if category_key and "category_key" in fields:
                fields.remove("category_key")
            if category_key == DOCUMENT and "columns" in fields:
                fields.remove("columns")
            return fields

        def formfield_for_foreignkey(self, db_field, request, **kwargs):
            if direction and db_field.name == "definition":
                kwargs["queryset"] = definition_model.objects.all()
            return super().formfield_for_foreignkey(db_field, request, **kwargs)

        def save_model(self, request, obj, form, change):
            if category_key:
                obj.category_key = category_key
            super().save_model(request, obj, form, change)

    Admin.__name__ = f"{model.__name__}Admin"
    return Admin


admin.site.register(ExportCategoryConfig, _category_admin(ExportCategoryConfig, "export"))
admin.site.register(ImportCategoryConfig, _category_admin(ImportCategoryConfig, "import"))
