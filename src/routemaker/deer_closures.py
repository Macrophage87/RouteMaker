"""The parks' deer-management closures, as "Check before you go" notices on the routes they meet.

The owner, 2026-10-25, of the NPS record of determination for Rock Creek Park's deer
management: "Put this notice in the park though for some routes. Unfortunately the language is
not particularly strong, so it's not an absolute block. 'These areas may be closed'"; then of
Montgomery Parks' deer schedule, "Montgomery parks has one too"; and "Make sure it's only for
the duration of the closure." So each closure is a notice (`dc_closures.Notice`), never routed
round, shown only on a route that runs along the closed roads or trails (`runs_along`) at a
ride time inside one of its windows (`in_force`):

- **Rock Creek Park** (NPS; `ROCK_CREEK_URL`). Bingham Drive, Sherrill Drive and three car-free
  stretches of Beach Drive "may also [be] closed to pedestrians, bicyclists and non-motorized
  recreation from 6:45 p.m. to 4 a.m.", every night of the season. The record covers Nov 10,
  2025 to Mar 31, 2026; NPS had not posted the 2026-27 one when this was written, and the owner
  chose (2026-10-25) to assume the same dates again, said as expected (`ROCK_CREEK_SEASONS`).
  The roads it closes to cars only are left out: bicycles may still use them.
- **Montgomery Parks** (`MOCO_URL`, "Fall 2026 - Winter 2027"). Park Police sharpshooting:
  "Parks and Trails Closed, January 15 - March 31 from Sunset - Sunrise, Monday-Friday", at
  the parks of `SHARPSHOOTING`. Firearms hunts: "Parks are CLOSED for 24 hours on each
  scheduled date" (`FIREARMS`). Archery hunts close nothing and are left out; so is Goshen
  Recreation Park's year-round tenant hunting, which gives no dates.

The closed ways are in `src/core/geodata/deer-closures.geojson` (scripts/build_deer_closures.py:
OpenStreetMap's roads and paths, a park's paths chosen by Montgomery Parks' own boundary). A
park's public roads are never part of its closure.

Pure: no network, no database. `core.workzones.snapshot` adds `notices(now)` to the snapshot.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path

from . import dc_closures as dc
from .ridetime import ZONE

GEODATA = Path(__file__).resolve().parents[1] / "core" / "geodata" / "deer-closures.geojson"

ROCK_CREEK_URL = (
    "https://www.nps.gov/rocr/learn/management/record-of-determination-for-the-temporary-closure"
    "-of-certain-park-roads-and-park-areas-for-the-2025-2026-implementation-of-the-rock-creek-park"
    "-white-tailed-deer-management-plan.htm"
)
MOCO_URL = "https://montgomeryparks.org/deer-population-management-schedule-locations/"

NPS, MOCO = "nps_deer", "mcparks"
# Their names are `workzones.SOURCES`'.
SOURCES = frozenset({NPS, MOCO})

# A ride that starts this long before a window opens may still be riding when it does.
LEAD = timedelta(hours=1)
# How far ahead the windows are made: past the plan dial's next representative day.
AHEAD_DAYS = 15
# A route is on a closure where at least this much of it lies within `NEAR_M` of a closed way;
# a road it only crosses is not.
NEAR_M = 15.0
ALONG_MIN_M = 100.0
_STEP_M = 10.0
_CELL_M = 30.0
_LAT0 = 39.0

# (first night, last night, posted by NPS). The owner, 2026-10-25, chose "Assume Nov 10 to Mar
# 31 again" until NPS posts this winter's record.
ROCK_CREEK_SEASONS = (
    (date(2025, 11, 10), date(2026, 3, 31), True),
    (date(2026, 11, 10), date(2027, 3, 31), False),
)
ROCK_CREEK_HOURS = (time(18, 45), time(4, 0))

SHARPSHOOTING_SEASON = (date(2027, 1, 15), date(2027, 3, 31))

# area key: the park's name, as Montgomery Parks lists it (Northwest Golf Course is left out: its
# cart paths are closed to bicycles all year, #351). The keys are the geodata file's
# (`moco-` and the park's code in Montgomery Parks' Park Units layer).
SHARPSHOOTING = {
    "moco-K01": "Agricultural History Farm Park",
    "moco-P55": "Rock Creek Stream Valley Park Unit 15",
    "moco-P56": "Rock Creek Stream Valley Park Unit 16",
    "moco-F06": "Layhill Local Park",
    "moco-H02": "Martin Luther King Jr. Recreational Park",
    "moco-G08": "Northwest Branch Recreational Park",
    "moco-P35": "Northwest Branch Stream Valley Park Unit 4",
    "moco-D57": "Kemp Mill Estates Local Park",
    "moco-P37": "Northwest Branch Stream Valley Park Unit 7",
    "moco-L07": "Ovid Hazen Wells Recreational Park",
    "moco-P39": "Paint Branch Stream Valley Park Unit 5",
    "moco-P40": "Paint Branch Stream Valley Park Unit 6",
    # "with attached neighborhood, local, and special parks"
    "moco-B43": "Paint Branch Neighborhood Park",
    "moco-D88": "Pilgrim Hill Local Park",
    "moco-B55": "Tamarack Neighborhood Park",
    "moco-L05": "Valley Mill Special Park",
    "moco-K08": "Red Door Store Historical Cultural Park",
    "moco-P61": "Sligo Creek Stream Valley Park Unit 5",
    "moco-B75": "Colt Terrace Neighborhood Park",
    "moco-G12": "Wheaton Regional Park",
    "moco-K03": "Woodlawn Cultural Park",
}

FIREARMS_PARKS = {
    "moco-S15": "Hoyles Mill Conservation Park",
    "moco-S20": "Bennett Creek Conservation Park",
    "moco-L14": "Woodstock Equestrian Park",
    "moco-G09": "Rachel Carson Conservation Park",
    "moco-G07": "Black Hill Regional Park, 10 Mile Creek segment",
    "moco-S12": "Bucklodge Forest Conservation Park",
    "moco-S21": "Royce Hanson Conservation Park",
    "moco-G06": "Little Bennett Regional Park",
}
_BLACK_HILL = ("moco-G07", "moco-S12")  # hunted together: "10 Mile Creek Segment & Bucklodge"
FIREARMS = {
    "moco-S15": ("2026-10-08", "2026-10-31", "2026-11-12", "2026-11-21", "2026-12-03",
                 "2026-12-19", "2027-01-07", "2027-01-23"),
    "moco-S20": ("2026-10-10", "2026-11-07", "2026-12-17", "2027-01-09"),
    "moco-L14": ("2026-10-16", "2026-11-05", "2026-11-19", "2026-12-05", "2027-01-02"),
    "moco-G09": ("2026-10-27", "2026-11-03", "2026-11-17", "2026-12-01"),
    _BLACK_HILL: ("2026-10-29", "2026-11-14", "2026-12-11", "2027-01-16"),
    "moco-S21": ("2026-12-02", "2026-12-30", "2027-01-06"),
    "moco-G06": ("2026-12-08", "2026-12-09", "2026-12-15", "2026-12-16", "2026-12-18"),
}  # fmt: skip

ROCK_CREEK_AREA = "rocr-deer"
ROCK_CREEK_NAME = "Rock Creek Park"


# --- The sun ------------------------------------------------------------------------


def sun_times(day: date, lat: float = _LAT0, lon: float = -77.1) -> tuple[datetime, datetime]:
    """Sunrise and sunset on `day` (NOAA's sunrise equation, to a minute or two), as aware UTC
    times."""
    n = (day - date(2000, 1, 1)).days - lon / 360.0  # the local solar noon, days after J2000
    m = math.radians((357.5291 + 0.98560028 * n) % 360)
    c = 1.9148 * math.sin(m) + 0.02 * math.sin(2 * m) + 0.0003 * math.sin(3 * m)
    ecl = math.radians((math.degrees(m) + c + 180 + 102.9372) % 360)
    transit = n + 0.0053 * math.sin(m) - 0.0069 * math.sin(2 * ecl)
    dec = math.asin(math.sin(ecl) * math.sin(math.radians(23.44)))
    phi = math.radians(lat)
    cos_w = (math.sin(math.radians(-0.833)) - math.sin(phi) * math.sin(dec)) / (
        math.cos(phi) * math.cos(dec)
    )
    half = math.degrees(math.acos(max(-1.0, min(1.0, cos_w)))) / 360.0
    noon = datetime(2000, 1, 1, 12, tzinfo=UTC)
    return noon + timedelta(days=transit - half), noon + timedelta(days=transit + half)


# --- The windows --------------------------------------------------------------------


@dataclass(frozen=True)
class Window:
    area: str
    source: str
    start: datetime
    end: datetime
    expected: bool = False


def _local(day: date, at: time) -> datetime:
    return datetime.combine(day, at, tzinfo=ZONE).astimezone(UTC)


def _days(first: date, last: date):
    day = first
    while day <= last:
        yield day
        day += timedelta(days=1)


def windows(first: date, last: date) -> list[Window]:
    """Every closure window that starts on a day from `first` to `last` (the region's days)."""
    found: list[Window] = []
    opens, closes = ROCK_CREEK_HOURS
    for season_first, season_last, posted in ROCK_CREEK_SEASONS:
        for day in _days(max(first, season_first), min(last, season_last)):
            found.append(
                Window(
                    ROCK_CREEK_AREA,
                    NPS,
                    _local(day, opens),
                    _local(day + timedelta(days=1), closes),
                    expected=not posted,
                )
            )
    season_first, season_last = SHARPSHOOTING_SEASON
    for day in _days(max(first, season_first), min(last, season_last)):
        if day.weekday() > 4:  # Monday to Friday nights
            continue
        sunset = sun_times(day)[1]
        sunrise = sun_times(day + timedelta(days=1))[0]
        found += [Window(area, MOCO, sunset, sunrise) for area in SHARPSHOOTING]
    for areas, days in FIREARMS.items():
        for text in days:
            day = date.fromisoformat(text)
            if first <= day <= last:
                start, end = _local(day, time(0)), _local(day + timedelta(days=1), time(0))
                for area in areas if isinstance(areas, tuple) else (areas,):
                    found.append(Window(area, MOCO, start, end))
    return found


def first_each(notices: list[dc.Notice]) -> list[dc.Notice]:
    """One notice an area: the earliest, so back-to-back hunt days are not said twice."""
    kept: dict[str, dc.Notice] = {}
    for n in sorted(notices, key=lambda n: n.start or datetime.min.replace(tzinfo=UTC)):
        kept.setdefault(n.area, n)
    return list(kept.values())


def moments(notices) -> set[datetime]:
    """When a deer notice starts or stops being in force for a ride now: a route cached
    across one of these must be planned again (`core.route_cache`)."""
    return {
        m
        for n in notices
        if n.source in SOURCES and n.start is not None and n.end is not None
        for m in (n.start - LEAD, n.end)
    }


def in_force(notice: dc.Notice, at: datetime) -> bool:
    """Whether a ride at `at` meets the notice's window: inside it, or starting at most `LEAD`
    before it opens."""
    if notice.start is None or notice.end is None:
        return False
    return notice.start - LEAD <= at < notice.end


# --- The words ----------------------------------------------------------------------


def _name(area: str) -> str:
    if area == ROCK_CREEK_AREA:
        return ROCK_CREEK_NAME
    return SHARPSHOOTING.get(area) or FIREARMS_PARKS[area]


def notice(window: Window) -> dc.Notice:
    if window.source == NPS:
        title = "Beach Dr, Bingham Dr and Sherrill Dr may close to bikes at night"
        text = (
            "Deer management: these car-free roads may be closed to bikes and walkers 6:45 pm "
            "to 4 am, Nov 10 to Mar 31."
        )
        if window.expected:
            text += " Dates expected from last winter's notice; NPS has not posted this one yet."
        url = ROCK_CREEK_URL
    elif (window.end - window.start) >= timedelta(hours=23):
        title = f"{_name(window.area)} closed all day for a deer hunt"
        text = "Montgomery Parks closes the park and its trails for 24 hours on each hunt date."
        url = MOCO_URL
    else:
        title = f"{_name(window.area)} closed at night for deer management"
        text = (
            "Montgomery Parks closes the park and its trails sunset to sunrise, Monday to Friday "
            "nights, Jan 15 to Mar 31."
        )
        url = MOCO_URL
    return dc.Notice(
        notice_id=f"deer-{window.area}-{window.start.astimezone(ZONE).date().isoformat()}",
        source=window.source,
        title=title,
        text=text,
        url=url,
        area=window.area,
        start=window.start,
        end=window.end,
        category="Deer management",
    )


def notices(now: datetime) -> list[dc.Notice]:
    """The notices for the windows from yesterday (a night still going) to `AHEAD_DAYS` on."""
    today = now.astimezone(ZONE).date()
    return [
        notice(w)
        for w in windows(today - timedelta(days=1), today + timedelta(days=AHEAD_DAYS))
        if w.end > now
    ]


# --- Where -------------------------------------------------------------------------


def _xy(lon: float, lat: float) -> tuple[float, float]:
    k = math.pi / 180 * 6_371_008.8
    return lon * k * math.cos(math.radians(_LAT0)), lat * k


@dataclass(frozen=True)
class _Ways:
    lines: tuple[tuple[tuple[float, float], ...], ...]
    samples: dict
    box: tuple[float, float, float, float]


def _sample(line_xy, step: float):
    out = [line_xy[0]]
    for a, b in zip(line_xy, line_xy[1:], strict=False):
        n = max(1, int(math.dist(a, b) // step))
        out += [
            (a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(1, n + 1)
        ]
    return out


@lru_cache(maxsize=1)
def ways() -> dict[str, _Ways]:
    """Each area's closed ways, with a grid of points along them for `runs_along`."""
    if not GEODATA.exists():
        return {}
    found = {}
    for feature in json.loads(GEODATA.read_text())["features"]:
        lines = tuple(
            tuple((float(p[0]), float(p[1])) for p in line)
            for line in feature["geometry"]["coordinates"]
            if len(line) >= 2
        )
        if not lines:
            continue
        samples: dict[tuple[int, int], list] = {}
        for line in lines:
            for p in _sample([_xy(*q) for q in line], _STEP_M / 2):
                samples.setdefault((int(p[0] // _CELL_M), int(p[1] // _CELL_M)), []).append(p)
        lons = [p[0] for line in lines for p in line]
        lats = [p[1] for line in lines for p in line]
        key = feature["properties"]["area"]
        found[key] = _Ways(lines, samples, (min(lons), min(lats), max(lons), max(lats)))
    return found


def _point(w: _Ways) -> tuple[float, float]:
    """The marker: the middle of the area's longest line."""

    def length(line) -> float:
        return sum(math.dist(_xy(*a), _xy(*b)) for a, b in zip(line, line[1:], strict=False))

    longest = max(w.lines, key=length)
    return longest[len(longest) // 2]


@lru_cache(maxsize=1)
def areas() -> dict[str, dc.Area]:
    url = {**dict.fromkeys(SHARPSHOOTING, MOCO_URL), **dict.fromkeys(FIREARMS_PARKS, MOCO_URL)}
    url[ROCK_CREEK_AREA] = ROCK_CREEK_URL
    return {
        key: dc.Area(_name(key), _point(w), (w.box,), url[key])
        for key, w in ways().items()
        if key in url
    }


def runs_along(area: str, coordinates: Sequence[Sequence[float]]) -> bool:
    """Whether at least `ALONG_MIN_M` of the route lies within `NEAR_M` of the area's ways."""
    w = ways().get(area)
    if w is None or len(coordinates) < 2:
        return False
    west, south, east, north = w.box
    pad = 0.001
    near_m = 0.0
    for a, b in zip(coordinates, coordinates[1:], strict=False):
        if max(a[0], b[0]) < west - pad or min(a[0], b[0]) > east + pad:
            continue
        if max(a[1], b[1]) < south - pad or min(a[1], b[1]) > north + pad:
            continue
        pa, pb = _xy(a[0], a[1]), _xy(b[0], b[1])
        length = math.dist(pa, pb)
        pieces = _sample([pa, pb], _STEP_M)
        each = length / max(1, len(pieces) - 1)
        for p in pieces[1:]:
            cx, cy = int(p[0] // _CELL_M), int(p[1] // _CELL_M)
            if any(
                math.dist(p, q) <= NEAR_M
                for dx in (-1, 0, 1)
                for dy in (-1, 0, 1)
                for q in w.samples.get((cx + dx, cy + dy), ())
            ):
                near_m += each
                if near_m >= ALONG_MIN_M:
                    return True
    return False


# How near an assumed season's first night, or the last night in these tables, is a reminder
# (audit 2026-10-29: the tables run out in March with nothing to prompt next season's dates,
# and the assumed Rock Creek season is never checked against NPS's own record).
ASSUMED_WARN_DAYS = 14
TABLES_WARN_DAYS = 30


def check_due(today: date) -> list[str]:
    """What to check in the schedules above (`scripts/ddot_advisories.py watch` prints them):
    an assumed Rock Creek season starting within `ASSUMED_WARN_DAYS`, and the tables' last
    night within `TABLES_WARN_DAYS` (or past)."""
    out = [
        f"Deer closures: Rock Creek's {first.year}-{last.year % 100:02d} season is assumed and"
        f" starts {first.isoformat()}; confirm it against NPS's record"
        for first, last, posted in ROCK_CREEK_SEASONS
        if not posted and today <= first <= today + timedelta(days=ASSUMED_WARN_DAYS)
    ]
    final = max(
        [last for _first, last, _posted in ROCK_CREEK_SEASONS]
        + [SHARPSHOOTING_SEASON[1]]
        + [date.fromisoformat(day) for days in FIREARMS.values() for day in days]
    )
    if final <= today + timedelta(days=TABLES_WARN_DAYS):
        out.append(f"Deer closures: the schedules end {final.isoformat()}; add next season's dates")
    return out


__all__ = [
    "MOCO",
    "NPS",
    "SOURCES",
    "Window",
    "areas",
    "check_due",
    "first_each",
    "in_force",
    "moments",
    "notice",
    "notices",
    "runs_along",
    "sun_times",
    "windows",
]
