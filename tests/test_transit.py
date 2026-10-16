"""The transit ride types (core.transit) and the schedule they read
(scripts/build_transit_schedule.py), against the synthetic GTFS fixture.

tests/data/transit holds small feeds written by its make_fixture.py, one per system:
- WMATA Metro: Orange from Eastern Market to Metro Center (every 10 min in the weekday morning,
  12 after, 15 on Saturdays) and Red from Union Station to Metro Center by frequencies.txt; no
  Sunday service, Thanksgiving 2026 removed, the Saturday of 2026-10-17 a planned shutdown, and a
  platform that matches no station;
- Metrobus: B10, Lincoln Park to Union Station every 15 min on weekdays;
- MARC: the Penn Line (Washington to Baltimore, frequent toward Washington in the morning and
  away in the evening, every two hours at weekends, its weekend timetable on Thanksgiving) and the
  Camden Line (weekdays only, three trains each way in the peak direction); College Park's
  step-free access unknown (it takes a bike all the same);
- Light RailLink: every 15 min on weekdays, 20 at weekends; one stop not step-free (likewise).
- VRE (built only into `vre_schedule`, so the other tests' closures stay as they are): the
  Fredericksburg and Manassas Lines through Alexandria to Union Station, weekdays only, every
  40 min each toward Washington in the morning and away in the evening; short names are numbers.
The places are real; the times are invented. A fake router rides straight lines, so every figure
is arithmetic.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import math
import shutil
import sys
from dataclasses import replace
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

import pytest
from test_route_api import CONTRACT_KEYS, router, segments, standard_router

from core import api, gbfs, presets, transit
from routemaker.ridetime import ZONE

# The API tests take these two of test_route_api's fixtures by name.
FIXTURES = (router, segments)

REPO = Path(__file__).resolve().parents[1]
DATA = Path(__file__).parent / "data" / "transit"
FEEDS = {name: DATA / name for name in ("wmata-rail", "wmata-bus", "marc", "mta-light-rail")}


def _build_module():
    spec = importlib.util.spec_from_file_location(
        "build_transit_schedule", REPO / "scripts" / "build_transit_schedule.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


build = _build_module()


@lru_cache(maxsize=4)
def built(start: date) -> tuple[str, tuple[str, ...]]:
    doc, report = build.build(FEEDS, start)
    return json.dumps(doc), tuple(report)


def doc_from(start: date = date(2026, 9, 28)) -> dict:
    return json.loads(built(start)[0])


@lru_cache(maxsize=4)
def schedule_from(start: date = date(2026, 9, 28)) -> transit.Schedule:
    return transit.parse(doc_from(start))


@pytest.fixture(scope="module")
def schedule():
    return schedule_from()


def at(*args) -> datetime:
    return datetime(*args, tzinfo=ZONE)


def stop_named(schedule, name: str) -> transit.Stop:
    return next(s for s in schedule.stops if s.name == name)


class Straight:
    """The router: straight lines at 18 km/h, the line as its two ends."""

    def __init__(self) -> None:
        self.calls = 0
        self.spent_s = 0.0

    def ride(self, a, b):
        self.calls += 1
        return transit.Ride(transit._distance(a, b) / (18 / 3.6), (tuple(a), tuple(b)))

    def walk(self, a, b):
        """On foot: the straight line at 3 mph (the planner's pace), its length given."""
        self.calls += 1
        metres = transit._distance(a, b)
        speed = transit.WALK_SPEED_KMH / 3.6
        return transit.Ride(metres / speed, (tuple(a), tuple(b)), metres)


# Near Eastern Market (east, a short ride), and near Federal Triangle (west).
CAPITOL_HILL = [-76.9930, 38.8830]
DOWNTOWN = [-77.0300, 38.8960]
# Near Union Station (Red and MARC), and near Smithsonian (Orange).
NOMA = [-77.0040, 38.9010]
MALL = [-77.0300, 38.8870]
# Downtown Baltimore, by Lexington Market (Light RailLink), not far from Penn Station.
BALTIMORE = [-76.6200, 39.2900]
LINCOLN_PARK = [-76.9893, 38.8899]


def plan_bike(schedule, start, end, when):
    return transit.plan_bike(schedule, start, end, when, Straight(), 18.0)


def transit_legs(option) -> list[transit.Leg]:
    return [leg for leg in option.legs if leg.transit]


# --- The schedule ---------------------------------------------------------------------------


def test_the_build_restates_the_bands_core_transit_reads() -> None:
    assert build.BANDS == transit.BANDS
    assert build.SCHEMA == transit.SCHEMA


def test_every_system_is_kept_with_its_bike_rule_and_what_did_not_fit(schedule) -> None:
    assert [s.id for s in schedule.systems] == ["wmata-rail", "wmata-bus", "marc", "mta-light-rail"]
    assert [s.vehicle for s in schedule.systems] == ["all", "all", "all", "all"]
    report = built(date(2026, 9, 28))[1]
    assert any("PF_XX_1" in line for line in report)
    assert any(line.startswith("mta-metro: no feed given") for line in report)


def test_stations_and_whether_a_bike_may_board_there(schedule) -> None:
    eastern = stop_named(schedule, "Eastern Market")
    # The map's bike entrance: DC's elevator (rule 1), not the station point.
    assert eastern.bike and eastern.rail and eastern.bike_entrance != eastern.point
    # Every MARC and MTA station takes a bike, whatever GTFS says of step-free access (the
    # owner, 2026-10-12: ramps or elevators everywhere, and stairs in a pinch): Union Station's
    # platform says nothing, College Park's access is unknown, University Center's is not
    # step-free. A bus stop takes a bike at the curb.
    assert stop_named(schedule, "Union Station MARC").bike
    assert stop_named(schedule, "College Park").bike
    assert stop_named(schedule, "University Center/Baltimore St").bike
    lincoln = stop_named(schedule, "Lincoln Park")
    assert lincoln.bike and not lincoln.rail
    # Only the stops a pattern uses are kept.
    assert len(schedule.stops) == 25


def test_the_calendar_is_kept_day_by_day_with_holidays_and_closures() -> None:
    doc = doc_from()
    metro_saturday = next(
        s["days"] for s in doc["services"] if s["system"] == 0 and s["days"][5] == "1"
    )
    # 2026-10-10 (offset 12) runs; 2026-10-17 (offset 19) is the planned shutdown.
    assert metro_saturday[12] == "1" and metro_saturday[19] == "0"
    thanksgiving = schedule_from(date(2026, 11, 20))
    day = (date(2026, 11, 26) - thanksgiving.start).days
    marc_services = sorted(
        {s for p in thanksgiving.patterns if p.system == 2 for s in p.trips},
    )
    # MARC's weekday service is removed and its weekend one added: one runs that day.
    assert sorted(thanksgiving.services[i][day] for i in marc_services) == ["0", "1"]


def test_runs_and_departures_by_pattern(schedule) -> None:
    orange = next(
        p
        for p in schedule.patterns
        if p.route == "Orange Line" and schedule.stops[p.stops[0]].name == "Eastern Market"
    )
    assert orange.runs_at(8 * 60)[:3] == (0, 120, 240)
    # Red is frequencies.txt, expanded into its trips: every 6 minutes from 06:00.
    red = next(p for p in schedule.patterns if p.route == "Red Line")
    weekday = max(red.trips.values(), key=len)  # the weekday's, every 6 minutes
    assert [d >> 1 for d in weekday[:3]] == [360, 366, 372]
    assert all(d & 1 for d in weekday)  # every Metro trip takes a bike


def test_a_file_of_another_schema_or_bands_is_refused(tmp_path) -> None:
    doc = doc_from()
    with pytest.raises(transit.Unavailable):
        transit.parse({**doc, "schema": 1})
    with pytest.raises(transit.Unavailable):
        transit.parse({**doc, "bands": doc["bands"][:-1]})
    (tmp_path / "broken.json").write_text("{")
    with pytest.raises(transit.Unavailable):
        transit.load(tmp_path / "broken.json")
    path = tmp_path / "schedule.json"
    path.write_text(json.dumps(doc))
    assert transit.load(path).systems[0].name == "Metro"


# --- The wait and the ride ----------------------------------------------------------------------


def test_a_frequent_service_waits_half_its_headway(schedule) -> None:
    day = transit._Day(schedule, transit.moment_of(at(2026, 9, 30, 8, 0)), bike=False)
    eastern = stop_named(schedule, "Eastern Market")
    triangle = stop_named(schedule, "Federal Triangle")
    hop = day.reach(eastern.index, 8 * 60)[triangle.index]
    assert (hop.wait_s, hop.ride_s, hop.routes, hop.frequent) == (300, 600, ("Orange Line",), True)
    assert len(hop.path) == 6 and hop.depart is None
    # Midday, every 12 minutes.
    assert day.reach(eastern.index, 12 * 60)[triangle.index].wait_s == 360
    # Not running before its first train, or on a Sunday (no Sunday service here).
    assert day.reach(eastern.index, 4 * 60) == {}
    sunday = transit._Day(schedule, transit.moment_of(at(2026, 10, 4, 12, 0)), bike=False)
    assert sunday.reach(eastern.index, 12 * 60) == {}


def test_frequent_means_every_gap_short_over_three_or_four_departures() -> None:
    # Every 6 min: frequent, the mean gap.
    assert transit.headway([480, 486, 492, 498]) == 6
    # A near pair, then a long gap: not frequent (the wait is the actual next departure).
    assert transit.headway([480, 484, 540, 600]) == math.inf
    # Two patterns leaving the same minute count once: 480, 490, 500 is every 10 min.
    assert transit.headway([480, 480, 490, 490.2, 500]) == 10
    # Two departures only (the end of service): not enough to call it frequent.
    assert transit.headway([480, 485]) == math.inf
    # Uneven but all short: the mean gap.
    assert transit.headway([480, 484, 496, 500]) == pytest.approx(20 / 3)


def test_a_near_pair_before_a_long_gap_waits_for_the_actual_departure() -> None:
    class P:
        def __init__(self, index, route):
            self.index, self.route, self.system = index, route, 0
            self.stops = (1, 2)

    near = [([484.0, 488.0, 540.0], 600.0, P(0, "A"), 0, 1)]
    hop = transit._hop(480.0, near)
    assert not hop.frequent and hop.wait_s == 4 * 60 and hop.depart == 484 and hop.after == 488
    every = [([484.0, 490.0, 496.0, 502.0], 600.0, P(0, "A"), 0, 1)]
    assert transit._hop(480.0, every).frequent and transit._hop(480.0, every).wait_s == 180


def test_an_infrequent_service_waits_for_its_next_departure_and_names_the_one_after(
    schedule,
) -> None:
    day = transit._Day(schedule, transit.moment_of(at(2026, 9, 30, 6, 40)), bike=True)
    union = stop_named(schedule, "Union Station MARC")
    penn = stop_named(schedule, "Baltimore Penn Station")
    hop = day.reach(union.index, 6 * 60 + 40)[penn.index]
    # Hourly away from Washington in the morning: the 7:00, then the 8:00.
    assert not hop.frequent
    assert (hop.depart, hop.after, hop.wait_s) == (420, 480, 1200)
    leg = transit._transit_leg(schedule, hop, False, True)
    assert leg.words() == (
        "Board the MARC Penn Line at 7:00 am scheduled from Union Station MARC: you arrive"
        " 6:40 am, 20 min spare; next train after that: 8:00 am scheduled. Ride 45 min to"
        " Baltimore Penn Station."
    )


def test_go_is_told_the_departure_and_the_time_to_spare(schedule) -> None:
    plan = plan_bike(schedule, NOMA, BALTIMORE, at(2026, 9, 30, 6, 20))
    out = transit.block(plan, schedule)
    departure = out["departure"]
    marc = out["steps"][departure["step"]]
    assert marc["mode"] == "rail" and marc["departs"] == "7:00 am"
    assert departure["departs"] == "7:00 am" and departure["next"] == "8:00 am"
    assert departure["departs_at"] == "2026-09-30T07:00:00-04:00"
    assert departure["board_at"] == "Union Station MARC"
    spare = departure["spare_s"]
    assert departure["label"] == f"MARC 7:00 am scheduled · {round(spare / 60)} min spare"
    # Where the times are from, for the page's word (live times, v0.7, will say "live").
    assert departure["source"] == "scheduled" and marc["source"] == "scheduled"
    assert departure["close"] is (spare < transit.CLOSE_S)
    # A frequent service has no departure to time.
    metro = plan_bike(schedule, CAPITOL_HILL, DOWNTOWN, at(2026, 9, 30, 8, 0))
    key = next(o.key for o in metro.options if not o.direct)
    assert transit.block(transit.choose(metro, key), schedule)["departure"] is None


def test_a_slower_routed_ride_that_misses_the_train_takes_the_next(schedule) -> None:
    plan = plan_bike(schedule, NOMA, BALTIMORE, at(2026, 9, 30, 6, 20))
    on_time = transit.block(plan, schedule)["departure"]
    assert on_time["departs"] == "7:00 am"
    # The routed first ride takes 50 min more than the estimate: the 7:00 is missed.
    slower = transit.with_ride(plan, plan.legs[0].seconds + 3000)
    out = transit.block(slower, schedule)
    assert out["departure"]["departs"] == "8:00 am"
    assert any(
        n.startswith("You would miss the 7:00 am scheduled (the MARC Penn Line)")
        for n in out["notes"]
    )
    assert out["total_s"] > transit.block(plan, schedule)["total_s"]
    # The one after the new departure is recomputed, not dropped: the 9:00.
    assert out["departure"]["next"] == "9:00 am"


def test_a_trip_whose_every_departure_is_missed_is_left_out_not_totalled(schedule) -> None:
    plan = plan_bike(schedule, NOMA, BALTIMORE, at(2026, 9, 30, 6, 20))
    chosen = plan.option.key
    # Four hours late on the first ride: no departure seen can be caught.
    late = transit.with_ride(plan, plan.legs[0].seconds + 4 * 3600)
    assert chosen not in {o.key for o in late.options}
    assert late.option.key != chosen
    assert any("no later one leaves within the hour" in n for n in late.notes)


def test_the_service_day_runs_to_3_am_and_a_holiday_is_flagged() -> None:
    late = transit.moment_of(at(2026, 10, 3, 1, 30))  # a Saturday, 1:30 am
    assert (late.service_day, late.minute) == (date(2026, 10, 2), 25 * 60 + 30)
    assert late.date == date(2026, 10, 3) and late.day_type == "weekday"
    thanksgiving = transit.moment_of(at(2026, 11, 26, 9, 0))
    assert thanksgiving.holiday and not thanksgiving.rush(8 * 60)
    assert transit.moment_of(at(2026, 9, 30, 8, 0)).rush(8 * 60)
    assert transit.clock(25 * 60 + 30) == "1:30 am" and transit.clock(19 * 60 + 42) == "7:42 pm"


def test_times_are_real_across_the_end_of_daylight_saving_on_2026_11_01() -> None:
    # 2026-11-01 has 25 hours (2 am EDT becomes 1 am EST). GTFS times count from noon less 12 h,
    # so its 08:00 is 8 am EST, and the page's clock carries the right offset.
    morning = transit.moment_of(at(2026, 11, 1, 8, 0))
    assert (morning.service_day, morning.minute) == (date(2026, 11, 1), 8 * 60)
    assert transit._local(morning, 8 * 60 + 42) == "2026-11-01T08:42:00-05:00"
    # 1:30 am the first time (EDT) is still Saturday's service day, 25:30.
    first = transit.moment_of(datetime(2026, 11, 1, 1, 30, tzinfo=ZONE, fold=0))
    assert (first.service_day, first.minute) == (date(2026, 10, 31), 25 * 60 + 30)
    # The second 1:30 am (EST) is an hour later in real time: 26:30 of Saturday's service day.
    second = transit.moment_of(datetime(2026, 11, 1, 1, 30, tzinfo=ZONE, fold=1))
    assert second.minute == 26 * 60 + 30
    assert transit._local(second, second.minute) == "2026-11-01T01:30:00-05:00"
    # The spring change too: 2027-03-14 at 9 am EDT is GTFS 09:00.
    assert transit.moment_of(at(2027, 3, 14, 9, 0)).minute == 9 * 60


def test_the_clock_says_the_wall_time_on_daylight_saving_nights() -> None:
    # 2026-11-01: GTFS zero is 1:00 am EDT. Its 00:30 is the first 1:30 am, its 08:00 is 8 am.
    fall = date(2026, 11, 1)
    assert transit.clock(30, fall) == "1:30 am" and transit.clock(8 * 60, fall) == "8:00 am"
    # Saturday's owl at 26:30 leaves at the second 1:30 am (EST), not "2:30 am".
    assert transit.clock(26 * 60 + 30, date(2026, 10, 31)) == "1:30 am"
    # 2027-03-14: GTFS zero is 11:00 pm EST the night before; its 08:00 is 8 am EDT.
    spring = date(2027, 3, 14)
    assert transit.clock(30, spring) == "11:30 pm" and transit.clock(8 * 60, spring) == "8:00 am"
    # Saturday 2027-03-13's 26:30 is 3:30 am EDT (2:30 am does not exist that night).
    assert transit.clock(26 * 60 + 30, date(2027, 3, 13)) == "3:30 am"
    # Without a service day, the minute read as a plain day (as before).
    assert transit.clock(26 * 60 + 30) == "2:30 am"


def test_around_3_am_both_service_days_are_searched_owl_trips_past_27_00_included() -> None:
    schedule = schedule_from(date(2026, 9, 28))
    when = at(2026, 10, 1, 3, 20)  # Thursday 3:20 am
    moments = transit.moments_of(when)
    assert [m.service_day for m in moments] == [date(2026, 10, 1), date(2026, 9, 30)]
    assert [m.minute for m in moments] == [200, 27 * 60 + 20]
    assert len(transit.moments_of(at(2026, 10, 1, 9, 0))) == 1
    # Wednesday's owl Light RailLink leaves Camden Yards at 27:30, 3:30 am Thursday.
    plan = transit.plan_bikeshare(
        schedule, [-76.6206, 39.2849], [-76.6159, 39.3071], when, Straight(), NO_DOCKS
    )
    owl = next(o for o in plan.options for leg in o.legs if leg.system == "Light RailLink")
    leg = next(leg for leg in owl.legs if leg.transit)
    # Boarded at Convention Center, a stop that is not a timepoint: 27:32, interpolated.
    assert leg.board_at == "Convention Center" and leg.depart == 27 * 60 + 32
    assert owl.moment.service_day == date(2026, 9, 30)
    out = transit.block(transit.choose(plan, owl.key), schedule)
    assert out["departure"]["departs_at"] == "2026-10-01T03:32:00-04:00"
    assert out["departure"]["departs"] == "3:32 am" and leg.service_day == date(2026, 9, 30)


def test_stops_that_are_not_timepoints_are_interpolated_not_dropped() -> None:
    rows = [(1, "A", 100, None), (2, "B", None, None), (3, "C", None, None), (4, "D", 400, None)]
    assert build.interpolated(rows) == [(1, "A", 100), (2, "B", 200), (3, "C", 300), (4, "D", 400)]
    by_distance = [(1, "A", 0, 0.0), (2, "B", None, 900.0), (3, "C", 100, 1000.0)]
    assert build.interpolated(by_distance)[1] == (2, "B", 90)
    # Untimed at either end: nothing to interpolate from, dropped.
    assert build.interpolated([(1, "A", None, None), (2, "B", 50, None)]) == [(2, "B", 50)]
    # The owl trip's blank middle stops keep it on the Light RailLink's one stop order.
    doc = doc_from()
    names = [s["name"] for s in doc["stops"]]
    light = [p for p in doc["patterns"] if names[p["stops"][0]] == "Camden Yards"]
    assert len(light) == 1 and len(light[0]["stops"]) == 5


def test_a_schedule_about_to_run_out_is_logged_and_alerted(tmp_path, caplog) -> None:
    path = tmp_path / "transit-schedule.json"
    path.write_text(built(date(2026, 9, 28))[0])
    schedule = transit.load(path, date(2026, 10, 1))
    assert schedule.last_day == date(2026, 11, 11)
    assert transit.days_left(schedule, date(2026, 11, 8)) == 4
    assert transit.schedule_alert(path, date(2026, 10, 1)) is None
    assert "4 day(s) left" in transit.schedule_alert(path, date(2026, 11, 8))
    assert "ran out on 2026-11-11" in transit.schedule_alert(path, date(2026, 11, 20))
    assert transit.schedule_alert(tmp_path / "none.json") is None
    (tmp_path / "bad.json").write_text("{")
    assert transit.schedule_alert(tmp_path / "bad.json").startswith("transit: ")
    # The log line, once a day, when the file is read.
    transit._warned_on = None
    with caplog.at_level("WARNING", logger=transit.logger.name):
        transit._warn_if_stale(schedule)  # today (2026-10-12 or later): under a week? only if so
    expected = transit.days_left(schedule) < transit.STALE_DAYS
    assert ("the transit schedule runs out" in caplog.text) is expected


def test_a_walk_of_a_few_yards_is_not_the_answers_line() -> None:
    a, b = (-77.0, 38.9), (-77.00005, 38.9)  # about 4 m apart
    far = (-77.01, 38.9)
    legs = (
        transit.Leg(transit.WALK, 3.0, (a, b)),
        transit.Leg(transit.ENTER, 120.0),
        transit.Leg("metro", 600.0, (b, far)),
        transit.Leg(transit.EXIT, 120.0),
        transit.Leg(transit.WALK, 400.0, (far, (-77.02, 38.9))),
    )
    assert transit.line_m(legs[0]) < transit.MIN_LINE_M
    # The first walk is a few yards: the line is the last walk, which the router can route.
    assert transit.Option("k", legs).ride == 4
    # Every ride and walk a few yards: the first walk, which the API draws start to end instead.
    tiny = (legs[0], legs[1], legs[2], legs[3], transit.Leg(transit.WALK, 3.0, (far, far)))
    assert transit.Option("k", tiny).ride == 0


def test_the_blackout_list_has_july_4_every_year_and_dates_by_hand(tmp_path) -> None:
    assert transit.bike_blackout(date(2026, 7, 4))
    assert transit.bike_blackout(date(2031, 7, 4))
    assert transit.bike_blackout(date(2029, 1, 20))
    assert not transit.bike_blackout(date(2026, 7, 5))
    own = tmp_path / "blackouts.json"
    own.write_text(json.dumps({"dates": [{"date": "2027-03-28", "why": "peak bloom"}]}))
    assert transit.bike_blackout(date(2027, 3, 28), own)
    # An unreadable list flags nothing, rather than failing the plan.
    assert not transit.bike_blackout(date(2026, 7, 4), tmp_path / "missing.json")


# --- Own Bike + 🚆🚌 ---------------------------------------------------------------------------


def test_own_bike_lists_the_direct_ride_and_the_quickest_transit_trips(schedule) -> None:
    straight = Straight()
    plan = transit.plan_bike(
        schedule, CAPITOL_HILL, DOWNTOWN, at(2026, 9, 30, 8, 0), straight, 18.0
    )
    totals = [transit.minutes(o.total_s) for o in plan.options]
    assert totals == sorted(totals)
    assert sum(o.direct for o in plan.options) == 1
    assert len(plan.options) <= transit.TRANSIT_OPTIONS + 1
    assert straight.calls <= transit.MAX_ROUTER_CALLS
    metro = next(o for o in plan.options if not o.direct)
    assert [leg.mode for leg in metro.legs] == ["ride", "enter", "metro", "exit", "ride"]
    assert metro.legs[0].to == "Eastern Market" and metro.legs[2].to == "Federal Triangle"
    assert transit.label(metro, presets.BIKE_TRANSIT) == (
        "Ride, Metro to Federal Triangle (Orange Line), ride"
    )
    words = [leg.words(last=i == 4) for i, leg in enumerate(metro.legs)]
    assert words[1] == "About 4 min into the station by the elevator."
    assert words[2] == (
        "Board the Orange Line (every 10 min, scheduled; about 5 min wait); ride 10 min to"
        " Federal Triangle."
    )
    assert words[4].endswith("min to your destination.")


def _valhalla(seconds: float, a, b) -> dict:
    from test_route_api import encode_polyline6

    return {
        "trip": {
            "legs": [
                {"shape": encode_polyline6([tuple(a), tuple(b)]), "summary": {"time": seconds}}
            ]
        }
    }


def test_a_router_that_fails_after_the_first_call_still_gives_the_direct_ride(
    schedule, monkeypatch
) -> None:
    from core import routing

    calls = []

    def flaky(variant, endpoint, payload, deadline):
        calls.append(deadline)
        if len(calls) == 1:
            locs = payload["locations"]
            a, b = [locs[0]["lon"], locs[0]["lat"]], [locs[1]["lon"], locs[1]["lat"]]
            return _valhalla(777.0, a, b)
        raise (routing.RouterUnavailable if len(calls) % 2 else routing.DeadlineExceeded)("down")

    monkeypatch.setattr(routing, "_call", flaky)
    services = transit.RoutingServices(routing.clock() + 30, presets.BIKE_TRANSIT)
    plan = transit.plan_bike(
        schedule, CAPITOL_HILL, DOWNTOWN, at(2026, 9, 30, 8, 0), services, 18.0
    )
    # The direct ride was asked first, and has the router's own time.
    assert plan.direct is not None and plan.direct.total_s == 777.0
    # Every later call failed: the candidates were estimated, and transit is still offered.
    assert any(not o.direct for o in plan.options)
    assert 1 < len(calls) <= transit.MAX_ROUTER_CALLS
    # Each call was capped.
    assert all(d.per_call_s <= transit.CANDIDATE_CALL_S for d in calls)


def test_the_router_calls_stop_at_the_cap_and_the_budget(schedule, monkeypatch) -> None:
    from core import routing

    calls = []

    def slow(variant, endpoint, payload, deadline):
        calls.append(deadline)
        raise routing.RouterUnavailable("down")

    monkeypatch.setattr(routing, "_call", slow)
    capped = transit.RoutingServices(routing.clock() + 30, presets.BIKE_TRANSIT, max_calls=2)
    plan = transit.plan_bike(schedule, CAPITOL_HILL, DOWNTOWN, at(2026, 9, 30, 8, 0), capped, 18.0)
    assert len(calls) == 2 and capped.calls == 2
    # With no answer at all, the direct ride is estimated from the straight line, still offered.
    assert plan.direct is not None and plan.direct.legs[0].estimated
    calls.clear()
    spent = transit.RoutingServices(routing.clock() - 1, presets.BIKE_TRANSIT)
    transit.plan_bike(schedule, CAPITOL_HILL, DOWNTOWN, at(2026, 9, 30, 8, 0), spent, 18.0)
    assert calls == []


def test_own_bike_never_walks(schedule) -> None:
    for when in (at(2026, 9, 30, 8, 0), at(2026, 9, 30, 6, 20), at(2026, 10, 3, 10, 0)):
        for start, end in ((CAPITOL_HILL, DOWNTOWN), (NOMA, BALTIMORE), (LINCOLN_PARK, MALL)):
            plan = plan_bike(schedule, start, end, when)
            for option in plan.options:
                assert all(leg.mode not in (transit.WALK, transit.TAKE) for leg in option.legs)
                assert all(leg.bike for leg in transit_legs(option))
                assert len(transit_legs(option)) <= transit.MAX_LEGS


def test_a_change_at_the_same_station(schedule) -> None:
    plan = plan_bike(schedule, NOMA, MALL, at(2026, 9, 30, 8, 0))
    changed = next(o for o in plan.options if len(transit_legs(o)) == 2)
    first, second = transit_legs(changed)
    assert (first.lines, first.to, second.lines, second.to, second.change) == (
        ("Red Line",),
        "Metro Center",
        ("Orange Line",),
        "Smithsonian",
        True,
    )
    assert second.words().startswith("Change to the Orange Line (every 10 min, scheduled;")


def test_dc_to_baltimore_takes_marc_with_the_bike(schedule) -> None:
    plan = plan_bike(schedule, NOMA, BALTIMORE, at(2026, 9, 30, 6, 20))
    best = plan.options[0]
    assert not best.direct
    assert [(leg.system, leg.lines) for leg in transit_legs(best)] == [("MARC", ("Penn Line",))]
    out = transit.block(plan, schedule)
    assert out["credits"] == ["MDOT MTA GTFS (scheduled times)"]
    assert any(n == "MARC: ride in the car marked for bikes." for n in out["notes"])
    assert transit.SCHEDULED_WORDS in out["notes"]
    # Each rule is said once, however many legs ride that system.
    assert len(out["notes"]) == len(set(out["notes"]))
    # Light RailLink takes a bike in the weekday rush too (the owner, 2026-10-12: "you can use
    # it unless it's too crowded to do so").
    assert "Light RailLink: no bikes on board at this time." not in out["notes"]


def test_the_light_rail_takes_a_bike_at_rush_hour_and_outside_it(schedule) -> None:
    light_rail = next(
        p for p in schedule.patterns if schedule.systems[p.system].name == "Light RailLink"
    )
    rush = transit._Day(schedule, transit.moment_of(at(2026, 9, 30, 7, 30)), True)
    assert rush.moment.rush(7 * 60 + 30) and rush.boards(light_rail, 7 * 60 + 30, 1)
    plan = plan_bike(schedule, NOMA, BALTIMORE, at(2026, 10, 3, 10, 0))
    assert any(
        [leg.system for leg in transit_legs(o)] == ["MARC", "Light RailLink"] for o in plan.options
    )


# --- VRE --------------------------------------------------------------------------------------

# Old Town Alexandria, by VRE's Alexandria station; the Metro of the fixture does not reach it.
OLD_TOWN = [-77.0590, 38.8060]


@pytest.fixture(scope="module")
def vre_schedule():
    doc, _report = build.build({**FEEDS, "vre": DATA / "vre"}, date(2026, 9, 28))
    return transit.parse(doc)


def test_vre_is_built_with_every_train_and_station_taking_a_bike(vre_schedule) -> None:
    vre = next(s for s in vre_schedule.systems if s.id == "vre")
    assert (vre.name, vre.mode, vre.vehicle) == ("VRE", "rail", "all")
    assert vre.source == "https://www.vre.org/about/onboard-policies/"
    stations = [s for s in vre_schedule.stops if vre_schedule.systems[s.system] is vre]
    assert "Union Station VRE" in {s.name for s in stations} and all(s.bike for s in stations)
    # Named by the long name, not the code (systems.json `route_name` long).
    routes = {p.route for p in vre_schedule.patterns if vre_schedule.systems[p.system] is vre}
    assert routes == {"Fredericksburg Line", "Manassas Line"}


def test_a_weekday_vre_trip_plans_with_the_bike_and_says_the_rule_once(vre_schedule) -> None:
    plan = plan_bike(vre_schedule, OLD_TOWN, NOMA, at(2026, 9, 30, 6, 0))
    best = plan.options[0]
    assert [(leg.system, leg.lines) for leg in transit_legs(best)] == [("VRE", ("Manassas Line",))]
    out = transit.block(plan, vre_schedule)
    assert out["credits"] == ["VRE GTFS (scheduled times)"]
    # Its row's legs name VRE and the line, for the mark "🚆Manassas" (lib/transitMarks.ts).
    row = next(o for o in out["options"] if o["key"] == best.key)
    assert [(leg["mode"], leg["system"], leg["lines"]) for leg in row["legs"]][1] == (
        "rail",
        "VRE",
        ["Manassas Line"],
    )
    assert any(
        step["text"].startswith("Board the VRE Manassas Line at 6:10 am scheduled from Alexandria")
        for step in out["steps"]
    )
    rule = "VRE: board last; bungee it to a car's south-end bench."
    assert out["notes"].count(rule) == 1
    # Two VRE legs (a change of line) still say the rule once.
    twice = next(o for o in plan.options if [x.system for x in transit_legs(o)] == ["VRE", "VRE"])
    assert transit.block(transit.choose(plan, twice.key), vre_schedule)["notes"].count(rule) == 1


def test_vre_runs_weekdays_only_and_says_so_at_weekends(vre_schedule) -> None:
    saturday = plan_bike(vre_schedule, OLD_TOWN, NOMA, at(2026, 10, 3, 10, 0))
    assert "VRE Fredericksburg Line: no weekend service." in saturday.notes
    assert "VRE Manassas Line: no weekend service." in saturday.notes
    assert not any(leg.system == "VRE" for o in saturday.options for leg in o.legs)
    closed = transit.closed_stations(vre_schedule, transit.moment_of(at(2026, 10, 3, 12, 0)))
    vre = [c for c in closed if c.system.id == "vre"]
    assert "Alexandria" in {c.stop.name for c in vre}
    assert {c.reason for c in vre} == {"no VRE weekend service"}


def test_a_vre_station_says_its_next_train_each_way_and_none_at_weekends(vre_schedule) -> None:
    alexandria = [-77.0618, 38.8064]
    weekday = [
        t
        for t in transit.station_times(vre_schedule, alexandria, at(2026, 9, 30, 6, 0))
        if t.system.id == "vre"
    ]
    assert {t.route for t in weekday} == {"Fredericksburg Line", "Manassas Line"}
    assert all(t.kind in ("next", "none") for t in weekday)
    assert any(t.kind == "next" and t.depart is not None and t.toward for t in weekday)
    saturday = [
        (t.route, t.kind, t.today)
        for t in transit.station_times(vre_schedule, alexandria, at(2026, 10, 3, 12, 0))
        if t.system.id == "vre"
    ]
    assert sorted(saturday) == [
        ("Fredericksburg Line", "none", False),
        ("Manassas Line", "none", False),
    ]


def test_a_line_that_does_not_run_at_weekends_drops_out_and_is_said_plainly(schedule) -> None:
    saturday = plan_bike(schedule, NOMA, BALTIMORE, at(2026, 10, 3, 10, 0))
    assert "MARC Camden Line: no weekend service." in saturday.notes
    assert not any("Camden Line" in leg.lines for o in saturday.options for leg in o.legs)
    # On a weekday the Camden Line runs, but from Washington only in the evening.
    weekday = plan_bike(schedule, NOMA, BALTIMORE, at(2026, 9, 30, 12, 0))
    assert "MARC Camden Line: no service at this time." in weekday.notes


def test_a_holiday_runs_each_systems_holiday_timetable() -> None:
    schedule = schedule_from(date(2026, 11, 20))
    plan = plan_bike(schedule, NOMA, BALTIMORE, at(2026, 11, 26, 8, 30))
    assert "MARC Camden Line: no holiday service." in plan.notes
    # MARC's weekend timetable runs (the 9:00 from Washington); Metro has no service at all.
    marc = next(o for o in plan.options if not o.direct)
    assert [leg.depart for leg in transit_legs(marc)] == [9 * 60]
    assert not any(leg.system == "Metro" for o in plan.options for leg in o.legs)
    assert transit.HOLIDAY_WORDS in transit.block(plan, schedule)["notes"]


def test_a_planned_shutdown_closes_metro_for_the_day(schedule) -> None:
    plan = plan_bike(schedule, CAPITOL_HILL, DOWNTOWN, at(2026, 10, 17, 12, 0))
    assert [o.direct for o in plan.options] == [True]
    assert transit.NO_TRANSIT_WORDS in plan.notes
    closed = transit.closed_stations(schedule, transit.moment_of(at(2026, 10, 17, 12, 0)))
    metro = [c for c in closed if c.system.id == "wmata-rail"]
    assert {c.stop.name for c in metro} >= {"Eastern Market", "Union Station", "Metro Center"}
    assert {c.reason for c in metro} == {"no Metro weekend service"}


def test_a_station_closed_for_the_day_is_one_with_no_service_at_all_that_day(schedule) -> None:
    saturday = transit.closed_stations(schedule, transit.moment_of(at(2026, 10, 3, 12, 0)))
    assert [(c.stop.name, c.reason) for c in saturday] == [
        ("Camden Station", "no MARC weekend service"),
        ("College Park", "no MARC weekend service"),
    ]
    # Out of its hours on a day it runs is not closed: Camden Station on a weekday evening.
    assert transit.closed_stations(schedule, transit.moment_of(at(2026, 9, 30, 22, 30))) == []
    # Sunday: no Metro in this fixture at all.
    sunday = transit.closed_stations(schedule, transit.moment_of(at(2026, 10, 4, 12, 0)))
    assert "Eastern Market" in {c.stop.name for c in sunday}


def test_after_midnight_a_station_that_runs_on_the_new_date_is_not_closed(schedule) -> None:
    # 1 am Monday is still Sunday's service day, when MARC's Camden Line and (in this fixture)
    # Metro do not run; but both run on Monday, so no station is closed: its card gives
    # Monday's first train instead.
    night = transit.moment_of(at(2026, 10, 5, 1, 0))
    assert night.service_day == date(2026, 10, 4)
    assert transit.closed_stations(schedule, night) == []
    camden = next(s for s in schedule.stops if s.name == "Camden Station")
    first = [
        (t.kind, t.service_day)
        for t in transit.station_times(schedule, list(camden.point), at(2026, 10, 5, 1, 0))
        if t.route == "Camden Line"
    ]
    assert first == [("next", date(2026, 10, 5))]
    # Before midnight it is closed, and 1 am Sunday (Saturday's service day, no MARC on Sunday
    # either) it still is.
    sunday_night = transit.closed_stations(schedule, transit.moment_of(at(2026, 10, 4, 23, 30)))
    assert "Eastern Market" in {c.stop.name for c in sunday_night}
    saturday_night = transit.closed_stations(schedule, transit.moment_of(at(2026, 10, 4, 1, 0)))
    assert "Camden Station" in {c.stop.name for c in saturday_night}
    # A plan at 1 am still waits for the trains' actual times: nothing runs until the morning.
    plan = plan_bike(schedule, NOMA, BALTIMORE, at(2026, 10, 5, 1, 0))
    assert [o.direct for o in plan.options] == [True]
    # Its notes say the lines that run on Monday are out of their hours, not "no weekend
    # service"; at 1 am Sunday they still are "no weekend service".
    assert "MARC Camden Line: no service at this time." in plan.notes
    assert not any("weekend" in note for note in plan.notes)
    sunday = plan_bike(schedule, NOMA, BALTIMORE, at(2026, 10, 4, 1, 0))
    assert "MARC Camden Line: no weekend service." in sunday.notes


# --- A station's times, for its card on the map (the owner, 2026-10-12) ---------------------

UNION_STATION = [-77.0063, 38.8971]
PENN_STATION = [-76.6157, 39.3075]


def times_at(schedule, point, when) -> list[tuple]:
    return [
        (t.system.name, t.route, t.kind, t.every_min, t.toward, t.depart, t.today)
        for t in transit.station_times(schedule, point, when)
    ]


def test_a_station_says_each_frequent_lines_interval_and_each_commuter_lines_next_train_each_way(
    schedule,
) -> None:
    # Wednesday 8 am at Union Station: Red every 6 min (frequencies.txt), and MARC's next trains
    # leaving it (Union Station is the terminal: one way each). Only the nearest stop of each
    # system counts, so the bus bay beside it is not one.
    assert times_at(schedule, UNION_STATION, at(2026, 9, 30, 8, 0)) == [
        ("Metro", "Red Line", "every", 6, None, None, True),
        ("MARC", "Camden Line", "next", None, "Camden Station", 16 * 60 + 30, True),
        ("MARC", "Penn Line", "next", None, "Baltimore Penn Station", 8 * 60, True),
    ]
    # Baltimore Penn Station: the Penn Line toward Washington, and Light RailLink every 15 min.
    assert times_at(schedule, PENN_STATION, at(2026, 9, 30, 17, 30)) == [
        ("MARC", "Penn Line", "next", None, "Union Station MARC", 18 * 60, True),
        ("Light RailLink", "Light RailLink", "every", 15, None, None, True),
    ]


def test_a_station_says_plainly_when_no_more_trains_run_today(schedule) -> None:
    late = times_at(schedule, UNION_STATION, at(2026, 9, 30, 23, 30))
    assert ("MARC", "Penn Line", "none", None, "Baltimore Penn Station", None, True) in late
    assert all(kind == "none" and today for _s, _r, kind, *_x, today in late)
    # A Saturday: the Camden Line does not run at all (one line for both ways), the Penn Line does.
    saturday = times_at(schedule, UNION_STATION, at(2026, 10, 3, 12, 0))
    assert ("MARC", "Camden Line", "none", None, None, None, False) in saturday
    assert ("MARC", "Penn Line", "next", None, "Baltimore Penn Station", 13 * 60, True) in saturday
    # Far from every station, and beyond the installed window: nothing.
    assert transit.station_times(schedule, [-77.5, 38.5], at(2026, 9, 30, 8, 0)) == []
    assert transit.station_times(schedule, UNION_STATION, at(2027, 9, 30, 8, 0)) == []


def test_typical_metro_at_a_station_is_its_interval_or_before_opening_its_first_trains() -> None:
    typical = without_metro_gtfs()
    morning = times_at(typical, UNION_STATION, at(2026, 9, 30, 8, 0))
    red = [t for t in morning if t[0] == "Metro"]
    assert len(red) == 1 and red[0][:3] == ("Metro", "Red Line", "every") and 3 <= red[0][3] <= 8
    # 3:30 am, before Metro opens: the first train each way, by its terminal.
    early = [t for t in times_at(typical, UNION_STATION, at(2026, 9, 30, 3, 30)) if t[0] == "Metro"]
    assert {t[4] for t in early} == {"Glenmont", "Shady Grove"}
    assert all(t[2] == "next" and 5 * 60 <= t[5] < 6 * 60 for t in early)


def test_an_interval_needs_three_trains_and_fewer_are_said_one_by_one() -> None:
    assert transit._every_min([600.0, 610.0]) is None
    assert transit._every_min([600.0, 610.0, 620.0]) == 10
    # Three, but the third more than an hour after the first: not an interval.
    assert transit._every_min([600.0, 610.0, 661.0]) is None


def test_after_midnight_a_finished_line_gives_the_new_days_first_train(schedule) -> None:
    # Thursday 1:30 am is Wednesday's service day, and nothing more runs on it: not "no more
    # trains today", but the first train of Thursday morning, on Thursday's service day.
    night = transit.station_times(schedule, UNION_STATION, at(2026, 10, 1, 1, 30))
    penn = next(t for t in night if t.route == "Penn Line")
    assert (penn.kind, penn.toward, penn.service_day) == (
        "next",
        "Baltimore Penn Station",
        date(2026, 10, 1),
    )
    assert transit.clock(penn.depart, penn.service_day) == "6:00 am"
    # At 11:30 pm, the same service day, it is still "no more trains today".
    late = transit.station_times(schedule, UNION_STATION, at(2026, 9, 30, 23, 30))
    assert all(t.kind == "none" and t.service_day is None for t in late)


def test_the_night_the_clocks_go_back_says_the_times_the_station_clock_shows() -> None:
    typical = without_metro_gtfs(date(2026, 10, 26))
    # 1:30 am EDT on Sunday 2026-11-01: Saturday's trains still run (to 26:00, 1 am EST).
    before = [
        t
        for t in transit.station_times(
            typical, UNION_STATION, datetime(2026, 11, 1, 1, 30, tzinfo=ZONE)
        )
        if t.system.name == "Metro"
    ]
    assert [t.kind for t in before] == ["every"]
    # 1:30 am EST, an hour later: closed, and Sunday's first trains at the time the clock says.
    after = [
        t
        for t in transit.station_times(
            typical, UNION_STATION, datetime(2026, 11, 1, 1, 30, fold=1, tzinfo=ZONE)
        )
        if t.system.name == "Metro"
    ]
    assert {t.kind for t in after} == {"next"} and {t.service_day for t in after} == {
        date(2026, 11, 1)
    }
    assert {transit.clock(t.depart, t.service_day) for t in after} == {"6:22 am", "6:38 am"}


def _branch_schedule(first: int = 13 * 60) -> transit.Schedule:
    """One commuter route along a line, A-B-C-D, with a short turn each way (B-C, C-A; its run
    times slower in the evening rush than in the midday), weekday service only; the first train
    toward Delta leaves Alpha at `first`, the second at 16:00."""
    system = transit.System(
        0, "test-rail", "MARC", transit.RAIL, "the MARC {route}", "", True, "all", "", ""
    )
    names = ["Alpha", "Bravo", "Charlie", "Delta"]
    stops = [
        transit.Stop(
            i,
            name,
            (-77.0 + 0.05 * i, 39.0),
            (-77.0 + 0.05 * i, 39.0),
            True,
            ((-77.0 + 0.05 * i, 39.0),),
            0,
            True,
        )
        for i, name in enumerate(names)
    ]
    midday = 2
    evening = 3

    def runs(cumulative, slow):
        return tuple(
            tuple(c * 2 for c in cumulative) if band == evening and slow else tuple(cumulative)
            for band in range(len(transit.BANDS))
        )

    def trips(*minutes):
        return {0: tuple(m * 2 + 1 for m in minutes)}

    assert transit.BANDS[midday][2] == "midday"
    patterns = [
        transit.Pattern(
            0,
            0,
            "Penn Line",
            (0, 1, 2, 3),
            runs((0, 600, 1200, 1800), True),
            trips(first, 16 * 60),
        ),
        transit.Pattern(1, 0, "Penn Line", (1, 2), runs((0, 600), False), trips(14 * 60 + 5)),
        transit.Pattern(
            2, 0, "Penn Line", (3, 2, 1, 0), runs((0, 600, 1200, 1800), False), trips(14 * 60 + 30)
        ),
        transit.Pattern(
            3, 0, "Penn Line", (2, 1, 0), runs((0, 600, 1200), False), trips(14 * 60 + 20)
        ),
    ]
    days = 14
    return transit.Schedule([system], stops, patterns, ["1" * days], date(2026, 9, 28), days)


def test_a_short_turn_heads_the_way_its_route_does_and_each_departure_takes_its_own_run_times():
    branch = _branch_schedule()
    bravo = list(branch.stops[1].point)
    found = transit.station_times(branch, bravo, at(2026, 9, 30, 14, 0))
    # Two ways, not one per pattern: the short turn to Charlie is the next train toward Delta's
    # end (14:05), and toward Alpha the short turn from Charlie (it reaches Bravo at 14:30)
    # beats the 14:30 from Delta, which reaches Bravo at 14:50.
    assert [(t.kind, t.toward, t.depart) for t in found] == [
        ("next", "Charlie", 14 * 60 + 5),
        ("next", "Alpha", 14 * 60 + 30),
    ]
    # At 14:06 the next toward Delta is the 16:00, which reaches Bravo by the evening rush's
    # run times (20 min), not the midday's the request was made in (10 min).
    later = transit.station_times(branch, bravo, at(2026, 9, 30, 14, 6))
    assert (later[0].toward, later[0].depart) == ("Delta", 16 * 60 + 20)


def test_the_planner_and_the_station_card_time_a_train_alike_across_a_band_edge() -> None:
    # The 2:50 pm from Alpha runs on midday times (10 min to Bravo): it leaves Bravo at 3:00,
    # though a request at 3:01 is in the evening rush (20 min). Neither the planner nor the card
    # offers it at 3:01; both offer the 4:00 pm (by the evening's times, at Bravo 4:20).
    branch = _branch_schedule(first=14 * 60 + 50)
    pattern = branch.patterns[0]
    card = sorted(transit._departures_at(branch.active(date(2026, 9, 30)), pattern, 1))
    assert card == [15 * 60, 16 * 60 + 20]
    for minute in range(14 * 60 + 45, 16 * 60 + 25):
        moment = transit.moment_of(at(2026, 9, 30, minute // 60, minute % 60))
        planner = transit._Day(branch, moment, bike=False).departures(pattern, 1, moment.minute)
        assert planner == [t for t in card if t >= moment.minute], minute
    bravo = list(branch.stops[1].point)
    found = transit.station_times(branch, bravo, at(2026, 9, 30, 15, 1))
    assert ("Delta", 16 * 60 + 20) in [(t.toward, t.depart) for t in found]
    # Down the line too: the planner's arrival at Charlie and Delta is when the card's timing
    # has that train there. The 2:50 pm boards Bravo at 3:00 (an evening-rush minute) yet rides
    # on midday times: at Charlie 3:10 and Delta 3:20, not 3:20 and 3:40.
    down = {
        later: sorted(transit._departures_at(branch.active(date(2026, 9, 30)), pattern, later))
        for later in (2, 3)
    }
    assert down == {2: [15 * 60 + 10, 16 * 60 + 40], 3: [15 * 60 + 20, 17 * 60]}
    for minute in [*range(14 * 60 + 45, 15 * 60 + 1), *range(15 * 60 + 21, 16 * 60 + 21)]:
        moment = transit.moment_of(at(2026, 9, 30, minute // 60, minute % 60))
        hops = transit._Day(branch, moment, bike=False).reach(1, moment.minute, {0})
        trip = 0 if minute <= 15 * 60 else 1
        for later, times in down.items():
            hop = hops[pattern.stops[later]]
            assert hop.depart + hop.ride_s / 60.0 == times[trip], (minute, later)


def test_no_bike_on_metro_on_a_blackout_date_said_plainly_and_metro_on_foot_still_fine() -> None:
    schedule = schedule_from(date(2026, 7, 1))
    plan = plan_bike(schedule, CAPITOL_HILL, DOWNTOWN, at(2026, 7, 4, 10, 0))
    # Bikes are allowed on Metro "at all times except" these days: no option takes Metro.
    assert not any(leg.system == "Metro" for o in plan.options for leg in o.legs if leg.transit)
    assert plan.notes[0] == "Bikes aren't allowed on Metro today (July 4)."
    out = transit.block(transit.choose(plan, "direct"), schedule)
    assert (
        out["notes"][0] == "Bikes aren't allowed on Metro today (July 4)." and out["bike_blackout"]
    )
    # The day before, Metro takes the bike as usual.
    usual = plan_bike(schedule, CAPITOL_HILL, DOWNTOWN, at(2026, 7, 3, 10, 0))
    assert any(leg.system == "Metro" for o in usual.options for leg in o.legs if leg.transit)
    assert not transit.block(usual, schedule)["bike_blackout"]
    # Bikeshare + 🚶🚆🚌 walks onto Metro: the blackout does not touch it.
    share = transit.plan_bikeshare(
        schedule, CAPITOL_HILL, DOWNTOWN, at(2026, 7, 4, 10, 0), Straight(), NO_DOCKS
    )
    assert any(leg.system == "Metro" for o in share.options for leg in o.legs if leg.transit)
    assert not transit.block(share, schedule)["bike_blackout"]


def test_beyond_the_installed_timetables_only_the_direct_ride_is_offered(schedule) -> None:
    plan = plan_bike(schedule, CAPITOL_HILL, DOWNTOWN, at(2027, 1, 15, 8, 0))
    assert [o.direct for o in plan.options] == [True]
    assert plan.notes[0].startswith("The timetables installed run September 28 to November 11")


# --- Choosing an option, and the answer's block ---------------------------------------------------


def test_an_option_is_chosen_by_its_key_and_a_stale_key_falls_back_to_the_quickest(schedule):
    plan = plan_bike(schedule, CAPITOL_HILL, DOWNTOWN, at(2026, 9, 30, 8, 0))
    metro = next(o for o in plan.options if not o.direct)
    chosen = transit.choose(plan, metro.key)
    assert chosen.option is metro
    out = transit.block(chosen, schedule)
    assert out["key"] == metro.key and not out["direct"]
    assert [o["chosen"] for o in out["options"]].count(True) == 1
    stale = transit.choose(plan, "a1>p99>e3")
    assert stale.chosen == 0 and stale.asked == "a1>p99>e3"
    assert transit.block(stale, schedule)["notes"][0].startswith("The trip chosen is no longer")


def test_the_block_says_about_and_scheduled_and_compares_with_riding(schedule) -> None:
    plan = plan_bike(schedule, CAPITOL_HILL, DOWNTOWN, at(2026, 9, 30, 8, 0))
    metro = next(o for o in plan.options if not o.direct)
    plan = transit.with_ride(transit.choose(plan, metro.key), 300.0)
    out = transit.block(plan, schedule)
    assert out["scheduled"] is True and out["credits"] == ["WMATA GTFS (scheduled times)"]
    assert out["summary"] == f"About {out['minutes']} min door to door, scheduled."
    assert out["steps"][0]["seconds"] == 300 and out["steps"][0]["route_line"]
    assert out["steps"][0]["coordinates"] == []
    assert out["steps"][2]["system"] == "Metro"
    assert (out["day_type"], out["band"]) == ("weekday", "morning rush")
    # Straight lines at 18 km/h beat it here: riding is quicker, and the answer says so.
    assert out["riding_quicker"] is True
    assert out["comparison"].startswith("Riding the whole way is quicker: about ")
    direct = transit.block(transit.choose(plan, "direct"), schedule)
    assert direct["direct"] and not direct["scheduled"]
    assert direct["summary"].endswith("riding the whole way.")
    assert direct["comparison"].startswith("Riding the whole way is quickest:")
    assert direct["steps"][0]["route_line"] and direct["credits"] == []


# --- Bikeshare + 🚶🚆🚌 ------------------------------------------------------------------------


def _dock(station_id, name, lon, lat, bikes, docks):
    return (
        gbfs.Station(station_id, name, lon, lat, bikes + docks),
        gbfs.StationStatus(station_id, bikes, 0, docks, True, True, True),
    )


def snapshot(*docks) -> gbfs.Snapshot:
    return gbfs.Snapshot(
        fetched_at=0.0,
        stations=[d[0] for d in docks],
        status={d[0].station_id: d[1] for d in docks},
    )


SHARE = snapshot(
    _dock("a", "8th & D St SE", -76.9945, 38.8836, 5, 5),
    _dock("b", "7th & Pennsylvania Ave SE", -76.9963, 38.8848, 0, 9),
    _dock("c", "12th & Pennsylvania Ave NW", -77.0279, 38.8941, 6, 3),
    _dock("d", "14th & F St NW", -77.0310, 38.8968, 0, 7),
)
NO_DOCKS = snapshot()


def test_bikeshare_walks_where_walking_is_quicker_and_names_the_docks_where_it_rides(schedule):
    plan = transit.plan_bikeshare(
        schedule, CAPITOL_HILL, DOWNTOWN, at(2026, 9, 30, 8, 0), Straight(), SHARE
    )
    direct = plan.direct
    assert direct is not None
    assert [leg.mode for leg in direct.legs] == ["take", "bikeshare", "walk"]
    assert direct.legs[0].words().startswith("Walk 2 min to the bikeshare dock at 8th & D St SE")
    assert direct.legs[1].words().endswith("and dock it at 14th & F St NW.")
    metro = next(o for o in plan.options if not o.direct)
    # Eastern Market is a short walk: walking beats taking a bike there and docking it.
    assert [leg.mode for leg in metro.legs][:3] == ["walk", "enter", "metro"]
    assert not any(leg.bike for leg in metro.legs)
    assert transit.label(metro, presets.BIKESHARE_TRANSIT).startswith("Walk, Metro to")


def test_bikeshare_needs_no_dock_to_walk_metro_and_walk(schedule) -> None:
    plan = transit.plan_bikeshare(
        schedule, CAPITOL_HILL, DOWNTOWN, at(2026, 9, 30, 8, 0), Straight(), NO_DOCKS
    )
    assert plan.direct is None
    modes = [leg.mode for leg in plan.options[0].legs]
    assert modes == ["walk", "enter", "metro", "exit", "walk"]


def test_bikeshare_with_nothing_in_reach_is_said_plainly(schedule) -> None:
    with pytest.raises(transit.NoTransit, match="classic bike"):
        transit.plan_bikeshare(
            schedule, CAPITOL_HILL, DOWNTOWN, at(2026, 10, 17, 12, 0), Straight(), NO_DOCKS
        )


# A few blocks from Capitol Hill, under 1 mi (1.6 km) in a straight line.
NEAR_CAPITOL_HILL = [-76.9990, 38.8850]


def test_a_short_trip_offers_walking_the_whole_way_among_the_options(schedule) -> None:
    # The owner, 2026-10-12 20:32: walking where it is reasonable; riding directly there stays.
    plan = transit.plan_bikeshare(
        schedule, CAPITOL_HILL, NEAR_CAPITOL_HILL, at(2026, 9, 30, 12, 0), Straight(), SHARE
    )
    walk = next(o for o in plan.options if o.walk)
    assert walk.key == transit.WALK_ONLY and [leg.mode for leg in walk.legs] == ["walk"]
    assert plan.direct is not None and not walk.direct
    # Quickest first, among the others; walked by the router (not estimated).
    totals = [transit.minutes(o.total_s) for o in plan.options]
    assert totals == sorted(totals) and not walk.legs[0].estimated
    assert transit.label(walk, presets.BIKESHARE_TRANSIT) == "Walk the whole way"
    out = transit.block(transit.choose(plan, transit.WALK_ONLY), schedule)
    assert out["summary"].endswith("door to door, walking.") and out["key"] == transit.WALK_ONLY
    assert not out["scheduled"] and out["comparison"] is None and out["departure"] is None
    assert transit.SCHEDULED_WORDS not in out["notes"]
    row = next(o for o in out["options"] if o["walk"])
    assert row["legs"] == [{"mode": "walk", "system": None, "lines": [], "minutes": row["minutes"]}]


def test_walking_the_whole_way_is_offered_when_quickest_or_short_and_not_otherwise(
    schedule,
) -> None:
    far = transit.plan_bikeshare(
        schedule, CAPITOL_HILL, DOWNTOWN, at(2026, 9, 30, 8, 0), Straight(), SHARE
    )
    assert not any(o.walk for o in far.options)  # 2 mi (3 km): bikeshare and Metro are quicker
    quick = transit.Option("x", (transit.Leg(transit.RIDE, 600.0),))
    slow = transit.Option("y", (transit.Leg(transit.RIDE, 6000.0),))
    assert transit.walk_offered(CAPITOL_HILL, NEAR_CAPITOL_HILL, 9999.0, [quick])  # short
    assert transit.walk_offered(CAPITOL_HILL, DOWNTOWN, 3000.0, [slow])  # quickest
    assert not transit.walk_offered(CAPITOL_HILL, DOWNTOWN, 3000.0, [quick])
    # Nothing else to beat: a long walk alone is not offered (the plan says why instead).
    assert not transit.walk_offered(CAPITOL_HILL, DOWNTOWN, 3000.0, [])


def test_own_bike_never_offers_walking_the_whole_way(schedule) -> None:
    # Walking the whole way is Bikeshare + 🚶🚆🚌's: Own Bike + 🚆🚌 keeps the bike, even for
    # a few blocks.
    plan = plan_bike(schedule, CAPITOL_HILL, NEAR_CAPITOL_HILL, at(2026, 9, 30, 12, 0))
    assert plan.direct is not None
    assert not any(o.walk or o.key == transit.WALK_ONLY for o in plan.options)
    assert not any(leg.mode == transit.WALK for o in plan.options for leg in o.legs)


def test_the_walk_the_whole_way_is_routed_with_pedestrian_costing(monkeypatch) -> None:
    from core import routing

    asked = []

    def answer(graph, endpoint, payload, deadline):
        asked.append((graph, endpoint, payload))
        return {"trip": {"legs": [{"shape": "", "summary": {"time": 420.0, "length": 0.55}}]}}

    monkeypatch.setattr(routing, "_call", answer)
    monkeypatch.setattr(routing, "decode_polyline6", lambda _shape: [(-77.0, 38.9), (-77.01, 38.9)])
    services = transit.RoutingServices(routing.clock() + 30, presets.BIKESHARE_TRANSIT)
    walked = services.walk(CAPITOL_HILL, NEAR_CAPITOL_HILL)
    graph, endpoint, payload = asked[0]
    assert (graph, endpoint, payload["costing"]) == ("standard", "route", "pedestrian")
    assert payload["costing_options"] == {"pedestrian": {"walking_speed": transit.WALK_SPEED_KMH}}
    assert walked.seconds == 420.0 and walked.metres == 550.0
    # The option built from it is that walk, not an estimate.
    option = transit._walk_whole(CAPITOL_HILL, NEAR_CAPITOL_HILL, services)
    assert option.walk and option.legs[0].seconds == 420.0 and not option.legs[0].estimated


class Bendy(Straight):
    """The router, its lines bent through a point off the straight one, and each call kept."""

    def __init__(self, answers: bool = True) -> None:
        super().__init__()
        self.asked: list[str] = []
        self.answers = answers

    def _bent(self, kind, found, a, b):
        self.asked.append(kind)
        if not self.answers:
            return None
        middle = ((a[0] + b[0]) / 2 + 0.001, (a[1] + b[1]) / 2)
        return replace(found, coordinates=(tuple(a), middle, tuple(b)))

    def ride(self, a, b):
        return self._bent("ride", super().ride(a, b), a, b)

    def walk(self, a, b):
        return self._bent("walk", super().walk(a, b), a, b)


def test_the_chosen_trips_other_walks_and_rides_are_routed_for_the_map(schedule) -> None:
    # The owner, 2026-10-15: "The bikeshare mode doesn't seem to properly route walking." Every
    # walk is walked (pedestrian costing) and every ride ridden for the map; no time changes.
    plan = transit.plan_bikeshare(
        schedule, CAPITOL_HILL, DOWNTOWN, at(2026, 9, 30, 8, 0), Straight(), SHARE
    )
    direct = transit.choose(plan, transit.DIRECT)
    assert [leg.mode for leg in direct.legs] == ["take", "bikeshare", "walk"]
    services = Bendy()
    drawn = transit.drawn(direct, services)
    # The route line (the bikeshare ride) is the answer's own; the two walks are walked.
    assert services.asked == ["walk", "walk"]
    assert [len(leg.coordinates) for leg in drawn.legs] == [3, 2, 3]
    assert [leg.seconds for leg in drawn.legs] == [leg.seconds for leg in direct.legs]
    assert drawn.option.total_s == direct.option.total_s
    for before, after in zip(direct.legs, drawn.legs, strict=True):
        assert after.coordinates[0] == before.coordinates[0]
        assert after.coordinates[-1] == before.coordinates[-1]
    # Walk, Metro, walk: the route line is the first walk, the last one is walked for the map.
    metro = transit.choose(plan, next(o.key for o in plan.options if o.scheduled))
    services = Bendy()
    drawn = transit.drawn(metro, services)
    walks = [i for i, leg in enumerate(drawn.legs) if leg.mode == transit.WALK]
    assert walks[0] == drawn.ride and services.asked == ["walk"]
    assert len(drawn.legs[walks[-1]].coordinates) == 3
    assert len(drawn.legs[walks[0]].coordinates) == 2
    # Own Bike + 🚆🚌: a ride estimated from the straight line is ridden for the map.
    own = plan_bike(schedule, CAPITOL_HILL, DOWNTOWN, at(2026, 9, 30, 12, 0))
    ridden = transit.choose(own, next(o.key for o in own.options if o.scheduled))
    services = Bendy()
    drawn = transit.drawn(ridden, services)
    assert services.asked == ["ride"] and len(drawn.legs[-1].coordinates) == 3
    # A later ride already routed for its stress colours (api._later_rides) is not asked again.
    services = Bendy()
    later = len(ridden.legs) - 1
    assert transit.drawn(ridden, services, skip={later}) is ridden and services.asked == []
    # A router that does not answer: the straight lines stay, the plan as it was.
    services = Bendy(answers=False)
    assert transit.drawn(direct, services) is direct and services.asked == ["walk", "walk"]


def test_drawing_the_map_never_holds_a_ready_answer_long(monkeypatch) -> None:
    """Drawing changes no times: its calls are few, short, and stop at their own budget."""
    from core import routing

    assert transit.MAX_DRAW_CALLS * transit.DRAW_CALL_S <= 10
    now = [100.0]
    monkeypatch.setattr(routing, "clock", lambda: now[0])
    services = transit.RoutingServices(
        now[0] + transit.DRAW_BUDGET_S, "default", max_calls=transit.MAX_DRAW_CALLS
    )
    now[0] += transit.DRAW_BUDGET_S + 0.1
    # Past the budget: no call is made and the leg stays straight.
    assert services.walk((-77.0, 38.9), (-77.01, 38.91)) is None
    assert services.calls == 0


def test_each_option_lists_its_legs_compactly_for_its_row(schedule) -> None:
    plan = transit.plan_bikeshare(
        schedule, CAPITOL_HILL, DOWNTOWN, at(2026, 9, 30, 8, 0), Straight(), SHARE
    )
    metro = next(o for o in plan.options if o.scheduled)
    legs = transit.option_legs(metro)
    # Walk (and into the station), Metro with its wait, out and walk: three legs, in order.
    assert [leg["mode"] for leg in legs] == ["walk", "metro", "walk"]
    assert legs[1]["system"] == "Metro" and legs[1]["lines"] == ["Orange Line"]
    assert abs(sum(leg["minutes"] for leg in legs) - transit.minutes(metro.total_s)) <= 2
    # Bikeshare directly there: the walk to the dock, the ride, the walk on.
    direct = transit.option_legs(plan.direct)
    assert [leg["mode"] for leg in direct] == ["walk", "bikeshare", "walk"]
    # Own bike: rides, the station's way in and out counted with them.
    own = plan_bike(schedule, CAPITOL_HILL, DOWNTOWN, at(2026, 9, 30, 12, 0))
    ridden = next(o for o in own.options if o.scheduled)
    assert [leg["mode"] for leg in transit.option_legs(ridden)] == ["ride", "metro", "ride"]


# --- Metro's typical timetable (no WMATA rail GTFS) ---------------------------------------------

TYPICAL = transit._typical_doc()
# Metro's average speed including stops, the run-time estimate's (docs/SOURCES.md).
TYPICAL_SPEED_MS = 33 * 1609.344 / 3600


@lru_cache(maxsize=2)
def without_metro_gtfs(start: date = date(2026, 9, 28)) -> transit.Schedule:
    """The fixture's schedule as a host builds it with no WMATA key: no Metro, no Metrobus."""
    feeds = {k: v for k, v in FEEDS.items() if not k.startswith("wmata-")}
    return transit.with_typical_metro(transit.parse(build.build(feeds, start)[0]))


def test_the_typical_timetable_has_the_maps_stations_and_the_documented_run_times() -> None:
    # The map's 98 stations, each with the bike entrance the GTFS build would give it.
    assert TYPICAL["stations"] == build.metro_stations()
    names = {s["name"] for s in TYPICAL["stations"]}
    served = {name for service in TYPICAL["services"] for name in service["stations"]}
    assert served == names and len(names) == 98
    points = {s["name"]: s["point"] for s in TYPICAL["stations"]}
    for service in TYPICAL["services"]:
        stations = service["stations"]
        assert service["to"] == stations[-1] and len(service["run_s"]) == len(stations) - 1
        hops = zip(stations, stations[1:], strict=False)
        for (a, b), run in zip(hops, service["run_s"], strict=True):
            metres = build.distance_m(points[a], points[b])
            assert run == max(90, round(metres / TYPICAL_SPEED_MS / 10) * 10), (a, b)
    assert set(TYPICAL["lines"]) == {s["line"] for s in TYPICAL["services"]}
    for line, about in TYPICAL["lines"].items():
        assert about["info"] == f"https://www.wmata.com/ridertools/line/{line.lower()}/info"
    # Red, end to end: about an hour.
    red = next(s for s in TYPICAL["services"] if s["line"] == "Red")
    assert 55 <= sum(red["run_s"]) / 60 <= 70


def test_typical_trains_run_from_opening_to_closing_at_each_bands_interval() -> None:
    weekday = transit.typical_departures(TYPICAL, "Red", "monday-thursday")
    # Opens 5:00 am, every 6 min; every 4-5 min (4.5) from 7 am; the last before midnight.
    assert weekday[:3] == [300, 306, 312]
    rush = [t for t in weekday if 7 * 60 <= t < 9 * 60]
    assert len(rush) == 27 and weekday[-1] < 24 * 60
    friday = transit.typical_departures(TYPICAL, "Red", "friday")
    assert 25 * 60 < friday[-1] < 26 * 60  # Friday closes at 2 am
    sunday = transit.typical_departures(TYPICAL, "Orange", "sunday")
    assert sunday[0] == 6 * 60 and sunday[-1] - sunday[-2] == 10  # Orange, Sunday late night
    assert transit.typical_day_type(date(2026, 10, 16)) == "friday"
    assert transit.typical_day_type(date(2026, 11, 26)) == "sunday"  # Thanksgiving


def test_the_typical_wait_is_half_the_interval_or_the_time_to_the_first_or_last_train() -> None:
    assert transit.typical_wait_min(480, [483, 489, 495, 501]) == (3, 6)
    assert transit.typical_wait_min(270, [300, 306, 312]) == (30, 6)  # before opening
    assert transit.typical_wait_min(1430, [1435]) == (5, None)  # the last train
    assert transit.typical_first(270, [300, 306, 312]) == 300
    assert transit.typical_first(480, [483, 489, 495, 501]) is None
    assert transit.typical_first(1430, [1435]) is None


def test_before_metro_opens_the_step_names_the_first_train() -> None:
    # #111's review: at 4:50 am not "every 6 min, scheduled; about 30 min wait".
    typical = without_metro_gtfs()
    plan = plan_bike(typical, CAPITOL_HILL, DOWNTOWN, at(2026, 9, 30, 4, 50))
    metro = next(o for o in plan.options if o.scheduled)
    leg = transit_legs(metro)[0]
    words = leg.words()
    assert "(first train 5:" in words and " am scheduled; about " in words
    assert "every" not in words and leg.depart is None
    # Once Metro runs, the interval again.
    later = plan_bike(typical, CAPITOL_HILL, DOWNTOWN, at(2026, 9, 30, 12, 0))
    assert "every " in transit_legs(next(o for o in later.options if o.scheduled))[0].words()


def test_a_holiday_on_typical_metro_says_its_sunday_timetable() -> None:
    # #111's review: typical Metro has no holiday timetable; a holiday runs its Sunday one.
    typical = without_metro_gtfs(date(2026, 11, 20))
    plan = plan_bike(typical, CAPITOL_HILL, DOWNTOWN, at(2026, 11, 26, 12, 0))
    metro = next(o for o in plan.options if o.scheduled)
    assert {leg.system for leg in transit_legs(metro)} == {"Metro"}
    notes = transit.block(transit.choose(plan, metro.key), typical)["notes"]
    assert "Today is a federal holiday: Metro is planned on its Sunday timetable." in notes
    assert transit.HOLIDAY_WORDS not in notes


def test_with_no_wmata_gtfs_metro_runs_its_typical_timetable_and_the_gtfs_replaces_it(
    schedule,
) -> None:
    typical = without_metro_gtfs()
    ids = [s.id for s in typical.systems]
    # Metro is added on its typical timetable; Metrobus stays out.
    assert ids == ["marc", "mta-light-rail", "wmata-rail"] and typical.systems[-1].typical
    assert typical.start == date(2026, 9, 28) and len(typical.services[-1]) == typical.days
    # A schedule with WMATA's rail GTFS is left as it is.
    assert transit.with_typical_metro(schedule) is schedule


def test_a_metro_trip_on_the_typical_timetable_has_no_departure_and_says_scheduled() -> None:
    typical = without_metro_gtfs()
    plan = plan_bike(typical, CAPITOL_HILL, DOWNTOWN, at(2026, 9, 30, 12, 0))
    metro = next(o for o in plan.options if not o.direct)
    legs = transit_legs(metro)
    assert [leg.system for leg in legs] == ["Metro"]
    assert legs[0].depart is None and 0 < legs[0].wait_s <= 6 * 60
    # The same word as a timetable's, and the interval, never a departure.
    assert ", scheduled; about " in legs[0].words() and legs[0].every is not None
    out = transit.block(transit.choose(plan, metro.key), typical)
    assert out["departure"] is None
    step = next(s for s in out["steps"] if s["mode"] == "metro")
    assert step["source"] == "scheduled" and step["departs"] is None and step["every_min"]
    # Its credit names it typical service; no separate note says so.
    assert out["credits"] == ["WMATA, wmata.com (typical service)"]
    assert not any("typical" in note for note in out["notes"])
    # Nothing mentions Metrobus.
    direct = transit.block(transit.choose(plan, "direct"), typical)
    assert not any("bus" in note.lower() for note in out["notes"] + direct["notes"])


def test_typical_metro_is_out_of_service_after_closing_and_closes_no_station() -> None:
    typical = without_metro_gtfs()
    # Tuesday 2:30 am (Monday's service day closed at midnight).
    plan = plan_bike(typical, CAPITOL_HILL, DOWNTOWN, at(2026, 9, 29, 2, 30))
    assert not any(leg.system == "Metro" for o in plan.options for leg in o.legs)
    sunday = transit.closed_stations(typical, transit.moment_of(at(2026, 10, 4, 12, 0)))
    assert not [c for c in sunday if c.system.id == "wmata-rail"]


def test_with_no_schedule_installed_metro_alone_runs_on_its_typical_timetable(tmp_path) -> None:
    alone = transit.load(tmp_path / "none.json", date(2030, 3, 6))
    assert [s.id for s in alone.systems] == ["wmata-rail"] and alone.covers(date(2030, 3, 6))
    plan = transit.plan_bikeshare(
        alone, CAPITOL_HILL, DOWNTOWN, at(2030, 3, 6, 9, 0), Straight(), NO_DOCKS
    )
    assert any(leg.system == "Metro" for o in plan.options for leg in o.legs if leg.transit)
    # A schedule built without WMATA gets Metro's typical timetable when it is loaded.
    path = tmp_path / "schedule.json"
    feeds = {k: v for k, v in FEEDS.items() if not k.startswith("wmata-")}
    path.write_text(json.dumps(build.build(feeds, date(2026, 9, 28))[0]))
    assert [s.id for s in transit.load(path, date(2026, 10, 1)).systems] == [
        "marc",
        "mta-light-rail",
        "wmata-rail",
    ]
    assert [s.id for s in transit.load(path, date(2026, 10, 12)).systems] == [
        "marc",
        "mta-light-rail",
        "wmata-rail",
    ]


def test_an_expired_schedule_keeps_metro_on_its_typical_timetable(tmp_path) -> None:
    # #111's review: the typical timetable needs no refresh, so Metro stays when the file runs out.
    path = tmp_path / "transit-schedule.json"
    path.write_text(built(date(2026, 9, 28))[0])
    after_end = date(2026, 11, 20)  # the file ends 2026-11-11
    schedule = transit.load(path, after_end)
    assert [s.id for s in schedule.systems] == ["wmata-rail"] and schedule.covers(after_end)
    plan = plan_bike(schedule, CAPITOL_HILL, DOWNTOWN, at(2026, 11, 20, 12, 0))
    assert any(leg.system == "Metro" for o in plan.options for leg in transit_legs(o))
    assert plan.notes[-1] == (
        "Only Metro is planned: the other timetables installed cover September 28 to"
        " November 11, 2026."
    )
    # A date before the file's window says the same, and is as true.
    before = transit.load(path, date(2026, 9, 1))
    assert [s.id for s in before.systems] == ["wmata-rail"]
    assert "cover September 28 to November 11, 2026." in before.note
    # The operator is still told to rebuild it.
    assert "ran out on 2026-11-11" in transit.schedule_alert(path, after_end)
    # Within its window, the file itself.
    assert transit.load(path, date(2026, 10, 1)).systems[0].id == "wmata-rail"
    assert len(transit.load(path, date(2026, 10, 1)).systems) > 1


def _feeds_with_marc_ending(tmp_path, end: str) -> dict:
    """The fixture's feeds with MARC's timetable ending on `end` (YYYYMMDD)."""
    marc = tmp_path / "marc"
    shutil.copytree(DATA / "marc", marc)
    calendar = marc / "calendar.txt"
    calendar.write_text(calendar.read_text().replace("20271231", end))
    (marc / "calendar_dates.txt").write_text("service_id,date,exception_type\n")
    return {**FEEDS, "marc": marc}


def test_a_system_whose_feed_ends_inside_the_window_is_left_out_after_it_not_closed(
    tmp_path,
) -> None:
    """pipeline-1 + TB-1: MARC's feed ends 2026-10-20, inside the window to 2026-11-11. Past
    it MARC is not covered: no plan, no struck-through station, a note; the alert counts down
    to MARC's end, not the file's."""
    doc, report = build.build(_feeds_with_marc_ending(tmp_path, "20261020"), date(2026, 9, 28))
    marc = next(s for s in doc["systems"] if s["id"] == "marc")
    assert marc["last_day"] == "2026-10-20"
    assert any(line.startswith("marc: its timetable ends 2026-10-20") for line in report)
    assert all(s["last_day"] == "2027-12-31" for s in doc["systems"] if s["id"] != "marc")
    path = tmp_path / "transit-schedule.json"
    path.write_text(json.dumps(doc))

    before = transit.load(path, date(2026, 10, 20))
    assert "marc" in [s.id for s in before.systems] and before.note == ""
    after = transit.load(path, date(2026, 10, 21))
    assert "marc" not in [s.id for s in after.systems]
    assert "wmata-rail" in [s.id for s in after.systems], "the others are still planned"
    assert after.note == (
        "MARC is not planned for this date: its installed timetable ends October 20, 2026."
    )
    weekday = transit.closed_stations(after, transit.moment_of(at(2026, 10, 21, 12, 0)))
    assert not [c for c in weekday if c.system.id == "marc"], "not covered is not closed"
    plan = plan_bike(after, NOMA, BALTIMORE, at(2026, 10, 21, 12, 0))
    assert not any(leg.system == "MARC" for o in plan.options for leg in transit_legs(o))
    assert after.note in plan.notes

    assert transit.days_left(before, date(2026, 10, 18)) == 3
    assert "MARC's timetable runs out on 2026-10-20, 3 day(s) left" in transit.schedule_alert(
        path, date(2026, 10, 18)
    )
    assert "MARC's timetable ran out on 2026-10-20" in transit.schedule_alert(
        path, date(2026, 10, 25)
    )
    assert transit.schedule_alert(path, date(2026, 10, 1)) is None


def test_a_metro_gtfs_that_ends_early_gives_way_to_the_typical_timetable(tmp_path) -> None:
    rail = tmp_path / "wmata-rail"
    shutil.copytree(DATA / "wmata-rail", rail)
    calendar = rail / "calendar.txt"
    calendar.write_text(calendar.read_text().replace("20271231", "20261020"))
    (rail / "calendar_dates.txt").write_text("service_id,date,exception_type\n")
    path = tmp_path / "transit-schedule.json"
    path.write_text(json.dumps(build.build({**FEEDS, "wmata-rail": rail}, date(2026, 9, 28))[0]))

    after = transit.load(path, date(2026, 10, 21))
    metro = [s for s in after.systems if s.id == "wmata-rail"]
    assert len(metro) == 1 and metro[0].typical
    assert after.note.startswith("Metro is not planned for this date")


# --- POST /api/route and GET /api/transit/closures ----------------------------------------------

db = pytest.mark.django_db(transaction=True)


@pytest.fixture
def installed(tmp_path, settings, monkeypatch):
    """The schedule installed where the API reads it, and the bike legs' router straight lines."""
    path = tmp_path / "transit-schedule.json"
    path.write_text(built(date(2026, 9, 28))[0])
    settings.TRANSIT_SCHEDULE_PATH = path
    monkeypatch.setattr(transit, "RoutingServices", lambda *_args, **_kwargs: Straight())
    return path


def post_transit(client, points, preset=presets.BIKE_TRANSIT, **extra):
    body = {"points": points, "preset": preset, **extra}
    return client.post("/api/route", data=json.dumps(body), content_type="application/json")


@db
@pytest.mark.usefixtures("weekday_clock")
class TestApi:
    def test_the_answer_lists_the_options_and_routes_the_chosen_ones_first_ride(
        self, client, segments, router, installed
    ) -> None:
        fake = router(standard_router())
        response = post_transit(client, [CAPITOL_HILL, DOWNTOWN])
        assert response.status_code == 200, response.content
        body = response.json()
        assert set(body) == CONTRACT_KEYS
        trip = body["transit"]
        assert trip["mode"] == "bike-transit"
        assert [o["direct"] for o in trip["options"]].count(True) == 1
        assert trip["options"][0]["chosen"] and trip["key"] == trip["options"][0]["key"]
        assert "route" in fake.endpoints()
        metro = next(o for o in trip["options"] if not o["direct"])
        again = post_transit(client, [CAPITOL_HILL, DOWNTOWN], transit_option=metro["key"])
        chosen = again.json()["transit"]
        assert chosen["key"] == metro["key"] and chosen["scheduled"]
        assert [s["mode"] for s in chosen["steps"]] == ["ride", "enter", "metro", "exit", "ride"]
        assert chosen["steps"][0]["seconds"] == round(again.json()["duration_s"])
        # Midday (the pinned clock): Orange every 12 minutes, so a 6-minute wait.
        assert chosen["steps"][2]["wait_s"] == 360 and chosen["band"] == "midday"

    @pytest.mark.parametrize("preset", [presets.BIKE_TRANSIT, presets.BIKESHARE_TRANSIT])
    def test_novice_legs_price_the_bike_legs_as_novice_and_nervous(
        self, client, segments, router, installed, monkeypatch, preset
    ) -> None:
        """v0.7.0, Novice and Nervous item 4: the transit options offered beside its route
        plan their bike legs with the same one-level-up pricing; a share bike keeps its pace."""
        from core import gbfs

        seen = []

        def services(until, leg_preset, costing=None, **_options):
            seen.append((leg_preset, costing))
            return Straight()

        monkeypatch.setattr(transit, "RoutingServices", services)
        monkeypatch.setattr(gbfs.client, "snapshot", lambda: SHARE)
        fake = router(standard_router())
        response = post_transit(client, [CAPITOL_HILL, DOWNTOWN], preset, novice_legs=True)
        assert response.status_code == 200, response.content
        assert response.json()["preset"] == preset
        assert response.json()["novice"] is None
        bike = [p["costing_options"].get("bicycle") for _u, p in fake.calls]
        assert any(b and b["use_roads"] == 0.0 for b in bike)
        leg_preset, costing = seen[0]
        assert leg_preset == presets.NOVICE
        # The routed lines are priced as the candidates were, so the retiming is at the same
        # pace: a share bike's on Bikeshare + Transit, Novice's own on Bike + Transit.
        line_speeds = {b.get("cycling_speed") for b in bike if b}
        if preset == presets.BIKESHARE_TRANSIT:
            assert costing["bicycle"]["cycling_speed"] == presets.BIKESHARE_CLASSIC_SPEED_KMH
            assert line_speeds == {presets.BIKESHARE_CLASSIC_SPEED_KMH}
        else:
            assert costing is None
            novice = presets.costing(presets.NOVICE)["bicycle"].get("cycling_speed")
            assert line_speeds == {novice}

    def test_a_router_too_slow_for_the_answers_line_draws_it_straight_and_says_so(
        self, client, segments, router, installed, monkeypatch, caplog
    ) -> None:
        from core import routing

        router(standard_router())

        def late(*_args, **_kwargs):
            raise routing.DeadlineExceeded("the router did not answer in time")

        monkeypatch.setattr(routing, "plan", late)
        with caplog.at_level(logging.INFO, logger="core.api"):
            response = post_transit(client, [CAPITOL_HILL, DOWNTOWN])
        assert response.status_code == 200, response.content
        body = response.json()
        trip = body["transit"]
        # Not refused: the line is the leg drawn straight, its time the plan's own estimate.
        assert len(body["geometry"]["coordinates"]) == 2 and body["intersections"] is None
        assert api.UNROUTED_NOTE in trip["notes"]
        assert trip["steps"][0]["seconds"] == round(body["duration_s"])
        metro = next(o for o in trip["options"] if not o["direct"])
        again = post_transit(client, [CAPITOL_HILL, DOWNTOWN], transit_option=metro["key"])
        assert again.status_code == 200 and api.UNROUTED_NOTE in again.json()["transit"]["notes"]
        # Each phase's time is logged.
        assert any("search" in r.getMessage() and "line" in r.getMessage() for r in caplog.records)

    def test_depart_at_plans_another_day(self, client, segments, router, installed) -> None:
        router(standard_router())
        response = post_transit(client, [NOMA, BALTIMORE], depart_at="2026-10-03T10:00:00-04:00")
        assert response.status_code == 200, response.content
        trip = response.json()["transit"]
        assert trip["day_type"] == "saturday"
        assert "MARC Camden Line: no weekend service." in trip["notes"]

    def test_an_unreadable_schedule_is_a_503_said_plainly(self, client, router, settings, tmp_path):
        settings.TRANSIT_SCHEDULE_PATH = tmp_path / "broken.json"
        settings.TRANSIT_SCHEDULE_PATH.write_text("{")
        response = post_transit(client, [CAPITOL_HILL, DOWNTOWN])
        assert response.status_code == 503
        assert response.json()["code"] == "transit_unavailable"
        assert response["Retry-After"]
        assert client.get("/api/transit/closures").status_code == 503

    def test_with_no_schedule_installed_metro_runs_on_its_typical_timetable(
        self, client, segments, router, settings, tmp_path, monkeypatch
    ) -> None:
        router(standard_router())
        settings.TRANSIT_SCHEDULE_PATH = tmp_path / "none.json"
        monkeypatch.setattr(transit, "RoutingServices", lambda *_args, **_kwargs: Straight())
        response = post_transit(client, [CAPITOL_HILL, DOWNTOWN])
        assert response.status_code == 200, response.content
        trip = response.json()["transit"]
        metro = next(o for o in trip["options"] if not o["direct"])
        again = post_transit(client, [CAPITOL_HILL, DOWNTOWN], transit_option=metro["key"])
        chosen = again.json()["transit"]
        assert chosen["departure"] is None and "typical service" in chosen["credits"][0]
        closures = client.get("/api/transit/closures", {"at": "2026-10-04T12:00:00"})
        assert closures.status_code == 200 and closures.json()["stations"] == []

    def test_walking_the_whole_way_is_the_walk_itself_on_the_map(
        self, client, segments, router, installed, monkeypatch
    ) -> None:
        fake = router(standard_router())
        monkeypatch.setattr(gbfs.client, "snapshot", lambda: SHARE)
        response = post_transit(
            client, [CAPITOL_HILL, NEAR_CAPITOL_HILL], presets.BIKESHARE_TRANSIT
        )
        assert response.status_code == 200, response.content
        options = response.json()["transit"]["options"]
        walk = next(o for o in options if o["walk"])
        assert all("legs" in o for o in options) and walk["legs"][0]["mode"] == "walk"
        calls = len(fake.calls)
        again = post_transit(
            client,
            [CAPITOL_HILL, NEAR_CAPITOL_HILL],
            presets.BIKESHARE_TRANSIT,
            transit_option=walk["key"],
        )
        assert again.status_code == 200, again.content
        body = again.json()
        assert body["transit"]["key"] == transit.WALK_ONLY
        assert body["transit"]["summary"].endswith("walking.")
        # The line is the walk (the pedestrian router's), timed at walking pace; no bike route.
        assert body["geometry"]["coordinates"] == [CAPITOL_HILL, NEAR_CAPITOL_HILL]
        assert body["duration_s"] == pytest.approx(body["transit"]["total_s"], abs=1)
        assert len(fake.calls) == calls

    def test_a_bikeshare_trips_walks_are_walked_not_ridden_on_the_map(
        self, client, segments, router, installed, monkeypatch
    ) -> None:
        # The route line of walk, Metro, walk is a walk: the pedestrian router's, never the
        # bike's, and the other walk is walked for the map too. The times are the plan's.
        fake = router(standard_router())
        monkeypatch.setattr(gbfs.client, "snapshot", lambda: NO_DOCKS)
        services = Bendy()
        monkeypatch.setattr(transit, "RoutingServices", lambda *_args, **_kwargs: services)
        response = post_transit(client, [CAPITOL_HILL, DOWNTOWN], presets.BIKESHARE_TRANSIT)
        assert response.status_code == 200, response.content
        body = response.json()
        trip = body["transit"]
        assert [s["mode"] for s in trip["steps"]] == ["walk", "enter", "metro", "exit", "walk"]
        assert "route" not in fake.endpoints()
        first, last = trip["steps"][0], trip["steps"][-1]
        assert first["route_line"] and len(body["geometry"]["coordinates"]) == 3
        assert body["duration_s"] == pytest.approx(first["seconds"], abs=1)
        assert not last["route_line"] and len(last["coordinates"]) == 3
        # The same trip drawn straight (the router not answering) has the same times.
        monkeypatch.setattr(
            transit, "RoutingServices", lambda *_args, **_kwargs: Bendy(answers=False)
        )
        straight = post_transit(client, [CAPITOL_HILL, DOWNTOWN], presets.BIKESHARE_TRANSIT)
        again = straight.json()
        assert len(again["transit"]["steps"][-1]["coordinates"]) == 2
        assert len(again["geometry"]["coordinates"]) == 2
        assert again["transit"]["total_s"] == trip["total_s"]
        timed = [(s["seconds"], s["wait_s"]) for s in again["transit"]["steps"]]
        assert timed == [(s["seconds"], s["wait_s"]) for s in trip["steps"]]

    def test_a_transit_trip_is_two_points_no_loop_and_options_only_on_transit(
        self, client, router, installed
    ) -> None:
        assert post_transit(client, [CAPITOL_HILL, MALL, DOWNTOWN]).status_code == 400
        assert post_transit(client, [CAPITOL_HILL, DOWNTOWN], loop=True).status_code == 400
        other = post_transit(client, [CAPITOL_HILL, DOWNTOWN], "default", transit_option="direct")
        assert other.status_code == 400

    def test_the_closures_list_the_stations_with_no_service_that_day(
        self, client, installed
    ) -> None:
        response = client.get("/api/transit/closures", {"at": "2026-10-03T12:00:00"})
        assert response.status_code == 200
        body = response.json()
        assert body["service_day"] == "2026-10-03"
        assert [(s["name"], s["system"], s["reason"]) for s in body["stations"]] == [
            ("Camden Station", "MARC", "no MARC weekend service"),
            ("College Park", "MARC", "no MARC weekend service"),
        ]
        weekday = client.get("/api/transit/closures", {"at": "2026-09-30T22:30:00"}).json()
        assert weekday["stations"] == []

    def test_a_stations_times_are_small_scheduled_and_cached_for_a_minute(
        self, client, installed
    ) -> None:
        lon, lat = UNION_STATION
        response = client.get(
            "/api/transit/station-times", {"lon": lon, "lat": lat, "at": "2026-09-30T08:00:00"}
        )
        assert response.status_code == 200, response.content
        assert response["Cache-Control"] == "public, max-age=60"
        body = response.json()
        assert body["service_day"] == "2026-09-30" and body["source"] == "scheduled"
        red, camden, penn = body["lines"]
        assert (red["system"], red["line"], red["kind"], red["every_min"]) == (
            "Metro",
            "Red Line",
            "every",
            6,
        )
        assert red["time"] is None and red["toward"] is None
        assert (penn["kind"], penn["toward"], penn["time"]) == (
            "next",
            "Baltimore Penn Station",
            "8:00 am",
        )
        assert penn["at"] == "2026-09-30T08:00:00-04:00" and penn["station"] == "Union Station MARC"
        assert camden["time"] == "4:30 pm"
        # A point with no station near it: no lines; no point at all: refused.
        far = client.get("/api/transit/station-times", {"lon": -77.5, "lat": 38.5}).json()
        assert far["lines"] == []
        assert client.get("/api/transit/station-times").status_code in (400, 422)

    def test_a_stations_times_are_a_503_where_no_schedule_can_be_read(
        self, client, settings, tmp_path
    ) -> None:
        settings.TRANSIT_SCHEDULE_PATH = tmp_path / "broken.json"
        settings.TRANSIT_SCHEDULE_PATH.write_text("{")
        lon, lat = UNION_STATION
        response = client.get("/api/transit/station-times", {"lon": lon, "lat": lat})
        assert response.status_code == 503
        assert response.json()["code"] == "transit_unavailable"

    def test_a_stations_times_are_limited_per_address_apart_from_the_other_limits(
        self, client, installed
    ) -> None:
        from test_ratelimit import in_one_window

        from core import ratelimit

        limit = ratelimit.STATION_TIMES
        assert limit.scope not in {ratelimit.COVERAGE.scope, ratelimit.ROUTING.scope}
        far = {"lon": -77.5, "lat": 38.5}

        def attempt(n):
            headers = {"HTTP_X_FORWARDED_FOR": f"198.51.100.{70 + 100 * n}"}
            statuses = {
                client.get("/api/transit/station-times", far, **headers).status_code
                for _ in range(limit.requests)
            }
            return statuses, client.get("/api/transit/station-times", far, **headers)

        statuses, refused = in_one_window(limit.window_s, attempt)
        assert statuses == {200}
        assert refused.status_code == 429 and refused["Retry-After"]

    def test_after_midnight_the_next_train_is_timed_on_its_own_day(self, client, installed):
        lon, lat = UNION_STATION
        body = client.get(
            "/api/transit/station-times", {"lon": lon, "lat": lat, "at": "2026-10-01T01:30:00"}
        ).json()
        assert body["service_day"] == "2026-09-30"
        penn = next(line for line in body["lines"] if line["line"] == "Penn Line")
        assert (penn["kind"], penn["time"], penn["at"]) == (
            "next",
            "6:00 am",
            "2026-10-01T06:00:00-04:00",
        )
