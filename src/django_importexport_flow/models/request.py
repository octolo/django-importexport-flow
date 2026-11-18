"""Persistent import/export requests and their optional related objects."""

from __future__ import annotations

import logging
import posixpath
import uuid
from datetime import datetime
from typing import Any

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage.base import Storage
from django.db import models
from django.db.models import QuerySet
from django.utils.translation import gettext_lazy as _
from django_boosted.models import AuditMixin

logger = logging.getLogger(__name__)

DEFAULT_EXPORT_UPLOAD_TO = "export_outputs/%Y/%m/"
DEFAULT_IMPORT_UPLOAD_TO = "report_import_asks/%Y/%m/"


class _SettingsStorage(Storage):
    """Resolve a storage setting on each operation, not when the model is imported."""

    def __init__(self, setting_name: str) -> None:
        self.setting_name = setting_name

    def _current(self) -> Storage:
        from django.core.files.storage import default_storage, storages
        from django.utils.module_loading import import_string

        from ..utils.helpers import get_setting

        value = get_setting(self.setting_name, None)
        if value in (None, ""):
            return default_storage
        if isinstance(value, Storage):
            return value
        if callable(value) and not isinstance(value, type):
            value = value()
            if isinstance(value, Storage):
                return value
            raise TypeError(f"{self.setting_name} callable must return a Django storage.")
        text = str(value)
        if text in getattr(settings, "STORAGES", {}):
            return storages[text]
        try:
            storage = import_string(text)
        except ImportError as exc:
            raise TypeError(f"{self.setting_name} {text!r} is not an importable storage.") from exc
        if isinstance(storage, type):
            storage = storage()
        if not isinstance(storage, Storage):
            raise TypeError(f"{self.setting_name} must point to a Django storage.")
        return storage

    def open(self, name, mode="rb"):
        return self._current().open(name, mode)

    def save(self, name, content, max_length=None):
        return self._current().save(name, content, max_length=max_length)

    def delete(self, name):
        return self._current().delete(name)

    def exists(self, name):
        return self._current().exists(name)

    def listdir(self, path):
        return self._current().listdir(path)

    def size(self, name):
        return self._current().size(name)

    def url(self, name):
        return self._current().url(name)

    def path(self, name):
        return self._current().path(name)

    def generate_filename(self, filename):
        return self._current().generate_filename(filename)

    def get_available_name(self, name, max_length=None):
        return self._current().get_available_name(name, max_length=max_length)

    def get_accessed_time(self, name):
        return self._current().get_accessed_time(name)

    def get_created_time(self, name):
        return self._current().get_created_time(name)

    def get_modified_time(self, name):
        return self._current().get_modified_time(name)


def _export_output_storage():
    """Storage for ``ExportRequest.output_file``, from ``EXPORT_OUTPUT_STORAGE``."""
    return _SettingsStorage("EXPORT_OUTPUT_STORAGE")


def _import_file_storage():
    """Storage for ``ImportRequest.data_file``, from ``IMPORT_FILE_STORAGE``."""
    return _SettingsStorage("IMPORT_FILE_STORAGE")


def _resolve_upload_to(setting_name: str, default: str, instance: Any, filename: str) -> str:
    from django.utils.module_loading import import_string

    from ..utils.helpers import get_setting

    value = get_setting(setting_name, None)
    if value in (None, ""):
        value = default
    if callable(value):
        return value(instance, filename)
    text = str(value).strip()
    if "." in text and "/" not in text:
        try:
            callback = import_string(text)
        except ImportError as exc:
            raise TypeError(f"{setting_name} {text!r} is not an importable callable.") from exc
        if not callable(callback):
            raise TypeError(f"{setting_name} must be a path template or a callable.")
        return callback(instance, filename)
    return posixpath.join(datetime.now().strftime(text), filename)


def export_output_upload_to(instance: Any, filename: str) -> str:
    """Path for an export file. Override with ``EXPORT_OUTPUT_UPLOAD_TO``."""
    return _resolve_upload_to(
        "EXPORT_OUTPUT_UPLOAD_TO",
        DEFAULT_EXPORT_UPLOAD_TO,
        instance,
        filename,
    )


def import_file_upload_to(instance: Any, filename: str) -> str:
    """Path for an import file. Override with ``IMPORT_FILE_UPLOAD_TO``."""
    return _resolve_upload_to(
        "IMPORT_FILE_UPLOAD_TO",
        DEFAULT_IMPORT_UPLOAD_TO,
        instance,
        filename,
    )


def persist_import_request_files() -> bool:
    """Whether an import request stores its uploaded file."""
    from ..utils.helpers import get_setting

    return bool(get_setting("PERSIST_IMPORT_REQUEST_FILES"))


def persist_export_request_files() -> bool:
    """Whether an export request stores its generated file."""
    from ..utils.helpers import get_setting

    return bool(get_setting("PERSIST_EXPORT_REQUEST_FILES"))


