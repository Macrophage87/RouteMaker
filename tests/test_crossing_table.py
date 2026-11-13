"""The one crossing function (the methodology audit of 2026-11-13, package W2).

Each test names the rule it pins and, where the audit gave one, the figure the model
gave before (run on release/v0.26.0 by the audit, areas/06-junction-cost.md)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from routemaker import intersections as model
from routemaker import ridetime
from routemaker.intersections import Control, Junction, Movement, Road, assess, assess_route

QUIET = Road(1, speed_mph=25.0, lanes=1, oneway=False)


def road(lanes: int, speed: float, aadt: int | None = None, tier: int = 2, **more) -> Road:
    """A two-way road of `lanes` each way; the map's level low, so the traffic decides."""
    return Road(tier, speed_mph=speed, lanes=lanes, oneway=False, aadt=aadt, **more)


def crossing(
    crossed: Road,
    control: Control = Control.STOP,
    own: Road = QUIET,
    movement: Movement = Movement.STRAIGHT,
    **more,
) -> Junction:
    return Junction(0.0, -77.0, 39.0, movement, own, own, (crossed,), control, **more)


def cost(junction: Junction, when: str | None = None) -> float:
    event = assess(junction, when=when)
    return 0.0 if event is None else event.cost_ft


class TestPublishedPrices:
    """The stopped side's price is Broach's by the count and Furth's by lanes and speed.
    Before (release/v0.26.0, the audit's runs): 1,088 to 3,900 ft for 5,000-20,000 a day,
    3 to 11 times Broach."""

    @pytest.mark.parametrize(
        "aadt,feet", [(4_000, 0), (5_000, 0), (7_500, 380), (15_000, 550), (20_000, 3260)]
    )
    def test_broachs_bins_on_a_two_lane_30_mph_street(self, aadt: int, feet: int) -> None:
        assert cost(crossing(road(1, 30, aadt))) == pytest.approx(feet, abs=0.5)

    @pytest.mark.parametrize(
        "lanes,speed,feet",
        [
            (1, 30, 0),
            (1, 35, 380),
            (1, 40, 550),
            (1, 55, 550),
            (2, 25, 380),
            (2, 30, 380),
            (2, 35, 550),
            (2, 40, 3260),
            (3, 25, 3260),
        ],
    )
    def test_furths_crossing_table_where_there_is_no_count(self, lanes, speed, feet) -> None:
        # Table 7, cell for cell: up to 3 lanes 1/1/2/3, 4 to 5 lanes 2/2/3/4, 6 or more 4.
        assert cost(crossing(road(lanes, speed))) == pytest.approx(feet, abs=0.5)

    def test_a_four_lane_30_mph_road_is_not_level_4_to_cross(self) -> None:
        # Before: LTS 4 by the riding-along table, 4,500 ft and red. The owner's Sheridan St
        # across Piney Branch Rd NW now prices by the road's count.
        assert cost(crossing(road(2, 30, 15_000))) == pytest.approx(550, abs=0.5)
        assert cost(crossing(road(2, 30, 25_000))) == pytest.approx(3260, abs=0.5)

    def test_a_bike_lane_or_the_maps_level_does_not_change_the_crossing(self) -> None:
        plain = cost(crossing(road(2, 30, 15_000, tier=4)))
        assert plain == cost(crossing(road(2, 30, 15_000, tier=2, painted_lane=True)))

    def test_no_count_or_speed_is_a_cliff(self) -> None:
        # Before: 1,368 to 3,420 ft between 7,999 and 8,000 a day.
        steps = [
            cost(crossing(road(1, 30, a + 1))) - cost(crossing(road(1, 30, a)))
            for a in range(4_000, 30_000, 37)
        ]
        assert 0 <= min(steps) and max(steps) < 0.6
        slow, mid, fast = (cost(crossing(road(2, v))) for v in (35, 37.5, 40))
        assert mid == pytest.approx((slow + fast) / 2)

    def test_a_fast_road_with_few_cars_is_not_the_top(self) -> None:
        # Before: 50 mph and 1,800 a day paid the 9,840 ft rush-hour floor, 10,560 ft.
        assert cost(crossing(road(1, 50, 1_800)), ridetime.WEEKDAY_RUSH) == pytest.approx(550)

    def test_the_colours_are_waits_of_30_and_45_seconds(self) -> None:
        assert model.ORANGE_MIN_FT == pytest.approx(984)
        assert model.RED_MIN_FT == pytest.approx(1476)
        assert assess(crossing(road(1, 30, 15_000))).severity is None
        assert assess(crossing(road(1, 30, 16_000))).severity == model.ORANGE
        assert assess(crossing(road(1, 30, 20_000))).severity == model.RED


