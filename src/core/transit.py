"""The two transit ride types: Own Bike + 🚆🚌 and Bikeshare + 🚶🚆🚌.

TRANSIT-ASSIST. Stephen, 2026-10-11: "relative options for a transit assisted commute.
Basically we'd have a selection that would also bring up how long it would roughly take by
bikeshare and metro or bus and metro, or taking bike on metro. Only when enabled." On
2026-10-12 transit became two commuting ride types, chosen like any other (that is how it is
enabled; there is no separate setting), and later that day (15:00) each answers with a short
ranked list: riding directly there always, and the quickest transit trips, quickest first, the
map following the one chosen. The region runs from DC to Baltimore, so the trips use every
system in transitdata/systems.json (WMATA Metro and Metrobus, MARC, Light RailLink, Metro
SubwayLink, VRE), chained: at most `MAX_LEGS` transit legs with a transfer between them.

The owner renamed them on 2026-10-12 (20:35): "Own Bike + Transit" is "Own Bike + 🚆🚌" (said
"Own bike plus train or bus") and "Bikeshare + Transit" is "Bikeshare + 🚶🚆🚌" (said "Bikeshare
plus walk, train or bus"); the ids and links are unchanged.

- **Own Bike + 🚆🚌** (`presets.BIKE_TRANSIT`): the bike goes the whole way, on board or on a
  bus's front rack, where each system's rules allow it; never left at a station, and no leg on
  foot (a transfer between two systems' stops is ridden).
- **Bikeshare + 🚶🚆🚌** (`presets.BIKESHARE_TRANSIT`): each end on foot or by Capital
  Bikeshare, whichever is quicker (a bikeshare bike is docked before boarding, and the walk from
  that dock to the entrance counts; at the far end, a new bike from a dock near the exit to a
  dock near the destination). Walk, Metro, walk is a fair answer. The docks are named. Walking
  the whole way is offered too, among the options, where it is the quickest or the trip is under
  `WALK_ONLY_M` (the owner, 2026-10-12 20:32), walked by Valhalla's pedestrian costing.

Each option lists its legs compactly (`option_legs`), which the page shows as marks
("🚶 4 min · 🚲 12 min · 🔴 18 min") and says in words (frontend/src/lib/transitMarks.ts).

The answer is a route like any other ride type's (`routing.plan`): its line is the chosen
option's **first ride leg** (the whole ride, riding directly there), with the stress colours
and the rest. The trip is the route's `transit` block (`block`): the options, and the chosen
one's steps in order, each with its line on the map, the total ("about N min, scheduled") and
the time of riding the whole way, said plainly when it is quicker. A route line that is a walk
is walked by Valhalla's pedestrian costing, and the chosen trip's other walks and rides are
routed for the map too (`drawn`: pedestrian or bicycle costing), straight only where the router
does not answer; the drawing never changes a time.

The times are **scheduled** (core.transit_live then times a Metro or Metrobus departure by
WMATA's prediction where it has one, and says "live"): each system's static GTFS, compacted on the
host by scripts/build_transit_schedule.py into one file the API reads
(`settings.TRANSIT_SCHEDULE_PATH`). The agencies' terms do not let this project republish the
data, so the file is built on the host and never committed (docs/SOURCES.md). A planned closure
is in it only where the agency published it in the static timetable; every transit answer says
to check for track work. Until WMATA's rail GTFS is built (it needs a WMATA key), Metro runs on
its committed typical timetable from wmata.com (`with_typical_metro`), with or without the file:
waits are half the published interval, never a counted-down departure, and its credit names it
"typical service". Metrobus waits for its GTFS. Every transit time a rider sees says
"scheduled" (`SCHEDULED`), timetable or typical alike: "8:12 am scheduled", "every 8 min,
scheduled".

The time of day
---------------
A plan is for a moment (now, unless the request says when). The file keeps each service id's
calendar day by day (`Schedule.active`), as the feed publishes it with its holidays and service
changes, so a weekend or a holiday a commuter line does not run, or a peak-only route out of its
peak direction, is simply not there. Before 3:00 am a moment belongs to the day before, as GTFS
writes it (25:30 is 1:30 am); from 1 to 5 am both service days are searched, so the day before's
owl trips (even past 27:00) and the new day's first are both found. A service-day minute is real
elapsed time from GTFS's zero (noon less 12 hours), so times are right across daylight saving.

A pattern (one stop order of one route) has the median run time from its first stop to each
later one per band of the service day (`BANDS`), and every trip's departure from its first stop.
At a stop, the next departures of every pattern going on to the stop wanted are merged (same
minute counted once). Where at least three come and every gap is at most `FREQUENT_MIN`, the wait
is half the mean gap (a rider who does not time the trip); otherwise (a near pair before a long
gap included) the wait is the time to the actual next departure, and the step says when the one
after it leaves. A rider who would miss it is planned on the next one that can be caught; with
none within the hour the trip is left out. A departure more than `MAX_WAIT_MIN` off is not offered.

Choosing stops
--------------
Straight lines first, the router only where it pays: the nearest `STATION_CANDIDATES` stations
at each end are routed for Own Bike + 🚆🚌 (at most `MAX_ROUTER_CALLS` calls, the direct ride
first, each capped at `CANDIDATE_CALL_S` and all inside the search's budget; a leg the router does
not answer in time is estimated, never fatal); the nearest stations of every other rail system
and the nearest bus stops are estimated from the straight line times `DETOUR`. The chosen
option's first ride is then routed as the answer's line, and its time replaces the estimate.

Bikes on transit
----------------
Each system's rule is in systems.json with its source, read 2026-10-12: one short line a rider
needs, said once in the notes of a plan that takes a bike on it ("Metro: use the elevators and a
car's end doors."). Bikes ride WMATA Metro at all hours by the elevators (the stations with
neither DC's nor OpenStreetMap's elevator are not used with a bike: unclear bike access is
closed), Metrobus on the front rack, and every MARC, Light RailLink and Metro SubwayLink train
(the owner, 2026-10-12: "you can use it unless it's too crowded to do so. No API knows how many
people can fit." There is no crowding model and no crowding note: "It's common courtesy.").
VRE takes full-size bikes on every train (read 2026-10-12; the owner added VRE that day).
Every station of the other rail systems takes a bike (the owner, 2026-10-12: every station has a
ramp or an elevator, and stairs will do in a pinch).
On the dates in `BLACKOUTS_PATH` (July 4 every year, and dates the owner adds by hand) bikes
are not allowed on Metro (the owner: allowed "at all times except" those days): Own Bike +
🚆🚌 uses no Metro that day and says so plainly; Bikeshare + 🚶🚆🚌 still rides Metro on
foot.

Every sentence is US units first with metric in brackets (OWNER-DECISIONS 85), worded so the
page and a screen reader read the same words.
"""

from __future__ import annotations

import json
import logging
import math
import re
from bisect import bisect_left
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache, partial
from pathlib import Path
from typing import Protocol

from routemaker.geo import Point, haversine
from routemaker.lang import spanish, t
from routemaker.ridetime import ZONE, is_federal_holiday

from . import bikeshare, gbfs, presets

logger = logging.getLogger(__name__)

LonLat = list[float]

SCHEMA = 2

# The service day's bands, in minutes after midnight of the service day (GTFS times run
# past 24:00): (start, end, name). 3:00 am to 3:00 am the next morning.
BANDS = (
    (180, 360, "early morning"),
    (360, 570, "morning rush"),
    (570, 900, "midday"),
    (900, 1140, "evening rush"),
    (1140, 1320, "evening"),
    (1320, 1800, "late night"),  # to 30:00: owl trips past 27:00 included
)
DAY_START_MIN = 180
# Weekday rush hour, the `offpeak` bike rule's: the morning and evening rush bands.
RUSH_BANDS = (1, 3)

# Paces. The walk is the bikeshare planner's 3 mph; a street route is about `DETOUR`
# times the straight line, the same figure the bikeshare planner estimates rides with.
WALK_SPEED_KMH = bikeshare.WALK_SPEED_KMH
DETOUR = bikeshare.RIDE_DETOUR
BIKESHARE_SPEED_KMH = presets.BIKESHARE_CLASSIC_SPEED_KMH

# How far each leg may go, in straight lines.
WALK_TO_STATION_M = 1609.0  # 1 mi
WALK_TO_STOP_M = 640.0  # 0.4 mi, on foot to a bus stop
RIDE_TO_STOP_M = 1609.0  # 1 mi, on your bike to a bus stop
DOCK_NEAR_M = 800.0  # 0.5 mi, to a dock with a bike, or from one to the destination
DOCK_AT_STATION_M = 400.0  # 0.25 mi, a dock beside the station
BIKE_TO_STATION_M = 8047.0  # 5 mi
TRANSFER_M = 400.0  # 0.25 mi between two stops, to change
BUS_STOPS_NEAR = 8  # the nearest bus stops tried, each end
PER_SYSTEM = 2  # the nearest stations of each rail system tried, each end

STATION_CANDIDATES = 3
# Novice and Nervous's hop past a busy stretch (v0.11.0; the owner, 2026-10-21: "We might also
# want to offer transit to avoid particularly problematic sections"): the stations and stops
# within this of the stretch's ends are tried too, boarding near where it begins and getting
# off near where it ends (`plan_bike`'s and `plan_bikeshare`'s `hop`), their legs from the
# start and to the end estimated (no router calls past the budget's).
HOP_NEAR_M = 1609.0  # 1 mi
# The hop is planned unasked only where it is at most this much slower than the quickest
# other transit trip (riding directly there rides the stretch, so is not compared); past it,
# it is listed and the quickest is planned.
HOP_SLACK_S = 900.0  # 15 min
# Router calls for Own Bike + 🚆🚌: three stations each end and the direct ride.
MAX_ROUTER_CALLS = 2 * STATION_CANDIDATES + 1
# The options each answer lists (the owner, 2026-10-12 15:00): riding directly there always,
# and the quickest transit trips, one of each kind, up to this many.
TRANSIT_OPTIONS = 3
DIRECT = "direct"
# Bikeshare + 🚶🚆🚌 also offers walking the whole way (the owner, 2026-10-12 20:32: "bikeshare
# plus transit could also include walking if that's a reasonable option"): where walking is the
# quickest option, or the trip is under this, in a straight line (1 mi).
WALK_ONLY = "walk"
WALK_ONLY_M = 1609.0
# At most this many transit legs, with a transfer between (the owner, 2026-10-12).
MAX_LEGS = 2

ACCESS_WALK_S = 120.0
ACCESS_BIKE_S = 240.0
TRANSFER_S = 60.0
# Departures at most this far apart are "frequent": the wait is half the headway.
FREQUENT_MIN = 15
# A departure further off than this is not offered.
MAX_WAIT_MIN = 60

# Every Metro station has elevators (WMATA: all 98 stations are accessible), so every one takes
# a bike. A station the elevator files miss (27 of them, NoMa-Gallaudet U among them) was left out,
# and a rider a block from NoMa was sent 14 min to another station (Stephen, 2026-10-21). Its
# bike entrance is then its nearest entrance, where the files have no elevator.
EVERY_STATION_TAKES_A_BIKE = True
SYSTEMS_PATH = Path(__file__).resolve().parent / "transitdata" / "systems.json"
BLACKOUTS_PATH = Path(__file__).resolve().parent / "transitdata" / "metro-bike-blackouts.json"
METRO_SYSTEM = "wmata-rail"
TYPICAL_PATH = Path(__file__).resolve().parent / "transitdata" / "metro-typical.json"


def _month(number: int) -> str:
    months = (
        t("January"), t("February"), t("March"), t("April"), t("May"), t("June"),
        t("July"), t("August"), t("September"), t("October"), t("November"), t("December"),
    )  # fmt: skip
    return months[number - 1]


def day_said(day: date) -> str:
    """A date as a note says it, in the language in force: "July 4"."""
    return t("{month} {number}", month=_month(day.month), number=day.day)


def ended_words(system: str, last_day: date) -> str:
    """A system left out after its own timetable's end (`_without`)."""
    return t(
        "{system} is not planned for this date: its installed timetable ends {day}, {year}.",
        system=system,
        day=day_said(last_day),
        year=last_day.year,
    )


def beyond_words(start: date, last_day: date) -> str:
    """Metro's typical timetable alone, past the installed file (`_typical_beyond`)."""
    return t(
        "Only Metro is planned: the other timetables installed cover {first} to {last}, {year}.",
        first=day_said(start),
        last=day_said(last_day),
        year=last_day.year,
    )


def blackout_words(day: date) -> str:
    """The plain note on a blackout date: "Bikes aren't allowed on Metro today (July 4)."."""
    return t("Bikes aren't allowed on Metro today ({day}).", day=day_said(day))


# The holiday note in English (`holiday_words` says it in the language in force). Metro on its
# typical timetable has no holiday timetable: a holiday runs the typical file's `holiday` day
# type (Sunday), and the note says that instead.
HOLIDAY_WORDS = (
    "Today is a federal holiday: each system's holiday timetable is used, as it publishes it."
)
# Said in English whatever the language: the app finds these two among the notes by their words
# and says them itself, translated (frontend/src/lib/transit.ts SAID_IN_TIMES).
SCHEDULED_WORDS = "Scheduled service: check for track work and service alerts before you go."
# Every transit time a rider sees says where it is from, in one word (the owner, 2026-10-12:
# "Make it clear whether it's a schedule or live."): "8:12 am scheduled", "every 8 min,
# scheduled". GTFS timetables and Metro's typical timetable are both "scheduled"; live times
# (v0.7) will say "live". Each transit step and the departure carry it as `source`.
SCHEDULED = "scheduled"
# A departure WMATA predicts (core.transit_live.with_live_trains, with_live_buses): said "live".
LIVE = "live"
LIVE_WORDS = "Departures marked live are WMATA's predictions; the time on board is scheduled."
NO_TRANSIT_WORDS = (
    "No Metro, train or bus is scheduled between these places at this time: riding the whole"
    " way is the plan."
)


def no_transit_words() -> str:
    """`NO_TRANSIT_WORDS` in the language in force."""
    return t(
        "No Metro, train or bus is scheduled between these places at this time: riding the whole"
        " way is the plan."
    )


# The kinds of step. A transit step's mode is its system's (`TRANSIT_MODES`).
RIDE = "ride"  # your own bike
TAKE = "take"  # walk to a bikeshare dock and take a bike
SHARE = "bikeshare"  # ride a bikeshare bike and dock it
WALK = "walk"
ENTER = "enter"  # into a station, to the platform
EXIT = "exit"
METRO = "metro"
RAIL = "rail"
LIGHT_RAIL = "light-rail"
SUBWAY = "subway"
BUS = "bus"
TRANSIT_MODES = (METRO, RAIL, LIGHT_RAIL, SUBWAY, BUS)


class Unavailable(Exception):
    """The schedule file is missing, unreadable or of another schema."""


class NoTransit(Exception):
    """No option at all can be made; the message says why, in words for a rider."""


# --- The schedule ------------------------------------------------------------------


@dataclass(frozen=True)
class System:
    index: int
    id: str
    name: str  # "Metro", "MARC"
    mode: str  # one of TRANSIT_MODES
    words: str  # "the MARC {route}"
    credit: str
    idle_notes: bool
    vehicle: str  # the bike rule: all, trip, offpeak or none
    rule: str  # the bike rule in words
    source: str
    typical: bool = False  # Metro's typical timetable (`with_typical_metro`), not a GTFS
    # The feed's own last day of service, when the file says it (scripts/build_transit_schedule):
    # a later day is not covered for this system (`load` leaves it out), never "no service".
    last_day: date | None = None

    def vehicle_words(self, routes) -> str:
        return self.words.format(route=" or ".join(routes))

    def route_name(self, route: str) -> str:
        """A route as a note names it: "MARC Camden Line", "Metro Orange Line"."""
        if route.lower() in self.name.lower():
            return self.name
        if self.name.lower() in route.lower():
            return route
        return f"{self.name} {route}"


