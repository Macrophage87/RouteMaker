"""Make it a loop (OWNER-DECISIONS 266): the way back by a different way.

`refine.make_loop` with the router and the readings of its routes replaced, as in
test_refine; and the plan's own rules (`routing.loop_wanted`, `loop_points`,
`loop_stats`).
"""

from __future__ import annotations

import dataclasses
import threading
import time
from concurrent.futures import Future, wait

import pytest
from test_refine import BASE, context

from core import presets, refine, routing

# --- Readings of a loop ---------------------------------------------------------------


def piece_at(i: int, way: int) -> routing.Piece:
    return routing.Piece(way, BASE[0] + i * 1e-3, BASE[1], 100.0)


def loop_read(
    out: list[int], back: list[int], tiers: str | None = None, events=()
) -> refine.Analysis:
    """A loop's reading: the way out over these ways and the way back over those, 100 m
    a piece, the leg boundary between them."""
    ways = [*out, *back]
    pieces = [piece_at(i, w) for i, w in enumerate(ways)]
    tiers = tiers or "1" * len(ways)
    return refine.Analysis(
        length_m=100.0 * len(ways),
        cost_s=1.0,
        exposure_m=0.0,
        climb_m=0.0,
        pieces=pieces,
        classes=[(t, "none") for t in tiers],
        events=list(events),
        via_m=[100.0 * len(out)],
        lts4_m=100.0 * sum(t in "45" for t in tiers),
        lts3_m=100.0 * tiers.count("3"),
    )


OUT = list(range(1, 41))  # a way out of 40 pieces, 4 km


class TestTheOverlap:
    def test_it_is_the_way_back_on_ways_the_way_out_rides(self) -> None:
        read = loop_read(OUT, [1, 2, 3, 4, 91, 92, 93, 94, 95, 96])
        assert refine.return_overlap(read) == (400.0, 1000.0)
        assert refine.overlap_share(read) == pytest.approx(0.4)

    def test_a_way_back_over_other_ways_shares_nothing(self) -> None:
        assert refine.overlap_share(loop_read(OUT, list(range(101, 141)))) == 0.0

    def test_the_same_way_back_shares_all_of_it(self) -> None:
        assert refine.overlap_share(loop_read(OUT, list(reversed(OUT)))) == 1.0

    def test_a_plan_with_one_leg_has_no_overlap(self) -> None:
        read = loop_read(OUT, [])
        read.via_m = []
        assert refine.return_overlap(read) == (0.0, 0.0) and refine.overlap_share(read) == 0.0

    def test_with_several_stops_the_way_out_is_every_leg_before_the_last(self) -> None:
        read = loop_read(OUT, [1, 20, 30, 91])
        read.via_m = [1500.0, 4000.0]  # three legs: out to 1,500 m, on to 4,000 m, then back
        assert refine.return_overlap(read) == (300.0, 400.0)

    def test_a_loop_may_not_share_more_than_it_has_or_the_ok_share(self) -> None:
        ctx = context(rate=10.0)
        assert not refine.loop_refused(loop_read(OUT, OUT[:30]), ctx), "not a loop: no rule"
        ctx.loop_overlap = 0.10
        # The limit is the larger of the loop's own and LOOP_OVERLAP_OK.
        assert not refine.loop_refused(loop_read(OUT, OUT[:3] + list(range(100, 107))), ctx)
        assert refine.loop_refused(loop_read(OUT, OUT[:4] + list(range(100, 106))), ctx)
        ctx.loop_overlap = 0.50
        assert not refine.loop_refused(loop_read(OUT, OUT[:5] + list(range(100, 105))), ctx)
        assert refine.loop_refused(loop_read(OUT, OUT[:6] + list(range(100, 104))), ctx)

    def test_the_numbers_are_the_documented_ones(self) -> None:
        assert refine.LOOP_OVERLAP_OK == 0.30
        assert refine.LOOP_OUT_AND_BACK == 0.90
        assert refine.LOOP_THINNING == (1, 2, 4, 8)


# --- Making one -----------------------------------------------------------------------


