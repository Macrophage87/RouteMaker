"""POST /api/route's sliders, ride time and facility breakdown (PUBLIC-DIALS).

The owner, 2026-09-27: sliders for traffic stress and hilliness on every ride
type, three ride-time settings, the four facility classes, and Cargo Bike.
The router is the same fake as tests/test_route_api.py's; the segment table is
real, because the breakdown is a PostGIS join.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from django.conf import settings
from django.db import connection
from test_route_api import (
    VERTICES,
    FakeRouter,
    clock,  # noqa: F401, F811 - a fixture, used by name
    good_body,
    post,
    route_answer,
    standard_router,
    timed,
    trace_answer,
)

from core import presets, routing
from routemaker import ridetime

# A route test plans a weekday ride unless it says otherwise: the weekend router
# is chosen by the day the suite runs on (conftest `weekday_clock`).
pytestmark = pytest.mark.usefixtures("weekday_clock")


db = pytest.mark.django_db(transaction=True)

FACILITY_KEYS = {"path", "protected", "lane", "none", "unknown"}


@pytest.fixture
def router(monkeypatch):
    def install(fake: FakeRouter) -> FakeRouter:
        monkeypatch.setattr(routing, "_transport", fake)
        return fake

    return install


@pytest.fixture
def facility_segments(segment_schemas):
    """Way 101 a path; way 202 a painted lane, then a road closed to cars at weekends."""
    live, _staging = segment_schemas
    rows = [
        (101, 0, 1, VERTICES[0:2], "path", []),
        (202, 0, 3, VERTICES[1:3], "lane", []),
        (202, 1, 2, VERTICES[2:4], "none", ["weekend"]),
    ]
    with connection.cursor() as cursor:
        for way, ordinal, tier, line, facility, when in rows:
            wkt = "LINESTRING(" + ", ".join(f"{lon} {lat}" for lon, lat in line) + ")"
            cursor.execute(
                f"INSERT INTO {live}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                "stress_rule, facility, car_free_when) "
                "VALUES (%s, %s, ST_GeomFromText(%s, 4326), %s, 'test', %s, %s::text[])",
                [way, ordinal, wkt, tier, facility, when],
            )
    return live


def sent_options(fake: FakeRouter) -> dict:
    return fake.calls[0][1]["costing_options"]["bicycle"]


@db
class TestTheSlidersReachTheRouter:
    @pytest.mark.parametrize("name", sorted(presets.PRESETS))
    def test_absent_dials_are_the_presets_start(self, name, client, facility_segments, router):
        fake = router(standard_router())
        body = post(client, good_body(name)).json()
        start = presets.PRESETS[name]
        assert body["dials"]["stress"] == presets.stress_start(name)
        assert body["dials"]["hills"] == start.hills
        assert sent_options(fake)["use_roads"] == presets.use_roads_for(presets.stress_start(name))
        assert sent_options(fake)["use_hills"] == presets.use_hills_for(start.hills)

    @pytest.mark.parametrize("name", sorted(set(presets.PRESETS) - {"mass-ride"}))
    @pytest.mark.parametrize(("stress", "use_roads"), [(0, 1.0), (35, 0.55), (70, 0.1), (100, 0.0)])
    def test_stress_is_use_roads_run_backwards(
        self, name, stress, use_roads, client, facility_segments, router
    ):
        fake = router(standard_router())
        response = post(client, {**good_body(name), "stress": stress})
        assert response.status_code == 200
        assert all(p["costing_options"]["bicycle"]["use_roads"] == use_roads for _, p in fake.calls)
        assert response.json()["dials"]["stress"] == stress

    @pytest.mark.parametrize(("hills", "use_hills"), [(-100, 0.0), (-50, 0.5), (0, 1.0)])
    def test_hills_below_the_detent_is_use_hills(
        self, hills, use_hills, client, facility_segments, router
    ):
        fake = router(standard_router())
        assert post(client, {**good_body(), "hills": hills}).status_code == 200
        assert sent_options(fake)["use_hills"] == use_hills
        # Below the detent the alternatives are weighed for sustained grades.
        assert ("alternates" in fake.calls[0][1]) == (hills < 0)

    def test_more_stress_never_means_more_use_roads(self):
        values = [presets.use_roads_for(s) for s in range(0, 101, 5)]
        assert values == sorted(values, reverse=True)
        values = [presets.use_hills_for(h) for h in range(-100, 1, 5)]
        assert values == sorted(values)

    def test_the_other_dials_are_the_presets(self, client, facility_segments, router):
        fake = router(standard_router())
        post(client, {**good_body("group-ride"), "stress": 10, "hills": -10})
        expected = presets.costing("group-ride", 10, -10)["bicycle"]
        assert sent_options(fake) == expected
        # The preset's own table is not retuned by a request.
        assert presets.PRESETS["group-ride"].costing_options["use_roads"] == presets.use_roads_for(
            40
        )

    def test_carrying_people_starts_the_stress_slider_higher(
        self, client, facility_segments, router
    ):
        fake = router(standard_router())
        body = post(client, {**good_body("cargo"), "carrying": "people"}).json()
        assert body["dials"]["carrying"] == "people"
        assert body["dials"]["stress"] == presets.CARGO_CARRYING_STRESS["people"]
        assert body["dials"]["stress"] > presets.CARGO_CARRYING_STRESS["cargo"]
        assert sent_options(fake)["use_roads"] < presets.use_roads_for(presets.DEFAULT_STRESS)
        # The slider still moves from there.
        router(standard_router())
        moved = post(client, {**good_body("cargo"), "carrying": "people", "stress": 20}).json()
        assert moved["dials"]["stress"] == 20

    def test_cargo_defaults_to_carrying_cargo(self, client, facility_segments, router):
        router(standard_router())
        assert post(client, good_body("cargo")).json()["dials"]["carrying"] == "cargo"
        router(standard_router())
        assert post(client, good_body("default")).json()["dials"]["carrying"] is None


@db
class TestRefusedDials:
    @pytest.mark.parametrize(
        "extra",
        [
            {"stress": 101},
            {"stress": -1},
            {"stress": 50.5},
            {"stress": "50"},
            {"stress": True},
            {"hills": 101},
            {"hills": -101},
            {"hills": None, "stress": [1]},
            {"when": "someday"},
            {"when": "Weekend"},
            {"carrying": "goats"},
            {"carrying": "people"},
            {"hills": "50"},
            {"hills": 20.0},
            {"hills": True},
        ],
    )
    def test_bad_dials_are_a_400_before_the_router(self, extra, client, facility_segments, router):
        fake = router(standard_router())
        response = post(client, {**good_body("default"), **extra})
        assert response.status_code == 400
        assert "error" in response.json()
        assert fake.calls == []

    @pytest.mark.parametrize("carrying", ["goats", "Cargo", "", 1])
    def test_a_load_cargo_bike_has_no_start_for_is_a_400(
        self, carrying, client, facility_segments, router
    ):
        """On the ride type that does carry, not only on one that does not:
        with the type loosened this reached `preset.carrying[...]` and was a
        500 (mutation review r1, A11)."""
        fake = router(standard_router())
        response = post(client, {**good_body("cargo"), "carrying": carrying})
        assert response.status_code == 400
        assert "error" in response.json()
        assert fake.calls == []

    def test_mass_ride_does_not_seek_climbs(self, client, facility_segments, router):
        fake = router(standard_router())
        response = post(client, {**good_body("mass-ride"), "hills": 1})
        assert response.status_code == 400
        assert fake.calls == []
        router(standard_router())
        assert post(client, {**good_body("mass-ride"), "hills": 0}).status_code == 200


@db
class TestRideTime:
    @pytest.mark.parametrize("when", ridetime.WHENS)
    def test_the_router_is_told_the_settings_time(self, when, client, facility_segments, router):
        fake = router(standard_router())
        body = post(client, {**good_body(), "when": when}).json()
        assert body["dials"]["when"] == when
        assert fake.calls[0][1]["date_time"] == {
            "type": 3,
            "value": routing.planning_time(when=when),
        }

    def test_absent_is_the_moment_the_plan_is_made(self, client, facility_segments, router):
        fake = router(standard_router())
        body = post(client, good_body()).json()
        assert body["dials"]["when"] == routing.default_when()
        assert fake.calls[0][1]["date_time"]["value"] == routing.planning_time(
            when=routing.default_when()
        )

    @pytest.mark.parametrize(
        ("now", "when", "told"),
        [
            # 08:30 in Washington on Tuesday 29 September: morning rush.
            (datetime(2026, 9, 29, 12, 30, tzinfo=UTC), "weekday_rush", "2026-10-06T08:00"),
            # 22:00 on Friday 2 October there, Saturday already in UTC.
            (datetime(2026, 10, 3, 2, 0, tzinfo=UTC), "weekday_offpeak", "2026-10-06T12:00"),
            # Saturday noon there.
            (datetime(2026, 10, 3, 16, 0, tzinfo=UTC), "weekend", "2026-10-10T09:00"),
        ],
    )
    def test_absent_is_the_setting_of_the_clock_in_washington(
        self, client, facility_segments, router, monkeypatch, now, when, told
    ):
        """Pinned to a clock, not to `default_when()` itself, which a test
        cannot fail against (mutation review r1, R9 and RT21)."""
        monkeypatch.setattr(routing.timezone, "now", lambda: now)
        fake = router(standard_router())
        body = post(client, good_body()).json()
        assert body["dials"]["when"] == when
        assert fake.calls[0][1]["date_time"]["value"] == told


@db
class TestFacilityBreakdown:
    def test_the_breakdown_sums_to_the_traced_length(self, client, facility_segments, router):
        router(standard_router())
        body = post(client, {**good_body(), "when": "weekday_rush"}).json()
        facility = body["facility_m"]
        assert set(facility) == FACILITY_KEYS
        assert sum(facility.values()) == pytest.approx(sum(body["stress_m"].values()))
        # Way 101: 900 m of path; way 202 400 m lane and 400 m street; 303 unknown.
        assert facility == pytest.approx(
            {"path": 900.0, "protected": 0.0, "lane": 400.0, "none": 400.0, "unknown": 500.0}
        )

    def test_a_weekend_closure_is_a_path_only_at_the_weekend(
        self, client, facility_segments, router
    ):
        router(standard_router())
        weekend = post(client, {**good_body(), "when": "weekend"}).json()["facility_m"]
        router(standard_router())
        offpeak = post(client, {**good_body(), "when": "weekday_offpeak"}).json()["facility_m"]
        assert weekend["path"] - offpeak["path"] == pytest.approx(400.0)
        assert offpeak["none"] - weekend["none"] == pytest.approx(400.0)

    def test_a_weekend_closure_is_tier_1_only_at_the_weekend(
        self, client, facility_segments, router
    ):
        """Way 202's second segment is tier 2 with cars on it and closed to
        them at the weekend, when it is what the weekend graph routes it as."""
        router(standard_router())
        weekend = post(client, {**good_body(), "when": "weekend"}).json()["stress_m"]
        router(standard_router())
        weekday = post(client, {**good_body(), "when": "weekday_rush"}).json()["stress_m"]
        assert weekend["1"] - weekday["1"] == pytest.approx(400.0)
        assert weekday["2"] - weekend["2"] == pytest.approx(400.0)
        assert sum(weekend.values()) == pytest.approx(sum(weekday.values()))

    def test_a_live_schema_without_the_columns_is_all_unknown(
        self, client, facility_segments, router, monkeypatch
    ):
        with connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE {facility_segments}.segment DROP COLUMN car_free_when")
            cursor.execute(f"ALTER TABLE {facility_segments}.segment DROP COLUMN facility")
        monkeypatch.setattr(routing, "_facility_columns_seen", False)
        router(standard_router())
        body = post(client, good_body()).json()
        assert body["facility_m"]["unknown"] == pytest.approx(sum(body["stress_m"].values()))
        assert body["stress_m"]["3"] == pytest.approx(400.0)


def _trip(vertices, length_km, elevations):
    return route_answer([(vertices, length_km, elevations)])["trip"]


FLAT = [10.0, 10.0, 10.0, 10.0]
HILLY = [10.0, 40.0, 10.0, 60.0]
STEEPEST = [10.0, 90.0, 10.0, 120.0]


def seeking_router(alternates) -> FakeRouter:
    return FakeRouter(
        {
            "route": {
                "trip": _trip(VERTICES, 2.0, FLAT),
                "alternates": [{"trip": _trip(VERTICES, km, elev)} for km, elev in alternates],
            },
            "trace_attributes": trace_answer(VERTICES, [(101, 0, 4, 2.0)]),
        }
    )


@db
class TestSeekingClimbs:
    def test_past_the_detent_the_router_is_asked_for_alternatives(
        self, client, facility_segments, router
    ):
        fake = router(seeking_router([(2.2, HILLY)]))
        body = post(client, {**good_body(), "hills": 60}).json()
        request = fake.calls[0][1]
        assert request["alternates"] == routing.SEEK_ALTERNATES
        assert request["costing_options"]["bicycle"]["use_hills"] == 1.0
        assert body["hills_seek"]["candidates"] == 2
        assert body["hills_seek"]["chosen"] == 1
        assert body["hills_seek"]["extra_climb_m"] > 0
        assert body["distance_m"] == pytest.approx(2200.0)

    def test_the_budget_binds(self, client, facility_segments, router):
        # At 60 the budget is 1.3 times the direct route: 2.8 km is past it.
        router(seeking_router([(2.8, STEEPEST), (2.4, HILLY)]))
        body = post(client, {**good_body(), "hills": 60}).json()
        assert body["hills_seek"]["chosen"] == 2
        router(seeking_router([(2.8, STEEPEST), (2.4, HILLY)]))
        body = post(client, {**good_body(), "hills": 100}).json()
        assert body["hills_seek"]["chosen"] == 1

    def test_the_extra_climb_is_over_the_direct_routes_own(self, client, facility_segments, router):
        """RT9: on a direct route that climbs too, what is reported is the
        difference, not the chosen route's whole climb."""
        direct, hilly = _trip(VERTICES, 2.0, HILLY), _trip(VERTICES, 2.2, STEEPEST)
        router(
            FakeRouter(
                {
                    "route": {"trip": direct, "alternates": [{"trip": hilly}]},
                    "trace_attributes": trace_answer(VERTICES, [(101, 0, 4, 2.0)]),
                }
            )
        )
        body = post(client, {**good_body(), "hills": 100}).json()
        assert body["hills_seek"]["chosen"] == 1
        assert routing._climb_of(direct) > 0
        assert body["hills_seek"]["extra_climb_m"] == pytest.approx(
            routing._climb_of(hilly) - routing._climb_of(direct), abs=0.1
        )

    def test_the_search_asks_for_every_alternative_the_routers_allow(self):
        """RT3: the routers' `max_alternates`, in every variant's config."""
        import json
        from pathlib import Path

        configs = sorted((Path(settings.BASE_DIR) / "valhalla").glob("valhalla-*.json"))
        assert len(configs) == 5
        for path in configs:
            limits = json.loads(path.read_text())["service_limits"]
            assert routing.SEEK_ALTERNATES == limits["max_alternates"], path.name

    def test_nothing_climbs_more_keeps_the_direct_route(self, client, facility_segments, router):
        router(seeking_router([(2.1, FLAT)]))
        body = post(client, {**good_body(), "hills": 100}).json()
        assert body["hills_seek"]["chosen"] == 0
        assert body["hills_seek"]["extra_climb_m"] == 0

    def test_at_or_below_the_detent_there_is_no_search(self, client, facility_segments, router):
        router(standard_router())
        assert post(client, {**good_body(), "hills": 0}).json()["hills_seek"] is None

    def test_a_via_point_keeps_the_direct_route_and_says_why(
        self, client, facility_segments, router
    ):
        fake = router(standard_router())
        points = [list(VERTICES[0]), list(VERTICES[2]), list(VERTICES[-1])]
        body = post(client, {"points": points, "preset": "default", "hills": 50}).json()
        assert "alternates" not in fake.calls[0][1]
        assert body["hills_seek"]["limited"] == "two_points"
        assert body["hills_seek"]["chosen"] == 0

    def test_a_long_ride_does_not_search(self, facility_segments, router):
        fake = router(standard_router())
        points = [list(VERTICES[0]), list(VERTICES[-1])]
        body = routing.plan(points, "default", long_ride=True, dials=routing.Dials(hills=50))
        assert "alternates" not in fake.calls[0][1]
        assert body["hills_seek"]["limited"] == "long_ride"