@dataclass(frozen=True)
class Stop:
    index: int
    name: str
    point: tuple[float, float]
    bike_entrance: tuple[float, float]
    bike: bool  # a bike can board here: WMATA's elevator, any MARC or MTA station, a bus stop
    entrances: tuple[tuple[float, float], ...]
    system: int
    rail: bool  # a station (entered and left), not a bus stop
    # Its bike entrance is an elevator the files know; else an entrance, often step-free
    # (Stephen, 2026-10-21: "a lot have walk-in entrances"), and the steps do not say elevator.
    elevator: bool = True
    # Every elevator a bike could use here is out (core.transit_live.blocked_stations): a trip
    # taking its own bike in or out here is ranked this many seconds down (`ELEVATOR_OUT_S`).
    elevator_out_s: float = 0.0


@dataclass(frozen=True)
class Pattern:
    index: int
    system: int
    route: str  # "Red Line", "Penn Line", "B10"
    stops: tuple[int, ...]
    runs: tuple[tuple[int, ...] | None, ...]  # per band, from the first stop, seconds
    # service index -> departures from the first stop, minutes * 2 + 1 where a bike may board
    trips: dict[int, tuple[int, ...]]

    def runs_at(self, minute: float) -> tuple[int, ...]:
        """The run times of the band at `minute`, else the nearest band's."""
        index = band_index(minute)
        order = sorted(range(len(BANDS)), key=lambda i: abs(i - index) if index is not None else -i)
        for i in order:
            if self.runs[i] is not None:
                return self.runs[i]
        raise Unavailable("a pattern has no run times")


@dataclass(frozen=True)
class Hop:
    """One ride from a stop to another: the wait, the ride, the routes that run it, the stops
    the one taken calls at (both ends included), and for an infrequent service the departure
    taken and the one after it (service-day minutes)."""

    wait_s: float
    ride_s: float
    routes: tuple[str, ...]
    path: tuple[int, ...]
    system: int
    pattern: int
    frequent: bool
    depart: float | None = None
    after: float | None = None
    later: tuple[float, ...] = ()  # every later departure seen, for a rider who misses one
    every: float | None = None  # a frequent service: minutes between departures
    first: float | None = None  # typical Metro before its first train: that train (minutes)

    @property
    def total_s(self) -> float:
        return self.wait_s + self.ride_s


def band_index(minute: float) -> int | None:
    for index, (start, end, _name) in enumerate(BANDS):
        if start <= minute < end:
            return index
    return None


CELL = 0.01  # degrees: the stop index's grid


@dataclass
class Schedule:
    systems: list[System]
    stops: list[Stop]
    patterns: list[Pattern]
    services: list[str]  # per service: one 0 or 1 per day from `start`
    start: date
    days: int
    source: dict = field(default_factory=dict)
    # Said with every plan from it: Metro's typical timetable standing in for an installed file
    # that does not reach the date (`load`), or the systems left out (`_without`). Each phrase
    # with its places, worded when read (`note`): the schedule is cached across requests.
    said: tuple[Callable[[], str], ...] = ()

    def __post_init__(self) -> None:
        self.at_stop: dict[int, list[tuple[int, int]]] = {}
        for pattern in self.patterns:
            for pos, stop in enumerate(pattern.stops):
                self.at_stop.setdefault(stop, []).append((pattern.index, pos))
        self.grid: dict[tuple[int, int], list[int]] = {}
        for stop in self.stops:
            self.grid.setdefault(_cell(stop.point), []).append(stop.index)

    @property
    def last_day(self) -> date:
        return self.start + timedelta(days=self.days - 1)

    def covers(self, day: date) -> bool:
        return 0 <= (day - self.start).days < self.days

    @property
    def note(self) -> str:
        """`said`, in the language in force; "" for none."""
        return " ".join(words() for words in self.said)

    @property
    def first_end(self) -> tuple[date, System | None]:
        """The first last day of the installed timetables: the window's, or an earlier one of a
        system whose feed ends inside it (that system)."""
        ending = [s for s in self.systems if s.last_day is not None and s.last_day < self.last_day]
        if not ending:
            return self.last_day, None
        system = min(ending, key=lambda s: (s.last_day, s.index))
        return system.last_day, system

    def active(self, day: date) -> frozenset[int]:
        """The services running on the service day `day`."""
        offset = (day - self.start).days
        if not 0 <= offset < self.days:
            return frozenset()
        return frozenset(i for i, bits in enumerate(self.services) if bits[offset] == "1")

    def near(self, point, limit_m: float) -> list[tuple[float, Stop]]:
        """The stops within `limit_m` of `point`, nearest first."""
        lat_cells = math.ceil(limit_m / 1110.0)
        lon_cells = math.ceil(limit_m / (1110.0 * max(0.2, math.cos(math.radians(point[1])))))
        cx, cy = _cell(point)
        found = []
        for x in range(cx - lon_cells, cx + lon_cells + 1):
            for y in range(cy - lat_cells, cy + lat_cells + 1):
                for index in self.grid.get((x, y), ()):
                    stop = self.stops[index]
                    distance = _distance(point, stop.point)
                    if distance <= limit_m:
                        found.append((distance, stop))
        return sorted(found, key=lambda t: (t[0], t[1].index))

    def place(self, stop: Stop) -> str:
        """A stop as a step names it: a station by its name, a bus stop as "the stop at X"."""
        if stop.rail:
            return stop.name
        return f"the stop at {stop.name}" if stop.name else "the bus stop"


# Stephen, 2026-10-21: "I'd say an elevator outage is about a 15 minute penalty" (with no other
# elevator to use; "Most cyclists would just ride from the next station over"), on the ranking's
# score only, never the time shown, and "15 minutes for everyone". In the search, so the same
# line's next station is kept where it wins.
ELEVATOR_OUT_S = 900.0
# Stops of one station (its platforms) lie within this much of each other beyond the nearest.
SAME_STATION_M = 60.0


def with_elevators_out(schedule: Schedule, points, cost_s: float = ELEVATOR_OUT_S) -> Schedule:
    """The schedule with the Metro stations at `points` ([lon, lat]) costing `cost_s` to take
    a bike in or out of (`Stop.elevator_out_s`)."""
    if not points:
        return schedule
    metro = {s.index for s in schedule.systems if s.id == METRO_SYSTEM}
    rail = [stop for stop in schedule.stops if stop.rail and stop.system in metro]
    # Only the station at each point, not the next one over (Farragut North and West are
    # 227 m apart): the nearest Metro stop, and any of the same station's within
    # SAME_STATION_M more.
    marked: set[int] = set()
    for p in points:
        near = [(_distance(stop.point, p), stop.index) for stop in rail]
        near = [(d, i) for d, i in near if d <= STATION_NEAR_M]
        if near:
            closest = min(d for d, _ in near)
            marked.update(i for d, i in near if d <= closest + SAME_STATION_M)

    stops = [
        replace(stop, elevator_out_s=cost_s) if stop.index in marked else stop
        for stop in schedule.stops
    ]
    return replace(schedule, stops=stops)


def _cell(point) -> tuple[int, int]:
    return (math.floor(point[0] / CELL), math.floor(point[1] / CELL))


_PLATFORM_WAY = re.compile(r"\s+(?:nb|sb|eb|wb)$")
# All-capital words kept as written (up to three letters: "BWI", "MD", "W VA") but these.
_SMALL_WORDS = {"OF": "of", "ST": "St", "NEW": "New"}


def station_name(name: str, system: str) -> str:
    """A rail stop's name as a card says it: MDOT MTA's MARC feed writes "PENN STATION MARC sb"
    and "UNION STATION MARC Washington", said "Penn Station MARC" and "Union Station MARC" (the
    platform's way dropped, the words after the system's name too, capitals as a name has them)."""
    name = _PLATFORM_WAY.sub("", name.strip())
    cut = name.find(f" {system} ")
    if cut >= 0:
        name = name[: cut + len(system) + 1]
    words = name.split()
    plain = [w for w in words if w != system]
    # Only a name in MARC's form, ending in its system's name, all in capitals.
    if words[-1:] != [system] or not plain or any(w != w.upper() for w in plain):
        return name
    return " ".join(
        w if w == system else _SMALL_WORDS.get(w, w if len(w) <= 3 else w.capitalize())
        for w in words
    )


def parse(doc: dict) -> Schedule:
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise Unavailable(f"the transit schedule is not schema {SCHEMA}")
    if [b[2] for b in doc.get("bands", [])] != [b[2] for b in BANDS]:
        raise Unavailable("the transit schedule's bands are not this code's")
    systems = [
        System(
            i,
            s["id"],
            s["name"],
            s["mode"] if s["mode"] in TRANSIT_MODES else RAIL,
            s["words"],
            s.get("credit", ""),
            bool(s.get("idle_notes")),
            s["bike"]["vehicle"],
            s["bike"].get("rule", ""),
            s["bike"].get("source", ""),
            last_day=date.fromisoformat(s["last_day"]) if s.get("last_day") else None,
        )
        for i, s in enumerate(doc["systems"])
    ]
    stops = [
        Stop(
            i,
            (
                s["name"]
                if systems[int(s["system"])].mode == BUS
                else station_name(s["name"], systems[int(s["system"])].name)
            ),
            tuple(s["point"]),
            tuple(s.get("bike_entrance") or s["point"]),
            # Every station takes a bike (`EVERY_STATION_TAKES_A_BIKE`); a bus stop, at the curb.
            bool(s["bike"]) or EVERY_STATION_TAKES_A_BIKE,
            tuple(tuple(e) for e in s.get("entrances") or [s["point"]]),
            int(s["system"]),
            systems[int(s["system"])].mode != BUS,
            bool(s["bike"]),
        )
        for i, s in enumerate(doc["stops"])
    ]
    days = int(doc["days"])
    services = [str(s["days"]) for s in doc["services"]]
    if any(len(bits) != days for bits in services):
        raise Unavailable("a service's calendar is not the file's window")
    patterns = []
    for i, p in enumerate(doc["patterns"]):
        stops_of = tuple(int(s) for s in p["stops"])
        if any(not 0 <= s < len(stops) for s in stops_of):
            raise Unavailable("a pattern names a stop that is not listed")
        runs = tuple(None if r is None else tuple(int(x) for x in r) for r in p["runs"])
        if len(runs) != len(BANDS) or any(r is not None and len(r) != len(stops_of) for r in runs):
            raise Unavailable("a pattern's run times do not match its stops")
        trips = {int(k): tuple(int(d) for d in v) for k, v in p["trips"].items()}
        patterns.append(Pattern(i, int(p["system"]), str(p["route"]), stops_of, runs, trips))
    return Schedule(
        systems,
        stops,
        patterns,
        services,
        date.fromisoformat(doc["start"]),
        days,
        {s["id"]: s.get("source", {}) for s in doc["systems"]},
    )


_loaded: tuple[Path, float, Schedule] | None = None


def load(path: Path, day: date | None = None) -> Schedule:
    """The schedule at `path`, read again when the file changes, with Metro on its typical
    timetable where the file has no WMATA rail GTFS (`with_typical_metro`). With no file
    installed, or one whose window does not reach `day` (default today: it has run out, say),
    Metro's typical timetable alone, from the day before `day`: it needs no refresh, so Metro
    stays while the other systems wait for the file to be rebuilt (`schedule_alert` says so)."""
    day = day or datetime.now(ZONE).date()
    try:
        path.stat()
    except OSError:
        return typical_only(day)
    schedule = _read(path)
    if not schedule.covers(day):
        return _typical_beyond(day, schedule.start, schedule.last_day)
    ended = frozenset(s.id for s in schedule.systems if s.last_day is not None and s.last_day < day)
    return _without(schedule, ended) if ended else schedule


_trimmed: dict[tuple[int, frozenset[str]], tuple[Schedule, Schedule]] = {}


def _without(schedule: Schedule, ended: frozenset[str]) -> Schedule:
    """`schedule` without the systems whose own timetables have ended (pipeline-1): not
    covered, so neither planned nor struck through as closed, and said with every plan. Metro's
    WMATA GTFS gives way to its typical timetable, as when no GTFS is installed."""
    key = (id(schedule), ended)
    if key in _trimmed and _trimmed[key][0] is schedule:
        return _trimmed[key][1]
    gone = [s for s in schedule.systems if s.id in ended]
    kept = [s for s in schedule.systems if s.id not in ended]
    system_of = {s.index: i for i, s in enumerate(kept)}
    stop_of: dict[int, int] = {}
    stops = []
    for stop in schedule.stops:
        if stop.system in system_of:
            stop_of[stop.index] = len(stops)
            stops.append(replace(stop, index=len(stops), system=system_of[stop.system]))
    patterns = [
        replace(p, index=i, system=system_of[p.system], stops=tuple(stop_of[x] for x in p.stops))
        for i, p in enumerate(p for p in schedule.patterns if p.system in system_of)
    ]
    trimmed = Schedule(
        [replace(s, index=i) for i, s in enumerate(kept)],
        stops,
        patterns,
        schedule.services,
        schedule.start,
        schedule.days,
        {k: v for k, v in schedule.source.items() if k not in ended},
    )
    if METRO_SYSTEM in ended:
        trimmed = with_typical_metro(trimmed)
    trimmed.said = tuple(partial(ended_words, s.name, s.last_day) for s in gone)
    if len(_trimmed) > 16:
        _trimmed.clear()
    _trimmed[key] = (schedule, trimmed)
    return trimmed


@lru_cache(maxsize=8)
def _typical_beyond(day: date, start: date, last_day: date) -> Schedule:
    """Metro's typical timetable alone for a day the installed file does not reach (before its
    first day or after its last), saying so."""
    return replace(
        typical_only(day),
        said=(partial(beyond_words, start, last_day),),
    )


def _read(path: Path) -> Schedule:
    """The installed file itself (with typical Metro where it has no WMATA rail GTFS), read
    again when it changes; `Unavailable` when it cannot be read."""
    global _loaded
    try:
        mtime = path.stat().st_mtime
    except OSError as error:
        raise Unavailable(f"the transit schedule could not be read: {error}") from error
    if _loaded is not None and _loaded[0] == path and _loaded[1] == mtime:
        _warn_if_stale(_loaded[2])
        return _loaded[2]
    try:
        schedule = with_typical_metro(parse(json.loads(path.read_text())))
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        raise Unavailable(f"the transit schedule could not be read: {error}") from error
    _loaded = (path, mtime, schedule)
    _warn_if_stale(schedule)
    return schedule


# --- Metro's typical timetable -------------------------------------------------------------
#
# The owner, 2026-10-12: "Just use defaults. The wmata website has a typical timetable for
# rail." and "Rail is so frequent that it's not a major issue. It's bus where the API helps."
# Until WMATA's rail GTFS is built into the schedule (it needs a WMATA key), Metro runs on
# transitdata/metro-typical.json: each day type's opening hours, each line's minutes between
# trains per time band (wmata.com's line pages), and run times between stations (an estimate:
# the file's `about` and docs/SOURCES.md). Its trains are laid out evenly at those intervals and
# a wait is half the interval (`_hop`): no departure is named or counted down. Metrobus stays
# out until its own GTFS is built, and nothing is said about it.

