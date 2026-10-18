"""Metrobus live: the next buses at a bus step's boarding stop, and where the next one is (v0.9.0).

The same as Metro's next trains (core.wmata_live, v0.7.0), for a bus: a plan's Metrobus step adds
"Live: bus 52 in 4 min, 13 min.", marked live and credited "Data: WMATA"; its own times stay the
timetable's ("scheduled"). And while a rider waits at the stop (GET /api/transit/next-vehicle),
where the next bus is: "Bus 52 is 0.8 mi away (1.3 km), 3 stops back."

What is read (WMATA's developer API; the key and its rules are core.wmata_live's: only ever in
the `api_key` header):

- `Bus.svc/json/jStops?Lat=&Lon=&Radius=`: the stops near a point, each with WMATA's StopID and
  the routes that serve it. The installed timetable keeps no GTFS stop code (a bus stop there is a
  name and a point, scripts/build_transit_schedule.py), and carrying it would need the schedule
  file rebuilt, so the boarding stop is found by its point: the nearest WMATA stop within
  `STOP_NEAR_M` that the step's route serves. Kept a day.
- `NextBusService.svc/json/jPredictions?StopID=`: a stop's next buses, by route and direction,
  each with its bus (VehicleID). Kept `PREDICTIONS_TTL_S` (40 s).
- `Bus.svc/json/jBusPositions?RouteID=`: a route's buses and their points, for where the next one
  is. Kept `POSITIONS_TTL_S` (20 s), and read only while someone is waiting.

Limits (WMATA: 10 calls a second, 50,000 a day): a plan asks for its chosen trip's bus steps only,
at most `MAX_STOPS` (4), at once, all within `PLAN_BUDGET_S` (1.5 s), so a slow WMATA never holds
a plan up noticeably. Every call is counted deployment-wide (core.wmata_live.SharedBudget: 18 a
minute and 4 a second at most); a call over it is not made, and that step shows nothing live.
No reading (no key, WMATA down, over the budget, no stop or route matched) adds nothing.
"""

from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
import urllib.parse
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Any

from . import wmata_live

logger = logging.getLogger(__name__)

API = wmata_live.API
STOPS_URL = f"{API}/Bus.svc/json/jStops"
PREDICTIONS_URL = f"{API}/NextBusService.svc/json/jPredictions"
POSITIONS_URL = f"{API}/Bus.svc/json/jBusPositions"

METROBUS = "Metrobus"
STOP_NEAR_M = 60.0
STOP_SEARCH_M = 120
STOPS_TTL_S = 24 * 3600.0
PREDICTIONS_TTL_S = 40.0
POSITIONS_TTL_S = 20.0
FAILED_TTL_S = 15.0
TIMEOUT_S = 1.2
PLAN_BUDGET_S = 1.5
MAX_STOPS = 4
BUSES_SHOWN = 2
KEPT_MAX = 2000
METRES_PER_MILE = 1609.344


@dataclass(frozen=True)
class BusStop:
    stop_id: str
    name: str
    lon: float
    lat: float
    routes: tuple[str, ...]


@dataclass(frozen=True)
class Prediction:
    route: str
    direction: str  # "0" or "1"
    direction_text: str  # "North to Silver Spring Station"
    minutes: int
    vehicle: str | None


@dataclass(frozen=True)
class BusAt:
    vehicle: str
    route: str
    lon: float
    lat: float


def same_route(a: str, b: str) -> bool:
    """One Metrobus route: "52" and "52", or a WMATA variant ("52v1") of the timetable's "52"."""

    def base(name: str) -> str:
        return re.sub(r"v\d+$", "", name.strip()).upper()

    return bool(a.strip()) and base(a) == base(b)


