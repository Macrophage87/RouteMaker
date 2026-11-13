"""A ride's loop from a start and a distance (`core.bike_loop`, backlog 2026-11-12 item 5) and
POST /api/route/loop-shapes. The router is a stand-in: each leg rides its straight line, longer
by a factor, so the sizing can be checked against known answers."""

from __future__ import annotations

import json

import pytest

from core import bike_loop, dedodge, routing
from routemaker.geo import Point, haversine

START = (-77.0365, 38.8977)
MILE = bike_loop.METRES_PER_MILE


def straight(a, b) -> float:
    return haversine(Point(*a), Point(*b))


class FakeAsk:
    """A /route: each leg its straight line, `factor` times longer (by bearing, where given)."""

    def __init__(self, factor: float = 1.3, by_bearing=None, refuse=(), climb_m: float = 10.0):
        self.factor = factor
        self.by_bearing = by_bearing or {}
        self.refuse = set(refuse)
        self.climb_m = climb_m
        self.asked: list[list[tuple[float, float]]] = []

    def bearing_of(self, points) -> float:
        lon0, lat0 = points[0]
        lon1, lat1 = points[1]
        import math

        dx = (lon1 - lon0) * math.cos(math.radians(lat0))
        dy = lat1 - lat0
        return round(math.degrees(math.atan2(dx, dy)) % 360.0)

    def __call__(self, payload: dict, cap_s: float) -> dict:
        points = [(p["lon"], p["lat"]) for p in payload["locations"]]
        self.asked.append(points)
        bearing = self.bearing_of(points)
        if bearing in self.refuse:
            raise routing.RouterRefused(400, 442, "no way")
        factor = self.by_bearing.get(bearing, self.factor)
        legs = []
        total = 0.0
        for a, b in zip(points, points[1:], strict=False):
            metres = straight(a, b) * factor
            total += metres
            middle = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            legs.append(
                {
                    "shape": dedodge.encode_polyline6([a, middle, b]),
                    "summary": {"length": metres / 1000.0},
                    "elevation": [0.0, self.climb_m / 3.0],
                }
            )
        return {"trip": {"legs": legs, "summary": {"length": total / 1000.0}}}, "standard"


def payload_of(points):
    return {
        "locations": [{"lon": lon, "lat": lat} for lon, lat in points],
    }


def router(ask, trace=None, left_s: float = 30.0) -> bike_loop.Router:
    return bike_loop.Router(routing.clock() + left_s, ask, trace)


