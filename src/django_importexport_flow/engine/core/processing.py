"""Run import and export requests through the standard hook pipeline."""

from __future__ import annotations

import traceback
from typing import Any

from django.utils import timezone

# Statuses that indicate a request has reached its final state.
_TERMINAL_STATUSES = ("success", "failure")


def _mark_request_failure(request: Any, error_trace: str) -> None:
    request.status = request.Status.FAILURE
    request.error_trace = error_trace
    request.completed_at = timezone.now()
    request.save(update_fields=["status", "error_trace", "completed_at"])


def _build_er_filter_payload(er: Any) -> dict[str, Any]:
    """
    Reconstruct the full export payload from a saved
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
    Persist a successful export onto *er* and save it.

    Shared by :func:`process_export_request` and
    :func:`~django_importexport_flow.utils.process.run_export_with_audit`
    so any field addition only needs a single change.
    """
    from ...models.request import attach_export_file, persist_export_request_files

    er.status = er.Status.SUCCESS
    er.output_bytes = len(content)
    er.error_trace = ""
    er.completed_at = timezone.now()
    attach_export_file(er, f"export{ext}", content)
    update_fields = [
        "status",
        "output_bytes",
        "error_trace",
        "completed_at",
    ]
    if persist_export_request_files():
        update_fields.append("output_file")
    er.save(update_fields=update_fields)


def process_import_request(ask: Any) -> Any:
    from ...models import ImportRequest
    from .run import run_import_request

    if not isinstance(ask, ImportRequest):
        raise TypeError("Expected ImportRequest instance.")

    ask.refresh_from_db()
    if ask.status in _TERMINAL_STATUSES:
        return ask
    try:
        return run_import_request(ask)
    except Exception:  # noqa: BLE001 — import hooks may raise anything
        _mark_request_failure(ask, traceback.format_exc())
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
    from .hooks import run_export_hooks

    if not isinstance(er, ExportRequest):
        raise TypeError("Expected ExportRequest instance.")

    er.refresh_from_db()
    if er.status in _TERMINAL_STATUSES:
        return er

    try:
        content, _content_type, ext = run_export_hooks(
            er.export_definition,
            _build_er_filter_payload(er),
            template_override=er.template_override or "",
            configuration_overrides=er.configuration_overrides or {},
        )
    except Exception:  # noqa: BLE001 — export hooks may raise anything
        _mark_request_failure(er, traceback.format_exc())
        return er
    _finalize_native_export(er, content, ext)
    return er
