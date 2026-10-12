"""The hill seek (`core.hillseek`): which categorised climbs near the line are worth
asking the router for, the points that ask for them uphill, which climbs a route
rides, and how they are said. OWNER-DECISIONS 205, FOLLOWUP-HILL-SEEK.

All pure: the climbs are made here, and the router is a stand-in (`ask`). The plan's
own use of it is in tests/test_route_dials.py (`TestHillSeek`).
"""

from __future__ import annotations

import json
import math

import pytest

from core import hillseek as hs
from core import routing

START = (-77.0, 38.9)
# 0.1 degrees east: about 8.7 km.
END = (-76.9, 38.9)
KX = 111_320.0 * math.cos(math.radians(38.9))
KY = 110_540.0
SPAN = 0.1 * KX


def east(metres: float) -> float:
    return metres / KX


def north(metres: float) -> float:
    return metres / KY


def climb(
    ident: str = "a",
    category: str = "4",
    gain: float = 90.0,
    at_m: float = 3000.0,
    north_m: float = 0.0,
    length_m: float = 1000.0,
    westward: bool = False,
    **kw,
) -> hs.Climb:
    """A straight climb along the parallel `north_m` north of the line, its foot
    `at_m` east of START (its summit `length_m` further east, or west)."""
    lat = START[1] + north(north_m)
    sign = -1 if westward else 1
    n = 10
    line = tuple((START[0] + east(at_m + sign * length_m * i / n), lat) for i in range(n + 1))
    return hs.Climb(
        id=ident,
        category=category,
        length_m=length_m,
        gain_m=gain,
        grade_pct=round(100 * gain / length_m, 1),
        line=line,
        **kw,
    )


def straight(*stops) -> list[tuple[float, float]]:
    """A route through `stops` (metres east, metres north of START), a vertex every
    50 m."""
    out: list[tuple[float, float]] = []
    for (x0, y0), (x1, y1) in zip(stops, stops[1:], strict=False):
        n = max(1, round(math.hypot(x1 - x0, y1 - y0) / 50))
        for i in range(n + (1 if (x1, y1) == stops[-1] else 0)):
            f = i / n
            out.append((START[0] + east(x0 + (x1 - x0) * f), START[1] + north(y0 + (y1 - y0) * f)))
    return out


def doc(*rows, version: int = 1) -> dict:
    return {"version": version, "climbs": list(rows)}


def raw(**kw) -> dict:
    base = {
        "id": "abc",
        "c": "4",
        "l": 1200,
        "r": 90,
        "g": 7.5,
        "x": -77.0,
        "y": 38.91,
        "line": [[-77.01, 38.9], [-77.0, 38.91]],
    }
    base.update(kw)
    return base


