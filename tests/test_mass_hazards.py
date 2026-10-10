"""Rider-marked hazards on the Mass Ride map (FOLLOWUP-MASSRIDE-MAP part 3; OWNER-DECISIONS
325-327; core.mass_hazards).

"Some stretches can be marked as a caution or warning where we've had problems. ... These
hazards will be marked by riders and will be for this mode only." Two levels chosen by the
reporter with a reason (326), reviewed with the suggestions' three actions, stored by way id.
"""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest
from django.db import IntegrityError, transaction
from django.test import Client
from test_ratelimit import in_one_window
from test_stress_edits import LAT, LON, WAY, addr, make_segment, make_user, post
from test_suggestions import admin_client, cross_street, open_to, rider_client

from core import mass_hazards, ratelimit, segment_info, suggestion_post, suggestions
from core.models import AuditLogEntry, MassHazard, User

db = pytest.mark.django_db(transaction=True)

REPORT = "/api/mass-hazards"
OPEN = "/api/mass-hazards/open"
ACTION = "/api/mass-hazards/{}/{}"
WHY = "Drivers turn across the whole group here at the light."


@pytest.fixture(autouse=True)
def _columns():
    segment_info.forget_columns()
    yield
    segment_info.forget_columns()


@pytest.fixture(autouse=True)
def router(monkeypatch):
    def fake(lat, lon, costing, timeout_s=None):
        raise segment_info.RouterSilent("down")

    monkeypatch.setattr(segment_info, "locate_edges", fake)


@pytest.fixture
def live(segment_schemas):
    schema, _staging = segment_schemas
    make_segment(schema, WAY, 3, trail_name="Oak Street", map_class="road")
    cross_street(schema, 6001, "Elm Street", LON)
    cross_street(schema, 6002, "Ash Avenue", LON + 0.002)
    return schema


def body(**change) -> dict:
    return {
        "osm_way_id": WAY,
        "lat": LAT,
        "lon": LON + 0.001,
        "level": "caution",
        "reason": WHY,
        **change,
    }


def report(user=None, **change) -> MassHazard:
    user = user or make_user(admin=False)
    return mass_hazards.create(
        user,
        change.pop("way", WAY),
        change.pop("lat", LAT),
        change.pop("lon", LON + 0.001),
        change.pop("level", "caution"),
        change.pop("reason", WHY),
    )


