"""Deleting an account (core.account_deletion; Google Play's account-deletion rule): one page,
GET and POST /delete-account, linked from Settings > Account and usable without the app.

What is the rider's own goes, what is the map's record stays with nothing naming them, every
device is signed out, and the last instance admin is refused with nothing changed.
"""

from __future__ import annotations

import re
from html import escape
from pathlib import Path

import pytest
from django.test import Client
from django.utils import timezone
from test_accounts import addr, make_user, route_body, send, signed_in

from core import account_deletion
from core.models import (
    AccountSettings,
    AssistantKey,
    AuditLogEntry,
    CachedMembership,
    ConfiguredGuild,
    JunctionSuggestion,
    MassHazard,
    MyGo,
    SavedRoute,
    Session,
    SharedRoute,
    StressSuggestion,
    StressSuggestionReview,
    User,
)

db = pytest.mark.django_db(transaction=True)
ROOT = Path(__file__).resolve().parents[1]


def page_csrf(client: Client) -> str:
    r = client.get(account_deletion.PATH, **addr())
    assert r.status_code == 200
    return re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', r.content.decode()).group(1)


def delete(client: Client, csrf: str | None, confirm: bool = True):
    data = {"csrfmiddlewaretoken": csrf} if csrf else {}
    if confirm:
        data[account_deletion.CONFIRM_FIELD] = "yes"
    return client.post(account_deletion.PATH, data=data, **addr())


def suggestion(user, status: str, way: int) -> StressSuggestion:
    return StressSuggestion.objects.create(
        suggester=user, suggester_user_id=user.pk, osm_way_id=way, lat=38.9, lon=-77.0,
        current_tier=3, tier=2, reason="fast cars", status=status,
    )  # fmt: skip


def a_full_account():
    client, user, csrf = signed_in()
    assert send(client, "post", "/api/me/settings", {"settings": {"v": 1, "topo": True}}, csrf)
    assert send(client, "post", "/api/me/routes", route_body(), csrf).status_code == 201
    assert send(client, "post", "/api/me/assistant-key", {}, csrf).status_code == 201
    MyGo.objects.create(user=user, home_lat=38.9, home_lon=-77.0, home_label="Home")
    SharedRoute.objects.create(id="c" * 32, owner=user, line=[[0, 0], [1, 1]], distance_m=1.0)
    return client, user


@db
class TestPage:
    def test_signed_out_it_explains_and_offers_sign_in(self, client, settings) -> None:
        settings.DISCORD_CLIENT_ID, settings.DISCORD_CLIENT_SECRET = "id", "secret"
        r = client.get(account_deletion.PATH, **addr())
        body = r.content.decode()
        assert r.status_code == 200 and r["Cache-Control"] == "no-store"
        assert "/auth/login?next=/delete-account" in body
        assert "Your saved routes" in body and "Kept" in body
        assert "<form" not in body
        assert escape(account_deletion.BANNED) in body

    def test_signed_out_post_deletes_nothing(self, client) -> None:
        user = make_user()
        assert delete(client, None).status_code in (401, 403)
        assert User.objects.filter(pk=user.pk).exists()

    def test_signed_out_post_with_a_token_is_401(self) -> None:
        client = Client(enforce_csrf_checks=True)
        user = make_user()
        token = "a" * 32  # a CSRF secret, as the cookie and the form both carry it
        client.cookies["csrftoken"] = token
        r = delete(client, token)
        assert r.status_code == 401 and User.objects.filter(pk=user.pk).exists()

    def test_signed_in_it_offers_the_one_button(self) -> None:
        client, _user, _csrf = signed_in()
        body = client.get(account_deletion.PATH, **addr()).content.decode()
        assert "Delete my account" in body and "required" in body
        # The form comes first, then what deletion does; a signed-in rider is not banned.
        assert body.index("<form") < body.index("Deleted at once")
        assert escape(account_deletion.BANNED) not in body

    def test_it_needs_the_csrf_token(self) -> None:
        client, user, _csrf = signed_in()
        assert delete(client, None).status_code == 403
        assert User.objects.filter(pk=user.pk).exists()

    def test_it_needs_the_box_ticked(self) -> None:
        client, user, _csrf = signed_in()
        r = delete(client, page_csrf(client), confirm=False)
        assert r.status_code == 400 and account_deletion.NOT_CONFIRMED in r.content.decode()
        assert User.objects.filter(pk=user.pk).exists()

    def test_the_settings_link_is_this_page(self) -> None:
        sign_in = (ROOT / "frontend/src/lib/signIn.ts").read_text()
        assert f'DELETE_ACCOUNT_PAGE = "{account_deletion.PATH}"' in sign_in
        assert "DELETE_ACCOUNT_PAGE" in (ROOT / "frontend/src/app/Sheets.tsx").read_text()


