#!/usr/bin/env python3
"""RouteMaker's routing engine as an MCP server, for any assistant that speaks MCP (the owner,
2026-10-18: "Make me a 100 mile route that goes around DC using low stress roads and doesn't stray
more than 5 miles from a metro station"; "other users might use different models").

A thin client of a RouteMaker site's own HTTP API: it plans with POST /api/route, finds places
with GET /api/geocode, and saves to the owner's My routes with POST /api/keyed/routes and a
save-only key from Settings. It never talks to the router directly, so every route it answers
is one the site would plan. Metro distances are read from the station file the map bundles
(frontend/src/rail-data/metro-stations.geojson, DC Open Data, CC BY 4.0) and are straight-line.

Standard library only, so it runs on any Python 3.11 or later with nothing to install. It
speaks MCP over stdio (newline-delimited JSON-RPC 2.0), which Claude Desktop and Claude Code
both launch as a local server. See mcp/README.md.

Configuration, all from the environment:
- ROUTEMAKER_BASE_URL: the site, e.g. http://localhost for a local stack. Required.
- ROUTEMAKER_SAVE_KEY: the save-only key from Settings > AI assistant key. Optional; without it
  routes are planned and linked but not saved.
- ROUTEMAKER_ROUTES_DIR: where GPX files are written. Default ~/RouteMaker-routes.
- ROUTEMAKER_METRO_STATIONS: the station file. Default: the one in this checkout.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

SERVER_NAME = "routemaker"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

METRES_PER_MILE = 1609.344
FEET_PER_METRE = 3.28084
EARTH_RADIUS_MI = 3958.7613

# The middle of DC, the default centre a loop goes around (the Zero Milestone, Ellipse).
DC_CENTRE = (-77.0365, 38.8949)
# The site's own limits (core/api.py MAX_POINTS, COVERAGE_BBOX).
MAX_POINTS = 25
COVERAGE_BBOX = (-78.05, 38.2, -76.02, 39.72)
# A long ride's plan may take the site's whole long budget (core/routing.py LONG_PLAN_BUDGET_S,
# 50 s) after a wait for its one long slot.
ROUTE_TIMEOUT_S = 120
# How much longer a planned loop is than its waypoints in straight lines, for a first guess at
# the ring's radius; the loop is then rescaled by what the router answered.
ROAD_FACTOR = 1.3
# The ride types this planner takes from points alone (the transit and bikeshare ride types plan
# from two points with options of their own and are left to the site).
PRESETS = (
    "default",
    "trailmaxxing",
    "novice",
    "group-ride",
    "mountain-goat",
    "mountain-bike",
    "gravel",
    "fast",
    "cargo",
    "ebike",
    "mass-ride",
)
# Densify the route line to this spacing for the Metro check, so a long straight segment
# cannot hide a stretch past the limit between its two vertices.
CHECK_STEP_MI = 0.1
# Ring waypoints closer than this to each other add nothing but a point to the plan.
MIN_GAP_MI = 2.0


class ToolError(Exception):
    """A refusal to show the model as the tool's answer, not a protocol error."""


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


# --- Metro stations -------------------------------------------------------------------------


@dataclass(frozen=True)
class Station:
    name: str
    lines: str
    lon: float
    lat: float

    @property
    def point(self) -> tuple[float, float]:
        return (self.lon, self.lat)


def default_stations_path() -> Path:
    return Path(__file__).resolve().parents[1] / "frontend/src/rail-data/metro-stations.geojson"


def load_stations(path: str | os.PathLike | None = None) -> list[Station]:
    path = Path(path or os.environ.get("ROUTEMAKER_METRO_STATIONS") or default_stations_path())
    data = json.loads(path.read_text(encoding="utf-8"))
    stations = []
    for feature in data.get("features", []):
        lon, lat = feature["geometry"]["coordinates"][:2]
        props = feature.get("properties", {})
        stations.append(Station(props.get("NAME", "?"), props.get("LINE", ""), lon, lat))
    if not stations:
        raise ToolError(f"no Metro stations in {path}")
    return stations


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


