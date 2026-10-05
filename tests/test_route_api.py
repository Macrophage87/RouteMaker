"""POST /api/route: signed-out route planning, per the shared API contract.

The router is replaced by a fake at the one function that touches the network
(`core.routing._transport`), so these tests see exactly what the API would have
sent to Valhalla and control exactly what comes back. The segment table is real
(a live schema from the `segment_schemas` fixture), because the stress join is
a PostGIS query and a stand-in would test nothing about it. The transport
itself is tested against a real local HTTP server at the bottom.
"""

from __future__ import annotations

import http.server
import json
import logging
import math
import socket
import threading
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.db import connection
from django.test import override_settings
from test_ratelimit import in_one_window

from core import junctions as core_junctions
from core import presets, routing
from routemaker import flow

# A route test plans a weekday ride unless it says otherwise: the weekend router
# is chosen by the day the suite runs on (conftest `weekday_clock`).
pytestmark = pytest.mark.usefixtures("weekday_clock")


db = pytest.mark.django_db(transaction=True)

ROUTE_PATH = "/api/route"
CONTRACT_KEYS = {
    "preset",
    "variant",
    "geometry",
    "distance_m",
    "duration_s",
    "climb_m",
    "descent_m",
    "stress_m",
    "attribution",
    # Additive, PUBLIC-DIALS (tests/test_route_dials.py).
    "facility_m",
    "stress_adjustments",
    # Additive, NO-BIKE-PATHS: the trip points the planner moved (the Zoo's).
    "moved_points",
    "dials",
    "hills_seek",
    "hills_avoid",
    "leg_ends",
    # Additive, FOLLOWUP-ROUTE-COLOURS (OWNER-DECISIONS item 81).
    "stress_spans",
    # Additive, FOLLOWUP-ELEVATION-CHART (OWNER-DECISIONS 322, 323, 328, 333): the elevation
    # profile, and on a Mass Ride its riders a minute and major junctions.
    "profile",
    # Additive, FOLLOWUP-INTERSECTIONS (OWNER-DECISIONS items 163-172):
    # the stressful junctions, the calm search and the detour.
    "intersections",
    # Additive, OWNER-DECISIONS items 233 and 234: a Mass Ride's groups of signalized crossings.
    "intersection_groups",
    "calm_search",
    "detour",
    # Additive, ROUTE-DESCRIPTION (OWNER-DECISIONS item 220): the route in words.
    "description",
    # Additive, OWNER-DECISIONS item 226: the same with short stretches merged.
    "description_overview",
    # Additive, FOLLOWUP-LONG-CALM (OWNER-DECISIONS 262-265): the route's effort-equivalent
    # distance, and at the top of the stress slider the others to choose from.
    "effort_m",
    "rank",
    "candidates",
    # Additive, OWNER-DECISIONS 266: a loop's way back against its way out.
    "loop",
    # Additive, FOLLOWUP-DEDODGE (OWNER-DECISIONS 272): side-street dodges found and removed.
    "dodges",
}
STRESS_KEYS = {"1", "2", "3", "4", "5", "unknown"}

LAT = 38.9
# Five vertices along one parallel, equally spaced, so every stretch between two
# of them has the same ground length.
VERTICES = [(-77.05, LAT), (-77.04, LAT), (-77.035, LAT), (-77.03, LAT), (-77.02, LAT)]


def encode_polyline6(coordinates) -> str:
    out = []
    prev_lat = prev_lon = 0
    for lon, lat in coordinates:
        for value, prev in ((round(lat * 1e6), prev_lat), (round(lon * 1e6), prev_lon)):
            delta = value - prev
            delta = ~(delta << 1) if delta < 0 else delta << 1
            while delta >= 0x20:
                out.append(chr((0x20 | (delta & 0x1F)) + 63))
                delta >>= 5
            out.append(chr(delta + 63))
        prev_lat, prev_lon = round(lat * 1e6), round(lon * 1e6)
    return "".join(out)


def route_answer(legs) -> dict:
    """A Valhalla /route body. `legs` is [(vertices, length_km, elevations)]."""
    return {
        "trip": {
            "legs": [
                {
                    "shape": encode_polyline6(vertices),
                    "summary": {"length": length_km, "time": 100.0 * length_km},
                    "elevation": elevations,
                    "elevation_interval": 30,
                }
                for vertices, length_km, elevations in legs
            ],
            "summary": {
                "length": sum(length for _v, length, _e in legs),
                "time": 100.0 * sum(length for _v, length, _e in legs),
            },
            "units": "kilometers",
        }
    }


def trace_answer(vertices, edges) -> dict:
    """A Valhalla /trace_attributes body. `edges` is [(way_id, begin, end, km)]."""
    return {
        "units": "kilometers",
        "shape": encode_polyline6(vertices),
        "edges": [
            {"way_id": way, "begin_shape_index": b, "end_shape_index": e, "length": km}
            for way, b, e, km in edges
        ],
    }


class FakeRouter:
    """Records every call; answers from `answers[endpoint]` (a body, a list of
    bodies consumed in order, or an exception to raise)."""

    def __init__(self, answers: dict) -> None:
        self.answers = answers
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, payload: dict, timeout: float) -> dict:
        self.calls.append((url, payload))
        endpoint = url.rsplit("/", 1)[1]
        answer = self.answers[endpoint]
        if isinstance(answer, list):
            answer = answer.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def endpoints(self) -> list[str]:
        return [url.rsplit("/", 1)[1] for url, _ in self.calls]


# One leg over all five vertices: way 101 (one segment, tier 3), way 202 (two
# segments: tier 1 on its first half, tier 4 on its second), way 303 (no
# segment row at all).
STANDARD_EDGES = [(101, 0, 1, 0.9), (202, 1, 3, 0.8), (303, 3, 4, 0.5)]
STANDARD_EXPECTED = {"1": 400.0, "2": 0.0, "3": 900.0, "4": 400.0, "5": 0.0, "unknown": 500.0}


def standard_router() -> FakeRouter:
    return FakeRouter(
        {
            "route": route_answer([(VERTICES, 2.2, [10.0, 20.0, 15.0, 30.0])]),
            "trace_attributes": trace_answer(VERTICES, STANDARD_EDGES),
        }
    )


@pytest.fixture
def segments(segment_schemas):
    live, _staging = segment_schemas
    rows = [
        (101, 0, 3, VERTICES[0:2]),
        (202, 0, 1, VERTICES[1:3]),
        (202, 1, 4, VERTICES[2:4]),
    ]
    with connection.cursor() as cursor:
        for way, ordinal, tier, line in rows:
            wkt = "LINESTRING(" + ", ".join(f"{lon} {lat}" for lon, lat in line) + ")"
            cursor.execute(
                f"INSERT INTO {live}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                "stress_rule) VALUES (%s, %s, ST_GeomFromText(%s, 4326), %s, 'test')",
                [way, ordinal, wkt, tier],
            )
    return live


@pytest.fixture
def router(monkeypatch):
    def install(fake: FakeRouter) -> FakeRouter:
        monkeypatch.setattr(routing, "_transport", fake)
        return fake

    return install


def post(client, body, content_type: str = "application/json", **extra):
    data = body if isinstance(body, (str, bytes)) else json.dumps(body)
    return client.post(ROUTE_PATH, data=data, content_type=content_type, **extra)


def good_body(preset: str = "default") -> dict:
    return {"points": [list(VERTICES[0]), list(VERTICES[-1])], "preset": preset}