class TestSearch:
    def test_shapes_come_near_the_target_on_a_map_that_winds_as_guessed(self) -> None:
        ask = FakeAsk(factor=1.3)
        shapes, note = bike_loop.search(router(ask), START, 30 * MILE, payload_of)
        assert 1 <= len(shapes) <= bike_loop.SHAPES
        for shape in shapes:
            assert abs(shape.metres - 30 * MILE) / (30 * MILE) <= bike_loop.TOLERANCE
        # Six directions, nothing resized: the first guess was right.
        assert note.tried == len(bike_loop.BEARINGS)
        assert note.resized == 0

    def test_a_map_that_winds_more_is_sized_again_from_what_was_ridden(self) -> None:
        ask = FakeAsk(factor=2.2)
        shapes, note = bike_loop.search(router(ask), START, 30 * MILE, payload_of)
        assert note.resized > 0
        assert shapes
        assert abs(shapes[0].metres - 30 * MILE) / (30 * MILE) <= bike_loop.TOLERANCE

    def test_the_shapes_kept_head_apart(self) -> None:
        ask = FakeAsk(factor=1.3)
        shapes, _note = bike_loop.search(router(ask), START, 20 * MILE, payload_of)
        assert len(shapes) >= 2
        for i, a in enumerate(shapes):
            for b in shapes[i + 1 :]:
                assert bike_loop.angle_between(a.heading, b.heading) >= bike_loop.APART_DEG

    def test_a_refused_direction_is_left_out_not_a_failure(self) -> None:
        ask = FakeAsk(factor=1.3, refuse={0, 60, 120, 180, 240})
        shapes, _note = bike_loop.search(router(ask), START, 20 * MILE, payload_of)
        assert [s.bearing for s in shapes] == [300.0]

    def test_no_direction_ridden_is_no_loop(self) -> None:
        ask = FakeAsk(refuse={0, 60, 120, 180, 240, 300})
        with pytest.raises(bike_loop.NoLoop):
            bike_loop.search(router(ask), START, 20 * MILE, payload_of)

    def test_a_router_that_answers_nothing_is_down_not_no_loop(self) -> None:
        def down(payload, cap_s):
            raise routing.RouterUnavailable("down")

        with pytest.raises(routing.RouterUnavailable):
            bike_loop.search(router(down), START, 20 * MILE, payload_of)

    def test_the_quietest_near_shape_comes_first(self) -> None:
        ask = FakeAsk(factor=1.3)
        quiet_by_leg_start: dict = {}

        def trace(shape, cap_s):
            legs = shape.legs
            # The shape heading south-east is the quiet one.
            corner = legs[1][0]
            quiet = corner[1] < START[1] and corner[0] > START[0]
            metres = sum(straight(a, b) for leg in legs for a, b in zip(leg, leg[1:], strict=False))
            quiet_by_leg_start[corner] = quiet
            return {"1": metres if quiet else 0.0, "4": 0.0 if quiet else metres}

        shapes, note = bike_loop.search(router(ask, trace), START, 20 * MILE, payload_of)
        assert note.traced >= 2
        first = shapes[0]
        assert first.quiet_m and first.quiet_m > 0
        assert first.busy_m == 0.0

    def test_a_spur_ranks_below_a_clean_loop_near_the_target(self) -> None:
        clean = bike_loop.Shape(0.0, 1.0, [], [], 20 * MILE, 0.0, spur=0.05, quiet_m=0.0)
        spur = bike_loop.Shape(120.0, 1.0, [], [], 20 * MILE, 0.0, spur=0.5, quiet_m=20 * MILE)
        assert bike_loop.pick([spur, clean], 20 * MILE, 1) == [clean]

    def test_a_far_shape_never_sits_under_a_near_one(self) -> None:
        near = bike_loop.Shape(0.0, 1.0, [], [], 20 * MILE, 0.0, spur=0.0)
        far = bike_loop.Shape(180.0, 1.0, [], [], 30 * MILE, 0.0, spur=0.0)
        assert bike_loop.pick([far, near], 20 * MILE) == [near]

    def test_off_target_everywhere_the_nearest_shapes_are_kept(self) -> None:
        a = bike_loop.Shape(0.0, 1.0, [], [], 26 * MILE, 0.0, spur=0.0)
        b = bike_loop.Shape(180.0, 1.0, [], [], 30 * MILE, 0.0, spur=0.0)
        assert bike_loop.pick([b, a], 20 * MILE) == [a, b]

    def test_a_corner_off_the_map_is_not_asked(self) -> None:
        ask = FakeAsk(factor=1.3)
        edge = (-78.04, 38.21)  # the coverage box's south-west corner
        shapes, _note = bike_loop.search(router(ask), edge, 30 * MILE, payload_of)
        for points in ask.asked:
            for lon, lat in points:
                assert -78.05 <= lon and 38.2 <= lat
        assert all(90 <= s.bearing % 360 or s.bearing == 0 for s in shapes)


class TestShapeOut:
    def test_a_shape_is_planned_through_its_corners_as_via_points(self) -> None:
        ask = FakeAsk(factor=1.3)
        shapes, _note = bike_loop.search(router(ask), START, 20 * MILE, payload_of)
        out = bike_loop.shape_out(shapes[0], 20 * MILE)
        assert out["via_points"] == [1, 2]
        assert len(out["points"]) == 4
        assert out["points"][0] == out["points"][-1]
        assert out["points"][0] == [round(START[0], 6), round(START[1], 6)]
        assert out["near_target"] is True
        assert out["quiet_pct"] is None  # not traced
        assert out["geometry"]["type"] == "LineString"
        assert out["climb_m"] > 0

    def test_quiet_is_a_share_of_the_loop(self) -> None:
        shape = bike_loop.Shape(
            0.0, 1.0, [(0, 0), (1, 1), (2, 2)], [(0, 0), (1, 1)], 1000.0, 5.0, 0.0, 750.0, 250.0
        )
        assert bike_loop.shape_out(shape, 1000.0)["quiet_pct"] == 75


