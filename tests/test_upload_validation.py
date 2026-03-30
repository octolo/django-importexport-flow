"""Tests for upload content sniffing and configuration JSON shape checks."""

from __future__ import annotations

import pytest

from django_importexport_flow.utils.upload_validation import (
    validate_configuration_json_payload,
    validate_tabular_upload_bytes,
)


def test_csv_rejects_zip_magic():
    with pytest.raises(ValueError, match="xlsx|Excel"):
        validate_tabular_upload_bytes(b"PK\x03\x04" + b"x" * 20, "data.csv")


def test_xlsx_requires_zip_magic():
    with pytest.raises(ValueError, match="xlsx|ZIP"):
        validate_tabular_upload_bytes(b"not a zip", "book.xlsx")


def test_xls_requires_ole_magic():
    with pytest.raises(ValueError, match="xls|OLE"):
        validate_tabular_upload_bytes(b"not ole compound", "book.xls")


def test_csv_accepts_utf8_text():
    validate_tabular_upload_bytes("a,b\n1,2".encode(), "data.csv")


def test_configuration_payload_requires_objects():
    with pytest.raises(ValueError, match="objects"):
        validate_configuration_json_payload({"format_version": 1})

    with pytest.raises(ValueError, match="array"):
        validate_configuration_json_payload({"format_version": 1, "objects": {}})

    with pytest.raises(ValueError, match="model"):
        validate_configuration_json_payload({"format_version": 1, "objects": [{}]})

    validate_configuration_json_payload(
        {
            "format_version": 1,
            "objects": [
                {
                    "model": "django_importexport_flow.exportdefinition",
                    "pk": "00000000-0000-0000-0000-000000000001",
                    "fields": {"name": "X"},
                }
            ],
        }
    )


def test_configuration_format_version_must_be_int_if_present():
    with pytest.raises(ValueError, match="format_version"):
        validate_configuration_json_payload({"format_version": "1", "objects": []})
