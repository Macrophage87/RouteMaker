"""The search over the router's own routes (`core.refine`): the calm detour at
the top of the stress slider (OWNER-DECISIONS 163, 164) and the avoidance of the
worst crossings (165-169), with the router and the route's reading replaced.

Valhalla's `exclude_locations` is what steers it; the tests hold what is asked of
it, what is kept, and why the search stops.
"""

from __future__ import annotations

import pytest

from core import presets, refine, routing
from routemaker import intersections as model
from routemaker.intersections import Control, Event, Movement

QUIET_COST = 0.5
BASE = (-77.0, 38.9)


def piece(along: float, tier: str) -> tuple:
    """A traced piece 100 m long at `along` metres: (piece, (tier, facility))."""
    point = (BASE[0] + along * 1e-5, BASE[1])
    return routing.Piece(1, point[0], point[1], 100.0), (tier, "none")


def analysis(
    name: str,
    tiers: str = "1" * 40,
    cost_s: float = 4000.0,
    events: list | None = None,
    climb_m: float = 0.0,
) -> refine.Analysis:
    pieces, classes = zip(*[piece(i * 100.0, tier) for i, tier in enumerate(tiers)], strict=True)
    stress = {"3": 1, "4": 2, "5": 3}
    return refine.Analysis(
        length_m=100.0 * len(tiers),
        cost_s=cost_s,
        exposure_m=sum(100.0 * stress.get(tier, 0) for tier in tiers),
        climb_m=climb_m,
        pieces=list(pieces),
        classes=list(classes),
        events=events,
        via_m=[],
    )


def event(m: float, cost_ft: float = 3000.0, approach=None) -> Event:
    return Event(
        m=m,
        lon=BASE[0],
        lat=BASE[1],
        kind="crossing",
        movement=Movement.STRAIGHT,
        control=Control.NONE,
        cost_ft=cost_ft,
        severity=model.severity_of(cost_ft),
        reason="Crossing a road (LTS 4), no signal",
        crossed_tier=4,
        flagged=True,
        approach=approach if approach is not None else (BASE[0] + m * 1e-5, BASE[1] + 1e-5),
    )


def trip_of(name: str, km: float, cost: float = 0.0) -> dict:
    return {"legs": [{"shape": name}], "summary": {"length": km, "time": 100.0 * km, "cost": cost}}


def context(rate=0.0, weight=1.0, climb_weight=0.0, group=False) -> refine.Context:
    return refine.Context(
        variant="standard",
        request={
            "locations": [{"lon": BASE[0], "lat": BASE[1]}],
            "costing": "bicycle",
            "alternates": 3,
            "elevation_interval": 30,
        },
        costing={"bicycle": {}},
        when="weekend",
        deadline=routing.Deadline(routing.clock() + 40, 35),
        traces={},
        points=[[BASE[0], BASE[1]], [BASE[0] + 0.04, BASE[1]]],
        roadway_only=False,
        with_facility=False,
        group=group,
        rate=rate,
        weight=weight,
        climb_weight=climb_weight,
        quiet_cost=QUIET_COST,
    )


class World:
    """The router and the reading of its routes, in one place: `routes` is what
    each request gets (a trip, or an exception), in order; `analyses` is what
    each trip's shape reads as."""

    def __init__(self, monkeypatch, analyses: dict, routes: list) -> None:
        self.analyses = analyses
        self.routes = list(routes)
        self.requests: list[dict] = []
        monkeypatch.setattr(
            refine, "analyse", lambda trip, ctx, deadline: self.analyses[trip["legs"][0]["shape"]]
        )
        monkeypatch.setattr(routing, "_call", self.call)

    def call(self, variant, endpoint, payload, deadline):
        assert endpoint == "route"
        self.requests.append(payload)
        answer = self.routes.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return {"trip": answer}

    def excluded(self, number: int) -> list[tuple[float, float]]:
        return [(p["lon"], p["lat"]) for p in self.requests[number]["exclude_locations"]]


