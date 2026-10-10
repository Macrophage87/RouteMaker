"""FOLLOWUP-DEDODGE (OWNER-DECISIONS 272, 273) in the plan: `routing.plan` takes the dodges
out of the route it is about to answer, and says so.

The router is a fake at the one function that touches the network, over the synthetic
graph of tests/test_dedodge.py; the segment table is real (the stress join is a PostGIS
query), with one row for each edge of the graph.
"""

from __future__ import annotations

import pytest
from test_dedodge import Graph, Unit, at, key, leg_of, metres_of

from core import dedodge, presets, routing

db = pytest.mark.django_db(transaction=True)

pytestmark = [pytest.mark.usefixtures("weekday_clock"), db]


class Router:
    """A fake of the router's transport: `route` answers each pair of locations from
    `routes`, `trace_attributes` reads the graph, `locate` knows nothing."""

    def __init__(self, graph: Graph, routes: dict) -> None:
        self.graph = graph
        self.routes = routes
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, payload: dict, timeout: float) -> dict:
        endpoint = url.rsplit("/", 1)[1]
        self.calls.append((endpoint, payload))
        if endpoint == "route":
            legs = []
            places = payload["locations"]
            for here, there in zip(places, places[1:], strict=False):
                points = self.routes.get(
                    (key((here["lon"], here["lat"])), key((there["lon"], there["lat"])))
                )
                if points is None:
                    raise routing.RouterRefused(400, 442, "no path")
                legs.append(leg_of(points, elevation=[1.0, 2.0, 3.0]))
            summary = {
                k: sum(leg["summary"][k] for leg in legs) for k in ("length", "time", "cost")
            }
            return {"trip": {"legs": legs, "summary": summary, "units": "kilometers"}}
        if endpoint == "trace_attributes":
            try:
                return self.graph.trace(payload["encoded_polyline"])
            except KeyError as error:
                raise routing.RouterRefused(400, 444, "no match") from error
        if endpoint == "locate":
            return []
        raise AssertionError(endpoint)

    def asked(self, endpoint: str) -> list[dict]:
        return [p for e, p in self.calls if e == endpoint]


@pytest.fixture
def world(monkeypatch, segment_schemas):
    """`make(unit_kwargs, loop=False) -> (unit, router)`: the unit's graph in the segment
    table and the transport."""
    from django.db import connection

    live, _staging = segment_schemas

    def make(loop: bool = False, **kw):
        graph = Graph()
        unit = Unit(graph, at(0, 0), **kw)
        if loop:
            graph.add(unit.e, unit.a, ["Main St"], 90, "2")
        routes = {
            (key(unit.a), key(unit.e)): unit.dodge_route,
            (key(unit.b), key(unit.d)): unit.between,
        }
        if loop:
            routes[(key(unit.e), key(unit.a))] = [unit.e, unit.a]
        with connection.cursor() as cursor:
            for (a, b), edge in graph.edges.items():
                wkt = f"LINESTRING({a[0] / 1e6} {a[1] / 1e6}, {b[0] / 1e6} {b[1] / 1e6})"
                cursor.execute(
                    f"INSERT INTO {live}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                    "stress_rule) VALUES (%s, 0, ST_GeomFromText(%s, 4326), %s, 'test')",
                    [edge["way"], wkt, int(graph.tiers[edge["way"]])],
                )
        router = Router(graph, routes)
        monkeypatch.setattr(routing, "_transport", router)
        return unit, router

    return make


def plan(unit, preset="default", **dials):
    points = [list(unit.a), list(unit.e)]
    return routing.plan(
        points, preset, long_ride=True, dials=routing.Dials(when="weekday_offpeak", **dials)
    )


