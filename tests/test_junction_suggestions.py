"""Rider suggestions for junctions (OWNER-DECISIONS 232; core.junction_suggestions).

"Add a mechanism for intersections as well. In some times the road is fine, but the
intersection can be especially dangerous." The road suggestions' twin: the same setting, limits
and three admin actions (approve now, delete, send to Discord), for a junction's node.
"""

from __future__ import annotations

import re

import pytest
from django.contrib.gis.geos import Point
from django.db import IntegrityError, connection, transaction
from django.test import Client
from test_ratelimit import in_one_window
from test_stress_edits import LAT, LON, WAY, addr, make_segment, make_user, post
from test_suggestions import admin_client, open_to, rider_client, router  # noqa: F401

from core import junction_suggestions as js
from core import ratelimit, segment_info, suggestion_post, suggestions
from core.models import (
    AuditLogEntry,
    AvoidJunction,
    JunctionOverride,
    JunctionSuggestion,
    StressSuggestion,
    User,
)

db = pytest.mark.django_db(transaction=True)

SUGGEST = "/api/junction-suggestions"
AT = "/api/junction-suggestions/at"
OPEN = "/api/junction-suggestions/open"
ACTION = "/api/junction-suggestions/{}/{}"
WHY = "Drivers turn right on red without looking; I was nearly hit twice."
# The junction: Oak Street's west end, where Elm Street crosses it.
NODE = (round(LON, 6), round(LAT, 6))


@pytest.fixture(autouse=True)
def _columns():
    segment_info.forget_columns()
    yield
    segment_info.forget_columns()


def cross_street(schema, way, name, lon, tier=2) -> None:
    """A street running north-south across (lon, LAT), with a vertex where it crosses (OSM
    ways share the junction's node)."""
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {schema}.segment (osm_way_id, ordinal, stress_tier, stress_rule, "
            "trail_name, map_class, geometry) VALUES (%s, 0, %s, 'r', %s, 'road', "
            "ST_MakeLine(ARRAY[ST_MakePoint(%s, %s), ST_MakePoint(%s, %s), "
            "ST_MakePoint(%s, %s)]))",
            [way, tier, name, lon, LAT - 0.001, lon, LAT, lon, LAT + 0.001],
        )


@pytest.fixture
def live(segment_schemas):
    schema, _staging = segment_schemas
    make_segment(schema, WAY, 3, trail_name="Oak Street", map_class="road")
    cross_street(schema, 6001, "Elm Street", LON)
    cross_street(schema, 6002, "Ash Avenue", LON + 0.002)
    return schema


def suggest(user=None, *, lat=LAT, lon=LON, level=4, direction="", shown=None, reason=WHY):
    user = user or make_user(admin=False)
    return js.create(user, lat, lon, level, direction, shown, reason)


def body(**change) -> dict:
    return {"lat": LAT + 0.00005, "lon": LON + 0.00005, "level": 4, "reason": WHY, **change}


@db
class TestLocate:
    def test_the_node_is_kept_never_the_spot_asked_about(self, live) -> None:
        open_to("signed_in")
        # About 6 m (20 ft) north-east of the junction, as a tap beside it.
        s = suggest(lat=LAT + 0.00004, lon=LON + 0.00004)
        assert (s.lon, s.lat) == NODE and s.node == f"{NODE[0]:.6f},{NODE[1]:.6f}"
        assert s.roads == ["Oak Street", "Elm Street"]
        assert s.name == "Oak Street and Elm Street"

    def test_a_spot_more_than_82_ft_from_any_junction_is_refused(self, live) -> None:
        open_to("signed_in")
        with pytest.raises(js.stress_edits.Invalid) as far:
            # The middle of Oak Street, about 87 m (285 ft) from either end.
            suggest(lon=LON + 0.001)
        assert far.value.code == "no_junction" and "82 ft (25 m)" in far.value.message
        assert JunctionSuggestion.objects.count() == 0

    def test_a_bend_in_one_road_is_not_a_junction(self, live) -> None:
        open_to("signed_in")
        make_segment(live, 7001, 2, lat=LAT + 0.01, trail_name="Pine Lane", map_class="road")
        make_segment(
            live, 7002, 2, lat=LAT + 0.01, lon=LON + 0.002, trail_name="Pine Lane",
            map_class="road",
        )  # fmt: skip
        with pytest.raises(js.stress_edits.Invalid) as bend:
            suggest(lat=LAT + 0.01, lon=LON + 0.002)
        assert "bend in Pine Lane" in bend.value.message

    def test_two_unnamed_pieces_of_one_road_are_a_bend_too(self, live) -> None:
        open_to("signed_in")
        make_segment(live, 7101, 2, lat=LAT + 0.02, trail_name=None, map_class="road")
        make_segment(
            live, 7102, 2, lat=LAT + 0.02, lon=LON + 0.002, trail_name=None, map_class="road",
        )  # fmt: skip
        with pytest.raises(js.stress_edits.Invalid) as bend:
            suggest(lat=LAT + 0.02, lon=LON + 0.002)
        assert "bend in an unnamed road" in bend.value.message

    def test_the_endpoint_answers_the_junction_for_a_suggester(self, live) -> None:
        assert Client().get(AT, {"lat": LAT, "lon": LON}, **addr()).status_code == 401
        open_to("signed_in")
        client, _ = rider_client()
        r = client.get(AT, {"lat": LAT + 0.00005, "lon": LON}, **addr())
        assert r.status_code == 200, r.content
        assert r.json() == {
            "lon": NODE[0], "lat": NODE[1], "name": "Oak Street and Elm Street",
            "roads": ["Oak Street", "Elm Street"],
        }  # fmt: skip
        assert r["Cache-Control"] == "no-store"
        far = client.get(AT, {"lat": LAT, "lon": LON + 0.001}, **addr())
        assert far.status_code == 400 and far.json()["code"] == "no_junction"

    def test_there_is_no_road_data_yet(self, segment_schemas, monkeypatch) -> None:
        open_to("signed_in")
        monkeypatch.setattr(js.stress_edits, "live_oid", lambda schema: None)
        with pytest.raises(js.stress_edits.NotFound):
            suggest()


