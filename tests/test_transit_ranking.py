"""Own bike + transit trips ranked by the time to get there with the busy roads and junctions on
top, and every Metro station taking a bike (Stephen, 2026-10-21: "We should order by time to get
there with a penalty for time taken on busy roads and intersections"; A at 106 min was listed above
B at 88 min, and NoMa, a block from him, was not offered).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest
from test_transit import (
    CAPITOL_HILL,
    DOWNTOWN,
    NOMA,
    Straight,
    at,
    doc_from,
    plan_bike,
    schedule,
    stop_named,
)

from core import api, presets, transit

FIXTURES = (schedule,)


def moment():
    return transit._moment(transit.day_zero(date(2026, 9, 30)).replace(hour=12), date(2026, 9, 30))


def ride(seconds: float, **kw) -> transit.Leg:
    return transit.Leg(transit.RIDE, seconds, ((0.0, 0.0), (0.01, 0.0)), **kw)


def option(key: str, *legs: transit.Leg) -> transit.Option:
    return transit.Option(key, tuple(legs))


# --- The score: time plus busy roads and junctions ------------------------------------------


def test_a_quicker_trip_on_busy_roads_ranks_below_a_calmer_one_but_shows_its_own_time() -> None:
    busy = option("busy", ride(1200.0, penalty_s=900.0, busy_m=3000.0))
    calm = option("calm", ride(1500.0, penalty_s=0.0, busy_m=0.0))
    assert busy.total_s < calm.total_s
    assert busy.score_s == 2100.0 and calm.score_s == 1500.0
    assert sorted([busy, calm], key=transit.rank_key) == [calm, busy]
    # The busy metres are said with the option; unknown where any ride's are not known.
    assert busy.busy_m == 3000.0 and calm.busy_m == 0.0
    assert option("x", ride(60.0, busy_m=10.0), ride(60.0)).busy_m is None


def test_a_traced_ride_is_penalized_by_its_busy_share_and_its_waits() -> None:
    # 600 s riding, 100 s of it waiting at junctions, a quarter of its metres busy.
    traced = transit.Ride(600.0, ((0.0, 0.0), (0.01, 0.0)), 2000.0, busy_m=500.0, waits_s=100.0)
    penalty, busy = transit.priced(traced, 600.0, 2000.0, transit.UNPRICED)
    assert penalty == pytest.approx(500 * 0.25 + 100) and busy == 500.0
    # A ride the router could not trace is priced as the whole ride was.
    pricing = transit.pricing_of(traced)
    penalty, busy = transit.priced(None, 300.0, 1000.0, pricing)
    assert penalty == pytest.approx(300 * 225 / 600) and busy == pytest.approx(250.0)
    # With no trace at all: no penalty, the busy roads unknown.
    assert transit.priced(None, 300.0, 1000.0, transit.UNPRICED) == (0.0, None)


def test_the_block_says_each_options_busy_metres_and_elevator_out(schedule) -> None:
    plan = plan_bike(schedule, CAPITOL_HILL, DOWNTOWN, at(2026, 9, 30, 8, 0))
    rows = transit.block(plan, schedule)["options"]
    assert all("busy_m" in row and row["elevator_out"] is False for row in rows)


# --- Re-ranked once the chosen trip's rides are routed ---------------------------------------


def two_trips() -> transit.Plan:
    # A first on its estimate (1000 s), B behind (1100 s).
    a = option("A", ride(400.0, estimated=True), transit.Leg(transit.METRO, 600.0))
    b = option("B", ride(500.0, estimated=True), transit.Leg(transit.METRO, 600.0))
    return transit.Plan(presets.BIKE_TRANSIT, [a, b], moment(), [])


def test_a_chosen_trip_routed_slower_than_the_next_moves_below_it() -> None:
    # The rider chose nothing: A's ride routes at 1000 s, so B is now best, and is chosen (the
    # caller then plans B).
    timed = transit.with_rides(two_trips(), {0: 1000.0}, keep=False)
    assert [o.key for o in timed.options] == ["B", "A"]
    assert timed.option.key == "B"
    # The rider chose A: it moves down, and stays chosen.
    kept = transit.with_rides(two_trips(), {0: 1000.0}, keep=True)
    assert [o.key for o in kept.options] == ["B", "A"]
    assert kept.option.key == "A"


def test_routed_busy_metres_replace_the_estimate_and_the_penalty_keeps_its_share() -> None:
    plan = two_trips()
    leg = replace(plan.options[0].legs[0], penalty_s=200.0, busy_m=100.0)
    plan = replace(plan, options=[replace(plan.options[0], legs=(leg, plan.options[0].legs[1]))])
    timed = transit.with_rides(plan, {0: 800.0}, {0: 750.0}).option.legs[0]
    assert timed.seconds == 800.0 and timed.penalty_s == pytest.approx(400.0)
    assert timed.busy_m == 750.0 and not timed.estimated


# --- A pick survives a fresh plan ------------------------------------------------------------


def test_a_pick_is_the_same_trip_by_another_pattern_of_the_same_line(schedule) -> None:
    plan = plan_bike(schedule, NOMA, DOWNTOWN, at(2026, 9, 30, 8, 0))
    picked = next(o for o in plan.options if not o.direct)
    # The same line's other pattern (its other direction's index is the neighbour).
    line = [
        i
        for i, p in enumerate(schedule.patterns)
        if (p.system, p.route) == (0, "Red Line") or (p.system, p.route) == (0, "Orange Line")
    ]
    index = next(int(t[1:]) for t in picked.key.replace("-", ">").split(">") if t[:1] == "p")
    twin = next(
        i
        for i in line
        if i != index
        and (schedule.patterns[i].system, schedule.patterns[i].route)
        == (schedule.patterns[index].system, schedule.patterns[index].route)
    )
    asked = picked.key.replace(f"p{index}", f"p{twin}", 1)
    assert asked not in [o.key for o in plan.options]
    assert transit.same_trip(schedule, asked, picked.key)
    chosen = transit.choose(plan, asked, schedule)
    assert chosen.option.key == picked.key and chosen.asked is None
    # Another line's pattern is another trip.
    other = next(i for i in range(len(schedule.patterns)) if schedule.patterns[i].system == 1)
    assert not transit.same_trip(
        schedule, picked.key.replace(f"p{index}", f"p{other}", 1), picked.key
    )
    assert not transit.same_trip(schedule, "direct", "direct")


# --- Every Metro station takes a bike --------------------------------------------------------


def test_a_station_the_elevator_files_miss_takes_a_bike_and_does_not_say_elevator() -> None:
    doc = doc_from()
    row = next(s for s in doc["stops"] if s["name"] == "Eastern Market")
    row["bike"] = None
    row.pop("bike_entrance", None)
    missed = stop_named(transit.parse(doc), "Eastern Market")
    assert missed.bike and missed.rail and not missed.elevator
    plan = transit.plan_bike(
        transit.parse(doc), CAPITOL_HILL, DOWNTOWN, at(2026, 9, 30, 8, 0), Straight(), 18.0
    )
    metro = next(o for o in plan.options if not o.direct and o.legs[0].to == "Eastern Market")
    enter = metro.legs[1]
    assert enter.mode == transit.ENTER and not enter.elevator
    assert "elevator" not in enter.words()
    # One the files know still says it.
    known = plan_bike(transit.parse(doc_from()), CAPITOL_HILL, DOWNTOWN, at(2026, 9, 30, 8, 0))
    known_metro = next(o for o in known.options if not o.direct)
    assert known_metro.legs[1].words().endswith("by the elevator.")


# --- An elevator out with no spare: 15 min on the score, never the time ----------------------


def test_an_elevator_out_with_no_spare_costs_15_min_on_the_score_only(schedule) -> None:
    when = at(2026, 9, 30, 8, 0)
    plain = plan_bike(schedule, CAPITOL_HILL, DOWNTOWN, when)
    metro = next(o for o in plain.options if not o.direct)
    eastern = stop_named(schedule, "Eastern Market")
    out = transit.with_elevators_out(schedule, [list(eastern.point)])
    assert stop_named(out, "Eastern Market").elevator_out_s == transit.ELEVATOR_OUT_S == 900.0
    marked = plan_bike(out, CAPITOL_HILL, DOWNTOWN, when)
    assert metro.legs[0].to == "Eastern Market"
    # The 15 min puts riding on to the next station ahead: Eastern Market is no longer the way in.
    best = next(o for o in marked.options if not o.direct)
    assert best.legs[0].to != "Eastern Market"
    # Its way in, ranked 15 min down, its time unchanged, and the row showing it.
    enter = transit._station_leg(transit.ENTER, stop_named(out, "Eastern Market"))
    assert (
        enter.seconds == transit.ACCESS_BIKE_S and enter.penalty_s == 900.0 and enter.elevator_out
    )
    trip = replace(metro, legs=(metro.legs[0], enter, *metro.legs[2:]))
    assert trip.total_s == pytest.approx(metro.total_s)
    assert trip.score_s == pytest.approx(metro.score_s + 900.0)
    row = transit.block(replace(plain, options=[trip]), out)["options"][0]
    assert row["elevator_out"] is True
    assert transit.with_elevators_out(schedule, []) is schedule


# --- Every ride's length, climb and profile on its step --------------------------------------


def test_a_later_rides_step_carries_its_length_climb_and_profile() -> None:
    block = {
        "steps": [
            {"route_line": True, "coordinates": [], "stress_spans": []},
            {"route_line": False, "coordinates": [], "stress_spans": []},
        ]
    }
    profile = {
        "interval_m": 10,
        "m": [0, 10],
        "elevation_m": [5, 6],
        "grade_pct": [1],
        "climbs": [],
    }
    answered = {
        "geometry": {"coordinates": [[0, 0], [0.01, 0]]},
        "stress_spans": [{"from_m": 0, "to_m": 900, "lts": 2}],
        "distance_m": 900.0,
        "climb_m": 12.0,
        "descent_m": 3.0,
        "profile": profile,
    }
    out = api._with_leg_lines(block, {0: answered, 1: answered})["steps"]
    # The first ride is the answer's own line: left as it is.
    assert "distance_m" not in out[0]
    assert out[1]["distance_m"] == 900.0 and out[1]["climb_m"] == 12.0
    assert out[1]["descent_m"] == 3.0 and out[1]["profile"] == profile