@db
class TestAnswer:
    def test_a_route_carries_every_contract_field(self, client, segments, router) -> None:
        router(standard_router())
        response = post(client, good_body())
        assert response.status_code == 200
        body = response.json()
        assert set(body) == CONTRACT_KEYS
        assert set(body["stress_m"]) == STRESS_KEYS
        assert body["geometry"]["type"] == "LineString"
        assert body["preset"] == "default"
        assert body["variant"] == presets.variant_for_ride("default", routing.default_when())

    def test_the_route_is_coloured_by_stretch_in_route_order(self, client, segments, router):
        """OWNER-DECISIONS item 81: "Could we also get a color on the route for
        what LTS it is?" Way 101 (tier 3), way 202's two segments (tier 1, then
        tier 4), way 303 with no segment row (unknown), in the order ridden."""
        router(standard_router())
        body = post(client, good_body()).json()
        assert body["stress_spans"] == [
            {"from_m": 0, "to_m": 900, "tier": 3, "facility": "none", "unpaved": None, "rpm": None},
            {
                "from_m": 900,
                "to_m": 1300,
                "tier": 1,
                "facility": "none",
                "unpaved": None,
                "rpm": None,
            },
            {
                "from_m": 1300,
                "to_m": 1700,
                "tier": 4,
                "facility": "none",
                "unpaved": None,
                "rpm": None,
            },
            {
                "from_m": 1700,
                "to_m": 2200,
                "tier": None,
                "facility": None,
                "unpaved": None,
                "rpm": None,
            },
        ]
        # The sections agree with the totals.
        by_tier = {}
        for span in body["stress_spans"]:
            key = str(span["tier"]) if span["tier"] else "unknown"
            by_tier[key] = by_tier.get(key, 0) + span["to_m"] - span["from_m"]
        assert by_tier == {k: v for k, v in body["stress_m"].items() if v}

    def test_a_route_reversed_is_coloured_reversed(self, client, segments, router):
        """Route order, not table order: the same edges ridden the other way."""
        vertices = list(reversed(VERTICES))
        edges = [(303, 0, 1, 0.5), (202, 1, 3, 0.8), (101, 3, 4, 0.9)]
        router(
            FakeRouter(
                {
                    "route": route_answer([(vertices, 2.2, [1.0])]),
                    "trace_attributes": trace_answer(vertices, edges),
                }
            )
        )
        spans = post(client, good_body()).json()["stress_spans"]
        assert [s["tier"] for s in spans] == [None, 4, 1, 3]
        assert spans[-1]["to_m"] == 2200

    def test_the_geometry_is_lon_lat(self, client, segments, router) -> None:
        router(standard_router())
        coordinates = post(client, good_body()).json()["geometry"]["coordinates"]
        assert coordinates == [list(v) for v in VERTICES]

    def test_distance_and_duration_are_the_routers_in_metres_and_seconds(
        self, client, segments, router
    ) -> None:
        router(standard_router())
        body = post(client, good_body()).json()
        assert body["distance_m"] == pytest.approx(2200.0)
        assert body["duration_s"] == pytest.approx(220.0)

    def test_climb_and_descent_use_the_hysteresis_definition(
        self, client, segments, router
    ) -> None:
        """10 -> 20 -> 15 -> 30: gain 10 then 15 from the dip's bottom; the one
        descent, 5 m, clears the 3 m hysteresis."""
        router(standard_router())
        body = post(client, good_body()).json()
        assert body["climb_m"] == pytest.approx(25.0)
        assert body["descent_m"] == pytest.approx(5.0)

    def test_the_profile_is_the_routers_elevation_samples_with_grades_and_no_riders(
        self, client, segments, router
    ) -> None:
        """OWNER-DECISIONS 322, 323: the chart's data is the router's per-leg elevation
        (every ELEVATION_INTERVAL_M), where each sample is along the route, and the
        grade there. Off a Mass Ride there are no riders a minute or crossings."""
        router(standard_router())
        profile = post(client, good_body()).json()["profile"]
        assert profile["interval_m"] == routing.ELEVATION_INTERVAL_M
        assert profile["m"] == [0, 30, 60, 90]
        assert profile["elevation_m"] == [10.0, 20.0, 15.0, 30.0]
        assert len(profile["grade_pct"]) == 4
        # Read across the samples either side (here all four, 90 m): (30 - 10) / 90.
        assert profile["grade_pct"][1] == pytest.approx((30.0 - 10.0) / 90 * 100, abs=0.1)
        assert profile["riders_per_min"] is None
        assert profile["flow"] is None and profile["crossings"] is None

    def test_a_route_with_no_elevation_has_a_null_profile(self, client, segments, router) -> None:
        answers = standard_router()
        answers.answers["route"] = route_answer([(VERTICES, 2.2, [])])
        router(answers)
        response = post(client, good_body())
        assert response.status_code == 200
        assert response.json()["profile"] is None

    def test_a_mass_ride_has_riders_a_minute_that_a_climb_lowers(
        self, client, segments, router
    ) -> None:
        """OWNER-DECISIONS 328: the flow model is grade-adjusted. Level, a street whose
        Mass Ride width (`mass_usable_width_m`, the column the capacity map colours by) is
        6.7 m carries about 198 riders a minute; a 6% climb of 300 m carries fewer, and the
        climb's row says by how much. The column wins over the lanes' estimate (three lanes
        a direction here would be 298): the chart and the map agree (394, 404)."""
        heights = [10.0] * 6 + [10.0 + 1.8 * i for i in range(1, 11)] + [28.0] * 4
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {segments}.segment SET mass_usable_width_m = 6.7, road_lanes = 3"
            )
        answers = standard_router()
        answers.answers["route"] = route_answer([(VERTICES, 2.2, heights)])
        router(answers)
        response = post(client, good_body("mass-ride"))
        assert response.status_code == 200
        profile = response.json()["profile"]
        assert len(profile["riders_per_min"]) == len(profile["m"]) == len(heights)
        assert profile["riders_per_min"][0] == 198
        known = [r for r in profile["riders_per_min"] if r is not None]
        assert min(known) < 198
        assert profile["flow"]["narrowest_riders_per_min"] == min(known)
        assert profile["flow"]["typical_riders_per_min"] == 198
        assert profile["climbs"] and profile["climbs"][0]["capacity_drop_pct"] > 20
        assert profile["climbs"][0]["min_riders_per_min"] == min(known)
        assert isinstance(profile["crossings"], list)

    def test_a_mass_ride_whose_junctions_were_not_read_says_not_checked_end_to_end(
        self, client, segments, router, monkeypatch
    ) -> None:
        """Mutation re-review SHOULD-FIX 1: junctions not read (a failed or late read) reach
        the chart as `crossings: null`, never as `[]` ("none")."""
        router(standard_router())
        monkeypatch.setattr(routing, "_events", lambda *_args: None)
        profile = post(client, good_body("mass-ride")).json()["profile"]
        assert profile["crossings"] is None
        assert profile["crossings_complete"] is None

    def test_an_over_budget_mass_ride_says_its_junctions_were_not_checked(
        self, client, segments, router, monkeypatch
    ) -> None:
        """Over budget the joins are skipped: the chart says "not checked"."""
        router(standard_router())
        clock = iter(range(0, 10_000, 30))
        monkeypatch.setattr(routing, "clock", lambda: float(next(clock)))
        response = post(client, good_body("mass-ride"))
        assert response.status_code == 200
        profile = response.json()["profile"]
        assert profile is not None and profile["crossings"] is None

    def test_a_mass_ride_whose_events_come_as_a_plain_list_lists_its_flagged_junctions(
        self, client, segments, router, monkeypatch
    ) -> None:
        """Events without majors beside them: the flagged ones stand in, said as possibly
        incomplete (correctness re-review R3, mutation re-review SHOULD-FIX 1)."""
        router(standard_router())
        full = post(client, good_body("mass-ride")).json()["profile"]
        assert full["crossings_complete"] is True
        original = routing._events
        monkeypatch.setattr(routing, "_events", lambda *args: list(original(*args) or []))
        profile = post(client, good_body("mass-ride")).json()["profile"]
        assert isinstance(profile["crossings"], list)
        assert profile["crossings"] == [c for c in full["crossings"] if c["kind"] == "flagged"]
        assert profile["crossings_complete"] is False

    def test_a_mass_ride_whose_majors_could_not_be_found_says_its_list_may_be_incomplete(
        self, client, segments, router, monkeypatch
    ) -> None:
        """Mutation r4 SHOULD-FIX 1 (CC02): `major_crossings` failing inside `plan()` keeps
        the flagged junctions, sent as `crossings_complete: false`, so the chart never says
        "No major intersections ahead" from a flagged-only list."""
        router(standard_router())
        full = post(client, good_body("mass-ride")).json()["profile"]
        assert full["crossings_complete"] is True

        def broken(*_args):
            raise RuntimeError("boom")

        monkeypatch.setattr(core_junctions, "major_crossings", broken)
        response = post(client, good_body("mass-ride"))
        assert response.status_code == 200
        profile = response.json()["profile"]
        assert isinstance(profile["crossings"], list)
        assert profile["crossings"] == [c for c in full["crossings"] if c["kind"] == "flagged"]
        assert profile["crossings_complete"] is False

    def test_on_an_older_table_a_mass_rides_width_comes_from_the_segments_lanes(
        self, client, segments, router, monkeypatch
    ) -> None:
        """Mutation review, finding 4: on a table built before `mass_usable_width_m`, the
        estimate's `road_lanes` reach the width end to end. Way 101 is a 2-lane one-way
        (6.7 m: 198 a minute; one lane a direction would be 99), way 202 a street of 2 lanes
        a direction, two-way: its own side only (OWNER-DECISIONS 406), 6.7 m, 198 (it was
        13.4 m, 396, before the rebuild bundle), and way 303 has no segment row (not known).
        Level all the way, so no grade factor."""
        with connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE {segments}.segment DROP COLUMN mass_usable_width_m")
        monkeypatch.setattr(routing, "_capacity_column_seen", False)
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {segments}.segment SET road_lanes = 2, road_oneway = true"
                " WHERE osm_way_id = 101"
            )
            cursor.execute(
                f"UPDATE {segments}.segment SET road_lanes = 2, road_oneway = false"
                " WHERE osm_way_id = 202"
            )
        answers = standard_router()
        answers.answers["route"] = route_answer([(VERTICES, 2.2, [10.0] * 75)])
        router(answers)
        response = post(client, good_body("mass-ride"))
        assert response.status_code == 200
        profile = response.json()["profile"]
        at = dict(zip(profile["m"], profile["riders_per_min"], strict=True))
        assert at[450] == 198
        assert at[1290] == 198
        assert at[2010] is None
        assert profile["unchecked"] == [] and profile["avoid"] == []

    def test_nothing_about_the_request_needs_or_makes_a_session(
        self, client, segments, router
    ) -> None:
        """Owner decision of 2026-09-26: planning works signed out, and a
        signed-out plan is not saved."""
        router(standard_router())
        response = post(client, good_body())
        assert response.status_code == 200
        assert settings.SESSION_COOKIE_NAME not in response.cookies

    def test_the_answer_carries_the_public_tier_attribution(self, client, segments, router) -> None:
        router(standard_router())
        credits = " | ".join(post(client, good_body()).json()["attribution"])
        assert "OpenStreetMap" in credits and "ODbL" in credits
        assert "CC BY 4.0" in credits
        assert "VDOT" in credits

    def test_multi_leg_geometry_is_one_line_with_no_repeated_joint(
        self, client, segments, router
    ) -> None:
        first, second = VERTICES[:3], VERTICES[2:]
        router(
            FakeRouter(
                {
                    "route": route_answer([(first, 1.0, [1.0]), (second, 1.0, [1.0])]),
                    "trace_attributes": [
                        trace_answer(first, [(101, 0, 2, 1.0)]),
                        trace_answer(second, [(303, 0, 2, 1.0)]),
                    ],
                }
            )
        )
        body = {"points": [list(VERTICES[0]), list(VERTICES[2]), list(VERTICES[4])]}
        answer = post(client, {**body, "preset": "default"}).json()
        assert answer["geometry"]["coordinates"] == [list(v) for v in VERTICES]

    def test_leg_ends_mark_where_each_leg_finishes_in_the_line(
        self, client, segments, router
    ) -> None:
        """The front end inserts a via dragged off the line into the leg that
        was grabbed; the leg boundaries are the router's, not a guess."""
        legs = [VERTICES[:2], VERTICES[1:4], VERTICES[3:]]
        router(
            FakeRouter(
                {
                    "route": route_answer([(leg, 1.0, [1.0]) for leg in legs]),
                    "trace_attributes": [trace_answer(leg, [(101, 0, 1, 1.0)]) for leg in legs],
                }
            )
        )
        body = {"points": [list(VERTICES[i]) for i in (0, 1, 3, 4)], "preset": "default"}
        answer = post(client, body).json()
        coordinates = answer["geometry"]["coordinates"]
        ends = answer["leg_ends"]
        assert len(ends) == len(body["points"]) - 1
        assert ends == sorted(ends)
        assert ends[-1] == len(coordinates) - 1
        for end, leg in zip(ends, legs, strict=True):
            assert coordinates[end] == list(leg[-1])

    def test_a_one_leg_route_ends_its_leg_at_the_last_vertex(
        self, client, segments, router
    ) -> None:
        router(standard_router())
        answer = post(client, good_body()).json()
        assert answer["leg_ends"] == [len(answer["geometry"]["coordinates"]) - 1]


@db
class TestStressBreakdown:
    def test_each_tier_gets_the_metres_ridden_on_it(self, client, segments, router) -> None:
        router(standard_router())
        stress = post(client, good_body()).json()["stress_m"]
        assert stress == pytest.approx(STANDARD_EXPECTED, abs=0.2)

    def test_the_breakdown_accounts_for_the_whole_trace(self, client, segments, router) -> None:
        router(standard_router())
        stress = post(client, good_body()).json()["stress_m"]
        assert sum(stress.values()) == pytest.approx(1000 * sum(e[3] for e in STANDARD_EDGES))

    def test_an_out_and_back_counts_both_traversals(self, client, segments, router) -> None:
        """PLAN, Preprocessing pipeline: the join is per traversal instance, so
        riding a way twice reports twice its length."""
        there_and_back = [VERTICES[0], VERTICES[1], VERTICES[0]]
        router(
            FakeRouter(
                {
                    "route": route_answer([(there_and_back, 1.8, [1.0])]),
                    "trace_attributes": trace_answer(
                        there_and_back, [(101, 0, 1, 0.9), (101, 1, 2, 0.9)]
                    ),
                }
            )
        )
        body = {"points": [list(VERTICES[0]), list(VERTICES[1]), list(VERTICES[0])]}
        stress = post(client, {**body, "preset": "default"}).json()["stress_m"]
        assert stress["3"] == pytest.approx(1800.0, abs=0.2)

    def test_a_trace_the_router_refuses_to_edge_walk_falls_back_to_map_snap(
        self, client, segments, router
    ) -> None:
        fake = router(
            FakeRouter(
                {
                    "route": route_answer([(VERTICES, 2.2, [1.0])]),
                    "trace_attributes": [
                        routing.RouterRefused(400, 443, "no edge walk"),
                        trace_answer(VERTICES, STANDARD_EDGES),
                    ],
                }
            )
        )
        stress = post(client, good_body()).json()["stress_m"]
        matches = [p["shape_match"] for url, p in fake.calls if url.endswith("trace_attributes")]
        assert matches == ["edge_walk", "map_snap"]
        assert stress == pytest.approx(STANDARD_EXPECTED, abs=0.2)

    def test_a_leg_that_cannot_be_traced_is_unknown_not_guessed(
        self, client, segments, router
    ) -> None:
        router(
            FakeRouter(
                {
                    "route": route_answer([(VERTICES, 2.2, [1.0])]),
                    "trace_attributes": [
                        routing.RouterRefused(400, 443, "no"),
                        routing.RouterRefused(400, 444, "no"),
                    ],
                }
            )
        )
        response = post(client, good_body())
        assert response.status_code == 200
        stress = response.json()["stress_m"]
        assert stress["unknown"] == pytest.approx(2200.0)
        assert sum(v for k, v in stress.items() if k != "unknown") == 0
        assert response.json()["stress_spans"] == [
            {
                "from_m": 0,
                "to_m": 2200,
                "tier": None,
                "facility": None,
                "unpaved": None,
                "rpm": None,
            }
        ]
        # And the facility breakdown, which must sum to the same distance
        # (mutation review r1, RT15).
        facility = response.json()["facility_m"]
        assert facility["unknown"] == pytest.approx(2200.0)
        assert sum(v for k, v in facility.items() if k != "unknown") == 0


@db
class TestWhatIsSentToTheRouter:
    @pytest.mark.parametrize("name", sorted(presets.PRESETS))
    def test_every_call_goes_to_the_presets_variant(self, name, client, segments, router) -> None:
        """PLAN, Stats source: the trace goes to the same variant and costing
        as the route that produced the shape."""
        fake = router(standard_router())
        assert post(client, good_body(name)).status_code == 200
        base = settings.VALHALLA_UPSTREAMS[presets.variant_for_ride(name, routing.default_when())]
        preset = presets.PRESETS[name]
        middle = presets.costing(name, presets.stress_start(name), 0)
        if preset.hills < 0:
            # The avoid half asks for the same trip at the hills middle and
            # traces both, so a busier route gives way to the calmer one (the
            # owner, 2026-09-28: "Traffic wins").
            assert fake.endpoints()[:2] == ["route", "route"]
            assert set(fake.endpoints()[2:]) == {"trace_attributes"}
            assert fake.calls[1][1]["costing_options"] == middle
        elif name == "trailmaxxing":
            # The top of the slider offers other routes (OWNER-DECISIONS 265): once the route is
            # traced the router is asked for one more that avoids its roads, and the fake gives
            # the same route, which is no different, so the asking ends.
            assert fake.endpoints() == ["route", "trace_attributes", "route"]
        else:
            assert fake.endpoints() == ["route", "trace_attributes"]
        assert all(url.startswith(base + "/") for url, _ in fake.calls)
        assert all(p["costing_options"] in (presets.costing(name), middle) for _, p in fake.calls)
        assert fake.calls[0][1]["costing_options"] == presets.costing(name)
        assert all(p["costing"] == "bicycle" for _, p in fake.calls)

    def test_the_points_are_sent_in_order_as_lon_lat(self, client, segments, router) -> None:
        fake = router(standard_router())
        post(client, good_body())
        locations = fake.calls[0][1]["locations"]
        assert [(loc["lon"], loc["lat"]) for loc in locations] == [VERTICES[0], VERTICES[-1]]

    def test_the_route_asks_for_elevation_and_an_invariant_planning_time(
        self, client, segments, router
    ) -> None:
        fake = router(standard_router())
        post(client, good_body())
        request = fake.calls[0][1]
        assert request["elevation_interval"] > 0
        assert request["date_time"]["type"] == 3
        assert request["date_time"]["value"] == routing.planning_time(when=routing.default_when())


def refused_before_the_router(client, router, body, **kwargs) -> dict:
    fake = router(standard_router())
    response = post(client, body, **kwargs)
    assert response.status_code == 400, response.content
    assert fake.calls == []
    # The contract's shape for every error, not Ninja's own {"detail": ...}.
    assert set(response.json()) == {"error"}
    assert response.json()["error"]
    return response.json()


