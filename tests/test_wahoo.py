"""Wahoo (core.wahoo, core.wahoo_views, core.wahoo_routes; the owner, 2026-10-23): a rider
connects once in Settings, the tokens are kept encrypted and bound to the account, Send to Wahoo
adds the route's FIT course to their Wahoo app (a saved route updates in place), and Disconnect and
deleting the account each end it, deleting the account removing the routes sent too. No test calls
Wahoo: `wahoo.Transport` is replaced by `FakeWahoo`."""

from __future__ import annotations

import base64
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from django.test import Client, override_settings
from django.utils import timezone
from test_account_deletion import delete, page_csrf
from test_accounts import addr, make_user, send, signed_in

from core import account_deletion, wahoo, wahoo_routes, wahoo_views
from core.models import User, WahooLink

db = pytest.mark.django_db(transaction=True)
KEYS = {
    "WAHOO_CLIENT_ID": "test-client",
    "WAHOO_CLIENT_SECRET": "test-secret",
    "WAHOO_REDIRECT_URI": "https://example.org/auth/wahoo/callback",
}
# About 1.1 km due north along a meridian, rising 20 m then falling 5 m.
LINE = [[-77.0, 38.9, 10.0], [-77.0, 38.905, 30.0], [-77.0, 38.91, 25.0]]
# A 14-byte FIT header and two bytes of body: enough for the checks the server makes.
FIT = bytes([14, 0x20, 0, 0, 2, 0, 0, 0]) + b".FIT" + b"\x00\x00" + b"\x01\x02"
FIT_B64 = base64.b64encode(FIT).decode()


class FakeWahoo(wahoo.Transport):
    """Wahoo's token, user, permissions and routes endpoints, recording each call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.token_status = 200
        self.token_error = "invalid_grant"
        self.user = 60462
        self.issued = 0
        self.answers: list[int] = []
        self.next_id = 100

    def send_form(self, method, url, form, access=None):
        self.calls.append((method, url, {**dict(form), "access": access}))
        if url == wahoo.TOKEN_URL:
            if self.token_status != 200:
                return self.token_status, {"error": self.token_error}
            self.issued += 1
            return 200, {
                "access_token": f"access-{self.issued}",
                "token_type": "Bearer",
                "expires_in": 7200,
                "refresh_token": f"refresh-{self.issued}",
                "created_at": 1,
            }
        status = self.answers.pop(0) if self.answers else (201 if method == "POST" else 200)
        if method == "POST" and status in (200, 201):
            self.next_id += 1
            return status, {"id": self.next_id, "user_id": self.user}
        return status, {}

    def get_json(self, url, access):
        self.calls.append(("GET", url, {"access": access}))
        return 200, {"id": self.user, "first": "Ignored"}

    def delete(self, url, access):
        self.calls.append(("DELETE", url, {"access": access}))
        return 204, {}


@pytest.fixture
def fake(monkeypatch) -> FakeWahoo:
    instance = FakeWahoo()
    monkeypatch.setattr(wahoo, "Transport", lambda: instance)
    return instance


@pytest.fixture
def keys(settings) -> None:
    for name, value in KEYS.items():
        setattr(settings, name, value)


def connect(client: Client):
    """Run the whole sign-in: start, then Wahoo's redirect back with a code."""
    start = client.get("/auth/wahoo/start", **addr())
    assert start.status_code == 302
    query = parse_qs(urlparse(start["Location"]).query)
    return client.get(
        "/auth/wahoo/callback", {"code": "the-code", "state": query["state"][0]}, **addr()
    )


