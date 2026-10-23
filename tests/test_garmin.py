"""Garmin Connect (core.garmin, core.garmin_views; the owner, 2026-10-23, "Keep it, encrypted"):
a rider connects once in Settings, the tokens are kept encrypted and bound to the account, and
Disconnect, Garmin's deregistration notice and deleting the account each end it. No test calls
Garmin: `garmin.Transport` is replaced by `FakeGarmin`."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from django.test import Client, override_settings
from django.utils import timezone
from test_account_deletion import delete, page_csrf
from test_accounts import addr, make_user, send, signed_in

from core import account_deletion, garmin, garmin_views
from core.models import GarminLink, User

db = pytest.mark.django_db(transaction=True)
KEYS = {
    "GARMIN_CLIENT_ID": "test-client",
    "GARMIN_CLIENT_SECRET": "test-secret",
    "GARMIN_REDIRECT_URI": "https://example.org/auth/garmin/callback",
}


class FakeGarmin(garmin.Transport):
    """Garmin's token, user id and registration endpoints, recording each call."""

    def __init__(self, token_status: int = 200, user: str = "garmin-user-1") -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.token_status = token_status
        self.token_error = "invalid_grant"
        self.user = user
        self.issued = 0

    def post_form(self, url, form):
        self.calls.append(("POST", url, dict(form)))
        if self.token_status != 200:
            return self.token_status, {"error": self.token_error}
        self.issued += 1
        return 200, {
            "access_token": f"access-{self.issued}",
            "token_type": "bearer",
            "expires_in": 86400,
            "refresh_token": f"refresh-{self.issued}",
            "refresh_token_expires_in": 7775998,
        }

    def get_json(self, url, access):
        self.calls.append(("GET", url, {"access": access}))
        return 200, {"userId": self.user}

    def delete(self, url, access):
        self.calls.append(("DELETE", url, {"access": access}))
        return 204, {}


@pytest.fixture
def fake(monkeypatch) -> FakeGarmin:
    instance = FakeGarmin()
    monkeypatch.setattr(garmin, "Transport", lambda: instance)
    return instance


def connect(client: Client) -> FakeGarmin | None:
    """Run the whole sign-in: start, then Garmin's redirect back with a code."""
    start = client.get("/auth/garmin/start", **addr())
    assert start.status_code == 302
    query = parse_qs(urlparse(start["Location"]).query)
    return client.get(
        "/auth/garmin/callback", {"code": "the-code", "state": query["state"][0]}, **addr()
    )


