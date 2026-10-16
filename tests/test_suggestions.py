"""Rider suggestions (441h, 460.4, 460.5; core.suggestions) and the admin's three actions.

The owner, 2026-10-10: approve now (live at once, as the editor's change), delete, or send to
Discord, which answers a ready-to-paste plain-English poll and marks the suggestion as sent.
"""

from __future__ import annotations

import re

import pytest
from django.db import IntegrityError, connection, transaction
from django.test import Client
from test_ratelimit import in_one_window
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

from core import ratelimit, segment_info, suggestions
from core.models import AuditLogEntry, Override, StressSuggestion, SuggestionSettings, User

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


@pytest.fixture(autouse=True)
def router(monkeypatch):
    """The router's names by way, at any spot (`names`); silent while `names` is None, so the
    table's names stand."""

    class Fake:
        names: dict[int, str] | None = None

    def fake(lat, lon, costing, timeout_s=None):
        if Fake.names is None:
            raise segment_info.RouterSilent("down")
        return [{"edge_info": {"way_id": w, "names": [n]}} for w, n in Fake.names.items()]

    monkeypatch.setattr(segment_info, "locate_edges", fake)
    return Fake


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
    """A suggestion from a spot on the road, by the service."""
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
        assert r.json() == {
            "signed_in": True,
            "can_change_lts": False,
            "can_suggest": True,
            "can_review_closures": False,
            "sign_in": True,
        }
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

    def test_a_reason_of_500_characters_is_taken_and_501_refused(self, live) -> None:
        open_to("signed_in")
        assert len(suggest(reason="x" * 500).reason) == 500
        with pytest.raises(suggestions.stress_edits.Invalid) as long:
            suggest(reason="x" * 501)
        assert long.value.field == "reason"

    def test_at_most_open_max_waiting_per_rider(self, live) -> None:
        open_to("signed_in")
        rider = make_user(admin=False)
        for i in range(suggestions.OPEN_MAX):
            make_segment(live, 9000 + i, 3, lat=LAT + 0.01 * (i + 1), map_class="road")
            suggestions.create(rider, 9000 + i, LAT + 0.01 * (i + 1), LON + 0.001, 2, WHY)
        with pytest.raises(suggestions.Conflict) as full:
            suggest(rider)
        assert str(suggestions.OPEN_MAX) in full.value.message
        # Another rider is not held back by this one's list.
        assert suggest(make_user(admin=False)).status == "pending"

    def test_the_database_holds_one_open_suggestion_per_road_per_rider(self, live) -> None:
        open_to("signed_in")
        rider = make_user(admin=False)
        first = suggest(rider)
        with pytest.raises(IntegrityError), transaction.atomic():
            StressSuggestion.objects.create(
                suggester=rider, osm_way_id=WAY, lat=LAT, lon=LON, current_tier=3, tier=1,
                reason=WHY,
            )  # fmt: skip
        # Once decided, the rider may suggest for the road again.
        StressSuggestion.objects.filter(pk=first.pk).update(status="deleted")
        assert suggest(rider, step=1).status == "pending"

    def test_ten_suggestions_an_hour_per_account(self, live) -> None:
        open_to("signed_in")

        def attempt(n):
            client, csrf = rider_client()
            user = User.objects.latest("pk")
            key = ratelimit.client_key(f"user:{user.pk}")
            for _ in range(ratelimit.SUGGEST_WRITES.requests):
                ratelimit.hit(ratelimit.SUGGEST_WRITES, key)
            return post(client, SUGGEST, suggestion_body(), csrf)

        r = in_one_window(ratelimit.SUGGEST_WRITES.window_s, attempt)
        assert ratelimit.SUGGEST_WRITES.requests == 10
        assert r.status_code == 429 and StressSuggestion.objects.count() == 0

    def test_a_half_step_is_refused_until_the_road_data_can_hold_one(self, live) -> None:
        open_to("signed_in")
        with connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE {live}.segment DROP COLUMN stress_half")
        segment_info.forget_columns()
        with pytest.raises(suggestions.stress_edits.Invalid) as half:
            suggest(step=2.5)
        assert half.value.code == "half_unavailable"
        assert suggest(step=2).tier == 2


