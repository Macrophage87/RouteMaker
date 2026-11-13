"""The intersection cost model (OWNER-DECISIONS items 165-169, 171, 172).

Each rule is pinned to the owner's words, and each number to the range the
literature review gives it ("Bicycle stress literature in depth",
reports/LTS-literature-review-2.md, "Crossing
penalties by control type and right of way", "Left turns, multi-lane merges
capped by box turns, and slip lanes"), because every value is a proposal the
owner will move: a test that fixes a value and not its reason would be moved
with it.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from routemaker import intersections as m
from routemaker import ridetime
from routemaker.intersections import Control, Junction, Movement, Road

QUIET = Road(2)
LTS3 = Road(3, speed_mph=25, lanes=2)  # LTS 3 by its traffic too (`by_traffic`)
LTS4 = Road(4, speed_mph=40, lanes=3)
ONEWAY_LTS3 = Road(3, speed_mph=30, lanes=2, oneway=True)


def junction(**fields) -> Junction:
    base = {
        "m": 0.0,
        "lon": -77.0,
        "lat": 38.9,
        "movement": Movement.STRAIGHT,
        "incoming": QUIET,
        "outgoing": QUIET,
    }
    return Junction(**(base | fields))


def cost(**fields) -> float:
    return m.cost_of(junction(**fields))[0]


def drawn(j: Junction, group: bool = False) -> bool:
    """Whether the planner would draw a marker at this junction."""
    event = m.assess(j, group)
    return event is not None and event.flagged


class TestMovement:
    @pytest.mark.parametrize(
        ("heading_in", "heading_out", "expected"),
        [
            (0, 0, Movement.STRAIGHT),
            (0, 30, Movement.STRAIGHT),
            (350, 20, Movement.STRAIGHT),
            (0, 90, Movement.RIGHT),
            (0, 270, Movement.LEFT),
            (270, 0, Movement.RIGHT),
            (90, 0, Movement.LEFT),
            (180, 100, Movement.LEFT),
            (10, 355, Movement.STRAIGHT),
        ],
    )
    def test_a_clockwise_change_is_a_right_turn(self, heading_in, heading_out, expected) -> None:
        assert m.movement_of(heading_in, heading_out) is expected

    def test_a_45_degree_change_is_a_turn(self) -> None:
        assert m.movement_of(0, 45) is Movement.RIGHT
        assert m.movement_of(0, 315) is Movement.LEFT

    def test_straight_is_within_the_named_angle(self) -> None:
        edge = m.STRAIGHT_MAX_DEG
        assert m.movement_of(0, edge) is Movement.STRAIGHT
        assert m.movement_of(0, edge + 1) is Movement.RIGHT
        assert m.movement_of(0, 360 - edge - 1) is Movement.LEFT


class TestCrossing:
    """Item 165: "an at-grade crossing of an LTS 3+ road costs a penalty"."""

    @pytest.mark.parametrize("group", [False, True])
    def test_an_event_carries_the_crossed_roads_mapped_names(self, group) -> None:
        """Item 230: `road_names` are matching keys, `road_display` is for saying."""
        road = Road(
            4, 40, 3, names=frozenset({"macarthur boulevard"}), display=("MacArthur Boulevard",)
        )
        event = m.assess(junction(crossed=(road,)), group)
        assert event is not None
        assert event.road_names == frozenset({"macarthur boulevard"})
        assert event.road_display == ("MacArthur Boulevard",)

    def test_the_mapped_names_are_not_part_of_a_roads_identity(self) -> None:
        keys = frozenset({"i-395"})
        assert Road(4, names=keys, display=("I-395",)) == Road(4, names=keys, display=())

    def test_neighbourhood_streets_cost_nothing_to_cross(self) -> None:
        """ "an at-grade crossing of an LTS 3+ road": a quiet cross street is not one."""
        assert cost(crossed=(QUIET,)) == 0
        assert cost(crossed=(Road(1), Road(2))) == 0
        assert m.assess(junction(crossed=(QUIET,))) is None

    def test_the_cost_is_capped(self) -> None:
        wild = Road(5, speed_mph=70, lanes=6, aadt=90_000)
        assert m.crossing_ft(wild, Control.NONE, 1) <= m.MAX_CROSSING_FT

    def test_grade_separated_roads_are_never_met(self) -> None:
        """ "no penalty for grade-separated crossings" (item 165). A bridge or
        underpass shares no node with the road it passes, so the router's trace
        has no junction there and the model is never asked: the route's
        junctions are the only input."""
        assert m.assess_route([]) == []
        assert m.penalty_m([]) == 0


class TestControl:
    def test_an_all_way_stop_is_the_literature_range(self) -> None:
        assert 50 <= m.crossing_ft(LTS4, Control.ALL_STOP, 1) <= 100

    def test_riding_along_a_busy_road_past_side_streets_is_not_flagged(self) -> None:
        along = junction(incoming=LTS3, outgoing=LTS3, crossed=(QUIET,), control=Control.NONE)
        assert not drawn(along)

    def test_riding_along_a_road_busier_than_the_cross_street_is_along(self) -> None:
        """At exactly the priority side's cost the label is "along"."""
        # A 25 mph four-lane road: LTS 3 by its traffic too (`by_traffic`).
        side = Road(3, speed_mph=25, lanes=2)
        event = m.assess(junction(incoming=LTS4, outgoing=LTS4, crossed=(side,)))
        assert event.cost_ft == m.PRIORITY_SIDE_FT
        assert event.kind == "along"


class TestByTraffic:
    """The owner, 2026-10-26, of Sheridan St NW across Piney Branch Rd NW: "a busy 2 lane
    each way road. It's only LTS2 because it also has a bike lane. Given that there's a
    stop sign and no cross stop, this intersection should be weighted much more highly."
    A road the rider gives way to is read by its traffic, not its bike lane."""

    # Piney Branch Rd NW at Sheridan St (OSM ways 6054706 and 1111094169): lanes=4,
    # two-way, 30 mph, cycleway:both=lane; LTS 2 on the map. Sheridan St: 20 mph.
    PINEY_BRANCH = Road(
        2, speed_mph=30, lanes=2, oneway=False, display=("Piney Branch Road Northwest",)
    )
    SHERIDAN = Road(2, speed_mph=20, lanes=1, oneway=False)

    def crossing(self, road: Road = PINEY_BRANCH, **fields) -> Junction:
        return junction(
            **({"incoming": self.SHERIDAN, "crossed": (road,), "control": Control.STOP} | fields)
        )

    def test_straight_on_from_one_multilane_road_into_the_next_is_not_joining(self) -> None:
        # A name change at the node (`continues` is False), nothing mapped or a stop: both
        # roads read busy by their traffic, so it is riding along.
        other = replace(self.PINEY_BRANCH, names=frozenset({"other"}))
        for control in (Control.NONE, Control.STOP):
            j = junction(incoming=self.PINEY_BRANCH, outgoing=other, control=control)
            assert m.assess(j) is None

    def test_a_rated_junction_still_names_the_map_tier(self) -> None:
        event = m.assess(replace(self.crossing(), rating=4))
        assert event.rating == 4
        assert event.crossed_tier == 2

    def test_a_protected_lane_does_not_make_a_busy_road_easier_to_cross(self) -> None:
        # The owner, 2026-10-31: "a protected bike lane on a busy road is just as hard to
        # cross". A 35 mph road, one lane each way, 15,000 a day, LTS 1 on the map.
        protected = Road(1, speed_mph=35, lanes=1, oneway=False, aadt=15_000, urban=True)
        plain = replace(protected, tier=4)
        for control in (Control.STOP, Control.NONE, Control.SIGNAL):
            for when in (None, ridetime.WEEKDAY_RUSH):
                a = m.assess(self.crossing(protected, control=control), when=when)
                b = m.assess(self.crossing(plain, control=control), when=when)
                assert a.cost_ft == b.cost_ft, (control, when)
        left = junction(incoming=protected, outgoing=self.SHERIDAN, movement=Movement.LEFT)
        plain_left = replace(left, incoming=plain)
        assert m.assess(left).cost_ft == m.assess(plain_left).cost_ft > 0

    def test_a_mass_ride_keeps_the_roads_own_tier(self) -> None:
        """396: a Mass Ride's junctions go by the roads' stress ratings."""
        assert m.assess(self.crossing(), group=True) is None


