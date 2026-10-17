"""Sign out (core.auth_views.logout_view): the page's Settings > Account form POSTs to /auth/logout
with the CSRF token; the session ends and the page goes to "/", which loads signed out."""

from __future__ import annotations

from itertools import count

import pytest
from django.test import Client
from django.utils import timezone

from core.models import Session, User

db = pytest.mark.django_db(transaction=True)

_ids = count(98100)
_clients = count(20)


def addr() -> dict:
    return {"HTTP_X_FORWARDED_FOR": f"198.51.100.{next(_clients) % 250}"}


def signed_in() -> tuple[Client, str]:
    user = User.objects.create(discord_user_id=next(_ids))
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    now = timezone.now()
    Session.objects.create(
        session_key=client.session.session_key,
        user=user,
        issued_epoch=user.session_epoch,
        created_at=now,
        last_seen_at=now,
    )
    assert client.get("/api/me", **addr()).json()["signed_in"] is True
    # The page reads the account's My Go once signed in (App): that sets the cookie the form sends.
    assert client.get("/api/me/go", **addr()).status_code == 200
    return client, client.cookies["csrftoken"].value


@db
def test_sign_out_ends_the_session_and_goes_to_the_signed_out_page() -> None:
    client, token = signed_in()
    key = client.session.session_key
    r = client.post("/auth/logout", {"csrfmiddlewaretoken": token}, **addr())
    assert r.status_code == 302 and r["Location"] == "/"
    assert not Session.objects.filter(session_key=key).exists()
    assert client.get("/api/me", **addr()).json()["signed_in"] is False


@db
def test_sign_out_without_the_token_is_refused_and_the_session_stays() -> None:
    client, _token = signed_in()
    key = client.session.session_key
    assert client.post("/auth/logout", {}, **addr()).status_code == 403
    assert Session.objects.filter(session_key=key).exists()