# The window of a schedule of Metro's typical timetable alone, in days from the day before.
TYPICAL_DAYS = 400
TYPICAL_DAY_TYPES = ("monday-thursday", "friday", "saturday", "sunday")
_WEEKDAY_TYPES = ("monday-thursday",) * 4 + ("friday", "saturday", "sunday")


@lru_cache(maxsize=2)
def _typical_doc(path: Path = TYPICAL_PATH) -> dict:
    return json.loads(path.read_text())


def _metro_config() -> dict:
    systems = json.loads(SYSTEMS_PATH.read_text())["systems"]
    return next(s for s in systems if s["id"] == METRO_SYSTEM)


def typical_day_type(day: date, doc: dict | None = None) -> str:
    """The typical timetable's day type of a service day; a federal holiday runs the file's
    `holiday` day type."""
    doc = doc or _typical_doc()
    if is_federal_holiday(day):
        return doc["holiday"]
    return _WEEKDAY_TYPES[day.weekday()]


def _clock_min(value: str, hours: tuple[int, int]) -> int:
    """A clock time ("05:00") in service-day minutes ("26:00" is 2 am the next morning); "open"
    and "close" are the day's hours."""
    if value == "open":
        return hours[0]
    if value == "close":
        return hours[1]
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def typical_departures(doc: dict, line: str, day_type: str) -> list[int]:
    """A line's trains from its terminals on a day type, in service-day minutes: from opening
    to closing, evenly at each band's interval ("every 4-5 min" is every 4.5)."""
    opens, closes = (_clock_min(v, (0, 0)) for v in doc["hours"][day_type])
    hours = (opens, closes)
    every = doc["lines"][line]["every"]
    bands = every["weekday"] if day_type in TYPICAL_DAY_TYPES[:2] else every[day_type]
    out: list[int] = []
    at = float(opens)
    for start, end, gap in bands:
        step = sum(gap) / len(gap) if isinstance(gap, list) else float(gap)
        at = max(at, float(_clock_min(start, hours)))
        while at < min(_clock_min(end, hours), closes):
            out.append(round(at))
            at += step
    return out


@lru_cache(maxsize=8)
def typical_only(day: date) -> Schedule:
    """Metro's typical timetable alone (no schedule installed), from the day before `day`."""
    return with_typical_metro(Schedule([], [], [], [], day - timedelta(days=1), TYPICAL_DAYS))


def with_typical_metro(schedule: Schedule, path: Path = TYPICAL_PATH) -> Schedule:
    """`schedule` with Metro on its typical timetable over the schedule's own window, unless it
    already has WMATA's rail GTFS, which then replaces the typical timetable with no setting."""
    if any(s.id == METRO_SYSTEM for s in schedule.systems):
        return schedule
    doc = _typical_doc(path)
    config = _metro_config()
    system = System(
        len(schedule.systems),
        METRO_SYSTEM,
        config["name"],
        config["mode"] if config["mode"] in TRANSIT_MODES else RAIL,
        config["words"],
        doc["credit"],
        bool(config.get("idle_notes")),
        config["bike"]["vehicle"],
        config["bike"].get("rule", ""),
        config["bike"].get("source", ""),
        typical=True,
    )
    stops = list(schedule.stops)
    index: dict[str, int] = {}
    for row in doc["stations"]:
        index[row["name"]] = len(stops)
        stops.append(
            Stop(
                len(stops),
                row["name"],
                tuple(row["point"]),
                tuple(row["bike_entrance"]),
                bool(row["bike"]) or EVERY_STATION_TAKES_A_BIKE,
                tuple(tuple(e) for e in row["entrances"]),
                system.index,
                True,
                bool(row["bike"]),
            )
        )
    # One service per day type, running on its days of the window.
    services = list(schedule.services)
    service_of: dict[str, int] = {}
    for day_type in TYPICAL_DAY_TYPES:
        service_of[day_type] = len(services)
        services.append(
            "".join(
                "1"
                if typical_day_type(schedule.start + timedelta(days=n), doc) == day_type
                else "0"
                for n in range(schedule.days)
            )
        )
    branches: dict[str, list[dict]] = {}
    for service in doc["services"]:
        branches.setdefault(service["line"], []).append(service)
    patterns = list(schedule.patterns)
    for line, found in branches.items():
        trains = {t: typical_departures(doc, line, t) for t in TYPICAL_DAY_TYPES}
        for branch, service in enumerate(found):
            runs = [0]
            for run in service["run_s"]:
                runs.append(runs[-1] + int(run))
            # A line with two services alternates its trains between them (Silver, Yellow).
            trips = {
                service_of[t]: tuple(m * 2 + 1 for m in deps[branch :: len(found)])
                for t, deps in trains.items()
            }
            for order, cumulative in (
                (service["stations"], runs),
                (service["stations"][::-1], [runs[-1] - r for r in runs[::-1]]),
            ):
                patterns.append(
                    Pattern(
                        len(patterns),
                        system.index,
                        f"{line} Line",
                        tuple(index[name] for name in order),
                        tuple(tuple(cumulative) for _band in BANDS),
                        trips,
                    )
                )
    return Schedule(
        [*schedule.systems, system],
        stops,
        patterns,
        services,
        schedule.start,
        schedule.days,
        {**schedule.source, METRO_SYSTEM: {"file": path.name, "typical": True}},
    )


# Fewer days of timetable than this left: a warning in the log, and an alert from
# `manage.py check_operations` (docs/OPERATIONS.md, "Transit schedule": refresh within 45 days).
STALE_DAYS = 7
_warned_on: date | None = None


def days_left(schedule: Schedule, today: date | None = None) -> int:
    """Days of timetable left from `today` (Washington), today included; 0 or less is past.
    Counted to the earliest end of any system's timetable (`Schedule.first_end`)."""
    today = today or datetime.now(ZONE).date()
    return (schedule.first_end[0] - today).days + 1


def _warn_if_stale(schedule: Schedule) -> None:
    """Once a day, a log line when the installed timetables are about to run out."""
    global _warned_on
    today = datetime.now(ZONE).date()
    if _warned_on == today:
        return
    left = days_left(schedule, today)
    if left < STALE_DAYS:
        _warned_on = today
        end, system = schedule.first_end
        logger.warning(
            "the transit schedule runs out %s%s (%d day(s) left): rebuild it"
            " (docs/OPERATIONS.md, 'Transit schedule')",
            end.isoformat(),
            f" ({system.name}'s timetable)" if system is not None else "",
            max(left, 0),
        )


def schedule_alert(path: Path, today: date | None = None) -> str | None:
    """`check_operations`' line for an installed schedule with fewer than `STALE_DAYS` days
    left, or one that cannot be read; None when it is fresh or none is installed (the transit
    ride types are optional, and say so themselves)."""
    if not path.exists():
        return None
    try:
        schedule = _read(path)
    except Unavailable as error:
        return f"transit: {error} ({path})"
    left = days_left(schedule, today)
    if left >= STALE_DAYS:
        return None
    end, system = schedule.first_end
    if system is not None:
        if left <= 0:
            return (
                f"transit: {system.name}'s timetable ran out on {end.isoformat()}; transit plans"
                f" leave {system.name} out until a newer feed is fetched and the schedule rebuilt"
                " (docs/OPERATIONS.md, 'Transit schedule')"
            )
        return (
            f"transit: {system.name}'s timetable runs out on {end.isoformat()}, {left} day(s)"
            " left; fetch a newer feed and rebuild the schedule (docs/OPERATIONS.md,"
            " 'Transit schedule')"
        )
    if left <= 0:
        return (
            f"transit: the schedule ran out on {end.isoformat()}; transit plans"
            " use Metro's typical timetable only until it is rebuilt (docs/OPERATIONS.md,"
            " 'Transit schedule')"
        )
    return (
        f"transit: the schedule runs out on {end.isoformat()}, {left} day(s) left;"
        " rebuild it (docs/OPERATIONS.md, 'Transit schedule')"
    )


# --- Bike blackout dates ---------------------------------------------------------------


@lru_cache(maxsize=4)
def _blackouts(path: Path) -> tuple[frozenset[str], frozenset[str]]:
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError):
        logger.warning("the Metro bike blackout list could not be read: %s", path)
        return frozenset(), frozenset()
    recurring = frozenset(d["date"] for d in doc.get("recurring", []))
    dates = frozenset(d["date"] for d in doc.get("dates", []))
    return recurring, dates


def bike_blackout(day: date, path: Path = BLACKOUTS_PATH) -> bool:
    """Whether `day` is on the list of dates bikes are not allowed on Metro (the owner: bikes
    are allowed "at all times except" these): Metro takes no bike that day."""
    recurring, dates = _blackouts(path)
    return day.strftime("%m-%d") in recurring or day.isoformat() in dates


def blackout_day(moment: Moment) -> date | None:
    """The blackout date a moment falls in, or None: its service day (00:30 on July 5 is
    still July 4's service) or its calendar date (review TB-4)."""
    for day in (moment.service_day, moment.date):
        if bike_blackout(day):
            return day
    return None


# --- When ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Moment:
    service_day: date  # the GTFS service day (the day before, before 3:00 am)
    minute: float  # minutes after the service day's midnight
    date: date  # the calendar date the rider is travelling on
    holiday: bool

    @property
    def day_type(self) -> str:
        weekday = self.service_day.weekday()
        return "weekday" if weekday < 5 else ("saturday" if weekday == 5 else "sunday")

    @property
    def weekend(self) -> bool:
        return self.service_day.weekday() >= 5

    def rush(self, minute: float) -> bool:
        """Weekday rush hour (the `offpeak` bike rule's), on a working weekday."""
        return not self.weekend and not self.holiday and band_index(minute) in RUSH_BANDS


def day_zero(day: date) -> datetime:
    """GTFS's 00:00:00 of a service day: noon local time less 12 hours (the GTFS reference), in
    UTC, so a time is real elapsed time across a daylight-saving change (2026-11-01 has 25 hours
    and its 08:00 is still 8 am)."""
    noon = datetime(day.year, day.month, day.day, 12, tzinfo=ZONE)
    return noon.astimezone(UTC) - timedelta(hours=12)


def _moment(when: datetime, service_day: date) -> Moment:
    minute = (when.astimezone(UTC) - day_zero(service_day)).total_seconds() / 60.0
    holiday = is_federal_holiday(service_day)
    return Moment(service_day, minute, when.astimezone(ZONE).date(), holiday)


def moment_of(when: datetime) -> Moment:
    """The service day a time belongs to (before 3:00 am, the day before) and its minute."""
    local = when.astimezone(ZONE)
    service_day = local.date()
    if local.hour * 60 + local.minute < DAY_START_MIN:
        service_day -= timedelta(days=1)
    return _moment(when, service_day)


# Between these local minutes a trip may be on either service day: the day before's owl trips
# (GTFS times past 24:00, even past 27:00) and the new day's first trips. Both are searched.
BOTH_DAYS = (60, 300)


def moments_of(when: datetime) -> list[Moment]:
    """The moment on its service day, then, around 1 to 5 am, on the other one too."""
    first = moment_of(when)
    local = when.astimezone(ZONE)
    if not BOTH_DAYS[0] <= local.hour * 60 + local.minute < BOTH_DAYS[1]:
        return [first]
    other = local.date() if first.service_day != local.date() else local.date() - timedelta(days=1)
    return [first, _moment(when, other)]


def clock(minute: float, service_day: date | None = None) -> str:
    """A service-day minute as a clock: "7:42 am". With its service day, the wall-clock time
    (as `_local`), so a daylight-saving night says the time the station clock shows; without
    one, the minute read as a plain day (tests and day-free notes)."""
    if service_day is not None:
        at = (day_zero(service_day) + timedelta(minutes=round(minute))).astimezone(ZONE)
        total = at.hour * 60 + at.minute
    else:
        total = int(round(minute)) % 1440
    hour, mins = divmod(total, 60)
    suffix = "am" if hour < 12 else "pm"
    return f"{(hour % 12) or 12}:{mins:02d} {suffix}"


# --- Legs and words ----------------------------------------------------------------------


def _distance(a, b) -> float:
    return haversine(Point(a[0], a[1]), Point(b[0], b[1]))


def walk_s(a, b) -> float:
    return _distance(a, b) * DETOUR / (WALK_SPEED_KMH / 3.6)


def ride_s(a, b, speed_kmh: float) -> float:
    return _distance(a, b) * DETOUR / (speed_kmh / 3.6)


def minutes(seconds: float) -> int:
    return max(1, round(seconds / 60))


def miles(metres: float) -> str:
    return f"{metres / bikeshare.METRES_PER_MILE:.0f} mi ({metres / 1000:.0f} km)"


def _pt(point) -> list[float]:
    return [round(point[0], 6), round(point[1], 6)]


