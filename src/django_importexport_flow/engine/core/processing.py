"""Resolve ``processing_backend`` and run import/export requests."""

from __future__ import annotations

import traceback
from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django.core.files.base import ContentFile
from django.utils import timezone
from django.utils.module_loading import import_string

# Statuses that indicate a request has reached its final state.
_TERMINAL_STATUSES = ("success", "failure")


def _processing_kwargs(kwargs_field: dict[str, Any] | None) -> dict[str, Any]:
    return dict(kwargs_field or {})


def get_import_processing_config(import_definition: Any) -> tuple[str, dict[str, Any]]:
    backend = (import_definition.processing_backend or "").strip()
    return backend, _processing_kwargs(import_definition.processing_backend_kwargs)


def get_export_processing_config(export_definition: Any) -> tuple[str, dict[str, Any]]:
    for related_name in ("config_table", "config_pdf"):
        try:
            config = getattr(export_definition, related_name)
        except ObjectDoesNotExist:
            continue
        return (
            (config.processing_backend or "").strip(),
            _processing_kwargs(config.processing_backend_kwargs),
        )
    return "", {}


def _method_name_from_backend(backend: str) -> str:
    return backend.rsplit(".", 1)[-1] if "." in backend else backend


def _try_import_path(backend_path: str, request: Any, kwargs: dict[str, Any]) -> None:
    fn = import_string(backend_path)
    if not callable(fn):
        raise TypeError(f"{backend_path!r} is not callable")
    fn(request, **kwargs)


def _try_model_method(
    model: type,
    method_name: str,
    request: Any,
    kwargs: dict[str, Any],
) -> None:
    """
    Call ``model.method_name(request, **kwargs)``.

    The method must be a ``@classmethod`` or ``@staticmethod`` with the signature
    ``(cls_or_no_arg, request, **kwargs)``.  Instance methods are not supported
    because ``model`` is the class, not an instance.
    """
    fn = getattr(model, method_name, None)
    if fn is None:
        raise AttributeError(
            f"Model {model.__name__!r} has no attribute {method_name!r}"
        )
    if not callable(fn):
        raise TypeError(f"{model.__name__}.{method_name} is not callable")
    fn(request, **kwargs)


def _mark_request_failure(request: Any, error_trace: str) -> None:
    request.status = request.Status.FAILURE
    request.error_trace = error_trace
    request.completed_at = timezone.now()
    request.save(update_fields=["status", "error_trace", "completed_at"])


def _build_er_filter_payload(er: Any) -> dict[str, Any]:
    """
    Reconstruct the full ``run_table_export`` payload from a saved
    :class:`~django_importexport_flow.models.ExportRequest`.

    Always use this instead of re-assembling manually, so both
    :func:`process_export_request` and
    :func:`~django_importexport_flow.utils.process.run_export_with_audit`
    produce identical payloads for the same request.

    The stored fields are guaranteed to be disjoint (fr_* in ``filter_payload``,
    mg_* in ``manager_kwargs_payload``), so the merge is collision-free.
    ``export_format`` falls back to ``er.export_format`` for requests created
    programmatically without it in ``filter_payload``.
    """
    payload: dict[str, Any] = dict(er.filter_payload or {})
    payload.setdefault("export_format", er.export_format)
    if er.manager_kwargs_payload:
        payload.update(er.manager_kwargs_payload)
    return payload


def _finalize_native_export(er: Any, content: bytes, ext: str) -> None:
    """
    Persist a successful native export onto *er* and save it.

    Shared by :func:`process_export_request` and
    :func:`~django_importexport_flow.utils.process.run_export_with_audit`
    so any field addition only needs a single change.
    """
    er.status = er.Status.SUCCESS
    er.output_bytes = len(content)
    er.error_trace = ""
    er.completed_at = timezone.now()
    er.output_file.save(f"export{ext}", ContentFile(content), save=False)
    er.save(
        update_fields=[
            "status",
            "output_bytes",
            "error_trace",
            "completed_at",
            "output_file",
        ]
    )


def run_custom_processing(
    request: Any,
    *,
    backend: str,
    kwargs: dict[str, Any],
    target_model: type | None,
) -> None:
    """
    Try ``backend`` as a dotted import path first, then as a method name on
    ``target_model``.  On total failure mark the request as ``failure``.

    The callable receives ``(request, **kwargs)`` where ``request`` is the
    :class:`~django_importexport_flow.models.ImportRequest` or
    :class:`~django_importexport_flow.models.ExportRequest` instance.  It is
    responsible for updating the request status before returning.
    """
    errors: list[str] = []

    try:
        _try_import_path(backend, request, kwargs)
        return
    except Exception as exc:
        errors.append(f"import path ({backend!r}): {exc}")

    method_name = _method_name_from_backend(backend)
    if target_model is not None:
        try:
            _try_model_method(target_model, method_name, request, kwargs)
            return
        except Exception as exc:
            errors.append(f"model method ({target_model.__name__}.{method_name}): {exc}")
    else:
        errors.append("no target content type for model-method fallback")

    _mark_request_failure(request, "\n".join(errors))


def _ensure_custom_processing_finished(request: Any) -> None:
    """Mark as failure if the custom backend returned without updating the status."""
    request.refresh_from_db()
    if request.status not in _TERMINAL_STATUSES:
        _mark_request_failure(
            request,
            "processing_backend completed without updating request status",
        )


def process_import_request(ask: Any) -> Any:
    from ...models import ImportRequest
    from .run import run_import_request

    if not isinstance(ask, ImportRequest):
        raise TypeError("Expected ImportRequest instance.")

    ask.refresh_from_db()
    if ask.status in _TERMINAL_STATUSES:
        return ask

    definition = ask.import_definition
    backend, kwargs = get_import_processing_config(definition)
    if not backend:
        return run_import_request(ask)

    target = definition.target.model_class() if definition.target_id else None
    try:
        run_custom_processing(ask, backend=backend, kwargs=kwargs, target_model=target)
    except Exception:
        _mark_request_failure(ask, traceback.format_exc())
        return ask

    _ensure_custom_processing_finished(ask)
    return ask


def process_export_request(er: Any) -> Any:
    """
    Run processing for a :class:`~django_importexport_flow.models.ExportRequest`
    that has already been set to ``processing`` status.

    Used by the :meth:`~django_importexport_flow.models.ExportRequest.save`
    ``trigger_processing=True`` path (programmatic / async).

    Both this function and :func:`~django_importexport_flow.utils.process.run_export_with_audit`
    persist the result in ``output_file`` on success.  Use
    ``run_export_with_audit`` when you need the bytes returned directly and the
    original exception type preserved (e.g. HTTP response path).
    """
    from ...models import ExportRequest
    from .export import run_table_export

    if not isinstance(er, ExportRequest):
        raise TypeError("Expected ExportRequest instance.")

    er.refresh_from_db()
    if er.status in _TERMINAL_STATUSES:
        return er

    definition = er.export_definition
    backend, kwargs = get_export_processing_config(definition)
    if not backend:
        try:
            content, _content_type, ext = run_table_export(
                definition, _build_er_filter_payload(er)
            )
        except Exception:
            _mark_request_failure(er, traceback.format_exc())
            return er
        _finalize_native_export(er, content, ext)
        return er

    target = definition.target.model_class() if definition.target_id else None
    try:
        run_custom_processing(er, backend=backend, kwargs=kwargs, target_model=target)
    except Exception:
        _mark_request_failure(er, traceback.format_exc())
        return er

    _ensure_custom_processing_finished(er)
    return er