class TestMovementCosts:
    def test_straight_on_from_one_busy_road_onto_a_busier_is_not_a_turn(self) -> None:
        on = junction(incoming=Road(3), outgoing=Road(4))
        assert m.cost_of(on)[0] == 0
        assert m.assess(on) is None

    def test_the_onto_cost_is_capped(self) -> None:
        wild = Road(5, speed_mph=60, lanes=4, aadt=60_000)
        assert cost(movement=Movement.LEFT, outgoing=wild) <= m.MAX_CROSSING_FT
        # And a left from a quiet street across it to a quiet one.
        across = junction(movement=Movement.LEFT, crossed=(wild,))
        assert m.cost_of(across)[1] == "left_across"
        assert m.cost_of(across)[0] == m.MAX_CROSSING_FT

    def test_straight_along_a_busy_road_costs_nothing_by_itself(self) -> None:
        """Riding on along a busy road with nothing crossed: no turn off it."""
        assert cost(incoming=LTS3, outgoing=LTS3) == 0
        assert m.assess(junction(incoming=LTS3, outgoing=LTS3)) is None

    def test_a_left_from_a_quiet_street_onto_a_busy_road_is_onto_not_across(self) -> None:
        """A left onto LTS 3 past a crossed LTS 4 at the same node is the left
        onto (`left_across` is a left from quiet street to quiet street)."""
        turn = junction(movement=Movement.LEFT, outgoing=Road(3), crossed=(Road(4),))
        assert m.cost_of(turn)[1] == "left_onto"

    def test_a_left_off_a_busy_road_is_not_also_a_crossing_of_the_road_it_meets(self) -> None:
        """The rider on LTS 3 turning left onto a quiet street, past a crossed LTS 4
        road at the same node: the left's own cost, not the crossing's (a left
        from a quiet street is the one that crosses)."""
        turn = junction(movement=Movement.LEFT, incoming=LTS3, outgoing=QUIET, crossed=(LTS4,))
        assert m.cost_of(turn)[1] == "left_from"
        assert m.cost_of(turn)[0] == pytest.approx(m.left_from_ft(LTS3, Control.NONE))

    def test_the_merge_is_uncapped_unsignalised_and_box_turn_capped_at_a_signal(self) -> None:
        wide = Road(4, speed_mph=30, lanes=6)
        assert m.merge_ft(wide) == pytest.approx(5 * 0.30 * 5280)
        assert m.merge_ft(wide, Control.SIGNAL) == m.BOX_TURN_CAP_FT
        assert m.BOX_TURN_CAP_FT == 750.0

    def test_at_a_signal_the_whole_left_is_capped_at_a_box_turn(self) -> None:
        """Item 186, "Cap at box turn": "At signals a left never costs more than
        the two-stage box-turn alternative (about 500 ft equivalent)", 750 ft since 468. The round-1
        review's case: two lanes a direction on LTS 4, 910 ft before."""
        wide = Road(4, speed_mph=40, lanes=2)
        assert m.left_from_ft(wide, Control.SIGNAL) == m.BOX_TURN_CAP_FT
        assert m.left_from_ft(Road(4, speed_mph=60, lanes=4), Control.SIGNAL) == m.BOX_TURN_CAP_FT
        turn = junction(movement=Movement.LEFT, incoming=wide, control=Control.SIGNAL)
        assert not drawn(turn)
        # Without a signal the box turn is no cap.
        assert m.left_from_ft(wide, Control.NONE) > m.BOX_TURN_CAP_FT
        # A narrow road's signalized left stays below the cap.
        assert m.left_from_ft(Road(3, lanes=1), Control.SIGNAL) == pytest.approx(
            m.LEFT_ACROSS_ONCOMING_FT[3] * m.SIGNALISED_LEFT_FACTOR
        )


class TestSlipLanes:
    def test_a_slip_lane_adds_a_penalty(self) -> None:
        """ "Sliplanes should get a penalty too." (item 169): about an
        unsignalized LTS 3 crossing, 800 ft."""
        along = junction(incoming=LTS3, outgoing=LTS3, crossed=(QUIET,), slip_lane=True)
        assert (
            cost(incoming=LTS3, outgoing=LTS3, crossed=(QUIET,), slip_lane=True) == m.SLIP_LANE_FT
        )
        event = m.assess(along)
        assert event is not None and event.kind == "slip_lane"
        assert event.severity == m.ORANGE

    def test_a_signal_halves_it(self) -> None:
        assert m.slip_ft(Control.SIGNAL) == m.SLIP_LANE_FT * m.SIGNALISED_SLIP_FACTOR

    def test_the_slip_lane_is_about_the_busiest_road_there(self) -> None:
        """The channel leaves or joins the busiest road at the node."""
        along = junction(incoming=Road(3), outgoing=Road(3), slip_lane=True, links=(Road(4),))
        event = m.assess(along)
        assert event.kind == "slip_lane"
        assert event.crossed_tier == 4
        assert (
            event.reason
            == "Crossing a slip lane off a heavy-traffic road (LTS 4), no signal mapped"
        )

    def test_a_crossed_turn_channel_is_a_slip_lane_not_a_road_crossing(self) -> None:
        """Review r1, B1: the road's own turn channel is not a road crossed;
        where the route crosses its path (item 195; `core.junctions.crossed_links`
        says where) it is the slip lane's cost."""
        along = junction(incoming=Road(4), outgoing=Road(4), slip_lane=True, links=(Road(4),))
        event = m.assess(along)
        assert event.kind == "slip_lane" and event.cost_ft == m.SLIP_LANE_FT
        assert event.severity == m.ORANGE

    def test_a_slip_lane_beside_a_quiet_street_is_nothing(self) -> None:
        assert m.assess(junction(slip_lane=True)) is None
        assert cost(slip_lane=True) == 0