@db
def test_a_span_past_the_search_limit_does_not_search(facility_segments, router):
    fake = router(standard_router())
    far = [[-77.05, 38.9], [-77.05 + 0.6, 38.9]]  # about 52 km of straight line
    assert (
        routing.haversine(routing.Point(*far[0]), routing.Point(*far[1])) > routing.SEEK_MAX_SPAN_M
    )
    body = routing.plan(far, "default", dials=routing.Dials(hills=50))
    assert "alternates" not in fake.calls[0][1]
    assert body["hills_seek"]["limited"] == "long_ride"
    near = [[-77.05, 38.9], [-77.05 + 0.5, 38.9]]  # about 43 km
    fake = router(seeking_router([(2.2, HILLY)]))
    routing.plan(near, "default", dials=routing.Dials(hills=50))
    assert fake.calls[0][1]["alternates"] == routing.SEEK_ALTERNATES


def test_choose_climb_prefers_the_first_on_a_tie():
    trips = [_trip(VERTICES, 2.0, HILLY), _trip(VERTICES, 2.0, HILLY)]
    assert routing.choose_climb(trips, 1.5) == 0


@pytest.mark.parametrize("hills", [1, 50, 100])
def test_the_distance_budget_grows_with_the_slider(hills):
    assert presets.seek_distance_ratio(hills) > presets.seek_distance_ratio(hills - 1)
    assert presets.seek_distance_ratio(100) == pytest.approx(1.5)
    assert presets.seek_distance_ratio(0) == 1.0


