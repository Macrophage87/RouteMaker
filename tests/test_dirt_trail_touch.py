# ruff: noqa: F811 (the route tests' fixtures, imported by name)
"""A dirt trail the rider is on, or put a point on, is ridden on a ride type that does not
plan on them (the owner, 2026-10-20: "Don't plan on the route, but if you enter it or mark a
waypoint in it, it will continue to route through." and "Connecting trails too").

The router is the fake of tests/test_route_api.py."""

from __future__ import annotations

import pytest
from django.conf import settings
from django.db import connection
from test_route_api import (  # noqa: F401 (fixtures)
    STANDARD_EDGES,
    VERTICES,
    FakeRouter,
    good_body,
    post,
    route_answer,
    router,
    segments,
    trace_answer,
)

from core import routing, trail_touch

pytestmark = pytest.mark.usefixtures("weekday_clock")

db = pytest.mark.django_db(transaction=True)

# A dirt trail (way 404) under the route's start, and another (way 505) along its middle.
TOUCHED = 404
STRAY = 505


def add_trail(live: str, way: int, line) -> None:
    wkt = "LINESTRING(" + ", ".join(f"{lon} {lat}" for lon, lat in line) + ")"
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {live}.segment (osm_way_id, ordinal, geometry, stress_tier, "
            "stress_rule, bike_access_reason) "
            "VALUES (%s, 0, ST_GeomFromText(%s, 4326), 1, 'test', 'mtb')",
            [way, wkt],
        )


def routes(fake) -> list[tuple[str, dict]]:
    return [(url, payload) for url, payload in fake.calls if url.endswith("/route")]


def graph_of(url: str) -> str:
    return next(name for name, base in settings.VALHALLA_UPSTREAMS.items() if url.startswith(base))


def plain_router() -> FakeRouter:
    return FakeRouter(
        {
            "route": lambda _payload: route_answer([(VERTICES, 2.2, [10.0, 20.0, 15.0, 30.0])]),
            "trace_attributes": trace_answer(VERTICES, STANDARD_EDGES),
        }
    )


