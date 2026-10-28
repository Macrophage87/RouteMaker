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

# A dirt trail (way 404) under the route's end, and another (way 505) along its middle.
TOUCHED = 404
STRAY = 505
END_TRAIL = [VERTICES[-1], (VERTICES[-1][0], VERTICES[-1][1] + 0.001)]
START_TRAIL = [VERTICES[0], (VERTICES[0][0], VERTICES[0][1] + 0.001)]
# Ride's Road closed stretch on START_TRAIL as the app sends it: the road ahead, a few points,
# a few metres off the mapped line.
ALONG_TRAIL = [
    [VERTICES[0][0] + 0.00003, VERTICES[0][1] + 0.0002],
    [VERTICES[0][0], VERTICES[0][1] + 0.0005],
    [VERTICES[0][0] - 0.00003, VERTICES[0][1] + 0.0008],
]
# The route the first time: on to 505, then a road, then to the end on 404.
STRAY_EDGES = [(101, 0, 1, 0.9), (STRAY, 1, 2, 0.4), (202, 2, 3, 0.4), (TOUCHED, 3, 4, 0.5)]
# The route with a stray left out: another shape, as a router's is once it leaves a way out.
# The rounds share their traces (audit S12), so the same shape is not traced again.
AROUND = [*VERTICES[:2], (VERTICES[2][0], VERTICES[2][1] + 0.00001), *VERTICES[3:]]


def stray_route(payload: dict) -> dict:
    """The fake router's route: by AROUND where strays are left out, else VERTICES."""
    line = AROUND if payload.get("exclude_polygons") else VERTICES
    return route_answer([(line, 2.2, [10.0, 20.0, 15.0, 30.0])])


