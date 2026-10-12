#!/usr/bin/env python3
"""Compact the region's static GTFS feeds into the transit ride types' schedule (core.transit).

TRANSIT-ASSIST. The API reads one JSON file, `<DATA_ROOT>/tiles/transit/transit-schedule.json`. This
writes it from the GTFS zips `scripts/fetch_transit_gtfs.py` downloads on the host, one per system
in src/core/transitdata/systems.json (WMATA Metro and Metrobus, MARC, Light RailLink, Metro
SubwayLink), and from the Metro stations, entrances and elevators the repository already carries
(frontend/src/rail-data/):

    python3 scripts/build_transit_schedule.py --feeds ~/rmdata/transit \\
        --out "$DATA_ROOT/tiles/transit/transit-schedule.json"

Each system's zip is looked for in `--feeds` by the name systems.json gives it (`feed.file`); a
system whose zip is missing is reported and left out. `--feed SYSTEM=PATH` names one by hand
(a zip or an unzipped folder: the test fixture's form).

What is kept, and nothing else (core.transit's docstring has the method):

- **the service calendar, day by day:** for each service id, which of the `DAYS` days from
  `--date` it runs, read from calendar.txt and calendar_dates.txt as the feed publishes them, so a
  holiday timetable, a weekend with no service and a planned shutdown published as a service
  change are all exact. Past the window a plan says the timetable needs refreshing.
- **stops:** WMATA's Metro stations are the map's 98 (each platform matched to the nearest within
  `MATCH_M`), each with its bike entrance as the map picks it (DC's elevator, else
  OpenStreetMap's, else an entrance; `bike` says whether it is an elevator). Other rail systems'
  stations are their GTFS stations (a platform's parent), `bike` where GTFS says step-free
  (`wheelchair_boarding` 1 on the platform or its station; unknown is no). Bus stops are kept as
  they are, `bike` true (the rack is at the curb).
- **patterns:** per stop order of each route, the median run time from its first stop to each
  later one per band of the service day (core.transit.BANDS), and every trip's departure from the
  first stop by service id, with whether the trip takes a bike (systems.json `bike.vehicle`;
  `trip` reads GTFS `bikes_allowed`).

Times past 24:00 stay on their service day, as GTFS writes them. The file is the agencies' data,
derived: it stays on the host and is never committed (docs/SOURCES.md).

Standard library only, so it runs on the host without the virtualenv. The committed fixture
`tests/data/transit/` holds small synthetic feeds this is tested against.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import statistics
import sys
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RAIL_DATA = REPO / "frontend" / "src" / "rail-data"
SYSTEMS = REPO / "src" / "core" / "transitdata" / "systems.json"
SCHEMA = 2
# core.transit.BANDS, restated so the script needs nothing but the standard library;
# tests/test_transit.py holds the two equal.
BANDS = (
    (180, 360, "early morning"),
    (360, 570, "morning rush"),
    (570, 900, "midday"),
    (900, 1140, "evening rush"),
    (1140, 1320, "evening"),
    (1320, 1800, "late night"),  # to 30:00: owl trips past 27:00 included
)
# The calendar window kept, in days from --date: a fortnight's refresh with room to spare.
DAYS = 45
MATCH_M = 400.0
LINES = ("Red", "Blue", "Orange", "Silver", "Green", "Yellow")
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def distance_m(a, b) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371008.8 * math.asin(math.sqrt(h))


def _round(point) -> list[float]:
    return [round(point[0], 6), round(point[1], 6)]


# --- Metro stations, from the committed rail data -----------------------------------------


def metro_stations(data: Path = RAIL_DATA) -> list[dict]:
    """The map's Metro stations, each with its bike entrance (the map's rule) and entrances."""
    raw = json.loads((data / "metro-stations.geojson").read_text())["features"]
    found = [
        {
            "name": f["properties"]["NAME"],
            "gis_id": f["properties"]["GIS_ID"],
            "point": f["geometry"]["coordinates"][:2],
            "elevators": [],
            "osm_elevators": [],
            "entrances": [],
        }
        for f in raw
    ]
    for f in json.loads((data / "metro-entrances.geojson").read_text())["features"]:
        point = f["geometry"]["coordinates"][:2]
        nearest = min(found, key=lambda s: distance_m(point, s["point"]))
        kind = (
            "elevators"
            if f["properties"]["DESCRIPTION"] == "Metro Station Elevator"
            else "entrances"
        )
        nearest[kind].append(point)
    by_id = {s["gis_id"]: s for s in found}
    for f in json.loads((data / "metro-osm-elevators.geojson").read_text())["features"]:
        station = by_id.get(f["properties"]["station_gis_id"])
        if station is not None:
            station["osm_elevators"].append(f["geometry"]["coordinates"][:2])
    out = []
    for s in sorted(found, key=lambda s: s["name"]):
        entrance, elevator = s["point"], False
        for kind, is_elevator in (
            ("elevators", True),
            ("osm_elevators", True),
            ("entrances", False),
        ):
            if s[kind]:
                entrance = min(s[kind], key=lambda p: distance_m(p, s["point"]))
                elevator = is_elevator
                break
        out.append(
            {
                "name": s["name"],
                "point": _round(s["point"]),
                "bike_entrance": _round(entrance),
                "bike": elevator,
                "entrances": [
                    _round(p) for p in s["elevators"] + s["osm_elevators"] + s["entrances"]
                ]
                or [_round(s["point"])],
            }
        )
    return out


# --- GTFS ---------------------------------------------------------------------------------


class _Folder:
    """An unzipped feed (a folder of .txt files), read as a zip is: the test fixture's form."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def namelist(self) -> list[str]:
        return sorted(p.name for p in self.path.iterdir())

    def open(self, name: str):
        return (self.path / name).open("rb")

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


