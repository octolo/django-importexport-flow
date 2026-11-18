from __future__ import annotations

from typing import Any, ClassVar

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from ..engine.core.formats import DOCUMENT, get_format
from .category import CategoryConfig
from .mixins import FormatConfigurationMixin

_FORMAT_LABELS = {
    "csv": _("Format CSV"),
    "excel": _("Format Excel"),
    "pdf": _("Format PDF"),
    "json": _("Format JSON"),
}


class FormatConfig(FormatConfigurationMixin):
    """One enabled format. Deleting the row disables that format."""

    category_config = models.ForeignKey(
        CategoryConfig,
        on_delete=models.CASCADE,
        related_name="format_configs",
        verbose_name=_("Category config"),
    )
    format_key = models.CharField(max_length=32, verbose_name=_("Format"))
    template = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Template"),
        help_text=_("Template rendered for a document format."),
    )

    class Meta:
        ordering = ("category_config", "format_key")
        verbose_name = _("Format config")
        verbose_name_plural = _("Format configs")
        constraints = (
            models.UniqueConstraint(
                fields=["category_config", "format_key"],
                name="format_config_category_key_uniq",
            ),
        )

    def __str__(self) -> str:
        label = _FORMAT_LABELS.get(self.format_key, self.format_key)
        return f"{label} — {self.category_config.definition.name}"

    @property
    def category_key(self) -> str:
        return self.category_config.category_key

    @property
    def direction(self) -> str:
        return self.category_config.direction

    def clean(self) -> None:
        super().clean()
        if self.template is None:
            self.template = ""
        spec = get_format(self.format_key)
        document_format = spec is not None and spec.category == DOCUMENT
        if (self.template or "").strip() and not document_format:
            raise ValidationError({"template": _("Only a document format can store a template.")})

    def render_options(self) -> dict[str, Any]:
        return {
            "template": self.template or "",
            "configuration": self.get_effective_configuration(),
        }


def _format_manager(direction: str, format_key: str = ""):
    class Manager(models.Manager):
        def get_queryset(self):
            queryset = (
                super().get_queryset().filter(category_config__definition__direction=direction)
            )
            if format_key:
                queryset = queryset.filter(format_key=format_key)
            return queryset

    return Manager()


def _reject_format_direction(config: FormatConfig, direction: str) -> None:
    if config.category_config_id and config.category_config.direction != direction:
        raise ValidationError(
            {"category_config": _("This format does not belong to this direction.")}
        )


class _FormatKeyProxyMixin:
    format_key_value = ""
    format_key: str

    def full_clean(self, *args: Any, **kwargs: Any) -> None:
        self.format_key = self.format_key_value
        super().full_clean(*args, **kwargs)  # type: ignore[misc]

    def clean(self) -> None:
        self.format_key = self.format_key_value
        super().clean()  # type: ignore[misc]


class ExportFormatConfig(FormatConfig):
    objects: ClassVar[models.Manager[Any]] = _format_manager("export")

    class Meta:
        proxy = True
        verbose_name = _("Export format")
        verbose_name_plural = _("Export formats")

    def clean(self) -> None:
        _reject_format_direction(self, "export")
        super().clean()


class ImportFormatConfig(FormatConfig):
    objects: ClassVar[models.Manager[Any]] = _format_manager("import")

    class Meta:
        proxy = True
        verbose_name = _("Import format")
        verbose_name_plural = _("Import formats")

    def clean(self) -> None:
        _reject_format_direction(self, "import")
        super().clean()


class ExportCsvFormat(_FormatKeyProxyMixin, ExportFormatConfig):
    format_key_value = "csv"
    objects: ClassVar[models.Manager[Any]] = _format_manager("export", "csv")

    class Meta:
        proxy = True
        verbose_name = _("Format CSV")
        verbose_name_plural = _("Format CSV")


class ExportExcelFormat(_FormatKeyProxyMixin, ExportFormatConfig):
    format_key_value = "excel"
    objects: ClassVar[models.Manager[Any]] = _format_manager("export", "excel")

    class Meta:
        proxy = True
        verbose_name = _("Format Excel")
        verbose_name_plural = _("Format Excel")


class ExportJsonFormat(_FormatKeyProxyMixin, ExportFormatConfig):
    format_key_value = "json"
    objects: ClassVar[models.Manager[Any]] = _format_manager("export", "json")

    class Meta:
        proxy = True
        verbose_name = _("Format JSON")
        verbose_name_plural = _("Format JSON")


class ExportPdfFormat(_FormatKeyProxyMixin, ExportFormatConfig):
    format_key_value = "pdf"
    objects: ClassVar[models.Manager[Any]] = _format_manager("export", "pdf")

    class Meta:
        proxy = True
        verbose_name = _("Format PDF")
        verbose_name_plural = _("Format PDF")


class ImportCsvFormat(_FormatKeyProxyMixin, ImportFormatConfig):
    format_key_value = "csv"
    objects: ClassVar[models.Manager[Any]] = _format_manager("import", "csv")

    class Meta:
        proxy = True
        verbose_name = _("Format CSV")
        verbose_name_plural = _("Format CSV")


class ImportExcelFormat(_FormatKeyProxyMixin, ImportFormatConfig):
    format_key_value = "excel"
    objects: ClassVar[models.Manager[Any]] = _format_manager("import", "excel")

    class Meta:
        proxy = True
        verbose_name = _("Format Excel")
        verbose_name_plural = _("Format Excel")