@db
class TestPrivacy:
    def test_the_spot_kept_is_the_nearest_point_on_the_road_never_the_riders(self, live) -> None:
        open_to("signed_in")
        rider = make_user(admin=False)
        # 0.0001 degrees north of the road (about 11 m (36 ft)), as a click beside it.
        s = suggestions.create(rider, WAY, LAT + 0.0001, LON + 0.001, 2, WHY)
        assert s.lat == pytest.approx(LAT, abs=1e-6) and s.lon == pytest.approx(
            LON + 0.001, abs=1e-6
        )

    def test_a_spot_more_than_30_m_from_the_road_is_refused(self, live) -> None:
        open_to("signed_in")
        rider = make_user(admin=False)
        with pytest.raises(suggestions.stress_edits.Invalid) as far:
            # 0.0004 degrees north: about 44 m (146 ft).
            suggestions.create(rider, WAY, LAT + 0.0004, LON + 0.001, 2, WHY)
        assert far.value.code == "off_the_road" and "98 ft (30 m)" in far.value.message
        assert StressSuggestion.objects.count() == 0
        client, csrf = rider_client()
        r = post(client, SUGGEST, suggestion_body(lat=LAT + 0.0004), csrf)
        assert r.status_code == 400 and r.json()["field"] == "lat"

    def test_the_post_has_no_coordinates_and_links_the_roads_middle_to_four_decimals(
        self, live
    ) -> None:
        open_to("signed_in")
        rider = make_user(admin=False)
        # A spot near the road's west end: the link still points at the road's middle.
        s = suggestions.create(rider, WAY, LAT + 0.0001, LON + 0.0002, 2, WHY)
        text = suggestions.post_for(s, "http://testserver").text
        link = re.search(r"#at=(-?\d+\.\d+),(-?\d+\.\d+)>", text)
        assert link, text
        assert link.group(1) == f"{LON + 0.001:.4f}" and link.group(2) == f"{LAT:.4f}"
        outside = text.replace(link.group(0), "")
        assert not re.search(r"-?\d+\.\d{3,}", outside), text
        assert f"{s.lat:.5f}" not in text and f"{s.lon:.5f}" not in text


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
            "signed_out", "reasons", "agree", "reviews",
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

    def test_the_poll_names_roads_as_the_panel_does_even_where_the_table_has_no_name(
        self, live, router
    ) -> None:
        # A busy road and its cross streets carry no name in the table (only calm and long
        # ways do); the router names them, as in the road panel.
        with connection.cursor() as cursor:
            cursor.execute(f"UPDATE {live}.segment SET trail_name = NULL")
        router.names = {WAY: "Georgia Avenue NW", 6001: "Elm Street", 6002: "Ash Avenue"}
        open_to("signed_in")
        s = suggest()
        assert s.road_name == "Georgia Avenue NW"
        post_ = suggestions.post_for(s, "http://testserver")
        assert post_.text.splitlines()[0] == (
            "**How comfortable is biking on Georgia Avenue NW, between Elm Street and Ash Avenue?**"
        )

    def test_a_rider_cannot_take_an_action(self, live) -> None:
        open_to("signed_in")
        s = suggest()
        client, csrf = rider_client()
        for action in ("approve", "delete", "discord"):
            assert post(client, ACTION.format(s.pk, action), {}, csrf).status_code == 403

    def test_review_actions_have_their_own_larger_budget(self, live) -> None:
        open_to("signed_in")
        assert ratelimit.SUGGEST_REVIEW_WRITES.requests > ratelimit.STRESS_EDIT_WRITES.requests
        s = suggest()

        def attempt(n):
            client, csrf = admin_client()
            user = User.objects.latest("pk")
            key = ratelimit.client_key(f"user:{user.pk}")
            # A full road-editing budget does not hold back a review.
            for _ in range(ratelimit.STRESS_EDIT_WRITES.requests):
                ratelimit.hit(ratelimit.STRESS_EDIT_WRITES, key)
            first = post(client, ACTION.format(s.pk, "discord"), {}, csrf)
            for _ in range(ratelimit.SUGGEST_REVIEW_WRITES.requests):
                ratelimit.hit(ratelimit.SUGGEST_REVIEW_WRITES, key)
            return first, post(client, ACTION.format(s.pk, "delete"), {}, csrf)

        first, spent = in_one_window(ratelimit.SUGGEST_REVIEW_WRITES.window_s, attempt)
        assert first.status_code == 200 and spent.status_code == 429


MINE = "/api/stress-suggestions/mine?way={}"