@db
class TestTheWeekendGraph:
    """The owner's "Build the weekend graph" (2026-09-27)."""

    @pytest.mark.parametrize("name", sorted(presets.PRESETS))
    def test_a_weekend_ride_on_the_standard_graph_takes_its_twin(
        self, name, client, facility_segments, router
    ):
        fake = router(standard_router())
        body = post(client, {**good_body(name), "when": "weekend"}).json()
        expected = (
            "weekend"
            if presets.PRESETS[name].variant == "standard"
            else presets.PRESETS[name].variant
        )
        if name in presets.OFFROAD_PRESETS:
            expected = "offroad"
        assert body["variant"] == expected
        base = settings.VALHALLA_UPSTREAMS[expected]
        assert all(url.startswith(base + "/") for url, _ in fake.calls)

    @pytest.mark.parametrize("when", ["weekday_rush", "weekday_offpeak"])
    def test_a_weekday_ride_stays_on_the_standard_graph(
        self, when, client, facility_segments, router
    ):
        fake = router(standard_router())
        body = post(client, {**good_body(), "when": when}).json()
        assert body["variant"] == "standard"
        assert all("valhalla-weekend" not in url for url, _ in fake.calls)

    def test_a_weekend_router_that_does_not_answer_falls_back_to_standard(
        self, client, facility_segments, router
    ):
        standard = standard_router()

        def transport(url, payload, timeout):
            if url.startswith(settings.VALHALLA_UPSTREAMS["weekend"]):
                raise routing.RouterUnavailable("connection refused")
            return standard(url, payload, timeout)

        router(transport)
        response = post(client, {**good_body(), "when": "weekend"})
        assert response.status_code == 200
        assert response.json()["variant"] == "standard"
        assert all(
            url.startswith(settings.VALHALLA_UPSTREAMS["standard"]) for url, _ in standard.calls
        )

    def test_a_weekend_router_with_no_tiles_falls_back_to_standard(
        self, client, facility_segments, router
    ):
        """OPS review, 2026-09-28: after a rollback withdrew the weekend graph,
        or before its first promotion, the router is up on an empty directory
        and answers 171 "No suitable edges near location"."""
        standard = standard_router()
        weekend_calls = []

        def transport(url, payload, timeout):
            if url.startswith(settings.VALHALLA_UPSTREAMS["weekend"]):
                weekend_calls.append(url)
                raise routing.RouterRefused(400, 171, "No suitable edges near location")
            return standard(url, payload, timeout)

        router(transport)
        response = post(client, {**good_body(), "when": "weekend"})
        assert response.status_code == 200
        assert response.json()["variant"] == "standard"
        assert len(weekend_calls) == 1
        post(client, {**good_body(), "when": "weekend"})
        assert len(weekend_calls) == 1, "remembered as down for a minute"

    def test_a_point_neither_graph_can_place_is_still_no_route(
        self, client, facility_segments, router
    ):
        weekend_calls = []

        def transport(url, payload, timeout):
            if url.startswith(settings.VALHALLA_UPSTREAMS["weekend"]):
                weekend_calls.append(url)
            raise routing.RouterRefused(400, 171, "No suitable edges near location")

        router(transport)
        response = post(client, {**good_body(), "when": "weekend"})
        assert response.status_code != 200
        assert "error" in response.json()
        assert routing._weekend_failed_at is None, "a real refusal is not a missing graph"
        post(client, {**good_body(), "when": "weekend"})
        assert len(weekend_calls) == 2, "so the weekend graph is asked again"

    def test_a_real_no_path_on_the_weekend_graph_is_not_masked(
        self, client, facility_segments, router
    ):
        """442 (no path) is the graph's answer, not a missing graph: reported,
        and the standard graph is not asked in its place."""
        calls = []

        def transport(url, payload, timeout):
            calls.append(url)
            raise routing.RouterRefused(400, 442, "No path could be found for input")

        router(transport)
        response = post(client, {**good_body(), "when": "weekend"})
        assert response.status_code != 200
        assert all(url.startswith(settings.VALHALLA_UPSTREAMS["weekend"]) for url in calls)

    def test_no_weekend_settings_row_plans_on_standard(
        self, client, facility_segments, router, weekend_rows_read
    ):
        """A deployment before its first four-graph promotion, or after a
        rollback withdrew the weekend graph, has no weekend row."""
        from core.models import ValhallaUpstream

        ValhallaUpstream.objects.filter(variant="weekend").delete()
        fake = router(standard_router())
        body = post(client, {**good_body(), "when": "weekend"}).json()
        assert body["variant"] == "standard"
        assert all(url.startswith(settings.VALHALLA_UPSTREAMS["standard"]) for url, _ in fake.calls)
        # A row naming no build is no promotion either.
        ValhallaUpstream.objects.create(variant="weekend", url="http://valhalla-weekend:8002")
        fake = router(standard_router())
        assert post(client, {**good_body(), "when": "weekend"}).json()["variant"] == "standard"
        # And once a weekend build is promoted, its row sends the ride there.
        ValhallaUpstream.objects.filter(variant="weekend").update(build_id="20260917T080000Z")
        fake = router(standard_router())
        assert post(client, {**good_body(), "when": "weekend"}).json()["variant"] == "weekend"

    def test_a_failed_weekend_router_is_not_asked_again_for_a_minute(
        self, client, facility_segments, router, monkeypatch
    ):
        """Between the deploy and `up -d valhalla-weekend`, or with the weekend
        router hung, every weekend ride paid the failure (2.5-35 s). It is
        remembered for WEEKEND_FAILURE_TTL_S."""
        weekend_calls = []
        standard = standard_router()

        def transport(url, payload, timeout):
            if url.startswith(settings.VALHALLA_UPSTREAMS["weekend"]):
                weekend_calls.append(timeout)
                raise routing.RouterUnavailable("connection refused")
            return standard(url, payload, timeout)

        now = [1000.0]
        monkeypatch.setattr(routing, "clock", lambda: now[0])
        router(transport)
        assert post(client, {**good_body(), "when": "weekend"}).json()["variant"] == "standard"
        assert len(weekend_calls) == 1
        assert weekend_calls[0] <= routing.WEEKEND_TIMEOUT_S, "a hung one is cut short"
        now[0] += routing.WEEKEND_FAILURE_TTL_S - 1
        assert post(client, {**good_body(), "when": "weekend"}).json()["variant"] == "standard"
        assert len(weekend_calls) == 1, "not asked again inside the minute"
        now[0] += 2
        post(client, {**good_body(), "when": "weekend"})
        assert len(weekend_calls) == 2, "and asked again after it"

    def test_a_standard_router_that_does_not_answer_is_still_a_502(
        self, client, facility_segments, router
    ):
        def transport(url, payload, timeout):
            raise routing.RouterUnavailable("down")

        router(transport)
        assert post(client, {**good_body(), "when": "weekday_rush"}).status_code == 502
        assert post(client, {**good_body(), "when": "weekend"}).status_code == 502


@db
class TestMassRideStress:
    """The owner's "Lock at 0 (Recommended)" for Mass Ride's stress slider."""

    def test_mass_ride_refuses_any_stress_above_zero(self, client, facility_segments, router):
        fake = router(standard_router())
        assert post(client, {**good_body("mass-ride"), "stress": 1}).status_code == 400
        assert fake.calls == []
        router(standard_router())
        assert post(client, {**good_body("mass-ride"), "stress": 0}).status_code == 200

    def test_only_mass_ride_is_locked(self):
        assert {n for n, p in presets.PRESETS.items() if p.stress_max < presets.STRESS_MAX} == {
            "mass-ride"
        }


@db
class TestCargoAssist:
    def test_assist_takes_the_ebike_graph_and_a_faster_pace(
        self, client, facility_segments, router
    ):
        fake = router(standard_router())
        body = post(client, {**good_body("cargo"), "assist": True, "when": "weekend"}).json()
        assert body["variant"] == "ebike"
        assert body["dials"]["assist"] is True
        options = sent_options(fake)
        assert options["cycling_speed"] > presets.CARGO_PLANNING_SPEED_KMH
        assert all(url.startswith(settings.VALHALLA_UPSTREAMS["ebike"]) for url, _ in fake.calls)

    def test_assist_keeps_cargos_hill_averse_start(self, client, facility_segments, router):
        fake = router(standard_router())
        body = post(client, {**good_body("cargo"), "assist": True}).json()
        assert body["dials"]["hills"] == presets.CARGO_HILLS
        assert sent_options(fake)["use_hills"] == presets.use_hills_for(presets.CARGO_HILLS)

    def test_without_assist_cargo_is_unchanged(self, client, facility_segments, router):
        fake = router(standard_router())
        body = post(client, {**good_body("cargo"), "when": "weekday_rush"}).json()
        assert body["variant"] == "standard"
        assert body["dials"]["assist"] is False
        assert sent_options(fake)["cycling_speed"] == presets.CARGO_PLANNING_SPEED_KMH

    @pytest.mark.parametrize("extra", [{"assist": 1}, {"assist": "yes"}])
    def test_assist_must_be_a_boolean(self, extra, client, facility_segments, router):
        router(standard_router())
        assert post(client, {**good_body("cargo"), **extra}).status_code == 400

    def test_assist_is_cargo_only(self, client, facility_segments, router):
        fake = router(standard_router())
        assert post(client, {**good_body("default"), "assist": True}).status_code == 400
        assert fake.calls == []


@db
def test_legal_but_avoid_is_its_own_key_and_the_sum_is_the_distance(
    client, facility_segments, router
):
    """Way 303 had no segment row; as tier 5 its 500 m are "5", not "unknown"."""
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {facility_segments}.segment (osm_way_id, ordinal, geometry, stress_tier, "
            "stress_rule, facility) VALUES (303, 0, ST_GeomFromText(%s, 4326), 5, 'test', 'none')",
            ["LINESTRING(" + ", ".join(f"{lon} {lat}" for lon, lat in VERTICES[3:5]) + ")"],
        )
    router(standard_router())
    stress = post(client, {**good_body(), "when": "weekday_rush"}).json()["stress_m"]
    assert stress["5"] == pytest.approx(500.0)
    assert stress["unknown"] == pytest.approx(0.0)
    assert sum(stress.values()) == pytest.approx(2200.0)


@pytest.mark.parametrize("name", sorted(presets.PRESETS))
def test_every_preset_charges_entering_a_legal_but_avoid_way(name):
    """The alley penalty is how tier 5 reaches every preset, Mass Ride at
    use_roads 1.0 included (core.presets.AVOID_ENTRY_PENALTY_S), and
    destination-only ways keep Valhalla's own penalty: none is sent."""
    options = presets.costing(name)["bicycle"]
    assert options["alley_penalty"] == presets.AVOID_ENTRY_PENALTY_S
    assert presets.AVOID_ENTRY_PENALTY_S >= 15 * 60
    assert "destination_only_penalty" not in options
    assert "service_penalty" not in options


WHY = ("direction", "category", "public_note", "display")


@db
class TestTheStressAdjustmentsARouteUses:
    """The owner, 2026-09-27: "Only provide the warnings if the route goes over
    the road." The answer names the adjustments the traced route rides over,
    with the why only where the segment table carries it."""

    def mark(self, live, way, ordinal, **columns) -> None:
        sets = ", ".join(f"{name} = %s" for name in columns)
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {live}.segment SET {sets} WHERE osm_way_id = %s AND ordinal = %s",
                [*columns.values(), way, ordinal],
            )

    def test_a_route_over_no_adjustment_has_none(self, client, facility_segments, router):
        router(standard_router())
        assert post(client, good_body()).json()["stress_adjustments"] == []

    def test_a_public_approved_adjustment_carries_its_note(self, client, facility_segments, router):
        self.mark(
            facility_segments,
            202,
            0,
            stress_adjustment_id="a-stretch",
            stress_computed_tier=2,
            stress_adjustment_direction="up",
            stress_adjustment_category="sightlines",
            stress_adjustment_note="Off-ramp traffic merges in at a blind corner.",
            stress_adjustment_display="route_only",
        )
        router(standard_router())
        (used,) = post(client, good_body()).json()["stress_adjustments"]
        assert used == {
            "adjustment_id": "a-stretch",
            "tier": 3,
            "adjusted": True,
            "length_m": pytest.approx(used["length_m"]),
            "direction": "up",
            "category": "sightlines",
            "public_note": "Off-ramp traffic merges in at a blind corner.",
            "display": "route_only",
        }
        assert used["length_m"] > 0

    def test_a_hidden_adjustment_is_only_adjusted(self, client, facility_segments, router):
        self.mark(facility_segments, 101, 0, stress_adjustment_id="quiet-one")
        self.mark(facility_segments, 202, 1, stress_adjustment_id="quiet-two")
        router(standard_router())
        used = post(client, good_body()).json()["stress_adjustments"]
        assert [u["adjustment_id"] for u in used] == ["quiet-one", "quiet-two"], "route order"
        for entry in used:
            assert entry["adjusted"] is True
            assert all(entry[key] is None for key in WHY), "no why for a hidden one"

    def test_a_live_schema_without_the_columns_has_none(
        self, client, facility_segments, router, monkeypatch
    ):
        with connection.cursor() as cursor:
            cursor.execute(
                f"ALTER TABLE {facility_segments}.segment DROP COLUMN stress_adjustment_display"
            )
        monkeypatch.setattr(routing, "_adjustment_columns_seen", False)
        router(standard_router())
        assert post(client, good_body()).json()["stress_adjustments"] == []