@db
class TestRefusedInput:
    """Each body is wrong for exactly one reason, and none reaches the router."""

    def test_one_point(self, client, router) -> None:
        assert "error" in refused_before_the_router(
            client, router, {"points": [list(VERTICES[0])], "preset": "default"}
        )

    def test_twenty_six_points(self, client, router) -> None:
        points = [[-77.05 + i * 0.001, LAT] for i in range(26)]
        refused_before_the_router(client, router, {"points": points, "preset": "default"})

    def test_twenty_five_points_are_accepted(self, client, segments, router) -> None:
        router(standard_router())
        points = [[-77.05 + i * 0.001, LAT] for i in range(25)]
        assert post(client, {"points": points, "preset": "default"}).status_code == 200

    @pytest.mark.parametrize(
        "point",
        [
            [settings.COVERAGE_BBOX[0] - 0.01, LAT],
            [-77.0, settings.COVERAGE_BBOX[1] - 0.01],
            [settings.COVERAGE_BBOX[2] + 0.01, LAT],
            [-77.0, settings.COVERAGE_BBOX[3] + 0.01],
        ],
        ids=["west", "south", "east", "north"],
    )
    def test_a_point_outside_the_coverage_box(self, point, client, router) -> None:
        refused_before_the_router(
            client, router, {"points": [list(VERTICES[0]), point], "preset": "default"}
        )

    @pytest.mark.parametrize("corner", ["south-west", "north-east"])
    def test_the_coverage_edges_are_inside(self, corner, client, segments, router) -> None:
        """Corner by corner, with a short hop inward, because corner to corner
        is longer than one request may be."""
        router(standard_router())
        west, south, east, north = settings.COVERAGE_BBOX
        if corner == "south-west":
            points = [[west, south], [west + 0.01, south + 0.01]]
        else:
            points = [[east, north], [east - 0.01, north - 0.01]]
        assert post(client, {"points": points, "preset": "default"}).status_code == 200

    def test_lat_lon_order_is_refused_not_misread(self, client, router) -> None:
        """[lat, lon] for a DC point is far outside the box in both axes."""
        refused_before_the_router(
            client, router, {"points": [[LAT, -77.05], [LAT, -77.02]], "preset": "default"}
        )

    def test_an_unknown_preset(self, client, router) -> None:
        refused_before_the_router(client, router, {**good_body(), "preset": "night"})

    def test_a_missing_preset(self, client, router) -> None:
        refused_before_the_router(client, router, {"points": good_body()["points"]})

    def test_a_point_with_three_numbers(self, client, router) -> None:
        points = [[*VERTICES[0], 10.0], list(VERTICES[-1])]
        refused_before_the_router(client, router, {"points": points, "preset": "default"})

    def test_not_a_number(self, client, router) -> None:
        """Python's json module reads NaN; it must not reach the router."""
        body = '{"points": [[NaN, 38.9], [-77.02, 38.9]], "preset": "default"}'
        refused_before_the_router(client, router, body)

    def test_an_unexpected_field(self, client, router) -> None:
        refused_before_the_router(client, router, {**good_body(), "save": True})

    def test_malformed_json(self, client, router) -> None:
        refused_before_the_router(client, router, '{"points": [[-77.05, 38.9], ')

    def test_a_body_that_is_not_an_object(self, client, router) -> None:
        refused_before_the_router(client, router, "[1, 2]")

    def test_an_oversized_body(self, client, router) -> None:
        body = json.dumps(good_body()) + " " * 9000
        refused_before_the_router(client, router, body)

    def test_a_body_that_is_not_json_typed(self, client, router) -> None:
        refused_before_the_router(
            client, router, json.dumps(good_body()), content_type="text/plain"
        )

    def test_a_refusal_names_the_problem_field(self, client, router) -> None:
        error = refused_before_the_router(client, router, {**good_body(), "preset": "x"})["error"]
        assert "preset" in error

    @pytest.mark.parametrize("problem", ["outside", "too-long"])
    def test_a_validators_own_sentence_comes_without_pydantics_prefix(
        self, problem, client, router
    ) -> None:
        """Follow-up to the front-end re-check: a 201 km plan read "Points:
        Value error, the route is too long ...". The API wrote that sentence
        itself; the field path and Pydantic's "Value error," are for a
        developer, and the rider saw them."""
        from core.api import MAX_SPAN_M

        if problem == "outside":
            west = settings.COVERAGE_BBOX[0]
            points = [list(VERTICES[0]), [west - 0.01, LAT]]
        else:
            points = bouncing(MAX_SPAN_M / 1000 + 1)
        error = refused_before_the_router(
            client, router, {"points": points, "preset": "default", "confirm_long": True}
        )["error"]
        assert "value error" not in error.lower(), error
        assert not error.startswith("points"), error
        assert ":" not in error.split(" ")[0], error


@db
class TestRouterOutcomes:
    def test_no_path_is_422(self, client, router) -> None:
        router(FakeRouter({"route": routing.RouterRefused(400, 442, "No path could be found")}))
        response = post(client, good_body())
        assert response.status_code == 422
        assert response.json()["error"]

    def test_a_no_trail_no_route_says_why(self, client, router) -> None:
        """PLAN, Routing model: a no-route result on the no-trail variant
        reports the disconnection rather than failing blankly."""
        router(FakeRouter({"route": routing.RouterRefused(400, 442, "No path could be found")}))
        standard = post(client, good_body("default")).json()["error"]
        router(FakeRouter({"route": routing.RouterRefused(400, 442, "No path could be found")}))
        no_trail = post(client, good_body("mass-ride")).json()["error"]
        assert no_trail != standard
        assert no_trail.startswith(standard)

    def test_both_no_path_codes_tell_the_crossing_story(self, client, router) -> None:
        """Valhalla answers 442 or 443 for no path, depending on where the
        search gave up; either can be the no-trail variant's missing crossing."""
        router(FakeRouter({"route": routing.RouterRefused(400, 442, "No path")}))
        explained = post(client, good_body("mass-ride")).json()["error"]
        router(FakeRouter({"route": routing.RouterRefused(400, 443, "No path")}))
        response = post(client, good_body("mass-ride"))
        assert response.status_code == 422
        assert response.json()["error"] == explained

    def test_no_legs_on_mass_ride_tells_no_crossing_story(self, client, router) -> None:
        """An empty answer is not the router saying there is no path."""
        router(FakeRouter({"route": routing.RouterRefused(400, 442, "No path")}))
        explained = post(client, good_body("mass-ride")).json()["error"]
        router(FakeRouter({"route": {"trip": {"legs": []}}}))
        response = post(client, good_body("mass-ride"))
        assert response.status_code == 422
        assert response.json()["error"] != explained

    @pytest.mark.parametrize("preset", ["default", "mass-ride"])
    @pytest.mark.parametrize("code", list(range(150, 160)))
    def test_a_router_limit_is_the_callers_too_long(self, code, preset, client, router) -> None:
        """154 is "Path distance exceeds the max distance limit": the request
        asked for too much, which is a 400 and not a missing crossing."""
        router(FakeRouter({"route": routing.RouterRefused(400, code, "exceeds a limit")}))
        response = post(client, good_body(preset))
        assert response.status_code == 400
        assert set(response.json()) == {"error"}
        assert "roadway" not in response.json()["error"]

    @pytest.mark.parametrize("code", [149, 160, 171, 999, None])
    def test_other_refusals_are_no_route_without_the_crossing_story(
        self, code, client, router
    ) -> None:
        """Only "no path" means the no-trail variant may have run out of
        crossings; no road near a point, or an unknown refusal, does not."""
        router(FakeRouter({"route": routing.RouterRefused(400, 442, "No path")}))
        explained = post(client, good_body("mass-ride")).json()["error"]
        router(FakeRouter({"route": routing.RouterRefused(400, code, "something else")}))
        response = post(client, good_body("mass-ride"))
        assert response.status_code == 422
        assert response.json()["error"] != explained
        assert explained.startswith(response.json()["error"])

    def test_an_answer_with_no_legs_is_no_route(self, client, router) -> None:
        router(FakeRouter({"route": {"trip": {"legs": []}}}))
        assert post(client, good_body()).status_code == 422

    def test_a_router_that_does_not_answer_is_502(self, client, router) -> None:
        router(FakeRouter({"route": routing.RouterUnavailable("connection refused")}))
        response = post(client, good_body())
        assert response.status_code == 502
        assert response.json()["error"]

    def test_a_router_that_fails_mid_trace_is_502(self, client, segments, router) -> None:
        router(
            FakeRouter(
                {
                    "route": route_answer([(VERTICES, 2.2, [1.0])]),
                    "trace_attributes": routing.RouterUnavailable("gone"),
                }
            )
        )
        assert post(client, good_body()).status_code == 502


@db
class TestRateLimit:
    def test_the_sixty_first_request_in_a_minute_is_429(self, client, segments, router) -> None:
        from core.ratelimit import ROUTING

        fake = router(standard_router())
        fake.answers["route"] = [fake.answers["route"]] * (2 * ROUTING.requests + 5)
        fake.answers["trace_attributes"] = [fake.answers["trace_attributes"]] * (
            2 * ROUTING.requests + 5
        )

        def attempt(n):
            headers = {"HTTP_X_FORWARDED_FOR": f"198.51.100.{7 + 100 * n}"}
            statuses = [
                post(client, good_body(), **headers).status_code for _ in range(ROUTING.requests)
            ]
            calls_before = len(fake.calls)
            return statuses, calls_before, post(client, good_body(), **headers)

        statuses, calls_before, refused = in_one_window(ROUTING.window_s, attempt)
        assert statuses == [200] * ROUTING.requests
        assert refused.status_code == 429
        assert 1 <= int(refused["Retry-After"]) <= ROUTING.window_s
        assert refused.json()["error"]
        assert len(fake.calls) == calls_before

        other = post(client, good_body(), HTTP_X_FORWARDED_FOR="198.51.100.8")
        assert other.status_code == 200

    def test_malformed_json_spends_the_budget(self, client, router) -> None:
        """Otherwise a flood of bad bodies is free. Only a script can send a
        JSON-typed body, so counting it costs no visitor anything."""
        from core.ratelimit import ROUTING

        router(standard_router())

        def attempt(n):
            headers = {"HTTP_X_FORWARDED_FOR": f"198.51.100.{9 + 100 * n}"}
            for _ in range(ROUTING.requests):
                post(client, "{", **headers)
            return post(client, good_body(), **headers).status_code

        assert in_one_window(ROUTING.window_s, attempt) == 429

    def test_a_cross_site_simple_post_does_not_spend_the_budget(
        self, client, segments, router
    ) -> None:
        """A page on any site can make a visitor's browser send a text/plain or
        form POST here without a preflight. Counting those would let it spend
        the visitor's routing budget; they are refused before the count."""
        from core.ratelimit import ROUTING

        router(standard_router())
        headers = {"HTTP_X_FORWARDED_FOR": "198.51.100.10"}
        body = json.dumps(good_body())
        for content_type in ("text/plain", "application/x-www-form-urlencoded"):
            for _ in range(ROUTING.requests + 5):
                assert post(client, body, content_type=content_type, **headers).status_code == 400
        assert post(client, good_body(), **headers).status_code == 200

    def test_the_routing_limit_is_the_plans(self) -> None:
        """PLAN, Moderation and abuse limits: routing 60 per minute, and the
        unauthenticated paths 60 per minute per client address."""
        from core.ratelimit import ROUTING

        assert (ROUTING.requests, ROUTING.window_s) == (60, 60)


def test_the_route_is_in_the_openapi_schema(client) -> None:
    """PLAN, Backend: the front end's TypeScript types are generated from it."""
    schema = client.get("/api/openapi.json").json()
    operation = schema["paths"][ROUTE_PATH]["post"]
    assert {"200", "400", "422", "429", "500", "502", "503"} <= set(operation["responses"])
    assert settings.ADMIN_PATH.strip("/") not in json.dumps(schema)


def test_the_interactive_docs_are_not_served(client) -> None:
    """They load their script from a third-party CDN, which the planned
    Content-Security-Policy of `default-src 'self'` refuses."""
    assert client.get("/api/docs").status_code == 404


class TestPlanningTime:
    ZONE = ZoneInfo("America/New_York")

    @pytest.mark.parametrize(
        "now",
        [
            datetime(2026, 9, 26, 8, 59, tzinfo=ZONE),  # Saturday, before nine
            datetime(2026, 9, 26, 9, 0, tzinfo=ZONE),  # Saturday, at nine
            datetime(2026, 9, 27, 12, 0, tzinfo=ZONE),  # Sunday
            datetime(2026, 10, 2, 23, 30, tzinfo=ZONE),  # Friday night
            datetime(2026, 11, 1, 1, 30, tzinfo=ZONE),  # the autumn clock change
        ],
    )
    def test_it_is_the_next_saturday_at_nine_local(self, now) -> None:
        value = datetime.strptime(routing.planning_time(now), "%Y-%m-%dT%H:%M").replace(
            tzinfo=self.ZONE
        )
        assert value.weekday() == 5
        assert (value.hour, value.minute) == (9, 0)
        assert now < value <= now + timedelta(days=7)


class TestPolyline:
    def test_it_decodes_what_valhalla_encodes(self) -> None:
        line = [(-77.043400, 38.909700), (-77.0091, 38.8899), (-76.612, 39.29)]
        assert routing.decode_polyline6(encode_polyline6(line)) == pytest.approx(line)

    def test_the_empty_shape_is_no_points(self) -> None:
        assert routing.decode_polyline6("") == []


