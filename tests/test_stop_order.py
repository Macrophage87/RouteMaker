"""Stops in any order (OWNER-DECISIONS 449): the solver and POST /api/stop-order.

The solver (`routemaker.stoporder`) is checked against brute force over every
order on random asymmetric matrices, so a wrong recurrence or a lost fixed end
shows as a cheaper order it missed. The endpoint is checked with the router
replaced at its one network function (`core.routing._transport`), as the route
API's tests do: what it asks the router for, and how it answers with and
without the router's matrix.
"""

from __future__ import annotations

import itertools
import json
import math
import random

import pytest
from test_route_api import FakeRouter

from core import presets, routing, stoporder
from routemaker import stoporder as solver

pytestmark = pytest.mark.usefixtures("weekday_clock")

ORDER_PATH = "/api/stop-order"


def brute(cost) -> float:
    n = len(cost)
    return min(
        solver.total(cost, [0, *middle, n - 1])
        for middle in itertools.permutations(range(1, n - 1))
    )


def random_matrix(rng: random.Random, n: int) -> list[list[float]]:
    return [[0.0 if i == j else rng.uniform(1, 100) for j in range(n)] for i in range(n)]


class TestSolver:
    @pytest.mark.parametrize("n", [4, 5, 6, 7, 8])
    def test_the_exact_order_is_the_cheapest_of_every_order(self, n) -> None:
        rng = random.Random(449 + n)
        for _ in range(25):
            cost = random_matrix(rng, n)
            chosen = solver.best_order(cost)
            assert chosen.exact
            assert chosen.order[0] == 0 and chosen.order[-1] == n - 1
            assert sorted(chosen.order) == list(range(n))
            assert chosen.after == pytest.approx(solver.total(cost, chosen.order))
            # Either the cheapest order, or the rider's own when it is within 1% of it.
            cheapest = brute(cost)
            if chosen.changed:
                assert chosen.after == pytest.approx(cheapest)
            else:
                assert chosen.before - cheapest <= chosen.before * solver.MIN_SAVING_FRACTION

    def test_costs_are_read_in_the_direction_ridden(self) -> None:
        # 0 -> 2 -> 1 -> 3 is cheap one way only: the reverse legs cost 100.
        big = 100.0
        cost = [
            [0, 50, 1, big],
            [big, 0, big, 1],
            [big, 1, 0, 50],
            [big, big, big, 0],
        ]
        chosen = solver.best_order(cost)
        assert chosen.order == [0, 2, 1, 3]
        assert (chosen.before, chosen.after) == (50 + big + 50, 3)

    def test_the_riders_order_wins_a_tie(self) -> None:
        cost = [[0, 1, 1, 9], [1, 0, 1, 1], [1, 1, 0, 1], [9, 1, 1, 0]]
        chosen = solver.best_order(cost)
        assert chosen.order == [0, 1, 2, 3]
        assert not chosen.changed

    def test_a_saving_under_one_percent_keeps_the_riders_order(self) -> None:
        # Own order 0-1-2-3 costs 1000; 0-2-1-3 costs 995 (0.5% less).
        cost = [[0, 300, 300, 0], [0, 0, 400, 300], [0, 395, 0, 300], [0, 0, 0, 0]]
        assert solver.total(cost, [0, 1, 2, 3]) == 1000
        assert solver.total(cost, [0, 2, 1, 3]) == 995
        assert not solver.best_order(cost).changed

    def test_the_local_search_never_moves_the_ends(self, monkeypatch) -> None:
        # Asymmetric costs that make reversing a run through the destination cheap.
        monkeypatch.setattr(solver, "EXACT_MAX_STOPS", 0)
        rng = random.Random(4493)
        for _ in range(20):
            cost = random_matrix(rng, 10)
            for i in range(9):
                cost[i][9] = 1000.0  # reaching the destination is dear from anywhere
                cost[9][i] = 0.1  # leaving it is cheap
            order = solver.best_order(cost).order
            assert order[0] == 0 and order[-1] == 9 and sorted(order) == list(range(10))

    def test_a_saving_over_one_percent_is_taken(self) -> None:
        # Own order costs 1000; 0-2-1-3 costs 980 (2% less).
        cost = [[0, 300, 300, 0], [0, 0, 400, 300], [0, 380, 0, 300], [0, 0, 0, 0]]
        chosen = solver.best_order(cost)
        assert chosen.order == [0, 2, 1, 3] and (chosen.before, chosen.after) == (1000, 980)

    def test_a_leg_the_router_could_not_join_is_avoided(self) -> None:
        cost = [[0, 1, 5, 9], [1, 0, None, 1], [5, 1, 0, 1], [9, 1, 1, 0]]
        chosen = solver.best_order(cost)
        assert chosen.before == math.inf
        assert chosen.order == [0, 2, 1, 3]
        assert chosen.after == 7

    def test_when_no_order_joins_the_riders_order_stays(self) -> None:
        cost = [[0, None, None, None]] + [[None, 0, None, None]] * 3
        chosen = solver.best_order(cost)
        assert chosen.order == [0, 1, 2, 3] and not chosen.changed

    @pytest.mark.parametrize("n", [0, 1, 2, 3])
    def test_fewer_than_two_stops_is_nothing_to_choose(self, n) -> None:
        cost = [[1.0] * n for _ in range(n)]
        assert solver.best_order(cost).order == list(range(n))

    def test_a_matrix_that_is_not_square_is_refused(self) -> None:
        with pytest.raises(ValueError):
            solver.best_order([[0, 1, 2], [0, 1]])

    def test_past_ten_stops_the_local_search_improves_on_the_riders_order(self) -> None:
        rng = random.Random(4490)
        # Points on a line, given in a shuffled order: the best order is along the line.
        xs = [0.0, *rng.sample(range(1, 24), 23), 24.0]
        cost = [[abs(a - b) for b in xs] for a in xs]
        chosen = solver.best_order(cost)
        assert not chosen.exact
        assert chosen.after == pytest.approx(24.0)
        assert [xs[i] for i in chosen.order] == sorted(xs)

    def test_the_local_search_comes_close_to_the_exact_answer(self, monkeypatch) -> None:
        # Near-metric costs, as riding times are: straight lines stretched by up to
        # 30%, differently each way.
        rng = random.Random(4491)
        monkeypatch.setattr(solver, "EXACT_MAX_STOPS", 0)
        for _ in range(30):
            spots = [(rng.random(), rng.random()) for _ in range(8)]
            cost = [[math.dist(a, b) * rng.uniform(1, 1.3) for b in spots] for a in spots]
            chosen = solver.best_order(cost)
            assert not chosen.exact
            assert chosen.order[0] == 0 and chosen.order[-1] == 7
            assert sorted(chosen.order) == list(range(8))
            assert chosen.after <= chosen.before
            assert min(chosen.after, chosen.before) <= brute(cost) * 1.02

    def test_the_local_search_is_repeatable(self, monkeypatch) -> None:
        monkeypatch.setattr(solver, "EXACT_MAX_STOPS", 0)
        cost = random_matrix(random.Random(4492), 12)
        assert solver.best_order(cost).order == solver.best_order(cost).order