def parse_stops(doc) -> tuple[BusStop, ...]:
    out = []
    items = doc.get("Stops") if isinstance(doc, dict) else None
    for item in items if isinstance(items, list) else ():
        if not isinstance(item, dict):
            continue
        stop_id = wmata_live._text(item.get("StopID"))
        try:
            lat, lon = float(item.get("Lat")), float(item.get("Lon"))
        except (TypeError, ValueError):
            continue
        routes = item.get("Routes")
        if not stop_id or not isinstance(routes, list):
            continue
        out.append(
            BusStop(
                stop_id,
                wmata_live._text(item.get("Name")),
                lon,
                lat,
                tuple(r.strip() for r in routes if isinstance(r, str) and r.strip()),
            )
        )
    return tuple(out)


def parse_predictions(doc) -> tuple[Prediction, ...]:
    out = []
    items = doc.get("Predictions") if isinstance(doc, dict) else None
    for item in items if isinstance(items, list) else ():
        if not isinstance(item, dict):
            continue
        route = wmata_live._text(item.get("RouteID"))
        try:
            minutes = int(item.get("Minutes"))
        except (TypeError, ValueError):
            continue
        if not route or not 0 <= minutes <= 90:
            continue
        out.append(
            Prediction(
                route=route,
                direction=str(item.get("DirectionNum", "")).strip(),
                direction_text=wmata_live._text(item.get("DirectionText")),
                minutes=minutes,
                vehicle=wmata_live._text(item.get("VehicleID")) or None,
            )
        )
    return tuple(out)


def parse_positions(doc) -> tuple[BusAt, ...]:
    out = []
    items = doc.get("BusPositions") if isinstance(doc, dict) else None
    for item in items if isinstance(items, list) else ():
        if not isinstance(item, dict):
            continue
        vehicle = wmata_live._text(item.get("VehicleID"))
        try:
            lat, lon = float(item.get("Lat")), float(item.get("Lon"))
        except (TypeError, ValueError):
            continue
        if vehicle and -90 <= lat <= 90 and -180 <= lon <= 180:
            out.append(BusAt(vehicle, wmata_live._text(item.get("RouteID")), lon, lat))
    return tuple(out)


# --- Matching -------------------------------------------------------------------------------

COMPASS = {"north": (0.0, 1.0), "south": (0.0, -1.0), "east": (1.0, 0.0), "west": (-1.0, 0.0)}


def _heading(text: str) -> tuple[float, float] | None:
    """The compass way WMATA's direction words start with ("North to ...", "NORTHBOUND")."""
    words = re.findall(r"[a-z]+", text.lower())
    if not words:
        return None
    first = words[0].removesuffix("bound")
    return COMPASS.get(first)


def stop_for(stops, point, route: str) -> BusStop | None:
    """The nearest stop within `STOP_NEAR_M` of `point` that `route` serves."""
    best: tuple[float, BusStop] | None = None
    for stop in stops:
        if not any(same_route(r, route) for r in stop.routes):
            continue
        d = wmata_live._metres(point, (stop.lon, stop.lat))
        if d <= STOP_NEAR_M and (best is None or d < best[0]):
            best = (d, stop)
    return None if best is None else best[1]


def coming(predictions, route: str, board, alight) -> list[Prediction]:
    """The next buses of `route` the step's way, soonest first. A stop that sees the route one
    way only needs no more; where it sees both, the way is the one whose compass word ("North to
    ...") is nearest the step's own heading, board to alight. None matched: an empty list."""
    mine = [p for p in predictions if same_route(p.route, route)]
    ways: dict[str, list[Prediction]] = {}
    for p in mine:
        ways.setdefault(p.direction, []).append(p)
    if len(ways) > 1:
        if alight is None:
            return []
        lat = math.radians((board[1] + alight[1]) / 2)
        dx, dy = (alight[0] - board[0]) * math.cos(lat), alight[1] - board[1]
        size = math.hypot(dx, dy)
        if size == 0:
            return []
        scored = []
        for key, group in ways.items():
            heading = _heading(group[0].direction_text)
            if heading is not None:
                scored.append(((heading[0] * dx + heading[1] * dy) / size, key))
        if not scored:
            return []
        score, key = max(scored)
        if score < 0.3:
            return []
        mine = ways[key]
    return sorted(mine, key=lambda p: p.minutes)


def bus_minutes(p: Prediction) -> str:
    return "arriving" if p.minutes == 0 else f"{p.minutes} min"