class TestNeighbourhoodStopSigns:
    def test_near_zero_and_never_flagged(self) -> None:
        """ "Don't overpenalize neighborhood roads with stop signs though. They
        rarely cause issue. Also DC law lets bikes roll through if safe." (item
        171; the owner's account, not legal advice)."""
        for control in (Control.STOP, Control.ALL_STOP, Control.NONE, Control.SIGNAL):
            value = cost(crossed=(QUIET,), control=control)
            assert value <= m.NEIGHBOURHOOD_STOP_FT
            assert m.assess(junction(crossed=(QUIET,), control=control)) is None
        assert m.NEIGHBOURHOOD_STOP_FT < m.ORANGE_MIN_FT / 10
        # A stop (or an all-way stop) is what costs the little there is.
        for control in (Control.STOP, Control.ALL_STOP):
            assert cost(crossed=(QUIET,), control=control) == m.NEIGHBOURHOOD_STOP_FT
        for control in (Control.NONE, Control.SIGNAL, Control.CROSS_STOP):
            assert cost(crossed=(QUIET,), control=control) == 0

    def test_the_stop_sign_cost_is_below_every_busy_crossing_cost(self) -> None:
        assert m.NEIGHBOURHOOD_STOP_FT < m.PRIORITY_SIDE_FT * 2


class TestSeverity:
    def test_a_signalised_crossing_is_not_flagged(self) -> None:
        assert not drawn(junction(crossed=(Road(4),), control=Control.SIGNAL))

    def test_the_priority_side_is_not_flagged(self) -> None:
        assert not drawn(junction(crossed=(Road(4),), control=Control.CROSS_STOP))


class TestReasons:
    def test_the_owners_example_sentence(self) -> None:
        """ "Left turn across 4-lane 35 mph road, no signal" (item 172's example),
        with the metric in brackets (the owner's units rule)."""
        event = m.assess(
            junction(
                movement=Movement.LEFT, incoming=Road(4, speed_mph=35, lanes=2), outgoing=QUIET
            )
        )
        assert event.reason == ("Left turn across a 4-lane 35 mph (56 km/h) road, no signal mapped")

    def test_miles_per_hour_come_first(self) -> None:
        text = m.reason_of("crossing", Road(4, speed_mph=45, lanes=1, oneway=True), Control.STOP)
        assert text.index("45 mph") < text.index("72 km/h")
        assert "1-lane" in text and "stop sign on your side" in text

    def test_a_one_way_road_counts_its_lanes_once(self) -> None:
        assert "2-lane" in m.describe_road(Road(3, lanes=2, oneway=True))
        assert "4-lane" in m.describe_road(Road(3, lanes=2, oneway=False))

    def test_unknown_lanes_and_speed_name_the_tier_in_the_legends_words(self) -> None:
        assert m.describe_road(Road(3)) == "busy road (LTS 3)"
        assert m.describe_road(Road(4)) == "heavy-traffic road (LTS 4)"
        assert m.describe_road(Road(5)) == "road best avoided (Avoid)"
        assert m.reason_of("crossing", Road(4), Control.NONE) == (
            "Crossing a heavy-traffic road (LTS 4), no signal mapped"
        )

    def test_an_8_lane_road_takes_an(self) -> None:
        assert m.reason_of("crossing", Road(4, lanes=4), Control.NONE).startswith(
            "Crossing an 8-lane road"
        )

    @pytest.mark.parametrize(
        ("kind", "start"),
        [
            ("crossing", "Crossing a"),
            ("left_onto", "Left turn onto a"),
            ("left_from", "Left turn across a"),
            ("slip_lane", "Crossing a slip lane off a"),
        ],
    )
    def test_each_kind_has_its_words(self, kind, start) -> None:
        assert m.reason_of(kind, LTS3, Control.NONE).startswith(start)

    @pytest.mark.parametrize("control", list(Control))
    def test_each_control_is_worded(self, control) -> None:
        assert m.CONTROL_WORDS[control] in m.reason_of("crossing", LTS3, control)