class TestWaitForAGap:
    """ "Most people would rather bike 10 minutes than wait 5 minutes at a busy crossing
    for an opening. There are rarely openings." Charged once: twice the published wait."""

    def test_the_formula(self) -> None:
        import math

        flow = 8_000 * 0.08 / 3600
        x = flow * (3 + 2 * 12 / 16.4)
        want = (math.exp(x) - x - 1) / flow
        assert model.gap_delay_s(road(1, 30, 8_000), ridetime.WEEKDAY_RUSH) == pytest.approx(want)
        assert model.gap_delay_s(road(1, 30)) == 0.0

    def test_a_six_lane_commuter_road_is_the_level_4_price_at_every_daytime_hour(self) -> None:
        # A six-lane commuter road at a stop sign. Before the audit: 10,560 ft plus
        # 9,840 ft for the red plus the give-way wait, 3 to 4 miles in all. Then 10,560 ft
        # at rush hour on a 599 s wait the rider was shown as 33 s. Now the wait priced is
        # the wait shown, 30 s at most, and the published price carries the rest.
        wide = crossing(road(3, 35, 38_000))
        assert cost(wide, ridetime.WEEKDAY_RUSH) == cost(wide, ridetime.WEEKDAY_OFFPEAK) == 3260
        assert model.wait_s(road(3, 35, 38_000), ridetime.WEEKDAY_RUSH) == model.GAP_WAIT_MAX_S

    def test_the_capped_wait_is_inside_the_published_price_on_any_road_with_one(self) -> None:
        # The wait for a gap, weighed at WAIT_PAIN, is at most 984 ft (30 s), and the
        # published price of a road busy enough to make a rider wait is more: a crossing
        # costs the larger, never the two added. Two lanes each way at 30 mph, 14,000 a
        # day: 527 ft by its count at every hour's wait.
        middling = crossing(road(2, 30, 14_000))
        assert cost(middling) == pytest.approx(527, abs=1)
        assert cost(middling, ridetime.WEEKDAY_RUSH) >= cost(middling)
        assert model.gap_ft(road(2, 30, 14_000), ridetime.WEEKDAY_RUSH) < cost(middling)

    def test_rush_hour_does_nothing_where_there_are_gaps(self) -> None:
        # Before: x1.25 on every busy junction, x2 on every LTS 4 one.
        small = crossing(road(1, 30, 8_000))
        assert cost(small, ridetime.WEEKDAY_RUSH) == cost(small)

    def test_quieter_hours_read_the_count_at_the_hours_traffic(self) -> None:
        street = crossing(road(1, 30, 20_000))
        assert cost(street, ridetime.NIGHT) < cost(street, ridetime.WEEKEND) < cost(street)
        # Lanes and speed do not change at night: six lanes stay level 4.
        assert cost(crossing(road(3, 35, 38_000)), ridetime.NIGHT) == pytest.approx(3260)

    def test_nothing_passes_two_miles(self) -> None:
        worst = crossing(road(4, 55, 90_000), movement=Movement.LEFT)
        assert cost(worst, ridetime.WEEKDAY_RUSH) <= model.MAX_CROSSING_FT == 10560


