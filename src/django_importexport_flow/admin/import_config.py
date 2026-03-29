"""Shared admin logic for JSON report configuration import."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.serializers.base import DeserializationError
from django.db import IntegrityError
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)


def run_json_configuration_import(
    request: HttpRequest,
    form: Any,
    import_fn: Callable[[dict[str, Any]], Any],
    *,
    log_label: str,
) -> Any | None:
    """
    Call ``import_fn(form.import_data)`` and surface errors via messages.

    Returns the imported instance on success, or ``None`` on failure (the view
    should then return ``{"form": form}``).
    """
    try:
        return import_fn(form.import_data)
    except (ValueError, ValidationError) as exc:
        messages.error(request, str(exc))
        return None
    except DeserializationError as exc:
        logger.warning("%s JSON deserialize failed: %s", log_label, exc)
        messages.error(
            request,
            _("Could not read the configuration from this file."),
        )
        return None
    except IntegrityError as exc:
        logger.warning("%s import integrity error: %s", log_label, exc)
        messages.error(
            request,
            _("Import failed: this configuration conflicts with existing data."),
        )
        return None
    except Exception:
        logger.exception("%s failed", log_label)
        messages.error(
            request,
            _("Import failed. Check the file format and try again."),
        )
        return None
