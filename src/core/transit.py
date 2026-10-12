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
the time of riding the whole way, said plainly when it is quicker.

Nothing here is live. The times are **scheduled**: each system's static GTFS, compacted on the
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
from bisect import bisect_left
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from routemaker.geo import Point, haversine
from routemaker.ridetime import ZONE, federal_holidays

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

SYSTEMS_PATH = Path(__file__).resolve().parent / "transitdata" / "systems.json"
BLACKOUTS_PATH = Path(__file__).resolve().parent / "transitdata" / "metro-bike-blackouts.json"
METRO_SYSTEM = "wmata-rail"
TYPICAL_PATH = Path(__file__).resolve().parent / "transitdata" / "metro-typical.json"


def blackout_words(day: date) -> str:
    """The plain note on a blackout date: "Bikes aren't allowed on Metro today (July 4)."."""
    return f"Bikes aren't allowed on Metro today ({day:%B} {day.day})."


HOLIDAY_WORDS = (
    "Today is a federal holiday: each system's holiday timetable is used, as it publishes it."
)
# Metro on its typical timetable has no holiday timetable: a holiday runs the typical file's
# `holiday` day type (Sunday), and the note says that instead (`holiday_words`).
TYPICAL_HOLIDAY_WORDS = "Today is a federal holiday: Metro is planned on its {day} timetable."
SCHEDULED_WORDS = "Scheduled service: check for track work and service alerts before you go."
# Every transit time a rider sees says where it is from, in one word (the owner, 2026-10-12:
# "Make it clear whether it's a schedule or live."): "8:12 am scheduled", "every 8 min,
# scheduled". GTFS timetables and Metro's typical timetable are both "scheduled"; live times
# (v0.7) will say "live". Each transit step and the departure carry it as `source`.
SCHEDULED = "scheduled"
NO_TRANSIT_WORDS = (
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
    # that does not reach the date (`load`).
    note: str = ""

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


def _cell(point) -> tuple[int, int]:
    return (math.floor(point[0] / CELL), math.floor(point[1] / CELL))


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
        )
        for i, s in enumerate(doc["systems"])
    ]
    stops = [
        Stop(
            i,
            s["name"],
            tuple(s["point"]),
            tuple(s.get("bike_entrance") or s["point"]),
            bool(s["bike"]),
            tuple(tuple(e) for e in s.get("entrances") or [s["point"]]),
            int(s["system"]),
            systems[int(s["system"])].mode != BUS,
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
        return _typical_beyond(day, schedule.last_day)
    return schedule


@lru_cache(maxsize=8)
def _typical_beyond(day: date, last_day: date) -> Schedule:
    """Metro's typical timetable alone for a day the installed file does not reach, saying so."""
    return replace(
        typical_only(day),
        note=(
            "Only Metro is planned: the other timetables installed end"
            f" {last_day:%B} {last_day.day}, {last_day.year}."
        ),
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
    if day in federal_holidays(day.year):
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
                bool(row["bike"]),
                tuple(tuple(e) for e in row["entrances"]),
                system.index,
                True,
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
    """Days of timetable left from `today` (Washington), today included; 0 or less is past."""
    today = today or datetime.now(ZONE).date()
    return (schedule.last_day - today).days + 1


def _warn_if_stale(schedule: Schedule) -> None:
    """Once a day, a log line when the installed timetables are about to run out."""
    global _warned_on
    today = datetime.now(ZONE).date()
    if _warned_on == today:
        return
    left = days_left(schedule, today)
    if left < STALE_DAYS:
        _warned_on = today
        logger.warning(
            "the transit schedule runs out %s (%d day(s) left): rebuild it"
            " (docs/OPERATIONS.md, 'Transit schedule')",
            schedule.last_day.isoformat(),
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
    if left <= 0:
        return (
            f"transit: the schedule ran out on {schedule.last_day.isoformat()}; transit plans"
            " use Metro's typical timetable only until it is rebuilt (docs/OPERATIONS.md,"
            " 'Transit schedule')"
        )
    return (
        f"transit: the schedule runs out on {schedule.last_day.isoformat()}, {left} day(s) left;"
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
    holiday = service_day in federal_holidays(service_day.year)
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

    @property
    def total_s(self) -> float:
        return self.seconds + self.wait_s

    @property
    def arrive(self) -> float | None:
        """An infrequent service: when the rider reaches the stop (service-day minutes)."""
        return None if self.depart is None else self.depart - self.wait_s / 60.0

    @property
    def transit(self) -> bool:
        return self.mode in TRANSIT_MODES

    def _after_words(self) -> str:
        noun = "bus" if self.mode == BUS else "train"
        if self.after is None:
            return f"no later {noun} within the hour"
        return f"next {noun} after that: {clock(self.after, self.service_day)} {SCHEDULED}"

    def words(self, last: bool = False) -> str:
        """The step as one sentence."""
        m = minutes(self.seconds)
        to = self.to or ("your destination" if last else None)
        at = f" to {to}" if to else ""
        if self.mode == RIDE:
            return f"Ride {m} min{at}."
        if self.mode == TAKE:
            return f"Walk {m} min to the bikeshare dock at {self.to} and take a classic bike."
        if self.mode == SHARE:
            return f"Ride the bikeshare bike {m} min and dock it at {self.to}."
        if self.mode == WALK:
            return f"Walk {m} min{at}."
        if self.mode == ENTER:
            how = " by the elevator" if self.bike else ""
            return f"About {m} min into the station{how}."
        if self.mode == EXIT:
            how = " by the elevator" if self.bike else ""
            return f"About {m} min out of the station{how}."
        if self.mode == BUS and self.bike:
            board = f"Put your bike on the front rack of {self.vehicle}"
        else:
            board = f"{'Change to' if self.change else 'Board'} {self.vehicle}"
        if self.depart is None:
            wait = f"about {minutes(self.wait_s)} min wait"
            if self.first is not None:
                # Before opening (#111's review): the first train, not the interval after it.
                first = f"first train {clock(self.first, self.service_day)} {SCHEDULED}"
                return f"{board} ({first}; {wait}); ride {m} min{at}."
            if self.every is None:
                return f"{board} ({wait}, {SCHEDULED}); ride {m} min{at}."
            every = f"every {max(1, round(self.every))} min, {SCHEDULED}"
            return f"{board} ({every}; {wait}); ride {m} min{at}."
        # An infrequent service (the owner, 2026-10-12): the departure, when the rider gets
        # there and the time to spare, and the one after it.
        spare = round(self.wait_s / 60)
        place = f" from {self.board_at}" if self.board_at else ""
        return (
            f"{board} at {clock(self.depart, self.service_day)} {SCHEDULED}{place}: you arrive"
            f" {clock(self.arrive, self.service_day)},"
            f" {spare} min spare; {self._after_words()}. Ride {m} min{at}."
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
        self.blackout = bike and bike_blackout(moment.date)

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
        `minute` (enough to tell a frequent service from a near pair)."""
        found: list[float] = []
        offset = pattern.runs_at(minute)[pos] / 60.0
        low = math.ceil(minute - offset - 1e-9) * 2
        for service, deps in pattern.trips.items():
            if service not in self.active:
                continue
            taken = 0
            for encoded in deps[bisect_left(deps, low) :]:
                at = (encoded >> 1) + offset
                if at - minute > MAX_WAIT_MIN * 3:  # far enough for a missed one's next two
                    break
                if at < minute or not self.boards(pattern, at, encoded):
                    continue
                found.append(at)
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
            deps = self.departures(pattern, pos, minute)
            if not deps or deps[0] - minute > MAX_WAIT_MIN:
                continue
            runs = pattern.runs_at(deps[0])
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
    for t in sorted(times):
        if not distinct or t - distinct[-1] >= 0.5:
            distinct.append(t)
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
    for t in times:
        if t >= (later_times[-1] if later_times else deps[0]) + 0.5:
            later_times.append(t)
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
    ) -> None:
        self._until = until
        self._preset = preset_name
        self._max_calls = MAX_ROUTER_CALLS if max_calls is None else max_calls
        self._per_call_s = per_call_s
        self.calls = 0
        self.spent_s = 0.0  # time in router calls, for the API's log of its phases

    def ride(self, a: LonLat, b: LonLat) -> Ride | None:
        return self._route(a, b, "bicycle", presets.costing(self._preset))

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
        return Ride(
            float(summary.get("time", 0.0)),
            shape,
            None if length is None else float(length) * 1000.0,
        )


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


def _ride_to(schedule: Schedule, start, stop: Stop, ride: Ride | None, speed: float) -> _End:
    """Ride your own bike to a stop (and, a station, in by the elevator)."""
    to = stop.bike_entrance
    if ride is None:
        ride = Ride(ride_s(start, to, speed), (tuple(start), to))
        estimated = True
    else:
        estimated = False
    legs = [Leg(RIDE, ride.seconds, ride.coordinates, schedule.place(stop), estimated=estimated)]
    if stop.rail:
        legs.append(Leg(ENTER, ACCESS_BIKE_S, bike=True))
    return _End(stop.index, legs, f"a{stop.index}")


def _ride_from(schedule: Schedule, end, stop: Stop, ride: Ride | None, speed: float) -> _End:
    start = stop.bike_entrance
    if ride is None:
        ride = Ride(ride_s(start, end, speed), (start, tuple(end)))
        estimated = True
    else:
        estimated = False
    legs = [Leg(EXIT, ACCESS_BIKE_S, bike=True)] if stop.rail else []
    legs.append(Leg(RIDE, ride.seconds, ride.coordinates, estimated=estimated))
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
    # Found on the other service day (around 1 to 5 am): that day's moment; else the plan's.
    moment: Moment | None = None

    @property
    def total_s(self) -> float:
        return _total(self.legs)

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
        legs.append(Leg(EXIT, ACCESS_BIKE_S if bike else ACCESS_WALK_S, bike=bike))
    start = _nearest_entrance(a, b.point)
    end = b.bike_entrance if bike else _nearest_entrance(b, start)
    place = day.schedule.place(b)
    if bike:
        legs.append(Leg(RIDE, ride_s(start, end, speed), (start, end), place, estimated=True))
    else:
        legs.append(Leg(WALK, walk_s(start, end), (start, end), place))
    if b.rail:
        legs.append(Leg(ENTER, ACCESS_BIKE_S if bike else ACCESS_WALK_S, bike=bike))
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


def _ranked(
    direct: Option | None, transit: list[Option], walk: Option | None = None
) -> list[Option]:
    """The direct ride always (and walking the whole way, where it is offered), then the
    quickest of each kind of transit trip (one per signature), up to `TRANSIT_OPTIONS`; all of
    them by total time, quickest first."""
    best: dict[tuple, Option] = {}
    for option in transit:
        held = best.get(option.signature)
        if held is None or (option.total_s, option.key) < (held.total_s, held.key):
            best[option.signature] = option
    kept = sorted(best.values(), key=lambda o: (o.total_s, o.key))[:TRANSIT_OPTIONS]
    kept += [o for o in (direct, walk) if o is not None]
    # A tie to the minute (the same train) goes to the simpler trip: fewer transit legs.
    return sorted(
        kept,
        key=lambda o: (minutes(o.total_s), sum(leg.transit for leg in o.legs), o.total_s, o.key),
    )


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
    for (system_index, route), found in sorted(routes.items()):
        system = schedule.systems[system_index]
        services = {s for p in found for s in p.trips}
        name = system.route_name(route)
        if not services & day.active:
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


def choose(plan: Plan, key: str | None) -> Plan:
    """The plan with the option `key` chosen; the quickest where it is not (or no longer) one."""
    if key is None:
        return plan
    for index, option in enumerate(plan.options):
        if option.key == key:
            return replace(plan, chosen=index, asked=None)
    return replace(plan, chosen=0, asked=key)


@dataclass(frozen=True)
class Closed:
    stop: Stop
    system: System
    reason: str  # "no MARC weekend service"


def closed_stations(schedule: Schedule, moment: Moment) -> list[Closed]:
    """The stations with no service at all on the moment's service day (the owner, 2026-10-12:
    struck through and greyed on the map): a weekend or holiday a line does not run, or a
    planned closure the agency published in its timetable. A station outside its hours on a day
    it runs is not closed. Bus stops are left out. Beyond the installed window nothing is said."""
    if not schedule.covers(moment.service_day):
        return []
    active = schedule.active(moment.service_day)
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


def _window_note(schedule: Schedule, moment: Moment) -> list[str]:
    if schedule.covers(moment.service_day):
        return []
    return [
        f"The timetables installed run {schedule.start:%B} {schedule.start.day} to"
        f" {schedule.last_day:%B} {schedule.last_day.day}: no transit is planned for this date."
    ]


def _credits(schedule: Schedule) -> dict[str, str]:
    return {s.name: s.credit for s in schedule.systems}


def _search_days(day: _Day, moments: list[Moment], starts, ends, speed: float) -> list[Option]:
    """`_search` on the plan's service day and, around 1 to 5 am, the other one too (each
    option found there carries that day's moment)."""
    found = _search(day, starts, ends, speed)
    for other in moments[1:]:
        alt = _Day(day.schedule, other, day.bike)
        found += [replace(o, moment=other) for o in _search(alt, starts, ends, speed)]
    return found


def plan_bike(schedule, start, end, when: datetime, services: Services, speed_kmh: float) -> Plan:
    """Own Bike + 🚆🚌: the bike goes the whole way. Riding directly there, and up to two
    transit legs (Metro, a train, a bus's rack) with rides between. Never a leg on foot."""
    moments = moments_of(when)
    moment = moments[0]
    day = _Day(schedule, moment, bike=True)
    found: list[Option] = []
    notes = _window_note(schedule, moment)
    if day.blackout:
        notes.append(blackout_words(moment.date))
    # Riding directly there first: it is always offered, so it has the router before the
    # candidates; with no answer it is estimated from the straight line.
    whole = services.ride(start, end)
    estimated = whole is None
    if whole is None:
        whole = Ride(ride_s(start, end, speed_kmh), (tuple(start), tuple(end)))
    direct = Option(
        DIRECT, (Leg(RIDE, whole.seconds, whole.coordinates, estimated=estimated),), direct=True
    )
    near_start, more_start = _candidates(schedule, start, True, BIKE_TO_STATION_M, RIDE_TO_STOP_M)
    near_end, more_end = _candidates(schedule, end, True, BIKE_TO_STATION_M, RIDE_TO_STOP_M)
    if not notes:
        starts = [
            _ride_to(schedule, start, s, services.ride(start, list(s.bike_entrance)), speed_kmh)
            for s in near_start
        ] + [_ride_to(schedule, start, s, None, speed_kmh) for s in more_start]
        ends = {
            s.index: _ride_from(
                schedule, end, s, services.ride(list(s.bike_entrance), end), speed_kmh
            )
            for s in near_end
        }
        for s in more_end:
            ends[s.index] = _ride_from(schedule, end, s, None, speed_kmh)
        found = _search_days(day, moments, starts, ends, speed_kmh)
        if not found:
            where = "the start" if not near_start else "the destination"
            notes.append(
                NO_TRANSIT_WORDS
                if near_start and near_end
                else f"No station that takes a bike is within {miles(BIKE_TO_STATION_M)} of"
                f" {where}: riding the whole way is the plan."
            )
        notes += _idle(day, near_start + more_start + near_end + more_end)
    if schedule.note:
        notes.append(schedule.note)
    return Plan(presets.BIKE_TRANSIT, _ranked(direct, found), moment, notes, _credits(schedule))


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


def plan_bikeshare(schedule, start, end, when: datetime, services: Services, snapshot) -> Plan:
    """Bikeshare + 🚶🚆🚌: bikeshare the whole way, or each end on foot or by bikeshare,
    whichever is quicker (a bikeshare bike is docked before boarding), with up to two transit
    legs between; and walking the whole way where that is reasonable (`walk_offered`)."""
    moments = moments_of(when)
    moment = moments[0]
    day = _Day(schedule, moment, bike=False)
    found: list[Option] = []
    notes = _window_note(schedule, moment)
    if snapshot.status is None:
        notes.append("Bike and dock availability is unknown right now: the nearest docks are used.")
    # Bikeshare directly there first, so its ride has the router before anything else.
    direct = _share_direct(start, end, services, snapshot)
    near_start, more_start = _candidates(schedule, start, False, BIKE_TO_STATION_M, WALK_TO_STOP_M)
    near_end, more_end = _candidates(schedule, end, False, BIKE_TO_STATION_M, WALK_TO_STOP_M)
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
        if not found:
            notes.append(NO_TRANSIT_WORDS)
        notes += _idle(day, near_start + more_start + near_end + more_end)
    if schedule.note:
        notes.append(schedule.note)
    # Walking the whole way: decided on the straight line's estimate (no router call where it
    # is plainly out), then walked by the router for its time and line.
    others = [o for o in (direct, *found) if o is not None]
    walk = None
    if walk_offered(start, end, walk_s(start, end), others):
        walk = _walk_whole(start, end, services)
    if direct is None and not found and walk is None:
        raise NoTransit(
            "No dock with a classic bike near the start has a free dock near the destination,"
            " and no transit is in reach on foot or by bikeshare at both ends."
        )
    return Plan(
        presets.BIKESHARE_TRANSIT, _ranked(direct, found, walk), moment, notes, _credits(schedule)
    )


# --- The answer's block ------------------------------------------------------------------------


def with_ride(plan: Plan, seconds: float) -> Plan:
    """The plan with its chosen option's route line timed by the routed line (the answer's
    own). A walk keeps its walking time: the line is the bike router's, the pace is not."""
    option = plan.option
    legs = list(option.legs)
    leg = legs[option.ride]
    if leg.mode not in (RIDE, SHARE):
        return plan
    legs[option.ride] = replace(leg, seconds=seconds, estimated=False)
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
    return replace(plan, options=options, notes=plan.notes + notes)


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
                if not catchable or catchable[0] - arrive > MAX_WAIT_MIN:
                    notes.append(
                        f"You would miss the {clock(missed, leg.service_day)} {SCHEDULED}"
                        f" ({leg.vehicle})"
                        " and no later one"
                        " leaves within the hour: that trip is left out."
                    )
                    return None, notes
                rest = tuple(t for t in leg.later if t > catchable[0])
                leg = replace(leg, depart=catchable[0], after=rest[0] if rest else None, later=rest)
                notes.append(
                    f"You would miss the {clock(missed, leg.service_day)} {SCHEDULED}"
                    f" ({leg.vehicle}): planned on the {clock(leg.depart, leg.service_day)}"
                    f" {SCHEDULED} instead."
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
    rider gets there, the time to spare and the one after it, as Go shows it."""
    legs = plan.legs
    for index, leg in enumerate(legs):
        if not leg.transit or leg.depart is None:
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
            "source": SCHEDULED,
            "label": (
                f"{leg.system} {clock(leg.depart, plan.when.service_day)} {SCHEDULED}"
                f" · {round(leg.wait_s / 60)} min spare"
            ),
        }
    return None


def label(option: Option, mode: str) -> str:
    """The option in a few words: how it starts, its transit legs, how it ends."""
    if option.direct:
        return "Ride the whole way" if mode == presets.BIKE_TRANSIT else "Bikeshare the whole way"
    if option.walk:
        return "Walk the whole way"
    ends = {RIDE: "ride", TAKE: "bikeshare", SHARE: "bikeshare", WALK: "walk"}
    parts = [ends.get(option.legs[0].mode, "walk")]
    for leg in option.legs:
        if not leg.transit:
            continue
        routes = " or ".join(leg.lines)
        if leg.mode == BUS:
            parts.append(f"bus {routes} to {leg.to}")
        elif routes.lower() in leg.system.lower():
            parts.append(f"{leg.system} to {leg.to}")
        else:
            parts.append(f"{leg.system} to {leg.to} ({routes})")
    parts.append(ends.get(option.legs[-1].mode, "walk"))
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
        return HOLIDAY_WORDS
    day = TYPICAL_HOLIDAY_WORDS.format(day=_typical_doc()["holiday"].capitalize())
    if used <= typical:
        return day
    return f"{day[:-1]}; the others, their holiday timetables."


def _notes(plan: Plan, rules: dict[str, str]) -> list[str]:
    legs = plan.legs
    notes = list(plan.notes)
    if plan.asked is not None:
        notes.insert(0, "The trip chosen is no longer scheduled: the quickest is shown.")
    for leg in legs:
        rule = rules.get(leg.system)
        if leg.transit and leg.bike and rule:
            said = f"{leg.system}: {rule[0].lower()}{rule[1:]}"
            if said not in notes:
                notes.append(said)
    if any(leg.transit for leg in legs):
        notes.append(SCHEDULED_WORDS)
    return notes


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
                # Where a transit step's times are from: "scheduled" (live, from v0.7).
                "source": SCHEDULED if leg.transit else None,
                "with_bike": leg.bike,
                # The route's own line is this step's: the map draws the rest from here.
                "route_line": index == option.ride,
                "coordinates": [_pt(p) for p in leg.coordinates] if index != option.ride else [],
            }
        )
    total_min = minutes(total)
    share = plan.mode == presets.BIKESHARE_TRANSIT
    whole = "Riding a bikeshare bike" if share else "Riding"
    if option.direct:
        how = "by bikeshare" if share else "riding the whole way"
        summary = f"About {total_min} min door to door, {how}."
    elif option.walk:
        summary = f"About {total_min} min door to door, walking."
    else:
        summary = f"About {total_min} min door to door, scheduled."
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
                "chosen": index == plan.chosen,
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
        "bike_blackout": plan.mode == presets.BIKE_TRANSIT and bike_blackout(plan.moment.date),
        "scheduled": option.scheduled,
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
            out["comparison"] = (
                f"{whole} the whole way is quickest: the quickest transit trip is about"
                f" {best_min} min."
            )
        else:
            out["comparison"] = (
                f"{whole} the whole way: about {total_min} min. Transit could save about"
                f" {max(1, total_min - best_min)} min."
            )
    elif option.scheduled and plan.bike_only_s is not None:
        bike_min = minutes(plan.bike_only_s)
        if plan.bike_only_s <= total:
            out["riding_quicker"] = True
            out["comparison"] = (
                f"{whole} the whole way is quicker: about {bike_min} min, against about"
                f" {total_min} min with transit."
            )
        else:
            out["comparison"] = (
                f"{whole} the whole way: about {bike_min} min. Transit saves about"
                f" {max(1, bike_min - total_min)} min."
            )
    return out
