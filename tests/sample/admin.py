"""Minimal admin for the sample test app."""

from django.contrib import admin

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


@admin.register(Author)
class AuthorAdmin(admin.ModelAdmin):
    list_display = ("id", "name")
    search_fields = ("name",)


@admin.register(AuthorProfile)
class AuthorProfileAdmin(admin.ModelAdmin):
    list_display = ("id", "author", "bio")


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name")
    search_fields = ("name",)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "importance", "category")
    search_fields = ("name",)
    list_filter = ("category",)


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "author", "pages", "price")
    list_filter = ("author",)
    search_fields = ("title",)


@admin.register(FieldShowcase)
class FieldShowcaseAdmin(admin.ModelAdmin):
    list_display = ("id", "char_f", "fk_author")
    list_filter = ("bool_f",)


@admin.register(FieldShowcaseDetail)
class FieldShowcaseDetailAdmin(admin.ModelAdmin):
    list_display = ("id", "showcase", "note")


@admin.register(GenericBookmark)
class GenericBookmarkAdmin(admin.ModelAdmin):
    list_display = ("id", "label", "content_type", "object_id")
