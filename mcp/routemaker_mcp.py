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
from datetime import date, timedelta
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
MAX_DRAFTS = 200  # drafts kept in memory
PLAN_BUDGET_S = 48  # the longest one plan can take: the site's long-plan budget, and a little
OUT_OF_TIME = (
    "stopped there to answer inside the site's time limit; revise_route on this draft can still"
    " fix where it strays (fix_metro_rounds) or move its points"
)
COVERAGE_BBOX = (-78.05, 38.2, -76.02, 39.72)
# A long ride's plan may take the site's whole long budget (core/routing.py LONG_PLAN_BUDGET_S,
# 50 s) after a wait for its one long slot.
ROUTE_TIMEOUT_S = 120
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
    "cargo",
    "ebike",
    "bikeshare",
    "rebalance",
    "bike-transit",
    "bikeshare-transit",
)
TWO_POINT_PRESETS = ("bikeshare", "rebalance", "bike-transit", "bikeshare-transit")
KG_PER_LB = 0.45359237
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
        # A site behind a password (the beta's nginx gate): "user:password", sent on every request.
        basic = os.environ.get("ROUTEMAKER_BASIC_AUTH", "")
        self.basic = "Basic " + base64.b64encode(basic.encode()).decode() if ":" in basic else None

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
            raise ToolError(refusal(status, message or payload))
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

    def scenic_roads(
        self, near: tuple[float, float], miles: float, designation: str = ""
    ) -> list[dict]:
        """GET /api/scenic-roads: the designated roads near a point, nearest first."""
        params = {"lon": near[0], "lat": near[1], "miles": miles}
        if designation:
            params["designation"] = designation
        status, payload, _ = self._request(
            "GET", "/api/scenic-roads?" + urllib.parse.urlencode(params)
        )
        if status != 200 or not isinstance(payload, dict):
            message = payload.get("error") if isinstance(payload, dict) else payload
            raise ToolError(f"the scenic road search failed ({status}): {message}")
        return payload.get("roads", [])

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
        if "p=" not in fragment:
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


def find_station(text: str, stations: list[Station]) -> Station | None:
    """The one Metro station `text` names: its whole name, its first part ("Navy Yard" for
    Navy Yard-Ballpark; later parts such as "Adams Morgan" are neighbourhoods, left to place
    search), or the start of it ("Ronald Reagan"), with or without "Metro" or "station" after
    it. None when nothing or more than one station fits ("Farragut"), so the text goes to place
    search."""
    said = _station_words(text)
    asked = {said, re.sub(r"( metro| station| metro station)+$", "", said).strip()}
    asked.discard("")
    for test in (
        lambda s: _station_words(s.name) in asked,
        lambda s: _station_words(re.split(r"[-/]", s.name)[0]) in asked,
        lambda s: any(_station_words(s.name).startswith(a + " ") for a in asked),
    ):
        fits = [s for s in stations if test(s)]
        if len(fits) == 1:
            return fits[0]
        if fits:
            return None
    return None


# Matches of one place search farther apart than this are different places.
SAME_PLACE_MI = 5.0


def pick_place(text: str, found: list[dict], neighbours: list[tuple[float, float]]) -> tuple:
    """The match of a place search to take for `text`, and the other places it could have
    been ([] where it could be nothing else). One place, wherever it is, is taken. Where the
    matches are different places (Moore Road in Boyds, MD and in Centreville, VA), the first
    within NEAR_PLACE_MI of one of the route's other points (`neighbours`) is taken, and where
    none is the answer is a question back; with no other points to go by, the first match."""
    if not found:
        raise ToolError(f"no place found for {text!r}")
    first = (found[0]["lon"], found[0]["lat"])
    if all(haversine_mi(first, (r["lon"], r["lat"])) <= SAME_PLACE_MI for r in found):
        return found[0], []

    if not neighbours:
        # Nothing to go by (the first of the route's names): the search's own first match,
        # with the others said.
        return found[0], [
            r for r in found if haversine_mi(first, (r["lon"], r["lat"])) > SAME_PLACE_MI
        ]

    def away(r) -> float:
        here = (r["lon"], r["lat"])
        return min(haversine_mi(here, n) for n in neighbours) if neighbours else math.inf

    near = [r for r in found if away(r) <= NEAR_PLACE_MI]
    if near:
        chosen = near[0]
        here = (chosen["lon"], chosen["lat"])
        others = [r for r in found if haversine_mi(here, (r["lon"], r["lat"])) > SAME_PLACE_MI]
        return chosen, others
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
) -> tuple[tuple[float, float], str]:
    """A point from [lon, lat], {"lon", "lat"}, a Metro station's name or a place to search
    for, with a label saying what it was taken as. A place name is searched near the route's
    other points (`neighbours`), and taken as `pick_place` says; the other places it could have
    been go in `others`."""
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
        station = find_station(text, stations)
        if station is not None:
            return station.point, f"{station.name} Metro"
        if api is None:
            raise ToolError(f"cannot search for {text!r} without the site")
        neighbours = list(neighbours or [])
        near = neighbours[0] if neighbours else None
        found = [r for r in api.geocode(text, near) if inside_coverage((r["lon"], r["lat"]))]
        chosen, elsewhere = pick_place(text, found, neighbours)
        if others is not None:
            others.extend(elsewhere)
        return (round(chosen["lon"], 5), round(chosen["lat"], 5)), chosen["label"]
    raise ToolError(f"not a point: {value!r}")