@dataclass(frozen=True)
class Leg:
    mode: str
    seconds: float
    coordinates: tuple[tuple[float, float], ...] = ()
    to: str | None = None  # a place's name; None: the destination, or no name
    lines: tuple[str, ...] = ()
    wait_s: float = 0.0
    change: bool = False  # a transit leg after a change at the same station
    bike: bool = False  # with your own bike (the elevator, on board, the rack)
    estimated: bool = False  # a ride timed from the straight line, not the router
    system: str = ""  # a transit leg's system: "Metro", "MARC"
    vehicle: str = ""  # a transit leg's vehicle in words: "the MARC Penn Line", "bus B10"
    depart: float | None = None  # an infrequent service: the departure taken
    after: float | None = None  # and the one after it
    later: tuple[float, ...] = ()  # the departures after `depart` that were seen, in order
    board_at: str | None = None  # a transit leg's first stop, by name
    service_day: date | None = None  # a transit leg's service day, for its clock times
    every: float | None = None  # a frequent service: minutes between departures
    first: float | None = None  # typical Metro before its first train: that train
    live: bool = False  # `depart` and `later` are WMATA's predictions (core.transit_live)
    elevator: bool = True  # a station's way in or out with the bike is a known elevator
    elevator_out: bool = False  # and every one is out (the option's row shows it)
    # A ride's time on busy roads and waiting at junctions, added again for ranking only
    # (`Option.score_s`), and its metres on busy roads, said with the option (`busy_m`).
    penalty_s: float = 0.0
    busy_m: float | None = None

    @property
    def total_s(self) -> float:
        return self.seconds + self.wait_s

    @property
    def source(self) -> str:
        """The word said after the step's departure times: "live" or "scheduled"."""
        return LIVE if self.live else SCHEDULED

    @property
    def arrive(self) -> float | None:
        """An infrequent service: when the rider reaches the stop (service-day minutes)."""
        return None if self.depart is None else self.depart - self.wait_s / 60.0

    @property
    def transit(self) -> bool:
        return self.mode in TRANSIT_MODES

    def _source_said(self) -> str:
        """`source` in a sentence, in the language in force ("scheduled", "live")."""
        return t("live") if self.live else t("scheduled")

    def _after_words(self) -> str:
        if self.after is None:
            if self.mode == BUS:
                return t("no later bus within the hour")
            return t("no later train within the hour")
        time = clock(self.after, self.service_day)
        if self.mode == BUS:
            return t("next bus after that: {time} {source}", time=time, source=self._source_said())
        return t("next train after that: {time} {source}", time=time, source=self._source_said())

    def _vehicle_said(self) -> str:
        """The vehicle as a sentence names it: the schedule's words in English ("the MARC Penn
        Line", "bus B10"); in Spanish the line's name after its noun ("tren MARC Penn Line",
        "autobús B10"), the names as they are (routing audit D30)."""
        if not spanish():
            return self.vehicle
        name = self.vehicle.removeprefix("the ").replace(" or ", t(" or "))
        if self.mode == BUS:
            return t("bus {name}", name=name.removeprefix("bus "))
        return t("train {name}", name=name)

    def words(self, last: bool = False) -> str:
        """The step as one sentence, in the language in force (`routemaker.lang`; routing
        audit D30). English is as it always was."""
        m = minutes(self.seconds)
        to = self.to or (t("your destination") if last else None)
        if self.mode == RIDE:
            return t("Ride {m} min to {place}.", m=m, place=to) if to else t("Ride {m} min.", m=m)
        if self.mode == TAKE:
            return t(
                "Walk {m} min to the bikeshare dock at {place} and take a classic bike.",
                m=m,
                place=self.to,
            )
        if self.mode == SHARE:
            return t("Ride the bikeshare bike {m} min and dock it at {place}.", m=m, place=self.to)
        if self.mode == WALK:
            return t("Walk {m} min to {place}.", m=m, place=to) if to else t("Walk {m} min.", m=m)
        lift = self.bike and self.elevator
        if self.mode == ENTER:
            if lift:
                return t("About {m} min into the station by the elevator.", m=m)
            return t("About {m} min into the station.", m=m)
        if self.mode == EXIT:
            if lift:
                return t("About {m} min out of the station by the elevator.", m=m)
            return t("About {m} min out of the station.", m=m)
        vehicle = self._vehicle_said()
        if self.mode == BUS and self.bike:
            board = t("Put your bike on the front rack of {vehicle}", vehicle=vehicle)
        elif self.change:
            board = t("Change to {vehicle}", vehicle=vehicle)
        else:
            board = t("Board {vehicle}", vehicle=vehicle)
        # The time on board, after the boarding ("ride 10 min to Federal Triangle"): a transit
        # ride, worded apart from a bike ride's "Ride 10 min to ..." above.
        ride = t("ride {m} min to {place}", m=m, place=to) if to else t("ride {m} min", m=m)
        if self.depart is None:
            wait = t("about {m} min wait", m=minutes(self.wait_s))
            source = t("scheduled")
            if self.first is not None:
                # Before opening (#111's review): the first train, not the interval after it.
                return t(
                    "{board} (first train {time} {source}; {wait}); {ride}.",
                    board=board,
                    time=clock(self.first, self.service_day),
                    source=source,
                    wait=wait,
                    ride=ride,
                )
            if self.every is None:
                return t(
                    "{board} ({wait}, {source}); {ride}.",
                    board=board,
                    wait=wait,
                    source=source,
                    ride=ride,
                )
            return t(
                "{board} (every {n} min, {source}; {wait}); {ride}.",
                board=board,
                n=max(1, round(self.every)),
                source=source,
                wait=wait,
                ride=ride,
            )
        # An infrequent service (the owner, 2026-10-12): the departure, when the rider gets
        # there and the time to spare, and the one after it. The app takes the "you arrive"
        # clause out once riding (frontend/src/lib/rideTrip.ts withoutSpare, in both languages).
        place = t(" from {place}", place=self.board_at) if self.board_at else ""
        head = t(
            "{board} at {time} {source}{from}",
            board=board,
            time=clock(self.depart, self.service_day),
            source=self._source_said(),
            **{"from": place},
        )
        return t(
            "{head}: you arrive {time}, {spare} min spare; {after}. {ride}.",
            head=head,
            time=clock(self.arrive, self.service_day),
            spare=round(self.wait_s / 60),
            after=self._after_words(),
            ride=ride[:1].upper() + ride[1:],
        )


def _total(legs) -> float:
    return sum(leg.total_s for leg in legs)


def _nearest_entrance(stop: Stop, point) -> tuple[float, float]:
    candidates = stop.entrances or (stop.point,)
    return min(candidates, key=lambda e: _distance(point, e))


# --- Departures and reach ----------------------------------------------------------------


class _Day:
    """One plan's view of the schedule: the moment, the services running, the bike rule."""

    def __init__(self, schedule: Schedule, moment: Moment, bike: bool) -> None:
        self.schedule = schedule
        self.moment = moment
        self.bike = bike
        self.active = schedule.active(moment.service_day)
        self._cache: dict[tuple, dict[int, Hop]] = {}
        # A blackout date: no bike on Metro at all (a rider on foot still rides it).
        self.blackout_day = blackout_day(moment) if bike else None
        self.blackout = self.blackout_day is not None
        # How a ride with no trace is priced (`priced`): as the whole ride is.
        self.pricing = UNPRICED

    def boards(self, pattern: Pattern, minute: float, encoded: int) -> bool:
        if not self.bike:
            return True
        system = self.schedule.systems[pattern.system]
        if self.blackout and system.id == METRO_SYSTEM:
            return False
        rule = system.vehicle
        if rule == "none" or not encoded & 1:
            return False
        return not (rule == "offpeak" and self.moment.rush(minute))

    def departures(self, pattern: Pattern, pos: int, minute: float) -> list[float]:
        """The next `DEPARTURES_SEEN` departures of `pattern` from its stop `pos` at or after
        `minute` (enough to tell a frequent service from a near pair). Each trip is timed with
        the run times of its own band (the band it starts in), as the station card's are
        (`_departures_at`), so a trip that started before a band edge keeps its own times."""
        return [at for at, _start in self.trips_from(pattern, pos, minute)]

    def trips_from(self, pattern: Pattern, pos: int, minute: float) -> list[tuple[float, int]]:
        """`departures`, each with its trip's start minute (whose band times the rest of it)."""
        found: list[tuple[float, int]] = []
        reach = [runs[pos] / 60.0 for runs in pattern.runs if runs is not None]
        if not reach:
            reach = [pattern.runs_at(minute)[pos] / 60.0]
        # A trip started this long before `minute` may still be on its way to the stop.
        low = math.ceil(minute - max(reach) - 1e-9) * 2
        soonest = min(reach)
        offsets: dict[int | None, float] = {}
        for service, deps in pattern.trips.items():
            if service not in self.active:
                continue
            taken = 0
            for encoded in deps[bisect_left(deps, low) :]:
                start = encoded >> 1
                # far enough for a missed one's next two, whichever band times it
                if start + soonest - minute > MAX_WAIT_MIN * 3:
                    break
                band = band_index(start)
                if band not in offsets:
                    offsets[band] = pattern.runs_at(start)[pos] / 60.0
                at = start + offsets[band]
                if at - minute > MAX_WAIT_MIN * 3:
                    continue
                if at < minute or not self.boards(pattern, at, encoded):
                    continue
                found.append((at, start))
                taken += 1
                if taken == DEPARTURES_SEEN:
                    break
        return sorted(found)[:DEPARTURES_SEEN]

    def reach(self, stop: int, minute: float, patterns=None, targets=None) -> dict[int, Hop]:
        """Every stop one ride from `stop` leaving at or after `minute`, with its wait and ride
        (`patterns` and `targets` narrow it: the second leg's search)."""
        key = (stop, round(minute, 1), id(patterns), id(targets))
        if key in self._cache:
            return self._cache[key]
        schedule = self.schedule
        # to -> [(departures, ride s, pattern, pos, later)]
        groups: dict[int, list] = {}
        for p_index, pos in schedule.at_stop.get(stop, ()):
            if patterns is not None and p_index not in patterns:
                continue
            pattern = schedule.patterns[p_index]
            trips = self.trips_from(pattern, pos, minute)
            if not trips or trips[0][0] - minute > MAX_WAIT_MIN:
                continue
            deps = [at for at, _start in trips]
            # The ride by the first trip's own band, as its departure is: down the line it
            # arrives when the station card says it leaves there.
            runs = pattern.runs_at(trips[0][1])
            for later in range(pos + 1, len(pattern.stops)):
                to = pattern.stops[later]
                if to == stop or (targets is not None and to not in targets):
                    continue
                if self.bike and not schedule.stops[to].bike:
                    continue
                ride = float(max(0, runs[later] - runs[pos]))
                groups.setdefault(to, []).append((deps, ride, pattern, pos, later))
        out = {
            to: _hop(minute, entries, schedule.systems[schedule.stops[to].system].typical)
            for to, entries in groups.items()
        }
        self._cache[key] = out
        return out


# How many departures decide whether a service is frequent: every gap between them must be at
# most `FREQUENT_MIN`, so a near pair before a long gap is not taken for a frequent service.
DEPARTURES_SEEN = 4
FREQUENT_SEEN = 3


def _distinct(times) -> list[float]:
    """The departures in order, two within half a minute counted once."""
    distinct: list[float] = []
    for dep in sorted(times):
        if not distinct or dep - distinct[-1] >= 0.5:
            distinct.append(dep)
    return distinct


def headway(times) -> float:
    """The mean gap between the next departures when every gap is at most `FREQUENT_MIN` over
    at least `FREQUENT_SEEN` of them (two patterns leaving the same minute count once); else
    infinity: the service is not frequent, and the actual next departure is waited for."""
    seen = _distinct(times)[:DEPARTURES_SEEN]
    if len(seen) < FREQUENT_SEEN:
        return math.inf
    gaps = [b - a for a, b in zip(seen, seen[1:], strict=False)]
    if max(gaps) > FREQUENT_MIN:
        return math.inf
    return sum(gaps) / len(gaps)


def typical_wait_min(minute: float, times) -> tuple[float, float | None]:
    """The wait on Metro's typical timetable, and the minutes between its trains: half the
    interval (the mean gap of the next few), or, before the first train or for the last, the
    time until it (the interval None for the last)."""
    seen = _distinct(times)[:DEPARTURES_SEEN]
    every = (seen[-1] - seen[0]) / (len(seen) - 1) if len(seen) > 1 else math.inf
    until = seen[0] - minute
    wait = until if len(seen) == 1 or until > every else every / 2.0
    return wait, None if math.isinf(every) else every


def typical_first(minute: float, times) -> float | None:
    """Before the first train (the wait to it longer than the interval after it): that train's
    minute, which the step names in place of the interval; else None."""
    seen = _distinct(times)[:DEPARTURES_SEEN]
    if len(seen) < 2:
        return None
    every = (seen[-1] - seen[0]) / (len(seen) - 1)
    return seen[0] if seen[0] - minute > every else None


def _hop(minute: float, entries, typical: bool = False) -> Hop:
    """The ride to one stop from the patterns that go there: the earliest arrival taken. On
    Metro's typical timetable the wait is always `typical_wait_min`, never a departure."""
    times = sorted(t for deps, *_rest in entries for t in deps)
    first = min(entries, key=lambda e: (e[0][0] + e[1] / 60.0, e[2].index))
    deps, ride, pattern, pos, later = first
    path = pattern.stops[pos : later + 1]
    every = headway(times)
    if typical or every <= FREQUENT_MIN:
        routes = tuple(sorted({e[2].route for e in entries}))
        ride = min(e[1] for e in entries)
        wait, gap = typical_wait_min(minute, times) if typical else (every / 2.0, every)
        first = typical_first(minute, times) if typical else None
        return Hop(
            wait * 60.0,
            ride,
            routes,
            path,
            pattern.system,
            pattern.index,
            True,
            every=gap,
            first=first,
        )
    later_times = []
    for dep in times:
        if dep >= (later_times[-1] if later_times else deps[0]) + 0.5:
            later_times.append(dep)
    return Hop(
        (deps[0] - minute) * 60.0,
        ride,
        (pattern.route,),
        path,
        pattern.system,
        pattern.index,
        False,
        deps[0],
        later_times[0] if later_times else None,
        tuple(later_times),
    )


def _transit_leg(
    schedule: Schedule, hop: Hop, change: bool, bike: bool, service_day: date | None = None
) -> Leg:
    system = schedule.systems[hop.system]
    to = schedule.stops[hop.path[-1]]
    return Leg(
        system.mode,
        hop.ride_s + (TRANSFER_S if change else 0.0),
        tuple(schedule.stops[s].point for s in hop.path),
        schedule.place(to),
        hop.routes,
        hop.wait_s,
        change=change,
        bike=bike,
        system=system.name,
        vehicle=system.vehicle_words(hop.routes),
        depart=hop.depart,
        after=hop.after,
        later=hop.later,
        board_at=schedule.place(schedule.stops[hop.path[0]]),
        service_day=service_day,
        every=hop.every,
        first=hop.first,
    )


# --- The router, for own-bike legs ---------------------------------------------------------


@dataclass(frozen=True)
class Ride:
    seconds: float
    coordinates: tuple[tuple[float, float], ...]
    metres: float | None = None  # the routed length, where the router gave it
    # Its metres on busy roads (LTS 3 and up), where its trace was read; its junction waits
    # are in `seconds` then, as the answer's line has them (routing.plan).
    busy_m: float | None = None
    waits_s: float = 0.0


class Services(Protocol):
    def ride(self, a: LonLat, b: LonLat) -> Ride | None:
        """A bike route between two points (time and line), or None where there is none."""

    def walk(self, a: LonLat, b: LonLat) -> Ride | None:
        """A walk between two points (time and line), or None where there is none."""


# One router call for a candidate leg may take at most this long; the search as a whole stops
# routing at `until` (the API keeps the rest of the request's budget for the answer's own line).
CANDIDATE_CALL_S = 5.0


class RoutingServices:
    """Valhalla's bicycle costing on the standard graph, with the ride type's own options:
    one cheap call per leg, no trace (the answer's own line is `routing.plan`'s).

    Never fatal: a refusal, a router that does not answer, a call past its cap or past the
    search's budget, or a call beyond `max_calls`, is None, and the leg is estimated from the
    straight line instead. The direct ride is asked first (plan_bike), so it has the budget."""

    def __init__(
        self,
        until: float,
        preset_name: str,
        *,
        max_calls: int | None = None,
        per_call_s: float = CANDIDATE_CALL_S,
        costing: dict | None = None,
        when: str | None = None,
    ) -> None:
        self._until = until
        # The ride time setting the busy roads are read at; None: rides are not traced.
        self._when = when
        self._preset = preset_name
        # The bike legs' costing where it is not the preset's own (Novice and Nervous's
        # Bikeshare + Transit: its pricing at the share bike's pace).
        self._costing = costing
        self._max_calls = MAX_ROUTER_CALLS if max_calls is None else max_calls
        self._per_call_s = per_call_s
        self.calls = 0
        self.spent_s = 0.0  # time in router calls, for the API's log of its phases

    def ride(self, a: LonLat, b: LonLat) -> Ride | None:
        return self._route(a, b, "bicycle", self._costing or presets.costing(self._preset))

    def walk(self, a: LonLat, b: LonLat) -> Ride | None:
        """On foot, as the bikeshare planner walks (Valhalla's pedestrian costing at 3 mph)."""
        return self._route(
            a, b, "pedestrian", {"pedestrian": {"walking_speed": bikeshare.WALK_SPEED_KMH}}
        )

    def _route(self, a: LonLat, b: LonLat, costing: str, options: dict) -> Ride | None:
        from . import routing

        if _distance(a, b) < 5.0:
            return Ride(0.0, (tuple(a), tuple(b)))
        if self.calls >= self._max_calls:
            return None
        now = routing.clock()
        left = self._until - now
        if left <= 0:
            return None
        self.calls += 1
        cap = min(left, self._per_call_s)
        deadline = routing.Deadline(now + cap, cap)
        payload = {
            "locations": [{"lon": p[0], "lat": p[1], "type": "break"} for p in (a, b)],
            "costing": costing,
            "costing_options": options,
            "directions_type": "none",
            "units": "kilometers",
        }
        try:
            answer = routing._call("standard", "route", payload, deadline)
        except (routing.RouterRefused, routing.RouterUnavailable, routing.DeadlineExceeded):
            return None
        finally:
            self.spent_s += routing.clock() - now
        legs = (answer.get("trip") or {}).get("legs") or []
        if not legs:
            return None
        shape = tuple(tuple(p) for p in routing.decode_polyline6(legs[0].get("shape", "")))
        summary = legs[0].get("summary") or {}
        length = summary.get("length")
        seconds = float(summary.get("time", 0.0))
        metres = None if length is None else float(length) * 1000.0
        if costing != "bicycle" or self._when is None:
            return Ride(seconds, shape, metres)
        # Its busy roads and junction waits, from its trace, inside the same call's cap.
        traced_at = routing.clock()
        try:
            measured = routing.busy_and_waits(
                "standard", options, legs[0].get("shape", ""), self._when, deadline
            )
        except (routing.RouterUnavailable, routing.DeadlineExceeded):
            measured = None
        finally:
            self.spent_s += routing.clock() - traced_at
        if measured is None:
            return Ride(seconds, shape, metres)
        busy, waits = measured
        return Ride(seconds + waits, shape, metres, busy, waits)


