"""Rider suggestions (441h, 460.4, 460.5; core.suggestions) and the admin's three actions.

The owner, 2026-10-10: approve now (live at once, as the editor's change), delete, or send to
Discord, which answers a ready-to-paste plain-English poll and marks the suggestion as sent.
"""

from __future__ import annotations

import pytest
from django.db import connection
from django.test import Client
from test_stress_edits import (
    LAT,
    LON,
    ME,
    WAY,
    addr,
    live_row,
    make_segment,
    make_user,
    post,
    sign_in,
)

from core import segment_info, suggestions
from core.models import AuditLogEntry, Override, StressSuggestion, SuggestionSettings

db = pytest.mark.django_db(transaction=True)

SUGGEST = "/api/stress-suggestions"
OPEN = "/api/stress-suggestions/open"
ACTION = "/api/stress-suggestions/{}/{}"
WHY = "A protected lane opened here this summer."


@pytest.fixture(autouse=True)
def _columns():
    segment_info.forget_columns()
    yield
    segment_info.forget_columns()


def cross_street(schema, way, name, lon) -> None:
    """A street running north-south across (lon, LAT)."""
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {schema}.segment (osm_way_id, ordinal, stress_tier, stress_rule, "
            "trail_name, map_class, geometry) VALUES (%s, 0, 2, 'r', %s, 'road', "
            "ST_MakeLine(ST_MakePoint(%s, %s), ST_MakePoint(%s, %s)))",
            [way, name, lon, LAT - 0.001, lon, LAT + 0.001],
        )


@pytest.fixture
def live(segment_schemas):
    schema, _staging = segment_schemas
    # The road, west to east, and a cross street at each end.
    make_segment(schema, WAY, 3, trail_name="Oak Street", map_class="road")
    cross_street(schema, 6001, "Elm Street", LON)
    cross_street(schema, 6002, "Ash Avenue", LON + 0.002)
    return schema


def open_to(who: str) -> None:
    SuggestionSettings.objects.update_or_create(pk=1, defaults={"who": who})


def rider_client(user=None):
    client = Client(enforce_csrf_checks=True)
    sign_in(client, user or make_user(admin=False))
    assert client.get(ME, **addr()).status_code == 200
    return client, client.cookies["csrftoken"].value


def admin_client():
    client = Client(enforce_csrf_checks=True)
    sign_in(client, make_user())
    client.get(ME, **addr())
    return client, client.cookies["csrftoken"].value


def suggestion_body(**change) -> dict:
    return {"osm_way_id": WAY, "lat": LAT, "lon": LON + 0.001, "step": 2, "reason": WHY, **change}


def suggest(user=None, **change) -> StressSuggestion:
    user = user or make_user(admin=False)
    return suggestions.create(
        user,
        change.pop("way", WAY),
        LAT,
        LON + 0.001,
        change.pop("step", 2),
        change.pop("reason", WHY),
    )


@db
class TestWhoMaySuggest:
    def test_nobody_by_default(self, live) -> None:
        assert SuggestionSettings.current().who == "nobody"
        assert suggestions.may_suggest(make_user(admin=False)) is False

    def test_anyone_signed_in_when_opened(self, live) -> None:
        open_to("signed_in")
        assert suggestions.may_suggest(make_user(admin=False)) is True

    def test_members_only_means_a_member_of_a_configured_server(self, live) -> None:
        open_to("members")
        rider = make_user(admin=False)
        rider._member_guild_ids = frozenset()
        assert suggestions.may_suggest(rider) is False
        rider._member_guild_ids = frozenset({123})
        assert suggestions.may_suggest(rider) is True

    def test_an_instance_admin_edits_and_does_not_suggest(self, live) -> None:
        open_to("signed_in")
        assert suggestions.may_suggest(make_user()) is False

    def test_me_says_so_and_sets_the_csrf_cookie(self, live) -> None:
        open_to("signed_in")
        client = sign_in(Client(), make_user(admin=False))
        r = client.get(ME, **addr())
        assert r.json() == {"signed_in": True, "can_change_lts": False, "can_suggest": True}
        assert "csrftoken" in r.cookies