@db
def test_a_mass_ride_counts_bike_lanes_as_none(client, facility_segments, router):
    """Mass Ride rides the roadway (the owner: "Even protected bike lanes
    aren't used."), so way 202's painted lane is "none" in its breakdown, and
    the path stays a path."""
    router(standard_router())
    ordinary = post(client, {**good_body("default"), "when": "weekday_rush"}).json()["facility_m"]
    router(standard_router())
    body = post(client, {**good_body("mass-ride"), "when": "weekday_rush"}).json()
    assert body["variant"] == "no-trail"
    mass = body["facility_m"]
    assert ordinary["lane"] > 0
    assert mass["lane"] == 0 and mass["protected"] == 0
    assert mass["none"] == pytest.approx(
        ordinary["none"] + ordinary["lane"] + ordinary["protected"]
    )
    assert mass["path"] == pytest.approx(ordinary["path"])
    # And a protected lane the same way.
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {facility_segments}.segment SET facility = 'protected' "
            "WHERE osm_way_id = 202 AND ordinal = 0"
        )
    router(standard_router())
    ordinary = post(client, {**good_body("default"), "when": "weekday_rush"}).json()["facility_m"]
    router(standard_router())
    mass = post(client, {**good_body("mass-ride"), "when": "weekday_rush"}).json()["facility_m"]
    assert ordinary["protected"] > 0
    assert mass["protected"] == 0


# --- The avoid half: sustained climbs and descents (the owner, 2026-09-28) ----


