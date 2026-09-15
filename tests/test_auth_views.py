"""The Discord login flow as the browser walks it.

Before these views existed the flow stopped at a module of pure protocol logic:
nothing routed to a callback, nothing created a user, and nothing wrote the
Session row the epoch middleware requires - so even a reachable login would have
been signed straight back out on the next request.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from core.auth_views import STATE_SESSION_KEY

pytestmark = pytest.mark.django_db


def start_login(client):
    response = client.get(reverse("login"))
    return response, client.session[STATE_SESSION_KEY]["state"]


def callback(client, monkeypatch, state, *, user_id=1234, scope="identify", code="abc"):
    monkeypatch.setattr(
        "core.auth_views.exchange_code", lambda _code: (user_id, scope), raising=False
    )
    return client.get(reverse("login-callback"), {"state": state, "code": code})


def test_the_authorize_url_asks_for_identify_and_nothing_else(client) -> None:
    """`guilds` would list every server the person is in, which is more than this
    needs and more than they should disclose to plan a bike ride."""
    response, _state = start_login(client)
    assert response.status_code == 302
    assert response["Location"].startswith("https://discord.com/oauth2/authorize?")
    assert "scope=identify" in response["Location"]
    assert "guilds" not in response["Location"]


def test_a_mismatched_state_is_refused(client, monkeypatch) -> None:
    """A replayed callback must not mint a second session from one
    authorization."""
    start_login(client)
    response = callback(client, monkeypatch, state="not-the-stored-one")
    assert response.status_code == 400


def test_a_callback_with_no_login_in_progress_is_refused(client, monkeypatch) -> None:
    response = callback(client, monkeypatch, state="anything")
    assert response.status_code == 400


def test_an_expired_login_request_is_refused(client, monkeypatch) -> None:
    from core.discord_oauth import STATE_LIFETIME

    _response, state = start_login(client)
    stale = (timezone.now() - STATE_LIFETIME - timedelta(seconds=1)).isoformat()
    session = client.session
    session[STATE_SESSION_KEY] = {**session[STATE_SESSION_KEY], "issued_at": stale}
    session.save()

    assert callback(client, monkeypatch, state=state).status_code == 400


def test_a_grant_carrying_more_than_identify_is_refused(client, monkeypatch) -> None:
    """Either the authorize URL was tampered with or the application's
    configuration drifted; the extra scope is not used and its presence is worth
    refusing rather than ignoring."""
    from core.models import User

    _response, state = start_login(client)
    response = callback(client, monkeypatch, state=state, scope="identify guilds")
    assert response.status_code == 403
    assert not User.objects.exists()


def test_a_successful_login_creates_the_user_and_the_session_row(client, monkeypatch) -> None:
    from core.models import Session, User

    _response, state = start_login(client)
    response = callback(client, monkeypatch, state=state, user_id=777)
    assert response.status_code == 302

    user = User.objects.get(discord_user_id=777)
    assert user.last_login is not None
    row = Session.objects.get(user=user)
    assert row.issued_epoch == user.session_epoch
    assert row.created_at is not None and row.last_seen_at is not None
    assert row.session_key == client.session.session_key


def test_a_banned_account_cannot_sign_in(client, monkeypatch) -> None:
    from core.models import Session, User

    User.objects.create(discord_user_id=778, is_banned=True)
    _response, state = start_login(client)
    assert callback(client, monkeypatch, state=state, user_id=778).status_code == 403
    assert not Session.objects.exists()


def test_a_deleted_account_cannot_sign_in(client, monkeypatch) -> None:
    from core.models import Session, User

    User.objects.create(discord_user_id=779, is_deleted=True)
    _response, state = start_login(client)
    assert callback(client, monkeypatch, state=state, user_id=779).status_code == 403
    assert not Session.objects.exists()


def test_a_tombstoned_account_is_refused_before_a_row_is_created(client, monkeypatch) -> None:
    """Checked before get_or_create, so a banned account that deleted itself and
    came back does not get a fresh row and a fresh start."""
    from core.models import BanTombstone, User
    from core.revocation import tombstone

    BanTombstone.objects.create(tombstone=tombstone(780, settings.TOMBSTONE_KEY))
    _response, state = start_login(client)
    assert callback(client, monkeypatch, state=state, user_id=780).status_code == 403
    assert not User.objects.filter(discord_user_id=780).exists()


def test_signing_out_removes_the_session_row(client, monkeypatch) -> None:
    from core.models import Session

    _response, state = start_login(client)
    callback(client, monkeypatch, state=state, user_id=781)
    assert Session.objects.count() == 1

    assert client.post(reverse("logout")).status_code == 302
    assert not Session.objects.exists()


def test_no_discord_token_is_persisted_anywhere(client, monkeypatch) -> None:
    """The stated consequence is that this deployment holds no per-user
    third-party credential at all: nothing to encrypt, refresh, leak, or revoke
    on deletion. Asserted rather than described - the OAuth module had six tests
    and none of them covered this.
    """
    from django.apps import apps

    from core.models import Session, User

    # No column anywhere could hold one.
    suspicious = {"access_token", "refresh_token", "token", "discord_token", "oauth_token"}
    for model in apps.get_app_config("core").get_models():
        names = {field.name for field in model._meta.fields}
        assert not (names & suspicious), f"{model.__name__} has a token column"

    # And a completed login leaves exactly two rows in the application's own
    # tables: the account and its session. Anything the exchange returned beyond
    # the id would have nowhere to have gone.
    _response, state = start_login(client)
    callback(client, monkeypatch, state=state, user_id=782)

    populated = {
        model.__name__: model.objects.count()
        for model in apps.get_app_config("core").get_models()
        if model._meta.managed and model.objects.count()
    }
    assert populated == {"User": 1, "Session": 1}
    assert not User.objects.get(discord_user_id=782).has_usable_password()
    assert Session.objects.get().issued_epoch == User.objects.get(discord_user_id=782).session_epoch
