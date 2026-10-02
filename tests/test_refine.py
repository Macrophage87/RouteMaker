"""The search over the router's own routes (`core.refine`): the calm detour at
the top of the stress slider (OWNER-DECISIONS 163, 164) and the avoidance of the
worst crossings (165-169), with the router and the route's reading replaced.

Valhalla's `exclude_locations` is what steers it; the tests hold what is asked of
it, what is kept, and why the search stops.
"""

from __future__ import annotations

import dataclasses
import tempfile

import pytest

from core import presets, refine, routing, trailseek
from routemaker import intersections as model
from routemaker.intersections import Control, Event, Movement

QUIET_COST = 0.5
BASE = (-77.0, 38.9)


def piece(along: float, tier: str) -> tuple:
    """A traced piece 100 m long at `along` metres: (piece, (tier, facility))."""
    point = (BASE[0] + along * 1e-5, BASE[1])
    return routing.Piece(1, point[0], point[1], 100.0), (tier, "none")


# A reading whose junctions were read and found to have nothing to say.
NO_EVENTS = ()


def analysis(
    name: str,
    tiers: str = "1" * 40,
    cost_s: float = 4000.0,
    events: list | tuple | None = NO_EVENTS,
    climb_m: float = 0.0,
    shift: int = 0,
    trails: str = "",
) -> refine.Analysis:
    """A candidate read: `tiers` is one letter a 100 m piece, and `shift` moves it
    along (in pieces) so that two candidates can have busy stretches in different places.
    `trails` is a letter a piece too: "t" is a piece of trail (a path)."""
    pieces, classes = zip(
        *[piece((i + shift) * 100.0, tier) for i, tier in enumerate(tiers)], strict=True
    )
    flags = [letter == "t" for letter in trails.ljust(len(tiers))]
    classes = [
        (tier, "path" if on else kind) for (tier, kind), on in zip(classes, flags, strict=True)
    ]
    stress = {"3": 1, "4": 2, "5": 3}
    return refine.Analysis(
        trail_m=100.0 * sum(flags) if trails else 0.0,
        trail_pieces=flags if trails else [],
        length_m=100.0 * len(tiers),
        cost_s=cost_s,
        exposure_m=sum(100.0 * stress.get(tier, 0) for tier in tiers),
        climb_m=climb_m,
        pieces=list(pieces),
        classes=list(classes),
        events=None if events is None else list(events),
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


def context(
    rate=0.0, weight=1.0, climb_weight=0.0, group=False, trail_credit=0.0
) -> refine.Context:
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
        trail_credit=trail_credit,
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


class TestTrafficWins:
    """The owner's "Traffic wins" (OWNER-DECISIONS 61, of hill avoidance), carried
    to this search: it never makes a route busier, however much it saves."""

    def routes(self, monkeypatch, candidate: refine.Analysis, rate: float = 0.0) -> str:
        original = analysis(
            "o", "1" * 10 + "3" * 5 + "1" * 25, cost_s=4000.0, events=[event(1500.0, 4500.0)]
        )
        World(monkeypatch, {"o": original, "c": candidate}, [trip_of("c", 4.0)] * 4)
        kept, _ = refine.refine(trip_of("o", 4.0), context(rate=rate))
        return kept["legs"][0]["shape"]

    def test_fewer_crossings_do_not_buy_more_busy_road(self, monkeypatch) -> None:
        busier = analysis("c", "1" * 10 + "4" * 10 + "1" * 20, cost_s=4000.0, events=[])
        assert busier.score(context()) < analysis(
            "o", "1" * 10 + "3" * 5 + "1" * 25, cost_s=4000.0, events=[event(1500.0, 4500.0)]
        ).score(context()), "it would win on score alone"
        assert self.routes(monkeypatch, busier) == "o"

    def test_the_same_exposure_is_fine(self, monkeypatch) -> None:
        same = analysis("c", "1" * 20 + "3" * 5 + "1" * 15, cost_s=4000.0, events=[])
        assert self.routes(monkeypatch, same) == "c"

    def test_a_little_more_is_within_the_tolerance(self, monkeypatch) -> None:
        # 5 pieces of LTS 3 is 500 weighted metres; a sixth piece is 20 per cent more.
        a_bit = 500.0 * (1 + refine.EXPOSURE_TOLERANCE) + refine.EXPOSURE_SLACK_M
        assert a_bit > 500.0
        within = analysis("c", "1" * 20 + "3" * 5 + "1" * 15, cost_s=4000.0, events=[])
        within.exposure_m = a_bit
        assert self.routes(monkeypatch, within) == "c"
        over = analysis("c", "1" * 20 + "3" * 5 + "1" * 15, cost_s=4000.0, events=[])
        over.exposure_m = a_bit + 1
        assert self.routes(monkeypatch, over) == "o"

    def test_the_calm_search_does_not_trade_lts3_for_lts4_either(self, monkeypatch) -> None:
        swap = analysis("c", "1" * 10 + "4" * 6 + "1" * 24, cost_s=3000.0, events=[])
        assert self.routes(monkeypatch, swap, rate=10.0) == "o"

    def test_a_calmer_route_is_taken_as_before(self, monkeypatch) -> None:
        calm = analysis("c", "1" * 40, cost_s=4100.0, events=[])
        assert self.routes(monkeypatch, calm) == "c"


class TestMargins:
    """A candidate has to beat the best by a margin: a few seconds of cost are not
    a reason to send a rider a different way."""

    def original_score(self) -> float:
        return analysis("o", TestCalmDetour().stretch()).score(context(rate=0.0001))

    def run(self, monkeypatch, candidate_cost: float) -> str:
        orig = analysis("o", TestCalmDetour().stretch(), cost_s=4000.0)
        cand = analysis("c", "1" * 40, cost_s=candidate_cost)
        World(monkeypatch, {"o": orig, "c": cand}, [trip_of("c", 4.0)] * 5)
        kept, _ = refine.refine(trip_of("o", 4.0), context(rate=0.0001))
        return kept["legs"][0]["shape"]

    def test_better_by_more_than_the_margin_is_taken(self, monkeypatch) -> None:
        assert self.run(monkeypatch, self.original_score() - refine.IMPROVEMENT_EPS_S - 1) == "c"

    def test_better_by_less_is_not(self, monkeypatch) -> None:
        assert self.run(monkeypatch, self.original_score() - refine.IMPROVEMENT_EPS_S / 2) == "o"

    def test_slightly_worse_is_not_taken_either(self, monkeypatch) -> None:
        assert self.run(monkeypatch, self.original_score() + refine.IMPROVEMENT_EPS_S / 2) == "o"


class TestStopping:
    def test_two_rounds_without_improvement_end_the_search(self, monkeypatch) -> None:
        orig = analysis("o", TestCalmDetour().stretch(), cost_s=4000.0)
        worse = analysis("w", "1" * 5 + "4" * 4 + "1" * 5 + "3" * 8 + "1" * 18, cost_s=9000.0)
        world = World(monkeypatch, {"o": orig, "w": worse}, [trip_of("w", 6.0)] * 6)
        kept, info = refine.refine(trip_of("o", 4.0), context(rate=0.001))
        assert kept["legs"][0]["shape"] == "o"
        assert info["rounds"] == refine.REFINE_PATIENCE == 2
        assert len(world.requests) == 2

    def test_the_patience_counts_rounds_not_targets(self, monkeypatch) -> None:
        """Each candidate has a new busy stretch, so there is always something to
        exclude: only the patience ends the search, after exactly two rounds that
        do not beat the best."""
        orig = analysis("o", "1" * 5 + "3" * 8 + "1" * 27, cost_s=4000.0)
        worse = {
            name: analysis(name, "1" * 5 + "3" * 8 + "1" * 27, cost_s=9000.0, shift=shift)
            for name, shift in (("w1", 100), ("w2", 200), ("w3", 300), ("w4", 400))
        }
        world = World(monkeypatch, {"o": orig, **worse}, [trip_of(n, 4.0) for n in worse])
        kept, info = refine.refine(trip_of("o", 4.0), context(rate=0.001))
        assert kept["legs"][0]["shape"] == "o"
        assert info["rounds"] == 2 and len(world.requests) == 2

    def test_a_better_candidate_resets_the_patience(self, monkeypatch) -> None:
        orig = analysis("o", "1" * 5 + "3" * 8 + "1" * 27, cost_s=5000.0)
        steps = {
            "w1": analysis("w1", "1" * 5 + "3" * 8 + "1" * 27, cost_s=9000.0, shift=100),
            "b": analysis("b", "1" * 5 + "3" * 8 + "1" * 27, cost_s=4100.0, shift=200),
            "w2": analysis("w2", "1" * 5 + "3" * 8 + "1" * 27, cost_s=9000.0, shift=300),
            "w3": analysis("w3", "1" * 5 + "3" * 8 + "1" * 27, cost_s=9000.0, shift=400),
            "w4": analysis("w4", "1" * 5 + "3" * 8 + "1" * 27, cost_s=9000.0, shift=500),
        }
        world = World(monkeypatch, {"o": orig, **steps}, [trip_of(n, 4.0) for n in steps])
        refine.refine(trip_of("o", 4.0), context(rate=1.0))
        # w1 is worse (1 stale), b is better (reset), w2 and w3 are worse (2 stale): four rounds.
        assert len(world.requests) == 4

    def test_the_exclusions_sent_are_capped_at_what_the_router_takes(self, monkeypatch) -> None:
        shapes = {
            "o": analysis("o", "3" * 200, cost_s=4000.0),
            "c1": analysis("c1", "3" * 200, cost_s=3900.0, shift=300),
            "c2": analysis("c2", "3" * 200, cost_s=3800.0, shift=600),
            "c3": analysis("c3", "3" * 200, cost_s=3700.0, shift=900),
        }
        routes = [trip_of(n, 4.0) for n in ("c1", "c2", "c3", "c3", "c3")]
        world = World(monkeypatch, shapes, routes)
        refine.refine(trip_of("o", 4.0), context(rate=10.0))
        assert len(world.requests) >= 3
        sent = [len(r["exclude_locations"]) for r in world.requests]
        assert sent[0] == refine.CALM_POINTS_PER_ROUND
        assert sent[2] == refine.MAX_EXCLUDES < 3 * refine.CALM_POINTS_PER_ROUND

    def test_later_rounds_exclude_stretches_not_crossings(self, monkeypatch) -> None:
        """Crossing avoidance is the first round's: after it the search is about
        the busy stretches alone."""
        later = (BASE[0] + 0.0009, BASE[1] + 1e-5)
        orig = analysis("o", "1" * 5 + "4" * 4 + "1" * 31, cost_s=4000.0, events=[event(1500.0)])
        step = analysis(
            "s",
            "1" * 15 + "3" * 8 + "1" * 17,
            cost_s=4300.0,
            events=[event(2500.0, 3000.0, approach=later)],
        )
        world = World(monkeypatch, {"o": orig, "s": step}, [trip_of("s", 4.3)] * 3)
        refine.refine(trip_of("o", 4.0), context(rate=10.0))
        assert len(world.requests) >= 2
        assert later not in set(world.excluded(1)) - set(world.excluded(0))

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

    def test_a_full_list_ends_the_search_rather_than_asking_again(self, monkeypatch) -> None:
        """Review r1, SHOULD_FIX 3: once the list is at the router's limit, a
        new round would only send it again."""
        shapes = {
            "o": analysis("o", "3" * 200, cost_s=4000.0),
            "c1": analysis("c1", "3" * 200, cost_s=3900.0, shift=300),
            "c2": analysis("c2", "3" * 200, cost_s=3800.0, shift=600),
            "c3": analysis("c3", "3" * 200, cost_s=3700.0, shift=900),
        }
        routes = [trip_of(n, 4.0) for n in ("c1", "c2", "c3", "c3", "c3")]
        world = World(monkeypatch, shapes, routes)
        _kept, info = refine.refine(trip_of("o", 4.0), context(rate=10.0))
        assert len(world.requests) == 3
        assert info["limited"] == "excludes"
        sent = [tuple(world.excluded(n)) for n in range(len(world.requests))]
        assert len(set(sent)) == len(sent), "no exclusion list is sent twice"

    def test_the_same_set_is_never_sent_twice_in_another_order(self, monkeypatch) -> None:
        """Round 1's full ask is refused and its LTS 4 ask taken; round 2's ask,
        the same points in another order, is not sent again."""
        orig = analysis("o", "1" * 5 + "44" + "33" + "1" * 31, cost_s=9000.0)
        c1 = analysis("c1", "1" * 7 + "33" + "44" + "1" * 29, cost_s=8000.0)
        c2 = analysis("c2", "1" * 7 + "33" + "1" * 31, cost_s=7000.0)
        world = World(
            monkeypatch,
            {"o": orig, "c1": c1, "c2": c2},
            [
                trip_of("c1", 4.0),
                routing.RouterRefused(400, 442, "no path"),
                trip_of("c2", 4.0),
                routing.RouterRefused(400, 442, "no path"),
            ],
        )
        refine.refine(trip_of("o", 4.0), context(rate=10.0))
        sent = [frozenset(world.excluded(n)) for n in range(len(world.requests))]
        assert len(sent) == 3
        assert len(set(sent)) == 3

    def test_the_same_list_is_never_sent_twice(self, monkeypatch) -> None:
        """A reduced ask that equals one already sent is not asked again."""
        orig = analysis("o", "1" * 5 + "4" * 4 + "3" * 4 + "1" * 27)
        world = World(
            monkeypatch,
            {"o": orig},
            [
                routing.RouterRefused(400, 442, "no path"),
                routing.RouterRefused(400, 442, "no path"),
            ],
        )
        refine.refine(trip_of("o", 4.0), context(rate=10.0))
        sent = [tuple(world.excluded(n)) for n in range(len(world.requests))]
        assert len(set(sent)) == len(sent)


class TestUnreadJunctions:
    def test_a_candidate_whose_junctions_could_not_be_read_is_not_taken(self, monkeypatch) -> None:
        """Review r1, SHOULD_FIX 4: it would score as having no crossings at all."""
        orig = analysis("o", "1" * 5 + "4" * 4 + "1" * 31, events=[event(1500.0)])
        unread = analysis("u", "1" * 40, cost_s=3000.0, events=None)
        World(monkeypatch, {"o": orig, "u": unread}, [trip_of("u", 4.0)] * 3)
        kept, info = refine.refine(trip_of("o", 4.0), context(rate=10.0))
        assert kept["legs"][0]["shape"] == "o"
        assert info["rounds"] >= 1

    def test_the_same_candidate_read_is_taken(self, monkeypatch) -> None:
        orig = analysis("o", "1" * 5 + "4" * 4 + "1" * 31, events=[event(1500.0)])
        read = analysis("r", "1" * 40, cost_s=3000.0, events=[])
        World(monkeypatch, {"o": orig, "r": read}, [trip_of("r", 4.0)] * 3)
        kept, _info = refine.refine(trip_of("o", 4.0), context(rate=10.0))
        assert kept["legs"][0]["shape"] == "r"


class TestNoLimitOfItsOwn:
    """Review r2, SHOULD_FIX 3: the search runs inside an API routing request,
    which holds one of the deployment's `ROUTING_CONCURRENCY` advisory-lock
    slots, so it has no slot of its own; round 1's lock files were dropped."""

    def test_the_search_takes_no_slot_and_writes_no_file(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
        orig = analysis("o", "1" * 5 + "4" * 4 + "1" * 31, events=[event(1500.0)])
        calm = analysis("c", "1" * 50, cost_s=3000.0, events=[])
        world = World(monkeypatch, {"o": orig, "c": calm}, [trip_of("c", 5.0)] * 3)
        kept, info = refine.refine(trip_of("o", 4.0), context(rate=10.0))
        assert world.requests and kept["legs"][0]["shape"] == "c"
        assert info["limited"] != "busy"
        assert list(tmp_path.iterdir()) == []
        for name in ("search_slot", "CALM_SLOT_DIR", "CALM_SEARCHES_PER_HOST"):
            assert not hasattr(refine, name)

    def test_a_long_ride_never_runs_it(self) -> None:
        """Long rides have a pool of their own (`LONG_ROUTING_IN_FLIGHT`); they
        do not search, so every search is inside a `ROUTING_CONCURRENCY` slot."""
        deadline = routing.Deadline(routing.clock() + 60, 30)
        points = [[-77.0, 38.9], [-77.01, 38.91]]
        assert routing._refine_limit("default", points, True, False, deadline) == "long_ride"
        assert routing._refine_limit("default", points, False, False, deadline) is None


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

    def test_the_points_are_the_edges_interpolated_middles(self) -> None:
        """Review r1, SHOULD_FIX 1: never a vertex at a node."""
        a = analysis("a", "1" * 10 + "3" * 20 + "1" * 10)
        middle = (BASE[0] + 0.0155, BASE[1] + 2e-6)
        a.marks = [(1550.0, *middle, 300.0)]
        assert refine.calm_targets(a, context(rate=10.0)) == [refine.Target(middle, 3)]

    def test_a_short_edges_middle_is_too_near_its_nodes(self) -> None:
        a = analysis("a", "1" * 10 + "3" * 20 + "1" * 10)
        a.marks = [(1550.0, BASE[0] + 0.0155, BASE[1], refine.CALM_MIN_EDGE_M - 1)]
        assert refine.calm_targets(a, context(rate=10.0)) == []

    def test_the_tier_is_the_one_under_the_middle(self) -> None:
        a = analysis("a", "1" * 10 + "3" * 10 + "4" * 10 + "1" * 10)
        a.marks = [(1550.0, 0.1, 0.1, 100.0), (2550.0, 0.2, 0.2, 100.0), (3550.0, 0.3, 0.3, 100.0)]
        assert [t.tier for t in refine.calm_targets(a, context(rate=10.0))] == [3, 4]

    def test_no_pieces_no_targets(self) -> None:
        a = analysis("a", "1")
        a.pieces, a.classes = [], []
        assert refine.calm_targets(a, context(rate=10.0)) == []


class TestWideSearch:
    """OWNER-DECISIONS 187, an exploration: candidates through points off the
    straight line, which the nested exclusion rounds cannot reach."""

    def wide_context(self, rate=10.0) -> refine.Context:
        ctx = context(rate=rate)
        ctx.request["locations"] = [
            {"lon": BASE[0], "lat": BASE[1]},
            {"lon": BASE[0] + 0.1, "lat": BASE[1]},
        ]
        ctx.points = [[BASE[0], BASE[1]], [BASE[0] + 0.1, BASE[1]]]
        ctx.wide = True
        return ctx

    def test_off_unless_the_owner_turns_it_on(self, monkeypatch) -> None:
        assert refine.WIDE_SEARCH_FROM_RATE is None
        assert not refine.wide_search_for(1e9)
        monkeypatch.setattr(refine, "WIDE_SEARCH_FROM_RATE", 10.0)
        assert refine.wide_search_for(10.0) and not refine.wide_search_for(9.9)

    def test_the_points_are_either_side_of_the_middle(self) -> None:
        span_lon = 0.1
        points = refine.wide_points([[BASE[0], BASE[1]], [BASE[0] + span_lon, BASE[1]]])
        assert len(points) == len(refine.WIDE_OFFSETS)
        for (lon, lat), offset in zip(points, refine.WIDE_OFFSETS, strict=True):
            assert lon == pytest.approx(BASE[0] + span_lon / 2, abs=1e-9)
            # Going east, left is north.
            assert (lat > BASE[1]) == (offset > 0)
        north = sorted(lat for _lon, lat in points)
        assert north[0] < north[1] < BASE[1] < north[2] < north[3]

    def test_a_short_span_has_no_room(self) -> None:
        assert refine.wide_points([[BASE[0], BASE[1]], [BASE[0] + 0.01, BASE[1]]]) == []

    def test_each_point_is_asked_as_a_through_location_and_the_best_kept(self, monkeypatch) -> None:
        orig = analysis("o", "1" * 10 + "3" * 10 + "1" * 20, cost_s=4000.0)
        # The exclusion rounds find nothing better ...
        worse = analysis("w", "1" * 10 + "3" * 10 + "1" * 20, cost_s=9000.0, shift=100)
        # ... and the second wide point is calm.
        wide_calm = analysis("c", "1" * 50, cost_s=4800.0, shift=300)
        wide_busy = analysis("b", "1" * 10 + "4" * 10 + "1" * 30, cost_s=4100.0, shift=600)
        routes = [trip_of("w", 4.0), trip_of("w", 4.0)] + [
            trip_of(n, 5.0) for n in ("b", "c", "b", "b")
        ]
        world = World(monkeypatch, {"o": orig, "w": worse, "c": wide_calm, "b": wide_busy}, routes)
        kept, info = refine.refine(trip_of("o", 4.0), self.wide_context())
        assert kept["legs"][0]["shape"] == "c"
        assert info["wide"] == {"asked": 4, "taken": True}
        wide_asks = [r for r in world.requests if len(r["locations"]) == 3]
        assert len(wide_asks) == 4
        assert all(r["locations"][1]["type"] == "through" for r in wide_asks)
        assert all("exclude_locations" not in r and "alternates" not in r for r in wide_asks)

    def test_a_busier_wide_route_is_never_taken(self, monkeypatch) -> None:
        orig = analysis("o", "1" * 10 + "3" * 10 + "1" * 20, cost_s=4000.0)
        busy = analysis("b", "1" * 10 + "4" * 10 + "1" * 20, cost_s=100.0, shift=100)
        routes = [refine_none for refine_none in [routing.RouterRefused(400, 442, "no path")] * 2]
        routes += [trip_of("b", 4.0)] * 4
        World(monkeypatch, {"o": orig, "b": busy}, routes)
        kept, info = refine.refine(trip_of("o", 4.0), self.wide_context(rate=0.0))
        assert kept["legs"][0]["shape"] == "o"
        assert info["wide"] == {"asked": 4, "taken": False}

    def wide_world(self, monkeypatch, wide_cost: float, events=NO_EVENTS):
        orig = analysis("o", "1" * 40, cost_s=4000.0)
        wide = analysis("w", "1" * 40, cost_s=wide_cost, shift=100, events=events)
        World(monkeypatch, {"o": orig, "w": wide}, [trip_of("w", 4.0)] * 4)
        kept, info = refine.refine(trip_of("o", 4.0), self.wide_context(rate=0.0))
        return kept["legs"][0]["shape"], info

    def test_a_wide_route_must_beat_the_best_by_the_margin(self, monkeypatch) -> None:
        shape, _info = self.wide_world(monkeypatch, 4000.0 - refine.IMPROVEMENT_EPS_S / 2)
        assert shape == "o"
        shape, info = self.wide_world(monkeypatch, 4000.0 - refine.IMPROVEMENT_EPS_S - 1)
        assert shape == "w" and info["wide"]["taken"]

    def test_a_wide_route_whose_junctions_were_not_read_is_not_taken(self, monkeypatch) -> None:
        shape, info = self.wide_world(monkeypatch, 1000.0, events=None)
        assert shape == "o" and not info["wide"]["taken"]

    def test_not_asked_without_the_time(self, monkeypatch) -> None:
        orig = analysis("o", "1" * 40)
        world = World(monkeypatch, {"o": orig}, [])
        ctx = self.wide_context(rate=0.0)
        ctx.deadline = routing.Deadline(routing.clock() + refine.REFINE_TRACE_RESERVE_S + 1, 35)
        _kept, info = refine.refine(trip_of("o", 4.0), ctx)
        assert world.requests == [] and info["wide"] == {"asked": 0, "taken": False}


class SeekWorld(World):
    """A World that also records each route request's deadline."""

    def __init__(self, monkeypatch, analyses: dict, routes: list) -> None:
        super().__init__(monkeypatch, analyses, routes)
        self.deadlines: list[float] = []

    def call(self, variant, endpoint, payload, deadline):
        if asks_through(payload):
            self.deadlines.append(deadline.at - routing.clock())
        return super().call(variant, endpoint, payload, deadline)


KY = 110_540.0


def asks_through(request: dict) -> bool:
    return any(p.get("type") == "through" for p in request["locations"])


def trail_segments(lon0=0.01, lon1=0.09, north_m=100.0, step=0.002) -> list:
    """A trail beside the straight line from BASE 0.1 degrees east, as the
    segment table's rows (two vertices each)."""
    n = round((lon1 - lon0) / step)
    lat = BASE[1] + north_m / KY
    pts = [(BASE[0] + lon0 + (lon1 - lon0) * i / n, lat) for i in range(n + 1)]
    return [[a, b] for a, b in zip(pts, pts[1:], strict=False)]


ALL_BUSY = analysis("o", "3" * 40, cost_s=4000.0)
BUSY = "1" * 5 + "4" * 4 + "1" * 5 + "3" * 8 + "1" * 18
NO_ROUTE = routing.RouterRefused(400, 442, "no path")


class TestTrailSeek:
    """OWNER-DECISIONS 194, FOLLOWUP-TRAIL-SEEK: after the exclusion rounds, the
    router's route through the entry and exit of the best corridors of trail near
    the line, each scored and guarded as every other candidate."""

    @pytest.fixture(autouse=True)
    def trails(self, monkeypatch):
        self.asked: list[tuple] = []
        self.segments = trail_segments()

        def table(schema, guide, width_m, has_facility, when, avoid_unpaved=False, **kw):
            self.asked.append((schema, guide, width_m, has_facility, when, avoid_unpaved))
            self.table_kw = kw
            if isinstance(self.segments, Exception):
                raise self.segments
            return self.segments

        monkeypatch.setattr(trailseek, "corridor_segments", table)
        route = [(BASE[0] + i * 0.01, BASE[1]) for i in range(11)]
        monkeypatch.setattr(routing, "decode_polyline6", lambda shape: route)

    def seek_context(self, rate=10.0, deadline_s=40.0) -> refine.Context:
        ctx = context(rate=rate)
        ctx.request["locations"] = [
            {"lon": BASE[0], "lat": BASE[1]},
            {"lon": BASE[0] + 0.1, "lat": BASE[1]},
        ]
        ctx.points = [[BASE[0], BASE[1]], [BASE[0] + 0.1, BASE[1]]]
        ctx.deadline = routing.Deadline(routing.clock() + deadline_s, 35)
        ctx.seek = True
        ctx.schema = "live"
        ctx.with_facility = True
        ctx.when = "weekend"
        return ctx

    def orig(self, **kw) -> refine.Analysis:
        return analysis("o", "1" * 10 + "3" * 10 + "1" * 20, cost_s=4000.0, **kw)

    def run(self, monkeypatch, analyses, routes, ctx=None):
        # At this rate the exclusion search runs first; the router has no route
        # for its one round, so what follows is the seek's.
        world = SeekWorld(monkeypatch, {"o": self.orig(), **analyses}, [NO_ROUTE, *routes])
        kept, info = refine.refine(trip_of("o", 4.0), ctx or self.seek_context())
        world.searches = [r for r in world.requests if not asks_through(r)]
        world.requests = [r for r in world.requests if asks_through(r)]
        return world, kept["legs"][0]["shape"], info

    def test_off_unless_the_plan_asks(self, monkeypatch) -> None:
        ctx = self.seek_context()
        ctx.seek = False
        world, shape, info = self.run(monkeypatch, {}, [], ctx)
        assert shape == "o" and world.requests == [] and "seek" not in info and self.asked == []

    def test_the_route_is_asked_for_through_the_corridors_entry_and_exit(self, monkeypatch) -> None:
        calm = analysis("t", "1" * 45, cost_s=3000.0, shift=100)
        world, shape, info = self.run(monkeypatch, {"t": calm}, [trip_of("t", 4.5)])
        assert shape == "t"
        (request,) = world.requests
        start, entry, leave, end = request["locations"]
        assert (entry["type"], leave["type"]) == ("through", "through")
        assert "alternates" not in request
        # On the trail, a little inside its ends, in the order ridden.
        lat = BASE[1] + 100 / KY
        assert entry["lat"] == pytest.approx(lat) and leave["lat"] == pytest.approx(lat)
        # The route's busy stretch is 0.025 to 0.05 degrees along: the trail leaves
        # the route by its start and rejoins it past its end.
        assert BASE[0] + 0.01 < entry["lon"] <= BASE[0] + 0.0275
        assert BASE[0] + 0.0475 <= leave["lon"] < BASE[0] + 0.09
        assert start == {"lon": BASE[0], "lat": BASE[1]}
        assert end == {"lon": BASE[0] + 0.1, "lat": BASE[1]}
        seek = info["seek"]
        assert seek["corridors"] == 1 and seek["asked"] == 1 and seek["taken"] is True
        assert seek["limited"] is None
        (tried,) = seek["tried"]
        assert tried["outcome"] == "taken" and tried["corridors"] == 1
        assert tried["gain_m"] == pytest.approx(2165, abs=100) and tried["length_m"] == 4500
        # 1,000 s of cost and 1,000 m of exposure at the rate.
        assert tried["score_gain_s"] == pytest.approx(1000.0 + QUIET_COST * 10.0 * 1000.0, abs=1.0)

    def test_the_table_is_read_for_the_straight_line_and_the_route(self, monkeypatch) -> None:
        ctx = self.seek_context()
        ctx.avoid_gravel = True
        self.run(monkeypatch, {}, [NO_ROUTE], ctx)
        ((schema, guide, width, has_facility, when, avoid_unpaved),) = self.asked
        assert (schema, has_facility, when, avoid_unpaved) == ("live", True, "weekend", True)
        straight, route = guide
        assert straight == [tuple(ctx.points[0]), tuple(ctx.points[1])]
        assert route[0] == (BASE[0], BASE[1]) and route[-1] == (BASE[0] + 0.1, BASE[1])
        span = 0.1 * 111_320.0 * 0.7782
        assert width == pytest.approx(trailseek.band_m(span), rel=0.01)

    def test_a_long_route_is_thinned_for_the_query(self, monkeypatch) -> None:
        long = [(BASE[0] + i * 1e-5, BASE[1]) for i in range(4000)]
        monkeypatch.setattr(routing, "decode_polyline6", lambda shape: long)
        self.run(monkeypatch, {}, [NO_ROUTE])
        route = self.asked[0][1][1]
        assert 350 <= len(route) <= 450 and route[-1] == long[-1]

    def test_the_best_of_the_candidates_is_kept(self, monkeypatch) -> None:
        # Two trails one after the other, and a third over the first: three asks.
        self.segments = (
            trail_segments(0.01, 0.04)
            + trail_segments(0.06, 0.09, north_m=-100.0)
            + trail_segments(0.012, 0.038, north_m=180.0)
        )
        better = analysis("a", "1" * 40, cost_s=3500.0, shift=100)
        best = analysis("b", "1" * 40, cost_s=3000.0, shift=200)
        worse = analysis("c", "1" * 40, cost_s=4500.0, shift=300)
        world, shape, info = self.run(
            monkeypatch,
            {"o": ALL_BUSY, "a": better, "b": best, "c": worse},
            [trip_of("a", 4.0), trip_of("b", 4.0), trip_of("c", 4.0)],
        )
        assert len(world.requests) == info["seek"]["asked"] == trailseek.SEEK_MAX_CANDIDATES
        assert shape == "b"
        assert [t["outcome"] for t in info["seek"]["tried"]] == ["taken", "taken", "not_better"]

    def test_two_corridors_are_asked_for_together_in_order(self, monkeypatch) -> None:
        self.segments = trail_segments(0.01, 0.04) + trail_segments(0.06, 0.09, north_m=-100.0)
        analyses = {"o": ALL_BUSY}
        world, _shape, info = self.run(monkeypatch, analyses, [trip_of("o", 4.0)] * 3)
        assert info["seek"]["corridors"] == 2
        first = world.requests[0]["locations"]
        types = [p.get("type") for p in first]
        assert types == [None, "through", "through", "through", "through", None]
        lons = [p["lon"] for p in first]
        assert lons == sorted(lons)
        # Then the best alone.
        assert len(world.requests[1]["locations"]) == 4

    def test_a_busier_route_is_never_taken(self, monkeypatch) -> None:
        busy = analysis("t", "1" * 10 + "4" * 10 + "1" * 20, cost_s=100.0, shift=100)
        _w, shape, info = self.run(monkeypatch, {"t": busy}, [trip_of("t", 4.0)])
        assert shape == "o"
        assert info["seek"]["tried"][0]["outcome"] == "busier"
        assert info["seek"]["taken"] is False

    def test_a_route_busier_by_less_than_the_tolerance_is_not_busier(self, monkeypatch) -> None:
        # The router's own route has 1,000 m of exposure; the allowance is 2% and 50 m.
        limit = 1000.0 * (1 + refine.EXPOSURE_TOLERANCE) + refine.EXPOSURE_SLACK_M
        assert limit == pytest.approx(1070.0)
        for extra, outcome in ((0, "taken"), (1, "busier")):
            candidate = analysis("t", "1" * 30 + "3" * 10, cost_s=100.0, shift=100)
            candidate.exposure_m = limit + extra
            _w, _shape, info = self.run(monkeypatch, {"t": candidate}, [trip_of("t", 4.0)])
            assert info["seek"]["tried"][0]["outcome"] == outcome

    def test_a_route_that_does_not_beat_the_best_by_the_margin_is_not_taken(
        self, monkeypatch
    ) -> None:
        eps = refine.IMPROVEMENT_EPS_S
        for gain, outcome in ((eps / 2, "not_better"), (eps + 1, "taken")):
            cand = analysis("t", "1" * 10 + "3" * 10 + "1" * 20, cost_s=4000.0 - gain, shift=100)
            _w, shape, info = self.run(monkeypatch, {"t": cand}, [trip_of("t", 4.0)])
            assert info["seek"]["tried"][0]["outcome"] == outcome
            assert shape == ("t" if outcome == "taken" else "o")

    def test_a_route_whose_junctions_could_not_be_read_is_not_taken(self, monkeypatch) -> None:
        unread = analysis("t", "1" * 40, cost_s=100.0, shift=100, events=None)
        _w, shape, info = self.run(monkeypatch, {"t": unread}, [trip_of("t", 4.0)])
        assert shape == "o" and info["seek"]["tried"][0]["outcome"] == "unread"

    def test_junction_costs_still_count(self, monkeypatch) -> None:
        # Quieter on paper, but through a worse crossing.
        crossing = analysis(
            "t", "1" * 40, cost_s=3900.0, shift=100, events=[event(1500.0, 60_000.0)]
        )
        _w, shape, info = self.run(monkeypatch, {"t": crossing}, [trip_of("t", 4.0)])
        assert shape == "o" and info["seek"]["tried"][0]["outcome"] == "not_better"

    def test_no_route_through_the_points_keeps_the_route(self, monkeypatch) -> None:
        _w, shape, info = self.run(monkeypatch, {}, [NO_ROUTE])
        assert shape == "o"
        assert info["seek"]["tried"][0]["outcome"] == "no_route"
        assert "length_m" not in info["seek"]["tried"][0]

    def test_a_route_with_no_legs_is_no_route(self, monkeypatch) -> None:
        _w, shape, info = self.run(monkeypatch, {}, [{"legs": []}])
        assert shape == "o" and info["seek"]["tried"][0]["outcome"] == "no_route"

    def test_the_search_keeps_the_ways_it_excluded_and_asks_with_them(self, monkeypatch) -> None:
        analyses = {
            "o": analysis("o", BUSY, cost_s=4000.0),
            "c": analysis("c", "1" * 20 + "3" * 8 + "1" * 12, cost_s=4300.0),
            "t": analysis("t", "1" * 40, cost_s=3000.0, shift=100),
        }
        routes = [trip_of("c", 4.0), NO_ROUTE, trip_of("t", 4.0)]
        world = SeekWorld(monkeypatch, analyses, routes)
        kept, info = refine.refine(trip_of("o", 4.0), self.seek_context(rate=10.0))
        assert kept["legs"][0]["shape"] == "t"
        searched = [r for r in world.requests if not asks_through(r)]
        seek = [r for r in world.requests if asks_through(r)]
        assert len(seek) == 1 and searched
        wanted = searched[0]["exclude_locations"]
        assert seek[0]["exclude_locations"] == wanted and len(wanted) > 0
        assert info["seek"]["tried"][0]["excluded"] == len(wanted)

    def test_with_no_route_under_the_exclusions_it_asks_again_without(self, monkeypatch) -> None:
        analyses = {
            "o": analysis("o", BUSY, cost_s=4000.0),
            "c": analysis("c", "1" * 20 + "3" * 8 + "1" * 12, cost_s=4300.0),
            "t": analysis("t", "1" * 40, cost_s=3000.0, shift=100),
        }
        routes = [trip_of("c", 4.0), NO_ROUTE, NO_ROUTE, trip_of("t", 4.0)]
        world = SeekWorld(monkeypatch, analyses, routes)
        kept, info = refine.refine(trip_of("o", 4.0), self.seek_context(rate=10.0))
        assert kept["legs"][0]["shape"] == "t"
        seek = [r for r in world.requests if asks_through(r)]
        assert len(seek) == 2
        assert "exclude_locations" in seek[0] and "exclude_locations" not in seek[1]
        assert info["seek"]["tried"][0]["excluded"] == 0

    def test_no_trail_no_ask(self, monkeypatch) -> None:
        self.segments = []
        world, shape, info = self.run(monkeypatch, {}, [])
        assert world.requests == [] and shape == "o"
        empty = {
            "corridors": 0,
            "asked": 0,
            "routes": 0,
            "taken": False,
            "limited": None,
            "whole_trip": None,
            "tried": [],
            "legs": 1,
        }
        assert info["seek"] == empty

    def test_a_table_that_cannot_be_read_keeps_the_route(self, monkeypatch) -> None:
        self.segments = RuntimeError("the database is down")
        world, shape, info = self.run(monkeypatch, {}, [])
        assert world.requests == [] and shape == "o" and info["seek"]["limited"] == "table"

    def test_only_a_start_and_an_end(self, monkeypatch) -> None:
        ctx = self.seek_context()
        ctx.points.append([BASE[0] + 0.2, BASE[1]])
        ctx.request["locations"].append({"lon": BASE[0] + 0.2, "lat": BASE[1]})
        world, _shape, info = self.run(monkeypatch, {}, [], ctx)
        assert info["seek"]["limited"] == "points" and self.asked == [] and world.requests == []

    def test_the_points_and_the_locations_must_both_be_two(self, monkeypatch) -> None:
        ctx = self.seek_context()
        ctx.points.append([BASE[0] + 0.2, BASE[1]])
        _w, _shape, info = self.run(monkeypatch, {}, [], ctx)
        assert info["seek"]["limited"] == "points"
        ctx = self.seek_context()
        ctx.request["locations"].append({"lon": BASE[0] + 0.2, "lat": BASE[1]})
        _w, _shape, info = self.run(monkeypatch, {}, [], ctx)
        assert info["seek"]["limited"] == "points"

    def test_a_short_span_has_no_room(self, monkeypatch) -> None:
        ctx = self.seek_context()
        ctx.points[1] = [BASE[0] + 0.01, BASE[1]]
        ctx.request["locations"][1] = {"lon": BASE[0] + 0.01, "lat": BASE[1]}
        _world, _shape, info = self.run(monkeypatch, {}, [], ctx)
        assert info["seek"]["limited"] == "span" and self.asked == []

    def test_its_own_budget_is_past_the_searchs(self, monkeypatch) -> None:
        calm = analysis("t", "1" * 40, cost_s=3000.0, shift=100)
        world, _shape, _info = self.run(monkeypatch, {"t": calm}, [trip_of("t", 4.0)])
        assert world.deadlines[0] == pytest.approx(trailseek.SEEK_BUDGET_S, abs=0.5)

    def test_the_budget_is_cut_to_what_the_request_has_left(self, monkeypatch) -> None:
        calm = analysis("t", "1" * 40, cost_s=3000.0, shift=100)
        ctx = self.seek_context(deadline_s=refine.REFINE_TRACE_RESERVE_S + 3.0)
        world, _shape, _info = self.run(monkeypatch, {"t": calm}, [trip_of("t", 4.0)], ctx)
        assert world.deadlines[0] == pytest.approx(3.0, abs=0.5)

    def test_not_asked_without_the_time(self, monkeypatch) -> None:
        ctx = self.seek_context(deadline_s=refine.REFINE_TRACE_RESERVE_S + 1.0)
        world, _shape, info = self.run(monkeypatch, {}, [], ctx)
        assert world.requests == [] and info["seek"]["limited"] == "time"
        assert self.asked == []

    def test_the_time_running_out_mid_search_ends_it(self, monkeypatch) -> None:
        self.segments = trail_segments(0.01, 0.04) + trail_segments(0.06, 0.09, north_m=500.0)
        ran_out = routing.DeadlineExceeded("out of time")
        world, shape, info = self.run(monkeypatch, {}, [ran_out])
        assert shape == "o" and info["seek"]["limited"] == "time"
        assert len(world.requests) == 1 and info["seek"]["tried"] == []

    def test_a_router_that_stops_answering_keeps_the_route(self, monkeypatch) -> None:
        down = routing.RouterUnavailable("down")
        _w, shape, info = self.run(monkeypatch, {}, [down])
        assert shape == "o" and info["seek"]["limited"] == "time"

    def test_a_candidate_is_not_started_with_less_than_the_least(self, monkeypatch) -> None:
        # Two candidates; the clock jumps after the first one's route is asked.
        self.segments = trail_segments(0.01, 0.04) + trail_segments(0.06, 0.09, north_m=-100.0)
        now = [routing.clock()]
        monkeypatch.setattr(routing, "clock", lambda: now[0])
        ctx = self.seek_context()
        routes = [NO_ROUTE] + [trip_of("o", 4.0)] * 3
        world = SeekWorld(monkeypatch, {"o": ALL_BUSY}, routes)
        real_call = world.call

        def call(variant, endpoint, payload, deadline):
            answer = real_call(variant, endpoint, payload, deadline)
            if asks_through(payload):
                now[0] += trailseek.SEEK_BUDGET_S - trailseek.SEEK_ROUND_MIN_S + 0.5
            return answer

        monkeypatch.setattr(routing, "_call", call)
        _kept, info = refine.refine(trip_of("o", 4.0), ctx)
        asks = [r for r in world.requests if asks_through(r)]
        assert info["seek"]["limited"] == "time" and len(asks) == 1

    # --- review r1 -------------------------------------------------------------

    def test_a_ride_on_the_roadway_only_graph_does_not_seek(self, monkeypatch) -> None:
        # Group Ride with trails off at 100: the no-trail graph has no trails, and
        # through points would snap to the roads beside them.
        ctx = self.seek_context()
        ctx.roadway_only = True
        world, shape, info = self.run(monkeypatch, {}, [], ctx)
        assert info["seek"]["limited"] == "roadway_only"
        assert self.asked == [] and world.requests == [] and shape == "o"

    def test_the_table_read_has_the_legs_time_as_its_timeout(self, monkeypatch) -> None:
        self.run(monkeypatch, {}, [NO_ROUTE])
        assert self.table_kw["timeout_s"] == pytest.approx(trailseek.TABLE_TIMEOUT_S)
        ctx = self.seek_context(deadline_s=refine.REFINE_TRACE_RESERVE_S + 2.2)
        self.run(monkeypatch, {}, [NO_ROUTE], ctx)
        assert self.table_kw["timeout_s"] == pytest.approx(2.2, abs=0.1)

    def test_a_table_read_past_its_timeout_ends_the_seek_for_time(self, monkeypatch) -> None:
        self.segments = trailseek.SeekOutOfTime("slow")
        world, shape, info = self.run(monkeypatch, {}, [])
        assert info["seek"]["limited"] == "time" and world.requests == [] and shape == "o"

    def test_a_corridor_search_that_fails_is_reported_and_the_route_kept(self, monkeypatch) -> None:
        def broken(*args, **kw):
            raise trailseek.SeekError("a step of no cost")

        monkeypatch.setattr(trailseek, "find_corridors", broken)
        world, shape, info = self.run(monkeypatch, {}, [])
        assert info["seek"]["limited"] == "error" and world.requests == [] and shape == "o"

    def test_a_corridor_search_past_its_time_ends_the_seek(self, monkeypatch) -> None:
        def slow(*args, **kw):
            raise trailseek.SeekOutOfTime("slow")

        monkeypatch.setattr(trailseek, "find_corridors", slow)
        world, _shape, info = self.run(monkeypatch, {}, [])
        assert info["seek"]["limited"] == "time" and world.requests == []

    def test_the_corridor_search_is_held_to_the_time_a_candidate_needs(self, monkeypatch) -> None:
        seen: list = []
        real = trailseek.find_corridors

        def spy(*args, **kw):
            seen.append((routing.clock(), kw))
            return real(*args, **kw)

        monkeypatch.setattr(trailseek, "find_corridors", spy)
        world, _shape, _info = self.run(monkeypatch, {}, [NO_ROUTE])
        ((now, kw),) = seen
        assert kw["clock"] is routing.clock
        # The leg's stop (6 s on) less a candidate's least.
        assert kw["stop_at"] - now == pytest.approx(
            trailseek.SEEK_BUDGET_S - trailseek.SEEK_ROUND_MIN_S, abs=0.3
        )

    def test_no_corridor_search_once_a_slow_table_read_has_used_the_time(self, monkeypatch) -> None:
        now = [routing.clock()]
        monkeypatch.setattr(routing, "clock", lambda: now[0])
        segments = trail_segments()

        def slow_table(*args, **kw):
            now[0] += trailseek.SEEK_BUDGET_S - trailseek.SEEK_ROUND_MIN_S + 0.1
            return segments

        monkeypatch.setattr(trailseek, "corridor_segments", slow_table)
        searched: list = []
        monkeypatch.setattr(trailseek, "find_corridors", lambda *a, **k: searched.append(1) or [])
        world, _shape, info = self.run(monkeypatch, {}, [])
        assert info["seek"]["limited"] == "time" and searched == [] and world.requests == []

    def test_only_the_kept_exclusions_in_the_legs_band_are_sent(self, monkeypatch) -> None:
        near = (BASE[0] + 0.03, BASE[1] + 200 / KY)
        far = (BASE[0] + 0.03, BASE[1] + 9000 / KY)
        ctx = self.seek_context()
        ctx.kept_excludes = [near, far]
        calm = analysis("t", "1" * 45, cost_s=3000.0, shift=100)
        world, shape, info = self.run(monkeypatch, {"t": calm}, [trip_of("t", 4.5)], ctx)
        (request,) = world.requests
        assert [(p["lon"], p["lat"]) for p in request["exclude_locations"]] == [near]
        assert info["seek"]["tried"][0]["excluded"] == 1 and shape == "t"

    def test_a_much_longer_answer_under_the_exclusions_is_asked_again_without(
        self, monkeypatch
    ) -> None:
        ctx = self.seek_context()
        ctx.kept_excludes = [(BASE[0] + 0.03, BASE[1] + 200 / KY)]
        # 20 km for a 4 km route and a corridor of a few hundred metres' detour.
        long = analysis("long", "1" * 200, cost_s=9000.0, shift=100)
        calm = analysis("t", "1" * 45, cost_s=3000.0, shift=100)
        world, shape, info = self.run(
            monkeypatch,
            {"long": long, "t": calm},
            [trip_of("long", 20.0), trip_of("t", 4.5)],
            ctx,
        )
        first, second = world.requests
        assert "exclude_locations" in first and "exclude_locations" not in second
        assert first["locations"][1:3] == second["locations"][1:3]
        assert [(t["excluded"], t["outcome"], t.get("retry")) for t in info["seek"]["tried"]] == [
            (1, "not_better", None),
            (0, "taken", "longer"),
        ]
        assert shape == "t" and info["seek"]["asked"] == 1
        # One proposal, two routes (review r2).
        assert info["seek"]["routes"] == 2

    def test_an_answer_not_much_longer_is_not_asked_again(self, monkeypatch) -> None:
        ctx = self.seek_context()
        ctx.kept_excludes = [(BASE[0] + 0.03, BASE[1] + 200 / KY)]
        # 5 km: under 1.15 x (4 km and the corridor's detour) and 500 m.
        longer = analysis("t", "1" * 50, cost_s=3000.0, shift=100)
        world, shape, info = self.run(monkeypatch, {"t": longer}, [trip_of("t", 5.0)], ctx)
        assert len(world.requests) == 1 and shape == "t"
        assert refine.SEEK_RETRY_OVER == 0.15 and refine.SEEK_RETRY_SLACK_M == 500.0

    def test_the_length_expected_includes_the_corridors_detour(self, monkeypatch) -> None:
        # Review r2, mutant V19: a corridor said to add 2 km is expected at up to
        # 1.15 x (4 km + 2 km) + 500 m = 7.4 km, so a 6 km answer is not asked
        # again (without the detour it would be past 5.1 km).
        incumbent = self.orig()
        long_way = trailseek.Proposal(
            (
                trailseek.Corridor(
                    entry=BASE,
                    exit=BASE,
                    trail_m=1000.0,
                    gain_m=1000.0,
                    detour_m=2000.0,
                    score=0.0,
                    t_in=0.0,
                    t_out=1000.0,
                ),
            )
        )
        assert refine._expected_m(incumbent, long_way) == pytest.approx(
            (4000.0 + 2000.0) * 1.15 + 500.0
        )
        real = trailseek.propose

        def detoured(corridors, *args, **kw):
            return [
                trailseek.Proposal(
                    tuple(dataclasses.replace(c, detour_m=2000.0) for c in p.corridors)
                )
                for p in real(corridors, *args, **kw)
            ]

        monkeypatch.setattr(trailseek, "propose", detoured)
        ctx = self.seek_context()
        ctx.kept_excludes = [(BASE[0] + 0.03, BASE[1] + 200 / KY)]
        six_km = analysis("t", "1" * 60, cost_s=3000.0, shift=100)
        world, shape, info = self.run(monkeypatch, {"t": six_km}, [trip_of("t", 6.0)], ctx)
        assert len(world.requests) == 1 and shape == "t"
        assert info["seek"]["routes"] == 1 and info["seek"]["tried"][0]["detour_m"] == 2000

    def test_the_retry_is_not_started_without_the_time(self, monkeypatch) -> None:
        now = [routing.clock()]
        monkeypatch.setattr(routing, "clock", lambda: now[0])
        ctx = self.seek_context()
        ctx.kept_excludes = [(BASE[0] + 0.03, BASE[1] + 200 / KY)]
        long = analysis("long", "1" * 200, cost_s=9000.0, shift=100)
        world = SeekWorld(
            monkeypatch, {"o": self.orig(), "long": long}, [NO_ROUTE, trip_of("long", 20.0)]
        )
        real_call = world.call

        def call(variant, endpoint, payload, deadline):
            answer = real_call(variant, endpoint, payload, deadline)
            if asks_through(payload):
                now[0] += trailseek.SEEK_BUDGET_S - trailseek.SEEK_ROUND_MIN_S + 0.5
            return answer

        monkeypatch.setattr(routing, "_call", call)
        _kept, info = refine.refine(trip_of("o", 4.0), ctx)
        assert [r for r in world.requests if asks_through(r)][1:] == []
        assert [t["outcome"] for t in info["seek"]["tried"]] == ["not_better"]


class TestExposureSpans:
    def test_each_busy_piece_is_a_span_weighted_by_its_tier(self) -> None:
        a = analysis("a", "1334155")
        spans, traced = refine.exposure_spans(a)
        assert traced == 700.0
        assert spans == [
            (100.0, 200.0, 1.0),
            (200.0, 300.0, 1.0),
            (300.0, 400.0, 2.0),
            (500.0, 600.0, 3.0),
            (600.0, 700.0, 3.0),
        ]

    def test_a_route_with_no_pieces_has_no_length(self) -> None:
        a = analysis("a", "1")
        a.pieces, a.classes = [], []
        assert refine.exposure_spans(a) == ([], None)


class TestSeekRuns:
    def test_the_plan_runs_it_from_the_top_of_the_old_slider(self) -> None:
        assert trailseek.seek_for(presets.calm_rate_for(100))
        assert not trailseek.seek_for(presets.calm_rate_for(99))
        assert not trailseek.seek_for(presets.calm_rate_for(80))


class TestTrailCreditScore:
    """OWNER-DECISIONS 202, "Trail bonus for Trailmaxxing only": each metre of
    trail takes the credit, in metres of quiet riding, off the route's score."""

    def test_a_metre_of_trail_takes_the_credit_off_the_score(self) -> None:
        a = analysis("a", "1" * 10, cost_s=1000.0, trails="t" * 4)
        assert a.trail_m == 400.0
        assert a.score(context(trail_credit=0.5)) == pytest.approx(
            1000.0 - QUIET_COST * 0.5 * 400.0
        )
        assert a.score(context()) == 1000.0

    def test_it_is_in_the_same_units_as_the_rest_of_the_extra_price(self) -> None:
        a = analysis(
            "a", "1133", cost_s=1000.0, events=[event(0, 1000.0)], climb_m=10.0, trails="tt"
        )
        ctx = context(rate=2.0, weight=0.5, climb_weight=3.0, trail_credit=0.75)
        penalty_m = 1000.0 / model.FEET_PER_METRE
        extra = 2.0 * a.exposure_m + 0.5 * penalty_m + 3.0 * 10.0 - 0.75 * 200.0
        assert a.score(ctx) == pytest.approx(1000.0 + QUIET_COST * extra)

    def test_a_route_with_no_trail_pays_no_credit(self) -> None:
        a = analysis("a", "1" * 10, cost_s=1000.0)
        assert a.trail_m == 0.0 and a.score(context(trail_credit=0.9)) == 1000.0

    def test_trail_is_a_path_or_protected_way_at_lts_1_or_2(self) -> None:
        pieces = [routing.Piece(1, 0.0, 0.0, 100.0)] * 8
        classes = [
            ("1", "path"),
            ("2", "protected"),
            ("1", "lane"),
            ("3", "path"),
            ("1", "none"),
            ("unknown", "path"),
            ("2", "path"),
            ("1", "unknown"),
        ]
        ctx = context()
        ctx.with_facility = True
        flags = refine.trail_flags(pieces, classes, ctx)
        assert flags == [True, True, False, False, False, False, True, False]
        assert refine.TRAIL_KINDS == {"path", "protected"} and refine.TRAIL_TIERS == {"1", "2"}

    def test_before_the_facility_column_the_recorded_rule_says_it(self, monkeypatch) -> None:
        from pipeline.schema import PATH_RULES, SIDEPATH_RULES

        path, sidepath = sorted(PATH_RULES)[0], sorted(SIDEPATH_RULES)[0]
        rows = [(1, path), (2, "residential"), (3, path), (1, None), (2, sidepath)]
        ran: list = []

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, params):
                ran.append((sql, params))

            def fetchall(self):
                return rows

        class Connection:
            def cursor(self):
                return Cursor()

        monkeypatch.setattr(refine, "connection", Connection())
        ctx = context()
        ctx.with_facility = False
        ctx.schema = "live"
        pieces = [routing.Piece(i + 1, float(i), 2.0, 10.0) for i in range(5)]
        assert refine.trail_flags(pieces, [], ctx) == [True, False, False, False, True]
        ((sql, params),) = ran
        assert "live.segment" in sql and "stress_rule" in sql and "stress_tier" in sql
        assert params == [[1, 2, 3, 4, 5], [0.0, 1.0, 2.0, 3.0, 4.0], [2.0] * 5]

    def read(self, monkeypatch, classes, credit):
        """The real `analyse`, with the router, the table and the junctions replaced."""
        pieces = [routing.Piece(1, BASE[0] + i * 1e-4, BASE[1], 100.0) for i in range(len(classes))]
        monkeypatch.setattr(routing, "_trace", lambda *a, **k: {"shape": "x"})
        monkeypatch.setattr(routing, "pieces_of_trace", lambda trace: pieces)
        monkeypatch.setattr(
            routing, "decode_polyline6", lambda s: [BASE, (BASE[0] + 0.01, BASE[1])]
        )
        monkeypatch.setattr(routing, "classify", lambda p, when, roadway_only=False: classes)
        monkeypatch.setattr(refine.trace_junctions, "junctions_of_trace", lambda *a: [])
        monkeypatch.setattr(refine.trace_junctions, "edge_midpoints", lambda *a: [])
        monkeypatch.setattr(refine, "events_of_raws", lambda raws, ctx, deadline: [])
        ctx = context(trail_credit=credit)
        ctx.with_facility = True
        trip = {"legs": [{"shape": "x"}], "summary": {"length": 0.4, "time": 100.0, "cost": 100.0}}
        return refine.analyse(trip, ctx, ctx.deadline)

    def test_the_reading_counts_the_trail_when_there_is_a_credit(self, monkeypatch) -> None:
        classes = [("1", "path"), ("1", "none"), ("2", "protected"), ("3", "none")]
        read = self.read(monkeypatch, classes, 0.5)
        assert read.trail_m == 200.0 and read.trail_pieces == [True, False, True, False]

    def test_without_a_credit_the_trail_is_not_looked_for(self, monkeypatch) -> None:
        def never(*args):
            raise AssertionError("the trail was looked for with no credit")

        monkeypatch.setattr(refine, "trail_flags", never)
        classes = [("1", "path"), ("1", "none")]
        read = self.read(monkeypatch, classes, 0.0)
        assert read.trail_m == 0.0 and read.trail_pieces == []


class TestTrailCreditSeek:
    """The seek's corridors count the credit, so a route with nothing busy to
    replace still finds a trail (the W&OD, Capital Crescent, Anacostia and Sligo
    trips, where the seek asked nothing before), and the Traffic-wins guard still
    holds: the credit never buys more LTS 3 or 4."""

    @pytest.fixture(autouse=True)
    def trails(self, monkeypatch):
        self.segments = trail_segments()

        def table(schema, guide, width_m, has_facility, when, avoid_unpaved=False, **kw):
            return self.segments

        monkeypatch.setattr(trailseek, "corridor_segments", table)
        route = [(BASE[0] + i * 0.01, BASE[1]) for i in range(11)]
        monkeypatch.setattr(routing, "decode_polyline6", lambda shape: route)

    seek_context = TestTrailSeek.seek_context

    def run(self, monkeypatch, analyses, routes, credit=0.5, orig=None):
        quiet = orig or analysis("o", "1" * 40, cost_s=4000.0)
        world = SeekWorld(monkeypatch, {"o": quiet, **analyses}, routes)
        ctx = self.seek_context()
        ctx.trail_credit = credit
        kept, info = refine.refine(trip_of("o", 4.0), ctx)
        return world, kept["legs"][0]["shape"], info

    def test_a_quiet_route_asks_for_a_trail_with_a_credit_and_not_without(
        self, monkeypatch
    ) -> None:
        trail = analysis("t", "1" * 45, cost_s=4300.0, trails="t" * 30)
        world, shape, info = self.run(monkeypatch, {"t": trail}, [trip_of("t", 4.5)], credit=0.0)
        assert world.requests == [] and shape == "o" and info["seek"]["corridors"] == 0
        world, shape, info = self.run(monkeypatch, {"t": trail}, [trip_of("t", 4.5)])
        (request,) = world.requests
        assert [p.get("type") for p in request["locations"]] == [None, "through", "through", None]
        assert info["seek"]["corridors"] == 1 and info["seek"]["asked"] == 1

    def test_the_trail_is_taken_where_the_credit_pays_for_the_extra_cost(self, monkeypatch) -> None:
        # 3,000 m of trail at a credit of 0.5 and a quiet cost of 0.5 is 750 s.
        for extra, outcome in ((500.0, "taken"), (800.0, "not_better")):
            trail = analysis("t", "1" * 45, cost_s=4000.0 + extra, trails="t" * 30)
            _w, shape, info = self.run(monkeypatch, {"t": trail}, [trip_of("t", 4.5)])
            (tried,) = info["seek"]["tried"]
            assert tried["outcome"] == outcome and shape == ("t" if outcome == "taken" else "o")
            assert tried["score_gain_s"] == pytest.approx(750.0 - extra, abs=0.5)

    def test_a_bigger_credit_takes_a_dearer_trail(self, monkeypatch) -> None:
        trail = analysis("t", "1" * 45, cost_s=4000.0 + 500.0, trails="t" * 30)
        for credit, outcome in ((0.25, "not_better"), (0.5, "taken")):
            _w, _shape, info = self.run(
                monkeypatch, {"t": trail}, [trip_of("t", 4.5)], credit=credit
            )
            assert info["seek"]["tried"][0]["outcome"] == outcome

    def test_the_credit_never_buys_more_busy_road(self, monkeypatch) -> None:
        # Far cheaper and mostly trail, but with 400 m of LTS 3 the route did not have.
        busy = analysis("t", "1" * 36 + "3" * 4, cost_s=1000.0, trails="t" * 30)
        _w, shape, info = self.run(monkeypatch, {"t": busy}, [trip_of("t", 4.0)], credit=0.9)
        assert shape == "o"
        assert info["seek"]["tried"][0]["outcome"] == "busier"
        assert info["seek"]["tried"][0]["score_gain_s"] > 0

    def test_a_trailier_route_with_no_more_busy_road_than_the_slack_allows_is_taken(
        self, monkeypatch
    ) -> None:
        ok = analysis("t", "1" * 45, cost_s=3000.0, trails="t" * 30)
        ok.exposure_m = refine.EXPOSURE_SLACK_M
        _w, shape, _info = self.run(monkeypatch, {"t": ok}, [trip_of("t", 4.5)])
        assert shape == "t"

    def test_a_route_that_is_all_trail_has_nothing_to_gain(self, monkeypatch) -> None:
        riding = analysis("o", "1" * 40, cost_s=4000.0, trails="t" * 40)
        world, shape, info = self.run(monkeypatch, {}, [], orig=riding)
        assert world.requests == [] and shape == "o" and info["seek"]["corridors"] == 0

    def test_the_trail_is_reported_before_and_after(self, monkeypatch) -> None:
        start = analysis("o", "1" * 40, cost_s=4000.0, trails="t" * 10)
        trail = analysis("t", "1" * 45, cost_s=3000.0, trails="t" * 30)
        _w, shape, info = self.run(monkeypatch, {"t": trail}, [trip_of("t", 4.5)], orig=start)
        assert shape == "t"
        assert info["trail_credit"] == 0.5
        assert (info["trail_before_m"], info["trail_after_m"]) == (1000.0, 3000.0)

    def test_a_plan_with_no_credit_reports_none(self, monkeypatch) -> None:
        _w, _shape, info = self.run(monkeypatch, {}, [], credit=0.0)
        assert not {"trail_credit", "trail_before_m", "trail_after_m"} & set(info)

    def test_the_corridor_search_is_given_the_routes_trail_and_the_credit(
        self, monkeypatch
    ) -> None:
        seen: list = []
        real = trailseek.find_corridors

        def spy(*args, **kw):
            seen.append(args)
            return real(*args, **kw)

        monkeypatch.setattr(trailseek, "find_corridors", spy)
        # The router has no route for the exclusion round; the seek's follows.
        start = analysis("o", "1" * 10 + "3" * 10 + "1" * 20, cost_s=4000.0, trails="t" * 5)
        world = SeekWorld(monkeypatch, {"o": start}, [NO_ROUTE, NO_ROUTE])
        ctx = self.seek_context()
        ctx.trail_credit = 0.5
        refine.refine(trip_of("o", 4.0), ctx)
        (args,) = seen
        spans, traced, rate, credit, trail_spans = args[4], args[5], args[6], args[7], args[8]
        assert (spans[0][0], spans[-1][1], len(spans)) == (1000.0, 2000.0, 10) and traced == 4000.0
        assert (rate, credit) == (10.0, 0.5)
        assert (trail_spans[0][0], trail_spans[-1][1], len(trail_spans)) == (0.0, 500.0, 5)
        assert world.requests


class TestTheSearchWithTheCredit:
    def test_the_credit_does_not_buy_busy_road_in_the_exclusion_search_either(
        self, monkeypatch
    ) -> None:
        orig = analysis("o", "1" * 30 + "3" * 10, cost_s=4000.0)
        cheap = analysis("c", "1" * 20 + "4" * 10 + "1" * 10, cost_s=100.0, trails="t" * 20)
        world = World(monkeypatch, {"o": orig, "c": cheap}, [trip_of("c", 4.0)] * 3)
        ctx = context(rate=2.0, trail_credit=0.9)
        kept, info = refine.refine(trip_of("o", 4.0), ctx)
        assert kept["legs"][0]["shape"] == "o" and world.requests
        assert info["trail_credit"] == 0.9

    def test_the_credit_can_pick_the_trailier_of_two_candidates(self, monkeypatch) -> None:
        # The first round's route has a little busy road; the second's is quiet,
        # dearer and mostly trail. Only a credit makes the second better.
        orig = analysis("o", "1" * 15 + "3" * 10 + "1" * 15, cost_s=4000.0)
        first = analysis("a", "1" * 28 + "3" * 3 + "1" * 9, cost_s=3000.0)
        second = analysis("b", "1" * 40, cost_s=3300.0, trails="t" * 30)
        for credit, expected in ((0.0, "a"), (0.5, "b")):
            World(
                monkeypatch,
                {"o": orig, "a": first, "b": second},
                [trip_of("a", 4.0), trip_of("b", 4.0)],
            )
            kept, _info = refine.refine(trip_of("o", 4.0), context(rate=0.1, trail_credit=credit))
            assert kept["legs"][0]["shape"] == expected, credit


def leg_of(name: str, km: float = 8.7, cost: float = 4000.0) -> dict:
    return {"shape": name, "summary": {"length": km, "time": 100.0 * km, "cost": cost}}


def one_leg(name: str, km: float = 8.7, cost: float = 4000.0) -> dict:
    """A route of one leg: what the router answers a leg asked for alone."""
    return {
        "legs": [leg_of(name, km, cost)],
        "summary": {"length": km, "time": 100 * km, "cost": cost},
    }


def multi_trip(names: list[str], km: float = 8.7, cost: float = 4000.0) -> dict:
    return {
        "legs": [leg_of(name, km, cost) for name in names],
        "summary": {
            "length": km * len(names),
            "time": 100.0 * km * len(names),
            "cost": cost * len(names),
            "min_lat": 38.0,
        },
    }


def leg_number(shape: str) -> int:
    """Which leg a shape name belongs to: "o1", "t1" are the first leg's."""
    return int(shape[-1]) - 1


class LegWorld(SeekWorld):
    """A SeekWorld whose readings are by the legs' shapes, joined with "+"."""

    def __init__(self, monkeypatch, analyses: dict, routes: list) -> None:
        super().__init__(monkeypatch, analyses, routes)
        self.read: list[str] = []

        def read(trip, ctx, deadline):
            key = "+".join(leg["shape"] for leg in trip["legs"])
            self.read.append(key)
            return self.analyses[key]

        monkeypatch.setattr(refine, "analyse", read)

    def asked(self) -> list[dict]:
        return [r for r in self.requests if asks_through(r)]


def leg_orig(number: int, **kw) -> refine.Analysis:
    """A leg as the router gave it: 1,000 m of LTS 3 in 4,000."""
    return analysis(f"o{number}", "1" * 10 + "3" * 10 + "1" * 20, cost_s=4000.0, **kw)


def whole_of(*legs: refine.Analysis, **kw) -> refine.Analysis:
    """The whole route's reading, from its legs'."""
    tiers = "".join("1" * 10 + "3" * 10 + "1" * 20 for _ in legs)
    whole = analysis(
        "+".join(a_name(i) for i in range(len(legs))), tiers, cost_s=4000.0 * len(legs)
    )
    whole.via_m = [4000.0 * (i + 1) for i in range(len(legs) - 1)]
    for key, value in kw.items():
        setattr(whole, key, value)
    return whole


def a_name(i: int) -> str:
    return f"o{i + 1}"


class TestSeekLegByLeg:
    """OWNER-DECISIONS 203, "Now, before rebuild": the seek runs leg by leg on
    plans with stops: each stretch between consecutive locations is asked for
    alone, its own corridors, its own guard, its share of the budget."""

    @pytest.fixture(autouse=True)
    def trails(self, monkeypatch):
        self.tables: list[int] = []
        self.none_for: set[int] = set()

        def table(schema, guide, width_m, has_facility, when, avoid_unpaved=False, **kw):
            number = round((guide[0][0][0] - BASE[0]) / 0.1)
            self.tables.append(number)
            if number in self.none_for:
                return []
            return trail_segments(0.01 + 0.1 * number, 0.09 + 0.1 * number)

        monkeypatch.setattr(trailseek, "corridor_segments", table)

        def line_of(shape):
            number = leg_number(shape) if shape[-1].isdigit() else 0
            return [(BASE[0] + 0.1 * number + i * 0.01, BASE[1]) for i in range(11)]

        monkeypatch.setattr(routing, "decode_polyline6", line_of)

    def leg_context(self, legs=2, step=0.1, deadline_s=40.0) -> refine.Context:
        ctx = context(rate=10.0)
        ctx.points = [[BASE[0] + step * i, BASE[1]] for i in range(legs + 1)]
        ctx.request["locations"] = [{"lon": lon, "lat": lat} for lon, lat in ctx.points]
        ctx.deadline = routing.Deadline(routing.clock() + deadline_s, 35)
        ctx.seek = True
        ctx.schema = "live"
        ctx.with_facility = True
        ctx.when = "weekend"
        return ctx

    def plan(self, monkeypatch, analyses, routes, legs=2, ctx=None):
        """The plan's refine on `legs` legs: the exclusion round has no route, so
        what follows is the seek's."""
        names = [f"o{i + 1}" for i in range(legs)]
        base = {name: leg_orig(i + 1) for i, name in enumerate(names)}
        base["+".join(names)] = whole_of(*base.values())
        world = LegWorld(monkeypatch, {**base, **analyses}, [NO_ROUTE, *routes])
        kept, info = refine.refine(multi_trip(names), ctx or self.leg_context(legs))
        return world, kept, info

    def calm(self, number: int, **kw) -> refine.Analysis:
        return analysis(f"t{number}", "1" * 40, cost_s=3000.0, **kw)

    def test_each_leg_is_asked_for_alone_between_its_own_locations(self, monkeypatch) -> None:
        analyses = {
            "t1": self.calm(1),
            "t2": self.calm(2),
            "t1+o2": whole_of(leg_orig(1), leg_orig(2)),
            "t1+t2": whole_of(leg_orig(1), leg_orig(2)),
        }
        routes = [one_leg("t1", 9.0, 3000.0), one_leg("t2", 9.0, 3000.0)]
        world, kept, info = self.plan(monkeypatch, analyses, routes)
        first, second = world.asked()
        ctx = self.leg_context()
        assert [len(r["locations"]) for r in (first, second)] == [4, 4]
        assert (first["locations"][0], first["locations"][-1]) == (
            ctx.request["locations"][0],
            ctx.request["locations"][1],
        )
        assert (second["locations"][0], second["locations"][-1]) == (
            ctx.request["locations"][1],
            ctx.request["locations"][2],
        )
        assert [p["type"] for p in first["locations"][1:3]] == ["through", "through"]
        lons = [p["lon"] for p in second["locations"][1:3]]
        assert all(BASE[0] + 0.1 < lon < BASE[0] + 0.2 for lon in lons)
        assert self.tables == [0, 1]
        seek = info["seek"]
        assert (seek["legs"], seek["corridors"], seek["asked"], seek["taken"]) == (2, 2, 2, True)
        assert [(t["leg"], t["outcome"]) for t in seek["tried"]] == [(0, "taken"), (1, "taken")]
        assert seek["limited"] is None

    def test_a_leg_taken_is_spliced_into_the_trip_and_its_summary(self, monkeypatch) -> None:
        analyses = {
            "t1": self.calm(1),
            "t2": self.calm(2),
            "t1+o2": whole_of(leg_orig(1), leg_orig(2)),
            "t1+t2": whole_of(leg_orig(1), leg_orig(2)),
        }
        routes = [one_leg("t1", 9.0, 3000.0), one_leg("t2", 9.5, 3500.0)]
        world, kept, _info = self.plan(monkeypatch, analyses, routes)
        assert [leg["shape"] for leg in kept["legs"]] == ["t1", "t2"]
        summary = kept["summary"]
        assert summary["length"] == pytest.approx(8.7 * 2 - 8.7 + 9.0 - 8.7 + 9.5)
        assert summary["time"] == pytest.approx(100.0 * (9.0 + 9.5))
        assert summary["cost"] == pytest.approx(3000.0 + 3500.0)
        assert summary["min_lat"] == 38.0
        # One reading of the whole trip, last, for the answer to reuse.
        assert world.read[-1] == "t1+t2"

    def test_a_leg_with_nothing_to_find_is_left_as_it_was(self, monkeypatch) -> None:
        self.none_for = {0}
        analyses = {
            "t2": self.calm(2),
            "o1+t2": whole_of(leg_orig(1), leg_orig(2)),
        }
        world, kept, info = self.plan(monkeypatch, analyses, [one_leg("t2", 9.0, 3000.0)])
        assert [leg["shape"] for leg in kept["legs"]] == ["o1", "t2"]
        assert len(world.asked()) == 1 and info["seek"]["tried"][0]["leg"] == 1
        assert info["seek"]["corridors"] == 1

    def test_a_leg_kept_as_it_was_leaves_the_trip_untouched(self, monkeypatch) -> None:
        worse = analysis("t1", "1" * 40, cost_s=9000.0)
        world, kept, info = self.plan(monkeypatch, {"t1": worse, "t2": worse}, [one_leg("t1")] * 2)
        assert [leg["shape"] for leg in kept["legs"]] == ["o1", "o2"]
        assert info["seek"]["taken"] is False
        assert {t["outcome"] for t in info["seek"]["tried"]} == {"not_better"}
        # No whole reading but the first: nothing was spliced.
        assert world.read.count("o1+o2") == 1 and "t1+o2" not in world.read

    def test_the_guard_is_against_each_legs_own_exposure(self, monkeypatch) -> None:
        # 75 m over the leg's 1,000 m is past its allowance (2% and 50 m), though
        # 75 m over the whole trip's 2,000 m is well inside it.
        busier = self.calm(1)
        busier.exposure_m = 1075.0
        analyses = {
            "t1": busier,
            "t2": self.calm(2),
            "o1+t2": whole_of(leg_orig(1), leg_orig(2)),
        }
        routes = [one_leg("t1", 9.0, 3000.0), one_leg("t2", 9.0, 3000.0)]
        _w, kept, info = self.plan(monkeypatch, analyses, routes)
        assert [(t["leg"], t["outcome"]) for t in info["seek"]["tried"]] == [
            (0, "busier"),
            (1, "taken"),
        ]
        assert [leg["shape"] for leg in kept["legs"]] == ["o1", "t2"]

    def test_a_leg_may_not_trade_exposure_with_another(self, monkeypatch) -> None:
        # The first leg was cleaned up by the search; the second may not take what
        # the first saved.
        analyses = {"t1": self.calm(1), "t2": self.calm(2)}
        busier = self.calm(2)
        busier.exposure_m = 1500.0
        analyses["t2"] = busier
        analyses["t1+o2"] = whole_of(leg_orig(1), leg_orig(2))
        routes = [one_leg("t1", 9.0, 3000.0), one_leg("t2", 9.0, 100.0)]
        _w, kept, info = self.plan(monkeypatch, analyses, routes)
        assert [t["outcome"] for t in info["seek"]["tried"]] == ["taken", "busier"]
        assert [leg["shape"] for leg in kept["legs"]] == ["t1", "o2"]

    def test_the_budget_is_shared_by_span_with_at_least_a_candidates_worth(
        self, monkeypatch
    ) -> None:
        # Four legs at 6 s: a quarter is 1.5 s and a third of what is left 2 s, each
        # under the least a leg is given; then a half, and the last takes the rest
        # (no time passes here).
        analyses = {f"t{i}": analysis(f"t{i}", "1" * 40, cost_s=9000.0) for i in range(1, 5)}
        routes = [one_leg(f"t{i}") for i in range(1, 5)]
        world, _kept, info = self.plan(
            monkeypatch, analyses, routes, legs=4, ctx=self.leg_context(4)
        )
        least = trailseek.SEEK_LEG_MIN_S
        assert world.deadlines == pytest.approx([least, least, 3.0, 6.0], abs=0.4)
        assert info["seek"]["asked"] == 4 and info["seek"]["limited"] is None

    def test_a_longer_leg_gets_a_bigger_share(self, monkeypatch) -> None:
        # Legs of 8.7 and 17.4 km: a third of 6 s is 2 s (the floor gives 2.5 s), not
        # the half that sharing by count would give.
        ctx = self.leg_context(2)
        ctx.points[2] = [BASE[0] + 0.3, BASE[1]]
        ctx.request["locations"][2] = {"lon": BASE[0] + 0.3, "lat": BASE[1]}
        worse = {f"t{i}": analysis(f"t{i}", "1" * 40, cost_s=9000.0) for i in (1, 2)}
        world, _kept, _info = self.plan(monkeypatch, worse, [one_leg("t1"), one_leg("t2")], ctx=ctx)
        assert world.deadlines[0] == pytest.approx(trailseek.SEEK_LEG_MIN_S, abs=0.2)
        assert world.deadlines[1] == pytest.approx(trailseek.SEEK_BUDGET_S, abs=0.5)

    def test_a_leg_with_no_room_is_skipped_and_the_rest_share_the_budget(self, monkeypatch) -> None:
        # The second leg is 0.87 km: too short for a corridor, and not counted.
        ctx = self.leg_context(2)
        ctx.points[2] = [BASE[0] + 0.11, BASE[1]]
        ctx.request["locations"][2] = {"lon": BASE[0] + 0.11, "lat": BASE[1]}
        analyses = {"t1": self.calm(1), "t1+o2": whole_of(leg_orig(1), leg_orig(2))}
        world, _kept, info = self.plan(monkeypatch, analyses, [one_leg("t1", 9.0, 3000.0)], ctx=ctx)
        assert self.tables == [0]
        assert world.deadlines[0] == pytest.approx(trailseek.SEEK_BUDGET_S, abs=0.5)
        assert info["seek"]["legs"] == 2 and info["seek"]["asked"] == 1

    def test_no_leg_with_room_is_a_span_limit(self, monkeypatch) -> None:
        ctx = self.leg_context(2, step=0.01)
        world, _kept, info = self.plan(monkeypatch, {}, [], ctx=ctx)
        assert info["seek"]["limited"] == "span" and world.asked() == [] and self.tables == []

    def test_the_time_running_out_ends_the_seek_for_every_leg(self, monkeypatch) -> None:
        ran_out = routing.DeadlineExceeded("out of time")
        world, kept, info = self.plan(monkeypatch, {}, [ran_out])
        assert info["seek"]["limited"] == "time" and len(world.asked()) == 1
        assert self.tables == [0] and [leg["shape"] for leg in kept["legs"]] == ["o1", "o2"]

    def test_a_table_that_cannot_be_read_ends_the_seek_for_every_leg(self, monkeypatch) -> None:
        def broken(*args, **kw):
            raise RuntimeError("the database is down")

        monkeypatch.setattr(trailseek, "corridor_segments", broken)
        world, kept, info = self.plan(monkeypatch, {}, [])
        assert info["seek"]["limited"] == "table" and world.asked() == []
        assert [leg["shape"] for leg in kept["legs"]] == ["o1", "o2"]

    def test_a_whole_route_that_cannot_be_read_after_the_splice_is_not_taken(
        self, monkeypatch
    ) -> None:
        unread = whole_of(leg_orig(1), leg_orig(2), events=None)
        analyses = {"t1": self.calm(1), "t1+t2": unread, "t2": self.calm(2)}
        routes = [one_leg("t1", 9.0, 3000.0), one_leg("t2", 9.0, 3000.0)]
        world, kept, info = self.plan(monkeypatch, analyses, routes)
        assert [leg["shape"] for leg in kept["legs"]] == ["o1", "o2"]
        assert info["seek"]["taken"] is False and info["seek"]["limited"] == "unread"
        assert kept["summary"]["length"] == pytest.approx(17.4)

    def test_a_whole_route_the_router_cannot_be_asked_for_is_not_taken(self, monkeypatch) -> None:
        analyses = {"t1": self.calm(1), "t2": self.calm(2)}
        routes = [one_leg("t1", 9.0, 3000.0), one_leg("t2", 9.0, 3000.0)]
        world = LegWorld(
            monkeypatch,
            {
                "o1": leg_orig(1),
                "o2": leg_orig(2),
                "o1+o2": whole_of(leg_orig(1), leg_orig(2)),
                **analyses,
            },
            [NO_ROUTE, *routes],
        )
        real = refine.analyse

        def failing(trip, ctx, deadline):
            if [leg["shape"] for leg in trip["legs"]][:1] == ["t1"] and len(trip["legs"]) == 2:
                raise routing.RouterUnavailable("down")
            return real(trip, ctx, deadline)

        monkeypatch.setattr(refine, "analyse", failing)
        kept, info = refine.refine(multi_trip(["o1", "o2"]), self.leg_context())
        assert [leg["shape"] for leg in kept["legs"]] == ["o1", "o2"]
        assert info["seek"]["taken"] is False and world.asked()

    def test_each_leg_is_scored_against_the_leg_the_trip_has(self, monkeypatch) -> None:
        # The first leg's candidate is better than the original and taken; the
        # second is compared with the second leg's own reading, not the first's.
        cheaper = analysis("t2", "1" * 40, cost_s=3990.0)
        analyses = {
            "t1": self.calm(1),
            "t2": cheaper,
            "t1+o2": whole_of(leg_orig(1), leg_orig(2)),
            "t1+t2": whole_of(leg_orig(1), leg_orig(2)),
        }
        routes = [one_leg("t1", 9.0, 3000.0), one_leg("t2", 9.0, 3990.0)]
        _w, kept, info = self.plan(monkeypatch, analyses, routes)
        # 10 s is the least gain: this second candidate is quieter but gains the
        # 1,000 m of exposure at the rate, which is far more.
        assert [t["outcome"] for t in info["seek"]["tried"]] == ["taken", "taken"]
        assert info["seek"]["tried"][1]["score_gain_s"] == pytest.approx(
            10.0 + QUIET_COST * 10.0 * 1000.0, abs=1.0
        )
        assert [leg["shape"] for leg in kept["legs"]] == ["t1", "t2"]

    def test_the_trip_must_have_a_leg_for_each_stretch(self, monkeypatch) -> None:
        ctx = self.leg_context(3)
        world = LegWorld(monkeypatch, {"o1+o2": whole_of(leg_orig(1), leg_orig(2))}, [NO_ROUTE])
        _kept, info = refine.refine(multi_trip(["o1", "o2"]), ctx)
        assert info["seek"]["limited"] == "points" and world.asked() == []

    def test_a_first_reading_without_its_legs_falls_back_to_the_legs_own(self, monkeypatch) -> None:
        # Where the trip's first reading does not say where its legs run, the guard
        # reference is the leg's own exposure when the seek started.
        busier = self.calm(1)
        busier.exposure_m = 1075.0
        whole = whole_of(leg_orig(1), leg_orig(2))
        whole.via_m = []
        analyses = {"t1": busier, "t2": self.calm(2), "o1+o2": whole, "o1+t2": whole}
        routes = [one_leg("t1", 9.0, 3000.0), one_leg("t2", 9.0, 3000.0)]
        _w, _kept, info = self.plan(monkeypatch, analyses, routes)
        assert [t["outcome"] for t in info["seek"]["tried"]] == ["busier", "taken"]

    def test_the_guard_is_against_what_the_router_first_gave_not_what_the_search_left(
        self, monkeypatch
    ) -> None:
        # The router first gave each leg 2,000 m of exposure; by the time the seek
        # runs the leg reads 1,000. A candidate of 1,500 is inside the first's
        # allowance (2% and 50 m over 2,000) and is taken.
        first = analysis("o1+o2", ("1" * 10 + "3" * 20 + "1" * 10) * 2, cost_s=8000.0)
        first.via_m = [4000.0]
        candidate = analysis("t1", "1" * 40, cost_s=100.0)
        candidate.exposure_m = 1500.0
        self.none_for = {1}
        analyses = {
            "o1+o2": first,
            "t1": candidate,
            "t1+o2": whole_of(leg_orig(1), leg_orig(2)),
        }
        _w, kept, info = self.plan(monkeypatch, analyses, [one_leg("t1", 9.0, 3000.0)])
        assert [t["outcome"] for t in info["seek"]["tried"]] == ["taken"]
        assert [leg["shape"] for leg in kept["legs"]] == ["t1", "o2"]

    # --- review r1 -------------------------------------------------------------

    def test_each_leg_is_guarded_against_its_own_first_exposure_not_its_neighbours(
        self, monkeypatch
    ) -> None:
        # Asymmetric legs (mutant R25): the router first gave leg 1 2,000 m of
        # exposure and leg 2 500. A candidate of 1,500 on each is inside leg 1's
        # allowance and far past leg 2's.
        first = analysis("o1+o2", "3" * 20 + "1" * 20 + "3" * 5 + "1" * 35, cost_s=8000.0)
        first.via_m = [4000.0]
        t1, t2 = self.calm(1), self.calm(2)
        t1.exposure_m = t2.exposure_m = 1500.0
        t1.cost_s = t2.cost_s = 100.0
        analyses = {
            "o1+o2": first,
            "t1": t1,
            "t2": t2,
            "t1+o2": whole_of(leg_orig(1), leg_orig(2)),
        }
        routes = [one_leg("t1", 9.0, 3000.0), one_leg("t2", 9.0, 3000.0)]
        _w, kept, info = self.plan(monkeypatch, analyses, routes)
        assert [(t["leg"], t["outcome"]) for t in info["seek"]["tried"]] == [
            (0, "taken"),
            (1, "busier"),
        ]
        assert [leg["shape"] for leg in kept["legs"]] == ["t1", "o2"]

    def test_a_leg_whose_reading_used_its_time_does_not_read_the_table(self, monkeypatch) -> None:
        # The leg's deadline is looked at again before the table: reading the leg
        # took what it had.
        now = [routing.clock()]
        monkeypatch.setattr(routing, "clock", lambda: now[0])
        ctx = self.leg_context(2)
        base = {"o1": leg_orig(1), "o2": leg_orig(2), "o1+o2": whole_of(leg_orig(1), leg_orig(2))}
        world = LegWorld(monkeypatch, base, [NO_ROUTE])
        read = refine.analyse

        def slow(trip, ctx, deadline):
            got = read(trip, ctx, deadline)
            if [leg["shape"] for leg in trip["legs"]] == ["o1"]:
                now[0] += deadline.at - now[0] - trailseek.SEEK_ROUND_MIN_S + 0.1
            return got

        monkeypatch.setattr(refine, "analyse", slow)
        _kept, info = refine.refine(multi_trip(["o1", "o2"]), ctx)
        assert self.tables == [] and world.asked() == [] and info["seek"]["limited"] == "time"

    def test_a_late_leg_is_held_to_the_seeks_stop(self, monkeypatch) -> None:
        # 2.3 s left (mutant R8): the leg's least (2.5 s) may not run past the stop
        # and into the time kept back for the answer's traces.
        ctx = self.leg_context(2, deadline_s=refine.REFINE_TRACE_RESERVE_S + 2.3)
        worse = {f"t{i}": analysis(f"t{i}", "1" * 40, cost_s=9000.0) for i in (1, 2)}
        world, _kept, _info = self.plan(monkeypatch, worse, [one_leg("t1"), one_leg("t2")], ctx=ctx)
        assert world.deadlines[0] == pytest.approx(2.3, abs=0.1)
        assert max(world.deadlines) <= 2.3 + 0.05

    def test_a_table_that_cannot_be_read_is_not_read_again_for_the_next_leg(
        self, monkeypatch
    ) -> None:
        # Mutant R22: the failure ends the later legs; it is not met again.
        calls: list = []

        def broken(*args, **kw):
            calls.append(args)
            raise RuntimeError("the database is down")

        monkeypatch.setattr(trailseek, "corridor_segments", broken)
        world, _kept, info = self.plan(monkeypatch, {}, [])
        assert len(calls) == 1 and info["seek"]["limited"] == "table" and world.asked() == []

    def test_the_whole_trip_is_guarded_as_well_as_each_leg(self, monkeypatch) -> None:
        # Each leg 60 m over its 1,000 m is inside its own allowance (1,070 m);
        # the whole trip 120 m over its 2,000 is past the trip's (2,090 m).
        t1, t2 = self.calm(1), self.calm(2)
        t1.exposure_m = t2.exposure_m = 1060.0
        for whole_m, taken in ((2120.0, False), (2080.0, True)):
            analyses = {
                "t1": t1,
                "t2": t2,
                "t1+o2": whole_of(leg_orig(1), leg_orig(2)),
                "t1+t2": whole_of(leg_orig(1), leg_orig(2), exposure_m=whole_m),
            }
            routes = [one_leg("t1", 9.0, 3000.0), one_leg("t2", 9.0, 3000.0)]
            _w, kept, info = self.plan(monkeypatch, analyses, routes)
            assert [t["outcome"] for t in info["seek"]["tried"]] == ["taken", "taken"]
            assert info["seek"]["taken"] is taken
            if taken:
                assert [leg["shape"] for leg in kept["legs"]] == ["t1", "t2"]
            else:
                assert [leg["shape"] for leg in kept["legs"]] == ["o1", "o2"]
                assert info["seek"]["limited"] == "busier"
                assert info["exposure_after_m"] == info["exposure_before_m"]
            assert info["seek"]["whole_trip"] == ("taken" if taken else "busier")

    # --- review r2 -------------------------------------------------------------

    def test_the_whole_trip_is_guarded_against_the_first_exposure_not_the_searchs_best(
        self, monkeypatch
    ) -> None:
        # Mutant V18: the exclusion search found a calmer whole route (1,500 m of
        # exposure) than the router's first (2,000 m). A spliced trip of 1,800 m is
        # inside the first's allowance (2,090 m), though past the best's (1,580 m),
        # and is taken: Traffic wins is against what the router first gave.
        searched = analysis("s", "1" * 80, cost_s=7000.0)
        searched.exposure_m = 1500.0
        searched.via_m = [4000.0]
        t1, t2 = self.calm(1), self.calm(2)
        t1.exposure_m = t2.exposure_m = 1060.0
        analyses = {
            "o1": leg_orig(1),
            "o2": leg_orig(2),
            "o1+o2": whole_of(leg_orig(1), leg_orig(2)),
            "s1+s2": searched,
            "s1": leg_orig(1),
            "s2": leg_orig(2),
            "t1": t1,
            "t2": t2,
            "t1+s2": whole_of(leg_orig(1), leg_orig(2)),
            "t1+t2": whole_of(leg_orig(1), leg_orig(2), exposure_m=1800.0),
        }
        routes = [
            multi_trip(["s1", "s2"]),
            one_leg("t1", 9.0, 3000.0),
            one_leg("t2", 9.0, 3000.0),
        ]
        world = LegWorld(monkeypatch, analyses, routes)
        kept, info = refine.refine(multi_trip(["o1", "o2"]), self.leg_context())
        assert info["rounds"] == 1 and len(world.asked()) == 2
        assert [t["outcome"] for t in info["seek"]["tried"]] == ["taken", "taken"]
        assert info["seek"]["taken"] is True and info["seek"]["whole_trip"] == "taken"
        assert [leg["shape"] for leg in kept["legs"]] == ["t1", "t2"]
        assert info["exposure_after_m"] == 1800.0

    def test_a_busier_whole_trip_is_shown_after_a_leg_ran_out_of_time(self, monkeypatch) -> None:
        # The first leg is taken, the second runs out of time; the spliced trip is
        # past the whole trip's allowance. `limited` keeps the first stop ("time")
        # and `whole_trip` says why the splice was not taken.
        t1 = self.calm(1)
        t1.exposure_m = 1060.0
        analyses = {
            "t1": t1,
            "t1+o2": whole_of(leg_orig(1), leg_orig(2), exposure_m=2120.0),
        }
        routes = [one_leg("t1", 9.0, 3000.0), routing.DeadlineExceeded("out of time")]
        _w, kept, info = self.plan(monkeypatch, analyses, routes)
        seek = info["seek"]
        assert [t["outcome"] for t in seek["tried"]] == ["taken"]
        assert seek["limited"] == "time" and seek["whole_trip"] == "busier"
        assert seek["taken"] is False and seek["asked"] == seek["routes"] == 2
        assert [leg["shape"] for leg in kept["legs"]] == ["o1", "o2"]


class TestRouteSpansAndLegs:
    def test_busy_road_and_trail_are_spans_in_traced_metres(self) -> None:
        a = analysis("a", "1331", trails="t  t")
        busy, trail, traced = refine.route_spans(a)
        assert busy == [(100.0, 200.0, 1.0), (200.0, 300.0, 1.0)]
        assert trail == [(0.0, 100.0, 1.0), (300.0, 400.0, 1.0)]
        assert traced == 400.0

    def test_a_stretch_of_the_route_is_cut_out_and_measured_from_its_start(self) -> None:
        a = analysis("a", "1334155", trails="t     t")
        busy, trail, traced = refine.route_spans(a, 200.0, 600.0)
        assert busy == [(0.0, 100.0, 1.0), (100.0, 200.0, 2.0), (300.0, 400.0, 3.0)]
        assert trail == [] and traced == 400.0
        busy, trail, traced = refine.route_spans(a, 600.0, None)
        assert busy == [(0.0, 100.0, 3.0)] and trail == [(0.0, 100.0, 1.0)] and traced == 100.0

    def test_a_piece_across_the_cut_is_clipped(self) -> None:
        a = analysis("a", "333")
        busy, _trail, traced = refine.route_spans(a, 50.0, 250.0)
        assert busy == [(0.0, 50.0, 1.0), (50.0, 150.0, 1.0), (150.0, 200.0, 1.0)]
        assert traced == 200.0
        assert refine.route_spans(a, 0.0, 1e9)[2] == 300.0

    def test_pieces_without_a_trail_reading_have_no_trail(self) -> None:
        a = analysis("a", "133")
        assert refine.route_spans(a)[1] == []

    def test_the_legs_run_between_the_via_points(self) -> None:
        a = analysis("a", "1" * 10)
        a.via_m = [300.0, 700.0]
        assert refine.leg_bounds(a) == [(0.0, 300.0), (300.0, 700.0), (700.0, 1000.0)]
        a.via_m = []
        assert refine.leg_bounds(a) == [(0.0, 1000.0)]

    def test_a_leg_is_a_trip_of_its_own(self) -> None:
        trip = multi_trip(["a", "b"])
        assert refine._leg_trip(trip, 1) == {
            "legs": [trip["legs"][1]],
            "summary": trip["legs"][1]["summary"],
        }

    def test_splicing_replaces_a_leg_and_adjusts_what_the_summary_adds_up(self) -> None:
        trip = multi_trip(["a", "b", "c"])
        spliced = refine._splice(trip, 1, one_leg("x", 10.0, 3000.0))
        assert [leg["shape"] for leg in spliced["legs"]] == ["a", "x", "c"]
        assert spliced["summary"]["length"] == pytest.approx(8.7 * 3 - 8.7 + 10.0)
        assert spliced["summary"]["cost"] == pytest.approx(12_000.0 - 4000.0 + 3000.0)
        assert spliced["summary"]["min_lat"] == 38.0
        # The trip it came from is not changed.
        assert [leg["shape"] for leg in trip["legs"]] == ["a", "b", "c"]
        assert trip["summary"]["length"] == pytest.approx(26.1)

    def test_a_summary_without_a_field_is_left_without_it(self) -> None:
        trip = multi_trip(["a", "b"])
        del trip["summary"]["cost"]
        spliced = refine._splice(trip, 0, one_leg("x", 10.0, 3000.0))
        assert "cost" not in spliced["summary"]
        assert spliced["summary"]["length"] == pytest.approx(8.7 + 10.0)