class LoopWorld:
    """The router for a loop: `backs` are what each ask for the way back gets (a route's
    name and length in km, or an exception), in order; `readings` what each trip's
    shapes read as."""

    def __init__(self, monkeypatch, readings: dict, backs: list) -> None:
        self.readings = readings
        self.backs = list(backs)
        self.requests: list[dict] = []
        monkeypatch.setattr(refine, "analyse", self.analyse)
        monkeypatch.setattr(routing, "_call", self.call)

    def analyse(self, trip, ctx, deadline, with_events=True):
        key = tuple(leg["shape"] for leg in trip["legs"])
        if key not in self.readings and len(key) == 1:
            # A way back read on its own (`_through`): only that it was read matters.
            return loop_read([], [1])
        return self.readings[key]

    def call(self, variant, endpoint, payload, deadline):
        assert endpoint == "route"
        self.requests.append(payload)
        if not self.backs:
            raise routing.RouterRefused(400, 442, "no path")
        answer = self.backs.pop(0)
        if isinstance(answer, Exception):
            raise answer
        name, km = answer
        summary = {"length": km, "time": 100.0 * km, "cost": 100.0 * km}
        return {"trip": {"legs": [{"shape": name, "summary": summary}], "summary": summary}}

    def excluded(self, number: int) -> list[tuple[float, float]]:
        return [(p["lon"], p["lat"]) for p in self.requests[number].get("exclude_locations", [])]


def two_leg_trip(back: str = "same", km: float = 8.0) -> dict:
    return {
        "legs": [
            {"shape": "out", "summary": {"length": 4.0}},
            {"shape": back, "summary": {"length": 4.0}},
        ],
        "summary": {"length": km, "time": 100.0, "cost": 100.0},
    }


def loop_context(ceiling_m=None, preset="trailmaxxing") -> refine.Context:
    ctx = context(rate=10.0, maxcalm=True, ceiling_m=ceiling_m)
    ctx.points = [[BASE[0], BASE[1]], [BASE[0] + 0.04, BASE[1]], [BASE[0], BASE[1]]]
    ctx.request = {
        "locations": [
            {"lon": BASE[0], "lat": BASE[1], "type": "break"},
            {"lon": BASE[0] + 0.04, "lat": BASE[1], "type": "break"},
            {"lon": BASE[0], "lat": BASE[1], "type": "break"},
        ],
        "costing": "bicycle",
    }
    return ctx


def readings(**backs) -> dict:
    """The readings for a plan whose way back is each named route: `same` is the way
    out reversed; the others are given as {name: back ways}."""
    out = {
        ("out", "same"): loop_read(OUT, list(reversed(OUT))),
        ("out",): loop_read(OUT, []),
    }
    for name, ways in backs.items():
        out[("out", name)] = loop_read(OUT, ways)
    return out