class TestRefuge:
    """Furth's Table 8 in place of a flat x0.75 on the dearer carriageway."""

    def one_way(self, lanes: int, speed: float, aadt: int | None = None) -> Road:
        return Road(2, speed_mph=speed, lanes=lanes, oneway=True, aadt=aadt)

    def refuge(self, lanes: int, speed: float, aadt: int | None = None) -> float:
        event = assess(crossing(self.one_way(lanes, speed, aadt)))
        return 0.0 if event is None else event.refuge_ft

    def test_table_8(self) -> None:
        assert self.refuge(2, 25) == 0  # four lanes at 25 mph: level 1 with a refuge
        assert self.refuge(2, 30) == pytest.approx(380)  # no credit at 30
        assert self.refuge(2, 35) == pytest.approx(550)  # nor at 35 (before: x0.75)
        assert self.refuge(3, 25) == pytest.approx(380)  # six lanes: two levels at 25
        assert self.refuge(3, 30) == pytest.approx(550)
        assert self.refuge(3, 35) == pytest.approx(3260)

    def test_the_rider_faces_one_direction_at_a_time(self) -> None:
        # Four lanes at 30 mph and 25,000 a day: 3,260 ft undivided.
        assert self.refuge(2, 30, 25_000) < cost(crossing(road(2, 30, 25_000))) / 3
        divided = replace(self.one_way(3, 35, 38_000), divided=True)
        whole = road(3, 35, 38_000)
        rush = ridetime.WEEKDAY_RUSH
        assert model.gap_delay_s(divided, rush) < model.gap_delay_s(whole, rush) / 5

    def test_two_carriageways_are_one_crossing(self) -> None:
        a = crossing(replace(self.one_way(2, 35), names=frozenset({"x"}), ways=frozenset({1})))
        b = replace(
            crossing(replace(self.one_way(2, 35), names=frozenset({"x"}), ways=frozenset({2}))),
            m=20.0,
        )
        events = assess_route([a, b])
        assert len(events) == 1 and events[0].cost_ft == pytest.approx(550)


class TestSignalsAndStops:
    def test_a_signalised_crossing_has_no_stress_price_but_keeps_its_event(self) -> None:
        # Before: 150 ft at LTS 3 and 600 ft at LTS 4 on top of the wait.
        event = assess(crossing(road(3, 40, 40_000), Control.SIGNAL), when=ridetime.WEEKDAY_RUSH)
        assert event is not None and event.cost_ft == 0 and not event.flagged
        (only,) = assess_route([crossing(road(3, 40, 40_000), Control.SIGNAL)])
        assert only.signals

    def test_an_all_way_stop_and_the_priority_side(self) -> None:
        assert cost(crossing(road(2, 35, 30_000), Control.ALL_STOP)) == model.ALL_WAY_STOP_FT
        assert cost(crossing(road(2, 35, 30_000), Control.CROSS_STOP)) == model.PRIORITY_SIDE_FT

    def test_a_marked_trail_crossing_by_the_share_who_do_not_yield(self) -> None:
        # Before: a flat x0.5 and never red.
        slow = crossing(road(2, 25, 25_000), marked_crossing=True)
        fast = crossing(road(2, 40), marked_crossing=True)
        assert cost(slow) == pytest.approx(3260 * 0.39)
        assert cost(fast) == pytest.approx(3260 * 0.83)
        assert assess(fast).severity == model.RED


class TestLeftTurns:
    def test_a_left_off_a_busy_road_at_an_all_way_stop(self) -> None:
        # Before: priced as if nobody stopped, 1,920 to 6,584 ft.
        own = road(2, 35, 30_000)
        j = crossing(road(1, 25), Control.ALL_STOP, own=own, movement=Movement.LEFT)
        assert cost(j) == model.ALL_WAY_STOP_FT

    def test_a_left_off_is_broachs_whole_left(self) -> None:
        def left(own: Road, control: Control = Control.NONE) -> float:
            return cost(crossing(road(1, 25), control, own=own, movement=Movement.LEFT))

        assert left(road(1, 30, 15_000)) == pytest.approx(855)
        # Lanes to merge across add, but the whole left stops at his 2,276 ft (before:
        # 4,000 + 1,584 a lane).
        assert left(road(2, 30, 15_000)) == pytest.approx(855 + 792)
        assert left(road(2, 35, 30_000)) == pytest.approx(2276)
        assert left(road(3, 40, 30_000), Control.SIGNAL) == model.BOX_TURN_CAP_FT

    def test_a_signalised_left_onto_never_costs_more_than_the_left_off(self) -> None:
        # Before: 900 ft onto against 750 ft off.
        big = road(2, 40, 30_000)
        onto = Junction(0.0, 0.0, 0.0, Movement.LEFT, QUIET, big, (), Control.SIGNAL)
        off = Junction(0.0, 0.0, 0.0, Movement.LEFT, big, QUIET, (), Control.SIGNAL)
        assert cost(onto) <= cost(off) <= model.BOX_TURN_CAP_FT

    def test_turns_onto(self) -> None:
        big = road(2, 40, 30_000)
        straight = cost(crossing(big))
        left = Junction(0.0, 0.0, 0.0, Movement.LEFT, QUIET, big, (), Control.STOP)
        right = Junction(0.0, 0.0, 0.0, Movement.RIGHT, QUIET, big, (), Control.STOP)
        assert cost(left) == straight  # before: x1.5
        assert cost(right) == model.RIGHT_ONTO_MAX_FT == 354  # before: x0.1


