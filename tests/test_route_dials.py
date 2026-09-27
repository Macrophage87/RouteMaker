"""POST /api/route's sliders, ride time and facility breakdown (PUBLIC-DIALS).

The owner, 2026-09-27: sliders for traffic stress and hilliness on every ride
type, three ride-time settings, the four facility classes, and Cargo Bike.
The router is the same fake as tests/test_route_api.py's; the segment table is
real, because the breakdown is a PostGIS join.
"""

from __future__ import annotations

import pytest
from django.conf import settings
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

    @pytest.mark.parametrize("name", sorted(set(presets.PRESETS) - {"mass-ride"}))
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
    """The destination-only penalty is how tier 5 reaches every preset,
    Mass Ride at use_roads 1.0 included (core.presets.AVOID_ENTRY_PENALTY_S)."""
    options = presets.costing(name)["bicycle"]
    assert options["destination_only_penalty"] == presets.AVOID_ENTRY_PENALTY_S
    assert presets.AVOID_ENTRY_PENALTY_S >= 15 * 60
