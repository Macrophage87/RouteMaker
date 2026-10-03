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
        are labelled 'signal not mapped'". Its cost still counts in full. The
        words are the road junctions' own, "no signal mapped" (review r2: one
        phrase for one fact)."""
        rural = Road(4, speed_mph=55, lanes=3, aadt=40_000)
        event = m.assess(junction(crossed=(rural,), control=control, marked_crossing=True))
        assert event.cost_ft >= m.RED_MIN_FT
        assert event.severity == m.ORANGE and event.flagged
        if control is Control.NONE:
            assert event.reason.endswith(", no signal mapped")
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
        assert track.reason.endswith(", no signal mapped")
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

    def test_a_divided_roads_two_carriageways_count_once_with_a_refuge(self) -> None:
        """Item 185: "Divided-road crossings count once, with a median-refuge
        credit", and 196: "x0.75". The carriageways share the road's names and
        are one-way roads of ways of their own."""
        name = frozenset({"connecticut avenue northwest"})
        north = Road(4, oneway=True, names=name, ways=frozenset({1}))
        south = Road(4, oneway=True, names=name, ways=frozenset({2}))
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
        name = frozenset({"rockville pike"})
        road = Road(4, oneway=True, names=name, ways=frozenset({1}))
        other = Road(4, oneway=True, names=name, ways=frozenset({2}))
        both = m.assess_route(
            [junction(m=0.0, crossed=(road,)), junction(m=20.0, crossed=(other,))]
        )
        assert both[0].cost_ft == pytest.approx(m.STOPPED_CROSSING_FT[4] * m.MEDIAN_REFUGE_FACTOR)
        assert both[0].severity == m.severity_of(both[0].cost_ft)
        # A red LTS 4 crossing at 25 mph whose credit takes it to orange.
        slow = Road(
            4, speed_mph=25, oneway=True, names=frozenset({"slow road"}), ways=frozenset({3})
        )
        slow_back = replace(slow, ways=frozenset({4}))
        assert m.assess(junction(crossed=(slow,))).severity == m.RED
        merged = m.assess_route(
            [junction(m=0.0, crossed=(slow,)), junction(m=9.0, crossed=(slow_back,))]
        )
        assert merged[0].cost_ft < m.RED_MIN_FT
        assert merged[0].severity == m.ORANGE and merged[0].flagged

    def test_a_capped_crossing_stays_capped_through_any_refuge(self, monkeypatch) -> None:
        """At 0.75 the credit takes every capped crossing under red anyway; the
        cap holds whatever the owner sets the credit to."""
        monkeypatch.setattr(m, "MEDIAN_REFUGE_FACTOR", 1.0)
        rural = Road(4, speed_mph=55, lanes=3, oneway=True, names=frozenset({"route 28"}))
        events = m.assess_route(
            [
                junction(
                    m=0.0, crossed=(replace(rural, ways=frozenset({1})),), marked_crossing=True
                ),
                junction(
                    m=15.0, crossed=(replace(rural, ways=frozenset({2})),), marked_crossing=True
                ),
            ]
        )
        assert events[0].cost_ft >= m.RED_MIN_FT
        assert [e.severity for e in events] == [m.ORANGE]

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

    def test_a_left_onto_a_road_from_a_stop_and_a_right_off_it_keep_the_left(self) -> None:
        """Review r2: 3,375 ft (the refuge's) where the left alone is 4,500."""
        name = frozenset({"veirs mill road"})
        road = Road(4, speed_mph=40, lanes=3, names=name, ways=frozenset({1}))
        on = junction(m=0.0, movement=Movement.LEFT, outgoing=road, control=Control.STOP)
        off = junction(m=25.0, movement=Movement.RIGHT, incoming=road)
        (merged,) = m.assess_route([on, off])
        assert merged.cost_ft == m.MAX_CROSSING_FT
        assert merged.kind == "left_onto" and merged.severity == m.RED

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

    def test_a_signal_at_one_carriageway_is_the_other_ones(self) -> None:
        shared = m.share_controls(self.carriageways(Control.SIGNAL, Control.NONE))
        assert [j.control for j in shared] == [Control.SIGNAL, Control.SIGNAL]
        (event,) = m.assess_route(self.carriageways(Control.NONE, Control.SIGNAL))
        assert event.control is Control.SIGNAL and not event.flagged
        assert event.cost_ft == pytest.approx(m.SIGNALISED_CROSSING_FT[4] * m.MEDIAN_REFUGE_FACTOR)

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
        signalised left off Main St and the left back onto it 30 m on are
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
        # Unsignalised, both stay as they are.
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

    @pytest.mark.parametrize("name", [*UNTAGGED, *TAGGED])
    def test_leaving_the_ring_crosses_no_oncoming_traffic(self, name) -> None:
        ring = self.ring({**self.UNTAGGED, **self.TAGGED}[name])
        assert m.left_from_ft(ring, Control.NONE) == m.merge_ft(ring)
        two_way = replace(ring, oneway=False)
        assert m.left_from_ft(two_way, Control.NONE) > m.left_from_ft(ring, Control.NONE)

    @pytest.mark.parametrize("name", list(UNTAGGED))
    def test_mass_ride_draws_no_left_across_traffic_off_the_ring(self, name) -> None:
        """Items 133 and 138: a left off a one-way road meets no oncoming lanes,
        so a Mass Ride draws none; read two-way, the untagged ring drew one."""
        ring = self.ring(self.UNTAGGED[name])
        off = junction(movement=Movement.LEFT, incoming=ring)
        assert m.assess(off, group=True) is None
        assert m.assess(replace(off, incoming=replace(ring, oneway=False)), group=True)

    @pytest.mark.parametrize("name", list(UNTAGGED))
    def test_two_arcs_of_one_ring_crossed_close_together_count_once(self, name) -> None:
        """A path across a small ring's two arcs, through its island: the arcs are
        one-way ways of their own with the ring's name, so they count once with
        the refuge's credit (`_divided`), as a tagged ring's always did."""
        tags = self.UNTAGGED[name]
        near, far = self.ring(tags, way=1), self.ring(tags, way=2)
        events = m.assess_route(
            [junction(m=100.0, crossed=(near,)), junction(m=130.0, crossed=(far,))]
        )
        one = m.assess(junction(crossed=(near,)))
        assert len(events) == 1
        assert events[0].cost_ft == pytest.approx(one.cost_ft * m.MEDIAN_REFUGE_FACTOR)

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
