"""Tests for :func:`django_importexport_flow.admin.import_config.run_json_configuration_import`."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from django.core.exceptions import ValidationError
from django.core.serializers.base import DeserializationError
from django.db import IntegrityError

from django_importexport_flow.admin.import_config import run_json_configuration_import


@pytest.fixture
def request_obj() -> MagicMock:
    return MagicMock()


@pytest.fixture
def form_obj() -> MagicMock:
    f = MagicMock()
    f.import_data = {"format_version": 1}
    return f


def test_run_json_configuration_import_success(request_obj, form_obj) -> None:
    def importer(data: dict) -> str:
        assert data is form_obj.import_data
        return "imported"

    assert (
        run_json_configuration_import(
            request_obj,
            form_obj,
            importer,
            log_label="test_import",
        )
        == "imported"
    )


@patch("django_importexport_flow.admin.import_config.messages")
def test_run_json_configuration_import_value_error(mock_messages, request_obj, form_obj) -> None:
    def importer(data: dict) -> None:
        raise ValueError("bad payload")

    assert (
        run_json_configuration_import(
            request_obj,
            form_obj,
            importer,
            log_label="test_import",
        )
        is None
    )
    mock_messages.error.assert_called_once_with(request_obj, "bad payload")


@patch("django_importexport_flow.admin.import_config.messages")
def test_run_json_configuration_import_validation_error(
    mock_messages, request_obj, form_obj
) -> None:
    err = ValidationError("invalid")

    def importer(data: dict) -> None:
        raise err

    assert (
        run_json_configuration_import(
            request_obj,
            form_obj,
            importer,
            log_label="test_import",
        )
        is None
    )
    mock_messages.error.assert_called_once_with(request_obj, str(err))


@pytest.mark.parametrize(
    "exc_factory",
    [
        lambda: DeserializationError("x"),
        lambda: IntegrityError(),
    ],
)
@patch("django_importexport_flow.admin.import_config.messages")
@patch("django_importexport_flow.admin.import_config.logger")
def test_run_json_configuration_import_deserialization_or_integrity(
    mock_logger,
    mock_messages,
    request_obj,
    form_obj,
    exc_factory,
) -> None:
    """DeserializationError and IntegrityError: no generic exception log, user message set."""

    def importer(data: dict) -> None:
        raise exc_factory()

    assert (
        run_json_configuration_import(
            request_obj,
            form_obj,
            importer,
            log_label="test_import",
        )
        is None
    )
    mock_messages.error.assert_called_once()
    assert mock_messages.error.call_args[0][0] is request_obj
    mock_logger.exception.assert_not_called()


@patch("django_importexport_flow.admin.import_config.messages")
@patch("django_importexport_flow.admin.import_config.logger")
def test_run_json_configuration_import_unexpected(
    mock_logger,
    mock_messages,
    request_obj,
    form_obj,
) -> None:
    def importer(data: dict) -> None:
        raise RuntimeError("boom")

    assert (
        run_json_configuration_import(
            request_obj,
            form_obj,
            importer,
            log_label="my_label",
        )
        is None
    )
    mock_logger.exception.assert_called_once_with("%s failed", "my_label")
    mock_messages.error.assert_called_once()
    assert mock_messages.error.call_args[0][0] is request_obj