class TestTheFile:
    def test_an_entry_is_read_with_its_keys(self) -> None:
        (one,) = hs.parse(doc(raw(u=1, n="Capital Crescent Trail")))
        assert one.id == "abc"
        assert one.category == "4"
        assert one.length_m == 1200
        assert one.gain_m == 90
        assert one.grade_pct == 7.5
        assert one.foot == (-77.01, 38.9)
        assert one.summit == (-77.0, 38.91)
        assert one.unpaved
        assert one.name == "Capital Crescent Trail"

    def test_paved_and_unnamed_by_default(self) -> None:
        (one,) = hs.parse(doc(raw()))
        assert not one.unpaved
        assert one.name is None

    @pytest.mark.parametrize(
        "bad",
        [
            {"c": "U"},
            {"line": [[-77.0, 38.9]]},
            {"l": 0},
            {"l": "long"},
            {"line": None},
        ],
    )
    def test_an_entry_that_is_not_a_climb_is_left_out(self, bad) -> None:
        good = raw(id="good")
        assert [c.id for c in hs.parse(doc(raw(**bad), good))] == ["good"]

    def test_a_missing_key_is_left_out(self) -> None:
        broken = raw()
        del broken["r"]
        assert hs.parse(doc(broken)) == ()

    @pytest.mark.parametrize("value", [doc(raw(), version=2), {"climbs": []}, [], {"version": 1}])
    def test_another_format_is_not_read(self, value) -> None:
        assert hs.parse(value) is None

    def test_a_missing_file_is_none(self, tmp_path) -> None:
        assert hs.load(tmp_path / "nothing.json") is None

    def test_a_missing_file_is_logged_once(self, tmp_path, caplog) -> None:
        path = tmp_path / "nothing.json"
        with caplog.at_level("WARNING", logger="core.hillseek"):
            hs.load(path)
            hs.load(path)
        said = [r for r in caplog.records if "no climbs file" in r.getMessage()]
        assert len(said) == 1
        assert str(path) in said[0].getMessage()
        # Back, then gone again: said again.
        path.write_text(json.dumps(doc(raw())))
        assert hs.load(path) is not None
        path.unlink()
        caplog.clear()
        with caplog.at_level("WARNING", logger="core.hillseek"):
            assert hs.load(path) is None
        assert any("no climbs file" in r.getMessage() for r in caplog.records)

    def test_a_file_that_is_not_json_is_none(self, tmp_path) -> None:
        path = tmp_path / "climbs.json"
        path.write_text("{not json")
        assert hs.load(path) is None

    def test_read_again_when_it_changes(self, tmp_path) -> None:
        path = tmp_path / "climbs.json"
        path.write_text(json.dumps(doc(raw(id="one"))))
        assert [c.id for c in hs.load(path)] == ["one"]
        path.write_text(json.dumps(doc(raw(id="two"), raw(id="three"))))
        assert [c.id for c in hs.load(path)] == ["two", "three"]

    def test_the_committed_file_is_read(self) -> None:
        climbs = hs.load()
        assert climbs is not None and len(climbs) > 1000
        assert {c.category for c in climbs} <= set(hs.CATEGORY_RANK)

    def test_the_ranks_put_hc_first_and_cat_5_last(self) -> None:
        ranks = [hs.CATEGORY_RANK[c] for c in ("HC", "1", "2", "3", "4", "5")]
        assert ranks == sorted(ranks, reverse=True)
        assert len(set(ranks)) == 6


class TestTheCorridor:
    def test_the_estimate_is_circuity_times_the_way_plus_the_climb(self) -> None:
        c = climb(at_m=3000.0, length_m=1000.0)
        way = hs._metres(START, c.foot) + hs._metres(c.summit, END)
        assert hs.estimate_m(START, END, (c,)) == pytest.approx(hs.CIRCUITY * way + 1000.0)

    def test_two_climbs_in_order_count_the_way_between(self) -> None:
        a = climb("a", at_m=1000.0, length_m=1000.0)
        b = climb("b", at_m=5000.0, length_m=1000.0)
        way = SPAN - 2000.0
        assert hs.estimate_m(START, END, (a, b)) == pytest.approx(
            hs.CIRCUITY * way + 2000.0, rel=1e-3
        )

    def test_no_climbs_is_the_straight_line_with_circuity(self) -> None:
        # The plane's metres and the sphere's differ by a few in ten thousand here.
        assert hs.estimate_m(START, END, ()) == pytest.approx(hs.CIRCUITY * SPAN, rel=2e-3)

    def test_the_budget_binds(self) -> None:
        on_line = climb("on", north_m=0.0)
        off_line = climb("off", north_m=3000.0)
        tight = hs.estimate_m(START, END, (on_line,)) + 1.0
        assert [c.id for c in hs.in_corridor([on_line, off_line], START, END, tight)] == ["on"]
        wide = hs.estimate_m(START, END, (off_line,)) + 1.0
        assert {c.id for c in hs.in_corridor([on_line, off_line], START, END, wide)} == {
            "on",
            "off",
        }

    def test_the_corridor_widens_with_the_budget(self) -> None:
        climbs = [climb(str(k), north_m=500.0 * k) for k in range(8)]
        counts = [
            len(hs.in_corridor(climbs, START, END, ratio * hs.CIRCUITY * SPAN))
            for ratio in (1.05, 1.25, 1.5)
        ]
        assert counts == sorted(counts)
        assert counts[0] < counts[-1]

    def test_avoiding_gravel_leaves_out_the_unpaved(self) -> None:
        dirt = climb("dirt", unpaved=True)
        road = climb("road", at_m=5000.0)
        budget = 2 * SPAN
        assert {c.id for c in hs.in_corridor([dirt, road], START, END, budget)} == {"dirt", "road"}
        assert [c.id for c in hs.in_corridor([dirt, road], START, END, budget, True)] == ["road"]

    def test_higher_categories_first_then_gain_then_the_shorter(self) -> None:
        climbs = [
            climb("cat5", category="5", gain=60.0),
            climb("cat4 far", category="4", gain=90.0, north_m=800.0),
            climb("cat4 near", category="4", gain=90.0),
            climb("cat4 more", category="4", gain=120.0, north_m=1500.0),
            climb("cat3", category="3", gain=170.0, north_m=2000.0),
        ]
        near = hs.in_corridor(climbs, START, END, 3 * SPAN)
        assert [c.id for c in near] == ["cat3", "cat4 more", "cat4 near", "cat4 far", "cat5"]