@db
class TestCreate:
    def test_a_level_waits_and_changes_nothing(self, live) -> None:
        open_to("signed_in")
        s = suggest(level=4)
        assert (s.status, s.current_level, s.level, s.target_level) == ("pending", 2, 4, 4)
        assert JunctionOverride.objects.count() == 0 and AvoidJunction.objects.count() == 0
        assert AuditLogEntry.objects.filter(action="junction_suggest").count() == 1

    def test_more_dangerous_than_shown_alone_means_one_level_up(self, live) -> None:
        open_to("signed_in")
        s = suggest(level=None, direction="more", shown="orange")
        assert (s.current_level, s.level, s.direction, s.target_level) == (3, None, "more", 4)

    def test_less_dangerous_than_shown_alone_means_one_level_down(self, live) -> None:
        open_to("signed_in")
        s = suggest(level=None, direction="less", shown="red")
        assert s.target_level == 3

    def test_avoid_may_be_suggested(self, live) -> None:
        open_to("signed_in")
        assert suggest(level=5, shown="red").target_level == 5

    @pytest.mark.parametrize(
        ("level", "direction", "shown", "field"),
        [
            (None, "", None, "level"),  # nothing chosen
            (2, "", None, "level"),  # the level shown already ("not marked" is easy)
            (1, "", None, "level"),  # not a junction level
            (None, "less", None, "direction"),  # easy already
            (2, "more", "red", "direction"),  # the two disagree
            (None, "sideways", None, "direction"),
        ],
    )
    def test_unclear_choices_are_refused_plainly(self, live, level, direction, shown, field):
        open_to("signed_in")
        with pytest.raises(js.stress_edits.Invalid) as refused:
            suggest(level=level, direction=direction, shown=shown)
        assert refused.value.field == field

    def test_a_route_that_showed_avoid_where_none_is_approved_is_refused(self, live) -> None:
        open_to("signed_in")
        with pytest.raises(js.stress_edits.Invalid) as stale:
            suggest(level=4, shown="avoid")
        assert stale.value.code == "stale"

    def test_the_approved_rating_is_the_shown_level_whatever_the_route_said(self, live) -> None:
        open_to("signed_in")
        JunctionOverride.objects.create(name="x", location=Point(*NODE, srid=4326), level=4)
        with pytest.raises(js.stress_edits.Invalid):
            suggest(level=4, shown="none")
        assert suggest(level=None, direction="less").target_level == 3

    def test_an_approved_avoid_junction_is_shown_as_avoid(self, live) -> None:
        open_to("signed_in")
        AvoidJunction.objects.create(
            name="x", location=Point(*NODE, srid=4326), reason="r", approved=True
        )
        with pytest.raises(js.stress_edits.Invalid) as top:
            suggest(level=None, direction="more")
        assert "Avoid already" in top.value.message
        assert suggest(level=None, direction="less", shown="avoid").target_level == 4

    def test_a_reason_is_required_and_at_most_500_characters(self, live) -> None:
        open_to("signed_in")
        with pytest.raises(js.stress_edits.Invalid) as empty:
            suggest(reason=" ")
        assert empty.value.field == "reason"
        with pytest.raises(js.stress_edits.Invalid) as long:
            suggest(reason="x" * 501)
        assert long.value.field == "reason"
        assert len(suggest(reason="x" * 500).reason) == 500

    def test_nobody_may_suggest_until_the_setting_opens_it(self, live) -> None:
        with pytest.raises(js.Forbidden):
            suggest()
        open_to("signed_in")
        with pytest.raises(js.Forbidden):
            suggest(make_user())  # an instance admin edits, never suggests

    def test_one_waiting_suggestion_per_junction_per_rider(self, live) -> None:
        open_to("signed_in")
        rider = make_user(admin=False)
        suggest(rider)
        with pytest.raises(js.Conflict):
            suggest(rider, level=3, lat=LAT + 0.00003)
        # Another junction, or another rider, is not held back.
        assert suggest(rider, lon=LON + 0.002).status == "pending"
        assert suggest(make_user(admin=False)).status == "pending"

    def test_the_database_holds_one_open_suggestion_per_junction_per_rider(self, live) -> None:
        open_to("signed_in")
        rider = make_user(admin=False)
        first = suggest(rider)
        with pytest.raises(IntegrityError), transaction.atomic():
            JunctionSuggestion.objects.create(
                suggester=rider, lon=NODE[0], lat=NODE[1], node=first.node, current_level=2,
                target_level=3, reason=WHY,
            )  # fmt: skip
        JunctionSuggestion.objects.filter(pk=first.pk).update(status="deleted")
        assert suggest(rider, level=3).status == "pending"

    def test_the_waiting_cap_counts_roads_and_junctions_together(self, live) -> None:
        open_to("signed_in")
        rider = make_user(admin=False)
        for i in range(suggestions.OPEN_MAX):
            StressSuggestion.objects.create(
                suggester=rider, osm_way_id=8000 + i, lat=LAT, lon=LON, current_tier=3, tier=2,
                reason=WHY,
            )  # fmt: skip
        with pytest.raises(js.Conflict) as full:
            suggest(rider)
        assert str(suggestions.OPEN_MAX) in full.value.message

    def test_the_endpoint_needs_a_session_the_setting_and_the_csrf_token(self, live) -> None:
        assert post(Client(), SUGGEST, body()).status_code == 401
        open_to("signed_in")
        client, csrf = rider_client()
        open_to("nobody")
        assert post(client, SUGGEST, body(), csrf).status_code == 403
        open_to("signed_in")
        assert post(client, SUGGEST, body()).status_code == 403  # no token
        r = post(client, SUGGEST, body(), csrf, HTTP_SEC_FETCH_SITE="cross-site")
        assert r.status_code == 403
        r = post(client, SUGGEST, body(), csrf)
        assert r.status_code == 200, r.content
        assert "Oak Street and Elm Street" in r.json()["message"]
        assert "Nothing changes on the map" in r.json()["message"]
        assert r["Cache-Control"] == "no-store"
        assert JunctionSuggestion.objects.get().lat == NODE[1]

    def test_the_endpoint_refuses_unknown_fields_and_values(self, live) -> None:
        open_to("signed_in")
        client, csrf = rider_client()
        assert post(client, SUGGEST, body(home=[1, 2]), csrf).status_code in (400, 422)
        assert post(client, SUGGEST, body(shown="purple"), csrf).status_code in (400, 422)
        r = post(client, SUGGEST, body(level=None), csrf)
        assert r.status_code == 400 and r.json()["field"] == "level"

    def test_ten_suggestions_an_hour_per_account_roads_and_junctions_together(self, live):
        open_to("signed_in")

        def attempt(n):
            client, csrf = rider_client()
            user = User.objects.latest("pk")
            key = ratelimit.client_key(f"user:{user.pk}")
            for _ in range(ratelimit.SUGGEST_WRITES.requests):
                ratelimit.hit(ratelimit.SUGGEST_WRITES, key)
            return post(client, SUGGEST, body(), csrf)

        r = in_one_window(ratelimit.SUGGEST_WRITES.window_s, attempt)
        assert ratelimit.SUGGEST_WRITES.requests == 10
        assert r.status_code == 429 and JunctionSuggestion.objects.count() == 0