class TestOffered:
    @pytest.mark.parametrize("name", ["default", "trailmaxxing", "gravel", "road-bike"])
    def test_the_bike_ride_types_plan_it(self, name) -> None:
        assert bike_loop.offered(name)

    @pytest.mark.parametrize(
        "name",
        ["mass-ride", "bikeshare", "rebalance", "bike-transit", "bikeshare-transit", "walk", "run"],
    )
    def test_trips_with_an_end_mass_ride_and_run_do_not(self, name) -> None:
        assert not bike_loop.offered(name)


PATH = "/api/route/loop-shapes"


@pytest.mark.django_db
class TestEndpoint:
    def post(self, client, body: dict):
        return client.post(PATH, data=json.dumps(body), content_type="application/json")

    @pytest.fixture
    def stand_in(self, monkeypatch):
        ask = FakeAsk(factor=1.3)

        def fake_ask(variant, endpoint, payload, deadline):
            assert endpoint == "route"
            return ask(payload, 1.0)

        monkeypatch.setattr(bike_loop.stoporder, "_ask", fake_ask)
        monkeypatch.setattr(bike_loop.stoporder, "ride_exclusions", lambda *a, **k: [])
        monkeypatch.setattr(routing, "trace_leg", lambda *a, **k: None)
        return ask

    def test_shapes_for_a_bike_ride_type(self, client, stand_in) -> None:
        answer = self.post(
            client, {"start": list(START), "target_distance_m": 20 * MILE, "preset": "default"}
        )
        assert answer.status_code == 200, answer.content
        body = answer.json()
        assert 1 <= len(body["shapes"]) <= 3
        assert body["shapes"][0]["via_points"] == [1, 2]
        assert body["tried"] >= 6
        # Every triangle asked rides the ride type's own costing.
        assert stand_in.asked

    def test_the_corners_go_through_and_the_start_breaks(self, client, monkeypatch) -> None:
        seen: list[dict] = []
        ask = FakeAsk(factor=1.3)

        def fake_ask(variant, endpoint, payload, deadline):
            seen.append(payload)
            return ask(payload, 1.0)

        monkeypatch.setattr(bike_loop.stoporder, "_ask", fake_ask)
        monkeypatch.setattr(bike_loop.stoporder, "ride_exclusions", lambda *a, **k: [])
        monkeypatch.setattr(routing, "trace_leg", lambda *a, **k: None)
        self.post(
            client, {"start": list(START), "target_distance_m": 10 * MILE, "preset": "gravel"}
        )
        types = [loc["type"] for loc in seen[0]["locations"]]
        assert types == ["break", "through", "through", "break"]
        assert seen[0]["costing"] == "bicycle"

    @pytest.mark.parametrize("preset", ["run", "mass-ride", "bikeshare", "walk"])
    def test_a_ride_type_without_it_is_refused(self, client, stand_in, preset) -> None:
        answer = self.post(
            client, {"start": list(START), "target_distance_m": 10 * MILE, "preset": preset}
        )
        assert answer.status_code in (400, 422)

    @pytest.mark.parametrize("miles", [1, 150])
    def test_the_distance_is_held_to_its_range(self, client, stand_in, miles) -> None:
        answer = self.post(
            client, {"start": list(START), "target_distance_m": miles * MILE, "preset": "default"}
        )
        assert answer.status_code in (400, 422)

    def test_a_start_off_the_map_is_refused(self, client, stand_in) -> None:
        answer = self.post(
            client, {"start": [-80.0, 40.0], "target_distance_m": 10 * MILE, "preset": "default"}
        )
        assert answer.status_code in (400, 422)

    def test_no_loop_is_422(self, client, monkeypatch) -> None:
        ask = FakeAsk(refuse={0, 60, 120, 180, 240, 300})
        monkeypatch.setattr(bike_loop.stoporder, "_ask", lambda v, e, p, d: ask(p, 1.0))
        monkeypatch.setattr(bike_loop.stoporder, "ride_exclusions", lambda *a, **k: [])
        answer = self.post(
            client, {"start": list(START), "target_distance_m": 10 * MILE, "preset": "default"}
        )
        assert answer.status_code == 422
        assert answer.json()["code"] == "no_loop"

    def test_a_router_down_is_503(self, client, monkeypatch) -> None:
        def down(*a, **k):
            raise routing.RouterUnavailable("down")

        monkeypatch.setattr(bike_loop.stoporder, "_ask", down)
        monkeypatch.setattr(bike_loop.stoporder, "ride_exclusions", lambda *a, **k: [])
        answer = self.post(
            client, {"start": list(START), "target_distance_m": 10 * MILE, "preset": "default"}
        )
        assert answer.status_code == 503

    def test_quiet_is_read_on_the_graph_that_answered(self, client, monkeypatch) -> None:
        # A twin that is down answers from its fallback: the trace goes there, and the stress
        # is read with that graph set (hunt X1: outside a plan none is, and a timed closure
        # read as a tier-1 path).
        ask = FakeAsk(factor=1.3)
        traced_on: list[str] = []
        read_on: list = []

        def fake_ask(variant, endpoint, payload, deadline):
            answer, _graph = ask(payload, 1.0)
            # Not the ride type's own graph: the one a twin that is down fell back to.
            return answer, "fallback-graph"

        def fake_trace(variant, costing, shape, deadline):
            traced_on.append(variant)
            return {"edges": [], "shape": shape}

        def fake_breakdown(pieces, when, roadway_only=False):
            read_on.append(routing._routed_graph.get())
            return {"1": 100.0, "2": 0.0, "3": 0.0, "4": 0.0, "5": 0.0}, {}

        monkeypatch.setattr(bike_loop.stoporder, "_ask", fake_ask)
        monkeypatch.setattr(bike_loop.stoporder, "ride_exclusions", lambda *a, **k: [])
        monkeypatch.setattr(routing, "trace_leg", fake_trace)
        monkeypatch.setattr(routing, "pieces_of_trace", lambda trace: [])
        monkeypatch.setattr(routing, "breakdown", fake_breakdown)
        answer = self.post(
            client, {"start": list(START), "target_distance_m": 10 * MILE, "preset": "road-bike"}
        )
        assert answer.status_code == 200, answer.content
        assert traced_on and set(traced_on) == {"fallback-graph"}
        assert read_on and set(read_on) == {"fallback-graph"}
        assert routing._routed_graph.get() is None

    def test_the_roads_the_rider_closed_are_left_out(self, client, monkeypatch) -> None:
        asked_with: list = []
        ask = FakeAsk(factor=1.3)

        def exclusions(points, dials, reach_m=0.0):
            asked_with.append(dials.blocked)
            return []

        monkeypatch.setattr(bike_loop.stoporder, "_ask", lambda v, e, p, d: ask(p, 1.0))
        monkeypatch.setattr(bike_loop.stoporder, "ride_exclusions", exclusions)
        monkeypatch.setattr(routing, "trace_leg", lambda *a, **k: None)
        line = [[-77.03, 38.90], [-77.02, 38.90]]
        self.post(
            client,
            {
                "start": list(START),
                "target_distance_m": 10 * MILE,
                "preset": "default",
                "blocked_lines": [line],
            },
        )
        assert asked_with == [(((-77.03, 38.90), (-77.02, 38.90)),)]

    def test_a_cancelled_search_is_answered_as_cancelled(self, client, monkeypatch) -> None:
        def cancelled(*a, **k):
            raise routing.PlanCancelled("cancelled")

        monkeypatch.setattr(bike_loop.stoporder, "_ask", cancelled)
        monkeypatch.setattr(bike_loop.stoporder, "ride_exclusions", lambda *a, **k: [])
        answer = self.post(
            client, {"start": list(START), "target_distance_m": 10 * MILE, "preset": "default"}
        )
        assert answer.status_code == 409