class TestProposals:
    def test_nothing_near_asks_nothing(self) -> None:
        assert hs.propose([], START, END, 2 * SPAN) == []

    def test_the_pair_then_the_best_then_the_next(self) -> None:
        a = climb("a", category="3", at_m=5000.0)
        b = climb("b", category="4", at_m=1000.0)
        c = climb("c", category="5", at_m=7000.0, length_m=600.0)
        proposals = hs.propose([a, b, c], START, END, 2 * SPAN)
        # The pair is ridden in the shorter order: b (west) first. The pair's route
        # covers b, so the third call is the next climb, not b alone.
        assert [[x.id for x in p] for p in proposals] == [["b", "a"], ["a"], ["c"]]

    def test_the_pairs_partner_is_not_asked_for_again(self) -> None:
        a = climb("a", category="3", at_m=5000.0)
        b = climb("b", category="4", at_m=1000.0)
        assert [[x.id for x in p] for p in hs.propose([a, b], START, END, 2 * SPAN)] == [
            ["b", "a"],
            ["a"],
        ]

    def test_the_limit_holds(self) -> None:
        climbs = [climb(str(k), at_m=500.0 + 1500.0 * k, length_m=600.0) for k in range(5)]
        assert len(hs.propose(climbs, START, END, 3 * SPAN)) == hs.MAX_CANDIDATES
        assert len(hs.propose(climbs, START, END, 3 * SPAN, limit=1)) == 1
        assert hs.propose(climbs, START, END, 3 * SPAN, limit=0) == []

    def test_no_pair_past_the_budget(self) -> None:
        a = climb("a", at_m=2000.0)
        b = climb("b", at_m=2000.0, north_m=2500.0)
        budget = max(hs.estimate_m(START, END, (x,)) for x in (a, b)) + 1.0
        assert hs.estimate_m(START, END, hs.ordered(START, END, a, b)) > budget
        assert [[x.id for x in p] for p in hs.propose([a, b], START, END, budget)] == [
            ["a"],
            ["b"],
        ]

    def test_two_sides_of_one_hill_are_not_a_pair_nor_both_asked(self) -> None:
        up_east = climb("east side", at_m=3000.0)
        # The other side: from 2 km further east, up westward to the same summit.
        up_west = climb("west side", at_m=5000.0, westward=True)
        assert up_east.summit == pytest.approx(up_west.summit)
        assert not hs.apart(up_east, up_west)
        other = climb("other", at_m=6000.0, north_m=400.0, length_m=600.0)
        proposals = hs.propose([up_east, up_west, other], START, END, 3 * SPAN)
        ids = [[x.id for x in p] for p in proposals]
        assert ["west side"] not in ids
        assert all("west side" not in p for p in ids)

    def test_apart_needs_both_ends_apart(self) -> None:
        a = climb("a", at_m=3000.0)
        same_foot = climb("b", at_m=3000.0, north_m=10.0, length_m=2000.0)
        assert not hs.apart(a, same_foot)
        assert hs.apart(a, climb("c", at_m=5000.0))