class TestRoute:
    def test_events_come_in_route_order(self) -> None:
        events = m.assess_route(
            [
                junction(m=900.0, crossed=(LTS4,)),
                junction(m=100.0, crossed=(LTS3,)),
            ]
        )
        assert [e.m for e in events] == [100.0, 900.0]

    def test_the_signalised_nodes_are_carried_for_the_junction_delay(self) -> None:
        """Hunt J5: the delay model reads the junction model's signals by point
        (`signal_points`), each node of a junction merged into one event kept."""
        name = frozenset({"connecticut avenue northwest"})
        north = Road(4, oneway=True, names=name, ways=frozenset({1}))
        south = Road(4, oneway=True, names=name, ways=frozenset({2}))
        events = m.assess_route(
            [
                junction(m=100.0, lon=-77.0, crossed=(north,), control=Control.SIGNAL),
                junction(m=111.0, lon=-77.0001, crossed=(south,)),
            ]
        )
        # The control is shared across the junction's nodes, so both are signalised.
        assert len(events) == 1
        assert m.signal_points(events) == {(-77.0, 38.9), (-77.0001, 38.9)}
        unsignalised = m.assess_route([junction(m=100.0, crossed=(north,))])
        assert m.signal_points(unsignalised) == frozenset()
        assert m.signal_points(None) == frozenset()

    def test_a_signals_big_road_and_stop_sign_price_are_carried_for_the_delay(self) -> None:
        """The owner, 2026-11-08: outside the cities a signal across a road of 4+ lanes or
        40 mph+ waits as a big road's, and a beg-button crossing is held below a stop sign
        across the same road (`big_signal_points`, `stop_extra_ft`)."""
        wide = Road(3, lanes=2, oneway=False, names=frozenset({"beulah street"}))
        narrow = Road(3, lanes=1, oneway=False, speed_mph=35.0, names=frozenset({"a street"}))
        fast = Road(3, lanes=1, oneway=False, default_speed_mph=40.0)
        for road, big in ((wide, True), (narrow, False), (fast, True)):
            assert m.big_road(road) is big
            events = m.assess_route([junction(crossed=(road,), control=Control.SIGNAL)])
            assert (m.big_signal_points(events) == {(-77.0, 38.9)}) is big
            stop = m.assess(junction(crossed=(road,), control=Control.STOP))
            assert m.stop_extra_ft(events)[(-77.0, 38.9)] == pytest.approx(
                stop.cost_ft - events[0].cost_ft
            )
        # A stop sign is no signal: nothing carried.
        stopped = m.assess_route([junction(crossed=(wide,), control=Control.STOP)])
        assert m.big_signal_points(stopped) == frozenset()
        assert m.stop_extra_ft(stopped) == {}
        assert m.stop_extra_ft(None) == {}

    def test_a_rated_signals_stop_sign_price_is_the_models_own(self) -> None:
        """The 2026-11-08 hunt, J3-4: a rating costs the same whatever the control, so a
        rated signal's stop sign had cost 0 ft over it, and its lights ranked cheaper."""
        prim = Road(4, lanes=2, oneway=False, speed_mph=40.0, names=frozenset({"p"}))
        across = junction(crossed=(prim,), control=Control.SIGNAL)
        expected = m.stop_extra_ft(m.assess_route([across]))[(-77.0, 38.9)]
        assert expected > 0.0
        for rating in (2, 3, 4):
            events = m.assess_route([replace(across, rating=rating)])
            # Before: 0 ft at ratings 3 and 4.
            assert m.stop_extra_ft(events)[(-77.0, 38.9)] == pytest.approx(expected)

    def test_the_riders_own_big_road_is_carried_apart_from_the_crossed_one(self) -> None:
        """The signal review, 2026-11-08: the junction-delay model's busiest road at a
        signal counts the rider's own 4-lane or 40 mph road (`own_big_signal_points`),
        which before was not carried at all; the crossed road's reading stays its own."""
        wide = Road(3, lanes=2, oneway=False, names=frozenset({"beulah street"}))
        side = Road(3, lanes=1, oneway=False, names=frozenset({"a street"}))
        along = junction(incoming=wide, outgoing=wide, crossed=(side,), control=Control.SIGNAL)
        events = m.assess_route([replace(along, continues=True)])
        assert m.own_big_signal_points(events) == {(-77.0, 38.9)}
        assert m.big_signal_points(events) == frozenset()
        across = junction(crossed=(wide,), control=Control.SIGNAL)
        assert m.own_big_signal_points(m.assess_route([across])) == frozenset()
        assert m.own_big_signal_points(None) == frozenset()

    def test_a_divided_roads_merged_event_keeps_both_nodes_big_road_reading(self) -> None:
        name = frozenset({"telegraph road"})
        north = Road(4, oneway=True, lanes=2, names=name, ways=frozenset({1}))
        south = Road(4, oneway=True, lanes=2, names=name, ways=frozenset({2}))
        events = m.assess_route(
            [
                junction(m=100.0, lon=-77.0, crossed=(north,), control=Control.SIGNAL),
                junction(m=111.0, lon=-77.0001, crossed=(south,)),
            ]
        )
        assert len(events) == 1
        # Each carriageway's two lanes one way are not four lanes on their own.
        assert m.big_signal_points(events) == frozenset()
        assert set(m.stop_extra_ft(events)) == {(-77.0, 38.9), (-77.0001, 38.9)}

    def test_different_roads_at_one_junction_add_half(self) -> None:
        a = Road(3, names=frozenset({"a street"}))
        b = Road(3, names=frozenset({"b street"}))
        events = m.assess_route([junction(m=100.0, crossed=(a,)), junction(m=130.0, crossed=(b,))])
        one = m.assess(junction(crossed=(a,))).cost_ft
        assert len(events) == 1
        assert events[0].cost_ft == pytest.approx(one * (1 + m.MERGED_SHARE))

    def test_far_apart_junctions_stay_separate(self) -> None:
        gap = m.MERGE_WITHIN_M + 1
        events = m.assess_route(
            [junction(m=0.0, crossed=(LTS3,)), junction(m=gap, crossed=(LTS3,))]
        )
        assert len(events) == 2

    def test_unnamed_roads_are_not_taken_for_one_road(self) -> None:
        events = m.assess_route(
            [junction(m=0.0, crossed=(Road(3),)), junction(m=10.0, crossed=(Road(3),))]
        )
        one = m.assess(junction(crossed=(Road(3),))).cost_ft
        assert events[0].cost_ft == pytest.approx(one * (1 + m.MERGED_SHARE))

    def test_a_chain_of_close_junctions_is_one(self) -> None:
        """Each within the distance of the one before: one junction, chained."""
        step = m.MERGE_WITHIN_M - 5
        events = m.assess_route(
            [junction(m=i * step, crossed=(Road(3, names=frozenset({f"r{i}"})),)) for i in range(3)]
        )
        assert len(events) == 1

    def test_junctions_exactly_the_merge_distance_apart_are_one(self) -> None:
        events = m.assess_route(
            [
                junction(m=0.0, crossed=(LTS3,)),
                junction(m=m.MERGE_WITHIN_M, crossed=(LTS3,)),
            ]
        )
        assert len(events) == 1

    def test_the_refuge_is_only_for_a_divided_roads_carriageways(self) -> None:
        """Review r2, SHOULD_FIX 2, and item 196: two crossings of one-way roads
        of different ways with a name in common. One way crossed at two nodes,
        or a two-way road, counts once with no credit."""
        name = frozenset({"georgia avenue"})
        one_way = Road(4, oneway=True, names=name, ways=frozenset({7}))
        alone = m.assess(junction(crossed=(one_way,))).cost_ft
        same_way = m.assess_route(
            [junction(m=0.0, crossed=(one_way,)), junction(m=20.0, crossed=(one_way,))]
        )
        assert [e.cost_ft for e in same_way] == [pytest.approx(alone)]
        two_way = Road(4, oneway=False, names=name, ways=frozenset({8}))
        both_ways = m.assess_route(
            [
                junction(m=0.0, crossed=(two_way,)),
                junction(m=20.0, crossed=(replace(two_way, ways=frozenset({9})),)),
            ]
        )
        assert [e.cost_ft for e in both_ways] == [pytest.approx(alone)]
        # A carriageway whose ways are unknown is not taken for one either.
        unknown = replace(one_way, ways=frozenset())
        assert m.assess_route(
            [junction(m=0.0, crossed=(unknown,)), junction(m=20.0, crossed=(one_way,))]
        )[0].cost_ft == pytest.approx(alone)

    def test_a_turn_onto_a_road_and_a_left_off_it_add(self) -> None:
        """Review r2: a right onto an arterial and a left off it 30 m later was
        1,312 ft, less than the left alone (1,750). They are two conflicts."""
        name = frozenset({"rockville pike"})
        pike = Road(4, speed_mph=40, lanes=2, names=name, ways=frozenset({1}))
        on = junction(m=0.0, movement=Movement.RIGHT, outgoing=pike)
        off = junction(m=30.0, movement=Movement.LEFT, incoming=pike)
        (merged,) = m.assess_route([on, off])
        right, left = m.assess(on).cost_ft, m.assess(off).cost_ft
        assert merged.cost_ft == pytest.approx(left + right * m.MERGED_SHARE)
        assert merged.cost_ft > left

    def test_a_slip_lane_and_a_crossing_of_its_road_add(self) -> None:
        """Review r2: the Rockville Pike slip lanes 31 m apart were 600 ft, the
        refuge's; a slip lane and a crossing are two conflicts, 800 + 400."""
        name = frozenset({"rockville pike"})
        pike = Road(4, oneway=True, names=name, ways=frozenset({1}))
        slip = junction(m=0.0, slip_lane=True, links=(pike,))
        cross = junction(
            m=31.0, crossed=(replace(pike, ways=frozenset({2})),), control=Control.SIGNAL
        )
        (merged,) = m.assess_route([slip, cross])
        a, b = m.assess(slip).cost_ft, m.assess(cross).cost_ft
        assert merged.cost_ft == pytest.approx(max(a, b) + min(a, b) * m.MERGED_SHARE)

    def test_the_merged_colour_is_the_worst_not_the_costliest(self) -> None:
        """Mutant M03 (review r2): under Mass Ride the colour is the tier, so a
        cheaper event can be the red one."""
        costly = m.Event(
            0.0,
            0,
            0,
            "crossing",
            Movement.STRAIGHT,
            Control.NONE,
            3000.0,
            m.ORANGE,
            "a",
            3,
            True,
            group_severity=True,
            road_names=frozenset({"a"}),
        )
        cheap = m.Event(
            10.0,
            0,
            0,
            "crossing",
            Movement.STRAIGHT,
            Control.SIGNAL,
            300.0,
            m.RED,
            "b",
            4,
            True,
            group_severity=True,
            road_names=frozenset({"b"}),
        )
        (merged,) = m.merge_nearby([costly, cheap])
        assert merged.severity == m.RED
        assert merged.cost_ft == pytest.approx(3000.0 + 300.0 * m.MERGED_SHARE)

    def test_the_total_cost_is_in_metres_of_riding(self) -> None:
        events = m.assess_route([junction(crossed=(LTS3,))])
        assert m.penalty_m(events) == pytest.approx(events[0].cost_ft / m.FEET_PER_METRE)