@db
class TestReview:
    def test_the_list_is_the_admins_and_names_nobody(self, live) -> None:
        open_to("signed_in")
        suggest(level=None, direction="more", shown="orange")
        member, _ = rider_client()
        assert member.get(OPEN, **addr()).status_code == 403
        client, _ = admin_client()
        r = client.get(OPEN, **addr())
        assert r.status_code == 200
        (item,) = r.json()["suggestions"]
        assert item["junction"] == "Oak Street and Elm Street"
        assert (item["current_level"], item["level"], item["direction"]) == (3, 4, "more")
        assert item["words"] == "Hard: long waits or fast traffic"
        assert set(item) == {
            "id", "junction", "lat", "lon", "current_level", "current_words", "level", "words",
            "direction", "reason", "status", "created_at", "sent_at", "withdraws_avoid",
        }  # fmt: skip

    def test_approve_now_makes_a_junction_override_the_next_plan_reads(self, live) -> None:
        open_to("signed_in")
        s = suggest(level=4)
        client, csrf = admin_client()
        r = post(client, ACTION.format(s.pk, "approve"), {}, csrf)
        assert r.status_code == 200, r.content
        assert r.json()["message"] == (
            "Approved. Oak Street and Elm Street is now rated hard: long waits or fast traffic. "
            "Routes planned from now on use it."
        )
        override = JunctionOverride.objects.get()
        assert (override.level, override.active, override.name) == (
            4, True, "Oak Street and Elm Street",
        )  # fmt: skip
        (rating,) = js.approved_ratings()
        assert (rating.lon, rating.lat, rating.level) == (*NODE, 4)
        s.refresh_from_db()
        assert s.status == "approved" and s.override == override and s.decided_at
        assert AuditLogEntry.objects.filter(action="junction_suggest_approve").count() == 1
        # Delete or approve again: it is decided.
        assert post(client, ACTION.format(s.pk, "delete"), {}, csrf).status_code == 409

    def test_a_later_approval_replaces_the_earlier_rating(self, live) -> None:
        open_to("signed_in")
        client, csrf = admin_client()
        first = suggest(level=4)
        post(client, ACTION.format(first.pk, "approve"), {}, csrf)
        second = suggest(level=None, direction="less")
        assert second.current_level == 4 and second.target_level == 3
        post(client, ACTION.format(second.pk, "approve"), {}, csrf)
        assert [r.level for r in js.approved_ratings()] == [3]
        assert JunctionOverride.objects.filter(active=False).count() == 1

    def test_approving_avoid_makes_an_approved_avoid_junction(self, live) -> None:
        open_to("signed_in")
        s = suggest(level=5)
        client, csrf = admin_client()
        r = post(client, ACTION.format(s.pk, "approve"), {}, csrf)
        assert r.status_code == 200 and "now rated Avoid" in r.json()["message"]
        avoid = AvoidJunction.objects.get()
        assert avoid.approved and avoid.source == "community"
        assert avoid.suggestion_ref == f"junction suggestion {s.pk}"
        # Shown to riders: a neutral reason, never the rider's own words.
        assert avoid.reason == js.AVOID_REASON and WHY not in avoid.reason
        assert (avoid.location.x, avoid.location.y) == NODE
        assert JunctionOverride.objects.count() == 0

    def test_approving_avoid_where_it_is_already_avoid_keeps_the_one_rating(self, live) -> None:
        # Review api-3: two riders' Avoid suggestions, both approved, made two rows.
        open_to("signed_in")
        first, second = suggest(level=5), suggest(level=5)
        client, csrf = admin_client()
        for s in (first, second):
            assert post(client, ACTION.format(s.pk, "approve"), {}, csrf).status_code == 200
        avoid = AvoidJunction.objects.get()
        first.refresh_from_db()
        second.refresh_from_db()
        assert first.avoid == second.avoid == avoid and second.status == "approved"
        entry = AuditLogEntry.objects.filter(action="junction_suggest_approve").last()
        assert entry.detail == f"kept avoid junction {avoid.pk}"

    def test_approving_a_lower_level_withdraws_the_avoid_rating(self, live) -> None:
        open_to("signed_in")
        avoid = AvoidJunction.objects.create(
            name="x", location=Point(*NODE, srid=4326), reason="r", approved=True
        )
        s = suggest(level=None, direction="less")
        client, csrf = admin_client()
        # The review list says so first, so the admin can be warned before approving.
        (listed,) = client.get(OPEN, **addr()).json()["suggestions"]
        assert listed["withdraws_avoid"] == 1
        assert js.avoid_withdrawn_by(suggest(level=5, lat=LAT, lon=LON + 0.002)) == 0
        assert post(client, ACTION.format(s.pk, "approve"), {}, csrf).status_code == 200
        avoid.refresh_from_db()
        assert avoid.approved is False and avoid.approved_by is None
        assert [r.level for r in js.approved_ratings()] == [4]
        entry = AuditLogEntry.objects.get(action="junction_suggest_approve")
        assert f"avoid junction {avoid.pk}" in entry.detail

    def test_delete(self, live) -> None:
        open_to("signed_in")
        s = suggest()
        client, csrf = admin_client()
        r = post(client, ACTION.format(s.pk, "delete"), {}, csrf)
        assert r.status_code == 200 and r.json()["status"] == "deleted"
        assert JunctionOverride.objects.count() == 0
        assert post(client, ACTION.format(s.pk, "approve"), {}, csrf).status_code == 409
        assert AuditLogEntry.objects.filter(action="junction_suggest_delete").count() == 1

    def test_send_to_discord_answers_the_plain_poll_and_marks_it_sent(self, live) -> None:
        open_to("signed_in")
        s = suggest(level=None, direction="more", shown="orange", reason="Bad @everyone corner")
        client, csrf = admin_client()
        r = post(client, ACTION.format(s.pk, "discord"), {}, csrf, HTTP_HOST="testserver")
        assert r.status_code == 200, r.content
        data = r.json()
        text = data["post"]
        assert data["characters"] == len(text) <= suggestion_post.POST_MAX
        assert text.splitlines()[0] == (
            "**Is crossing Oak Street at Elm Street harder or easier than we show?**"
        )
        assert "A rider suggested it's harder than we show." in text
        assert "We currently show it as: Takes patience: you wait for a gap" in text
        assert "The rider suggested: Hard: long waits or fast traffic" in text
        assert "Where: Oak Street at Elm Street" in text
        assert "Votes help set how the junction is shown on the bike map." in text
        assert "@everyone" not in text and "LTS" not in text
        assert [o["tier"] for o in data["options"]] == [2, 3, 4, 5, None]
        s.refresh_from_db()
        assert s.status == "sent_to_discord" and s.sent_at is not None
        assert post(client, ACTION.format(s.pk, "approve"), {}, csrf).status_code == 200

    def test_a_rider_cannot_take_an_action(self, live) -> None:
        open_to("signed_in")
        s = suggest()
        client, csrf = rider_client()
        for action in ("approve", "delete", "discord"):
            assert post(client, ACTION.format(s.pk, action), {}, csrf).status_code == 403

    def test_review_actions_share_the_road_reviews_budget(self, live) -> None:
        open_to("signed_in")
        s = suggest()

        def attempt(n):
            client, csrf = admin_client()
            user = User.objects.latest("pk")
            key = ratelimit.client_key(f"user:{user.pk}")
            for _ in range(ratelimit.SUGGEST_REVIEW_WRITES.requests):
                ratelimit.hit(ratelimit.SUGGEST_REVIEW_WRITES, key)
            return post(client, ACTION.format(s.pk, "delete"), {}, csrf)

        spent = in_one_window(ratelimit.SUGGEST_REVIEW_WRITES.window_s, attempt)
        assert spent.status_code == 429


