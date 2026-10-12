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
  step-free access unknown;
- Light RailLink: every 15 min on weekdays, 20 at weekends; one stop not step-free.
The places are real; the times are invented. A fake router rides straight lines, so every figure
is arithmetic.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

import pytest
from test_route_api import CONTRACT_KEYS, router, segments, standard_router

from core import gbfs, presets, transit
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

    def ride(self, a, b):
        self.calls += 1
        return transit.Ride(transit._distance(a, b) / (18 / 3.6), (tuple(a), tuple(b)))


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
    assert [s.vehicle for s in schedule.systems] == ["all", "all", "all", "offpeak"]
    report = built(date(2026, 9, 28))[1]
    assert any("PF_XX_1" in line for line in report)
    assert any(line.startswith("mta-metro: no feed given") for line in report)


def test_stations_and_whether_a_bike_may_board_there(schedule) -> None:
    eastern = stop_named(schedule, "Eastern Market")
    # The map's bike entrance: DC's elevator (rule 1), not the station point.
    assert eastern.bike and eastern.rail and eastern.bike_entrance != eastern.point
    # MARC's Union Station: the platform says nothing (0), the station says step-free.
    assert stop_named(schedule, "Union Station MARC").bike
    # College Park's access is unknown, and University Center's platform not known step-free:
    # closed to a bike. A bus stop takes a bike at the curb.
    assert not stop_named(schedule, "College Park").bike
    assert not stop_named(schedule, "University Center/Baltimore St").bike
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
    with pytest.raises(transit.Unavailable):
        transit.load(tmp_path / "missing.json")
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
        "Board the MARC Penn Line at 7:00 am from Union Station MARC: you arrive 6:40 am,"
        " 20 min spare; next train after that: 8:00 am. Ride 45 min to Baltimore Penn Station."
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
    assert departure["label"] == f"MARC 7:00 am · {round(spare / 60)} min spare"
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
        n.startswith("You would miss the 7:00 am (the MARC Penn Line)") for n in out["notes"]
    )
    assert out["total_s"] > transit.block(plan, schedule)["total_s"]


def test_the_service_day_runs_to_3_am_and_a_holiday_is_flagged() -> None:
    late = transit.moment_of(at(2026, 10, 3, 1, 30))  # a Saturday, 1:30 am
    assert (late.service_day, late.minute) == (date(2026, 10, 2), 25 * 60 + 30)
    assert late.date == date(2026, 10, 3) and late.day_type == "weekday"
    thanksgiving = transit.moment_of(at(2026, 11, 26, 9, 0))
    assert thanksgiving.holiday and not thanksgiving.rush(8 * 60)
    assert transit.moment_of(at(2026, 9, 30, 8, 0)).rush(8 * 60)
    assert transit.clock(25 * 60 + 30) == "1:30 am" and transit.clock(19 * 60 + 42) == "7:42 pm"


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


# --- Own Bike + Transit -------------------------------------------------------------------------


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
    assert words[2] == "Board the Orange Line (about 5 min wait); ride 10 min to Federal Triangle."
    assert words[4].endswith("min to your destination.")


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
    assert second.words().startswith("Change to the Orange Line (about 5 min wait)")


def test_dc_to_baltimore_takes_marc_with_the_bike(schedule) -> None:
    plan = plan_bike(schedule, NOMA, BALTIMORE, at(2026, 9, 30, 6, 20))
    best = plan.options[0]
    assert not best.direct
    assert [(leg.system, leg.lines) for leg in transit_legs(best)] == [("MARC", ("Penn Line",))]
    out = transit.block(plan, schedule)
    assert out["credits"] == ["MDOT MTA GTFS (scheduled times)"]
    assert any(
        n.startswith("Full-size bikes are allowed on every MARC train") for n in out["notes"]
    )
    assert transit.SCHEDULED_WORDS in out["notes"]
    # Light RailLink is beside the destination but takes no bike in the weekday rush.
    assert "Light RailLink: no bikes on board at this time." in out["notes"]
    assert not any(leg.system == "Light RailLink" for o in plan.options for leg in o.legs)


def test_the_light_rail_takes_a_bike_outside_rush_hour(schedule) -> None:
    plan = plan_bike(schedule, NOMA, BALTIMORE, at(2026, 10, 3, 10, 0))
    assert any(
        [leg.system for leg in transit_legs(o)] == ["MARC", "Light RailLink"] for o in plan.options
    )


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


def test_bikes_are_flagged_on_a_blackout_date_and_still_offered() -> None:
    schedule = schedule_from(date(2026, 7, 1))
    plan = plan_bike(schedule, CAPITOL_HILL, DOWNTOWN, at(2026, 7, 4, 10, 0))
    metro = next(o for o in plan.options if not o.direct)
    out = transit.block(transit.choose(plan, metro.key), schedule)
    assert out["notes"][0] == transit.BLACKOUT_WORDS and out["bike_blackout"] is True
    # The direct ride takes no bike on Metro: nothing to flag.
    assert transit.block(transit.choose(plan, "direct"), schedule)["bike_blackout"] is False


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


# --- Bikeshare + Transit ------------------------------------------------------------------------


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


# --- POST /api/route and GET /api/transit/closures ----------------------------------------------

db = pytest.mark.django_db(transaction=True)


@pytest.fixture
def installed(tmp_path, settings, monkeypatch):
    """The schedule installed where the API reads it, and the bike legs' router straight lines."""
    path = tmp_path / "transit-schedule.json"
    path.write_text(built(date(2026, 9, 28))[0])
    settings.TRANSIT_SCHEDULE_PATH = path
    monkeypatch.setattr(transit, "RoutingServices", lambda *_args: Straight())
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

    def test_depart_at_plans_another_day(self, client, segments, router, installed) -> None:
        router(standard_router())
        response = post_transit(client, [NOMA, BALTIMORE], depart_at="2026-10-03T10:00:00-04:00")
        assert response.status_code == 200, response.content
        trip = response.json()["transit"]
        assert trip["day_type"] == "saturday"
        assert "MARC Camden Line: no weekend service." in trip["notes"]

    def test_a_missing_schedule_is_a_503_said_plainly(self, client, router, settings, tmp_path):
        settings.TRANSIT_SCHEDULE_PATH = tmp_path / "none.json"
        response = post_transit(client, [CAPITOL_HILL, DOWNTOWN])
        assert response.status_code == 503
        assert response.json()["code"] == "transit_unavailable"
        assert response["Retry-After"]
        assert client.get("/api/transit/closures").status_code == 503

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