def ramp_profile(segments, step=30.0):
    """Elevations every `step` metres for [(length_m, grade)] ridden in order."""
    heights, e = [100.0], 100.0
    for length, grade in segments:
        for _ in range(int(length // step)):
            e += grade * step
            heights.append(e)
    return heights


# 1.5 km at 9%: a sustained climb; the same rise as a 120 m kick then flat.
LONG_STEEP = ramp_profile([(1500, 0.09)])
KICK_THEN_FLAT = ramp_profile([(120, 0.10), (1380, 0.0)])
LONG_STEEP_DOWN = ramp_profile([(1500, -0.09)])
GENTLE_DOWN = ramp_profile([(1500, -0.02)])


def avoid_router(first, alternates) -> FakeRouter:
    return FakeRouter(
        {
            "route": {
                "trip": _trip(VERTICES, *first),
                "alternates": [{"trip": _trip(VERTICES, km, elev)} for km, elev in alternates],
            },
            "trace_attributes": trace_answer(VERTICES, [(101, 0, 4, 2.0)]),
        }
    )


@db
class TestAvoidingSustainedGrades:
    def test_a_long_steep_climb_loses_to_a_longer_kick(self, client, facility_segments, router):
        # The router's own route climbs 1.5 km at 9%; the alternative is 20% longer
        # (40 s at the fake's 100 s a km) and climbs only a 120 m kick.
        router(avoid_router((2.0, LONG_STEEP), [(2.4, KICK_THEN_FLAT)]))
        body = post(client, {**good_body(), "hills": -60}).json()
        assert body["hills_avoid"]["chosen"] == 1
        assert body["hills_avoid"]["grade_cost_s"] == 0
        assert body["hills_avoid"]["direct_grade_cost_s"] > 500
        assert body["hills_avoid"]["weight"] == 0.6
        assert body["distance_m"] == pytest.approx(2400.0)

    def test_a_short_kick_is_kept(self, client, facility_segments, router):
        router(avoid_router((2.0, KICK_THEN_FLAT), [(2.4, ramp_profile([(1500, 0.0)]))]))
        assert post(client, {**good_body(), "hills": -60}).json()["hills_avoid"]["chosen"] == 0

    def test_a_steep_descent_is_avoided_by_cargo_and_kept_by_fast(
        self, client, facility_segments, router
    ):
        routes = ((2.0, LONG_STEEP_DOWN), [(2.3, GENTLE_DOWN)])
        router(avoid_router(*routes))
        cargo = post(client, {**good_body("cargo"), "hills": -60}).json()["hills_avoid"]
        assert (cargo["chosen"], cargo["brake_grade"]) == (1, 0.03)
        router(avoid_router(*routes))
        fast = post(client, {**good_body("fast"), "hills": -60}).json()["hills_avoid"]
        assert (fast["chosen"], fast["brake_grade"]) == (0, None)

    def test_the_slider_scales_it(self, client, facility_segments, router):
        # 100 s longer: more than the climb costs at -5, less than at -100.
        routes = ((2.0, LONG_STEEP), [(3.0, KICK_THEN_FLAT)])
        router(avoid_router(*routes))
        assert post(client, {**good_body(), "hills": -5}).json()["hills_avoid"]["chosen"] == 0
        router(avoid_router(*routes))
        assert post(client, {**good_body(), "hills": -100}).json()["hills_avoid"]["chosen"] == 1

    def test_the_middle_is_untouched(self, client, facility_segments, router):
        fake = router(avoid_router((2.0, LONG_STEEP), [(2.4, KICK_THEN_FLAT)]))
        body = post(client, {**good_body(), "hills": 0}).json()
        assert body["hills_avoid"] is None
        assert "alternates" not in fake.calls[0][1]
        assert body["distance_m"] == pytest.approx(2000.0)

    def test_a_via_point_keeps_the_router_route_and_says_why(
        self, client, facility_segments, router
    ):
        fake = router(standard_router())
        points = [list(VERTICES[0]), list(VERTICES[2]), list(VERTICES[-1])]
        body = post(client, {"points": points, "preset": "default", "hills": -50}).json()
        assert "alternates" not in fake.calls[0][1]
        assert body["hills_avoid"]["limited"] == "two_points"
        assert body["hills_avoid"]["chosen"] == 0


def test_every_preset_states_a_brake_grade():
    """Proposed per ride type for the owner to confirm (the owner, 2026-09-28:
    "Depends on ride type"); Cargo's is the owner's 2-3%."""
    assert set(presets.BRAKE_GRADES) == set(presets.PRESETS)
    assert presets.PRESETS["cargo"].brake_grade == 0.03
    graded = [g for g in presets.BRAKE_GRADES.values() if g is not None]
    assert min(graded) == presets.PRESETS["cargo"].brake_grade
    assert presets.PRESETS["default"].brake_grade > presets.PRESETS["cargo"].brake_grade


def test_grade_profile_splits_legs():
    trip = route_answer([(VERTICES, 0.09, [1.0, 2.0, 3.0, 4.0]), (VERTICES, 0.09, [4.0, 5.0])])[
        "trip"
    ]
    profile = routing.grade_profile(trip)
    assert profile[:4] == [(0.0, 1.0), (30.0, 2.0), (60.0, 3.0), (90.0, 4.0)]
    assert profile[4][1] is None
    assert profile[5] == (90.0, 4.0)


def test_choose_gentlest_keeps_the_router_route_on_a_tie():
    trips = [_trip(VERTICES, 2.0, LONG_STEEP), _trip(VERTICES, 2.0, LONG_STEEP)]
    assert routing.choose_gentlest(trips, 1.0, 0.06) == 0


# --- The avoid half ranks by the router's cost (correctness review, 2026-09-28) ---


def _costed(vertices, km, elevations, cost):
    trip = _trip(vertices, km, elevations)
    trip["summary"]["cost"] = cost
    return trip


def test_a_faster_but_busier_alternate_is_not_taken():
    """Mass Ride at -95 took the Frederick Douglass roadway: faster (1072 s
    against 1693 s) but dearer by the router's own cost (4346 against 4111),
    with the same sustained-grade cost. Ranked by cost, the router's own
    route stays."""
    flat = [10.0, 10.0, 10.0, 10.0]
    own = _costed(VERTICES, 3.0, flat, 4111.0)
    own["summary"]["time"] = 1693.0
    douglass = _costed(VERTICES, 2.5, flat, 4346.0)
    douglass["summary"]["time"] = 1072.0
    assert routing.choose_gentlest([own, douglass], 0.95, 0.04) == 0


def test_a_dearer_alternate_still_wins_on_a_long_climb_it_avoids():
    own = _costed(VERTICES, 2.0, LONG_STEEP, 1000.0)
    gentle = _costed(VERTICES, 2.4, KICK_THEN_FLAT, 1100.0)
    assert routing.choose_gentlest([own, gentle], 1.0, 0.06) == 1


def test_a_trip_without_a_cost_falls_back_to_its_time():
    trip = _trip(VERTICES, 2.0, [10.0, 10.0])
    assert routing._router_cost(trip) == trip["summary"]["time"]


@db
class TestAlternatesInsideTheBudget:
    """OPS review, 2026-09-28: a request for alternatives could run past the
    per-call limit and turn a ride the plain request answers into a 502."""

    def test_a_slow_request_for_alternatives_is_asked_again_without(
        self, client, facility_segments, router
    ):
        plain = standard_router()
        calls = []

        def transport(url, payload, timeout):
            calls.append((payload.get("alternates"), timeout))
            if url.endswith("/route") and "alternates" in payload:
                raise routing.RouterUnavailable("timed out")
            return plain(url, payload, timeout)

        router(transport)
        body = post(client, {**good_body(), "hills": -60}).json()
        assert calls[0] == (routing.SEEK_ALTERNATES, routing.ALTERNATES_TIMEOUT_S)
        assert calls[1][0] is None, "asked again without alternatives"
        assert body["hills_avoid"]["limited"] == "timed_out"
        assert body["distance_m"] == pytest.approx(2200.0)

    def test_the_seek_half_says_so_too(self, client, facility_segments, router):
        plain = standard_router()

        def transport(url, payload, timeout):
            if url.endswith("/route") and "alternates" in payload:
                raise routing.RouterUnavailable("timed out")
            return plain(url, payload, timeout)

        router(transport)
        assert post(client, {**good_body(), "hills": 60}).json()["hills_seek"]["limited"] == (
            "timed_out"
        )

    def test_the_avoid_half_stops_at_a_shorter_span(self, facility_segments, router):
        mid = [[-77.05, 38.9], [-77.05 + 0.35, 38.9]]  # about 30 km
        assert (
            routing.AVOID_MAX_SPAN_M
            < routing.haversine(routing.Point(*mid[0]), routing.Point(*mid[1]))
            < routing.SEEK_MAX_SPAN_M
        )
        fake = router(standard_router())
        body = routing.plan(mid, "default", dials=routing.Dials(hills=-50))
        assert "alternates" not in fake.calls[0][1]
        assert body["hills_avoid"]["limited"] == "long_ride"
        fake = router(seeking_router([(2.2, HILLY)]))
        routing.plan(mid, "default", dials=routing.Dials(hills=50))
        assert fake.calls[0][1]["alternates"] == routing.SEEK_ALTERNATES


@db
class TestTheAvoidHalfNeverTradesCalmForBusy:
    """Correctness review, 2026-09-28: the hills slider never trades calm
    roads for busy ones. An alternative that wins on sustained grades is
    traced and kept only if it is no busier than the router's own route."""

    def router_with(self, own_way, alternate_way):
        own = _trip(VERTICES, 2.0, LONG_STEEP)
        alternate = _trip(list(reversed(VERTICES)), 2.4, KICK_THEN_FLAT)
        alternate_shape = alternate["legs"][0]["shape"]

        def transport(url, payload, timeout):
            if url.endswith("/route"):
                return {"trip": own, "alternates": [{"trip": alternate}]}
            way = alternate_way if payload["encoded_polyline"] == alternate_shape else own_way
            return trace_answer(VERTICES, [(way, 0, 4, 2.0)])

        return transport

    def test_a_busier_alternative_is_not_taken(self, client, facility_segments, router):
        # The router's own route on way 101 (tier 1), the gentler one on 202 (tiers 3 and 2).
        router(self.router_with(101, 202))
        assert post(client, {**good_body(), "hills": -60}).json()["hills_avoid"]["chosen"] == 0

    def test_a_calmer_alternative_is_taken(self, client, facility_segments, router):
        router(self.router_with(202, 101))
        assert post(client, {**good_body(), "hills": -60}).json()["hills_avoid"]["chosen"] == 1


@db
class TestTrafficWinsOverHills:
    """The owner, 2026-09-28 (item 61): "Traffic wins (Recommended)". Hill
    avoidance never makes a route busier than the same trip at the middle of
    the hills slider."""

    def router_with(self, avoid_way, middle_way, middle_fails=False):
        avoid = _trip(VERTICES, 2.0, KICK_THEN_FLAT)
        middle = _trip(list(reversed(VERTICES)), 2.2, LONG_STEEP)
        middle_shape = middle["legs"][0]["shape"]
        calls = []

        def transport(url, payload, timeout):
            if url.endswith("/route"):
                use_hills = payload["costing_options"]["bicycle"]["use_hills"]
                calls.append((use_hills, "alternates" in payload, timeout))
                if use_hills == 1.0:
                    if middle_fails:
                        raise routing.RouterUnavailable("timed out")
                    return {"trip": middle}
                return {"trip": avoid}
            way = middle_way if payload["encoded_polyline"] == middle_shape else avoid_way
            return trace_answer(VERTICES, [(way, 0, 4, 2.0)])

        return transport, calls

    def test_a_busier_hill_avoiding_route_gives_way_to_the_middle(
        self, client, facility_segments, router
    ):
        # The hill-avoiding route on way 202 (tiers 3 and 2), the middle on 101 (tier 1).
        transport, calls = self.router_with(202, 101)
        router(transport)
        body = post(client, {**good_body(), "hills": -60}).json()
        assert body["hills_avoid"]["kept_middle"] is True
        assert body["distance_m"] == pytest.approx(2200.0), "the middle's route"
        middle_call = [c for c in calls if c[0] == 1.0]
        assert len(middle_call) == 1
        assert middle_call[0][1] is False, "one /route, without alternatives"
        assert middle_call[0][2] <= routing.ALTERNATES_TIMEOUT_S

    def test_a_calmer_hill_avoiding_route_is_kept(self, client, facility_segments, router):
        transport, _calls = self.router_with(101, 202)
        router(transport)
        body = post(client, {**good_body(), "hills": -60}).json()
        assert body["hills_avoid"]["kept_middle"] is False
        assert body["distance_m"] == pytest.approx(2000.0)

    def test_an_equally_busy_one_is_kept(self, client, facility_segments, router):
        transport, _calls = self.router_with(202, 202)
        router(transport)
        assert (
            post(client, {**good_body(), "hills": -60}).json()["hills_avoid"]["kept_middle"]
            is False
        )

    def test_a_middle_call_that_fails_keeps_the_answer(self, client, facility_segments, router):
        transport, _calls = self.router_with(202, 101, middle_fails=True)
        router(transport)
        response = post(client, {**good_body(), "hills": -60})
        assert response.status_code == 200
        assert response.json()["hills_avoid"]["kept_middle"] is False
        assert response.json()["distance_m"] == pytest.approx(2000.0)

    def test_it_applies_where_no_alternatives_were_asked_for(
        self, client, facility_segments, router
    ):
        """A via point: the router's own hill-avoiding route, still no busier."""
        transport, _calls = self.router_with(202, 101)
        router(transport)
        points = [list(VERTICES[0]), list(VERTICES[2]), list(VERTICES[-1])]
        body = post(client, {"points": points, "preset": "default", "hills": -50}).json()
        assert body["hills_avoid"]["limited"] == "two_points"
        assert body["hills_avoid"]["kept_middle"] is True

    def test_a_slow_first_route_leaves_the_answers_traces_their_time(
        self,
        client,
        facility_segments,
        router,
        clock,  # noqa: F811
    ):
        """Correctness review, round 3 (S1): a 3-point Cargo ride whose first
        route took 21 s and whose middle call hung was answered at 37 s with
        every metre "unknown". The middle call now gets what is left less the
        traces' reserve, and the answer is traced."""
        transport, calls = self.router_with(202, 101)
        slow = timed(clock, transport, {"route": [21.0, 100.0]})
        router(slow)
        points = [list(VERTICES[0]), list(VERTICES[2]), list(VERTICES[-1])]
        started = clock.now
        body = post(client, {"points": points, "preset": "cargo", "hills": -60}).json()
        assert body["hills_avoid"]["kept_middle"] is False
        assert body["stress_m"]["unknown"] == 0
        assert body["facility_m"]["unknown"] == 0
        middle_timeout = slow.timeouts[1]
        budget_end = started + routing.PLAN_BUDGET_S - routing.ANSWER_RESERVE_S
        assert middle_timeout <= budget_end - routing.MIDDLE_TRACE_RESERVE_S - (started + 21.0)
        assert clock.now - started < routing.PLAN_BUDGET_S

    def test_with_too_little_time_left_the_middle_is_not_asked(
        self,
        client,
        facility_segments,
        router,
        clock,  # noqa: F811
    ):
        transport, calls = self.router_with(202, 101)
        router(timed(clock, transport, {"route": [27.0]}))
        points = [list(VERTICES[0]), list(VERTICES[2]), list(VERTICES[-1])]
        body = post(client, {"points": points, "preset": "cargo", "hills": -60}).json()
        assert [c for c in calls if c[0] == 1.0] == [], "no middle call"
        assert body["hills_avoid"]["kept_middle"] is False
        assert body["stress_m"]["unknown"] == 0

    @pytest.mark.parametrize(("avoid_way", "middle_way"), [(202, 101), (101, 202)])
    def test_the_answers_route_is_traced_once(
        self, avoid_way, middle_way, client, facility_segments, router
    ):
        """The check traced both routes; the one answered is not traced again."""
        transport, _calls = self.router_with(avoid_way, middle_way)
        traced = []

        def counting(url, payload, timeout):
            if url.endswith("/trace_attributes"):
                traced.append(payload["encoded_polyline"])
            return transport(url, payload, timeout)

        router(counting)
        post(client, {**good_body(), "hills": -60})
        assert len(traced) == 2
        assert len(set(traced)) == 2

    def test_a_chosen_alternative_is_traced_once_too(self, client, facility_segments, router):
        """The re-check of 152261f (P12): with an alternative chosen, the
        router's own route and the alternative are traced by calmer_or_own,
        the middle by the traffic-wins check, and the alternative answered
        reuses its trace - three traces, not four."""
        own = _trip(VERTICES, 2.0, LONG_STEEP)
        alternative = _trip(list(reversed(VERTICES)), 2.4, KICK_THEN_FLAT)
        traced = []

        def transport(url, payload, timeout):
            if url.endswith("/route"):
                if payload["costing_options"]["bicycle"]["use_hills"] == 1.0:
                    return {"trip": own}
                return {"trip": own, "alternates": [{"trip": alternative}]}
            use_hills = payload["costing_options"]["bicycle"]["use_hills"]
            traced.append((payload["encoded_polyline"], use_hills))
            return trace_answer(VERTICES, [(101, 0, 4, 2.0)])

        router(transport)
        body = post(client, {**good_body(), "hills": -60}).json()
        assert body["hills_avoid"]["chosen"] == 1
        assert body["hills_avoid"]["kept_middle"] is False
        assert len(traced) == 3
        assert len(set(traced)) == 3, "each route once, under the costing it was routed with"

    def test_nothing_is_asked_at_the_middle_or_above(self, client, facility_segments, router):
        for hills in (0, 60):
            transport, calls = self.router_with(202, 101)
            router(transport)
            post(client, {**good_body(), "hills": hills})
            assert len(calls) == 1, "one /route, and no second call for the middle"


# --- Correctness review, round 2 (S1, S2) -------------------------------------


def test_a_hung_weekend_router_costs_at_most_its_limit_then_standard_has_the_rest():
    """The weekend router's limit and the standard graph's share after it both
    fit the budget the routers have (R17)."""
    routers_s = routing.PLAN_BUDGET_S - routing.ANSWER_RESERVE_S
    assert routing.WEEKEND_TIMEOUT_S <= routing.ALTERNATES_TIMEOUT_S
    assert routing.WEEKEND_TIMEOUT_S + routing.ALTERNATES_TIMEOUT_S <= routers_s


@db
def test_a_hung_weekend_router_is_asked_once_on_a_ride_with_alternatives(
    client, facility_segments, router
):
    """Round 2, S1: a request for alternatives the weekend router did not
    answer was asked again there without them - 15 s and 15 s more."""
    standard = standard_router()
    weekend_calls = []

    def transport(url, payload, timeout):
        if url.startswith(settings.VALHALLA_UPSTREAMS["weekend"]):
            weekend_calls.append(("alternates" in payload, timeout))
            raise routing.RouterUnavailable("timed out")
        return standard(url, payload, timeout)

    router(transport)
    body = post(client, {**good_body(), "when": "weekend", "hills": -50}).json()
    assert body["variant"] == "standard"
    assert weekend_calls == [(True, routing.WEEKEND_TIMEOUT_S)]


def test_exposure_weights_lts_4_twice_and_tier_5_three_times(monkeypatch):
    """R2, R3: the exposure the guards compare is LTS 3 + 2 x LTS 4 + 3 x tier 5
    (and the LTS 4 and Avoid metres, for the hold)."""
    monkeypatch.setattr(routing, "trace_leg", lambda *args: {"edges": []})
    monkeypatch.setattr(
        routing,
        "breakdown",
        lambda pieces, when, roadway_only=False: (
            {"1": 1000.0, "2": 1000.0, "3": 100.0, "4": 10.0, "5": 1.0, "unknown": 0.0},
            {},
        ),
    )
    trip = _trip(VERTICES, 2.0, FLAT)
    deadline = routing.Deadline(routing.clock() + 30, 10)
    assert routing._exposure("standard", {}, trip, "weekday_rush", deadline) == (123.0, 11.0)


def test_an_untraceable_leg_has_no_exposure_at_all(monkeypatch):
    """R7: a leg that cannot be traced makes the whole trip's exposure None -
    not the exposure of the legs that could be, which would make it look calm."""
    calls = []

    def trace(variant, costing, shape, deadline):
        calls.append(shape)
        return None if len(calls) == 1 else {"edges": []}

    monkeypatch.setattr(routing, "trace_leg", trace)
    monkeypatch.setattr(
        routing,
        "breakdown",
        lambda pieces, when, roadway_only=False: (dict.fromkeys("12345", 0.0), {}),
    )
    trip = route_answer([(VERTICES, 1.0, FLAT), (VERTICES, 1.0, FLAT)])["trip"]
    deadline = routing.Deadline(routing.clock() + 30, 10)
    assert routing._exposure("standard", {}, trip, "weekday_rush", deadline) is None


class TestTheCalmerOrOwnFallbacks:
    """R5, R6: a trace that cannot be made, or runs out of time, keeps the
    router's own route - and never raises."""

    trips = [_trip(VERTICES, 2.0, LONG_STEEP), _trip(VERTICES, 2.4, KICK_THEN_FLAT)]
    deadline = routing.Deadline(1e12, 10)

    def test_an_untraceable_own_route_keeps_it(self, monkeypatch):
        exposures = iter([None, (5.0, 0.0)])
        monkeypatch.setattr(routing, "_exposure", lambda *args: next(exposures))
        assert routing.calmer_or_own(self.trips, 1, "standard", {}, "w", self.deadline) == 0

    def test_an_untraceable_alternative_is_not_taken(self, monkeypatch):
        exposures = iter([(5.0, 0.0), None])
        monkeypatch.setattr(routing, "_exposure", lambda *args: next(exposures))
        assert routing.calmer_or_own(self.trips, 1, "standard", {}, "w", self.deadline) == 0

    @pytest.mark.parametrize(
        "failure", [routing.RouterUnavailable("down"), routing.DeadlineExceeded("no time")]
    )
    def test_a_trace_that_fails_keeps_the_router_route(self, monkeypatch, failure):
        def fail(*args):
            raise failure

        monkeypatch.setattr(routing, "_exposure", fail)
        assert routing.calmer_or_own(self.trips, 1, "standard", {}, "w", self.deadline) == 0

    def test_a_calmer_alternative_is_taken(self, monkeypatch):
        exposures = iter([(5.0, 0.0), (4.0, 0.0)])
        monkeypatch.setattr(routing, "_exposure", lambda *args: next(exposures))
        assert routing.calmer_or_own(self.trips, 1, "standard", {}, "w", self.deadline) == 1


AVERSE = presets.EXPOSURE_STRESS_AVERSE


class TestTheHillsChoiceUsesThePlansExposure:
    """GATE-corr SF1: the hills slider's choice of an alternate, and the middle
    check, weigh the plan's own Exposure and never take more LTS 4 and Avoid than the
    router's own route on a ride that holds it (OWNER-DECISIONS 250)."""

    trips = [_trip(VERTICES, 2.0, LONG_STEEP), _trip(VERTICES, 2.4, KICK_THEN_FLAT)]
    deadline = routing.Deadline(1e12, 10)

    def stress(self, monkeypatch, own, alternative):
        """Each trip's metres by tier: `own` for the first traced, then `alternative`."""
        readings = iter([own, alternative])
        monkeypatch.setattr(routing, "_trace", lambda *args: {"edges": []})
        monkeypatch.setattr(routing, "pieces_of_trace", lambda trace: [])
        monkeypatch.setattr(
            routing,
            "breakdown",
            lambda pieces, when, roadway_only=False: (
                {"1": 0.0, "2": 0.0, "3": 0.0, "4": 0.0, "5": 0.0, "unknown": 0.0} | next(readings),
                {},
            ),
        )

    def test_the_exposure_is_the_plans_weights_and_the_lts4_metres(self, monkeypatch):
        self.stress(monkeypatch, {"3": 100.0, "4": 10.0, "5": 1.0}, {})
        trip = _trip(VERTICES, 2.0, FLAT)
        got = routing._exposure("standard", {}, trip, "w", self.deadline, None, AVERSE)
        assert got == (100.0 + 80.0 + 16.0, 11.0)

    def test_an_alternate_with_more_lts4_is_not_taken_though_its_standard_exposure_is_less(
        self, monkeypatch
    ):
        # At 1/2/3 the alternate (300 m of LTS 3, 0 of LTS 4) is calmer than the
        # own route (0 of LTS 3, 200 of LTS 4)? 300 < 400: yes. At 1/8/16 it is
        # 300 against 1,600; calmer still. The hold is the point: give the alternate
        # 150 m of LTS 4 against the own route's 100, with less LTS 3.
        own = {"3": 900.0, "4": 100.0}
        alternative = {"3": 0.0, "4": 150.0}
        self.stress(monkeypatch, own, alternative)
        standard = routing.calmer_or_own(self.trips, 1, "standard", {}, "w", self.deadline, {})
        assert standard == 1, "at 1/2/3: 1,100 against 300"
        self.stress(monkeypatch, own, alternative)
        held = routing.calmer_or_own(self.trips, 1, "standard", {}, "w", self.deadline, {}, AVERSE)
        assert held == 0, "150 m of LTS 4 against 100 m: the hold refuses, whatever the weights"

    def test_without_the_hold_the_plans_weights_still_decide(self, monkeypatch):
        weighted = presets.Exposure(lts3=1.0, lts4=8.0, avoid=16.0, hold_lts4=False)
        # LTS 3 900 against LTS 4 150 at 8: 900 against 1,200.
        self.stress(monkeypatch, {"3": 900.0}, {"4": 150.0})
        assert (
            routing.calmer_or_own(self.trips, 1, "standard", {}, "w", self.deadline, {}, weighted)
            == 0
        )
        self.stress(monkeypatch, {"3": 900.0}, {"4": 150.0})
        assert routing.calmer_or_own(self.trips, 1, "standard", {}, "w", self.deadline, {}) == 1, (
            "at 1/2/3 it is 900 against 300"
        )

    def test_an_alternate_with_no_more_lts4_is_taken_on_a_ride_that_holds_it(self, monkeypatch):
        self.stress(monkeypatch, {"3": 900.0, "4": 100.0}, {"3": 200.0, "4": 100.0})
        assert (
            routing.calmer_or_own(self.trips, 1, "standard", {}, "w", self.deadline, {}, AVERSE)
            == 1
        )

    def test_the_hold_has_a_metre_of_slack(self, monkeypatch):
        # The own route's 900 m of LTS 3 keep it the busier by the weights either way.
        own = {"3": 900.0, "4": 100.0}
        self.stress(monkeypatch, own, {"4": 101.0})
        assert (
            routing.calmer_or_own(self.trips, 1, "standard", {}, "w", self.deadline, {}, AVERSE)
            == 1
        )
        self.stress(monkeypatch, own, {"4": 101.5})
        assert (
            routing.calmer_or_own(self.trips, 1, "standard", {}, "w", self.deadline, {}, AVERSE)
            == 0
        )

    def test_the_own_routes_exposure_is_weighed_as_the_alternates_is(self, monkeypatch):
        """Both routes are weighed by the plan's weights, not only the alternate: 100 m of
        LTS 4 is 800 at 1/8/16 (and 200 at 1/2/3), against 700 m of LTS 3."""
        self.stress(monkeypatch, {"4": 100.0}, {"3": 700.0})
        assert (
            routing.calmer_or_own(self.trips, 1, "standard", {}, "w", self.deadline, {}, AVERSE)
            == 1
        )
        self.stress(monkeypatch, {"4": 100.0}, {"3": 700.0})
        assert routing.calmer_or_own(self.trips, 1, "standard", {}, "w", self.deadline, {}) == 0

    def test_the_middle_routes_exposure_is_weighed_by_the_plans_weights(self, monkeypatch):
        weighted = presets.Exposure(lts3=1.0, lts4=8.0, avoid=16.0, hold_lts4=False)
        middle = _trip(list(reversed(VERTICES)), 2.2, LONG_STEEP)
        trip = _trip(VERTICES, 2.0, KICK_THEN_FLAT)
        monkeypatch.setattr(routing, "_call", lambda *a: {"trip": middle})
        deadline = routing.Deadline(routing.clock() + 37, routing.ROUTER_TIMEOUT_S)
        # The hill-avoiding route has 300 m of LTS 3 (300); the middle's 60 m of LTS 4 is 480
        # at 1/8/16 and 120 at 1/2/3: the plan's weights keep the hill-avoiding route.
        self.stress(monkeypatch, {"3": 300.0}, {"4": 60.0})
        kept = routing.no_busier_than_middle(
            trip, {"alternates": 3}, "standard", {}, {}, "w", deadline, None, weighted
        )
        assert kept == (trip, False)
        self.stress(monkeypatch, {"3": 300.0}, {"4": 60.0})
        kept = routing.no_busier_than_middle(
            trip, {"alternates": 3}, "standard", {}, {}, "w", deadline, None
        )
        assert kept == (middle, True), "at 1/2/3 the middle is calmer"

    def test_the_middle_route_with_more_lts4_is_not_swapped_in(self, monkeypatch):
        middle = _trip(list(reversed(VERTICES)), 2.2, LONG_STEEP)
        trip = _trip(VERTICES, 2.0, KICK_THEN_FLAT)
        monkeypatch.setattr(routing, "_call", lambda *a: {"trip": middle})
        deadline = routing.Deadline(routing.clock() + 37, routing.ROUTER_TIMEOUT_S)
        # The hill-avoiding route: 600 m of LTS 3 and 50 of LTS 4. The middle's: 0 of
        # LTS 3 and 120 of LTS 4: calmer by 1/8/16, with more LTS 4.
        self.stress(monkeypatch, {"3": 600.0, "4": 50.0}, {"4": 120.0})
        kept = routing.no_busier_than_middle(
            trip, {"alternates": 3}, "standard", {}, {}, "w", deadline, None, AVERSE
        )
        assert kept == (trip, False)
        self.stress(monkeypatch, {"3": 600.0, "4": 50.0}, {"4": 40.0})
        kept = routing.no_busier_than_middle(
            trip, {"alternates": 3}, "standard", {}, {}, "w", deadline, None, AVERSE
        )
        assert kept == (middle, True)

    def test_the_plan_passes_its_exposure_to_both(self, monkeypatch):
        seen = []
        monkeypatch.setattr(routing, "calmer_or_own", lambda *a, **k: seen.append(("own", a)) or 0)
        assert presets.exposure_for("trailmaxxing") is AVERSE
        assert presets.exposure_for("cargo", presets.CARRYING_PEOPLE) is AVERSE
        assert presets.exposure_for("default") is presets.EXPOSURE_STANDARD


class TestNoBusierThanMiddleFallbacks:
    """Correctness review, round 3 (S2: X2, X3, X4, X8): every way the check
    can fail keeps the hill-avoiding route and never raises."""

    trip = _trip(VERTICES, 2.0, KICK_THEN_FLAT)
    middle = _trip(list(reversed(VERTICES)), 2.2, LONG_STEEP)

    def check(self, monkeypatch, answer, exposures=None, variant="standard", deadline=None):
        seen = {"exposures": 0, "limits": [], "trace_deadlines": []}

        def call(variant_, endpoint, payload, deadline_):
            seen["limits"].append(deadline_.per_call_s)
            if isinstance(answer, Exception):
                raise answer
            return answer

        values = iter(exposures or [])

        def exposure(*args):
            seen["exposures"] += 1
            seen["trace_deadlines"].append(args[4].at)
            return next(values)

        monkeypatch.setattr(routing, "_call", call)
        monkeypatch.setattr(routing, "_exposure", exposure)
        deadline = deadline or routing.Deadline(routing.clock() + 37, routing.ROUTER_TIMEOUT_S)
        result = routing.no_busier_than_middle(
            self.trip, {"alternates": 3}, variant, {}, {}, "weekday_rush", deadline
        )
        return result, seen

    @pytest.mark.parametrize(
        "exposures", [[None, (5.0, 0.0)], [(5.0, 0.0), None]], ids=["own", "middle"]
    )
    def test_an_untraceable_route_keeps_the_answer(self, monkeypatch, exposures):
        (trip, kept), _seen = self.check(monkeypatch, {"trip": self.middle}, exposures)
        assert (trip, kept) == (self.trip, False)

    def test_a_refused_middle_call_keeps_the_answer(self, monkeypatch):
        refused = routing.RouterRefused(400, 442, "No path could be found")
        (trip, kept), seen = self.check(monkeypatch, refused)
        assert (trip, kept) == (self.trip, False)
        assert seen["exposures"] == 0

    def test_a_middle_with_no_legs_keeps_the_answer(self, monkeypatch):
        (trip, kept), seen = self.check(monkeypatch, {"trip": {"legs": []}})
        assert (trip, kept) == (self.trip, False)
        assert seen["exposures"] == 0, "a legless middle is not measured, so never taken"

    def test_a_busier_answer_gives_way(self, monkeypatch):
        (trip, kept), _seen = self.check(
            monkeypatch, {"trip": self.middle}, [(9.0, 0.0), (5.0, 0.0)]
        )
        assert (trip, kept) == (self.middle, True)

    def test_the_middle_call_is_held_to_the_alternates_limit(self, monkeypatch):
        _result, seen = self.check(monkeypatch, {"trip": self.middle}, [(5.0, 0.0), (5.0, 0.0)])
        assert seen["limits"] == [routing.ALTERNATES_TIMEOUT_S]

    def test_on_the_weekend_graph_to_the_weekend_limit(self, monkeypatch):
        _result, seen = self.check(
            monkeypatch, {"trip": self.middle}, [(5.0, 0.0), (5.0, 0.0)], "weekend"
        )
        assert seen["limits"] == [routing.WEEKEND_TIMEOUT_S]

    def test_it_leaves_the_traces_reserve(self, monkeypatch):
        left = routing.MIDDLE_TRACE_RESERVE_S + 6.0
        deadline = routing.Deadline(routing.clock() + left, routing.ROUTER_TIMEOUT_S)
        _result, seen = self.check(
            monkeypatch, {"trip": self.middle}, [(5.0, 0.0), (5.0, 0.0)], deadline=deadline
        )
        assert seen["limits"] == [pytest.approx(6.0, abs=0.5)]
        # Both routes' traces are inside the same step, not the whole budget.
        assert seen["trace_deadlines"] == [deadline.at - routing.MIDDLE_TRACE_RESERVE_S] * 2

    def test_with_less_than_its_minimum_left_it_is_not_asked(self, monkeypatch):
        left = routing.MIDDLE_TRACE_RESERVE_S + routing.MIDDLE_MIN_S - 1.0
        deadline = routing.Deadline(routing.clock() + left, routing.ROUTER_TIMEOUT_S)
        (trip, kept), seen = self.check(monkeypatch, {"trip": self.middle}, deadline=deadline)
        assert (trip, kept) == (self.trip, False)
        assert seen["limits"] == []


@db
class TestAvoidGravel:
    """OWNER-DECISIONS 91, 92, 111: the "Avoid gravel" box."""

    def test_off_by_default_and_echoed(self, client, facility_segments, router):
        fake = router(standard_router())
        body = post(client, good_body("cargo")).json()
        assert body["dials"]["avoid_gravel"] is False
        sent = fake.calls[0][1]["costing_options"]["bicycle"]["avoid_bad_surfaces"]
        assert sent == presets.costing("cargo")["bicycle"]["avoid_bad_surfaces"]

    @pytest.mark.parametrize("name", ["default", "gravel", "cargo", "mass-ride"])
    def test_checked_it_steers_off_unpaved_surfaces(self, name, client, facility_segments, router):
        fake = router(standard_router())
        body = post(client, {**good_body(name), "avoid_gravel": True}).json()
        assert body["dials"]["avoid_gravel"] is True
        for _url, payload in fake.calls:
            options = payload["costing_options"]["bicycle"]
            assert options["avoid_bad_surfaces"] >= presets.AVOID_GRAVEL_SURFACES

    def test_only_a_boolean(self, client, facility_segments, router):
        fake = router(standard_router())
        assert post(client, {**good_body(), "avoid_gravel": "yes"}).status_code == 400
        assert fake.calls == []


@db
class TestTrailsOff:
    """OWNER-DECISIONS 463 (and the 2026-09-26 "Every type, roadways ok"): the
    "Keep to roads, not trails" switch (463b) plans on the no-trail graph, on
    every ride type, e-bike rides included with no lock (463a)."""

    def test_off_by_default_and_echoed(self, client, facility_segments, router):
        fake = router(standard_router())
        body = post(client, good_body("default")).json()
        assert body["dials"]["trails_off"] is False
        assert body["variant"] != "no-trail"
        assert fake.calls[0][0].startswith(settings.VALHALLA_UPSTREAMS[body["variant"]])

    @pytest.mark.parametrize(
        "name", ["default", "trailmaxxing", "group-ride", "fast", "cargo", "ebike", "gravel", "mountain-goat"]
    )
    def test_on_it_routes_on_the_no_trail_graph(self, name, client, facility_segments, router):
        fake = router(standard_router())
        body = post(client, {**good_body(name), "trails_off": True}).json()
        assert body["variant"] == "no-trail"
        assert body["dials"]["trails_off"] is True
        assert fake.calls[0][0].startswith(settings.VALHALLA_UPSTREAMS["no-trail"])

    def test_mass_ride_is_always_trails_off_whatever_is_sent(self, client, facility_segments, router):
        router(standard_router())
        for sent in ({}, {"trails_off": False}, {"trails_off": True}):
            body = post(client, {**good_body("mass-ride"), **sent}).json()
            assert body["variant"] == "no-trail"
            assert body["dials"]["trails_off"] is True

    def test_on_a_weekend_it_still_takes_the_no_trail_graph(self, client, facility_segments, router):
        router(standard_router())
        body = post(client, {**good_body("default"), "trails_off": True, "when": "weekend"}).json()
        assert body["variant"] == "no-trail"

    def test_electric_assist_with_trails_off_keeps_its_pace_on_the_no_trail_graph(
        self, client, facility_segments, router
    ):
        """463a: "Most ebikes are allowed on multiuse trails" - no lock, and
        the no-trail graph, not the e-bike graph."""
        fake = router(standard_router())
        body = post(client, {**good_body("cargo"), "trails_off": True, "assist": True}).json()
        assert body["variant"] == "no-trail"
        assert body["dials"]["assist"] is True
        assert body["dials"]["trails_off"] is True
        assert fake.calls[0][0].startswith(settings.VALHALLA_UPSTREAMS["no-trail"])

    def test_the_e_bike_ride_type_with_trails_off_is_not_locked(
        self, client, facility_segments, router
    ):
        """463a: the E-bike ride type's own graph is the e-bike graph; with
        the switch on it takes the no-trail graph, and the switch is honoured."""
        router(standard_router())
        off = post(client, good_body("ebike")).json()
        assert off["variant"] == "ebike"
        assert off["dials"]["trails_off"] is False
        on = post(client, {**good_body("ebike"), "trails_off": True}).json()
        assert on["variant"] == "no-trail"
        assert on["dials"]["trails_off"] is True

    def test_only_a_boolean(self, client, facility_segments, router):
        fake = router(standard_router())
        assert post(client, {**good_body(), "trails_off": "yes"}).status_code == 400
        assert fake.calls == []


# --- The route's coloured sections (FOLLOWUP-ROUTE-COLOURS, item 81) ---------


class TestStressSpans:
    """routing.stress_spans: the sections the route line is drawn in."""

    def test_adjacent_equal_stretches_are_one_section(self):
        spans = routing.stress_spans(
            [(100.0, "2", "none"), (150.0, "2", "none"), (50.0, "3", "lane")]
        )
        assert spans == [
            {"from_m": 0, "to_m": 250, "tier": 2, "facility": "none", "unpaved": None},
            {"from_m": 250, "to_m": 300, "tier": 3, "facility": "lane", "unpaved": None},
        ]

    def test_the_same_tier_on_another_facility_is_another_section(self):
        spans = routing.stress_spans([(100.0, "1", "path"), (100.0, "1", "none")])
        assert [(s["tier"], s["facility"]) for s in spans] == [(1, "path"), (1, "none")]

    def test_a_short_section_is_folded_into_the_one_before(self):
        spans = routing.stress_spans(
            [(100.0, "2", "none"), (9.9, "4", "none"), (100.0, "3", "none")]
        )
        assert spans == [
            {"from_m": 0, "to_m": 110, "tier": 2, "facility": "none", "unpaved": None},
            {"from_m": 110, "to_m": 210, "tier": 3, "facility": "none", "unpaved": None},
        ]

    def test_ten_metres_is_a_section(self):
        spans = routing.stress_spans(
            [(100.0, "2", "none"), (routing.MIN_SPAN_M, "4", "none"), (100.0, "3", "none")]
        )
        assert [s["tier"] for s in spans] == [2, 4, 3]

    def test_many_short_pieces_of_one_class_are_one_section(self):
        """A trace cuts its edges at every shape vertex: 50 m of LTS 4 made of
        ten 5 m pieces is a section, not ten short ones folded away."""
        stretches = [(100.0, "2", "none"), *[(5.0, "4", "none")] * 10, (100.0, "2", "none")]
        assert [s["tier"] for s in routing.stress_spans(stretches)] == [2, 4, 2]

    def test_a_short_crossing_between_two_equal_sections_leaves_one(self):
        spans = routing.stress_spans(
            [(200.0, "1", "path"), (6.0, "3", "none"), (300.0, "1", "path")]
        )
        assert spans == [{"from_m": 0, "to_m": 506, "tier": 1, "facility": "path", "unpaved": None}]

    def test_a_short_first_section_takes_the_next_ones_class(self):
        spans = routing.stress_spans([(4.0, "4", "none"), (3.0, "3", "none"), (100.0, "1", "path")])
        assert spans == [{"from_m": 0, "to_m": 107, "tier": 1, "facility": "path", "unpaved": None}]

    def test_unknown_is_null_and_tier_5_is_5(self):
        spans = routing.stress_spans([(100.0, "unknown", "unknown"), (100.0, "5", "none")])
        assert spans == [
            {"from_m": 0, "to_m": 100, "tier": None, "facility": None, "unpaved": None},
            {"from_m": 100, "to_m": 200, "tier": 5, "facility": "none", "unpaved": None},
        ]

    def test_empty_and_zero_length_stretches(self):
        assert routing.stress_spans([]) == []
        assert routing.stress_spans([(0.0, "1", "none"), (50.0, "2", "none")]) == [
            {"from_m": 0, "to_m": 50, "tier": 2, "facility": "none", "unpaved": None}
        ]

    def test_sections_meet_end_to_end_in_whole_metres(self):
        stretches = [(33.3, str(1 + i % 4), "none") for i in range(30)]
        spans = routing.stress_spans(stretches)
        assert spans[0]["from_m"] == 0
        assert spans[-1]["to_m"] == round(sum(m for m, _t, _f in stretches))
        for a, b in zip(spans, spans[1:], strict=False):
            assert a["to_m"] == b["from_m"]
            assert isinstance(a["to_m"], int)

    def test_a_long_ride_stays_compact(self):
        """10,000 pieces alternating every 5 m between two classes fold away."""
        stretches = [(5.0, "1" if i % 2 else "2", "none") for i in range(10_000)]
        assert len(routing.stress_spans(stretches)) == 1

    def test_a_change_of_surface_is_another_section(self):
        """OWNER-DECISIONS 302: the route line draws unpaved sections in the brown ramp."""
        spans = routing.stress_spans(
            [(100.0, "1", "path", False), (150.0, "1", "path", True), (50.0, "1", "path", True)]
        )
        assert spans == [
            {"from_m": 0, "to_m": 100, "tier": 1, "facility": "path", "unpaved": False},
            {"from_m": 100, "to_m": 300, "tier": 1, "facility": "path", "unpaved": True},
        ]

    def test_a_short_unpaved_piece_is_folded_into_the_one_before(self):
        spans = routing.stress_spans(
            [(100.0, "2", "none", False), (5.0, "2", "none", True), (100.0, "2", "none", False)]
        )
        assert spans == [
            {"from_m": 0, "to_m": 205, "tier": 2, "facility": "none", "unpaved": False}
        ]


@db
class TestStressSpansThroughThePlan:
    def test_a_car_free_road_is_a_path_section_at_the_weekend_only(
        self, client, facility_segments, router
    ):
        """Way 202's second segment is closed to cars at weekends
        (facility_segments): a tier-1 path then, a tier-2 street otherwise."""
        router(standard_router())
        weekend = post(client, {**good_body(), "when": "weekend"}).json()["stress_spans"]
        router(standard_router())
        weekday = post(client, {**good_body(), "when": "weekday_rush"}).json()["stress_spans"]
        assert (1, "path") in [(s["tier"], s["facility"]) for s in weekend]
        assert [(s["tier"], s["facility"]) for s in weekday] == [
            (1, "path"),
            (3, "lane"),
            (2, "none"),
            (None, None),
        ]

    def test_a_mass_ride_counts_its_lanes_as_the_roadway(self, client, facility_segments, router):
        """On the no-trail variant a lane is "none", in the sections as in the totals."""
        router(standard_router())
        spans = post(client, {**good_body("mass-ride"), "when": "weekday_rush"}).json()[
            "stress_spans"
        ]
        assert "lane" not in [s["facility"] for s in spans]

    def test_an_untraced_leg_is_one_unknown_section_between_the_traced_ones(
        self, client, facility_segments, router
    ):
        legs = [(VERTICES, 2.2, FLAT), (list(reversed(VERTICES)), 1.0, FLAT)]
        trace = trace_answer(VERTICES, [(101, 0, 4, 2.2)])
        calls = []

        def transport(url, payload, timeout):
            if url.endswith("/route"):
                return route_answer(legs)
            calls.append(payload["encoded_polyline"])
            if len(calls) > 1:
                raise routing.RouterRefused(400, 444, "no")
            return trace

        router(transport)
        points = [list(VERTICES[0]), list(VERTICES[-1]), list(VERTICES[0])]
        body = post(client, {"points": points, "preset": "default", "when": "weekday_rush"}).json()
        spans = body["stress_spans"]
        assert spans[0] == {
            "from_m": 0,
            "to_m": 2200,
            "tier": 1,
            "facility": "path",
            "unpaved": None,
            "rpm": None,
        }
        assert spans[-1] == {
            "from_m": 2200,
            "to_m": 3200,
            "tier": None,
            "facility": None,
            "unpaved": None,
            "rpm": None,
        }


@db
class TestTheOffroadGraph:
    """Gravel and Mountain Goat ride the off-road graph, where the mountain-bike
    class is open (OWNER-DECISIONS 291(2)); it falls back to the standard graph
    as the weekend one does."""

    @pytest.mark.parametrize("name", ["gravel", "mountain-goat"])
    @pytest.mark.parametrize("when", ["weekday_offpeak", "weekend"])
    def test_these_rides_take_the_offroad_graph_at_any_time(
        self, name, when, client, facility_segments, router
    ):
        fake = router(standard_router())
        body = post(client, {**good_body(name), "when": when}).json()
        assert body["variant"] == "offroad"
        base = settings.VALHALLA_UPSTREAMS["offroad"]
        assert all(url.startswith(base + "/") for url, _ in fake.calls)

    def test_other_rides_never_do(self, client, facility_segments, router):
        fake = router(standard_router())
        body = post(client, {**good_body("default"), "when": "weekday_offpeak"}).json()
        assert body["variant"] == "standard"
        assert all("offroad" not in url for url, _ in fake.calls)

    def test_an_offroad_router_that_does_not_answer_falls_back_to_standard(
        self, client, facility_segments, router
    ):
        standard = standard_router()

        def transport(url, payload, timeout):
            if url.startswith(settings.VALHALLA_UPSTREAMS["offroad"]):
                raise routing.RouterUnavailable("connection refused")
            return standard(url, payload, timeout)

        router(transport)
        response = post(client, {**good_body("gravel"), "when": "weekday_offpeak"})
        assert response.status_code == 200
        assert response.json()["variant"] == "standard"
        assert routing._offroad_down()

    def test_an_offroad_graph_not_yet_promoted_plans_on_standard(
        self, client, facility_segments, router, monkeypatch
    ):
        monkeypatch.setattr(routing, "_offroad_is_promoted", lambda: False)
        fake = router(standard_router())
        body = post(client, {**good_body("mountain-goat"), "when": "weekday_offpeak"}).json()
        assert body["variant"] == "standard"
        assert all("offroad" not in url for url, _ in fake.calls)