def plan_fragment(points, vias, preset: str, dials: dict, sent: dict) -> str:
    """The page's own plan link fragment (frontend/src/lib/planHash.ts `encodePlan`): the
    answer's `dials`, and what only the request carried (`sent`, the POST /api/route body)."""
    parts = ["p=" + ";".join(f"{lon:.5f},{lat:.5f}" for lon, lat in points)]
    if vias:
        parts.append("via=" + ",".join(str(i) for i in vias))
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
    if dials.get("avoid_gravel"):
        parts.append("avoidgravel=1")
    if dials.get("trails_off"):
        parts.append("trailsoff=1")
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
    return "#" + "&".join(parts)


def page_dials(dials: dict, sent: dict) -> dict:
    """The plan's dials as the page keeps them in a saved route (frontend lib/dials.ts)."""
    kept = {
        "stress": dials["stress"],
        "hills": dials["hills"],
        "when": sent.get("when"),
        "carrying": dials.get("carrying"),
        "assist": bool(dials.get("assist")),
        "avoidGravel": bool(dials.get("avoid_gravel")),
        "trailsOff": bool(dials.get("trails_off")),
        "loop": bool(dials.get("loop")),
    }
    optional = {
        "targetDistanceM": dials.get("target_distance_m"),
        "noviceLegs": sent.get("novice_legs"),
        "bike": sent.get("bike"),
        "ending": sent.get("ending"),
        "mtbLevel": sent.get("mtb_level"),
        "mtbPreferred": sent.get("mtb_preferred"),
    }
    kept.update({k: v for k, v in optional.items() if v})
    return kept


PRESET_ALIASES = {"kids": "novice"}  # planHash.ts PRESET_ALIASES
STRESS_DEFAULT_AT = 70  # dials.ts: the stress slider's Default


def stress_from_v1(old: float) -> int:
    """An old (v1) link's stress on the new slider, as planHash.ts `stressFromV1`: old x 70/90
    up to 90, then 70 + (old - 90)."""
    if old <= 90:
        return round(old * STRESS_DEFAULT_AT / 90)
    return STRESS_DEFAULT_AT + round(old - 90)


def parse_fragment(fragment: str) -> tuple[list, list[int], str, dict]:
    """A plan link's fragment as the page reads it (planHash.ts `decodePlan`): the points, the
    via points, the ride type and POST /api/route's options."""
    params = urllib.parse.parse_qs(fragment.lstrip("#"), keep_blank_values=False)

    def one(key):
        values = params.get(key)
        return values[0] if values else None

    points = []
    for pair in (one("p") or "").split(";"):
        try:
            lon, lat = (float(v) for v in pair.split(","))
        except ValueError:
            continue
        if inside_coverage((lon, lat)):
            points.append((lon, lat))
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
        "avoid_gravel": one("avoidgravel") == "1",
        "trails_off": one("trailsoff") == "1",
        "novice_legs": one("novice") == "1",
        "loop": one("loop") == "1",
        "bike": one("bike") if one("bike") in ("classic", "ebike") else None,
        "ending": "outside_dock" if one("ending") == "outside" else None,
        "mtb_level": number("level"),
        "mtb_preferred": number("prefer"),
    }
    if one("targetmi"):
        try:
            options["target_distance_m"] = int(float(one("targetmi")) * METRES_PER_MILE)
        except ValueError:
            pass
    return points, vias, preset, options


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
        kind = entry.get("facility") or "street"
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


def busy_stretches(answer: dict) -> list[dict]:
    """Where the route rides LTS 3 and up, in route order: from and to (miles), the roads and
    the worst LTS (5 is Avoid). The longest MAX_BUSY_ROWS where there are more."""
    spans: list[dict] = []
    for entry in _stretches(answer):
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


# --- Interval training: where an effort can run unbroken ------------------------------------
#
# The owner, 2026-10-25: "Are there any good routes for doing sets of 5 minutes on, 3
# minutes off, in repeat 5 times. We'd need to find places with limited needs to turn, go
# downhill, or stop during the on sets." An effort is broken by a stop or signal, a busy road
# to cross without one, a sharp turn, a descent or an LTS 4 road; recovery can be anywhere.