@db
class TestSecondReviewer:
    """v0.7.0: a second reviewer marks a waiting suggestion agree or disagree, with an optional
    one-line reason; the list shows the tallies; approving still takes Approve now."""

    def test_agree_and_disagree_are_tallied_and_change_nothing(self, live) -> None:
        open_to("signed_in")
        s = suggest()
        first, csrf1 = admin_client()
        second, csrf2 = admin_client()
        r = post(first, ACTION.format(s.pk, "review"), {"verdict": "agree"}, csrf1)
        assert r.status_code == 200, r.content
        assert r.json()["reviews"] == {"agree": 1, "disagree": 0, "mine": "agree", "notes": []}
        # The counts as the review list says them (lib/suggestions.ts talliesLine).
        assert "Reviewers: 1 agrees, 0 disagree." in r.json()["message"]
        r = post(
            second,
            ACTION.format(s.pk, "review"),
            {"verdict": "disagree", "reason": "  The lane\n ends at Elm.  "},
            csrf2,
        )
        assert r.status_code == 200, r.content
        assert (
            "Reviewers: 1 agrees, 1 disagrees. Approving still takes Approve now"
            in (r.json()["message"])
        )
        (item,) = second.get(OPEN, **addr()).json()["suggestions"]
        assert item["reviews"] == {
            "agree": 1,
            "disagree": 1,
            "mine": "disagree",
            "notes": [{"agree": False, "reason": "The lane ends at Elm."}],
        }
        # Advice only: the suggestion still waits and the road is as it was.
        s.refresh_from_db()
        assert s.status == "pending" and live_row(live)["stress_tier"] == 3
        assert not Override.objects.exists()
        assert AuditLogEntry.objects.filter(action="stress_suggest_review").count() == 2

    def test_a_second_mark_replaces_the_first(self, live) -> None:
        open_to("signed_in")
        s = suggest()
        admin = make_user()
        suggestions.review(admin, s.pk, True)
        suggestions.review(admin, s.pk, False, "no")
        assert suggestions.tallies(s, admin) == {
            "agree": 0,
            "disagree": 1,
            "mine": "disagree",
            "notes": [{"agree": False, "reason": "no"}],
        }

    def test_only_a_reviewer_on_a_waiting_suggestion(self, live) -> None:
        open_to("signed_in")
        rider = make_user(admin=False)
        s = suggest(rider)
        client, csrf = rider_client(rider)
        refused = post(client, ACTION.format(s.pk, "review"), {"verdict": "agree"}, csrf)
        assert refused.status_code == 403
        with pytest.raises(suggestions.Forbidden):
            suggestions.review(rider, s.pk, True)
        admin = make_user()
        with pytest.raises(suggestions.stress_edits.Invalid):
            suggestions.review(admin, s.pk, True, "x" * 201)
        suggestions.delete(admin, s.pk)
        with pytest.raises(suggestions.Conflict):
            suggestions.review(admin, s.pk, True)

    def test_nobody_reviews_their_own_suggestion(self, live, monkeypatch) -> None:
        from core import reviewed_closures

        open_to("signed_in")
        rider = make_user(admin=False)
        s = suggest(rider)
        # A guild reviewer who also suggests (behind GUILD_REVIEWERS).
        monkeypatch.setattr(reviewed_closures, "GUILD_REVIEWERS", True)
        rider._reviewer_guild_ids = frozenset({1})
        with pytest.raises(suggestions.Forbidden):
            suggestions.review(rider, s.pk, True)

    def test_an_instance_admin_is_refused_on_their_own_suggestion(self, live) -> None:
        open_to("signed_in")
        rider = make_user(admin=False)
        s = suggest(rider)
        # The rider who sent it is made an instance admin later.
        rider.is_instance_admin = True
        rider.save(update_fields=["is_instance_admin"])
        client, csrf = rider_client(rider)
        refused = post(client, ACTION.format(s.pk, "review"), {"verdict": "agree"}, csrf)
        assert refused.status_code == 403, refused.content
        assert "You sent this suggestion" in refused.json()["error"]
        assert not s.reviews.exists()


@db
class TestRiderSeesStatus:
    def test_the_rider_reads_their_latest_suggestions_status(self, live) -> None:
        open_to("signed_in")
        rider = make_user(admin=False)
        client, _ = rider_client(rider)
        assert client.get(MINE.format(WAY), **addr()).json() == {"suggestion": None}
        s = suggest(rider)
        mine = client.get(MINE.format(WAY), **addr()).json()["suggestion"]
        assert mine["status"] == "pending" and mine["status_words"] == "Waiting for review."
        assert mine["step"] == 2 and mine["words"] == "Fine for adults"
        suggestions.approve(make_user(), s.pk)
        mine = client.get(MINE.format(WAY), **addr()).json()["suggestion"]
        assert mine["status"] == "approved" and mine["status_words"] == "Approved: the map uses it."
        # Nothing of the reviewers reaches the rider.
        assert "reviews" not in mine and "agree" not in mine

    def test_another_rider_and_a_signed_out_visitor_see_none(self, live) -> None:
        open_to("signed_in")
        suggest(make_user(admin=False))
        other, _ = rider_client()
        assert other.get(MINE.format(WAY), **addr()).json() == {"suggestion": None}
        assert Client().get(MINE.format(WAY), **addr()).status_code == 401

    def test_a_way_id_past_a_bigint_is_refused_as_a_bad_request(self, live) -> None:
        open_to("signed_in")
        client, _ = rider_client(make_user(admin=False))
        assert client.get(MINE.format(2**63 - 1), **addr()).json() == {"suggestion": None}
        assert client.get(MINE.format(2**63), **addr()).status_code == 400
        ticket = Client().get("/api/stress-suggestions/ticket", {"way": 2**63}, **addr())
        assert ticket.status_code == 400, ticket.content