class TestScore:
    def test_the_routers_cost_plus_the_extra_price_in_its_own_units(self) -> None:
        a = analysis("a", "1133", cost_s=1000.0, events=[event(0, 1000.0)], climb_m=10.0)
        ctx = context(rate=2.0, weight=0.5, climb_weight=3.0)
        penalty_m = 1000.0 / model.FEET_PER_METRE
        extra = 2.0 * a.exposure_m + 0.5 * penalty_m + 3.0 * 10.0
        assert a.score(ctx) == pytest.approx(1000.0 + QUIET_COST * extra)

    def test_a_route_with_no_events_costs_no_penalty(self) -> None:
        assert analysis("a", events=None).score(context(weight=1.0)) == 4000.0
        assert analysis("a", events=[]).score(context(weight=1.0)) == 4000.0

    def test_the_quiet_cost_is_2_2_times_the_time_per_metre_at_the_requests_speed(self) -> None:
        hybrid = refine.quiet_cost_per_m({"bicycle": {"bicycle_type": "Hybrid"}})
        assert hybrid == pytest.approx(2.2 * 3.6 / 18.0)
        cargo = refine.quiet_cost_per_m({"bicycle": {"cycling_speed": 14.0}})
        assert cargo > hybrid
        assert refine.quiet_cost_per_m({"bicycle": {"bicycle_type": "Road"}}) < hybrid

    def test_intersection_costs_stay_active_at_every_position(self) -> None:
        """The literature review: "keep turn and intersection costs active at every
        slider position"."""
        weights = [refine.intersection_weight(s) for s in range(0, 101, 5)]
        assert weights == sorted(weights)
        assert weights[0] == refine.INTERSECTION_WEIGHT_AT_ZERO > 0
        assert refine.intersection_weight(presets.STRESS_DEFAULT_AT) == 1.0
        assert refine.intersection_weight(100) == 1.0


class TestCrossingAvoidance:
    def test_the_worst_crossings_approaches_are_excluded_and_a_better_route_kept(
        self, monkeypatch
    ) -> None:
        original = analysis(
            "o", events=[event(1500.0, 3000.0), event(2500.0, 2100.0), event(3000.0, 1300.0)]
        )
        better = analysis("b", cost_s=4050.0, events=[])
        world = World(monkeypatch, {"o": original, "b": better}, [trip_of("b", 4.2)])
        kept, info = refine.refine(trip_of("o", 4.0), context())
        assert kept["legs"][0]["shape"] == "b"
        assert info["rounds"] == 1 and info["limited"] is None
        # The two red events (2,000 ft and up); an orange one is not worth a second route.
        assert len(world.requests[0]["exclude_locations"]) == 2
        assert world.excluded(0)[0] == pytest.approx((BASE[0] + 1500.0 * 1e-5, BASE[1] + 1e-5))
        assert "alternates" not in world.requests[0], "one route, not alternatives"
        assert world.requests[0]["elevation_interval"] == 30
        assert info["extra_distance_m"] == 0.0 or info["extra_distance_m"] == pytest.approx(0.0)

    def test_a_longer_route_that_saves_less_than_it_costs_is_not_taken(self, monkeypatch) -> None:
        original = analysis("o", events=[event(1500.0, 2200.0)])
        # +20 minutes of cost to save 2,200 ft of crossing.
        longer = analysis("l", cost_s=5200.0, events=[])
        World(monkeypatch, {"o": original, "l": longer}, [trip_of("l", 9.0)] * 2)
        kept, _info = refine.refine(trip_of("o", 4.0), context())
        assert kept["legs"][0]["shape"] == "o"

    def test_the_intersection_weight_scales_what_a_crossing_is_worth(self, monkeypatch) -> None:
        original = analysis("o", events=[event(1500.0, 3000.0)])
        mid = analysis("m", cost_s=4300.0, events=[])
        for weight, taken in ((1.0, "m"), (0.05, "o")):
            World(monkeypatch, {"o": original, "m": mid}, [trip_of("m", 4.5)] * 2)
            kept, _ = refine.refine(trip_of("o", 4.0), context(weight=weight))
            assert kept["legs"][0]["shape"] == taken, weight

    def test_nothing_to_avoid_asks_the_router_nothing(self, monkeypatch) -> None:
        world = World(monkeypatch, {"o": analysis("o", events=[event(1500.0, 1900.0)])}, [])
        kept, info = refine.refine(trip_of("o", 4.0), context())
        assert kept == trip_of("o", 4.0) and world.requests == []
        assert info["rounds"] == 0 and info["limited"] is None

    def test_crossing_avoidance_alone_is_one_round(self, monkeypatch) -> None:
        original = analysis("o", events=[event(1500.0, 3000.0)])
        again = analysis("a", cost_s=4100.0, events=[event(1700.0, 3000.0)])
        world = World(monkeypatch, {"o": original, "a": again}, [trip_of("a", 4.1)] * 3)
        refine.refine(trip_of("o", 4.0), context())
        assert len(world.requests) == refine.CROSSING_ONLY_ROUNDS == 1

    def test_only_red_junctions_are_worth_a_second_route(self) -> None:
        assert refine.REFINE_MIN_EVENT_FT == model.RED_MIN_FT

    def test_a_mass_ride_has_none(self, monkeypatch) -> None:
        """Items 133 to 136 and 171: a group's crossings are priced for the group."""
        world = World(monkeypatch, {"o": analysis("o", events=[event(1500.0, 3000.0)])}, [])
        refine.refine(trip_of("o", 4.0), context(group=True))
        assert world.requests == []

    def test_a_crossing_near_either_end_is_left_alone(self, monkeypatch) -> None:
        near = analysis("o", events=[event(100.0, 3000.0), event(3900.0, 3000.0)])
        world = World(monkeypatch, {"o": near}, [])
        refine.refine(trip_of("o", 4.0), context())
        assert world.requests == []
        assert refine.ENDPOINT_CLEARANCE_M >= 500