class TestViaPoints:
    def test_from_near_the_foot_to_near_the_summit_in_order(self) -> None:
        c = climb(at_m=3000.0, length_m=1000.0)
        vias = hs.via_points(c)
        xs = [(lon - START[0]) * KX for lon, _ in vias]
        assert xs == sorted(xs)
        assert xs[0] == pytest.approx(3000.0 + hs.VIA_INSET_M, abs=1.0)
        assert xs[-1] == pytest.approx(4000.0 - hs.VIA_INSET_M, abs=1.0)

    def test_westward_climbs_are_asked_for_westward(self) -> None:
        c = climb(at_m=5000.0, length_m=1000.0, westward=True)
        xs = [(lon - START[0]) * KX for lon, _ in hs.via_points(c)]
        assert xs == sorted(xs, reverse=True)
        assert xs[0] == pytest.approx(5000.0 - hs.VIA_INSET_M, abs=1.0)

    def test_a_short_climb_has_a_middle_point(self) -> None:
        assert len(hs.via_points(climb(length_m=500.0))) == 3

    def test_a_long_climb_has_more_up_to_the_cap(self) -> None:
        assert len(hs.via_points(climb(length_m=4000.0))) == 4
        assert len(hs.via_points(climb(at_m=0.0, length_m=20_000.0))) == hs.MAX_VIAS

    def test_the_points_lie_on_the_line(self) -> None:
        c = climb(north_m=700.0)
        assert all(lat == pytest.approx(c.foot[1]) for _, lat in hs.via_points(c))

    def test_the_points_of_a_pair_are_each_climbs_in_turn(self) -> None:
        a, b = climb("a", at_m=1000.0), climb("b", at_m=5000.0)
        assert hs.vias_of((a, b)) == hs.via_points(a) + hs.via_points(b)


