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

    @pytest.mark.parametrize(
        ("mph", "factor"),
        [
            (25, 0.8),
            (26, 0.9),
            (30, 0.9),
            (31, 1.0),
            (35, 1.0),
            (36, 1.1),
            (40, 1.1),
            (41, 1.2),
            (45, 1.2),
        ],
    )
    def test_the_speed_bands_include_their_upper_edge(self, mph, factor) -> None:
        """25 mph is the lowest band, not the next one up."""
        assert m.scale(Road(3, speed_mph=mph), stopped_side=False) == pytest.approx(factor)
        assert m.scale(Road(3, speed_mph=46), stopped_side=False) == m.SPEED_FACTOR_FASTER

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
        # A stop sign on the trail's side is no signal either.
        stopped = cost(crossed=(LTS3,), control=Control.STOP, marked_crossing=True)
        assert stopped == pytest.approx(
            cost(crossed=(LTS3,), control=Control.STOP) * m.MARKED_CROSSING_FACTOR
        )

    @pytest.mark.parametrize("control", [Control.NONE, Control.STOP])
    def test_a_marked_crossing_with_no_signal_mapped_is_at_most_orange(self, control) -> None:
        """Item 185: "Trail crossings whose signal is not mapped cap at orange and
        are labelled 'signal not mapped'". Its cost still counts in full."""
        rural = Road(4, speed_mph=55, lanes=3, aadt=40_000)
        event = m.assess(junction(crossed=(rural,), control=control, marked_crossing=True))
        assert event.cost_ft >= m.RED_MIN_FT
        assert event.severity == m.ORANGE and event.flagged
        if control is Control.NONE:
            assert event.reason.endswith(", signal not mapped")
        else:
            assert event.reason.endswith(", stop sign on your side")
        # An unmarked crossing of the same road is red.
        assert m.assess(junction(crossed=(rural,), control=control)).severity == m.RED

    def test_a_cycletrack_crossing_is_a_trail_crossing_too(self) -> None:
        """Item 185, measured downtown: the Pennsylvania Ave cycle track crosses
        15th St NW at a node of its own, with no signal flag; it is a trail
        crossing whose signal is not mapped, not a red unsignalised crossing."""
        plain = m.assess(junction(crossed=(Road(4),)))
        track = m.assess(junction(crossed=(Road(4),), path_crossing=True))
        assert plain.severity == m.RED
        assert track.severity == m.ORANGE
        assert track.cost_ft == pytest.approx(plain.cost_ft * m.MARKED_CROSSING_FACTOR)
        assert track.reason.endswith(", signal not mapped")
        # A signal the router has is priced as one either way.
        signalled = junction(crossed=(Road(4),), path_crossing=True, control=Control.SIGNAL)
        assert m.cost_of(signalled)[0] == m.SIGNALISED_CROSSING_FT[4]

    def test_riding_along_a_road_busier_than_the_cross_street_is_along(self) -> None:
        """At exactly the priority side's cost the label is "along"."""
        event = m.assess(junction(incoming=LTS4, outgoing=LTS4, crossed=(LTS3,)))
        assert event.cost_ft == m.PRIORITY_SIDE_FT
        assert event.kind == "along"


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

    def test_a_left_from_one_busy_road_onto_a_busier_one_is_the_stopped_sides(self) -> None:
        """Review r1, B3: LTS 3 left onto LTS 4 is the stopped side entering the
        free-flowing road, up to the cap, not the 600-850 ft of a left across
        the rider's own oncoming lanes."""
        turn = junction(movement=Movement.LEFT, incoming=Road(3), outgoing=Road(4))
        cost_ft, kind, about = m.cost_of(turn)
        assert kind == "left_onto" and about == Road(4)
        assert cost_ft == pytest.approx(m.STOPPED_CROSSING_FT[4] * m.MOVEMENT_FACTOR_ONTO["left"])
        assert cost_ft > m.left_from_ft(Road(3), Control.NONE)

    def test_a_left_with_a_stop_on_the_riders_side_onto_an_equal_road(self) -> None:
        """Review r1, B3: Flanders Ave (LTS 3, stop) left onto Strathmore Ave (LTS
        3) is the stopped side's left, 1,800 ft."""
        turn = junction(
            movement=Movement.LEFT, incoming=Road(3), outgoing=Road(3), control=Control.STOP
        )
        cost_ft, kind, _about = m.cost_of(turn)
        assert kind == "left_onto"
        assert cost_ft == pytest.approx(1800.0)
        # Without the stop, between equal roads, the left across oncoming stands.
        free = junction(movement=Movement.LEFT, incoming=Road(3), outgoing=Road(3))
        assert m.cost_of(free)[1] == "left_from"
        assert m.cost_of(free)[0] == pytest.approx(m.LEFT_ACROSS_ONCOMING_FT[3])

    def test_a_right_onto_a_busier_road_from_a_busy_one_stays_near_zero(self) -> None:
        turn = junction(movement=Movement.RIGHT, incoming=Road(3), outgoing=Road(4))
        cost_ft, kind, _about = m.cost_of(turn)
        assert kind == "right_onto"
        assert cost_ft == pytest.approx(m.STOPPED_CROSSING_FT[4] * m.MOVEMENT_FACTOR_ONTO["right"])
        assert m.assess(turn).severity is None

    def test_straight_on_from_one_busy_road_onto_a_busier_is_not_a_turn(self) -> None:
        on = junction(incoming=Road(3), outgoing=Road(4))
        assert m.cost_of(on)[0] == 0
        assert m.assess(on) is None

    def test_the_onto_cost_is_capped(self) -> None:
        wild = Road(5, speed_mph=60, lanes=4, aadt=60_000)
        assert cost(movement=Movement.LEFT, outgoing=wild) <= m.MAX_CROSSING_FT

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

    def test_at_a_signal_the_whole_left_is_capped_at_a_box_turn(self) -> None:
        """Item 186, "Cap at box turn": "At signals a left never costs more than
        the two-stage box-turn alternative (about 500 ft equivalent)". The round-1
        review's case: two lanes a direction on LTS 4, 910 ft before."""
        wide = Road(4, speed_mph=40, lanes=2)
        assert m.left_from_ft(wide, Control.SIGNAL) == m.BOX_TURN_CAP_FT
        assert m.left_from_ft(Road(4, speed_mph=60, lanes=4), Control.SIGNAL) == m.BOX_TURN_CAP_FT
        turn = junction(movement=Movement.LEFT, incoming=wide, control=Control.SIGNAL)
        assert not drawn(turn)
        # Without a signal the box turn is no cap.
        assert m.left_from_ft(wide, Control.NONE) > m.BOX_TURN_CAP_FT
        # A narrow road's signalised left stays below the cap.
        assert m.left_from_ft(Road(3, lanes=1), Control.SIGNAL) == pytest.approx(
            m.LEFT_ACROSS_ONCOMING_FT[3] * m.SIGNALISED_LEFT_FACTOR
        )

    def test_a_left_off_a_fast_road_has_no_rural_stopped_side_factor(self) -> None:
        """The rider turning left off the road is on its free-flowing side."""
        fast = Road(3, speed_mph=55, lanes=1)
        assert m.left_from_ft(fast, Control.NONE) == pytest.approx(
            m.LEFT_ACROSS_ONCOMING_FT[3] * m.SPEED_FACTOR_FASTER
        )


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

    def test_the_slip_lane_is_about_the_busiest_road_there(self) -> None:
        """The channel leaves or joins the busiest road at the node."""
        along = junction(incoming=Road(3), outgoing=Road(3), slip_lane=True, links=(Road(4),))
        event = m.assess(along)
        assert event.kind == "slip_lane"
        assert event.crossed_tier == 4
        assert event.reason == "Slip lane beside a heavy-traffic road (LTS 4), no signal mapped"

    def test_a_turn_channel_ridden_straight_past_is_a_slip_lane_not_a_crossing(self) -> None:
        """Review r1, B1: the road's own turn channel is not a road crossed."""
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

    def test_a_divided_roads_two_carriageways_count_once_with_a_refuge(self) -> None:
        """Item 185: "Divided-road crossings count once, with a median-refuge
        credit." The carriageways share the road's names."""
        name = frozenset({"connecticut avenue northwest"})
        north = Road(4, oneway=True, names=name)
        south = Road(4, oneway=True, names=name)
        events = m.assess_route(
            [junction(m=100.0, crossed=(north,)), junction(m=111.0, crossed=(south,))]
        )
        one = m.assess(junction(crossed=(north,)))
        assert len(events) == 1
        assert events[0].cost_ft == pytest.approx(one.cost_ft * m.MEDIAN_REFUGE_FACTOR)
        assert events[0].cost_ft < one.cost_ft

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

    def test_a_merge_never_raises_the_colour(self) -> None:
        """Item 185: "A merge must never raise the colour of one road's crossing."
        Two orange carriageways stay orange (the refuge lowers the cost), and
        two different orange roads together add cost but stay orange."""
        fast = Road(3, speed_mph=45, names=frozenset({"river road"}))
        a = junction(m=0.0, crossed=(fast,))
        one = m.assess(a)
        divided = m.assess_route([a, junction(m=10.0, crossed=(fast,))])[0]
        assert one.severity == m.ORANGE
        assert divided.severity == m.ORANGE
        other = Road(3, speed_mph=45, names=frozenset({"falls road"}))
        two_roads = m.assess_route([a, junction(m=10.0, crossed=(other,))])[0]
        assert two_roads.cost_ft == pytest.approx(one.cost_ft * (1 + m.MERGED_SHARE))
        assert two_roads.cost_ft >= m.RED_MIN_FT
        assert two_roads.severity == m.ORANGE

    def test_the_refuge_can_lower_the_colour(self) -> None:
        road = Road(4, names=frozenset({"rockville pike"}))
        both = m.assess_route([junction(m=0.0, crossed=(road,)), junction(m=20.0, crossed=(road,))])
        assert both[0].cost_ft == pytest.approx(m.STOPPED_CROSSING_FT[4] * m.MEDIAN_REFUGE_FACTOR)
        assert both[0].severity == m.severity_of(both[0].cost_ft)
        # A red LTS 4 crossing at 25 mph whose credit takes it to orange.
        slow = Road(4, speed_mph=25, names=frozenset({"slow road"}))
        assert m.assess(junction(crossed=(slow,))).severity == m.RED
        merged = m.assess_route(
            [junction(m=0.0, crossed=(slow,)), junction(m=9.0, crossed=(slow,))]
        )
        assert merged[0].cost_ft < m.RED_MIN_FT
        assert merged[0].severity == m.ORANGE and merged[0].flagged

    def test_a_capped_crossing_stays_capped_through_a_merge(self) -> None:
        rural = Road(4, speed_mph=55, lanes=3, names=frozenset({"route 28"}))
        events = m.assess_route(
            [
                junction(m=0.0, crossed=(rural,), marked_crossing=True),
                junction(m=15.0, crossed=(rural,), marked_crossing=True),
            ]
        )
        assert [e.severity for e in events] == [m.ORANGE]

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
