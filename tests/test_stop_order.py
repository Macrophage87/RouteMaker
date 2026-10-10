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


NO_PATH = routing.RouterRefused(400, 442, "no path")


def MatrixOnly(answers: dict) -> FakeRouter:
    """A router that refuses every /route (a pair it cannot join), so the matrix orders."""
    return FakeRouter({"route": NO_PATH, **answers})


class LegRouter(FakeRouter):
    """A router whose /route answers each leg from matrices over `points`: `cost`,
    `times` (s) and `km`, read in the direction ridden. A leg into the start's
    place, in a loop, is the finish (the last row and column)."""

    def __init__(self, points, cost, times=None, km=None, matrix=None) -> None:
        super().__init__({"sources_to_targets": matrix} if matrix else {})
        self.points = [tuple(p) for p in points]
        self.cost, self.times, self.km = cost, times or cost, km or cost

    def _index(self, location: dict, arriving: bool) -> int:
        at = (location["lon"], location["lat"])
        if arriving and at == self.points[0]:
            return len(self.points) - 1
        return self.points.index(at)

    def __call__(self, url: str, payload: dict, timeout: float) -> dict:
        if not url.endswith("/route"):
            return super().__call__(url, payload, timeout)
        self.calls.append((url, payload))
        locations = payload["locations"]
        legs = []
        for a, b in zip(locations, locations[1:], strict=False):
            i, j = self._index(a, False), self._index(b, True)
            summary = {"cost": self.cost[i][j], "time": self.times[i][j], "length": self.km[i][j]}
            legs.append({"summary": summary})
        return {"trip": {"legs": legs, "summary": {}}}

    def pairs_of(self, call) -> list[tuple[int, int]]:
        url, payload = call
        if not url.endswith("/route"):
            return []
        ids = [self._index(loc, k > 0) for k, loc in enumerate(payload["locations"])]
        return list(zip(ids, ids[1:], strict=False))

    def pairs(self) -> list[tuple[int, int]]:
        return [pair for call in self.calls for pair in self.pairs_of(call)]


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
    def test_the_order_is_by_the_routers_cost_as_any_route_is(self, client, router) -> None:
        # The quickest order starts by the busy way from the start to the middle stop;
        # the router prices that way's stress in, and the order the cost picks avoids it.
        times = along_the_line(POINTS)
        cost = [row[:] for row in times]
        cost[0][2] = 5_000.0
        km = [[t / 1000 for t in row] for row in times]
        fake = router(LegRouter(POINTS, cost, times, km))
        body = post(client, {"points": POINTS, "preset": "default"}).json()
        by_time = min(
            ([0, *m, 4] for m in itertools.permutations([1, 2, 3])),
            key=lambda o: solver.total(times, o),
        )
        assert by_time == [0, 2, 1, 3, 4]
        assert body["by"] == "route_cost" and body["exact"] is True
        assert body["order"] == [0, 1, 2, 3, 4] and body["changed"] is False
        assert body["before_s"] == body["after_s"] == 600
        assert body["before_m"] == body["after_m"] == 600
        assert "sources_to_targets" not in fake.endpoints()

    def test_a_new_order_reports_its_riding_time_and_length(self, client, router) -> None:
        times = along_the_line(POINTS)
        km = [[float(10 * i + j) for j in range(5)] for i in range(5)]  # asymmetric
        router(LegRouter(POINTS, times, times, km))
        body = post(client, {"points": POINTS, "preset": "default"}).json()
        assert body["by"] == "route_cost" and body["order"] == [0, 2, 1, 3, 4]
        assert body["before_s"] == 600 and body["after_s"] == 400
        assert body["after_m"] == (2 + 21 + 13 + 34) * 1000
        assert body["before_m"] == (1 + 12 + 23 + 34) * 1000

    def test_the_legs_are_a_plans_requests_and_every_pair_is_asked_once(
        self, client, router
    ) -> None:
        fake = router(LegRouter(POINTS, along_the_line(POINTS)))
        body = {"points": POINTS, "preset": "cargo", "stress": 85, "hills": -40, "assist": True}
        assert post(client, body).json()["by"] == "route_cost"
        pairs = fake.pairs()
        stops = [1, 2, 3]
        wanted = (
            {(0, s) for s in stops}
            | {(s, 4) for s in stops}
            | {(s, t) for s in stops for t in stops if s != t}
        )
        assert sorted(pairs) == sorted(wanted), "each pair an order may ride, once"
        for url, payload in fake.calls:
            assert url == f"{routing.settings.VALHALLA_UPSTREAMS['ebike']}/route"
            assert payload["costing"] == "bicycle"
            assert payload["costing_options"] == presets.costing(
                "cargo", 85, -40, assist=True, avoid_gravel=False
            )
            assert {loc["type"] for loc in payload["locations"]} == {"break"}
            assert payload["date_time"]["type"] == 3
            assert payload["directions_type"] == "none"

    def test_a_loops_legs_end_at_its_start(self, client, router) -> None:
        points = [[-77.05, 38.90], [-77.04, 38.91], [-77.04, 38.90], [-77.05, 38.91]]
        request = [*points, points[0]]
        fake = router(LegRouter(request, straight(request)))
        body = post(client, {"points": points, "preset": "default", "loop": True}).json()
        assert body["by"] == "route_cost" and body["order"] in ([0, 2, 1, 3], [0, 3, 1, 2])
        assert (3, 4) in fake.pairs() and (0, 4) not in fake.pairs()

    def test_past_ten_stops_the_matrix_orders_them(self, client, router) -> None:
        points = [[-77.05 + 0.002 * i, 38.90 + 0.001 * (i % 3)] for i in range(13)]
        fake = router(LegRouter(points, straight(points), matrix=matrix_answer(straight(points))))
        body = post(client, {"points": points, "preset": "default"}).json()
        assert stoporder.COST_MAX_STOPS == 10
        assert body["by"] == "riding_time"
        assert fake.endpoints() == ["sources_to_targets"]

    def test_ten_stops_are_still_by_the_routers_cost(self, client, router) -> None:
        points = [[-77.05 + 0.002 * i, 38.90 + 0.001 * (i % 3)] for i in range(12)]
        fake = router(LegRouter(points, straight(points)))
        assert post(client, {"points": points, "preset": "default"}).json()["by"] == "route_cost"
        assert len(fake.pairs()) == 10 * 11
        assert all(len(p["locations"]) <= stoporder.ROUTE_MAX_LOCATIONS for _, p in fake.calls)

    def test_legs_without_a_cost_leave_the_order_to_the_matrix(self, client, router) -> None:
        class NoCost(LegRouter):
            def __call__(self, url, payload, timeout):
                answer = super().__call__(url, payload, timeout)
                for leg in (answer.get("trip") or {}).get("legs", []):
                    leg["summary"].pop("cost")
                return answer

        times = along_the_line(POINTS)
        router(NoCost(POINTS, times, matrix=matrix_answer(times)))
        assert post(client, {"points": POINTS, "preset": "default"}).json()["by"] == "riding_time"

    def test_legs_past_their_time_leave_the_order_to_the_matrix(
        self, client, router, monkeypatch
    ) -> None:
        times = along_the_line(POINTS)
        fake = router(LegRouter(POINTS, times, matrix=matrix_answer(times)))
        times_asked = []

        def clock() -> float:
            # The request starts at 0; every later look at the clock is past the legs' time.
            times_asked.append(None)
            return 0.0 if len(times_asked) == 1 else stoporder.COST_BUDGET_S + 1.0

        monkeypatch.setattr(routing, "clock", clock)
        body = post(client, {"points": POINTS, "preset": "default"}).json()
        assert body["by"] == "riding_time"
        assert fake.endpoints()[-1] == "sources_to_targets"

    def test_a_weekend_router_down_for_the_legs_leaves_them_to_the_standard_graph(
        self, client, router, monkeypatch
    ) -> None:
        monkeypatch.setattr(routing, "_is_promoted", lambda variant: True)
        down = set()
        monkeypatch.setattr(routing, "_twin_down", lambda variant: variant in down)

        def mark(variant, ok):
            (down.discard if ok else down.add)(variant)

        monkeypatch.setattr(routing, "_mark_twin", mark)

        class WeekendHung(LegRouter):
            def __call__(self, url, payload, timeout):
                if url.startswith(routing.settings.VALHALLA_UPSTREAMS["weekend"]):
                    self.calls.append((url, payload))
                    raise routing.RouterUnavailable("hung")
                return super().__call__(url, payload, timeout)

        fake = router(WeekendHung(POINTS, along_the_line(POINTS)))
        body = post(client, {"points": POINTS, "preset": "default", "when": "weekend"}).json()
        assert body["by"] == "route_cost" and body["order"] == [0, 2, 1, 3, 4]
        weekend = [
            u for u, _ in fake.calls if u.startswith(routing.settings.VALHALLA_UPSTREAMS["weekend"])
        ]
        assert len(weekend) == 1, "asked once, then the standard graph answers the rest"
        standard = routing.settings.VALHALLA_UPSTREAMS["standard"]
        asked = [p for c in fake.calls if c[0].startswith(standard) for p in fake.pairs_of(c)]
        assert len(asked) == 3 * 4, "nothing was filled from the weekend graph to ask again"
        assert down == {"weekend"}

    def _weekend(self, monkeypatch):
        monkeypatch.setattr(routing, "_is_promoted", lambda variant: True)
        down = set()
        monkeypatch.setattr(routing, "_twin_down", lambda variant: variant in down)
        monkeypatch.setattr(
            routing, "_mark_twin", lambda v, ok: (down.discard if ok else down.add)(v)
        )
        return down

    def test_a_weekend_router_silent_past_the_legs_time_leaves_the_matrix_to_standard(
        self, client, router, monkeypatch
    ) -> None:
        down = self._weekend(monkeypatch)
        weekend = routing.settings.VALHALLA_UPSTREAMS["weekend"]

        class WeekendLate(LegRouter):
            def __call__(self, url, payload, timeout):
                if url.startswith(weekend):
                    self.calls.append((url, payload))
                    raise routing.DeadlineExceeded("late")
                if url.endswith("/route"):
                    raise AssertionError("the legs are not asked again on the standard graph")
                return super().__call__(url, payload, timeout)

        times = along_the_line(POINTS)
        fake = router(WeekendLate(POINTS, times, matrix=matrix_answer(times)))
        body = post(client, {"points": POINTS, "preset": "default", "when": "weekend"}).json()
        assert body["by"] == "riding_time"
        urls = [u for u, _ in fake.calls]
        assert sum(u.startswith(weekend) for u in urls) == 1
        assert urls[-1] == f"{routing.settings.VALHALLA_UPSTREAMS['standard']}/sources_to_targets"
        assert down == set(), "not remembered as down: it had less than its own limit"

    def test_a_weekend_router_that_drops_part_way_leaves_every_leg_to_the_standard_graph(
        self, client, router, monkeypatch
    ) -> None:
        down = self._weekend(monkeypatch)
        weekend = routing.settings.VALHALLA_UPSTREAMS["weekend"]
        standard = routing.settings.VALHALLA_UPSTREAMS["standard"]
        cheap = [[1.0] * 5 for _ in range(5)]  # the weekend graph's costs, if kept, would tie

        class WeekendDrops(LegRouter):
            answered = 0

            def __call__(self, url, payload, timeout):
                if url.startswith(weekend):
                    WeekendDrops.answered += 1
                    if WeekendDrops.answered > 1:
                        self.calls.append((url, payload))
                        raise routing.RouterUnavailable("dropped")
                    saved, self.cost = self.cost, cheap
                    try:
                        return super().__call__(url, payload, timeout)
                    finally:
                        self.cost = saved
                return super().__call__(url, payload, timeout)

        fake = router(WeekendDrops(POINTS, along_the_line(POINTS)))
        body = post(client, {"points": POINTS, "preset": "default", "when": "weekend"}).json()
        assert body["by"] == "route_cost" and body["order"] == [0, 2, 1, 3, 4]
        on_standard = [
            pair
            for (url, _), pairs in ((c, fake.pairs_of(c)) for c in fake.calls)
            if url.startswith(standard)
            for pair in pairs
        ]
        wanted = {(0, s) for s in (1, 2, 3)} | {(s, 4) for s in (1, 2, 3)}
        wanted |= {(s, t) for s in (1, 2, 3) for t in (1, 2, 3) if s != t}
        assert set(on_standard) == wanted, "every pair asked again of the standard graph"
        # The weekend graph's ties are not kept: the order is the standard graph's.
        assert down == {"weekend"}

    def test_a_weekend_refusal_that_is_not_missing_tiles_is_not_asked_again(
        self, client, router, monkeypatch
    ) -> None:
        self._weekend(monkeypatch)
        times = along_the_line(POINTS)
        fake = router(LegRouter(POINTS, times, matrix=matrix_answer(times)))
        fake.answers["route"] = NO_PATH
        weekend = routing.settings.VALHALLA_UPSTREAMS["weekend"]
        original = LegRouter.__call__

        def call(self, url, payload, timeout):
            if url.endswith("/route"):
                self.calls.append((url, payload))
                raise NO_PATH
            return original(self, url, payload, timeout)

        monkeypatch.setattr(LegRouter, "__call__", call)
        body = post(client, {"points": POINTS, "preset": "default", "when": "weekend"}).json()
        assert body["by"] == "riding_time"
        routes = [u for u, _ in fake.calls if u.endswith("/route")]
        assert routes == [f"{weekend}/route"]

    def test_legs_of_the_wrong_number_leave_the_order_to_the_matrix(self, client, router) -> None:
        class ShortLegs(LegRouter):
            def __call__(self, url, payload, timeout):
                answer = super().__call__(url, payload, timeout)
                if "trip" in answer:
                    answer["trip"]["legs"].pop()
                return answer

        times = along_the_line(POINTS)
        router(ShortLegs(POINTS, times, matrix=matrix_answer(times)))
        assert post(client, {"points": POINTS, "preset": "default"}).json()["by"] == "riding_time"

    def test_without_leg_costs_the_matrixs_riding_times_order_them(self, client, router) -> None:
        fake = router(MatrixOnly({"sources_to_targets": matrix_answer(along_the_line(POINTS))}))
        response = post(client, {"points": POINTS, "preset": "default"})
        assert response.status_code == 200
        body = response.json()
        assert body["order"] == [0, 2, 1, 3, 4]
        assert body["changed"] is True and body["by"] == "riding_time" and body["exact"] is True
        assert body["before_s"] == 600 and body["after_s"] == 400
        assert body["before_m"] == 600_000 and body["after_m"] == 400_000
        # The legs were asked first, and the first refusal ended them.
        assert fake.endpoints() == ["route", "sources_to_targets"]

    def test_the_matrix_is_asked_with_the_rides_own_graph_and_costing(self, client, router) -> None:
        fake = router(MatrixOnly({"sources_to_targets": matrix_answer(along_the_line(POINTS))}))
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
        url, payload = fake.calls[-1]
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
        router(MatrixOnly({"sources_to_targets": matrix_answer(times, km)}))
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
        fake = router(MatrixOnly({"sources_to_targets": matrix_answer(along_the_line(POINTS))}))
        for body in (
            {"preset": "default", "stress": 90, "hills": 30, "when": "weekday_rush"},
            {"preset": "cargo", "carrying": "people", "assist": True, "avoid_gravel": True},
            {"preset": "gravel", "hills": -60},
            {"preset": "group-ride", "when": "weekend"},
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
            MatrixOnly({"sources_to_targets": [routing.RouterUnavailable("hung"), matrix]})
        )
        body = post(client, {"points": POINTS, "preset": "default", "when": "weekend"}).json()
        assert body["by"] == "riding_time" and body["order"] == [0, 2, 1, 3, 4]
        urls = [url for url, _ in fake.calls if url.endswith("/sources_to_targets")]
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
        router(MatrixOnly({"sources_to_targets": [refusal, matrix]}))
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
        router(MatrixOnly({"sources_to_targets": matrix_answer(along_the_line(ordered))}))
        body = post(client, {"points": ordered, "preset": "default"}).json()
        assert body["order"] == [0, 1, 2, 3, 4] and body["changed"] is False
        assert body["before_s"] == body["after_s"] == 400

    def test_a_loop_the_rider_chose_moves_every_point_after_the_start(self, client, router) -> None:
        # A square ridden corner to opposite corner crosses itself; round its edge
        # is shorter. The last point given is a stop in a loop, so it may move.
        points = [[-77.05, 38.90], [-77.04, 38.91], [-77.04, 38.90], [-77.05, 38.91]]
        fake = router(
            MatrixOnly({"sources_to_targets": matrix_answer(straight([*points, points[0]]))})
        )
        body = post(client, {"points": points, "preset": "default", "loop": True}).json()
        assert body["changed"] is True
        # Round the edge, one way or the other; the finish (the start again) is not returned.
        assert body["order"] in ([0, 2, 1, 3], [0, 3, 1, 2])
        # The matrix carries the start again as the loop's finish.
        assert fake.calls[-1][1]["sources"][-1] == {"lon": -77.05, "lat": 38.90}
        assert len(fake.calls[-1][1]["sources"]) == 5

    def test_the_same_points_without_the_loop_keep_their_end(self, client, router) -> None:
        points = [[-77.05, 38.90], [-77.04, 38.91], [-77.04, 38.90], [-77.05, 38.91]]
        router(MatrixOnly({"sources_to_targets": matrix_answer(straight(points))}))
        body = post(client, {"points": points, "preset": "default"}).json()
        assert body["order"][-1] == 3

    def test_without_the_routers_matrix_it_orders_by_straight_line(self, client, router) -> None:
        router(
            MatrixOnly({"sources_to_targets": routing.RouterRefused(400, 106, "Try any of: route")})
        )
        body = post(client, {"points": POINTS, "preset": "default"}).json()
        assert body["order"] == [0, 2, 1, 3, 4] and body["by"] == "straight_line"
        assert body["before_s"] is None and body["after_s"] is None
        assert body["after_m"] < body["before_m"]

    def test_a_router_that_does_not_answer_falls_back_too(self, client, router) -> None:
        router(MatrixOnly({"sources_to_targets": routing.RouterUnavailable("down")}))
        body = post(client, {"points": POINTS, "preset": "default"}).json()
        assert body["by"] == "straight_line" and body["order"] == [0, 2, 1, 3, 4]

    def test_a_matrix_of_the_wrong_shape_falls_back(self, client, router) -> None:
        router(MatrixOnly({"sources_to_targets": {"sources_to_targets": [[]]}}))
        body = post(client, {"points": POINTS, "preset": "default"}).json()
        assert body["by"] == "straight_line"

    def test_a_pair_the_router_cannot_join_is_not_ridden(self, client, router) -> None:
        times = along_the_line(POINTS)
        times[0][2] = None  # start to the middle stop cannot be ridden that way
        router(MatrixOnly({"sources_to_targets": matrix_answer(times, along_the_line(POINTS))}))
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
        router(MatrixOnly({"sources_to_targets": matrix_answer(along_the_line(points))}))
        body = post(client, {"points": points, "preset": "default"}).json()
        assert body["order"][0] == 0 and body["order"][-1] == 4

    def test_a_mass_ride_keeps_its_order(self, client, router) -> None:
        fake = router(FakeRouter({}))
        response = post(client, {"points": POINTS, "preset": "mass-ride"})
        assert response.status_code == 400
        assert "Mass Ride keeps its stops in the order given" in response.json()["error"]
        assert fake.calls == []

    def test_the_body_is_checked_as_a_route_requests_is(self, client, router) -> None:
        router(FakeRouter({}))
        response = post(client, {"points": [[0, 0], [1, 1]], "preset": "default"})
        assert response.status_code == 400
        assert "outside the area" in response.json()["error"]

    def test_a_router_past_the_budget_leaves_the_straight_line_order(self, client, router):
        router(MatrixOnly({"sources_to_targets": routing.DeadlineExceeded("late")}))
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