class TestRidden:
    def test_a_route_along_the_climb_rides_it(self) -> None:
        c = climb(at_m=3000.0, length_m=1000.0)
        route = straight((0, 0), (SPAN, 0))
        (found,) = hs.ridden(route, [c])
        assert found.climb is c
        # Where the route first comes within reach of the summit, and last of the foot
        # before it: within the reach of the true places, inside the climb.
        assert 3000.0 <= found.start_m <= 3000.0 + hs.ON_CLIMB_M + 1.0
        assert 4000.0 - hs.ON_CLIMB_M - 1.0 <= found.summit_m <= 4000.0

    def test_down_it_is_not_riding_it(self) -> None:
        c = climb(at_m=5000.0, length_m=1000.0, westward=True)
        assert hs.ridden(straight((0, 0), (SPAN, 0)), [c]) == []

    def test_passing_beside_it_is_not_riding_it(self) -> None:
        near = climb(north_m=hs.ON_CLIMB_M - 10.0)
        far = climb(north_m=hs.ON_CLIMB_M + 10.0)
        route = straight((0, 0), (SPAN, 0))
        assert [r.climb.id for r in hs.ridden(route, [near])] == ["a"]
        assert hs.ridden(route, [far]) == []

    def test_passing_beside_it_on_a_diagonal_is_not_riding_it(self) -> None:
        """A route at 45 degrees, its climb 60 m off it square: inside each segment's
        box, so the distance itself must turn it away."""
        off = 60.0 / math.sqrt(2)

        def diagonal(dx: float, dy: float) -> tuple:
            return tuple(
                (START[0] + east(1000 + dx + d), START[1] + north(1000 + dy + d))
                for d in range(0, 1001, 100)
            )

        on = hs.Climb("on", "4", 1414.0, 90.0, 6.4, diagonal(0, 0))
        beside = hs.Climb("beside", "4", 1414.0, 90.0, 6.4, diagonal(-off, off))
        route = straight((0, 0), (3000, 3000))
        assert [r.climb.id for r in hs.ridden(route, [on, beside])] == ["on"]

    def test_part_of_it_is_not_riding_it(self) -> None:
        c = climb(at_m=3000.0, length_m=1000.0)
        route = straight((0, 0), (3500, 0), (3500, 2000), (SPAN, 2000))
        assert hs.ridden(route, [c]) == []

    def test_leaving_it_and_coming_back_is_not_riding_it(self) -> None:
        c = climb(at_m=3000.0, length_m=1000.0)
        route = straight((0, 0), (3500, 0), (3500, 300), (3600, 300), (3600, 0), (SPAN, 0))
        assert hs.ridden(route, [c]) == []
        # A shorter loop off it, inside the 1.3 times allowed, is still riding it.
        nudge = straight((0, 0), (3500, 0), (3500, 40), (3600, 40), (3600, 0), (SPAN, 0))
        assert len(hs.ridden(nudge, [c])) == 1

    def test_down_it_then_back_up_starts_it_at_the_turn(self) -> None:
        c = climb(at_m=3000.0, length_m=1000.0)
        # From the east down the climb, and away north at its foot: not ridden.
        route = straight((4500, 0), (2800, 0), (2800, 500))
        assert hs.ridden(route, [c]) == []
        # Down it, past its foot, back up it, and away north at the summit: it starts
        # where the route last passed the foot, on the way up, not on the way down.
        route = straight((4500, 0), (2800, 0), (4000, 0), (4000, 500))
        (found,) = hs.ridden(route, [c])
        assert 1900.0 <= found.start_m <= 1900.0 + hs.ON_CLIMB_M + 1.0
        assert 2900.0 - hs.ON_CLIMB_M - 1.0 <= found.summit_m <= 2900.0

    def test_in_the_order_reached(self) -> None:
        a = climb("a", at_m=5000.0)
        b = climb("b", at_m=1000.0)
        route = straight((0, 0), (SPAN, 0))
        assert [r.climb.id for r in hs.ridden(route, [a, b])] == ["b", "a"]

    def test_a_route_of_one_point_rides_nothing(self) -> None:
        assert hs.ridden([START], [climb()]) == []

    def test_the_climbs_a_route_could_ride(self) -> None:
        on = climb("on")
        off = climb("off", north_m=3000.0)
        route_m = SPAN + 100.0
        assert [c.id for c in hs.candidates_for_naming([on, off], START, END, route_m)] == ["on"]
        assert len(hs.candidates_for_naming([on, off], START, END, 3 * SPAN)) == 2