def add_trail(live: str, way: int, line, reason: str = "mtb") -> None:
    wkt = "LINESTRING(" + ", ".join(f"{lon} {lat}" for lon, lat in line) + ")"
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {live}.segment (osm_way_id, ordinal, geometry, stress_tier, "
            "stress_rule, bike_access_reason) "
            "VALUES (%s, 0, ST_GeomFromText(%s, 4326), 1, 'test', %s)",
            [way, wkt, reason],
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
    def test_an_end_on_a_dirt_trail_is_planned_on_the_off_road_graph(
        self, client, segments, router
    ) -> None:
        add_trail(segments, TOUCHED, END_TRAIL)
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
        add_trail(segments, TOUCHED, END_TRAIL)
        monkeypatch.setattr(routing, "_offroad_is_promoted", lambda: False)
        fake = router(plain_router())
        assert post(client, good_body()).json()["variant"] == "standard"
        assert {graph_of(url) for url, _ in routes(fake)} == {"standard"}

    def test_a_dirt_trail_the_plan_found_for_itself_is_left_out(
        self, client, segments, router
    ) -> None:
        """The route ends on way 404 and, the first time, takes dirt trail 505 a road away:
        planned again with 505 left out (a strip across it in `exclude_polygons`)."""
        add_trail(segments, TOUCHED, END_TRAIL)
        add_trail(segments, STRAY, VERTICES[1:3])
        asked: list[dict] = []

        def route(payload):
            asked.append(payload)
            return stray_route(payload)

        def trace(_payload):
            left_out = bool(asked[-1].get("exclude_polygons"))
            edges = STANDARD_EDGES if left_out else STRAY_EDGES
            return trace_answer(VERTICES, edges)

        router(FakeRouter({"route": route, "trace_attributes": trace}))
        response = post(client, good_body())
        assert response.status_code == 200, response.content
        assert response.json()["variant"] == "offroad"
        assert not asked[0].get("exclude_polygons")
        ring = asked[-1]["exclude_polygons"][0]
        lons = [p[0] for p in ring]
        # Across 505 (between the second and third vertices), nowhere near the end.
        assert VERTICES[1][0] < min(lons) and max(lons) < VERTICES[2][0]

    def test_a_stray_on_the_routers_own_route_starts_the_next_round_at_once(
        self, client, segments, router
    ) -> None:
        """Audit S12 part 1 (the owner, 2026-10-27 7:52 PM ET: "make the banked changes"): the
        router's own route is checked for strays before the search, so the round that strays
        asks the router for nothing but that route and its trace before planning again."""
        add_trail(segments, TOUCHED, END_TRAIL)
        add_trail(segments, STRAY, VERTICES[1:3])
        asked: list[dict] = []

        def route(payload):
            asked.append(payload)
            return stray_route(payload)

        def trace(_payload):
            left_out = bool(asked[-1].get("exclude_polygons"))
            return trace_answer(VERTICES, STANDARD_EDGES if left_out else STRAY_EDGES)

        fake = router(FakeRouter({"route": route, "trace_attributes": trace}))
        body = {**good_body(), "stress": 100}
        response = post(client, body)
        assert response.status_code == 200, response.content
        again = next(
            i for i, (url, payload) in enumerate(fake.calls) if payload.get("exclude_polygons")
        )
        first_round = [url.rsplit("/", 1)[-1] for url, _ in fake.calls[:again]]
        assert first_round == ["route", "trace_attributes"]

    def test_a_dirt_trail_the_plan_keeps_finding_is_planned_without_any(
        self, client, segments, router
    ) -> None:
        add_trail(segments, TOUCHED, END_TRAIL)
        add_trail(segments, STRAY, VERTICES[1:3])
        fake = router(
            FakeRouter(
                {
                    "route": lambda _p: route_answer([(VERTICES, 2.2, [10.0, 20.0, 15.0, 30.0])]),
                    "trace_attributes": lambda p: trace_answer(
                        VERTICES,
                        STANDARD_EDGES
                        if graph_of(fake.calls[-1][0]) == "standard"
                        else STRAY_EDGES,
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

    def test_green_singletrack_the_plan_found_is_left_out_too(
        self, client, segments, router
    ) -> None:
        add_trail(segments, TOUCHED, END_TRAIL)
        add_trail(segments, STRAY, VERTICES[1:3], reason="singletrack")
        asked: list[dict] = []

        def route(payload):
            asked.append(payload)
            return stray_route(payload)

        def trace(_payload):
            edges = STANDARD_EDGES if asked[-1].get("exclude_polygons") else STRAY_EDGES
            return trace_answer(VERTICES, edges)

        router(FakeRouter({"route": route, "trace_attributes": trace}))
        response = post(client, good_body())
        assert response.status_code == 200, response.content
        assert response.json()["variant"] == "offroad"
        assert asked[-1].get("exclude_polygons")

    def test_no_route_once_a_stray_is_left_out_plans_without_dirt_trails(
        self, client, segments, router
    ) -> None:
        add_trail(segments, TOUCHED, END_TRAIL)
        add_trail(segments, STRAY, VERTICES[1:3])
        graphs: list[str] = []

        def route(payload):
            graph = graph_of(fake.calls[-1][0])
            graphs.append(graph)
            if graph == "offroad" and payload.get("exclude_polygons"):
                raise routing.RouterRefused(400, 442, "No path could be found")
            return route_answer([(VERTICES, 2.2, [10.0, 20.0, 15.0, 30.0])])

        def trace(_payload):
            edges = STANDARD_EDGES if graphs[-1] == "standard" else STRAY_EDGES
            return trace_answer(VERTICES, edges)

        fake = router(FakeRouter({"route": route, "trace_attributes": trace}))
        response = post(client, good_body())
        assert response.status_code == 200, response.content
        assert response.json()["variant"] == "standard"
        assert graphs[0] == "offroad" and graphs[-1] == "standard"

    def test_a_waypoint_on_a_dirt_trail_plans_on_the_off_road_graph(
        self, client, segments, router
    ) -> None:
        add_trail(segments, TOUCHED, [VERTICES[2], (VERTICES[2][0], VERTICES[2][1] + 0.001)])
        fake = router(plain_router())
        body = {"points": [list(VERTICES[0]), list(VERTICES[2]), list(VERTICES[-1])]}
        response = post(client, {**body, "preset": "default"})
        assert response.status_code == 200, response.content
        assert response.json()["variant"] == "offroad"
        assert {graph_of(url) for url, _ in routes(fake)} == {"offroad"}

    def test_a_start_alone_on_a_dirt_trail_plans_as_before(self, client, segments, router) -> None:
        """Plan and Go: standing on a trail is not choosing it (the owner, 2026-10-21: "I
        wouldn't use that as a start for routing unless "opted-in"")."""
        add_trail(segments, TOUCHED, START_TRAIL)
        fake = router(plain_router())
        body = post(client, good_body()).json()
        assert body["variant"] == "standard" and body["dirt_trails"] is False
        assert {graph_of(url) for url, _ in routes(fake)} == {"standard"}

    def test_a_loop_from_a_dirt_trail_plans_as_before(self, client, segments, router) -> None:
        """A loop's end is its start again: still the start alone."""
        add_trail(segments, TOUCHED, START_TRAIL)
        fake = router(plain_router())
        response = post(client, {**good_body(), "loop": True})
        assert response.status_code == 200, response.content
        assert response.json()["variant"] == "standard"
        assert {graph_of(url) for url, _ in routes(fake)} == {"standard"}

    def test_out_of_time_while_leaving_strays_out_plans_without_dirt_trails(
        self, client, segments, router
    ) -> None:
        add_trail(segments, TOUCHED, END_TRAIL)
        add_trail(segments, STRAY, VERTICES[1:3])
        graphs: list[str] = []

        def route(payload):
            graph = graph_of(fake.calls[-1][0])
            graphs.append(graph)
            if graph == "offroad" and payload.get("exclude_polygons"):
                raise routing.DeadlineExceeded("out of time")
            return route_answer([(VERTICES, 2.2, [10.0, 20.0, 15.0, 30.0])])

        def trace(_payload):
            edges = STANDARD_EDGES if graphs[-1] == "standard" else STRAY_EDGES
            return trace_answer(VERTICES, edges)

        fake = router(FakeRouter({"route": route, "trace_attributes": trace}))
        response = post(client, good_body())
        assert response.status_code == 200, response.content
        assert response.json()["variant"] == "standard"

    def test_a_ride_re_plan_from_on_a_dirt_trail_may_ride_any(
        self, client, segments, router
    ) -> None:
        """'If someone goes onto a dirt trail, any reroutes should include dirt': 505 is not
        joined to the 404 the rider is on, and is ridden all the same."""
        add_trail(segments, TOUCHED, START_TRAIL)
        add_trail(segments, STRAY, VERTICES[2:4])
        edges = [(TOUCHED, 0, 1, 0.9), (202, 1, 2, 0.4), (STRAY, 2, 3, 0.4), (303, 3, 4, 0.5)]
        asked: list[dict] = []

        def route(payload):
            asked.append(payload)
            return route_answer([(VERTICES, 2.2, [10.0, 20.0, 15.0, 30.0])])

        router(FakeRouter({"route": route, "trace_attributes": trace_answer(VERTICES, edges)}))
        response = post(client, {**good_body(), "ride_replan": True})
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["variant"] == "offroad" and body["dirt_trails"] is True
        assert len(asked) == 1 and not asked[0].get("exclude_polygons")

    def test_after_a_dirt_trail_a_ride_re_plan_from_a_road_may_ride_any(
        self, client, segments, router
    ) -> None:
        fake = router(plain_router())
        body = {**good_body(), "ride_replan": True, "dirt_ridden": True}
        assert post(client, body).json()["variant"] == "offroad"
        assert {graph_of(url) for url, _ in routes(fake)} == {"offroad"}

    def test_road_closed_on_a_dirt_trail_closes_dirt_for_the_ride(
        self, client, segments, router
    ) -> None:
        """The owner, 2026-10-21: "If you ride a dirt trail outside of mtb or gravel and it's
        marked as road closed, assume that means bad riding conditions until it's opted back
        in"."""
        add_trail(segments, TOUCHED, START_TRAIL)
        fake = router(plain_router())
        body = {
            **good_body(),
            "ride_replan": True,
            "dirt_ridden": True,
            "blocked_lines": [ALONG_TRAIL],
        }
        response = post(client, body)
        assert response.status_code == 200, response.content
        assert response.json()["variant"] == "standard"
        assert response.json()["dirt_closed"] is True
        assert {graph_of(url) for url, _ in routes(fake)} == {"standard"}

    def test_a_road_closed_across_a_dirt_trail_leaves_dirt_open(
        self, client, segments, router
    ) -> None:
        add_trail(segments, TOUCHED, START_TRAIL)
        router(plain_router())
        lon, lat = VERTICES[0]
        across = [[lon - 0.001, lat + 0.0005], [lon + 0.001, lat + 0.0005]]
        body = {**good_body(), "ride_replan": True, "blocked_lines": [across]}
        answer = post(client, body).json()
        assert answer["variant"] == "offroad" and answer["dirt_closed"] is False

    def test_dirt_closed_earlier_in_the_ride_overrides_a_stop_on_a_trail(
        self, client, segments, router
    ) -> None:
        """Once the ride said a dirt trail was closed, a stop or end on one no longer opens
        them, though the stretch has dropped out of the ones the ride sends."""
        add_trail(segments, TOUCHED, END_TRAIL)
        fake = router(plain_router())
        body = {**good_body(), "ride_replan": True, "dirt_closed": True}
        answer = post(client, body).json()
        assert answer["variant"] == "standard" and answer["dirt_closed"] is True
        assert {graph_of(url) for url, _ in routes(fake)} == {"standard"}

    def test_dirt_closed_alone_is_not_a_ride(self, client, segments, router) -> None:
        add_trail(segments, TOUCHED, END_TRAIL)
        router(plain_router())
        assert post(client, {**good_body(), "dirt_closed": True}).json()["variant"] == "offroad"

    def test_road_closed_on_a_road_leaves_dirt_open(self, client, segments, router) -> None:
        add_trail(segments, TOUCHED, START_TRAIL)
        fake = router(plain_router())
        road = [list(VERTICES[2]), [VERTICES[2][0], VERTICES[2][1] + 0.001]]
        body = {**good_body(), "ride_replan": True, "blocked_lines": [road]}
        assert post(client, body).json()["variant"] == "offroad"
        assert "offroad" in {graph_of(url) for url, _ in routes(fake)}

    def test_dirt_ridden_alone_is_not_a_ride(self, client, segments, router) -> None:
        router(plain_router())
        assert post(client, {**good_body(), "dirt_ridden": True}).json()["variant"] == "standard"

    def test_green_singletrack_stays_closed_on_a_ride_re_plan(
        self, client, segments, router
    ) -> None:
        add_trail(segments, TOUCHED, START_TRAIL)
        add_trail(segments, STRAY, VERTICES[2:4], reason="singletrack")
        edges = [(TOUCHED, 0, 1, 0.9), (202, 1, 2, 0.4), (STRAY, 2, 3, 0.4), (303, 3, 4, 0.5)]
        asked: list[dict] = []

        def route(payload):
            asked.append(payload)
            return stray_route(payload)

        def trace(_payload):
            left_out = bool(asked[-1].get("exclude_polygons"))
            return trace_answer(VERTICES, STANDARD_EDGES if left_out else edges)

        router(FakeRouter({"route": route, "trace_attributes": trace}))
        response = post(client, {**good_body(), "ride_replan": True})
        assert response.status_code == 200, response.content
        assert asked[-1].get("exclude_polygons")


class TestRounds:
    """The rounds of `plan` share their traces and `/locate` answers, and drop them before the
    plan on the ride type's own graph (audit S12, part 2)."""

    RING = ((-77.0, 38.9), (-77.0, 38.901), (-77.001, 38.901), (-77.0, 38.9))
    POINTS = [[-77.05, 38.9], [-77.02, 38.9]]

    def fake(self, monkeypatch, strays: int) -> list[dict]:
        """`routing._plan` that traces and locates one thing a round, and finds a stray in
        its first `strays` rounds."""
        seen: list[dict] = []

        def fake_plan(*args, traces=None, located=None, **_):
            seen.append({"traces": traces, "located": located, "started": args[3]})
            if traces is not None:
                seen[-1]["held"] = (len(traces), len(located))
                traces[("offroad", f"shape{len(seen)}", "{}")] = {"edges": []}
                located[("offroad", -77.0, 38.9 + len(seen), 10)] = [{"edges": []}]
            if len(seen) <= strays:
                raise routing.StrayTrails((self.RING,), (frozenset({TOUCHED}),))
            return {"round": len(seen)}

        monkeypatch.setattr(routing, "_plan", fake_plan)
        return seen

    def test_a_later_round_has_what_the_rounds_before_traced_and_located(self, monkeypatch) -> None:
        seen = self.fake(monkeypatch, strays=routing.STRAY_ROUNDS - 1)
        answer = routing.plan(self.POINTS, "default", started=5.0)
        assert answer == {"round": routing.STRAY_ROUNDS}
        assert all(r["traces"] is seen[0]["traces"] for r in seen)
        assert all(r["located"] is seen[0]["located"] for r in seen)
        assert [r["held"] for r in seen] == [(n, n) for n in range(routing.STRAY_ROUNDS)]
        assert {r["started"] for r in seen} == {5.0}

    def test_the_plan_on_the_ride_types_own_graph_starts_afresh(self, monkeypatch) -> None:
        seen = self.fake(monkeypatch, strays=routing.STRAY_ROUNDS)
        answer = routing.plan(self.POINTS, "default", started=5.0)
        assert answer == {"round": routing.STRAY_ROUNDS + 1}
        assert seen[-1]["traces"] is None and seen[-1]["located"] is None
        # Cleared, so the worker does not hold them through the last plan.
        assert seen[0]["traces"] == {} and seen[0]["located"] == {}
        assert {r["started"] for r in seen} == {5.0}

    def test_the_earlier_rounds_readings_are_dropped_before_the_final_round(
        self, monkeypatch
    ) -> None:
        """Each reading pins its trace (`routing._reading_memo`); the final round's traces are
        new objects, so the earlier rounds' readings go with their traces (review of S19)."""
        held: list[list] = []

        def fake_plan(*args, traces=None, **_):
            memo = routing._reading_memo.get()
            held.append([entry.trace for entry in memo.values()])
            trace = {"shape": "", "units": "kilometers", "edges": []}
            routing.trace_reading(trace)
            if traces is not None:
                traces[("offroad", f"shape{len(held)}", "{}")] = trace
                raise routing.StrayTrails((self.RING,), (frozenset({TOUCHED}),))
            return {"round": len(held)}

        monkeypatch.setattr(routing, "_plan", fake_plan)
        assert routing.plan(self.POINTS, "default") == {"round": routing.STRAY_ROUNDS + 1}
        assert [len(h) for h in held[:-1]] == list(range(routing.STRAY_ROUNDS))
        assert held[-1] == [], "the final round starts with no earlier reading"

    def test_a_plan_without_strays_is_one_round(self, monkeypatch) -> None:
        seen = self.fake(monkeypatch, strays=0)
        assert routing.plan(self.POINTS, "default") == {"round": 1}
        assert len(seen) == 1


class TestRuns:
    def test_a_run_of_dirt_trails_one_after_another_is_one_run(self) -> None:
        dirt = frozenset({1, 2, 3})
        far = [100.0] * 6
        assert trail_touch.runs([1, 2, 9, 3, 3, 9], far, dirt) == [(0, 2), (3, 5)]
        assert trail_touch.runs([9, 9], far, dirt) == []
        assert trail_touch.runs([1], far, dirt) == [(0, 1)]

    def test_a_joined_trail_counts_with_the_touched_one_and_a_separate_one_does_not(self) -> None:
        """'Connecting trails too': 2 follows the touched 1 without a road between."""
        dirt = frozenset({1, 2, 3})
        far = [100.0] * 4
        assert trail_touch.strays([1, 2, 9, 3], far, dirt, frozenset({1})) == [(3, 4)]
        assert trail_touch.strays([1, 2, 9, 3], far, dirt, frozenset({3})) == [(0, 2)]
        assert trail_touch.strays([1, 2, 9, 3], far, dirt, frozenset({2, 3})) == []

    def test_a_trail_across_a_short_bridge_or_road_is_joined(self) -> None:
        """A paved bridge or a road crossed between two trails joins them; a longer road
        between them does not."""
        dirt = frozenset({1, 2})
        kept = frozenset({1})
        assert trail_touch.strays([1, 9, 2], [200.0, 12.0, 300.0], dirt, kept) == []
        assert trail_touch.strays([1, 9, 2], [200.0, 400.0, 300.0], dirt, kept) == [(2, 3)]

    def test_the_strip_across_a_stray_is_small_and_along_it(self) -> None:
        ring = trail_touch.block_ring(-77.0, 38.9, 90.0)
        assert ring[0] == ring[-1] and len(ring) == 5
        lons = [p[0] for p in ring]
        lats = [p[1] for p in ring]
        along = (max(lons) - min(lons)) * 111_320.0 * 0.7782
        across = (max(lats) - min(lats)) * 110_540.0
        assert along == pytest.approx(trail_touch.BLOCK_ALONG_M, rel=0.05)
        assert across == pytest.approx(trail_touch.BLOCK_ACROSS_M, rel=0.05)


class TestStrayRings:
    @staticmethod
    def pieces(ways):
        from types import SimpleNamespace

        return [
            SimpleNamespace(
                way_id=w, lon=-77.0 + i * 0.001, lat=38.9, metres=100.0, heading_in=90.0
            )
            for i, w in enumerate(ways)
        ]

    def test_singletrack_joined_to_a_touched_trail_is_still_left_out(self) -> None:
        ways = {1: "mtb", 2: "singletrack"}
        rings = trail_touch.stray_rings(self.pieces([1, 2]), ways, frozenset({1}))
        assert len(rings) == 1
        assert min(p[0] for p in rings[0]) > -77.0 + 0.0005

    def test_any_dirt_leaves_out_only_singletrack(self) -> None:
        ways = {1: "mtb", 3: "mtb", 2: "singletrack"}
        pieces = self.pieces([1, 9, 3, 9, 2])
        assert len(trail_touch.stray_rings(pieces, ways, frozenset(), any_dirt=True)) == 1
        assert len(trail_touch.stray_rings(pieces, ways, frozenset())) == 3
