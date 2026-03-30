"""Shared pytest fixtures for django-importexport-flow tests."""

from __future__ import annotations

import pytest


@pytest.fixture
def auditor_user(django_user_model):
    return django_user_model.objects.create_user(
        username="auditor",
        email="auditor@example.com",
        password="test-password-123",
    )