class TestInWords:
    def test_category_length_grade_and_gain_us_first(self) -> None:
        c = hs.Climb("a", "4", 1300.0, 80.0, 6.2, ((0.0, 0.0), (0.01, 0.0)))
        assert hs.climb_words(c) == (
            "Category 4 climb, 0.8 miles (1.3 km) at 6.2%, 262 ft (80 m) gained"
        )

    def test_one_mile_is_a_mile(self) -> None:
        c = hs.Climb("a", "5", 1609.0, 45.0, 2.8, ((0.0, 0.0), (0.01, 0.0)))
        assert hs.climb_words(c).startswith("Category 5 climb, 1.0 mile (1.6 km) at 2.8%")

    def test_hc_is_said_in_full(self) -> None:
        c = hs.Climb("a", "HC", 18_700.0, 893.0, 4.8, ((0.0, 0.0), (0.1, 0.0)))
        assert hs.climb_words(c).startswith("Hors catégorie (HC) climb, 11.6 miles (18.7 km)")
        assert hs.climb_words(c).endswith("2,930 ft (893 m) gained")

    def test_the_sentence_says_where(self) -> None:
        c = climb(at_m=3000.0, length_m=1000.0, gain=90.0, name="Rock Creek Trail", unpaved=True)
        item = hs.Ridden(c, 1609.344, 2 * 1609.344)
        assert hs.sentence(item) == (
            "At 1.0 mi (1.6 km): Category 4 climb, 0.6 miles (1.0 km) at 9.0%, 295 ft (90 m)"
            " gained, to the summit at 2.0 mi (3.2 km). On the Rock Creek Trail. Mostly unpaved."
        )
        assert hs.sentence(item, scale=2.0).startswith("At 2.0 mi (3.2 km)")
        assert "to the summit at 4.0 mi (6.4 km)." in hs.sentence(item, scale=2.0)

    def test_the_entry_and_the_row(self) -> None:
        c = climb(at_m=3000.0, length_m=1000.0)
        item = hs.Ridden(c, 1000.0, 2000.0)
        entry = hs.entry(item, scale=1.5)
        assert entry["kind"] == "climb"
        assert (entry["from_m"], entry["to_m"]) == (1500, 3000)
        assert entry["from_mi"] == round(1500 / 1609.344, 2)
        assert entry["text"] == hs.sentence(item, 1.5)
        assert entry["surface"] is None
        row = hs.row(item, scale=1.5)
        assert row["category"] == "4"
        assert (row["from_m"], row["to_m"]) == (1500, 3000)
        assert row["length_m"] == 1000
        assert row["gain_m"] == 90
        assert row["text"] == hs.climb_words(c)

    def test_entries_go_in_route_order(self) -> None:
        description = [{"kind": "stretch", "from_m": m} for m in (0, 1000, 2000)]
        added = [{"kind": "climb", "from_m": 1500}, {"kind": "climb", "from_m": 1000}]
        merged = hs.with_entries(description, added)
        assert [(e["kind"], e["from_m"]) for e in merged] == [
            ("stretch", 0),
            ("climb", 1000),
            ("stretch", 1000),
            ("climb", 1500),
            ("stretch", 2000),
        ]
        late = hs.with_entries(description, [{"kind": "climb", "from_m": 5000}])
        assert late[-1]["kind"] == "climb"

    def test_no_description_stays_none_and_nothing_added_is_unchanged(self) -> None:
        assert hs.with_entries(None, [{"from_m": 0}]) is None
        description = [{"kind": "stretch", "from_m": 0}]
        assert hs.with_entries(description, []) is description


class Asker:
    """The router, stood in for: answers each call from `answers` (a trip, None for
    no route, or an exception), and records the points it was asked through."""

    def __init__(self, *answers) -> None:
        self.answers = list(answers)
        self.asked: list[list] = []

    def __call__(self, vias):
        self.asked.append(vias)
        answer = self.answers.pop(0) if self.answers else {"legs": [{}]}
        if isinstance(answer, Exception):
            raise answer
        return answer


def trip(name: str) -> dict:
    return {"legs": [{"shape": ""}], "name": name}