class TestMakingALoop:
    @pytest.fixture(autouse=True)
    def in_turn(self, settings) -> None:
        # LoopWorld answers its asks in the order they come: with the ways back asked together
        # on the pool (audit round 2, S24) that order is the threads', so these tests ask them
        # in turn. `TestWaysBackTogether` has the pool on.
        settings.ROUTER_PARALLEL_CALLS = 1

    def test_a_way_back_that_shares_little_is_taken_and_the_overlap_reported(
        self, monkeypatch
    ) -> None:
        world = LoopWorld(
            monkeypatch,
            readings(R1=[1, 2] + list(range(101, 139))),
            [("R1", 4.2)],
        )
        trip, info = refine.make_loop(two_leg_trip(), loop_context())
        assert [leg["shape"] for leg in trip["legs"]] == ["out", "R1"]
        assert info["fallback"] is None and info["tried"] == len(refine.LOOP_THINNING)
        assert (
            info["overlap_pct"] == 5.0 and info["shared_m"] == 200.0 and info["return_m"] == 4000.0
        )
        assert info["excluded"] == len(world.excluded(0)) > 10

    def test_the_way_out_is_excluded_along_it_but_not_near_the_ends(self, monkeypatch) -> None:
        world = LoopWorld(monkeypatch, readings(R1=list(range(101, 141))), [("R1", 4.2)])
        refine.make_loop(two_leg_trip(), loop_context())
        lons = [lon for lon, _lat in world.excluded(0)]
        along = [(lon - BASE[0]) / 1e-3 * 100.0 for lon in lons]
        assert min(along) >= refine.ENDPOINT_CLEARANCE_M - 100.0
        assert max(along) <= 4000.0 - refine.ENDPOINT_CLEARANCE_M + 100.0
        gaps = [b - a for a, b in zip(sorted(lons), sorted(lons)[1:], strict=False)]
        assert min(gaps) * 1e3 * 100.0 / 1e-3 / 1e3 >= 0 and len(lons) <= refine.MAX_EXCLUDES

    def test_the_request_is_the_way_back_alone(self, monkeypatch) -> None:
        world = LoopWorld(monkeypatch, readings(R1=list(range(101, 141))), [("R1", 4.2)])
        refine.make_loop(two_leg_trip(), loop_context())
        locations = world.requests[0]["locations"]
        assert len(locations) == 2
        assert locations[0]["lon"] == pytest.approx(BASE[0] + 0.04)
        assert locations[1]["lon"] == pytest.approx(BASE[0])
        assert "alternates" not in world.requests[0]

    def test_the_overlap_is_preferred_away_not_forced(self, monkeypatch) -> None:
        """One bridge: every way back shares a third of the way, which is past the share
        a loop likes, and is what there is: the one that shares least is kept and the
        share is said."""
        world = LoopWorld(
            monkeypatch,
            readings(
                B1=list(range(11, 27)) + list(range(201, 225)),  # 40% shared
                B2=list(range(11, 25)) + list(range(301, 327)),  # 35%
                B3=list(range(11, 24)) + list(range(401, 428)),  # 32.5%
            ),
            [routing.RouterRefused(400, 442, "no path"), ("B1", 4.1), ("B2", 4.2), ("B3", 4.3)],
        )
        trip, info = refine.make_loop(two_leg_trip(), loop_context())
        assert info["fallback"] is None
        assert info["overlap_pct"] == 32.5 and info["shared_m"] == 1300.0
        assert [leg["shape"] for leg in trip["legs"]] == ["out", "B3"]
        assert info["tried"] == 4 and len(world.requests) == 4
        # Each ask excluded fewer points than the one before.
        sizes = [len(world.excluded(i)) for i in range(4)]
        assert sizes == sorted(sizes, reverse=True) and len(set(sizes)) == 4

    def test_every_thinning_is_asked_even_when_the_first_is_within_the_ok_share(
        self, monkeypatch
    ) -> None:
        world = LoopWorld(monkeypatch, readings(R1=[1] + list(range(101, 140))), [("R1", 4.0)])
        _trip, info = refine.make_loop(two_leg_trip(), loop_context())
        assert info["tried"] == 4 and len(world.requests) == 4

    def test_among_those_within_the_ok_share_the_least_stressful_is_taken(
        self, monkeypatch
    ) -> None:
        ways = list(range(101, 141))
        busy = loop_read(OUT, [1] * 4 + ways[4:], "1" * 60 + "3" * 20)
        calm = loop_read(OUT, [1] * 8 + ways[8:])
        LoopWorld(
            monkeypatch,
            {
                ("out", "same"): loop_read(OUT, list(reversed(OUT))),
                ("out",): loop_read(OUT, []),
                ("out", "A"): busy,
                ("out", "B"): calm,
            },
            [("A", 4.0), ("B", 4.0)],
        )
        # Both share under 30% (A 10%, B 20%); A has more LTS 3, so the more shared B is taken.
        trip, info = refine.make_loop(two_leg_trip(), loop_context())
        assert [leg["shape"] for leg in trip["legs"]] == ["out", "B"]
        assert info["overlap_pct"] == 20.0

    def test_the_order_the_ways_back_come_in_does_not_decide(self, monkeypatch) -> None:
        ways = list(range(101, 141))
        calm = loop_read(OUT, [1] * 8 + ways[8:])
        busy = loop_read(OUT, [1] * 4 + ways[4:], "1" * 60 + "3" * 20)
        LoopWorld(
            monkeypatch,
            {
                ("out", "same"): loop_read(OUT, list(reversed(OUT))),
                ("out",): loop_read(OUT, []),
                ("out", "A"): calm,
                ("out", "B"): busy,
            },
            [("A", 4.0), ("B", 4.0)],
        )
        trip, _info = refine.make_loop(two_leg_trip(), loop_context())
        assert [leg["shape"] for leg in trip["legs"]] == ["out", "A"]

    def test_an_unavoidable_there_and_back_keeps_the_routers_route_and_says_so(
        self, monkeypatch
    ) -> None:
        LoopWorld(monkeypatch, readings(), [("same", 4.0)] * 4)
        trip0 = two_leg_trip()
        trip, info = refine.make_loop(trip0, loop_context())
        assert trip is trip0
        assert info["fallback"] == "out_and_back" and info["overlap_pct"] == 100.0

    def test_a_router_with_no_way_back_at_all_is_an_out_and_back(self, monkeypatch) -> None:
        LoopWorld(monkeypatch, readings(), [routing.RouterRefused(400, 442, "no path")] * 4)
        trip0 = two_leg_trip()
        trip, info = refine.make_loop(trip0, loop_context())
        assert trip is trip0 and info["fallback"] == "out_and_back"

    def ways_back(self, monkeypatch, calm_pieces: int, maxcalm: bool = True):
        """A busier way back (200 m of LTS 3, 8 km loop) and a calm longer one."""
        ways = list(range(101, 141))
        busy = loop_read(OUT, [1] * 4 + ways[4:], "1" * 60 + "3" * 2 + "1" * 18)
        busy.exposure_m = 200.0
        calm = loop_read(OUT, [1] * 4 + list(range(201, 201 + calm_pieces - 4)))
        LoopWorld(
            monkeypatch,
            {
                ("out", "same"): loop_read(OUT, list(reversed(OUT))),
                ("out",): loop_read(OUT, []),
                ("out", "A"): busy,
                ("out", "B"): calm,
            },
            [("A", 4.0), ("B", 4.0)],
        )
        ctx = loop_context()
        ctx.maxcalm = maxcalm
        trip, _info = refine.make_loop(two_leg_trip(), ctx)
        return [leg["shape"] for leg in trip["legs"]][1]

    def test_a_calmer_way_back_must_be_worth_its_miles(self, monkeypatch) -> None:
        """OWNER-DECISIONS 268, 271: the whole loop's extra distance has diminishing
        returns: 200 m of LTS 3 buys 1 km more, not 2."""
        assert self.ways_back(monkeypatch, 50) == "B"
        assert self.ways_back(monkeypatch, 60) == "A"

    def test_below_the_top_the_least_stress_decides(self, monkeypatch) -> None:
        assert self.ways_back(monkeypatch, 60, maxcalm=False) == "B"

    def test_below_the_top_the_least_stress_beats_the_least_shared(self, monkeypatch) -> None:
        """Both under 30%: the busier one shares less (10%), the calmer more (20%)."""
        ways = list(range(101, 141))
        LoopWorld(
            monkeypatch,
            {
                ("out", "same"): loop_read(OUT, list(reversed(OUT))),
                ("out",): loop_read(OUT, []),
                ("out", "A"): loop_read(OUT, [1] * 4 + ways[4:], "1" * 60 + "3" * 20),
                ("out", "B"): loop_read(OUT, [1] * 8 + ways[8:]),
            },
            [("A", 4.0), ("B", 4.0)],
        )
        ctx = loop_context()
        ctx.maxcalm = False
        trip, _info = refine.make_loop(two_leg_trip(), ctx)
        assert [leg["shape"] for leg in trip["legs"]] == ["out", "B"]

    def test_the_whole_loop_is_within_the_ceiling_not_each_half(self, monkeypatch) -> None:
        # 4 km out and 4 km first back: the whole is 8 km. A way back of 5 km makes 9.
        LoopWorld(
            monkeypatch,
            readings(LONG=list(range(101, 141)), FITS=list(range(201, 241))),
            [("LONG", 5.0), ("FITS", 4.4)],
        )
        trip, info = refine.make_loop(two_leg_trip(), loop_context(ceiling_m=8_600.0))
        assert [leg["shape"] for leg in trip["legs"]] == ["out", "FITS"]
        assert trip["summary"]["length"] * 1000.0 <= 8_600.0 and info["tried"] == 4

    def test_a_way_back_past_the_limit_every_time_is_the_out_and_back(self, monkeypatch) -> None:
        LoopWorld(monkeypatch, readings(LONG=list(range(101, 141))), [("LONG", 5.0)] * 4)
        trip0 = two_leg_trip()
        trip, info = refine.make_loop(trip0, loop_context(ceiling_m=8_200.0))
        assert trip is trip0 and info["fallback"] == "out_and_back"

    def test_a_route_with_one_leg_is_not_a_loop(self, monkeypatch) -> None:
        LoopWorld(monkeypatch, readings(), [])
        trip0 = {"legs": [{"shape": "out"}], "summary": {"length": 4.0}}
        trip, info = refine.make_loop(trip0, loop_context())
        assert trip is trip0 and info["fallback"] == "points"

    def test_out_of_time_leaves_the_route(self, monkeypatch) -> None:
        LoopWorld(
            monkeypatch, readings(R1=list(range(101, 141))), [routing.DeadlineExceeded("late")]
        )
        trip0 = two_leg_trip()
        trip, info = refine.make_loop(trip0, loop_context())
        assert trip is trip0 and info["fallback"] in ("time", "out_and_back")

    def test_a_way_back_that_shares_more_than_the_routers_own_is_not_taken(
        self, monkeypatch
    ) -> None:
        """The router's own way back already shares 20%; a way that shares 60% is no better."""
        own = loop_read(OUT, OUT[:8] + list(range(101, 133)))
        world = LoopWorld(
            monkeypatch, readings(R1=OUT[:24] + list(range(101, 117))), [("R1", 4.0)] * 4
        )
        world.readings[("out", "same")] = own
        trip0 = two_leg_trip()
        trip, info = refine.make_loop(trip0, loop_context())
        assert trip is trip0 and info["overlap_pct"] == 20.0


