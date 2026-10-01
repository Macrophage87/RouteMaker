"""The intersection cost model (OWNER-DECISIONS items 165-169, 171, 172).

Each rule is pinned to the owner's words, and each number to the range the
literature review gives it (reports/LTS-literature-review-2.md, "Crossing
penalties by control type and right of way", "Left turns, multi-lane merges
capped by box turns, and slip lanes"), because every value is a proposal the
owner will move: a test that fixes a value and not its reason would be moved
with it.
"""

from __future__ import annotations

import pytest

from routemaker import intersections as m
from routemaker.intersections import Control, Junction, Movement, Road

QUIET = Road(2)
LTS3 = Road(3, speed_mph=35, lanes=2)
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

    def test_straight_is_within_the_named_angle(self) -> None:
        edge = m.STRAIGHT_MAX_DEG
        assert m.movement_of(0, edge) is Movement.STRAIGHT
        assert m.movement_of(0, edge + 1) is Movement.RIGHT
        assert m.movement_of(0, 360 - edge - 1) is Movement.LEFT


class TestCrossing:
    """Item 165: "an at-grade crossing of an LTS 3+ road costs a penalty"."""

    def test_the_stopped_side_pays_the_literature_review_range(self) -> None:
        # LTS 3: 800-1,600 ft; LTS 4: 2,500-3,500 ft (Eugene, Broach); the speed
        # and width of the road move it inside its tier.
        lts3 = m.crossing_ft(Road(3), Control.STOP, rider_tier=1)
        lts4 = m.crossing_ft(Road(4), Control.STOP, rider_tier=1)
        assert 800 <= lts3 <= 1600
        assert 2500 <= lts4 <= 3500

    def test_a_busier_road_costs_more(self) -> None:
        assert m.crossing_ft(Road(4), Control.NONE, 1) > m.crossing_ft(Road(3), Control.NONE, 1) > 0

    def test_neighbourhood_streets_cost_nothing_to_cross(self) -> None:
        """ "an at-grade crossing of an LTS 3+ road": a quiet cross street is not one."""
        assert cost(crossed=(QUIET,)) == 0
        assert cost(crossed=(Road(1), Road(2))) == 0
        assert m.assess(junction(crossed=(QUIET,))) is None

    @pytest.mark.parametrize(
        ("slower", "faster"),
        [
            (Road(3, speed_mph=25), Road(3, speed_mph=45)),
            (Road(3, speed_mph=35, lanes=1), Road(3, speed_mph=35, lanes=3)),
            (Road(3, speed_mph=35, aadt=4_000), Road(3, speed_mph=35, aadt=30_000)),
        ],
    )
    def test_scaled_by_speed_width_and_volume(self, slower, faster) -> None:
        """ "scaled by the crossed road's stress, speed and volume" (item 165)."""
        assert m.crossing_ft(slower, Control.NONE, 1) < m.crossing_ft(faster, Control.NONE, 1)

    def test_unknown_speed_width_and_volume_are_not_guessed(self) -> None:
        assert m.scale(Road(3), stopped_side=True) == 1.0

    def test_rural_roads_cost_more_from_the_stopped_side(self) -> None:
        """ "especially in rural areas where it's usually a stop sign against
        free-flowing traffic" (item 165): at 45 mph and over."""
        urban = Road(3, speed_mph=40)
        rural = Road(3, speed_mph=m.RURAL_SPEED_MPH)
        assert m.scale(rural, True) > m.scale(urban, True) * 1.1
        # And only from the stopped side: the free-flowing rider is not charged.
        assert m.scale(rural, False) < m.scale(rural, True)

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
    def test_a_signal_costs_much_less_than_no_signal(self) -> None:
        """ "Much lower penalty for traffic signals" (item 165)."""
        for tier in (3, 4):
            road = Road(tier, speed_mph=35, lanes=2)
            signalled = m.crossing_ft(road, Control.SIGNAL, 1)
            unsignalled = m.crossing_ft(road, Control.NONE, 1)
            assert signalled * 4 <= unsignalled
        assert 100 <= m.SIGNALISED_CROSSING_FT[3] <= 200

    def test_the_free_flowing_side_pays_little(self) -> None:
        """ "if you're on the free-flowing route of traffic and there's a stoplight
        or sign for cross traffic, the penalty is much less than being on the
        cross side" (item 169)."""
        stopped = m.crossing_ft(LTS4, Control.STOP, 1)
        priority = m.crossing_ft(LTS4, Control.CROSS_STOP, 3)
        assert priority == m.PRIORITY_SIDE_FT
        assert priority * 20 < stopped
        # A rider on a busier road than the one crossed has priority without a sign.
        assert m.crossing_ft(Road(3), Control.NONE, rider_tier=4) == m.PRIORITY_SIDE_FT
        # An equal or lesser rider road does not.
        assert m.crossing_ft(Road(3), Control.NONE, rider_tier=3) > m.PRIORITY_SIDE_FT

    def test_an_all_way_stop_is_the_literature_range(self) -> None:
        assert 50 <= m.crossing_ft(LTS4, Control.ALL_STOP, 1) <= 100

    def test_riding_along_a_busy_road_past_side_streets_is_not_flagged(self) -> None:
        along = junction(incoming=LTS3, outgoing=LTS3, crossed=(QUIET,), control=Control.NONE)
        assert not drawn(along)

    def test_a_marked_trail_crossing_counts_less_until_signals_are_derived(self) -> None:
        plain = cost(crossed=(LTS3,), control=Control.NONE)
        marked = cost(crossed=(LTS3,), control=Control.NONE, marked_crossing=True)
        assert marked == pytest.approx(plain * m.MARKED_CROSSING_FACTOR)
        # Never below what the router says has a signal.
        assert cost(crossed=(LTS3,), control=Control.SIGNAL, marked_crossing=True) == cost(
            crossed=(LTS3,), control=Control.SIGNAL
        )


