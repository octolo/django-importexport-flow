from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.module_loading import import_string
from django.utils.translation import gettext_lazy as _

# Options that belong on a format config, never on the shared category configuration.
FORMAT_OPTION_KEYS = frozenset(
    {
        "csv",
        "excel",
        "json",
        "xml",
        "pdf",
        "docx",
        "word",
        "ods",
        "xls",
        "xlsx",
        "split_by",
    }
)


class CategoryConfigurationMixin(models.Model):
    """Shared options for one export or import category. No relation to the definition."""

    configuration = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Configuration"),
        help_text=_("Options shared by every format in this category."),
    )

    class Meta:
        abstract = True

    def clean(self) -> None:
        super().clean()
        configuration = self.configuration
        if configuration is None:
            self.configuration = {}
            return
        if not isinstance(configuration, dict):
            raise ValidationError({"configuration": _("Configuration must be an object.")})
        owned = sorted(set(configuration) & FORMAT_OPTION_KEYS)
        if owned:
            raise ValidationError(
                {
                    "configuration": _(
                        "Format-specific options belong on the format configuration: %(keys)s."
                    )
                    % {"keys": ", ".join(owned)}
                }
            )

    def get_common_configuration(self) -> dict[str, Any]:
        raw = self.configuration or {}
        if not isinstance(raw, dict):
            return {}
        return dict(raw)

    def get_effective_configuration(self, format_config: Any) -> dict[str, Any]:
        """Merge category options and the format options without mutating either."""
        specific = getattr(format_config, "configuration", None) or {}
        if not isinstance(specific, dict):
            specific = {}
        specific = dict(specific)
        merged = self.get_common_configuration()
        merged["format"] = specific
        format_key = getattr(format_config, "format_key", "") or ""
        if format_key:
            merged[format_key] = dict(specific)
        if format_key == "excel" and "split_by" in specific:
            merged["split_by"] = specific["split_by"]
        return merged


class ColumnSelectionMixin(models.Model):
    """Columns, shared annotations, and labels for a tabular export category."""

    columns = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_("Columns"),
        help_text=_(
            "List of field paths (author.name), JSON keys (metadata.lang), properties, "
            "expand specs (relation.*[field1:field2]), or annotation names declared in "
            "configuration (annotation_columns, annotations)."
        ),
    )

    class Meta:
        abstract = True

    def clean(self) -> None:
        super().clean()
        from ..utils.helpers import normalize_table_column, parse_reverse_expand_spec

        columns = self.columns
        if columns is None:
            self.columns = []
            return
        if not isinstance(columns, list):
            raise ValidationError({"columns": _("Columns must be a list of paths.")})
        cleaned: list[str] = []
        for item in columns:
            try:
                spec = normalize_table_column(item)
            except (TypeError, ValueError) as exc:
                raise ValidationError({"columns": str(exc)}) from exc
            if ".*[" in spec and parse_reverse_expand_spec(spec) is None:
                raise ValidationError(
                    {"columns": _("Invalid expand spec: %(spec)s.") % {"spec": spec}}
                )
            cleaned.append(spec)
        self.columns = cleaned

    def resolved_columns(self) -> list[str]:
        raw = self.columns or []
        if not isinstance(raw, list):
            return []
        return [str(item) for item in raw if str(item).strip()]


def normalize_hook_paths(value: Any) -> list[str]:
    """Return dotted paths. A string is one hook, or one path per line."""
    if value is None or value == "":
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                value = parsed
            else:
                return [text]
        else:
            return [line.strip() for line in text.splitlines() if line.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    raise ValueError(str(_("Hooks must be a list of dotted paths.")))


class FormatConfigurationMixin(models.Model):
    """Per-format options and an optional sequence of hook paths."""

    configuration = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Configuration"),
        help_text=_("Options for this format only."),
    )
    hook = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_("Hooks"),
        help_text=_(
            "Dotted paths, run in order. Leave empty to use the native hook for this format."
        ),
    )

    class Meta:
        abstract = True

    if TYPE_CHECKING:
        format_key: str
        category_config: Any

        @property
        def category_key(self) -> str: ...

        @property
        def direction(self) -> str: ...

    def clean(self) -> None:
        super().clean()
        from ..engine.core.formats import get_format

        spec = get_format(self.format_key)
        if spec is None:
            raise ValidationError(_("Format %(key)s is not available.") % {"key": self.format_key})
        if spec.category != self.category_key:
            raise ValidationError(
                _("Format %(key)s does not belong to category %(category)s.")
                % {"key": self.format_key, "category": self.category_key}
            )
        if self.direction == "export" and not spec.default_export_hook:
            raise ValidationError(
                _("Format %(key)s cannot be used for export.") % {"key": self.format_key}
            )
        if self.direction == "import" and not spec.default_import_hook:
            raise ValidationError(
                _("Format %(key)s cannot be used for import.") % {"key": self.format_key}
            )
        if self.configuration is None:
            self.configuration = {}
        elif not isinstance(self.configuration, dict):
            raise ValidationError({"configuration": _("Configuration must be an object.")})
        try:
            paths = normalize_hook_paths(self.hook)
        except ValueError as exc:
            raise ValidationError({"hook": str(exc)}) from exc
        self.hook = paths
        from ..engine.core.hooks import assert_custom_hook_allowed

        for path in paths:
            try:
                assert_custom_hook_allowed(path)
                resolved = import_string(path)
            except ImportError as exc:
                raise ValidationError({"hook": str(exc)}) from exc
            except ValidationError as exc:
                raise ValidationError({"hook": exc.messages}) from exc
            if not callable(resolved):
                raise ValidationError(
                    {"hook": _("Hook %(hook)s is not callable.") % {"hook": path}}
                )

    def get_format_spec(self) -> Any:
        from ..engine.core.formats import get_format

        spec = get_format(self.format_key)
        if spec is None:
            raise ValidationError(_("Format %(key)s is not available.") % {"key": self.format_key})
        return spec

    def get_effective_hooks(self) -> list[str]:
        """Configured paths, or the native hook when the list is empty."""
        custom = normalize_hook_paths(self.hook)
        if custom:
            return custom
        spec = self.get_format_spec()
        native = (
            spec.default_import_hook if self.direction == "import" else spec.default_export_hook
        )
        return [native] if native else []

    def get_effective_configuration(self) -> dict[str, Any]:
        return self.get_category().get_effective_configuration(self)

    def get_category(self) -> Any:
        return self.category_config

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)