class SlowLoopWorld(LoopWorld):
    """LoopWorld whose every ask takes a moment, counting how many are in flight at once."""

    def __init__(self, monkeypatch, readings: dict, backs: list, delay: float = 0.05) -> None:
        super().__init__(monkeypatch, readings, backs)
        self.delay = delay
        self.lock = threading.Lock()
        self.flying = 0
        self.most = 0
        self.alone: list[bool] = []
        self.traced: list[str] = []
        monkeypatch.setattr(routing, "trace_leg", self.trace_leg)

    def trace_leg(self, variant, costing, shape, deadline):
        # A trace is a router call too: it takes its moment, within the reader's deadline.
        with self.lock:
            self.flying += 1
            self.most = max(self.most, self.flying)
            self.traced.append(shape)
        try:
            time.sleep(max(0.0, min(self.delay, deadline.at - routing.clock())))
            if routing.clock() >= deadline.at:
                raise routing.DeadlineExceeded
            return {"shape": shape}
        finally:
            with self.lock:
                self.flying -= 1

    def analyse(self, trip, ctx, deadline, with_events=True):
        key = tuple(leg["shape"] for leg in trip["legs"])
        if key not in self.readings and len(key) == 1:
            # The way back alone, as the real `analyse` reads it: no junctions without events.
            self.alone.append(with_events)
            read = loop_read([], [1])
            return read if with_events else dataclasses.replace(read, events=None)
        return self.readings[key]

    def call(self, variant, endpoint, payload, deadline):
        with self.lock:
            self.flying += 1
            self.most = max(self.most, self.flying)
        try:
            time.sleep(self.delay)
            with self.lock:
                return super().call(variant, endpoint, payload, deadline)
        finally:
            with self.lock:
                self.flying -= 1