class TestCalmDetour:
    def stretch(self) -> str:
        # 40 pieces: LTS 4 for four, LTS 3 for eight, quiet between.
        return "1" * 5 + "4" * 4 + "1" * 5 + "3" * 8 + "1" * 18

    def test_nothing_is_excluded_below_the_old_top_of_the_slider(self, monkeypatch) -> None:
        world = World(monkeypatch, {"o": analysis("o", self.stretch())}, [])
        refine.refine(trip_of("o", 4.0), context(rate=presets.calm_rate_for(80)))
        assert world.requests == []

    def test_the_worst_stretches_go_first_then_everything_busy(self, monkeypatch) -> None:
        r1 = analysis("r1", "1" * 5 + "1" * 4 + "1" * 5 + "3" * 8 + "1" * 18, cost_s=4300.0)
        r2 = analysis("r2", "1" * 40, cost_s=5200.0)
        world = World(
            monkeypatch,
            {"o": analysis("o", self.stretch()), "r1": r1, "r2": r2},
            [trip_of("r1", 4.5), trip_of("r2", 5.5)],
        )
        refine.refine(trip_of("o", 4.0), context(rate=10.0))
        first = world.excluded(0)
        assert len(first) == 4 and all(499.9 <= (x - BASE[0]) / 1e-5 <= 1000 for x, _ in first)
        # Round two keeps round one's and adds the LTS 3 stretch of the candidate.
        second = world.excluded(1)
        assert set(first) <= set(second)
        assert len(second) == 4 + 8

    def test_the_rate_picks_among_the_nested_candidates(self, monkeypatch) -> None:
        """Each round's route is calmer and longer: a higher rate takes a later
        one, a lower rate an earlier."""
        orig = analysis("o", self.stretch(), cost_s=4000.0)
        r1 = analysis("r1", "1" * 14 + "3" * 8 + "1" * 18, cost_s=4200.0)
        r2 = analysis("r2", "1" * 40, cost_s=4900.0)
        chosen = {}
        for rate in (0.2, 2.0, 10.0):
            World(
                monkeypatch,
                {"o": orig, "r1": r1, "r2": r2},
                [trip_of("r1", 4.4), trip_of("r2", 5.0), trip_of("r2", 5.0)],
            )
            kept, _ = refine.refine(trip_of("o", 4.0), context(rate=rate))
            chosen[rate] = kept["legs"][0]["shape"]
        assert chosen[0.2] == "o"
        assert chosen[10.0] == "r2"
        order = ["o", "r1", "r2"]
        assert [order.index(chosen[r]) for r in (0.2, 2.0, 10.0)] == sorted(
            order.index(chosen[r]) for r in (0.2, 2.0, 10.0)
        )

    def test_there_is_no_cap_on_the_detour(self, monkeypatch) -> None:
        """ "the upper end could be much greater than straight line distance" (item
        164): a calm route eight times as long is taken if it is calm enough."""
        orig = analysis("o", "1" * 5 + "4" * 30 + "1" * 5, cost_s=4000.0)
        calm = analysis("c", "1" * 320, cost_s=20000.0)
        World(monkeypatch, {"o": orig, "c": calm}, [trip_of("c", 32.0)] * 3)
        kept, info = refine.refine(trip_of("o", 4.0), context(rate=10.0))
        assert kept["legs"][0]["shape"] == "c"
        assert info["extra_distance_m"] == pytest.approx(28_000.0)

    def test_the_search_says_what_it_did(self, monkeypatch) -> None:
        orig = analysis("o", self.stretch())
        calm = analysis("c", "1" * 40, cost_s=4300.0)
        World(monkeypatch, {"o": orig, "c": calm}, [trip_of("c", 4.0)] * 5)
        _, info = refine.refine(trip_of("o", 4.0), context(rate=10.0))
        assert info["rate"] == 10.0
        assert info["exposure_before_m"] > info["exposure_after_m"] == 0
        assert info["original_m"] == 4000.0 and info["excluded"] > 0

    def test_a_calm_route_with_a_climb_is_not_free(self, monkeypatch) -> None:
        orig = analysis("o", self.stretch(), cost_s=4000.0)
        flat = analysis("f", "1" * 40, cost_s=4200.0, climb_m=0.0)
        hilly = analysis("h", "1" * 40, cost_s=4200.0, climb_m=600.0)
        for climb_weight, shape in ((0.0, "h"), (12.0, "o")):
            World(monkeypatch, {"o": orig, "h": hilly}, [trip_of("h", 4.0)] * 5)
            kept, _ = refine.refine(trip_of("o", 4.0), context(rate=1.0, climb_weight=climb_weight))
            assert kept["legs"][0]["shape"] == shape, climb_weight
        assert flat.climb_m == 0