class TestProtocol:
    def test_begin_asks_for_a_code_for_routes_only(self) -> None:
        url, pending = wahoo.begin("cid", "https://example.org/cb", timezone.now())
        parsed = urlparse(url)
        assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == wahoo.AUTHORIZE_URL
        # Spaces as %20, as Wahoo's documentation shows them.
        assert "scope=user_read%20routes_read%20routes_write" in parsed.query
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        assert query == {
            "client_id": "cid",
            "redirect_uri": "https://example.org/cb",
            "scope": "user_read routes_read routes_write",
            "response_type": "code",
            "state": pending.state,
        }

    def test_state_must_match_and_be_live(self) -> None:
        now = timezone.now()
        _, pending = wahoo.begin("cid", "https://example.org/cb", now)
        assert wahoo.state_matches(pending, pending.state, now)
        assert not wahoo.state_matches(pending, pending.state + "x", now)
        assert not wahoo.state_matches(None, pending.state, now)
        assert not wahoo.state_matches(pending, pending.state, now + timedelta(minutes=11))

    def test_a_malformed_token_answer_is_refused(self) -> None:
        now = timezone.now()
        for body in ({}, {"access_token": "a", "refresh_token": "r", "expires_in": "x"},
                     {"access_token": "", "refresh_token": "r", "expires_in": 60}):  # fmt: skip
            with pytest.raises(wahoo.WahooError):
                wahoo.tokens_from(body, now)

    def test_tokens_are_sealed_bound_to_the_account_under_their_own_key(self) -> None:
        from django.conf import settings

        sealed = wahoo.seal("secret-token", 7)
        assert "secret-token" not in sealed and wahoo.unseal(sealed, 7) == "secret-token"
        with pytest.raises(wahoo.NotConnected):
            wahoo.unseal(sealed, 8)
        assert len(settings.WAHOO_TOKEN_KEY) == 32
        assert settings.WAHOO_TOKEN_KEY not in (settings.GARMIN_TOKEN_KEY, settings.TOMBSTONE_KEY)


@db
@pytest.mark.usefixtures("keys")
class TestConnecting:
    def test_off_without_keys(self) -> None:
        mine, _user, _ = signed_in()
        with override_settings(WAHOO_CLIENT_ID="", WAHOO_CLIENT_SECRET=""):
            assert mine.get("/auth/wahoo/start", **addr()).status_code == 503
            assert mine.get("/auth/wahoo/callback", **addr()).status_code == 503
            assert mine.get("/api/me/wahoo", **addr()).json()["available"] is False
        assert mine.get("/api/me/wahoo", **addr()).json()["available"] is True

    def test_signed_out_is_sent_back_to_sign_in(self, client) -> None:
        r = client.get("/auth/wahoo/start", **addr())
        assert r.status_code == 302 and r["Location"] == "/?wahoo=signin"
        assert client.get("/api/me/wahoo", **addr()).status_code == 401

    def test_connecting_keeps_the_tokens_encrypted(self, fake) -> None:
        mine, user, _ = signed_in()
        r = connect(mine)
        assert r.status_code == 302 and r["Location"] == "/?wahoo=connected"
        link = WahooLink.objects.get(user=user)
        assert link.wahoo_user_id == "60462"
        assert "access-1" not in link.access_token and "refresh-1" not in link.refresh_token
        assert wahoo.unseal(link.access_token, user.pk) == "access-1"
        assert wahoo.unseal(link.refresh_token, user.pk) == "refresh-1"
        method, url, form = fake.calls[0]
        assert (method, url) == ("POST", wahoo.TOKEN_URL)
        assert form["grant_type"] == "authorization_code" and form["code"] == "the-code"
        assert form["client_secret"] == "test-secret"
        assert form["redirect_uri"] == KEYS["WAHOO_REDIRECT_URI"]
        assert fake.calls[1] == ("GET", wahoo.USER_URL, {"access": "access-1"})
        assert mine.get("/api/me/wahoo", **addr()).json()["connected"] is True

    def test_a_wrong_replayed_or_foreign_state_connects_nothing(self, fake) -> None:
        theirs, _, _ = signed_in()
        foreign = parse_qs(urlparse(theirs.get("/auth/wahoo/start", **addr())["Location"]).query)
        mine, user, _ = signed_in()
        start = mine.get("/auth/wahoo/start", **addr())
        state = parse_qs(urlparse(start["Location"]).query)["state"][0]
        r = mine.get("/auth/wahoo/callback", {"code": "c", "state": foreign["state"][0]}, **addr())
        assert r["Location"] == "/?wahoo=failed"
        # The state is spent by the first callback, right or wrong.
        r = mine.get("/auth/wahoo/callback", {"code": "c", "state": state}, **addr())
        assert r["Location"] == "/?wahoo=failed"
        assert not WahooLink.objects.filter(user=user).exists() and fake.calls == []

    def test_saying_no_at_wahoo(self, fake) -> None:
        mine, user, _ = signed_in()
        start = mine.get("/auth/wahoo/start", **addr())
        state = parse_qs(urlparse(start["Location"]).query)["state"][0]
        r = mine.get("/auth/wahoo/callback", {"state": state, "error": "access_denied"}, **addr())
        assert r["Location"] == "/?wahoo=declined"
        assert not WahooLink.objects.filter(user=user).exists()

    def test_wahoo_refusing_the_code(self, fake) -> None:
        fake.token_status = 400
        mine, user, _ = signed_in()
        assert connect(mine)["Location"] == "/?wahoo=failed"
        assert not WahooLink.objects.filter(user=user).exists()


