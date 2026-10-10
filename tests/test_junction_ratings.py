"""Riders' ratings of a junction in the intersection model (OWNER-DECISIONS 232).

"In some times the road is fine, but the intersection can be especially dangerous." An approved
rating sets the junction's cost and marker on every route through it, raising or lowering the
model's own figure, a junction of two quiet streets included.
"""

from __future__ import annotations

from dataclasses import replace

from test_intersections import LTS4, QUIET, junction
from test_junctions import raw

from core import junctions as core_junctions
from routemaker import intersections as m
from routemaker.intersections import Control, Movement, Rating

AT = (-77.0, 38.9)


def rating(level: int, lon: float = AT[0], lat: float = AT[1]) -> Rating:
    return Rating(1, lon, lat, level)


class TestRatedJunction:
    def test_a_quiet_junction_rated_hard_is_red_and_costs_an_lts4_crossing(self) -> None:
        quiet = junction(movement=Movement.LEFT, outgoing=QUIET)
        assert m.assess(quiet) is None
        event = m.assess(replace(quiet, rating=4))
        assert event is not None and event.flagged
        assert (event.severity, event.cost_ft, event.rating) == ("red", 3000.0, 4)
        assert event.kind == "rated" and event.reason == "Riders rate this junction hard"

    def test_takes_patience_is_orange(self) -> None:
        event = m.assess(junction(rating=3))
        assert event is not None and (event.severity, event.cost_ft) == ("orange", 1200.0)

    def test_a_red_crossing_rated_easy_loses_its_marker_and_most_of_its_cost(self) -> None:
        red = junction(crossed=(LTS4,), control=Control.NONE)
        before = m.assess(red)
        assert before is not None and before.severity == "red"
        after = m.assess(replace(red, rating=2))
        assert after is not None and not after.flagged and after.severity is None
        assert after.cost_ft == m.ALL_WAY_STOP_FT < before.cost_ft
        assert after.reason.endswith("Riders rate this junction easy")
        assert after.reason.startswith("Crossing")

    def test_the_group_reading_takes_the_rating_too(self) -> None:
        event = m.assess(junction(rating=4), group=True)
        assert event is not None and event.severity == "red"

    def test_a_rating_is_matched_within_15_m_of_the_node(self) -> None:
        near = rating(4, AT[0] + 0.0001, AT[1])  # about 9 m (29 ft) east
        far = rating(4, AT[0] + 0.0003, AT[1])  # about 26 m (85 ft)
        assert m.rating_at(*AT, [near]) == near
        assert m.rating_at(*AT, [far]) is None
        (rated,) = m.with_ratings([junction()], [near])
        assert rated.rating == 4
        (plain,) = m.with_ratings([junction()], [far])
        assert plain.rating is None

    def test_a_rated_junction_stands_for_its_other_nodes_when_merged(self) -> None:
        # A red crossing 30 m on, one junction as the rider meets it: the riders' "easy" is
        # the junction's colour and cost, not the other node's red.
        red = m.assess(junction(m=30.0, crossed=(LTS4,)))
        easy = m.assess(junction(m=0.0, crossed=(LTS4,), rating=2))
        (merged,) = m.merge_nearby([easy, red])
        assert merged.rating == 2 and merged.severity is None
        assert merged.cost_ft == m.ALL_WAY_STOP_FT

    def test_route_assessment_carries_the_rating(self) -> None:
        events = m.assess_route(m.with_ratings([junction()], [rating(3)]))
        assert [e.severity for e in events] == ["orange"]


class TestRatedJunctionsAreRead:
    def test_a_quiet_junction_is_read_only_where_riders_rated_it(self) -> None:
        quiet = raw(other_classes=("residential", "residential"))
        assert not core_junctions.wanted(quiet)
        assert core_junctions._rated(quiet, [rating(4, quiet.lon, quiet.lat)])
        assert not core_junctions._rated(quiet, [])
        # A bend with nothing meeting it is never a junction, rated or not.
        bend = raw(others=(), other_classes=(), in_way=10, out_way=10)
        assert not core_junctions._rated(bend, [rating(4, bend.lon, bend.lat)])


def test_the_plan_hands_its_approved_ratings_to_the_junction_reading(monkeypatch) -> None:
    from test_refine import context

    from core import refine

    seen = {}

    def events_of(raws, when, with_facility, locate, group=False, cut_short=(), ratings=()):
        seen["ratings"] = ratings
        return []

    monkeypatch.setattr(refine.junctions, "events_of", events_of)
    ctx = replace(context(), junction_ratings=(rating(4),))
    assert refine.events_of_raws([], ctx, ctx.deadline) == []
    assert seen["ratings"] == (rating(4),)