class TestContinuing:
    """Review r2, SHOULD_FIX 1: going straight on along one road whose tier
    rises at a node is not "joining" it."""

    def test_straight_on_along_the_same_road_is_not_joining_it(self) -> None:
        on = junction(incoming=Road(2), outgoing=Road(4), continues=True)
        assert m.cost_of(on)[0] == 0
        assert m.assess(on) is None
        # A crossing there is still a crossing.
        crossing = junction(incoming=Road(2), outgoing=Road(4), continues=True, crossed=(Road(4),))
        assert m.assess(crossing).kind == "crossing"

    def test_straight_onto_another_road_is_joining_it(self) -> None:
        join = junction(incoming=Road(2), outgoing=Road(4))
        event = m.assess(join)
        assert event.kind == "straight_onto" and event.severity == m.RED
        assert event.reason.startswith("Joining a heavy-traffic road")


class TestSharedControl:
    """Review r2, blocker: the nodes of one junction take its strongest control
    (Plyers Mill Rd across Connecticut Ave: one carriageway's node reads the
    signal, the other none)."""

    name = frozenset({"connecticut avenue"})

    def carriageways(self, first, second, gap=20.0, other_name=None):
        a = Road(4, oneway=True, names=self.name, ways=frozenset({1}))
        b = Road(4, oneway=True, names=other_name or self.name, ways=frozenset({2}))
        return [
            junction(m=0.0, crossed=(a,), control=first),
            junction(m=gap, crossed=(b,), control=second),
        ]

    def test_an_all_way_stop_is_shared_but_a_stop_sign_is_not(self) -> None:
        shared = m.share_controls(self.carriageways(Control.ALL_STOP, Control.NONE))
        assert [j.control for j in shared] == [Control.ALL_STOP, Control.ALL_STOP]
        kept = m.share_controls(self.carriageways(Control.STOP, Control.NONE))
        assert [j.control for j in kept] == [Control.STOP, Control.NONE]
        # And the signal beats the all-way stop.
        both = m.share_controls(self.carriageways(Control.ALL_STOP, Control.SIGNAL))
        assert [j.control for j in both] == [Control.SIGNAL, Control.SIGNAL]

    def test_not_across_different_roads_or_beyond_the_merge_distance(self) -> None:
        other = m.share_controls(
            self.carriageways(Control.SIGNAL, Control.NONE, other_name=frozenset({"x st"}))
        )
        assert [j.control for j in other] == [Control.SIGNAL, Control.NONE]
        far = m.share_controls(
            self.carriageways(Control.SIGNAL, Control.NONE, gap=m.MERGE_WITHIN_M + 1)
        )
        assert [j.control for j in far] == [Control.SIGNAL, Control.NONE]
        edge = m.share_controls(
            self.carriageways(Control.SIGNAL, Control.NONE, gap=m.MERGE_WITHIN_M)
        )
        assert edge[1].control is Control.SIGNAL

    def test_not_between_side_streets_along_the_road_ridden(self) -> None:
        """Riding straight along a road, a signal at one side street is not the
        next side street's: the road ridden along is not what they are about."""
        along = Road(4, names=self.name)
        first = junction(
            m=0.0,
            incoming=along,
            outgoing=along,
            continues=True,
            crossed=(Road(3, names=frozenset({"a st"})),),
            control=Control.SIGNAL,
        )
        turn = junction(
            m=30.0,
            movement=Movement.LEFT,
            incoming=along,
            outgoing=Road(2, names=frozenset({"b st"})),
        )
        shared = m.share_controls([first, turn])
        assert shared[1].control is Control.NONE

    def test_a_turn_off_a_divided_road_shares_with_its_far_carriageway(self) -> None:
        """The left off one carriageway and the crossing of the other are one
        junction: the road turned off is what the turn is about."""
        near = Road(4, oneway=True, names=self.name, ways=frozenset({1}))
        far = Road(4, oneway=True, names=self.name, ways=frozenset({2}))
        side = Road(2, names=frozenset({"a st"}))
        turn = junction(m=0.0, movement=Movement.LEFT, incoming=near, outgoing=side)
        cross = junction(
            m=12.0,
            crossed=(far,),
            continues=True,
            control=Control.SIGNAL,
            incoming=side,
            outgoing=side,
        )
        shared = m.share_controls([turn, cross])
        assert shared[0].control is Control.SIGNAL

    def test_a_turn_onto_a_divided_road_shares_with_its_near_carriageway(self) -> None:
        """Across the near carriageway, then left onto the far one: the rider
        is on the side street between the two nodes."""
        near = Road(4, oneway=True, names=self.name, ways=frozenset({1}))
        far = Road(4, oneway=True, names=self.name, ways=frozenset({2}))
        side = Road(2, names=frozenset({"a st"}))
        cross = junction(
            m=0.0,
            crossed=(near,),
            continues=True,
            incoming=side,
            outgoing=side,
            control=Control.SIGNAL,
        )
        turn = junction(m=12.0, movement=Movement.LEFT, incoming=side, outgoing=far)
        assert m.share_controls([cross, turn])[1].control is Control.SIGNAL

    # Review r3, B2: two junctions along one named road, with the rider on that
    # road between them (a jog, a staggered junction), are two junctions.
    main = Road(4, names=frozenset({"main st"}), ways=frozenset({10}))
    a_st = Road(1, names=frozenset({"a st"}))
    b_st = Road(1, names=frozenset({"b st"}))

    def test_a_jog_left_onto_the_road_then_right_off_it_at_a_signal(self) -> None:
        onto = junction(m=0.0, movement=Movement.LEFT, incoming=self.a_st, outgoing=self.main)
        off = junction(
            m=35.0,
            movement=Movement.RIGHT,
            incoming=self.main,
            outgoing=self.b_st,
            control=Control.SIGNAL,
        )
        shared = m.share_controls([onto, off])
        assert [j.control for j in shared] == [Control.NONE, Control.SIGNAL]
        (event,) = [e for e in m.assess_route([onto, off]) if e.flagged]
        assert event.kind == "left_onto" and event.severity == m.RED

    def test_a_jog_right_onto_the_road_then_left_off_it_at_a_signal(self) -> None:
        onto = junction(m=0.0, movement=Movement.RIGHT, incoming=self.a_st, outgoing=self.main)
        off = junction(
            m=40.0,
            movement=Movement.LEFT,
            incoming=self.main,
            outgoing=self.b_st,
            control=Control.SIGNAL,
        )
        shared = m.share_controls([onto, off])
        assert [j.control for j in shared] == [Control.NONE, Control.SIGNAL]

    def test_a_signalised_left_off_the_road_then_a_left_back_onto_it(self) -> None:
        off = junction(
            m=0.0,
            movement=Movement.LEFT,
            incoming=self.main,
            outgoing=self.a_st,
            control=Control.SIGNAL,
        )
        onto = junction(m=30.0, movement=Movement.LEFT, incoming=self.a_st, outgoing=self.main)
        shared = m.share_controls([off, onto])
        assert [j.control for j in shared] == [Control.SIGNAL, Control.NONE]
        assert any(e.flagged and e.kind == "left_onto" for e in m.assess_route([off, onto]))

    def test_a_left_off_the_road_then_back_onto_it_crossing_its_own_lanes(self) -> None:
        """Gate 1, B2: in a real trace a left turn crosses its own road's
        opposite lanes (`crossed=(Main St,)`). That is not a road crossed: the
        signalized left off Main St and the left back onto it 30 m on are
        still two junctions, and the second keeps its warning."""
        off = junction(
            m=0.0,
            movement=Movement.LEFT,
            incoming=self.main,
            outgoing=self.a_st,
            crossed=(self.main,),
            control=Control.SIGNAL,
        )
        onto = junction(
            m=30.0,
            movement=Movement.LEFT,
            incoming=self.a_st,
            outgoing=self.main,
            crossed=(self.main,),
        )
        shared = m.share_controls([off, onto])
        assert [j.control for j in shared] == [Control.SIGNAL, Control.NONE]
        flagged = [e for e in m.assess_route([off, onto]) if e.flagged]
        assert [(e.kind, e.severity) for e in flagged] == [("left_onto", m.RED)]
        # With only the first turn's lanes crossed, or a right off at the
        # signal and the left back onto it crossing them, the same.
        bare = replace(onto, crossed=())
        assert m.share_controls([off, bare])[1].control is Control.NONE
        right_off = replace(off, movement=Movement.RIGHT, crossed=())
        assert m.share_controls([right_off, onto])[1].control is Control.NONE
        # A one-way road of the turn's name is a carriageway, and still counts.
        far = Road(4, oneway=True, names=self.main.names, ways=frozenset({11}))
        crossing = replace(onto, crossed=(far,))
        assert m.share_controls([off, crossing])[1].control is Control.SIGNAL

    def test_a_divided_roads_crossover_shares_with_its_left_turn(self) -> None:
        """MD 355's U-turn crossover: a left off one carriageway into the
        crossover, then 15 m on a left onto the other, each crossing a one-way
        carriageway of MD 355. One junction: a signal at one is the other's."""
        near = Road(4, oneway=True, names=frozenset({"md 355"}), ways=frozenset({1}))
        far = Road(4, oneway=True, names=frozenset({"md 355"}), ways=frozenset({2}))
        crossover = Road(1, names=frozenset({"way 577536224"}), ways=frozenset({3}))
        off = junction(
            m=0.0,
            movement=Movement.LEFT,
            incoming=near,
            outgoing=crossover,
            crossed=(far,),
            control=Control.SIGNAL,
        )
        onto = junction(
            m=15.0, movement=Movement.LEFT, incoming=crossover, outgoing=far, crossed=(far,)
        )
        assert m.share_controls([off, onto])[1].control is Control.SIGNAL
        # Unsignalized, both stay as they are.
        none = replace(off, control=Control.NONE)
        assert [j.control for j in m.share_controls([none, onto])] == [Control.NONE] * 2

    def test_a_jog_whose_turns_cross_their_own_road(self) -> None:
        """The jogs with the turns' own lanes crossed, as a trace has them."""
        onto = junction(
            m=0.0,
            movement=Movement.LEFT,
            incoming=self.a_st,
            outgoing=self.main,
            crossed=(self.main,),
        )
        off = junction(
            m=35.0,
            movement=Movement.RIGHT,
            incoming=self.main,
            outgoing=self.b_st,
            control=Control.SIGNAL,
        )
        assert m.share_controls([onto, off])[0].control is Control.NONE
        right_onto = junction(
            m=0.0, movement=Movement.RIGHT, incoming=self.a_st, outgoing=self.main
        )
        left_off = junction(
            m=40.0,
            movement=Movement.LEFT,
            incoming=self.main,
            outgoing=self.b_st,
            crossed=(self.main,),
            control=Control.SIGNAL,
        )
        assert m.share_controls([right_onto, left_off])[0].control is Control.NONE

    def test_two_crossings_of_one_road_from_different_streets(self) -> None:
        """Across Main St from A St, then 40 m on across it again from B St at
        a signal: the rider reached the second by another road."""
        first = junction(
            m=0.0, crossed=(self.main,), continues=True, incoming=self.a_st, outgoing=self.a_st
        )
        second = junction(
            m=40.0,
            crossed=(self.main,),
            continues=True,
            incoming=self.b_st,
            outgoing=self.b_st,
            control=Control.SIGNAL,
        )
        shared = m.share_controls([first, second])
        assert [j.control for j in shared] == [Control.NONE, Control.SIGNAL]
        assert any(e.flagged and e.severity == m.RED for e in m.assess_route([first, second]))

    def test_a_turn_onto_a_road_then_a_left_off_it_across_it(self) -> None:
        """17th St SW: right onto it from Constitution Ave at a signal, then
        18 m on a left off it across it onto a crosswalk. The rider rode 17th
        St between: the left is a junction of its own."""
        seventeenth = Road(4, names=frozenset({"17th street southwest"}), ways=frozenset({6}))
        constitution = Road(3, names=frozenset({"constitution avenue"}), ways=frozenset({7}))
        walk = Road(1, names=frozenset({"way 274416516"}), ways=frozenset({8}))
        onto = junction(
            m=0.0,
            movement=Movement.RIGHT,
            incoming=constitution,
            outgoing=seventeenth,
            control=Control.SIGNAL,
        )
        off = junction(
            m=18.0,
            movement=Movement.LEFT,
            incoming=seventeenth,
            outgoing=walk,
            crossed=(seventeenth,),
        )
        assert m.share_controls([onto, off])[1].control is Control.NONE

    def test_a_turn_onto_a_divided_road_then_a_left_off_it_across_its_far_side(self) -> None:
        """17th St SW's shape on a divided road: right onto its near carriageway
        at a signal, then 18 m on a left off it across the far one-way
        carriageway. The far carriageway still counts as crossed (gate 1), but
        the rider rode the road between: the left is a junction of its own."""
        near = Road(4, oneway=True, names=frozenset({"main st"}), ways=frozenset({1}))
        far = Road(4, oneway=True, names=frozenset({"main st"}), ways=frozenset({2}))
        onto = junction(
            m=0.0,
            movement=Movement.RIGHT,
            incoming=self.a_st,
            outgoing=near,
            control=Control.SIGNAL,
        )
        off = junction(
            m=18.0, movement=Movement.LEFT, incoming=near, outgoing=self.b_st, crossed=(far,)
        )
        assert m.share_controls([onto, off])[1].control is Control.NONE

    def test_a_crossing_then_a_turn_onto_the_same_road_from_a_link(self) -> None:
        """Columbus Circle NE: a left across Massachusetts Ave at a signal onto
        the circle's link, then 20 m on a left onto Massachusetts Ave. The
        rider rides the link between, whose name both turns share, but the
        road crossed at the one and turned onto at the other is one junction's."""
        mass = Road(4, oneway=True, names=frozenset({"massachusetts avenue"}), ways=frozenset({3}))
        circle = Road(4, names=frozenset({"columbus circle"}), ways=frozenset({4}))
        link = Road(3, names=frozenset({"columbus circle"}), ways=frozenset({5}))
        across = junction(
            m=0.0,
            movement=Movement.LEFT,
            incoming=circle,
            outgoing=link,
            crossed=(mass,),
            control=Control.SIGNAL,
        )
        onto = junction(m=20.0, movement=Movement.LEFT, incoming=link, outgoing=mass)
        assert m.share_controls([across, onto])[1].control is Control.SIGNAL

    def test_route_order_does_not_matter(self) -> None:
        a, b = self.carriageways(Control.NONE, Control.SIGNAL)
        shared = m.share_controls([b, a])
        assert [j.control for j in shared] == [Control.SIGNAL, Control.SIGNAL]