@db
@pytest.mark.usefixtures("keys")
class TestUsingAndEnding:
    def _linked(self, fake) -> tuple[Client, User, str]:
        mine, user, csrf = signed_in()
        connect(mine)
        fake.calls.clear()
        return mine, user, csrf

    def test_a_token_near_its_end_is_refreshed(self, fake) -> None:
        _mine, user, _ = self._linked(fake)
        assert wahoo_views.access_for(user) == "access-1" and fake.calls == []
        WahooLink.objects.filter(user=user).update(
            access_expires_at=timezone.now() + timedelta(minutes=4)
        )
        assert wahoo_views.access_for(user) == "access-2"
        assert fake.calls[0][2]["grant_type"] == "refresh_token"
        assert fake.calls[0][2]["refresh_token"] == "refresh-1"
        link = WahooLink.objects.get(user=user)
        assert wahoo.unseal(link.refresh_token, user.pk) == "refresh-2"

    def test_a_refused_refresh_ends_the_connection(self, fake) -> None:
        _mine, user, _ = self._linked(fake)
        WahooLink.objects.filter(user=user).update(access_expires_at=timezone.now())
        fake.token_status = 401
        with pytest.raises(wahoo.NotConnected):
            wahoo_views.access_for(user)
        assert not WahooLink.objects.filter(user=user).exists()

    def test_our_own_refused_secret_keeps_every_connection(self, fake) -> None:
        _mine, user, _ = self._linked(fake)
        WahooLink.objects.filter(user=user).update(access_expires_at=timezone.now())
        fake.token_status, fake.token_error = 401, "invalid_client"
        with pytest.raises(wahoo.WahooError) as raised:
            wahoo_views.access_for(user)
        assert not isinstance(raised.value, wahoo.NotConnected)
        assert WahooLink.objects.filter(user=user).exists()

    def test_disconnect_withdraws_access_and_keeps_the_routes(self, fake) -> None:
        mine, user, csrf = self._linked(fake)
        send(mine, "post", "/api/me/wahoo/routes", {"line": LINE, "fit": FIT_B64}, csrf)
        fake.calls.clear()
        r = send(mine, "post", "/api/me/wahoo/delete", {}, csrf)
        assert r.status_code == 200 and r.json()["connected"] is False
        assert fake.calls == [("DELETE", wahoo.PERMISSIONS_URL, {"access": "access-1"})]
        assert not WahooLink.objects.filter(user=user).exists()

    def test_disconnect_needs_the_csrf_token(self, fake) -> None:
        mine, user, _ = self._linked(fake)
        assert send(mine, "post", "/api/me/wahoo/delete", {}, None).status_code == 403
        assert WahooLink.objects.filter(user=user).exists()

    def test_deleting_the_account_removes_the_routes_sent_and_withdraws(self, fake) -> None:
        mine, user, csrf = self._linked(fake)
        for _ in range(2):
            send(mine, "post", "/api/me/wahoo/routes", {"line": LINE, "fit": FIT_B64}, csrf)
        fake.calls.clear()
        assert delete(mine, page_csrf(mine)).status_code == 200
        assert not User.objects.filter(pk=user.pk).exists()
        assert not WahooLink.objects.filter(user_id=user.pk).exists()
        deletes = sorted(c[1] for c in fake.calls if c[0] == "DELETE")
        assert deletes == sorted(
            [f"{wahoo.ROUTES_URL}/101", f"{wahoo.ROUTES_URL}/102", wahoo.PERMISSIONS_URL]
        )

    def test_removing_routes_stops_when_wahoo_slows_down_or_time_runs_out(self) -> None:
        class Slow(FakeWahoo):
            def delete(self, url, access):
                self.calls.append(("DELETE", url, {"access": access}))
                return (429, {}) if len(self.calls) == 2 else (204, {})

        slow = Slow()
        assert wahoo_views.remove_routes("a", [1, 2, 3], slow) == 1 and len(slow.calls) == 2
        ticks = iter([0.0, 0.0, wahoo_views.REMOVE_DEADLINE_S, 99.0])
        fake = FakeWahoo()
        assert wahoo_views.remove_routes("a", [1, 2, 3], fake, clock=lambda: next(ticks)) == 1
        assert len(fake.calls) == 1
        many = FakeWahoo()
        wahoo_views.remove_routes("a", list(range(150)), many)
        assert len(many.calls) == wahoo_views.MAX_ROUTES_REMOVED == wahoo_routes.MAX_REMEMBERED

    def test_a_refused_account_deletion_keeps_everything(self, fake) -> None:
        mine, user, _ = self._linked(fake)
        assert delete(mine, page_csrf(mine), confirm=False).status_code == 400
        assert WahooLink.objects.filter(user=user).exists() and fake.calls == []

    def test_the_deletion_page_names_wahoo_only_where_it_applies(self, fake, settings) -> None:
        mine, _user, _ = self._linked(fake)
        other, _, _ = signed_in()
        assert "Wahoo" in other.get(account_deletion.PATH, **addr()).content.decode()
        settings.WAHOO_CLIENT_ID = ""
        assert "Wahoo" in mine.get(account_deletion.PATH, **addr()).content.decode()
        assert "Wahoo" not in other.get(account_deletion.PATH, **addr()).content.decode()