class TestMovementCosts:
    def test_a_left_onto_a_busy_road_costs_more_than_straight_and_right_near_zero(self) -> None:
        """ "Make it less of a penalty for right turns and more of one for left.
        For most roads, a right turn might be close to 0." (item 166)."""
        left = cost(movement=Movement.LEFT, outgoing=LTS3)
        straight = cost(movement=Movement.STRAIGHT, crossed=(LTS3,))
        right = cost(movement=Movement.RIGHT, outgoing=LTS3)
        assert left > straight > right
        assert right <= straight * 0.15
        assert left == pytest.approx(straight * m.MOVEMENT_FACTOR_ONTO["left"], rel=0.2)

    def test_left_is_two_to_three_times_right_in_the_base_turn(self) -> None:
        """The literature review: "left turns cost about 2-3x right turns"."""
        ratio = m.MOVEMENT_FACTOR_ONTO["left"] / max(m.MOVEMENT_FACTOR_ONTO["right"], 1e-9)
        assert ratio >= 2

    def test_a_left_from_a_busy_road_crosses_its_oncoming_lanes(self) -> None:
        turn = cost(movement=Movement.LEFT, incoming=LTS3)
        assert turn >= m.LEFT_ACROSS_ONCOMING_FT[3]
        assert cost(movement=Movement.RIGHT, incoming=LTS3) == m.RIGHT_FROM_BUSY_FT

    def test_no_oncoming_traffic_on_a_one_way(self) -> None:
        """ "unless it's a 1-way" (item 133, carried into the ordinary model by 171)."""
        two_way = m.left_from_ft(Road(3, speed_mph=30, lanes=1), Control.NONE)
        one_way = m.left_from_ft(Road(3, speed_mph=30, lanes=1, oneway=True), Control.NONE)
        assert two_way > 0 == one_way

    def test_a_multi_lane_road_adds_a_merge_by_lanes_capped_at_a_box_turn(self) -> None:
        """ "having to cross several lanes to get into the left turn can add stress
        too, though box turns are an option" (item 167)."""
        one = m.merge_ft(Road(3, lanes=1))
        two = m.merge_ft(Road(3, lanes=2))
        assert one == 0 < two
        assert m.merge_ft(Road(3, lanes=3)) <= m.BOX_TURN_CAP_FT
        assert m.merge_ft(Road(3, lanes=8)) == m.BOX_TURN_CAP_FT
        # The cap is a two-stage box turn: 200-500 ft at a signalised junction.
        assert 200 <= m.BOX_TURN_CAP_FT <= 500

    def test_the_merge_rises_with_lanes_until_the_cap(self) -> None:
        costs = [m.merge_ft(Road(4, lanes=n)) for n in range(1, 7)]
        assert costs == sorted(costs)
        assert costs[-1] == m.BOX_TURN_CAP_FT

    def test_lanes_unknown_use_the_tier(self) -> None:
        assert m.merge_ft(Road(3)) == 0
        assert m.merge_ft(Road(4)) == min(m.MERGE_FT_PER_LANE, m.BOX_TURN_CAP_FT)

    def test_a_signal_lowers_a_left_across_oncoming_traffic(self) -> None:
        free = m.left_from_ft(Road(4, speed_mph=35, lanes=1), Control.NONE)
        signalled = m.left_from_ft(Road(4, speed_mph=35, lanes=1), Control.SIGNAL)
        assert signalled < free


class TestSlipLanes:
    def test_a_slip_lane_adds_a_penalty(self) -> None:
        """ "Sliplanes should get a penalty too." (item 169): about an
        unsignalised LTS 3 crossing, 800 ft."""
        along = junction(incoming=LTS3, outgoing=LTS3, crossed=(QUIET,), slip_lane=True)
        assert (
            cost(incoming=LTS3, outgoing=LTS3, crossed=(QUIET,), slip_lane=True) == m.SLIP_LANE_FT
        )
        event = m.assess(along)
        assert event is not None and event.kind == "slip_lane"
        assert event.severity == m.ORANGE

    def test_a_signal_halves_it(self) -> None:
        assert m.slip_ft(Control.SIGNAL) == m.SLIP_LANE_FT * m.SIGNALISED_SLIP_FACTOR

    def test_a_slip_lane_beside_a_quiet_street_is_nothing(self) -> None:
        assert m.assess(junction(slip_lane=True)) is None


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

    def test_the_stop_sign_cost_is_below_every_busy_crossing_cost(self) -> None:
        assert m.NEIGHBOURHOOD_STOP_FT < m.PRIORITY_SIDE_FT * 2