class _Handler(http.server.BaseHTTPRequestHandler):
    status = 200
    body = b"{}"

    def do_POST(self) -> None:  # noqa: N802 - the stdlib's name
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def server():
    started = []

    def start(status: int, body: bytes):
        handler = type("H", (_Handler,), {"status": status, "body": body})
        httpd = http.server.HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        started.append(httpd)
        return f"http://127.0.0.1:{httpd.server_port}/route"

    yield start
    for httpd in started:
        httpd.shutdown()


class TestTransport:
    def test_a_success_is_its_json(self, server) -> None:
        url = server(200, b'{"trip": {}}')
        assert routing._transport(url, {"a": 1}, 5) == {"trip": {}}

    def test_a_client_error_is_a_refusal_with_valhallas_code(self, server) -> None:
        url = server(400, b'{"error_code": 442, "error": "No path could be found"}')
        with pytest.raises(routing.RouterRefused) as refused:
            routing._transport(url, {}, 5)
        assert (refused.value.status, refused.value.code) == (400, 442)

    def test_a_server_error_is_unavailable(self, server) -> None:
        with pytest.raises(routing.RouterUnavailable):
            routing._transport(server(500, b"oops"), {}, 5)

    def test_a_body_that_is_not_json_is_unavailable(self, server) -> None:
        with pytest.raises(routing.RouterUnavailable):
            routing._transport(server(200, b"<html>"), {}, 5)

    def test_nobody_listening_is_unavailable(self) -> None:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        with pytest.raises(routing.RouterUnavailable):
            routing._transport(f"http://127.0.0.1:{port}/route", {}, 5)

    def test_a_router_that_hangs_is_unavailable(self) -> None:
        with socket.socket() as silent:
            silent.bind(("127.0.0.1", 0))
            silent.listen()
            port = silent.getsockname()[1]
            with pytest.raises(routing.RouterUnavailable):
                routing._transport(f"http://127.0.0.1:{port}/route", {}, 0.5)


def test_climb_of_a_flat_profile_is_zero() -> None:
    assert routing.climb_and_descent([12.0] * 50) == (0.0, 0.0)


def test_missing_elevations_are_skipped_not_zeroed() -> None:
    """A null sample read as 0 m would add the whole height back as climb."""
    climb, descent = routing.climb_and_descent([100.0, None, 101.0, None, 100.0])
    assert (climb, descent) == (0.0, 0.0)
    assert not math.isnan(climb)


# --- Review round 1: the properties the first suite left unasserted -------------------

# Way 909 has two segments of different tiers, and one edge spans both, with
# the first stretch twice as long on the ground as the second.
UNEVEN = [(-77.05, LAT), (-77.03, LAT), (-77.02, LAT)]


@pytest.fixture
def uneven_way(segments):
    with connection.cursor() as cursor:
        for ordinal, tier, line in ((0, 2, UNEVEN[0:2]), (1, 3, UNEVEN[1:3])):
            wkt = "LINESTRING(" + ", ".join(f"{lon} {lat}" for lon, lat in line) + ")"
            cursor.execute(
                f"INSERT INTO {segments}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                "stress_rule) VALUES (909, %s, ST_GeomFromText(%s, 4326), %s, 'test')",
                [ordinal, wkt, tier],
            )
    return segments


def one_edge_router(vertices, edges, length_km: float = 1.5) -> FakeRouter:
    return FakeRouter(
        {
            "route": route_answer([(vertices, length_km, [1.0])]),
            "trace_attributes": trace_answer(vertices, edges),
        }
    )


@db
class TestApportioning:
    def test_an_edge_over_two_segments_is_split_by_ground_length(
        self, client, uneven_way, router
    ) -> None:
        """PLAN, Stats source: "apportioning length where an edge spans several
        segments". The reported 1.5 km is shared 2:1, as the ground is."""
        router(one_edge_router(UNEVEN, [(909, 0, 2, 1.5)]))
        stress = post(client, good_body()).json()["stress_m"]
        assert stress["2"] == pytest.approx(1000.0, abs=0.5)
        assert stress["3"] == pytest.approx(500.0, abs=0.5)

    def test_an_edge_with_no_ground_length_keeps_its_length(self, client, segments, router) -> None:
        """Two shape vertices at one place: the edge's reported length still
        belongs to the route, on that place's segment."""
        vertices = [VERTICES[0], (-77.045, LAT), (-77.045, LAT)]
        router(one_edge_router(vertices, [(101, 0, 1, 0.4), (101, 1, 2, 0.2)], 0.6))
        stress = post(client, good_body()).json()["stress_m"]
        assert stress["3"] == pytest.approx(600.0, abs=0.5)

    def test_an_edge_on_a_single_vertex_keeps_its_length(self, client, segments, router) -> None:
        vertices = [VERTICES[0], (-77.045, LAT)]
        router(one_edge_router(vertices, [(101, 0, 1, 0.4), (101, 1, 1, 0.1)], 0.5))
        stress = post(client, good_body()).json()["stress_m"]
        assert stress["3"] == pytest.approx(500.0, abs=0.5)

    @pytest.mark.parametrize("begin, end", [(0, 2), (1, 0), (-1, 1)])
    def test_an_edge_outside_the_shape_is_skipped_not_guessed(
        self, begin, end, client, segments, router
    ) -> None:
        """Indices that do not describe a run of the returned shape - one past
        its end, reversed - are a response this module does not understand."""
        vertices = [VERTICES[0], (-77.045, LAT)]
        if begin < 0:
            edges = [(101, 0, 1, 0.4)]
        else:
            edges = [(101, 0, 1, 0.4), (202, begin, end, 0.3)]
        router(one_edge_router(vertices, edges, 0.7))
        response = post(client, good_body())
        assert response.status_code == 200
        assert sum(response.json()["stress_m"].values()) == pytest.approx(400.0, abs=0.5)


@db
class TestMultiLegStress:
    def test_every_legs_stress_is_counted_and_a_failed_leg_is_its_own_length(
        self, client, segments, router
    ) -> None:
        first, second = VERTICES[:2], VERTICES[3:]
        router(
            FakeRouter(
                {
                    "route": route_answer([(first, 0.9, [1.0]), (second, 1.0, [1.0])]),
                    "trace_attributes": [
                        trace_answer(first, [(101, 0, 1, 0.9)]),
                        routing.RouterRefused(400, 443, "no"),
                        routing.RouterRefused(400, 444, "no"),
                    ],
                }
            )
        )
        points = [list(VERTICES[0]), list(VERTICES[1]), list(VERTICES[4])]
        stress = post(client, {"points": points, "preset": "default"}).json()["stress_m"]
        assert stress["3"] == pytest.approx(900.0, abs=0.5)
        assert stress["unknown"] == pytest.approx(1000.0, abs=0.5)

    def test_two_traced_legs_both_count(self, client, segments, router) -> None:
        first, second = VERTICES[:2], VERTICES[1:3]
        router(
            FakeRouter(
                {
                    "route": route_answer([(first, 0.9, [1.0]), (second, 0.4, [1.0])]),
                    "trace_attributes": [
                        trace_answer(first, [(101, 0, 1, 0.9)]),
                        trace_answer(second, [(202, 0, 1, 0.4)]),
                    ],
                }
            )
        )
        points = [list(VERTICES[0]), list(VERTICES[1]), list(VERTICES[2])]
        stress = post(client, {"points": points, "preset": "default"}).json()["stress_m"]
        assert stress["3"] == pytest.approx(900.0, abs=0.5)
        assert stress["1"] == pytest.approx(400.0, abs=0.5)


@db
class TestTheTraceRequest:
    def test_it_asks_for_what_the_join_reads(self, client, segments, router) -> None:
        """The fake answers whatever it is asked, so the request itself is what
        holds the join's inputs: the way id, the lengths and the shape."""
        fake = router(standard_router())
        post(client, good_body())
        trace = [p for url, p in fake.calls if url.endswith("trace_attributes")][0]
        assert trace["filters"]["action"] == "include"
        assert {
            "edge.way_id",
            "edge.length",
            "edge.begin_shape_index",
            "edge.end_shape_index",
            "shape",
        } <= set(trace["filters"]["attributes"])

    def test_every_point_is_a_break(self, client, segments, router) -> None:
        """Break locations are what make one leg per point, which the per-leg
        trace and the elevation profile depend on."""
        fake = router(standard_router())
        post(client, good_body())
        assert {loc["type"] for loc in fake.calls[0][1]["locations"]} == {"break"}

    @pytest.mark.parametrize("name", sorted(presets.PRESETS))
    def test_the_answer_names_the_variant_that_routed_it(
        self, name, client, segments, router
    ) -> None:
        router(standard_router())
        body = post(client, good_body(name)).json()
        assert body["variant"] == presets.variant_for_ride(name, routing.default_when())
        assert body["preset"] == name


class Clock:
    """A monotonic clock the fake router can move."""

    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(routing, "time", fake)
    return fake


def timed(clock, fake, durations):
    """`fake`, with each call taking `durations[endpoint]` seconds on `clock`
    (a number, or a list consumed in order). A call longer than its timeout
    moves the clock by the timeout and raises RouterUnavailable, as a socket
    timeout does. The timeouts given are kept in `.timeouts`."""

    def call(url, payload, timeout):
        call.timeouts.append(timeout)
        took = durations.get(url.rsplit("/", 1)[1], 0.0)
        if isinstance(took, list):
            took = took.pop(0)
        if took > timeout:
            clock.now += timeout
            raise routing.RouterUnavailable("timed out")
        clock.now += took
        return fake(url, payload, timeout)

    call.timeouts = []
    return call


def arrives_late(monkeypatch, clock, seconds: float) -> None:
    """The request spends `seconds` in the per-minute count, before any
    routing starts, as a loaded host or a swapped-out worker makes it."""
    from core import ratelimit

    real = ratelimit.hit

    def slow_hit(limit, client):
        clock.now += seconds
        return real(limit, client)

    monkeypatch.setattr(ratelimit, "hit", slow_hit)


# The routers' window: what is left of a budget once the answer's share is kept back.
WINDOW_S = routing.PLAN_BUDGET_S - routing.ANSWER_RESERVE_S
LONG_WINDOW_S = routing.LONG_PLAN_BUDGET_S - routing.ANSWER_RESERVE_S


