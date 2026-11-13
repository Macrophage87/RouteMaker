#!/usr/bin/env python3
"""RouteMaker's routing engine as an MCP server, for any assistant that speaks MCP (the owner,
2026-10-18: "Make me a 100 mile route that goes around DC using low stress roads and doesn't stray
more than 5 miles from a metro station"; "other users might use different models").

A thin client of a RouteMaker site's own HTTP API: it plans with POST /api/route and finds places
with GET /api/geocode. On a rider's own computer it keeps a route as a GPX file; saving to My
routes is the site's own connector's (core.connector, /mcp), which signs the rider in (the owner,
2026-10-25, retiring the save-only key: "the old method with the random token, we should take it
out"). It never talks to the router directly, so every route it answers
is one the site would plan. Metro distances are read from the station file the map bundles
(frontend/src/rail-data/metro-stations.geojson, DC Open Data, CC BY 4.0) and are straight-line.

Standard library only, so it runs on any Python 3.11 or later with nothing to install. It
speaks MCP over stdio (newline-delimited JSON-RPC 2.0), which Claude Desktop and Claude Code
both launch as a local server. See mcp/README.md.

Configuration, all from the environment:
- ROUTEMAKER_BASE_URL: the site, e.g. http://localhost for a local stack. Required.
- ROUTEMAKER_ROUTES_DIR: where GPX files are written. Default ~/RouteMaker-routes.
- ROUTEMAKER_METRO_STATIONS: the station file. Default: the one in this checkout.
"""

from __future__ import annotations

import base64
import bisect
import contextvars
import dataclasses
import itertools
import json
import math
import os
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

SERVER_NAME = "routemaker"
SERVER_VERSION = "0.26.0"
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

METRES_PER_MILE = 1609.344
FEET_PER_METRE = 3.28084
EARTH_RADIUS_MI = 3958.7613

# The middle of DC, the default centre a loop goes around (the Zero Milestone, Ellipse).
DC_CENTRE = (-77.0365, 38.8949)
# The site's own limits (core/api.py MAX_POINTS, COVERAGE_BBOX).
MAX_POINTS = 25
MAX_DRAFTS = 200  # drafts kept in memory
# A draft's name: what the rider finds it by in the app's Load route and in my_drafts.
DRAFT_NAME_SCHEMA = {
    "type": "string",
    "minLength": 1,
    "maxLength": 120,
    "description": (
        "A short name the rider will find this draft by in the app's Load route and in"
        ' my_drafts, such as "Round trip to the sandwich shop". Default: the named start and'
        " end, else a revision keeps its draft's name."
    ),
}
# A call that only tests or checks RouteMaker, not one for the rider (the owner, 2026-11-12:
# "When a test route is made from an agent, it somehow keeps loading on my account in beta.
# Archive them when done."): its drafts are archived as they are made, never listed in the app's
# Load route or my_drafts, and go after a week as every draft does.
TEST_SCHEMA = {
    "type": "boolean",
    "description": (
        "true when this plan only tests or checks RouteMaker and is not a route the rider asked"
        " for: the draft is archived at once (kept out of the rider's Load route and my_drafts,"
        " gone in a week). Default false."
    ),
}
# Set while a call with `test` runs (Server.call): the draft stores archive what they keep.
TEST_CALL: contextvars.ContextVar[bool] = contextvars.ContextVar("TEST_CALL", default=False)
# The tools that take `test` (a revision of an archived route stays archived on its own).
TEST_TOOLS = ("plan_route", "plan_metro_loop", "open_link")
PLAN_BUDGET_S = 48  # the longest one plan can take: the site's long-plan budget, and a little
# Another plan starts while one more as long as the longest timed so far, by this factor and
# these seconds over, still fits before the call's deadline (as _best_order always has; the
# round 4 hunt, L4-4). Claude's defaults, not measured: they are _best_order's.
PLAN_TIME_FACTOR = 1.5
PLAN_TIME_SPARE_S = 5
OUT_OF_TIME = (
    "stopped there to answer inside the site's time limit; to fix where it strays, add the"
    " station named in metro_check as a via point (revise_route add_points), or move its points"
)
COVERAGE_BBOX = (-78.05, 38.2, -76.02, 39.72)
# A long ride's plan may take the site's whole long budget (core/routing.py LONG_PLAN_BUDGET_S,
# 50 s) after a wait for its one long slot.
ROUTE_TIMEOUT_S = 120

# How long one tools/call waits, in all its lookups, for the site's busy answers (429, or a 503
# "busy") to clear before it gives up with `Busy`: an assistant that sends three calls at once
# shares the rider's one place search slot (core.ratelimit GEOCODE_IN_FLIGHT) and its five a
# second (GEOCODE_BURST), so the second and third wait their turn instead of being refused. Kept
# short, since on the site a waiting call holds its web worker asleep (the site keeps workers
# free within about a second; three calls at once wait about one search each). Our default,
# unmeasured.
LOOKUP_WAIT_S = 4.0
# The longest single pause between tries, whatever the Retry-After says, the shortest, and the
# most added at random so calls sent together do not knock together again. Our defaults,
# unmeasured.
LOOKUP_PAUSE_MAX_S = 1.0
LOOKUP_PAUSE_MIN_S = 0.2
LOOKUP_JITTER_MS = 200
# The tools/call running in this thread (Server.call), so lookups share one wait and stop at its
# deadline or cancellation.
CURRENT_CALL: contextvars.ContextVar = contextvars.ContextVar("CURRENT_CALL", default=None)
# How much longer a planned loop is than its ring in straight lines, for a first guess at the
# ring's radius; the loop is then rescaled by what the router answered. Calmer settings wind
# more: a 100 mi loop at stress 80 came out about 2.0 times its ring (tester, 2026-10-19).
ROAD_FACTOR = 1.3
CALM_ROAD_FACTOR = 2.0


def road_factor(stress: int | None) -> float:
    """ROAD_FACTOR up to stress 70 (Default), CALM_ROAD_FACTOR from 80, scaled in between."""
    share = min(1.0, max(0.0, ((stress if stress is not None else 70) - 70) / 10))
    return ROAD_FACTOR + share * (CALM_ROAD_FACTOR - ROAD_FACTOR)


# The site plans at most 200 km (124 mi) of straight lines between points (core/api.py
# MAX_SPAN_M); a loop's ring is kept a little under it.
MAX_SPAN_MI = 124
LOOP_SPAN_MI = 120
# Every ride type the site plans (frontend/src/lib/presets.ts; the owner, 2026-10-18: "Allow the
# MCP server to pick whatever mode makes sense for this and to adjust any parameters"). The
# bikeshare and transit ride types take a start and an end only.
PRESETS = (
    "default",
    "trailmaxxing",
    "novice",
    "group-ride",
    "mass-ride",
    "mountain-goat",
    "mountain-bike",
    "gravel",
    "fast",
    "road-bike",
    "cargo",
    # Tandem (2026-11-08): a bicycle built for two (core/presets.py TANDEM).
    "tandem",
    "ebike",
    "bikeshare",
    "rebalance",
    "bike-transit",
    "bikeshare-transit",
    # Walk and Walk + 🚆🚌 (2026-11-02): on foot, a start and an end.
    "walk",
    "walk-transit",
    # Run (2026-11-02): on foot, trails first, loops (core/run_plan.py).
    "run",
)
TWO_POINT_PRESETS = (
    "bikeshare",
    "rebalance",
    "bike-transit",
    "bikeshare-transit",
    "walk",
    "walk-transit",
)
KG_PER_LB = 0.45359237
# Densify the route line to this spacing for the Metro check, so a long straight segment
# cannot hide a stretch past the limit between its two vertices.
CHECK_STEP_MI = 0.1
# Ring waypoints closer than this to each other add nothing but a point to the plan.
MIN_GAP_MI = 2.0


class ToolError(Exception):
    """A refusal to show the model as the tool's answer, not a protocol error."""


class Busy(ToolError):
    """The site was busy with the rider's other calls for longer than a lookup waits: nothing is
    wrong with the request. `retry_after_s`: when to send it again."""

    def __init__(self, what: str, retry_after_s: int):
        self.retry_after_s = max(1, int(retry_after_s))
        super().__init__(
            f"{what} is busy with this rider's other calls (retry_after_s: {self.retry_after_s});"
            f" send the same call again in {self.retry_after_s} s. Nothing is wrong with the"
            " request."
        )


def finite(value) -> float:
    """A number argument as a float; "inf", "nan" and their like are not in the expected form."""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{value!r} is not a finite number")
    return number


# --- Geometry -------------------------------------------------------------------------------


def haversine_mi(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MI * math.asin(min(1.0, math.sqrt(h)))


def bearing_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    y = math.sin(lon2 - lon1) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def destination(origin: tuple[float, float], bearing: float, miles: float) -> tuple[float, float]:
    lon1, lat1 = map(math.radians, origin)
    d = miles / EARTH_RADIUS_MI
    b = math.radians(bearing)
    lat2 = math.asin(math.sin(lat1) * math.cos(d) + math.cos(lat1) * math.sin(d) * math.cos(b))
    lon2 = lon1 + math.atan2(
        math.sin(b) * math.sin(d) * math.cos(lat1), math.cos(d) - math.sin(lat1) * math.sin(lat2)
    )
    return (round(math.degrees(lon2), 5), round(math.degrees(lat2), 5))


def inside_coverage(point: tuple[float, float]) -> bool:
    west, south, east, north = COVERAGE_BBOX
    return west <= point[0] <= east and south <= point[1] <= north


def miles_text(metres: float) -> str:
    """US first, metric in brackets (OWNER-DECISIONS 85)."""
    return f"{metres / METRES_PER_MILE:.1f} mi ({metres / 1000:.1f} km)"


def feet_text(metres: float) -> str:
    return f"{metres * FEET_PER_METRE:,.0f} ft ({metres:,.0f} m)"


# Below this a distance is said in feet (and metres), as the page's `formatDistance` does
# (frontend/src/lib/format.ts FEET_BELOW_M): a tenth of a mile, where "0.1 mi" or "0.0 mi"
# would stop saying anything.
FEET_BELOW_M = METRES_PER_MILE / 10


def distance_text(metres: float) -> str:
    """A distance as the page's `formatDistance` gives it: "4.7 mi (7.6 km)", and below a
    tenth of a mile "105 ft (32 m)", rounded as its `roundShort` does (to ten from 100 up)."""
    if metres >= FEET_BELOW_M:
        return miles_text(metres)

    def short(value: float) -> int:
        # Halves round up, as JavaScript's Math.round does (Python's round goes to even).
        return math.floor(value / 10 + 0.5) * 10 if value >= 100 else math.floor(value + 0.5)

    return f"{short(metres * FEET_PER_METRE):,} ft ({short(metres):,} m)"


# --- Metro stations -------------------------------------------------------------------------


@dataclass(frozen=True)
class Station:
    name: str
    lines: str
    lon: float
    lat: float
    # Where a ride with a bike goes in (`station_entrances`); None where no way in is known.
    entrance: tuple[float, float] | None = None

    @property
    def point(self) -> tuple[float, float]:
        """DC GIS's station point: what straight-line distances to the station are measured
        from (the Metro check, the nearest station). It is the platform's middle, up to 190 m
        from any way in and some in a freeway median (Vienna, Dunn Loring, Innovation Center),
        so a route never goes to it: a route goes to `way_in`."""
        return (self.lon, self.lat)

    # Every bike way in of the station's kind (`station_entrances`), `entrance` first.
    ways_in: tuple[tuple[float, float], ...] = ()

    @property
    def way_in(self) -> tuple[float, float]:
        """The point a route to or through the station goes to with nothing to go by: its bike
        entrance where one is known, as the transit planner takes it, else the station point."""
        return self.entrance if self.entrance is not None else self.point

    def way_in_from(self, start: tuple[float, float] | None) -> tuple[float, float]:
        """The bike way in nearest `start`, where the leg comes from, as the map takes it
        (railStations.ts `bikeEntrance(station, from)`; the owner, 2026-10-20, at Shady Grove:
        "Somehow it missed one of the metro entrances"); `way_in` with no `start`. The Silver
        Line's stations sit in a freeway median with an elevator on each side, and the one
        nearest the platform is across the toll road from half the rides (Herndon's north
        pavilion from Reston, the second 2026-11-08 hunt, P1). The app then asks the router
        which is quickest (lib/stationWayIn.ts); this takes the nearest in a straight line."""
        if start is None or not self.ways_in:
            return self.way_in
        return min(self.ways_in, key=lambda p: haversine_mi(start, p))

    def is_way_in(self, point: tuple[float, float]) -> bool:
        """Whether `point` is one of the station's bike ways in (or its `way_in`)."""
        return tuple(point) == self.way_in or tuple(point) in self.ways_in


def default_stations_path() -> Path:
    return Path(__file__).resolve().parents[1] / "frontend/src/rail-data/metro-stations.geojson"


# DC's entrance points are all well within this of their station; one farther off is not
# trusted (frontend/src/lib/railStations.ts ENTRANCE_REACH_M).
ENTRANCE_REACH_M = 600.0


def _features(path: Path) -> list[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("features", [])
    except FileNotFoundError:
        return []


def station_entrances(stations_path: Path, rows: list[dict]) -> dict:
    """{GIS_ID: ((lon, lat), ...)}: each station's bike ways in, by the rule the map and the
    transit planner use (railStations.ts `bikeWaysIn` and `bikeEntrance`,
    scripts/build_transit_schedule.py `metro_stations`): DC's elevators first (the owner,
    2026-09-27: the elevator is where a bike gets in), else OpenStreetMap's elevators, else
    the other entrances; nearest the station's own point first. Read from
    metro-entrances.geojson and metro-osm-elevators.geojson beside the station file. A station
    with none is left out, and a station file with neither beside it gives none at all, so a
    route goes to the station point as it did before (issue #39)."""
    here = stations_path.parent
    found = {
        r["gis_id"]: {"point": r["point"], "elevators": [], "osm": [], "entrances": []}
        for r in rows
    }
    for f in _features(here / "metro-entrances.geojson"):
        point = tuple(f["geometry"]["coordinates"][:2])
        near = min(found.values(), key=lambda s: haversine_mi(point, s["point"]), default=None)
        if near is None or haversine_mi(point, near["point"]) * METRES_PER_MILE > ENTRANCE_REACH_M:
            continue
        description = str(f.get("properties", {}).get("DESCRIPTION", ""))
        near["elevators" if "elevator" in description.lower() else "entrances"].append(point)
    for f in _features(here / "metro-osm-elevators.geojson"):
        station = found.get(f.get("properties", {}).get("station_gis_id"))
        if station is not None:
            station["osm"].append(tuple(f["geometry"]["coordinates"][:2]))
    out = {}
    for gis_id, s in found.items():
        for kind in ("elevators", "osm", "entrances"):
            if s[kind]:
                ways = sorted(s[kind], key=lambda p, s=s: haversine_mi(p, s["point"]))
                out[gis_id] = tuple((round(p[0], 6), round(p[1], 6)) for p in ways)
                break
    return out


def load_stations(path: str | os.PathLike | None = None) -> list[Station]:
    path = Path(path or os.environ.get("ROUTEMAKER_METRO_STATIONS") or default_stations_path())
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for feature in data.get("features", []):
        lon, lat = feature["geometry"]["coordinates"][:2]
        props = feature.get("properties", {})
        rows.append(
            {
                "gis_id": props.get("GIS_ID"),
                "name": props.get("NAME", "?"),
                "lines": props.get("LINE", ""),
                "point": (lon, lat),
            }
        )
    if not rows:
        raise ToolError(f"no Metro stations in {path}")
    entrances = station_entrances(path, rows)
    out = []
    for r in rows:
        ways = entrances.get(r["gis_id"], ())
        out.append(
            Station(
                r["name"],
                r["lines"],
                *r["point"],
                entrance=ways[0] if ways else None,
                ways_in=ways,
            )
        )
    return out


def nearest_station(point: tuple[float, float], stations: list[Station]) -> tuple[Station, float]:
    best = min(stations, key=lambda s: haversine_mi(point, s.point))
    return best, haversine_mi(point, best.point)


def densified(line: list[list[float]], step_mi: float = CHECK_STEP_MI):
    """(point, miles along) for each vertex, with points added on any longer segment."""
    along = 0.0
    previous = None
    for vertex in line:
        point = (vertex[0], vertex[1])
        if previous is not None:
            seg = haversine_mi(previous, point)
            pieces = int(seg // step_mi)
            for i in range(1, pieces + 1):
                t = i * step_mi / seg
                if t >= 1:
                    break
                mid = (
                    previous[0] + (point[0] - previous[0]) * t,
                    previous[1] + (point[1] - previous[1]) * t,
                )
                yield mid, along + seg * t
            along += seg
        yield point, along
        previous = point


def metro_check(line: list[list[float]], limit_mi: float, stations: list[Station]) -> dict:
    """How far the route ever is from a Metro station in a straight line, and the stretches
    past `limit_mi`, in miles along the route's own line."""
    worst = (0.0, None, None, 0.0)  # miles, point, station, along
    stretches: list[dict] = []
    current = None
    for point, along in densified(line):
        station, miles = nearest_station(point, stations)
        if miles > worst[0]:
            worst = (miles, point, station, along)
        if miles > limit_mi:
            if current is None:
                current = {
                    "from_mi": along,
                    "to_mi": along,
                    "max_mi": miles,
                    "at": point,
                    "nearest_station": station.name,
                }
            current["to_mi"] = along
            if miles > current["max_mi"]:
                current.update(max_mi=miles, at=point, nearest_station=station.name)
        elif current is not None:
            stretches.append(current)
            current = None
    if current is not None:
        stretches.append(current)
    for s in stretches:
        s["from_mi"] = round(s["from_mi"], 1)
        s["to_mi"] = round(s["to_mi"], 1)
        s["max_mi"] = round(s["max_mi"], 2)
        s["at"] = [round(s["at"][0], 5), round(s["at"][1], 5)]
    miles, point, station, along = worst
    return {
        "limit_mi": limit_mi,
        "ok": not stretches,
        "farthest_mi": round(miles, 2),
        "farthest_at": None if point is None else [round(point[0], 5), round(point[1], 5)],
        "farthest_at_mile": round(along, 1),
        "farthest_nearest_station": None if station is None else station.name,
        "stretches_over_limit": stretches,
        "miles_over_limit": round(sum(s["to_mi"] - s["from_mi"] for s in stretches), 1),
        "measured": "straight line from each point of the route to the nearest Metrorail station",
    }


# --- The site's API -------------------------------------------------------------------------


def retry_after(headers, default: float = 1.0) -> float:
    """A busy answer's Retry-After in seconds (urllib's headers, a dict or Django's response)."""
    try:
        return float((headers.get("Retry-After") if headers is not None else None) or default)
    except (TypeError, ValueError):
        return default


def patient_request(
    api, method: str, path: str, body=None, what: str = "the site", fresh_kw=None, **kw
):
    """`api._request`, trying again while the site answers busy (429, or 503 other than a long
    ride out of time), each pause its Retry-After (clamped to LOOKUP_PAUSE_MIN_S..
    LOOKUP_PAUSE_MAX_S, plus up to LOOKUP_JITTER_MS). The call's lookups share LOOKUP_WAIT_S in
    all, and none waits past the call's deadline or after it is cancelled. Raises `Busy` when
    the wait would run past that. `fresh_kw`: a function giving keyword arguments worked out
    again for each try (the site's own budget, counted from when it is asked). A plain function,
    not an `Api` method, so the site's in-process api (core.connector.InProcessApi) uses it too."""
    call = CURRENT_CALL.get()
    waited = [0.0] if call is None else call.lookup_waited
    while True:
        extra = fresh_kw() if fresh_kw else {}
        status, payload, headers = api._request(method, path, body, **kw, **extra)
        code = payload.get("code") if isinstance(payload, dict) else None
        if not (status == 429 or (status == 503 and code != "long_ride_timed_out")):
            return status, payload, headers
        asked = retry_after(headers)
        pause = min(LOOKUP_PAUSE_MAX_S, max(LOOKUP_PAUSE_MIN_S, asked))
        pause += secrets.randbelow(LOOKUP_JITTER_MS) / 1000
        late = call is not None and call.deadline is not None
        if (
            asked > LOOKUP_WAIT_S
            or waited[0] + pause > LOOKUP_WAIT_S
            or (late and time.monotonic() + pause > call.deadline)
        ):
            raise Busy(what, math.ceil(asked))
        time.sleep(pause)
        waited[0] += pause
        if call is not None:
            call.check()


class Api:
    def __init__(self, base_url: str | None = None):
        base = (base_url or os.environ.get("ROUTEMAKER_BASE_URL") or "").strip().rstrip("/")
        if not base:
            raise ToolError(
                "ROUTEMAKER_BASE_URL is not set: give the MCP server the site's address, e.g."
                " http://localhost for the local stack (mcp/README.md)."
            )
        if not re.match(r"^https?://", base):
            raise ToolError("ROUTEMAKER_BASE_URL must start with http:// or https://")
        self.base = base
        # A site behind a password (the beta's nginx gate): "user:password", sent on every request,
        # so only over https, or plain http to this computer.
        basic = os.environ.get("ROUTEMAKER_BASIC_AUTH", "")
        self.basic = "Basic " + base64.b64encode(basic.encode()).decode() if ":" in basic else None
        host = (urllib.parse.urlsplit(base).hostname or "").lower()
        local = host in ("localhost", "127.0.0.1", "::1") or host.endswith(".localhost")
        if self.basic and base.startswith("http://") and not local:
            raise ToolError(
                "ROUTEMAKER_BASIC_AUTH is set but ROUTEMAKER_BASE_URL is plain http: use the site's"
                " https:// address (plain http only for localhost)."
            )

    def _request(self, method: str, path: str, body=None, headers=None, timeout=30):
        data = None if body is None else json.dumps(body, separators=(",", ":")).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method)
        request.add_header("Accept", "application/json")
        request.add_header("User-Agent", f"routemaker-mcp/{SERVER_VERSION}")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if self.basic:
            request.add_header("Authorization", self.basic)
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                try:
                    payload = json.loads(response.read() or b"null")
                except ValueError:
                    # A wrong address, or a sign-in or captive page answering 200: a setup problem,
                    # not the assistant's arguments.
                    raise ToolError(
                        f"{self.base} did not answer as a RouteMaker site (not JSON);"
                        " check ROUTEMAKER_BASE_URL"
                    ) from None
                return response.status, payload, response.headers
        except urllib.error.HTTPError as error:
            try:
                payload = json.loads(error.read() or b"null")
            except ValueError:
                payload = None
            return error.code, payload, error.headers
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise ToolError(f"could not reach {self.base}: {error}") from None

    def route(self, body: dict) -> dict:
        """POST /api/route, waiting out one busy answer (a 429, or a 503 that is not a long
        ride that ran out of time) for its Retry-After, up to 30 s."""
        for attempt in range(2):
            status, payload, headers = self._request(
                "POST", "/api/route", body, timeout=ROUTE_TIMEOUT_S
            )
            if status == 200 and isinstance(payload, dict):
                return payload
            message = (payload or {}).get("error") if isinstance(payload, dict) else None
            code = (payload or {}).get("code") if isinstance(payload, dict) else None
            busy = status == 429 or (status == 503 and code != "long_ride_timed_out")
            if busy and attempt == 0:
                try:
                    wait = float(headers.get("Retry-After", "5"))
                except (TypeError, ValueError):
                    wait = 5.0
                time.sleep(min(30.0, max(1.0, wait)))
                continue
            if code == "long_ride_timed_out":
                raise ToolError(
                    f"the site ran out of time planning this long ride ({message}). Try fewer"
                    " points, a lower stress setting, or plan it in two halves."
                )
            raise ToolError(refusal(status, message or payload))
        raise Busy("The route planner", math.ceil(retry_after(headers, 5.0)))

    def geocode(self, query: str, near: tuple[float, float] | None = None) -> list[dict]:
        params = {"q": query, "limit": 5}
        if near:
            params.update(lon=near[0], lat=near[1])
        status, payload, _ = patient_request(
            self, "GET", "/api/geocode?" + urllib.parse.urlencode(params), what="Place search"
        )
        if status != 200 or not isinstance(payload, dict):
            message = payload.get("error") if isinstance(payload, dict) else payload
            raise ToolError(f"place search failed ({status}): {message}")
        return payload.get("results", [])

    def scenic_roads(
        self, near: tuple[float, float], miles: float, designation: str = ""
    ) -> list[dict]:
        """GET /api/scenic-roads: the designated roads near a point, nearest first."""
        params = {"lon": near[0], "lat": near[1], "miles": miles}
        if designation:
            params["designation"] = designation
        status, payload, _ = patient_request(
            self,
            "GET",
            "/api/scenic-roads?" + urllib.parse.urlencode(params),
            what="The scenic road search",
        )
        if status != 200 or not isinstance(payload, dict):
            message = payload.get("error") if isinstance(payload, dict) else payload
            raise ToolError(f"the scenic road search failed ({status}): {message}")
        return payload.get("roads", [])

    def climbs_near(self, near: tuple[float, float], miles: float, **filters) -> list[dict]:
        """GET /api/climbs-near: the categorised climbs near a point, nearest first, or
        steepest first with `steepest`; `filters` as the endpoint takes them."""
        params = {"lon": near[0], "lat": near[1], "miles": miles}
        params.update({k: str(v).lower() if isinstance(v, bool) else v for k, v in filters.items()})
        status, payload, _ = patient_request(
            self,
            "GET",
            "/api/climbs-near?" + urllib.parse.urlencode(params),
            what="The climb search",
        )
        if status != 200 or not isinstance(payload, dict):
            message = payload.get("error") if isinstance(payload, dict) else payload
            raise ToolError(f"the climb search failed ({status}): {message}")
        return payload.get("climbs", [])

    def reach(self, body: dict) -> dict:
        """POST /api/reach: the reach rings (isochrones) for points, a ride type and its dials."""
        status, payload, _ = patient_request(
            self, "POST", "/api/reach", body, what="Reach", timeout=ROUTE_TIMEOUT_S
        )
        if status != 200 or not isinstance(payload, dict):
            message = payload.get("error") if isinstance(payload, dict) else payload
            raise ToolError(f"the reach rings could not be drawn ({status}): {message}")
        return payload

    def nearest(self, body: dict) -> dict:
        """POST /api/nearest: riding time and distance from the first point to each other
        one, on the ride type's own graph and dials (one matrix row)."""
        status, payload, _ = patient_request(
            self, "POST", "/api/nearest", body, what="Riding times", timeout=ROUTE_TIMEOUT_S
        )
        if status != 200 or not isinstance(payload, dict):
            message = payload.get("error") if isinstance(payload, dict) else payload
            raise ToolError(f"the riding times could not be found ({status}): {message}")
        return payload

    def closures_map(self, box: tuple[float, float, float, float], permits: bool) -> list[dict]:
        """GET /api/closures/map: the closures in force now with any part in the box."""
        params = {"bbox": ",".join(f"{v:.5f}" for v in box), "permits": str(permits).lower()}
        status, payload, _ = patient_request(
            self,
            "GET",
            "/api/closures/map?" + urllib.parse.urlencode(params),
            what="The closure search",
        )
        if status != 200 or not isinstance(payload, dict):
            message = payload.get("error") if isinstance(payload, dict) else payload
            raise ToolError(f"the closure search failed ({status}): {message}")
        return payload.get("closures", [])

    def shared_route(self, route_id: str) -> dict:
        """A shared route as it was shared: its exact line, answer and plan inputs (GET
        /api/shared-routes/{id}, public)."""
        status, payload, _ = self._request(
            "GET", "/api/shared-routes/" + urllib.parse.quote(route_id, safe="")
        )
        if status != 200 or not isinstance(payload, dict):
            message = payload.get("error") if isinstance(payload, dict) else payload
            raise ToolError(f"that shared route could not be opened ({status}): {message}")
        return payload

    def shared_fragment(self, route_id: str) -> str:
        """A shared route's plan link fragment."""
        fragment = (self.shared_route(route_id).get("inputs") or {}).get("hash") or ""
        if not has_plan_points(fragment):
            raise ToolError("that shared route keeps no plan to continue from (an opened file?)")
        return fragment

    def share(self, body: dict) -> str:
        """Keep the exact route under a new link id (POST /api/shared-routes, as the app's Share
        does); the id."""
        status, payload, _ = self._request("POST", "/api/shared-routes", body)
        if status != 201:
            message = payload.get("error") if isinstance(payload, dict) else payload
            raise ToolError(f"the exact route was not kept ({status}): {message}")
        return body["id"]

    def weather_check(self, points: list[list[float]]) -> dict:
        """POST /api/weather/check: the NWS alerts in force along the ride and the first point
        where rain is forecast as the rider gets there. The site rounds the points and keeps
        nothing (core.weather)."""
        status, payload, _ = self._request("POST", "/api/weather/check", {"points": points})
        if status != 200 or not isinstance(payload, dict):
            message = payload.get("error") if isinstance(payload, dict) else payload
            raise ToolError(f"the weather check failed ({status}): {message}")
        return payload

    def saved_routes(self) -> list[dict]:
        """GET /api/me/routes: the signed-in rider's saved routes (names and figures only)."""
        status, payload, _ = self._request("GET", "/api/me/routes")
        if status in (401, 403):
            raise ToolError(
                "My routes is read only through RouteMaker's own connector, signed in"
                " (Settings > Connectors in the assistant app); here, paste the route's link"
                " into open_link"
            )
        if status != 200 or not isinstance(payload, dict):
            message = payload.get("error") if isinstance(payload, dict) else payload
            raise ToolError(f"My routes could not be read ({status}): {message}")
        return payload.get("routes") or []

    def change_route(self, route_id: int, change: dict) -> dict:
        """PATCH /api/me/routes/{id}: tag, archive or restore one of the rider's saved routes.
        Only RouteMaker's own connector is signed in; here the site refuses it."""
        status, payload, _ = self._request("PATCH", f"/api/me/routes/{int(route_id)}", change)
        if status in (401, 403):
            raise ToolError(
                "My routes is organized only through RouteMaker's own connector, signed in"
                " (Settings > Connectors in the assistant app), or in the app's Load route"
            )
        if status != 200 or not isinstance(payload, dict):
            message = payload.get("error") if isinstance(payload, dict) else payload
            raise ToolError(f"that saved route was not changed ({status}): {message}")
        return payload

    def saved_route(self, route_id: int) -> dict:
        """GET /api/me/routes/{id}: one of the rider's saved routes, with its line and answer."""
        status, payload, _ = self._request("GET", f"/api/me/routes/{int(route_id)}")
        if status != 200 or not isinstance(payload, dict):
            message = payload.get("error") if isinstance(payload, dict) else payload
            raise ToolError(f"that saved route could not be opened ({status}): {message}")
        return payload


# --- Points, links and files ----------------------------------------------------------------


# Spellings riders use for the words station names shorten.
SHORT_WORDS = {
    "place": "pl",
    "square": "sq",
    "street": "st",
    "avenue": "ave",
    "mount": "mt",
    "university": "u",
}


def _station_words(text: str) -> str:
    words = re.sub(r"[^a-z0-9 ]+", " ", text.lower().replace("'", "")).split()
    return " ".join(SHORT_WORDS.get(w, w) for w in words)


_SAID_STATION = re.compile(r"( metro| station| metro station)+$")
# The last words of a road's name (after SHORT_WORDS): a station named for its road (Braddock
# Road, King St-Old Town, Minnesota Ave) is taken for the station only when "Metro" or
# "station" is said, since the road itself is what a rider more often means.
ROAD_WORDS = frozenset(
    {"road", "rd", "st", "ave", "boulevard", "blvd", "pike", "parkway", "pkwy", "highway"}
    | {"hwy", "drive", "dr", "lane", "ln", "way"}
)


def _one(stations: list[Station], tests) -> Station | None:
    for test in tests:
        fits = [s for s in stations if test(s)]
        if len(fits) == 1:
            return fits[0]
        if fits:
            return None
    return None


def find_station(text: str, stations: list[Station]) -> Station | None:
    """The one Metro station `text` names for certain, so it is taken without a place search:
    said with "Metro" or "station" after it (its whole name, its first part, or the start of
    it: "Navy Yard Metro", "Ronald Reagan station"), or its whole name where that can be
    nothing else: a name of several parts said in full ("Navy Yard-Ballpark") or one ending in
    Station or Airport ("Union Station"). None otherwise, and when more than one station fits
    ("Farragut Metro"), so the text goes to place search (`station_said`).

    Before the 2026-11-08 hunt (G2) a bare first part or start was taken too, so "Mount Vernon"
    went to Mt Vernon Sq, 12.7 mi from the estate, and "Arlington", "Reston", "Vienna" and
    "Braddock Road" to stations rather than the town or the road."""
    said = _station_words(text)
    bare = _SAID_STATION.sub("", said).strip()
    if bare and bare != said:
        return _one(
            stations,
            (
                lambda s: _station_words(s.name) == bare,
                lambda s: _station_words(re.split(r"[-/]", s.name)[0]) == bare,
                lambda s: _station_words(s.name).startswith(bare + " "),
            ),
        )
    return _one(
        stations,
        (
            lambda s: (
                _station_words(s.name) == said
                and (
                    re.search(r"[-/]", s.name) is not None
                    or said.split()[-1] in ("station", "airport")
                )
            ),
        ),
    )


def station_said(text: str, stations: list[Station]) -> Station | None:
    """The station a bare name may mean (its whole name or its first part: "Navy Yard",
    "Gallery Place", "Rockville"), which a place search must confirm (`as_point`); never a
    name that ends in a road's word, nor the mere start of a name ("Mount Vernon" is not Mt
    Vernon Sq, nor "Arlington" Arlington Cemetery). Later parts such as "Adams Morgan" are
    neighbourhoods, left to place search."""
    said = _SAID_STATION.sub("", _station_words(text)).strip()
    if not said or said.split()[-1] in ROAD_WORDS:
        return None
    return _one(
        stations,
        (
            lambda s: _station_words(s.name) == said,
            lambda s: _station_words(re.split(r"[-/]", s.name)[0]) == said,
            # The start of a name only from three words ("Mount Vernon Square" for Mt Vernon
            # Sq 7th St-Convention Center): two ("Mount Vernon") or one ("Arlington") are as
            # often a place of their own.
            lambda s: len(said.split()) >= 3 and _station_words(s.name).startswith(said + " "),
        ),
    )


# A place search's first match this close to a station a bare name may mean (`station_said`)
# confirms it: the search found the station, or a neighbourhood the station stands in. Farther,
# the name meant the town, the museum or the road (Vienna, Rockville, Smithsonian).
STATION_CONFIRM_MI = 0.25
# A place search match tagged as a rail station this close to a Metro station is that station
# (railStations.ts STATION_MATCH_M, 300 m).
STATION_MATCH_MI = 300 / METRES_PER_MILE


def is_rail_station(row: dict) -> bool:
    """A place search row that is a station (railStations.ts `stationForPlace`'s test)."""
    return row.get("osm_key") in ("railway", "public_transport") and row.get("osm_value") in (
        "station",
        "halt",
    )


# Matches of one place search farther apart than this are different places.
SAME_PLACE_MI = 5.0

# An area's way in, as the site's search takes it (src/core/geocode.py AREA_TAGS,
# ARRIVAL_TAGS and ARRIVAL_WORDS, the 2026-11-08 hunt G1 and G5): a park, refuge, campus or
# battlefield is one point at its middle in the search, which the router snaps to whatever
# road is nearest, often a busy one or a dead end, when a calm gate was a few hundred metres
# off. The site's search moves such a match to a way in it found (and says so in `way_in`);
# this takes one from the same search where the site did not (an older site).
AREA_KEYS = frozenset({"leisure", "boundary", "landuse", "historic", "natural", "tourism"})
AREA_AMENITIES = frozenset({"university", "college", "school", "hospital"})
# No tourism=information, as the site's search (geocode.ARRIVAL_TAGS): a notice board or a
# trail map as often as a visitor centre, which still counts by its name (the second
# 2026-11-08 hunt, P2).
ARRIVAL_TAGS = frozenset(
    {
        ("amenity", "parking"),
        ("amenity", "bicycle_parking"),
        ("amenity", "ranger_station"),
        ("highway", "trailhead"),
        ("leisure", "slipway"),
        ("barrier", "gate"),
        ("entrance", "main"),
        ("entrance", "yes"),
    }
)
ARRIVAL_WORDS = re.compile(
    r"\b(visitor('?s)? (center|centre)|nature (center|centre)|entrance|gate|parking|trailhead"
    r"|boat (launch|ramp))\b",
    re.IGNORECASE,
)
AREA_WAY_IN_MI = 3.0


def is_area(row: dict) -> bool:
    """A search match that is an area kept as its middle: a way or relation that is a park, a
    reserve, a campus, a battlefield (not a road, a town or a building's point)."""
    if row.get("way_in") or row.get("osm_type") not in ("W", "R"):
        return False
    key = row.get("osm_key")
    if key == "amenity":
        return row.get("osm_value") in AREA_AMENITIES
    if key == "boundary":
        return row.get("osm_value") in ("protected_area", "national_park")
    return key in AREA_KEYS


def is_arrival(row: dict) -> bool:
    """A match that is where a visit starts: a visitor centre, an entrance or gate, parking,
    a trailhead or a boat launch."""
    return (row.get("osm_key"), row.get("osm_value")) in ARRIVAL_TAGS or bool(
        ARRIVAL_WORDS.search(str(row.get("name") or ""))
    )


def named_for(own: str, name: str) -> bool:
    """Whether a match named `own` is named for the area `name` by whole words, as the site's
    search (geocode.named_for): "Rock Creek Parkway Parking" is not Rock Creek Park's (the
    second 2026-11-08 hunt, P3)."""
    own, name = own.casefold(), name.casefold()
    return len(own) > len(name) > 0 and own.startswith(name) and not own[len(name)].isalnum()


def way_in_of(chosen: dict, found: list[dict], near: tuple[float, float] | None = None) -> dict:
    """`chosen`, or where an area is gone into: a match of the same search named for it
    ("Occoquan Regional Park Boat Launch", "Great Falls Park Visitor Center") that is a way
    in (`is_arrival`) within AREA_WAY_IN_MI; the one nearest `near` (the route's neighbouring
    point) where given, else the search's first, as the site's search takes the one nearest
    its bias (the second 2026-11-08 hunt, P4). The row comes back with the area's name and
    its `way_in` said, so the label still names what the rider asked for."""
    if not is_area(chosen):
        return chosen
    name = str(chosen.get("name") or "")
    here = (chosen["lon"], chosen["lat"])
    ways = [
        r
        for r in found
        if r is not chosen
        and not is_area(r)
        and named_for(str(r.get("name") or ""), name)
        and is_arrival(r)
        and haversine_mi(here, (r["lon"], r["lat"])) <= AREA_WAY_IN_MI
    ]
    if not ways:
        return chosen
    if near is not None:
        ways.sort(key=lambda r: haversine_mi(near, (r["lon"], r["lat"])))
    r = ways[0]
    return {**chosen, "lon": r["lon"], "lat": r["lat"], "way_in": r.get("name")}


def nearby_points(chosen: dict, found: list[dict], most: int = 4) -> list[dict]:
    """The other matches of one place search near the one taken, under other names (a boat
    launch, a visitor centre, a second gate): pick_place takes one, and the assistant is told
    of these so it can offer them (the 2026-11-08 hunt G5: matches within SAME_PLACE_MI were
    one place and the rest were never said)."""
    here = (chosen["lon"], chosen["lat"])
    names = {str(chosen.get("name") or "").casefold(), str(chosen.get("way_in") or "").casefold()}
    out = []
    for r in found:
        if str(r.get("name") or "").casefold() in names:
            continue
        if haversine_mi(here, (r["lon"], r["lat"])) <= SAME_PLACE_MI:
            out.append(r)
    return out[:most]


# Photon's `type` for a town, village or neighbourhood (core/geocode.py PLACE_KINDS).
PLACE_KINDS = frozenset({"city", "district", "locality"})
# State words a place name may end with after its town ("Fairfax VA", "Urbana, Maryland").
STATE_WORDS = ("va", "md", "dc", "virginia", "maryland", "district of columbia", "d.c.")


def _state_dropped(part: str) -> str:
    part = " ".join(part.casefold().split())
    for state in STATE_WORDS:
        if part == state:
            return ""
        if part.endswith(" " + state):
            return part[: -len(state) - 1].strip()
    return part


def place_rank(text: str, r: dict) -> tuple[bool, bool, bool]:
    """How well a match answers `text`, best first (the routing hunt 4, G4-1): a town,
    village or neighbourhood named just what was typed before the comma ("Leesburg, VA" is
    the town, not the Leesburg Pike or the clinic nearer the route), then any match named
    just that, then one whose label names the town typed after the comma ("Old Town
    Fairfax, Fairfax VA" is Old Town Hall, Fairfax, not Wiehle Town Hall, Reston). The order
    is Claude's default, not measured against the live index."""
    lead, _, rest = text.partition(",")
    lead = " ".join(lead.casefold().split())
    towns = {t for t in (_state_dropped(p) for p in rest.split(",")) if t}
    name = " ".join(str(r.get("name") or "").casefold().split())
    town = r.get("kind") in PLACE_KINDS or r.get("osm_key") == "place"
    where = {" ".join(p.casefold().split()) for p in str(r.get("label") or "").split(",")[1:]}
    return (not (name == lead and town), name != lead, not (towns & where))


def pick_place(text: str, found: list[dict], neighbours: list[tuple[float, float]]) -> tuple:
    """The match of a place search to take for `text`, and the other places it could have
    been ([] where it could be nothing else). One place, wherever it is, is taken. Where the
    matches are different places (Moore Road in Boyds, MD and in Centreville, VA), the first
    within NEAR_PLACE_MI of one of the route's other points (`neighbours`) is taken, and where
    none is the answer is a question back; with no other points to go by, the first match.
    Among the near ones, a town named what was typed, then a match named it, then one in the
    town typed after the comma comes before the search's nearer streets (`place_rank`)."""
    if not found:
        raise ToolError(f"no place found for {text!r}")
    # An area is gone into by its way in nearest the route's nearest point (`way_in_of`).
    beside = neighbours[0] if neighbours else None
    first = (found[0]["lon"], found[0]["lat"])
    if all(haversine_mi(first, (r["lon"], r["lat"])) <= SAME_PLACE_MI for r in found):
        return way_in_of(found[0], found, beside), []

    if not neighbours:
        # Nothing to go by (the first of the route's names): the search's own first match,
        # with the others said.
        return way_in_of(found[0], found), [
            r for r in found if haversine_mi(first, (r["lon"], r["lat"])) > SAME_PLACE_MI
        ]

    def away(r) -> float:
        here = (r["lon"], r["lat"])
        return min(haversine_mi(here, n) for n in neighbours) if neighbours else math.inf

    near = sorted((r for r in found if away(r) <= NEAR_PLACE_MI), key=lambda r: place_rank(text, r))
    if near:
        chosen = near[0]
        here = (chosen["lon"], chosen["lat"])
        others = [r for r in found if haversine_mi(here, (r["lon"], r["lat"])) > SAME_PLACE_MI]
        return way_in_of(chosen, found, beside), others
    listed = "; ".join(
        f"{r['label']} [{r['lon']:.5f}, {r['lat']:.5f}]"
        + f", {away(r):.0f} mi from the route's other points"
        for r in found
    )
    raise ToolError(
        f"{text!r} matches more than one place and none is near the route's other points:"
        f" {listed}. Ask the rider which one they mean (or add the town to the name), then"
        " send it as [lon, lat]."
    )


def as_point(
    value,
    api: Api | None,
    stations: list[Station],
    neighbours: list[tuple[float, float]] | None = None,
    others: list | None = None,
    nearby: list | None = None,
) -> tuple[tuple[float, float], str]:
    """A point from [lon, lat], {"lon", "lat"}, a Metro station's name or a place to search
    for, with a label saying what it was taken as. A place name is searched near the route's
    other points (`neighbours`), and taken as `pick_place` says; the other places it could have
    been go in `others`, and the other points of the same place the search found (an
    entrance, a boat launch) in `nearby`.

    A station is gone to at its bike entrance (`Station.way_in`, issue #39), the one nearest
    `neighbours[0]` where given (`Station.way_in_from`), as the map goes. A bare name that may
    be a station (`station_said`: "Navy Yard", "Vienna") is the station only where the place
    search finds it there; otherwise it is the place the search found (the town of Vienna, not
    the station in the I-66 median)."""
    if isinstance(value, dict) and "lon" in value and "lat" in value:
        value = [value["lon"], value["lat"]]
    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            point = (float(value[0]), float(value[1]))
        except (TypeError, ValueError):
            raise ToolError(f"not a [lon, lat] pair: {value!r}") from None
        if not inside_coverage(point):
            raise ToolError(
                f"{list(point)} is outside the map's area (or lat and lon are swapped: send"
                " [lon, lat])"
            )
        return point, f"{point[1]:.5f}, {point[0]:.5f}"
    if isinstance(value, str) and value.strip():
        text = value.strip()
        # The route's point nearest this one in the list (`_neighbours`: the one before, or
        # for a start the one after, as the app's legFrom): a station is gone to at its way
        # in nearest it (`Station.way_in_from`).
        neighbours = list(neighbours or [])
        near = neighbours[0] if neighbours else None
        station = find_station(text, stations)
        if station is not None:
            return station.way_in_from(near), f"{station.name} Metro"
        maybe = station_said(text, stations)
        if api is None:
            if maybe is not None:
                return maybe.way_in_from(near), f"{maybe.name} Metro"
            raise ToolError(f"cannot search for {text!r} without the site")
        found = [r for r in api.geocode(text, near) if inside_coverage((r["lon"], r["lat"]))]
        if maybe is not None and (
            not found
            or haversine_mi((found[0]["lon"], found[0]["lat"]), maybe.point) <= STATION_CONFIRM_MI
        ):
            return maybe.way_in_from(near), f"{maybe.name} Metro"
        chosen, elsewhere = pick_place(text, found, neighbours)
        if others is not None:
            others.extend(elsewhere)
        if is_rail_station(chosen):
            # The search found a Metro station (by another of its names): its bike entrance,
            # as the map puts a searched station (railStations.ts `stationForPlace`).
            at, miles = nearest_station((chosen["lon"], chosen["lat"]), stations)
            if miles <= STATION_MATCH_MI:
                return at.way_in_from(near), f"{at.name} Metro"
        if nearby is not None:
            nearby.extend(nearby_points(chosen, found))
        label = chosen["label"]
        if chosen.get("way_in"):
            label = f"{label}, at {chosen['way_in']}"
        return (round(chosen["lon"], 5), round(chosen["lat"], 5)), label
    raise ToolError(f"not a point: {value!r}")


# The ride types whose link is a live ride (frontend/src/lib/rideGroup.ts `isRideLinkType`). Every
# ride link carries its ride's key (the owner, 2026-10-29: "All rides should have a key."): 16
# random bytes, base64url without padding (22 characters; an older link's 43 still open), as the
# fragment's `k=` (frontend/src/lib/rideSeal.ts).
RIDE_LINK_TYPES = ("mass-ride", "group-ride")
RIDE_KEY_RE = re.compile(r"[A-Za-z0-9_-]{22}|[A-Za-z0-9_-]{43}")


def new_ride_key() -> str:
    """A ride's key as rideSeal.ts `newRideSecret` makes one."""
    return base64.urlsafe_b64encode(secrets.token_bytes(16)).rstrip(b"=").decode("ascii")


def ride_key_of(fragment: str) -> str | None:
    """The ride key a link's fragment carries (rideSeal.ts `secretFrom`), or None."""
    values = urllib.parse.parse_qs(str(fragment or "").lstrip("#")).get("k") or []
    return values[0] if values and RIDE_KEY_RE.fullmatch(values[0]) else None


def with_ride_key(fragment: str, key: str | None) -> str:
    """The fragment with `key` as its `k=` (rideSeal.ts `withSecret`), replacing any it had;
    None takes it out."""
    lead = "#" if fragment.startswith("#") else ""
    params = [p for p in fragment.lstrip("#").split("&") if p and not p.startswith("k=")]
    if key:
        params.append(f"k={key}")
    return lead + "&".join(params)


def without_ride_marks(fragment: str) -> str:
    """The fragment without a ride's key, its ride mark or its leader (`k=`, `ride=`, `lead=`):
    a route kept in My routes is a plan, and each ride opened from it is a new ride."""
    lead = "#" if fragment.startswith("#") else ""
    marks = ("k=", "ride=", "lead=")
    return lead + "&".join(
        p for p in fragment.lstrip("#").split("&") if p and not p.startswith(marks)
    )


def ride_key_for(preset: str, key: str | None) -> str | None:
    """A ride type's key: the one it had (`key`), else a new one; none for a ride type whose
    link is not a live ride."""
    if preset not in RIDE_LINK_TYPES:
        return None
    return key if isinstance(key, str) and RIDE_KEY_RE.fullmatch(key) else new_ride_key()


STOP_NAME_MAX = 40  # pointKinds.ts STOP_NAME_MAX


def clean_stop_name(name) -> str | None:
    """A stop's name as the page keeps it (pointKinds.ts `cleanStopName`): spaces squeezed,
    trimmed, at most STOP_NAME_MAX characters; None when nothing is left."""
    clean = re.sub(r"\s+", " ", str(name or "")).strip()[:STOP_NAME_MAX].strip()
    return clean or None


def link_stop_names(names, count: int, vias, loop: bool) -> dict[int, str]:
    """The names a link carries for a plan of `count` points (pointKinds.ts `stopNames`): the
    stops between the ends only, a loop's last point included, never a via point."""
    out: dict[int, str] = {}
    for i, name in sorted((names or {}).items()):
        last = i == count - 1
        middle = 0 < i < (count if loop else count - 1)
        clean = clean_stop_name(name)
        if clean and middle and (last or i not in vias):
            out[i] = clean
    return out


def link_stop_icons(icons, count: int, vias, loop: bool) -> dict[int, str]:
    """The stops' icons a link carries (pointKinds.ts `stopIcons`; Stephen 2026-11-10: "Stops can
    have icons too"): as `link_stop_names`, the stops between the ends only, each a NOTE_ICONS
    name."""
    out: dict[int, str] = {}
    for i, icon in sorted((icons or {}).items()):
        last = i == count - 1
        middle = 0 < i < (count if loop else count - 1)
        if icon in NOTE_ICONS and middle and (last or i not in vias):
            out[i] = icon
    return out


# Route notes (frontend/src/lib/routeNotes.ts; Stephen 2026-11-10): a Caution or a Point of
# interest at a spot, in the rider's own words, kept in the link as `nt=c,lon,lat,words`.
NOTE_TEXT_MAX = 80  # routeNotes.ts NOTE_TEXT_MAX, our default
MAX_NOTES = 20  # routeNotes.ts MAX_NOTES, our default
NOTE_NEAR_M = 60  # routeNotes.ts NOTE_NEAR_M: a note this close to the line is a cue
# A note asked for further off than NOTE_NEAR_M, but within this, is put on the route where it
# passes nearest (our default, unmeasured: a place looked up by name is often its middle).
NOTE_SNAP_M = 400
NOTE_KINDS = {"caution": "c", "interest": "i"}
# The icons a note can show on the map (routeNotes.ts NOTE_ICONS, our default set; the owner,
# 2026-11-10: "have that note appear on the map with a choice of icon"), each kind's own first.
NOTE_ICONS = {
    "warning": "⚠️",
    "pothole": "🕳️",
    "traffic": "🚗",
    "construction": "🚧",
    "view": "🏞️",
    "photo": "📷",
    "water": "💧",
    "food": "🍴",
    "coffee": "☕",
    "restroom": "🚻",
    "bikeshop": "🔧",
    "pin": "📍",
}
KIND_ICON = {"caution": "warning", "interest": "pin"}
NOTE_RE = re.compile(
    r"^([ci])(?:\.([a-z]+))?,(-?\d{1,3}(?:\.\d+)?),(-?\d{1,2}(?:\.\d+)?),(.*)$", re.S
)


def clean_note_text(text) -> str:
    """A note's words as the page keeps them (routeNotes.ts `cleanNoteText`): no control
    characters, spaces squeezed, at most NOTE_TEXT_MAX characters; "" for none."""
    clean = re.sub(r"[\x00-\x1f\x7f]", " ", str(text or ""))
    return re.sub(r"\s+", " ", clean).strip()[:NOTE_TEXT_MAX].strip()


# The notes' share of the link as the address writes it (routeNotes.ts NOTES_LINK_MAX, our
# default): the whole link stays under the server's 2048 (core/accounts.py HASH_MAX).
NOTES_LINK_MAX = 1200


def encode_notes(notes) -> list[str]:
    """The link's `nt` values (routeNotes.ts `encodeNotes`): kind letter, place, then words; those
    past the link's share (NOTES_LINK_MAX) left out."""
    out = []
    used = 0
    for note in (notes or [])[:MAX_NOTES]:
        text = clean_note_text(note.get("text"))
        if text and note.get("kind") in NOTE_KINDS:
            letter = NOTE_KINDS[note["kind"]]
            icon = note.get("icon")
            if icon in NOTE_ICONS and icon != KIND_ICON[note["kind"]]:
                letter += f".{icon}"
            value = f"{letter},{float(note['lon']):.5f},{float(note['lat']):.5f},{text}"
            used += len("&" + urllib.parse.urlencode({"nt": value}).replace("%2C", ","))
            if used > NOTES_LINK_MAX:
                break
            out.append(value)
    return out


def decode_notes(values) -> list[dict]:
    """The `nt` values read back (routeNotes.ts `decodeNotes`); one that does not read is left
    out. Each {kind, lon, lat, text}."""
    out: list[dict] = []
    for value in values or []:
        m = NOTE_RE.match(str(value))
        if not m:
            continue
        lon, lat, text = float(m[3]), float(m[4]), clean_note_text(m[5])
        if not text or abs(lon) > 180 or abs(lat) > 90:
            continue
        kind = "caution" if m[1] == "c" else "interest"
        note = {"kind": kind, "lon": lon, "lat": lat, "text": text}
        if m[2] in NOTE_ICONS and m[2] != KIND_ICON[kind]:
            note["icon"] = m[2]
        out.append(note)
        if len(out) >= MAX_NOTES:
            break
    return out


def line_nearest(line, lon: float, lat: float) -> tuple[float, float, tuple[float, float]]:
    """The nearest point of `line` to (lon, lat): metres along the line to it, metres off the
    line, and the point; the first along where two passes are as near (a loop's)."""
    kx = 111_320 * math.cos(math.radians(lat))
    ky = 110_574
    best = (math.inf, 0.0, (lon, lat))
    along = 0.0
    for a, b in itertools.pairwise(line):
        ax, ay = (a[0] - lon) * kx, (a[1] - lat) * ky
        bx, by = (b[0] - lon) * kx, (b[1] - lat) * ky
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        t = 0.0 if length2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / length2))
        off = math.hypot(ax + t * dx, ay + t * dy)
        seg = math.sqrt(length2)
        if off < best[0] - 1:
            point = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
            best = (off, along + t * seg, point)
        along += seg
    return best[1], best[0], best[2]


def _line_scale(answer: dict) -> float:
    """The line's metres to one of the description's (the router's), for a mile the figures give."""
    line = (answer.get("geometry") or {}).get("coordinates") or []
    total = sum(
        haversine_mi((a[0], a[1]), (b[0], b[1])) * METRES_PER_MILE
        for a, b in itertools.pairwise(line)
    )
    distance = float(answer.get("distance_m") or 0.0)
    return total / distance if total and distance else 1.0


def point_at_mile(line, mile: float) -> tuple[float, float]:
    """The point `mile` miles along `line` (its end past the end)."""
    want = mile * METRES_PER_MILE
    along = 0.0
    for a, b in itertools.pairwise(line):
        seg = haversine_mi((a[0], a[1]), (b[0], b[1])) * METRES_PER_MILE
        if seg > 0 and along + seg >= want:
            t = (want - along) / seg
            return a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
        along += seg
    if not line:
        raise ToolError("the draft has no line")
    return line[-1][0], line[-1][1]


def notes_along(answer: dict, notes) -> list[dict]:
    """The notes near the route's line as cue rows' places (core/cue_cards.py `cue_rows`): each
    {kind, text, at_m}, `at_m` in the description's metres, in order along; one further off than
    NOTE_NEAR_M is on the map only."""
    line = (answer.get("geometry") or {}).get("coordinates") or []
    if len(line) < 2:
        return []
    total = sum(
        math.hypot((b[0] - a[0]) * 111_320 * math.cos(math.radians(a[1])), (b[1] - a[1]) * 110_574)
        for a, b in itertools.pairwise(line)
    )
    scale = float(answer.get("distance_m") or total) / total if total else 1.0
    out = []
    for note in notes or []:
        along, off, _ = line_nearest(line, float(note["lon"]), float(note["lat"]))
        if off <= NOTE_NEAR_M:
            at = min(max(along, 2.0), max(0.0, total - 1)) * scale
            out.append({"kind": note["kind"], "text": note["text"], "at_m": at})
    return sorted(out, key=lambda n: n["at_m"])


def route_notes_out(answer: dict, notes) -> list[dict]:
    """The route's notes as an answer gives them: each {kind, text, lon, lat, mi}, `mi` the
    mile where the route passes it, or None for one too far off the line to be a cue."""
    line = (answer.get("geometry") or {}).get("coordinates") or []
    scale = 1 / _line_scale(answer)
    out = []
    for note in notes or []:
        mi = None
        if len(line) >= 2:
            along, off, _ = line_nearest(line, float(note["lon"]), float(note["lat"]))
            if off <= NOTE_NEAR_M:
                mi = round(along * scale / METRES_PER_MILE, 1)
        out.append({**note, "mi": mi})
    return out


def plan_fragment(
    points, vias, preset: str, dials: dict, sent: dict, names=None, notes=None, icons=None
) -> str:
    """The page's own plan link fragment (frontend/src/lib/planHash.ts `encodePlan`): the
    answer's `dials`, what only the request carried (`sent`, the POST /api/route body: the
    legs drawn in the app's manual mode among it) and the stops' own `names` by index."""
    parts = ["p=" + ";".join(f"{lon:.5f},{lat:.5f}" for lon, lat in points)]
    if vias:
        parts.append("via=" + ",".join(str(i) for i in vias))
    drawn = sorted({i for i in sent.get("straight_legs") or [] if 0 <= i < len(points) - 1})
    if drawn:
        parts.append("line=" + ",".join(str(i) for i in drawn))
    for i, name in link_stop_names(names, len(points), set(vias), bool(dials.get("loop"))).items():
        # As URLSearchParams writes it, with the page's commas left bare.
        parts.append(urllib.parse.urlencode({"sn": f"{i}:{name}"}).replace("%2C", ","))
    for value in encode_notes(notes):
        # The route's notes (routeNotes.ts encodeNotes), written as the page writes them.
        parts.append(urllib.parse.urlencode({"nt": value}).replace("%2C", ","))
    for i, icon in link_stop_icons(icons, len(points), set(vias), bool(dials.get("loop"))).items():
        # The stops' icons (pointKinds.ts encodeStopIcons; 2026-11-10), as the page writes them.
        parts.append(urllib.parse.urlencode({"si": f"{i}:{icon}"}))
    parts.append("preset=" + preset)
    parts.append("v=2")
    parts.append(f"stress={dials['stress']}")
    parts.append(f"hills={dials['hills']}")
    # "when I'm planning" unless the ride time was asked for.
    if sent.get("when"):
        parts.append(f"when={sent['when']}")
    if dials.get("carrying"):
        parts.append(f"carrying={dials['carrying']}")
    if dials.get("assist"):
        parts.append("assist=1")
    if dials.get("trails_off"):
        parts.append("trailsoff=1")
    if dials.get("easy_mtb"):
        parts.append("easymtb=1")
    if sent.get("novice_legs"):
        parts.append("novice=1")
    if dials.get("target_distance_m"):
        parts.append(f"targetmi={dials['target_distance_m'] / METRES_PER_MILE:.1f}")
    if dials.get("loop"):
        parts.append("loop=1")
    if sent.get("bike"):
        parts.append(f"bike={sent['bike']}")
        if sent["bike"] == "ebike" and sent.get("ending") == "outside_dock":
            parts.append("ending=outside")
    if sent.get("mtb_level"):
        parts.append(f"level={sent['mtb_level']}")
    if sent.get("mtb_preferred"):
        parts.append(f"prefer={sent['mtb_preferred']}")
    if preset == "mass-ride" and sent.get("ride_size"):
        parts.append(f"riders={sent['ride_size']}")
    return "#" + "&".join(parts)


def page_dials(dials: dict, sent: dict) -> dict:
    """The plan's dials as the page keeps them in a saved route (frontend lib/dials.ts)."""
    kept = {
        "stress": dials["stress"],
        "hills": dials["hills"],
        "when": sent.get("when"),
        "carrying": dials.get("carrying"),
        "assist": bool(dials.get("assist")),
        "trailsOff": bool(dials.get("trails_off")),
        "loop": bool(dials.get("loop")),
    }
    if dials.get("easy_mtb"):
        kept["easyMtb"] = True
    optional = {
        "targetDistanceM": dials.get("target_distance_m"),
        "noviceLegs": sent.get("novice_legs"),
        "bike": sent.get("bike"),
        "ending": sent.get("ending"),
        "mtbLevel": sent.get("mtb_level"),
        "mtbPreferred": sent.get("mtb_preferred"),
        "rideSize": sent.get("ride_size"),
    }
    kept.update({k: v for k, v in optional.items() if v})
    return kept


PRESET_ALIASES = {"kids": "novice"}  # planHash.ts PRESET_ALIASES
# presets.ts AVOID_GRAVEL_BECOMES: the ride types an old Avoid gravel link turns into Road Bike.
AVOID_GRAVEL_BECOMES = ("default", "fast", "gravel", "mountain-goat")
STRESS_DEFAULT_AT = 70  # dials.ts: the stress slider's Default


def stress_from_v1(old: float) -> int:
    """An old (v1) link's stress on the new slider, as planHash.ts `stressFromV1`: old x 70/90
    up to 90, then 70 + (old - 90)."""
    if old <= 90:
        return round(old * STRESS_DEFAULT_AT / 90)
    return STRESS_DEFAULT_AT + round(old - 90)


LINK_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
LINK_VALUE = {c: i for i, c in enumerate(LINK_ALPHABET)}


def decode_points(text: str) -> list[tuple[float, float]]:
    """The points a link's `q=` holds (linkCode.ts `decodePoints`): zigzagged whole 1e-5 degrees,
    longitude then latitude, each after the first as the change from the one before, 5 bits a
    base64url character, lowest first, with a sixth bit saying another follows. Read up to the
    first character outside the alphabet or a number left unfinished; a number over 53 bits
    stops there too."""
    numbers: list[int] = []
    z = 0
    scale = 1
    for c in text:
        v = LINK_VALUE.get(c)
        if v is None:
            break
        z += (v % 32) * scale
        scale *= 32
        if scale > 2**53:
            break
        if v >= 32:
            continue
        numbers.append(-(z + 1) // 2 if z % 2 == 1 else z // 2)
        z = 0
        scale = 1
    points = []
    lon = lat = 0
    for i in range(0, len(numbers) - 1, 2):
        lon += numbers[i]
        lat += numbers[i + 1]
        points.append((lon / 1e5, lat / 1e5))
    return points


def fragment_points(params: dict) -> list[tuple[float, float]]:
    """The points a parsed fragment holds, in either form (planHash.ts `linkPoints`): `q=` first,
    the older `p=` when there is no `q=` or it holds no point."""
    short = params.get("q")
    if short:
        points = decode_points(short[0])
        if points:
            return points
    points = []
    for pair in ((params.get("p") or [""])[0]).split(";"):
        try:
            lon, lat = (float(v) for v in pair.split(","))
        except ValueError:
            continue
        points.append((lon, lat))
    return points


PLAN_POINTS_RE = re.compile(r"(?:^|[#&?])[pq]=[^&]")


# A link's fields that are not its plan: the ride's key, its ride mark and leader, the kept
# route's id and the Reach view (rideSeal.ts, sharedRoutes.ts, App.tsx), and the route's notes,
# which change no line (a note added in the app keeps the kept route's exact line).
NOT_THE_PLAN = ("k", "ride", "lead", "route", "reach", "nt")


def plan_params(fragment: str) -> list[tuple[str, str]]:
    """A link fragment's plan, field by field and in no order: the same plan however the app
    added a ride's key, ride mark, leader or kept route id to its link."""
    pairs = urllib.parse.parse_qsl(str(fragment or "").lstrip("#"), keep_blank_values=True)
    return sorted((k, v) for k, v in pairs if k not in NOT_THE_PLAN)


def has_plan_points(fragment: str) -> bool:
    """Whether a link's fragment carries stops in either form (`q=` or the older `p=`)."""
    return bool(PLAN_POINTS_RE.search(str(fragment or "")))


def parse_fragment(fragment: str) -> tuple[list, list[int], str, dict]:
    """A plan link's fragment as the page reads it (planHash.ts `decodePlan`): the points, the
    via points, the ride type and POST /api/route's options."""
    params = urllib.parse.parse_qs(fragment.lstrip("#"), keep_blank_values=False)

    def one(key):
        values = params.get(key)
        return values[0] if values else None

    points = [point for point in fragment_points(params) if inside_coverage(point)]
    points = points[:MAX_POINTS]  # the page opens the first 25 too
    if len(points) < 2:
        raise ToolError("that link holds no route (it needs at least a start and an end)")
    vias = sorted(
        int(i)
        for i in (one("via") or "").split(",")
        if i.isdigit() and 0 < int(i) < len(points) - 1
    )
    # A ride type since renamed opens the new one at its own start, as the page does.
    renamed = one("preset") in PRESET_ALIASES
    preset = PRESET_ALIASES.get(one("preset") or "", one("preset") or "default")
    if preset not in PRESETS:
        preset = "default"
    # The retired Avoid gravel box: a link with it ticked on a rider's own bike opens as Road
    # Bike, its sliders as linked, as the page does (planHash.ts, AVOID_GRAVEL_BECOMES).
    if one("avoidgravel") == "1" and preset in AVOID_GRAVEL_BECOMES:
        preset = "road-bike"

    def number(key):
        try:
            return int(float(one(key))) if one(key) is not None else None
        except (ValueError, OverflowError):
            return None

    stress = None if renamed else number("stress")
    if stress is not None and one("v") != "2":
        stress = stress_from_v1(stress)
    options = {
        "stress": stress,
        "hills": None if renamed else number("hills"),
        "when": one("when")
        if one("when") in ("weekend", "weekday_rush", "weekday_offpeak", "night")
        else None,
        "carrying": one("carrying") if one("carrying") in ("cargo", "people") else None,
        "assist": one("assist") == "1",
        "trails_off": one("trailsoff") == "1",
        # Default and Trailmaxxing only, as the page reads it (dials.ts fitDials).
        "easy_mtb": one("easymtb") == "1" and preset in EASY_MTB_PRESETS,
        "novice_legs": one("novice") == "1",
        "loop": one("loop") == "1",
        "bike": one("bike") if one("bike") in ("classic", "ebike") else None,
        "ending": "outside_dock" if one("ending") == "outside" else None,
        "mtb_level": number("level"),
        "mtb_preferred": number("prefer"),
        "ride_size": (None if number("riders") is None else min(2000, max(100, number("riders")))),
    }
    if one("targetmi"):
        try:
            options["target_distance_m"] = int(float(one("targetmi")) * METRES_PER_MILE)
        except ValueError:
            pass
    # The legs drawn in the app's manual mode (`line=0,2`, pointKinds.ts `decodeDrawn`), ridden
    # as drawn (POST /api/route's `straight_legs`), and the stops' own names (`sn=2:Union
    # Market`, `decodeStopNames`), carried to the next link.
    drawn = {int(i) for i in (one("line") or "").split(",") if i.isdigit()}
    options["straight_legs"] = sorted(i for i in drawn if i < len(points) - 1) or None
    names: dict[int, str] = {}
    for value in params.get("sn") or []:
        at, _, name = value.partition(":")
        clean = clean_stop_name(name)
        if at.isdigit() and 0 < int(at) < len(points) and clean:
            names[int(at)] = clean
    options["stop_names"] = names or None
    # The stops' icons (`si=2:coffee`, pointKinds.ts `decodeStopIcons`), carried likewise.
    icons: dict[int, str] = {}
    for value in params.get("si") or []:
        at, _, icon = value.partition(":")
        if at.isdigit() and 0 < int(at) < len(points) and icon in NOTE_ICONS:
            icons[int(at)] = icon
    options["stop_icons"] = icons or None
    # The route's notes (`nt=c,lon,lat,words`, routeNotes.ts `decodeNotes`), carried likewise.
    options["route_notes"] = decode_notes(params.get("nt")) or None
    return points, vias, preset, options


# What a plan's options carry for its link or for the MCP server only, never sent to POST
# /api/route: the stops' names, and that a followed line is an alternative's, not the rider's
# (the round 4 hunt, L4-1: an avoid plans such a draft through its points instead).
LINK_ONLY_OPTIONS = ("stop_names", "stop_icons", "route_notes", "follow_alternative", "corking")


def marks_with_point_at(options: dict, at: int) -> dict:
    """The options with a point put in at index `at` (a Metro station): the drawn legs and the
    stops' names after it move up one; the drawn leg it splits is planned, not drawn."""
    out = dict(options)
    if options.get("straight_legs"):
        legs = [i if i < at - 1 else i + 1 for i in options["straight_legs"] if i != at - 1]
        out["straight_legs"] = legs or None
    for key in ("stop_names", "stop_icons"):
        if options.get(key):
            out[key] = {i if i < at else i + 1: n for i, n in options[key].items()}
    return out


def marks_revised(plan, built: list, whole: bool) -> tuple[list[int] | None, dict | None]:
    """The drawn legs and stops' names of `plan` on the revised points (`built`: rows of [the
    draft's index or None for a point added, point, via]). A leg stays drawn while its two
    points stay side by side; a name stays with its point unless the point moved. None of
    either when every point was given anew (`whole`)."""
    if whole:
        return None, None
    at = {row[0]: k for k, row in enumerate(built) if row[0] is not None}
    legs = sorted(
        at[i]
        for i in plan.sent.get("straight_legs") or []
        if i in at and i + 1 in at and at[i + 1] == at[i] + 1
    )
    names = labels_revised(plan, built, plan.names)
    return legs or None, names or None


def labels_revised(plan, built: list, labels) -> dict | None:
    """A stop's label (its name or icon, by index) on the revised points (`built`, as
    `marks_revised` takes it): it stays with its point unless the point moved."""
    at = {row[0]: k for k, row in enumerate(built) if row[0] is not None}
    out = {
        at[i]: label
        for i, label in (labels or {}).items()
        if i in at and tuple(built[at[i]][1]) == tuple(plan.points[i])
    }
    return out or None


def routes_dir() -> Path:
    return Path(os.environ.get("ROUTEMAKER_ROUTES_DIR") or Path.home() / "RouteMaker-routes")


def gpx_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "route"


def gpx_text(name: str, line: list[list[float]]) -> str:
    """The route as a GPX 1.1 track, with heights where the answer has them."""
    points = []
    for vertex in line:
        ele = f"<ele>{vertex[2]:.1f}</ele>" if len(vertex) > 2 else ""
        points.append(f'<trkpt lat="{vertex[1]:.6f}" lon="{vertex[0]:.6f}">{ele}</trkpt>')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="RouteMaker MCP" xmlns="http://www.topografix.com/GPX/1/1">\n'
        f"<metadata><name>{escape(name)}</name></metadata>\n"
        f"<trk><name>{escape(name)}</name><trkseg>\n" + "\n".join(points) + "\n</trkseg></trk>\n"
        "</gpx>\n"
    )


def write_gpx(name: str, line: list[list[float]], directory: Path | None = None) -> Path:
    directory = directory or routes_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{time.strftime('%Y%m%d-%H%M%S')}-{gpx_slug(name)}.gpx"
    path.write_text(gpx_text(name, line), encoding="utf-8")
    return path


# --- Planning -------------------------------------------------------------------------------


def refusal(status: int, message) -> str:
    """Why the site gave no route, in words an assistant can act on. A 5xx with no message is
    the web server giving up, almost always its time limit on a long route."""
    if status >= 500 and not message:
        return (
            f"the site failed while planning ({status}), most likely its time limit on a long"
            " route. Try again, or plan a shorter ride or fewer points."
        )
    return f"the site refused the route ({status}): {message}"


# The ride types that offer Easy MTB trails (core/presets.py EASY_MTB_PRESETS).
EASY_MTB_PRESETS = frozenset({"default", "trailmaxxing"})


def easy_mtb_said(info: object) -> str | None:
    """What an Easy MTB trails answer says of its route (core/easy_mtb.py), or None."""
    if not isinstance(info, dict):
        return None
    if info.get("limited") == "no_offroad_graph":
        return (
            "the off-road router is not running, so this route was planned on the standard map"
            " and keeps to the usual trails, with no mountain-bike trails"
        )
    harder = info.get("harder_m") or 0.0
    if harder > 1.0:
        return (
            f"{miles_text(harder)} on mountain-bike trails rated 2 or harder (no way round"
            " was found)"
        )
    return None


# The ride types whose summary names the barriers on the route (core/barriers.py PRESETS;
# the owner, 2026-11-12: "Exclude; line on Cargo+Tandem").
BARRIER_PRESETS = frozenset({"cargo", "tandem"})
BARRIER_WORDS = {
    "stile": "stile",
    "kissing_gate": "kissing gate",
    "turnstile": "turnstile",
    "steps": "steps",
    "narrow_gap": "narrow gap",
    "bollard": "bollard",
    "cycle_barrier": "cycle barrier",
    "gate": "gate",
}


def barriers_said(answer: dict) -> str | None:
    """What a Cargo or Tandem answer says of the barriers on its route, as the page's line
    (frontend/src/lib/barriers.ts): the impassable ones no way round was found for, else every
    barrier, a gap with no width mapped said as unmapped. None where there are none, or where
    no barrier list is loaded (never "none")."""
    if answer.get("preset") not in BARRIER_PRESETS:
        return None
    reading = answer.get("barriers")
    if not isinstance(reading, dict) or not reading.get("data"):
        return None
    items = [i for i in reading.get("items") or [] if isinstance(i, dict)]
    blocking = [i for i in items if i.get("impassable")]
    if not items:
        return None
    groups: dict[tuple[str, bool], int] = {}
    for item in blocking or items:
        key = (str(item.get("word")), item.get("width_mapped") is False)
        groups[key] = groups.get(key, 0) + 1
    parts = [
        BARRIER_WORDS.get(word, "other barrier")
        + (f" x{n}" if n > 1 else "")
        + (" (width not mapped)" if unmapped else "")
        for (word, unmapped), n in groups.items()
    ]
    if blocking:
        # "No way round found" only where the barrier round looked and found none.
        limited = (answer.get("barrier_round") or {}).get("limited")
        listed = ", ".join(parts)
        if limited == "no_way_round":
            where = f"no way round found: {listed} on this route"
        elif limited == "at_stop":
            where = f"{listed} by the start, a stop or the end"
        else:
            where = f"{listed} on this route"
        return f"{where}; a cargo bike or tandem may not get through"
    return ", ".join(parts)


# A Mountain Bike reading's figure below this many metres is not said: the page's
# `mtbMode.SAY_FROM_M` (a crossing, a driveway).
MTB_SAY_FROM_M = 20.0
MTB_LEVEL_WORDS = {
    1: "level 1 (green)",
    2: "level 2 (blue)",
    3: "level 3 (black)",
    4: "level 4 (red)",
}


def mtb_said(info: object) -> list[str] | None:
    """What a Mountain Bike answer's trail reading (`mtb`, core/mtb.py) says of its route, as
    the page says it (frontend/src/lib/mtbMode.ts `mtbNotes`), warnings first; None where
    there is no reading (routing hunt 4, M4-1: the connector never said it)."""
    if not isinstance(info, dict):
        return None

    def metres(key: str) -> float:
        value = info.get(key)
        return float(value) if isinstance(value, (int, float)) else 0.0

    level = MTB_LEVEL_WORDS.get(info.get("max_level"), f"level {info.get('max_level')}")
    if info.get("limited") == "no_mtb_graph":
        return [
            "The mountain-bike trails are not available right now, so this route keeps to"
            " roads and ordinary paths. Try again later for a trail route."
        ]
    out = []
    over = metres("over_level_m")
    if over >= MTB_SAY_FROM_M:
        out.append(
            f"This route uses {distance_text(over)} of trail harder than {level}: no way round it"
            " was found. Check the trail before you ride, or raise the hardest level."
        )
    busy = metres("lts4_m")
    if busy >= MTB_SAY_FROM_M:
        out.append(
            f"It uses {distance_text(busy)} of busy road (LTS 4 or Avoid): no calmer connection"
            " was found."
        )
    long3 = metres("long_lts3_m")
    if long3 >= MTB_SAY_FROM_M:
        out.append(
            f"It has {distance_text(long3)} of LTS 3 road in stretches of a half mile or more."
        )
    if info.get("limited") in ("time", "untraced"):
        out.append(
            "The trail search ran short of time, so this may not be the most trail-rich route."
        )
    trail, single = metres("trail_m"), metres("singletrack_m")
    if trail >= MTB_SAY_FROM_M:
        out.append(
            f"{distance_text(trail)} on trail, {distance_text(single)} of it mountain-bike"
            f" singletrack, up to {level}."
            if single >= MTB_SAY_FROM_M
            else f"{distance_text(trail)} on trail, up to {level}."
        )
    else:
        out.append("No trail was found on this route; it keeps to calm roads and paths.")
    if info.get("preferred_level") is not None:
        preferred = MTB_LEVEL_WORDS.get(
            info.get("preferred_level"), f"level {info.get('preferred_level')}"
        )
        easier, harder = metres("easier_m"), metres("harder_m")
        if easier >= MTB_SAY_FROM_M:
            out.append(
                f"{distance_text(easier)} of trail is easier than the preferred {preferred}."
            )
        if harder >= MTB_SAY_FROM_M:
            out.append(
                f"{distance_text(harder)} of trail is harder than the preferred {preferred},"
                f" up to {level}."
            )
        if (
            easier < MTB_SAY_FROM_M
            and harder < MTB_SAY_FROM_M
            and single >= MTB_SAY_FROM_M
            and over < MTB_SAY_FROM_M
        ):
            out.append(f"Its mountain-bike trails are at the preferred {preferred}.")
    return out


def over_target_said(answer: dict) -> str | None:
    """How far past the rider's target distance the route is, as the page flags it
    (frontend/src/lib/summary.ts `overTarget`: the answer's `calm_search.over_target_m`, a
    candidate's own `over_target_m`), or None where it is within it or there is none
    (routing hunt 4, M4-3: the target is a limit, OWNER-DECISIONS 257, 267, 271)."""
    search = answer.get("calm_search") if isinstance(answer.get("calm_search"), dict) else {}
    over = search.get("over_target_m")
    if over is None:
        over = answer.get("over_target_m")
    if not isinstance(over, (int, float)) or over <= 0:
        return None
    target = search.get("target_distance_m") or (answer.get("dials") or {}).get("target_distance_m")
    if target:
        return f"{miles_text(over)} over the rider's target of {miles_text(target)}"
    return f"{miles_text(over)} over the rider's target distance"


def road_bike_said(answer: dict) -> str | None:
    """What a Road Bike answer from a fallback map says of its route, as the page says it
    (frontend/src/lib/roadBike.ts `roadBikeNotice`, from the answer's `variant` and ride time),
    or None (hunt 3, PL3-10: the connector never said it)."""
    if answer.get("preset") != "road-bike":
        return None
    variant = answer.get("variant")
    if variant == "standard":
        return (
            "Road Bike's paved-only map isn't available, so this route may use packed gravel"
            " and winding trails"
        )
    when = (answer.get("dials") or {}).get("when")
    if variant == "paved" and when == "weekend":
        return (
            "Road Bike's weekend map isn't available, so this route treats car-free parkways"
            " such as Beach Drive as roads with cars"
        )
    return None


def _trail_spans(answer: dict) -> list[tuple[float, float]]:
    """The route's mountain-bike trails (`trail_levels`, traced metres) in miles along it."""
    scale = _traced_scale(answer) / METRES_PER_MILE
    return [
        (s["from_m"] * scale, s["to_m"] * scale)
        for s in answer.get("trail_levels") or []
        if isinstance(s, dict) and s.get("to_m") is not None and s.get("from_m") is not None
    ]


def _trail_mi(spans: list[tuple[float, float]], a: float, b: float) -> float:
    """The miles of `a`-`b` along the route on a mountain-bike trail."""
    return sum(max(0.0, min(b, hi) - max(a, lo)) for lo, hi in spans)


def _with_trail(facility: dict, answer: dict) -> dict:
    """The facility table with the mountain-bike trails taken out of "none" as "trail".
    The map gives such a trail no facility (pipeline/run.py: no path rail on a trail only a
    mountain bike rides), so it was said as an ordinary street (routing hunt 4, M4-4)."""
    trails = answer.get("trail_levels") or []
    none = facility.get("none") or 0.0
    if not trails or not none:
        return facility
    plain = [
        (s["from_m"], s["to_m"])
        for s in answer.get("stress_spans") or []
        if s.get("facility") == "none"
    ]
    on_trail = sum(
        max(0.0, min(b, t["to_m"]) - max(a, t["from_m"]))
        for a, b in plain
        for t in trails
        if isinstance(t, dict) and t.get("to_m") is not None and t.get("from_m") is not None
    )
    on_trail = min(on_trail, none)
    if on_trail <= 0:
        return facility
    return {**facility, "none": none - on_trail, "trail": on_trail}


def summary(answer: dict) -> dict:
    """The answer in a few lines a model can reason about and repeat to a rider."""
    distance = answer.get("distance_m") or 0.0
    stress = answer.get("stress_m") or {}
    facility = answer.get("facility_m") or {}

    def shares(table: dict, keys: dict) -> dict:
        total = sum(v for v in table.values() if isinstance(v, (int, float))) or 1.0
        return {
            label: f"{table.get(key, 0) / total * 100:.0f}% ({miles_text(table.get(key, 0))})"
            for key, label in keys.items()
            if table.get(key, 0) >= 0.05 * METRES_PER_MILE
        }

    out = {
        "distance": miles_text(distance),
        "distance_mi": round(distance / METRES_PER_MILE, 1),
        "moving_time": f"{(answer.get('duration_s') or 0) / 3600:.1f} h",
        "climb": feet_text(answer.get("climb_m") or 0.0),
        "traffic_stress": shares(
            stress,
            {
                "1": "LTS 1",
                "2": "LTS 2",
                "3": "LTS 3",
                "4": "LTS 4",
                "5": "Avoid",
                "unknown": "unknown",
            },
        ),
        "facilities": shares(
            _with_trail(facility, answer),
            {
                "path": "traffic-free path",
                "trail": "mountain-bike trail",
                "protected": "protected lane",
                "lane": "painted lane",
                "none": "ordinary street",
                "unknown": "unknown",
            },
        ),
    }
    unpaved = _unpaved_mi(answer)
    if unpaved >= 0.05:
        out["unpaved"] = miles_text(unpaved * METRES_PER_MILE)
    turns = turn_count(answer)
    if turns is not None:
        out["turns"] = turns
    waits = (answer.get("junction_delay_s") or 0.0) / 60
    if waits >= 0.5:
        # The time the route spends at signals and stop signs, inside moving_time.
        out["junction_waits"] = f"{waits:.0f} min"
    if answer.get("loop"):
        pct = answer["loop"].get("overlap_pct")
        if pct is not None:
            out["loop_way_back_shared"] = f"{pct:.0f}%"
    if answer.get("avoid_notice"):
        out["avoid_notice"] = answer["avoid_notice"]
    easy = easy_mtb_said(answer.get("easy_mtb"))
    if easy:
        out["easy_mtb"] = easy
    barriers = barriers_said(answer)
    if barriers:
        out["barriers"] = barriers
    road_bike = road_bike_said(answer)
    if road_bike:
        out["road_bike_map"] = road_bike
    mtb = mtb_said(answer.get("mtb"))
    if mtb:
        out["mtb"] = mtb
    over_target = over_target_said(answer)
    if over_target:
        out["over_target"] = over_target
    if answer.get("moved_points"):
        out["moved_points"] = len(answer["moved_points"])
    share = answer.get("bikeshare")
    if isinstance(share, dict):
        out["bikeshare"] = {k: share.get(k) for k in ("summary", "notes", "pricing_note")}
    transit = answer.get("transit")
    if isinstance(transit, dict):
        out["transit"] = {k: transit.get(k) for k in ("summary", "comparison", "notes")}
        out["transit"]["options"] = [
            {k: o.get(k) for k in ("key", "label", "minutes", "chosen")}
            for o in transit.get("options") or []
        ]
        later = later_rides(answer)
        if later:
            # The figures above are the route line's, the trip's first ride; the rides after
            # it were left out of every figure (routing hunt 4, X4-2).
            out["transit"]["later_rides"] = later
            # Every ride's miles together, where every later ride was routed (an unrouted one
            # has its minutes only).
            if all(r["routed"] for r in later):
                ridden = distance / METRES_PER_MILE + sum(r["miles"] for r in later)
                out["transit"]["ridden_mi"] = round(ridden, 1)
            out["transit"]["figures_cover"] = LATER_RIDES_NOTE
    return out


# What a Bike + transit or Bikeshare + transit answer's own figures cover when the trip rides
# again after its route line (routing hunt 4, X4-2).
LATER_RIDES_NOTE = (
    "distance, traffic_stress, roads, busy_stretches, junctions and route_segments cover the"
    " trip's first ride only; transit.later_rides describes each ride after it"
)
_RIDE_STEPS = {"ride": "ride", "bikeshare": "bikeshare"}


def later_rides(answer: dict) -> list[dict]:
    """Each own-bike or bikeshare ride of a transit trip after its route line (the answer's own
    line, which every other figure describes), in trip order: where it starts and ends, its
    miles, its LTS shares and its busy stretches (LTS 3 and up, miles into that ride), from the
    step's routed line (`stress_spans`, api.py `_with_leg_lines`). A ride the router did not
    draw says `routed: false` and its minutes only. Empty off a transit trip or with one ride.
    The later rides' road names are not in the answer, so none are listed."""
    transit = answer.get("transit")
    steps = transit.get("steps") if isinstance(transit, dict) else None
    if not steps:
        return []
    line_at = next((i for i, step in enumerate(steps) if step.get("route_line")), None)
    if line_at is None or steps[line_at].get("mode") not in _RIDE_STEPS:
        return []
    out = []
    for index in range(line_at + 1, len(steps)):
        step = steps[index]
        kind = _RIDE_STEPS.get(step.get("mode"))
        if kind is None:
            continue
        before = next(
            (steps[i].get("to") for i in range(index - 1, -1, -1) if steps[i].get("to")), None
        )
        row: dict = {
            "mode": kind,
            "from": before,
            "to": step.get("to") or "the destination",
            "minutes": round((step.get("seconds") or 0) / 60),
        }
        spans = step.get("stress_spans") or []
        metres = step.get("distance_m")
        if not spans or not metres:
            row["routed"] = False
            out.append(row)
            continue
        traced = spans[-1]["to_m"] or metres
        scale = metres / traced / METRES_PER_MILE
        tiers: dict[str, float] = {}
        entries = []
        for span in spans:
            length = (span["to_m"] - span["from_m"]) * scale
            key = str(span["tier"]) if span.get("tier") is not None else "unknown"
            tiers[key] = tiers.get(key, 0.0) + length
            entries.append(
                {
                    "tier": span.get("tier"),
                    "from_mi": span["from_m"] * scale,
                    "to_mi": span["to_m"] * scale,
                }
            )
        miles = metres / METRES_PER_MILE
        labels = {"1": "LTS 1", "2": "LTS 2", "3": "LTS 3", "4": "LTS 4", "5": "Avoid"}
        row["routed"] = True
        row["miles"] = round(miles, 2)
        row["traffic_stress"] = {
            labels.get(key, key): (
                f"{part / miles * 100:.0f}% ({miles_text(part * METRES_PER_MILE)})"
            )
            for key, part in tiers.items()
            if part >= 0.05
        }
        row["busy_stretches"] = [
            {k: v for k, v in busy.items() if k != "roads"} for busy in _busy_rows(entries)
        ]
        out.append(row)
    return out


# --- What the route rides, for an assistant to reason about ---------------------------------
#
# The owner, 2026-10-25, after a towpath and rustic-roads ride the connector could build but
# not find: "The goal would be for a new user to be able to make routes like this." The
# percentages alone hide which roads a route takes, where its busy stretches are and where it
# doubles back; these say it, short enough to read in one answer.

# The road list aims at no more than this many rows, grouping short links to keep to it.
MAX_ROAD_ROWS = 50
ROAD_ROW_MIN_MI = 0.2  # a row shorter than this is a short link, grouped with its neighbours
ROAD_ROW_MAX_MIN_MI = 1.0  # past this a long list stays long: a mile of road is worth its row
# A break in one road shorter than this (a nameless path: BRIDGE_NAMELESS_MI) is no new row.
BRIDGE_MI = 0.15
BRIDGE_NAMELESS_MI = 0.3
# A busy stretch (LTS 3 and up) shorter than this is left out of the list unless it is LTS 4
# or Avoid; pieces of one this close together are one stretch.
BUSY_MIN_MI = 0.1
BUSY_JOIN_MI = 0.05
# A busy stretch at a route's Metro station end left out of busy_stretches: at most this long
# (about 160 m, near station_links' 150 m walk-link reach), and starting or ending within
# STATION_END_TOUCH_MI of that end, judged before the rows' miles are rounded. Claude's
# defaults, not measured (the round 4 hunt, L4-8).
STATION_END_MI = 0.1
STATION_END_TOUCH_MI = 0.05
MAX_BUSY_ROWS = 20
# Small detours (the owner, 2026-10-25: "these small excursions aren't worth including"): a
# span of the route at least twice as long as the straight line between its ends, with its
# ends within DETOUR_GAP_MI of each other and at least DETOUR_MIN_EXTRA_MI of extra riding,
# and no longer than DETOUR_MAX_MI, that leaves a road and comes back to the same road. A
# calm route winds (a trail's hairpin, a neighbourhood's curves) without leaving its way, so
# where the streets are not known only a tight loop counts: ends within DETOUR_BLIND_GAP_MI
# and three times the straight line.
DETOUR_GAP_MI = 0.37  # 600 m
DETOUR_BLIND_GAP_MI = 0.06  # 100 m
DETOUR_MIN_EXTRA_MI = 0.1
DETOUR_MAX_MI = 3.0
DETOUR_STEP_MI = 0.025  # the line is read every 40 m
MAX_DETOURS = 8
# A place name searched near the route's other points is taken only this close to them;
# farther, the server asks which was meant (Moore Road went to Centreville, VA: 2026-10-25).
NEAR_PLACE_MI = 15.0
NAMELESS = ("path", "unnamed road")


def _stretches(answer: dict) -> list[dict]:
    """The full description's stretches, in route order (the overview merges short ones)."""
    entries = answer.get("description") or answer.get("description_overview") or []
    return [e for e in entries if e.get("kind") == "stretch" and e.get("to_mi") is not None]


def _traced_scale(answer: dict) -> float:
    """Metres along the route (`distance_m`) per traced metre (`stress_spans`, junctions)."""
    spans = answer.get("stress_spans") or []
    traced = spans[-1]["to_m"] if spans else 0
    distance = answer.get("distance_m") or 0.0
    return distance / traced if traced and distance else 1.0


def _scenic_rows(answer: dict) -> list[dict]:
    scale = _traced_scale(answer) / METRES_PER_MILE
    return [
        {**s, "from_mi": s["from_m"] * scale, "to_mi": s["to_m"] * scale}
        for s in answer.get("scenic_roads") or []
    ]


def _street(entry: dict) -> str:
    return str(entry.get("street") or "unnamed road")


def _bridged(rows: list[dict]) -> list[dict]:
    """The rows with a short break in one road (a nameless path, a junction's few metres of
    another street) folded into it: road, BRIDGE_MI of something else, the same road again
    is one row of that road."""
    out: list[dict] = []
    for row in rows:
        if (
            len(out) >= 2
            and out[-2]["road"].casefold() == row["road"].casefold()
            and out[-1]["to_mi"] - out[-1]["from_mi"]
            < (BRIDGE_NAMELESS_MI if out[-1]["road"] in NAMELESS else BRIDGE_MI)
        ):
            gap, before = out.pop(), out[-1]
            for part in (gap, row):
                for table in ("tiers", "facility"):
                    for key, miles in part[table].items():
                        before[table][key] = before[table].get(key, 0.0) + miles
                before["unpaved"] = before.get("unpaved", 0.0) + part.get("unpaved", 0.0)
            before["to_mi"] = row["to_mi"]
            continue
        out.append(row)
    return out


def road_list(answer: dict) -> dict | None:
    """The roads the route takes, in order: each with its miles, its main and worst LTS, its
    miles at LTS 3 and up, and its scenic designation (a rustic road, a byway); rows under
    ROAD_ROW_MIN_MI are counted as short links. None where the site sent no description."""
    stretches = _stretches(answer)
    if not stretches:
        return None
    rows: list[dict] = []
    trails = _trail_spans(answer)
    for entry in stretches:
        street = _street(entry)
        miles = max(0.0, entry["to_mi"] - entry["from_mi"])
        tier = entry.get("tier")
        last = rows[-1] if rows else None
        if last is None or last["road"].casefold() != street.casefold():
            last = {"road": street, "from_mi": entry["from_mi"], "tiers": {}, "facility": {}}
            rows.append(last)
        last["to_mi"] = entry["to_mi"]
        last["tiers"][tier] = last["tiers"].get(tier, 0.0) + miles
        surface = entry.get("surface")
        unpaved = miles if surface == "unpaved" else miles / 2 if surface == "partly unpaved" else 0
        last["unpaved"] = last.get("unpaved", 0.0) + unpaved
        # "none" (known no facility, round-2 D28) and None (not known) are both plain street.
        kind = entry.get("facility")
        kind = kind if kind in ("path", "protected", "lane") else "street"
        if kind == "street" and trails:
            # A mountain-bike trail is no street (M4-4).
            trail = min(miles, _trail_mi(trails, entry["from_mi"], entry["to_mi"]))
            last["facility"]["trail"] = last["facility"].get("trail", 0.0) + trail
            miles -= trail
        last["facility"][kind] = last["facility"].get(kind, 0.0) + miles
    rows = _bridged(rows)
    scenic = _scenic_rows(answer)
    minimum = ROAD_ROW_MIN_MI
    while True:
        grouped = _grouped(rows, minimum)
        if len(grouped) <= MAX_ROAD_ROWS or minimum * 1.25 > ROAD_ROW_MAX_MIN_MI:
            break
        minimum *= 1.25
    out = []
    for group in grouped:
        first, last = group[0], group[-1]
        miles = last["to_mi"] - first["from_mi"]
        if miles < 0.05:
            continue  # a few metres between two listed roads
        tiers: dict = {}
        facilities: dict = {}
        for row in group:
            for key, value in row["tiers"].items():
                tiers[key] = tiers.get(key, 0.0) + value
            for key, value in row["facility"].items():
                facilities[key] = facilities.get(key, 0.0) + value
        rated = {t: m for t, m in tiers.items() if t is not None}
        if len(group) == 1:
            road = first["road"]
        else:
            names = list(dict.fromkeys(r["road"] for r in group if r["road"] not in NAMELESS))
            road = f"{len(group)} short links: " + (
                ", ".join(names[:4]) + (f" and {len(names) - 4} more" if len(names) > 4 else "")
                if names
                else "paths and unnamed ways"
            )
        item = {
            "road": road,
            "from_mi": round(first["from_mi"], 1),
            "miles": round(miles, 1),
            "lts": max(rated, key=rated.get) if rated else None,
        }
        worst = max((t for t, m in rated.items() if m >= 0.02), default=None)
        if worst is not None and worst != item["lts"]:
            item["worst_lts"] = worst
        busy = sum(m for t, m in rated.items() if t >= 3)
        if busy >= 0.05 and item["lts"] is not None and item["lts"] < 3:
            item["miles_lts_3_up"] = round(busy, 1)
        facility = max(facilities, key=facilities.get)
        if facility != "street":
            item["facility"] = facility
        unpaved = sum(r.get("unpaved", 0.0) for r in group)
        if unpaved >= 0.05:
            item["unpaved_mi"] = round(unpaved, 1)
        designations = {
            s["designation"]
            for s in scenic
            if min(s["to_mi"], last["to_mi"]) - max(s["from_mi"], first["from_mi"])
            >= min(0.1, miles / 2)
        }
        if designations:
            item["scenic"] = " · ".join(sorted(designations))
        out.append(item)
    return {"roads": out}


def _grouped(rows: list[dict], minimum: float) -> list[list[dict]]:
    """The rows in route order, each run of rows shorter than `minimum` miles one group."""
    groups: list[list[dict]] = []
    for row in rows:
        short = row["to_mi"] - row["from_mi"] < minimum
        if short and groups and groups[-1][-1]["to_mi"] - groups[-1][-1]["from_mi"] < minimum:
            groups[-1].append(row)
        else:
            groups.append([row])
    return groups


def busy_stretches(answer: dict, station_ends: tuple[bool, bool] = (False, False)) -> list[dict]:
    """Where the route rides LTS 3 and up, in route order: from and to (miles), the roads and
    the worst LTS (5 is Avoid). The longest MAX_BUSY_ROWS where there are more.

    `station_ends` says whether the route line starts and ends at a Metro station's way in. A
    busy stretch no longer than STATION_END_MI that touches such an end is left out: it is the
    bit of sidewalk beside the road that the elevator stands on, which the map rates as its road
    (the round 4 hunt, L4-8). Its price is unchanged; only the list leaves it out (the owner's
    card, 2026-11-10: "Hide from busy list now")."""
    end_mi = (answer.get("distance_m") or 0.0) / METRES_PER_MILE
    return _busy_rows(_stretches(answer), station_ends, end_mi)


def _busy_rows(
    entries: list[dict],
    station_ends: tuple[bool, bool] = (False, False),
    end_mi: float | None = None,
) -> list[dict]:
    """`busy_stretches` from stretches in route order ({tier, from_mi, to_mi, street}), leaving
    out a short one at a station end (`busy_stretches`), judged before the miles are rounded.
    `end_mi` is where the route ends (the last stretch's end where not given)."""
    spans: list[dict] = []
    for entry in entries:
        tier = entry.get("tier")
        if tier is None or tier < 3:
            continue
        last = spans[-1] if spans else None
        if last is not None and entry["from_mi"] - last["to_mi"] <= BUSY_JOIN_MI:
            last["to_mi"] = entry["to_mi"]
            last["lts"] = max(last["lts"], tier)
            if _street(entry) not in last["roads"]:
                last["roads"].append(_street(entry))
            continue
        spans.append(
            {
                "from_mi": entry["from_mi"],
                "to_mi": entry["to_mi"],
                "roads": [_street(entry)],
                "lts": tier,
            }
        )
    if end_mi is None:
        end_mi = entries[-1]["to_mi"] if entries else 0.0

    def at_station_end(span: dict) -> bool:
        if span["to_mi"] - span["from_mi"] > STATION_END_MI:
            return False
        at_start = station_ends[0] and span["from_mi"] <= STATION_END_TOUCH_MI
        at_end = station_ends[1] and end_mi - span["to_mi"] <= STATION_END_TOUCH_MI
        return at_start or at_end

    spans = [s for s in spans if not at_station_end(s)]
    kept = [s for s in spans if s["to_mi"] - s["from_mi"] >= BUSY_MIN_MI or s["lts"] >= 4]
    if len(kept) > MAX_BUSY_ROWS:
        longest = sorted(kept, key=lambda s: s["to_mi"] - s["from_mi"], reverse=True)
        keep = {id(s) for s in longest[:MAX_BUSY_ROWS]}
        kept = [s for s in kept if id(s) in keep]
    return [
        {
            "from_mi": round(s["from_mi"], 1),
            "to_mi": round(s["to_mi"], 1),
            "miles": round(s["to_mi"] - s["from_mi"], 2),
            "lts": s["lts"],
            "roads": [r for r in s["roads"] if r not in NAMELESS] or s["roads"][:1],
        }
        for s in kept
    ]


def risky_junctions(answer: dict) -> dict:
    """The very-high-stress (red) junctions, each with its mile, road and reason, and how
    many higher-stress (orange) ones there are besides."""
    found = answer.get("intersections") or []
    scale = _traced_scale(answer) / METRES_PER_MILE
    stretches = _stretches(answer)
    red = []
    for junction in found:
        if junction.get("severity") != "red":
            continue
        mile = junction.get("m", 0) * scale
        on = next((e for e in stretches if e["from_mi"] <= mile <= e["to_mi"]), None)
        red.append(
            {
                "at_mi": round(mile, 1),
                "road": _street(on) if on and _street(on) not in NAMELESS else None,
                "reason": junction.get("reason"),
                "lon_lat": [junction.get("lon"), junction.get("lat")],
            }
        )
    return {
        "very_high": red,
        "higher_count": sum(1 for j in found if j.get("severity") == "orange"),
    }


def _flat(origin: tuple[float, float]):
    """Miles east and north of `origin`, flat: enough within a few miles."""
    per_lon = EARTH_RADIUS_MI * math.radians(1) * math.cos(math.radians(origin[1]))
    per_lat = EARTH_RADIUS_MI * math.radians(1)
    return lambda p: ((p[0] - origin[0]) * per_lon, (p[1] - origin[1]) * per_lat)


def _resampled(line: list[list[float]], step: float) -> list[tuple[float, float]]:
    """The line's points every `step` miles along it, as flat miles from its start."""
    if len(line) < 2:
        return []
    flat = _flat((line[0][0], line[0][1]))
    xy = [flat((v[0], v[1])) for v in line]
    out = [xy[0]]
    need = step  # miles from here to the next sample
    for a, b in zip(xy, xy[1:], strict=False):
        seg, at = math.dist(a, b), 0.0
        while seg - at >= need:
            at += need
            t = at / seg
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            need = step
        need -= seg - at
    return out


def small_detours(
    line: list[list[float]],
    keep_at: list[tuple[float, float]] = (),
    street_at=None,
    distance_mi: float | None = None,
) -> list[dict]:
    """Spans where the route leaves its road and comes back to it close to where it left (a
    loop through a side lane, an out-and-back to a point off the road): at least twice the
    straight line between their ends, ends within DETOUR_GAP_MI, at least DETOUR_MIN_EXTRA_MI
    extra. `street_at(mile)` names the street at a mile along the route (`distance_mi` long):
    a span counts only where it starts and ends on one street and leaves it between; without
    it, only a tight loop counts (DETOUR_BLIND_GAP_MI). A span holding one of `keep_at` (a
    stop: the point of the trip) is left out. The biggest MAX_DETOURS, in route order."""
    step = DETOUR_STEP_MI
    pts = _resampled(line, step)
    n = len(pts)
    if n < 4:
        return []
    total = (n - 1) * step
    longest = min(int(DETOUR_MAX_MI / step), int(total / 2 / step))
    scale = (distance_mi / total) if distance_mi and total else 1.0
    named = street_at is not None
    gap2 = (DETOUR_GAP_MI if named else DETOUR_BLIND_GAP_MI) ** 2
    ratio = 2 if named else 3

    def same_road_left_between(i: int, j: int) -> bool:
        if not named:
            return True
        road = street_at(i * step * scale)
        if road is None or road != street_at(j * step * scale):
            return False
        return any(street_at(k * step * scale) != road for k in range(i + 1, j, 2))

    found = []
    for i in range(n):
        xi, yi = pts[i]
        best = None
        for j in range(i + 3, min(n, i + longest + 1)):
            dx, dy = pts[j][0] - xi, pts[j][1] - yi
            d2 = dx * dx + dy * dy
            if d2 > gap2:
                continue
            path = (j - i) * step
            gap = math.sqrt(d2)
            extra = path - gap
            if path >= ratio * gap and extra >= DETOUR_MIN_EXTRA_MI:
                if (best is None or extra > best[2] + step) and same_road_left_between(i, j):
                    best = (i, j, extra)
        if best:
            found.append(best)
    # The biggest first, each span once; a span wider than a bigger one it overlaps is the same
    # detour read from further along the road.
    found.sort(key=lambda f: (-f[2], f[1] - f[0]))
    flat = _flat((line[0][0], line[0][1]))
    kept_xy = [flat(p) for p in keep_at]
    chosen: list[tuple[int, int, float]] = []
    for i, j, extra in found:
        if any(i < cj and ci < j for ci, cj, _ in chosen):
            continue
        if any(min(math.dist(p, k) for p in pts[i : j + 1]) < 0.05 for k in kept_xy):
            continue
        chosen.append((i, j, extra))
        if len(chosen) == MAX_DETOURS:
            break
    origin = (line[0][0], line[0][1])
    per_lon = EARTH_RADIUS_MI * math.radians(1) * math.cos(math.radians(origin[1]))
    per_lat = EARTH_RADIUS_MI * math.radians(1)

    def lon_lat(p):
        return [round(origin[0] + p[0] / per_lon, 5), round(origin[1] + p[1] / per_lat, 5)]

    out = []
    for i, j, extra in sorted(chosen):
        apex = max(pts[i : j + 1], key=lambda p: math.dist(p, pts[i]))
        out.append(
            {
                "from_mi": round(i * step * scale, 1),
                "to_mi": round(j * step * scale, 1),
                "extra_mi": round(extra, 2),
                "leaves_at": lon_lat(pts[i]),
                "rejoins_at": lon_lat(pts[j]),
                "farthest_point": lon_lat(apex),
            }
        )
    return out


def _street_finder(answer: dict):
    """street_at(mile) over the description's stretches (casefolded), or None without one."""
    stretches = _stretches(answer)
    if not stretches:
        return None
    starts = [e["from_mi"] for e in stretches]

    def street_at(mile: float) -> str | None:
        k = bisect.bisect_right(starts, mile) - 1
        return _street(stretches[max(0, k)]).casefold()

    return street_at


def via_spurs(plan: Plan) -> list[dict]:
    """The via points the route reaches by an out-and-back of SPUR_MI or more."""
    out = []
    for i in plan.vias:
        length, junction = spur_at(plan.line, plan.points[i])
        if length >= SPUR_MI:
            out.append({"point": i, "spur_mi": round(length, 2), "leaves_at": list(junction)})
    return out


# --- Checkpoint order: an alleycat's best way round ------------------------------------------
#
# The owner, 2026-10-25: "Another common usage would be something for alleycat racing,
# basically if I scanned a sheet that would provide a number of points, and would find the
# best route around them." With `best_order`, plan_route keeps the start and the finish and
# rides the checkpoints between in the order that is quickest: the shortest orders by straight
# line (exact up to EXACT_MAX checkpoints, Held and Karp's dynamic programme; nearest
# neighbour and 2-opt beyond), then the first ORDER_TRIES of them planned, the quickest kept.

EXACT_MAX = 13
ORDER_TRIES = 3


def _round_mi(points: list, order: list[int]) -> float:
    return sum(haversine_mi(points[a], points[b]) for a, b in itertools.pairwise(order))


def _exact_order(points: list) -> list[int]:
    """The shortest order through points[1:-1] from points[0] to points[-1], by straight line."""
    n = len(points) - 2
    far = [
        [haversine_mi(points[i], points[j]) for j in range(len(points))] for i in range(len(points))
    ]
    best: dict[tuple[int, int], tuple[float, int]] = {
        (1 << i, i): (far[0][i + 1], -1) for i in range(n)
    }
    for size in range(2, n + 1):
        for subset in itertools.combinations(range(n), size):
            mask = sum(1 << i for i in subset)
            for j in subset:
                before = mask & ~(1 << j)
                best[(mask, j)] = min(
                    (best[(before, k)][0] + far[k + 1][j + 1], k) for k in subset if k != j
                )
    full = (1 << n) - 1
    _, last = min((best[(full, j)][0] + far[j + 1][n + 1], j) for j in range(n))
    order, mask = [], full
    while last != -1:
        order.append(last + 1)
        mask, last = mask & ~(1 << last), best[(mask, last)][1]
    return [0, *reversed(order), n + 1]


def _two_opt(points: list, order: list[int]) -> list[int]:
    """`order` bettered by reversing stretches of it while any reversal shortens it."""
    better = True
    while better:
        better = False
        for i in range(1, len(order) - 2):
            for j in range(i + 1, len(order) - 1):
                tried = order[:i] + order[i : j + 1][::-1] + order[j + 1 :]
                if _round_mi(points, tried) < _round_mi(points, order) - 1e-9:
                    order, better = tried, True
    return order


def best_orders(points: list, tries: int = ORDER_TRIES) -> list[list[int]]:
    """Up to `tries` orders of all the points (indices; the first and last fixed), shortest by
    straight line first: the best, then the best of its one-move changes (a stretch reversed,
    a checkpoint moved), which riding may favour where a river or a highway is in the way."""
    n = len(points) - 2
    if n <= 1:
        return [list(range(len(points)))]
    if n <= EXACT_MAX:
        best = _exact_order(points)
    else:
        left, order = set(range(1, n + 1)), [0]
        while left:
            nearest = min(left, key=lambda k: haversine_mi(points[order[-1]], points[k]))
            order.append(nearest)
            left.remove(nearest)
        best = _two_opt(points, [*order, n + 1])
    near: dict[tuple, float] = {}
    for i in range(1, n + 1):
        for j in range(i + 1, n + 1):
            flipped = best[:i] + best[i : j + 1][::-1] + best[j + 1 :]
            near[tuple(flipped)] = _round_mi(points, flipped)
        for j in range(1, n + 1):
            if j != i:
                moved = best[:i] + best[i + 1 :]
                moved.insert(j, best[i])
                near[tuple(moved)] = _round_mi(points, moved)
    near.pop(tuple(best), None)
    others = sorted(near, key=near.get)[: max(0, tries - 1)]
    return [best, *(list(o) for o in others)]


# --- Interval training: where an effort can run unbroken ------------------------------------
#
# The owner, 2026-10-25: "Are there any good routes for doing sets of 5 minutes on, 3
# minutes off, in repeat 5 times. We'd need to find places with limited needs to turn, go
# downhill, or stop during the on sets." Then: "the off set can be in the reverse direction.
# So ride up the hill for a workout, ride down it for a rest." An effort is broken by a stop
# or signal, a busy road to cross or join without one, a sharp turn, a descent or an LTS 4
# road; recovery can be anywhere.

INTERVAL_PAD_MI = 0.05  # slowing before, and getting going after, a stop or a turn
DESCENT_PCT = -2.0  # a grade this steep downhill breaks an effort
DESCENT_MIN_M = 150.0  # held this far (a few metres of dip is nothing)
STOP_CONTROLS = ("signal", "stop", "all_stop")
SHARP_TURN_DEG = 60  # a turn this sharp slows an effort
MAX_LAPS = 10
# Speed on a climb at the effort's pace: pace / (1 + CLIMB_SLOWING * grade%), so 18 mph on
# the flat is about 11 mph at 5% (a rough fit; only the minutes an effort takes need it).
CLIMB_SLOWING = 0.12
# Recovery rides slower than the effort: it covers this share of the effort's ground a minute.
RECOVERY_SHARE = 0.7
# The next effort may start up to this many times the asked rest later (waiting for a clear
# stretch); later than that the sets are no longer one session.
REST_SLACK = 1.5
# A route whose ends are this close is ridden again from the start (a loop, an out-and-back).
SAME_END_MI = 0.1
# A hill repeat climbs at least this on average; windows are tried every REPEAT_STEP_MI.
REPEAT_MIN_GRADE = 2.0
REPEAT_STEP_MI = 0.05
# A session's first effort is tried every this far along each clear stretch.
SESSION_STEP_MI = 0.05
# Ends this close on two sides of the start, ridden on from it, make a loop, not a turn back.
SEAM_MI = 0.1


# The climbs climbs_near rides up to check for stops and turns (one route call each).
CLIMB_CHECKS = 4
# A plan up a climb rides it when its length is within these shares of the climb's (the
# front end's rule for a climb ridden, `hillseek.RIDDEN_MIN`/`RIDDEN_MAX`).
CLIMB_RIDDEN = (0.8, 1.3)


def climb_minutes(miles: float, grade_pct: float, pace: float) -> float:
    """The minutes up a climb of that length and grade at an effort `pace` mph on the flat."""
    speed = pace / (1 + CLIMB_SLOWING * max(0.0, grade_pct))
    return round(miles / speed * 60, 1)


def _grades(answer: dict) -> list[tuple[float, float, float]]:
    """(from_mi, to_mi, grade %) between the profile's samples, from the heights themselves
    (a thinned profile keeps each window's steepest sample grade, which overstates a dip).
    The profile's `m` is along the route as `distance_m` measures it."""
    profile = answer.get("profile") or {}
    out, last = [], None
    for m, height in zip(profile.get("m") or [], profile.get("elevation_m") or [], strict=False):
        if height is None:
            last = None
            continue
        if last is not None and m > last[0]:
            out.append(
                (
                    last[0] / METRES_PER_MILE,
                    m / METRES_PER_MILE,
                    (height - last[1]) / (m - last[0]) * 100,
                )
            )
        last = (m, height)
    return out


def _breaks(answer: dict) -> tuple[list[tuple[float, float, str]], dict]:
    """The spans (from_mi, to_mi, why) an effort cannot run through, and how many of each."""
    scale = _traced_scale(answer) / METRES_PER_MILE
    distance_mi = (answer.get("distance_m") or 0.0) / METRES_PER_MILE
    spans: list[tuple[float, float, str]] = []
    counts: dict[str, int] = {}

    def add(a: float, b: float, why: str) -> None:
        spans.append((a, b, why))
        counts[why] = counts.get(why, 0) + 1

    events = answer.get("junctions_debug")
    if events is None:  # only the flagged ones: a quiet stop sign goes unseen
        events = answer.get("intersections") or []
    for event in events:
        control, tier = event.get("control"), event.get("crossed_tier")
        mile = event.get("m", 0) * scale
        if control in STOP_CONTROLS:
            why = "signal" if control == "signal" else "stop sign"
            add(mile - INTERVAL_PAD_MI, mile + INTERVAL_PAD_MI, why)
        elif control == "none" and tier is not None and tier >= 3:
            add(mile - INTERVAL_PAD_MI, mile + INTERVAL_PAD_MI, "busy road to cross or join")
    before = None
    for entry in answer.get("description") or []:
        if entry.get("kind") != "stretch":
            continue
        turn = entry.get("turn") or {}
        out = (turn.get("shape") or {}).get("out")
        if out is not None:  # the angle itself, where the answer has it
            sharp = abs(out) >= SHARP_TURN_DEG
        else:
            # A named trail or street going on under its own name is no turn to slow for.
            same_way = (
                before is not None
                and entry.get("street") not in (None, "path")
                and before.get("street") == entry.get("street")
            )
            sharp = turn.get("movement") in ("left", "right") and not same_way
        if sharp:
            add(
                entry["from_mi"] - INTERVAL_PAD_MI, entry["from_mi"] + INTERVAL_PAD_MI, "sharp turn"
            )
        if (entry.get("tier") or 0) >= 4:
            add(entry["from_mi"], entry["to_mi"], "LTS 4 road")
        before = entry
    run = None
    for a, b, grade in _grades(answer):
        if grade <= DESCENT_PCT:
            run = [run[0] if run else a, b]
            continue
        if run and (run[1] - run[0]) * METRES_PER_MILE >= DESCENT_MIN_M:
            add(run[0], run[1], "descent")
        run = None
    if run and (run[1] - run[0]) * METRES_PER_MILE >= DESCENT_MIN_M:
        add(run[0], run[1], "descent")
    clipped = [(max(0.0, a), min(distance_mi, b), why) for a, b, why in spans if b > 0]
    return sorted(clipped), counts


def _clear(spans: list[tuple[float, float, str]], distance_mi: float) -> list[tuple[float, float]]:
    """The stretches between the breaks."""
    out, at = [], 0.0
    for a, b, _ in spans:
        if a > at:
            out.append((at, a))
        at = max(at, b)
    if distance_mi > at:
        out.append((at, distance_mi))
    return out


def _minutes_along(answer: dict, pace: float):
    """minutes(mile): the effort's minutes from the start to `mile`, slower up the climbs."""
    marks, total, last_mi = [(0.0, 0.0)], 0.0, 0.0
    for a, b, grade in _grades(answer):
        if b <= last_mi:
            continue
        if a > last_mi:  # a gap in the heights: flat
            total += (a - last_mi) / pace * 60
            marks.append((a, total))
        speed = pace / (1 + CLIMB_SLOWING * grade) if grade > 0 else pace
        total += (b - max(a, last_mi)) / speed * 60
        marks.append((b, total))
        last_mi = b
    miles = [m for m, _ in marks]

    def minutes(mile: float) -> float:
        if mile >= last_mi:
            return total + (mile - last_mi) / pace * 60
        k = max(1, bisect.bisect_left(miles, mile))
        (m0, t0), (m1, t1) = marks[k - 1], marks[k]
        return t0 + (t1 - t0) * ((mile - m0) / (m1 - m0) if m1 > m0 else 0.0)

    return minutes


def _mile_after(minutes, start: float, wanted: float, end: float) -> float | None:
    """The mile `wanted` minutes on from `start`, or None past `end`."""
    goal = minutes(start) + wanted
    if minutes(end) < goal:
        return None
    lo, hi = start, end
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if minutes(mid) < goal else (lo, mid)
    return hi


def _rise_ft(answer: dict, a: float, b: float) -> float:
    """The height gained, feet, from mile `a` to mile `b` (net: rolling ground is none)."""
    rise = 0.0
    for x, y, grade in _grades(answer):
        overlap = min(y, b) - max(x, a)
        if overlap > 0:
            rise += grade / 100 * overlap * METRES_PER_MILE
    return rise * FEET_PER_METRE


def _along_line(line: list, mi: float) -> tuple:
    """The point `mi` along the line from its first point."""
    done = 0.0
    for p, q in itertools.pairwise(line):
        step = haversine_mi(tuple(p[:2]), tuple(q[:2]))
        if done + step >= mi and step > 0:
            f = (mi - done) / step
            return (p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f)
        done += step
    return tuple(line[-1][:2])


def _seamless(line: list) -> bool:
    """Whether a route that ends where it began rides on through its start (a loop) rather
    than turning back there (an out-and-back): the line SEAM_MI after the start and SEAM_MI
    before the end are apart."""
    if len(line) < 3:
        return True  # no line to tell by: the answer said loop
    return haversine_mi(_along_line(line, SEAM_MI), _along_line(line[::-1], SEAM_MI)) > SEAM_MI / 2


def _session(clear, minutes, start, on_min, rest_mi, sets):
    """The efforts (from_mi, to_mi, extra rest miles) of one session from `start`: each next
    one begins after rest_mi of recovery, or up to REST_SLACK times that later where it must
    wait for a clear stretch."""
    efforts, at = [], start
    while len(efforts) < sets:
        latest = at + rest_mi * (REST_SLACK - 1) if efforts else at
        fit = None
        for a, b in clear:
            begin = max(a, at)
            if begin > min(b, latest):
                continue
            finish = _mile_after(minutes, begin, on_min, b)
            if finish is not None:
                fit = (begin, finish)
                break
        if fit is None:
            break
        efforts.append((fit[0], fit[1], fit[0] - at))
        at = fit[1] + rest_mi
    return efforts


def _laps(clear, minutes, distance_mi: float, seamless: bool):
    """The clear stretches and minutes(mile) over MAX_LAPS laps of a route ridden again from
    the start; a loop's stretches either side of the start join where `seamless` (no U-turn)."""
    lap_min = minutes(distance_mi)
    out: list[list[float]] = []
    for lap in range(MAX_LAPS):
        for a, b in clear:
            a, b = a + lap * distance_mi, b + lap * distance_mi
            if seamless and out and abs(out[-1][1] - a) < 1e-6:
                out[-1][1] = b
            else:
                out.append([a, b])

    def lapped(mile: float) -> float:
        lap = min(int(mile // distance_mi), MAX_LAPS - 1) if distance_mi else 0
        return lap * lap_min + minutes(mile - lap * distance_mi)

    return [tuple(c) for c in out], lapped


def interval_check(answer: dict, ask: dict, roads_at=None) -> dict:
    """Whether the route holds the asked sets in one session (`ask`: on_minutes, off_minutes,
    sets, pace_mph on the flat), riding it again from the start where it ends where it began:
    the best session's efforts, its rests, the hill repeats (a clear climb ridden up for each
    effort and back down to recover), the longest clear stretches and what breaks the rest."""

    def asked(key: str, default: float) -> float:
        return float(default if ask.get(key) is None else ask[key])

    on_min, off_min = asked("on_minutes", 5), asked("off_minutes", 3)
    sets, pace = int(asked("sets", 5)), asked("pace_mph", 18)
    distance_mi = (answer.get("distance_m") or 0.0) / METRES_PER_MILE
    minutes = _minutes_along(answer, pace)
    spans, counts = _breaks(answer)
    clear = [c for c in _clear(spans, distance_mi) if c[1] - c[0] > 0.01]
    line = (answer.get("geometry") or {}).get("coordinates") or []
    again = bool(answer.get("loop")) or (
        len(line) > 1 and haversine_mi(tuple(line[0][:2]), tuple(line[-1][:2])) <= SAME_END_MI
    )
    rest_mi = pace * RECOVERY_SHARE * off_min / 60
    ridden, along = clear, minutes
    if again and distance_mi > 0:
        # Ridden round: the start is no break on a loop, but is the turn of an out-and-back.
        seamless = bool(answer.get("loop")) or _seamless(line)
        ridden, along = _laps(clear, minutes, distance_mi, seamless)
    best: list = []
    for a, b in clear:  # a session's first effort, tried all along each clear stretch
        start = a
        while start < b and len(best) < sets:
            found = _session(ridden, along, start, on_min, rest_mi, sets)
            if len(found) > len(best):
                best = found
            start += SESSION_STEP_MI
        if len(best) >= sets:
            break
    per_mi = 60 / (pace * RECOVERY_SHARE)

    def on_route(mile: float) -> tuple[int, float]:
        """(lap, mile on the route) of a mile ridden round, rounding clear of a lap's edge."""
        if not (again and distance_mi):
            return 0, mile
        lap = int((mile + 1e-6) // distance_mi)
        return lap, max(0.0, mile - lap * distance_mi)

    def roads_round(start: float, finish: float) -> list:
        if finish <= distance_mi or not again:
            return roads_at(start, min(finish, distance_mi))
        rest = [
            r for r in roads_at(0.0, finish - distance_mi) if r not in roads_at(start, distance_mi)
        ]
        return roads_at(start, distance_mi) + rest

    efforts = []
    for k, (a, b, extra) in enumerate(best):
        lap, start = on_route(a)
        finish = b - lap * distance_mi if again and distance_mi else b
        through = again and finish > distance_mi + 1e-6  # on through the start
        efforts.append(
            {
                "set": k + 1,
                **({"lap": lap + 1} if again else {}),
                "from_mi": round(start, 2),
                "to_mi": round(finish - distance_mi if through else finish, 2),
                **({"through_start": True} if through else {}),
                **({"rest_min": round(off_min + extra * per_mi, 1)} if k else {}),
                **({"roads": roads_round(start, finish)} if roads_at else {}),
            }
        )
    # Repeats: the climbiest on_min window of each clear stretch, ridden this way for each
    # effort and back the other way to recover (only this direction needs to be clear).
    repeats = []
    for a, b in clear:
        top = None
        start = a
        while True:
            finish = _mile_after(minutes, start, on_min, b)
            if finish is None:
                break
            rise = _rise_ft(answer, start, finish)
            if top is None or rise > top[2]:
                top = (start, finish, rise)
            start += REPEAT_STEP_MI
        if top is None:
            continue
        start, finish, gain = top
        grade = gain / FEET_PER_METRE / ((finish - start) * METRES_PER_MILE) * 100
        if grade < REPEAT_MIN_GRADE:
            continue
        repeats.append(
            {
                "from_mi": round(start, 2),
                "to_mi": round(finish, 2),
                "climb_ft": round(gain),
                "avg_grade_pct": round(grade, 1),
                **({"roads": roads_at(start, finish)} if roads_at else {}),
            }
        )
    repeats.sort(key=lambda r: -r["climb_ft"])
    longest = sorted(clear, key=lambda c: c[1] - c[0], reverse=True)[:5]
    out = {
        "asked": f"{sets} x {on_min:g} min on, {off_min:g} min off, {pace:g} mph on the flat",
        "sets_in_one_session": len(efforts),
        "efforts": efforts,
        "repeats": repeats[:3],
        "longest_clear": [
            {
                "from_mi": round(a, 2),
                "to_mi": round(b, 2),
                "effort_minutes": round(minutes(b) - minutes(a), 1),
                **({"roads": roads_at(a, b)} if roads_at else {}),
            }
            for a, b in sorted(longest)
        ],
        "breaks": counts,
    }
    if repeats:
        out["repeat_note"] = (
            f"a repeat holds all {sets} sets: ride it up for each effort, back down to recover"
        )
    if answer.get("junctions_debug") is None:
        out["note"] = "only flagged junctions were read: a quiet stop sign may be missing"
    return out


def _intervals_asked(value) -> dict | None:
    """The interval set asked for, checked, or None."""
    if value is None or value is False:
        return None
    if value is True:
        value = {}
    if not isinstance(value, dict):
        raise ToolError("intervals is {on_minutes, off_minutes, sets, pace_mph}")
    asked = {}
    for key, low, high in (
        ("on_minutes", 0.5, 60),
        ("off_minutes", 0, 60),
        ("sets", 1, 30),
        ("pace_mph", 4, 35),
    ):
        if value.get(key) is not None:
            try:
                number = float(value[key])
            except (TypeError, ValueError):
                raise ToolError(f"intervals.{key} is a number") from None
            if not low <= number <= high:
                raise ToolError(f"intervals.{key} is {low:g} to {high:g}")
            asked[key] = number
    return asked or {"on_minutes": 5}


def _roads_between(answer: dict):
    stretches = _stretches(answer)

    def roads_at(a: float, b: float) -> list[str]:
        names = [
            _street(e)
            for e in stretches
            if min(e["to_mi"], b) - max(e["from_mi"], a) >= 0.1 and _street(e) not in NAMELESS
        ]
        return list(dict.fromkeys(names))[:4]

    return roads_at


def route_details(
    plan: Plan, stations: list[Station] | None = None, corking: dict | None = None
) -> dict:
    """What the route rides, for the answer: its roads, busy stretches, very-high-stress
    junctions, scenic roads and small detours. With `stations`, a short busy bit at a start or
    end that is a station's way in is left out of the busy stretches (`busy_stretches`)."""
    answer = plan.answer
    out: dict = {}
    roads = road_list(answer)
    if roads:
        out.update(roads)
    if answer.get("description") or answer.get("description_overview"):
        ends = (False, False)
        # The route line's own ends: a loop's line comes back to its start (the site adds the
        # closing leg), and a transit trip's line is its first ride, which ends at the station.
        line = (answer.get("geometry") or {}).get("coordinates") or plan.points
        if stations and line:
            ends = tuple(
                any(_at_station(tuple(point[:2]), station) for station in stations)
                for point in (line[0], line[-1])
            )
        out["busy_stretches"] = busy_stretches(answer, ends)
        # What the list leaves out (short LTS 3 bits, short bits at a station end, past
        # MAX_BUSY_ROWS), so it adds up.
        stress = answer.get("stress_m") or {}
        total = sum(stress.get(k, 0.0) or 0.0 for k in ("3", "4", "5")) / METRES_PER_MILE
        unlisted = total - sum(b["miles"] for b in out["busy_stretches"])
        if unlisted >= 0.1:
            out["busy_unlisted_mi"] = round(unlisted, 1)
    if answer.get("intersections") is not None:
        out["junctions"] = risky_junctions(answer)
    scenic: dict[tuple[str, str], float] = {}
    for s in _scenic_rows(answer):
        key = (s["road"], s["designation"])
        scenic[key] = scenic.get(key, 0.0) + s["to_mi"] - s["from_mi"]
    if scenic:
        out["scenic_roads"] = [
            {"road": road, "designation": what, "miles": round(miles, 1)}
            for (road, what), miles in scenic.items()
            if miles >= 0.05
        ]
    stops = [plan.points[i] for i in range(1, len(plan.points) - 1) if i not in set(plan.vias)]
    if not answer.get("loop"):
        detours = small_detours(
            plan.line,
            stops,
            _street_finder(answer),
            (answer.get("distance_m") or 0.0) / METRES_PER_MILE,
        )
        if detours:
            out["small_detours"] = detours
    spurs = via_spurs(plan)
    if spurs:
        out["via_spurs"] = spurs
    legs = leg_rows(plan)
    if legs:
        out["legs"] = legs
    out.update(grades_and_hazards(answer))
    out.update(route_closures(plan))
    capacity = mass_capacity(answer, corking)
    if capacity:
        out["mass_capacity"] = capacity
    return out


# A skip by mile takes the corked junction this near it (our default: a block or so).
CORK_SKIP_NEAR_MI = 0.05


def corker_plan(corkers: dict, corking: dict | None, total_m: float) -> dict:
    """The corkers a Mass Ride needs with the organiser's triage (the owner, 2026-11-10: "allow a
    triage of roads for corking, Basically ask to not cork some lower stress roads"): the
    junctions corked and those left out, the corkers held at once along the route as
    [from_m, to_m, corkers] steps (a junction is held from when the group's head reaches it until
    its tail has passed, the site's `exit_m`), the most held at once, and the ride's count, that
    times the rotation factor: corkers leapfrog to the junctions ahead, and a factor of 2 is
    corkers riding twice the group's pace (a corker freed when the tail passes catches the head a
    group's length on in the same time the hold took). Without `exit_m` (an older site) only the
    site's own figures."""
    corking = corking or {}
    floor = corking.get("from_lts")
    skips = list(corking.get("skip") or [])
    kept: list[dict] = []
    skipped: list[dict] = []
    matched: set[int] = set()
    for j in corkers.get("junctions") or []:
        mi = (j.get("m") or 0) / METRES_PER_MILE
        street = str(j.get("street") or "")
        why = None
        lts = j.get("lts")
        if isinstance(floor, (int, float)) and isinstance(lts, (int, float)) and lts < floor:
            why = f"below LTS {floor:g}"
        for k, skip in enumerate(skips):
            # A name in whole words, any case, so "K St" is not "Park St".
            hit = (
                isinstance(skip, str)
                and bool(street)
                and re.search(rf"(?<!\w){re.escape(skip.strip())}(?!\w)", street, re.IGNORECASE)
                is not None
            ) or (
                isinstance(skip, (int, float))
                and not isinstance(skip, bool)
                and abs(mi - skip) <= CORK_SKIP_NEAR_MI
            )
            if hit:
                matched.add(k)
                why = why or "asked to skip"
        (skipped if why else kept).append({**j, **({"why": why} if why else {})})
    factor = corkers.get("rotation_factor") or 2
    out: dict = {
        "kept": kept,
        "skipped": skipped,
        "unmatched": [s for k, s in enumerate(skips) if k not in matched],
        "rotation_factor": factor,
        "at_least": corkers.get("at_least"),
    }
    timed = all(isinstance(j.get("exit_m"), (int, float)) for j in kept)
    if not timed:
        out.update(
            about=corkers.get("headline"),
            most=corkers.get("most_at_once"),
            most_m=corkers.get("most_at_once_m"),
            held=None,
        )
        return out

    def start(j: dict) -> float:
        return j["at_m"] if isinstance(j.get("at_m"), (int, float)) else j["m"]

    def held_at(x: float) -> int:
        return sum(j["corkers"] or 0 for j in kept if start(j) <= x < j["exit_m"])

    cuts = sorted({0.0, float(total_m), *(start(j) for j in kept), *(j["exit_m"] for j in kept)})
    cuts = [c for c in cuts if 0 <= c <= total_m]
    held: list[list[float]] = []
    most, most_m = 0, None
    for a, b in zip(cuts, cuts[1:], strict=False):
        if b <= a:
            continue
        n = held_at(a)
        if held and held[-1][2] == n:
            held[-1][1] = b
        else:
            held.append([a, b, n])
        if n > most:
            most, most_m = n, a
    # At the end itself the junctions near it are still held (a group longer than what is left).
    n = held_at(float(total_m))
    if n > most:
        most, most_m = n, float(total_m)
        if held:
            held[-1][2] = max(held[-1][2], n)
    out.update(about=math.ceil(most * factor), most=most, most_m=most_m, held=held)
    return out


def _corker_length(answer: dict, corkers: dict) -> float:
    """The length the site counted the corkers along: the route's, or to its last junction."""
    ends = [
        v
        for j in corkers.get("junctions") or []
        for v in (j.get("m"), j.get("at_m"))
        if isinstance(v, (int, float))
    ]
    return max([answer.get("distance_m") or 0.0, *ends])


def mass_capacity(answer: dict, corking: dict | None = None) -> dict | None:
    """A Mass Ride's road capacity and corker needs, in miles, for an assistant to improve the
    route on (the owner, 2026-10-29: "allow for things like road capacity and corker
    requirements for mass rides to be returned so the agents can improve opon them"): what the
    ride size needs and what the route carries, where it falls short, and the corkers held at
    once. None off a Mass Ride."""
    found = answer.get("mass_capacity")
    if not found:
        return None

    def mi(metres) -> float | None:
        return None if metres is None else round(metres / METRES_PER_MILE, 2)

    out: dict = {
        "riders": found.get("riders"),
        "needs_riders_per_min": found.get("need_riders_per_min"),
        "narrowest_riders_per_min": found.get("narrowest_riders_per_min"),
        "narrowest_at_mi": mi(found.get("narrowest_m")),
        "miles_below_need": mi(found.get("below_need_m") or 0),
        "capacity_changes": found.get("capacity_changes"),
        "narrow_stretches": [
            {
                "from_mi": mi(row.get("from_m")),
                "to_mi": mi(row.get("to_m")),
                "street": row.get("street"),
                "riders_per_min": row.get("riders_per_min"),
                **({"avoid": True} if row.get("avoid") else {}),
            }
            for row in found.get("narrow_stretches") or []
        ],
        "how_to_improve": (
            "The planner weighs capacity only between a start and an end up to about 15 mi apart"
            " (with stops or via points it reports, not chooses). To lift a narrow stretch above"
            " the need, plan again by way of a wider parallel street and compare the two"
            " answers; fewer changes of width keep the group together; fewer busy junctions"
            " need fewer corkers."
        ),
    }
    corkers = found.get("corkers")
    if corkers:
        plan = corker_plan(corkers, corking, _corker_length(answer, corkers))

        def row(j: dict) -> dict:
            return {
                "at_mi": mi(j.get("m")),
                "street": j.get("street"),
                "corkers": j.get("corkers"),
                **({"lts": j["lts"]} if j.get("lts") is not None else {}),
                **({"why": j["why"]} if j.get("why") else {}),
            }

        out["corkers"] = {
            "about": plan["about"],
            "at_least": plan["at_least"],
            "most_held_at_once": plan["most"],
            "most_held_at_mi": mi(plan["most_m"]),
            "how": (
                f"about = the most held at once x {plan['rotation_factor']:g}: corkers leapfrog"
                " to the junctions ahead, riding about twice the group's pace (a corker freed as"
                " the tail passes catches the head a group's length on in the time the hold"
                " took)"
            ),
            "junctions": [row(j) for j in plan["kept"]],
        }
        if corking:
            out["corkers"]["corking"] = corking
            out["corkers"]["about_corking_every_junction"] = corkers.get("headline")
            out["corkers"]["not_corked"] = [row(j) for j in plan["skipped"]]
            if plan["unmatched"]:
                out["corkers"]["skip_matched_nothing"] = plan["unmatched"]
    else:
        out["corkers"] = None
        out["corkers_note"] = "the intersections were not checked, so the corkers are not known"
    return out


# --- Closures, for an assistant to say ---------------------------------------------------------
#
# The owner, 2026-10-25, after a connector route ran along Lake Frank's closed Lakeside Trail
# ("make sure that the MCP server has access to the closure list"): the site's answer said the
# route went through, but the summary left it out. A route's closures and a place's are said.

# A closure's effect on the route, as the site names it (`routemaker.workzones`), and the ones
# worth saying: "none" is no effect, "possible" a DDOT permit that is never routed round.
CLOSURE_SAID = ("on_route", "may_still_apply", "routed_round", "bypassed")
# A stop or via point reached this close to a closed stretch is on it (metres along the route).
ON_CLOSURE_M = 30.0
# Potential closures along the route (a permit, planned utility work: effect "possible"), the
# first this many by mile. The owner, 2026-11-02: return "the link or citation to where the
# closures would or could be".
MAX_POTENTIAL = 20
# The site lists the potential closures on its map view round the route (up to 400 m off it),
# without saying where the route meets them: one is along the route where its line comes this
# close (miles, about 30 m).
POTENTIAL_NEAR_MI = 0.02
CLOSURES_NEAR_MAX_MI = 10.0  # the site's map view is at most 0.4 by 0.3 degrees


def _resampled_lonlat(line: list, step_mi: float = 0.02) -> list[tuple[float, float]]:
    """The line's points, with more between any two further apart than `step_mi`."""
    out = [(line[0][0], line[0][1])]
    for p, q in zip(line, line[1:], strict=False):
        n = max(1, math.ceil(haversine_mi((p[0], p[1]), (q[0], q[1])) / step_mi))
        out.extend(
            (p[0] + (q[0] - p[0]) * k / n, p[1] + (q[1] - p[1]) * k / n) for k in range(1, n + 1)
        )
    return out


def _points_along(plan: Plan) -> list[tuple[int, float]]:
    """Each stop or via point and the metres along the route where it is reached (the end of
    its leg, `leg_ends`), on the answer's own scale."""
    ends = plan.answer.get("leg_ends") or []
    line = plan.line
    if len(ends) != len(plan.points) - 1 or len(line) < 2:
        return []
    cum = [0.0]
    for p, q in zip(line, line[1:], strict=False):
        cum.append(cum[-1] + haversine_mi((p[0], p[1]), (q[0], q[1])) * METRES_PER_MILE)
    scale = (plan.answer.get("distance_m") or cum[-1]) / (cum[-1] or 1.0)
    return [(i + 1, cum[min(end, len(cum) - 1)] * scale) for i, end in enumerate(ends[:-1])]


def _route_cells(flat_route: list) -> dict[tuple[int, int], list[int]]:
    """The route's steps by the POTENTIAL_NEAR_MI square each comes near, so a point checks
    only the few steps round it."""
    cells: dict[tuple[int, int], list[int]] = {}
    for i in range(len(flat_route) - 1):
        (ax, ay), (bx, by) = flat_route[i], flat_route[i + 1]
        x0 = math.floor((min(ax, bx) - POTENTIAL_NEAR_MI) / POTENTIAL_NEAR_MI)
        x1 = math.floor((max(ax, bx) + POTENTIAL_NEAR_MI) / POTENTIAL_NEAR_MI)
        y0 = math.floor((min(ay, by) - POTENTIAL_NEAR_MI) / POTENTIAL_NEAR_MI)
        y1 = math.floor((max(ay, by) + POTENTIAL_NEAR_MI) / POTENTIAL_NEAR_MI)
        if (x1 - x0 + 1) * (y1 - y0 + 1) > 10_000:  # a long straight step: checked everywhere
            cells.setdefault(("all", 0), []).append(i)  # type: ignore[arg-type]
            continue
        for cx in range(x0, x1 + 1):
            for cy in range(y0, y1 + 1):
                cells.setdefault((cx, cy), []).append(i)
    return cells


def _route_span(flat_route: list, cum: list, cells: dict, flat, pts: list):
    """The miles along the route (flat points `flat_route`, miles `cum` at each, steps by
    `_route_cells`) where it comes within POTENTIAL_NEAR_MI of any of `pts`, first and last;
    None when it never does."""
    near = []
    for p in pts:
        x, y = flat((p[0], p[1]))
        cell = (math.floor(x / POTENTIAL_NEAR_MI), math.floor(y / POTENTIAL_NEAR_MI))
        best = None
        for i in cells.get(cell, []) + cells.get(("all", 0), []):  # type: ignore[call-overload]
            (ax, ay), (bx, by) = flat_route[i], flat_route[i + 1]
            dx, dy = bx - ax, by - ay
            seg = dx * dx + dy * dy
            f = 0.0 if seg == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / seg))
            d = math.hypot(ax + f * dx - x, ay + f * dy - y)
            if d <= POTENTIAL_NEAR_MI and (best is None or d < best[0]):
                best = (d, cum[i] + f * (cum[i + 1] - cum[i]))
        if best is not None:
            near.append(best[1])
    return (min(near), max(near)) if near else None


PIECED_SOURCES = (
    "reviewer",
    "ddot_advisory",
    "purple_line",
    "fcpa",
    "park_alert",
    "protrack",
    "wssc",
    "sha",
    "moco",
)


def _closure_id(row: dict) -> str:
    """The closure a row is part of: a reviewer's closure comes as a row for each of its ways,
    `reviewer-{closure}-{way}`, and a DDOT project advisory's for each of its lines,
    `ddot_advisory-{closure}-{line}`, as is a Purple Line update's (`purple_line-...`), a Fairfax
    park alert's (`fcpa-...`) and planned work's (v0.17.0: `protrack-{project}-{line}`,
    `wssc-{main}-{line}`), and a Maryland Road Closure Reporter closure's (`sha-{closure}-{n}`)."""
    zone_id = str(row.get("id") or "")
    if row.get("source") in PIECED_SOURCES:
        return re.sub(r"-\d+$", "", zone_id)
    return zone_id or str((row.get("title"), row.get("when_text")))


def _closure_row(row: dict) -> dict:
    """One closure as an assistant tells it: what, until when, what it does, and who says so."""
    out = {
        "what": row.get("title") or row.get("road") or "closure",
        "when": row.get("when_text"),
        "effect": row.get("effect"),
        "says": row.get("effect_text"),
        "source": row.get("source_name"),
        "url": row.get("url"),
    }
    if row.get("delay_s"):
        out["detour_minutes"] = round(row["delay_s"] / 60)
    return {k: v for k, v in out.items() if v is not None}


def _notice_row(row: dict) -> dict:
    """A "Check before you go" notice on the route (an NPS park alert, or a park's deer-
    management closure at the ride's time, v0.12.3): a warning, never routed round."""
    out = {
        "where": row.get("area_name"),
        "what": row.get("title"),
        "when": row.get("when_text"),
        "says": row.get("text"),
        "source": row.get("source_name"),
        "url": row.get("url"),
    }
    return {k: v for k, v in out.items() if v}


# The site's words for a closure a run or a walk rides through because its source does not
# say people on foot are kept out (`routemaker.workzones.effect_text`).
ON_FOOT_UNSAID = "the source does not say whether people on foot can pass"


def _on_foot_unsaid(row: dict) -> bool:
    return ON_FOOT_UNSAID in (row.get("says") or "")


def route_closures(plan: Plan) -> dict:
    """The closures the site found on or round the route, one row per closure (a reviewer's
    closure comes as a row for each of its ways), and the points that sit on one."""
    zones = plan.answer.get("work_zones")
    if not isinstance(zones, dict):
        return {}
    rows: dict[tuple, dict] = {}
    spans: list[tuple[float, float, tuple]] = []  # where the route rides through one, metres
    potential: dict[str, dict] = {}
    route = plan.line
    flat = _flat((route[0][0], route[0][1])) if len(route) >= 2 else None
    flat_route = [flat((p[0], p[1])) for p in route] if flat else []
    cum = _cum_miles(route) if flat else []
    cells = _route_cells(flat_route)
    total_mi = (plan.answer.get("distance_m") or 0.0) / METRES_PER_MILE
    scale = total_mi / cum[-1] if total_mi and cum and cum[-1] else 1.0
    for row in zones.get("closures") or []:
        if row.get("effect") == "possible":
            # A permit or planned work on the map round the route: it may close the road (or
            # the bike lane) some time in its window. Never routed round: said, with its
            # source, when the route rides along it.
            pts = row.get("line") or ([row["point"]] if row.get("point") else [])
            span = _route_span(flat_route, cum, cells, flat, pts) if flat and pts else None
            if span is None:
                continue
            said = potential.setdefault(_closure_id(row), _closure_row(row))
            said.pop("effect", None)
            said["closes"] = "bike lane" if row.get("kind") == "lane" else "road"
            a, b = span[0] * scale, span[1] * scale
            said["from_mi"] = round(min(said.get("from_mi", a), a), 1)
            said["to_mi"] = round(max(said.get("to_mi", b), b), 1)
            if row.get("point") and "lon_lat" not in said:
                said["lon_lat"] = row["point"]
            continue
        if row.get("effect") not in CLOSURE_SAID:
            continue
        key = (_closure_id(row), row.get("effect"))
        kept = rows.setdefault(key, _closure_row(row))
        if row.get("from_m") is not None and row.get("to_m") is not None:
            a = round(row["from_m"] / METRES_PER_MILE, 1)
            b = round(row["to_m"] / METRES_PER_MILE, 1)
            kept["from_mi"] = min(kept.get("from_mi", a), a)
            kept["to_mi"] = max(kept.get("to_mi", b), b)
            # A blocked bike lane leaves the road open: listed, not warned about.
            if row["effect"] == "on_route" and row.get("kind") != "lane":
                spans.append((row["from_m"], row["to_m"], key))
    notices = [_notice_row(n) for n in zones.get("notices") or [] if isinstance(n, dict)]
    if not rows and not notices and not potential:
        return {}
    said = sorted(rows.values(), key=lambda r: (r["effect"] != "on_route", r.get("from_mi", 0)))
    out: dict = {"closures": said}
    if potential:
        listed = sorted(potential.values(), key=lambda r: r["from_mi"])
        out["potential_closures"] = listed[:MAX_POTENTIAL]
        if len(listed) > MAX_POTENTIAL:
            out["potential_closures_more"] = len(listed) - MAX_POTENTIAL
        out["potential_closures_note"] = (
            "permits and planned work that allow closing the road or bike lane some time in"
            " their window: they may be open, and the route is not planned round them. Give"
            " the rider each one's source and link; avoid one with revise_route's avoid"
            " (from_mi, to_mi) if the rider wants."
        )
    if notices:
        out["check_before_you_go"] = notices
    if zones.get("ride_at"):
        # A shared route's answer (open_link) is as it was planned: say for when.
        out["closures_checked_for"] = zones["ride_at"]
    if spans:
        # A point reached on a closed stretch makes the router ride it (a landmark only the
        # closed path goes past): the likeliest reason it found no way round.
        on = []
        for i, metres in _points_along(plan):
            key = next(
                (k for a, b, k in spans if a - ON_CLOSURE_M <= metres <= b + ON_CLOSURE_M), None
            )
            if key is not None:
                on.append(f"point {i} ({rows[key]['what']}, {rows[key]['when']})")
        words = "The route goes through a closure: tell the rider."
        if on:
            words += (
                f" Reached on a closed stretch: {'; '.join(on)}. Move it off the closed path"
                " and plan again."
            )
        else:
            # A run or a walk is not routed round a closure to traffic whose source is silent
            # on people on foot (the site's `for_plan`): the router never tried, so it is not
            # said to have found no way round (routing hunt 4, C4-1).
            silent = {k for _, _, k in spans if _on_foot_unsaid(rows[k])}
            if any(k not in silent for _, _, k in spans):
                words += " The router found no way round from these points: try others."
            if silent:
                names = "; ".join(rows[k]["what"] for k in sorted(silent, key=str))
                words += (
                    f" The source does not say people on foot may pass {names}, so this run or"
                    " walk was not routed round it."
                )
        out["closure_warning"] = words
    return out


# --- Optimizing a route: its figures, its legs, its segments, roads to avoid ------------------
#
# The owner, 2026-11-02: "We'd want to make sure that an llm would be able to revise a call and
# would have access to routing data for optimization", for long trips and rides done often,
# such as a commute. Everything here reads the answer the site already gave (or a draft's kept
# one) and keeps nothing new.

# Roads to avoid (`blocked_lines`, as Ride's "Road closed"): the site takes up to 10 lines of
# up to 50 points each. A stretch is cut back this far at each end so the junctions where the
# route would join it stay open.
MAX_AVOID = 10
AVOID_LINE_POINTS = 50
AVOID_TRIM_MI = 0.02
# Alternatives (`candidates`): the routes at other stress levels the site found, each kept as a
# draft of its own.
MAX_ALTERNATIVES = 3
# An alternative's draft follows its own line when planned again (the site's `follow`, which
# takes up to 5,000 points in 64 KB): thinned to this many points.
ALTERNATIVE_FOLLOW_POINTS = 3000
# route_segments: rows a page, by default and at most.
SEGMENT_ROWS = 60
MAX_SEGMENT_ROWS = 200


def pace_kmh(mph) -> float:
    """The rider's pace on the flat, mph, as the site's `cycling_speed_kmh` (8 to 50 km/h)."""
    value = finite(mph)
    if not 5 <= value <= 31:
        raise ToolError("pace_mph is 5 to 31")
    return round(value * METRES_PER_MILE / 1000, 1)


def run_pace_kmh(mph) -> float:
    """A runner's pace, mph, as the site's `run_pace_kmh` (core/run_plan.py: 4 to 10 mph)."""
    value = finite(mph)
    if not 4 <= value <= 10:
        raise ToolError("a run's pace_mph is 4 to 10")
    return round(value * METRES_PER_MILE / 1000, 1)


def pace_option(mph, preset: str) -> tuple[str, float]:
    """The pace field the site reads for the ride type, and its value: Run's running pace, a
    bike's riding speed (the site keeps Walk's and a share bike's own)."""
    if preset == "run":
        return "run_pace_kmh", run_pace_kmh(mph)
    return "cycling_speed_kmh", pace_kmh(mph)


def _cum_miles(line: list) -> list[float]:
    """Miles along the line at each of its points, by straight steps."""
    cum = [0.0]
    for p, q in zip(line, line[1:], strict=False):
        cum.append(cum[-1] + haversine_mi((p[0], p[1]), (q[0], q[1])))
    return cum


def _thinned(points: list, most: int) -> list:
    """At most `most` of the points, evenly picked, the first and last kept."""
    if len(points) <= most:
        return points
    step = (len(points) - 1) / (most - 1)
    return [points[round(i * step)] for i in range(most)]


def line_between(plan: Plan, a_mi: float, b_mi: float) -> list[list[float]]:
    """The route's line from mile `a_mi` to `b_mi` (the answer's own miles), [lon, lat] pairs,
    at most AVOID_LINE_POINTS of them."""
    line = plan.line
    cum = _cum_miles(line)
    scale = (cum[-1] or 1.0) / max((plan.answer.get("distance_m") or 0.0) / METRES_PER_MILE, 1e-9)
    a, b = a_mi * scale, b_mi * scale

    def at(d: float) -> list[float]:
        k = max(1, min(len(cum) - 1, bisect.bisect_left(cum, d)))
        p, q = line[k - 1], line[k]
        f = (d - cum[k - 1]) / (cum[k] - cum[k - 1]) if cum[k] > cum[k - 1] else 0.0
        f = min(1.0, max(0.0, f))  # never past the line's ends
        return [round(p[0] + (q[0] - p[0]) * f, 6), round(p[1] + (q[1] - p[1]) * f, 6)]

    inside = [
        [round(v[0], 6), round(v[1], 6)] for v, d in zip(line, cum, strict=False) if a < d < b
    ]
    return _thinned([at(a), *inside, at(b)], AVOID_LINE_POINTS)


# Hunt 4 L4-3: avoiding a road by name left out the separated path beside it ("path beside
# Georgia Avenue") and still rode the road. Asked "What do you mean avoid georgia avenue?
# Usually a good idea, but be more specific", Claude put it as: match only the road and
# its own painted lane, and keep sidepaths and cycletracks mapped as their own ways unless
# the rider names them. The owner, 2026-11-09: "We can keep that approach." A way of its
# own beside a road is labelled with one of these heads or tails (`describe.beside_words`,
# `routing.sidepath_names_of`: "9th Street Northwest protected bike lane"); the road's own
# painted lane is a stretch of the road, under the road's name.
SEPARATE_WAY_HEADS = ("path beside ", "service road beside ", "sidewalk beside ")
SEPARATE_WAY_TAILS = (
    " bike lane",
    " bike lanes",
    " bike path",
    " cycletrack",
    " cycle track",
    " sidepath",
    " side path",
)


def _separate_way(label: str) -> bool:
    """Whether a stretch's label (case-folded) names a way of its own beside a road: a side
    path, a service road or sidewalk beside it, or a cycletrack named for it."""
    return label.startswith(SEPARATE_WAY_HEADS) or label.endswith(SEPARATE_WAY_TAILS)


def _mile_range(a: float, b: float) -> str:
    """'miles A to B' for a note, to a tenth; to a hundredth where a short stretch would read
    "0.0 to 0.0" at a tenth, and with its length where even that rounds to one number."""
    if f"{a:.1f}" != f"{b:.1f}":
        return f"miles {a:.1f} to {b:.1f}"
    if f"{a:.2f}" != f"{b:.2f}":
        return f"miles {a:.2f} to {b:.2f}"
    feet = max(0.0, b - a) * METRES_PER_MILE * FEET_PER_METRE
    return f"at mile {a:.2f} ({feet:,.0f} ft)"


def _road_runs(plan: Plan, road: str) -> list[tuple[float, float, list[str]]]:
    """The mile ranges of the draft that ride a road of that name (a few metres of another
    street between two pieces is one run), each with the stretch labels it matched. The road
    itself and its own painted lane, never a side path, service road, sidewalk or cycletrack
    mapped as a way of its own beside it unless the rider names that in full (L4-3; the
    owner, 2026-11-09: "We can keep that approach"). A run is not bridged across one."""
    wanted = road.strip().casefold()
    runs: list[list] = []
    broken = False
    for entry in _stretches(plan.answer):
        label = _street(entry)
        street = label.casefold()
        if _separate_way(street) and street != wanted:
            broken = True
            continue
        if not (street == wanted or (len(wanted) >= 4 and wanted in street)):
            continue
        if runs and not broken and entry["from_mi"] - runs[-1][1] <= BRIDGE_MI:
            runs[-1][1] = entry["to_mi"]
            if label not in runs[-1][2]:
                runs[-1][2].append(label)
        else:
            runs.append([entry["from_mi"], entry["to_mi"], [label]])
        broken = False
    return [(a, b, labels) for a, b, labels in runs]


def _beside_only(plan: Plan, road: str) -> list[str]:
    """The labels of the draft's separate ways beside a road of that name (for saying why
    nothing was matched)."""
    wanted = road.strip().casefold()
    seen: list[str] = []
    for entry in _stretches(plan.answer):
        label = _street(entry)
        street = label.casefold()
        if len(wanted) >= 4 and _separate_way(street) and wanted in street and label not in seen:
            seen.append(label)
    return seen


def avoid_lines(plan: Plan | None, asked) -> tuple[list[list[list[float]]], list[str]]:
    """The lines of road to leave out, from what was asked: a road by name or a mile range (of
    the draft `plan`), or a line of [lon, lat] pairs; and what each was, to say back."""
    if not isinstance(asked, list):
        raise ToolError("avoid is a list")
    lines: list[list[list[float]]] = []
    said: list[str] = []
    for item in asked:
        if not isinstance(item, dict):
            raise ToolError("each avoid is an object: road, from_mi and to_mi, or line")
        if item.get("line") is not None:
            raw = item["line"]
            if not isinstance(raw, list) or len(raw) < 2:
                raise ToolError("avoid.line is [lon, lat] pairs, two or more")
            pts = [[finite(p[0]), finite(p[1])] for p in raw]
            for p in pts:
                if not inside_coverage((p[0], p[1])):
                    raise ToolError("an avoid.line point is outside the map's area")
            lines.append(_thinned(pts, AVOID_LINE_POINTS))
            said.append(f"a line of {len(pts)} points")
            continue
        if plan is None:
            raise ToolError(
                "avoid by road or miles reads the draft's own roads: plan first, then"
                " revise_route with avoid (or give avoid as a line here)"
            )
        if item.get("road"):
            named = _road_runs(plan, str(item["road"]))
            if not named:
                beside = _beside_only(plan, str(item["road"]))
                if beside:
                    raise ToolError(
                        f"the draft does not ride {item['road']!r} itself, only "
                        + ", ".join(repr(b) for b in beside)
                        + ", a way of its own beside it: name that in full, or give a mile"
                        " range, to leave it out"
                    )
                raise ToolError(f"the draft does not ride {item['road']!r}: check its roads")
            runs = [(a, b) for a, b, _ in named]
            matched = [", ".join(labels) for _, _, labels in named]
        elif item.get("from_mi") is not None and item.get("to_mi") is not None:
            a, b = finite(item["from_mi"]), finite(item["to_mi"])
            total = (plan.answer.get("distance_m") or 0.0) / METRES_PER_MILE
            if not 0 <= a < b or a >= total:
                raise ToolError(
                    f"avoid's from_mi is 0 or more, below to_mi and on the draft ({total:.1f} mi)"
                )
            runs = [(a, min(b, total))]
        else:
            raise ToolError("each avoid gives road, from_mi and to_mi, or line")
        for k, (a, b) in enumerate(runs):
            if b - a > 2.5 * AVOID_TRIM_MI:
                a, b = a + AVOID_TRIM_MI, b - AVOID_TRIM_MI
            lines.append(line_between(plan, a, b))
            what = f"{item['road']} " if item.get("road") else ""
            words = f"{what}{_mile_range(a, b)}".strip()
            if item.get("road"):
                # Which stretches the name matched (L4-3): the road and its painted lane.
                words += f" (matched: {matched[k]})"
            said.append(words)
    return lines, said


def _unpaved_mi(answer: dict) -> float:
    """Miles on stretches the site calls unpaved (half of each partly unpaved one)."""
    total = 0.0
    for entry in _stretches(answer):
        miles = max(0.0, entry["to_mi"] - entry["from_mi"])
        if entry.get("surface") == "unpaved":
            total += miles
        elif entry.get("surface") == "partly unpaved":
            total += miles / 2
    return total


# The movements that are turns, as the app counts them (frontend lib/quickFigures.ts
# turnTotal): left, right, bear and U-turns; not "continue" or straight on at a junction.
TURN_MOVEMENTS = frozenset({"left", "right", "bear_left", "bear_right", "uturn"})


def turn_count(answer: dict) -> int | None:
    """The turns in the route's directions, as the app's summary counts them; None where the
    answer has no directions (an older API), so 0 is never guessed."""
    entries = answer.get("description")
    if entries is None:
        return None
    return sum(
        1
        for entry in entries
        if entry.get("kind") == "stretch"
        and (entry.get("turn") or {}).get("movement") in TURN_MOVEMENTS
    )


def figures(answer: dict) -> dict:
    """The route in the numbers a rider weighs one plan against another by: its turns among
    them (the backlog's "fewer turns" item, 2026-11-12), so "the same but fewer turns" can be
    compared like "calmer"."""
    stress = answer.get("stress_m") or {}
    found = answer.get("intersections") or []
    turns = turn_count(answer)
    return {
        "miles": round((answer.get("distance_m") or 0.0) / METRES_PER_MILE, 2),
        "minutes": round((answer.get("duration_s") or 0.0) / 60, 1),
        "climb_ft": round((answer.get("climb_m") or 0.0) * FEET_PER_METRE),
        "miles_lts_3_up": round(
            sum(stress.get(k, 0.0) or 0.0 for k in ("3", "4", "5")) / METRES_PER_MILE, 2
        ),
        "miles_lts_4_up": round(
            sum(stress.get(k, 0.0) or 0.0 for k in ("4", "5")) / METRES_PER_MILE, 2
        ),
        "unpaved_mi": round(_unpaved_mi(answer), 2),
        "very_high_junctions": sum(1 for j in found if j.get("severity") == "red"),
        "higher_junctions": sum(1 for j in found if j.get("severity") == "orange"),
        "junction_wait_minutes": round((answer.get("junction_delay_s") or 0.0) / 60, 1),
        **({} if turns is None else {"turns": turns}),
    }


# "Why this way" (the backlog's connector item 5, the owner's "do 9" of 2026-11-13): each plan
# set against the most direct route between the same points, the Fast ride type's, in numbers
# from our own ratings, never prose. Planned only for the bike ride types below, where a direct
# route means something (not Fast itself, a loop, a followed line, Mass Ride's fixed roadway or a
# transit, bikeshare, walk or run trip), on rides up to WHY_MAX_MI in straight lines between the
# points (our default, unmeasured: one more plan on a long ride can cost most of the site's 55 s),
# and only while the call still has time for another plan.
WHY_PRESETS = (
    "default",
    "trailmaxxing",
    "novice",
    "group-ride",
    "mountain-goat",
    "mountain-bike",
    "gravel",
    "road-bike",
    "cargo",
    "tandem",
    "ebike",
)
WHY_MAX_MI = 25.0
# A busy road on the direct route is said as one this route leaves when it carries at least this
# many miles at LTS 3 and up there, the largest WHY_MAX_LEAVES of them (both our defaults,
# unmeasured).
WHY_MIN_BUSY_MI = 0.25
WHY_MAX_LEAVES = 3
KM_PER_MILE = METRES_PER_MILE / 1000


def _busy_mi(row: dict) -> float:
    """A road row's miles at LTS 3 and up. road_list gives them apart only on a road mostly
    calmer; one mostly LTS 3 or up counts whole, which can overstate it a little."""
    if (row.get("lts") or 0) >= 3:
        return float(row.get("miles") or 0.0)
    return float(row.get("miles_lts_3_up") or 0.0)


def _row_at(rows: list[dict], mile: float) -> dict | None:
    for row in rows:
        if row["from_mi"] <= mile <= row["from_mi"] + row["miles"] + 0.05:
            return row
    return rows[-1] if rows else None


def why_this_way(ours: dict, direct: dict) -> dict:
    """This route against the direct one (both the site's answers): the difference in miles,
    minutes (at this route's own average speed, so the direct ride type's faster pace does not
    count) and busy miles, said in one line, and the busy roads of the direct route this one
    leaves, each with what it rides instead near the middle of that road's stretch."""
    mine, theirs = figures(ours), figures(direct)
    extra_mi = round(mine["miles"] - theirs["miles"], 1)
    speed = mine["miles"] / mine["minutes"] if mine["minutes"] else 0.0
    extra_min = round(extra_mi / speed) if speed else None
    fewer_busy = round(theirs["miles_lts_3_up"] - mine["miles_lts_3_up"], 1)
    fewer_lts4 = round(theirs["miles_lts_4_up"] - mine["miles_lts_4_up"], 1)
    out: dict = {
        "against": "the most direct route between the same points (the Fast ride type's)",
        "extra_miles": extra_mi,
        "fewer_busy_miles": fewer_busy,
    }
    if extra_min is not None:
        out["extra_minutes"] = extra_min
    if fewer_lts4:
        out["fewer_lts_4_miles"] = fewer_lts4
    if abs(extra_mi) < 0.1 and abs(fewer_busy) < 0.1:
        out["said"] = "this is the direct route, or rides as busy and as far"
        return out
    length = (
        f"{abs(extra_mi)} mi ({abs(extra_mi) * KM_PER_MILE:.1f} km)"
        f" {'longer' if extra_mi >= 0 else 'shorter'}"
    )
    if extra_min:
        length += f", about {abs(extra_min)} min {'more' if extra_min > 0 else 'less'}"
    if fewer_busy >= 0.1:
        busy = f"{fewer_busy} fewer miles on busy roads (LTS 3 and up)"
    elif fewer_busy <= -0.1:
        busy = f"{-fewer_busy} more miles on busy roads (LTS 3 and up)"
    else:
        busy = "as many miles on busy roads"
    out["said"] = f"{length}; {busy}"
    our_rows = (road_list(ours) or {}).get("roads") or []
    their_rows = (road_list(direct) or {}).get("roads") or []
    ridden = {r["road"].casefold() for r in our_rows}
    line = (ours.get("geometry") or {}).get("coordinates") or []
    direct_line = (direct.get("geometry") or {}).get("coordinates") or []
    ours_scale, direct_scale = _line_scale(ours), _line_scale(direct)
    leaves = []
    for row in sorted(their_rows, key=_busy_mi, reverse=True):
        busy_mi = _busy_mi(row)
        if len(leaves) >= WHY_MAX_LEAVES or busy_mi < WHY_MIN_BUSY_MI:
            break
        road = row["road"]
        if road in NAMELESS or road.casefold() in ridden or " short links" in road:
            continue
        item = {
            "road": row["road"],
            "lts": max(row.get("lts") or 0, row.get("worst_lts") or 0),
            "busy_miles": round(busy_mi, 1),
        }
        if line and direct_line:
            middle = row["from_mi"] + row["miles"] / 2
            lon, lat = point_at_mile(direct_line, middle * direct_scale)
            along_m, _off, _ = line_nearest(line, lon, lat)
            instead = _row_at(our_rows, along_m / METRES_PER_MILE / ours_scale)
            unnamed = instead is not None and (
                instead["road"] in NAMELESS or " short links" in instead["road"]
            )
            if instead is not None and unnamed and instead.get("facility") in ("path", "trail"):
                item["for"] = f"a {instead['facility']}"
            elif instead is not None and unnamed:
                instead = None  # nothing to name
            if instead is not None:
                item.setdefault("for", instead["road"])
                if instead.get("lts") is not None:
                    item["for_lts"] = instead["lts"]
                if instead.get("facility"):
                    item["for_facility"] = instead["facility"]
                item["at_mile"] = instead["from_mi"]
        leaves.append(item)
    if leaves:
        out["leaves"] = leaves
    return out


def figures_change(before: dict, after: dict) -> dict:
    """Each figure before and after a revision, and by how much it moved (after less before)."""
    return {
        key: {
            "before": before[key],
            "after": after[key],
            "change": round(after[key] - before[key], 2),
        }
        for key in before
        if key in after
    }


def leg_rows(plan: Plan) -> list[dict]:
    """The route between each stop (via points do not split it): miles, minutes, climb and
    busy miles, for planning food, water and overnight stops on a long ride."""
    answer = plan.answer
    along = _points_along(plan)
    if not along:
        return []
    vias = set(plan.vias)
    total_mi = (answer.get("distance_m") or 0.0) / METRES_PER_MILE
    cuts = [0.0]
    stops = [0]
    for index, metres in along:
        if index not in vias:
            cuts.append(metres / METRES_PER_MILE)
            stops.append(index)
    cuts.append(total_mi)
    stops.append(len(plan.points) - 1)
    if len(cuts) <= 2:
        return []
    clock = _clock(answer)
    rows = []
    for k in range(len(cuts) - 1):
        a, b = cuts[k], cuts[k + 1]
        busy = sum(
            max(0.0, min(b, e["to_mi"]) - max(a, e["from_mi"]))
            for e in _stretches(answer)
            if (e.get("tier") or 0) >= 3
        )
        rows.append(
            {
                "from_point": stops[k],
                "to_point": stops[k + 1],
                "from_mi": round(a, 1),
                "miles": round(b - a, 1),
                "minutes": round(clock(b) - clock(a)),
                "climb_ft": round(_gain_ft(answer, a, b)),
                "miles_lts_3_up": round(busy, 1),
            }
        )
    return rows


def _clock(answer: dict):
    """minutes(mile): the site's own minutes from the start to `mile` (`time_marks`, hills and
    junction waits in place), else the ride's minutes spread evenly."""
    total_mi = max((answer.get("distance_m") or 0.0) / METRES_PER_MILE, 1e-9)
    total_min = (answer.get("duration_s") or 0.0) / 60
    marks = [
        (m[0] * total_mi, m[1] / 60)
        for m in answer.get("time_marks") or []
        if isinstance(m, (list, tuple)) and len(m) >= 2
    ]
    if len(marks) < 2:
        return lambda mile: total_min * min(max(mile, 0.0), total_mi) / total_mi
    marks.sort()
    miles = [m for m, _ in marks]

    def minutes(mile: float) -> float:
        if mile <= miles[0]:
            return marks[0][1] * (mile / miles[0] if miles[0] > 0 else 1.0)
        if mile >= miles[-1]:
            return marks[-1][1]
        k = bisect.bisect_left(miles, mile)
        (m0, t0), (m1, t1) = marks[k - 1], marks[k]
        return t0 + (t1 - t0) * ((mile - m0) / (m1 - m0) if m1 > m0 else 0.0)

    return minutes


def _gain_ft(answer: dict, a: float, b: float) -> float:
    """Feet climbed from mile `a` to `b`, every rise counted (not net)."""
    up = 0.0
    for x, y, grade in _grades(answer):
        overlap = min(y, b) - max(x, a)
        if overlap > 0 and grade > 0:
            up += grade / 100 * overlap * METRES_PER_MILE
    return up * FEET_PER_METRE


def _grade_in(answer: dict, a: float, b: float) -> tuple[float | None, float | None]:
    """The average and steepest uphill grade (%) from mile `a` to `b`; None without heights."""
    rise, run, steepest = 0.0, 0.0, None
    for x, y, grade in _grades(answer):
        overlap = min(y, b) - max(x, a)
        if overlap <= 0:
            continue
        rise += grade * overlap
        run += overlap
        steepest = grade if steepest is None else max(steepest, grade)
    if run <= 0:
        return None, None
    return round(rise / run, 1), round(steepest, 1)


def grades_and_hazards(answer: dict) -> dict:
    """The steep and very steep grades the site marks (up or down) and the cobbles and rails the
    route meets, with their miles."""
    scale = _traced_scale(answer) / METRES_PER_MILE
    out: dict = {}
    steep = [
        {
            "from_mi": round(g["from_m"] * scale, 2),
            "to_mi": round(g["to_m"] * scale, 2),
            "direction": g.get("direction"),
            "grade_pct": g.get("grade_pct"),
            "level": g.get("level"),
        }
        for g in answer.get("steep_grades") or []
    ]
    if steep:
        out["steep_grades"] = steep
    hazards = [
        {
            "from_mi": round(h["from_m"] * scale, 2),
            "to_mi": round(h["to_m"] * scale, 2),
            "kinds": h.get("kinds"),
            "road": h.get("road"),
        }
        for h in answer.get("road_hazards") or []
    ]
    if hazards:
        out["road_hazards"] = hazards
    return out


def route_segments(
    plan: Plan, from_mi: float = 0.0, to_mi: float | None = None, rows: int = SEGMENT_ROWS
) -> dict:
    """The route stretch by stretch from `from_mi` to `to_mi`: road, LTS, facility, surface,
    grades, climb and minutes; every higher and very-high junction; steep grades and hazards.
    Paged: `next_from_mi` where there are more rows."""
    answer = plan.answer
    total = (answer.get("distance_m") or 0.0) / METRES_PER_MILE
    end = total if to_mi is None else min(total, to_mi)
    clock = _clock(answer)
    out_rows: list[dict] = []
    next_from = None
    trails = _trail_spans(answer)
    for entry in _stretches(answer):
        if entry["to_mi"] <= from_mi or entry["from_mi"] >= end:
            continue
        a, b = max(from_mi, entry["from_mi"]), min(end, entry["to_mi"])
        facility = entry.get("facility")
        if facility not in ("path", "protected", "lane"):
            # A stretch mostly on a mountain-bike trail is a trail, not a street (M4-4).
            facility = "trail" if b > a and _trail_mi(trails, a, b) * 2 >= b - a else None
        key = (_street(entry), entry.get("tier"), facility, entry.get("surface"))
        last = out_rows[-1] if out_rows else None
        if last is not None and last["_key"] == key and a - last["_b"] <= 0.01:
            last["_b"] = b
            continue
        if len(out_rows) >= rows:
            next_from = round(a, 2)
            break
        out_rows.append({"_key": key, "_a": a, "_b": b, "_oneway": entry.get("oneway")})
    segments = []
    for row in out_rows:
        street, tier, facility, surface = row["_key"]
        a, b = row["_a"], row["_b"]
        avg, steepest = _grade_in(answer, a, b)
        seg = {
            "from_mi": round(a, 2),
            "to_mi": round(b, 2),
            "road": street,
            "lts": tier,
            "facility": facility or "street",
            "minutes": round(clock(b) - clock(a), 1),
        }
        if surface:
            seg["surface"] = surface
        if avg is not None:
            seg["grade_pct"] = avg
            if steepest is not None and steepest >= avg + 2:
                seg["steepest_pct"] = steepest
            gain = _gain_ft(answer, a, b)
            if gain >= 10:
                seg["climb_ft"] = round(gain)
        if row["_oneway"]:
            seg["one_way"] = True
        segments.append(seg)
    stop = next_from if next_from is not None else end
    scale = _traced_scale(answer) / METRES_PER_MILE
    stretches = _stretches(answer)
    junctions = []
    for j in answer.get("intersections") or []:
        mile = (j.get("m") or 0) * scale
        if not from_mi <= mile <= stop:
            continue
        on = next((e for e in stretches if e["from_mi"] <= mile <= e["to_mi"]), None)
        junctions.append(
            {
                "at_mi": round(mile, 2),
                "level": "very high" if j.get("severity") == "red" else "higher",
                "road": _street(on) if on and _street(on) not in NAMELESS else None,
                "reason": j.get("reason"),
                "lon_lat": [j.get("lon"), j.get("lat")],
            }
        )
    out: dict = {
        "from_mi": round(from_mi, 2),
        "to_mi": round(stop, 2),
        "route_miles": round(total, 2),
        "segments": segments,
        "junctions": junctions,
    }
    extra = grades_and_hazards(answer)
    for key, items in extra.items():
        kept = [i for i in items if i["to_mi"] >= from_mi and i["from_mi"] <= stop]
        if kept:
            out[key] = kept
    if next_from is not None:
        out["next_from_mi"] = next_from
    if not stretches:
        out["note"] = "the site sent no stretch-by-stretch description for this route"
    return out


# --- The route view: a map and graphs in the assistant's chat ------------------------------------
#
# The owner, 2026-11-10: "Is it possible for the MCP server to return a map and the various relevant
# graphs?", then picked an interactive view with a text fallback. An assistant that speaks the MCP
# Apps extension (io.modelcontextprotocol/ui) shows mcp/route_view.html under its reply to
# plan_route, revise_route, open_link and plan_metro_loop: the route on a map coloured by traffic
# stress, a stress ribbon and the elevation profile on one mile axis, and buttons to open the
# route, get its GPX or save it. Every other assistant reads the same text answer as before.
#
# What the view draws travels in the tool result's `_meta` (VIEW_META_KEY), which the extension
# keeps out of the model's context: the answer the model reads is unchanged. Nothing is kept for
# it on the server; the base map behind the line is drawn on request by the app-only tool
# route_view_map, from the box alone, in memory.

VIEW_URI = "ui://routemaker/route-view.html"
# The answer's keys for what Server.call takes out of it (never seen by the model).
VIEW_PRIVATE = "_route_view"
IMAGES_PRIVATE = "_images"
VIEW_MIME = "text/html;profile=mcp-app"
VIEW_META_KEY = "routemaker/route-view"
UI_EXTENSION = "io.modelcontextprotocol/ui"
VIEW_TOOLS = ("plan_route", "revise_route", "open_link", "plan_metro_loop", "route_notes")
VIEW_FILE = Path(__file__).resolve().parent / "route_view.html"
# The elevation profile's samples sent to the view: enough for a chat-width graph. Our default.
VIEW_PROFILE_POINTS = 400
# The line's precision: 5 decimals (about a metre), half the size of the router's 6.
VIEW_LINE_PRECISION = 5
# The base map picture route_view_map draws: no bigger than this, in pixels (the view's map is at
# most 1200 wide and 460 tall). Our defaults: a 1200 x 480 draw takes about 0.4 to 1.8 s.
VIEW_MAP_MAX_W = 1200
VIEW_MAP_MAX_H = 480


def view_html() -> str:
    """The view's page (mcp/route_view.html), read from beside this file."""
    return VIEW_FILE.read_text(encoding="utf-8")


def _profile_rows(answer: dict, most: int = VIEW_PROFILE_POINTS) -> list[list[float]]:
    """The elevation profile as [mile, feet] rows, at most `most` of them (a thinned profile
    keeps the highest and lowest of each window, so a summit is not cut off)."""
    profile = answer.get("profile") or {}
    rows = [
        (m / METRES_PER_MILE, h * FEET_PER_METRE)
        for m, h in zip(profile.get("m") or [], profile.get("elevation_m") or [], strict=False)
        if isinstance(m, (int, float)) and isinstance(h, (int, float))
    ]
    # A gap in the heights (no elevation data there) is drawn straight across: the profile is a
    # sketch of the climbing, and route_segments gives the grades where they are known.
    if len(rows) > most:
        step = len(rows) / (most / 2)
        kept = [rows[0]]
        for k in range(int(most / 2)):
            window = rows[int(k * step) : int((k + 1) * step)] or [rows[-1]]
            low = min(window, key=lambda r: r[1])
            high = max(window, key=lambda r: r[1])
            kept.extend(sorted({low, high}))
        kept.append(rows[-1])
        rows = kept
    return [[round(mi, 3), round(ft)] for mi, ft in rows]


def _mass_view(answer: dict, corking: dict | None = None) -> dict | None:
    """A Mass Ride's flow and corkers for the view, as Ride's graphs show them (the owner,
    2026-11-03: "Mass ride can also add traffic flow and corker requirements"; 2026-11-10 asked
    for them in the chat): riders a minute along the route as [from_mi, to_mi, riders] steps
    (equal neighbours joined), the ride's need, and each junction needing corkers; the corkers
    held at once along the route and the ride's count (the owner, 2026-11-10: "We'd also want a
    chart of corkers required"), with the organiser's triage (`corker_plan`). None off a Mass
    Ride, or where the profile carries no flow."""
    profile = answer.get("profile") or {}
    metres = profile.get("m") or []
    riders = profile.get("riders_per_min") or []
    steps: list[list] = []
    for i in range(1, len(metres)):
        r = riders[i - 1] if i - 1 < len(riders) else None
        if not isinstance(r, (int, float)):
            continue
        a, b = metres[i - 1] / METRES_PER_MILE, metres[i] / METRES_PER_MILE
        if steps and steps[-1][2] == round(r) and abs(steps[-1][1] - a) < 1e-6:
            steps[-1][1] = b
        else:
            steps.append([a, b, round(r)])
    if not steps:
        return None
    found = answer.get("mass_capacity") or {}
    corkers = found.get("corkers")
    out: dict = {
        "need": found.get("need_riders_per_min"),
        "steps": [[round(a, 3), round(b, 3), r] for a, b, r in steps],
        "corkers": None,
    }
    if not corkers:
        return out
    plan = corker_plan(corkers, corking, _corker_length(answer, corkers))

    def row(j: dict) -> dict:
        return {
            "mi": round((j.get("m") or 0) / METRES_PER_MILE, 2),
            "street": j.get("street"),
            "corkers": j.get("corkers"),
        }

    out["corkers"] = [row(j) for j in plan["kept"]]
    out["skipped"] = [row(j) for j in plan["skipped"]]
    out["about"] = plan["about"]
    out["most"] = plan["most"]
    out["at_least"] = bool(plan["at_least"])
    out["rotation_factor"] = plan["rotation_factor"]
    out["held"] = (
        None
        if plan["held"] is None
        else [
            [round(a / METRES_PER_MILE, 3), round(b / METRES_PER_MILE, 3), n]
            for a, b, n in plan["held"]
        ]
    )
    return out


def cue_card_names(plan: Plan, asked) -> dict[int, str]:
    """The stops' names by point index for the cue images: the plan's own (its link's `sn=`),
    then `asked`, by stop number from 1 (cue_cards' `stop_names`); a loop's last point is a stop
    too, as the link counts it (`link_stop_names`)."""
    names = {int(k): str(v) for k, v in (plan.names or {}).items()}
    loop = plan.answer.get("loop") is not None or bool((plan.answer.get("dials") or {}).get("loop"))
    count = len(plan.points)
    vias = set(plan.vias)
    stops = [i for i in range(1, count if loop else count - 1) if i not in vias]
    for key, name in (asked or {}).items():
        try:
            number = int(key)
        except (TypeError, ValueError):
            continue
        clean = clean_stop_name(name)
        if 1 <= number <= len(stops) and clean:
            names[stops[number - 1]] = clean
    return names


def cue_card_args(draft, names: dict[int, str]) -> tuple:
    """core.cue_cards.draw's arguments for a draft: its answer, its name, its through points,
    the stops' names, the route's credits, a source to a line, and its notes near the line."""
    answer = draft.plan.answer
    sources = [str(a) for a in answer.get("attribution") or []] or [
        "© OpenStreetMap contributors, ODbL"
    ]
    return (
        answer,
        draft.name,
        list(draft.plan.vias),
        names,
        "\n".join(["Route data:", *sources, "Planned with RouteMaker."]),
        # The route's notes near its line, as rows (route_notes).
        notes_along(answer, draft.options.get("route_notes")),
    )


def draft_view(draft, draft_id: str) -> dict:
    """A kept draft's route view, as its answer gave it (for the picture, core.route_picture)."""
    plan = draft.plan
    said = {"draft_id": draft_id, "summary": summary(plan.answer), **route_closures(plan)}
    if draft.options.get("route_notes"):
        said["route_notes"] = route_notes_out(plan.answer, draft.options["route_notes"])
    return route_view(plan, said, draft.name, draft.options.get("corking"))


def route_view(plan: Plan, out: dict, name: str, corking: dict | None = None) -> dict:
    """What the view draws for a draft: its line, its stress and facility by mile, its
    profile, its points, its flagged junctions and closures, and its figures and link."""
    answer = plan.answer
    total = (answer.get("distance_m") or 0.0) / METRES_PER_MILE
    scale = _traced_scale(answer) / METRES_PER_MILE
    spans = []
    for s in answer.get("stress_spans") or []:
        tier = s.get("tier")
        if isinstance(tier, int) and s.get("half") and tier < 5:
            tier += 0.5
        spans.append(
            [
                round(s["from_m"] * scale, 3),
                round(s["to_m"] * scale, 3),
                tier,
                s.get("facility"),
            ]
        )
    junctions = [
        {
            "mi": round((j.get("m") or 0) * scale, 2),
            "level": "very high" if j.get("severity") == "red" else "higher",
            "reason": j.get("reason"),
        }
        for j in answer.get("intersections") or []
        if j.get("severity") in ("red", "orange")
    ]
    closures = [
        {"mi": row["from_mi"], "kind": kind, "what": row.get("what")}
        for kind, rows in (
            ("closure", out.get("closures") or []),
            ("possible", out.get("potential_closures") or []),
        )
        for row in rows
        if isinstance(row, dict) and row.get("from_mi") is not None
    ]
    said = out.get("summary") or {}
    return {
        "version": 1,
        "draft_id": out.get("draft_id"),
        "name": name,
        "link": out.get("link"),
        "miles": round(total, 3),
        "figures": {
            "distance": said.get("distance"),
            "time": said.get("moving_time"),
            "climb": said.get("climb"),
        },
        "line": encode_polyline(plan.line, VIEW_LINE_PRECISION) if plan.line else "",
        "line_precision": VIEW_LINE_PRECISION,
        "spans": spans,
        "profile": _profile_rows(answer),
        "points": [{"lon_lat": list(p), "via": i in plan.vias} for i, p in enumerate(plan.points)],
        "loop": bool(plan.sent.get("loop")),
        "junctions": junctions,
        "closures": closures,
        "mass": _mass_view(answer, corking),
        # The route's notes (route_notes), each where it was put and its mile where near the line.
        "notes": [
            {
                "lon_lat": [n["lon"], n["lat"]],
                "kind": n["kind"],
                "text": n["text"],
                "mi": n.get("mi"),
                "icon": NOTE_ICONS.get(n.get("icon") or KIND_ICON[n["kind"]]),
            }
            for n in out.get("route_notes") or []
        ],
    }


# --- Light and weather at the ride's time -----------------------------------------------------

# Civil twilight (the sun 6 degrees below the horizon): "Dawn" and "Dusk" in the app (#822).
TWILIGHT_DEG = -6.0
# The weather check takes up to 12 points along the line, up to 48 hours ahead.
WEATHER_POINTS = 12
WEATHER_AHEAD_S = 172800


def _eastern_offset(moment_utc) -> timedelta:
    """America/New_York's offset at a UTC moment (zoneinfo where it has its data, else the US
    rule: daylight time from the second Sunday of March to the first Sunday of November)."""
    from datetime import datetime

    try:
        from zoneinfo import ZoneInfo

        return moment_utc.astimezone(ZoneInfo("America/New_York")).utcoffset()
    except Exception:  # noqa: BLE001 - no tz data on this computer: the rule
        year = moment_utc.year
        march = datetime(year, 3, 8, 7, tzinfo=UTC)
        march += timedelta(days=(6 - march.weekday()) % 7)
        november = datetime(year, 11, 1, 6, tzinfo=UTC)
        november += timedelta(days=(6 - november.weekday()) % 7)
        return timedelta(hours=-4 if march <= moment_utc < november else -5)


def eastern(moment_utc) -> str:
    """A UTC moment as New York's clock reads it, 'YYYY-MM-DD HH:MM'."""
    return (moment_utc + _eastern_offset(moment_utc)).strftime("%Y-%m-%d %H:%M")


def parse_depart(text: str | None, now=None):
    """`depart_at` as an aware UTC datetime: ISO 8601, New York's time where it names no
    zone; now when absent."""
    from datetime import datetime

    now = now or datetime.now(UTC)
    if not text:
        return now
    try:
        moment = datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
    except ValueError:
        raise ToolError("depart_at is an ISO 8601 date and time, e.g. 2026-11-03T05:30") from None
    if moment.tzinfo is None:
        # Local time plus five hours is about the UTC moment: read the offset there.
        guess = moment.replace(tzinfo=UTC) + timedelta(hours=5)
        moment = moment.replace(tzinfo=UTC) - _eastern_offset(guess)
    return moment.astimezone(UTC)


def twilight(day: date, lon: float, lat: float):
    """Civil dawn and dusk on `day` at a place, as aware UTC datetimes (NOAA's sunrise
    equation with the sun at TWILIGHT_DEG, to a minute or two)."""
    from datetime import datetime

    n = (day - date(2000, 1, 1)).days - lon / 360.0
    m = math.radians((357.5291 + 0.98560028 * n) % 360)
    c = 1.9148 * math.sin(m) + 0.02 * math.sin(2 * m) + 0.0003 * math.sin(3 * m)
    ecl = math.radians((math.degrees(m) + c + 180 + 102.9372) % 360)
    transit = n + 0.0053 * math.sin(m) - 0.0069 * math.sin(2 * ecl)
    dec = math.asin(math.sin(ecl) * math.sin(math.radians(23.44)))
    phi = math.radians(lat)
    cos_w = (math.sin(math.radians(TWILIGHT_DEG)) - math.sin(phi) * math.sin(dec)) / (
        math.cos(phi) * math.cos(dec)
    )
    half = math.degrees(math.acos(max(-1.0, min(1.0, cos_w)))) / 360.0
    noon = datetime(2000, 1, 1, 12, tzinfo=UTC)
    return noon + timedelta(days=transit - half), noon + timedelta(days=transit + half)


def light_at(moment, lon: float, lat: float) -> dict:
    """Whether it is light or dark at a place and moment, with that day's dawn and dusk."""
    local_day = (moment + _eastern_offset(moment)).date()
    dawn, dusk = twilight(local_day, lon, lat)
    return {
        "at": eastern(moment),
        "light": "light" if dawn <= moment <= dusk else "dark",
        "dawn": eastern(dawn)[-5:],
        "dusk": eastern(dusk)[-5:],
    }


def weather_points(plan: Plan, ahead_s: float) -> list[list[float]]:
    """Up to WEATHER_POINTS points along the route, each [lon, lat, seconds until the rider is
    there], the ride starting `ahead_s` seconds from now."""
    line = plan.line
    cum = _cum_miles(line)
    total = cum[-1] or 1.0
    clock = _clock(plan.answer)
    route_mi = (plan.answer.get("distance_m") or 0.0) / METRES_PER_MILE
    count = min(WEATHER_POINTS, max(2, math.ceil(total / 5) + 1))
    out = []
    for i in range(count):
        d = total * i / (count - 1)
        k = max(1, min(len(cum) - 1, bisect.bisect_left(cum, d)))
        p = line[k] if cum[k] - d < d - cum[k - 1] else line[k - 1]
        seconds = ahead_s + clock(route_mi * d / total) * 60
        out.append([round(p[0], 5), round(p[1], 5), round(min(WEATHER_AHEAD_S, max(0.0, seconds)))])
    return out


def _saved_label(row: dict) -> dict:
    """A saved route as my_routes lists it."""
    out = {
        "route_id": row.get("id"),
        "name": row.get("name"),
        "miles": round((row.get("distance_m") or 0.0) / METRES_PER_MILE, 1),
        "ride_type": row.get("preset") or None,
        "updated": str(row.get("updated_at") or "")[:10],
    }
    if row.get("closure_alerts"):
        out["closures_on_it"] = len(row["closure_alerts"])
    if row.get("tags"):
        out["tags"] = list(row["tags"])
    if row.get("fixed"):
        # A fixed route (the owner, 2026-11-10): its exact line, never planned again.
        out["fixed"] = True
    if row.get("archived_at"):
        out["archived"] = str(row["archived_at"])[:10]
    return out


def _tags_arg(value) -> list[str]:
    """Tags as given: each trimmed, runs of spaces made one, the same one twice (by case) once."""
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ToolError("tags: a list of words")
    out: list[str] = []
    for tag in value:
        tag = " ".join(tag.split())
        if tag and tag.casefold() not in {x.casefold() for x in out}:
            if len(tag) > 30:
                raise ToolError("keep each tag to 30 characters")
            out.append(tag)
    if len(out) > 8:
        raise ToolError("a route keeps at most 8 tags")
    return out


def _tags_in_use(rows) -> list[str]:
    """The tags on these saved routes, most used first, then A to Z."""
    count: dict[str, list] = {}
    for row in rows:
        for tag in row.get("tags") or []:
            entry = count.setdefault(str(tag).casefold(), [str(tag), 0])
            entry[1] += 1
    return [t for t, _ in sorted(count.values(), key=lambda e: (-e[1], e[0].casefold()))]


def _draft_name(asked, points: list, default: str = "RouteMaker route") -> str:
    """A draft's name: the one asked, else "Start to End" (or "Loop from Start") where the
    points were given by name, else `default`."""
    name = " ".join(str(asked or "").split())[:120]
    if name:
        return name
    named = [p.strip() for p in points if isinstance(p, str) and p.strip()]
    if len(points) >= 2 and len(named) == len(points):
        first, last = named[0], named[-1]
        if first.casefold() == last.casefold():
            return f"Loop from {first}"[:120]
        return f"{first} to {last}"[:120]
    return default


@dataclass
class Draft:
    """A planned route the rider has not kept yet, with what it was planned with."""

    plan: Plan
    options: dict
    limit: float | None
    name: str
    trim_spurs: bool = True
    intervals: dict | None = None
    # A Group or Mass Ride's key (`ride_key_for`), kept as the draft is revised.
    ride_key: str | None = None
    # The draft this one revises (revise_route): my_drafts and the app's Load route list only
    # each route's newest revision.
    revises: str | None = None

    def fragment(self, dials: dict) -> str:
        """The draft's plan link fragment, with its ride key."""
        plan = self.plan
        fragment = plan_fragment(
            plan.points,
            plan.vias,
            plan.preset,
            dials,
            plan.sent,
            plan.names,
            self.options.get("route_notes"),
            self.options.get("stop_icons"),
        )
        return with_ride_key(fragment, self.ride_key)


@dataclass
class Plan:
    points: list[tuple[float, float]]
    vias: list[int]
    preset: str
    answer: dict
    check: dict | None
    sent: dict
    # The stops' own names by index (the link's `sn=`), carried from the link opened.
    names: dict[int, str] = dataclasses.field(default_factory=dict)

    @property
    def line(self) -> list[list[float]]:
        return self.answer["geometry"]["coordinates"]


def request_body(points, vias, preset: str, options: dict) -> dict:
    """POST /api/route's body: the points, and every option that was set (`Server._options`)."""
    body: dict = {
        "points": [list(p) for p in points],
        "preset": preset,
        # The MCP server asks on the rider's behalf; a long ride needs no second ask.
        "confirm_long": True,
        "candidates": False,
    }
    if vias:
        body["via_points"] = list(vias)
    body.update(
        {
            k: v
            for k, v in options.items()
            if v is not None and v is not False and k not in LINK_ONLY_OPTIONS
        }
    )
    return body


def plan_once(api, stations, points, vias, preset, options, limit_mi) -> Plan:
    if preset not in PRESETS:
        raise ToolError(f"preset is one of {', '.join(PRESETS)}")
    if preset == "rebalance":
        # A start alone (Stephen, 2026-11-07): it ends at the dock that needs bikes.
        if len(points) != 1:
            raise ToolError(
                "rebalance plans from a start alone: it walks to the nearest crowded station and"
                " rides to the nearest one that needs bikes"
            )
    elif not 2 <= len(points) <= MAX_POINTS:
        raise ToolError(f"a route has 2 to {MAX_POINTS} points")
    elif preset in TWO_POINT_PRESETS and len(points) != 2:
        raise ToolError(f"{preset} plans from a start and an end only")
    sent = request_body(points, vias, preset, options)
    answer = api.route(sent)
    check = metro_check(answer["geometry"]["coordinates"], limit_mi, stations) if limit_mi else None
    names = dict(options.get("stop_names") or {})
    return Plan(list(points), list(vias), preset, answer, check, sent, names)


def leg_of(plan: Plan, at_mile: float) -> int:
    """The index of the leg (between points i and i+1) holding the point `at_mile` along."""
    line = plan.line
    ends = plan.answer.get("leg_ends") or []
    along, previous, found = 0.0, None, len(line) - 1
    for index, vertex in enumerate(line):
        point = (vertex[0], vertex[1])
        if previous is not None:
            along += haversine_mi(previous, point)
        previous = point
        if along >= at_mile:
            found = index
            break
    for leg, end in enumerate(ends):
        if found <= end:
            return leg
    return max(0, len(plan.points) - 2)


# fix_metro_rounds tries, for each stretch over the limit (worst first), this many stations
# nearest it. Claude's default, not measured (the round 4 hunt, L4-5).
METRO_FIX_STATIONS = 3


def _at_station(point, station: Station) -> bool:
    """Whether the point is the station (its platform point or one of its ways in)."""
    ways = (station.point, station.way_in, *station.ways_in)
    return min(haversine_mi(w, point) for w in ways) < 0.05


def with_metro_fix(plan: Plan, stations: list[Station]) -> tuple[list, list[int], str] | None:
    """The points with a Metro station added as a via point in a leg that strays, or None where
    there is nothing left to try. The stretches over the limit are taken worst first, and for
    each the METRO_FIX_STATIONS stations nearest it, passing over a station that is already an
    end of the leg that strays (the round 4 hunt, L4-5: before, the nearest station already a
    point anywhere ended the fix). The via is the station's bike entrance (`Station.way_in`,
    issue #39): its platform point can sit in a freeway median (Vienna, Dunn Loring), and a
    through via there drags the route onto whatever edge is nearest it and back.

    On a loop whose way back strays (the closing leg the site adds, `routing.loop_points`), the
    ride is made a round trip in so many points: the station, then the start again (the round 4
    hunt, L4-2: before, the station went in as the last point, which the site refuses as a
    via)."""
    if plan.check is None or plan.check["ok"]:
        return None
    count = len(plan.points)
    for worst in sorted(plan.check["stretches_over_limit"], key=lambda s: -s["max_mi"]):
        leg = leg_of(plan, (worst["from_mi"] + worst["to_mi"]) / 2)
        closing = leg >= count - 1
        if count + (2 if closing else 1) > MAX_POINTS:
            continue
        ends = (plan.points[leg], plan.points[0] if closing else plan.points[leg + 1])
        here = tuple(worst["at"])
        nearest = sorted(stations, key=lambda s: haversine_mi(here, s.point))
        for station in nearest[:METRO_FIX_STATIONS]:
            if any(_at_station(p, station) for p in ends):
                continue
            # The way in nearest where the leg comes from, not one fixed elevator: at a Silver
            # Line station in the toll road's median the other side's elevator can take the
            # via across the freeway and back (the second 2026-11-08 hunt, P1, read from code).
            via = station.way_in_from(tuple(plan.points[leg]))
            if closing:
                points = [*plan.points, via, plan.points[0]]
                vias = sorted({*plan.vias, count})
            else:
                points = [*plan.points[: leg + 1], via, *plan.points[leg + 1 :]]
                vias = sorted({*(i if i <= leg else i + 1 for i in plan.vias), leg + 1})
            return points, vias, station.name
    return None


# An out-and-back to a loop's waypoint (the router reaching a point off any road through, and
# coming back the way it went) longer than this is a spur worth taking out.
SPUR_MI = 0.2
SPUR_SAME_MI = 0.03  # outbound and return closer than this (about 50 m) are the same road


def _along(line, cum, d):
    """The point `d` miles along `line` (cumulative miles `cum`)."""
    d = min(max(d, 0.0), cum[-1])
    i = max(1, bisect.bisect_left(cum, d))
    a, b = line[i - 1], line[i]
    span = cum[i] - cum[i - 1]
    t = 0.0 if span <= 0 else (d - cum[i - 1]) / span
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def spur_at(line, point) -> tuple[float, tuple[float, float]]:
    """How far the route goes out and comes back the same way at the vertex nearest `point`,
    in miles, and the junction the spur leaves from."""
    k = min(range(len(line)), key=lambda i: haversine_mi(point, (line[i][0], line[i][1])))
    cum = [0.0]
    for a, b in zip(line, line[1:], strict=False):
        cum.append(cum[-1] + haversine_mi((a[0], a[1]), (b[0], b[1])))
    here, reach, d = cum[k], min(cum[k], cum[-1] - cum[k]), 0.0
    step = 0.01
    while d + step <= reach:
        before = _along(line, cum, here - d - step)
        after = _along(line, cum, here + d + step)
        if haversine_mi(before, after) > SPUR_SAME_MI:
            break
        d += step
    return d, tuple(round(c, 5) for c in _along(line, cum, here - d))


def without_spurs(plan: Plan) -> tuple[list, list[int], int] | None:
    """The points with each via point that the route reaches by an out-and-back longer than
    SPUR_MI moved to where the spur leaves the loop, and how many moved; None where none."""
    points = list(plan.points)
    moved = 0
    for i in plan.vias:
        length, junction = spur_at(plan.line, plan.points[i])
        if length >= SPUR_MI:
            points[i] = junction
            moved += 1
    return (points, list(plan.vias), moved) if moved else None


def ring_waypoints(
    centre: tuple[float, float],
    radius_mi: float,
    limit_mi: float,
    stations: list[Station],
    sectors: int = 12,
) -> list[tuple[float, float]]:
    """Waypoints around `centre`, one per sector of the compass where a Metro station lies, at
    the station whose distance out is nearest `radius_mi`, moved straight out from the centre
    by up to 60% of `limit_mi` where the ring is wider than the station, so every waypoint is
    inside the limit with room to spare. Of stations that reach the ring alike, the one that
    moves least. A waypoint within `MIN_GAP_MI` of another is left out. Sorted clockwise from
    north."""
    reach = 0.6 * limit_mi
    chosen: list[tuple[float, float]] = []
    width = 360 / sectors

    def score(t):
        _b, d, _s = t
        reached = min(d + reach, max(d, radius_mi))
        return (round(abs(reached - radius_mi), 2), abs(d - radius_mi))

    for sector in range(sectors):
        lo, hi = sector * width, (sector + 1) * width
        here = [
            (bearing_deg(centre, s.point), haversine_mi(centre, s.point), s)
            for s in stations
            if lo <= bearing_deg(centre, s.point) < hi and haversine_mi(centre, s.point) >= 1.0
        ]
        if not here:
            continue
        b, d, s = min(here, key=score)
        out = min(reach, max(0.0, radius_mi - d))
        # A waypoint at the station itself is its bike entrance (`Station.way_in`, issue #39),
        # not the platform point, which can be in a freeway median.
        at_station = tuple(round(c, 5) for c in s.way_in)
        point = destination(s.point, b, out) if out > 0.05 else at_station
        if not inside_coverage(point):
            point = at_station
        if all(haversine_mi(point, other) >= MIN_GAP_MI for other in chosen):
            chosen.append(point)
    return sorted(set(chosen), key=lambda p: bearing_deg(centre, p))


def loop_points_from(
    start: tuple[float, float] | None, ring: list[tuple[float, float]], centre
) -> tuple[list[tuple[float, float]], list[int]]:
    """The loop as points [start, ring..., start] with every ring point a via point, starting
    at the ring point clockwise from the start's own bearing."""
    if start is None:
        start, ring = ring[0], ring[1:]
    else:
        b = bearing_deg(centre, start)
        turn = next((i for i, p in enumerate(ring) if bearing_deg(centre, p) >= b), 0)
        ring = ring[turn:] + ring[:turn]
    ring = ring[: MAX_POINTS - 2]
    points = [start, *ring, start]
    return points, list(range(1, len(points) - 1))


# --- Tools ----------------------------------------------------------------------------------

POINT_SCHEMA = {
    "description": (
        'A point: [lon, lat], {"lon": .., "lat": ..}, a Metro station said with "Metro" or'
        ' "station" ("Shady Grove Metro"), or a place or address to search for.'
    ),
    "anyOf": [
        {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
        {
            "type": "object",
            "properties": {"lon": {"type": "number"}, "lat": {"type": "number"}},
            "required": ["lon", "lat"],
        },
        {"type": "string"},
    ],
}
RIDE_OPTIONS = {
    "preset": {
        "type": "string",
        "enum": list(PRESETS),
        "default": "default",
        "description": (
            "The ride type; pick the one that fits the ask. default: everyday riding."
            " trailmaxxing: the calmest route, directness second (stress 100, honours"
            " target_miles). novice: Novice and Nervous, every road read one stress level up."
            " group-ride: a club ride. mass-ride: a large group on the direct roadway (no loops,"
            " stress and hills held low). mountain-goat: seeks climbs. mountain-bike: trails by"
            " IMBA level. gravel: unpaved welcome. fast: direct, traffic tolerant. road-bike: a"
            " road bike, off gravel, dirt and winding trails where there is a paved way round,"
            " fewer turns. cargo: cargo"
            " bike (carrying, assist). tandem: a bicycle built for two, no narrow barriers,"
            " fewer turns, gentler climbs. ebike: e-bike rules and pace. bikeshare: Capital"
            " Bikeshare dock to dock (two points). rebalance: from the start alone (one point),"
            " the nearest crowded station to the nearest one that needs bikes. bike-transit"
            " and bikeshare-transit:"
            " bike plus Metro and bus (two points; depart_at, transit_option). walk: on foot,"
            " turn by turn (two points). walk-transit: on foot plus Metro and bus (two points;"
            " depart_at, transit_option). run: a run on foot, trails, paths and quiet streets"
            " in long stretches first, fewer traffic lights, lit ways after dark; loops."
        ),
    },
    "stress": {
        "type": "integer",
        "minimum": 0,
        "maximum": 100,
        "description": (
            "The traffic-stress slider. 70 is Default; 80 keeps to low-stress ways unless"
            " avoiding them takes much longer (a good 'low stress' setting); above 80 a calm"
            " detour search accepts longer routes to avoid LTS 3, 4 and Avoid roads (slower to"
            " plan on a long ride); 100 is the calmest. Absent: the ride type's own."
        ),
    },
    "hills": {
        "type": "integer",
        "minimum": -100,
        "maximum": 100,
        "description": (
            "The hills slider: -100 avoids climbing, 0 fastest. Absent: the ride type's own."
        ),
    },
    "when": {
        "type": "string",
        "enum": ["weekend", "weekday_rush", "weekday_offpeak", "night"],
        "description": (
            "When the ride is, for traffic. Absent: depart_at's, where it is given, else now."
        ),
    },
    "rider_weight_lb": {
        "type": "number",
        "description": (
            "Rider, bike and load together, pounds; weighs climbs at the top of the stress slider."
        ),
    },
    "target_miles": {
        "type": "number",
        "description": (
            "At stress 100 (Trailmaxxing) only: the longest the ride may be, miles. A limit,"
            " not a length to fill; soft: where only a calmer route over it is found, the"
            " answer's summary says `over_target`."
        ),
    },
    "pace_mph": {
        "type": "number",
        "minimum": 4,
        "maximum": 31,
        "description": (
            "The rider's own speed on the flat, mph (the app's Riding speed), 5 to 31: times and"
            " arrival are worked out at it, hills and junction waits still counted. On Run, the"
            " running pace, 4 to 10. Absent: the ride type's own pace. Not on Mass Ride, a share"
            " bike or Walk."
        ),
    },
    "carrying": {"type": "string", "enum": ["cargo", "people"], "description": "Cargo only."},
    "assist": {"type": "boolean", "description": "Cargo only: electric assist."},
    "mtb_level": {
        "type": "integer",
        "minimum": 1,
        "maximum": 4,
        "description": "Mountain Bike only: the hardest trail level, 1 (green) to 4 (red).",
    },
    "mtb_preferred": {
        "type": "integer",
        "minimum": 1,
        "maximum": 4,
        "description": "Mountain Bike only: the trail level preferred.",
    },
    "bike": {
        "type": "string",
        "enum": ["classic", "ebike"],
        "description": "Bikeshare and Rebalance only.",
    },
    "ride_size": {
        "type": "integer",
        "minimum": 100,
        "maximum": 2000,
        "description": (
            "Mass Ride only: the expected number of riders. Send it when the organiser gave"
            " it; asking is fine but not needed, since without it the ride is planned at 500"
            " (our default) and the answer says so. The road room and the corkers depend on"
            " it. Roads carrying"
            " fewer riders a minute than it needs (riders / 5) are priced in the route choice;"
            " the answer's `mass_capacity` says where the route falls short and the corkers it"
            " needs."
        ),
    },
    "corking": {
        "type": "object",
        "description": (
            "Mass Ride only, when the organiser asks: which junctions to cork, for the corker"
            " count and chart (the route is not changed, and the app's link still counts every"
            " junction). from_lts corks only junctions whose road is at least that level (3, the"
            " default, is every junction the app flags; 4 leaves out LTS 3 roads; a junction whose"
            " road level is not known stays corked). skip leaves out junctions by street name"
            " (whole words, any case: 'Kennedy St') or by mile. Kept as the draft is"
            " revised; clear_settings corking undoes it."
        ),
        "properties": {
            "from_lts": {"type": "number", "enum": [3, 3.5, 4, 4.5, 5]},
            "skip": {
                "type": "array",
                "items": {"anyOf": [{"type": "string", "minLength": 2}, {"type": "number"}]},
                "maxItems": 40,
            },
        },
        "additionalProperties": False,
    },
    "ending": {
        "type": "string",
        "enum": ["dock", "outside_dock"],
        "description": "Bikeshare e-bike only: end at a dock or at the destination itself.",
    },
    "depart_at": {
        "type": "string",
        "description": (
            "Transit ride types only: ISO 8601 departure time; the bike legs are planned for its"
            " traffic and closures too, unless `when` says otherwise. Absent: now."
        ),
    },
    "transit_option": {
        "type": "string",
        "description": "Transit ride types only: an option's key from an earlier answer.",
    },
    "novice_legs": {
        "type": "boolean",
        "description": "Transit ride types only: plan the bike legs as Novice and Nervous.",
    },
    "trails_off": {
        "type": "boolean",
        "default": False,
        "description": "Keep to roads: no paths or trails.",
    },
    "fewer_turns": {
        "type": "boolean",
        "default": False,
        "description": (
            "Bike ride types: the same ride type and settings with turns charged more (Group"
            " Ride's and Road Bike's price), for \"the same but fewer turns\". Compare"
            " summary.turns before and after."
        ),
    },
    "paved": {
        "type": "boolean",
        "default": False,
        "description": (
            "Bike ride types: the same ride type and settings with gravel and dirt avoided"
            " wherever pavement runs near (never closed). Compare summary.unpaved."
        ),
    },
    "easy_mtb": {
        "type": "boolean",
        "default": False,
        "description": (
            "default and trailmaxxing only: Easy MTB trails. Also ride mountain-bike trails"
            " rated easy (mtb:scale or IMBA 0 or 1) or unrated (grass and dirt), on the"
            " off-road graph as gravel does, steering off trails rated 2 or harder. The"
            " summary's `easy_mtb` says where the route still rides a harder one, or where"
            " the off-road router was not running and the usual trails were kept."
        ),
    },
    "max_miles_from_metro": {
        "type": "number",
        "exclusiveMinimum": 0,
        "description": (
            "Check that the route never strays more than this far (straight line, miles) from a"
            " Metrorail station, and report the stretches that do."
        ),
    },
}

INTERVALS = {
    "type": "object",
    "description": (
        "Check the route for interval training: where an effort of on_minutes can run"
        " without a stop sign, signal, busy road to cross, sharp turn, descent or LTS 4"
        " road (climbs are fine and slow the effort's pace). The answer's `intervals` says"
        " `sets_in_one_session`: how many sets fit riding the route through with each rest"
        " near off_minutes (lap after lap where it ends where it began), each effort's"
        " miles, roads and rest; the `repeats`: clear climbs to ride up for each effort and"
        " back down to recover (one direction only needs to be clear), the longest clear"
        " stretches and what breaks the rest. For a repeat, plan just the stretch, in the"
        " effort's direction."
    ),
    "properties": {
        "on_minutes": {"type": "number", "default": 5},
        "off_minutes": {"type": "number", "default": 3},
        "sets": {"type": "integer", "default": 5},
        "pace_mph": {
            "type": "number",
            "default": 18,
            "description": "The effort's pace on the flat; climbs are slower.",
        },
    },
}

AVOID = {
    "type": "array",
    "maxItems": MAX_AVOID,
    "items": {
        "type": "object",
        "properties": {
            "road": {"type": "string", "description": "A road the draft rides, by its name."},
            "from_mi": {"type": "number", "minimum": 0},
            "to_mi": {"type": "number", "exclusiveMinimum": 0},
            "line": {
                "type": "array",
                "items": POINT_SCHEMA,
                "minItems": 2,
                "description": "[lon, lat] pairs along the road to leave out.",
            },
        },
    },
    "description": (
        "Roads to leave out of the plan, as Ride's Road closed does: each a road the draft"
        " rides (by name: every stretch of it), a mile range of the draft (from_mi, to_mi),"
        " or a line of [lon, lat] pairs. The route neither rides along nor crosses them, so"
        " give the stretch to avoid, not a whole long road. Kept as the draft is revised;"
        f" {MAX_AVOID} at most. plan_route takes lines only (there is no draft yet). Not with"
        " a followed line (follow), which is ridden as it is; an alternative's draft plans"
        " through its points instead."
    ),
}

ALTERNATIVES = {
    "type": "boolean",
    "default": False,
    "description": (
        "Also answer the other routes the site's search finds for these points at the same"
        f" settings (up to {MAX_ALTERNATIVES}, ranked after the chosen one): each with its own"
        " draft_id, its figures (miles, minutes, climb, LTS 3+ miles, unpaved miles,"
        " junctions), extra miles and minutes against the chosen route, and main roads, to"
        " compare, revise, read with route_segments or save. An alternative's draft keeps"
        " its own line when revised (a new pace, another ride type) until its points change"
        " or a road is avoided: then it plans through its points."
    ),
}

TRIM_SPURS = {
    "type": "boolean",
    "default": True,
    "description": (
        f"Where the route reaches a via point by an out-and-back of {SPUR_MI:g} mi or more, move"
        " the point to where the spur leaves the road and plan again (kept when shorter). False"
        " keeps the via points where they are."
    ),
}

# The plan tools' options, as POST /api/route names them (all optional).
# Reach (Stephen, 2026-11-04): the rings' points (core/reach.py MAX_POINTS) and the ride
# options they take.
REACH_MAX_POINTS = 5
REACH_OPTIONS = (
    "preset",
    "stress",
    "hills",
    "when",
    "pace_mph",
    "carrying",
    "assist",
    "trails_off",
)
REACH_NOT_YET = frozenset({"bike-transit", "bikeshare-transit", "walk-transit"})
REACH_ON_FOOT = frozenset({"walk", "run"})
# The calm layer's setting (core/reach.py CALM_STRESS: Low-stress).
CALM_STRESS = 80
# Where each bike ride type's traffic slider starts (core/presets.py stress_start), and Cargo
# Bike's by what it carries: the calm rule reads it when no stress is given.
STRESS_START = {
    "default": 70,
    "trailmaxxing": 100,
    "novice": 100,
    "group-ride": 40,
    "mass-ride": 0,
    "mountain-goat": 40,
    "mountain-bike": 80,
    "gravel": 40,
    "fast": 10,
    "road-bike": 40,
    "cargo": 70,
    "tandem": 80,
    "ebike": 70,
    "bikeshare": 80,
    "rebalance": 80,
}
CARGO_STRESS_START = {"cargo": 70, "people": 80}
# compare_places: one place needs a matrix row (or two, with the calm one) of the site's
# nearest-place search, each held to its own budget; a place is not begun with less than this
# left of the call's time, so none is answered in straight lines for want of it.
COMPARE_PLACE_S = 12


def calm_offered(preset: str, dials: dict) -> bool:
    """Whether a calm figure says anything (core/reach.py calm_offered): a bike ride type that
    is set below Low-stress, and whose slider is not locked (Mass Ride). A ride type at or past
    Low-stress, from its start or the rider's stress, is its own calm."""
    if preset in REACH_ON_FOOT or preset in REACH_NOT_YET or preset == "mass-ride":
        return False
    stress = dials.get("stress")
    if stress is None:
        if preset == "cargo":
            stress = CARGO_STRESS_START.get(dials.get("carrying") or "cargo", STRESS_START["cargo"])
        else:
            stress = STRESS_START.get(preset, STRESS_START["default"])
    return stress < CALM_STRESS


PASSED_OPTIONS = (
    "stress",
    "hills",
    "when",
    "carrying",
    "assist",
    "trails_off",
    "fewer_turns",
    "paved",
    "easy_mtb",
    "mtb_level",
    "mtb_preferred",
    "ride_size",
    "corking",
    "bike",
    "ending",
    "depart_at",
    "transit_option",
    "novice_legs",
)


# A saved route's tags (core.models.SavedRoute.TAGS_MAX and TAG_MAX), the rider's own words.
TAGS_SCHEMA = {
    "type": "array",
    "items": {"type": "string", "minLength": 1, "maxLength": 30},
    "maxItems": 8,
}

# The route view's base map (VIEW_URI): called by the view itself, never by the model (the MCP Apps
# extension's visibility "app" keeps it out of the model's tool list).
VIEW_MAP_TOOL = {
    "name": "route_view_map",
    "title": "Route view base map",
    "description": (
        "Called by the route view itself, with a key only it holds: never call it. The base"
        " map behind a draft's map in the view. plan_route's answer has everything to say."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "draft_id": {"type": "string"},
            "key": {"type": "string", "description": "The route view's own key."},
            "centre": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
            "scale": {"type": "number"},
            "width": {"type": "integer", "minimum": 16, "maximum": 1200},
            "height": {"type": "integer", "minimum": 16, "maximum": 480},
        },
        "required": ["draft_id", "key", "centre", "scale", "width", "height"],
    },
    "annotations": {"readOnlyHint": True, "openWorldHint": False},
    "_meta": {"ui": {"visibility": ["app"]}},
}

# A draft's map and graphs as one picture, to share (the owner, 2026-11-10: "Also allow for an
# image if requested so it can be shared"). On the site only (core.route_picture).
PICTURE_TOOL = {
    "name": "route_picture",
    "title": "Route picture",
    "description": (
        "Only when the rider asks for a picture or image of a route, to share: the draft's map"
        " coloured by traffic stress with its stress ribbon and elevation profile (and on a Mass"
        " Ride its rider flow and corkers), as one PNG, with a link that opens it while the"
        " draft is kept. Give the rider the link."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {"draft_id": {"type": "string"}},
        "required": ["draft_id"],
    },
    "annotations": {"readOnlyHint": True, "openWorldHint": False},
}

# The route's turn cues as phone-sized images, an arrow beside each (the owner, 2026-11-10: "some
# people perfer to just navigate by a static image ... Basically show the arrows"; "make sure stops
# are listed"). On the site only (core.cue_cards), as Plan's "Cue sheet image" export.
# The images sent in the answer itself (our default): the rest are linked.
INLINE_CUE_IMAGES = 3
CUE_CARDS_TOOL = {
    "name": "cue_cards",
    "title": "Turn cue images",
    "description": (
        "Only when the rider asks for turn cues, a cue sheet or arrows as images, to navigate by"
        " a picture on their phone: the draft's cues as phone-sized PNGs (a lock screen's size,"
        " its clock and controls left clear), each row the miles from the start, an arrow, the"
        " turn and the road; stops are listed by number, and by name where `stop_names` (or the"
        " plan's link) names them. Where the cues need more than one image, each leg (start or"
        " stop to the next stop or finish) has its own, Part 1 of N. The first few images come"
        " in the answer; each has a link that opens it while the draft is kept: give the rider"
        " the links. The last image (Part N of N) is the data credits alone. `cues` has the"
        " same cues as text."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "draft_id": {"type": "string"},
            "stop_names": {
                "type": "object",
                "description": (
                    'Names for the stops, by stop number from 1 ({"1": "Union Market"}),'
                    ' where the rider named them; a stop without one is "Stop N". Names given'
                    " are kept on a new draft (the answer's draft_id), as revise_route keeps a"
                    " change."
                ),
                "additionalProperties": {"type": "string", "maxLength": 60},
            },
            "dark": {
                "type": "boolean",
                "description": (
                    "Light type on black, for a ride at night (ask the rider which they want"
                    " when the ride is after dark); light images when left out."
                ),
            },
        },
        "required": ["draft_id"],
    },
    "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
}

# scenic_roads_near's max_lts: a road is kept when at least this share of its miles in reach is
# at the level asked or calmer (our default, unmeasured).
SCENIC_CALM_SHARE = 0.5


def _calm_share(road: dict, most: float) -> float:
    """The share of a scenic road's miles (`lts_miles`: "LTS 2", "Avoid") at `most` or calmer."""
    by_level = road.get("lts_miles") or {}
    total = sum(by_level.values())
    if total <= 0:
        return 0.0
    calm = 0.0
    for label, miles in by_level.items():
        try:
            level = 5.0 if label == "Avoid" else float(str(label).removeprefix("LTS "))
        except ValueError:
            continue
        if level <= most:
            calm += miles
    return calm / total


TOOLS = [
    {
        "name": "find_place",
        "title": "Find a place",
        "description": (
            "Search RouteMaker's place search (DC to Baltimore) for a place, address or street;"
            " returns up to five matches with [lon, lat]. Give near (a point of the route) to"
            " search around it: a road name such as 'Moore Road' exists in several counties."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string", "minLength": 2}, "near": POINT_SCHEMA},
            "required": ["query"],
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "metro_stations",
        "title": "Metro stations",
        "description": (
            "List Metrorail stations (all 98, or those within a distance of a point), with lines,"
            " [lon, lat], the [lon, lat] of its bike entrance (route to that, not the station"
            " point), and straight-line miles and compass bearing from the point."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "near": POINT_SCHEMA,
                "within_miles": {"type": "number", "exclusiveMinimum": 0},
            },
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "scenic_roads_near",
        "title": "Scenic roads near a place",
        "description": (
            "List the designated scenic roads near a point (nearest first, up to 25):"
            " Montgomery County Rustic and Exceptional Rustic Roads, Maryland Scenic Byways,"
            " the East Coast Greenway and US Bicycle Routes, each with its name, miles in"
            " reach, miles at each traffic-stress level, and a [lon, lat] on it. Use it when a"
            " rider asks for rustic, scenic or country roads: put via points on the ones that"
            " fit (lower LTS first) and plan. Several rustic roads rate LTS 3 or 4, and the"
            " router will not pick them on its own."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "near": POINT_SCHEMA,
                "within_miles": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "maximum": 15,
                    "default": 5,
                },
                "designation": {
                    "type": "string",
                    "description": "Only these, by a word of the designation: 'rustic', 'byway'.",
                },
                "max_lts": {
                    "type": "number",
                    "minimum": 1,
                    "maximum": 4.5,
                    "description": (
                        "Only roads with at least half their miles in reach at this traffic-stress"
                        " level or calmer (half is our default, unmeasured). Absent: every road."
                    ),
                },
            },
            "required": ["near"],
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "climbs_near",
        "title": "Climbs near a place",
        "description": (
            "List the categorised climbs near a point (Cat 5 to HC, from the Climbs map"
            " layer): name, miles, gain, average grade, surface, its foot and summit and"
            " `through` points up it, and `effort_minutes`, the time up it at pace_mph."
            " For hill repeats in an interval session (ride up for each effort, back down to"
            " recover; a steep climb needs the least road), pass on_minutes: only climbs"
            " long enough are listed, steepest first, and the first few are planned up and"
            " checked (`clear`): whether an effort fits with no stop, signal, busy crossing"
            " or sharp turn. Plan a repeat with plan_route from its foot through its"
            " `through` points (as via points) to its summit. Climbs mostly on LTS 3+ roads"
            " and unpaved ones are left out unless asked."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "near": POINT_SCHEMA,
                "within_miles": {"type": "number", "exclusiveMinimum": 0, "default": 3},
                "min_grade": {"type": "number", "minimum": 0, "description": "%"},
                "on_minutes": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "description": "An effort's minutes: list climbs that hold one, checked.",
                },
                "pace_mph": {"type": "number", "default": 18},
                "check": {"type": "boolean", "default": True},
                "include_busy": {"type": "boolean", "default": False},
                "include_unpaved": {"type": "boolean", "default": False},
            },
            "required": ["near"],
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "closures_near",
        "title": "Closures near a place",
        "description": (
            "List the closures and construction in force now near a point, nearest first: trail"
            " and road closures from Maryland SHA, NPS, MPD and RouteMaker's reviewers (Lake"
            " Frank's Lakeside Trail, say), blocked bike lanes and rideable work zones, each"
            " with what is closed, until when, the source and its link. Use it before"
            " suggesting a park, trail or place to ride, and say the closures. plan_route"
            " already routes round closures and lists those on or round its route. Potential"
            " closures (DDOT's permits and planned work by DDOT, DC Water and WSSC Water,"
            " which may never close anything) only with include_permits."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "near": POINT_SCHEMA,
                "within_miles": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "maximum": CLOSURES_NEAR_MAX_MI,
                    "default": 2,
                },
                "include_permits": {"type": "boolean", "default": False},
            },
            "required": ["near"],
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "plan_route",
        "title": "Plan a route",
        "description": (
            "Plan a bike route on RouteMaker through 2 to 25 points (start, stops or via points,"
            " end) and summarise it: distance, time, climbing, the share on each traffic-stress"
            " level (LTS 1 calmest to 4, and Avoid) and on paths and lanes. The route is a draft:"
            " it comes back with a draft_id and a link that opens this exact route in the app"
            " (a shared link, as the app's Share makes), and nothing is saved to My routes."
            " Revise it with revise_route; keep it with save_route once the rider is happy."
            " The answer also says what the route rides: `roads` in order (miles, main and"
            " worst LTS, facility, and `scenic` for a rustic road, scenic byway, the East Coast"
            " Greenway or a US Bicycle Route), `busy_stretches` (where it rides LTS 3 and up;"
            " a short bit at a Metro station end is left out),"
            " `junctions` (very-high-stress crossings and turns), `scenic_roads`, and"
            " `small_detours` / `via_spurs` (where it leaves a road and comes back to it, or"
            " goes out and back to a via point; riders rarely want these: move or drop the"
            " point with revise_route). On a transit trip these describe its first ride only;"
            " `summary.transit.later_rides` gives each ride after it (miles, LTS, busy"
            " stretches). To shape a route onto roads the router does not pick"
            " on its own (a rustic road, a trail; scenic_roads_near lists them), add via points"
            " ON those roads, by [lon, lat]"
            " or by name: a name is searched near the route's other points, and an ambiguous"
            " one is asked back. `closures` lists the closures it goes through or round, and"
            " `closure_warning` says when one is on the route (often a via point only a closed"
            " path reaches: move it); `check_before_you_go` lists park notices for the ride's"
            " time, such as a deer-management closure at night (warnings, not routed round);"
            " `potential_closures` lists the permits and planned work along the route that may"
            " close the road or bike lane in their window (DDOT permits, DDOT ProTrack+, DC"
            " Water, WSSC Water), with their miles, source and link: not routed round."
            " Every closure row names its source and links to it: give the rider both."
            " Read these before sending the link, and say the busy parts, any closure and any"
            " notice."
            " With max_miles_from_metro it checks the distance from Metro and, with"
            " fix_metro_rounds, adds the nearest station as a via point where the route strays."
            " The summary also gives unpaved miles and the minutes spent waiting at signals and"
            " stop signs; `legs` gives miles, minutes, climb and busy miles between stops (for"
            " food, water and overnight stops), and `steep_grades` and `road_hazards` (cobbles,"
            " rails) say where. To optimize, read the route stretch by stretch with"
            " route_segments, ask for `alternatives`, set the rider's pace_mph, `avoid` a"
            " stretch, and compare revisions by revise_route's `changed_from_previous`. `why`"
            " (bike rides up to 25 mi in straight lines) sets the route against the most direct"
            " one: miles and minutes more, busy miles fewer, and which busy roads it leaves for"
            " which; use it when the rider asks why it goes this way, or when it is much longer."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": DRAFT_NAME_SCHEMA,
                "test": TEST_SCHEMA,
                "points": {
                    "type": "array",
                    "items": POINT_SCHEMA,
                    # One: a Rebalance Ride's start alone (2026-11-07); other ride types take two.
                    "minItems": 1,
                    "maxItems": MAX_POINTS,
                    "description": (
                        "Start first, then any stops, then the end."
                        " rebalance takes the start alone."
                    ),
                },
                "best_order": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Alleycat or errand checkpoints: keep the first point (start) and the"
                        " last (finish) and visit the points between in the quickest order."
                        " The shortest orders by straight line are planned and the quickest"
                        " ridden one kept; `checkpoint_order` says the order. Not with"
                        " via_points or loop."
                    ),
                },
                "via_points": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": (
                        "Indices into points of via points, which only shape the route (no stop,"
                        " no U-turn); never the first or last."
                    ),
                },
                "loop": {
                    "type": "boolean",
                    "default": False,
                    "description": "Come back to the start by a different way.",
                },
                "fix_metro_rounds": {"type": "integer", "minimum": 0, "maximum": 4, "default": 0},
                "trim_spurs": TRIM_SPURS,
                "intervals": INTERVALS,
                "avoid": AVOID,
                "alternatives": ALTERNATIVES,
                "follow": {
                    "type": "object",
                    "properties": {
                        "polyline": {"type": "string", "minLength": 4},
                        "exact": {
                            "type": "boolean",
                            "default": False,
                            "description": "Follow the line as ridden, against one-way streets.",
                        },
                    },
                    "required": ["polyline"],
                    "description": (
                        "Plan along a line the rider has (a GPX track, a drawn route) instead of"
                        " through points: an encoded polyline at precision 6, planned as the"
                        " app plans an opened file. Leave points out."
                    ),
                },
                **RIDE_OPTIONS,
            },
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "reach",
        "title": "How far you can ride",
        "description": (
            "Where a rider can be in 15, 30, 45 and 60 minutes (reach rings, isochrones) from one"
            " to five points, by any bike ride type (its graph, pace and traffic setting), on"
            " foot (walk, run), from the points or to them. For each ring: its area (sq mi and"
            " km2) and the Metro stations, bike racks, places to eat and places to see inside;"
            " with calm (default on) the same rings at Low-stress (stress 80), so the gap shows"
            " what busy roads add. Several points combine as any (within the time of at least"
            " one), all (somewhere every point reaches: a meeting spot) or each (a set per"
            " point). Lower stress shrinks the rings to calmer ways; above 80 they are 80's."
            " The link opens the same rings in the app (Plan, Reach), shareable; the app draws"
            " only 15, 30, 45 and 60, and link_rings says which when other minutes were asked."
            " The transit"
            " ride types have no rings yet."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "points": {
                    "type": "array",
                    "items": POINT_SCHEMA,
                    "minItems": 1,
                    "maxItems": REACH_MAX_POINTS,
                },
                "minutes": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 5, "maximum": 60},
                    "minItems": 1,
                    "maxItems": 4,
                    "default": [15, 30, 45, 60],
                },
                "direction": {"type": "string", "enum": ["from", "to"], "default": "from"},
                "combine": {"type": "string", "enum": ["any", "all", "each"], "default": "any"},
                "calm": {"type": "boolean", "default": True},
                **{k: RIDE_OPTIONS[k] for k in REACH_OPTIONS},
            },
            "required": ["points"],
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "compare_places",
        "title": "Compare places by ride",
        "description": (
            "Compare 2 to 6 places to start from (a home, a hotel, an office)"
            " against 1 to 3 places the rider goes, each with an optional minute limit: one row"
            " per place, with the riding minutes and miles to each destination at the rider's"
            " traffic setting and at Low-stress (calm_minutes; none where the setting is"
            " already Low-stress or calmer), and whether each limit is met, best first. Times"
            " are the router's own on the ride type's graph (one matrix row a place), not full"
            " routes: plan the chosen one with plan_route. Bike ride types only. Each row has a"
            " reach link to its rings in the app. Places left when time runs out are listed in"
            " not_compared."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "places": {"type": "array", "items": POINT_SCHEMA, "minItems": 2, "maxItems": 6},
                "destinations": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 3,
                    "items": {
                        "type": "object",
                        "properties": {
                            "place": POINT_SCHEMA,
                            "max_minutes": {"type": "number", "exclusiveMinimum": 0},
                        },
                        "required": ["place"],
                    },
                },
                **{k: RIDE_OPTIONS[k] for k in REACH_OPTIONS},
            },
            "required": ["places", "destinations"],
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "plan_metro_loop",
        "title": "Plan a Metro loop",
        "description": (
            "Plan a loop of about target_miles around a centre (DC by default) that stays within"
            " max_miles_from_metro of a Metrorail station: waypoints are picked at Metro stations"
            " (or just beyond them) around the compass, the loop is planned, rescaled once"
            " towards the target length, and repaired where it strays by adding the nearest"
            " station. Each plan of a long loop can take up to a minute; max_plans bounds them."
            " Answers the best loop found, with its Metro check and link, as a draft (see"
            " plan_route): nothing is saved."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": DRAFT_NAME_SCHEMA,
                "test": TEST_SCHEMA,
                "target_miles": {
                    "type": "number",
                    "minimum": 5,
                    "maximum": 200,
                    "description": (
                        "The loop's length, miles. The site plans at most 124 mi of straight"
                        " lines between points, so past about 150 mi (more on calm settings,"
                        " which wind more) the ring is kept smaller and the loop comes out short."
                    ),
                },
                "max_miles_from_metro": {"type": "number", "exclusiveMinimum": 0, "default": 5},
                "start": POINT_SCHEMA,
                "centre": POINT_SCHEMA,
                "max_plans": {"type": "integer", "minimum": 1, "maximum": 6, "default": 4},
                **{
                    k: v
                    for k, v in RIDE_OPTIONS.items()
                    if k not in ("max_miles_from_metro", "target_miles", "stress")
                },
                "stress": {
                    **RIDE_OPTIONS["stress"],
                    "description": RIDE_OPTIONS["stress"]["description"].replace(
                        "Absent: the ride type's own.",
                        "Absent: 80 on default (low stress), else the ride type's own.",
                    ),
                },
            },
            "required": ["target_miles"],
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "open_link",
        "title": "Open a RouteMaker link",
        "description": (
            "Start a draft from a RouteMaker link the rider pastes: the address of the page"
            " showing a route (after changing it in the app, or opening one of their saved"
            " routes) or a shared route's link. A shared link (one this server gave, too) is"
            " taken exactly as it was kept; any other is planned as the app would. Answers it"
            " as a draft to revise or save."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "link": {"type": "string", "minLength": 3},
                "max_miles_from_metro": RIDE_OPTIONS["max_miles_from_metro"],
                "test": TEST_SCHEMA,
            },
            "required": ["link"],
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "revise_route",
        "title": "Revise a route",
        "description": (
            "Change a draft the rider has looked at and plan it again, as a new draft (the old"
            " one stays, to go back to). Send only what changes: points to add, move or remove,"
            " the ride type, any setting, loop, the Metro limit, or roads to avoid. Nothing is"
            " saved. `changed_from_previous` gives each figure (miles, minutes, climb, LTS 3+"
            " and 4+ miles, unpaved miles, junctions, junction waits) before and after, so you"
            " can tell whether the change helped; revise until the gains are small."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": DRAFT_NAME_SCHEMA,
                "draft_id": {"type": "string"},
                "points": {
                    "type": "array",
                    "items": POINT_SCHEMA,
                    "minItems": 1,
                    "maxItems": MAX_POINTS,
                    "description": (
                        "Replace every point (via_points then index these). rebalance takes the"
                        " start alone."
                    ),
                },
                "add_points": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "point": POINT_SCHEMA,
                            "after": {
                                "type": "integer",
                                "description": "Insert after this index of the draft's points.",
                            },
                            "via": {
                                "type": "boolean",
                                "default": True,
                                "description": "Shape the route only (true), or a stop.",
                            },
                        },
                        "required": ["point", "after"],
                    },
                },
                "move_points": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"index": {"type": "integer"}, "to": POINT_SCHEMA},
                        "required": ["index", "to"],
                    },
                },
                "remove_points": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": (
                        "Indices of the draft's points to drop (the same numbering as"
                        " move_points and add_points' after, before any change)."
                    ),
                },
                "via_points": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Which points of the revised route are via points, numbered"
                    " after the additions and removals.",
                },
                "stop_icons": {
                    "type": "object",
                    "additionalProperties": {
                        "type": ["string", "null"],
                        "enum": [*NOTE_ICONS, None],
                    },
                    "description": (
                        "Icons for stops on the map, by the stop's point index in the revised"
                        ' route (as via_points numbers them): {"2": "coffee"}; null takes'
                        " one away. The route notes' icons. A stop keeps its icon unless it moves."
                    ),
                },
                "loop": {"type": "boolean"},
                "fix_metro_rounds": {"type": "integer", "minimum": 0, "maximum": 4},
                "trim_spurs": TRIM_SPURS,
                "intervals": INTERVALS,
                **{
                    k: {kk: vv for kk, vv in v.items() if kk != "default"}
                    for k, v in RIDE_OPTIONS.items()
                },
                "avoid": AVOID,
                "alternatives": ALTERNATIVES,
                "clear_settings": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [*PASSED_OPTIONS, "max_miles_from_metro", "pace_mph", "avoid"],
                    },
                    "description": (
                        "Settings to set back to the ride type's own; avoid forgets every road"
                        " to avoid."
                    ),
                },
            },
            "required": ["draft_id"],
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "route_segments",
        "title": "Route segments",
        "description": (
            "Read a draft stretch by stretch, for optimizing it: each stretch's miles, road,"
            " LTS (1 calmest to 4, 5 Avoid), facility (path, trail: a mountain-bike trail,"
            " protected, lane, street), surface"
            " where unpaved, average and steepest uphill grade, climb, one-way, and minutes at"
            " the draft's pace (hills and junction waits in place); every higher and very-high"
            " stress junction with its reason; steep grades and road hazards. Give from_mi and"
            " to_mi to read part of a long ride; `next_from_mi` says where the next page starts."
            " Reads the draft only: nothing is planned or saved."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string"},
                "from_mi": {"type": "number", "minimum": 0, "default": 0},
                "to_mi": {"type": "number", "exclusiveMinimum": 0},
                "max_rows": {
                    "type": "integer",
                    "minimum": 5,
                    "maximum": MAX_SEGMENT_ROWS,
                    "default": SEGMENT_ROWS,
                },
            },
            "required": ["draft_id"],
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "ride_conditions",
        "title": "Ride conditions",
        "description": (
            "Light and weather for riding a draft at a time: whether it is dark at the start"
            " and the finish (civil dawn and dusk, as the app's Dawn and Dusk), the arrival"
            " time at the draft's pace, and within 48 hours the National Weather Service"
            " alerts along the route and the first place rain is forecast as the rider gets"
            " there. For a commute, try the times the rider could leave. Times are New York's."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string"},
                "depart_at": {
                    "type": "string",
                    "description": (
                        "ISO 8601 date and time the ride starts; New York's time where it names"
                        " no zone. Absent: now."
                    ),
                },
            },
            "required": ["draft_id"],
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "my_routes",
        "title": "My routes",
        "description": (
            "The rider's saved routes (My routes), on RouteMaker's own connector: with no"
            " route_id or name, their names, miles, ride types and tags (archived ones only"
            " with archived: true; tag and search narrow the list); with route_id or name,"
            ' open one as a draft to revise or read ("my commute"), as open_link opens a link.'
            " Reads only: save_route adds and organize_route tags or archives, on the rider's"
            " word."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "route_id": {"type": "integer"},
                "name": {"type": "string", "minLength": 1, "maxLength": 120},
                "tag": {"type": "string", "minLength": 1, "maxLength": 30},
                "search": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 120,
                    "description": "Words each route's name or tags must hold.",
                },
                "archived": {
                    "type": "boolean",
                    "description": "true: list the archived routes instead. Default false.",
                },
                "max_miles_from_metro": RIDE_OPTIONS["max_miles_from_metro"],
            },
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "route_notes",
        "title": "Route notes",
        "description": (
            "Put notes on a draft's route: a caution (a dangerous intersection, a bad surface)"
            " or a point of interest (a view, a mural, a water fountain), each at a spot, in a"
            " few words of the rider's own. Give the route's whole list of notes each time:"
            " the answer's route_notes lists those it has (an empty list takes them all"
            " away). A note near the route is a cue: on the app's cue sheets, phone images and"
            " bike computer courses, and said in Ride as the rider reaches it; one put further"
            f" off than {NOTE_NEAR_M} m (our default) but within {NOTE_SNAP_M} m is moved onto"
            " the route where it passes nearest. The notes travel in the link and are kept on"
            " a new draft (the answer's draft_id), as revise_route keeps a change."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string"},
                "notes": {
                    "type": "array",
                    "maxItems": MAX_NOTES,
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": ["caution", "interest"]},
                            "text": {"type": "string", "minLength": 1, "maxLength": NOTE_TEXT_MAX},
                            "icon": {
                                "type": "string",
                                "enum": list(NOTE_ICONS),
                                "description": (
                                    "Its sign on the map; a caution's is warning and a point of"
                                    " interest's pin when left out."
                                ),
                            },
                            "at": {
                                **POINT_SCHEMA,
                                "description": (
                                    "Where: [lon, lat], {lon, lat}, or a place or junction to"
                                    " look up near the route. Or give at_mile instead."
                                ),
                            },
                            "at_mile": {
                                "type": "number",
                                "minimum": 0,
                                "description": (
                                    "Miles from the start along the route, in place of at."
                                ),
                            },
                        },
                        "required": ["kind", "text"],
                    },
                },
            },
            "required": ["draft_id", "notes"],
        },
        # Only a new draft, as revise_route's: nothing kept or written.
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "save_route",
        "title": "Save a route",
        "description": (
            "Keep a draft once the rider has said to, under a name: on the site's own connector,"
            " in their My routes, with tags if given; on the rider's own computer, as a GPX"
            " file. replaces (a route_id from my_routes) archives that saved route once this"
            " one is saved, for a new route that supersedes it: only when the rider agrees."
            " fixed true keeps it as a fixed route: its exact line, like a GPX file, never"
            " re-routed in a ride (off it, the way back to the line); only a closure on its"
            " line offers Update route. Left out, it is saved by its via points (our"
            " default), which is usually better: give fixed only when the rider asks for a"
            " fixed or unchanging route. Only on the rider's word."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string"},
                "name": {"type": "string", "minLength": 1, "maxLength": 120},
                "tags": TAGS_SCHEMA,
                "replaces": {"type": "integer"},
                "fixed": {
                    "type": "boolean",
                    "description": (
                        "true: a fixed route, its exact line never planned again. Default"
                        " false: by its via points (our default)."
                    ),
                },
            },
            "required": ["draft_id", "name"],
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
    },
    {
        "name": "my_drafts",
        "title": "My drafts",
        "description": (
            "The routes planned through this app and not saved (drafts), newest revision of"
            " each, newest first: name, miles, ride type, when made, days left and link. Drafts"
            " go on their own a week after they were made (our default), so the rider can find"
            ' a recent one-off ("the sandwich shop loop from Tuesday") without it cluttering My'
            " routes. Revise one with revise_route; save_route keeps it, on the rider's word."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "search": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 120,
                    "description": "Words each draft's name must hold.",
                },
                "archived": {
                    "type": "boolean",
                    "description": "true: list the archived drafts instead. Default false.",
                },
            },
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "archive_draft",
        "title": "Archive a draft",
        "description": (
            "Archive a draft (every revision of its route): it leaves the rider's Load route and"
            " my_drafts, and still goes a week after it was made. For a draft that only tested"
            " or checked RouteMaker: archive it as soon as you are done with it (or plan with"
            " test: true). archived false restores it. Never touches My routes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string"},
                "archived": {"type": "boolean", "description": "Default true."},
            },
            "required": ["draft_id"],
        },
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
    {
        "name": "organize_route",
        "title": "Organize a route",
        "description": (
            "Tag, archive or restore one of the rider's saved routes (a route_id from"
            " my_routes), on RouteMaker's own connector. tags replaces its tags; add_tags and"
            " remove_tags change them; archived true archives it (left out of Load route, and"
            " the first to go when the account is full: the longest archived first), false"
            " restores it. Never renames or deletes. Only on the rider's word."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "route_id": {"type": "integer"},
                "tags": TAGS_SCHEMA,
                "add_tags": TAGS_SCHEMA,
                "remove_tags": TAGS_SCHEMA,
                "archived": {"type": "boolean"},
            },
            "required": ["route_id"],
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
    },
    {
        "name": "gpx_route",
        "title": "Route as a GPX file",
        "description": (
            "A draft as a GPX track for a bike computer or another app: on the rider's own"
            " computer a .gpx file, on the site a download link (for the rider who made the"
            " draft, while the draft is kept). Saves nothing to My routes; give the rider the"
            " file or link."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string"},
                "name": {"type": "string", "minLength": 1, "maxLength": 120},
            },
            "required": ["draft_id"],
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "draft_route_post",
        "title": "Draft a route post",
        "description": (
            "Write a Featured routes post (a page at /routes/<slug> around one exact route) as a"
            " DRAFT, for the site's admin to read and publish in the admin. Offered only to an"
            " instance admin on the site's own connector. The route is a draft_id from"
            " plan_route, open_link or revise_route, or a line to follow (an encoded polyline at"
            " precision 6, as from a GPX file), planned here as the app plans an opened file."
            " To revise it, send the same slug with replace: true (sections are replaced); a"
            " post that has left draft is refused. Refused too if the route starts, ends or"
            " stops in the admin's Home circle. Answers the draft page's link and its figures."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "minLength": 1, "maxLength": 120},
                "slug": {
                    "type": "string",
                    "maxLength": 80,
                    "description": "The page's address; made from the title when left out.",
                },
                "abstract": {"type": "string", "minLength": 1, "description": "About this ride."},
                "audience": {"type": "string", "description": "Who it's for."},
                "byline": {"type": "string", "maxLength": 60, "default": "RouteMaker"},
                "season_label": {"type": "string", "maxLength": 40},
                "season_start": {"type": "string", "description": 'Month and day, as "03-20".'},
                "season_end": {"type": "string", "description": 'Month and day, as "04-15".'},
                "sections": {
                    "type": "array",
                    "maxItems": 12,
                    "items": {
                        "type": "object",
                        "properties": {
                            "heading": {"type": "string", "minLength": 1, "maxLength": 120},
                            "body": {"type": "string"},
                            "from_mile": {"type": "number", "minimum": 0},
                            "to_mile": {"type": "number", "exclusiveMinimum": 0},
                        },
                        "required": ["heading"],
                    },
                    "description": (
                        "Highlighted sections in order; with both miles (along the route) the"
                        " page draws a small map of that stretch."
                    ),
                },
                "photos": {
                    "type": "array",
                    "maxItems": 20,
                    "items": {
                        "type": "object",
                        "properties": {
                            "alt_text": {"type": "string", "minLength": 1, "maxLength": 300},
                            "caption": {"type": "string", "maxLength": 200},
                            "section": {"type": "integer", "minimum": 0, "default": 0},
                        },
                        "required": ["alt_text"],
                    },
                    "description": (
                        "Photos the rider showed you, described: alt_text says what each shows"
                        " for people who cannot see it; section 0 puts it under About this ride,"
                        " 1 and on under that highlighted section. The answer's photo_uploads"
                        " gives each one an upload_url: POST the photo's file there as the body,"
                        " Content-Type image/jpeg, at most 2048 pixels a side and 900 KB (make"
                        " it smaller first if you can), within 24 hours, once, while the post is"
                        " still a draft. Keep its Exif:"
                        " where it was taken is shown on the page (never at the rider's Home);"
                        " when its Exif has no position and you know the spot (from the ride's"
                        " track at the photo's time), send it as the headers X-Photo-Lat and"
                        " X-Photo-Lon (never in the link itself)."
                        " Without a way to send files, leave it: the admin adds it on the"
                        " draft's page. On replace, those still waiting are described again"
                        " (with new links); photos already added stay."
                    ),
                },
                "replace": {
                    "type": "boolean",
                    "default": False,
                    "description": "Rewrite the draft already at this slug.",
                },
                "draft_id": {"type": "string"},
                "follow": {
                    "type": "object",
                    "properties": {
                        "polyline": {"type": "string", "minLength": 4},
                        "preset": RIDE_OPTIONS["preset"],
                        "exact": {
                            "type": "boolean",
                            "default": False,
                            "description": "Follow the line as ridden, against one-way streets.",
                        },
                    },
                    "required": ["polyline"],
                },
            },
            "required": ["title", "abstract"],
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
    },
]

# Offered only where the site says the rider may write posts (`Server(posts=True)`).
POST_TOOLS = {"draft_route_post"}
POST_FIELDS = (
    "title",
    "slug",
    "abstract",
    "audience",
    "byline",
    "season_label",
    "season_start",
    "season_end",
    "sections",
    "photos",
    "replace",
)


def encode_polyline(line: list, precision: int = 6) -> str:
    """[[lon, lat], ...] as an encoded polyline, the way Valhalla writes one."""
    factor, out, last = 10**precision, [], (0, 0)
    for point in line:
        here = (round(point[1] * factor), round(point[0] * factor))
        for delta in (here[0] - last[0], here[1] - last[1]):
            value = ~(delta << 1) if delta < 0 else delta << 1
            while value >= 0x20:
                out.append(chr((0x20 | (value & 0x1F)) + 63))
                value >>= 5
            out.append(chr(value + 63))
        last = here
    return "".join(out)


def decode_polyline(encoded: str, precision: int = 6) -> list[list[float]]:
    """An encoded polyline (Valhalla's, precision 6) as [[lon, lat], ...]."""
    factor = 10**precision
    points, index, lat, lon = [], 0, 0, 0
    while index < len(encoded):
        deltas = []
        for _ in range(2):
            shift = result = 0
            while True:
                if index >= len(encoded):
                    raise ToolError("follow.polyline is cut short")
                byte = ord(encoded[index]) - 63
                index += 1
                if not 0 <= byte < 64:
                    raise ToolError("follow.polyline is not an encoded polyline")
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        lat += deltas[0]
        lon += deltas[1]
        points.append([lon / factor, lat / factor])
    return points


class Call:
    """One tools/call in flight: its progress reports and whether the client cancelled it."""

    def __init__(self, progress=None, deadline: float | None = None):
        self.progress = progress  # function(done, total, message), or None
        self.cancelled = threading.Event()
        # time.monotonic() by which the answer must be sent, or None: the site's own connector
        # (core.connector) answers inside one web request, which the server ends at 60 s.
        self.deadline = deadline
        # The longest plan timed in this call (seconds), or None before the first.
        self.longest_plan_s: float | None = None
        # What the answer carries beside its text, set by Server.call: the route view's data
        # (the result's _meta, never the model's) and pictures (image content).
        self.meta: dict = {}
        self.images: list[dict] = []
        # Seconds this call's lookups have waited for busy answers (patient_request).
        self.lookup_waited: list[float] = [0.0]

    def timed_plan(self, seconds: float) -> None:
        """Note how long one plan took, for `time_for_another_plan`."""
        self.longest_plan_s = max(seconds, self.longest_plan_s or 0.0)

    def time_for_another_plan(self) -> bool:
        """Whether one more plan still fits before the deadline: one as long as the longest
        timed in this call, with room over (PLAN_TIME_FACTOR, PLAN_TIME_SPARE_S), or a long
        ride's whole budget (PLAN_BUDGET_S) before any plan was timed. Before the round 4 hunt
        (L4-4) it was always the whole budget, so on the site's connector (a 55 s deadline) no
        plan could follow one that took more than about 7 s."""
        if self.deadline is None:
            return True
        if self.longest_plan_s is None:
            needed = PLAN_BUDGET_S
        else:
            needed = PLAN_TIME_FACTOR * self.longest_plan_s + PLAN_TIME_SPARE_S
        return time.monotonic() + needed < self.deadline

    def report(self, done, total, message) -> None:
        if self.progress:
            self.progress(done, total, message)

    def check(self) -> None:
        """Stop before the next plan or save once the client has given up on the call: a save
        it no longer waits for would be a second copy when it asks again."""
        if self.cancelled.is_set():
            raise Cancelled()


class Cancelled(ToolError):
    pass


class MemoryDrafts:
    """The drafts of this session (the owner, 2026-10-18: "see a ride, then tell the agent the
    revisions to make and only save it ... when committed"), by id. Held in memory only: nothing
    reaches the site until save_route. The site's own connector keeps them in its database
    instead (core.connector), with the same methods."""

    def __init__(self):
        self._drafts: dict[str, Draft] = {}
        # Each draft's first draft (the route it revises, or itself), when it was made, and
        # whether it was saved (my_drafts).
        self._made: dict[str, tuple[str, datetime, bool]] = {}
        # The routes archived, by their first draft (archive_draft, or a `test` call's).
        self._archived: set[str] = set()
        self._lock = threading.Lock()

    def get(self, draft_id: str) -> Draft | None:
        return self._drafts.get(draft_id)

    def put(self, draft: Draft) -> str:
        with self._lock:
            # Random, so an id from before a restart finds nothing rather than another route.
            draft_id = f"d{secrets.token_hex(4)}"
            self._drafts[draft_id] = draft
            before = self._made.get(draft.revises or "")
            root = before[0] if before else draft_id
            self._made[draft_id] = (root, datetime.now(UTC), False)
            if TEST_CALL.get():
                self._archived.add(root)
            while len(self._drafts) > MAX_DRAFTS:  # the oldest go first
                oldest = next(iter(self._drafts))
                del self._drafts[oldest]
                self._made.pop(oldest, None)
        return draft_id

    def listing(self, archived: bool = False) -> list[dict]:
        """Each route's newest draft not saved, newest first (my_drafts): `draft_id`, `draft`,
        `made` (UTC) and `route_id` (its link's, or None). The archived ones instead with
        `archived`."""
        with self._lock:
            newest: dict[str, dict] = {}
            for draft_id, draft in self._drafts.items():
                root, made, saved = self._made.get(draft_id, (draft_id, None, False))
                if (root in self._archived) != archived:
                    newest.pop(root, None)
                    continue
                newest[root] = {
                    "draft_id": draft_id,
                    "draft": draft,
                    "made": made,
                    "route_id": None,
                    "saved": saved,
                }
            # Newest first by each route's newest draft (ids are put in order).
            order = list(self._drafts)
            rows = [r for r in newest.values() if not r.pop("saved")]
        return sorted(rows, key=lambda r: order.index(r["draft_id"]), reverse=True)

    def saved(self, draft_id: str) -> None:
        """The route was saved: it and its earlier drafts are no longer listed."""
        with self._lock:
            found = self._made.get(draft_id)
            if found is None:
                return
            for key, (root, made, _saved) in list(self._made.items()):
                if root == found[0] and made <= found[1]:
                    self._made[key] = (root, made, True)

    def archive(self, draft_id: str, archived: bool = True) -> bool:
        """Archive the draft's route, every revision (or restore it); whether it was found."""
        with self._lock:
            found = self._made.get(draft_id)
            if found is None:
                return False
            if archived:
                self._archived.add(found[0])
            else:
                self._archived.discard(found[0])
        return True

    def shared(self, draft_id: str, route_id: str) -> None:
        """The draft's link was kept under `route_id`. Nothing to tie here: on the site's own
        connector the link goes with the draft."""

    def __contains__(self, draft_id) -> bool:
        return draft_id in self._drafts


# The site deletes a draft's exact-route link after a week at the latest (shared_routes keep
# "until"): a draft often starts at home, and every revision makes one. On the site's own
# connector it goes with its draft (seven days, our default: core.models.ConnectorDraft.KEPT). A
# route the rider saves is kept in My routes on its own.
DRAFT_LINK_DAYS = 7
# How long a draft lasts on the site's own connector (core.models.ConnectorDraft.KEPT, our
# default): my_drafts counts each one's days left from it.
DRAFT_KEPT = timedelta(days=DRAFT_LINK_DAYS)


def draft_link_keep(today: date | None = None) -> dict:
    """The share body's keep fields for a draft's link: deleted after DRAFT_LINK_DAYS."""
    day = (today or date.today()) + timedelta(days=DRAFT_LINK_DAYS)
    return {"keep": "until", "delete_after": day.isoformat()}


def kept_route(plan: Plan, name: str, fragment: str, dials: dict) -> dict:
    """The route as the site keeps it, saved or shared: the exact line with its heights, the
    plan's inputs, and its answer without the alternatives."""
    return {
        "name": name,
        "source": "plan",
        "line": [list(v[:3]) for v in plan.line],
        "distance_m": plan.answer["distance_m"],
        "inputs": {
            "hash": fragment,
            "points": [list(p) for p in plan.points],
            "preset": plan.preset,
            "dials": page_dials(dials, plan.sent),
        },
        "answer": {
            **plan.answer,
            "candidates": None,
            "avoid_alternate": None,
            "closure_through": None,
        },
    }


def _neighbours(points: list, i: int) -> list[tuple[float, float]]:
    """The points already found, nearest in the list to place `i` first."""
    order = sorted(
        (k for k, p in enumerate(points) if p is not None and k != i), key=lambda k: abs(k - i)
    )
    return [points[k] for k in order]


class Server:
    def __init__(
        self,
        api_factory=Api,
        stations: list[Station] | None = None,
        out_dir=None,
        drafts=None,
        files: bool = True,
        gpx_link=None,
        posts: bool = False,
        icons: list[dict] | None = None,
        routes_read: bool = True,
        routes_organize: bool = True,
        basemap=None,
        view_key=None,
        picture=None,
        picture_link=None,
        cue_cards=None,
        cue_cards_link=None,
    ):
        self._api_factory = api_factory
        self._api: Api | None = None
        self._stations = stations
        self.out_dir = out_dir
        self._lock = threading.Lock()
        self.drafts = MemoryDrafts() if drafts is None else drafts
        # Whether save_route may write a GPX file: not on the site's own connector, whose
        # "computer" is the server.
        self.files = files
        # On the site: function(draft_id, name) -> a download link for the draft's GPX.
        self.gpx_link = gpx_link
        # Whether draft_route_post is offered: on the site's connector, for an instance admin.
        self.posts = posts
        # On the site: the app's icons, for serverInfo (MCP 2025-11-25), so an assistant app
        # that shows them draws RouteMaker's logo beside the connector.
        self.icons = icons or []
        # Whether my_routes may read the rider's My routes: on the site, a grant the rider gave
        # on a consent page that said so (core.connector). On a rider's own computer the site
        # refuses the read itself (no sign-in).
        self.routes_read = routes_read
        # Whether organize_route (and save_route's `replaces`) may tag and archive them: on the
        # site, a grant whose consent page said so (from v0.22.0).
        self.routes_organize = routes_organize
        # On the site: function(centre (lon, lat), scale, width, height) -> (png bytes, town
        # names as (x, y, name)) or None, the base map behind the route view
        # (core.route_view_map). Without it the view draws the line on a plain background.
        self.basemap = basemap
        # On the site: function(draft_id) -> the key route_view_map asks for (core.connector).
        self.view_key = view_key
        # On the site: function(view, line) -> PNG of the draft's map and graphs
        # (core.route_picture), and function(draft_id) -> a link that opens it.
        self.picture = picture
        self.picture_link = picture_link
        # On the site: core.cue_cards (count, draw and cue_rows of the phone cue images), and
        # function(draft_id, page from 1) -> a link that opens one.
        self.cue_cards = cue_cards
        self.cue_cards_link = cue_cards_link

    def tools(self) -> list[dict]:
        """The tools, as tools/list gives them: without the post tool unless posts may be
        written, the route view named on the tools that draft a route, and the view's own
        base map tool where there is a base map."""
        out = []
        for t in TOOLS:
            if t["name"] in POST_TOOLS and not self.posts:
                continue
            if t["name"] in VIEW_TOOLS:
                # The flat "ui/resourceUri" is the extension's older spelling, still read by
                # some assistant apps.
                t = {**t, "_meta": {"ui": {"resourceUri": VIEW_URI}, "ui/resourceUri": VIEW_URI}}
            out.append(t)
        if self.basemap is not None and self.view_key is not None:
            out.append(VIEW_MAP_TOOL)
        if self.picture is not None:
            out.append(PICTURE_TOOL)
        if self.cue_cards is not None:
            out.append(CUE_CARDS_TOOL)
        return out

    def resources(self) -> list[dict]:
        """The resources, as resources/list gives them: the route view's page."""
        return [
            {
                "uri": VIEW_URI,
                "name": "route_view",
                "title": "Route map and graphs",
                "description": (
                    "The route on a map coloured by traffic stress, with its stress ribbon and"
                    " elevation profile, for plan_route, revise_route, open_link and"
                    " plan_metro_loop."
                ),
                "mimeType": VIEW_MIME,
            }
        ]

    def read_resource(self, uri: str) -> dict:
        """resources/read: the route view's page, which needs nothing from any other site (its
        script and styles are inline, the base map comes as a picture from route_view_map)."""
        if uri != VIEW_URI:
            raise ToolError(f"no resource {uri}")
        return {
            "contents": [
                {
                    "uri": VIEW_URI,
                    "mimeType": VIEW_MIME,
                    "text": view_html(),
                    "_meta": {"ui": {"csp": {}, "prefersBorder": True}},
                }
            ]
        }

    # route_picture
    def route_picture(self, args: dict, call: Call) -> dict:
        draft_id = str(args["draft_id"])
        draft = self.drafts.get(draft_id)
        if draft is None:
            raise ToolError(f"no draft {draft_id} (drafts last only a while; plan it again)")
        png = self.picture(draft_view(draft, draft_id), draft.plan.line)
        if png is None:
            raise ToolError("this draft has no line to draw")
        out: dict = {"draft_id": draft_id, "name": draft.name}
        if self.picture_link is not None:
            out["picture_link"] = self.picture_link(draft_id)
            out["note"] = (
                "the link opens the picture (PNG) to share; it works while the draft is kept"
            )
        out[IMAGES_PRIVATE] = [
            {
                "type": "image",
                "data": base64.b64encode(png).decode("ascii"),
                "mimeType": "image/png",
            }
        ]
        return out

    # route_notes
    def route_notes(self, args: dict, call: Call) -> dict:
        draft_id = str(args["draft_id"])
        draft = self.drafts.get(draft_id)
        if draft is None:
            raise ToolError(f"no draft {draft_id} (drafts last only a while; plan it again)")
        asked = args.get("notes")
        if not isinstance(asked, list):
            raise ToolError("notes is the route's whole list of notes ([] for none)")
        if len(asked) > MAX_NOTES:
            raise ToolError(f"a route has at most {MAX_NOTES} notes (our default)")
        plan = draft.plan
        line = plan.line
        if asked and len(line) < 2:
            raise ToolError("the draft has no line to put notes on: plan it again")
        taken: list[dict] = []
        notes: list[dict] = []
        moved: list[str] = []
        for n, note in enumerate(asked, start=1):
            if not isinstance(note, dict):
                raise ToolError(f"note {n}: give kind, text and at or at_mile")
            kind = note.get("kind")
            if kind not in NOTE_KINDS:
                raise ToolError(f"note {n}: kind is caution or interest")
            text = clean_note_text(note.get("text"))
            if not text:
                raise ToolError(f"note {n}: give a few words")
            if note.get("at_mile") is not None:
                try:
                    mile = float(note["at_mile"])
                except (TypeError, ValueError):
                    raise ToolError(f"note {n}: at_mile is a number of miles") from None
                if not math.isfinite(mile):
                    raise ToolError(f"note {n}: at_mile is a number of miles")
                total = (plan.answer.get("distance_m") or 0.0) / METRES_PER_MILE
                if not 0 <= mile <= total + 0.05:
                    raise ToolError(
                        f"note {n}: at_mile is from 0 to {total:.1f}, the route's miles"
                    )
                # The description's miles, as the route's figures give them, on the line.
                lon, lat = point_at_mile(line, mile * _line_scale(plan.answer))
            elif note.get("at") is not None:
                # A place looked up for a note is said apart from the route's points.
                lon, lat = self._point(note["at"], taken, [plan.points[0], plan.points[-1]])
                _, off, nearest = line_nearest(line, lon, lat)
                if off > NOTE_SNAP_M:
                    raise ToolError(
                        f"note {n} ({text}) is {off / METRES_PER_MILE:.1f} mi from the route:"
                        " put it on the route (at_mile, or a junction the route passes)"
                    )
                if off > NOTE_NEAR_M:
                    lon, lat = nearest
                    moved.append(f"note {n} ({text}) was {round(off)} m off the route: put on it")
            else:
                raise ToolError(f"note {n}: give at or at_mile")
            icon = note.get("icon")
            if icon is not None and icon not in NOTE_ICONS:
                raise ToolError(f"note {n}: icon is one of {', '.join(NOTE_ICONS)}")
            kept = {"kind": kind, "lon": round(lon, 5), "lat": round(lat, 5), "text": text}
            if icon and icon != KIND_ICON[kind]:
                kept["icon"] = icon
            notes.append(kept)
        if len(encode_notes(notes)) < len(notes):
            raise ToolError(
                "the notes are too long for the route's link: shorten some, or use fewer"
            )
        options = {**draft.options, "route_notes": notes or None}
        out = self._draft(
            plan,
            options,
            draft.limit,
            moved,
            draft.name,
            revised_from=draft_id,
            trim_spurs=draft.trim_spurs,
            intervals=draft.intervals,
            ride_key=draft.ride_key,
        )
        if not notes:
            out["route_notes"] = []
        if taken:
            out["note_places_taken_as"] = taken
        return out

    # cue_cards
    def cue_cards_tool(self, args: dict, call: Call) -> dict:
        draft_id = str(args["draft_id"])
        draft = self.drafts.get(draft_id)
        if draft is None:
            raise ToolError(f"no draft {draft_id} (drafts last only a while; plan it again)")
        names = cue_card_names(draft.plan, args.get("stop_names"))
        out: dict = {}
        if names != (draft.plan.names or {}):
            # Names given here are kept as a revision of the draft, so its links (and the app's
            # link) name the stops as these images do.
            named = dataclasses.replace(
                draft, plan=dataclasses.replace(draft.plan, names=names), revises=draft_id
            )
            draft_id = self.drafts.put(named)
            draft = named
            out["revised"] = "the stop names are kept on a new draft: use this draft_id from now on"
        drawn = cue_card_args(draft, names)
        total = self.cue_cards.count(*drawn)
        # Only the first few images travel in the answer (each is a phone screen's PNG); every
        # one has its link.
        dark = args.get("dark") is True
        images = self.cue_cards.draw(*drawn, only=range(1, INLINE_CUE_IMAGES + 1), dark=dark)
        out |= {"draft_id": draft_id, "name": draft.name, "images": total}
        # The cues as text too: for the assistant to read out, and for a reader who cannot see
        # the images.
        out["cues"] = [
            {
                "mi": round(r["at_m"] / METRES_PER_MILE, 1),
                "cue": r["turn"],
                **({"road": r["road"]} if r["road"] else {}),
                **({"note": r["reason"]} if r["reason"] else {}),
                **({"then": r["then"]} if r["then"] else {}),
            }
            for r in self.cue_cards.cue_rows(drawn[0], drawn[2], drawn[3], drawn[5])
        ]
        if total > len(images):
            out["shown"] = f"the first {len(images)} of {total} images are shown; all are linked"
        if self.cue_cards_link is not None:
            out["links"] = [
                self.cue_cards_link(draft_id, n + 1, dark)
                if dark
                else self.cue_cards_link(draft_id, n + 1)
                for n in range(total)
            ]
            out["note"] = (
                "each link opens one image (PNG) to save to the phone; they work while the"
                " draft is kept"
            )
        out[IMAGES_PRIVATE] = [
            {
                "type": "image",
                "data": base64.b64encode(png).decode("ascii"),
                "mimeType": "image/png",
            }
            for png in images
        ]
        return out

    # route_view_map (the route view's own: hidden from the model)
    def route_view_map(self, args: dict, call: Call) -> dict:
        if self.basemap is None or self.view_key is None:
            raise ToolError("no base map here")
        if not secrets.compare_digest(
            str(args.get("key") or ""), self.view_key(str(args.get("draft_id") or ""))
        ):
            raise ToolError("route_view_map is the route view's own: it has nothing to answer here")
        try:
            centre = args["centre"]
            lon, lat = float(centre[0]), float(centre[1])
            width, height = int(args["width"]), int(args["height"])
            scale = float(args["scale"])
        except (KeyError, IndexError, TypeError, ValueError):
            raise ToolError("give centre [lon, lat], width, height and scale as numbers") from None
        if not (-180 <= lon <= 180 and -85 <= lat <= 85):
            raise ToolError("centre: [lon, lat]")
        if not (16 <= width <= VIEW_MAP_MAX_W and 16 <= height <= VIEW_MAP_MAX_H):
            raise ToolError(f"width 16 to {VIEW_MAP_MAX_W} and height 16 to {VIEW_MAP_MAX_H} px")
        if not math.isfinite(scale) or not 256 <= scale <= 256 * 2**18:
            raise ToolError("scale: pixels across the world, 256 to 2^26")
        drawn = self.basemap((lon, lat), scale, width, height)
        if drawn is None:
            return {"drawn": False}
        png, places = drawn
        return {
            "drawn": True,
            "places": [[round(x), round(y), name] for x, y, name in places or []],
            IMAGES_PRIVATE: [
                {
                    "type": "image",
                    "data": base64.b64encode(png).decode("ascii"),
                    "mimeType": "image/png",
                }
            ],
        }

    @property
    def api(self) -> Api:
        with self._lock:
            if self._api is None:
                self._api = self._api_factory()
            return self._api

    @property
    def stations(self) -> list[Station]:
        with self._lock:
            if self._stations is None:
                self._stations = load_stations()
            return self._stations

    # find_place
    def find_place(self, args: dict, call: Call) -> dict:
        near = None
        if args.get("near") is not None:
            near, _ = as_point(args["near"], self.api, self.stations)
        rows = []
        # Each match as plan_route would take it (`as_point`): inside the map's area, and an
        # area at the way in its search found, here too where the site did not move it (an
        # older site). find_place gave the park's middle where plan_route went to its boat
        # launch, and a lon_lat copied from it rode to the middle (the second 2026-11-08
        # hunt, P5).
        found = [
            r
            for r in self.api.geocode(str(args["query"]), near)
            if inside_coverage((r["lon"], r["lat"]))
        ]
        for r in (way_in_of(r, found, near) for r in found):
            row = {
                "name": r["name"],
                "label": r["label"],
                "lon_lat": [r["lon"], r["lat"]],
                "kind": r.get("kind"),
            }
            # An area moved to the way in its search found (core.geocode): say so, so the
            # assistant can tell the rider the route goes to the boat launch, not the middle.
            if r.get("way_in"):
                row["way_in"] = r["way_in"]
            if is_rail_station(r):
                # A Metro station found by the search is gone to at its bike way in, as
                # plan_route takes it (`as_point`): its platform point can be in a freeway
                # median (Vienna, Herndon; issue #39), and a lon_lat copied from it rode there
                # (the third 2026-11-08 hunt, PL3-7).
                at, miles = nearest_station((r["lon"], r["lat"]), self.stations)
                if miles <= STATION_MATCH_MI:
                    entrance = list(at.way_in_from(near))
                    row["lon_lat"] = entrance
                    row["bike_entrance"] = entrance
            if near:
                row["miles_from_near"] = round(haversine_mi(near, tuple(row["lon_lat"])), 1)
            rows.append(row)
        return {"results": rows}

    # scenic_roads_near
    def scenic_roads_near(self, args: dict, call: Call) -> dict:
        near, _ = as_point(args["near"], self.api, self.stations)
        try:
            miles = min(15.0, max(0.5, float(args.get("within_miles") or 5)))
        except (TypeError, ValueError):
            raise ToolError("within_miles is a number") from None
        roads = self.api.scenic_roads(near, miles, str(args.get("designation") or "").strip())
        if args.get("max_lts") is not None:
            try:
                most = float(args["max_lts"])
            except (TypeError, ValueError):
                raise ToolError("max_lts is a number from 1 to 4.5") from None
            roads = [road for road in roads if _calm_share(road, most) >= SCENIC_CALM_SHARE]
        return {
            "roads": roads,
            "source": "Montgomery County Planning (Rustic Roads), MDOT SHA (Scenic Byways),"
            " OpenStreetMap (East Coast Greenway, US Bicycle Routes)",
        }

    # climbs_near
    def climbs_near(self, args: dict, call: Call) -> dict:
        near, _ = as_point(args["near"], self.api, self.stations)
        try:
            miles = min(15.0, max(0.5, float(args.get("within_miles") or 3)))
            min_grade = min(30.0, max(0.0, float(args.get("min_grade") or 0)))
            on_min = float(args.get("on_minutes") or 0)
            pace = float(args.get("pace_mph") or 18)
        except (TypeError, ValueError):
            raise ToolError(
                "within_miles, min_grade, on_minutes and pace_mph are numbers"
            ) from None
        if not 4 <= pace <= 35:
            raise ToolError("pace_mph is 4 to 35")
        if not 0 <= on_min <= 60:
            raise ToolError("on_minutes is 0 to 60")
        filters = {
            "min_grade": min_grade,
            "paved_only": not args.get("include_unpaved"),
            "quiet_only": not args.get("include_busy"),
        }
        if on_min:
            filters.update(on_minutes=on_min, pace_mph=pace, steepest=True)
        found = self.api.climbs_near(near, miles, **filters)
        for climb in found:
            climb["effort_minutes"] = climb_minutes(climb["miles"], climb["grade_pct"], pace)
        if on_min:
            # Long enough for one effort up it, steepest first: the least road for the work.
            found = [c for c in found if c["effort_minutes"] >= on_min]
            found.sort(key=lambda c: (-c["grade_pct"], c["away_mi"]))
        checked = 0
        if on_min and args.get("check", True):
            for climb in found[:CLIMB_CHECKS]:
                call.check()
                if not call.time_for_another_plan():
                    break
                began = time.monotonic()
                climb["clear"] = self._climb_clear(climb, on_min, pace)
                call.timed_plan(time.monotonic() - began)
                checked += 1
        out = {
            "climbs": found,
            "checked": checked,
            "source": "Climbs layer: OpenStreetMap (ODbL) and USGS 3DEP elevation",
        }
        if any(c.get("busy") is None for c in found):
            out["note"] = "this map's climbs file does not mark busy roads: check each one's LTS"
        return out

    def _climb_clear(self, climb: dict, on_min: float, pace: float) -> dict:
        """Whether an effort of on_min fits up the climb unbroken: its plan from the foot
        through its points to the summit, read by `interval_check`, if the plan rides it."""
        points = [climb["foot"], *climb.get("through", []), climb["summit"]]
        vias = list(range(1, len(points) - 1))
        try:
            plan = plan_once(
                self.api, self.stations, points, vias, "default", {"debug_junctions": True}, None
            )
        except ToolError as error:
            return {"checked": False, "why": str(error)}
        planned_mi = (plan.answer.get("distance_m") or 0.0) / METRES_PER_MILE
        if not CLIMB_RIDDEN[0] <= planned_mi / max(climb["miles"], 0.01) <= CLIMB_RIDDEN[1]:
            return {
                "checked": False,
                "why": f"the plan up it ran {planned_mi:.2f} mi, off the climb",
            }
        out = interval_check(
            plan.answer,
            {"on_minutes": on_min, "sets": 1, "pace_mph": pace},
            _roads_between(plan.answer),
        )
        longest = max(out["longest_clear"], key=lambda c: c["effort_minutes"], default=None)
        return {
            "checked": True,
            "effort_fits": bool(out["efforts"]),
            "longest_clear_minutes": longest["effort_minutes"] if longest else 0.0,
            "breaks": out["breaks"],
        }

    # closures_near
    def closures_near(self, args: dict, call: Call) -> dict:
        near, _ = as_point(args["near"], self.api, self.stations)
        try:
            miles = min(CLOSURES_NEAR_MAX_MI, max(0.25, float(args.get("within_miles") or 2)))
        except (TypeError, ValueError):
            raise ToolError("within_miles is a number") from None
        lat_deg = miles / (EARTH_RADIUS_MI * math.radians(1))
        lon_deg = lat_deg / math.cos(math.radians(near[1]))
        box = (near[0] - lon_deg, near[1] - lat_deg, near[0] + lon_deg, near[1] + lat_deg)
        # One row per closure: a reviewer's comes as a row for each of its ways.
        found: dict[tuple, dict] = {}
        for row in self.api.closures_map(box, bool(args.get("include_permits"))):
            line = row.get("line") or [row.get("point")]
            dense = _resampled_lonlat(line)
            away, at = min((haversine_mi(near, p), p) for p in dense)
            if away > miles:
                continue
            said = _closure_row(row)
            said.pop("effect", None)
            said["kind"] = row.get("kind")
            key = _closure_id(row)
            length = sum(haversine_mi(p, q) for p, q in zip(dense, dense[1:], strict=False))
            kept = found.get(key)
            if kept is None:
                found[key] = kept = {**said, "miles": 0.0, "away_mi": away, "lon_lat": at}
            kept["miles"] += length
            if away < kept["away_mi"]:
                kept["away_mi"], kept["lon_lat"] = away, at
        rows = sorted(found.values(), key=lambda r: r["away_mi"])
        for r in rows:
            r["miles"] = round(r["miles"], 1)
            r["away_mi"] = round(r["away_mi"], 1)
            r["lon_lat"] = [round(r["lon_lat"][0], 6), round(r["lon_lat"][1], 6)]
        return {
            "closures": rows,
            "within_miles": round(miles, 1),
            "note": "in force now; plan_route also checks the ride's own day",
        }

    # metro_stations
    def metro_stations(self, args: dict, call: Call) -> dict:
        near = None
        if args.get("near") is not None:
            near, _ = as_point(args["near"], self.api, self.stations)
        rows = []
        for s in self.stations:
            row = {
                "name": s.name,
                "lines": s.lines,
                "lon_lat": [s.lon, s.lat],
                # Where a route goes (issue #39): the platform point can be in a freeway median.
                "bike_entrance": list(s.way_in),
            }
            if near:
                row["miles"] = round(haversine_mi(near, s.point), 1)
                row["bearing"] = round(bearing_deg(near, s.point))
            rows.append(row)
        if near:
            if args.get("within_miles"):
                rows = [r for r in rows if r["miles"] <= float(args["within_miles"])]
            rows.sort(key=lambda r: r["miles"])
        return {"stations": rows, "source": "DC Open Data, Metro Stations Regional (CC BY 4.0)"}

    def _options(self, args: dict, preset: str | None = None) -> dict:
        options = {key: args.get(key) for key in PASSED_OPTIONS}
        options["loop"] = bool(args.get("loop"))
        if args.get("target_miles"):
            options["target_distance_m"] = int(finite(args["target_miles"]) * METRES_PER_MILE)
        if args.get("rider_weight_lb"):
            options["system_weight_kg"] = round(finite(args["rider_weight_lb"]) * KG_PER_LB)
        if args.get("pace_mph"):
            field, kmh = pace_option(args["pace_mph"], preset or args.get("preset") or "default")
            options[field] = kmh
        return options

    def _alternatives(self, first: Plan, options: dict, limit) -> list[dict]:
        """The other routes the site's search found for the first plan (`candidates`, ranked
        after it, at the same settings), each kept as a draft of its own to compare, revise,
        read by route_segments or save. Its draft follows its own line when planned again (a
        new pace, another ride type), until its points are changed or a road is avoided."""
        out = []
        main_mi = (first.answer.get("distance_m") or 0.0) / METRES_PER_MILE
        main_min = (first.answer.get("duration_s") or 0.0) / 60
        for found in (first.answer.get("candidates") or [])[:MAX_ALTERNATIVES]:
            line = (found.get("geometry") or {}).get("coordinates")
            if not line:
                continue
            alt_options = dict(options)
            alt_options["follow"] = encode_polyline(_thinned(line, ALTERNATIVE_FOLLOW_POINTS))
            alt_options["follow_alternative"] = True
            alt_options.pop("follow_exact", None)
            sent = request_body(first.points, first.vias, first.preset, alt_options)
            check = metro_check(line, limit, self.stations) if limit else None
            plan = Plan(
                list(first.points),
                list(first.vias),
                first.preset,
                {**found, "candidates": None},
                check,
                sent,
            )
            draft_id = self.drafts.put(
                Draft(
                    plan,
                    alt_options,
                    limit,
                    "RouteMaker route",
                    ride_key=ride_key_for(first.preset, None),
                )
            )
            roads = (road_list(found) or {}).get("roads") or []
            longest = sorted(roads, key=lambda r: r["miles"], reverse=True)[:5]
            fig = figures(found)
            row = {
                "draft_id": draft_id,
                "rank": found.get("rank"),
                "extra_miles": round(fig["miles"] - main_mi, 2),
                "extra_minutes": round(fig["minutes"] - main_min, 1),
                "figures": fig,
                "main_roads": [r["road"] for r in longest],
            }
            if check is not None:
                row["metro_check_ok"] = check["ok"]
            mtb = mtb_said(found.get("mtb"))
            if mtb:
                # Each route offered says its own trail reading (M4-1).
                row["mtb"] = mtb
            out.append(row)
        first.answer["candidates"] = None
        return out

    def _why(self, call: Call, plan: Plan, options: dict) -> dict | None:
        """`why_this_way` for a plan, against the Fast ride type's route through the same points
        at the same time of day; None where WHY_PRESETS and WHY_MAX_MI leave it out, where the
        call has no time left for one more plan, or where the direct plan fails."""
        if plan.preset not in WHY_PRESETS or options.get("loop") or options.get("follow"):
            return None
        straight = sum(haversine_mi(a, b) for a, b in itertools.pairwise(plan.points))
        if straight > WHY_MAX_MI or not call.time_for_another_plan():
            return None
        direct_options = {"when": options.get("when"), "loop": False}
        try:
            direct = self._plan(call, plan.points, plan.vias, "fast", direct_options, None)
        except ToolError:
            return None
        return why_this_way(plan.answer, direct.answer)

    def _plan(self, call: Call, points, vias, preset, options, limit) -> Plan:
        call.check()
        began = time.monotonic()
        try:
            return plan_once(self.api, self.stations, points, vias, preset, options, limit)
        finally:
            call.timed_plan(time.monotonic() - began)

    def _dials(self, plan: Plan) -> dict:
        answered = plan.answer.get("dials") or {}
        return {
            "stress": answered.get("stress", 70),
            "hills": answered.get("hills", 0),
            **{
                k: answered.get(k)
                for k in (
                    "trails_off",
                    "fewer_turns",
                    "paved",
                    "easy_mtb",
                    "target_distance_m",
                    "loop",
                    "carrying",
                    "assist",
                )
            },
        }

    def _point(self, value, taken: list[dict], neighbours=None) -> tuple[float, float]:
        """as_point, noting what a named point was taken as so the answer can say, and the
        other places the name could have meant."""
        others: list[dict] = []
        nearby: list[dict] = []
        point, label = as_point(value, self.api, self.stations, neighbours, others, nearby)
        if isinstance(value, str):
            row = {"asked": value, "taken_as": label, "at": list(point)}
            if nearby:
                # Other points of the same place (an entrance, a boat launch, a visitor centre):
                # said so the rider can be offered the one they mean (the 2026-11-08 hunt G5).
                row["nearby_matches"] = [
                    {"label": r["label"], "lon_lat": [r["lon"], r["lat"]]} for r in nearby
                ]
            if others:
                row["also_matches"] = [
                    {"label": r["label"], "lon_lat": [r["lon"], r["lat"]]} for r in others[:4]
                ]
                row["why"] = (
                    "the match nearest the route's other points"
                    if neighbours
                    else "the place search's first match"
                )
            taken.append(row)
        return point

    def _points(self, values: list, taken: list[dict]) -> list[tuple[float, float]]:
        """Every point, [lon, lat] and station names first (`find_station`: one said as a
        station; a bare name that may be one is searched like any other), then each place name
        searched near the points already found, those beside it in the list first."""
        found: list = [None] * len(values)
        named = []
        for i, value in enumerate(values):
            if isinstance(value, str) and find_station(value.strip(), self.stations) is None:
                named.append(i)
            else:
                found[i] = self._point(value, taken)
        for i in named:
            found[i] = self._point(values[i], taken, _neighbours(found, i))
        if named and len(named) == len(values) and taken and taken[0].get("also_matches"):
            # Every point a name: the first was taken with nothing to go by, so it is searched
            # again near the others.
            taken.pop(0)
            found[named[0]] = self._point(values[named[0]], taken, _neighbours(found, named[0]))
        # A station said as one was taken above with nothing to go by, at the way in nearest
        # its platform; now every point is known, it goes to the way in nearest the point its
        # leg comes from (`Station.way_in_from`; the second 2026-11-08 hunt, P1).
        for i, value in enumerate(values):
            station = find_station(value.strip(), self.stations) if isinstance(value, str) else None
            if station is None or len(values) < 2:
                continue
            nearer = station.way_in_from(_neighbours(found, i)[0])
            if nearer != found[i]:
                for row in taken:
                    if row["asked"] == value and row["at"] == list(found[i]):
                        row["at"] = list(nearer)
                found[i] = nearer
        return found

    def _draft(
        self,
        plan: Plan,
        options: dict,
        limit,
        notes: list[str],
        name: str,
        revised_from=None,
        taken: list[dict] | None = None,
        trim_spurs: bool = True,
        intervals: dict | None = None,
        ride_key: str | None = None,
    ) -> dict:
        """Keep the plan as a draft and describe it: nothing is saved or written. A Group or Mass
        Ride keeps `ride_key` (a revised draft's, or the opened link's), else gets a new one."""
        draft = Draft(
            plan,
            dict(options),
            limit,
            name,
            trim_spurs,
            intervals,
            ride_key_for(plan.preset, ride_key),
            revises=revised_from,
        )
        draft_id = self.drafts.put(draft)
        dials = self._dials(plan)
        fragment = draft.fragment(dials)
        notes = list(notes)
        # The link opens this exact line in the app, as its Share does, so the map, Start ride
        # and the app's GPX are this route; the plan's inputs ride along for editing.
        link = f"{self.api.base}/{fragment}"
        # What the link does not carry (the second 2026-11-08 hunt, P10): roads avoided are the
        # ride's, as Ride's "Road closed", and a followed line is the request's. The app opens
        # this exact line, but its Update route, a stop moved or another ride type plans again
        # without them, and an avoided road can come back with no word.
        lost = [
            what
            for key, what in (
                ("blocked_lines", "the roads avoided"),
                ("follow", "the line followed"),
                # The app has no control for these (its named options set them for a ride).
                ("fewer_turns", "Fewer turns"),
                ("paved", "All paved"),
            )
            if plan.sent.get(key)
        ]
        try:
            route_id = secrets.token_hex(16)
            self.api.share(
                {"id": route_id, **kept_route(plan, name, fragment, dials), **draft_link_keep()}
            )
            self.drafts.shared(draft_id, route_id)
            link = f"{self.api.base}/s/{route_id}{fragment}&route={route_id}"
        except ToolError as error:
            if lost:
                # The plain link plans without them: not this route at all, and never "this
                # exact route" (the round 4 hunt, L4-6).
                notes.append(
                    f"{error}; the link plans a new route when opened, without"
                    f" {' and '.join(lost)}, so it is not this route: tell the rider (gpx_route"
                    " gives this one's line)"
                )
            else:
                notes.append(
                    f"{error}; the link plans the route again when opened, so it can differ a"
                    " little"
                )
        else:
            if lost:
                notes.append(
                    f"the link opens this exact route, but {' and '.join(lost)} are not in it:"
                    " in the app, Update route, moving a stop or changing the ride type plans"
                    " again without them. Tell the rider before they edit it there."
                )
        out = {
            "draft_id": draft_id,
            "summary": summary(plan.answer),
            **route_details(plan, self.stations, options.get("corking")),
            "points": [list(p) for p in plan.points],
            "via_points": plan.vias,
            "preset": plan.preset,
            "settings_used": {
                **{
                    k: v
                    for k, v in plan.sent.items()
                    if k not in ("points", "confirm_long", "candidates") and v is not None
                },
                "stress": self._dials(plan)["stress"],
                "hills": self._dials(plan)["hills"],
            },
            "link": link,
            "saved": False,
        }
        if (
            plan.preset == "mass-ride"
            and not plan.sent.get("ride_size")
            and out.get("mass_capacity")
        ):
            # The ride size is an expected input (the owner, 2026-11-10: "should be an expected
            # input"; "That's askable, but typically not required"): a Mass Ride planned
            # without it says what it assumed, so the organiser can give theirs if it differs.
            assumed = out["mass_capacity"].get("riders") or 500
            out["mass_capacity"]["ride_size_note"] = (
                f"no ride size was given, so this assumed {assumed}"
                " riders (our default, not the organiser's number); if they expect a"
                " different number, plan again with ride_size, since the road room and the"
                " corkers depend on it"
            )
        if taken:
            # Named points, so a wrong match ("Navy Yard" the base, not the station) shows.
            out["points_taken_as"] = taken
        if revised_from:
            out["revised_from"] = revised_from
        if intervals:
            out["intervals"] = interval_check(plan.answer, intervals, _roads_between(plan.answer))
        if plan.check is not None:
            out["metro_check"] = plan.check
        if notes:
            out["notes"] = notes
        if options.get("route_notes"):
            out["route_notes"] = route_notes_out(plan.answer, options["route_notes"])
        out["credit"] = plan.answer.get("attribution", [])
        # For the route view only: Server.call moves it out of the answer (VIEW_META_KEY).
        view = route_view(plan, out, name, options.get("corking"))
        if self.basemap is not None and self.view_key is not None:
            # The base map tool answers only the view that holds this, which travels in the
            # result's _meta: an assistant without MCP Apps lists the tool, but its model never
            # sees the key, so cannot have pictures drawn into its context.
            view["map_key"] = self.view_key(draft_id)
        if self.picture_link is not None:
            view["picture_link"] = self.picture_link(draft_id)
        out[VIEW_PRIVATE] = view
        return out

    def _plan_and_fix(
        self, call: Call, points, vias, preset, options, limit, rounds, trim_spurs=True, first=None
    ):
        """The plan through the points (or `first`, one already planned through them), with
        Metro fixes and spurs trimmed as asked, and notes on what was done."""
        notes: list[str] = []
        call.report(0, rounds + 1, "planning the route")
        plan = first or self._plan(call, points, vias, preset, options, limit)
        # The options of the plan kept so far: a station put in moves the drawn legs and names.
        current = options
        for done in range(rounds if limit else 0):
            fix = with_metro_fix(plan, self.stations)
            if fix is None:
                if not plan.check["ok"]:
                    # Said, not given up in silence (the round 4 hunt, L4-5).
                    notes.append(
                        "fix_metro_rounds found no station left to add: the stations nearest"
                        " each stretch over the limit are already ends of the leg that strays"
                        f" (or the route has its {MAX_POINTS} points)"
                    )
                break
            if not call.time_for_another_plan():
                notes.append(OUT_OF_TIME)
                break
            new_points, new_vias, station = fix
            call.report(done + 1, rounds + 1, f"replanning by way of {station}")
            at = next(
                (
                    i
                    for i, (a, b) in enumerate(zip(new_points, plan.points, strict=False))
                    if a != b
                ),
                len(plan.points),
            )
            shifted = marks_with_point_at(current, at)
            try:
                again = self._plan(call, new_points, new_vias, preset, shifted, limit)
            except Cancelled:
                raise
            except ToolError as error:
                # The plan already made stands (the round 4 hunt, L4-2: before, the whole call
                # failed and the good first plan was lost).
                notes.append(f"adding {station} as a via point failed ({error}); kept the plan")
                break
            notes.append(
                f"added {station} as a via point: {plan.check['miles_over_limit']} -> "
                f"{again.check['miles_over_limit']} mi over the limit"
            )
            if again.check["miles_over_limit"] <= plan.check["miles_over_limit"]:
                plan = again
                current = shifted
        pruned = without_spurs(plan) if trim_spurs else None
        if pruned is not None and not call.time_for_another_plan():
            # Said, not skipped in silence (the round 4 hunt, L4-4).
            which = [
                str(i)
                for i, (a, b) in enumerate(zip(plan.points, pruned[0], strict=True))
                if a != b
            ]
            notes.append(
                f"no time left to take out the out-and-back to via point"
                f"{'s' if len(which) > 1 else ''} {', '.join(which)} (see"
                " via_spurs): move it to where the spur leaves the road with revise_route"
                " move_points"
            )
            pruned = None
        if pruned is not None:
            # A via point off the road through (a pier's end, a landmark beside a trail) is
            # reached by an out-and-back (the owner, 2026-10-24: "Avoid pointless out and backs
            # and short spurs"): it moves to where the spur leaves the road and is planned again.
            new_points, new_vias, moved = pruned
            call.report(rounds + 1, rounds + 2, "planning again without out-and-backs")
            again = self._plan(call, new_points, new_vias, preset, current, limit)
            if again.answer["distance_m"] < plan.answer["distance_m"] and (
                again.check is None
                or again.check["miles_over_limit"] <= plan.check["miles_over_limit"]
            ):
                which = "; ".join(
                    f"point {i} from {list(a)} to {list(b)}"
                    for i, (a, b) in enumerate(zip(plan.points, new_points, strict=True))
                    if a != b
                )
                notes.append(
                    f"moved {moved} via point{'s' if moved > 1 else ''} the route reached by an"
                    f" out-and-back to where the spur leaves the road ({which};"
                    f" {miles_text(plan.answer['distance_m'] - again.answer['distance_m'])}"
                    " shorter). Plan again with trim_spurs false to keep them where they were."
                )
                plan = again
        return plan, notes

    # gpx_route
    def gpx_route(self, args: dict, call: Call) -> dict:
        draft_id = str(args["draft_id"])
        draft = self.drafts.get(draft_id)
        if draft is None:
            raise ToolError(f"no draft {draft_id} (drafts last only a while; plan it again)")
        name = str(args.get("name") or draft.name).strip()[:120] or draft.name
        miles = round(draft.plan.answer["distance_m"] / METRES_PER_MILE, 1)
        out: dict = {"draft_id": draft_id, "name": name, "distance_mi": miles}
        if self.gpx_link is not None:
            out["gpx_link"] = self.gpx_link(draft_id, name)
            out["note"] = "the link downloads the file; it works while the draft is kept (a week)"
        elif self.files:
            try:
                out["gpx_file"] = str(write_gpx(name, draft.plan.line, self.out_dir))
            except OSError as error:
                raise ToolError(f"GPX not written: {error}") from None
        else:
            raise ToolError("no GPX here: open the link and use Save & load > GPX in the app")
        return out

    # save_route
    def save_route(self, args: dict, call: Call) -> dict:
        draft = self.drafts.get(str(args["draft_id"]))
        if draft is None:
            raise ToolError(
                f"no draft {args['draft_id']} (drafts last only a while; plan it again)"
            )
        name = str(args["name"]).strip()[:120]
        if not name:
            raise ToolError("give the route a name")
        tags = _tags_arg(args.get("tags"))
        fixed = args.get("fixed", False)
        if not isinstance(fixed, bool):
            raise ToolError("fixed: true or false")
        replaces = args.get("replaces")
        if replaces is not None:
            if self.files:
                raise ToolError("replaces is for My routes, on RouteMaker's own connector")
            self._check_organize()
            replaces = int(replaces)
        plan = draft.plan
        out: dict = {"draft_id": args["draft_id"], "name": name}
        notes: list[str] = []
        call.check()
        if self.files:
            # On the rider's own computer: a GPX file. My routes is the site connector's, which
            # signs the rider in.
            try:
                out["gpx_file"] = str(write_gpx(name, plan.line, self.out_dir))
            except OSError as error:
                raise ToolError(f"GPX not written: {error}") from None
            notes.append(
                "to keep it in My routes, open the link and press Save in the app, or use"
                " RouteMaker's own connector (mcp/README.md)"
            )
            if tags:
                notes.append("tags are kept in My routes only: add them there")
            if fixed:
                notes.append(
                    "a GPX file is always its exact line; to keep it as a fixed route in My"
                    " routes, open the link and save it there with Fixed route ticked"
                )
        else:
            dials = self._dials(plan)
            fragment = draft.fragment(dials)
            # My routes keeps the plan, never the ride's key: each ride opened from it is new.
            body = kept_route(plan, name, without_ride_marks(fragment), dials)
            if tags:
                body["tags"] = tags
            if fixed:
                body["fixed"] = True
            if replaces is not None:
                body["replaces"] = replaces
            saved = self.api.save(body)
            out["saved"] = {
                "id": saved.get("id"),
                "name": saved.get("name"),
                "where": "My routes on the site",
            }
            if saved.get("tags"):
                out["saved"]["tags"] = saved["tags"]
            if saved.get("fixed"):
                out["saved"]["fixed"] = True
            if replaces is not None:
                out["saved"]["archived"] = replaces
            if isinstance(saved.get("made_room"), dict):
                notes.append(
                    f'the account was full: "{saved["made_room"].get("name")}", archived'
                    " longest, was deleted to make room; tell the rider"
                )
            if plan.check is not None and not plan.check["ok"]:
                notes.append(
                    f"saved although {plan.check['miles_over_limit']} mi of it is more than"
                    f" {plan.check['limit_mi']:g} mi from Metro"
                )
        if notes:
            out["notes"] = notes
        self.drafts.saved(str(args["draft_id"]))
        return out

    # my_drafts
    def my_drafts(self, args: dict, call: Call) -> dict:
        now = datetime.now(UTC)
        rows = []
        archived = bool(args.get("archived"))
        for found in self.drafts.listing(archived=archived):
            draft: Draft = found["draft"]
            plan = draft.plan
            row = {
                "draft_id": found["draft_id"],
                "name": draft.name,
                "miles": round((plan.answer.get("distance_m") or 0.0) / METRES_PER_MILE, 1),
                "ride_type": plan.preset,
            }
            made = found.get("made")
            if made is not None:
                row["made"] = eastern(made)
                left = DRAFT_KEPT - (now - made)
                # A part day counted whole, as the app's Load route says it: 1 on the last day.
                row["days_left"] = max(0, -int(-left.total_seconds() // 86400))
            if found.get("route_id"):
                row["link"] = self._draft_link(draft, found["route_id"])
            rows.append(row)
        words = str(args.get("search") or "").casefold().split()
        if words:
            rows = [r for r in rows if all(w in str(r["name"]).casefold() for w in words)]
        if archived:
            note = (
                "the drafts archived (archive_draft, or planned with test), newest first: kept out"
                " of the rider's Load route, each still going a week after it was made"
            )
        else:
            note = (
                "the routes planned here and not saved, newest revision of each, newest first;"
                " each goes on its own a week after it was made (our default). Revise one with"
                " revise_route, or keep it with save_route on the rider's word"
            )
        return {"drafts": rows, "note": note}

    # archive_draft
    def archive_draft(self, args: dict, call: Call) -> dict:
        draft_id = str(args["draft_id"])
        archived = args.get("archived", True) is not False
        if not self.drafts.archive(draft_id, archived):
            raise ToolError(f"no draft {draft_id}: drafts go a week after they are made")
        return {"draft_id": draft_id, "archived": archived}

    def _draft_link(self, draft: Draft, route_id: str) -> str:
        """The draft's link, as `_draft` gave it: its exact line and its plan's inputs."""
        fragment = draft.fragment(self._dials(draft.plan))
        return f"{self.api.base}/s/{route_id}{fragment}&route={route_id}"

    # draft_route_post
    def draft_route_post(self, args: dict, call: Call) -> dict:
        if bool(args.get("draft_id")) == bool(args.get("follow")):
            raise ToolError("give the route as draft_id or as follow, one of the two")
        call.check()
        if args.get("draft_id"):
            draft = self.drafts.get(str(args["draft_id"]))
            if draft is None:
                raise ToolError(
                    f"no draft {args['draft_id']} (drafts last only a while; plan it again)"
                )
            plan = draft.plan
            dials = self._dials(plan)
            # The post's own key replaces the draft's (core.route_posts.freeze_route).
            fragment = draft.fragment(dials)
            route = kept_route(plan, draft.name, fragment, dials)
        else:
            follow = args["follow"]
            if not isinstance(follow, dict) or not isinstance(follow.get("polyline"), str):
                raise ToolError("follow: an object with the line as polyline")
            line = decode_polyline(follow["polyline"])
            if len(line) < 2:
                raise ToolError("follow.polyline has fewer than two points")
            preset = str(follow.get("preset") or "default")
            ends = [line[0], line[-1]]
            body = {
                "preset": preset,
                "points": ends,
                "follow": follow["polyline"],
                "follow_exact": bool(follow.get("exact")),
                "candidates": False,
            }
            call.report(0, 1, "planning the line")
            answer = self.api.route(body)
            geometry = (answer.get("geometry") or {}).get("coordinates") or []
            route = {
                "source": "gpx",
                "line": [list(v[:3]) for v in geometry],
                "distance_m": answer.get("distance_m"),
                "inputs": {"points": ends, "preset": preset},
                "answer": {
                    **answer,
                    "candidates": None,
                    "avoid_alternate": None,
                    "closure_through": None,
                },
            }
        fields = {k: args[k] for k in POST_FIELDS if k in args}
        call.check()
        out = self.api.draft_post(fields, route)
        out["notes"] = [
            "a draft: only admins can see the page until it is published in the admin",
        ]
        if out.get("photos_waiting"):
            out["notes"].append(
                "each photo described waits for its file: POST it to its upload_url (image/jpeg,"
                " at most 2048 px a side and 900 KB, Exif kept for where it was taken), or the"
                " admin adds it on the draft's page (For admins, Photos)"
            )
        return out

    # open_link
    def open_link(self, args: dict, call: Call) -> dict:
        link = str(args["link"]).strip()
        url = urllib.parse.urlparse(link)
        fragment = url.fragment
        shared = re.match(r"^/s/([A-Za-z0-9_-]{4,64})/?$", url.path or "")
        shared_id = shared.group(1) if shared else None
        if not shared_id:
            named = urllib.parse.parse_qs(fragment).get("route")
            shared_id = named[0] if named else None
        if not shared_id:
            named = urllib.parse.parse_qs(url.query).get("route")
            shared_id = named[0] if named else None
        has_points = has_plan_points(fragment)
        shared = None
        if shared_id:
            try:
                shared = self.api.shared_route(shared_id)
            except ToolError:
                if not has_points:
                    raise
        if shared is not None and not has_points:
            fragment = (shared.get("inputs") or {}).get("hash") or ""
            if not has_plan_points(fragment):
                raise ToolError(
                    "that shared route keeps no plan to continue from (an opened file?)"
                )
        if not fragment:
            match = re.search(r"(?:^|[#&?])([pq]=.*)$", link)
            fragment = match.group(1) if match else ""
        limit = args.get("max_miles_from_metro")
        answer = (shared or {}).get("answer")
        kept_hash = str(((shared or {}).get("inputs") or {}).get("hash") or "")
        if has_points and plan_params(fragment) != plan_params(kept_hash):
            answer = None  # the rider changed the route in the app: plan what the link says now
        name = str((shared or {}).get("name") or "RouteMaker route")
        return self._open_kept(call, fragment, answer, name, limit)

    def _open_kept(
        self, call: Call, fragment: str, answer, name: str, limit, keep_key: bool = True
    ) -> dict:
        """A draft of a kept route (shared or saved): its exact line where it is kept, else its
        plan planned again. A link's ride keeps its key; one opened from My routes
        (`keep_key` False) is a new ride, with a new key."""
        points, vias, preset, options = parse_fragment(fragment)
        ride_key = ride_key_of(fragment) if keep_key else None
        if isinstance(answer, dict) and (answer.get("geometry") or {}).get("coordinates"):
            # The exact route that was kept: as it is, not planned again.
            line = answer["geometry"]["coordinates"]
            check = metro_check(line, limit, self.stations) if limit else None
            sent = request_body(points, vias, preset, options)
            names = dict(options.get("stop_names") or {})
            plan = Plan(list(points), list(vias), preset, answer, check, sent, names)
            return self._draft(plan, options, limit, [], name, ride_key=ride_key)
        plan, notes = self._plan_and_fix(call, points, vias, preset, options, limit, 0)
        return self._draft(plan, options, limit, notes, name, ride_key=ride_key)

    # my_routes
    def my_routes(self, args: dict, call: Call) -> dict:
        if not self.routes_read:
            raise ToolError(
                "this connection was allowed before RouteMaker's connector could read My routes;"
                " to let it, the rider disconnects it (RouteMaker Settings > Account > AI"
                " assistants) and connects again. Meanwhile, paste the route's link into open_link"
            )
        rows = self.api.saved_routes()
        wanted_id = args.get("route_id")
        wanted_name = str(args.get("name") or "").strip()
        if wanted_id is None and not wanted_name:
            archived = bool(args.get("archived"))
            shown = [r for r in rows if bool(r.get("archived_at")) == archived]
            tag = " ".join(str(args.get("tag") or "").split()).casefold()
            if tag:
                shown = [
                    r for r in shown if tag in {str(x).casefold() for x in r.get("tags") or []}
                ]
            words = str(args.get("search") or "").casefold().split()
            if words:
                shown = [
                    r
                    for r in shown
                    if all(
                        w
                        in " ".join(
                            [str(r.get("name") or ""), *map(str, r.get("tags") or [])]
                        ).casefold()
                        for w in words
                    )
                ]
            out = {
                "routes": [_saved_label(r) for r in shown],
                "note": (
                    "open one as a draft with route_id or name; tag or archive one with"
                    " organize_route on the rider's word; nothing here changes My routes"
                ),
            }
            if not archived:
                out["archived_count"] = sum(1 for r in rows if r.get("archived_at"))
                out["tags_in_use"] = _tags_in_use(r for r in rows if not r.get("archived_at"))
            return out
        if wanted_id is not None:
            match = [r for r in rows if str(r.get("id")) == str(wanted_id)]
        else:
            folded = wanted_name.casefold()
            match = [r for r in rows if str(r.get("name") or "").casefold() == folded]
            if not match:
                match = [r for r in rows if folded in str(r.get("name") or "").casefold()]
        if not match:
            raise ToolError("no saved route by that " + ("id" if wanted_id is not None else "name"))
        if len(match) > 1:
            return {
                "routes": [_saved_label(r) for r in match],
                "note": (
                    "more than one saved route matches: ask the rider which, then give route_id"
                ),
            }
        call.check()
        kept = self.api.saved_route(int(match[0]["id"]))
        fragment = str((kept.get("inputs") or {}).get("hash") or "")
        if not has_plan_points(fragment):
            raise ToolError(
                "that saved route keeps no plan to continue from (an opened file?): open it in"
                " the app instead"
            )
        out = self._open_kept(
            call,
            fragment,
            kept.get("answer"),
            str(kept.get("name") or "RouteMaker route"),
            args.get("max_miles_from_metro"),
            keep_key=False,
        )
        out["opened_from"] = _saved_label(kept)
        if kept.get("fixed"):
            out.setdefault("notes", []).append(
                "a fixed route: this is its exact line as saved, never planned again; a revision"
                " is a new plan, so save it with fixed true only if the rider wants it fixed too"
            )
            if kept.get("closure_alerts"):
                # The owner, 2026-11-10: "Update route can be offered when a closure occurs".
                out["notes"].append(
                    "closures were on this fixed route's line when last checked: offer to plan it"
                    " again around them (revise_route), and to save that over it only on the"
                    " rider's word"
                )
        if parse_fragment(fragment)[2] in RIDE_LINK_TYPES:
            out.setdefault("notes", []).append(
                "a new ride, with its own ride key: links sent for an earlier ride on this route"
                " do not show this one"
            )
        return out

    def _check_organize(self) -> None:
        if not self.routes_read or not self.routes_organize:
            raise ToolError(
                "this connection was allowed before RouteMaker's connector could tag and archive"
                " saved routes; to let it, the rider disconnects it (RouteMaker Settings >"
                " Account > AI assistants) and connects again. Meanwhile, use Load route in the"
                " app"
            )

    # organize_route
    def organize_route(self, args: dict, call: Call) -> dict:
        if self.files:
            raise ToolError(
                "My routes is organized only through RouteMaker's own connector, or in the"
                " app's Load route"
            )
        self._check_organize()
        route_id = int(args["route_id"])
        given = {k for k in ("tags", "add_tags", "remove_tags", "archived") if k in args}
        if not given:
            raise ToolError("say what to change: tags, add_tags, remove_tags or archived")
        if "tags" in args and ({"add_tags", "remove_tags"} & given):
            raise ToolError("give tags (all of them) or add_tags/remove_tags, not both")
        change: dict = {}
        if "archived" in args:
            if not isinstance(args["archived"], bool):
                raise ToolError("archived is true or false")
            change["archived"] = args["archived"]
        if "tags" in args:
            change["tags"] = _tags_arg(args["tags"])
        elif {"add_tags", "remove_tags"} & given:
            rows = self.api.saved_routes()
            row = next((r for r in rows if str(r.get("id")) == str(route_id)), None)
            if row is None:
                raise ToolError("no saved route by that id")
            gone = {x.casefold() for x in _tags_arg(args.get("remove_tags"))}
            tags = [x for x in row.get("tags") or [] if x.casefold() not in gone]
            have = {x.casefold() for x in tags}
            for x in _tags_arg(args.get("add_tags")):
                if x.casefold() not in have:
                    tags.append(x)
                    have.add(x.casefold())
            change["tags"] = tags
        call.check()
        now = self.api.change_route(route_id, change)
        out = {"route": _saved_label(now)}
        if change.get("archived"):
            out["note"] = (
                "archived: left out of Load route (Archived lists it, with Restore); when the"
                " account is full, the longest archived goes first"
            )
        return out

    # route_segments
    def route_segments(self, args: dict, call: Call) -> dict:
        draft = self._kept_draft(args)
        start = max(0.0, finite(args.get("from_mi") or 0))
        end = finite(args["to_mi"]) if args.get("to_mi") is not None else None
        if end is not None and end <= start:
            raise ToolError("to_mi is past from_mi")
        rows = int(args.get("max_rows") or SEGMENT_ROWS)
        rows = max(5, min(MAX_SEGMENT_ROWS, rows))
        out = {"draft_id": str(args["draft_id"]), **route_segments(draft.plan, start, end, rows)}
        if later_rides(draft.plan.answer):
            # The rows are the first ride's alone (routing hunt 4, X4-2).
            out["covers"] = LATER_RIDES_NOTE
        return out

    # ride_conditions
    def ride_conditions(self, args: dict, call: Call) -> dict:
        from datetime import datetime

        draft = self._kept_draft(args)
        plan = draft.plan
        now = datetime.now(UTC)
        depart = parse_depart(args.get("depart_at"), now)
        ride_s = plan.answer.get("duration_s") or 0.0
        finish = depart + timedelta(seconds=ride_s)
        line = plan.line
        out: dict = {
            "draft_id": str(args["draft_id"]),
            "depart": eastern(depart),
            "arrive": eastern(finish),
            "start": light_at(depart, line[0][0], line[0][1]),
            "finish": light_at(finish, line[-1][0], line[-1][1]),
            "times": "America/New_York",
        }
        dark = [k for k in ("start", "finish") if out[k]["light"] == "dark"]
        if dark:
            out["lights_needed"] = (
                "dark at the " + " and the ".join(dark) + ": front and rear lights"
            )
        ahead = (depart - now).total_seconds()
        if ahead < -ride_s:
            out["weather"] = {"checked": False, "why": "the ride's time has passed"}
        elif ahead + ride_s > WEATHER_AHEAD_S:
            out["weather"] = {
                "checked": False,
                "why": "forecasts reach 48 hours ahead; ask again nearer the day",
            }
        else:
            call.check()
            asked = weather_points(plan, max(0.0, ahead))
            try:
                found = self.api.weather_check(asked)
            except ToolError as error:
                out["weather"] = {"checked": False, "why": str(error)}
            else:
                rain = found.get("rain")
                if isinstance(rain, dict) and isinstance(rain.get("index"), int):
                    route_mi = (plan.answer.get("distance_m") or 0.0) / METRES_PER_MILE
                    rain = {
                        "at_mi": round(route_mi * rain["index"] / max(1, len(asked) - 1), 1),
                        "starts": eastern(now + timedelta(seconds=rain.get("starts_in_s") or 0)),
                        "inches_in_15_min": rain.get("inches"),
                        "heavy": bool(rain.get("heavy")),
                    }
                keys = ("event", "severity", "onset", "ends", "area", "instruction", "url")
                out["weather"] = {
                    "checked": True,
                    "alerts": [
                        {k: a.get(k) for k in keys if a.get(k)} for a in found.get("alerts") or []
                    ],
                    "first_rain": rain,
                    "unchecked": found.get("unchecked") or [],
                    "source": "National Weather Service alerts; Open-Meteo (NOAA HRRR) rain",
                }
        return out

    def _kept_draft(self, args: dict) -> Draft:
        draft_id = str(args["draft_id"])
        draft = self.drafts.get(draft_id)
        if draft is None:
            raise ToolError(f"no draft {draft_id} (drafts last only a while; plan it again)")
        return draft

    # revise_route
    def revise_route(self, args: dict, call: Call) -> dict:
        draft_id = str(args["draft_id"])
        draft = self.drafts.get(draft_id)
        if draft is None:
            raise ToolError(f"no draft {draft_id} (drafts last only a while; plan it again)")
        plan = draft.plan
        points = list(plan.points)
        vias = set(plan.vias)
        taken: list[dict] = []
        if args.get("points"):
            points = self._points(list(args["points"]), taken)
            vias = set()
        # Moves, additions and removals all name points by their place in the draft (or in
        # `points` when given): each point keeps its first index until the new list is built.
        rows = [[i, point, i in vias] for i, point in enumerate(points)]  # index, point, via
        count = len(rows)
        for move in args.get("move_points") or []:
            index = int(move["index"])
            if not 0 <= index < count:
                raise ToolError(f"no point {index} to move")
            rows[index][1] = self._point(move["to"], taken, _neighbours(points, index))
        removed = {int(i) for i in args.get("remove_points") or []}
        for index in removed:
            if not 0 <= index < count:
                raise ToolError(f"no point {index} to remove")
        added: dict[int, list] = {}
        for add in args.get("add_points") or []:
            after = int(add["after"])
            if not 0 <= after < count:
                raise ToolError(f"no point {after} to add after")
            point = self._point(add["point"], taken, [points[after], *_neighbours(points, after)])
            added.setdefault(after, []).append([None, point, add.get("via", True)])
        built = []
        for row in rows:
            if row[0] not in removed:
                built.append(row)
            built.extend(added.get(row[0], []))
        reshaped = bool(args.get("points") or args.get("move_points") or removed or added)
        drawn, names = marks_revised(plan, built, bool(args.get("points")))
        points = [row[1] for row in built]
        vias = {i for i, row in enumerate(built) if row[2]}
        if args.get("via_points") is not None:
            vias = {int(i) for i in args["via_points"]}
        # A via point is never the first or the last.
        vias = sorted(i for i in vias if 0 < i < len(points) - 1)
        preset = args.get("preset") or plan.preset
        options = dict(draft.options)
        if preset != plan.preset:
            # A new ride type starts from its own settings, as in the app; keep the shape of the
            # ride (a loop, the ride time) and what this call sets.
            # The followed line, the roads to avoid and the rider's pace are the rider's, not
            # the ride type's: they stay too.
            # Keep to roads stays too, and Easy MTB trails between the ride types that offer
            # it, as the app's rideTypeDialog.choose keeps trailsOff and easyMtb.
            kept = (
                "loop",
                "when",
                # The route's notes are the rider's, whatever the ride type.
                "route_notes",
                "follow",
                "follow_exact",
                "follow_alternative",
                "blocked_lines",
                "trails_off",
                # The rider's choices, as Keep to roads.
                "fewer_turns",
                "paved",
            )
            if preset != "run":
                # A riding speed is no running pace: the run starts at Run's own.
                kept = (*kept, "cycling_speed_kmh")
            if preset in EASY_MTB_PRESETS:
                kept = (*kept, "easy_mtb")
            options = {k: v for k, v in options.items() if k in kept}
        # The legs drawn in the app and the stops' names are the rider's: they stay, on the
        # revised points, whatever the ride type.
        options["straight_legs"] = drawn
        options["stop_names"] = names
        # And their icons (2026-11-10): kept likewise, then as this call sets them.
        kept_icons = draft.options.get("stop_icons")
        icons = None if args.get("points") else labels_revised(plan, built, kept_icons)
        for at, icon in (args.get("stop_icons") or {}).items():
            index = int(at) if str(at).isdigit() else -1
            loop = args.get("loop", options.get("loop"))
            if not 0 < index < len(points) - (0 if loop else 1) or index in vias:
                raise ToolError(f"point {at} is not a stop of the revised route, so it has no icon")
            if icon is not None and icon not in NOTE_ICONS:
                raise ToolError(f"no icon {icon!r}: one of {', '.join(NOTE_ICONS)}")
            icons = {k: v for k, v in (icons or {}).items() if k != index}
            if icon:
                icons[index] = icon
        options["stop_icons"] = icons or None
        asked = self._options(args, preset)
        options.update({k: v for k, v in asked.items() if k in args})
        if "target_miles" in args:
            options["target_distance_m"] = asked.get("target_distance_m")
        if "rider_weight_lb" in args:
            options["system_weight_kg"] = asked.get("system_weight_kg")
        if args.get("pace_mph"):
            options.pop("cycling_speed_kmh", None)
            options.pop("run_pace_kmh", None)
            field, kmh = pace_option(args["pace_mph"], preset)
            options[field] = kmh
        limit = args.get("max_miles_from_metro", draft.limit)
        early_notes: list[str] = []
        if reshaped and options.get("follow"):
            # A followed line has only its two ends: new points plan through them instead.
            options.pop("follow", None)
            options.pop("follow_exact", None)
            options.pop("follow_alternative", None)
            early_notes.append("planned through its points now, no longer along the followed line")
        if args.get("avoid") and options.get("follow"):
            # A followed line is ridden as it is: the site's map matching never sees roads to
            # avoid, so the answer said a road was left out while the route still rode it (the
            # round 4 hunt, L4-1).
            if not options.get("follow_alternative"):
                raise ToolError(
                    "this draft follows the rider's own line, which is ridden as it is: a road"
                    " on it cannot be avoided. Draw the line round the road, or plan through"
                    " points (revise_route points) and avoid it there"
                )
            # An alternative's line is only the site's other route: plan through its points
            # round what is avoided.
            options.pop("follow", None)
            options.pop("follow_exact", None)
            options.pop("follow_alternative", None)
            early_notes.append(
                "planned through its points now, no longer along the alternative's line, so the"
                " route can go round what is avoided"
            )
        if args.get("avoid"):
            lines, avoided = avoid_lines(plan, args["avoid"])
            kept = [*(options.get("blocked_lines") or []), *lines]
            if len(kept) > MAX_AVOID:
                early_notes.append(
                    f"the site takes {MAX_AVOID} roads to avoid at most: the earliest were let go"
                )
            options["blocked_lines"] = kept[-MAX_AVOID:]
            early_notes.append(
                "left out of the plan (not ridden along or across): " + "; ".join(avoided)
            )
        for key in args.get("clear_settings") or []:
            if key == "max_miles_from_metro":
                limit = None
            elif key == "pace_mph":
                options.pop("cycling_speed_kmh", None)
                options.pop("run_pace_kmh", None)
            elif key == "avoid":
                options.pop("blocked_lines", None)
            else:
                options.pop(key, None)
        intervals = draft.intervals
        if "intervals" in args:
            intervals = _intervals_asked(args.get("intervals"))
        options.pop("debug_junctions", None)
        if intervals:
            options["debug_junctions"] = True
        rounds = int(args.get("fix_metro_rounds") or 0)
        trim = bool(args.get("trim_spurs", draft.trim_spurs))
        first = alternatives = None
        if args.get("alternatives"):
            first = self._plan(call, points, vias, preset, {**options, "candidates": True}, limit)
            alternatives = self._alternatives(first, options, limit)
        revised, notes = self._plan_and_fix(
            call, points, vias, preset, options, limit, rounds, trim, first=first
        )
        out = self._draft(
            revised,
            options,
            limit,
            notes,
            _draft_name(args.get("name"), [], draft.name),
            revised_from=draft_id,
            taken=taken,
            trim_spurs=trim,
            intervals=intervals,
            # Mass Ride and Group Ride are different rides: a change between them is a new key.
            ride_key=draft.ride_key if preset == plan.preset else None,
        )
        if early_notes:
            out["notes"] = [*early_notes, *out.get("notes", [])]
        # Whether the change helped, figure by figure (the owner, 2026-10-24: "Revise until
        # improvements are minimal").
        out["changed_from_previous"] = figures_change(figures(plan.answer), figures(revised.answer))
        if alternatives is not None:
            out["alternatives"] = self._alternatives_said(alternatives, revised is not first)
        return out

    # plan_route
    def plan_route(self, args: dict, call: Call) -> dict:
        taken: list[dict] = []
        options = self._options(args)
        follow = args.get("follow")
        if follow is not None:
            if args.get("points") or args.get("best_order") or args.get("loop"):
                raise ToolError(
                    "follow plans along its own line: leave points, loop and best_order out"
                )
            if not isinstance(follow, dict) or not isinstance(follow.get("polyline"), str):
                raise ToolError("follow: an object with the line as polyline")
            line = decode_polyline(follow["polyline"])
            if len(line) < 2:
                raise ToolError("follow.polyline has fewer than two points")
            points = [tuple(line[0]), tuple(line[-1])]
            options["follow"] = follow["polyline"]
            options["follow_exact"] = bool(follow.get("exact"))
        else:
            if not args.get("points"):
                raise ToolError("missing argument 'points'")
            points = self._points(list(args["points"]), taken)
        vias = [int(i) for i in args.get("via_points") or []]
        preset = args.get("preset") or "default"
        limit = args.get("max_miles_from_metro")
        avoided: list[str] = []
        if args.get("avoid"):
            if follow is not None:
                # The followed line is ridden as it is: the site's map matching never sees
                # roads to avoid (the round 4 hunt, L4-1).
                raise ToolError(
                    "follow rides its own line as it is, so it cannot avoid a road on it: draw"
                    " the line round the road, or give points instead of follow"
                )
            lines, avoided = avoid_lines(None, args["avoid"])
            options["blocked_lines"] = lines[-MAX_AVOID:]
        intervals = _intervals_asked(args.get("intervals"))
        if intervals:
            # Every junction, quiet stop signs too, for where an effort must stop.
            options["debug_junctions"] = True
        rounds = int(args.get("fix_metro_rounds") or 0)
        trim = bool(args.get("trim_spurs", True))
        ordered = first = None
        alternatives = None
        if args.get("best_order"):
            first, ordered = self._best_order(call, points, vias, preset, options, limit, taken)
            points = first.points
        elif args.get("alternatives"):
            first = self._plan(call, points, vias, preset, {**options, "candidates": True}, limit)
            alternatives = self._alternatives(first, options, limit)
        plan, notes = self._plan_and_fix(
            call, points, vias, preset, options, limit, rounds, trim, first=first
        )
        if avoided:
            notes.append("left out of the plan (not ridden along or across): " + "; ".join(avoided))
        if ordered:
            notes.insert(0, ordered["note"])
            # Numbered as the draft's points are, after any Metro station put in: each row the
            # first point at its place not yet taken, so a start given again as the finish is
            # stop 0 first and the last stop after (the round 4 hunt, L4-7).
            used: set[int] = set()
            for row in ordered["order"]:
                k = next(
                    (
                        k
                        for k, p in enumerate(plan.points)
                        if k not in used and tuple(p) == tuple(row["lon_lat"])
                    ),
                    None,
                )
                if k is not None:
                    used.add(k)
                    row["stop"] = k
        out = self._draft(
            plan,
            options,
            limit,
            notes,
            _draft_name(args.get("name"), args.get("points") or []),
            taken=taken,
            trim_spurs=trim,
            intervals=intervals,
        )
        if ordered:
            out["checkpoint_order"] = ordered["order"]
        if alternatives is not None:
            out["alternatives"] = self._alternatives_said(alternatives, plan is not first)
        why = self._why(call, plan, options)
        if why is not None:
            out["why"] = why
        return out

    @staticmethod
    def _alternatives_said(alternatives: list[dict], replanned: bool) -> dict:
        out: dict = {"routes": alternatives}
        if not alternatives:
            out["note"] = "the site found no other route that rides differently at another stress"
        elif replanned:
            out["note"] = (
                "extra miles and minutes are against the first plan; this draft was planned"
                " again after it (see notes)"
            )
        return out

    def _best_order(self, call: Call, points, vias, preset, options, limit, taken):
        """The plan through the points with the checkpoints between the first and last in
        their quickest order (`best_orders`, up to ORDER_TRIES planned while time allows; a
        try that fails after the first is passed over), and what was done."""
        if vias:
            raise ToolError("best_order puts the stops in order: leave via_points out")
        if options.get("loop"):
            raise ToolError(
                "best_order keeps the start and the finish: for a ride back to the start,"
                " give the start again as the last point, without loop"
            )
        if preset in TWO_POINT_PRESETS:
            raise ToolError(f"{preset} plans from a start and an end only")
        orders = best_orders(points)
        tried: list[tuple[float, Plan, list[int]]] = []
        failed = 0
        took = 0.0
        for k, order in enumerate(orders):
            if tried and call.deadline is not None:
                # Another try only while one more as long as the last still fits.
                if time.monotonic() + 1.5 * took + 5 > call.deadline:
                    break
            call.check()
            call.report(k, len(orders), f"trying checkpoint order {k + 1} of {len(orders)}")
            began = time.monotonic()
            try:
                plan = self._plan(call, [points[i] for i in order], [], preset, options, limit)
            except Cancelled:
                raise
            except ToolError:
                if not tried:
                    raise
                failed += 1
                break
            took = time.monotonic() - began
            tried.append((plan.answer.get("duration_s") or math.inf, plan, order))
        _, plan, order = min(tried, key=lambda row: row[0])
        asked: dict[tuple, list[str]] = {}
        for t in taken:
            if t.get("at"):
                asked.setdefault(tuple(t["at"]), []).append(t["asked"])
        named = []
        for k, i in enumerate(order):
            row = {"stop": k, "point_given": i, "lon_lat": list(points[i])}
            if tuple(points[i]) in asked:
                row["asked"] = " / ".join(asked[tuple(points[i])])
            named.append(row)
        minutes = [round(t / 60) for t, _, _ in tried if t != math.inf]
        count = f"{len(tried)} order{'s' if len(tried) > 1 else ''}"
        note = f"checkpoints put in order: {count} planned"
        if minutes:
            note += f" ({', '.join(f'{m} min' for m in minutes)}), the quickest kept"
        if len(tried) < len(orders):
            note += "; " + ("a later try failed" if failed else "no time to try more")
        return plan, {"order": named, "note": note}

    # plan_metro_loop
    def plan_metro_loop(self, args: dict, call: Call) -> dict:
        target = finite(args["target_miles"])
        limit = finite(args.get("max_miles_from_metro") or 5)
        taken: list[dict] = []
        centre = self._point(args["centre"], taken) if args.get("centre") is not None else DC_CENTRE
        start = self._point(args["start"], taken) if args.get("start") is not None else None
        preset = args.get("preset") or "default"
        if preset in TWO_POINT_PRESETS or preset == "mass-ride":
            raise ToolError(f"{preset} does not plan loops")
        max_plans = int(args.get("max_plans") or 4)
        options = {**self._options(args), "loop": True}
        # target_miles is the loop's length here, not the calm search's soft target.
        options.pop("target_distance_m", None)
        if options["stress"] is None and preset == "default":
            # "Low stress" on everyday riding: low-stress ways unless much longer. Every other
            # ride type keeps its own start, which the assistant can override.
            options["stress"] = 80
        radius = target / (2 * math.pi * road_factor(options["stress"]))
        rescaled = False
        notes: list[str] = []
        best: Plan | None = None

        def ring_points(radius):
            """The loop's points, the ring shrunk to stay inside what the site will plan."""
            for _ in range(8):
                points, vias = loop_points_from(
                    start, ring_waypoints(centre, radius, limit, self.stations), centre
                )
                span = sum(haversine_mi(a, b) for a, b in zip(points, points[1:], strict=False))
                if span <= LOOP_SPAN_MI:
                    return points, vias, radius
                radius *= 0.98 * LOOP_SPAN_MI / span
            return points, vias, radius

        points, vias, fitted = ring_points(radius)
        if fitted < radius:
            notes.append(
                f"the site plans at most {MAX_SPAN_MI} mi of straight lines between points, so"
                f" the ring was kept to {fitted:.1f} mi out"
            )
        radius = fitted
        timed_out = False
        for attempt in range(max_plans):
            if best is not None and not call.time_for_another_plan():
                notes.append(OUT_OF_TIME)
                timed_out = True
                break
            call.report(attempt, max_plans, f"planning loop {attempt + 1} ({len(points)} points)")
            try:
                plan = self._plan(call, points, vias, preset, options, limit)
            except Cancelled:
                raise
            except ToolError as error:
                if best is None:
                    raise
                notes.append(f"plan {attempt + 1} failed: {error}")
                break
            miles = plan.answer["distance_m"] / METRES_PER_MILE
            notes.append(
                f"plan {attempt + 1}: {miles:.1f} mi, {plan.check['miles_over_limit']} mi over the"
                f" Metro limit, ring {radius:.1f} mi out"
            )
            if best is None or _better(plan, best, target):
                best = plan
            off = miles / target
            if not rescaled and not 0.88 <= off <= 1.12:
                rescaled = True
                points, vias, radius = ring_points(max(1.5, radius / off))
                continue
            pruned = without_spurs(plan)
            if pruned is not None:
                points, vias, moved = pruned
                notes.append(
                    f"moving {moved} waypoint{'s' if moved > 1 else ''} the loop reached by an"
                    " out-and-back to where the spur left the loop"
                )
                continue
            fix = with_metro_fix(plan, self.stations)
            if fix is None:
                if not plan.check["ok"]:
                    # Said, not given up in silence (the round 4 hunt, L4-5).
                    notes.append(
                        "fix_metro_rounds found no station left to add: the stations nearest"
                        " each stretch over the limit are already ends of the leg that strays"
                        f" (or the route has its {MAX_POINTS} points)"
                    )
                break
            points, vias, station = fix
            notes.append(f"adding {station} where the loop strayed")
        miles = best.answer["distance_m"] / METRES_PER_MILE
        if not 0.85 <= miles / target <= 1.15:
            if timed_out:
                # Not tried, so not a limit of the ring: say what is left to do.
                notes.append(
                    f"the loop is {miles:.0f} mi against a target of {target:.0f}: there was no"
                    " time to plan it again closer; move its farthest points in with"
                    " revise_route, or plan a ring of via points on trails with plan_route"
                )
            else:
                notes.append(
                    f"the loop is {miles:.0f} mi against a target of {target:.0f}: within"
                    f" {limit:g} mi of Metro, the ring could not be made closer"
                )
        if start is None:
            begin = tuple(best.points[0])
            near = min(self.stations, key=lambda s: haversine_mi(begin, s.point))
            notes.insert(
                0,
                f"no start was given, so the loop starts and ends on the ring near {near.name}"
                f" Metro ({haversine_mi(begin, near.point):.1f} mi from it); pass start to begin"
                " somewhere else",
            )
        name = _draft_name(args.get("name"), [], f"{target:.0f} mi Metro loop")
        return self._draft(best, options, limit, notes, name, taken=taken)

    def _reach_dials(self, args: dict, preset: str) -> dict:
        """The ride options a reach or compare_places call sends, as the site's fields."""
        body: dict = {}
        for key in ("stress", "hills", "when", "carrying", "assist", "trails_off"):
            if args.get(key) is not None:
                body[key] = args[key]
        if args.get("pace_mph") and preset != "walk":
            field, kmh = pace_option(args["pace_mph"], preset)
            body[field] = kmh
        return body

    def _reach_link(
        self,
        points,
        preset: str,
        body: dict,
        direction: str,
        combine: str,
        calm: bool,
        minutes: list[int] | None = None,
    ):
        parts = [
            "p=" + ";".join(f"{lon:.5f},{lat:.5f}" for lon, lat in points),
            f"preset={preset}",
            "v=2",
        ]
        for key, field in (
            ("stress", "stress"),
            ("hills", "hills"),
            ("when", "when"),
            ("carrying", "carrying"),
        ):
            if body.get(key) is not None:
                parts.append(f"{field}={body[key]}")
        if body.get("assist") and preset == "bikeshare":
            # The app's Bikeshare takes the share e-bike as its bike choice, not an assist box.
            parts.append("bike=ebike")
        elif body.get("assist"):
            parts.append("assist=1")
        if body.get("trails_off"):
            parts.append("trailsoff=1")
        # Only some of the app's rings (15, 30, 45, 60) named: the link opens with just those.
        shown = [str(m) for m in (minutes or []) if m in (15, 30, 45, 60)]
        if len(shown) == 4:
            shown = []
        parts.append("reach=" + ".".join([direction, combine, *(["calm"] if calm else []), *shown]))
        return f"{self.api.base}/#" + "&".join(parts)

    def reach(self, args: dict, call: Call) -> dict:
        call.check()
        preset = str(args.get("preset") or "default")
        if preset not in PRESETS:
            raise ToolError(f"no ride type {preset!r}")
        if preset in REACH_NOT_YET:
            raise ToolError(
                "the transit ride types have no reach rings yet: pick a bike ride type, walk or run"
            )
        values = args.get("points") or []
        if not 1 <= len(values) <= REACH_MAX_POINTS:
            raise ToolError(f"points: 1 to {REACH_MAX_POINTS}")
        taken: list[dict] = []
        points = self._points(list(values), taken)
        direction = "to" if args.get("direction") == "to" else "from"
        combine = str(args.get("combine") or "any")
        if combine not in ("any", "all", "each"):
            raise ToolError("combine is any, all or each")
        calm = args.get("calm") is not False
        minutes = args.get("minutes") or [15, 30, 45, 60]
        try:
            minutes = sorted({int(m) for m in minutes})
        except (TypeError, ValueError):
            raise ToolError("minutes are whole numbers, 5 to 60") from None
        dials = self._reach_dials(args, preset)
        body = {
            "points": [list(p) for p in points],
            "preset": preset,
            "minutes": minutes,
            "direction": direction,
            "combine": combine,
            "calm": calm,
            **dials,
        }
        answer = self.api.reach(body)

        def rings(groups: list[dict]) -> list[dict]:
            out = []
            for group in groups:
                row = {
                    "rings": [
                        {
                            "minutes": r["minutes"],
                            "area_sq_mi": r["area_sq_mi"],
                            "area_km2": r["area_km2"],
                            "places": r["places"],
                        }
                        for r in group["rings"]
                    ],
                    "metro_stations": group.get("metro_stations", []),
                }
                if group.get("point") is not None:
                    row["point"] = group["point"]
                out.append(row)
            return out

        out: dict = {
            "ride_type": answer.get("preset", preset),
            "direction": direction,
            "stress_used": answer.get("stress_used"),
            "groups": rings(answer.get("groups") or []),
            "link": self._reach_link(points, preset, dials, direction, combine, calm, minutes),
        }
        # The app draws only 15, 30, 45 and 60: say which of them the link opens when the rings
        # asked for differ, so the link does not quietly disagree with the answer.
        app_rings = [m for m in minutes if m in (15, 30, 45, 60)] or [15, 30, 45, 60]
        if app_rings != minutes:
            out["link_rings"] = app_rings
        if len(points) > 1:
            # Only where there is something to combine: one point's answer leaves the key out.
            out["combine"] = combine
        if answer.get("calm"):
            out["calm"] = {
                "stress": answer["calm"]["stress"],
                "groups": rings(answer["calm"]["groups"]),
            }
        if answer.get("unplaced"):
            out["unplaced_points"] = answer["unplaced"]
        if answer.get("trail_level_applied") is False:
            out["trail_level"] = (
                "the rings take mountain-bike trails of every level; a planned ride keeps to the"
                " rider's level"
            )
        if taken:
            out["points_taken_as"] = taken
        return out

    def compare_places(self, args: dict, call: Call) -> dict:
        preset = str(args.get("preset") or "default")
        if preset not in PRESETS:
            raise ToolError(f"no ride type {preset!r}")
        if preset in REACH_NOT_YET or preset in REACH_ON_FOOT:
            raise ToolError("compare_places is for the bike ride types")
        if preset in ("bikeshare", "rebalance"):
            preset = "default"
        places = args.get("places") or []
        dests = args.get("destinations") or []
        if not 2 <= len(places) <= 6 or not 1 <= len(dests) <= 3:
            raise ToolError("places: 2 to 6; destinations: 1 to 3")
        # The places are alternatives, not one route's points: each is taken by the
        # destinations (a station at its way in nearest the first, a name searched near them),
        # not by the other candidates, which can be across a freeway or a county away (the
        # third 2026-11-08 hunt, PL3-8).
        taken: list[dict] = []
        ends = self._points([d.get("place") if isinstance(d, dict) else d for d in dests], taken)
        start_taken: list[dict] = []
        starts = [self._point(p, start_taken, ends) for p in places]
        taken = start_taken + taken
        limits = [
            finite(d["max_minutes"]) if isinstance(d, dict) and d.get("max_minutes") else None
            for d in dests
        ]
        dials = self._reach_dials(args, preset)
        # No calm figure where it says nothing: Mass Ride's slider is locked, and a ride type
        # set at or past Low-stress (its start or the rider's stress) is its own calm.
        offered = calm_offered(preset, dials)
        rows = []
        not_compared = []
        for i, start in enumerate(starts):
            call.check()
            if call.deadline is not None and time.monotonic() + COMPARE_PLACE_S > call.deadline:
                not_compared = places[i:]
                break
            body = {"points": [list(start), *[list(e) for e in ends]], "preset": preset, **dials}
            own = self.api.nearest(body)
            calm_body = {**body, "stress": CALM_STRESS}
            calm = self.api.nearest(calm_body) if offered else None
            trips = []
            for j in range(len(ends)):
                got = (own.get("places") or [{}] * len(ends))[j]
                seconds = got.get("time_s")
                metres = got.get("distance_m")
                minutes = None if seconds is None else round(seconds / 60, 1)
                trip = {
                    "to": dests[j].get("place") if isinstance(dests[j], dict) else dests[j],
                    "minutes": minutes,
                    "miles": None if metres is None else round(metres / METRES_PER_MILE, 2),
                    "by": own.get("by"),
                }
                if calm is not None:
                    calm_s = (calm.get("places") or [{}] * len(ends))[j].get("time_s")
                    trip["calm_minutes"] = None if calm_s is None else round(calm_s / 60, 1)
                if limits[j] is not None:
                    trip["max_minutes"] = limits[j]
                    trip["within_limit"] = minutes is not None and minutes <= limits[j]
                trips.append(trip)
            met = sum(1 for t in trips if t.get("within_limit"))
            unreachable = sum(1 for t in trips if t["minutes"] is None)
            total = sum(t["minutes"] for t in trips if t["minutes"] is not None)
            rows.append(
                {
                    "place": places[i],
                    "at": list(start),
                    "trips": trips,
                    "limits_met": met,
                    "total_minutes": round(total, 1),
                    "unreachable": unreachable,
                    "reach_link": self._reach_link([start], preset, dials, "from", "any", offered),
                }
            )
        # A place with a trip the router could not make ranks below every place it could: its
        # total leaves that trip out and would otherwise look short.
        rows.sort(key=lambda r: (-r["limits_met"], r["unreachable"], r["total_minutes"]))
        out: dict = {"ride_type": preset, "places": rows}
        if not_compared:
            out["not_compared"] = not_compared
            out["notes"] = [
                f"ran out of time after {len(rows)} of {len(places)} places: the rest"
                " (not_compared) were not measured; ask again with just those"
            ]
        if taken:
            out["points_taken_as"] = taken
        return out

    def handler(self, name: str):
        if name in POST_TOOLS and not self.posts:
            return None
        if name == "route_view_map" and (self.basemap is None or self.view_key is None):
            return None
        if name == "route_picture" and self.picture is None:
            return None
        if name == "cue_cards" and self.cue_cards is None:
            return None
        return {
            "route_picture": self.route_picture,
            "cue_cards": self.cue_cards_tool,
            "route_view_map": self.route_view_map,
            "find_place": self.find_place,
            "metro_stations": self.metro_stations,
            "scenic_roads_near": self.scenic_roads_near,
            "climbs_near": self.climbs_near,
            "closures_near": self.closures_near,
            "plan_route": self.plan_route,
            "plan_metro_loop": self.plan_metro_loop,
            "open_link": self.open_link,
            "revise_route": self.revise_route,
            "route_notes": self.route_notes,
            "save_route": self.save_route,
            "gpx_route": self.gpx_route,
            "draft_route_post": self.draft_route_post,
            "route_segments": self.route_segments,
            "ride_conditions": self.ride_conditions,
            "my_routes": self.my_routes,
            "my_drafts": self.my_drafts,
            "archive_draft": self.archive_draft,
            "organize_route": self.organize_route,
            "reach": self.reach,
            "compare_places": self.compare_places,
        }.get(name)

    def call(self, name: str, args: dict, call: Call | None = None) -> dict:
        handler = self.handler(name)
        if handler is None:
            raise ToolError(f"no tool named {name}")
        call = call or Call()
        # A test call's drafts are archived as they are made (TEST_CALL).
        testing = TEST_CALL.set(name in TEST_TOOLS and bool((args or {}).get("test")))
        current = CURRENT_CALL.set(call)
        try:
            out = handler(args or {}, call)
        except KeyError as missing:
            raise ToolError(f"missing argument {missing}") from None
        except (TypeError, ValueError, OverflowError) as wrong:
            raise ToolError(f"an argument is not in the expected form: {wrong}") from None
        finally:
            CURRENT_CALL.reset(current)
            TEST_CALL.reset(testing)
        if isinstance(out, dict):
            view = out.pop(VIEW_PRIVATE, None)
            if view is not None and name in VIEW_TOOLS:
                call.meta[VIEW_META_KEY] = view
            for image in out.pop(IMAGES_PRIVATE, None) or []:
                call.images.append(image)
        return out


def _better(plan: Plan, best: Plan, target: float) -> bool:
    """Fewer miles over the Metro limit first, then no out-and-back spurs, then nearer the
    target length."""

    def key(p: Plan):
        miles = p.answer["distance_m"] / METRES_PER_MILE
        return (p.check["miles_over_limit"], without_spurs(p) is not None, abs(miles - target))

    return key(plan) < key(best)


# --- Prompts: ready-made asks a person can pick ------------------------------------------------

# The backlog's connector item 3 (the owner's "do 9", 2026-11-13): a few starters an assistant app
# lists for the person to pick, each turned into one ask that names the tools and settings that
# fit, so the answer does not hang on the model finding them in the tool list. Kept few
# (Stephen, 2026-11-12: "simplicity is often more useful"); each answer is asked to stay short.
# Their numbers are our defaults, unmeasured: stress 80 for a commute and a loop (the tools'
# own "low stress"), a loop within 10% of its length, its via points about a quarter of the
# length out (a ring of radius r is about 2 pi r = 6.3 r round in straight lines, and roads add
# about 30%, ROAD_FACTOR, so 4 r is close to the length asked).
SAY_IT_SHORT = (
    " Answer in a few short lines: miles first (km in brackets), minutes, the busy parts, any"
    " closure or notice, then the link, whole."
)
PROMPTS = (
    {
        "name": "plan_commute",
        "title": "Plan a commute",
        "description": "A calm everyday ride between home and work, with light and rain for the"
        " time you leave.",
        "arguments": [
            {"name": "start", "description": "Where the ride starts", "required": True},
            {"name": "end", "description": "Where it ends", "required": True},
            {"name": "leave_at", "description": "When you leave, e.g. 6 AM weekdays"},
        ],
        "text": (
            "Plan my bike commute from {start} to {end}{leave_at_said} with RouteMaker: plan_route"
            " with ride type default at stress 80 (low stress), `when` to match the time I leave"
            " (weekday_rush if unsure), unless I said otherwise. Then ride_conditions for the time"
            " I leave, to say whether it is dark or rain is on the way. Say in one line why it"
            " goes this way, from the answer's `why`." + SAY_IT_SHORT
        ),
    },
    {
        "name": "family_trail_ride",
        "title": "Family trail ride",
        "description": "An easy ride on paths and quiet streets, for children or a new rider.",
        "arguments": [
            {"name": "start", "description": "Where the ride starts", "required": True},
            {
                "name": "end",
                "description": "Where it goes (leave out for a ride back to the start)",
            },
            {"name": "miles", "description": "About how far, in miles"},
        ],
        "text": (
            "Plan a family bike ride from {start}{end_said}{miles_said} with RouteMaker:"
            " plan_route with ride type novice (Novice and Nervous){loop_said}. Aim for no miles"
            " at LTS 3 and up: where busy_stretches is not empty, revise_route to avoid them or"
            " tell me where they are. Say the steep grades too." + SAY_IT_SHORT
        ),
    },
    {
        "name": "loop_of_n_miles",
        "title": "Loop of N miles",
        "description": "A ride back to where it starts, about as long as you ask.",
        "arguments": [
            {"name": "start", "description": "Where the loop starts and ends", "required": True},
            {"name": "miles", "description": "About how far, in miles", "required": True},
            {"name": "near_metro", "description": "yes to stay near Metro for a ride home"},
        ],
        "text": (
            "Plan a bike loop of about {miles} miles from {start} with RouteMaker, low stress"
            " (stress 80) unless I said otherwise. {loop_how} Keep it within 10% of {miles}"
            " miles: revise once if it is over or under by more." + SAY_IT_SHORT
        ),
    },
    {
        "name": "bike_plus_metro",
        "title": "Bike plus Metro",
        "description": "Ride to a train or bus, ride on at the other end.",
        "arguments": [
            {"name": "start", "description": "Where the trip starts", "required": True},
            {"name": "end", "description": "Where it ends", "required": True},
            {"name": "leave_at", "description": "When you leave"},
        ],
        "text": (
            "Plan a trip from {start} to {end} by bike and Metro or bus with RouteMaker:"
            " plan_route with ride type bike-transit{depart_said}. Say the station or stop where"
            " I board and leave, the next departures, and each ride's miles and busy parts; offer"
            " the other transit options only if I ask." + SAY_IT_SHORT
        ),
    },
)
# Plan a mass ride (Stephen, 2026-11-13): "free-flowing rides that don't require more corkers than
# we'd have"; "typically don't go over 5% grade and definitely not above 8%, either direction";
# "the goal is the distance, not the directness"; a midpoint "usually about 2/3" of the way, and
# "A ride could omit a midpoint" ("in the prompt ask to omit or if suggestions are desired"); "the time length of ride typically about 75-90 minutes of
# riding. That way, hills are considered", "And traffic signals". Mass Ride is planned at 6 mph
# on the flat (core.presets MASS_RIDE_PLANNING_SPEED_KMH).
# Within 10% of the length, and corking from LTS 4 as the first triage to offer: our defaults,
# unmeasured.
MASS_RIDE_PROMPT = {
    "name": "plan_mass_ride",
    "title": "Plan a mass ride",
    "description": "A large group ride that flows freely with the corkers you have, at the length"
    " you want.",
    "arguments": [
        {"name": "start", "description": "Where the ride starts", "required": True},
        {"name": "end", "description": "Where it ends", "required": True},
        {"name": "riders", "description": "About how many riders"},
        {"name": "corkers", "description": "How many corkers you have"},
        {"name": "minutes", "description": "How long the riding should take, in minutes"},
        {"name": "miles", "description": "Or how long the ride should be, in miles"},
        {"name": "speed_mph", "description": "The group's speed, mph"},
        {"name": "midpoint", "description": "The midpoint stop, if you have one"},
    ],
    "text": (
        "Plan a mass ride from {start} to {end} with RouteMaker.{known} Before planning, ask me"
        " for whichever of these I have not given: the number of riders, the number of corkers,"
        " the riding time in minutes (typically 75 to 90) or the length in miles, and the"
        " group's speed in mph.{midpoint_how}"
        " Plan with plan_route, ride type mass-ride, ride_size the riders, any midpoint as a"
        " stop and any shaping points as via points. The goal:"
        " (1) The length I asked for, within 10%: the goal is the length, not the directness, so"
        " add or move via points (revise_route) until it is that long. Given a riding time,"
        " aim at it, with the hills and traffic signals counted: the plan's time (its legs' minutes"
        " added up) is Mass Ride's 6 mph on the flat slowed by the hills, plus waits at signals"
        " and stop signs (summary junction_waits), so at my speed it is (that time less the"
        " waits) x 6 / mph, plus the waits."
        ' (2) Free-flowing: mass_capacity\'s corkers "about" no more than the corkers I have,'
        " and few narrow stretches; where it needs more, move the route off the busiest"
        " junctions, or offer corking (from_lts 4) to see which junctions to leave uncorked."
        " (3) No grade over 5% where it can be helped and never over 8%, up or down: read"
        " steep_grades and route_segments' steepest grade, and avoid or route round any"
        " stretch past that."
        " Give the miles, the riding time at my speed with hills and signals counted, the"
        " corkers"
        " needed against the corkers I have, the steepest grade, then the link."
    ),
}
PROMPTS = (*PROMPTS, MASS_RIDE_PROMPT)
PROMPT_BY_NAME = {p["name"]: p for p in PROMPTS}


def prompts_listed() -> list[dict]:
    """prompts/list: each prompt without its text."""
    return [{k: v for k, v in p.items() if k != "text"} for p in PROMPTS]


def prompt_text(name: str, arguments: dict) -> dict:
    """prompts/get: the prompt's one user message, with the person's words put in. Raises
    ToolError for an unknown prompt or a missing required argument."""
    prompt = PROMPT_BY_NAME.get(name)
    if prompt is None:
        raise ToolError(f"no prompt named {name}")
    if not isinstance(arguments, dict):
        raise ToolError("arguments: an object of the prompt's arguments")
    given = {
        str(k): " ".join(str(v).split())[:200]
        for k, v in (arguments or {}).items()
        if v is not None and str(v).strip()
    }
    for argument in prompt["arguments"]:
        if argument.get("required") and argument["name"] not in given:
            raise ToolError(f"{name} needs {argument['name']}")
    leave_at = given.get("leave_at")
    known = [
        f"{given[k]} {what}"
        for k, what in (
            ("riders", "riders"),
            ("corkers", "corkers"),
            ("minutes", "minutes of riding"),
            ("miles", "miles"),
            ("speed_mph", "mph"),
        )
        if given.get(k)
    ]
    near_metro = given.get("near_metro", "").casefold() in ("yes", "y", "true", "1")
    fields = {
        **{a["name"]: given.get(a["name"], "") for a in prompt["arguments"]},
        "leave_at_said": f", leaving {leave_at}" if leave_at else "",
        "depart_said": f", depart_at for {leave_at}" if leave_at else "",
        "end_said": f" to {given['end']}" if given.get("end") else " and back",
        "miles_said": f", about {given['miles']} miles" if given.get("miles") else "",
        "known": f" So far: {', '.join(known)}." if known else "",
        "midpoint_how": (
            f" The midpoint stop is {given['midpoint']}."
            if given.get("midpoint")
            else " Ask me about a midpoint stop (many rides have one, about two thirds of the"
            " way): do I have a place for it, want it left out, or want suggestions? Left out,"
            " plan without it. For suggestions, offer two or three near the point two thirds"
            " along a first plan (find_place near it: a park, a plaza, a school yard)."
        ),
        "loop_said": ""
        if given.get("end")
        else " and loop true, through one or two quiet via points about a third of the way round",
        "loop_how": (
            "Use plan_metro_loop with start and centre at the start, so the loop keeps near Metro."
            if near_metro
            else "Use plan_route with loop true from the start through two or three via points"
            " on calm roads or trails, set about a quarter of the length out (roads wind about"
            " 30% longer than straight lines)."
        ),
    }
    text = prompt["text"].format(**fields)
    return {
        "description": prompt["description"],
        "messages": [{"role": "user", "content": {"type": "text", "text": text}}],
    }


# The playbook in the server's instructions: which ride type for which ask, and the order of
# calls, kept short (the tool descriptions hold the detail).
PLAYBOOK = (
    "RouteMaker plans bike routes from DC to Baltimore, rated by traffic stress (LTS 1 calmest to"
    " 4, plus Avoid). Pick the ride type that fits: stress 80 for 'low stress', trailmaxxing for"
    " the calmest, novice for children or a new rider, bike-transit for bike plus Metro, else the"
    " one named for the bike or ride. Pass place names as points. After a plan, say the busy"
    " parts, any closure and notice, and `why` when the route is much longer or the rider asks."
    " Give distances in miles first, km in brackets. Share the link whole, with its # part: after"
    " a week only that part can plan the route again. Save to My routes only when asked. Planning"
    " only to test RouteMaker: pass test: true, or archive_draft each draft when done. Calls may"
    " be sent together; an answer with retry_after_s asks for the same call again after that."
)


# --- MCP over stdio -------------------------------------------------------------------------


_write_lock = threading.Lock()


def _send(message: dict, out=None) -> None:
    out = out or sys.stdout
    with _write_lock:
        out.write(json.dumps(message, separators=(",", ":")) + "\n")
        out.flush()


def _error(msg_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def handle(server: Server, message, send=_send, calls: dict | None = None) -> dict | None:
    """One JSON-RPC message in; the response out (None for a notification, or for a call the
    client cancelled, which the protocol says not to answer). `calls` holds the tools/calls in
    flight by request id, so a cancellation can reach one."""
    calls = {} if calls is None else calls
    if not isinstance(message, dict):
        return _error(None, -32600, "a request is one JSON object")
    method = message.get("method")
    msg_id = message.get("id")
    params = message.get("params") or {}
    if msg_id is None:
        if method == "notifications/cancelled":
            running = calls.get(params.get("requestId"))
            if running is not None:
                running.cancelled.set()
        return None  # notifications/initialized and the rest: nothing to answer
    if method == "initialize":
        asked = params.get("protocolVersion")
        version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        result = {
            "protocolVersion": version,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"listChanged": False},
                "prompts": {"listChanged": False},
                # The route view (VIEW_URI), for an assistant app that shows MCP Apps.
                "extensions": {UI_EXTENSION: {"mimeTypes": [VIEW_MIME]}},
            },
            "serverInfo": {
                "name": SERVER_NAME,
                "title": "RouteMaker",
                "version": SERVER_VERSION,
                **({"icons": server.icons} if server.icons else {}),
            },
            "instructions": PLAYBOOK,
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": server.tools()}
    elif method == "resources/list":
        result = {"resources": server.resources()}
    elif method == "prompts/list":
        result = {"prompts": prompts_listed()}
    elif method == "prompts/get":
        try:
            result = prompt_text(str(params.get("name")), params.get("arguments") or {})
        except ToolError as error:
            return _error(msg_id, -32602, str(error))
    elif method == "resources/templates/list":
        result = {"resourceTemplates": []}
    elif method == "resources/read":
        try:
            result = server.read_resource(str(params.get("uri")))
        except ToolError as error:
            return _error(msg_id, -32002, str(error))
    elif method == "tools/call":
        name = params.get("name")
        if server.handler(name) is None:
            return _error(msg_id, -32602, f"no tool named {name}")
        token = (params.get("_meta") or {}).get("progressToken")
        progress = None
        if token is not None:

            def progress(done, total, text):
                send(
                    {
                        "jsonrpc": "2.0",
                        "method": "notifications/progress",
                        "params": {
                            "progressToken": token,
                            "progress": done,
                            "total": total,
                            "message": text,
                        },
                    }
                )

        call = calls.get(msg_id) or Call()  # main() registers it first, so no cancel is missed
        call.progress = progress
        calls[msg_id] = call
        try:
            payload = server.call(name, params.get("arguments") or {}, call)
            result = {
                "content": [
                    *call.images,
                    # Compact: indenting only spends the model's context.
                    {"type": "text", "text": json.dumps(payload, separators=(",", ":"))},
                ],
                "structuredContent": payload,
                "isError": False,
            }
            if call.meta:
                # The route view's data: for the view, kept out of the model's context.
                result["_meta"] = dict(call.meta)
        except Cancelled:
            return None  # the protocol: a cancelled request gets no answer
        except ToolError as error:
            result = {"content": [{"type": "text", "text": str(error)}], "isError": True}
        finally:
            calls.pop(msg_id, None)
        # A call cancelled too late to stop is answered anyway: the client may drop it, but
        # if it reads it, it knows a save went through and need not ask again.
    else:
        return _error(msg_id, -32601, f"method not found: {method}")
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _answer(server: Server, message, calls: dict) -> None:
    try:
        response = handle(server, message, calls=calls)
    except Exception as error:  # a bug, not a refusal: say so and keep serving
        print(f"routemaker-mcp: {type(error).__name__}: {error}", file=sys.stderr)
        msg_id = message.get("id") if isinstance(message, dict) else None
        response = _error(msg_id, -32603, f"internal error: {type(error).__name__}: {error}")
    if response is not None:
        _send(response)


def main() -> None:
    """Read requests line by line. A tool call runs on its own thread, so a ping or a
    cancellation is read while a long plan runs; everything else is answered in turn."""
    server = Server()
    calls: dict = {}
    workers: list[threading.Thread] = []
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            message = json.loads(raw)
        except ValueError:
            _send(_error(None, -32700, "parse error"))
            continue
        if isinstance(message, dict) and message.get("method") == "tools/call":
            if message.get("id") is not None:
                calls[message["id"]] = Call()  # before a cancellation for it can be read
            worker = threading.Thread(target=_answer, args=(server, message, calls), daemon=True)
            worker.start()
            workers.append(worker)
        else:
            _answer(server, message, calls)
    # The client closed the input: finish what is in flight, then stop.
    for worker in workers:
        worker.join()


if __name__ == "__main__":
    main()
