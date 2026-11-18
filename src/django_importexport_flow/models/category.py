from __future__ import annotations

from typing import Any, ClassVar

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from ..engine.core.formats import DOCUMENT, SPREADSHEET, STRUCTURED_DATA
from .definition import Definition
from .mixins import CategoryConfigurationMixin, ColumnSelectionMixin

_CATEGORY_LABELS = {
    SPREADSHEET: _("Config spreadsheet"),
    DOCUMENT: _("Config document"),
    STRUCTURED_DATA: _("Config structured data"),
}


class CategoryConfig(CategoryConfigurationMixin, ColumnSelectionMixin):
    """Shared options for one category of a definition."""

    definition = models.ForeignKey(
        Definition,
        on_delete=models.CASCADE,
        related_name="category_configs",
        verbose_name=_("Definition"),
    )
    category_key = models.CharField(
        max_length=32,
        choices=(
            (SPREADSHEET, _("Spreadsheet")),
            (DOCUMENT, _("Document")),
            (STRUCTURED_DATA, _("Structured data")),
        ),
        verbose_name=_("Category"),
    )

    class Meta:
        ordering = ("definition", "category_key")
        verbose_name = _("Category config")
        verbose_name_plural = _("Category configs")
        constraints = (
            models.UniqueConstraint(
                fields=["definition", "category_key"],
                name="category_config_definition_key_uniq",
            ),
        )

    def __str__(self) -> str:
        label = _CATEGORY_LABELS.get(self.category_key, self.category_key)
        return f"{label} — {self.definition.name}"

    @property
    def direction(self) -> str:
        return self.definition.direction

    def clean(self) -> None:
        super().clean()
        if self.category_key == DOCUMENT and self.definition_id:
            if self.definition.direction == Definition.Direction.IMPORT:
                raise ValidationError(
                    {"category_key": _("Document categories are not available for import.")}
                )
            if self.columns:
                raise ValidationError({"columns": _("Document categories do not store columns.")})

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


def _choice_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    if isinstance(raw, str):
        return raw
    raise TypeError("Expected a choice value.")


def _category_manager(direction: Any, category_key: str = ""):
    direction = _choice_value(direction)

    class Manager(models.Manager):
        def get_queryset(self):
            queryset = super().get_queryset().filter(definition__direction=direction)
            if category_key:
                queryset = queryset.filter(category_key=category_key)
            return queryset

    return Manager()


def _reject_wrong_direction(category: CategoryConfig, direction: Any) -> None:
    direction = _choice_value(direction)
    if category.definition_id and category.definition.direction != direction:
        raise ValidationError({"definition": _("This category does not belong to this direction.")})


class _CategoryKeyProxyMixin:
    category_key_value = ""
    category_key: str

    def full_clean(self, *args: Any, **kwargs: Any) -> None:
        self.category_key = self.category_key_value
        super().full_clean(*args, **kwargs)  # type: ignore[misc]

    def clean(self) -> None:
        self.category_key = self.category_key_value
        super().clean()  # type: ignore[misc]


class ExportCategoryConfig(CategoryConfig):
    objects: ClassVar[models.Manager[Any]] = _category_manager(Definition.Direction.EXPORT)

    class Meta:
        proxy = True
        verbose_name = _("Export config")
        verbose_name_plural = _("Export configs")

    def clean(self) -> None:
        _reject_wrong_direction(self, Definition.Direction.EXPORT)
        super().clean()


class ImportCategoryConfig(CategoryConfig):
    objects: ClassVar[models.Manager[Any]] = _category_manager(Definition.Direction.IMPORT)

    class Meta:
        proxy = True
        verbose_name = _("Import config")
        verbose_name_plural = _("Import configs")

    def clean(self) -> None:
        _reject_wrong_direction(self, Definition.Direction.IMPORT)
        super().clean()


class ExportSpreadsheetConfig(_CategoryKeyProxyMixin, ExportCategoryConfig):
    category_key_value = SPREADSHEET
    objects: ClassVar[models.Manager[Any]] = _category_manager(
        Definition.Direction.EXPORT, SPREADSHEET
    )

    class Meta:
        proxy = True
        verbose_name = _("Config spreadsheet")
        verbose_name_plural = _("Config spreadsheets")


class ExportDocumentConfig(_CategoryKeyProxyMixin, ExportCategoryConfig):
    category_key_value = DOCUMENT
    objects: ClassVar[models.Manager[Any]] = _category_manager(
        Definition.Direction.EXPORT, DOCUMENT
    )

    class Meta:
        proxy = True
        verbose_name = _("Config document")
        verbose_name_plural = _("Config documents")


class ExportStructuredDataConfig(_CategoryKeyProxyMixin, ExportCategoryConfig):
    category_key_value = STRUCTURED_DATA
    objects: ClassVar[models.Manager[Any]] = _category_manager(
        Definition.Direction.EXPORT, STRUCTURED_DATA
    )

    class Meta:
        proxy = True
        verbose_name = _("Config structured data")
        verbose_name_plural = _("Config structured data")


class ImportSpreadsheetConfig(_CategoryKeyProxyMixin, ImportCategoryConfig):
    category_key_value = SPREADSHEET
    objects: ClassVar[models.Manager[Any]] = _category_manager(
        Definition.Direction.IMPORT, SPREADSHEET
    )

    class Meta:
        proxy = True
        verbose_name = _("Config spreadsheet")
        verbose_name_plural = _("Config spreadsheets")


class ImportStructuredDataConfig(_CategoryKeyProxyMixin, ImportCategoryConfig):
    category_key_value = STRUCTURED_DATA
    objects: ClassVar[models.Manager[Any]] = _category_manager(
        Definition.Direction.IMPORT, STRUCTURED_DATA
    )

    class Meta:
        proxy = True
        verbose_name = _("Config structured data")
        verbose_name_plural = _("Config structured data")