def open_feed(path: Path):
    return _Folder(path) if path.is_dir() else zipfile.ZipFile(path)


def _rows(feed, name: str):
    if name not in feed.namelist():
        return
    with feed.open(name) as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig"))


def _seconds(value: str | None) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    h, m, s = value.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def service_calendar(feed, start: date, days: int = DAYS) -> dict[str, str]:
    """Each service id that runs in the window: a string of `days` 0s and 1s from `start`."""
    calendar = list(_rows(feed, "calendar.txt"))
    exceptions: dict[str, list[tuple[str, str]]] = {}
    for row in _rows(feed, "calendar_dates.txt"):
        exceptions.setdefault(row["date"], []).append((row["service_id"], row["exception_type"]))
    ids = {row["service_id"] for row in calendar}
    ids |= {sid for rows in exceptions.values() for sid, _e in rows}
    bits = {sid: ["0"] * days for sid in ids}
    for offset in range(days):
        day = start + timedelta(days=offset)
        key = day.strftime("%Y%m%d")
        active = {
            row["service_id"]
            for row in calendar
            if row["start_date"] <= key <= row["end_date"] and row[WEEKDAYS[day.weekday()]] == "1"
        }
        for service, exception in exceptions.get(key, []):
            if exception == "1":
                active.add(service)
            elif exception == "2":
                active.discard(service)
        for service in active:
            bits[service][offset] = "1"
    return {sid: "".join(b) for sid, b in sorted(bits.items()) if "1" in b}


def route_names(feed, metro: bool) -> dict[str, str]:
    out = {}
    for row in _rows(feed, "routes.txt"):
        short = (row.get("route_short_name") or "").strip()
        long = (row.get("route_long_name") or "").strip()
        if metro:
            words = f"{row['route_id']} {short} {long}".lower()
            colour = next((c for c in LINES if c.lower() in words), None)
            out[row["route_id"]] = (
                f"{colour} Line" if colour else (long or short or row["route_id"])
            )
        else:
            out[row["route_id"]] = short or long or row["route_id"]
    return out