def attach_import_file(request: Any, name: str, raw: bytes, *, keep_for_later: bool) -> None:
    """Store an import upload on the request, or keep it in memory for this call."""
    if persist_import_request_files():
        request.data_file.save(name, ContentFile(raw), save=True)
        return
    if keep_for_later:
        raise ValueError(
            "PERSIST_IMPORT_REQUEST_FILES must be enabled when the import file is read later."
        )
    request._memory_file = ContentFile(raw, name=name)


def attach_export_file(request: Any, name: str, content: bytes) -> None:
    """Remember export bytes and, when enabled, write them to ``output_file``."""
    request._memory_file = ContentFile(content, name=name)
    if persist_export_request_files():
        request.output_file.save(name, ContentFile(content), save=False)


def request_file(request: Any, field_name: str) -> Any:
    """Return the in-memory file for this call, or the stored field."""
    memory = getattr(request, "_memory_file", None)
    if memory is not None:
        if hasattr(memory, "seek"):
            memory.seek(0)
        return memory
    stored = getattr(request, field_name)
    if stored:
        return stored
    raise ValueError("Request has no file.")


class ExportRequest(AuditMixin, models.Model):
    """
    One **Generate export** action in the admin: format + filter snapshot (``fr_*``),
    optional request template and configuration, and output size on success or
    ``error_trace`` on failure.
    """

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        PROCESSING = "processing", _("Processing")
        SUCCESS = "success", _("Success")
        FAILURE = "failure", _("Failure")

    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        verbose_name=_("UUID"),
    )
    export_definition = models.ForeignKey(
        "Definition",
        on_delete=models.CASCADE,
        related_name="export_requests",
        verbose_name=_("Export definition"),
    )
    export_format = models.CharField(
        max_length=16,
        blank=True,
        verbose_name=_("Export format"),
        help_text=_("csv, excel, or json."),
    )
    filter_payload = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Filter form payload"),
        help_text=_("export_format plus fr_get_* / fr_kw_* from the export form."),
    )
    manager_kwargs_payload = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Manager kwargs form payload"),
        help_text=_(
            "mg_get_* / mg_kw_* from the export form (manager_kwargs_* on the definition)."
        ),
    )
    template_override = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Template override"),
        help_text=_("PDF only. Leave empty to use the template stored on the format."),
    )
    configuration_overrides = models.JSONField(
        blank=True,
        default=dict,
        verbose_name=_("Configuration overrides"),
        help_text=_(
            'Optional request options: {"format": {...}, "hook": {...}}. '
            "format accepts native options for the selected format; hook is passed to hooks."
        ),
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name=_("Status"),
    )
    output_file = models.FileField(
        upload_to=export_output_upload_to,
        storage=_export_output_storage,
        blank=True,
        verbose_name=_("Output file"),
        help_text=_("Generated export file when status is success."),
    )
    output_bytes = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Output size (bytes)"),
        help_text=_("Set when export completed successfully."),
    )
    error_trace = models.TextField(
        blank=True,
        verbose_name=_("Error trace"),
        help_text=_("Message or traceback when status is failure."),
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Completed at"),
    )
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="initiated_export_requests",
        verbose_name=_("Initiated by"),
        help_text=_("User who ran the export in the admin."),
    )

    class Meta:
        ordering = ("-created_at",)
        verbose_name = _("Export request")
        verbose_name_plural = _("Export requests")

    def __str__(self) -> str:
        return f"{self.export_definition_id} · {self.get_status_display()} · {self.uuid}"

    def clean(self) -> None:
        from ..engine.core.overrides import (
            normalize_configuration_overrides,
            validate_template_override,
        )

        super().clean()
        definition = self.export_definition
        if definition is not None and definition.direction != "export":
            raise ValidationError(
                {"export_definition": _("An export request requires an export definition.")}
            )
        export_format = self.export_format or ""
        try:
            self.configuration_overrides = normalize_configuration_overrides(
                self.configuration_overrides,
                export_format=export_format,
            )
        except ValidationError as exc:
            raise ValidationError({"configuration_overrides": exc.messages}) from exc
        try:
            self.template_override = validate_template_override(
                self.template_override,
                export_format=export_format,
            )
        except ValidationError as exc:
            raise ValidationError({"template_override": exc.messages}) from exc

    def save(
        self,
        *args: Any,
        trigger_processing: bool = False,
        asynchronous: bool = False,
        **kwargs: Any,
    ) -> None:
        self.clean()
        super().save(*args, **kwargs)
        if not trigger_processing or self.status != self.Status.PENDING:
            return
        from ..task import dispatch_export_request

        dispatch_export_request(self, asynchronous=asynchronous)