INTERVAL_PAD_MI = 0.05  # slowing before, and getting going after, a stop or a turn
DESCENT_PCT = -2.0  # a grade this steep downhill breaks an effort
DESCENT_MIN_M = 150.0  # held this far (one steep sample is noise)
STOP_CONTROLS = ("signal", "stop", "all_stop")
SHARP_TURNS = ("left", "right")
MAX_LAPS = 10


def _breaks(answer: dict) -> tuple[list[tuple[float, float, str]], dict]:
    """The spans (from_mi, to_mi, why) an effort cannot run through, and how many of each."""
    scale = _traced_scale(answer) / METRES_PER_MILE
    distance_mi = (answer.get("distance_m") or 0.0) / METRES_PER_MILE
    spans: list[tuple[float, float, str]] = []
    counts: dict[str, int] = {}

    def point(mile: float, why: str) -> None:
        spans.append((mile - INTERVAL_PAD_MI, mile + INTERVAL_PAD_MI, why))
        counts[why] = counts.get(why, 0) + 1

    events = answer.get("junctions_debug")
    if events is None:  # only the flagged ones: a quiet stop sign goes unseen
        events = answer.get("intersections") or []
    for event in events:
        control, tier = event.get("control"), event.get("crossed_tier")
        if control in STOP_CONTROLS:
            point(event.get("m", 0) * scale, "signal" if control == "signal" else "stop sign")
        elif control == "none" and tier is not None and tier >= 3:
            point(event.get("m", 0) * scale, "busy road to cross")
    for entry in answer.get("description") or []:
        turn = entry.get("turn") or {}
        if entry.get("kind") == "stretch" and turn.get("movement") in SHARP_TURNS:
            point(entry["from_mi"], "sharp turn")
        if entry.get("kind") == "stretch" and (entry.get("tier") or 0) >= 4:
            spans.append((entry["from_mi"], entry["to_mi"], "LTS 4 road"))
            counts["LTS 4 road"] = counts.get("LTS 4 road", 0) + 1
    profile = answer.get("profile") or {}
    run = None
    for m, grade in zip(profile.get("m") or [], profile.get("grade_pct") or [], strict=False):
        if grade is not None and grade <= DESCENT_PCT:
            run = run or [m, m]
            run[1] = m
            continue
        if run and run[1] - run[0] >= DESCENT_MIN_M:
            spans.append((run[0] * scale, run[1] * scale, "descent"))
            counts["descent"] = counts.get("descent", 0) + 1
        run = None
    if run and run[1] - run[0] >= DESCENT_MIN_M:
        spans.append((run[0] * scale, run[1] * scale, "descent"))
        counts["descent"] = counts.get("descent", 0) + 1
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


# Speed on a climb at the effort's pace: pace / (1 + CLIMB_SLOWING * grade%), so 18 mph on
# the flat is about 11 mph at 5% (a rough fit; only the minutes an effort takes need it).
CLIMB_SLOWING = 0.12
# Recovery rides slower than the effort: it covers this share of the effort's ground a minute.
RECOVERY_SHARE = 0.7
# A route whose ends are this close is ridden again from the start (a loop, an out-and-back).
SAME_END_MI = 0.1


def _minutes_along(answer: dict, pace: float):
    """minutes(mile): the effort's minutes from the start to `mile`, slower up the climbs."""
    scale = _traced_scale(answer) / METRES_PER_MILE
    profile = answer.get("profile") or {}
    marks, total, last_mi = [(0.0, 0.0)], 0.0, 0.0
    for m, grade in zip(profile.get("m") or [], profile.get("grade_pct") or [], strict=False):
        mile = m * scale
        if mile <= last_mi:
            continue
        speed = pace / (1 + CLIMB_SLOWING * grade) if grade and grade > 0 else pace
        total += (mile - last_mi) / speed * 60
        marks.append((mile, total))
        last_mi = mile
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


def _gain_ft(answer: dict, a: float, b: float) -> float:
    """The climbing, feet, between miles `a` and `b` (the profile's rises, summed)."""
    scale = _traced_scale(answer) / METRES_PER_MILE
    profile = answer.get("profile") or {}
    gain, last = 0.0, None
    for m, height in zip(profile.get("m") or [], profile.get("elevation_m") or [], strict=False):
        if height is None or not a <= m * scale <= b:
            continue
        if last is not None and height > last:
            gain += height - last
        last = height
    return gain * FEET_PER_METRE