class TestSeverity:
    @pytest.mark.parametrize(
        ("feet", "colour"),
        [(0, None), (599, None), (600, m.ORANGE), (1999, m.ORANGE), (2000, m.RED), (4500, m.RED)],
    )
    def test_the_thresholds(self, feet, colour) -> None:
        assert m.severity_of(feet) == colour

    def test_the_thresholds_sit_between_the_literature_tiers(self) -> None:
        # Orange from an LTS 3 stopped-side crossing's low end, red from an LTS 4's.
        assert m.SIGNALISED_CROSSING_FT[4] < m.ORANGE_MIN_FT <= 800
        assert 1600 <= m.RED_MIN_FT <= 2500

    def test_an_unsignalised_lts3_crossing_is_orange_and_lts4_red(self) -> None:
        assert m.assess(junction(crossed=(Road(3),), control=Control.STOP)).severity == m.ORANGE
        assert m.assess(junction(crossed=(Road(4),), control=Control.STOP)).severity == m.RED

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
        assert event.reason == "Left turn across a 4-lane 35 mph (56 km/h) road, no signal"

    def test_miles_per_hour_come_first(self) -> None:
        text = m.reason_of("crossing", Road(4, speed_mph=45, lanes=1, oneway=True), Control.STOP)
        assert text.index("45 mph") < text.index("72 km/h")
        assert "1-lane" in text and "stop sign on your side" in text

    def test_a_one_way_road_counts_its_lanes_once(self) -> None:
        assert "2-lane" in m.describe_road(Road(3, lanes=2, oneway=True))
        assert "4-lane" in m.describe_road(Road(3, lanes=2, oneway=False))

    def test_unknown_lanes_and_speed_name_the_tier(self) -> None:
        assert m.describe_road(Road(4)) == "road (LTS 4)"

    @pytest.mark.parametrize(
        ("kind", "start"),
        [
            ("crossing", "Crossing a"),
            ("left_onto", "Left turn onto a"),
            ("left_from", "Left turn across a"),
            ("slip_lane", "Slip lane beside a"),
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

    def test_junctions_close_together_are_one_junction(self) -> None:
        """A divided road's two carriageways: the costliest names it and the
        rest add half (a median is a refuge)."""
        events = m.assess_route(
            [junction(m=100.0, crossed=(LTS3,)), junction(m=130.0, crossed=(LTS3,))]
        )
        one = m.assess(junction(crossed=(LTS3,))).cost_ft
        assert len(events) == 1
        assert events[0].cost_ft == pytest.approx(one * (1 + m.MERGED_SHARE))

    def test_far_apart_junctions_stay_separate(self) -> None:
        gap = m.MERGE_WITHIN_M + 1
        events = m.assess_route(
            [junction(m=0.0, crossed=(LTS3,)), junction(m=gap, crossed=(LTS3,))]
        )
        assert len(events) == 2

    def test_a_merge_can_raise_the_colour(self) -> None:
        a = junction(m=0.0, crossed=(Road(3, speed_mph=40),))
        one = m.assess(a)
        merged = m.assess_route([a, junction(m=10.0, crossed=(Road(3, speed_mph=40),))])[0]
        assert one.severity == m.ORANGE
        assert merged.cost_ft > one.cost_ft

    def test_the_total_cost_is_in_metres_of_riding(self) -> None:
        events = m.assess_route([junction(crossed=(LTS3,))])
        assert m.penalty_m(events) == pytest.approx(events[0].cost_ft / m.FEET_PER_METRE)


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


class TestNamedConstants:
    """Every proposal is one named line, in the ranges the review gives."""

    def test_stopped_crossing_midpoints(self) -> None:
        assert m.STOPPED_CROSSING_FT == {3: 1200.0, 4: 3000.0, 5: 3000.0}

    def test_the_tiers_are_ordered(self) -> None:
        for table in (m.STOPPED_CROSSING_FT, m.SIGNALISED_CROSSING_FT, m.LEFT_ACROSS_ONCOMING_FT):
            assert table[3] < table[4] <= table[5]

    def test_a_signal_is_cheaper_than_a_stop_at_every_tier(self) -> None:
        for tier in (3, 4, 5):
            assert m.SIGNALISED_CROSSING_FT[tier] < m.STOPPED_CROSSING_FT[tier]
            assert m.ALL_WAY_STOP_FT < m.STOPPED_CROSSING_FT[tier]