class TestMassRide:
    """Items 133 and 138: orange across an LTS 3 road, red across an LTS 4 or
    Avoid, left across a one-way not flagged. The colour is the tier."""

    def test_the_colour_is_the_roads_tier(self) -> None:
        orange = m.assess(junction(crossed=(Road(3),), control=Control.SIGNAL), group=True)
        red = m.assess(junction(crossed=(Road(4),), control=Control.SIGNAL), group=True)
        avoid = m.assess(junction(crossed=(Road(5),), control=Control.SIGNAL), group=True)
        assert (orange.severity, red.severity, avoid.severity) == (m.ORANGE, m.RED, m.RED)

    def test_a_signalised_busy_crossing_is_still_flagged_for_a_group(self) -> None:
        """ "Busy roads will almost always have lights" (item 135): the icon is for
        the crossing, not for the lack of a light."""
        assert m.assess(junction(crossed=(Road(3),), control=Control.SIGNAL), group=True)

    def test_a_left_across_a_one_way_is_not_flagged(self) -> None:
        turn = junction(movement=Movement.LEFT, incoming=ONEWAY_LTS3, outgoing=QUIET)
        assert m.assess(turn, group=True) is None
        two_way = junction(movement=Movement.LEFT, incoming=LTS3, outgoing=QUIET)
        assert m.assess(two_way, group=True).severity == m.ORANGE

    def test_the_group_reading_survives_a_merge(self) -> None:
        events = m.assess_route(
            [
                junction(m=0.0, crossed=(Road(3),), control=Control.SIGNAL),
                junction(m=20.0, crossed=(Road(3),), control=Control.SIGNAL),
            ],
            group=True,
        )
        assert [e.severity for e in events] == [m.ORANGE]

    def test_neighbourhood_junctions_are_never_flagged(self) -> None:
        assert m.assess(junction(crossed=(QUIET,), control=Control.STOP), group=True) is None