class ImportRequest(AuditMixin, models.Model):
    """
    One user upload + filter snapshot for a tabular import. Each confirmation or
    relaunch creates a **new** row so history stays linear; failed rows keep
    ``error_trace`` for support.

    Optional business scope via :class:`~django_importexport_flow.models.ImportRequestRelatedObject`
    (see admin inlines or :meth:`active_imports_for_object`).
    """

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        PROCESSING = "processing", _("Processing")
        SUCCESS = "success", _("Success")
        FAILURE = "failure", _("Failure")

    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        verbose_name=_("UUID"),
    )
    import_definition = models.ForeignKey(
        "Definition",
        on_delete=models.CASCADE,
        related_name="import_requests",
        verbose_name=_("Import definition"),
    )
    relaunched_from = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="relaunches",
        verbose_name=_("Relaunched from"),
        help_text=_("Previous request when this row was created by “Relaunch”."),
    )
    data_file = models.FileField(
        upload_to=import_file_upload_to,
        storage=_import_file_storage,
        verbose_name=_("Uploaded file"),
    )
    filter_payload = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Filter form payload"),
        help_text=_("Keys fr_get_* / fr_kw_* from the import wizard."),
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name=_("Status"),
    )
    imported_row_count = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Imported row count"),
    )
    error_trace = models.TextField(
        blank=True,
        verbose_name=_("Error trace"),
        help_text=_("Traceback or per-row errors when status is failure."),
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Completed at"),
    )
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="import_requests",
        verbose_name=_("Initiated by"),
        help_text=_("User who started the import (wizard or relaunch)."),
    )

    class Meta:
        ordering = ("-created_at",)
        verbose_name = _("Import request")
        verbose_name_plural = _("Import requests")

    def __str__(self) -> str:
        return f"{self.import_definition_id} · {self.get_status_display()} · {self.uuid}"

    def clean(self) -> None:
        super().clean()
        definition = self.import_definition
        if definition is not None and definition.direction != "import":
            raise ValidationError(
                {"import_definition": _("An import request requires an import definition.")}
            )

    def save(
        self,
        *args: Any,
        trigger_processing: bool = False,
        asynchronous: bool = False,
        **kwargs: Any,
    ) -> None:
        self.clean()
        super().save(*args, **kwargs)
        if not trigger_processing or self.status != self.Status.PENDING:
            return
        from ..task import dispatch_import_request

        dispatch_import_request(self, asynchronous=asynchronous)

    @classmethod
    def active_imports_for_object(cls, obj: Any) -> QuerySet[ImportRequest]:
        """
        Import requests still **pending** or **processing** linked to ``obj`` through
        :class:`~django_importexport_flow.models.ImportRequestRelatedObject`.
        """
        ct = ContentType.objects.get_for_model(obj, for_concrete_model=False)
        return cls.objects.filter(
            related_object_links__content_type=ct,
            related_object_links__object_id=str(obj.pk),
            status__in=(cls.Status.PENDING, cls.Status.PROCESSING),
        ).distinct()


class BaseRequestRelatedObject(models.Model):
    """Abstract: ContentType + object id + GenericFK + stored ``str`` for deleted targets."""

    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        verbose_name=_("Content type"),
        help_text=_("Model of the related instance."),
    )
    object_id = models.CharField(
        max_length=64,
        verbose_name=_("Object id"),
        help_text=_("Primary key as string (integer or UUID)."),
    )
    content_object = GenericForeignKey("content_type", "object_id")
    object_str = models.CharField(
        max_length=500,
        blank=True,
        default="",
        editable=False,
        verbose_name=_("Object representation"),
        help_text=_("Snapshot when saved; kept if the related row is deleted."),
    )

    class Meta:
        abstract = True
        ordering = ("pk",)

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.content_type_id and self.object_id:
            try:
                obj = self.content_object
                if obj is not None:
                    self.object_str = str(obj)[:500]
            except Exception:
                # ``__str__`` on an arbitrary related model can raise anything; the snapshot is optional.
                logger.warning(
                    "Could not snapshot related object %s:%s",
                    self.content_type_id,
                    self.object_id,
                    exc_info=True,
                )
        super().save(*args, **kwargs)


class ImportRequestRelatedObject(BaseRequestRelatedObject):
    import_request = models.ForeignKey(
        "ImportRequest",
        on_delete=models.CASCADE,
        related_name="related_object_links",
        verbose_name=_("Import request"),
    )

    class Meta:
        verbose_name = _("Import request related object")
        verbose_name_plural = _("Import request related objects")


class ExportRequestRelatedObject(BaseRequestRelatedObject):
    export_request = models.ForeignKey(
        "ExportRequest",
        on_delete=models.CASCADE,
        related_name="related_object_links",
        verbose_name=_("Export request"),
    )

    class Meta:
        verbose_name = _("Export request related object")
        verbose_name_plural = _("Export request related objects")
