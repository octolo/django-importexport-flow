"""Optional dotted-path delegation for export and import definitions.

When ``delegate_method`` is set on an :class:`~django_importexport_flow.models.ExportDefinition`
or :class:`~django_importexport_flow.models.ImportDefinition`, the standard pipeline is
bypassed and a single callable resolved on the target model is invoked instead.

The callable receives every concrete definition field as a keyword argument plus the
flattened filter payload (``fr_get_*`` / ``fr_kw_*`` / ``mg_get_*`` / ``mg_kw_*`` /
``export_format``) and any extras forwarded by the caller (``file``, ``user``, ...).
"""

from __future__ import annotations

from typing import Any, Callable

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


_SKIPPED_DEFINITION_FIELDS = frozenset(
    {
        "uuid",
        "named_id",
        "created_by",
        "updated_by",
        "created_at",
        "updated_at",
    }
)


def resolve_delegate_method(model_cls: type, dotted_path: str) -> Callable[..., Any]:
    """Walk ``dotted_path`` on ``model_cls`` and return a callable.

    Intermediate manager-like attributes are kept as-is (no implicit call) so that a
    path like ``"objects.run_export"`` resolves to ``Model.objects.run_export``.
    """
    path = (dotted_path or "").strip()
    if not path:
        raise ValidationError(_("Delegate method path is empty."))
    obj: Any = model_cls
    for part in path.split("."):
        if not part:
            raise ValidationError(
                _("Invalid delegate method path “%(path)s”.") % {"path": dotted_path}
            )
        try:
            obj = getattr(obj, part)
        except AttributeError as exc:
            raise ValidationError(
                _("Delegate method “%(path)s” cannot be resolved on %(model)s.")
                % {"path": dotted_path, "model": model_cls.__name__}
            ) from exc
    if not callable(obj):
        raise ValidationError(
            _("Delegate method “%(path)s” on %(model)s is not callable.")
            % {"path": dotted_path, "model": model_cls.__name__}
        )
    return obj


def build_delegate_kwargs(
    definition: Any,
    filter_payload: dict[str, Any] | None,
    **extras: Any,
) -> dict[str, Any]:
    """Build a flat kwargs dict from definition fields + filter payload + extras."""
    kwargs: dict[str, Any] = {}
    meta = getattr(definition, "_meta", None)
    if meta is not None:
        for field in meta.concrete_fields:
            if field.name in _SKIPPED_DEFINITION_FIELDS:
                continue
            kwargs[field.name] = getattr(definition, field.name, None)
        for field in meta.many_to_many:
            try:
                kwargs[field.name] = list(getattr(definition, field.name).all())
            except Exception:
                kwargs[field.name] = []
    if filter_payload:
        for key, value in filter_payload.items():
            kwargs[key] = value
    for key, value in extras.items():
        kwargs[key] = value
    return kwargs


def has_delegate(definition: Any) -> bool:
    return bool((getattr(definition, "delegate_method", "") or "").strip())


def call_delegate(
    definition: Any,
    filter_payload: dict[str, Any] | None,
    **extras: Any,
) -> Any:
    """Resolve and invoke the delegate method on the target model."""
    target = getattr(definition, "target", None)
    model_cls = target.model_class() if target is not None else None
    if model_cls is None:
        raise ValidationError(
            _("Delegate method requires a target content type on the definition.")
        )
    method = resolve_delegate_method(model_cls, definition.delegate_method)
    return method(**build_delegate_kwargs(definition, filter_payload, **extras))