class TestWaysBackTogether:
    """Audit round 2, S24: the four ways back are asked together on the pool, as `_wide`
    asks its routes, and each is read alone without its junctions."""

    def test_the_ways_back_are_asked_together_within_the_pools_bound(
        self, monkeypatch, settings
    ) -> None:
        settings.ROUTER_PARALLEL_CALLS = 3
        world = SlowLoopWorld(
            monkeypatch, readings(R1=[1, 2] + list(range(101, 139))), [("R1", 4.2)] * 4
        )
        trip, info = refine.make_loop(two_leg_trip(), loop_context())
        assert [leg["shape"] for leg in trip["legs"]] == ["out", "R1"]
        assert info["tried"] == 4 and len(world.requests) == 4
        assert world.most == 3, "asked together, never past the pool's bound"

    def test_a_way_back_read_without_its_junctions_is_still_taken(
        self, monkeypatch, settings
    ) -> None:
        # The gate is that the way back could be read at all: with it still on its junctions
        # every way back would be passed over and the loop left an out-and-back.
        settings.ROUTER_PARALLEL_CALLS = 3
        world = SlowLoopWorld(
            monkeypatch, readings(R1=[1, 2] + list(range(101, 139))), [("R1", 4.2)] * 4
        )
        trip, info = refine.make_loop(two_leg_trip(), loop_context())
        assert world.alone == [False] * 4
        assert info["fallback"] is None and [leg["shape"] for leg in trip["legs"]] == ["out", "R1"]

    def test_in_turn_on_a_pool_of_one(self, monkeypatch, settings) -> None:
        settings.ROUTER_PARALLEL_CALLS = 1
        world = SlowLoopWorld(
            monkeypatch, readings(R1=[1, 2] + list(range(101, 139))), [("R1", 4.2)] * 4
        )
        _trip, info = refine.make_loop(two_leg_trip(), loop_context())
        assert info["tried"] == 4 and world.most == 1

    def test_asks_not_read_once_the_time_is_gone_are_cancelled(self, monkeypatch, settings) -> None:
        # Review of S24: no call is left without a reader, neither an ask nor its trace.
        settings.ROUTER_PARALLEL_CALLS = 3
        world = SlowLoopWorld(
            monkeypatch, readings(R1=[1, 2] + list(range(101, 139))), [("R1", 4.2)] * 4
        )
        asked: list = []
        real = refine._ask_ways_back

        def ask(*args):
            asking = real(*args)
            asked.extend(asking)
            # The time runs out after the asks, while three are running and one is queued:
            # none is read.
            ends = time.monotonic() + 5
            while world.flying < 3 and time.monotonic() < ends:
                time.sleep(0.001)
            monkeypatch.setattr(routing, "clock", lambda: 1e12)
            return asking

        monkeypatch.setattr(refine, "_ask_ways_back", ask)
        trip0 = two_leg_trip()
        ctx = loop_context()
        trip, info = refine.make_loop(trip0, ctx)
        assert trip is trip0 and info["tried"] == 0 and info["fallback"] == "out_and_back"
        assert len(asked) == 4 and asked[3].cancelled(), "the one still queued is never sent"
        assert not any(isinstance(v, Future) for v in ctx.traces.values())
        wait(asked, timeout=5)
        assert world.traced == [], "an ask that answers once abandoned goes no further"
        assert len(world.requests) == 3 and all(f.done() for f in asked)
        assert not any(isinstance(v, Future) for v in ctx.traces.values())

    def test_a_slow_router_finds_the_loop_on_the_pool_as_in_turn(
        self, monkeypatch, settings
    ) -> None:
        # Review of S24: the answers read as each comes in, one already in hand not held to a
        # whole round. With every way back waited for and then each gated on a round, a slow
        # router left the pool's run the out-and-back where asking in turn found the loop.
        monkeypatch.setattr(refine, "LOOP_BUDGET_S", 1.4)
        monkeypatch.setattr(refine, "REFINE_ROUND_MIN_S", 0.5)
        found = {}
        for pool in (1, 3):
            settings.ROUTER_PARALLEL_CALLS = pool
            world = SlowLoopWorld(
                monkeypatch,
                readings(R1=[1, 2] + list(range(101, 139))),
                [("R1", 4.2)] * 4,
                delay=0.45,
            )
            trip, info = refine.make_loop(two_leg_trip(), loop_context())
            found[pool] = info
            assert info["fallback"] is None, (pool, info)
            assert [leg["shape"] for leg in trip["legs"]] == ["out", "R1"]
            assert world.most <= pool
        assert found[3]["tried"] >= found[1]["tried"] >= 1

    def test_each_way_back_is_read_with_the_trace_it_brought(self, monkeypatch, settings) -> None:
        settings.ROUTER_PARALLEL_CALLS = 3
        world = SlowLoopWorld(
            monkeypatch,
            readings(**{f"R{n}": [1, 2] + list(range(101, 139)) for n in (1, 2, 3, 4)}),
            [("R1", 4.2), ("R2", 4.2), ("R3", 4.2), ("R4", 4.2)],
        )
        ctx = loop_context()
        refine.make_loop(two_leg_trip(), ctx)
        assert sorted(world.traced) == ["R1", "R2", "R3", "R4"]
        kept = [v for v in ctx.traces.values() if isinstance(v, dict) and "shape" in v]
        assert sorted(v["shape"] for v in kept) == ["R1", "R2", "R3", "R4"]


