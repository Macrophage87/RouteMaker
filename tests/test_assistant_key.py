"""The AI assistant key (core.models.AssistantKey; the owner, 2026-10-18): Settings makes, shows
once and removes an account's one save-only key, and POST /api/keyed/routes adds a route to that
account's My routes with it, and does nothing else."""

from __future__ import annotations

import json

import pytest
from django.test import Client
from test_accounts import addr, route_body, send, signed_in

from core.models import AssistantKey, SavedRoute

db = pytest.mark.django_db(transaction=True)


def make_key(client, csrf) -> str:
    r = send(client, "post", "/api/me/assistant-key", {}, csrf)
    assert r.status_code == 201, r.content
    return r.json()["secret"]


def keyed(key: str | None, payload, client: Client | None = None):
    extra = {"HTTP_X_ROUTEMAKER_KEY": key} if key else {}
    return (client or Client()).post(
        "/api/keyed/routes",
        data=json.dumps(payload),
        content_type="application/json",
        **extra,
        **addr(),
    )


@db
class TestAssistantKey:
    def test_signed_out_cannot_make_or_read_one(self, client) -> None:
        assert client.get("/api/me/assistant-key", **addr()).status_code == 401
        r = client.post(
            "/api/me/assistant-key", data="{}", content_type="application/json", **addr()
        )
        assert r.status_code in (401, 403)

    def test_making_one_needs_the_csrf_token(self) -> None:
        client, user, _csrf = signed_in()
        assert send(client, "post", "/api/me/assistant-key", {}, None).status_code == 403
        assert not AssistantKey.objects.filter(user=user).exists()

    def test_the_key_is_shown_once_and_only_its_digest_kept(self) -> None:
        client, user, csrf = signed_in()
        assert client.get("/api/me/assistant-key", **addr()).json() == {"key": None}
        secret = make_key(client, csrf)
        assert secret.startswith("rmk_") and len(secret) > 40
        row = AssistantKey.objects.get(user=user)
        assert secret not in (row.digest, row.hint) and row.hint == secret[-4:]
        read = client.get("/api/me/assistant-key", **addr())
        assert read["Cache-Control"] == "no-store"
        assert "secret" not in read.json() and read.json()["key"]["hint"] == secret[-4:]
        assert secret not in read.content.decode()

    def test_a_key_adds_a_route_to_its_own_account(self) -> None:
        client, user, csrf = signed_in()
        secret = make_key(client, csrf)
        r = keyed(secret, route_body(name="100 mi Metro loop"))
        assert r.status_code == 201, r.content
        row = SavedRoute.objects.get(user=user)
        assert row.name == "100 mi Metro loop"
        assert AssistantKey.objects.get(user=user).last_used_at is not None
        # It shows in My routes like any other save.
        listed = client.get("/api/me/routes", **addr()).json()["routes"]
        assert [r["name"] for r in listed] == ["100 mi Metro loop"]

    def test_making_a_new_key_retires_the_old_one(self) -> None:
        client, user, csrf = signed_in()
        old = make_key(client, csrf)
        new = make_key(client, csrf)
        assert keyed(old, route_body()).status_code == 401
        assert keyed(new, route_body()).status_code == 201
        assert AssistantKey.objects.filter(user=user).count() == 1

    def test_a_removed_key_saves_nothing(self) -> None:
        client, user, csrf = signed_in()
        secret = make_key(client, csrf)
        r = send(client, "post", "/api/me/assistant-key/delete", {}, csrf)
        assert r.status_code == 200 and r.json() == {"key": None}
        assert keyed(secret, route_body()).status_code == 401
        assert not SavedRoute.objects.filter(user=user).exists()

    @pytest.mark.parametrize("key", [None, "", "rmk_nope", "not-a-key", "rmk_" + "x" * 200])
    def test_no_key_or_a_wrong_one_is_401(self, key) -> None:
        r = keyed(key, route_body())
        assert r.status_code == 401 and r.json()["code"] == "bad_key"
        assert not SavedRoute.objects.exists()

    def test_a_session_cookie_is_no_key(self) -> None:
        """The keyed endpoint reads the key only: a signed-in browser without one is refused."""
        client, user, _csrf = signed_in()
        r = keyed(None, route_body(), client=client)
        assert r.status_code == 401
        assert not SavedRoute.objects.filter(user=user).exists()

    def test_the_key_does_not_sign_in(self) -> None:
        client, _user, csrf = signed_in()
        secret = make_key(client, csrf)
        other = Client()
        auth = {"HTTP_X_ROUTEMAKER_KEY": secret, "HTTP_AUTHORIZATION": f"Bearer {secret}"}
        assert other.get("/api/me/routes", **auth, **addr()).status_code == 401
        assert other.get("/api/me/assistant-key", **auth, **addr()).status_code == 401

    def test_a_key_only_adds_and_never_saves_over_a_route(self) -> None:
        client, user, csrf = signed_in()
        secret = make_key(client, csrf)
        first = send(client, "post", "/api/me/routes", route_body(name="mine"), csrf).json()
        r = keyed(secret, route_body(name="changed", version_of=first["id"]))
        assert r.status_code == 400
        assert SavedRoute.objects.get(user=user).name == "mine"

    @pytest.mark.parametrize("field", ["is_banned", "is_deleted"])
    def test_a_ban_or_deletion_ends_the_key_for_good(self, field) -> None:
        client, user, csrf = signed_in()
        secret = make_key(client, csrf)
        setattr(user, field, True)
        user.save(update_fields=[field])
        assert keyed(secret, route_body()).status_code == 401
        assert not AssistantKey.objects.filter(user=user).exists()
        # Lifting a ban does not bring the key back.
        setattr(user, field, False)
        user.save(update_fields=[field])
        assert keyed(secret, route_body()).status_code == 401

    def test_the_beta_s_password_gate_and_the_key_travel_together(self) -> None:
        """The beta's nginx asks for Basic credentials in Authorization; the key has its own
        header, so a request can carry both."""
        client, user, csrf = signed_in()
        secret = make_key(client, csrf)
        r = Client().post(
            "/api/keyed/routes",
            data=json.dumps(route_body()),
            content_type="application/json",
            HTTP_AUTHORIZATION="Basic cmlkZXI6cGFzcw==",
            HTTP_X_ROUTEMAKER_KEY=secret,
            **addr(),
        )
        assert r.status_code == 201 and SavedRoute.objects.filter(user=user).count() == 1

    def test_a_failure_is_worded_as_a_save_not_a_route_plan(self, monkeypatch) -> None:
        import core.api

        client, _user, csrf = signed_in()
        secret = make_key(client, csrf)

        def broken(request, versions=True):
            raise RuntimeError("boom")

        monkeypatch.setattr(core.api, "_add_saved_route", broken)
        r = keyed(secret, route_body())
        assert r.status_code == 500 and "nothing was changed" in r.json()["error"]

    def test_the_key_goes_with_the_account(self) -> None:
        client, user, csrf = signed_in()
        make_key(client, csrf)
        user.delete()
        assert not AssistantKey.objects.exists()

    def test_a_bad_route_is_refused_as_my_routes_refuses_it(self) -> None:
        client, _user, csrf = signed_in()
        secret = make_key(client, csrf)
        assert keyed(secret, route_body(line=[[0, 0]])).status_code == 400
