"""Sign out (core.auth_views.logout_view): the page's Settings > Account form POSTs to /auth/logout
with the CSRF token; the session ends and the page goes to "/", which loads signed out. Sign out
everywhere (logout_everywhere_view) is the form beside it, POSTing to /auth/logout-everywhere: every
session of the account ends, and its assistant apps' grants, and nobody else's."""

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


def signed_in(user: User | None = None) -> tuple[Client, str]:
    user = user or User.objects.create(discord_user_id=next(_ids))
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


def copy_of(client: Client) -> Client:
    """Another device holding the same session cookie."""
    other = Client()
    other.cookies["sessionid"] = client.cookies["sessionid"].value
    return other


def is_signed_in(client: Client) -> bool:
    return client.get("/api/me", **addr()).json()["signed_in"]


@db
def test_a_copy_of_the_cookie_stops_working_once_this_device_signs_out() -> None:
    client, token = signed_in()
    elsewhere = copy_of(client)
    assert is_signed_in(elsewhere)
    client.post("/auth/logout", {"csrfmiddlewaretoken": token}, **addr())
    assert not is_signed_in(elsewhere)


def grant_for(user: User):
    from core.models import ConnectorClient, ConnectorGrant

    app = ConnectorClient.objects.create(client_id=f"app-{user.pk}", name="An app")
    return ConnectorGrant.objects.create(
        user=user, client=app, redirect_uri="https://example.org/cb", code_challenge="x"
    )


@db
def test_sign_out_everywhere_ends_every_session_of_the_account_and_its_apps() -> None:
    from django.contrib.sessions.models import Session as DjangoSession

    phone, token = signed_in()
    user = User.objects.get(sessions__session_key=phone.session.session_key)
    laptop, _ = signed_in(user)
    copied = copy_of(phone)
    keys = [phone.session.session_key, laptop.session.session_key]
    grant_for(user)
    r = phone.post("/auth/logout-everywhere", {"csrfmiddlewaretoken": token}, **addr())
    assert r.status_code == 302 and r["Location"] == "/"
    # Django's own rows go too, the copied cookie's (the phone's key) among them.
    assert DjangoSession.objects.filter(session_key__in=keys).count() == 0
    assert not any(is_signed_in(c) for c in (phone, laptop, copied))
    assert not Session.objects.filter(user=user).exists()
    assert not user.connector_grants.exists()


@db
def test_sign_out_everywhere_leaves_another_accounts_sessions_and_apps() -> None:
    mine, token = signed_in()
    theirs, _ = signed_in()
    them = User.objects.get(sessions__session_key=theirs.session.session_key)
    grant_for(them)
    mine.post("/auth/logout-everywhere", {"csrfmiddlewaretoken": token}, **addr())
    assert is_signed_in(theirs)
    assert them.connector_grants.count() == 1


@db
def test_sign_out_everywhere_signed_out_goes_home_and_changes_nothing() -> None:
    other, _ = signed_in()
    them = User.objects.get(sessions__session_key=other.session.session_key)
    epoch = them.session_epoch
    from django.middleware.csrf import _get_new_csrf_string

    # A valid token, as a signed-out page's cookie would carry it.
    visitor = Client(enforce_csrf_checks=True)
    token = _get_new_csrf_string()
    visitor.cookies["csrftoken"] = token
    r = visitor.post("/auth/logout-everywhere", {"csrfmiddlewaretoken": token}, **addr())
    assert r.status_code == 302 and r["Location"] == "/"
    assert is_signed_in(other)
    them.refresh_from_db()
    assert them.session_epoch == epoch
    assert Session.objects.filter(user=them).count() == 1


@db
def test_sign_out_everywhere_needs_a_post_with_the_token() -> None:
    client, _token = signed_in()
    other, _ = signed_in(User.objects.get(sessions__session_key=client.session.session_key))
    assert client.get("/auth/logout-everywhere", **addr()).status_code == 405
    assert client.post("/auth/logout-everywhere", {}, **addr()).status_code == 403
    assert is_signed_in(client) and is_signed_in(other)