# --- The plan's rules -----------------------------------------------------------------

A = [-77.0, 38.9]
B = [-76.95, 38.92]
C = [-76.9, 38.9]


class TestThePlansRules:
    def test_a_ride_that_ends_where_it_starts_is_a_loop(self) -> None:
        assert routing.is_round_trip([A, B, A])
        assert routing.is_round_trip([A, B, C, [A[0] + 1e-4, A[1]]])
        assert not routing.is_round_trip([A, B, [A[0] + 1e-2, A[1]]])
        assert not routing.is_round_trip([A, A]), "a place between is needed"
        assert routing.loop_wanted([A, B, A], False, "trailmaxxing")

    def test_a_point_to_point_ride_is_not_a_loop_until_asked(self) -> None:
        assert not routing.loop_wanted([A, B], False, "trailmaxxing")
        assert routing.loop_wanted([A, B], True, "trailmaxxing")
        assert not routing.loop_wanted([A], True, "trailmaxxing")

    def test_a_mass_ride_is_never_made_one(self) -> None:
        assert not routing.loop_wanted([A, B], True, "mass-ride")
        assert not routing.loop_wanted([A, B, A], False, "mass-ride")

    def test_the_points_of_a_loop_end_at_the_start(self) -> None:
        assert routing.loop_points([A, B], True) == [A, B, A]
        assert routing.loop_points([A, B, C], True) == [A, B, C, A]
        assert routing.loop_points([A, B, A], True) == [A, B, A]
        assert routing.loop_points([A, B], False) == [A, B]

    def test_the_stats_come_from_the_traced_pieces(self) -> None:
        pieces = [piece_at(i, w) for i, w in enumerate([1, 2, 3, 4, 3, 9, 8, 1])]
        stats = routing.loop_stats(pieces, [(0, 4), (4, 8)])
        assert stats == {"shared_m": 200.0, "return_m": 400.0, "overlap_pct": 50.0}

    def test_an_untraced_way_back_has_no_stats(self) -> None:
        assert routing.loop_stats([], [(0, 4), 1500.0]) is None
        assert routing.loop_stats([], [(0, 4)]) is None


