"""Sample admin view that loads or reloads the demo fixtures."""

from __future__ import annotations

import pytest
from django.db.models.deletion import ProtectedError
from django.urls import reverse

from django_importexport_flow.models import Definition, Step
from tests.sample.boosted_views import SAMPLE_FIXTURE_PREFIX, load_sample_fixtures
from tests.sample.models import Book


@pytest.mark.django_db
def test_load_sample_fixtures_keeps_rows_added_after_the_catalog():
    load_sample_fixtures(replace=False)
    Book.objects.create(title="Extra", pages=1)
    load_sample_fixtures(replace=False)
    assert Book.objects.filter(title="Extra").exists()
    assert Book.objects.filter(title="The Habit of Excellence").exists()
    assert Definition.objects.filter(name__startswith=SAMPLE_FIXTURE_PREFIX).exists()
    assert Step.objects.filter(
        parent__named_id='sample-fixture-import-books-combined',
    ).count() == 2


@pytest.mark.django_db
def test_reload_sample_fixtures_drops_rows_outside_the_catalog():
    load_sample_fixtures(replace=False)
    Book.objects.create(title="Extra", pages=1)
    load_sample_fixtures(replace=True)
    assert not Book.objects.filter(title="Extra").exists()
    assert Book.objects.filter(title="The Habit of Excellence").count() == 1
    assert Book.objects.count() == 3
    assert Step.objects.filter(
        parent__named_id='sample-fixture-import-books-combined',
    ).count() == 2


@pytest.mark.django_db
def test_reload_preserves_externally_referenced_sample_definitions():
    load_sample_fixtures(replace=False)
    child = Definition.objects.get(
        named_id='sample-fixture-import-books-match-title',
    )
    parent = Definition.objects.create(
        name='External combined import',
        direction='import',
        target=child.target,
    )
    Step.objects.create(parent=parent, definition=child, position=1)

    with pytest.raises(ProtectedError):
        load_sample_fixtures(replace=True)

    assert Step.objects.filter(parent=parent, definition=child).exists()
    assert Book.objects.filter(title='The Habit of Excellence').exists()


@pytest.mark.django_db
def test_load_sample_fixtures_view_reloads_from_the_admin(admin_user, client):
    client.force_login(admin_user)
    url = reverse("admin:django_boosted_boostedview_load_sample_fixtures_view")
    page = client.get(url)
    assert page.status_code == 200
    assert b"Reload" in page.content
    Book.objects.create(title="Extra", pages=1)
    response = client.post(url, {"_reload": "Reload"})
    assert response.status_code == 302
    assert not Book.objects.filter(title="Extra").exists()
    assert Definition.objects.filter(name__startswith=SAMPLE_FIXTURE_PREFIX).count() >= 1