@db
class TestReport:
    def test_a_report_waits_and_shows_nothing(self, live) -> None:
        open_to("signed_in")
        h = report(level="warning")
        assert (h.status, h.level, h.road_name, h.osm_way_id) == (
            "pending",
            "warning",
            "Oak Street",
            WAY,
        )
        assert mass_hazards.approved_layer()[0]["features"] == []
        assert AuditLogEntry.objects.filter(action="mass_hazard_report").count() == 1

    def test_nobody_by_default_and_never_an_instance_admin(self, live) -> None:
        with pytest.raises(suggestions.Forbidden):
            report()
        open_to("signed_in")
        with pytest.raises(suggestions.Forbidden):
            report(make_user())

    def test_only_caution_or_warning_with_a_reason_of_at_most_500(self, live) -> None:
        open_to("signed_in")
        with pytest.raises(suggestions.stress_edits.Invalid) as level:
            report(level="avoid")
        assert level.value.field == "level"
        with pytest.raises(suggestions.stress_edits.Invalid) as empty:
            report(reason="   ")
        assert empty.value.field == "reason"
        with pytest.raises(suggestions.stress_edits.Invalid) as long:
            report(reason="x" * 501)
        assert long.value.field == "reason"
        assert len(report(reason="x" * 500).reason) == 500

    def test_a_road_marked_avoid_takes_no_hazard(self, live) -> None:
        open_to("signed_in")
        make_segment(live, 7001, 5, lat=LAT + 0.01, map_class="road")
        with pytest.raises(suggestions.stress_edits.Invalid) as avoid:
            report(way=7001, lat=LAT + 0.01)
        assert avoid.value.code == "avoid" and "only Avoid" in avoid.value.message

    def test_one_open_report_per_rider_per_road(self, live) -> None:
        open_to("signed_in")
        rider = make_user(admin=False)
        first = report(rider)
        with pytest.raises(mass_hazards.Conflict):
            report(rider, level="warning")
        with pytest.raises(IntegrityError), transaction.atomic():
            MassHazard.objects.create(reporter=rider, osm_way_id=WAY, level="warning", reason=WHY)
        # Another rider may report the same road; once decided, this one may again.
        assert report().status == "pending"
        MassHazard.objects.filter(pk=first.pk).update(status="deleted")
        assert report(rider, level="warning").status == "pending"

    def test_at_most_open_max_waiting_per_rider(self, live) -> None:
        open_to("signed_in")
        rider = make_user(admin=False)
        for i in range(mass_hazards.OPEN_MAX):
            make_segment(live, 9000 + i, 3, lat=LAT + 0.01 * (i + 1), map_class="road")
            report(rider, way=9000 + i, lat=LAT + 0.01 * (i + 1))
        with pytest.raises(mass_hazards.Conflict) as full:
            report(rider)
        assert str(mass_hazards.OPEN_MAX) in full.value.message

    def test_the_same_level_already_on_the_map_is_refused(self, live) -> None:
        open_to("signed_in")
        mass_hazards.approve(make_user(), report().pk)
        with pytest.raises(suggestions.stress_edits.Invalid) as same:
            report()
        assert same.value.code == "same"
        assert report(level="warning").status == "pending"

    def test_the_endpoint_needs_a_session_the_setting_and_the_csrf_token(self, live) -> None:
        assert post(Client(), REPORT, body()).status_code == 401
        open_to("signed_in")
        client, csrf = rider_client()
        open_to("nobody")
        assert post(client, REPORT, body(), csrf).status_code == 403
        open_to("signed_in")
        assert post(client, REPORT, body()).status_code == 403  # no token
        r = post(client, REPORT, body(level="warning"), csrf)
        assert r.status_code == 200, r.content
        assert "Nothing changes on the Mass Ride map" in r.json()["message"]
        assert r["Cache-Control"] == "no-store"
        r = post(client, REPORT, body(osm_way_id=WAY), csrf)
        assert r.status_code == 409
        r = post(client, REPORT, body(level="bad", osm_way_id=6001), csrf)
        assert r.status_code == 400 and r.json()["field"] == "level"

    def test_the_same_ten_an_hour_as_suggestions(self, live) -> None:
        open_to("signed_in")

        def attempt(n):
            client, csrf = rider_client()
            user = User.objects.latest("pk")
            key = ratelimit.client_key(f"user:{user.pk}")
            for _ in range(ratelimit.SUGGEST_WRITES.requests):
                ratelimit.hit(ratelimit.SUGGEST_WRITES, key)
            return post(client, REPORT, body(), csrf)

        r = in_one_window(ratelimit.SUGGEST_WRITES.window_s, attempt)
        assert r.status_code == 429 and MassHazard.objects.count() == 0


@db
class TestPrivacy:
    def test_no_position_is_kept_only_the_way(self, live) -> None:
        open_to("signed_in")
        h = report(lat=LAT + 0.0001, lon=LON + 0.0003)
        fields = {f.name for f in MassHazard._meta.get_fields()}
        assert not fields & {"lat", "lon", "location", "point", "geometry"}
        assert h.osm_way_id == WAY

    def test_a_spot_more_than_98_ft_from_the_road_is_refused(self, live) -> None:
        open_to("signed_in")
        with pytest.raises(suggestions.stress_edits.Invalid) as far:
            report(lat=LAT + 0.0004)
        assert far.value.code == "off_the_road" and "98 ft (30 m)" in far.value.message
        assert MassHazard.objects.count() == 0

    def test_the_review_and_the_layer_name_nobody(self, live) -> None:
        open_to("signed_in")
        rider = make_user(admin=False)
        h = report(rider)
        client, _ = admin_client()
        (item,) = client.get(OPEN, **addr()).json()["hazards"]
        assert set(item) == {
            "id", "osm_way_id", "road", "lat", "lon", "level", "level_name", "words", "reason",
            "status", "created_at", "sent_at",
        }  # fmt: skip
        # The Show on map spot is the road piece's middle, to four decimals.
        assert (item["lat"], item["lon"]) == (round(LAT, 4), round(LON + 0.001, 4))
        mass_hazards.approve(make_user(), h.pk)
        layer = mass_hazards.approved_layer()[0]
        (feature,) = layer["features"]
        assert set(feature) == {"type", "id", "geometry", "properties"}
        assert set(feature["properties"]) == {
            "way", "level", "level_name", "words", "reason", "road",
        }  # fmt: skip
        assert "reporter" not in json.dumps(layer)

    def test_the_poll_has_no_coordinates_but_the_road_middle_link(self, live) -> None:
        open_to("signed_in")
        h = report(lat=LAT + 0.0001, lon=LON + 0.0002)
        text = mass_hazards.post_for(h, "http://testserver").text
        link = re.search(r"#at=(-?\d+\.\d+),(-?\d+\.\d+)>", text)
        assert link and link.group(1) == f"{LON + 0.001:.4f}" and link.group(2) == f"{LAT:.4f}"
        assert not re.search(r"-?\d+\.\d{3,}", text.replace(link.group(0), ""))