def test_a_dials_loop_defaults_off() -> None:
    assert routing.Dials().loop is False
    # Appended, so earlier positional uses are unchanged; a re-route's heading came after it,
    # then its keep-going-ahead flag (v0.10.1).
    assert [f.name for f in dataclasses.fields(routing.Dials)][-3:] == [
        "loop",
        "heading",
        "ahead_only",
    ]


def test_the_overlap_threshold_is_below_the_search_alternates_overlap() -> None:
    # A loop's way back and a candidate's overlap are different things, both documented.
    assert refine.LOOP_OVERLAP_OK < refine.ALT_OVERLAP
    assert presets.PRESETS["mass-ride"].name == "mass-ride"


# --- Fewer repeats (the owner, 2026-10-18) --------------------------------------------


def legs_read(*legs: list[int], tiers: str | None = None) -> refine.Analysis:
    """A plan's reading over these legs, each a list of ways, 100 m a piece."""
    ways = [w for leg in legs for w in leg]
    read = loop_read(ways, [], tiers)
    edges, along = [], 0.0
    for leg in legs[:-1]:
        along += 100.0 * len(leg)
        edges.append(along)
    read.via_m = edges
    return read


A_LEG = list(range(1, 21))  # 2 km
B_LEG = list(range(21, 41))


class TestRepeats:
    def test_a_leg_on_an_earlier_leg_s_ways_repeats_them(self) -> None:
        read = legs_read(A_LEG, B_LEG, [50, *A_LEG[5:15], 51])
        assert refine.repeated_by_leg(read) == [0.0, 0.0, 1000.0]

    def test_the_ends_of_a_leg_are_how_a_stop_is_reached(self) -> None:
        # Out along 20 and back along it: the stop's spur is not a repeat.
        read = legs_read(A_LEG, [20, *B_LEG])
        assert refine.repeated_by_leg(read) == [0.0, 0.0]

    def test_a_repeat_may_buy_half_its_length_of_equally_calm_riding(self) -> None:
        ctx = context(rate=10.0, maxcalm=True)
        repeats = legs_read(A_LEG, B_LEG, A_LEG)  # 2 km ridden twice
        assert sum(refine.repeated_by_leg(repeats)) == 1800.0
        fresh = legs_read(A_LEG, B_LEG, list(range(100, 128)))  # 2.8 km, nothing repeated
        assert refine.fewer_repeats_better(fresh, repeats, ctx)
        longer = legs_read(A_LEG, B_LEG, list(range(100, 130)))  # 3 km: 1 km more for 0.9
        assert not refine.fewer_repeats_better(longer, repeats, ctx)

    def test_a_repeat_never_buys_busier_riding(self) -> None:
        ctx = context(rate=10.0, maxcalm=True)
        repeats = legs_read(A_LEG, B_LEG, A_LEG)
        fresh = list(range(100, 120))
        assert refine.fewer_repeats_better(legs_read(A_LEG, B_LEG, fresh), repeats, ctx)
        lts4 = legs_read(A_LEG, B_LEG, fresh, tiers="1" * 40 + "4" + "1" * 19)
        assert not refine.fewer_repeats_better(lts4, repeats, ctx)
        lts3 = legs_read(A_LEG, B_LEG, fresh, tiers="1" * 40 + "3" + "1" * 19)
        assert not refine.fewer_repeats_better(lts3, repeats, ctx)

    def test_not_even_a_few_metres_of_lts4(self) -> None:
        ctx = context(rate=10.0, maxcalm=True)
        repeats = legs_read(A_LEG, B_LEG, A_LEG)
        fresh = legs_read(A_LEG, B_LEG, list(range(100, 120)))
        fresh.lts4_m = 10.0  # inside the ranking's 15 m tie step, past the hold's 1 m
        assert not refine.fewer_repeats_better(fresh, repeats, ctx)

    def test_the_numbers_are_the_documented_ones(self) -> None:
        assert refine.REPEAT_WEIGHT == 0.5
        assert refine.REPEAT_STOP_M == 100.0