class TestSeek:
    def run(self, climbs, ask, left=lambda: 10.0, already=(), **kw):
        return hs.seek(climbs, START, END, 2 * SPAN, already, ask, left, **kw)

    def test_no_climbs_file_asks_nothing_and_says_so(self) -> None:
        ask = Asker()
        out = self.run(None, ask)
        assert ask.asked == []
        assert out.limited == "no_climbs"
        assert out.trips == []
        assert out.info() == {"near": 0, "asked": 0, "found": 0, "limited": "no_climbs"}

    def test_each_proposal_is_asked_for_through_its_climbs(self) -> None:
        a = climb("a", category="3", at_m=5000.0)
        b = climb("b", category="4", at_m=1000.0)
        c = climb("c", category="5", at_m=7000.0, length_m=600.0)
        ask = Asker(trip("pair"), trip("a"), trip("c"))
        out = self.run([a, b, c], ask)
        assert ask.asked == [hs.vias_of((b, a)), hs.via_points(a), hs.via_points(c)]
        assert [t["name"] for t in out.trips] == ["pair", "a", "c"]
        assert [[x.id for x in p] for p in out.asked_for] == [["b", "a"], ["a"], ["c"]]
        assert out.info() == {"near": 3, "asked": 3, "found": 3, "limited": None}

    def test_no_route_is_skipped(self) -> None:
        a = climb("a", category="3", at_m=5000.0)
        b = climb("b", category="4", at_m=1000.0)
        c = climb("c", category="5", at_m=7000.0, length_m=600.0)
        out = self.run([a, b, c], Asker(None, {"legs": []}, trip("c")))
        assert [t["name"] for t in out.trips] == ["c"]
        assert [[x.id for x in p] for p in out.asked_for] == [["c"]]
        assert out.asked == 3

    def test_out_of_time_ends_it(self) -> None:
        a = climb("a", category="3", at_m=5000.0)
        b = climb("b", category="4", at_m=1000.0)
        c = climb("c", category="5", at_m=7000.0, length_m=600.0)
        ask = Asker(trip("pair"), hs.OutOfTime("no"), trip("c"))
        out = self.run([a, b, c], ask)
        assert len(ask.asked) == 2
        assert [t["name"] for t in out.trips] == ["pair"]
        assert out.limited == "time"

    def test_too_little_time_left_asks_no_more(self) -> None:
        a = climb("a", category="3", at_m=5000.0)
        b = climb("b", category="4", at_m=1000.0)
        times = iter([10.0, hs.ROUND_MIN_S - 0.1])
        ask = Asker()
        out = self.run([a, b], ask, left=lambda: next(times))
        assert len(ask.asked) == 1
        assert out.limited == "time"
        assert out.asked == 1

    def test_a_climb_the_router_already_rides_is_not_asked_for(self) -> None:
        a = climb("a", category="3", at_m=5000.0)
        b = climb("b", category="4", at_m=1000.0, north_m=600.0)
        own = straight((0, 0), (SPAN, 0))
        ask = Asker()
        out = self.run([a, b], ask, already=[own])
        assert ask.asked == [hs.via_points(b)]
        assert [c.id for c in out.near] == ["a", "b"]

    def test_nothing_in_the_corridor_asks_nothing(self) -> None:
        ask = Asker()
        out = hs.seek([climb(north_m=20_000.0)], START, END, SPAN, (), ask, lambda: 10.0)
        assert ask.asked == []
        assert out.limited is None
        assert out.info()["near"] == 0

    def test_gravel_avoided_is_passed_on(self) -> None:
        ask = Asker()
        self.run([climb(unpaved=True)], ask, avoid_gravel=True)
        assert ask.asked == []


