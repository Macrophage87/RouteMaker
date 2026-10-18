"""Where Metro's next train is, for a rider waiting to board it (v0.9.0).

The owner: "When waiting for each, can you show where the next train or bus is?" WMATA gives no
train a map point. It gives each train's track circuit (`TrainPositions/TrainPositions`) and each
line's circuits in order along each track, with the station at a station's circuits
(`TrainPositions/StandardRoutes`). So the next train the rider's way is the nearest train of the
step's line on the track that runs from the boarding station toward the alighting one, on a
circuit before the boarding station's; and where it is is said by the stations around it: "Next
Red Line train is at Dupont Circle, 2 stations away." Its map mark is that station's point, or
halfway between the two stations it is between.

How often: the positions are one call for the whole deployment at most every `CACHE_TTL_S` (20 s),
and only while a rider is waiting at a boarding (GET /api/transit/next-vehicle); the standard
routes are read once a day. Shared by the workers through one row of `bikeshare_feed_cache` (key
`ROW_KEY`), as Metro's next trains are (core.wmata_live). A reading is not served once older than
its 20 s: a position minutes old is no position, and nothing is shown.

The key and its rules are core.wmata_live's. Every value carries "Data: WMATA".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import wmata_live

API = wmata_live.API
POSITIONS_URL = f"{API}/TrainPositions/TrainPositions?contentType=json"
ROUTES_URL = f"{API}/TrainPositions/StandardRoutes?contentType=json"
ROW_KEY = "wmata-trains"
LOCK_KEY = 0x776D7472  # "wmtr"
CACHE_TTL_S = 20.0

# The line codes TrainPositions uses, by the timetable's names (core.wmata_live.LINES).
CODES = {name: code for code, name in wmata_live.LINES.items()}


@dataclass(frozen=True)
class Circuit:
    circuit: int
    station: str | None  # the station code at a station's circuit


@dataclass(frozen=True)
class TrainAt:
    train: str
    circuit: int
    line: str  # "RD"
    destination: str | None  # a station code
    direction: int | None


@dataclass(frozen=True)
class Board:
    """One reading: every line's tracks, circuits in order, and the trains on them."""

    as_of: float
    routes: dict[tuple[str, int], tuple[Circuit, ...]]
    trains: tuple[TrainAt, ...]
    stale: bool = False


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_routes(doc) -> dict[tuple[str, int], tuple[Circuit, ...]]:
    out: dict[tuple[str, int], tuple[Circuit, ...]] = {}
    items = doc.get("StandardRoutes") if isinstance(doc, dict) else None
    for item in items if isinstance(items, list) else ():
        if not isinstance(item, dict):
            continue
        line = wmata_live._text(item.get("LineCode")).upper()
        track = _int(item.get("TrackNum"))
        circuits = item.get("TrackCircuits")
        if line not in wmata_live.LINES or track is None or not isinstance(circuits, list):
            continue
        rows = []
        for c in circuits:
            if not isinstance(c, dict) or _int(c.get("CircuitId")) is None:
                continue
            rows.append((_int(c.get("SeqNum")) or 0, c))
        rows.sort(key=lambda r: r[0])
        out[(line, track)] = tuple(
            Circuit(int(c["CircuitId"]), wmata_live._text(c.get("StationCode")) or None)
            for _seq, c in rows
        )
    return out


def parse_positions(doc) -> tuple[TrainAt, ...]:
    out = []
    items = doc.get("TrainPositions") if isinstance(doc, dict) else None
    for item in items if isinstance(items, list) else ():
        if not isinstance(item, dict):
            continue
        circuit = _int(item.get("CircuitId"))
        line = wmata_live._text(item.get("LineCode")).upper()
        service = wmata_live._text(item.get("ServiceType"))
        if circuit is None or line not in wmata_live.LINES or service not in ("", "Normal"):
            continue
        out.append(
            TrainAt(
                train=wmata_live._text(item.get("TrainId")),
                circuit=circuit,
                line=line,
                destination=wmata_live._text(item.get("DestinationStationCode")) or None,
                direction=_int(item.get("DirectionNum")),
            )
        )
    return tuple(out)


def build(docs: dict[str, Any], as_of: float, stale: bool = False) -> Board:
    routes = parse_routes(docs.get("routes"))
    if not routes:
        raise wmata_live.Unavailable("the standard routes could not be read")
    return Board(as_of, routes, parse_positions(docs.get("positions")), stale)


@dataclass(frozen=True)
class Approach:
    """Where the next train the rider's way is, by the stations around it."""

    line: str  # "Red Line"
    at: str | None  # the station code it is at
    back: str | None  # between stations: the one behind it
    ahead: str | None  # and the one ahead of it
    away: int  # stations still to call at before the boarding station, the boarding one counted


def next_train(board: Board, line: str, boarding: set[str], alighting: set[str]) -> Approach | None:
    """The nearest train of `line` ("Red Line") coming to a station (`boarding`, its codes: its
    own and its other platforms') on the track that goes on to `alighting`; None where there is
    none, or the line runs no track between the two."""
    code = CODES.get(line) or next(
        (c for n, c in CODES.items() if wmata_live.same_line(n, line)), None
    )
    if code is None:
        return None
    for (route_line, _track), circuits in board.routes.items():
        if route_line != code:
            continue
        stations = [(i, c.station) for i, c in enumerate(circuits) if c.station]
        here = next((i for i, s in stations if s in boarding), None)
        there = next((i for i, s in stations if s in alighting), None)
        if here is None or there is None or there <= here:
            continue
        index = {c.circuit: i for i, c in enumerate(circuits)}
        behind = [
            index[t.circuit]
            for t in board.trains
            if t.line == code and t.circuit in index and index[t.circuit] <= here
        ]
        if not behind:
            return None
        where = max(behind)
        away = sum(1 for i, _s in stations if where < i <= here)
        at = circuits[where].station
        if at:
            return Approach(line, at, None, None, away)
        back = next((s for i, s in reversed(stations) if i < where), None)
        ahead = next((s for i, s in stations if i > where), None)
        return Approach(line, None, back, ahead, away)
    return None


def words(approach: Approach, live: wmata_live.Snapshot) -> tuple[str, Any] | None:
    """The line said ("Next Red Line train is at Dupont Circle, 2 stations away.") and its map
    point ([lon, lat]): the station's, or halfway between the two; None where a station is not
    known."""

    def station(code):
        return live.stations.get(code or "")

    count = "1 station away" if approach.away == 1 else f"{approach.away} stations away"
    lead = f"Next {approach.line} train is"
    if approach.at:
        found = station(approach.at)
        if found is None:
            return None
        if approach.away == 0:
            return f"{lead} at {found.name} now.", [found.lon, found.lat]
        return f"{lead} at {found.name}, {count}.", [found.lon, found.lat]
    ahead = station(approach.ahead)
    back = station(approach.back)
    if ahead is None:
        return None
    if back is None:
        return f"{lead} on its way to {ahead.name}, {count}.", [ahead.lon, ahead.lat]
    point = [round((back.lon + ahead.lon) / 2, 6), round((back.lat + ahead.lat) / 2, 6)]
    return f"{lead} between {back.name} and {ahead.name}, {count}.", point


# The one cache of the process: one reading for every worker, every 20 s at most while asked.
client = wmata_live.Live(
    store=wmata_live.DatabaseStore(ROW_KEY, LOCK_KEY),
    urls={"positions": POSITIONS_URL},
    daily={"routes": ROUTES_URL},
    builder=build,
    ttl=CACHE_TTL_S,
    grace=0.0,
    name="wmata trains",
)