# --- Busy roads: the ranking's penalty (Stephen, 2026-10-21) --------------------------------

# Stephen, 2026-10-21: "We should order by time to get there with a penalty for time taken on
# busy roads and intersections", and each option says it: "arrive in X min with x mi of busy
# roads". A ride's time on busy roads (LTS 3 and up) and its waits at junctions count twice in
# the ranking (`Option.score_s`); the times shown stay the times.
BUSY_WEIGHT = 1.0
WAITS_WEIGHT = 1.0


@dataclass(frozen=True)
class Pricing:
    """How a ride with no trace is priced: as the whole ride is, where it was traced. `share`
    is the penalty a second of riding; `busy_per_m` its busy metres a metre (None: unknown)."""

    share: float = 0.0
    busy_per_m: float | None = None


# A ride with no trace and no traced whole ride to price it by: no penalty, its busy roads unknown.
UNPRICED = Pricing()


def pricing_of(ride: Ride | None) -> Pricing:
    if ride is None or ride.busy_m is None or not ride.metres or ride.seconds <= 0:
        return UNPRICED
    penalty = _penalty_s(ride)
    return Pricing(penalty / ride.seconds, min(ride.busy_m / ride.metres, 1.0))


def _penalty_s(ride: Ride) -> float:
    moving = max(ride.seconds - ride.waits_s, 0.0)
    busy_s = moving * min((ride.busy_m or 0.0) / ride.metres, 1.0) if ride.metres else 0.0
    return BUSY_WEIGHT * busy_s + WAITS_WEIGHT * ride.waits_s


def priced(ride: Ride | None, seconds: float, line_m: float, pricing: Pricing):
    """(penalty seconds, busy metres or None) for a ride: its own where it was traced, else as
    `pricing` prices one of `seconds` and `line_m`."""
    if ride is not None and ride.busy_m is not None and ride.metres:
        return _penalty_s(ride), ride.busy_m
    busy = None if pricing.busy_per_m is None else pricing.busy_per_m * line_m
    return seconds * pricing.share, busy


# --- Ends: how a trip reaches a stop, or leaves one -----------------------------------------


@dataclass
class _End:
    stop: int
    legs: list[Leg]
    key: str = ""  # how the option's key names this end

    @property
    def seconds(self) -> float:
        return _total(self.legs)


def _best_few(ends, count: int) -> list[_End]:
    return sorted((e for e in ends if e is not None), key=lambda e: e.seconds)[:count]


def _quicker(*ends: _End | None) -> _End | None:
    found = [e for e in ends if e is not None]
    return min(found, key=lambda e: e.seconds) if found else None


def _candidates(schedule: Schedule, point, bike: bool, rail_m: float, bus_m: float):
    """The stops tried at one end: the nearest stations (routed first), the nearest of every
    rail system, and the nearest bus stops. Returns (nearest stations, the rest)."""
    rail, others, per_system, buses = [], [], {}, []
    for distance, stop in schedule.near(point, max(rail_m, bus_m)):
        if bike and not stop.bike:
            continue
        if not schedule.at_stop.get(stop.index):
            continue
        if stop.rail and distance <= rail_m:
            if len(rail) < STATION_CANDIDATES:
                rail.append(stop)
            elif per_system.get(stop.system, 0) < PER_SYSTEM:
                others.append(stop)
            per_system[stop.system] = per_system.get(stop.system, 0) + 1
        elif not stop.rail and distance <= bus_m and len(buses) < BUS_STOPS_NEAR:
            buses.append(stop)
    return rail, others + buses


def _station_leg(mode: str, stop: Stop) -> Leg:
    """Into (ENTER) or out of (EXIT) a station with your own bike: by its elevator, ranked
    ranked `Stop.elevator_out_s` down where every one is out."""
    return Leg(
        mode,
        ACCESS_BIKE_S,
        bike=True,
        elevator=stop.elevator,
        penalty_s=stop.elevator_out_s,
        elevator_out=stop.elevator_out_s > 0,
    )


def _line_m(ride: Ride) -> float:
    """A ride's length: the router's, else its straight line's with the usual detour."""
    if ride.metres is not None:
        return ride.metres
    return (
        _distance(ride.coordinates[0], ride.coordinates[-1]) * DETOUR if ride.coordinates else 0.0
    )


def _ride_to(
    schedule: Schedule,
    start,
    stop: Stop,
    ride: Ride | None,
    speed: float,
    pricing: Pricing = UNPRICED,
) -> _End:
    """Ride your own bike to a stop (and, a station, in by the elevator)."""
    to = stop.bike_entrance
    routed = ride
    if ride is None:
        ride = Ride(ride_s(start, to, speed), (tuple(start), to))
        estimated = True
    else:
        estimated = False
    penalty, busy = priced(routed, ride.seconds, _line_m(ride), pricing)
    legs = [
        Leg(
            RIDE,
            ride.seconds,
            ride.coordinates,
            schedule.place(stop),
            estimated=estimated,
            penalty_s=penalty,
            busy_m=busy,
        )
    ]
    if stop.rail:
        legs.append(_station_leg(ENTER, stop))
    return _End(stop.index, legs, f"a{stop.index}")


def _ride_from(
    schedule: Schedule,
    end,
    stop: Stop,
    ride: Ride | None,
    speed: float,
    pricing: Pricing = UNPRICED,
) -> _End:
    start = stop.bike_entrance
    routed = ride
    if ride is None:
        ride = Ride(ride_s(start, end, speed), (start, tuple(end)))
        estimated = True
    else:
        estimated = False
    penalty, busy = priced(routed, ride.seconds, _line_m(ride), pricing)
    legs = [_station_leg(EXIT, stop)] if stop.rail else []
    legs.append(
        Leg(
            RIDE,
            ride.seconds,
            ride.coordinates,
            estimated=estimated,
            penalty_s=penalty,
            busy_m=busy,
        )
    )
    return _End(stop.index, legs, f"e{stop.index}")


def _walk_to(schedule: Schedule, stop: Stop, point) -> _End | None:
    """Walk from the start to the stop (and into the station)."""
    entrance = _nearest_entrance(stop, point)
    if _distance(point, entrance) > (WALK_TO_STATION_M if stop.rail else WALK_TO_STOP_M):
        return None
    legs = [Leg(WALK, walk_s(point, entrance), (tuple(point), entrance), schedule.place(stop))]
    if stop.rail:
        legs.append(Leg(ENTER, ACCESS_WALK_S))
    return _End(stop.index, legs, f"a{stop.index}")


def _walk_from(schedule: Schedule, stop: Stop, point) -> _End | None:
    """Out of the station (or off the bus) and walk to the destination."""
    entrance = _nearest_entrance(stop, point)
    if _distance(point, entrance) > (WALK_TO_STATION_M if stop.rail else WALK_TO_STOP_M):
        return None
    legs = [Leg(EXIT, ACCESS_WALK_S)] if stop.rail else []
    legs.append(Leg(WALK, walk_s(entrance, point), (entrance, tuple(point))))
    return _End(stop.index, legs, f"e{stop.index}")


def _dock_ok(pick: bikeshare.Pick, snapshot: gbfs.Snapshot, taking: bool) -> bool:
    if taking:
        return bikeshare._can_start(pick, presets.BIKE_CLASSIC, snapshot)
    return bikeshare._can_end(pick, snapshot)


def _nearest_dock(snapshot: gbfs.Snapshot, point, limit_m: float, taking: bool):
    near = sorted(
        (
            (_distance(point, [s.lon, s.lat]), s)
            for s in snapshot.stations
            if abs(s.lat - point[1]) < 0.02 and abs(s.lon - point[0]) < 0.03
        ),
        key=lambda t: (t[0], t[1].name),
    )
    for distance, station in near:
        if distance > limit_m:
            break
        pick = bikeshare._dock_pick(station, snapshot)
        if not pick.stale and _dock_ok(pick, snapshot, taking):
            return pick
    return None


def _share_legs(before, after, pickup, dropoff, to_name: str | None) -> list[Leg]:
    pick_xy, drop_xy = tuple(pickup.point), tuple(dropoff.point)
    return [
        Leg(TAKE, walk_s(before, pick_xy), (tuple(before), pick_xy), pickup.name),
        Leg(
            SHARE,
            ride_s(pick_xy, drop_xy, BIKESHARE_SPEED_KMH),
            (pick_xy, drop_xy),
            dropoff.name,
            estimated=True,
        ),
        # Docked before boarding (the owner, 2026-10-12): the walk on from the dock counts.
        Leg(WALK, walk_s(drop_xy, after), (drop_xy, tuple(after)), to_name),
    ]


def _share_to(schedule: Schedule, stop: Stop, start, snapshot: gbfs.Snapshot) -> _End | None:
    """Walk to a dock with a classic bike, ride to a dock beside the station, walk in."""
    entrance = _nearest_entrance(stop, start)
    pickup = _nearest_dock(snapshot, start, DOCK_NEAR_M, taking=True)
    dropoff = _nearest_dock(snapshot, entrance, DOCK_AT_STATION_M, taking=False)
    if pickup is None or dropoff is None or pickup.station_id == dropoff.station_id:
        return None
    legs = _share_legs(start, entrance, pickup, dropoff, schedule.place(stop))
    if stop.rail:
        legs.append(Leg(ENTER, ACCESS_WALK_S))
    return _End(stop.index, legs, f"a{stop.index}")


def _share_from(schedule: Schedule, stop: Stop, end, snapshot: gbfs.Snapshot) -> _End | None:
    """Out of the station, a new bike from a dock beside it to a dock near the destination."""
    entrance = _nearest_entrance(stop, end)
    pickup = _nearest_dock(snapshot, entrance, DOCK_AT_STATION_M, taking=True)
    dropoff = _nearest_dock(snapshot, end, DOCK_NEAR_M, taking=False)
    if pickup is None or dropoff is None or pickup.station_id == dropoff.station_id:
        return None
    legs = [Leg(EXIT, ACCESS_WALK_S)] if stop.rail else []
    return _End(
        stop.index, legs + _share_legs(entrance, end, pickup, dropoff, None), f"e{stop.index}"
    )


# --- Options --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Option:
    """One way to make the trip. `key` names it to the API (`transit_option`); `direct` is
    riding the whole way (the plain bike route, or bikeshare dock to dock); `walk` is walking
    the whole way."""

    key: str
    legs: tuple[Leg, ...]
    direct: bool = False
    walk: bool = False  # walking the whole way (Bikeshare + 🚶🚆🚌)
    # Novice and Nervous's hop past the busy stretch (`HOP_NEAR_M`): boards near where it
    # begins and gets off near where it ends.
    hop: bool = False
    # Found on the other service day (around 1 to 5 am): that day's moment; else the plan's.
    moment: Moment | None = None

    @property
    def total_s(self) -> float:
        return _total(self.legs)

    @property
    def score_s(self) -> float:
        """What the options are ranked by: the time door to door, and each ride's busy roads and
        junctions on top (`penalty_s`; Stephen, 2026-10-21)."""
        return self.total_s + sum(leg.penalty_s for leg in self.legs)

    @property
    def busy_m(self) -> float | None:
        """Its rides' metres on busy roads; None where any ride's are not known."""
        rides = [leg.busy_m for leg in self.legs if leg.mode in (RIDE, SHARE)]
        if not rides or any(m is None for m in rides):
            return None if rides else 0.0
        return float(sum(rides))

    @property
    def ride(self) -> int:
        """The leg the answer's route line is: the first ride, else the first walk, of at least
        `MIN_LINE_M` (a walk of a few yards from a dock to a stop has no route to draw)."""
        for modes in ((RIDE, SHARE), (WALK, TAKE)):
            for index, leg in enumerate(self.legs):
                if leg.mode in modes and line_m(leg) >= MIN_LINE_M:
                    return index
        for index, leg in enumerate(self.legs):
            if leg.mode in (RIDE, SHARE, WALK, TAKE):
                return index
        return 0

    @property
    def signature(self) -> tuple:
        """What sets an option apart for the rider: its kind and its routes, in order."""
        return (self.direct, tuple((leg.system, leg.lines) for leg in self.legs if leg.transit))

    @property
    def scheduled(self) -> bool:
        """Any leg on transit: its times are scheduled."""
        return any(leg.transit for leg in self.legs)


# A leg shorter than this end to end is not routed as the answer's line (the router answers
# NoRoute for two points a few yards apart).
MIN_LINE_M = 20.0


def line_m(leg: Leg) -> float:
    """A leg's ends, how far apart in a straight line (0 for a leg with no line)."""
    if len(leg.coordinates) < 2:
        return 0.0
    return _distance(leg.coordinates[0], leg.coordinates[-1])


def _transfer(day: _Day, a: Stop, b: Stop, speed: float) -> tuple[list[Leg], float]:
    """From one transit leg's last stop to the next one's first: the same station (a change
    of line), or out, along the street (ridden, with your own bike) and in."""
    if a.index == b.index:
        return [], TRANSFER_S
    bike = day.bike
    legs = []
    if a.rail:
        legs.append(_station_leg(EXIT, a) if bike else Leg(EXIT, ACCESS_WALK_S))
    start = _nearest_entrance(a, b.point)
    end = b.bike_entrance if bike else _nearest_entrance(b, start)
    place = day.schedule.place(b)
    if bike:
        seconds = ride_s(start, end, speed)
        penalty, busy = priced(None, seconds, _distance(start, end) * DETOUR, day.pricing)
        legs.append(
            Leg(
                RIDE,
                seconds,
                (start, end),
                place,
                estimated=True,
                penalty_s=penalty,
                busy_m=busy,
            )
        )
    else:
        legs.append(Leg(WALK, walk_s(start, end), (start, end), place))
    if b.rail:
        legs.append(_station_leg(ENTER, b) if bike else Leg(ENTER, ACCESS_WALK_S))
    return legs, _total(legs)


