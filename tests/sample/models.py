"""Sample models for django-importexport tests (including most Django field types)."""

from __future__ import annotations

from datetime import date

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Author(models.Model):
    name = models.CharField(_("Author name"), max_length=100)


class AuthorProfile(models.Model):
    """Demonstrates ``OneToOneField`` (profile pattern)."""

    author = models.OneToOneField(
        Author,
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name=_("Author"),
    )
    bio = models.TextField(_("Biography"), blank=True, default="")


class Category(models.Model):
    """Optional taxonomy for tags."""

    name = models.CharField(_("Category name"), max_length=100)

    def __str__(self) -> str:
        return self.name


class Tag(models.Model):
    """Target model for ``ManyToManyField``."""

    name = models.CharField(_("Tag label"), max_length=50)
    importance = models.PositiveSmallIntegerField(_("Importance"), default=0)
    category = models.ForeignKey(
        Category,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tags",
        verbose_name=_("Category"),
    )


class Book(models.Model):
    title = models.CharField(_("Book title"), max_length=100)
    pages = models.PositiveIntegerField(_("Nb. of pages"), default=0)
    price = models.DecimalField(
        _("Price"),
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    metadata = models.JSONField(_("Extra metadata"), default=dict, blank=True)
    publication_date = models.DateField(_("Publication date"), default=date.today)
    recorded_at = models.DateTimeField(_("Recorded at"), default=timezone.now)
    author = models.ForeignKey(
        Author,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        verbose_name=_("Author"),
    )
    tags = models.ManyToManyField(
        Tag,
        blank=True,
        related_name="books",
        verbose_name=_("Tags"),
    )


class FieldShowcase(models.Model):
    """
    One attribute per common Django database field type (scalar + FK + M2M).

    Relation-specific types (O2O child, GFK) live on ``FieldShowcaseDetail`` and
    ``GenericBookmark``.

    Not included (environment-specific or extra deps): ``FilePathField`` (absolute
    ``path`` in migrations), ``ImageField`` (Pillow), database-specific fields
    (e.g. PostgreSQL-only).
    """

    # --- Text ---
    char_f = models.CharField(max_length=50, blank=True, default="")
    text_f = models.TextField(blank=True, default="")
    slug_f = models.SlugField(blank=True, default="")
    email_f = models.EmailField(blank=True, default="")
    url_f = models.URLField(blank=True, default="")

    # --- Integers & floats ---
    int_f = models.IntegerField(null=True, blank=True)
    bigint_f = models.BigIntegerField(null=True, blank=True)
    smallint_f = models.SmallIntegerField(null=True, blank=True)
    posint_f = models.PositiveIntegerField(null=True, blank=True)
    possmall_f = models.PositiveSmallIntegerField(null=True, blank=True)
    posbigint_f = models.PositiveBigIntegerField(null=True, blank=True)
    float_f = models.FloatField(null=True, blank=True)
    decimal_f = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # --- Boolean ---
    bool_f = models.BooleanField(default=False)
    bool_null_f = models.BooleanField(null=True, blank=True)

    # --- Date / time ---
    date_f = models.DateField(null=True, blank=True)
    datetime_f = models.DateTimeField(null=True, blank=True)
    time_f = models.TimeField(null=True, blank=True)
    duration_f = models.DurationField(null=True, blank=True)

    # --- UUID / binary / JSON / IP ---
    uuid_f = models.UUIDField(null=True, blank=True)
    binary_f = models.BinaryField(null=True, blank=True)
    json_f = models.JSONField(default=dict, blank=True)
    ip_f = models.GenericIPAddressField(null=True, blank=True)

    # --- File (ImageField omitted: optional Pillow dependency) ---
    file_f = models.FileField(upload_to="sample_fc/", blank=True, null=True)

    # --- Relations ---
    fk_author = models.ForeignKey(
        Author,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="field_showcases",
    )
    tags_m2m = models.ManyToManyField(Tag, blank=True, related_name="field_showcases")


class FieldShowcaseDetail(models.Model):
    """Demonstrates ``OneToOneField`` from child to parent."""

    showcase = models.OneToOneField(
        FieldShowcase,
        on_delete=models.CASCADE,
        related_name="detail",
    )
    note = models.CharField(max_length=100, blank=True, default="")


class GenericBookmark(models.Model):
    """Demonstrates ``GenericForeignKey`` (contenttypes)."""

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")
    label = models.CharField(max_length=50, blank=True, default="")