def band_index(minute: float) -> int | None:
    for index, (start, end, _name) in enumerate(BANDS):
        if start <= minute < end:
            return index
    return None


def _bike_of(rule: str, row: dict) -> int:
    if rule == "trip":
        return 1 if (row.get("bikes_allowed") or "").strip() == "1" else 0
    return 0 if rule == "none" else 1


def interpolated(rows: list[tuple]) -> list[tuple[int, str, int]]:
    """A trip's stop times with the stops that are not timepoints (blank times, which GTFS
    allows between two timed stops) given times between their timed neighbours: by
    shape_dist_traveled where the feed has it, else evenly by stop. Untimed stops before the first
    timed one or after the last are dropped (nothing to interpolate from)."""
    timed = [i for i, r in enumerate(rows) if r[2] is not None]
    out = []
    for i, (seq, stop_id, seconds, distance) in enumerate(rows):
        if seconds is None:
            before = max((t for t in timed if t < i), default=None)
            after = min((t for t in timed if t > i), default=None)
            if before is None or after is None:
                continue
            a, b = rows[before], rows[after]
            if distance is not None and a[3] is not None and b[3] is not None and b[3] > a[3]:
                share = (distance - a[3]) / (b[3] - a[3])
            else:
                share = (i - before) / (after - before)
            seconds = round(a[2] + (b[2] - a[2]) * min(1.0, max(0.0, share)))
        out.append((seq, stop_id, seconds))
    return out