def _search(day: _Day, starts: list[_End], ends: dict[int, _End], speed: float) -> list[Option]:
    """Every start, one or two transit legs (`MAX_LEGS`), and an end."""
    schedule = day.schedule
    # The patterns that reach an end, and the stops a second leg may board them at.
    end_patterns: dict[int, int] = {}
    for stop in ends:
        for p_index, pos in schedule.at_stop.get(stop, ()):
            end_patterns[p_index] = max(end_patterns.get(p_index, 0), pos)
    boardable = {
        stop
        for p_index, last in end_patterns.items()
        for stop in schedule.patterns[p_index].stops[:last]
    }
    targets = frozenset(ends)
    narrowed = frozenset(end_patterns)
    found: list[Option] = []
    for start in starts:
        at = day.moment.minute + start.seconds / 60.0
        for stop, hop in day.reach(start.stop, at).items():
            first = _transit_leg(schedule, hop, False, day.bike, day.moment.service_day)
            legs = start.legs + [first]
            arrive = at + hop.total_s / 60.0
            key = f"{start.key}>p{hop.pattern}"
            if stop in ends:
                found.append(Option(f"{key}>{ends[stop].key}", tuple(legs + ends[stop].legs)))
            if MAX_LEGS < 2:
                continue
            here = schedule.stops[stop]
            for _distance_m, next_stop in schedule.near(here.point, TRANSFER_M):
                if next_stop.index not in boardable or (day.bike and not next_stop.bike):
                    continue
                between, seconds = _transfer(day, here, next_stop, speed)
                second_hops = day.reach(next_stop.index, arrive + seconds / 60.0, narrowed, targets)
                for to, second in second_hops.items():
                    if second.system == hop.system and set(second.routes) <= set(hop.routes):
                        continue  # the same line on: no change
                    change = next_stop.index == stop
                    leg = _transit_leg(schedule, second, change, day.bike, day.moment.service_day)
                    found.append(
                        Option(
                            f"{key}-s{next_stop.index}>p{second.pattern}>{ends[to].key}",
                            tuple(legs + between + [leg] + ends[to].legs),
                        )
                    )
    return found


def rank_key(option: Option, extra_s: float = 0.0) -> tuple:
    """The options' order: the time door to door with the rides' busy roads and junctions on top
    (`Option.score_s`), to the minute, then (the same train) the simpler trip, with fewer transit
    legs. `extra_s` is a ranking cost on top (core.transit_live's elevator out)."""
    score = option.score_s + extra_s
    return (minutes(score), sum(leg.transit for leg in option.legs), score, option.key)


def _ranked(
    direct: Option | None,
    transit: list[Option],
    walk: Option | None = None,
    hops: list[Option] | None = None,
) -> list[Option]:
    """The direct ride always (and walking the whole way, where it is offered), then the best
    of each kind of transit trip (one per signature), up to `TRANSIT_OPTIONS`; all of them by
    `rank_key`, best first: the time door to door with each ride's busy roads and junction
    waits counted again (Stephen, 2026-10-21). The best of `hops` (Novice and Nervous's hop
    past the busy stretch) is kept too, marked, even where it is not among the best."""
    best: dict[tuple, Option] = {}
    for option in transit:
        held = best.get(option.signature)
        if held is None or (option.score_s, option.key) < (held.score_s, held.key):
            best[option.signature] = option
    kept = sorted(best.values(), key=lambda o: (o.score_s, o.key))[:TRANSIT_OPTIONS]
    if hops:
        hop = min(hops, key=lambda o: (o.score_s, o.key))
        kept = [o for o in kept if o.signature != hop.signature]
        kept = kept[: TRANSIT_OPTIONS - 1] + [hop]
    kept += [o for o in (direct, walk) if o is not None]
    # A tie to the minute (the same train) goes to the simpler trip: fewer transit legs.
    return sorted(kept, key=rank_key)


def _runs(day: _Day, patterns: list[Pattern]) -> bool:
    """Whether any of `patterns` leaves a stop (not its last) within `MAX_WAIT_MIN`."""
    minute = day.moment.minute
    for pattern in patterns:
        for pos in range(len(pattern.stops) - 1):
            deps = day.departures(pattern, pos, minute)
            if deps and deps[0] - minute <= MAX_WAIT_MIN:
                return True
    return False


def _idle(day: _Day, stops) -> list[str]:
    """Plain words for the routes near the trip that have no service at this time (the owner:
    "MARC Camden Line: no weekend service")."""
    schedule, moment = day.schedule, day.moment
    routes: dict[tuple[int, str], list[Pattern]] = {}
    for stop in stops:
        for p_index, _pos in schedule.at_stop.get(stop.index, ()):
            pattern = schedule.patterns[p_index]
            if schedule.systems[pattern.system].idle_notes:
                routes.setdefault((pattern.system, pattern.route), []).append(pattern)
    notes = []
    running = running_services(schedule, moment)
    for (system_index, route), found in sorted(routes.items()):
        system = schedule.systems[system_index]
        services = {s for p in found for s in p.trips}
        name = system.route_name(route)
        # After midnight a line that runs on the new date is not "no weekend service": it is
        # out of its hours (`closed_stations`' rule).
        if not services & running:
            if moment.holiday:
                notes.append(f"{name}: no holiday service.")
            elif moment.weekend:
                notes.append(f"{name}: no weekend service.")
            else:
                notes.append(f"{name}: no service today.")
            continue
        if not _runs(_Day(schedule, moment, bike=False), found):
            notes.append(f"{name}: no service at this time.")
        elif day.blackout and system.id == METRO_SYSTEM:
            continue  # said once, by the blackout note
        elif day.bike and not _runs(day, found):
            notes.append(f"{name}: no bikes on board at this time.")
    return notes


@dataclass
class Plan:
    """A transit ride type's options, ranked quickest first, and the one chosen (the first,
    unless the rider chose another by its key)."""

    mode: str
    options: list[Option]
    moment: Moment
    notes: list[str]
    credits: dict[str, str] = field(default_factory=dict)  # system name -> credit
    chosen: int = 0
    asked: str | None = None  # the key the rider asked for, when it is no longer an option

    @property
    def option(self) -> Option:
        return self.options[self.chosen]

    @property
    def when(self) -> Moment:
        """The chosen option's moment: its own service day's, for a trip found on the other
        one (around 1 to 5 am), else the plan's."""
        return self.option.moment or self.moment

    @property
    def legs(self) -> list[Leg]:
        return list(self.option.legs)

    @property
    def ride(self) -> int:
        return self.option.ride

    @property
    def direct(self) -> Option | None:
        return next((o for o in self.options if o.direct), None)

    @property
    def bike_only_s(self) -> float | None:
        direct = self.direct
        return None if direct is None else direct.total_s


def choose(
    plan: Plan, key: str | None, schedule: Schedule | None = None, hop: bool = False
) -> Plan:
    """The plan with the option `key` chosen; the same trip under another key where it is not
    (`same_trip`), else the best where it is not (or no longer) one. With no key and `hop`
    (Novice and Nervous's hop asked for), the hop past the busy stretch where there is one."""
    if key is None and hop:
        # Against the other transit trips only: riding directly there rides the stretch.
        others = [o.total_s for o in plan.options if not (o.hop or o.direct or o.walk)]
        quickest = min(others, default=float("inf"))
        for index, option in enumerate(plan.options):
            if option.hop and option.total_s <= quickest + HOP_SLACK_S:
                return replace(plan, chosen=index, asked=None)
    if key is None:
        return plan
    for index, option in enumerate(plan.options):
        if option.key == key:
            return replace(plan, chosen=index, asked=None)
    if schedule is not None:
        for index, option in enumerate(plan.options):
            if same_trip(schedule, key, option.key):
                return replace(plan, chosen=index, asked=None)
    return replace(plan, chosen=0, asked=key)


def _key_parts(schedule: Schedule, key: str) -> tuple | None:
    """A transit option's key as the trip the rider sees: its stops (the start's, each change's
    and the end's) and its lines in order (each pattern's system and route), or None for a key
    that is not a transit trip's or names a pattern this schedule does not have."""
    parts = []
    for token in re.split(r"[>-]", key):
        if token[:1] == "p" and token[1:].isdigit():
            index = int(token[1:])
            if index >= len(schedule.patterns):
                return None
            pattern = schedule.patterns[index]
            parts.append((pattern.system, pattern.route))
        else:
            parts.append(token)
    return tuple(parts) if any(isinstance(p, tuple) for p in parts) else None


def same_trip(schedule: Schedule, asked: str, key: str) -> bool:
    """Whether two keys are the same trip: the same stops and the same lines, by any of their
    patterns. A trip's key names the pattern that reached each stop first, which can be another
    of the same line's a minute later, so a pick kept by its exact key was lost on a plan again
    (Stephen, 2026-10-21: "I can't even click on the other options")."""
    a = _key_parts(schedule, asked)
    return a is not None and a == _key_parts(schedule, key)


def running_services(schedule: Schedule, moment: Moment) -> frozenset[int]:
    """The services that make a line "running" for the moment's words: its service day's, and
    between midnight and 3 am (the day before's service day) the new date's too, since its first
    train that morning is said (`station_times`). Plans still wait for actual departures."""
    active = schedule.active(moment.service_day)
    if moment.service_day != moment.date:
        active = active | schedule.active(moment.date)
    return active


@dataclass(frozen=True)
class Closed:
    stop: Stop
    system: System
    reason: str  # "no MARC weekend service"


def closed_stations(schedule: Schedule, moment: Moment) -> list[Closed]:
    """The stations with no service at all on the moment's service day (the owner, 2026-10-12:
    struck through and greyed on the map): a weekend or holiday a line does not run, or a
    planned closure the agency published in its timetable. A station outside its hours on a day
    it runs is not closed. Bus stops are left out. Beyond the installed window nothing is said.
    Between midnight and 3 am (the day before's service day) a station with service on the new
    date is not closed either: its card gives that day's first train (`station_times`). Only the
    map's word changes; a plan still waits for the trains' actual departures."""
    if not schedule.covers(moment.service_day):
        return []
    active = running_services(schedule, moment)
    serving: dict[int, bool] = {}
    for pattern in schedule.patterns:
        runs = any(service in active for service in pattern.trips)
        for stop in pattern.stops:
            serving[stop] = serving.get(stop, False) or runs
    out = []
    for stop in schedule.stops:
        if not stop.rail or serving.get(stop.index, True):
            continue
        system = schedule.systems[stop.system]
        if moment.holiday:
            reason = f"no {system.name} holiday service"
        elif moment.weekend:
            reason = f"no {system.name} weekend service"
        else:
            reason = f"no {system.name} service today"
        out.append(Closed(stop, system, reason))
    return out


# --- A station's times, for its card on the map (the owner, 2026-10-12) ---------------------
#
# Stephen, 2026-10-12: "In the metro and marc icons on the map, put either the headways for
# metro or in the case of MARC when the next train would be in each direction". A station's card
# says, for each rail stop at the station (`STATION_NEAR_M`, the nearest of each system): a
# frequent system's line (Metro, Light RailLink, Metro SubwayLink: `FREQUENT_MODES`) with the
# minutes between its trains now, and a commuter line (MARC, VRE) with its next train each way,
# its destination and time. A direction with nothing more today says so. Scheduled, as every
# transit time is (`SCHEDULED`); Metro on its typical timetable where no WMATA GTFS is installed.

STATION_NEAR_M = 400.0  # a stop this close to the map's station is at it (railClosures' MATCH_M)
# A system's stops of the nearest one's name this close to it are one station's platforms: MDOT
# MTA's MARC feed lists each station once per direction ("PENN STATION MARC nb" and "... sb",
# 6 m apart, both "Penn Station MARC" by `station_name`) with no parent station, and the card
# needs both to say each way's next train.
PLATFORM_M = 200.0
FREQUENT_MODES = (METRO, LIGHT_RAIL, SUBWAY)
EVERY_SEEN_MIN = 60  # a frequent line's interval is read from its trains within this
EVERY_SEEN = 3  # and only from at least this many of them: fewer are said one by one
EVERY = "every"
NEXT = "next"
NONE = "none"


@dataclass(frozen=True)
class LineTime:
    """One line's times at a station: `EVERY` (minutes between trains), `NEXT` (the next train
    one way: its destination and minute of `service_day`, the moment's own when None), or
    `NONE` (none more today that way; `today` False when none ran at all, and `toward` None for
    both ways)."""

    stop: Stop
    system: System
    route: str
    kind: str
    every_min: int | None = None
    toward: str | None = None
    depart: float | None = None
    today: bool = True
    service_day: date | None = None


def _departures_at(active, pattern: Pattern, pos: int) -> list[float]:
    """Every departure of `pattern` from its stop `pos` on a service day (`active`: the services
    running), in service-day minutes: each trip's start plus the run times of its own band."""
    offsets: dict[int | None, float] = {}
    out: list[float] = []
    for service, deps in pattern.trips.items():
        if service not in active:
            continue
        for encoded in deps:
            start = encoded >> 1
            band = band_index(start)
            if band not in offsets:
                offsets[band] = pattern.runs_at(start)[pos] / 60.0
            out.append(start + offsets[band])
    return out


def _direction(schedule: Schedule, pattern: Pattern, reference: Pattern) -> int:
    """0 where `pattern` heads the way its route's longest pattern does, else 1: by which of that
    pattern's ends its own last stop is nearer (a short-turn heads toward the far end)."""
    last = schedule.stops[pattern.stops[-1]].point
    to_end = _distance(last, schedule.stops[reference.stops[-1]].point)
    to_start = _distance(last, schedule.stops[reference.stops[0]].point)
    return 0 if to_end <= to_start else 1


def _longest(patterns) -> Pattern:
    return max(patterns, key=lambda p: (len(p.stops), -p.index))


def _every_min(times: list[float]) -> int | None:
    """The minutes between the next trains, read from at least `EVERY_SEEN` of them within
    `EVERY_SEEN_MIN` of the first, else None."""
    distinct: list[float] = []
    for dep in sorted(times):
        if not distinct or dep - distinct[-1] >= 0.5:
            distinct.append(dep)
    seen = [dep for dep in distinct if dep - distinct[0] <= EVERY_SEEN_MIN][:DEPARTURES_SEEN]
    if len(seen) < EVERY_SEEN:
        return None
    return max(1, round((seen[-1] - seen[0]) / (len(seen) - 1)))


def station_times(schedule: Schedule, point, when: datetime) -> list[LineTime]:
    """The lines at the rail stops within `STATION_NEAR_M` of `point` (the nearest of each
    system), at `when`: in the schedule's system order, then its route order. Bus stops are left
    out, and beyond the installed window nothing is said. Between midnight and 3 am (the day
    before's service day), a way with no more trains that night gives the first one of the new
    day instead of "no more trains today"."""
    moment = moment_of(when)
    if not schedule.covers(moment.service_day):
        return []
    active = schedule.active(moment.service_day)
    morning = None
    if moment.service_day != moment.date and schedule.covers(moment.date):
        morning = (schedule.active(moment.date), moment.date)
    nearby = [stop for _distance_m, stop in schedule.near(point, STATION_NEAR_M) if stop.rail]
    nearest: dict[int, Stop] = {}
    for stop in nearby:
        nearest.setdefault(stop.system, stop)
    out: list[LineTime] = []
    for system_index in sorted(nearest):
        stop = nearest[system_index]
        system = schedule.systems[system_index]
        platforms = [
            s
            for s in nearby
            if s.system == system_index
            and s.name == stop.name
            and _distance(s.point, stop.point) <= PLATFORM_M
        ]
        leaving = sorted(
            (p_index, pos)
            for platform in platforms
            for p_index, pos in schedule.at_stop.get(platform.index, ())
            # it ends here: nothing leaves on it
            if pos < len(schedule.patterns[p_index].stops) - 1
        )
        # Each route's ways are read against its longest pattern through this station, not the
        # system's: MARC's feed names all three lines "MARC", and against the Brunswick Line's
        # ends both of Penn Station's ways head the same way.
        references: dict[str, Pattern] = {}
        for p_index, _pos in leaving:
            pattern = schedule.patterns[p_index]
            best = references.get(pattern.route)
            references[pattern.route] = pattern if best is None else _longest((best, pattern))
        # route -> direction -> [(pattern, pos)], in the order the routes first appear
        routes: dict[str, dict[int, list[tuple[Pattern, int]]]] = {}
        for p_index, pos in leaving:
            pattern = schedule.patterns[p_index]
            direction = _direction(schedule, pattern, references[pattern.route])
            routes.setdefault(pattern.route, {}).setdefault(direction, []).append((pattern, pos))
        for route, ways in routes.items():
            out.extend(_line_times(schedule, active, moment, morning, stop, system, route, ways))
    return out


