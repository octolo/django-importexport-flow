"""Tests for ImportRequest create/relaunch (formerly ``test_report_import_ask.py``)."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from django_importexport_flow.engine.core.import_ import (
    create_import_request,
    default_importable_column_paths,
    relaunch_import_request,
)
from django_importexport_flow.models import Definition, ImportRequest
from django_importexport_flow.utils.process import process_import
from tests.sample.models import Book
from tests.support import attach_import_spreadsheet


def _book_columns_exclude_all_but(*keep: str) -> list[str]:
    full = default_importable_column_paths(Book)
    return [p for p in full if p not in keep]


@pytest.mark.django_db
def test_create_import_request_and_relaunch():
    User = get_user_model()
    user = User.objects.create_user("u1", "u1@example.com", "x")
    ct = ContentType.objects.get_for_model(Book)
    ri = Definition.objects.create(
        direction="import",
        name="RI",
        target=ct,
        filter_config={},
        columns_exclude=_book_columns_exclude_all_but("title", "pages"),
    )
    f = SimpleUploadedFile("t.csv", b"Book title,Nb. of pages\nx,1\n", content_type="text/csv")
    ask = create_import_request(ri, f, {"fr_get_tenant": "1"}, user)
    assert ask.status == ImportRequest.Status.PENDING
    assert ask.data_file
    assert ask.filter_payload["fr_get_tenant"] == "1"

    ask2 = relaunch_import_request(ask, user)
    assert ask2.pk != ask.pk
    assert ask2.relaunched_from_id == ask.pk
    assert ask2.status == ImportRequest.Status.PENDING


@pytest.mark.django_db
def test_import_request_related_object_and_active_imports_for_object():
    User = get_user_model()
    user = User.objects.create_user("u2", "u2@example.com", "x")
    book = Book.objects.create(title="Scope", pages=1)
    ct = ContentType.objects.get_for_model(Book)
    ri = Definition.objects.create(
        direction="import",
        name="RI scoped",
        target=ct,
        filter_config={},
        columns_exclude=_book_columns_exclude_all_but("title", "pages"),
    )
    f = SimpleUploadedFile("s.csv", b"Book title,Nb. of pages\ny,2\n", content_type="text/csv")
    ask = create_import_request(
        ri,
        f,
        {},
        user,
        related_object=book,
    )
    ask.refresh_from_db()
    links = list(ask.related_object_links.all())
    assert len(links) == 1
    assert links[0].content_type_id == ContentType.objects.get_for_model(Book).id
    assert links[0].object_id == str(book.pk)
    assert str(book.pk) in (links[0].object_str or "")
    active = ImportRequest.active_imports_for_object(book)
    assert active.filter(pk=ask.pk).exists()

    ask2 = relaunch_import_request(ask, user)
    links2 = list(ask2.related_object_links.all())
    assert len(links2) == 1
    assert links2[0].object_id == links[0].object_id
    assert links2[0].content_type_id == links[0].content_type_id


@pytest.mark.django_db
@override_settings(DJANGO_IMPORTEXPORT_FLOW={"PERSIST_IMPORT_REQUEST_FILES": False})
def test_sync_import_can_keep_the_file_in_memory():
    User = get_user_model()
    user = User.objects.create_user("u3", "u3@example.com", "x")
    ct = ContentType.objects.get_for_model(Book)
    definition = Definition.objects.create(
        direction="import",
        name="Memory import",
        target=ct,
        columns_exclude=_book_columns_exclude_all_but("title", "pages"),
    )
    attach_import_spreadsheet(definition)
    upload = SimpleUploadedFile(
        "books.csv",
        b"Book title,Nb. of pages\nMemory book,4\n",
        content_type="text/csv",
    )
    result = process_import(file=upload, import_definition=definition, user=user)
    assert result["success"] is True
    ask = result["import_request"]
    ask.refresh_from_db()
    assert not ask.data_file
    assert Book.objects.get(title="Memory book").pages == 4

    later = SimpleUploadedFile("later.csv", b"Book title,Nb. of pages\nLater,1\n")
    with pytest.raises(ValueError, match="PERSIST_IMPORT_REQUEST_FILES"):
        create_import_request(definition, later, {}, user)