class TestThePlansCall:
    """`routing.hill_seek`: what the router is asked, and what it does with what it
    answers. The router is a stand-in for `_transport`."""

    @pytest.fixture
    def climbs_file(self, tmp_path, monkeypatch):
        c = climb("a", at_m=3000.0, length_m=1000.0, north_m=500.0)
        path = tmp_path / "climbs.json"
        path.write_text(
            json.dumps(
                doc(
                    raw(
                        id="a",
                        c=c.category,
                        l=c.length_m,
                        r=c.gain_m,
                        g=c.grade_pct,
                        line=[list(p) for p in c.line],
                    )
                )
            )
        )
        monkeypatch.setattr(hs, "CLIMBS_FILE", path)
        return c

    def plan_parts(self):
        request = {
            "locations": [
                {"lon": START[0], "lat": START[1], "type": "break"},
                {"lon": END[0], "lat": END[1], "type": "break"},
            ],
            "costing": "bicycle",
            "alternates": 3,
        }
        own = {"summary": {"length": SPAN * 1.1 / 1000}, "legs": []}
        deadline = routing.Deadline(routing.clock() + 30.0, 10.0)
        return request, own, deadline

    def test_through_the_climb_without_alternates(self, climbs_file, monkeypatch) -> None:
        calls = []

        def transport(url, payload, timeout):
            calls.append((url, payload, timeout))
            return {"trip": trip("through")}

        monkeypatch.setattr(routing, "_transport", transport)
        request, own, deadline = self.plan_parts()
        out = routing.hill_seek([own], [list(START), list(END)], request, "standard", deadline, 1.5)
        assert len(calls) == 1
        url, payload, timeout = calls[0]
        assert url.endswith("/route")
        assert "alternates" not in payload
        assert payload["locations"][0] == request["locations"][0]
        assert payload["locations"][-1] == request["locations"][-1]
        middle = payload["locations"][1:-1]
        assert [(p["lon"], p["lat"]) for p in middle] == hs.via_points(climbs_file)
        assert {p["type"] for p in middle} == {"through"}
        assert timeout <= routing.ALTERNATES_TIMEOUT_S
        assert [t["name"] for t in out.trips] == ["through"]
        # The plan's own request is left as it was.
        assert request["alternates"] == 3 and len(request["locations"]) == 2

    def test_a_refusal_is_no_route_and_a_dead_router_is_out_of_time(
        self, climbs_file, monkeypatch
    ) -> None:
        request, own, deadline = self.plan_parts()

        def refuse(url, payload, timeout):
            raise routing.RouterRefused(400, 442, "no path")

        monkeypatch.setattr(routing, "_transport", refuse)
        out = routing.hill_seek([own], [list(START), list(END)], request, "standard", deadline, 1.5)
        assert out.trips == [] and out.asked == 1 and out.limited is None

        def dead(url, payload, timeout):
            raise routing.RouterUnavailable("down")

        monkeypatch.setattr(routing, "_transport", dead)
        out = routing.hill_seek([own], [list(START), list(END)], request, "standard", deadline, 1.5)
        assert out.trips == [] and out.limited == "time"

    def test_the_budget_is_the_ratio_of_the_routers_own(self, climbs_file, monkeypatch) -> None:
        monkeypatch.setattr(routing, "_transport", lambda *a: {"trip": trip("x")})
        request, own, deadline = self.plan_parts()
        # At 1.0 nothing past the straight line fits; at 1.5 the climb does.
        out = routing.hill_seek([own], [list(START), list(END)], request, "standard", deadline, 1.0)
        assert out.asked == 0
        out = routing.hill_seek([own], [list(START), list(END)], request, "standard", deadline, 1.5)
        assert out.asked == 1

    def test_no_time_left_in_the_plan_asks_nothing(self, climbs_file, monkeypatch) -> None:
        monkeypatch.setattr(routing, "_transport", lambda *a: {"trip": trip("x")})
        request, own, _ = self.plan_parts()
        deadline = routing.Deadline(routing.clock() + hs.TRACE_RESERVE_S + 1.0, 10.0)
        out = routing.hill_seek([own], [list(START), list(END)], request, "standard", deadline, 1.5)
        assert out.asked == 0 and out.limited == "time"

    def test_no_climbs_file_asks_nothing(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(hs, "CLIMBS_FILE", tmp_path / "none.json")
        called = []
        monkeypatch.setattr(routing, "_transport", lambda *a: called.append(a))
        request, own, deadline = self.plan_parts()
        out = routing.hill_seek([own], [list(START), list(END)], request, "standard", deadline, 1.5)
        assert called == [] and out.limited == "no_climbs"