@db
class TestTimeBudget:
    def test_every_call_has_a_finite_timeout_under_gunicorns(
        self, client, segments, router
    ) -> None:
        timeouts = []
        fake = standard_router()

        def recording(url, payload, timeout):
            timeouts.append(timeout)
            return fake(url, payload, timeout)

        router(recording)
        assert post(client, good_body()).status_code == 200
        assert timeouts
        assert all(timeout is not None and 0 < timeout < 60 for timeout in timeouts)

    def test_the_budget_is_under_gunicorns_timeout(self) -> None:
        assert 0 < routing.PLAN_BUDGET_S < 60
        assert 0 < routing.ROUTER_TIMEOUT_S <= WINDOW_S

    def test_a_late_call_gets_only_what_is_left(self, client, segments, router, clock) -> None:
        call = router(timed(clock, standard_router(), {"route": WINDOW_S - 5}))
        assert post(client, good_body()).status_code == 200
        assert call.timeouts[0] == routing.ROUTER_TIMEOUT_S
        assert call.timeouts[1] == pytest.approx(5.0)

    @pytest.mark.parametrize("long_ride", [False, True])
    def test_the_budget_starts_when_the_request_arrives(
        self, long_ride, client, segments, router, clock, monkeypatch
    ) -> None:
        """Review round 3: the clock started inside the planner, so time spent
        before it - the count, the slots, a worker swapped out - came on top of
        the budget and ate into gunicorn's margin."""
        arrives_late(monkeypatch, clock, 10)
        call = router(timed(clock, long_router(), {}))
        body = long_body(160, confirm_long=True) if long_ride else good_body()
        assert post(client, body).status_code == 200
        window = LONG_WINDOW_S if long_ride else WINDOW_S
        assert call.timeouts[0] == pytest.approx(window - 10)

    @pytest.mark.parametrize("long_ride", [False, True])
    def test_the_budget_counts_time_spent_in_djangos_middleware(
        self, long_ride, client, segments, router, clock, monkeypatch
    ) -> None:
        """API re-check should-fix 1: the budget was stamped at the view
        wrapper, after the middleware (a signed-in request's session read
        among them), and one request took 41.34 s by gunicorn's clock against
        a 40 s budget. The stamp is now taken by the first middleware."""
        from core.middleware import SessionEpochMiddleware

        real = SessionEpochMiddleware.__call__

        def slow(self, request):
            clock.now += 10
            return real(self, request)

        monkeypatch.setattr(SessionEpochMiddleware, "__call__", slow)
        call = router(timed(clock, long_router(), {}))
        body = long_body(160, confirm_long=True) if long_ride else good_body()
        assert post(client, body).status_code == 200
        window = LONG_WINDOW_S if long_ride else WINDOW_S
        assert call.timeouts[0] == pytest.approx(window - 10)

    def test_the_request_clock_is_the_first_middleware(self) -> None:
        assert settings.MIDDLEWARE[0] == "core.middleware.RequestClockMiddleware"

    @pytest.mark.parametrize("long_ride", [False, True])
    def test_no_router_call_runs_into_the_answers_reserve(
        self, long_ride, client, segments, router, clock
    ) -> None:
        """However the router behaves, the last call ends where the window
        ends, leaving the reserve for the stress join and the answer."""
        start = clock.now
        took = (LONG_WINDOW_S if long_ride else WINDOW_S) - 3
        router(timed(clock, long_router(), {"route": took, "trace_attributes": 1000.0}))
        body = long_body(160, confirm_long=True) if long_ride else good_body()
        assert post(client, body).status_code == 200
        budget = routing.LONG_PLAN_BUDGET_S if long_ride else routing.PLAN_BUDGET_S
        assert clock.now - start == pytest.approx(budget - routing.ANSWER_RESERVE_S)

    def test_an_ordinary_route_may_take_longer_than_twenty_seconds(
        self, client, segments, router, clock
    ) -> None:
        """Review round 3 (spec): a Mass Ride loop of 169 km spanning 141 km -
        no long ride - took 20.8 s and 23.5 s on /route with the host loaded,
        and a fixed 20 s per call made it a 502 with most of the budget left."""
        router(timed(clock, standard_router(), {"route": 25.0}))
        # At the hills middle, so no alternatives are asked for: a request for
        # them has ALTERNATES_TIMEOUT_S (tests/test_route_dials.py).
        assert post(client, {**good_body("mass-ride"), "hills": 0}).status_code == 200

    def test_a_route_that_ends_the_budget_is_503_with_retry_after(
        self, client, segments, router, clock
    ) -> None:
        call = router(timed(clock, standard_router(), {"route": 1000.0}))
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(routing, "ROUTER_TIMEOUT_S", routing.PLAN_BUDGET_S + 10)
            response = post(client, good_body())
        assert response.status_code == 503
        assert int(response["Retry-After"]) >= 1
        assert set(response.json()) == {"error"}
        assert len(call.timeouts) == 1, "no call is started once the budget is gone"

    def test_a_plan_past_its_budget_skips_the_joins_and_says_how_long_each_phase_took(
        self, client, segments, router, clock, caplog
    ) -> None:
        """Correctness review, 2026-09-28: one request took 49 s and nothing
        after the router calls was bounded. Past the budget the joins are
        skipped (stress unknown) and a warning names each phase."""
        fake = standard_router()
        # An adjustment on the route, so a join run past the budget would show.
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {segments}.segment SET stress_adjustment_id = 'a-stretch' "
                "WHERE osm_way_id = 101"
            )

        def slow_trace(url, payload, timeout):
            if url.endswith("/trace_attributes"):
                clock.now += routing.PLAN_BUDGET_S + 1
            return fake(url, payload, timeout)

        router(slow_trace)
        with caplog.at_level("WARNING", logger="core.routing"):
            response = post(client, {**good_body(), "hills": 0})
        assert response.status_code == 200
        body = response.json()
        assert body["stress_m"]["unknown"] == pytest.approx(body["distance_m"], rel=0.01)
        assert body["stress_adjustments"] == []
        # And the route is one unknown section, as its totals are.
        assert body["stress_spans"] == [
            {
                "from_m": 0,
                "to_m": 2200,
                "tier": None,
                "facility": None,
                "unpaved": None,
                "rpm": None,
            }
        ]
        assert any("past its" in r.message and "trace" in r.message for r in caplog.records)

    def test_a_route_answered_as_the_budget_ends_is_kept(
        self, client, segments, router, clock
    ) -> None:
        """A route found is not thrown away for want of time to trace it: its
        stress is unknown, and no trace is started."""
        fake = standard_router()

        def answers_late(url, payload, timeout):
            clock.now += WINDOW_S + 1
            return fake(url, payload, timeout)

        router(answers_late)
        response = post(client, good_body())
        assert response.status_code == 200
        stress = response.json()["stress_m"]
        assert stress["unknown"] == pytest.approx(2200.0)
        assert sum(stress.values()) == pytest.approx(2200.0)
        assert fake.endpoints() == ["route"]

    def test_legs_left_untraced_by_the_budget_are_unknown(
        self, client, segments, router, clock
    ) -> None:
        """The first leg traced in time keeps its tiers; the leg whose trace
        ran out of time and every leg after it count as unknown, untried."""
        legs = [VERTICES[:2], VERTICES[1:3], VERTICES[2:4]]
        fake = FakeRouter(
            {
                "route": route_answer(
                    [(legs[0], 0.9, [1.0]), (legs[1], 0.4, [1.0]), (legs[2], 0.6, [1.0])]
                ),
                "trace_attributes": [
                    trace_answer(legs[0], [(101, 0, 1, 0.9)]),
                    trace_answer(legs[1], [(202, 0, 1, 0.4)]),
                    trace_answer(legs[2], [(202, 0, 1, 0.6)]),
                ],
            }
        )
        call = router(timed(clock, fake, {"route": 1.0, "trace_attributes": [1.0, 1000.0, 1.0]}))
        points = [list(VERTICES[0]), list(VERTICES[1]), list(VERTICES[2]), list(VERTICES[3])]
        response = post(client, {"points": points, "preset": "default"})
        assert response.status_code == 200
        stress = response.json()["stress_m"]
        assert stress["3"] == pytest.approx(900.0, abs=0.5)
        assert stress["unknown"] == pytest.approx(1000.0, abs=0.5)
        assert len(call.timeouts) == 3, "the third leg is not tried"

    def test_a_timeout_inside_the_budget_is_still_502(
        self, client, segments, router, clock
    ) -> None:
        def hangs(url, payload, timeout):
            clock.now += 1
            raise routing.RouterUnavailable("refused")

        router(hangs)
        assert post(client, good_body()).status_code == 502

    def test_the_figures(self) -> None:
        """Written as numbers, because every other test here reads them from the
        module. An ordinary call may take nearly the whole window (35 of 37 s),
        because a loaded /route for a 169 km loop took 23.5 s; the answer keeps
        3 s for the stress join and the serialisation."""
        assert (routing.ROUTER_TIMEOUT_S, routing.PLAN_BUDGET_S) == (35, 40)
        assert routing.ANSWER_RESERVE_S == 3

    def test_gunicorns_timeout_leaves_ten_seconds_past_the_longest_budget(self) -> None:
        """The whole request is inside its budget, and the entrypoint's default
        GUNICORN_TIMEOUT must stay at least ten seconds past the longest one."""
        import re
        from pathlib import Path

        entrypoint = Path(settings.BASE_DIR) / "docker" / "api-entrypoint.sh"
        found = re.search(r"--timeout \"\$\{GUNICORN_TIMEOUT:-(\d+)\}\"", entrypoint.read_text())
        assert found is not None
        assert routing.LONG_PLAN_BUDGET_S + 10 <= int(found.group(1))


@db
class TestLongRideTime:
    """A confirmed long ride has more time than an ordinary plan. Measured on
    the real routers with the host loaded: a cold single-leg /route for
    Culpeper to Baltimore (150.4 km of straight line, 183 km routed) took
    43.9 s, the same request warm 9.5 s; the old 20 s per call made the first
    a 502."""

    def test_a_long_rides_router_call_may_take_the_long_timeout(
        self, client, segments, router, clock
    ) -> None:
        call = router(timed(clock, long_router(), {}))
        assert post(client, long_body(160, confirm_long=True)).status_code == 200
        assert call.timeouts[0] == routing.LONG_ROUTER_TIMEOUT_S
        assert routing.LONG_ROUTER_TIMEOUT_S > routing.ROUTER_TIMEOUT_S

    def test_a_signed_in_long_ride_has_the_long_timeout_too(
        self, client, segments, router, monkeypatch, clock
    ) -> None:
        from core.models import User

        call = router(timed(clock, long_router(), {}))
        sign_in(client, monkeypatch, User.objects.create(discord_user_id=4405))
        assert post(client, long_body(160)).status_code == 200
        assert call.timeouts[0] == routing.LONG_ROUTER_TIMEOUT_S

    def test_an_ordinary_plan_keeps_the_ordinary_timeout(
        self, client, segments, router, clock
    ) -> None:
        call = router(timed(clock, long_router(), {}))
        assert post(client, good_body()).status_code == 200
        assert call.timeouts[0] == routing.ROUTER_TIMEOUT_S

    def test_a_cold_long_leg_is_planned_and_traced(self, client, segments, router, clock) -> None:
        """The measured cold Culpeper-Baltimore /route, 43.9 s, fits."""
        router(timed(clock, long_router(), {"route": 43.9, "trace_attributes": 1.0}))
        response = post(client, long_body(160, confirm_long=True))
        assert response.status_code == 200
        assert response.json()["stress_m"]["3"] > 0, "and it is traced"

    @pytest.mark.parametrize(("took", "status"), [("ordinary", 200), ("long", 503)])
    def test_a_long_ride_has_the_long_budget(
        self, took, status, client, segments, router, clock
    ) -> None:
        """Past the ordinary budget a long ride is still planned; past its own
        it is the same 503 as any other."""
        seconds = routing.PLAN_BUDGET_S + 1 if took == "ordinary" else 1000.0
        router(timed(clock, long_router(), {"route": seconds}))
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(routing, "LONG_ROUTER_TIMEOUT_S", routing.LONG_PLAN_BUDGET_S + 10)
            response = post(client, long_body(160, confirm_long=True))
        assert response.status_code == status
        if status == 503:
            assert int(response["Retry-After"]) >= 1

    @pytest.mark.parametrize("long_ride", [False, True])
    def test_only_a_long_ride_that_ran_out_of_time_says_so_in_its_code(
        self, long_ride, client, segments, router, clock
    ) -> None:
        """Front-end re-check note: the planner resent a 503 with Retry-After
        up to three times, so one long ride past its budget held the long slot
        for minutes. A long ride's 503 carries its own code, which the planner
        shows at once instead of resending; an ordinary one is unchanged."""
        router(timed(clock, long_router(), {"route": 1000.0}))
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(routing, "ROUTER_TIMEOUT_S", routing.PLAN_BUDGET_S + 10)
            patch.setattr(routing, "LONG_ROUTER_TIMEOUT_S", routing.LONG_PLAN_BUDGET_S + 10)
            response = post(client, long_body(160, confirm_long=True) if long_ride else good_body())
        assert response.status_code == 503
        assert int(response["Retry-After"]) >= 1
        assert response.json()["error"]
        if long_ride:
            assert set(response.json()) == {"error", "code"}
            assert response.json()["code"] == "long_ride_timed_out"
        else:
            assert set(response.json()) == {"error"}

    def test_a_long_ride_refused_for_a_busy_slot_has_no_timed_out_code(
        self, client, segments, router, monkeypatch
    ) -> None:
        """The long slot being taken is a wait worth resending after; only a
        budget run out is not."""
        from core import ratelimit

        router(long_router())
        real = ratelimit.acquire

        def long_slot_taken(request, limit):
            if limit is ratelimit.LONG_ROUTING_IN_FLIGHT:
                return [], ratelimit._busy(503, 5, limit.deployment_busy)
            return real(request, limit)

        monkeypatch.setattr(ratelimit, "acquire", long_slot_taken)
        response = post(client, long_body(160, confirm_long=True))
        assert response.status_code == 503
        assert response.json()["error"] == ratelimit.LONG_ROUTING_IN_FLIGHT.deployment_busy
        assert "code" not in response.json()

    def test_a_late_long_call_gets_what_is_left_of_the_long_budget(
        self, client, segments, router, clock
    ) -> None:
        """Review round 3 (mutation, N92/N93): the long-budget mirror of
        test_a_late_call_gets_only_what_is_left."""
        call = router(timed(clock, long_router(), {"route": LONG_WINDOW_S - 5}))
        assert post(client, long_body(160, confirm_long=True)).status_code == 200
        assert call.timeouts[0] == routing.LONG_ROUTER_TIMEOUT_S
        assert call.timeouts[1] == pytest.approx(5.0)

    def test_the_long_figures(self) -> None:
        """Written as numbers; the owner's answer of 2026-09-26 is 50 s for a
        confirmed long ride. One call may take most of it."""
        assert (routing.LONG_ROUTER_TIMEOUT_S, routing.LONG_PLAN_BUDGET_S) == (45, 50)
        assert routing.LONG_ROUTER_TIMEOUT_S <= LONG_WINDOW_S


def spanning(km: float) -> list[list[float]]:
    """Two points on one parallel about `km` apart, inside the box."""
    import math as _m

    from routemaker.geo import EARTH_RADIUS_M

    degrees = km * 1000 / (EARTH_RADIUS_M * _m.cos(_m.radians(LAT))) * 180 / _m.pi
    return [[-77.9, LAT], [-77.9 + degrees, LAT]]


def bouncing(km: float) -> list[list[float]]:
    """Points bouncing along one parallel so the span is `km`, in legs of at
    most 100 km, which is how a span past the width of the box is built."""
    import math as _m

    legs = max(1, _m.ceil(km / 100))
    a, b = spanning(km / legs)
    return [a if i % 2 == 0 else b for i in range(legs + 1)]


def long_router() -> FakeRouter:
    fake = standard_router()
    fake.answers["route"] = [fake.answers["route"]] * 10
    fake.answers["trace_attributes"] = [fake.answers["trace_attributes"]] * 10
    return fake