class TestUnknownControl:
    """With nothing mapped the rider is the stopped side only on a true tie."""

    def test_the_clearly_bigger_road_has_the_right_of_way(self) -> None:
        # Before: a rider on a rural main road paid 4,080 ft at each unmapped crossroad.
        main, side = road(2, 40, 30_000), road(1, 35, 6_000)
        assert cost(crossing(side, Control.NONE, own=main)) <= model.PRIORITY_SIDE_FT
        assert cost(crossing(main, Control.NONE, own=side)) == pytest.approx(3260)

    def test_a_tie_in_traffic_goes_by_class_and_else_stays_cautious(self) -> None:
        a = road(1, 40, 9_000)
        tie = crossing(a, Control.NONE, own=a)
        assert cost(tie) == pytest.approx(550)
        assert cost(replace(tie, class_edge=1)) <= model.PRIORITY_SIDE_FT
        assert cost(replace(tie, class_edge=0)) == pytest.approx(550)


class TestSidePath:
    def test_a_side_path_has_the_right_of_way_of_the_road_it_runs_beside(self) -> None:
        path = Road(1, speed_mph=None, lanes=None)
        side = road(1, 35, 8_000)
        alone = crossing(side, Control.NONE, own=path, path_crossing=True)
        beside = replace(alone, beside=road(2, 40, 30_000))
        # The priority side's pass and the hook of cars turning off the main road.
        # (The pass is a marked crossing's, x0.83 at 35 mph.)
        assert cost(beside) == pytest.approx(25 * 0.83 + model.RIGHT_HOOK_FT)
        assert cost(beside) < cost(alone)


class TestRightHook:
    def test_it_is_a_quarter_of_a_slip_lane_on_top_of_the_junction(self) -> None:
        assert model.RIGHT_HOOK_FT == model.SLIP_LANE_FT / 4 == 250
        lane = Road(2, speed_mph=25.0, lanes=1, oneway=False, painted_lane=True)
        plain = replace(lane, painted_lane=False)
        busy = road(2, 35, 30_000)
        for control in (Control.SIGNAL, Control.CROSS_STOP):
            with_lane = cost(crossing(busy, control, own=lane))
            assert with_lane - cost(crossing(busy, control, own=plain)) == 250
        # It fades in with the crossed road, and a quiet street has none.
        assert cost(crossing(road(1, 30, 6_250), Control.CROSS_STOP, own=lane)) == pytest.approx(
            (250 + 25) / 2
        )
        assert assess(crossing(road(1, 25), Control.CROSS_STOP, own=lane)) is None

    def test_a_path_beside_a_road_takes_it_too_and_only_once(self) -> None:
        # The side path's own level no longer counts busy cross streets (package W4).
        path = Road(1, speed_mph=None, lanes=None)
        busy = road(2, 35, 30_000)
        main = road(3, 40, 40_000)
        alone = crossing(busy, Control.SIGNAL, own=path, path_crossing=True)
        beside = replace(alone, beside=main)
        assert cost(alone) == 0 and cost(beside) == 250


def test_urban_has_one_definition() -> None:
    assert model.is_urban(Road(3, urban=True)) is True
    assert model.is_urban(Road(3)) is None and model.is_urban(None) is None


