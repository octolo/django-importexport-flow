from django.contrib import admin

from ..models.translation import ColumnTranslation


@admin.register(ColumnTranslation)
class ColumnTranslationAdmin(admin.ModelAdmin):
    list_display = ("path", "language", "label", "content_type")
    list_filter = ("language", "content_type")
    search_fields = ("path", "label")
    ordering = ("content_type", "path", "language")
