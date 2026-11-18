"""Per-language column headers, edited in the admin and read at export and import time."""

from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _


class ColumnTranslation(models.Model):
    """
    Translation of one column path for one language.

    ``path`` is the column on ``content_type``'s model (``author.name``,
    ``metadata.lang``, ``title_len``). Slot columns share one row without the
    index (``tags.name``); the slot number is appended when the header is built.
    """

    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="column_translations",
        verbose_name=_("Content type"),
    )
    path = models.CharField(
        max_length=255,
        verbose_name=_("Path"),
        help_text=_("Column path on this model, e.g. author.name or tags.name."),
    )
    language = models.CharField(
        max_length=16,
        verbose_name=_("Language"),
        help_text=_("Language code, e.g. fr or en."),
    )
    label = models.CharField(max_length=255, verbose_name=_("Label"))

    class Meta:
        ordering = ("content_type", "path", "language")
        verbose_name = _("Column translation")
        verbose_name_plural = _("Column translations")
        constraints = (
            models.UniqueConstraint(
                fields=("content_type", "path", "language"),
                name="uniq_column_translation_path_language",
            ),
        )

    def __str__(self) -> str:
        return f"{self.path} [{self.language}] = {self.label}"

    def clean(self) -> None:
        super().clean()
        self.path = (self.path or "").strip()
        self.language = (self.language or "").replace("_", "-").strip().lower()
        self.label = (self.label or "").strip()

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)