def live_words(route: str, buses: list[Prediction]) -> dict | None:
    """The step's live line, as a Metro step's (core.transit_live.step_live)."""
    if not buses:
        return None
    shown = buses[:BUSES_SHOWN]
    times = [bus_minutes(p) for p in shown]
    if times[0] == "arriving":
        then = f", next in {times[1]}" if len(times) > 1 else ""
        text = f"Live: bus {route} arriving{then}."
    else:
        text = f"Live: bus {route} in {', '.join(times)}."
    return {
        "text": text,
        "minutes": [p.minutes for p in shown],
        "source": "live",
    }


def distance_words(metres: float) -> str:
    """US first, metric in brackets: "0.8 mi away (1.3 km)"; "500 ft away (150 m)" when near."""
    miles = metres / METRES_PER_MILE
    if miles < 0.1:
        feet = max(50, round(metres * 3.28084 / 50) * 50)
        return f"{feet} ft away ({max(10, round(metres / 10) * 10)} m)"
    return f"{miles:.1f} mi away ({metres / 1000:.1f} km)"


def where_words(route: str, metres: float, back: int | None) -> str:
    """ "Bus 52 is 0.8 mi away (1.3 km), 3 stops back." """
    if back == 0:
        return f"Bus {route} is at your stop."
    tail = "" if back is None else (", 1 stop back" if back == 1 else f", {back} stops back")
    return f"Bus {route} is {distance_words(metres)}{tail}."


# --- The client -----------------------------------------------------------------------------


class Kept:
    """A few answers kept a while, by key, in this process (bounded)."""

    def __init__(self, wall: Callable[[], float]) -> None:
        self._wall = wall
        self._lock = threading.Lock()
        self._items: dict[Any, tuple[float, float, Any]] = {}

    def get(self, key) -> tuple[bool, Any]:
        with self._lock:
            hit = self._items.get(key)
            if hit is None:
                return False, None
            at, ttl, value = hit
            age = self._wall() - at
            if 0 <= age < ttl:
                return True, value
            del self._items[key]
            return False, None

    def put(self, key, value, ttl: float) -> None:
        with self._lock:
            if len(self._items) >= KEPT_MAX:
                self._items.pop(next(iter(self._items)))
            self._items[key] = (self._wall(), ttl, value)


@dataclass(frozen=True)
class Reading:
    value: Any
    as_of: float


@dataclass(frozen=True)
class StepLives:
    """A plan's live bus lines, by step index, and when the oldest was read (or None)."""

    steps: dict[int, dict]
    as_of: float | None