@db
class TestCreate:
    def test_a_suggestion_waits_and_changes_nothing(self, live) -> None:
        open_to("signed_in")
        rider = make_user(admin=False)
        s = suggest(rider)
        assert (s.status, s.tier, s.half, s.current_tier, s.road_name) == (
            "pending",
            2,
            False,
            3,
            "Oak Street",
        )
        assert live_row(live)["stress_tier"] == 3 and Override.objects.count() == 0
        assert AuditLogEntry.objects.filter(action="stress_suggest").count() == 1

    def test_a_half_step_may_be_suggested(self, live) -> None:
        open_to("signed_in")
        s = suggest(step=2.5)
        assert (s.tier, s.half, s.step) == (2, True, 2.5)

    def test_the_road_level_itself_and_an_empty_reason_are_refused(self, live) -> None:
        open_to("signed_in")
        with pytest.raises(suggestions.stress_edits.Invalid) as same:
            suggest(step=3)
        assert same.value.field == "step"
        with pytest.raises(suggestions.stress_edits.Invalid) as empty:
            suggest(reason="  ")
        assert empty.value.field == "reason"

    def test_one_waiting_suggestion_per_road_per_rider(self, live) -> None:
        open_to("signed_in")
        rider = make_user(admin=False)
        suggest(rider)
        with pytest.raises(suggestions.Conflict):
            suggest(rider, step=1)

    def test_the_endpoint_needs_a_session_the_setting_and_the_csrf_token(self, live) -> None:
        assert post(Client(), SUGGEST, suggestion_body()).status_code == 401
        open_to("signed_in")
        client, csrf = rider_client()
        open_to("nobody")
        r = post(client, SUGGEST, suggestion_body(), csrf)
        assert r.status_code == 403 and r.json()["code"] == "not_allowed"
        open_to("signed_in")
        assert post(client, SUGGEST, suggestion_body()).status_code == 403  # no token
        r = post(client, SUGGEST, suggestion_body(), csrf)
        assert r.status_code == 200, r.content
        assert "Nothing changes on the map" in r.json()["message"]
        assert r["Cache-Control"] == "no-store"

    def test_a_bad_level_names_the_field(self, live) -> None:
        open_to("signed_in")
        client, csrf = rider_client()
        r = post(client, SUGGEST, suggestion_body(step=2.25), csrf)
        assert r.status_code == 400 and r.json()["field"] == "step"

    def test_a_foreign_page_is_refused(self, live) -> None:
        open_to("signed_in")
        client, csrf = rider_client()
        r = post(client, SUGGEST, suggestion_body(), csrf, HTTP_SEC_FETCH_SITE="cross-site")
        assert r.status_code == 403


@db
class TestReview:
    def test_the_list_is_the_admins_and_names_nobody(self, live) -> None:
        open_to("signed_in")
        rider = make_user(admin=False)
        suggest(rider)
        member, _ = rider_client()
        assert member.get(OPEN, **addr()).status_code == 403
        client, _ = admin_client()
        r = client.get(OPEN, **addr())
        assert r.status_code == 200
        (item,) = r.json()["suggestions"]
        assert item["road"] == "Oak Street" and item["step"] == 2 and item["current_step"] == 3
        assert item["words"] == "Fine for adults" and item["status"] == "pending"
        # Nothing about the rider: no account, no id, no name.
        assert set(item) == {
            "id", "osm_way_id", "road", "lat", "lon", "current_step", "current_words",
            "step", "words", "reason", "status", "created_at", "sent_at",
        }  # fmt: skip

    def test_approve_now_applies_it_as_the_admins_edit(self, live) -> None:
        open_to("signed_in")
        s = suggest(step=2.5)
        client, csrf = admin_client()
        r = post(client, ACTION.format(s.pk, "approve"), {}, csrf)
        assert r.status_code == 200, r.content
        assert r.json()["message"].startswith("Approved. Oak Street is now LTS 2.5")
        row = live_row(live)
        assert row["stress_tier"] == 2 and row["stress_half"] is True
        s.refresh_from_db()
        assert s.status == "approved" and s.edit is not None and s.decided_at is not None
        override = Override.objects.get()
        assert override.value["half"] is True and override.reason.startswith("Rider suggestion")

    def test_delete(self, live) -> None:
        open_to("signed_in")
        s = suggest()
        client, csrf = admin_client()
        r = post(client, ACTION.format(s.pk, "delete"), {}, csrf)
        assert r.status_code == 200 and r.json()["status"] == "deleted"
        assert live_row(live)["stress_tier"] == 3
        r = post(client, ACTION.format(s.pk, "approve"), {}, csrf)
        assert r.status_code == 409

    def test_send_to_discord_answers_the_plain_poll_and_marks_it_sent(self, live) -> None:
        open_to("signed_in")
        s = suggest(reason="Protected lane now @everyone")
        client, csrf = admin_client()
        r = post(client, ACTION.format(s.pk, "discord"), {}, csrf, HTTP_HOST="testserver")
        assert r.status_code == 200, r.content
        data = r.json()
        text = data["post"]
        assert data["characters"] == len(text) <= 2000
        assert text.splitlines()[0] == (
            "**How comfortable is biking on Oak Street, between Elm Street and Ash Avenue?**"
        )
        assert "We currently show it as: OK for confident riders" in text
        assert "The rider suggested: Fine for most people, even nervous riders" in text
        assert "Map: <http://testserver/#at=" in text
        assert "@everyone" not in text and "LTS" not in text
        assert [o["tier"] for o in data["options"]] == [1, 2, 3, 4, 5, None]
        s.refresh_from_db()
        assert s.status == "sent_to_discord" and s.sent_at is not None
        # Still waiting: approve or delete it later.
        assert post(client, ACTION.format(s.pk, "approve"), {}, csrf).status_code == 200

    def test_a_rider_cannot_take_an_action(self, live) -> None:
        open_to("signed_in")
        s = suggest()
        client, csrf = rider_client()
        for action in ("approve", "delete", "discord"):
            assert post(client, ACTION.format(s.pk, action), {}, csrf).status_code == 403
