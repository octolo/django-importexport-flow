"""Public API: process/validate/generate helpers (lazy-loaded).

Other helpers: ``django_importexport_flow.utils.helpers``, ``.validation``, etc.
"""

from __future__ import annotations

__all__ = [
    "generate_example_file",
    "process_export",
    "process_import",
    "resolved_headers_for_import",
    "run_export_with_audit",
    "validate_import",
]


def __getattr__(name: str):
    if name == "process_export":
        from .process import process_export

        return process_export
    if name == "process_import":
        from .process import process_import

        return process_import
    if name == "validate_import":
        from .process import validate_import

        return validate_import
    if name == "run_export_with_audit":
        from .process import run_export_with_audit

        return run_export_with_audit
    if name == "generate_example_file":
        from .process import generate_example_file

        return generate_example_file
    if name == "resolved_headers_for_import":
        from .process import resolved_headers_for_import

        return resolved_headers_for_import
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(__all__)