class Api:
    def __init__(self, base_url: str | None = None, save_key: str | None = None):
        base = (base_url or os.environ.get("ROUTEMAKER_BASE_URL") or "").strip().rstrip("/")
        if not base:
            raise ToolError(
                "ROUTEMAKER_BASE_URL is not set: give the MCP server the site's address, e.g."
                " http://localhost for the local stack (mcp/README.md)."
            )
        if not re.match(r"^https?://", base):
            raise ToolError("ROUTEMAKER_BASE_URL must start with http:// or https://")
        self.base = base
        self.save_key = save_key if save_key is not None else os.environ.get("ROUTEMAKER_SAVE_KEY")

    def _request(self, method: str, path: str, body=None, headers=None, timeout=30):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method)
        request.add_header("Accept", "application/json")
        request.add_header("User-Agent", f"routemaker-mcp/{SERVER_VERSION}")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, json.loads(response.read() or b"null"), response.headers
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
            raise ToolError(f"the site refused the route ({status}): {message or payload}")
        raise ToolError("the site stayed busy; try again shortly")

    def geocode(self, query: str, near: tuple[float, float] | None = None) -> list[dict]:
        params = {"q": query, "limit": 5}
        if near:
            params.update(lon=near[0], lat=near[1])
        status, payload, _ = self._request("GET", "/api/geocode?" + urllib.parse.urlencode(params))
        if status != 200 or not isinstance(payload, dict):
            message = payload.get("error") if isinstance(payload, dict) else payload
            raise ToolError(f"place search failed ({status}): {message}")
        return payload.get("results", [])

    def save(self, body: dict) -> dict:
        if not self.save_key:
            raise ToolError(
                "no save key: create one in RouteMaker's Settings > AI assistant key and set it as"
                " ROUTEMAKER_SAVE_KEY in the MCP server's config (mcp/README.md)."
            )
        status, payload, _ = self._request(
            "POST",
            "/api/keyed/routes",
            body,
            headers={"Authorization": f"Bearer {self.save_key}"},
        )
        if status == 201 and isinstance(payload, dict):
            return payload
        message = payload.get("error") if isinstance(payload, dict) else payload
        raise ToolError(f"the site did not save the route ({status}): {message}")


# --- Points, links and files ----------------------------------------------------------------


def as_point(value, api: Api | None, stations: list[Station]) -> tuple[tuple[float, float], str]:
    """A point from [lon, lat], {"lon", "lat"}, a Metro station's name or a place to search
    for, with a label saying what it was taken as."""
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
        wanted = re.sub(r"\s+(metro|station)$", "", text.lower()).strip()
        for station in stations:
            if station.name.lower() == wanted:
                return station.point, f"{station.name} Metro"
        if api is None:
            raise ToolError(f"cannot search for {text!r} without the site")
        found = [r for r in api.geocode(text) if inside_coverage((r["lon"], r["lat"]))]
        if not found:
            raise ToolError(f"no place found for {text!r}")
        return (round(found[0]["lon"], 5), round(found[0]["lat"], 5)), found[0]["label"]
    raise ToolError(f"not a point: {value!r}")


def plan_fragment(points, vias, preset: str, dials: dict) -> str:
    """The page's own plan link fragment (frontend/src/lib/planHash.ts `encodePlan`)."""
    parts = ["p=" + ";".join(f"{lon:.5f},{lat:.5f}" for lon, lat in points)]
    if vias:
        parts.append("via=" + ",".join(str(i) for i in vias))
    parts.append("preset=" + preset)
    parts.append("v=2")
    parts.append(f"stress={dials['stress']}")
    parts.append(f"hills={dials['hills']}")
    if dials.get("avoid_gravel"):
        parts.append("avoidgravel=1")
    if dials.get("trails_off"):
        parts.append("trailsoff=1")
    if dials.get("target_distance_m"):
        parts.append(f"targetmi={dials['target_distance_m'] / METRES_PER_MILE:.1f}")
    if dials.get("loop"):
        parts.append("loop=1")
    return "#" + "&".join(parts)