def test_the_table_is_left_out_of_backups() -> None:
    from config import procrastinate

    assert "wahoo_link" in procrastinate.BACKUP_EXCLUDED_TABLES


class TestRouteForm:
    def test_the_fit_file_and_totals(self) -> None:
        form = wahoo_routes.build("  Loop  ", LINE, FIT_B64)
        assert form["route[file]"] == "data:application/vnd.fit;base64," + FIT_B64
        assert form["route[name]"] == "Loop"
        assert form["route[workout_type_family_id]"] == 0
        assert (form["route[start_lat]"], form["route[start_lng]"]) == (38.9, -77.0)
        assert 1100 < form["route[distance]"] < 1125
        assert (form["route[ascent]"], form["route[descent]"]) == (20.0, 5.0)

    @pytest.mark.parametrize(
        "fit",
        [
            None,
            "",
            "not base64!",
            base64.b64encode(b"x" * 20).decode(),
            base64.b64encode(FIT.replace(b".FIT", b".GPX")).decode(),
        ],  # fmt: skip
    )
    def test_anything_but_a_fit_file_is_refused(self, fit) -> None:
        with pytest.raises(wahoo_routes.BadLine):
            wahoo_routes.build("Loop", LINE, fit)

    def test_a_file_over_the_cap_is_refused(self, monkeypatch) -> None:
        monkeypatch.setattr(wahoo_routes, "MAX_FIT_BYTES", 8)
        with pytest.raises(wahoo_routes.BadLine, match="too large"):
            wahoo_routes.build("Loop", LINE, FIT_B64)