class TestRoundabouts:
    """OWNER-DECISIONS 228: a roundabout is one-way for junction pricing as it is
    for routing. Spot-checked on the 2026-09-25 extract's own tags, through the
    classifier that writes `road_oneway` and `road_lanes`: four rings OSM leaves
    without a `oneway` tag (Washington Circle NW 6059311, Dupont Circle NW
    696063559, Westgate Circle MD 450 11508177, Prince Frederick Road MD 231
    114637602), and three it tags (Westmoreland Circle 131463009, Ward Circle NW
    130676670, Chevy Chase Circle NW 131448535), which read as they always did."""

    UNTAGGED = {
        "washington circle northwest": {
            "highway": "primary", "junction": "roundabout", "lanes": "4",
            "name": "Washington Circle Northwest",
        },
        "dupont circle northwest": {
            "highway": "primary", "junction": "circular", "lanes": "2",
            "name": "Dupont Circle Northwest",
        },
        "westgate circle": {
            "highway": "primary", "junction": "roundabout", "lanes": "1",
            "name": "Westgate Circle", "ref": "MD 450",
        },
        "prince frederick road": {
            "highway": "primary", "junction": "roundabout", "lanes": "2",
            "maxspeed": "15 mph", "name": "Prince Frederick Road",
        },
    }  # fmt: skip
    TAGGED = {
        "westmoreland circle": {
            "highway": "primary", "junction": "roundabout", "lanes": "2",
            "name": "Westmoreland Circle", "oneway": "yes",
        },
        "ward circle northwest": {
            "highway": "primary", "junction": "roundabout", "lanes": "4",
            "maxspeed": "25 mph", "name": "Ward Circle Northwest", "oneway": "yes",
        },
        "chevy chase circle northwest": {
            "highway": "primary", "junction": "roundabout", "lanes": "3",
            "name": "Chevy Chase Circle Northwest", "oneway": "yes",
        },
    }  # fmt: skip

    @staticmethod
    def ring(tags: dict, way: int = 1) -> Road:
        """The ring as `core.junctions.roads_by_way` reads it from the segment
        row the classifier wrote (busy, so the model prices it)."""
        from routemaker.stress import classify

        read = classify(tags, urban=True, jurisdiction="DC")
        return Road(
            max(int(read.tier), 3),
            speed_mph=read.speed_mph,
            lanes=read.lanes,
            oneway=read.oneway,
            names=frozenset({tags["name"].lower()}),
            ways=frozenset({way}),
        )

    @pytest.mark.parametrize("name", [*UNTAGGED, *TAGGED])
    def test_the_ring_is_one_way_with_its_lanes_a_direction(self, name) -> None:
        tags = {**self.UNTAGGED, **self.TAGGED}[name]
        ring = self.ring(tags)
        assert ring.oneway is True
        assert ring.lanes == int(tags["lanes"])
        # Its lanes are counted once ("a 4-lane road", not 8).
        assert f"{tags['lanes']}-lane" in m.describe_road(ring)

    @pytest.mark.parametrize("name", list(UNTAGGED))
    def test_mass_ride_draws_no_left_across_traffic_off_the_ring(self, name) -> None:
        """Items 133 and 138: a left off a one-way road meets no oncoming lanes,
        so a Mass Ride draws none; read two-way, the untagged ring drew one."""
        ring = self.ring(self.UNTAGGED[name])
        off = junction(movement=Movement.LEFT, incoming=ring)
        assert m.assess(off, group=True) is None
        assert m.assess(replace(off, incoming=replace(ring, oneway=False)), group=True)

    # Hunt J4: a two-lane-a-direction LTS 4 ring, unposted at the District's 30 mph
    # default, entered from a quiet street at a yield sign.
    BUSY_RING = Road(
        4, default_speed_mph=30, lanes=2, oneway=True, aadt=35_000, names=frozenset({"circle"})
    )

    def through(self, movement, ring=BUSY_RING, control=Control.STOP, when=None):
        """The events of a ride round `ring`: the entry (a right onto it), a node passed
        and the exit (a right off it)."""
        exit_road = Road(2, names=frozenset({"oak st"}))
        return m.assess_route(
            [
                junction(
                    m=100.0,
                    movement=Movement.RIGHT,
                    outgoing=ring,
                    control=control,
                    ring_movement=movement,
                ),
                junction(m=120.0, incoming=ring, outgoing=ring, continues=True),
                junction(m=140.0, movement=Movement.RIGHT, incoming=ring, outgoing=exit_road),
            ],
            when=when,
        )

    def test_a_three_quarter_turn_round_a_busy_ring_costs_its_crossing(self) -> None:
        """Before, every ride round a ring was a right turn onto it (0.1 of the crossing,
        555 ft) and a right off it, whatever the exit; a left round Chevy Chase Circle
        cost about 5% of the same left at a stop sign."""
        crossing = m.crossing_ft(self.BUSY_RING, Control.STOP, None)
        (left,) = self.through(Movement.LEFT)
        assert left.kind == "left_onto"
        assert left.severity == m.RED
        assert left.cost_ft == pytest.approx(crossing + m.RIGHT_FROM_BUSY_FT * m.MERGED_SHARE)
        (ahead,) = self.through(Movement.STRAIGHT)
        (right,) = self.through(Movement.RIGHT)
        assert right.cost_ft < ahead.cost_ft < left.cost_ft
        assert ahead.kind == "straight_onto" and right.kind == "right_onto"
        # The first exit is the right turn onto the ring it always was.
        plain = m.assess_route(
            [junction(m=100.0, movement=Movement.RIGHT, outgoing=self.BUSY_RING,
                      control=Control.STOP)]
        )  # fmt: skip
        assert right.cost_ft == pytest.approx(plain[0].cost_ft + m.RIGHT_FROM_BUSY_FT / 2)

    def test_a_signalised_ring_and_a_quiet_one(self) -> None:
        (signal,) = self.through(Movement.LEFT, control=Control.SIGNAL)
        assert signal.cost_ft < m.ORANGE_MIN_FT
        quiet = Road(2, speed_mph=15, lanes=1, oneway=True, names=frozenset({"circle"}))
        assert self.through(Movement.LEFT, ring=quiet) == []

    def test_a_ring_tagged_two_way_is_priced_two_way(self) -> None:
        """Kenton Court 1536402606, `junction=roundabout` with `oneway=no`: the
        mapper's word stands for the classifier (the graph's upstream reading
        makes it one-way regardless; the one such way in the region)."""
        ring = self.ring(
            {
                "highway": "residential",
                "junction": "roundabout",
                "lanes": "2",
                "maxspeed": "25 mph",
                "name": "Kenton Court",
                "oneway": "no",
            }
        )
        assert ring.oneway is False and ring.lanes == 1