def _line_times(schedule, active, moment, morning, stop, system, route, ways) -> list[LineTime]:
    """One route's `LineTime`s at a stop, from its patterns there by direction; `morning` (the
    services and date of the new day, after midnight) gives a finished way its first train."""
    # direction -> (every departure today, the next ones: minute, pattern, service day or None)
    found: dict[int, tuple[list[float], list[tuple[float, Pattern, date | None]]]] = {}
    for direction, entries in sorted(ways.items()):
        today: list[float] = []
        upcoming: list[tuple[float, Pattern, date | None]] = []
        for pattern, pos in entries:
            for at in _departures_at(active, pattern, pos):
                today.append(at)
                if at >= moment.minute:
                    upcoming.append((at, pattern, None))
        if not upcoming and morning is not None:
            for pattern, pos in entries:
                upcoming.extend(
                    (at, pattern, morning[1]) for at in _departures_at(morning[0], pattern, pos)
                )
        upcoming.sort(key=lambda t: (t[0], t[1].index))
        found[direction] = (today, upcoming)
    if not any(today or upcoming for today, upcoming in found.values()):
        return [LineTime(stop, system, route, NONE, today=False)]
    if system.mode in FREQUENT_MODES:
        # Running now: at least `EVERY_SEEN` trains at an interval, the next within it (before
        # the first train of the morning, the first trains each way are said instead).
        every = []
        for _today, upcoming in found.values():
            tonight = [t for t, _p, day in upcoming if day is None]
            e = _every_min(tonight)
            if e is not None and tonight[0] - moment.minute <= e + 1:
                every.append(e)
        if every:
            return [LineTime(stop, system, route, EVERY, every_min=min(every))]
    out = []
    for direction, (today, upcoming) in found.items():
        if upcoming:
            at, pattern, day = upcoming[0]
            toward = schedule.stops[pattern.stops[-1]].name
            out.append(
                LineTime(stop, system, route, NEXT, toward=toward, depart=at, service_day=day)
            )
        else:
            # The destination of the way's longest pattern: where its trains went today.
            pattern = _longest(p for p, _pos in ways[direction])
            toward = schedule.stops[pattern.stops[-1]].name
            out.append(LineTime(stop, system, route, NONE, toward=toward, today=bool(today)))
    return out


def _window_note(schedule: Schedule, moment: Moment) -> list[str]:
    if schedule.covers(moment.service_day):
        return []
    return [
        t(
            "The timetables installed run {first} to {last}: no transit is planned for this date.",
            first=day_said(schedule.start),
            last=day_said(schedule.last_day),
        )
    ]


def _credits(schedule: Schedule) -> dict[str, str]:
    return {s.name: s.credit for s in schedule.systems}


def _search_days(day: _Day, moments: list[Moment], starts, ends, speed: float) -> list[Option]:
    """`_search` on the plan's service day and, around 1 to 5 am, the other one too (each
    option found there carries that day's moment)."""
    found = _search(day, starts, ends, speed)
    for other in moments[1:]:
        alt = _Day(day.schedule, other, day.bike)
        alt.pricing = day.pricing
        found += [replace(o, moment=other) for o in _search(alt, starts, ends, speed)]
    return found


def _hop_stops(schedule: Schedule, point, other, bike: bool) -> list[Stop]:
    """The stations and stops a hop past a busy stretch tries at one of its ends, `point`:
    only those nearer it than the stretch's `other` end, so the hop boards before the
    stretch and gets off after it."""
    near, more = _candidates(schedule, point, bike, HOP_NEAR_M, HOP_NEAR_M)
    return [s for s in near + more if _distance(s.point, point) < _distance(s.point, other)]


def _hops(day: _Day, moments, starts: list[_End], ends: dict[int, _End], speed: float):
    """The trips from `starts` to `ends` (each a hop's), marked `hop`, with keys of their own."""
    starts = [replace(s, key=f"h{s.key}") for s in starts]
    ends = {stop: replace(e, key=f"h{e.key}") for stop, e in ends.items()}
    return [replace(o, hop=True) for o in _search_days(day, moments, starts, ends, speed)]


def plan_bike(
    schedule,
    start,
    end,
    when: datetime,
    services: Services,
    speed_kmh: float,
    hop: list | None = None,
) -> Plan:
    """Own Bike + 🚆🚌: the bike goes the whole way. Riding directly there, and up to two
    transit legs (Metro, a train, a bus's rack) with rides between. Never a leg on foot.
    `hop`: Novice and Nervous's busy stretch, where it begins and ends (`HOP_NEAR_M`)."""
    moments = moments_of(when)
    moment = moments[0]
    day = _Day(schedule, moment, bike=True)
    found: list[Option] = []
    notes = _window_note(schedule, moment)
    if day.blackout:
        notes.append(blackout_words(day.blackout_day))
    # Riding directly there first: it is always offered, so it has the router before the
    # candidates; with no answer it is estimated from the straight line.
    routed = services.ride(start, end)
    whole = routed or Ride(ride_s(start, end, speed_kmh), (tuple(start), tuple(end)))
    # The rides the router could not trace are priced as the whole ride is.
    day.pricing = pricing_of(routed)
    penalty, busy = priced(routed, whole.seconds, _line_m(whole), day.pricing)
    direct = Option(
        DIRECT,
        (
            Leg(
                RIDE,
                whole.seconds,
                whole.coordinates,
                estimated=routed is None,
                penalty_s=penalty,
                busy_m=busy,
            ),
        ),
        direct=True,
    )
    near_start, more_start = _candidates(schedule, start, True, BIKE_TO_STATION_M, RIDE_TO_STOP_M)
    near_end, more_end = _candidates(schedule, end, True, BIKE_TO_STATION_M, RIDE_TO_STOP_M)
    hops: list[Option] = []
    if not notes:
        starts = [
            _ride_to(
                schedule,
                start,
                s,
                services.ride(start, list(s.bike_entrance)),
                speed_kmh,
                day.pricing,
            )
            for s in near_start
        ] + [_ride_to(schedule, start, s, None, speed_kmh, day.pricing) for s in more_start]
        ends = {
            s.index: _ride_from(
                schedule,
                end,
                s,
                services.ride(list(s.bike_entrance), end),
                speed_kmh,
                day.pricing,
            )
            for s in near_end
        }
        for s in more_end:
            ends[s.index] = _ride_from(schedule, end, s, None, speed_kmh, day.pricing)
        found = _search_days(day, moments, starts, ends, speed_kmh)
        if hop:
            hop_starts = [
                _ride_to(schedule, start, s, None, speed_kmh, day.pricing)
                for s in _hop_stops(schedule, hop[0], hop[1], True)
            ]
            hop_ends = {
                s.index: _ride_from(schedule, end, s, None, speed_kmh, day.pricing)
                for s in _hop_stops(schedule, hop[1], hop[0], True)
            }
            hops = _hops(day, moments, hop_starts, hop_ends, speed_kmh)
        if not found and not hops:
            if near_start and near_end:
                notes.append(no_transit_words())
            elif not near_start:
                notes.append(
                    t(
                        "No station that takes a bike is within {distance} of the start: riding"
                        " the whole way is the plan.",
                        distance=miles(BIKE_TO_STATION_M),
                    )
                )
            else:
                notes.append(
                    t(
                        "No station that takes a bike is within {distance} of the destination:"
                        " riding the whole way is the plan.",
                        distance=miles(BIKE_TO_STATION_M),
                    )
                )
        notes += _idle(day, near_start + more_start + near_end + more_end)
    if schedule.note:
        notes.append(schedule.note)
    return Plan(
        presets.BIKE_TRANSIT, _ranked(direct, found, hops=hops), moment, notes, _credits(schedule)
    )


def _share_direct(start, end, services: Services, snapshot) -> Option | None:
    """Bikeshare the whole way: walk to a dock with a classic bike, ride it to a dock near the
    destination, walk on."""
    pickup = _nearest_dock(snapshot, start, DOCK_NEAR_M, taking=True)
    dropoff = _nearest_dock(snapshot, end, DOCK_NEAR_M, taking=False)
    if pickup is None or dropoff is None or pickup.station_id == dropoff.station_id:
        return None
    legs = _share_legs(start, end, pickup, dropoff, None)
    ride = services.ride(list(pickup.point), list(dropoff.point))
    if ride is not None:
        legs[1] = replace(legs[1], seconds=ride.seconds, coordinates=ride.coordinates)
    return Option(DIRECT, tuple(legs), direct=True)


def _walk_whole(start, end, services: Services) -> Option:
    """Walking the whole way: Valhalla's pedestrian costing, else the straight line's estimate."""
    walked = services.walk(start, end)
    if walked is None:
        walked = Ride(walk_s(start, end), (tuple(start), tuple(end)))
    leg = Leg(WALK, walked.seconds, walked.coordinates, estimated=walked.metres is None)
    return Option(WALK_ONLY, (leg,), walk=True)


def walk_offered(start, end, walk_total_s: float, others: list[Option]) -> bool:
    """Walking the whole way is offered where the trip is under `WALK_ONLY_M` (a straight line),
    or where it is quicker than every other option there is."""
    if _distance(start, end) <= WALK_ONLY_M:
        return True
    return bool(others) and walk_total_s < min(o.total_s for o in others)


def plan_bikeshare(
    schedule,
    start,
    end,
    when: datetime,
    services: Services,
    snapshot,
    hop: list | None = None,
) -> Plan:
    """Bikeshare + 🚶🚆🚌: bikeshare the whole way, or each end on foot or by bikeshare,
    whichever is quicker (a bikeshare bike is docked before boarding), with up to two transit
    legs between; and walking the whole way where that is reasonable (`walk_offered`).
    `hop`: Novice and Nervous's busy stretch, where it begins and ends (`HOP_NEAR_M`)."""
    moments = moments_of(when)
    moment = moments[0]
    day = _Day(schedule, moment, bike=False)
    found: list[Option] = []
    notes = _window_note(schedule, moment)
    if snapshot.status is None:
        notes.append(
            t("Bike and dock availability is unknown right now: the nearest docks are used.")
        )
    # Bikeshare directly there first, so its ride has the router before anything else.
    direct = _share_direct(start, end, services, snapshot)
    near_start, more_start = _candidates(schedule, start, False, BIKE_TO_STATION_M, WALK_TO_STOP_M)
    near_end, more_end = _candidates(schedule, end, False, BIKE_TO_STATION_M, WALK_TO_STOP_M)
    hops: list[Option] = []
    if not _window_note(schedule, moment):
        starts = _best_few(
            [
                _quicker(_walk_to(schedule, s, start), _share_to(schedule, s, start, snapshot))
                for s in near_start + more_start
            ],
            STATION_CANDIDATES + BUS_STOPS_NEAR,
        )
        ends = {}
        for s in near_end + more_end:
            quick = _quicker(_walk_from(schedule, s, end), _share_from(schedule, s, end, snapshot))
            if quick is not None:
                ends[s.index] = quick
        found = _search_days(day, moments, starts, ends, BIKESHARE_SPEED_KMH)
        if hop:
            hop_starts = _best_few(
                [
                    _share_to(schedule, s, start, snapshot)
                    for s in _hop_stops(schedule, hop[0], hop[1], False)
                ],
                STATION_CANDIDATES + BUS_STOPS_NEAR,
            )
            hop_ends = {}
            for s in _hop_stops(schedule, hop[1], hop[0], False):
                shared = _share_from(schedule, s, end, snapshot)
                if shared is not None:
                    hop_ends[s.index] = shared
            hops = _hops(day, moments, hop_starts, hop_ends, BIKESHARE_SPEED_KMH)
        if not found and not hops:
            notes.append(no_transit_words())
        notes += _idle(day, near_start + more_start + near_end + more_end)
    if schedule.note:
        notes.append(schedule.note)
    # Walking the whole way: decided on the straight line's estimate (no router call where it
    # is plainly out), then walked by the router for its time and line.
    others = [o for o in (direct, *found, *hops) if o is not None]
    walk = None
    if walk_offered(start, end, walk_s(start, end), others):
        walk = _walk_whole(start, end, services)
    if direct is None and not found and not hops and walk is None:
        raise NoTransit(
            "No dock with a classic bike near the start has a free dock near the destination,"
            " and no transit is in reach on foot or by bikeshare at both ends."
        )
    return Plan(
        presets.BIKESHARE_TRANSIT,
        _ranked(direct, found, walk, hops),
        moment,
        notes,
        _credits(schedule),
    )


# --- The answer's block ------------------------------------------------------------------------


def with_ride(plan: Plan, seconds: float) -> Plan:
    """The plan with its chosen option's route line timed by the routed line (the answer's
    own). A walk keeps its walking time (its line is the pedestrian router's, `drawn`'s)."""
    return with_rides(plan, {plan.option.ride: seconds})


def with_rides(
    plan: Plan,
    seconds: dict[int, float],
    busy: dict[int, float] | None = None,
    keep: bool = True,
) -> Plan:
    """The plan with its chosen option's ride legs timed as routed: `seconds` by leg index
    (the route line's own, and each later ride routed for its stress colours). A walk keeps
    its walking time; the waits for infrequent departures are worked out again from the new
    times, and an option whose departure can no longer be caught goes, as `with_ride`. The
    options are ranked again (`resorted`); without `keep` (the rider chose none), the best of
    them is chosen, which may now be another (the caller plans it)."""
    option = plan.option
    legs = list(option.legs)
    changed = False
    for index, routed in seconds.items():
        leg = legs[index]
        if leg.mode not in (RIDE, SHARE):
            continue
        # Its busy metres as routed (`busy`, the answer's own stress breakdown) where given;
        # the penalty keeps its share of the ride's time.
        share = leg.penalty_s / leg.seconds if leg.seconds > 0 else 0.0
        busy_m = (busy or {}).get(index, leg.busy_m)
        legs[index] = replace(
            leg, seconds=routed, estimated=False, penalty_s=routed * share, busy_m=busy_m
        )
        changed = True
    if not changed:
        return plan
    legs, notes = _retimed(plan.when.minute, legs)
    options = list(plan.options)
    if legs is None:
        # No departure this trip could catch within the hour: the option goes, and is never
        # totalled as caught. The quickest that is left is planned instead.
        del options[plan.chosen]
        if not options:
            raise NoTransit(" ".join(notes))
        return replace(plan, options=options, chosen=0, notes=plan.notes + notes)
    options[plan.chosen] = replace(option, legs=tuple(legs))
    ranked = resorted(replace(plan, options=options, notes=plan.notes + notes))
    return ranked if keep else replace(ranked, chosen=0)


def resorted(plan: Plan) -> Plan:
    """The options in `rank_key` order again, the same one chosen: the chosen trip's rides timed
    as routed can move it past another (Stephen, 2026-10-21: A listed first at 106 min above B at
    88 min, which was still an estimate)."""
    key = plan.option.key
    options = sorted(plan.options, key=rank_key)
    return replace(
        plan, options=options, chosen=next(i for i, o in enumerate(options) if o.key == key)
    )


