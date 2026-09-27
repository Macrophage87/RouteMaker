"""POST /api/route's sliders, ride time and facility breakdown (PUBLIC-DIALS).

The owner, 2026-09-27: sliders for traffic stress and hilliness on every ride
type, three ride-time settings, the four facility classes, and Cargo Bike.
The router is the same fake as tests/test_route_api.py's; the segment table is
real, because the breakdown is a PostGIS join.
"""

from __future__ import annotations

import pytest
from django.db import connection
from test_route_api import (
    VERTICES,
    FakeRouter,
    good_body,
    post,
    route_answer,
    standard_router,
    trace_answer,
)

from core import presets, routing
from routemaker import ridetime

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

    @pytest.mark.parametrize("name", sorted(presets.PRESETS))
    @pytest.mark.parametrize(("stress", "use_roads"), [(0, 1.0), (50, 0.5), (100, 0.0)])
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
        assert "alternates" not in fake.calls[0][1]

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
        assert presets.PRESETS["group-ride"].costing_options["use_roads"] == 0.5

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
        ],
    )
    def test_bad_dials_are_a_400_before_the_router(self, extra, client, facility_segments, router):
        fake = router(standard_router())
        response = post(client, {**good_body("default"), **extra})
        assert response.status_code == 400
        assert "error" in response.json()
        assert fake.calls == []

    def test_mass_ride_does_not_seek_climbs(self, client, facility_segments, router):
        fake = router(standard_router())
        response = post(client, {**good_body("mass-ride"), "hills": 5})
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

    def test_the_stress_breakdown_does_not_move_with_the_ride_time(
        self, client, facility_segments, router
    ):
        router(standard_router())
        a = post(client, {**good_body(), "when": "weekend"}).json()["stress_m"]
        router(standard_router())
        b = post(client, {**good_body(), "when": "weekday_rush"}).json()["stress_m"]
        assert a == b

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


def test_choose_climb_prefers_the_first_on_a_tie():
    trips = [_trip(VERTICES, 2.0, HILLY), _trip(VERTICES, 2.0, HILLY)]
    assert routing.choose_climb(trips, 1.5) == 0


@pytest.mark.parametrize("hills", [1, 50, 100])
def test_the_distance_budget_grows_with_the_slider(hills):
    assert presets.seek_distance_ratio(hills) > presets.seek_distance_ratio(hills - 1)
    assert presets.seek_distance_ratio(100) == pytest.approx(1.5)
    assert presets.seek_distance_ratio(0) == 1.0