class TestThePlan:
    def test_a_dodge_that_buys_nothing_is_taken_out_of_the_answer(self, world) -> None:
        unit, router = world(side="3", main="3")
        body = plan(unit)
        direct = metres_of(unit.direct)
        assert body["distance_m"] == pytest.approx(direct, rel=3e-3)
        assert body["geometry"]["coordinates"] == [
            [round(x, 6), round(y, 6)] for x, y in unit.direct
        ]
        # Both are LTS 3: the same stress over half the distance.
        assert body["stress_m"]["3"] == pytest.approx(unit.reach, abs=2.0)
        dodges = body["dodges"]
        assert (dodges["found"], dodges["removed"], dodges["kept"]) == (1, 1, 0)
        assert dodges["items"][0]["action"] == "removed"
        assert dodges["items"][0]["street"] == "main st"
        # The route asked for once, and once more for the stretch between the dodge's ends.
        routes = router.asked("route")
        assert [len(r["locations"]) for r in routes][-1] == 2
        assert routes[-1]["exclude_locations"]

    def test_a_dodge_that_avoids_enough_stays(self, world) -> None:
        unit, router = world(reach=700.0, side="1", main="3")
        body = plan(unit)
        assert body["distance_m"] == pytest.approx(metres_of(unit.dodge_route), rel=3e-3)
        assert body["geometry"]["coordinates"] == [
            [round(x, 6), round(y, 6)] for x, y in unit.dodge_route
        ]
        assert body["stress_m"]["3"] == 0.0
        assert (body["dodges"]["removed"], body["dodges"]["kept"]) == (0, 1)
        assert body["dodges"]["items"][0]["reason"] == "stress"

    def test_a_route_without_a_dodge_says_nothing_found(self, world) -> None:
        unit, router = world()
        unit.dodge_route = unit.direct
        router.routes[(key(unit.a), key(unit.e))] = unit.direct
        body = plan(unit)
        assert body["dodges"] == {
            "found": 0,
            "removed": 0,
            "kept": 0,
            "skipped": 0,
            "checked": 0,
            "saved_m": 0.0,
            "limited": None,
            "items": [],
        }

    def test_a_loop_keeps_its_way_back_as_it_was_made(self, world) -> None:
        """OWNER-DECISIONS 266: a way back chosen not to share the way out is not
        straightened onto it."""
        unit, router = world(loop=True, side="3", main="3")
        body = routing.plan(
            [list(unit.a), list(unit.e)],
            "default",
            long_ride=True,
            dials=routing.Dials(when="weekday_offpeak", loop=True),
        )
        assert body["loop"] is not None
        assert body["dodges"] is None
        coordinates = body["geometry"]["coordinates"]
        for x, y in unit.side[1:-1]:
            assert [round(x, 6), round(y, 6)] in coordinates, (
                "the way out still takes the side street"
            )

    @pytest.mark.parametrize(
        "preset", ["default", "trailmaxxing", "cargo", "fast", "group-ride", "mass-ride", "ebike"]
    )
    def test_it_runs_on_every_ride_type(self, world, preset) -> None:
        unit, router = world(side="3", main="3")
        body = plan(unit, preset)
        assert body["dodges"]["removed"] == 1, preset

    def test_a_group_ride_asks_the_router_for_its_own_graph(self, world) -> None:
        unit, router = world(side="3", main="3")
        urls = []
        real = router.__call__

        def spy(url, payload, timeout):
            urls.append(url)
            return real(url, payload, timeout)

        routing._transport = spy  # restored by the world fixture's monkeypatch
        plan(unit, "mass-ride")
        assert urls and all("no-trail" in u or "no_trail" in u for u in urls), urls

    def test_the_target_is_read_after_the_dodge_is_gone(self, world) -> None:
        """At the top of the slider the answer says how far past the target it is: the
        route as it is answered, 600 m shorter than the router's own."""
        unit, router = world(side="3", main="3")
        direct = metres_of(unit.direct)
        dodge = metres_of(unit.dodge_route)
        target = int((direct + dodge) / 2)
        body = routing.plan(
            [list(unit.a), list(unit.e)],
            "trailmaxxing",
            dials=routing.Dials(stress=100, when="weekday_offpeak", target_distance_m=target),
        )
        assert body["distance_m"] == pytest.approx(direct, rel=3e-3)
        search = body["calm_search"]
        assert search["over_target_m"] == 0.0 and search["fits"] is True
        #         assert body["dodges"]["saved_m"] == pytest.approx(dodge - direct, abs=3.0)
        # No route fitted the target until the dodge was gone: the flag goes with it.
        assert search["limited"] is None and search["no_fit"] is False

    def test_the_no_fit_flag_stays_where_the_route_is_still_over_the_target(self, world) -> None:
        """Mutation review X16: the flag is cleared only where the route now fits. A
        dodge taken out of a route still past the target leaves `limited` and `no_fit`."""
        unit, router = world(side="3", main="3")
        direct = metres_of(unit.direct)
        target = int(direct - 100)
        body = routing.plan(
            [list(unit.a), list(unit.e)],
            "trailmaxxing",
            dials=routing.Dials(stress=100, when="weekday_offpeak", target_distance_m=target),
        )
        assert body["dodges"]["removed"] == 1
        search = body["calm_search"]
        assert search["fits"] is False and search["over_target_m"] > 0
        assert search["limited"] == "target_distance" and search["no_fit"] is True

    def test_the_searchs_extra_distance_is_brought_down_by_what_was_taken_off(self, world) -> None:
        unit, router = world(side="3", main="3")
        direct = metres_of(unit.direct)
        dodge = metres_of(unit.dodge_route)
        body = routing.plan(
            [list(unit.a), list(unit.e)],
            "trailmaxxing",
            dials=routing.Dials(stress=100, when="weekday_offpeak"),
        )
        assert body["calm_search"]["extra_distance_m"] == pytest.approx(direct - dodge, abs=3.0)

    def test_the_searchs_figures_are_the_route_as_answered(self, world) -> None:
        """Review r0 nit: `exposure_after_m` (and the LTS figures after) follow the
        dodge's removal: the main road's 600 m of LTS 3, not the side streets' 1,200 m."""
        unit, router = world(side="3", main="3")
        body = routing.plan(
            [list(unit.a), list(unit.e)],
            "trailmaxxing",
            dials=routing.Dials(stress=100, when="weekday_offpeak"),
        )
        search = body["calm_search"]
        assert body["dodges"]["removed"] == 1
        assert body["stress_m"]["3"] == pytest.approx(unit.reach, abs=2.0)
        assert search["lts3_m_after"] == pytest.approx(unit.reach, abs=2.0)
        # Trailmaxxing weighs LTS 3 at 1, and LTS 2 at a quarter (FOLLOWUP-LTS2-WEIGHT).
        lts2 = presets.EXPOSURE_NOT_IN_CONTROL.lts2 * body["stress_m"].get("2", 0.0)
        assert search["exposure_after_m"] == pytest.approx(unit.reach + lts2, abs=2.0)

    def test_a_dodge_that_avoids_more_than_the_tie_step_stays_on_every_ride(self, world) -> None:
        """OWNER-DECISIONS 298(1): 300 m of LTS 3 avoided is kept at the top of the slider
        and on Default alike (272's quarter mile took it out below the top)."""
        unit, router = world(reach=300.0, side="1", main="3")
        top = routing.plan(
            [list(unit.a), list(unit.e)],
            "trailmaxxing",
            dials=routing.Dials(stress=100, when="weekday_offpeak"),
        )
        assert top["dodges"]["kept"] == 1 and top["dodges"]["items"][0]["reason"] == "stress"
        assert top["stress_m"]["3"] == 0.0
        below = plan(unit)
        assert below["dodges"]["kept"] == 1 and below["dodges"]["removed"] == 0
        assert below["dodges"]["items"][0]["needed_m"] == 50.0

    def test_it_is_the_planners_own_module_wired_in(self) -> None:
        """`plan` calls `core.dedodge.apply` once, on the answer's route, never on a loop,
        and never on a candidate (review r0 item 3: one bounded pass a plan); then
        `dedodge.settle`, which picks the candidates again against the answer as it now
        is (review r0 item 5)."""
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(routing.plan))
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "apply"
            and getattr(node.func.value, "id", "") == "dedodge"
        ]
        assert len(calls) == 1
        settles = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "settle"
            and getattr(node.func.value, "id", "") == "dedodge"
        ]
        assert len(settles) == 1
        # The candidates' loop reads each as the search found it.
        loops = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.For) and "candidates" in ast.dump(node.iter)
        ]
        assert loops and not any(
            isinstance(n, ast.Attribute) and getattr(n.value, "id", "") == "dedodge"
            for loop in loops
            for n in ast.walk(loop)
        )
        guarded = []
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and "loop" in ast.dump(node.test):
                guarded += [
                    c for c in calls if any(c is d for d in ast.walk(ast.Module(node.body, [])))
                ]
        assert len(guarded) == 1, "it is under `if not loop`"
        assert dedodge.apply  # the name the plan calls