class TestProtocol:
    def test_pkce_challenge_is_s256_base64url_without_padding(self) -> None:
        verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        assert garmin.challenge_of(verifier) == expected.rstrip(b"=").decode()
        assert garmin.challenge_of(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"

    def test_begin_asks_for_a_code_with_pkce_and_state(self) -> None:
        now = timezone.now()
        url, pending = garmin.begin("cid", "https://example.org/cb", now)
        parsed = urlparse(url)
        assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == garmin.AUTHORIZE_URL
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        assert query == {
            "response_type": "code",
            "client_id": "cid",
            "redirect_uri": "https://example.org/cb",
            "state": pending.state,
            "code_challenge": garmin.challenge_of(pending.verifier),
            "code_challenge_method": "S256",
        }
        assert 43 <= len(pending.verifier) <= 128
        assert set(pending.verifier) <= set(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
        )

    def test_state_must_match_and_be_live(self) -> None:
        now = timezone.now()
        _, pending = garmin.begin("cid", "https://example.org/cb", now)
        assert garmin.state_matches(pending, pending.state, now)
        assert not garmin.state_matches(pending, pending.state + "x", now)
        assert not garmin.state_matches(pending, "ü", now)
        assert not garmin.state_matches(None, pending.state, now)
        assert not garmin.state_matches(pending, pending.state, now + timedelta(minutes=11))

    def test_a_malformed_token_answer_is_refused(self) -> None:
        now = timezone.now()
        for body in ({}, {"access_token": "a", "refresh_token": "r", "expires_in": "x"},
                     {"access_token": "", "refresh_token": "r", "expires_in": 60}):  # fmt: skip
            with pytest.raises(garmin.GarminError):
                garmin.tokens_from(body, now)

    def test_refresh_comes_ten_minutes_early(self) -> None:
        now = timezone.now()
        assert garmin.needs_refresh(now + timedelta(seconds=600), now)
        assert not garmin.needs_refresh(now + timedelta(seconds=601), now)

    def test_tokens_are_sealed_and_bound_to_the_account(self) -> None:
        sealed = garmin.seal("secret-token", 7)
        assert "secret-token" not in sealed and sealed.startswith("v1.")
        assert garmin.unseal(sealed, 7) == "secret-token"
        assert garmin.seal("secret-token", 7) != sealed  # a fresh nonce each time
        with pytest.raises(garmin.NotConnected):
            garmin.unseal(sealed, 8)
        with pytest.raises(garmin.NotConnected):
            garmin.unseal("v0." + sealed[3:], 7)

    def test_the_token_key_is_its_own_subkey(self) -> None:
        from django.conf import settings

        assert len(settings.GARMIN_TOKEN_KEY) == 32
        assert settings.GARMIN_TOKEN_KEY != settings.TOMBSTONE_KEY

    def test_deregistration_notice_ids(self) -> None:
        body = {"deregistrations": [{"userId": "a"}, {"userId": ""}, {"userId": 5}, "x", {}]}
        assert garmin.deregistered_user_ids(body) == ["a"]
        assert garmin.deregistered_user_ids([]) == []
        assert garmin.deregistered_user_ids({"deregistrations": "a"}) == []


@pytest.fixture
def keys(settings) -> None:
    for name, value in KEYS.items():
        setattr(settings, name, value)


@db
@pytest.mark.usefixtures("keys")
class TestConnecting:
    def test_off_without_keys(self, client) -> None:
        mine, _user, _ = signed_in()
        with override_settings(GARMIN_CLIENT_ID="", GARMIN_CLIENT_SECRET=""):
            assert mine.get("/auth/garmin/start", **addr()).status_code == 503
            assert mine.get("/auth/garmin/callback", **addr()).status_code == 503
            assert mine.get("/api/me/garmin", **addr()).json()["available"] is False

    def test_settings_offers_it_only_once_courses_are_wired(self, monkeypatch) -> None:
        mine, _user, _ = signed_in()
        assert garmin.COURSES_WIRED is False
        assert mine.get("/api/me/garmin", **addr()).json()["available"] is False
        monkeypatch.setattr(garmin, "COURSES_WIRED", True)
        assert mine.get("/api/me/garmin", **addr()).json()["available"] is True

    def test_signed_out_is_sent_back_to_sign_in(self, client) -> None:
        r = client.get("/auth/garmin/start", **addr())
        assert r.status_code == 302 and r["Location"] == "/?garmin=signin"

    def test_connecting_keeps_the_tokens_encrypted(self, fake) -> None:
        mine, user, _ = signed_in()
        r = connect(mine)
        assert r.status_code == 302 and r["Location"] == "/?garmin=connected"
        link = GarminLink.objects.get(user=user)
        assert link.garmin_user_id == "garmin-user-1"
        assert "access-1" not in link.access_token and "refresh-1" not in link.refresh_token
        assert garmin.unseal(link.access_token, user.pk) == "access-1"
        assert garmin.unseal(link.refresh_token, user.pk) == "refresh-1"
        # The exchange sent the PKCE verifier whose challenge went to Garmin, and the secret.
        method, url, form = fake.calls[0]
        assert (method, url) == ("POST", garmin.TOKEN_URL)
        assert form["grant_type"] == "authorization_code" and form["code"] == "the-code"
        assert form["client_secret"] == "test-secret"
        assert form["redirect_uri"] == KEYS["GARMIN_REDIRECT_URI"]
        assert fake.calls[1] == ("GET", garmin.USER_ID_URL, {"access": "access-1"})
        assert mine.get("/api/me/garmin", **addr()).json()["connected"] is True

    def test_the_verifier_is_the_one_whose_challenge_was_sent(self, fake) -> None:
        mine, _user, _ = signed_in()
        start = mine.get("/auth/garmin/start", **addr())
        query = parse_qs(urlparse(start["Location"]).query)
        mine.get("/auth/garmin/callback", {"code": "c", "state": query["state"][0]}, **addr())
        verifier = fake.calls[0][2]["code_verifier"]
        assert garmin.challenge_of(verifier) == query["code_challenge"][0]

    def test_a_wrong_or_replayed_state_connects_nothing(self, fake) -> None:
        mine, user, _ = signed_in()
        start = mine.get("/auth/garmin/start", **addr())
        state = parse_qs(urlparse(start["Location"]).query)["state"][0]
        r = mine.get("/auth/garmin/callback", {"code": "c", "state": "other"}, **addr())
        assert r["Location"] == "/?garmin=failed"
        # The state is spent by the first callback, right or wrong.
        r = mine.get("/auth/garmin/callback", {"code": "c", "state": state}, **addr())
        assert r["Location"] == "/?garmin=failed"
        assert not GarminLink.objects.filter(user=user).exists() and fake.calls == []

    def test_a_state_from_another_session_connects_nothing(self, fake) -> None:
        # Someone else's sign-in, finished in this rider's browser, must not link their Garmin here.
        theirs, _, _ = signed_in()
        start = theirs.get("/auth/garmin/start", **addr())
        state = parse_qs(urlparse(start["Location"]).query)["state"][0]
        mine, user, _ = signed_in()
        mine.get("/auth/garmin/start", **addr())
        r = mine.get("/auth/garmin/callback", {"code": "the-code", "state": state}, **addr())
        assert r["Location"] == "/?garmin=failed"
        assert fake.calls == []
        assert not GarminLink.objects.filter(user=user).exists()

    def test_saying_no_at_garmin(self, fake) -> None:
        mine, user, _ = signed_in()
        start = mine.get("/auth/garmin/start", **addr())
        state = parse_qs(urlparse(start["Location"]).query)["state"][0]
        r = mine.get("/auth/garmin/callback", {"state": state, "error": "denied"}, **addr())
        assert r["Location"] == "/?garmin=declined"
        assert not GarminLink.objects.filter(user=user).exists()

    def test_garmin_refusing_the_code(self, fake) -> None:
        fake.token_status = 400
        mine, user, _ = signed_in()
        assert connect(mine)["Location"] == "/?garmin=failed"
        assert not GarminLink.objects.filter(user=user).exists()

    def test_connecting_again_replaces_the_link(self, fake) -> None:
        mine, user, _ = signed_in()
        connect(mine)
        connect(mine)
        link = GarminLink.objects.get(user=user)
        assert garmin.unseal(link.access_token, user.pk) == "access-2"


@db
@pytest.mark.usefixtures("keys")
class TestUsingAndEnding:
    def _linked(self, fake) -> tuple[Client, User, str]:
        mine, user, csrf = signed_in()
        connect(mine)
        fake.calls.clear()
        return mine, user, csrf

    def test_a_fresh_token_is_used_as_is(self, fake) -> None:
        _mine, user, _ = self._linked(fake)
        assert garmin_views.access_for(user) == "access-1"
        assert fake.calls == []
        assert GarminLink.objects.get(user=user).last_used_at is not None

    def test_a_token_near_its_end_is_refreshed_and_both_replaced(self, fake) -> None:
        _mine, user, _ = self._linked(fake)
        GarminLink.objects.filter(user=user).update(
            access_expires_at=timezone.now() + timedelta(minutes=5)
        )
        assert garmin_views.access_for(user) == "access-2"
        assert fake.calls[0][2]["grant_type"] == "refresh_token"
        assert fake.calls[0][2]["refresh_token"] == "refresh-1"
        link = GarminLink.objects.get(user=user)
        assert garmin.unseal(link.refresh_token, user.pk) == "refresh-2"

    def test_a_refused_refresh_ends_the_connection(self, fake) -> None:
        _mine, user, _ = self._linked(fake)
        GarminLink.objects.filter(user=user).update(access_expires_at=timezone.now())
        fake.token_status = 401
        with pytest.raises(garmin.NotConnected):
            garmin_views.access_for(user)
        assert not GarminLink.objects.filter(user=user).exists()

    def test_our_own_refused_secret_keeps_every_connection(self, fake) -> None:
        # A wrong or mid-rotation GARMIN_CLIENT_SECRET is ours to fix, not the rider's to redo.
        _mine, user, _ = self._linked(fake)
        GarminLink.objects.filter(user=user).update(access_expires_at=timezone.now())
        fake.token_status, fake.token_error = 401, "invalid_client"
        with pytest.raises(garmin.GarminError) as raised:
            garmin_views.access_for(user)
        assert not isinstance(raised.value, garmin.NotConnected)
        link = GarminLink.objects.get(user=user)
        assert garmin.unseal(link.refresh_token, user.pk) == "refresh-1"

    def test_a_token_that_does_not_decrypt_ends_the_connection(self, fake) -> None:
        _mine, user, _ = self._linked(fake)
        other = make_user()
        GarminLink.objects.filter(user=user).update(access_token=garmin.seal("access-1", other.pk))
        with pytest.raises(garmin.NotConnected):
            garmin_views.access_for(user)
        assert not GarminLink.objects.filter(user=user).exists()

    def test_disconnect_tells_garmin_and_deletes(self, fake) -> None:
        mine, user, csrf = self._linked(fake)
        r = send(mine, "post", "/api/me/garmin/delete", {}, csrf)
        assert r.status_code == 200 and r.json()["connected"] is False
        assert fake.calls == [("DELETE", garmin.REGISTRATION_URL, {"access": "access-1"})]
        assert not GarminLink.objects.filter(user=user).exists()

    def test_disconnect_needs_the_csrf_token(self, fake) -> None:
        mine, user, _ = self._linked(fake)
        r = send(mine, "post", "/api/me/garmin/delete", {}, None)
        assert r.status_code == 403
        assert GarminLink.objects.filter(user=user).exists()

    def test_signed_out_reads_nothing(self, client) -> None:
        assert client.get("/api/me/garmin", **addr()).status_code == 401

    def test_garmin_s_deregistration_notice(self, fake) -> None:
        _mine, user, _ = self._linked(fake)
        kept, kept_user, _ = signed_in()
        fake.user = "garmin-user-2"
        connect(kept)
        r = Client().post(
            "/garmin/deregistrations",
            data=json.dumps({"deregistrations": [{"userId": "garmin-user-1"}]}),
            content_type="application/json",
            **addr(),
        )
        assert r.status_code == 200 and r.json() == {"removed": 1}
        assert not GarminLink.objects.filter(user=user).exists()
        assert GarminLink.objects.filter(user=kept_user).exists()

    def test_a_malformed_notice_removes_nothing(self, fake) -> None:
        _mine, user, _ = self._linked(fake)
        r = Client().post(
            "/garmin/deregistrations", data="{", content_type="application/json", **addr()
        )
        assert r.status_code == 400
        assert GarminLink.objects.filter(user=user).exists()

    def test_the_notice_is_not_there_without_keys(self, fake, settings) -> None:
        _mine, user, _ = self._linked(fake)
        settings.GARMIN_CLIENT_SECRET = ""
        r = Client().post(
            "/garmin/deregistrations",
            data=json.dumps({"deregistrations": [{"userId": "garmin-user-1"}]}),
            content_type="application/json",
            **addr(),
        )
        assert r.status_code == 404
        assert GarminLink.objects.filter(user=user).exists()

    def test_a_refused_account_deletion_keeps_the_connection(self, fake) -> None:
        mine, user, _ = self._linked(fake)
        r = delete(mine, page_csrf(mine), confirm=False)
        assert r.status_code == 400
        assert GarminLink.objects.filter(user=user).exists()
        assert fake.calls == []

    def test_the_deletion_page_names_garmin_only_where_it_applies(self, fake) -> None:
        mine, _user, _ = self._linked(fake)
        assert "Garmin" in mine.get(account_deletion.PATH, **addr()).content.decode()
        other, _, _ = signed_in()
        assert "Garmin" not in other.get(account_deletion.PATH, **addr()).content.decode()

    def test_deleting_the_account_tells_garmin(self, fake) -> None:
        mine, user, _ = self._linked(fake)
        r = delete(mine, page_csrf(mine))
        assert r.status_code == 200
        assert not User.objects.filter(pk=user.pk).exists()
        assert not GarminLink.objects.filter(user_id=user.pk).exists()
        assert ("DELETE", garmin.REGISTRATION_URL, {"access": "access-1"}) in fake.calls


def test_the_table_is_left_out_of_backups() -> None:
    from config import procrastinate

    assert "garmin_link" in procrastinate.BACKUP_EXCLUDED_TABLES