@db
class TestLengthCap:
    def test_just_under_the_confirm_span_is_routed(self, client, segments, router) -> None:
        from core.api import CONFIRM_SPAN_M

        router(standard_router())
        body = {"points": spanning(CONFIRM_SPAN_M / 1000 - 0.5), "preset": "default"}
        assert post(client, body).status_code == 200

    def test_past_the_ceiling_is_too_long_however_it_is_asked(self, client, router) -> None:
        from core.api import MAX_SPAN_M

        body = {"points": bouncing(MAX_SPAN_M / 1000 + 1), "preset": "default"}
        refused_before_the_router(client, router, {**body, "confirm_long": True})

    def test_just_under_the_ceiling_is_planned_when_confirmed(
        self, client, segments, router
    ) -> None:
        from core.api import MAX_SPAN_M

        router(long_router())
        body = {"points": bouncing(MAX_SPAN_M / 1000 - 1), "preset": "default"}
        assert post(client, {**body, "confirm_long": True}).status_code == 200

    def test_the_confirm_span_is_150_km(self, client, segments, router) -> None:
        """In kilometres written out, so a change to the constant fails here."""
        router(long_router())
        assert post(client, {"points": spanning(149.5), "preset": "default"}).status_code == 200
        assert post(client, {"points": spanning(150.5), "preset": "default"}).status_code == 409

    def test_the_ceiling_is_200_km(self, client, segments, router) -> None:
        """The owner's answer of 2026-09-26: "200 km"."""
        router(long_router())
        under = {"points": bouncing(199.5), "preset": "default", "confirm_long": True}
        over = {"points": bouncing(200.5), "preset": "default", "confirm_long": True}
        assert post(client, under).status_code == 200
        assert post(client, over).status_code == 400

    def test_too_long_names_the_ceiling_it_is_held_to(self, client, router, monkeypatch) -> None:
        """The rider is told the limit, and the figure is MAX_SPAN_M's: moved
        to 180 km, the sentence says 180 km."""
        from core import api

        for ceiling_m in (api.MAX_SPAN_M, 180_000):
            monkeypatch.setattr(api, "MAX_SPAN_M", ceiling_m)
            body = {"points": bouncing(ceiling_m / 1000 + 1), "preset": "default"}
            error = refused_before_the_router(client, router, {**body, "confirm_long": True})
            assert f"{ceiling_m // 1000} km" in error["error"], error
            assert "too long" in error["error"]

    def test_a_routers_own_limit_does_not_claim_the_straight_line_ceiling(
        self, client, router
    ) -> None:
        """The router refusing a request well under 200 km is not "longer than
        200 km in straight lines"."""
        router(FakeRouter({"route": routing.RouterRefused(400, 154, "exceeds a limit")}))
        error = post(client, good_body()).json()["error"]
        assert "too long" in error
        assert "km" not in error

    def test_the_span_is_the_sum_of_legs(self, client, router) -> None:
        """Short hops that zig-zag add up: each leg is under the confirm span,
        and together they are past the ceiling."""
        from core.api import CONFIRM_SPAN_M, MAX_SPAN_M

        a, b = spanning(CONFIRM_SPAN_M / 1000 / 2)
        legs = int(MAX_SPAN_M / (CONFIRM_SPAN_M / 2)) + 1
        points = [a if i % 2 == 0 else b for i in range(legs + 1)]
        refused_before_the_router(
            client, router, {"points": points, "preset": "default", "confirm_long": True}
        )


def long_body(km: float = 160.0, **extra) -> dict:
    return {"points": bouncing(km), "preset": "default", **extra}


@db
class TestLongRide:
    """Owner decision of 2026-09-26: "Maybe ask to confirm that a long ride is
    intended so it won't mess with processing time", then "Actually do that with
    anonymous visitors only"."""

    def test_a_signed_out_long_ride_is_asked_to_confirm_without_routing(
        self, client, router
    ) -> None:
        fake = router(long_router())
        response = post(client, long_body(160))
        assert response.status_code == 409
        body = response.json()
        assert set(body) == {"error", "code", "span_km"}
        assert body["code"] == "confirm_long"
        assert body["span_km"] == 160
        assert body["error"]
        # US customary first, metric in brackets (OWNER-DECISIONS 85).
        assert body["error"].startswith(
            "This is a long ride, about 99 mi (160 km) in straight lines. "
        )
        assert fake.calls == []

    def test_the_span_is_reported_rounded_to_a_kilometre(self, client, router) -> None:
        router(long_router())
        assert post(client, long_body(187.4)).json()["span_km"] == 187

    def test_a_confirmed_long_ride_is_planned(self, client, segments, router) -> None:
        fake = router(long_router())
        response = post(client, long_body(160, confirm_long=True))
        assert response.status_code == 200
        assert "route" in fake.endpoints()

    def test_confirm_false_is_no_confirmation(self, client, router) -> None:
        router(long_router())
        assert post(client, long_body(160, confirm_long=False)).status_code == 409

    @pytest.mark.parametrize("value", ["true", 1, "yes", None])
    def test_only_a_json_true_confirms(self, value, client, router) -> None:
        refused_before_the_router(client, router, long_body(160, confirm_long=value))

    def test_a_short_ride_needs_no_confirmation_either_way(self, client, segments, router) -> None:
        router(long_router())
        assert post(client, good_body()).status_code == 200
        assert post(client, {**good_body(), "confirm_long": True}).status_code == 200

    def test_a_signed_in_long_ride_is_planned_without_asking(
        self, client, segments, router, monkeypatch
    ) -> None:
        from core.models import User

        router(long_router())
        sign_in(client, monkeypatch, User.objects.create(discord_user_id=4401))
        assert post(client, long_body(160)).status_code == 200

    def test_a_signed_in_ride_past_the_ceiling_is_still_too_long(
        self, client, router, monkeypatch
    ) -> None:
        from core.api import MAX_SPAN_M
        from core.models import User

        sign_in(client, monkeypatch, User.objects.create(discord_user_id=4402))
        refused_before_the_router(client, router, long_body(MAX_SPAN_M / 1000 + 1))

    def test_a_banned_account_is_asked_like_anyone_signed_out(
        self, client, router, monkeypatch
    ) -> None:
        from core.models import User

        router(long_router())
        user = User.objects.create(discord_user_id=4403)
        sign_in(client, monkeypatch, user)
        user.is_banned = True
        user.save()
        assert post(client, long_body(160)).status_code == 409

    @pytest.mark.parametrize(
        ("authenticated", "active", "expected"),
        [(True, True, True), (True, False, False), (False, True, False)],
    )
    def test_signed_in_means_an_account_in_standing(self, authenticated, active, expected) -> None:
        """The epoch middleware signs a banned or deleted account out before
        the view runs; the view checks standing too, so it does not rest on
        the middleware being installed and in order."""
        from types import SimpleNamespace

        from core.api import signed_in

        user = SimpleNamespace(is_authenticated=authenticated, is_active=active)
        assert signed_in(SimpleNamespace(user=user)) is expected

    def test_a_forged_session_cookie_is_signed_out(self, client, router) -> None:
        router(long_router())
        client.cookies[settings.SESSION_COOKIE_NAME] = "forged0123456789abcdefghijklmnop"
        assert post(client, long_body(160)).status_code == 409

    def test_the_figures_are_the_contracts(self) -> None:
        """Written as numbers, because every other test here reads them from
        the module and so moves with them."""
        from core.api import CONFIRM_SPAN_M, MAX_SPAN_M

        assert (CONFIRM_SPAN_M, MAX_SPAN_M) == (150_000, 200_000)

    def test_the_409_is_in_the_schema(self, client) -> None:
        operation = client.get("/api/openapi.json").json()["paths"][ROUTE_PATH]["post"]
        assert "409" in operation["responses"]


def sign_in(client, monkeypatch, user):
    """Through the real Discord flow, so the epoch middleware finds its row."""
    from django.urls import reverse

    from core.auth_views import STATE_SESSION_KEY

    monkeypatch.setattr(
        "core.auth_views.exchange_code",
        lambda code: (user.discord_user_id, "identify"),
        raising=False,
    )
    client.get(reverse("login"))
    state = client.session[STATE_SESSION_KEY]["state"]
    response = client.get(reverse("login-callback"), {"state": state, "code": "abc"})
    assert response.status_code == 302
    return client


@db
class TestUnexpectedErrors:
    @pytest.mark.parametrize("debug", [False, True])
    def test_an_unexpected_error_is_a_fixed_500(
        self, debug, client, segments, router, core_log
    ) -> None:
        """DJANGO_DEBUG=1 is the documented posture of a local stack on :80,
        and Django's debug page would hand a stranger the SQL and the paths.
        The traceback goes to the log instead, where the operator reads it."""

        def breaks(url, payload, timeout):
            raise RuntimeError("SELECT secret FROM somewhere /home/steph")

        router(breaks)
        with override_settings(DEBUG=debug):
            response = post(client, good_body())
        assert response.status_code == 500
        assert set(response.json()) == {"error"}
        assert b"secret" not in response.content
        assert b"Traceback" not in response.content
        assert_logged_with_traceback(core_log, RuntimeError)


@pytest.fixture
def core_log(caplog):
    """caplog, also fed by the `core` loggers, which do not propagate to root."""
    logger = logging.getLogger("core")
    logger.addHandler(caplog.handler)
    try:
        yield caplog
    finally:
        logger.removeHandler(caplog.handler)


def assert_logged_with_traceback(caplog, kind) -> None:
    logged = [r for r in caplog.records if r.name == "core.api" and r.levelname == "ERROR"]
    assert logged, "the failure is not in the log"
    assert any(r.exc_info and r.exc_info[0] is kind for r in logged)


@db
class TestContentType:
    @pytest.mark.parametrize(
        "content_type", ["application/json; charset=utf-8", "Application/JSON", " application/json"]
    )
    def test_the_json_type_is_accepted_however_it_is_written(
        self, content_type, client, segments, router
    ) -> None:
        router(standard_router())
        response = post(client, json.dumps(good_body()), content_type=content_type)
        assert response.status_code == 200

    def test_a_body_of_exactly_the_limit_is_accepted(self, client, segments, router) -> None:
        from core.api import MAX_BODY_BYTES

        router(standard_router())
        body = json.dumps(good_body())
        body += " " * (MAX_BODY_BYTES - len(body.encode()))
        assert len(body.encode()) == MAX_BODY_BYTES
        assert post(client, body).status_code == 200

    def test_one_byte_over_the_limit_is_refused(self, client, router) -> None:
        from core.api import MAX_BODY_BYTES

        body = json.dumps(good_body())
        body += " " * (MAX_BODY_BYTES + 1 - len(body.encode()))
        refused_before_the_router(client, router, body)


def hold_slots(pairs):
    """Take advisory locks on a connection of its own, as another worker would."""
    import psycopg2

    db_settings = connection.settings_dict
    other = psycopg2.connect(
        dbname=db_settings["NAME"],
        user=db_settings["USER"],
        password=db_settings["PASSWORD"],
        host=db_settings["HOST"],
        port=db_settings["PORT"],
    )
    other.autocommit = True
    with other.cursor() as cursor:
        for pair in pairs:
            cursor.execute("SELECT pg_advisory_lock(%s, %s)", list(pair))
    return other


def our_advisory_locks() -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid()"
        )
        return cursor.fetchone()[0]