def interval_check(answer: dict, ask: dict, roads_at=None) -> dict:
    """Whether the route holds the asked sets (`ask`: on_minutes, off_minutes, sets,
    pace_mph on the flat), riding it again from the start where it ends where it began (a
    loop, an out-and-back: efforts up the climb, recovery down it): where each effort goes,
    the longest clear stretches, and what breaks the rest."""
    on_min = float(ask.get("on_minutes") or 5)
    off_min = float(ask.get("off_minutes") or 3)
    sets = int(ask.get("sets") or 5)
    pace = float(ask.get("pace_mph") or 18)
    distance_mi = (answer.get("distance_m") or 0.0) / METRES_PER_MILE
    minutes = _minutes_along(answer, pace)
    spans, counts = _breaks(answer)
    clear = [c for c in _clear(spans, distance_mi) if c[1] - c[0] > 0.01]
    line = (answer.get("geometry") or {}).get("coordinates") or []
    again = bool(answer.get("loop")) or (
        len(line) > 1 and haversine_mi(tuple(line[0][:2]), tuple(line[-1][:2])) <= SAME_END_MI
    )
    efforts: list[dict] = []
    at, lap = 0.0, 0
    while len(efforts) < sets and lap < (MAX_LAPS if again else 1):
        fit = None
        for a, b in clear:
            begin = max(a, at)
            if begin >= b:
                continue
            finish = _mile_after(minutes, begin, on_min, b)
            if finish is not None:
                fit = (begin, finish)
                break
        if fit is None:
            lap, at = lap + 1, 0.0
            continue
        efforts.append(
            {
                "set": len(efforts) + 1,
                "lap": lap + 1,
                "from_mi": round(fit[0], 2),
                "to_mi": round(fit[1], 2),
            }
        )
        # Recovery: off_min at the slower pace, past the lap's end onto the next lap.
        at = fit[1] + pace * RECOVERY_SHARE * off_min / 60
        if again and at >= distance_mi:
            lap, at = lap + 1, at - distance_mi
    longest = sorted(clear, key=lambda c: c[1] - c[0], reverse=True)[:5]
    # Repeats (the owner, 2026-10-25: "ride up the hill for a workout, ride down it for a
    # rest"): one clear stretch, ridden this way for each effort and back the other way to
    # recover, so only this direction needs to be clear. Each one long enough, the most
    # climbing first.
    repeats = []
    for a, b in clear:
        finish = _mile_after(minutes, a, on_min, b)
        if finish is None:
            continue
        gain = _gain_ft(answer, a, finish)
        length_m = (finish - a) * METRES_PER_MILE
        repeats.append(
            {
                "from_mi": round(a, 2),
                "to_mi": round(finish, 2),
                "climb_ft": round(gain),
                "avg_grade_pct": round(gain / FEET_PER_METRE / length_m * 100, 1),
                **({"roads": roads_at(a, finish)} if roads_at else {}),
            }
        )
    repeats.sort(key=lambda r: -r["climb_ft"])
    out = {
        "asked": f"{sets} x {on_min:g} min on, {off_min:g} min off, {pace:g} mph on the flat",
        "sets_fit": len(efforts),
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
        "ridden_again_from_start": again,
    }
    if again and efforts:
        out["laps"] = efforts[-1]["lap"]
    if answer.get("junctions_debug") is None:
        out["note"] = "only flagged junctions were read: a quiet stop sign may be missing"
    return out


def _intervals_asked(value) -> dict | None:
    """The interval set asked for, checked, or None."""
    if not value:
        return None
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
            number = float(value[key])
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


def route_details(plan: Plan) -> dict:
    """What the route rides, for the answer: its roads, busy stretches, very-high-stress
    junctions, scenic roads and small detours."""
    answer = plan.answer
    out: dict = {}
    roads = road_list(answer)
    if roads:
        out.update(roads)
    if answer.get("description") or answer.get("description_overview"):
        out["busy_stretches"] = busy_stretches(answer)
        # What the list leaves out (short LTS 3 bits, past MAX_BUSY_ROWS), so it adds up.
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
    return out


@dataclass
class Draft:
    """A planned route the rider has not kept yet, with what it was planned with."""

    plan: Plan
    options: dict
    limit: float | None
    name: str
    trim_spurs: bool = True
    intervals: dict | None = None


@dataclass
class Plan:
    points: list[tuple[float, float]]
    vias: list[int]
    preset: str
    answer: dict
    check: dict | None
    sent: dict

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
    body.update({k: v for k, v in options.items() if v is not None and v is not False})
    return body