def three_leg_trip(last: str = "again") -> dict:
    summary = {"length": 2.0, "time": 100.0, "cost": 100.0}
    return {
        "legs": [
            {"shape": "a", "summary": dict(summary)},
            {"shape": "b", "summary": dict(summary)},
            {"shape": last, "summary": dict(summary)},
        ],
        "summary": {"length": 6.0, "time": 300.0, "cost": 300.0},
    }


def three_leg_context(group: bool = False) -> refine.Context:
    ctx = context(rate=10.0, maxcalm=True, group=group)
    ctx.request = {
        "locations": [
            {"lon": BASE[0] + i * 0.02, "lat": BASE[1], "type": "break"} for i in range(4)
        ],
        "costing": "bicycle",
    }
    return ctx


def three_leg_readings(**lasts) -> dict:
    out = {("a", "b", "again"): legs_read(A_LEG, B_LEG, A_LEG)}
    for name, ways in lasts.items():
        out[("a", "b", name)] = legs_read(A_LEG, B_LEG, ways)
    return out


class TestFewerRepeats:
    def test_a_leg_that_repeats_is_asked_again_and_a_fresh_way_kept(self, monkeypatch) -> None:
        world = LoopWorld(monkeypatch, three_leg_readings(R1=list(range(100, 124))), [("R1", 2.4)])
        trip, info = refine.fewer_repeats(three_leg_trip(), three_leg_context())
        assert [leg["shape"] for leg in trip["legs"]] == ["a", "b", "R1"]
        assert info["changed"] == 1 and info["was_m"] == 1800.0 and info["repeated_m"] == 0.0
        assert world.excluded(0), "the repeated stretch is excluded"
        locations = world.requests[0]["locations"]
        assert [loc["lon"] for loc in locations] == pytest.approx([BASE[0] + 0.04, BASE[0] + 0.06])

    def test_a_busier_way_is_not_taken(self, monkeypatch) -> None:
        busy = legs_read(A_LEG, B_LEG, list(range(100, 120)), tiers="1" * 40 + "4" * 20)
        readings_ = three_leg_readings()
        readings_[("a", "b", "busy")] = busy
        LoopWorld(monkeypatch, readings_, [("busy", 2.0), ("busy", 2.0)])
        trip, info = refine.fewer_repeats(three_leg_trip(), three_leg_context())
        assert [leg["shape"] for leg in trip["legs"]] == ["a", "b", "again"]
        assert info["changed"] == 0 and info["tried"] == len(refine.REPEAT_THINNING)

    def test_a_mass_ride_keeps_its_route(self, monkeypatch) -> None:
        world = LoopWorld(monkeypatch, three_leg_readings(), [])
        trip, info = refine.fewer_repeats(three_leg_trip(), three_leg_context(group=True))
        assert trip == three_leg_trip() and info["tried"] == 0 and not world.requests

    def test_a_plan_without_repeats_asks_nothing(self, monkeypatch) -> None:
        readings_ = {("a", "b", "fresh"): legs_read(A_LEG, B_LEG, list(range(100, 120)))}
        world = LoopWorld(monkeypatch, readings_, [])
        _trip, info = refine.fewer_repeats(three_leg_trip("fresh"), three_leg_context())
        assert info["tried"] == 0 and not world.requests

    def test_a_loop_s_way_back_is_left_to_make_loop(self, monkeypatch) -> None:
        world = LoopWorld(monkeypatch, three_leg_readings(), [])
        ctx = three_leg_context()
        ctx.loop_overlap = 0.9
        _trip, info = refine.fewer_repeats(three_leg_trip(), ctx)
        assert info["tried"] == 0 and not world.requests