@db
class TestThroughTheApi:
    def test_a_start_on_a_dirt_trail_is_planned_on_the_off_road_graph(
        self, client, segments, router
    ) -> None:
        add_trail(segments, TOUCHED, [VERTICES[0], (VERTICES[0][0], VERTICES[0][1] + 0.001)])
        fake = router(plain_router())
        response = post(client, good_body())
        assert response.status_code == 200, response.content
        assert response.json()["variant"] == "offroad"
        assert {graph_of(url) for url, _ in routes(fake)} == {"offroad"}
        # The ride type's own costing, not Gravel's.
        assert routes(fake)[0][1]["costing_options"]["bicycle"]["bicycle_type"] == "Hybrid"

    def test_no_dirt_trail_near_a_point_plans_as_before(self, client, segments, router) -> None:
        # A dirt trail half a kilometre off the route's points.
        add_trail(segments, TOUCHED, [(-77.045, 38.905), (-77.045, 38.906)])
        fake = router(plain_router())
        assert post(client, good_body()).json()["variant"] == "standard"
        assert {graph_of(url) for url, _ in routes(fake)} == {"standard"}

    def test_without_the_off_road_graph_it_is_planned_on_the_standard_one(
        self, client, segments, router, monkeypatch
    ) -> None:
        add_trail(segments, TOUCHED, [VERTICES[0], (VERTICES[0][0], VERTICES[0][1] + 0.001)])
        monkeypatch.setattr(routing, "_offroad_is_promoted", lambda: False)
        fake = router(plain_router())
        assert post(client, good_body()).json()["variant"] == "standard"
        assert {graph_of(url) for url, _ in routes(fake)} == {"standard"}

    def test_a_dirt_trail_the_plan_found_for_itself_is_left_out(
        self, client, segments, router
    ) -> None:
        """The route starts on way 404 and, the first time, takes dirt trail 505 a road away:
        planned again with 505 left out (a strip across it in `exclude_polygons`)."""
        add_trail(segments, TOUCHED, [VERTICES[0], (VERTICES[0][0], VERTICES[0][1] + 0.001)])
        add_trail(segments, STRAY, VERTICES[2:4])
        stray_edges = [(TOUCHED, 0, 1, 0.9), (202, 1, 2, 0.4), (STRAY, 2, 3, 0.4), (303, 3, 4, 0.5)]
        asked: list[dict] = []

        def route(payload):
            asked.append(payload)
            return route_answer([(VERTICES, 2.2, [10.0, 20.0, 15.0, 30.0])])

        def trace(_payload):
            left_out = bool(asked[-1].get("exclude_polygons"))
            edges = STANDARD_EDGES if left_out else stray_edges
            return trace_answer(VERTICES, edges)

        router(FakeRouter({"route": route, "trace_attributes": trace}))
        response = post(client, good_body())
        assert response.status_code == 200, response.content
        assert response.json()["variant"] == "offroad"
        assert not asked[0].get("exclude_polygons")
        ring = asked[-1]["exclude_polygons"][-1]
        lons = [p[0] for p in ring]
        # Across 505 (between the third and fourth vertices), nowhere near the start.
        assert VERTICES[2][0] < min(lons) and max(lons) < VERTICES[3][0]

    def test_a_dirt_trail_the_plan_keeps_finding_is_planned_without_any(
        self, client, segments, router
    ) -> None:
        add_trail(segments, TOUCHED, [VERTICES[0], (VERTICES[0][0], VERTICES[0][1] + 0.001)])
        add_trail(segments, STRAY, VERTICES[2:4])
        stray_edges = [(TOUCHED, 0, 1, 0.9), (202, 1, 2, 0.4), (STRAY, 2, 3, 0.4), (303, 3, 4, 0.5)]
        fake = router(
            FakeRouter(
                {
                    "route": lambda _p: route_answer([(VERTICES, 2.2, [10.0, 20.0, 15.0, 30.0])]),
                    "trace_attributes": lambda p: trace_answer(
                        VERTICES,
                        STANDARD_EDGES
                        if graph_of(fake.calls[-1][0]) == "standard"
                        else stray_edges,
                    ),
                }
            )
        )
        response = post(client, good_body())
        assert response.status_code == 200, response.content
        assert response.json()["variant"] == "standard"
        graphs = [graph_of(url) for url, _ in routes(fake)]
        assert graphs.count("offroad") == routing.STRAY_ROUNDS
        assert graphs[-1] == "standard"


class TestRuns:
    def test_a_run_of_dirt_trails_one_after_another_is_one_run(self) -> None:
        dirt = frozenset({1, 2, 3})
        assert trail_touch.runs([1, 2, 9, 3, 3, 9], dirt) == [(0, 2), (3, 5)]
        assert trail_touch.runs([9, 9], dirt) == []
        assert trail_touch.runs([1], dirt) == [(0, 1)]

    def test_a_joined_trail_counts_with_the_touched_one_and_a_separate_one_does_not(self) -> None:
        """'Connecting trails too': 2 follows the touched 1 without a road between."""
        dirt = frozenset({1, 2, 3})
        assert trail_touch.strays([1, 2, 9, 3], dirt, frozenset({1})) == [(3, 4)]
        assert trail_touch.strays([1, 2, 9, 3], dirt, frozenset({3})) == [(0, 2)]
        assert trail_touch.strays([1, 2, 9, 3], dirt, frozenset({2, 3})) == []

    def test_the_line_across_a_stray_is_short_and_along_it(self) -> None:
        a, b = trail_touch.block_line(-77.0, 38.9, 90.0)
        assert a[1] == pytest.approx(38.9) and b[1] == pytest.approx(38.9)
        metres = (b[0] - a[0]) * 111_320.0 * 0.7782
        assert metres == pytest.approx(trail_touch.BLOCK_LINE_M, rel=0.05)
