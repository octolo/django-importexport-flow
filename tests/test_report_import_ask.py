import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile

from django_importexport_flow.utils.import_tabular import (
    create_import_request,
    default_importable_column_paths,
    relaunch_import_request,
)
from django_importexport_flow.models import ImportDefinition, ImportRequest
from tests.sample.models import Book


def _book_columns_exclude_all_but(*keep: str) -> list[str]:
    full = default_importable_column_paths(Book)
    return [p for p in full if p not in keep]


@pytest.mark.django_db
def test_create_import_request_and_relaunch():
    User = get_user_model()
    user = User.objects.create_user("u1", "u1@example.com", "x")
    ct = ContentType.objects.get_for_model(Book)
    ri = ImportDefinition.objects.create(
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