@db
@pytest.mark.usefixtures("keys")
class TestSendingRoutes:
    def _linked(self, fake) -> tuple[Client, User, str]:
        mine, user, csrf = signed_in()
        connect(mine)
        fake.calls.clear()
        return mine, user, csrf

    def _send(self, client, csrf, saved=None):
        body = {"name": "Loop", "line": LINE, "fit": FIT_B64, "saved_route": saved}
        return send(client, "post", "/api/me/wahoo/routes", body, csrf)

    def _saved(self, user) -> int:
        from core.models import SavedRoute

        return SavedRoute.objects.create(user=user, name="Loop", line=LINE, distance_m=1112).pk

    def test_a_route_not_saved_is_added_each_time_and_remembered(self, fake) -> None:
        mine, user, csrf = self._linked(fake)
        assert self._send(mine, csrf).json() == {"sent": "added"}
        assert self._send(mine, csrf).json() == {"sent": "added"}
        assert [c[0] for c in fake.calls] == ["POST", "POST"]
        first, second = fake.calls[0][2], fake.calls[1][2]
        assert first["access"] == "access-1"
        assert first["route[external_id]"] != second["route[external_id]"]
        assert first["route[provider_updated_at]"]
        assert sorted(WahooLink.objects.get(user=user).routes.values()) == [101, 102]

    def test_a_saved_route_sent_again_updates_it(self, fake) -> None:
        mine, user, csrf = self._linked(fake)
        saved = self._saved(user)
        assert self._send(mine, csrf, saved).json() == {"sent": "added"}
        assert self._send(mine, csrf, saved).json() == {"sent": "updated"}
        method, url, form = fake.calls[1]
        assert (method, url) == ("PUT", f"{wahoo.ROUTES_URL}/101")
        assert "route[external_id]" not in form

    def test_a_route_deleted_in_the_wahoo_app_is_added_again(self, fake) -> None:
        mine, user, csrf = self._linked(fake)
        saved = self._saved(user)
        self._send(mine, csrf, saved)
        fake.answers = [404]
        assert self._send(mine, csrf, saved).json() == {"sent": "added"}
        assert WahooLink.objects.get(user=user).routes == {str(saved): 102}

    def test_connecting_another_wahoo_account_forgets_the_routes(self, fake) -> None:
        mine, user, csrf = self._linked(fake)
        self._send(mine, csrf, self._saved(user))
        fake.user = 99
        connect(mine)
        assert WahooLink.objects.get(user=user).routes == {}

    def test_someone_else_s_saved_route_is_not_used(self, fake) -> None:
        mine, _user, csrf = self._linked(fake)
        theirs = self._saved(make_user())
        assert self._send(mine, csrf, theirs).json() == {"sent": "added"}
        assert self._send(mine, csrf, theirs).json() == {"sent": "added"}

    def test_a_refused_token_is_refreshed_once(self, fake) -> None:
        mine, _user, csrf = self._linked(fake)
        fake.answers = [401, 201]
        assert self._send(mine, csrf).json() == {"sent": "added"}
        kinds = [(c[0], c[2].get("grant_type")) for c in fake.calls]
        assert kinds == [("POST", None), ("POST", "refresh_token"), ("POST", None)]
        assert fake.calls[2][2]["access"] == "access-2"

    @pytest.mark.parametrize(
        ("status", "words"),
        [
            (422, "could not read"),
            (429, "too many routes"),
            (403, "Connect Wahoo again"),
            (500, "did not take"),
        ],  # fmt: skip
    )
    def test_wahoo_s_refusals_are_said(self, fake, status, words) -> None:
        mine, _user, csrf = self._linked(fake)
        fake.answers = [status]
        r = self._send(mine, csrf)
        assert r.status_code == 502 and words in r.json()["error"]

    def test_without_a_connection_it_says_so(self, fake) -> None:
        mine, _user, csrf = signed_in()
        r = self._send(mine, csrf)
        assert r.status_code == 409 and r.json()["code"] == "not_connected"
        assert fake.calls == []

    def test_a_bad_file_or_line_sends_nothing(self, fake) -> None:
        mine, _user, csrf = self._linked(fake)
        r = send(mine, "post", "/api/me/wahoo/routes", {"line": LINE, "fit": "eA=="}, csrf)
        assert r.status_code == 400
        r = send(mine, "post", "/api/me/wahoo/routes", {"line": [[0, 0]], "fit": FIT_B64}, csrf)
        assert r.status_code == 400 and fake.calls == []

    def test_it_needs_the_csrf_token(self, fake) -> None:
        mine, _user, _ = self._linked(fake)
        assert self._send(mine, None).status_code == 403