class TestOptionC:
    """OWNER-DECISIONS 467, 468: option C, with merges, in calm miles."""

    def test_the_search_trigger_follows_red(self) -> None:
        from core import refine

        assert refine.REFINE_MIN_EVENT_FT == m.RED_MIN_FT

    def test_a_left_off_an_unsignalised_lts4_road_costs_as_much_as_crossing_it_from_a_stop(
        self,
    ) -> None:
        road = Road(4, speed_mph=30, lanes=1)
        left_off = m.left_from_ft(road, Control.NONE)
        stopped = m.crossing_ft(road, Control.NONE, 1)
        assert left_off == pytest.approx(stopped)

    def test_the_worst_junction_is_about_two_calm_miles(self) -> None:
        wild = Road(5, speed_mph=60, lanes=4, aadt=60_000)
        assert cost(movement=Movement.LEFT, outgoing=wild) == m.MAX_CROSSING_FT
        assert m.calm_miles(m.MAX_CROSSING_FT) == 2.0

    def test_the_worst_junctions_are_no_longer_all_the_same(self) -> None:
        """Before, every left onto an LTS 4 road was the 4,500 ft cap."""
        slow = cost(movement=Movement.LEFT, outgoing=Road(4, speed_mph=30, lanes=1))
        fast = cost(movement=Movement.LEFT, outgoing=Road(4, speed_mph=45, lanes=3))
        assert slow < fast
        assert slow < 0.7 * m.MAX_CROSSING_FT

    def test_calm_text_is_miles_first_with_km_in_brackets(self) -> None:
        assert m.calm_text(2900.0) == "0.55 calm mi (0.88 calm km)"
        assert m.calm_text(10560.0) == "2.00 calm mi (3.22 calm km)"


class TestTimeOfDay:
    """OWNER-DECISIONS 468a, 469c-469e: more intersection stress at rush hour,
    a little less at weekends, about half at night in town and a little less at
    night outside it; quiet-street stops unchanged."""

    def test_quiet_street_stops_are_unchanged_and_never_flagged(self) -> None:
        j = junction(crossed=(QUIET,), control=Control.STOP)
        assert m.assess(j, when="weekday_rush") is None
        assert cost(crossed=(QUIET,), control=Control.STOP) == m.NEIGHBOURHOOD_STOP_FT

    def test_a_signalised_left_stays_at_the_box_turn_at_rush_hour(self) -> None:
        """468: the box turn caps a signalised left at any hour, so rush hour cannot
        lift it to orange."""
        big = Road(4, speed_mph=45, lanes=3)
        j = junction(movement=Movement.LEFT, incoming=big, control=Control.SIGNAL)
        assert m.assess(j).cost_ft == m.BOX_TURN_CAP_FT
        event = m.assess(j, when="weekday_rush")
        assert event.cost_ft == m.BOX_TURN_CAP_FT and event.severity is None


class TestTimeBand:
    """468a: the hour's effect is "shown in the panel/chart in words ("rush hour")".
    The event names the ride time only where it moved that junction's cost, so the
    planner never says a junction counts more or less when it does not."""

    def test_no_band_off_peak_or_with_no_ride_time(self) -> None:
        j = junction(crossed=(Road(3),), control=Control.STOP)
        assert m.assess(j, when="weekday_offpeak").time_band is None
        assert m.assess(j).time_band is None

    def test_no_band_where_the_box_turn_holds_at_any_hour(self) -> None:
        big = Road(4, speed_mph=45, lanes=3)
        j = junction(movement=Movement.LEFT, incoming=big, control=Control.SIGNAL)
        assert m.assess(j, when="weekday_rush").time_band is None

    def test_a_rated_junction_has_no_band(self) -> None:
        j = junction(crossed=(Road(3),), control=Control.STOP, rating=4)
        event = m.assess(j, when="weekday_rush")
        assert event is not None and event.time_band is None


class TestRightHook:
    """Straight on along a painted lane past a busy road (the owner, 2026-11-13: "Add the risks
    to the junctions, rather than the road", "not as bad as a slip lane, but it's still a
    cost")."""

    LANE = Road(2, speed_mph=25, lanes=1, oneway=True, painted_lane=True, names=frozenset({"r"}))

    def test_a_painted_lane_past_a_busy_road_pays_the_hook_on_top(self) -> None:
        plain = replace(self.LANE, painted_lane=False)
        with_lane = cost(incoming=self.LANE, outgoing=self.LANE, crossed=(LTS3,), continues=True)
        without = cost(incoming=plain, outgoing=plain, crossed=(LTS3,), continues=True)
        assert with_lane == pytest.approx(without + m.RIGHT_HOOK_FT)
        assert m.RIGHT_HOOK_FT < m.SLIP_LANE_FT

    def test_a_quiet_side_street_turning_or_a_car_free_lane_pay_nothing(self) -> None:
        assert cost(incoming=self.LANE, outgoing=self.LANE, crossed=(QUIET,), continues=True) == 0
        turning = cost(incoming=self.LANE, outgoing=QUIET, crossed=(LTS3,), movement=Movement.RIGHT)
        assert turning < m.RIGHT_HOOK_FT
        car_free = replace(self.LANE, car_free=True)
        assert cost(incoming=car_free, outgoing=car_free, crossed=(LTS3,), continues=True) == (
            cost(
                incoming=replace(car_free, painted_lane=False),
                outgoing=car_free,
                crossed=(LTS3,),
                continues=True,
            )
        )

    def test_on_its_own_it_is_an_event_never_drawn(self) -> None:
        busy_lane = replace(self.LANE, tier=3, speed_mph=25, lanes=2)
        j = junction(
            incoming=busy_lane,
            outgoing=busy_lane,
            crossed=(Road(2, half=True, names=frozenset({"q"})),),
            continues=True,
            control=Control.SIGNAL,
        )
        event = m.assess(j)
        assert event is None or not event.flagged