def page_dials(dials: dict) -> dict:
    """The answer's dials as the page keeps them in a saved route (frontend lib/dials.ts)."""
    kept = {
        "stress": dials["stress"],
        "hills": dials["hills"],
        "when": None,
        "carrying": dials.get("carrying"),
        "assist": bool(dials.get("assist")),
        "avoidGravel": bool(dials.get("avoid_gravel")),
        "trailsOff": bool(dials.get("trails_off")),
        "loop": bool(dials.get("loop")),
    }
    if dials.get("target_distance_m"):
        kept["targetDistanceM"] = dials["target_distance_m"]
    return kept


def routes_dir() -> Path:
    return Path(os.environ.get("ROUTEMAKER_ROUTES_DIR") or Path.home() / "RouteMaker-routes")


def write_gpx(name: str, line: list[list[float]], directory: Path | None = None) -> Path:
    directory = directory or routes_dir()
    directory.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "route"
    path = directory / f"{time.strftime('%Y%m%d-%H%M%S')}-{slug}.gpx"
    points = []
    for vertex in line:
        ele = f"<ele>{vertex[2]:.1f}</ele>" if len(vertex) > 2 else ""
        points.append(f'<trkpt lat="{vertex[1]:.6f}" lon="{vertex[0]:.6f}">{ele}</trkpt>')
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="RouteMaker MCP" xmlns="http://www.topografix.com/GPX/1/1">\n'
        f"<metadata><name>{escape(name)}</name></metadata>\n"
        f"<trk><name>{escape(name)}</name><trkseg>\n" + "\n".join(points) + "\n</trkseg></trk>\n"
        "</gpx>\n",
        encoding="utf-8",
    )
    return path


# --- Planning -------------------------------------------------------------------------------


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
            if table.get(key)
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
            facility,
            {
                "path": "traffic-free path",
                "protected": "protected lane",
                "lane": "painted lane",
                "none": "ordinary street",
                "unknown": "unknown",
            },
        ),
    }
    if answer.get("loop"):
        pct = answer["loop"].get("overlap_pct")
        if pct is not None:
            out["loop_way_back_shared"] = f"{pct:.0f}%"
    if answer.get("avoid_notice"):
        out["avoid_notice"] = answer["avoid_notice"]
    if answer.get("moved_points"):
        out["moved_points"] = len(answer["moved_points"])
    return out


@dataclass
class Plan:
    points: list[tuple[float, float]]
    vias: list[int]
    preset: str
    answer: dict
    check: dict | None

    @property
    def line(self) -> list[list[float]]:
        return self.answer["geometry"]["coordinates"]


def request_body(
    points, vias, preset, *, stress, hills, loop, avoid_gravel, trails_off, target_miles
) -> dict:
    body: dict = {
        "points": [list(p) for p in points],
        "preset": preset,
        # The MCP server asks on the rider's behalf; a long ride needs no second ask.
        "confirm_long": True,
        "candidates": False,
    }
    if vias:
        body["via_points"] = list(vias)
    if stress is not None:
        body["stress"] = int(stress)
    if hills is not None:
        body["hills"] = int(hills)
    if loop:
        body["loop"] = True
    if avoid_gravel:
        body["avoid_gravel"] = True
    if trails_off:
        body["trails_off"] = True
    if target_miles:
        body["target_distance_m"] = int(target_miles * METRES_PER_MILE)
    return body


def plan_once(api, stations, points, vias, preset, options, limit_mi) -> Plan:
    if preset not in PRESETS:
        raise ToolError(f"preset is one of {', '.join(PRESETS)}")
    if not 2 <= len(points) <= MAX_POINTS:
        raise ToolError(f"a route has 2 to {MAX_POINTS} points")
    answer = api.route(request_body(points, vias, preset, **options))
    check = metro_check(answer["geometry"]["coordinates"], limit_mi, stations) if limit_mi else None
    return Plan(list(points), list(vias), preset, answer, check)


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


