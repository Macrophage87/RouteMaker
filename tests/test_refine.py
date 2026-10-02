"""The search over the router's own routes (`core.refine`): the calm detour at
the top of the stress slider (OWNER-DECISIONS 163, 164) and the avoidance of the
worst crossings (165-169), with the router and the route's reading replaced.

Valhalla's `exclude_locations` is what steers it; the tests hold what is asked of
it, what is kept, and why the search stops.
"""

from __future__ import annotations

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
) -> refine.Analysis:
    """A candidate read: `tiers` is one letter a 100 m piece, and `shift` moves it
    along (in pieces) so that two candidates can have busy stretches in different places."""
    pieces, classes = zip(
        *[piece((i + shift) * 100.0, tier) for i, tier in enumerate(tiers)], strict=True
    )
    stress = {"3": 1, "4": 2, "5": 3}
    return refine.Analysis(
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

        def table(schema, guide, width_m, has_facility, when, avoid_unpaved=False):
            self.asked.append((schema, guide, width_m, has_facility, when, avoid_unpaved))
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
        empty = {"corridors": 0, "asked": 0, "taken": False, "limited": None, "tried": []}
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
