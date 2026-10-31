"""Half-step roads at junctions (the owner, 2026-10-31: "Midpoint fix plus wording").

A junction about a 2.5 or 3.5 road costs the midpoint of the junction's whole cost with that
road read a level below and a level above, ride time included: the severe tier's weights
(LTS 4's speed and lane factors, the unsignalised rush-hour factor and its gap-wait floor)
reach a 3.5 road halfway, not at all. 4.5 stays LTS 4's (461a). And a half step is said as
the route's spans say it: "LTS 3.5".
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from routemaker import describe, ridetime
from routemaker import intersections as m
from routemaker.intersections import Control, Junction, Movement, Road

QUIET = Road(2)


def crossing(road: Road, **fields) -> Junction:
    base = {
        "m": 0.0,
        "lon": -77.0,
        "lat": 38.9,
        "movement": Movement.STRAIGHT,
        "incoming": QUIET,
        "outgoing": QUIET,
        "crossed": (road,),
        "control": Control.STOP,
    }
    return Junction(**(base | fields))


def cost(road: Road, when: str | None = None, **fields) -> float:
    event = m.assess(crossing(road, **fields), when=when)
    return 0.0 if event is None else event.cost_ft


# One lane each way, so the junction reads the road by its rating, not its traffic
# (`by_traffic` reads two or more lanes each way at 30 mph and up as LTS 4).
ARTERIAL = {"speed_mph": 35.0, "lanes": 1, "urban": True}


@pytest.mark.parametrize(
    "when", [None, ridetime.WEEKDAY_RUSH, ridetime.WEEKDAY_OFFPEAK, ridetime.WEEKEND]
)
def test_a_three_and_a_half_crossing_costs_halfway_between_three_and_four(when) -> None:
    low = cost(Road(3, **ARTERIAL), when)
    high = cost(Road(4, **ARTERIAL), when)
    assert cost(Road(3, half=True, **ARTERIAL), when) == pytest.approx((low + high) / 2)


def test_at_rush_hour_a_three_and_a_half_crossing_takes_half_the_gap_wait() -> None:
    # Before: LTS 3's x1.25 only (3,500 ft here), a third of LTS 4's 9,840 ft floor.
    three = cost(Road(3, **ARTERIAL), ridetime.WEEKDAY_RUSH)
    assert cost(Road(4, **ARTERIAL), ridetime.WEEKDAY_RUSH) == m.UNSIGNALISED_RUSH_MIN_FT
    half = cost(Road(3, half=True, **ARTERIAL), ridetime.WEEKDAY_RUSH)
    assert half == pytest.approx((three + m.UNSIGNALISED_RUSH_MIN_FT) / 2)


def test_a_two_and_a_half_crossing_costs_half_of_lts_three() -> None:
    three = cost(Road(3, **ARTERIAL), ridetime.WEEKDAY_RUSH)
    assert cost(Road(2, half=True, **ARTERIAL), ridetime.WEEKDAY_RUSH) == pytest.approx(three / 2)


def test_a_four_and_a_half_crossing_costs_as_lts_four() -> None:
    for when in (None, ridetime.WEEKDAY_RUSH):
        assert cost(Road(4, half=True, **ARTERIAL), when) == cost(Road(4, **ARTERIAL), when)


def test_a_left_off_a_three_and_a_half_road_counts_lts_four_merge_halfway() -> None:
    road = Road(3, half=True, oneway=False, lanes=2, speed_mph=40.0)
    left = {"movement": Movement.LEFT, "crossed": (), "control": Control.NONE}
    low = cost(replace(road, half=False), incoming=replace(road, half=False), **left)
    high = cost(
        replace(road, tier=4, half=False), incoming=replace(road, tier=4, half=False), **left
    )
    assert cost(road, incoming=road, **left) == pytest.approx((low + high) / 2)


def test_the_riders_own_half_step_still_gives_them_the_right_of_way() -> None:
    # Riding a 3.5 road across an LTS 3 one with nothing mapped: the rider's road is the
    # busier, so it is the priority side's small cost, not the midpoint of a stop.
    rider = Road(3, half=True, **ARTERIAL)
    event = m.assess(
        crossing(Road(3, **ARTERIAL), incoming=rider, outgoing=rider, control=Control.NONE)
    )
    assert event is not None and event.cost_ft == m.PRIORITY_SIDE_FT


def test_a_signalised_three_and_a_half_crossing_stays_cheap() -> None:
    half = cost(Road(3, half=True, **ARTERIAL), ridetime.WEEKDAY_RUSH, control=Control.SIGNAL)
    four = cost(Road(4, **ARTERIAL), ridetime.WEEKDAY_RUSH, control=Control.SIGNAL)
    assert half < four


def test_a_half_step_crossing_says_its_half_step() -> None:
    event = m.assess(crossing(Road(3, half=True)))
    assert event is not None and event.crossed_tier == 3 and event.crossed_half
    assert "busy road (LTS 3.5)" in event.reason
    assert describe._crossed(3, True) == " (LTS 3.5)"
    assert describe._crossed(2, True) == " (LTS 2.5)"
    assert describe._crossed(4, True) == " (LTS 4.5)"
    assert describe._crossed(3, False) == " (LTS 3)"


def test_a_road_read_by_its_traffic_still_names_the_maps_half_step() -> None:
    # A four-lane 30 mph 2.5 road with a bike lane is crossed as LTS 4 (`by_traffic`);
    # the event names the map's rating, half step included.
    road = Road(2, half=True, lanes=2, speed_mph=30.0, oneway=False)
    event = m.assess(crossing(road))
    assert event is not None and event.crossed_tier == 2 and event.crossed_half


def test_two_three_and_a_half_roads_crossing_leave_the_rider_on_the_stopped_side() -> None:
    # Neither road is the busier, so the rider gives way: a 3.5 crossing's own cost.
    rider = Road(3, half=True, names=frozenset({"a"}), **ARTERIAL)
    crossed = Road(3, half=True, names=frozenset({"b"}), **ARTERIAL)
    for when in (None, ridetime.WEEKDAY_RUSH):
        both = cost(crossed, when, incoming=rider, outgoing=rider, control=Control.NONE)
        alone = cost(crossed, when, control=Control.NONE)
        assert both == pytest.approx(alone), when


def test_a_two_and_a_half_all_way_stop_costs_half_of_lts_three() -> None:
    three = cost(Road(3, **ARTERIAL), control=Control.ALL_STOP)
    assert cost(Road(2, half=True, **ARTERIAL), control=Control.ALL_STOP) == pytest.approx(
        three / 2
    )