class TestTheIndependentReviewsSurvivors:
    """The eight mutants the independent review of 2026-11-13 found alive, and the two
    of the audit's that the capped wait let go."""

    def test_a_left_off_a_road_prices_a_gap_in_the_oncoming_lanes_only(self) -> None:
        # One lane each way, 25 mph, 8,000 a day at rush hour: the wait for the oncoming
        # lane is worth 23 ft, less than the left's own 57 ft; a gap in both lanes would
        # be 77 ft, which is what it was priced by.
        busy = model._by_traffic(road(1, 25, 8_000))
        rush = ridetime.WEEKDAY_RUSH
        assert model.gap_ft(busy, rush, lanes=1) < 57 < model.gap_ft(busy, rush)
        assert model.left_from_ft(busy, Control.NONE, rush) == pytest.approx(57, abs=0.5)
        # Where the oncoming wait is the larger, it is the price: a road too quiet to
        # have one of its own.
        thin = model._by_traffic(road(1, 25, 1_000))
        assert model.left_from_ft(thin, Control.NONE) == model.gap_ft(thin, lanes=1) > 0

    def test_each_stage_of_a_divided_road_crosses_one_carriageways_lanes(self) -> None:
        import math

        divided = road(2, 30, 20_000, divided=True)
        flow = 20_000 * 0.055 / 3600 / 2
        x = flow * (3 + 2 * 12 / 16.4)
        assert model.gap_delay_s(divided) == pytest.approx(2 * (math.exp(x) - x - 1) / flow)

    def test_priority_takes_half_a_level_and_the_class_does_not_overrule_the_traffic(
        self,
    ) -> None:
        # The rider on a two-lane 40 mph road (level 3) crossing a two-lane 35 mph one
        # (level 2), nothing mapped: a level clear, so the rider has the way, whatever
        # the classes say of two roads both read by their traffic.
        own, crossed = road(1, 40), road(1, 35)
        for edge in (None, 1, -1):
            passing = crossing(crossed, Control.NONE, own, class_edge=edge)
            assert cost(passing) == model.PRIORITY_SIDE_FT, edge
        assert model.PRIORITY_MARGIN == 0.5

    def test_a_cost_read_from_the_statutory_speed_says_so(self) -> None:
        unposted = Road(3, lanes=2, oneway=False, default_speed_mph=30.0)
        assert assess(crossing(unposted)).assumed_speed
        assert not assess(crossing(road(2, 30))).assumed_speed
        # At a signal the speed prices nothing, so nothing was assumed.
        assert not assess(crossing(unposted, Control.SIGNAL)).assumed_speed

    def test_with_the_lanes_unknown_none_is_merged_across_below_level_4(self) -> None:
        def unknown(speed: float, aadt: int | None = None) -> Road:
            return model._by_traffic(Road(3, speed_mph=speed, oneway=False, aadt=aadt))

        assert model.merge_ft(unknown(35.0)) == model.merge_ft(unknown(40.0)) == 0.0
        assert model.merge_ft(unknown(45.0, 30_000)) == model.MERGE_FT_PER_LANE[4]

    def test_a_slip_lane_at_a_signal_is_half_one(self) -> None:
        big = road(2, 40)
        off = Junction(0.0, -77.0, 39.0, Movement.RIGHT, big, QUIET, (), slip_lane=True)
        assert cost(off) == model.SLIP_LANE_FT == 1000
        assert cost(replace(off, control=Control.SIGNAL)) == 500

    def test_the_refuge_credit_is_priced_at_the_ride_time(self) -> None:
        # One carriageway of a divided road, one lane at 25 mph carrying 25,000 a day:
        # read as the whole road, 493 ft by day and 25 ft at night.
        half = Road(4, speed_mph=25.0, lanes=1, oneway=True, aadt=25_000)
        day, night = (assess(crossing(half), when=when) for when in (None, ridetime.NIGHT))
        assert day.refuge_ft == pytest.approx(493, abs=1)
        assert night.refuge_ft == pytest.approx(25, abs=1)
        assert night.refuge_untimed_ft == pytest.approx(day.refuge_ft)

    def test_the_wait_is_the_price_where_it_is_the_larger_and_counts_twice_its_seconds(
        self,
    ) -> None:
        # Only on a road with no published price: 4,000 a day at rush hour, 1 s of
        # waiting, 33 ft. With a price the wait is inside it (`TestWaitForAGap`).
        thin = model._by_traffic(road(1, 25, 4_000))
        rush = ridetime.WEEKDAY_RUSH
        wait = model.wait_s(thin, rush)
        assert model.crossing_ft(thin, Control.STOP, when=rush) == pytest.approx(
            model.WAIT_PAIN * wait * model.QUIET_FT_PER_S
        )
        assert model.crossing_ft(thin, Control.STOP, when=rush) > 30