class TestNoRoute:
    refused = routing.RouterRefused(400, 442, "no path")

    def test_a_round_the_router_has_no_route_for_ends_the_search_and_keeps_the_route(
        self, monkeypatch
    ) -> None:
        """Every way out excluded: nothing calmer exists to be found, and the
        route the router gave is still the answer."""
        orig = analysis("o", TestCalmDetour().stretch())
        world = World(monkeypatch, {"o": orig}, [self.refused])
        kept, info = refine.refine(trip_of("o", 4.0), context(rate=10.0))
        assert info["limited"] == "no_route" and kept["legs"][0]["shape"] == "o"
        assert len(world.requests) == 1, "only LTS 4 was asked: there is nothing less to ask"

    def test_an_ask_for_everything_is_asked_again_with_only_the_lts4_stretches(
        self, monkeypatch
    ) -> None:
        """Round two excludes the LTS 3 of the candidate too; where that leaves
        no route the worst alone is asked (here round one's route has LTS 4 left)."""
        both = "1" * 5 + "4" * 4 + "1" * 5 + "3" * 8 + "1" * 18
        orig = analysis("o", "1" * 40)
        step = analysis("s", both, cost_s=4300.0)
        # Make round one's choice LTS 3 only so that round two has both to ask.
        orig = analysis("o", "1" * 5 + "3" * 8 + "1" * 27)
        world = World(monkeypatch, {"o": orig, "s": step}, [self.refused, trip_of("s", 4.3)])
        kept, info = refine.refine(trip_of("o", 4.0), context(rate=10.0))
        # Round one asked for the LTS 3 stretch (the route has no LTS 4), was refused
        # and had nothing less to ask.
        assert info["limited"] == "no_route" and len(world.requests) == 1
        assert kept["legs"][0]["shape"] == "o"

    def test_the_reduced_ask_succeeds_where_the_full_one_is_refused(self, monkeypatch) -> None:
        mixed = analysis("o", "1" * 5 + "4" * 4 + "1" * 5 + "3" * 8 + "1" * 18)
        # Round one is only LTS 4; round two (on its route, which has LTS 4 left and LTS 3) is
        # refused for everything and then given the LTS 4 alone.
        first = analysis("a", "1" * 7 + "3" * 8 + "1" * 3 + "4" * 2 + "1" * 20, cost_s=4300.0)
        second = analysis("b", "1" * 40, cost_s=4600.0)
        world = World(
            monkeypatch,
            {"o": mixed, "a": first, "b": second},
            [trip_of("a", 4.3), self.refused, trip_of("b", 4.6)],
        )
        kept, info = refine.refine(trip_of("o", 4.0), context(rate=10.0))
        assert len(world.requests) >= 3
        assert world.requests[2]["exclude_locations"] != world.requests[1]["exclude_locations"]
        assert len(world.requests[2]["exclude_locations"]) < len(
            world.requests[1]["exclude_locations"]
        )
        assert info["rounds"] >= 2 and kept["legs"][0]["shape"] in {"a", "b"}