@db
class TestDeletion:
    def test_everything_of_the_riders_goes_and_they_are_signed_out(self) -> None:
        client, user = a_full_account()
        other_device, _same, _ = signed_in(user)
        r = delete(client, page_csrf(client))
        assert r.status_code == 200 and account_deletion.DONE in r.content.decode()
        assert not User.objects.filter(pk=user.pk).exists()
        for model in (AccountSettings, SavedRoute, AssistantKey, MyGo, Session):
            assert not model.objects.filter(user_id=user.pk).exists(), model
        # Signed out here and on the other device.
        assert client.get("/api/me/settings", **addr()).status_code == 401
        assert other_device.get("/api/me/settings", **addr()).status_code == 401
        # The audit keeps the account number, never the Discord id.
        entry = AuditLogEntry.objects.get(action="delete_account")
        assert entry.object_id == str(user.pk)
        assert str(user.discord_user_id) not in f"{entry.object_id} {entry.detail}"

    def test_a_shared_link_is_turned_off_and_names_nobody(self) -> None:
        client, user = a_full_account()
        delete(client, page_csrf(client))
        row = SharedRoute.objects.get(pk="c" * 32)
        assert row.revoked_at is not None and row.owner_id is None and row.line == []

    def test_waiting_suggestions_go_and_decided_ones_stay_unnamed(self) -> None:
        client, user, _csrf = signed_in()
        rider = make_user()
        waiting = suggestion(user, "pending", 1)
        sent = suggestion(user, "sent_to_discord", 2)
        decided = suggestion(user, "approved", 3)
        theirs = suggestion(rider, "pending", 4)
        StressSuggestionReview.objects.create(
            suggestion=theirs, reviewer=user, reviewer_user_id=user.pk, agree=True
        )
        hazard = MassHazard.objects.create(reporter=user, reporter_user_id=user.pk, osm_way_id=5,
                                           level="warning", reason="potholes")  # fmt: skip
        kept_hazard = MassHazard.objects.create(reporter=user, reporter_user_id=user.pk,
                                                osm_way_id=6, level="warning", reason="sand",
                                                status="approved")  # fmt: skip
        junction = JunctionSuggestion.objects.create(
            suggester=user, suggester_user_id=user.pk, lon=-77.0, lat=38.9, node="n1",
            current_level=2, target_level=5, reason="r",
        )  # fmt: skip
        # A row whose link was already cleared still carries the number: it goes as well.
        unlinked = suggestion(user, "pending", 7)
        StressSuggestion.objects.filter(pk=unlinked.pk).update(suggester=None)
        delete(client, page_csrf(client))
        assert not StressSuggestion.objects.filter(
            pk__in=[waiting.pk, sent.pk, unlinked.pk]
        ).exists()
        assert not JunctionSuggestion.objects.filter(pk=junction.pk).exists()
        hazard_kept = MassHazard.objects.get(pk=kept_hazard.pk)
        assert hazard_kept.reporter_id is None and hazard_kept.reporter_user_id is None
        assert not MassHazard.objects.filter(pk=hazard.pk).exists()
        kept = StressSuggestion.objects.get(pk=decided.pk)
        assert kept.suggester_id is None and kept.suggester_user_id is None
        assert StressSuggestion.objects.filter(pk=theirs.pk).exists()
        assert not StressSuggestionReview.objects.exists()

    def test_the_bots_cached_roles_go(self) -> None:
        client, user, _csrf = signed_in()
        guild = ConfiguredGuild.objects.create(guild_id=4242, name="Club")
        CachedMembership.objects.create(
            discord_user_id=user.discord_user_id,
            guild=guild,
            role_ids=[],
            last_confirmed=timezone.now(),
        )
        delete(client, page_csrf(client))
        assert not CachedMembership.objects.filter(discord_user_id=user.discord_user_id).exists()

    def test_signing_in_again_is_a_new_empty_account(self) -> None:
        client, user = a_full_account()
        discord_id = user.discord_user_id
        delete(client, page_csrf(client))
        again = User.objects.create(discord_user_id=discord_id)
        assert not SavedRoute.objects.filter(user=again).exists()
        assert not MyGo.objects.filter(user=again).exists()

    def test_the_last_instance_admin_is_refused_with_nothing_changed(self) -> None:
        admin = make_user(is_instance_admin=True)
        client, admin, _csrf = signed_in(admin)
        assert send(client, "post", "/api/me/routes", route_body(), _csrf).status_code == 201
        r = delete(client, page_csrf(client))
        assert r.status_code == 409 and "only admin" in r.content.decode()
        assert User.objects.filter(pk=admin.pk).exists()
        assert SavedRoute.objects.filter(user=admin).exists()
        assert not AuditLogEntry.objects.filter(action="delete_account").exists()

    def test_an_admin_with_another_admin_may_go(self) -> None:
        make_user(is_instance_admin=True)
        client, admin, _csrf = signed_in(make_user(is_instance_admin=True))
        assert delete(client, page_csrf(client)).status_code == 200
        assert not User.objects.filter(pk=admin.pk).exists()
