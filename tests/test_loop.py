"""Make it a loop (OWNER-DECISIONS 266): the way back by a different way.

`refine.make_loop` with the router and the readings of its routes replaced, as in
test_refine; and the plan's own rules (`routing.loop_wanted`, `loop_points`,
`loop_stats`).
"""

from __future__ import annotations

import dataclasses

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


def loop_context(max_m=None, preset="trailmaxxing") -> refine.Context:
    ctx = context(rate=10.0, maxcalm=True, max_m=max_m)
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
        assert info["fallback"] is None and info["tried"] == 1
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

    def test_the_first_way_back_within_the_ok_share_ends_the_asking(self, monkeypatch) -> None:
        world = LoopWorld(
            monkeypatch, readings(R1=[1] + list(range(101, 140))), [("R1", 4.0), ("R1", 4.0)]
        )
        _trip, info = refine.make_loop(two_leg_trip(), loop_context())
        assert info["tried"] == 1 and len(world.requests) == 1

    def test_among_those_within_the_ok_share_the_least_stressful_is_taken(
        self, monkeypatch
    ) -> None:
        ways = list(range(101, 141))
        ok_but_busy = loop_read(OUT, [1] * 4 + ways[4:], "1" * 40 + "1" * 20 + "3" * 20)
        ok_calm = loop_read(OUT, [1] * 4 + ways[4:])
        world = LoopWorld(
            monkeypatch,
            {
                ("out", "same"): loop_read(OUT, list(reversed(OUT))),
                ("out",): loop_read(OUT, []),
                ("out", "A"): ok_but_busy,
                ("out", "B"): ok_calm,
            },
            [("A", 4.0), ("B", 4.0)],
        )
        # The first within the share ends the asking, so make the first one a share past it.
        world.readings[("out", "A")] = loop_read(OUT, [1] * 20 + ways[20:])
        trip, info = refine.make_loop(two_leg_trip(), loop_context())
        assert [leg["shape"] for leg in trip["legs"]] == ["out", "B"]
        assert info["tried"] == 2

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

    def test_the_whole_loop_is_within_the_longest_ride_not_each_half(self, monkeypatch) -> None:
        # 4 km out and 4 km first back: the whole is 8 km. A way back of 5 km makes 9.
        LoopWorld(
            monkeypatch,
            readings(LONG=list(range(101, 141)), FITS=list(range(201, 241))),
            [("LONG", 5.0), ("FITS", 4.4)],
        )
        trip, info = refine.make_loop(two_leg_trip(), loop_context(max_m=8_600.0))
        assert [leg["shape"] for leg in trip["legs"]] == ["out", "FITS"]
        assert trip["summary"]["length"] * 1000.0 <= 8_600.0 and info["tried"] == 2

    def test_a_way_back_past_the_limit_every_time_is_the_out_and_back(self, monkeypatch) -> None:
        LoopWorld(monkeypatch, readings(LONG=list(range(101, 141))), [("LONG", 5.0)] * 4)
        trip0 = two_leg_trip()
        trip, info = refine.make_loop(trip0, loop_context(max_m=8_200.0))
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
    assert dataclasses.fields(routing.Dials)[-1].name == "loop"


def test_the_overlap_threshold_is_below_the_search_alternates_overlap() -> None:
    # A loop's way back and a candidate's overlap are different things, both documented.
    assert refine.LOOP_OVERLAP_OK < refine.ALT_OVERLAP
    assert presets.PRESETS["mass-ride"].name == "mass-ride"