def with_metro_fix(plan: Plan, stations: list[Station]) -> tuple[list, list[int], str] | None:
    """The points with the Metro station nearest the worst stretch added as a via point in the
    leg that strays, or None where that station is already a point (nothing left to try)."""
    if plan.check is None or plan.check["ok"] or len(plan.points) >= MAX_POINTS:
        return None
    worst = max(plan.check["stretches_over_limit"], key=lambda s: s["max_mi"])
    station, _ = nearest_station(tuple(worst["at"]), stations)
    if any(haversine_mi(station.point, p) < 0.05 for p in plan.points):
        return None
    leg = leg_of(plan, (worst["from_mi"] + worst["to_mi"]) / 2)
    points = [*plan.points[: leg + 1], station.point, *plan.points[leg + 1 :]]
    vias = sorted({*(i if i <= leg else i + 1 for i in plan.vias), leg + 1})
    return points, vias, station.name


def ring_waypoints(
    centre: tuple[float, float],
    radius_mi: float,
    limit_mi: float,
    stations: list[Station],
    sectors: int = 12,
    forced: tuple[tuple[float, float], ...] = (),
) -> list[tuple[float, float]]:
    """Waypoints around `centre`, one per sector of the compass where a Metro station lies, at
    the station whose distance out is nearest `radius_mi`, moved straight out from the centre
    by up to 60% of `limit_mi` where the ring is wider than the station, so every waypoint is
    inside the limit with room to spare. Of stations that reach the ring alike, the one that
    moves least. A waypoint within `MIN_GAP_MI` of another is left out. Sorted clockwise from
    north."""
    reach = 0.6 * limit_mi
    chosen: list[tuple[float, float]] = list(forced)
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
        point = destination(s.point, b, out) if out > 0.05 else (round(s.lon, 5), round(s.lat, 5))
        if not inside_coverage(point):
            point = (round(s.lon, 5), round(s.lat, 5))
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
        'A point: [lon, lat], {"lon": .., "lat": ..}, a Metro station\'s name ("Shady Grove"),'
        " or a place or address to search for."
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
            "The ride type. default: everyday riding. trailmaxxing: the calmest route,"
            " directness second. novice: Novice and Nervous, every road read one stress level up."
            " fast, gravel, mountain-goat (seeks climbs), ebike, cargo, group-ride."
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
    "avoid_gravel": {"type": "boolean", "default": False},
    "trails_off": {
        "type": "boolean",
        "default": False,
        "description": "Keep to roads: no paths or trails.",
    },
    "max_miles_from_metro": {
        "type": "number",
        "exclusiveMinimum": 0,
        "description": (
            "Check that the route never strays more than this far (straight line, miles) from a"
            " Metrorail station, and report the stretches that do."
        ),
    },
    "save_as": {
        "type": "string",
        "maxLength": 120,
        "description": (
            "Save the route to the rider's My routes on the site under this name (needs the save"
            " key). Only when the rider asked for it to be saved."
        ),
    },
}