@db
class TestReview:
    def test_the_list_is_the_admins(self, live) -> None:
        open_to("signed_in")
        report()
        member, _ = rider_client()
        assert member.get(OPEN, **addr()).status_code == 403
        assert Client().get(OPEN, **addr()).status_code == 401

    def test_approve_now_puts_it_on_the_map_and_replaces_the_earlier_one(self, live) -> None:
        open_to("signed_in")
        first = report()
        client, csrf = admin_client()
        r = post(client, ACTION.format(first.pk, "approve"), {}, csrf)
        assert r.status_code == 200, r.content
        assert r.json()["message"] == (
            "Approved. Oak Street is marked Caution on the Mass Ride map now."
        )
        (feature,) = mass_hazards.approved_layer()[0]["features"]
        assert feature["properties"]["level"] == "caution"
        assert feature["geometry"]["type"] == "LineString"
        second = report(level="warning")
        post(client, ACTION.format(second.pk, "approve"), {}, csrf)
        first.refresh_from_db()
        assert first.status == "removed"
        (feature,) = mass_hazards.approved_layer()[0]["features"]
        assert feature["properties"]["level_name"] == "Warning"
        assert AuditLogEntry.objects.filter(action="mass_hazard_approve").count() == 2

    def test_delete_then_nothing_more(self, live) -> None:
        open_to("signed_in")
        h = report()
        client, csrf = admin_client()
        r = post(client, ACTION.format(h.pk, "delete"), {}, csrf)
        assert r.status_code == 200 and r.json()["status"] == "deleted"
        assert post(client, ACTION.format(h.pk, "approve"), {}, csrf).status_code == 409
        assert mass_hazards.approved_layer()[0]["features"] == []

    def test_send_to_discord_answers_the_plain_poll_and_marks_it_sent(self, live) -> None:
        open_to("signed_in")
        h = report(level="warning", reason="Doors open into the lane @everyone")
        client, csrf = admin_client()
        r = post(client, ACTION.format(h.pk, "discord"), {}, csrf, HTTP_HOST="testserver")
        assert r.status_code == 200, r.content
        data = r.json()
        text = data["post"]
        assert data["characters"] == len(text) <= 2000
        assert text.splitlines()[0] == (
            "**Should the Mass Ride map warn big group rides about Oak Street, between Elm "
            "Street and Ash Avenue?**"
        )
        assert 'A rider asked us to mark it "Warning" for mass rides.' in text
        assert "@everyone" not in text and "LTS" not in text
        assert [o["level"] for o in data["options"]] == ["warning", "caution", "none", None]
        h.refresh_from_db()
        assert h.status == "sent_to_discord" and h.sent_at is not None
        assert post(client, ACTION.format(h.pk, "approve"), {}, csrf).status_code == 200

    def test_a_rider_cannot_take_an_action(self, live) -> None:
        open_to("signed_in")
        h = report()
        client, csrf = rider_client()
        for action in ("approve", "delete", "discord"):
            assert post(client, ACTION.format(h.pk, action), {}, csrf).status_code == 403

    def test_remove_takes_it_off_the_map_audited(self, live) -> None:
        open_to("signed_in")
        admin = make_user()
        h = mass_hazards.approve(admin, report().pk)
        mass_hazards.remove(admin, h.pk)
        assert mass_hazards.approved_layer()[0]["features"] == []
        assert AuditLogEntry.objects.filter(action="mass_hazard_remove").count() == 1
        with pytest.raises(mass_hazards.Conflict):
            mass_hazards.remove(admin, h.pk)


@db
class TestLayer:
    def test_public_cacheable_with_an_etag_and_a_304(self, live) -> None:
        open_to("signed_in")
        mass_hazards.approve(make_user(), report().pk)
        client = Client()
        r = client.get(REPORT, **addr())
        assert r.status_code == 200 and r["Cache-Control"] == "public, max-age=60"
        assert r["Content-Type"] == "application/geo+json"
        assert len(r.json()["features"]) == 1
        again = client.get(REPORT, HTTP_IF_NONE_MATCH=r["ETag"], **addr())
        assert again.status_code == 304 and again["ETag"] == r["ETag"]
        assert client.get(REPORT, HTTP_SEC_FETCH_SITE="cross-site", **addr()).status_code == 403

    def test_the_layer_starts_empty(self, live) -> None:
        r = Client().get(REPORT, **addr())
        assert r.status_code == 200 and r.json() == {"type": "FeatureCollection", "features": []}

    def test_a_piece_marked_avoid_after_approval_leaves_the_layer(self, live) -> None:
        open_to("signed_in")
        mass_hazards.approve(make_user(), report().pk)
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {live}.segment SET stress_tier = 5 WHERE osm_way_id = %s", [WAY]
            )
        assert mass_hazards.approved_layer()[0]["features"] == []