@db
class TestPrivacy:
    def test_the_post_has_no_coordinates_but_a_link_to_the_node_at_four_decimals(
        self, live
    ) -> None:
        open_to("signed_in")
        s = suggest(lat=LAT + 0.00012, lon=LON + 0.00009)
        text = js.post_for(s, "http://testserver").text
        link = re.search(r"#at=(-?\d+\.\d+),(-?\d+\.\d+)>", text)
        assert link, text
        assert link.group(1) == f"{NODE[0]:.4f}" and link.group(2) == f"{NODE[1]:.4f}"
        outside = text.replace(link.group(0), "")
        assert not re.search(r"-?\d+\.\d{3,}", outside), text

    def test_nothing_about_the_rider_is_in_the_post_or_the_list(self, live) -> None:
        open_to("signed_in")
        rider = make_user(admin=False)
        s = suggest(rider)
        text = js.post_for(s, "http://testserver").text
        assert str(rider.pk) not in re.sub(r"#at=\S+", "", text)
        for value in (getattr(rider, "username", None), getattr(rider, "discord_id", None)):
            if value:
                assert str(value) not in text
        assert "suggester" not in js.summary(s) and "suggester_user_id" not in js.summary(s)

    def test_an_unnamed_junction_is_placed_by_the_link_alone(self, live) -> None:
        with connection.cursor() as cursor:
            cursor.execute(f"UPDATE {live}.segment SET trail_name = NULL")
        open_to("signed_in")
        s = suggest()
        assert s.roads == [] and s.name == "An unnamed junction"
        text = js.post_for(s, "http://testserver").text
        assert text.splitlines()[0] == (
            "**Is this junction harder or easier to get through than we show?**"
        )
        assert "Where: A junction shown on the map link below" in text