TOOLS = [
    {
        "name": "find_place",
        "description": (
            "Search RouteMaker's place search (DC to Baltimore) for a place, address or street;"
            " returns up to five matches with [lon, lat]."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string", "minLength": 2}},
            "required": ["query"],
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "metro_stations",
        "description": (
            "List Metrorail stations (all 98, or those within a distance of a point), with lines,"
            " [lon, lat], and straight-line miles and compass bearing from the point."
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
        "name": "plan_route",
        "description": (
            "Plan a bike route on RouteMaker through 2 to 25 points (start, stops or via points,"
            " end) and summarise it: distance, time, climbing, the share on each traffic-stress"
            " level (LTS 1 calmest to 4, and Avoid) and on paths and lanes. Returns a link that"
            " opens the route in the app and writes a GPX file. With max_miles_from_metro it"
            " checks the distance from Metro and, with fix_metro_rounds, adds the nearest"
            " station as a via point and plans again where the route strays."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "points": {
                    "type": "array",
                    "items": POINT_SCHEMA,
                    "minItems": 2,
                    "maxItems": MAX_POINTS,
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
                "target_miles": {
                    "type": "number",
                    "description": "Only at stress 100: a soft target distance.",
                },
                "fix_metro_rounds": {"type": "integer", "minimum": 0, "maximum": 4, "default": 0},
                "name": {"type": "string", "description": "A name for the GPX file and link."},
                **RIDE_OPTIONS,
            },
            "required": ["points"],
        },
        "annotations": {"readOnlyHint": False, "openWorldHint": False},
    },
    {
        "name": "plan_metro_loop",
        "description": (
            "Plan a loop of about target_miles around a centre (DC by default) that stays within"
            " max_miles_from_metro of a Metrorail station: waypoints are picked at Metro stations"
            " (or just beyond them) around the compass, the loop is planned, rescaled once"
            " towards the target length, and repaired where it strays by adding the nearest"
            " station. Each plan of a long loop can take up to a minute; max_plans bounds them."
            " Answers the best loop found with its Metro check, link and GPX file."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "target_miles": {"type": "number", "minimum": 5, "maximum": 300},
                "max_miles_from_metro": {"type": "number", "exclusiveMinimum": 0, "default": 5},
                "start": POINT_SCHEMA,
                "centre": POINT_SCHEMA,
                "max_plans": {"type": "integer", "minimum": 1, "maximum": 6, "default": 4},
                "name": {"type": "string"},
                **{k: v for k, v in RIDE_OPTIONS.items() if k != "max_miles_from_metro"},
            },
            "required": ["target_miles"],
        },
        "annotations": {"readOnlyHint": False, "openWorldHint": False},
    },
]


class Server:
    def __init__(self, api_factory=Api, stations: list[Station] | None = None, out_dir=None):
        self._api_factory = api_factory
        self._api: Api | None = None
        self._stations = stations
        self.out_dir = out_dir
        self.progress = None  # set per call: a function(done, total, message)

    @property
    def api(self) -> Api:
        if self._api is None:
            self._api = self._api_factory()
        return self._api

    @property
    def stations(self) -> list[Station]:
        if self._stations is None:
            self._stations = load_stations()
        return self._stations

    def _report(self, done, total, message):
        if self.progress:
            self.progress(done, total, message)

    # find_place
    def find_place(self, args: dict) -> dict:
        results = self.api.geocode(str(args["query"]))
        return {
            "results": [
                {
                    "name": r["name"],
                    "label": r["label"],
                    "lon_lat": [r["lon"], r["lat"]],
                    "kind": r.get("kind"),
                }
                for r in results
            ]
        }

    # metro_stations
    def metro_stations(self, args: dict) -> dict:
        near = None
        if args.get("near") is not None:
            near, _ = as_point(args["near"], self.api, self.stations)
        rows = []
        for s in self.stations:
            row = {"name": s.name, "lines": s.lines, "lon_lat": [s.lon, s.lat]}
            if near:
                row["miles"] = round(haversine_mi(near, s.point), 1)
                row["bearing"] = round(bearing_deg(near, s.point))
            rows.append(row)
        if near:
            if args.get("within_miles"):
                rows = [r for r in rows if r["miles"] <= float(args["within_miles"])]
            rows.sort(key=lambda r: r["miles"])
        return {"stations": rows, "source": "DC Open Data, Metro Stations Regional (CC BY 4.0)"}

    def _options(self, args: dict) -> dict:
        return {
            "stress": args.get("stress"),
            "hills": args.get("hills"),
            "loop": bool(args.get("loop")),
            "avoid_gravel": bool(args.get("avoid_gravel")),
            "trails_off": bool(args.get("trails_off")),
            "target_miles": args.get("target_miles"),
        }

    def _deliver(self, plan: Plan, name: str, save_as: str | None, notes: list[str]) -> dict:
        dials = plan.answer.get("dials") or {}
        dials = {
            "stress": dials.get("stress", 70),
            "hills": dials.get("hills", 0),
            **{
                k: dials.get(k)
                for k in (
                    "avoid_gravel",
                    "trails_off",
                    "target_distance_m",
                    "loop",
                    "carrying",
                    "assist",
                )
            },
        }
        fragment = plan_fragment(plan.points, plan.vias, plan.preset, dials)
        out = {
            "summary": summary(plan.answer),
            "points": [list(p) for p in plan.points],
            "via_points": plan.vias,
            "preset": plan.preset,
            "stress": dials["stress"],
            "link": f"{self.api.base}/{fragment}",
        }
        if plan.check is not None:
            out["metro_check"] = plan.check
        try:
            out["gpx_file"] = str(write_gpx(name, plan.line, self.out_dir))
        except OSError as error:
            notes.append(f"GPX not written: {error}")
        if save_as:
            saved = self.api.save(
                {
                    "name": save_as.strip()[:120],
                    "source": "plan",
                    "line": [list(v[:2]) for v in plan.line],
                    "distance_m": plan.answer["distance_m"],
                    "inputs": {
                        "hash": fragment,
                        "points": [list(p) for p in plan.points],
                        "preset": plan.preset,
                        "dials": page_dials(dials),
                    },
                    "answer": {
                        **plan.answer,
                        "candidates": None,
                        "avoid_alternate": None,
                        "closure_through": None,
                    },
                }
            )
            out["saved"] = {
                "id": saved.get("id"),
                "name": saved.get("name"),
                "where": "My routes on the site",
            }
        if notes:
            out["notes"] = notes
        out["credit"] = plan.answer.get("attribution", [])
        return out

    # plan_route
    def plan_route(self, args: dict) -> dict:
        points = [as_point(p, self.api, self.stations)[0] for p in args["points"]]
        vias = [int(i) for i in args.get("via_points") or []]
        preset = args.get("preset") or "default"
        limit = args.get("max_miles_from_metro")
        rounds = int(args.get("fix_metro_rounds") or 0) if limit else 0
        options = self._options(args)
        notes: list[str] = []
        self._report(0, rounds + 1, "planning the route")
        plan = plan_once(self.api, self.stations, points, vias, preset, options, limit)
        for done in range(rounds):
            fix = with_metro_fix(plan, self.stations)
            if fix is None:
                break
            new_points, new_vias, station = fix
            self._report(done + 1, rounds + 1, f"replanning by way of {station}")
            again = plan_once(self.api, self.stations, new_points, new_vias, preset, options, limit)
            notes.append(
                f"added {station} as a via point: {plan.check['miles_over_limit']} -> "
                f"{again.check['miles_over_limit']} mi over the limit"
            )
            if again.check["miles_over_limit"] <= plan.check["miles_over_limit"]:
                plan = again
        name = args.get("name") or "RouteMaker route"
        return self._deliver(plan, name, args.get("save_as"), notes)

    # plan_metro_loop
    def plan_metro_loop(self, args: dict) -> dict:
        target = float(args["target_miles"])
        limit = float(args.get("max_miles_from_metro") or 5)
        centre = (
            as_point(args["centre"], self.api, self.stations)[0]
            if args.get("centre") is not None
            else DC_CENTRE
        )
        start = (
            as_point(args["start"], self.api, self.stations)[0]
            if args.get("start") is not None
            else None
        )
        preset = args.get("preset") or "default"
        max_plans = int(args.get("max_plans") or 4)
        options = {**self._options(args), "loop": True}
        options["stress"] = 80 if args.get("stress") is None else args["stress"]
        radius = target / (2 * math.pi * ROAD_FACTOR)
        forced: tuple = ()
        rescaled = False
        notes: list[str] = []
        best: Plan | None = None
        points, vias = loop_points_from(
            start, ring_waypoints(centre, radius, limit, self.stations, forced=forced), centre
        )
        for attempt in range(max_plans):
            self._report(attempt, max_plans, f"planning loop {attempt + 1} ({len(points)} points)")
            try:
                plan = plan_once(self.api, self.stations, points, vias, preset, options, limit)
            except ToolError as error:
                notes.append(f"plan {attempt + 1} failed: {error}")
                if best is None and attempt + 1 == max_plans:
                    raise
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
                radius = max(1.5, radius / off)
                points, vias = loop_points_from(
                    start,
                    ring_waypoints(centre, radius, limit, self.stations, forced=forced),
                    centre,
                )
                continue
            fix = with_metro_fix(plan, self.stations)
            if fix is None:
                break
            new_points, new_vias, station = fix
            forced = (*forced, _added(new_points, plan))
            points, vias = new_points, new_vias
            notes.append(f"adding {station} where the loop strayed")
        assert best is not None
        miles = best.answer["distance_m"] / METRES_PER_MILE
        if not 0.85 <= miles / target <= 1.15:
            notes.append(
                f"the loop is {miles:.0f} mi against a target of {target:.0f}: within"
                f" {limit:g} mi of Metro, the ring could not be made closer"
            )
        name = args.get("name") or f"{target:.0f} mi Metro loop"
        return self._deliver(best, name, args.get("save_as"), notes)

    def call(self, name: str, args: dict) -> dict:
        handler = {
            "find_place": self.find_place,
            "metro_stations": self.metro_stations,
            "plan_route": self.plan_route,
            "plan_metro_loop": self.plan_metro_loop,
        }.get(name)
        if handler is None:
            raise ToolError(f"no tool named {name}")
        return handler(args or {})


def _added(points: list, plan: Plan):
    """The one point `with_metro_fix` added to the plan's points."""
    return next(p for p in points if p not in plan.points)


def _better(plan: Plan, best: Plan, target: float) -> bool:
    """Fewer miles over the Metro limit first, then nearer the target length."""
    a = (plan.check["miles_over_limit"], abs(plan.answer["distance_m"] / METRES_PER_MILE - target))
    b = (best.check["miles_over_limit"], abs(best.answer["distance_m"] / METRES_PER_MILE - target))
    return a < b


# --- MCP over stdio -------------------------------------------------------------------------


def _send(message: dict, out=None) -> None:
    out = out or sys.stdout
    out.write(json.dumps(message, separators=(",", ":")) + "\n")
    out.flush()


def handle(server: Server, message: dict, send=_send) -> dict | None:
    """One JSON-RPC message in; the response out (None for a notification)."""
    method = message.get("method")
    msg_id = message.get("id")
    params = message.get("params") or {}
    if msg_id is None:
        return None  # notifications/initialized, cancelled: nothing to answer
    if method == "initialize":
        asked = params.get("protocolVersion")
        version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        result = {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": (
                "RouteMaker plans bike routes from DC to Baltimore, rated by traffic stress (LTS 1"
                " calmest to 4, plus Avoid). Give distances in miles first, km in brackets. Share"
                " the link so the rider can open the route in the app; save to My routes only when"
                " asked."
            ),
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        token = (params.get("_meta") or {}).get("progressToken")
        if token is not None:
            server.progress = lambda done, total, text: send(
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
        try:
            payload = server.call(params.get("name"), params.get("arguments") or {})
            result = {
                "content": [{"type": "text", "text": json.dumps(payload, indent=1)}],
                "structuredContent": payload,
                "isError": False,
            }
        except ToolError as error:
            result = {"content": [{"type": "text", "text": str(error)}], "isError": True}
        finally:
            server.progress = None
    else:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": f"method not found: {method}"},
        }
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def main() -> None:
    server = Server()
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            message = json.loads(raw)
        except ValueError:
            _send(
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
            )
            continue
        try:
            response = handle(server, message)
        except Exception as error:  # a bug, not a refusal: say so and keep serving
            print(f"routemaker-mcp: {type(error).__name__}: {error}", file=sys.stderr)
            response = {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "error": {"code": -32603, "message": f"internal error: {error}"},
            }
        if response is not None:
            _send(response)


if __name__ == "__main__":
    main()