class TestAlong:
    """The hazards a Mass Ride's route passes, in riding order (no database)."""

    @staticmethod
    def hazard(level="caution", reason=WHY, road="Oak Street"):
        return SimpleNamespace(
            level=level,
            reason=reason,
            road_name=road,
            get_level_display=lambda: level.capitalize(),
        )

    def test_riding_order_merged_pieces_and_avoid_left_out(self) -> None:
        piece = lambda way, m: SimpleNamespace(way_id=way, metres=m)  # noqa: E731
        pieces = [piece(1, 100), piece(2, 50), piece(2, 50), piece(3, 30), piece(4, 20)]
        classes = [("2", "none"), ("3", "none"), ("3", "none"), ("5", "none"), ("2", "none")]
        found = {2: self.hazard("warning"), 3: self.hazard(), 4: self.hazard(road="Elm")}
        out = mass_hazards.along([(0, 5)], pieces, classes, found)
        assert [(h["from_m"], h["to_m"], h["level"], h["road"]) for h in out] == [
            (100, 200, "warning", "Oak Street"),
            (230, 250, "caution", "Elm"),
        ]
        assert out[0]["words"] == mass_hazards.LEVEL_WORDS["warning"]

    def test_an_untraced_leg_counts_its_length_and_none_is_empty(self) -> None:
        piece = SimpleNamespace(way_id=2, metres=40)
        out = mass_hazards.along([500.0, (0, 1)], [piece], [("2", "none")], {2: self.hazard()})
        assert (out[0]["from_m"], out[0]["to_m"]) == (500, 540)
        assert mass_hazards.along([(0, 1)], [piece], [("2", "none")], {}) == []


class TestPoll:
    def test_the_hazard_poll_is_plain_and_short(self) -> None:
        post_ = suggestion_post.build_hazard(
            road="Oak Street",
            level="caution",
            reason="x" * 3000,
            map_url="https://example.org/#at=-77.0300,38.8990",
        )
        assert len(post_.text) <= suggestion_post.POST_MAX
        assert "The rider suggested: Caution: a big group should take care here" in post_.text
        assert "Where: Oak Street, shown on the map link below" in post_.text
        assert suggestion_post.level_for_vote(post_.options, "c") == "none"
        assert suggestion_post.level_for_vote(post_.options, "D") is None

    def test_an_unknown_level_is_a_programming_error(self) -> None:
        with pytest.raises(ValueError):
            suggestion_post.build_hazard(road=None, level="avoid", reason="", map_url="x")


@db
class TestRouteAnswer:
    """A Mass Ride's answer names the approved hazards it passes; no other ride type's does
    (325: "for this mode only")."""

    @pytest.fixture
    def planned(self, monkeypatch, segment_schemas):
        from test_avoid_junctions import PlanRouter, body_for
        from test_route_api import post as plan

        from core import routing

        monkeypatch.setattr(routing, "_transport", PlanRouter(detour_cost=600.0))
        return lambda preset: plan(Client(), body_for(preset)).json()

    def test_empty_on_a_mass_ride_with_none_and_null_elsewhere(self, planned) -> None:
        assert planned("mass-ride")["mass_hazards"] == []
        assert planned("default")["mass_hazards"] is None

    def test_a_mass_ride_names_the_hazard_in_riding_order(self, planned) -> None:
        # The fake router's trace rides way 101 the whole way.
        MassHazard.objects.create(
            osm_way_id=101, road_name="Oak Street", level="warning", reason=WHY, status="approved"
        )
        (hazard,) = planned("mass-ride")["mass_hazards"]
        assert hazard["level"] == "warning" and hazard["level_name"] == "Warning"
        assert hazard["from_m"] == 0 and hazard["to_m"] > 0 and hazard["reason"] == WHY
        assert planned("default")["mass_hazards"] is None
        # A report not yet approved is not on any route.
        MassHazard.objects.update(status="pending")
        assert planned("mass-ride")["mass_hazards"] == []