@db
class TestInFlight:
    """Routing takes a slot for as long as it runs, so a burst of long routes -
    each inside the per-minute count - cannot take every gunicorn worker."""

    def client_slots(self, address: str):
        from core import ratelimit

        limit = ratelimit.ROUTING_IN_FLIGHT
        key = ratelimit._client_lock_id(ratelimit.client_key(address))
        return [
            (ratelimit._LOCK_CLASS_CLIENT + limit.scope_id * 64 + slot, key)
            for slot in range(limit.per_client)
        ]

    def deployment_slots(self):
        from core import ratelimit

        limit = ratelimit.ROUTING_IN_FLIGHT
        return [(ratelimit._LOCK_CLASS_TOTAL + limit.scope_id, s) for s in range(limit.total)]

    def test_a_client_with_its_slots_taken_is_429(self, client, segments, router) -> None:
        router(standard_router())
        other = hold_slots(self.client_slots("198.51.100.20"))
        try:
            refused = post(client, good_body(), HTTP_X_FORWARDED_FOR="198.51.100.20")
            allowed = post(client, good_body(), HTTP_X_FORWARDED_FOR="198.51.100.21")
        finally:
            other.close()
        assert refused.status_code == 429
        assert int(refused["Retry-After"]) >= 1
        assert set(refused.json()) == {"error"}
        assert allowed.status_code == 200

    @override_settings(ROUTING_CONCURRENCY=6)
    def test_one_slot_of_the_clients_is_enough(self, client, segments, router) -> None:
        router(standard_router())
        other = hold_slots(self.client_slots("198.51.100.22")[:-1])
        try:
            response = post(client, good_body(), HTTP_X_FORWARDED_FOR="198.51.100.22")
        finally:
            other.close()
        assert response.status_code == 200

    def test_a_deployment_with_every_slot_taken_is_503(self, client, segments, router) -> None:
        fake = router(standard_router())
        other = hold_slots(self.deployment_slots())
        try:
            refused = post(client, good_body())
        finally:
            other.close()
        assert refused.status_code == 503
        assert int(refused["Retry-After"]) >= 1
        assert fake.calls == []
        assert post(client, good_body()).status_code == 200

    def test_the_slots_are_released_after_the_request(self, client, segments, router) -> None:
        router(standard_router())
        assert post(client, good_body()).status_code == 200
        assert our_advisory_locks() == 0

    def test_the_slots_are_released_after_a_failure(self, client, segments, router) -> None:
        def breaks(url, payload, timeout):
            raise RuntimeError("boom")

        router(breaks)
        assert post(client, good_body()).status_code == 500
        assert our_advisory_locks() == 0

    def test_the_slot_figures_are_the_agreed_ones(self) -> None:
        """Two per client, the second only while two of the api's slots would
        stay free after it. Written as numbers, because every other test here
        reads them from the module and so moves with them."""
        from core import ratelimit

        assert ratelimit.ROUTING_IN_FLIGHT.per_client == 2
        assert ratelimit.ROOM_FOR_OTHERS == 2

    def long_slots(self, address: str | None = None):
        from core import ratelimit

        limit = ratelimit.LONG_ROUTING_IN_FLIGHT
        if address is None:
            return [(ratelimit._LOCK_CLASS_TOTAL + limit.scope_id, s) for s in range(limit.total)]
        key = ratelimit._client_lock_id(ratelimit.client_key(address))
        return [(ratelimit._LOCK_CLASS_CLIENT + limit.scope_id * 64, key)]

    def test_a_second_long_ride_in_the_deployment_is_503(self, client, segments, router) -> None:
        fake = router(long_router())
        other = hold_slots(self.long_slots())
        try:
            refused = post(client, long_body(160, confirm_long=True))
            short = post(client, good_body())
        finally:
            other.close()
        assert refused.status_code == 503
        assert int(refused["Retry-After"]) >= 1
        assert "long ride" in refused.json()["error"]
        assert short.status_code == 200, "an ordinary plan is not held up by a long one"
        assert fake.endpoints() == ["route", "trace_attributes"]

    def test_a_second_long_ride_from_one_client_is_429(self, client, segments, router) -> None:
        router(long_router())
        other = hold_slots(self.long_slots("198.51.100.40"))
        try:
            refused = post(
                client, long_body(160, confirm_long=True), HTTP_X_FORWARDED_FOR="198.51.100.40"
            )
            elsewhere = post(
                client, long_body(160, confirm_long=True), HTTP_X_FORWARDED_FOR="198.51.100.41"
            )
        finally:
            other.close()
        assert refused.status_code == 429
        assert "long ride" in refused.json()["error"]
        assert elsewhere.status_code == 200

    def test_a_signed_in_long_ride_takes_the_long_slot_too(
        self, client, segments, router, monkeypatch
    ) -> None:
        from core.models import User

        router(long_router())
        sign_in(client, monkeypatch, User.objects.create(discord_user_id=4404))
        other = hold_slots(self.long_slots())
        try:
            assert post(client, long_body(160)).status_code == 503
        finally:
            other.close()

    def test_a_long_ride_is_not_held_up_by_ordinary_ones(self, client, segments, router) -> None:
        """The long slots are a separate pool: ordinary routes holding most of
        the ordinary slots leave the long slot free."""
        router(long_router())
        other = hold_slots(self.deployment_slots()[:-1])
        try:
            response = post(client, long_body(160, confirm_long=True))
        finally:
            other.close()
        assert response.status_code == 200

    def test_the_long_slots_are_released(self, client, segments, router) -> None:
        router(long_router())
        assert post(client, long_body(160, confirm_long=True)).status_code == 200
        assert our_advisory_locks() == 0

    def test_a_long_ride_counts_once_against_the_budget(self, client, segments, router) -> None:
        from core.models import RateLimitWindow

        router(long_router())
        post(client, long_body(160, confirm_long=True), HTTP_X_FORWARDED_FOR="198.51.100.42")
        assert list(RateLimitWindow.objects.values_list("hits", flat=True)) == [1]

    def test_one_long_ride_at_a_time(self) -> None:
        from core import ratelimit

        assert ratelimit.LONG_ROUTING_IN_FLIGHT.per_client == 1
        assert ratelimit.LONG_ROUTING_IN_FLIGHT.total == 1

    @override_settings(ROUTING_CONCURRENCY=3)
    def test_a_second_route_is_refused_when_the_pool_is_nearly_full(
        self, client, segments, router
    ) -> None:
        """Review round 2: on the default pool of three, one address holding two
        routes and another holding one fill it. A client's second slot must
        leave room for others, so filling the pool takes three addresses."""
        router(standard_router())
        # The client's first route, in flight: a client slot and a deployment slot.
        other = hold_slots(self.client_slots("198.51.100.50")[:1] + self.deployment_slots()[:1])
        try:
            response = post(client, good_body(), HTTP_X_FORWARDED_FOR="198.51.100.50")
        finally:
            other.close()
        assert response.status_code == 429
        assert our_advisory_locks() == 0, "a refused request holds nothing"

    @override_settings(ROUTING_CONCURRENCY=3)
    def test_filling_the_default_pool_takes_three_addresses(self, client, segments, router) -> None:
        """Two addresses each holding a route leave the third slot to a new
        address, not to a second route from either of them."""
        router(standard_router())

        holders = []
        try:
            for address in ("198.51.100.60", "198.51.100.61"):
                holders.append(
                    hold_slots(
                        self.client_slots(address)[:1] + [self.deployment_slots()[len(holders)]]
                    )
                )
            third_from_a_holder = post(client, good_body(), HTTP_X_FORWARDED_FOR="198.51.100.60")
            third_from_a_new_address = post(
                client, good_body(), HTTP_X_FORWARDED_FOR="198.51.100.62"
            )
        finally:
            for other in holders:
                other.close()
        assert third_from_a_holder.status_code == 429
        assert third_from_a_new_address.status_code == 200

    @pytest.mark.parametrize("total", [4, 6])
    def test_a_second_route_is_granted_while_the_pool_is_roomy(
        self, total, client, segments, router
    ) -> None:
        """On a pool of four, a second route leaves exactly two free: enough."""
        router(standard_router())
        with override_settings(ROUTING_CONCURRENCY=total):
            other = hold_slots(self.client_slots("198.51.100.51")[:1] + self.deployment_slots()[:1])
            try:
                response = post(client, good_body(), HTTP_X_FORWARDED_FOR="198.51.100.51")
                left = our_advisory_locks()
            finally:
                other.close()
        assert response.status_code == 200
        assert left == 0, "the second slot is released like the first (review round 3, N54)"

    @override_settings(ROUTING_CONCURRENCY=4)
    def test_locks_in_another_database_do_not_count(self, client, segments, router) -> None:
        """Review round 3: advisory locks are per database, and so is taking a
        slot, but pg_locks shows the whole server's. Another database's locks
        in the same classes - a second deployment, a parallel test run - must
        not make this pool look fuller than it is."""
        import psycopg2

        from core import ratelimit

        router(standard_router())
        db_settings = connection.settings_dict
        elsewhere = psycopg2.connect(
            dbname="postgres",
            user=db_settings["USER"],
            password=db_settings["PASSWORD"],
            host=db_settings["HOST"],
            port=db_settings["PORT"],
        )
        elsewhere.autocommit = True
        limit = ratelimit.ROUTING_IN_FLIGHT
        try:
            with elsewhere.cursor() as cursor:
                for slot in range(limit.total):
                    cursor.execute(
                        "SELECT pg_advisory_lock(%s, %s)",
                        [ratelimit._LOCK_CLASS_TOTAL + limit.scope_id, slot],
                    )
            # Here, the client's first route and one of four deployment slots:
            # a second route leaves two free, which is room enough.
            other = hold_slots(self.client_slots("198.51.100.71")[:1] + self.deployment_slots()[:1])
            try:
                response = post(client, good_body(), HTTP_X_FORWARDED_FOR="198.51.100.71")
            finally:
                other.close()
        finally:
            elsewhere.close()
        assert response.status_code == 200

    @pytest.mark.parametrize(
        ("workers", "slots"), [(None, 3), (1, 1), (2, 1), (3, 1), (5, 1), (7, 3), (9, 5)]
    )
    def test_the_pool_is_the_workers_less_two_and_never_empty(self, workers, slots) -> None:
        """The worker count less two and less the geocoding slots (2), so the
        two pools together leave two workers free; an empty pool would refuse
        every route with 503, so a small count still gets one slot and leaves
        fewer free."""
        from config.settings import routing_concurrency

        assert routing_concurrency(None if workers is None else str(workers)) == slots

    def test_the_setting_is_read_from_the_environment(self, monkeypatch) -> None:
        """The settings module run afresh with WEB_CONCURRENCY set, since the
        suite's own environment usually leaves it unset."""
        import runpy

        import config.settings as module

        monkeypatch.setenv("WEB_CONCURRENCY", "9")
        assert runpy.run_path(module.__file__)["ROUTING_CONCURRENCY"] == 5

    @pytest.mark.parametrize(("total", "held", "status"), [(1, 1, 503), (4, 3, 200)])
    def test_the_pool_follows_the_setting(
        self, total, held, status, client, segments, router
    ) -> None:
        """Not only at the default: the entrypoint gives cores*2+1 workers
        when WEB_CONCURRENCY is unset, so the pool is whatever that makes it."""
        from core import ratelimit

        router(standard_router())
        limit = ratelimit.ROUTING_IN_FLIGHT
        with override_settings(ROUTING_CONCURRENCY=total):
            other = hold_slots(
                [(ratelimit._LOCK_CLASS_TOTAL + limit.scope_id, s) for s in range(held)]
            )
            try:
                assert post(client, good_body()).status_code == status
            finally:
                other.close()

    @override_settings(LONG_ROUTING_CONCURRENCY=2)
    def test_the_long_pool_follows_its_setting(self, client, segments, router) -> None:
        router(long_router())
        other = hold_slots(self.long_slots()[:1])
        try:
            assert post(client, long_body(160, confirm_long=True)).status_code == 200
        finally:
            other.close()

    def test_the_count_comes_before_the_slots(self, client, segments, router) -> None:
        """A request refused for want of a slot has still spent its count, so
        retrying into a busy pool is not free."""
        from core.models import RateLimitWindow

        router(standard_router())
        other = hold_slots(self.deployment_slots())
        try:
            statuses = [
                post(client, good_body(), HTTP_X_FORWARDED_FOR="198.51.100.45").status_code
                for _ in range(3)
            ]
        finally:
            other.close()
        assert statuses == [503] * 3
        assert list(RateLimitWindow.objects.values_list("hits", flat=True)) == [3]

    def test_the_content_type_comes_before_the_slots(self, client, router) -> None:
        """A cross-site text/plain POST is refused before it can take a slot."""
        router(standard_router())
        other = hold_slots(self.deployment_slots())
        try:
            response = post(client, json.dumps(good_body()), content_type="text/plain")
        finally:
            other.close()
        assert response.status_code == 400

    def test_the_confirmation_comes_before_the_long_slot(self, client, router) -> None:
        """An unconfirmed long ride is asked to confirm even while the long
        slot is busy: asking costs nothing, and the 409 is the useful answer."""
        router(long_router())
        other = hold_slots(self.long_slots())
        try:
            assert post(client, long_body(160)).status_code == 409
        finally:
            other.close()

    def test_a_request_holds_its_slots_while_it_runs(self, client, segments, router) -> None:
        """In autocommit a transaction-scoped lock would end with its own
        statement: the request must still hold both slots when the router is
        asked."""
        fake = standard_router()
        seen = []

        def watching(url, payload, timeout):
            seen.append(our_advisory_locks())
            return fake(url, payload, timeout)

        router(watching)
        assert post(client, good_body()).status_code == 200
        assert seen and all(n == 2 for n in seen), seen

    def test_a_long_ride_holds_both_pools_while_it_runs(self, client, segments, router) -> None:
        fake = long_router()
        seen = []

        def watching(url, payload, timeout):
            seen.append(our_advisory_locks())
            return fake(url, payload, timeout)

        router(watching)
        assert post(client, long_body(160, confirm_long=True)).status_code == 200
        assert seen and all(n == 4 for n in seen), seen
        assert our_advisory_locks() == 0

    def test_a_503_leaves_no_slot_behind(self, client, segments, router) -> None:
        router(standard_router())
        other = hold_slots(self.deployment_slots())
        try:
            assert post(client, good_body()).status_code == 503
            assert our_advisory_locks() == 0
        finally:
            other.close()

    def test_a_refused_long_ride_leaves_no_slot_behind(self, client, segments, router) -> None:
        router(long_router())
        other = hold_slots(self.long_slots() + self.long_slots("198.51.100.43"))
        try:
            assert post(client, long_body(160, confirm_long=True)).status_code == 503
            assert our_advisory_locks() == 0
        finally:
            other.close()
        other = hold_slots(self.long_slots("198.51.100.44"))
        try:
            response = post(
                client, long_body(160, confirm_long=True), HTTP_X_FORWARDED_FOR="198.51.100.44"
            )
            assert response.status_code == 429
            assert our_advisory_locks() == 0
        finally:
            other.close()

    def test_a_long_ride_that_fails_releases_its_slots(self, client, segments, router) -> None:
        def breaks(url, payload, timeout):
            raise RuntimeError("boom")

        router(breaks)
        assert post(client, long_body(160, confirm_long=True)).status_code == 500
        assert our_advisory_locks() == 0

    def test_a_view_that_raises_still_releases(self) -> None:
        """The decorator is for other views too (the stress tiles). On a plain
        Django view nothing turns the exception into a response first."""
        from django.test import RequestFactory

        from core import ratelimit

        @ratelimit.in_flight_limited(ratelimit.ROUTING_IN_FLIGHT)
        def boom(request):
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            boom(RequestFactory().post("/x", REMOTE_ADDR="203.0.113.9"))
        assert our_advisory_locks() == 0

    def test_a_failure_while_taking_slots_holds_nothing(self, monkeypatch) -> None:
        """The deployment slot is taken before the client's; a database error
        between the two must not leave the first held on a pooled connection."""
        from django.db.utils import OperationalError
        from django.test import RequestFactory

        from core import ratelimit

        real = ratelimit._try
        calls = []

        def second_fails(cursor, pair):
            calls.append(pair)
            if len(calls) > 1:
                raise OperationalError("server closed the connection unexpectedly")
            return real(cursor, pair)

        monkeypatch.setattr(ratelimit, "_try", second_fails)
        with pytest.raises(OperationalError):
            ratelimit.acquire(
                RequestFactory().post("/x", REMOTE_ADDR="203.0.113.9"),
                ratelimit.ROUTING_IN_FLIGHT,
            )
        assert len(calls) == 2
        assert our_advisory_locks() == 0

    def test_a_release_whose_close_fails_too_does_not_raise(self, monkeypatch) -> None:
        """Django drops a connection whose close failed, so the locks go with
        it; the request that was planned is still answered."""
        from django.db.utils import InterfaceError

        from core import ratelimit

        def fails():
            raise InterfaceError("connection already closed")

        monkeypatch.setattr(connection, "cursor", fails)
        monkeypatch.setattr(connection, "close", fails)
        ratelimit.release([(ratelimit._LOCK_CLASS_TOTAL + 9, 0)])

    def test_a_release_that_fails_does_not_fail_the_request(self, monkeypatch, core_log) -> None:
        """A route that was planned is answered even if a release fails; the
        failure is logged, the other slots are still released, and the
        connection is closed, which ends any lock it still held."""
        from django.db.utils import InterfaceError

        from core import ratelimit

        pairs = [(ratelimit._LOCK_CLASS_TOTAL + 9, 0), (ratelimit._LOCK_CLASS_TOTAL + 9, 1)]
        with connection.cursor() as cursor:
            for pair in pairs:
                cursor.execute("SELECT pg_advisory_lock(%s, %s)", list(pair))
            cursor.execute("SELECT pg_backend_pid()")
            backend = cursor.fetchone()[0]
        real_cursor = connection.cursor
        attempts = []

        def first_fails():
            attempts.append(1)
            if len(attempts) == 1:
                raise InterfaceError("connection already closed")
            return real_cursor()

        monkeypatch.setattr(connection, "cursor", first_fails)
        ratelimit.release(pairs)
        monkeypatch.undo()
        assert any(
            r.name == "core.ratelimit" and r.levelname == "WARNING" for r in core_log.records
        )
        assert our_advisory_locks() == 0
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM pg_stat_activity WHERE pid = %s", [backend])
            assert cursor.fetchone()[0] == 0, "the connection that failed is closed"