def patterns(feed, services: dict[str, str], names, stop_key, bike_rule: str) -> list[dict]:
    """Per (route, stop order): median runs per band, and each trip's first departure (minutes
    of the service day, times two, plus 1 where it takes a bike) by service id.

    `stop_key` maps a GTFS stop id to the output's stop index, or None to drop the stop.
    """
    trips = {
        row["trip_id"]: (row["route_id"], row["service_id"], _bike_of(bike_rule, row))
        for row in _rows(feed, "trips.txt")
        if row["service_id"] in services
    }
    times: dict[str, list[tuple[int, str, int]]] = {}
    for row in _rows(feed, "stop_times.txt"):
        trip = row["trip_id"]
        if trip not in trips:
            continue
        seconds = _seconds(row.get("departure_time"))
        if seconds is None:
            seconds = _seconds(row.get("arrival_time"))
        distance = (row.get("shape_dist_traveled") or "").strip()
        times.setdefault(trip, []).append(
            (
                int(row["stop_sequence"]),
                row["stop_id"],
                seconds,
                float(distance) if distance else None,
            )
        )
    repeat: dict[str, list[tuple[int, int, int]]] = {}
    for row in _rows(feed, "frequencies.txt"):
        repeat.setdefault(row["trip_id"], []).append(
            (_seconds(row["start_time"]), _seconds(row["end_time"]), int(row["headway_secs"]))
        )
    # (name, stops) -> {"runs": band -> [runs], "trips": service -> [encoded departures]}
    found: dict[tuple, dict] = {}
    for trip, raw in times.items():
        raw.sort(key=lambda r: r[0])
        rows = interpolated(raw)
        route, service, bike = trips[trip]
        stops, deps = [], []
        for _seq, stop_id, seconds in rows:
            key = stop_key(stop_id)
            if key is None or (stops and stops[-1] == key):
                continue
            stops.append(key)
            deps.append(seconds)
        if len(stops) < 2:
            continue
        runs = [d - deps[0] for d in deps]
        starts = [deps[0]]
        if trip in repeat:
            starts = [t for begin, end, every in repeat[trip] for t in range(begin, end, every)]
        pattern = found.setdefault(
            (names.get(route, route), tuple(stops)), {"runs": {}, "trips": {}}
        )
        for first in starts:
            band = band_index(first / 60)
            if band is not None:
                pattern["runs"].setdefault(band, []).append(runs)
            pattern["trips"].setdefault(service, []).append((first // 60) * 2 + bike)
    out = []
    for (name, stops), found_pattern in sorted(found.items()):
        runs = []
        for index in range(len(BANDS)):
            rows = found_pattern["runs"].get(index)
            runs.append(
                [round(statistics.median(r[i] for r in rows)) for i in range(len(stops))]
                if rows
                else None
            )
        out.append(
            {
                "route": name,
                "stops": list(stops),
                "runs": runs,
                "trips": {
                    sid: sorted(deps) for sid, deps in sorted(found_pattern["trips"].items())
                },
            }
        )
    return out


def _stops(feed) -> dict[str, dict]:
    return {row["stop_id"]: row for row in _rows(feed, "stops.txt")}


def _point(row) -> tuple[float, float]:
    return (float(row["stop_lon"]), float(row["stop_lat"]))


def _step_free(row: dict, parent: dict | None) -> bool:
    own = (row.get("wheelchair_boarding") or "").strip()
    if own == "0" or own == "":
        own = ((parent or {}).get("wheelchair_boarding") or "").strip()
    return own == "1"


class _Stops:
    """The output's stop list, shared by every system."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, row: dict) -> int:
        self.rows.append(row)
        return len(self.rows) - 1


def metro_stop_key(feed, stops: _Stops, system: int, report: list[str], data: Path):
    """WMATA's platforms, matched to the map's stations by position."""
    first = len(stops.rows)
    for station in metro_stations(data):
        stops.add({**station, "system": system})
    station_rows = stops.rows[first:]
    rows = _stops(feed)
    keys: dict[str, int | None] = {}
    for stop_id, row in rows.items():
        parent = rows.get(row.get("parent_station") or "", row)
        point = _point(parent)
        index, best = min(
            ((i, distance_m(point, s["point"])) for i, s in enumerate(station_rows)),
            key=lambda t: t[1],
        )
        if best <= MATCH_M:
            keys[stop_id] = first + index
        else:
            keys[stop_id] = None
            if row.get("location_type", "0") in ("", "0"):
                report.append(
                    f"metro stop {stop_id} ({row.get('stop_name')}) matches no map station"
                )
    return keys.get


def station_stop_key(feed, stops: _Stops, system: int):
    """A rail system's stations: each platform goes to its parent station."""
    rows = _stops(feed)
    keys: dict[str, int] = {}
    entrances: dict[str, list] = {}
    for row in rows.values():
        if row.get("location_type") == "2" and row.get("parent_station"):
            entrances.setdefault(row["parent_station"], []).append(_round(_point(row)))
    for stop_id, row in sorted(rows.items()):
        if row.get("location_type", "0") not in ("", "0"):
            continue
        parent_id = row.get("parent_station") or ""
        parent = rows.get(parent_id)
        station_id = parent_id if parent else stop_id
        if station_id not in keys:
            place = parent or row
            point = _round(_point(place))
            keys[station_id] = stops.add(
                {
                    "name": (place.get("stop_name") or "").strip(),
                    "point": point,
                    "bike_entrance": point,
                    "bike": _step_free(row, parent),
                    "entrances": entrances.get(station_id) or [point],
                    "system": system,
                }
            )
        elif _step_free(row, parent):
            stops.rows[keys[station_id]]["bike"] = True
        keys[stop_id] = keys[station_id]
    return keys.get


def bus_stop_key(feed, stops: _Stops, system: int):
    keys: dict[str, int] = {}
    for stop_id, row in sorted(_stops(feed).items()):
        if row.get("location_type", "0") not in ("", "0"):
            continue
        point = _round(_point(row))
        keys[stop_id] = stops.add(
            {
                "name": (row.get("stop_name") or "").strip(),
                "point": point,
                "bike_entrance": point,
                "bike": True,
                "entrances": [point],
                "system": system,
            }
        )
    return keys.get


def _source(path: Path) -> dict:
    files = sorted(path.iterdir()) if path.is_dir() else [path]
    digest = hashlib.sha256()
    for file in files:
        digest.update(file.read_bytes())
    return {
        "file": path.name,
        "bytes": sum(f.stat().st_size for f in files),
        "sha256": digest.hexdigest(),
    }


def load_systems(path: Path = SYSTEMS) -> list[dict]:
    return json.loads(path.read_text())["systems"]


def build(
    feeds: dict[str, Path], start: date, data: Path = RAIL_DATA, systems_path: Path = SYSTEMS
) -> tuple[dict, list[str]]:
    report: list[str] = []
    stops = _Stops()
    systems, services, all_patterns = [], [], []
    for config in load_systems(systems_path):
        path = feeds.get(config["id"])
        if path is None:
            report.append(f"{config['id']}: no feed given, left out")
            continue
        system = len(systems)
        with open_feed(path) as feed:
            calendar = service_calendar(feed, start)
            if not calendar:
                report.append(f"{config['id']}: no service in the {DAYS} days from {start}")
            first_service = len(services)
            index = {sid: first_service + i for i, sid in enumerate(calendar)}
            services.extend({"system": system, "days": bits} for bits in calendar.values())
            if config.get("stations") == "wmata-map":
                key = metro_stop_key(feed, stops, system, report, data)
            elif config["mode"] == "bus":
                key = bus_stop_key(feed, stops, system)
            else:
                key = station_stop_key(feed, stops, system)
            found = patterns(
                feed,
                calendar,
                route_names(feed, metro=config.get("stations") == "wmata-map"),
                key,
                config["bike"]["vehicle"],
            )
        for pattern in found:
            pattern["system"] = system
            pattern["trips"] = {str(index[sid]): deps for sid, deps in pattern["trips"].items()}
        all_patterns.extend(found)
        if not found:
            report.append(f"{config['id']}: no patterns")
        systems.append(
            {
                **{k: config[k] for k in ("id", "name", "operator", "mode", "words", "credit")},
                "idle_notes": config.get("idle_notes", False),
                "bike": config["bike"],
                "source": _source(path),
            }
        )
    # Only the stops a pattern uses, renumbered.
    used = sorted({s for p in all_patterns for s in p["stops"]})
    renumber = {old: new for new, old in enumerate(used)}
    for pattern in all_patterns:
        pattern["stops"] = [renumber[s] for s in pattern["stops"]]
    doc = {
        "schema": SCHEMA,
        "built": datetime.now().astimezone().isoformat(timespec="seconds"),
        "bands": [list(b) for b in BANDS],
        "start": start.isoformat(),
        "days": DAYS,
        "systems": systems,
        "services": services,
        "stops": [stops.rows[old] for old in used],
        "patterns": all_patterns,
    }
    return doc, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--feeds", type=Path, help="the folder the fetch script wrote")
    parser.add_argument(
        "--feed", action="append", default=[], metavar="SYSTEM=PATH", help="one feed by hand"
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        default=date.today(),
        help="the first service day kept (default today)",
    )
    args = parser.parse_args(argv)
    feeds: dict[str, Path] = {}
    if args.feeds is not None:
        for config in load_systems():
            path = args.feeds / config["feed"]["file"]
            if path.exists():
                feeds[config["id"]] = path
    for item in args.feed:
        system, _sep, path = item.partition("=")
        feeds[system] = Path(path)
    doc, report = build(feeds, args.date)
    for line in report:
        print(f"warning: {line}", file=sys.stderr)
    if not doc["patterns"]:
        print("no patterns were found: nothing written", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, separators=(",", ":")))
    tmp.replace(args.out)
    print(
        f"wrote {args.out}: {', '.join(s['id'] for s in doc['systems'])};"
        f" {len(doc['stops'])} stops, {len(doc['patterns'])} patterns,"
        f" {len(doc['services'])} services, {DAYS} days from {args.date}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
