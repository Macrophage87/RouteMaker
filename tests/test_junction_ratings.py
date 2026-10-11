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

    def test_a_rated_junction_stands_for_its_own_nodes_within_15_m(self) -> None:
        # A red crossing 10 m on is the same junction's other node: the riders' "easy" is the
        # junction's colour and cost, not that node's red.
        red = m.assess(junction(m=10.0, crossed=(LTS4,)))
        easy = m.assess(junction(m=0.0, crossed=(LTS4,), rating=2))
        (merged,) = m.merge_nearby([easy, red])
        assert merged.rating == 2 and merged.severity is None
        assert merged.cost_ft == m.ALL_WAY_STOP_FT

    def test_a_rating_never_swallows_the_junctions_beyond_15_m(self) -> None:
        # Easy at 0 m, a signalised LTS 4 crossing at 40 m and an unsignalised one at 80 m: one
        # chain of nearby events, but the two crossings are other junctions and keep their red.
        easy = m.assess(junction(m=0.0, crossed=(LTS4,), rating=2))
        signal = m.assess(junction(m=40.0, crossed=(LTS4,), control=Control.SIGNAL))
        red = m.assess(junction(m=80.0, crossed=(LTS4,), control=Control.NONE))
        (unrated,) = m.merge_nearby([signal, red])
        (merged,) = m.merge_nearby([easy, signal, red])
        assert merged.severity == "red" and merged.flagged
        assert merged.cost_ft >= unrated.cost_ft > m.ALL_WAY_STOP_FT

    def test_hard_beside_another_red_crossing_adds_up_as_any_two_do(self) -> None:
        hard = m.assess(junction(m=0.0, rating=4))
        red = m.assess(junction(m=40.0, crossed=(LTS4,), control=Control.NONE))
        (merged,) = m.merge_nearby([hard, red])
        assert merged.severity == "red"
        assert merged.cost_ft == min(
            max(hard.cost_ft, red.cost_ft) + m.MERGED_SHARE * min(hard.cost_ft, red.cost_ft),
            m.MAX_CROSSING_FT,
        )
        assert merged.cost_ft > 3000.0

    def test_easy_keeps_a_cost_below_its_own_75_ft(self) -> None:
        # A right turn off an LTS 4 road onto a quiet one: the model's 15 ft, under easy's 75 ft.
        right = junction(movement=Movement.RIGHT, incoming=LTS4, outgoing=QUIET)
        model = m.assess(right)
        assert model is not None and model.cost_ft == m.RIGHT_FROM_BUSY_FT == 15.0
        rated = m.assess(replace(right, rating=2))
        assert rated is not None and rated.rating == 2
        assert rated.cost_ft == 15.0 < m.RATING_COST_FT[2]

    def test_easy_never_costs_more_than_the_model_and_adds_nothing_where_it_has_nothing(
        self,
    ) -> None:
        assert m.assess(junction(rating=2)) is None
        along = junction(incoming=LTS4, outgoing=LTS4, crossed=(QUIET,), control=Control.CROSS_STOP)
        model = m.assess(along)
        rated = m.assess(replace(along, rating=2))
        if model is None:
            assert rated is None
        else:
            assert rated is not None and rated.cost_ft == min(m.ALL_WAY_STOP_FT, model.cost_ft)

    def test_a_rated_signalised_crossing_keeps_its_mass_ride_group(self) -> None:
        def crossing(at: float, name: str, rating=None):
            road = replace(LTS4, names=frozenset({name}), ways=frozenset({hash(name) % 1000}))
            return junction(m=at, crossed=(road,), control=Control.SIGNAL, rating=rating)

        plain = [crossing(0.0, "a"), crossing(300.0, "b"), crossing(600.0, "c")]
        assert [e.group for e in m.assess_route(plain, group=True)] == [1, 1, 1]
        rated = [crossing(0.0, "a"), crossing(300.0, "b", 4), crossing(600.0, "c")]
        events = m.assess_route(rated, group=True)
        assert [e.group for e in events] == [1, 1, 1]
        assert events[1].rating == 4 and events[1].group_severity

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