class TestStopping:
    def test_two_rounds_without_improvement_end_the_search(self, monkeypatch) -> None:
        orig = analysis("o", TestCalmDetour().stretch(), cost_s=4000.0)
        worse = analysis("w", "1" * 5 + "4" * 4 + "1" * 5 + "3" * 8 + "1" * 18, cost_s=9000.0)
        world = World(monkeypatch, {"o": orig, "w": worse}, [trip_of("w", 6.0)] * 6)
        kept, info = refine.refine(trip_of("o", 4.0), context(rate=0.001))
        assert kept["legs"][0]["shape"] == "o"
        assert info["rounds"] == refine.REFINE_PATIENCE == 2
        assert len(world.requests) == 2

    def test_a_round_is_not_started_without_the_time_for_it(self, monkeypatch) -> None:
        orig = analysis("o", TestCalmDetour().stretch())
        world = World(monkeypatch, {"o": orig}, [])
        ctx = context(rate=10.0)
        ctx.deadline = routing.Deadline(routing.clock() + refine.REFINE_TRACE_RESERVE_S + 1, 35)
        kept, info = refine.refine(trip_of("o", 4.0), ctx)
        assert (
            info["limited"] == "time" and world.requests == [] and kept["legs"][0]["shape"] == "o"
        )

    def test_a_router_that_stops_answering_keeps_the_best_route_so_far(self, monkeypatch) -> None:
        orig = analysis("o", TestCalmDetour().stretch())
        calm = analysis("c", "1" * 14 + "3" * 8 + "1" * 18, cost_s=4300.0)
        world = World(
            monkeypatch,
            {"o": orig, "c": calm},
            [trip_of("c", 4.4), routing.RouterUnavailable("gone")],
        )
        kept, info = refine.refine(trip_of("o", 4.0), context(rate=10.0))
        assert kept["legs"][0]["shape"] == "c" and info["limited"] == "time"
        assert len(world.requests) == 2

    def test_a_route_that_cannot_be_read_is_kept_as_it_is(self, monkeypatch) -> None:
        monkeypatch.setattr(refine, "analyse", lambda trip, ctx, deadline: None)
        kept, info = refine.refine(trip_of("o", 4.0), context(rate=10.0))
        assert kept == trip_of("o", 4.0) and info["limited"] == "untraceable"

    def test_a_budget_gone_before_the_first_reading_keeps_the_route(self, monkeypatch) -> None:
        def out_of_time(trip, ctx, deadline):
            raise routing.DeadlineExceeded("no time")

        monkeypatch.setattr(refine, "analyse", out_of_time)
        kept, info = refine.refine(trip_of("o", 4.0), context(rate=10.0))
        assert kept == trip_of("o", 4.0) and info["limited"] == "time"

    def test_the_most_exclusions_are_under_the_routers_limit(self) -> None:
        assert refine.MAX_EXCLUDES <= 200
        assert refine.CALM_POINTS_PER_ROUND <= refine.MAX_EXCLUDES


class TestTargets:
    def test_one_point_per_edge_along_a_busy_stretch(self) -> None:
        a = analysis("a", "1" * 10 + "3" * 20 + "1" * 10)
        ctx = context(rate=10.0)
        targets = refine.calm_targets(a, ctx)
        assert targets and all(t.tier == 3 for t in targets)
        # 100 m pieces sampled at least CALM_SAMPLE_M apart: every piece here.
        assert len(targets) == 20

    def test_a_long_stretch_is_thinned_to_the_round_limit(self) -> None:
        a = analysis("a", "1" * 10 + "4" * 200 + "1" * 10)
        assert len(refine.calm_targets(a, context(rate=10.0))) == refine.CALM_POINTS_PER_ROUND

    def test_min_tier_leaves_the_lts3_for_later(self) -> None:
        a = analysis("a", "1" * 10 + "3" * 5 + "4" * 5 + "5" * 5 + "1" * 15)
        assert {t.tier for t in refine.calm_targets(a, context(), min_tier=4)} == {4, 5}
        assert {t.tier for t in refine.calm_targets(a, context(), min_tier=3)} == {3, 4, 5}

    def test_the_ends_and_the_vias_are_protected(self) -> None:
        a = analysis("a", "3" * 40)
        a.via_m = [2000.0]
        targets = refine.calm_targets(a, context())
        positions = sorted((t.point[0] - BASE[0]) / 1e-5 + 100 for t in targets)
        slack = 1e-3
        assert positions
        assert all(
            refine.ENDPOINT_CLEARANCE_M - slack <= p <= 4000 - refine.ENDPOINT_CLEARANCE_M + slack
            for p in positions
        )
        assert all(abs(p - 2000.0) >= refine.ENDPOINT_CLEARANCE_M - slack for p in positions)

    def test_quiet_roads_are_never_targets(self) -> None:
        assert refine.calm_targets(analysis("a", "12" * 20), context(rate=10.0)) == []