@pytest.mark.parametrize("n", range(4, 27))
def test_the_chains_ride_every_pair_an_order_may_use_once(n) -> None:
    pairs = []
    for chain in stoporder._pairs_chains(n):
        points = [[-77.05 + 0.001 * i, 38.90] for i in range(n)]
        requests = stoporder._requests_of(chain, points)
        assert all(2 <= len(r) <= stoporder.ROUTE_MAX_LOCATIONS for r in requests)
        assert [i for r in requests for i in r[:-1]] + [requests[-1][-1]] == chain
        for r in requests:
            pairs.extend(zip(r, r[1:], strict=False))
    stops = range(1, n - 1)
    wanted = (
        [(0, s) for s in stops]
        + [(s, n - 1) for s in stops]
        + [(s, t) for s in stops for t in stops if s != t]
    )
    assert sorted(pairs) == sorted(wanted)


def test_a_request_holds_no_more_locations_than_the_routers_allow() -> None:
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "build_valhalla_configs.py"
    text = path.read_text()
    assert f'"max_locations": {stoporder.ROUTE_MAX_LOCATIONS},' in text


def test_a_request_is_split_before_the_routers_distance_limit() -> None:
    # Points far apart: about 56 mi (90 km) between each and the next.
    points = [[-77.40 + 0.5 * (i % 2), 38.75 + 0.5 * (i % 2)] for i in range(12)]
    chain = list(range(12))
    requests = stoporder._requests_of(chain, points)
    assert len(requests) > 1
    for r in requests:
        span = sum(
            stoporder.haversine(stoporder.Point(*points[a]), stoporder.Point(*points[b]))
            for a, b in zip(r, r[1:], strict=False)
        )
        assert span <= stoporder.ROUTE_MAX_SPAN_M
    assert [i for r in requests for i in r[:-1]] + [requests[-1][-1]] == chain
    assert stoporder.ROUTE_MAX_SPAN_M < 500_000, "under the routers' max_distance"


def test_the_page_knows_where_the_routers_cost_stops() -> None:
    from pathlib import Path

    page = Path(__file__).resolve().parents[1] / "frontend" / "src" / "lib" / "stopOrder.ts"
    assert f"export const COST_MAX_STOPS = {stoporder.COST_MAX_STOPS};" in page.read_text()


def test_the_routers_serve_the_matrix() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "valhalla"
    for config in sorted(root.glob("valhalla-*.json")):
        actions = json.loads(config.read_text())["loki"]["actions"]
        assert "sources_to_targets" in actions, config.name