# The most router calls `drawn` makes for one trip's lines, each one's cap, and the time they may
# all take from when the trip is chosen: drawing changes no times, so it never holds an answer long
# (review of #134: twelve 5 s calls could hold a ready answer for half a minute).
MAX_DRAW_CALLS = 6
DRAW_CALL_S = 1.5
DRAW_BUDGET_S = 4.0
_ON_FOOT = (WALK, TAKE)


def drawn(plan: Plan, services: Services, skip: Iterable[int] = ()) -> Plan:
    """The plan with its chosen trip's walks and rides, all but the route line's (the answer's
    own), routed for the map: a walk by Valhalla's pedestrian costing, a ride by the bike's, so
    each is drawn along the streets and paths. Only the lines change, never a time; a leg the
    router does not route (or one of a few yards) keeps its straight line. `skip` names legs
    (by index) already routed elsewhere: the later rides routed for their stress colours."""
    option = plan.option
    legs = list(option.legs)
    skipped = set(skip)
    changed = False
    for index, leg in enumerate(legs):
        if index == option.ride or index in skipped:
            continue
        if leg.mode not in (*_ON_FOOT, RIDE, SHARE):
            continue
        # A routed ride has its shape already; a leg of a few yards has no route to draw.
        if len(leg.coordinates) != 2 or line_m(leg) < MIN_LINE_M:
            continue
        a, b = list(leg.coordinates[0]), list(leg.coordinates[-1])
        routed = services.walk(a, b) if leg.mode in _ON_FOOT else services.ride(a, b)
        if routed is None or len(routed.coordinates) < 2:
            continue
        # Joined to the leg's own ends (a stop's entrance, a dock), where the router snapped off.
        points = list(routed.coordinates)
        if points[0] != tuple(a):
            points.insert(0, tuple(a))
        if points[-1] != tuple(b):
            points.append(tuple(b))
        legs[index] = replace(leg, coordinates=tuple(points))
        changed = True
    if not changed:
        return plan
    options = list(plan.options)
    options[plan.chosen] = replace(option, legs=tuple(legs))
    return replace(plan, options=options)


def _retimed(minute: float, legs: list[Leg]) -> tuple[list[Leg] | None, list[str]]:
    """The infrequent departures' waits again from when the rider now reaches each stop; one
    the rider would miss is said plainly and the next catchable one taken, with the one after
    it (the owner, 2026-10-12). None when no departure seen can be caught."""
    notes = []
    at = minute
    out = []
    for leg in legs:
        if leg.depart is not None:
            arrive = at
            if leg.depart < arrive - 1e-6:
                missed = leg.depart
                catchable = [t for t in leg.later if t >= arrive - 1e-6]
                if leg.live and leg.every is not None and not catchable:
                    # A frequent service whose predictions run out before the rider gets there:
                    # its timetable's wait again, half the interval, never a trip left out.
                    leg = replace(
                        leg,
                        depart=None,
                        after=None,
                        later=(),
                        live=False,
                        wait_s=leg.every * 30.0,
                    )
                    out.append(leg)
                    at += leg.total_s / 60.0
                    continue
                if not catchable or catchable[0] - arrive > MAX_WAIT_MIN:
                    notes.append(
                        t(
                            "You would miss the {time} {source} ({vehicle}) and no later one"
                            " leaves within the hour: that trip is left out.",
                            time=clock(missed, leg.service_day),
                            source=leg._source_said(),
                            vehicle=leg._vehicle_said(),
                        )
                    )
                    return None, notes
                rest = tuple(t for t in leg.later if t > catchable[0])
                leg = replace(leg, depart=catchable[0], after=rest[0] if rest else None, later=rest)
                notes.append(
                    t(
                        "You would miss the {time} {source} ({vehicle}): planned on the {next}"
                        " {source} instead.",
                        time=clock(missed, leg.service_day),
                        source=leg._source_said(),
                        vehicle=leg._vehicle_said(),
                        next=clock(leg.depart, leg.service_day),
                    )
                )
            leg = replace(leg, wait_s=max(0.0, (leg.depart - arrive) * 60.0))
        out.append(leg)
        at += leg.total_s / 60.0
    return out, notes


# Less time than this to spare for an infrequent departure is "cutting it close" (the owner,
# 2026-10-12): Go shows a countdown to it.
CLOSE_S = 300.0


def _local(moment: Moment, minute: float) -> str:
    """A service-day minute as a local ISO time, for the page's clock (real elapsed time from
    the service day's GTFS zero, so right across a daylight-saving change)."""
    at = day_zero(moment.service_day) + timedelta(minutes=minute)
    return at.astimezone(ZONE).isoformat(timespec="seconds")


def departure(plan: Plan) -> dict | None:
    """The chosen trip's first infrequent departure: when it leaves and from where, when the
    rider gets there, the time to spare and the one after it, as Go shows it. A frequent
    service timed live (a train every few minutes) is not one: it never shows a countdown."""
    legs = plan.legs
    for index, leg in enumerate(legs):
        if not leg.transit or leg.depart is None or (leg.live and leg.every is not None):
            continue
        reach = plan.when.minute + _total(legs[:index]) / 60.0
        return {
            "step": index,
            "system": leg.system,
            "vehicle": leg.vehicle,
            "board_at": leg.board_at,
            "departs": clock(leg.depart, plan.when.service_day),
            "departs_at": _local(plan.when, leg.depart),
            "arrive_at": _local(plan.when, reach),
            "next": None if leg.after is None else clock(leg.after, plan.when.service_day),
            "next_at": None if leg.after is None else _local(plan.when, leg.after),
            "spare_s": round(leg.wait_s),
            "close": leg.wait_s < CLOSE_S,
            "planned_at": _local(plan.when, plan.when.minute),
            "point": _pt(leg.coordinates[0]) if leg.coordinates else None,
            "source": leg.source,
            "label": (
                f"{leg.system} {clock(leg.depart, plan.when.service_day)} {leg.source}"
                f" · {round(leg.wait_s / 60)} min spare"
            ),
        }
    return None


def label(option: Option, mode: str) -> str:
    """The option in a few words: how it starts, its transit legs, how it ends."""
    if option.direct:
        if mode == presets.BIKE_TRANSIT:
            return t("Ride the whole way")
        return t("Bikeshare the whole way")
    if option.walk:
        return t("Walk the whole way")
    walk = t("walk")
    ends = {RIDE: t("ride"), TAKE: t("bikeshare"), SHARE: t("bikeshare"), WALK: walk}
    parts = [ends.get(option.legs[0].mode, walk)]
    for leg in option.legs:
        if not leg.transit:
            continue
        lines = " or ".join(leg.lines)
        routes = lines.replace(" or ", t(" or "))
        if leg.mode == BUS:
            parts.append(t("bus {routes} to {place}", routes=routes, place=leg.to))
        elif lines.lower() in leg.system.lower():
            parts.append(t("{system} to {place}", system=leg.system, place=leg.to))
        else:
            parts.append(
                t("{system} to {place} ({routes})", system=leg.system, place=leg.to, routes=routes)
            )
    parts.append(ends.get(option.legs[-1].mode, walk))
    words = ", ".join(parts)
    return words[0].upper() + words[1:]


# The compact legs' kinds (`option_legs`): a walk, your own bike, a bikeshare bike, or transit.
_LEG_KIND = {WALK: WALK, TAKE: WALK, RIDE: RIDE, SHARE: SHARE}


def option_legs(option: Option) -> list[dict]:
    """The option's legs, compactly, for its row ("🚶 4 min · 🚲 12 min · 🔴 18 min"; the
    page draws the marks, frontend/src/lib/transitMarks.ts): one entry per walk, ride or
    transit leg in order, with its minutes. Walking into and out of a station counts with the
    walk or ride beside it, two walks or rides in a row are one, and a transit leg's minutes
    include its wait, so the legs add up to about the option's total."""
    out: list[dict] = []
    carry = 0.0  # a station's way out, held for the walk or ride after it
    for leg in option.legs:
        if leg.mode in (ENTER, EXIT):
            if leg.mode == ENTER and out and out[-1]["mode"] in _LEG_KIND.values():
                out[-1]["seconds"] += leg.seconds
            else:
                carry += leg.seconds
            continue
        if leg.transit:
            entry = {
                "mode": leg.mode,
                "system": leg.system or None,
                "lines": list(leg.lines),
                "seconds": leg.total_s,
            }
        else:
            kind = _LEG_KIND[leg.mode]
            entry = {"mode": kind, "system": None, "lines": [], "seconds": leg.seconds + carry}
            carry = 0.0
        if out and not leg.transit and out[-1]["mode"] == entry["mode"]:
            out[-1]["seconds"] += entry["seconds"]
            continue
        out.append(entry)
    if carry and out:
        out[-1]["seconds"] += carry
    for entry in out:
        entry["minutes"] = minutes(entry.pop("seconds"))
    return out


def holiday_words(option: Option, schedule: Schedule | None) -> str:
    """The holiday note, true to the systems the option uses: Metro on its typical timetable
    runs its Sunday one (the typical file's `holiday` day type), the others their own."""
    typical = {s.name for s in schedule.systems if s.typical} if schedule is not None else set()
    used = {leg.system for leg in option.legs if leg.transit}
    if not used & typical:
        return t(
            "Today is a federal holiday: each system's holiday timetable is used, as it publishes"
            " it."
        )
    kind = _typical_doc()["holiday"]
    day = {"sunday": t("Sunday"), "saturday": t("Saturday")}.get(kind, kind.capitalize())
    if used <= typical:
        return t("Today is a federal holiday: Metro is planned on its {day} timetable.", day=day)
    return t(
        "Today is a federal holiday: Metro is planned on its {day} timetable; the others, their"
        " holiday timetables.",
        day=day,
    )


def _notes(plan: Plan, rules: dict[str, str]) -> list[str]:
    legs = plan.legs
    notes = list(plan.notes)
    if plan.asked is not None:
        notes.insert(0, t("The trip chosen is no longer scheduled: the quickest is shown."))
    for leg in legs:
        rule = rules.get(leg.system)
        if leg.transit and leg.bike and rule:
            said = f"{leg.system}: {rule[0].lower()}{rule[1:]}"
            if said not in notes:
                notes.append(said)
    # A bike taken at the far end is counted now, not when the rider gets there (TB-9).
    ridden = False
    for leg in legs:
        ridden = ridden or leg.transit
        if ridden and leg.mode == TAKE and leg.to:
            said = far_dock_words(leg.to)
            if said not in notes:
                notes.append(said)
    if any(leg.transit and leg.live for leg in legs):
        notes.append(LIVE_WORDS)
    if any(leg.transit for leg in legs):
        notes.append(SCHEDULED_WORDS)
    return notes


def far_dock_words(dock: str) -> str:
    return t("Bikes at {dock} are counted now; check on arrival.", dock=dock)


def block(plan: Plan, schedule: Schedule | None = None) -> dict:
    """The route answer's `transit` object: the options, and the chosen one's steps, total
    and comparison with riding the whole way."""
    option = plan.option
    total = option.total_s
    rules = {s.name: s.rule for s in schedule.systems} if schedule is not None else {}
    steps = []
    last_index = len(option.legs) - 1
    for index, leg in enumerate(option.legs):
        steps.append(
            {
                "mode": leg.mode,
                "text": leg.words(last=index == last_index),
                "seconds": round(leg.seconds),
                "wait_s": round(leg.wait_s),
                "to": leg.to,
                "lines": list(leg.lines),
                "system": leg.system or None,
                "departs": None if leg.depart is None else clock(leg.depart, leg.service_day),
                "every_min": None if leg.every is None else max(1, round(leg.every)),
                # Where a transit step's times are from: "scheduled", or "live" where WMATA's
                # predictions time its departure (core.transit_live).
                "source": leg.source if leg.transit else None,
                "with_bike": leg.bike,
                # The route's own line is this step's: the map draws the rest from here.
                "route_line": index == option.ride,
                "coordinates": [_pt(p) for p in leg.coordinates] if index != option.ride else [],
            }
        )
    total_min = minutes(total)
    live_times = any(leg.transit and leg.live for leg in option.legs)
    share = plan.mode == presets.BIKESHARE_TRANSIT
    whole = t("Riding a bikeshare bike") if share else t("Riding")
    if option.direct and share:
        summary = t("About {m} min door to door, by bikeshare.", m=total_min)
    elif option.direct:
        summary = t("About {m} min door to door, riding the whole way.", m=total_min)
    elif option.walk:
        summary = t("About {m} min door to door, walking.", m=total_min)
    elif live_times:
        summary = t("About {m} min door to door, with live departures.", m=total_min)
    else:
        summary = t("About {m} min door to door, scheduled.", m=total_min)
    used = list(dict.fromkeys(leg.system for leg in option.legs if leg.transit))
    notes = _notes(plan, rules)
    out = {
        "mode": plan.mode,
        "key": option.key,
        "direct": option.direct,
        "total_s": round(total),
        "minutes": total_min,
        "summary": summary,
        "bike_only_s": None if plan.bike_only_s is None else round(plan.bike_only_s),
        "comparison": None,
        "riding_quicker": False,
        "options": [
            {
                "key": o.key,
                "label": label(o, plan.mode),
                "total_s": round(o.total_s),
                "minutes": minutes(o.total_s),
                "direct": o.direct,
                "walk": o.walk,
                "hop": o.hop,
                "chosen": index == plan.chosen,
                "busy_m": None if o.busy_m is None else round(o.busy_m),
                "elevator_out": any(leg.elevator_out for leg in o.legs),
                "legs": option_legs(o),
            }
            for index, o in enumerate(plan.options)
        ],
        "steps": steps,
        "notes": notes,
        "day_type": plan.when.day_type,
        "band": None,
        "holiday": plan.when.holiday,
        # Own Bike + 🚆🚌 on a blackout date: no option takes a bike on Metro, and it is said.
        "bike_blackout": plan.mode == presets.BIKE_TRANSIT
        and blackout_day(plan.moment) is not None,
        "scheduled": option.scheduled,
        # A departure on the chosen trip is WMATA's prediction (its step says "live").
        "live_times": live_times,
        "credits": [plan.credits[name] for name in used if plan.credits.get(name)],
        "departure": departure(plan),
    }
    band = band_index(plan.when.minute)
    if band is not None:
        out["band"] = BANDS[band][2]
    if plan.when.holiday and option.scheduled:
        out["notes"].append(holiday_words(option, schedule))
    transit = [o for o in plan.options if o.scheduled]
    if option.direct and transit:
        best = min(o.total_s for o in transit)
        best_min = minutes(best)
        out["riding_quicker"] = total <= best
        if total <= best:
            out["comparison"] = t(
                "{how} the whole way is quickest: the quickest transit trip is about {m} min.",
                how=whole,
                m=best_min,
            )
        else:
            out["comparison"] = t(
                "{how} the whole way: about {m} min. Transit could save about {saved} min.",
                how=whole,
                m=total_min,
                saved=max(1, total_min - best_min),
            )
    elif option.scheduled and plan.bike_only_s is not None:
        bike_min = minutes(plan.bike_only_s)
        if plan.bike_only_s <= total:
            out["riding_quicker"] = True
            out["comparison"] = t(
                "{how} the whole way is quicker: about {m} min, against about {transit} min with"
                " transit.",
                how=whole,
                m=bike_min,
                transit=total_min,
            )
        else:
            out["comparison"] = t(
                "{how} the whole way: about {m} min. Transit saves about {saved} min.",
                how=whole,
                m=bike_min,
                saved=max(1, bike_min - total_min),
            )
    return out