# Points a few blocks apart in Northwest DC: start, three stops, end.
POINTS = [[-77.05, 38.90], [-77.03, 38.90], [-77.04, 38.90], [-77.02, 38.90], [-77.01, 38.90]]


def matrix_answer(times, km=None) -> dict:
    km = km or times
    return {
        "sources_to_targets": [
            [
                {"from_index": i, "to_index": j, "time": t, "distance": d}
                for j, (t, d) in enumerate(zip(trow, drow, strict=True))
            ]
            for i, (trow, drow) in enumerate(zip(times, km, strict=True))
        ]
    }


def straight(points) -> list[list[float]]:
    """Riding times (s) proportional to the straight line between the points."""
    return [[math.dist(a, b) * 10_000 for b in points] for a in points]


def along_the_line(points) -> list[list[float]]:
    """Riding times (s) proportional to the distance along the parallel."""
    return [[abs(a[0] - b[0]) * 10_000 for b in points] for a in points]


@pytest.fixture
def router(monkeypatch):
    def install(fake: FakeRouter) -> FakeRouter:
        monkeypatch.setattr(routing, "_transport", fake)
        return fake

    return install


def post(client, body):
    return client.post(ORDER_PATH, data=json.dumps(body), content_type="application/json")


@pytest.mark.django_db
class TestEndpoint:
    def test_the_stops_come_back_in_the_order_that_rides_least(self, client, router) -> None:
        fake = router(FakeRouter({"sources_to_targets": matrix_answer(along_the_line(POINTS))}))
        response = post(client, {"points": POINTS, "preset": "default"})
        assert response.status_code == 200
        body = response.json()
        assert body["order"] == [0, 2, 1, 3, 4]
        assert body["changed"] is True and body["by"] == "riding_time" and body["exact"] is True
        assert body["before_s"] == 600 and body["after_s"] == 400
        assert body["before_m"] == 600_000 and body["after_m"] == 400_000
        assert fake.endpoints() == ["sources_to_targets"]

    def test_the_matrix_is_asked_with_the_rides_own_graph_and_costing(self, client, router) -> None:
        fake = router(FakeRouter({"sources_to_targets": matrix_answer(along_the_line(POINTS))}))
        body = {
            "points": POINTS,
            "preset": "cargo",
            "stress": 85,
            "hills": -40,
            "assist": True,
            "avoid_gravel": True,
            "when": "weekday_offpeak",
        }
        assert post(client, body).status_code == 200
        url, payload = fake.calls[0]
        assert url.startswith(routing.settings.VALHALLA_UPSTREAMS["ebike"])
        assert payload["costing"] == "bicycle"
        assert payload["costing_options"] == presets.costing(
            "cargo", 85, -40, assist=True, avoid_gravel=True
        )
        assert payload["sources"] == payload["targets"]
        assert payload["sources"] == [{"lon": lon, "lat": lat} for lon, lat in POINTS]

    def test_lengths_are_read_in_the_direction_ridden(self, client, router) -> None:
        times = along_the_line(POINTS)
        km = [[float(10 * i + j) for j in range(5)] for i in range(5)]  # asymmetric
        router(FakeRouter({"sources_to_targets": matrix_answer(times, km)}))
        body = post(client, {"points": POINTS, "preset": "default"}).json()
        assert body["order"] == [0, 2, 1, 3, 4]
        # 0->2, 2->1, 1->3, 3->4 against 0->1, 1->2, 2->3, 3->4, in metres.
        assert body["after_m"] == (2 + 21 + 13 + 34) * 1000
        assert body["before_m"] == (1 + 12 + 23 + 34) * 1000

    def test_the_matrix_is_on_the_graph_and_costing_the_route_would_use(
        self, client, router, monkeypatch
    ) -> None:
        asked = []

        def no_route(variant, request, deadline):
            asked.append((variant, request["costing_options"]))
            raise routing.RouterRefused(400, 442, "no path")

        monkeypatch.setattr(routing, "_route", no_route)
        fake = router(FakeRouter({"sources_to_targets": matrix_answer(along_the_line(POINTS))}))
        for body in (
            {"preset": "default", "stress": 90, "hills": 30, "when": "weekday_rush"},
            {"preset": "cargo", "carrying": "people", "assist": True, "avoid_gravel": True},
            {"preset": "gravel", "hills": -60},
            {"preset": "mass-ride"},
        ):
            body = {"points": POINTS, **body}
            assert (
                client.post(
                    "/api/route", data=json.dumps(body), content_type="application/json"
                ).status_code
                == 422
            )
            assert post(client, body).status_code == 200
            variant, costing = asked[-1]
            url, payload = fake.calls[-1]
            assert url == f"{routing.settings.VALHALLA_UPSTREAMS[variant]}/sources_to_targets"
            assert payload["costing_options"] == costing

    def test_a_weekend_router_that_does_not_answer_leaves_it_to_the_standard_graph(
        self, client, router, monkeypatch
    ) -> None:
        monkeypatch.setattr(routing, "_is_promoted", lambda variant: True)
        monkeypatch.setattr(routing, "_twin_down", lambda variant: False)
        marked = []
        monkeypatch.setattr(routing, "_mark_twin", lambda variant, ok: marked.append((variant, ok)))
        matrix = matrix_answer(along_the_line(POINTS))
        fake = router(
            FakeRouter({"sources_to_targets": [routing.RouterUnavailable("hung"), matrix]})
        )
        body = post(client, {"points": POINTS, "preset": "default", "when": "weekend"}).json()
        assert body["by"] == "riding_time" and body["order"] == [0, 2, 1, 3, 4]
        urls = [url for url, _ in fake.calls]
        assert urls[0].startswith(routing.settings.VALHALLA_UPSTREAMS["weekend"])
        assert urls[1].startswith(routing.settings.VALHALLA_UPSTREAMS["standard"])
        assert marked == [("weekend", False)]

    def test_a_weekend_router_with_no_tiles_leaves_it_to_the_standard_graph(
        self, client, router, monkeypatch
    ) -> None:
        monkeypatch.setattr(routing, "_is_promoted", lambda variant: True)
        monkeypatch.setattr(routing, "_twin_down", lambda variant: False)
        marked = []
        monkeypatch.setattr(routing, "_mark_twin", lambda variant, ok: marked.append((variant, ok)))
        matrix = matrix_answer(along_the_line(POINTS))
        refusal = routing.RouterRefused(400, 171, "no suitable edges")
        router(FakeRouter({"sources_to_targets": [refusal, matrix]}))
        body = post(client, {"points": POINTS, "preset": "default", "when": "weekend"}).json()
        assert body["by"] == "riding_time"
        assert marked == [("weekend", False)]

    def test_a_long_ride_is_ordered_by_straight_line_without_the_router(self, client, router):
        # About 99 mi (159 km) of straight line, past the long-ride line and under the cap.
        far = [[-77.05, 38.90], [-76.60, 39.30], [-77.00, 38.95], [-76.62, 39.28]]
        fake = router(FakeRouter({}))
        response = post(client, {"points": far, "preset": "default", "confirm_long": True})
        assert response.status_code == 200
        assert response.json()["by"] == "straight_line"
        assert fake.calls == []

    def test_a_loop_whose_way_back_is_too_long_is_refused(self, client, router) -> None:
        router(FakeRouter({}))
        far = [[-77.40, 38.75], [-76.50, 39.40], [-76.55, 39.35]]
        response = post(client, {"points": far, "preset": "default", "loop": True})
        assert response.status_code == 400
        assert "too long" in response.json()["error"]

    def test_an_order_already_best_is_unchanged(self, client, router) -> None:
        ordered = [POINTS[0], POINTS[2], POINTS[1], POINTS[3], POINTS[4]]
        router(FakeRouter({"sources_to_targets": matrix_answer(along_the_line(ordered))}))
        body = post(client, {"points": ordered, "preset": "default"}).json()
        assert body["order"] == [0, 1, 2, 3, 4] and body["changed"] is False
        assert body["before_s"] == body["after_s"] == 400

    def test_a_loop_the_rider_chose_moves_every_point_after_the_start(self, client, router) -> None:
        # A square ridden corner to opposite corner crosses itself; round its edge
        # is shorter. The last point given is a stop in a loop, so it may move.
        points = [[-77.05, 38.90], [-77.04, 38.91], [-77.04, 38.90], [-77.05, 38.91]]
        fake = router(
            FakeRouter({"sources_to_targets": matrix_answer(straight([*points, points[0]]))})
        )
        body = post(client, {"points": points, "preset": "default", "loop": True}).json()
        assert body["changed"] is True
        # Round the edge, one way or the other; the finish (the start again) is not returned.
        assert body["order"] in ([0, 2, 1, 3], [0, 3, 1, 2])
        # The matrix carries the start again as the loop's finish.
        assert fake.calls[0][1]["sources"][-1] == {"lon": -77.05, "lat": 38.90}
        assert len(fake.calls[0][1]["sources"]) == 5

    def test_the_same_points_without_the_loop_keep_their_end(self, client, router) -> None:
        points = [[-77.05, 38.90], [-77.04, 38.91], [-77.04, 38.90], [-77.05, 38.91]]
        router(FakeRouter({"sources_to_targets": matrix_answer(straight(points))}))
        body = post(client, {"points": points, "preset": "default"}).json()
        assert body["order"][-1] == 3

    def test_without_the_routers_matrix_it_orders_by_straight_line(self, client, router) -> None:
        router(
            FakeRouter({"sources_to_targets": routing.RouterRefused(400, 106, "Try any of: route")})
        )
        body = post(client, {"points": POINTS, "preset": "default"}).json()
        assert body["order"] == [0, 2, 1, 3, 4] and body["by"] == "straight_line"
        assert body["before_s"] is None and body["after_s"] is None
        assert body["after_m"] < body["before_m"]

    def test_a_router_that_does_not_answer_falls_back_too(self, client, router) -> None:
        router(FakeRouter({"sources_to_targets": routing.RouterUnavailable("down")}))
        body = post(client, {"points": POINTS, "preset": "default"}).json()
        assert body["by"] == "straight_line" and body["order"] == [0, 2, 1, 3, 4]

    def test_a_matrix_of_the_wrong_shape_falls_back(self, client, router) -> None:
        router(FakeRouter({"sources_to_targets": {"sources_to_targets": [[]]}}))
        body = post(client, {"points": POINTS, "preset": "default"}).json()
        assert body["by"] == "straight_line"

    def test_a_pair_the_router_cannot_join_is_not_ridden(self, client, router) -> None:
        times = along_the_line(POINTS)
        times[0][2] = None  # start to the middle stop cannot be ridden that way
        router(FakeRouter({"sources_to_targets": matrix_answer(times, along_the_line(POINTS))}))
        body = post(client, {"points": POINTS, "preset": "default"}).json()
        assert body["order"][1] != 2
        assert body["after_s"] is not None

    @pytest.mark.parametrize(
        "points,loop",
        [
            (POINTS[:3], False),  # start, one stop, end
            (POINTS[:2], True),  # a loop of a start and one stop
        ],
    )
    def test_with_fewer_than_two_stops_nothing_is_asked(self, client, router, points, loop) -> None:
        fake = router(FakeRouter({}))
        body = post(client, {"points": points, "preset": "default", "loop": loop}).json()
        assert body["order"] == list(range(len(points)))
        assert body["changed"] is False and body["by"] is None
        assert fake.calls == []

    def test_a_ride_that_ends_on_its_start_keeps_that_end(self, client, router) -> None:
        points = [*POINTS[:4], POINTS[0]]
        router(FakeRouter({"sources_to_targets": matrix_answer(along_the_line(points))}))
        body = post(client, {"points": points, "preset": "default"}).json()
        assert body["order"][0] == 0 and body["order"][-1] == 4

    def test_the_body_is_checked_as_a_route_requests_is(self, client, router) -> None:
        router(FakeRouter({}))
        response = post(client, {"points": [[0, 0], [1, 1]], "preset": "default"})
        assert response.status_code == 400
        assert "outside the area" in response.json()["error"]

    def test_a_router_past_the_budget_leaves_the_straight_line_order(self, client, router):
        router(FakeRouter({"sources_to_targets": routing.DeadlineExceeded("late")}))
        response = post(client, {"points": POINTS, "preset": "default"})
        assert response.status_code == 200
        assert response.json()["by"] == "straight_line"

    def test_a_weekend_router_gets_the_shorter_limit(self, client, router, monkeypatch) -> None:
        monkeypatch.setattr(routing, "_is_promoted", lambda variant: True)
        monkeypatch.setattr(routing, "_twin_down", lambda variant: False)
        monkeypatch.setattr(routing, "_mark_twin", lambda variant, ok: None)
        limits = []

        def transport(url, payload, timeout):
            limits.append(timeout)
            return matrix_answer(along_the_line(POINTS))

        monkeypatch.setattr(routing, "_transport", transport)
        post(client, {"points": POINTS, "preset": "default", "when": "weekend"})
        assert limits and limits[0] <= routing.WEEKEND_TIMEOUT_S


def test_the_long_ride_line_is_the_route_apis() -> None:
    from core import api

    assert stoporder.LONG_SPAN_M == api.CONFIRM_SPAN_M


def test_free_stops_counts_the_points_that_may_move() -> None:
    assert stoporder.free_stops(POINTS, loop=False) == 3
    assert stoporder.free_stops(POINTS, loop=True) == 4
    assert stoporder.free_stops([*POINTS[:3], POINTS[0]], loop=True) == 2
    assert stoporder.free_stops([], loop=False) == 0


def test_the_routers_serve_the_matrix() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "valhalla"
    for config in sorted(root.glob("valhalla-*.json")):
        actions = json.loads(config.read_text())["loki"]["actions"]
        assert "sources_to_targets" in actions, config.name