class Buses:
    def __init__(
        self,
        fetch: wmata_live.Fetch = wmata_live.http_get,
        budget: wmata_live.Budget | None = None,
        wall: Callable[[], float] = time.time,
        enabled: Callable[[], bool] = wmata_live.configured,
    ) -> None:
        self._fetch = fetch
        self._budget = budget if budget is not None else wmata_live.SharedBudget()
        self._wall = wall
        self._enabled = enabled
        self._kept = Kept(wall)
        self.calls = 0

    def _get(self, url: str, key, ttl: float, parse) -> Reading | None:
        """One document, from the kept copy or WMATA (counted in the budget); None: no reading."""
        found, value = self._kept.get(key)
        if found:
            return value
        if not self._budget.take():
            return None
        self.calls += 1
        try:
            reading = Reading(parse(json.loads(self._fetch(url, TIMEOUT_S))), self._wall())
        except (wmata_live.Unavailable, ValueError) as error:
            if not isinstance(error, wmata_live.Unavailable):
                error = f"{urllib.parse.urlsplit(url).path}: not JSON"
            logger.warning("wmata bus: %s", error)
            self._kept.put(key, None, FAILED_TTL_S)
            return None
        self._kept.put(key, reading, ttl)
        return reading

    def stop(self, point, route: str) -> BusStop | None:
        lon, lat = round(point[0], 5), round(point[1], 5)
        query = urllib.parse.urlencode(
            {"Lat": f"{lat:.5f}", "Lon": f"{lon:.5f}", "Radius": STOP_SEARCH_M}
        )
        got = self._get(f"{STOPS_URL}?{query}", ("stops", lon, lat), STOPS_TTL_S, parse_stops)
        return None if got is None else stop_for(got.value, (lon, lat), route)

    def predictions(self, stop_id: str) -> Reading | None:
        query = urllib.parse.urlencode({"StopID": stop_id})
        return self._get(
            f"{PREDICTIONS_URL}?{query}", ("next", stop_id), PREDICTIONS_TTL_S, parse_predictions
        )

    def positions(self, route: str) -> Reading | None:
        query = urllib.parse.urlencode({"RouteID": route})
        return self._get(
            f"{POSITIONS_URL}?{query}", ("where", route.upper()), POSITIONS_TTL_S, parse_positions
        )

    def next_buses(
        self, route: str, board, alight
    ) -> tuple[list[Prediction], BusStop, float] | None:
        stop = self.stop(board, route)
        if stop is None:
            return None
        got = self.predictions(stop.stop_id)
        if got is None:
            return None
        return coming(got.value, route, (stop.lon, stop.lat), alight), stop, got.as_of

    def step_live(self, route: str, board, alight) -> tuple[dict, float] | None:
        """A bus step's live line ("Live: bus 52 in 4 min, 13 min.") and when it was read."""
        found = self.next_buses(route, board, alight)
        if found is None:
            return None
        buses, _stop, as_of = found
        words = live_words(route, buses)
        return None if words is None else (words, as_of)

    def _step_live_apart(self, route: str, board, alight):
        """`step_live` in a thread of its own, which gives back the database connection the
        budget opened in it."""
        try:
            return self.step_live(route, board, alight)
        finally:
            try:
                from django.db import connections

                connections.close_all()
            except Exception:  # noqa: BLE001
                pass

    def lives(self, legs) -> StepLives:
        """The live lines of a plan's bus steps (`legs`: (index, route, board, alight)), the
        first `MAX_STOPS`, asked at once and given up after `PLAN_BUDGET_S`."""
        legs = list(legs)[:MAX_STOPS]
        if not legs or not self._enabled():
            return StepLives({}, None)
        pool = ThreadPoolExecutor(max_workers=len(legs))
        try:
            futures = {
                index: pool.submit(self._step_live_apart, route, board, alight)
                for index, route, board, alight in legs
            }
            deadline = time.monotonic() + PLAN_BUDGET_S
            steps, times = {}, []
            for index, future in futures.items():
                try:
                    got = future.result(timeout=max(0.0, deadline - time.monotonic()))
                except FutureTimeout:
                    logger.warning("wmata bus: no answer in time")
                    continue
                except Exception as error:  # noqa: BLE001 - a bus line is never worth a plan
                    logger.warning("wmata bus: %s", type(error).__name__)
                    continue
                if got is not None:
                    steps[index], _ = got
                    times.append(got[1])
            return StepLives(steps, min(times) if times else None)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def where(
        self, route: str, board, alight, stops_back: Callable[[Any], int | None] | None = None
    ) -> dict | None:
        """Where the next bus the step's way is: {"text", "point", "away", "as_of"}, or None."""
        if not self._enabled():
            return None
        found = self.next_buses(route, board, alight)
        if found is None:
            return None
        buses, stop, _as_of = found
        first = next((p for p in buses if p.vehicle), None)
        if first is None:
            return None
        got = self.positions(first.route)
        if got is None:
            return None
        bus = next((b for b in got.value if b.vehicle == first.vehicle), None)
        if bus is None:
            return None
        point = (bus.lon, bus.lat)
        metres = wmata_live._metres(point, (stop.lon, stop.lat))
        back = stops_back(point) if stops_back is not None else None
        return {
            "text": where_words(route, metres, back),
            "point": [round(bus.lon, 6), round(bus.lat, 6)],
            "away": back,
            "metres": round(metres),
            "as_of": got.as_of,
        }


# The one client of the process: its answers kept here; its calls counted for every worker.
client = Buses()