def plan_once(api, stations, points, vias, preset, options, limit_mi) -> Plan:
    if preset not in PRESETS:
        raise ToolError(f"preset is one of {', '.join(PRESETS)}")
    if not 2 <= len(points) <= MAX_POINTS:
        raise ToolError(f"a route has 2 to {MAX_POINTS} points")
    if preset in TWO_POINT_PRESETS and len(points) != 2:
        raise ToolError(f"{preset} plans from a start and an end only")
    sent = request_body(points, vias, preset, options)
    answer = api.route(sent)
    check = metro_check(answer["geometry"]["coordinates"], limit_mi, stations) if limit_mi else None
    return Plan(list(points), list(vias), preset, answer, check, sent)


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
            "The ride type; pick the one that fits the ask. default: everyday riding."
            " trailmaxxing: the calmest route, directness second (stress 100, honours"
            " target_miles). novice: Novice and Nervous, every road read one stress level up."
            " group-ride: a club ride. mass-ride: a large group on the direct roadway (no loops,"
            " stress and hills held low). mountain-goat: seeks climbs. mountain-bike: trails by"
            " IMBA level. gravel: unpaved welcome. fast: direct, traffic tolerant. cargo: cargo"
            " bike (carrying, assist). ebike: e-bike rules and pace. bikeshare and rebalance:"
            " Capital Bikeshare dock to dock (two points). bike-transit and bikeshare-transit:"
            " bike plus Metro and bus (two points; depart_at, transit_option)."
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
        "description": "When the ride is, for traffic. Absent: now.",
    },
    "rider_weight_lb": {
        "type": "number",
        "description": (
            "Rider, bike and load together, pounds; weighs climbs at the top of the stress slider."
        ),
    },
    "target_miles": {
        "type": "number",
        "description": "At stress 100 (Trailmaxxing) only: a soft target distance, miles.",
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
    "ending": {
        "type": "string",
        "enum": ["dock", "outside_dock"],
        "description": "Bikeshare e-bike only: end at a dock or at the destination itself.",
    },
    "depart_at": {
        "type": "string",
        "description": "Transit ride types only: ISO 8601 departure time. Absent: now.",
    },
    "transit_option": {
        "type": "string",
        "description": "Transit ride types only: an option's key from an earlier answer.",
    },
    "novice_legs": {
        "type": "boolean",
        "description": "Transit ride types only: plan the bike legs as Novice and Nervous.",
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
}

INTERVALS = {
    "type": "object",
    "description": (
        "Check the route for interval training: where an effort of on_minutes can run"
        " without a stop sign, signal, busy road to cross, sharp turn, descent or LTS 4"
        " road (climbs are fine and slow the effort's pace). The answer's `intervals` says"
        " how many sets fit riding the route through (again from the start where it ends"
        " where it began), the `repeats`: clear stretches to ride up for each effort and"
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
PASSED_OPTIONS = (
    "stress",
    "hills",
    "when",
    "carrying",
    "assist",
    "avoid_gravel",
    "trails_off",
    "mtb_level",
    "mtb_preferred",
    "bike",
    "ending",
    "depart_at",
    "transit_option",
    "novice_legs",
)


TOOLS = [
    {
        "name": "find_place",
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
        "name": "scenic_roads_near",
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
            },
            "required": ["near"],
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "plan_route",
        "description": (
            "Plan a bike route on RouteMaker through 2 to 25 points (start, stops or via points,"
            " end) and summarise it: distance, time, climbing, the share on each traffic-stress"
            " level (LTS 1 calmest to 4, and Avoid) and on paths and lanes. The route is a draft:"
            " it comes back with a draft_id and a link that opens this exact route in the app"
            " (a shared link, as the app's Share makes), and nothing is saved to My routes."
            " Revise it with revise_route; keep it with save_route once the rider is happy."
            " The answer also says what the route rides: `roads` in order (miles, main and"
            " worst LTS, facility, and `scenic` for a rustic road, scenic byway, the East Coast"
            " Greenway or a US Bicycle Route), `busy_stretches` (where it rides LTS 3 and up),"
            " `junctions` (very-high-stress crossings and turns), `scenic_roads`, and"
            " `small_detours` / `via_spurs` (where it leaves a road and comes back to it, or"
            " goes out and back to a via point; riders rarely want these: move or drop the"
            " point with revise_route). To shape a route onto roads the router does not pick"
            " on its own (a rustic road, a trail; scenic_roads_near lists them), add via points"
            " ON those roads, by [lon, lat]"
            " or by name: a name is searched near the route's other points, and an ambiguous"
            " one is asked back. Read these before sending the link, and say the busy parts."
            " With max_miles_from_metro it checks the distance from Metro and, with"
            " fix_metro_rounds, adds the nearest station as a via point where the route strays."
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
                "fix_metro_rounds": {"type": "integer", "minimum": 0, "maximum": 4, "default": 0},
                "trim_spurs": TRIM_SPURS,
                "intervals": INTERVALS,
                **RIDE_OPTIONS,
            },
            "required": ["points"],
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "plan_metro_loop",
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
            },
            "required": ["link"],
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "revise_route",
        "description": (
            "Change a draft the rider has looked at and plan it again, as a new draft (the old"
            " one stays, to go back to). Send only what changes: points to add, move or remove,"
            " the ride type, any setting, loop, or the Metro limit. Nothing is saved."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string"},
                "points": {
                    "type": "array",
                    "items": POINT_SCHEMA,
                    "minItems": 2,
                    "maxItems": MAX_POINTS,
                    "description": "Replace every point (via_points then index these).",
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
                "loop": {"type": "boolean"},
                "fix_metro_rounds": {"type": "integer", "minimum": 0, "maximum": 4},
                "trim_spurs": TRIM_SPURS,
                "intervals": INTERVALS,
                **{
                    k: {kk: vv for kk, vv in v.items() if kk != "default"}
                    for k, v in RIDE_OPTIONS.items()
                },
                "clear_settings": {
                    "type": "array",
                    "items": {"type": "string", "enum": [*PASSED_OPTIONS, "max_miles_from_metro"]},
                    "description": "Settings to set back to the ride type's own.",
                },
            },
            "required": ["draft_id"],
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "save_route",
        "description": (
            "Keep a draft once the rider has said to, under a name: on the site's own connector,"
            " in their My routes; on the rider's own computer, as a GPX file. Only on the"
            " rider's word."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string"},
                "name": {"type": "string", "minLength": 1, "maxLength": 120},
            },
            "required": ["draft_id", "name"],
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
    },
    {
        "name": "gpx_route",
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
    "replace",
)


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

    def time_for_another_plan(self) -> bool:
        """Whether one more plan of a long ride still fits before the deadline."""
        return self.deadline is None or time.monotonic() + PLAN_BUDGET_S < self.deadline

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
    instead (core.connector), with the same two methods."""

    def __init__(self):
        self._drafts: dict[str, Draft] = {}
        self._lock = threading.Lock()

    def get(self, draft_id: str) -> Draft | None:
        return self._drafts.get(draft_id)

    def put(self, draft: Draft) -> str:
        with self._lock:
            # Random, so an id from before a restart finds nothing rather than another route.
            draft_id = f"d{secrets.token_hex(4)}"
            self._drafts[draft_id] = draft
            while len(self._drafts) > MAX_DRAFTS:  # the oldest go first
                del self._drafts[next(iter(self._drafts))]
        return draft_id

    def __contains__(self, draft_id) -> bool:
        return draft_id in self._drafts


# A draft's exact-route link lasts as long as the draft (a week) and a day more, then the site
# deletes it (shared_routes keep "until"): a draft often starts at home, and every revision makes
# one. A route the rider saves is kept in My routes on its own.
DRAFT_LINK_DAYS = 8


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

    def tools(self) -> list[dict]:
        """The tools, as tools/list gives them: without the post tool unless posts may be
        written."""
        return [t for t in TOOLS if self.posts or t["name"] not in POST_TOOLS]

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
        for r in self.api.geocode(str(args["query"]), near):
            row = {
                "name": r["name"],
                "label": r["label"],
                "lon_lat": [r["lon"], r["lat"]],
                "kind": r.get("kind"),
            }
            if near:
                row["miles_from_near"] = round(haversine_mi(near, (r["lon"], r["lat"])), 1)
            rows.append(row)
        return {"results": rows}

    # scenic_roads_near
    def scenic_roads_near(self, args: dict, call: Call) -> dict:
        near, _ = as_point(args["near"], self.api, self.stations)
        miles = min(15.0, max(0.5, float(args.get("within_miles") or 5)))
        roads = self.api.scenic_roads(near, miles, str(args.get("designation") or "").strip())
        return {
            "roads": roads,
            "source": "Montgomery County Planning (Rustic Roads), MDOT SHA (Scenic Byways),"
            " OpenStreetMap (East Coast Greenway, US Bicycle Routes)",
        }

    # metro_stations
    def metro_stations(self, args: dict, call: Call) -> dict:
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
        options = {key: args.get(key) for key in PASSED_OPTIONS}
        options["loop"] = bool(args.get("loop"))
        if args.get("target_miles"):
            options["target_distance_m"] = int(float(args["target_miles"]) * METRES_PER_MILE)
        if args.get("rider_weight_lb"):
            options["system_weight_kg"] = round(float(args["rider_weight_lb"]) * KG_PER_LB)
        return options

    def _plan(self, call: Call, points, vias, preset, options, limit) -> Plan:
        call.check()
        return plan_once(self.api, self.stations, points, vias, preset, options, limit)

    def _dials(self, plan: Plan) -> dict:
        answered = plan.answer.get("dials") or {}
        return {
            "stress": answered.get("stress", 70),
            "hills": answered.get("hills", 0),
            **{
                k: answered.get(k)
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

    def _point(self, value, taken: list[dict], neighbours=None) -> tuple[float, float]:
        """as_point, noting what a named point was taken as so the answer can say, and the
        other places the name could have meant."""
        others: list[dict] = []
        point, label = as_point(value, self.api, self.stations, neighbours, others)
        if isinstance(value, str):
            row = {"asked": value, "taken_as": label, "at": list(point)}
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
        """Every point, [lon, lat] and station names first, then each place name searched near
        the points already found, those beside it in the list first."""
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
    ) -> dict:
        """Keep the plan as a draft and describe it: nothing is saved or written."""
        draft_id = self.drafts.put(Draft(plan, dict(options), limit, name, trim_spurs, intervals))
        dials = self._dials(plan)
        fragment = plan_fragment(plan.points, plan.vias, plan.preset, dials, plan.sent)
        notes = list(notes)
        # The link opens this exact line in the app, as its Share does, so the map, Start ride
        # and the app's GPX are this route; the plan's inputs ride along for editing.
        link = f"{self.api.base}/{fragment}"
        try:
            route_id = secrets.token_hex(16)
            self.api.share(
                {"id": route_id, **kept_route(plan, name, fragment, dials), **draft_link_keep()}
            )
            link = f"{self.api.base}/s/{route_id}{fragment}&route={route_id}"
        except ToolError as error:
            notes.append(
                f"{error}; the link plans the route again when opened, so it can differ a little"
            )
        out = {
            "draft_id": draft_id,
            "summary": summary(plan.answer),
            **route_details(plan),
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
        out["credit"] = plan.answer.get("attribution", [])
        return out

    def _plan_and_fix(
        self, call: Call, points, vias, preset, options, limit, rounds, trim_spurs=True
    ):
        notes: list[str] = []
        call.report(0, rounds + 1, "planning the route")
        plan = self._plan(call, points, vias, preset, options, limit)
        for done in range(rounds if limit else 0):
            fix = with_metro_fix(plan, self.stations)
            if fix is None:
                break
            if not call.time_for_another_plan():
                notes.append(OUT_OF_TIME)
                break
            new_points, new_vias, station = fix
            call.report(done + 1, rounds + 1, f"replanning by way of {station}")
            again = self._plan(call, new_points, new_vias, preset, options, limit)
            notes.append(
                f"added {station} as a via point: {plan.check['miles_over_limit']} -> "
                f"{again.check['miles_over_limit']} mi over the limit"
            )
            if again.check["miles_over_limit"] <= plan.check["miles_over_limit"]:
                plan = again
        pruned = without_spurs(plan) if trim_spurs else None
        if pruned is not None and call.time_for_another_plan():
            # A via point off the road through (a pier's end, a landmark beside a trail) is
            # reached by an out-and-back (the owner, 2026-10-24: "Avoid pointless out and backs
            # and short spurs"): it moves to where the spur leaves the road and is planned again.
            new_points, new_vias, moved = pruned
            call.report(rounds + 1, rounds + 2, "planning again without out-and-backs")
            again = self._plan(call, new_points, new_vias, preset, options, limit)
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
            out["note"] = "the link downloads the file; it works while the draft is kept"
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
        else:
            dials = self._dials(plan)
            fragment = plan_fragment(plan.points, plan.vias, plan.preset, dials, plan.sent)
            saved = self.api.save(kept_route(plan, name, fragment, dials))
            out["saved"] = {
                "id": saved.get("id"),
                "name": saved.get("name"),
                "where": "My routes on the site",
            }
            if plan.check is not None and not plan.check["ok"]:
                notes.append(
                    f"saved although {plan.check['miles_over_limit']} mi of it is more than"
                    f" {plan.check['limit_mi']:g} mi from Metro"
                )
        if notes:
            out["notes"] = notes
        return out

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
            fragment = plan_fragment(plan.points, plan.vias, plan.preset, dials, plan.sent)
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
        has_points = "p" in urllib.parse.parse_qs(fragment)
        shared = None
        if shared_id:
            try:
                shared = self.api.shared_route(shared_id)
            except ToolError:
                if not has_points:
                    raise
        if shared is not None and not has_points:
            fragment = (shared.get("inputs") or {}).get("hash") or ""
            if "p=" not in fragment:
                raise ToolError(
                    "that shared route keeps no plan to continue from (an opened file?)"
                )
        if not fragment:
            match = re.search(r"(?:^|[#&?])(p=.*)$", link)
            fragment = match.group(1) if match else ""
        points, vias, preset, options = parse_fragment(fragment)
        limit = args.get("max_miles_from_metro")
        answer = (shared or {}).get("answer")
        kept_hash = str(((shared or {}).get("inputs") or {}).get("hash") or "").lstrip("#")
        asked_hash = re.sub(r"&route=[^&]*", "", fragment).lstrip("#")
        if has_points and asked_hash != kept_hash:
            answer = None  # the rider changed the route in the app: plan what the link says now
        if isinstance(answer, dict) and (answer.get("geometry") or {}).get("coordinates"):
            # The exact route that was shared: kept as it is, not planned again.
            line = answer["geometry"]["coordinates"]
            check = metro_check(line, limit, self.stations) if limit else None
            sent = request_body(points, vias, preset, options)
            plan = Plan(list(points), list(vias), preset, answer, check, sent)
            name = str(shared.get("name") or "RouteMaker route")
            return self._draft(plan, options, limit, [], name)
        plan, notes = self._plan_and_fix(call, points, vias, preset, options, limit, 0)
        return self._draft(plan, options, limit, notes, "RouteMaker route")

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
            options = {k: v for k, v in options.items() if k in ("loop", "when")}
        options.update({k: v for k, v in self._options(args).items() if k in args})
        if "target_miles" in args:
            options["target_distance_m"] = self._options(args).get("target_distance_m")
        if "rider_weight_lb" in args:
            options["system_weight_kg"] = self._options(args).get("system_weight_kg")
        limit = args.get("max_miles_from_metro", draft.limit)
        for key in args.get("clear_settings") or []:
            if key == "max_miles_from_metro":
                limit = None
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
        revised, notes = self._plan_and_fix(
            call, points, vias, preset, options, limit, rounds, trim
        )
        return self._draft(
            revised,
            options,
            limit,
            notes,
            draft.name,
            revised_from=draft_id,
            taken=taken,
            trim_spurs=trim,
            intervals=intervals,
        )

    # plan_route
    def plan_route(self, args: dict, call: Call) -> dict:
        taken: list[dict] = []
        points = self._points(list(args["points"]), taken)
        vias = [int(i) for i in args.get("via_points") or []]
        preset = args.get("preset") or "default"
        limit = args.get("max_miles_from_metro")
        options = self._options(args)
        intervals = _intervals_asked(args.get("intervals"))
        if intervals:
            # Every junction, quiet stop signs too, for where an effort must stop.
            options["debug_junctions"] = True
        rounds = int(args.get("fix_metro_rounds") or 0)
        trim = bool(args.get("trim_spurs", True))
        plan, notes = self._plan_and_fix(call, points, vias, preset, options, limit, rounds, trim)
        return self._draft(
            plan,
            options,
            limit,
            notes,
            "RouteMaker route",
            taken=taken,
            trim_spurs=trim,
            intervals=intervals,
        )

    # plan_metro_loop
    def plan_metro_loop(self, args: dict, call: Call) -> dict:
        target = float(args["target_miles"])
        limit = float(args.get("max_miles_from_metro") or 5)
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
        for attempt in range(max_plans):
            if best is not None and not call.time_for_another_plan():
                notes.append(OUT_OF_TIME)
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
                break
            points, vias, station = fix
            notes.append(f"adding {station} where the loop strayed")
        miles = best.answer["distance_m"] / METRES_PER_MILE
        if not 0.85 <= miles / target <= 1.15:
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
        return self._draft(best, options, limit, notes, f"{target:.0f} mi Metro loop", taken=taken)

    def handler(self, name: str):
        if name in POST_TOOLS and not self.posts:
            return None
        return {
            "find_place": self.find_place,
            "metro_stations": self.metro_stations,
            "scenic_roads_near": self.scenic_roads_near,
            "plan_route": self.plan_route,
            "plan_metro_loop": self.plan_metro_loop,
            "open_link": self.open_link,
            "revise_route": self.revise_route,
            "save_route": self.save_route,
            "gpx_route": self.gpx_route,
            "draft_route_post": self.draft_route_post,
        }.get(name)

    def call(self, name: str, args: dict, call: Call | None = None) -> dict:
        handler = self.handler(name)
        if handler is None:
            raise ToolError(f"no tool named {name}")
        try:
            return handler(args or {}, call or Call())
        except KeyError as missing:
            raise ToolError(f"missing argument {missing}") from None
        except (TypeError, ValueError) as wrong:
            raise ToolError(f"an argument is not in the expected form: {wrong}") from None


def _better(plan: Plan, best: Plan, target: float) -> bool:
    """Fewer miles over the Metro limit first, then no out-and-back spurs, then nearer the
    target length."""

    def key(p: Plan):
        miles = p.answer["distance_m"] / METRES_PER_MILE
        return (p.check["miles_over_limit"], without_spurs(p) is not None, abs(miles - target))

    return key(plan) < key(best)


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
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": (
                "RouteMaker plans bike routes from DC to Baltimore, rated by traffic stress (LTS 1"
                " calmest to 4, plus Avoid). Pick the ride type and settings that fit the ask."
                " Give distances in miles first, km in brackets. Share the link so the rider can"
                " open the route in the app; save to My routes only when asked."
            ),
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": server.tools()}
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
                "content": [{"type": "text", "text": json.dumps(payload, indent=1)}],
                "structuredContent": payload,
                "isError": False,
            }
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