class TestTransportEdges:
    def test_a_client_error_that_is_not_json_is_still_a_refusal(self, server) -> None:
        url = server(404, b"<html>not here</html>")
        with pytest.raises(routing.RouterRefused) as refused:
            routing._transport(url, {}, 5)
        assert (refused.value.status, refused.value.code) == (404, None)


def test_the_attribution_names_dc_open_data_its_licence_and_the_change() -> None:
    """CC BY 4.0 section 3(a)(1)(B): an adaptation says it was modified and links the
    licence. One brief credit covers the District's layers (DDOT's volume and CBD, the
    Capitol grounds, the Roadway Block: OWNER-DECISIONS 306), docs/SOURCES.md each."""
    dc = [line for line in routing.ATTRIBUTION if "DC Open Data" in line]
    assert len(dc) == 1
    assert "CC BY 4.0" in dc[0] and "adapted" in dc[0]
    assert "creativecommons.org/licenses/by/4.0" in dc[0]
    assert any("USGS" in line for line in routing.ATTRIBUTION)
    assert not any("courtesy" in line for line in routing.ATTRIBUTION)
    sources = (Path(__file__).resolve().parents[1] / "docs" / "SOURCES.md").read_text()
    for layer in (
        "2024 Traffic Volume",
        "DDOT Central Business District",
        "Architect of the Capitol",
        "Roadway Block",
    ):
        assert layer in sources


def test_the_attribution_credits_the_agency_street_layers_as_their_licences_ask() -> None:
    """DC's Roadway Block is CC BY 4.0 (OWNER-DECISIONS 151): named, adapted, with the
    licence linked, and it supplies traffic counts where no count layer reached a street.
    Baltimore's layers are open by city code and carry the owner's credit line
    (OWNER-DECISIONS 159). Montgomery County Planning is credited in the same change as
    the Avoid rows derived from its layer (OWNER-DECISIONS 181), in the words its
    licence asks for: "attribution to the Montgomery County Planning Department"."""
    assert "DC Open Data (CC BY 4.0, adapted)" in " ".join(routing.ATTRIBUTION)
    baltimore = [line for line in routing.ATTRIBUTION if "Baltimore" in line]
    assert baltimore == ["Open Baltimore"]
    montgomery = [line for line in routing.ATTRIBUTION if "Montgomery" in line]
    assert montgomery == ["Montgomery County Planning Department"]


@db
@pytest.mark.parametrize("debug", [False, True])
def test_a_failure_in_the_limits_is_a_fixed_500_too(debug, client, monkeypatch, core_log) -> None:
    """The limits run around Ninja's own handling, so a database that fails
    inside them - the first thing a request touches - must not reach Django's
    debug page either."""
    from core import ratelimit

    def breaks(limit, client_id):
        raise RuntimeError("could not connect to server at /var/run/postgresql secret")

    monkeypatch.setattr(ratelimit, "hit", breaks)
    with override_settings(DEBUG=debug):
        response = post(client, good_body())
    assert response.status_code == 500
    assert set(response.json()) == {"error"}
    assert b"secret" not in response.content
    assert_logged_with_traceback(core_log, RuntimeError)


@db
def test_a_piece_is_placed_at_its_middle_not_its_end(client, segments, router) -> None:
    """One stretch, two segments of one way meeting just past its middle: the
    piece belongs to the segment its middle lies on, not the one at its end."""
    a, b = (-77.05, LAT), (-77.04, LAT)
    boundary = (-77.0448, LAT)
    with connection.cursor() as cursor:
        for ordinal, tier, line in ((0, 2, (a, boundary)), (1, 4, (boundary, b))):
            wkt = "LINESTRING(" + ", ".join(f"{lon} {lat}" for lon, lat in line) + ")"
            cursor.execute(
                f"INSERT INTO {segments}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                "stress_rule) VALUES (808, %s, ST_GeomFromText(%s, 4326), %s, 'test')",
                [ordinal, wkt, tier],
            )
    router(one_edge_router([a, b], [(808, 0, 1, 0.9)], 0.9))
    stress = post(client, good_body()).json()["stress_m"]
    assert stress["2"] == pytest.approx(900.0, abs=0.5)


@db
def test_every_failed_leg_adds_its_length(client, segments, router) -> None:
    legs = [VERTICES[:2], VERTICES[1:3], VERTICES[2:4]]
    router(
        FakeRouter(
            {
                "route": route_answer(
                    [(legs[0], 0.9, [1.0]), (legs[1], 0.4, [1.0]), (legs[2], 0.6, [1.0])]
                ),
                "trace_attributes": [
                    trace_answer(legs[0], [(101, 0, 1, 0.9)]),
                    routing.RouterRefused(400, 443, "no"),
                    routing.RouterRefused(400, 443, "no"),
                    routing.RouterRefused(400, 443, "no"),
                    routing.RouterRefused(400, 443, "no"),
                ],
            }
        )
    )
    points = [list(VERTICES[0]), list(VERTICES[1]), list(VERTICES[2]), list(VERTICES[3])]
    stress = post(client, {"points": points, "preset": "default"}).json()["stress_m"]
    assert stress["3"] == pytest.approx(900.0, abs=0.5)
    assert stress["unknown"] == pytest.approx(1000.0, abs=0.5)


def test_a_trace_in_miles_is_converted() -> None:
    trace = trace_answer([VERTICES[0], VERTICES[1]], [(101, 0, 1, 1.0)])
    trace["units"] = "miles"
    assert sum(p.metres for p in routing.pieces_of_trace(trace)) == pytest.approx(1609.344)


def test_the_refusals_name_miles_first_and_kilometres_in_brackets() -> None:
    """OWNER-DECISIONS 85: US customary first in every sentence a rider reads."""
    from core.api import MAX_SPAN_M, too_long

    assert MAX_SPAN_M == 200_000
    assert too_long().startswith("the route is longer than 124 mi (200 km) in straight lines")


@db
class TestSurfaceOfPieces:
    """OWNER-DECISIONS 280 (review SF5): `classify` reads the segment's surface
    beside its tier and facility, still a pair to every reader that unpacks it."""

    def test_classify_carries_is_unpaved(self, segments) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {segments}.segment SET is_unpaved = (ordinal = 1) WHERE osm_way_id = 202"
            )
            cursor.execute(
                f"UPDATE {segments}.segment SET is_unpaved = NULL WHERE osm_way_id = 101"
            )
        pieces = [
            routing.Piece(101, -77.045, LAT, 100.0),
            routing.Piece(202, -77.0375, LAT, 100.0),
            routing.Piece(202, -77.025, LAT, 100.0),
        ]
        classes = routing.classify(pieces, "weekday_offpeak")
        assert [c.unpaved for c in classes] == [None, False, True]
        assert [c[0] for c in classes] == ["3", "1", "4"] and all(len(c) == 2 for c in classes)
        tier, facility = classes[2]
        assert tier == "4" and classes[2] == (tier, facility)

    def test_the_no_trail_graph_keeps_the_surface(self, segments) -> None:
        """Mutation review X31: a ride on the no-trail variant (Group Ride, trails off)
        still says which pieces are unpaved."""
        with connection.cursor() as cursor:
            cursor.execute(f"UPDATE {segments}.segment SET is_unpaved = true")
        pieces = [routing.Piece(101, -77.045, LAT, 100.0), routing.Piece(202, -77.0375, LAT, 100.0)]
        classes = routing.classify(pieces, "weekday_offpeak", roadway_only=True)
        assert [c.unpaved for c in classes] == [True, True]

    def test_a_piece_class_pickles_with_its_surface(self) -> None:
        import pickle

        again = pickle.loads(pickle.dumps(routing.PieceClass("2", "path", True)))
        assert again == ("2", "path") and again.unpaved is True

    def test_the_route_description_says_unpaved(self, client, segments, router) -> None:
        router(standard_router())
        plain = post(client, good_body()).json()["description"]
        assert plain and all(e["surface"] is None for e in plain)
        with connection.cursor() as cursor:
            cursor.execute(f"UPDATE {segments}.segment SET is_unpaved = true")
        described = post(client, good_body()).json()["description"]
        # Every stretch on a segment; the trace's last piece matches none.
        stretches = [e for e in described if e["kind"] == "stretch" and e["tier"] is not None]
        assert stretches and all(
            e["surface"] == "unpaved" and e["text"].endswith(", unpaved.") for e in stretches
        ), [(e["surface"], e["text"]) for e in stretches]


@db
class TestMassRideCapacitySections:
    """The Mass Ride's route line is coloured by carrying capacity, riders a minute
    (OWNER-DECISIONS 325-327, 387): the API's sections carry `rpm` from the segment
    table's `mass_usable_width_m`, for a Mass Ride only and only where the table has it."""

    @staticmethod
    def capacities(segments, by_way: dict[int, int | None]) -> None:
        with connection.cursor() as cursor:
            for way, rpm in by_way.items():
                cursor.execute(
                    f"UPDATE {segments}.segment SET mass_usable_width_m = %s WHERE osm_way_id = %s",
                    [None if rpm is None else rpm / flow.level_riders_per_min(1.0), way],
                )

    def test_a_mass_ride_carries_the_capacity_and_ends_a_section_where_the_band_does(
        self, client, segments, router
    ) -> None:
        self.capacities(segments, {101: 50, 202: 250})
        router(standard_router())
        spans = post(client, good_body("mass-ride")).json()["stress_spans"]
        # The trace's last piece matches no segment: unknown, with no figure.
        assert [(s["tier"], s["rpm"]) for s in spans] == [(3, 50), (1, 250), (4, 250), (None, None)]

    def test_another_ride_type_carries_none(self, client, segments, router) -> None:
        self.capacities(segments, {101: 50, 202: 250})
        router(standard_router())
        spans = post(client, good_body("default")).json()["stress_spans"]
        assert spans and all(s["rpm"] is None for s in spans)

    def test_a_table_without_the_column_draws_a_mass_ride_by_stress_as_before(
        self, client, segments, router, monkeypatch
    ) -> None:
        with connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE {segments}.segment DROP COLUMN mass_usable_width_m")
        monkeypatch.setattr(routing, "_capacity_column_seen", False)
        router(standard_router())
        response = post(client, good_body("mass-ride"))
        assert response.status_code == 200
        spans = response.json()["stress_spans"]
        assert spans and all(s["rpm"] is None for s in spans)
        assert [s["tier"] for s in spans][:1] == [3], "still the stress sections"

    def test_a_piece_class_carries_the_capacity_and_still_pickles(self) -> None:
        import pickle

        width = 120 / flow.level_riders_per_min(1.0)
        again = pickle.loads(pickle.dumps(routing.PieceClass("2", "path", True, width_m=width)))
        assert again == ("2", "path") and again.unpaved is True and again.rpm == 120
        assert again.width_m == pytest.approx(width)
        assert routing.PieceClass("2", "path").rpm is None
        assert routing.PieceClass("2", "path").width_m is None

    def test_classify_reads_the_capacity(self, segments) -> None:
        self.capacities(segments, {101: 50, 202: None})
        pieces = [routing.Piece(101, -77.045, LAT, 100.0), routing.Piece(202, -77.0375, LAT, 100.0)]
        monkey = routing._capacity_column_seen
        try:
            routing._capacity_column_seen = False
            classes = routing.classify(pieces, "weekday_offpeak")
        finally:
            routing._capacity_column_seen = monkey
        assert [c.rpm for c in classes] == [50, None]
        assert all(len(c) == 2 for c in classes)
