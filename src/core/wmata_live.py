"""WMATA's live data: Metro's next trains, its rail incidents and its elevator outages (v0.7.0).

The owner, 2026-10-13 11:16 UTC: "Can live values be implemented as well as station incident's
like elevator closures and the like?" Then (11:17 UTC): "Elevator outages don't stop a ride
outright, because many people can walk their bike upstairs." So an outage is a warning, never an
avoidance: "Elevator out at Gallery Place: carry your bike on the stairs" (WMATA bars bikes on
escalators), and a small ranking cost (`ELEVATOR_OUT_S`, `core.transit_live`) so a station whose
elevator works wins a near-tie.

What is read (WMATA's developer API, <https://developer.wmata.com/>; the key is WMATA's, sent only
as its `api_key` header, never in a URL):

- `Rail.svc/json/jStations`: the stations, their codes, names and points (kept a day);
- `StationPrediction.svc/json/GetPrediction/All`: every station's next trains;
- `Incidents.svc/json/Incidents`: rail incidents (delays, single-tracking, closures);
- `Incidents.svc/json/ElevatorIncidents`: elevators and escalators out of service.

How often: one reading for the whole deployment at most every `CACHE_TTL_S` (45 s), and only
while someone is asking (a plan or a station card): WMATA allows 10 calls a second and 50,000 a
day, and three calls a reading every 45 s is under 6,000 a day. The API workers share the reading
through one row of `bikeshare_feed_cache` (key `ROW_KEY`; the table is "one current copy of a
live third-party feed per key", core.models.BikeshareFeedCache), replaced in place: no history.
A worker that finds it out of date and wins a PostgreSQL advisory lock reads WMATA; the others
use its row. A failed reading pauses `FAILURE_PAUSE_S` and the last one is served for
`STALE_GRACE_S` more, after which there is no live data and every time is the timetable's
("scheduled").

The key: the environment variable `KEY_ENV` (`WMATA_API_KEY`, the name the static GTFS fetch
already uses, systems.json `key_env`), set on the server by the owner. With no key nothing is
fetched and nothing is live. The key is never logged, never in a URL, never sent to a browser.

Every live value the page shows carries `CREDIT` ("Data: WMATA").
"""

from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

logger = logging.getLogger(__name__)

KEY_ENV = "WMATA_API_KEY"
KEY_HEADER = "api_key"
API = "https://api.wmata.com"
ALLOWED_HOSTS = frozenset({"api.wmata.com"})
STATIONS_URL = f"{API}/Rail.svc/json/jStations"
PREDICTIONS_URL = f"{API}/StationPrediction.svc/json/GetPrediction/All"
INCIDENTS_URL = f"{API}/Incidents.svc/json/Incidents"
ELEVATORS_URL = f"{API}/Incidents.svc/json/ElevatorIncidents"

CREDIT = "Data: WMATA"
ROW_KEY = "wmata"

CACHE_TTL_S = 45.0
STALE_GRACE_S = 120.0
FAILURE_PAUSE_S = 15.0
STATIONS_TTL_S = 24 * 3600.0
SHARED_WAIT_S = 4.0
SHARED_POLL_S = 0.25
TIMEOUT_S = 3.0
REFRESH_BUDGET_S = 3.0
MAX_BYTES = 4_000_000
USER_AGENT = "RouteMaker-transit-live"

# A map point this close to a WMATA station is that station (the transit planner's
# STATION_NEAR_M).
STATION_NEAR_M = 400.0

# WMATA's line codes, as the timetable names the lines ("Red Line").
LINES = {
    "RD": "Red Line",
    "BL": "Blue Line",
    "OR": "Orange Line",
    "SV": "Silver Line",
    "GR": "Green Line",
    "YL": "Yellow Line",
}


class Unavailable(Exception):
    """No live reading could be had."""


Fetch = Callable[[str, float], bytes]


def api_key() -> str:
    """The key, from `settings.WMATA_API_KEY` (the environment variable `KEY_ENV`)."""
    from django.conf import settings

    return (getattr(settings, "WMATA_API_KEY", "") or "").strip()


def configured() -> bool:
    return bool(api_key())


# Query names that would put a key in a URL: refused, so the key can only ever travel in its header.
KEY_PARAMS = frozenset({"api_key", "apikey", "subscription-key", "key"})


def _allowed(url: str) -> bool:
    """A WMATA API URL. Its query may name what is asked for (a stop, a route; v0.9.0) but never a
    key: the key goes in the `api_key` header only."""
    parts = urllib.parse.urlsplit(url)
    names = {
        name.lower() for name, _ in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    }
    return parts.scheme == "https" and parts.hostname in ALLOWED_HOSTS and not names & KEY_PARAMS


class _SameHostOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _allowed(newurl):
            raise urllib.error.URLError("a redirect off WMATA's API host was refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SameHostOnly)


def http_get(url: str, timeout: float) -> bytes:
    """GET one WMATA API URL with the key in its header. Errors name the URL's path only:
    the key is never in a URL, and never in a message."""
    key = api_key()
    if not key:
        raise Unavailable("no WMATA key is set")
    if not _allowed(url):
        raise Unavailable("not a WMATA API URL")
    path = urllib.parse.urlsplit(url).path
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT, KEY_HEADER: key},
    )
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            body = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise Unavailable(f"{path}: HTTP {error.code}") from None
    except (TimeoutError, urllib.error.URLError, ConnectionError, OSError) as error:
        raise Unavailable(f"{path}: {type(error).__name__}") from None
    if len(body) > MAX_BYTES:
        raise Unavailable(f"{path}: larger than expected")
    return body


# --- Parsed data ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Station:
    code: str
    name: str
    lon: float
    lat: float
    together: tuple[str, ...] = ()  # the codes of the same station's other platforms
    lines: tuple[str, ...] = ()  # "Red Line", ...


@dataclass(frozen=True)
class Train:
    station: str  # the station code it is predicted at
    line: str  # "Red Line"; "" where WMATA gives none (a train not in service)
    destination: str
    destination_code: str | None
    minutes: int | None  # None: no time given
    arriving: bool  # "ARR"
    boarding: bool  # "BRD"
    group: str


@dataclass(frozen=True)
class Incident:
    lines: tuple[str, ...]  # "Red Line", ...
    kind: str  # "Delay", "Alert"
    text: str


@dataclass(frozen=True)
class Outage:
    station: str  # the station code
    station_name: str
    unit: str  # "ELEVATOR" or "ESCALATOR"
    where: str
    back: str | None  # the estimated return, as WMATA gives it


@dataclass(frozen=True)
class Snapshot:
    as_of: float  # epoch seconds of the reading
    stations: dict[str, Station]
    trains: tuple[Train, ...] = ()
    incidents: tuple[Incident, ...] = ()
    outages: tuple[Outage, ...] = ()
    stale: bool = False

    def station_near(self, point, limit_m: float = STATION_NEAR_M) -> Station | None:
        """The nearest WMATA station within `limit_m` of `point` ([lon, lat])."""
        best: tuple[float, Station] | None = None
        for station in self.stations.values():
            d = _metres(point, (station.lon, station.lat))
            if d <= limit_m and (best is None or d < best[0]):
                best = (d, station)
        return None if best is None else best[1]

    def codes(self, station: Station) -> tuple[str, ...]:
        """A station's codes: its own and its other platforms' (Metro Center A01 and C01)."""
        return (station.code, *station.together)

    def name_of(self, code: str | None) -> str | None:
        station = self.stations.get(code or "")
        return None if station is None else station.name

    def elevators_out(self, station: Station) -> list[Outage]:
        codes = set(self.codes(station))
        return [o for o in self.outages if o.station in codes and o.unit == "ELEVATOR"]

    def trains_at(self, station: Station) -> list[Train]:
        codes = set(self.codes(station))
        return [t for t in self.trains if t.station in codes and t.line]

    def lines_at(self, station: Station) -> list[str]:
        """The lines that call at a station, its other platforms' too."""
        out: list[str] = []
        for code in self.codes(station):
            found = self.stations.get(code)
            for line in found.lines if found else ():
                if line not in out:
                    out.append(line)
        return out

    def closed(self) -> dict[str, str]:
        """The stations WMATA's incidents say are closed now: {code: the sentence that says so}.

        Rail incidents carry no station codes, only words ("As a result, Rosslyn and Court House
        stations are closed."), so a station counts as closed when a sentence that says
        "closed" (and not "open" or "reopen") names it. A sentence about the future ("will be
        closed starting Monday") is left out; one that names no station closes nothing."""
        out: dict[str, str] = {}
        for incident in self.incidents:
            # Clauses, not only sentences: "Rosslyn is closed; parking is free at Ballston-MU."
            for sentence in re.split(r"(?<=[.!?;])\s+", incident.text):
                words = sentence.lower()
                if not CLOSED_WORDS.search(words) or OPEN_WORDS.search(words):
                    continue
                if FUTURE_WORDS.search(words) or PART_CLOSED.search(words):
                    continue
                for station in self._named_in(words):
                    for code in self.codes(station):
                        out.setdefault(code, sentence)
        return out

    def named(self) -> set[str]:
        """The codes of every station an incident names, closed or not (the owner, 2026-10-18:
        "Put a little notice marker on all the stations that have alerts"). A line-wide
        incident that names no station marks none."""
        out: set[str] = set()
        for incident in self.incidents:
            for station in self._named_in(incident.text.lower()):
                out.update(self.codes(station))
        return out

    def elevator_out_codes(self) -> set[str]:
        """The codes of every station with an elevator out, its other platforms' too."""
        out: set[str] = set()
        for outage in self.outages:
            station = self.stations.get(outage.station)
            if outage.unit == "ELEVATOR" and station is not None:
                out.update(self.codes(station))
        return out

    def _named_in(self, words: str) -> list[Station]:
        """The stations lower-case `words` names, each as a whole phrase; a name inside a
        longer station's name where that one is named ("Pentagon" in "Pentagon City") is not."""
        spans: list[tuple[int, int, Station]] = []
        for station in self.stations.values():
            for match in _matches(station.name, words):
                spans.append((match.start(), match.end(), station))
        # A name only in passing is not about the station: a stretch's ends ("between Foggy Bottom
        # and Clarendon", where the shuttles stop) or a train's way ("trains to Ashburn").
        passing = [m.span() for m in BETWEEN.finditer(words)]
        out: list[Station] = []
        for start, end, station in spans:
            if any(s <= start and end <= e and (e - s) > (end - start) for s, e, _ in spans):
                continue
            if any(s <= start and end <= e for s, e in passing):
                continue
            if TOWARD.search(words[max(0, start - 20) : start]):
                continue
            if station not in out:
                out.append(station)
        return out

    def is_closed(self, station: Station) -> bool:
        closed = self.closed()
        return any(code in closed for code in self.codes(station))

    def incidents_on(self, lines) -> list[Incident]:
        """WMATA's incidents on any of `lines` (by colour: "Red Line" is "Metrorail Red")."""
        return [i for i in self.incidents if any(same_line(a, b) for a in lines for b in i.lines)]


# What makes an incident's sentence close the stations it names (`Snapshot.closed`).
CLOSED_WORDS = re.compile(r"\b(closed|closes|closures?)\b")
# A part of a station that is closed (an entrance, an elevator, a garage) leaves the station
# open: the part is what "is closed" ("The L Street entrance at Farragut North is closed").
PART_CLOSED = re.compile(
    r"\b(?:entrances?|exits?|elevators?|escalators?|garages?|parking|lots?|mezzanines?|kiosks?)\b"
    r"(?:(?!\bstations?\b)[^,]){0,60}?\b(?:is|are)\s+(?:temporarily\s+)?closed\b"
)
# A stretch of line between two stations names its ends only in passing (the shuttles stop
# there); the second end is a few words at most.
BETWEEN = re.compile(
    r"\bbetween\b[^.;:]*?\band\b\s+[^.;:,]*?"
    r"(?=\s+(?:due|because|stations?|and|is|are|was|were)\b|[.;:,]|$)"
)
# So does a train's way ("Silver Line trains to Ashburn are delayed").
TOWARD = re.compile(r"\btrains?\s+(?:to|toward|towards|for)\s+$")
OPEN_WORDS = re.compile(r"\b(open|opens|reopen|reopens|reopened)\b")
FUTURE_WORDS = re.compile(r"\b(will|beginning|starting)\b")


def _matches(name: str, words: str):
    """Where lower-case `words` names the station `name` as a whole phrase."""
    return re.finditer(rf"(?<![\w-]){re.escape(name.lower())}(?![\w-])", words)


def same_line(a: str, b: str) -> bool:
    """Whether two names are one Metro line: the colour word they start with ("Red Line" and
    a timetable's "RED" or "Metrorail Red Line")."""
    colours = {name.split()[0].lower() for name in LINES.values()}
    words_a = {w for w in a.lower().split() if w in colours}
    words_b = {w for w in b.lower().split() if w in colours}
    return bool(words_a & words_b)


def _metres(a, b) -> float:
    lat = math.radians((a[1] + b[1]) / 2)
    dx = (a[0] - b[0]) * 111_320.0 * math.cos(lat)
    dy = (a[1] - b[1]) * 110_540.0
    return math.hypot(dx, dy)


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def parse_stations(doc) -> dict[str, Station]:
    out: dict[str, Station] = {}
    items = doc.get("Stations") if isinstance(doc, dict) else None
    for item in items if isinstance(items, list) else ():
        if not isinstance(item, dict):
            continue
        code, name = _text(item.get("Code")), _text(item.get("Name"))
        try:
            lat, lon = float(item.get("Lat")), float(item.get("Lon"))
        except (TypeError, ValueError):
            continue
        if not code or not name or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        together = tuple(
            c
            for c in (_text(item.get("StationTogether1")), _text(item.get("StationTogether2")))
            if c
        )
        lines = tuple(
            LINES[c] for n in range(1, 5) if (c := _text(item.get(f"LineCode{n}")).upper()) in LINES
        )
        out[code] = Station(code, name, lon, lat, together, lines)
    return out


def parse_trains(doc) -> tuple[Train, ...]:
    out = []
    items = doc.get("Trains") if isinstance(doc, dict) else None
    for item in items if isinstance(items, list) else ():
        if not isinstance(item, dict):
            continue
        station = _text(item.get("LocationCode"))
        if not station:
            continue
        raw = _text(item.get("Min")).upper()
        minutes = int(raw) if raw.isdigit() else None
        if minutes is not None and minutes > 90:
            minutes = None
        out.append(
            Train(
                station=station,
                line=LINES.get(_text(item.get("Line")).upper(), ""),
                destination=_text(item.get("DestinationName")) or _text(item.get("Destination")),
                destination_code=_text(item.get("DestinationCode")) or None,
                minutes=0 if raw in ("ARR", "BRD") else minutes,
                arriving=raw == "ARR",
                boarding=raw == "BRD",
                group=_text(item.get("Group")),
            )
        )
    return tuple(out)


def parse_incidents(doc) -> tuple[Incident, ...]:
    out = []
    items = doc.get("Incidents") if isinstance(doc, dict) else None
    for item in items if isinstance(items, list) else ():
        if not isinstance(item, dict):
            continue
        text = " ".join(_text(item.get("Description")).split())
        if not text:
            continue
        codes = [c.strip().upper() for c in _text(item.get("LinesAffected")).split(";")]
        lines = tuple(LINES[c] for c in codes if c in LINES)
        out.append(Incident(lines, _text(item.get("IncidentType")) or "Alert", text))
    return tuple(out)


def parse_outages(doc) -> tuple[Outage, ...]:
    out = []
    items = doc.get("ElevatorIncidents") if isinstance(doc, dict) else None
    for item in items if isinstance(items, list) else ():
        if not isinstance(item, dict):
            continue
        station = _text(item.get("StationCode"))
        unit = _text(item.get("UnitType")).upper()
        if not station or unit not in ("ELEVATOR", "ESCALATOR"):
            continue
        out.append(
            Outage(
                station=station,
                station_name=_text(item.get("StationName")),
                unit=unit,
                where=_text(item.get("LocationDescription")),
                back=_text(item.get("EstimatedReturnToService")) or None,
            )
        )
    return tuple(out)


def build(docs: dict[str, Any], as_of: float, stale: bool = False) -> Snapshot:
    stations = parse_stations(docs.get("stations"))
    if not stations:
        raise Unavailable("the station list could not be read")
    return Snapshot(
        as_of=as_of,
        stations=stations,
        trains=parse_trains(docs.get("predictions")),
        incidents=parse_incidents(docs.get("incidents")),
        outages=parse_outages(docs.get("elevators")),
        stale=stale,
    )


# --- The shared copy ---------------------------------------------------------------------


@dataclass(frozen=True)
class Stored:
    fetched_wall: float | None
    docs: dict[str, Any]
    stations_wall: float | None = None
    failed_wall: float | None = None


class SharedStore(Protocol):
    def load(self) -> Stored | None: ...

    def save(self, stored: Stored) -> None: ...

    def mark_failed(self, wall: float) -> None: ...

    def refresh_turn(self) -> Any: ...


class DatabaseStore:
    """One row of `bikeshare_feed_cache` (key `ROW_KEY`, or the train positions' own,
    core.wmata_trains), replaced at every reading; the turn to read WMATA is a session advisory
    lock, so one worker reads however many run."""

    LOCK_KEY = 0x776D7461  # "wmta"

    def __init__(self, row_key: str = ROW_KEY, lock_key: int = LOCK_KEY) -> None:
        self.row_key = row_key
        self.lock_key = lock_key

    def load(self) -> Stored | None:
        from .models import BikeshareFeedCache

        row = BikeshareFeedCache.objects.filter(key=self.row_key).first()
        if row is None:
            return None
        payload = row.payload if isinstance(row.payload, dict) else {}
        docs = payload.get("docs")
        stations_wall = payload.get("stations_wall")
        return Stored(
            fetched_wall=None if row.fetched_at is None else row.fetched_at.timestamp(),
            docs=docs if isinstance(docs, dict) else {},
            stations_wall=float(stations_wall) if isinstance(stations_wall, int | float) else None,
            failed_wall=None if row.failed_at is None else row.failed_at.timestamp(),
        )

    def save(self, stored: Stored) -> None:
        from .models import BikeshareFeedCache

        BikeshareFeedCache.objects.update_or_create(
            key=self.row_key,
            defaults={
                "payload": {"docs": stored.docs, "stations_wall": stored.stations_wall},
                "fetched_at": (
                    None
                    if stored.fetched_wall is None
                    else datetime.fromtimestamp(stored.fetched_wall, UTC)
                ),
                "failed_at": None,
            },
        )

    def mark_failed(self, wall: float) -> None:
        from .models import BikeshareFeedCache

        BikeshareFeedCache.objects.update_or_create(
            key=self.row_key, defaults={"failed_at": datetime.fromtimestamp(wall, UTC)}
        )

    @contextmanager
    def refresh_turn(self) -> Iterator[bool]:
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [self.lock_key])
            got = bool(cursor.fetchone()[0])
        try:
            yield got
        finally:
            if got:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(%s)", [self.lock_key])


LIVE_URLS = {
    "predictions": PREDICTIONS_URL,
    "incidents": INCIDENTS_URL,
    "elevators": ELEVATORS_URL,
}
DAILY_URLS = {"stations": STATIONS_URL}


class Live:
    """The cache: one live reading for all workers, read again at most every `CACHE_TTL_S`
    while asked for. `snapshot()` never raises: None means nothing live (no key, or WMATA has
    not answered for a while), and every time is then the timetable's.

    The same cache serves Metro's train positions (core.wmata_trains, v0.9.0) with its own
    documents (`urls`, read every `ttl`; `daily`, read once a day), its own `builder`, a
    shorter `ttl` and no `grace` (a position minutes old is no position)."""

    def __init__(
        self,
        fetch: Fetch = http_get,
        store: SharedStore | None = None,
        wall: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        enabled: Callable[[], bool] = configured,
        urls: dict[str, str] | None = None,
        daily: dict[str, str] | None = None,
        builder: Callable[..., Any] | None = None,
        ttl: float = CACHE_TTL_S,
        grace: float = STALE_GRACE_S,
        name: str = "wmata live",
    ) -> None:
        self._urls = dict(LIVE_URLS if urls is None else urls)
        self._daily = dict(DAILY_URLS if daily is None else daily)
        self._builder = builder or build
        self._ttl = ttl
        self._grace = grace
        self._name = name
        self._fetch = fetch
        self._store = store
        self._wall = wall
        self._sleep = sleep
        self._enabled = enabled
        self._lock = threading.Lock()
        self._held: Stored | None = None
        self._failed_at: float | None = None
        self.readings = 0

    def snapshot(self) -> Any:
        if not self._enabled():
            return None
        with self._lock:
            now = self._wall()
            fresh = self._fresh(self._held, now)
            if fresh is not None:
                return fresh
            stored = self._load()
            fresh = self._fresh(stored, now)
            if fresh is not None:
                self._held = stored
                return fresh
            paused = (self._failed_at is not None and now - self._failed_at < FAILURE_PAUSE_S) or (
                stored is not None
                and stored.failed_wall is not None
                and 0 <= now - stored.failed_wall < FAILURE_PAUSE_S
            )
            if not paused:
                got = self._refresh_or_borrow(now, stored or self._held)
                if got is not None:
                    return got
            for held in (self._held, stored):
                late = self._fresh(held, self._wall(), grace=True)
                if late is not None:
                    return late
            return None

    def _fresh(self, stored: Stored | None, now: float, grace: bool = False) -> Any:
        if stored is None or stored.fetched_wall is None or not stored.docs:
            return None
        age = now - stored.fetched_wall
        limit = self._ttl + self._grace if grace else self._ttl
        if age < 0 or age >= limit:
            return None
        try:
            return self._builder(stored.docs, stored.fetched_wall, stale=age >= self._ttl)
        except Unavailable:
            return None

    def _load(self) -> Stored | None:
        if self._store is None:
            return None
        try:
            return self._store.load()
        except Exception as error:  # noqa: BLE001 - a store that fails is no store
            logger.warning(
                "%s: the shared copy could not be read: %s", self._name, type(error).__name__
            )
            return None

    def _refresh_or_borrow(self, now: float, stored: Stored | None) -> Any:
        if self._store is None:
            return self._read(now, stored)
        try:
            with self._store.refresh_turn() as mine:
                if mine:
                    again = self._load()
                    fresh = self._fresh(again, now)
                    if fresh is not None:
                        self._held = again
                        return fresh
                    return self._read(now, again or stored)
        except Exception as error:  # noqa: BLE001
            logger.warning(
                "%s: the shared copy could not be used: %s", self._name, type(error).__name__
            )
            return self._read(now, stored)
        waited = 0.0
        while waited < SHARED_WAIT_S:
            self._sleep(SHARED_POLL_S)
            waited += SHARED_POLL_S
            again = self._load()
            fresh = self._fresh(again, self._wall())
            if fresh is not None:
                self._held = again
                return fresh
        return None

    def _get(self, url: str):
        try:
            return json.loads(self._fetch(url, TIMEOUT_S))
        except ValueError:
            raise Unavailable(f"{urllib.parse.urlsplit(url).path}: not JSON") from None

    def _get_all(self, urls: dict[str, str]) -> dict[str, Any]:
        """The documents, read at once, all within `REFRESH_BUDGET_S`: a plan waits for a
        reading at most that long, once in `CACHE_TTL_S`."""
        pool = ThreadPoolExecutor(max_workers=len(urls))
        try:
            futures = {name: pool.submit(self._get, url) for name, url in urls.items()}
            deadline = time.monotonic() + REFRESH_BUDGET_S
            out = {}
            for name, future in futures.items():
                try:
                    out[name] = future.result(timeout=max(0.1, deadline - time.monotonic()))
                except FutureTimeout:
                    raise Unavailable(f"{name}: no answer in time") from None
            return out
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def _read(self, now: float, previous: Stored | None) -> Any:
        self.readings += 1
        try:
            docs: dict[str, Any] = {}
            # The daily documents' time (the station list's; the standard routes').
            stations_wall = previous.stations_wall if previous else None
            wanted = dict(self._urls)
            kept = (previous.docs or {}) if previous else {}
            daily_fresh = stations_wall is not None and 0 <= now - stations_wall < STATIONS_TTL_S
            if daily_fresh and all(kept.get(name) for name in self._daily):
                docs.update({name: kept[name] for name in self._daily})
            else:
                wanted.update(self._daily)
                stations_wall = now
            docs.update(self._get_all(wanted))
            snapshot = self._builder(docs, now)
        except Unavailable as error:
            logger.warning("%s: %s", self._name, error)
            self._failed_at = now
            if self._store is not None:
                try:
                    self._store.mark_failed(now)
                except Exception:  # noqa: BLE001
                    logger.warning("%s: could not note the failure", self._name)
            return None
        stored = Stored(now, docs, stations_wall)
        self._held = stored
        self._failed_at = None
        if self._store is not None:
            try:
                self._store.save(stored)
            except Exception:  # noqa: BLE001
                logger.warning("%s: could not keep the shared copy", self._name)
        return snapshot


# --- The bus calls' budget (v0.9.0) -------------------------------------------------------

# Metrobus's next buses, its stops and its bus positions (core.wmata_bus) are asked per stop and
# per route, so they are counted, deployment-wide: at most `BUS_CALLS_PER_MIN` a minute (25,920
# a day at the very most) and `BUS_CALLS_PER_S` a second. With Metro's reading (three calls every
# 45 s, 5,760 a day) and the train positions (one every 20 s, 4,320 a day, core.wmata_trains),
# the worst case is about 36,000 calls a day and 9 a second, under WMATA's 50,000 and 10.
BUS_CALLS_PER_MIN = 18
BUS_CALLS_PER_S = 4
BUDGET_ROW_KEY = "wmata-budget"


class Budget(Protocol):
    def take(self) -> bool: ...


def _take(counts: dict, now: float, per_min: int, per_s: int) -> bool:
    """Count one call in `counts` (this minute's and this second's) if both allow it."""
    minute, second = int(now // 60), int(now)
    if counts.get("minute") != minute:
        counts["minute"], counts["n"] = minute, 0
    if counts.get("second") != second:
        counts["second"], counts["ns"] = second, 0
    if counts["n"] >= per_min or counts["ns"] >= per_s:
        return False
    counts["n"] += 1
    counts["ns"] += 1
    return True


class LocalBudget:
    """The budget counted in this process alone (tests)."""

    def __init__(
        self,
        per_min: int = BUS_CALLS_PER_MIN,
        per_s: int = BUS_CALLS_PER_S,
        wall: Callable[[], float] = time.time,
    ) -> None:
        self.per_min, self.per_s, self._wall = per_min, per_s, wall
        self._lock = threading.Lock()
        self._counts: dict = {}

    def take(self) -> bool:
        with self._lock:
            return _take(self._counts, self._wall(), self.per_min, self.per_s)


class SharedBudget:
    """The budget for every worker at once: one row of `bikeshare_feed_cache` (key
    `BUDGET_ROW_KEY`) holding this minute's and this second's counts, taken under a row lock.
    No history: four numbers, replaced. A database that fails refuses the call (nothing live)."""

    def __init__(
        self,
        per_min: int = BUS_CALLS_PER_MIN,
        per_s: int = BUS_CALLS_PER_S,
        wall: Callable[[], float] = time.time,
    ) -> None:
        self.per_min, self.per_s, self._wall = per_min, per_s, wall

    def take(self) -> bool:
        from django.db import transaction

        from .models import BikeshareFeedCache

        try:
            with transaction.atomic():
                row, _ = BikeshareFeedCache.objects.select_for_update().get_or_create(
                    key=BUDGET_ROW_KEY, defaults={"payload": {}}
                )
                counts = dict(row.payload) if isinstance(row.payload, dict) else {}
                allowed = _take(counts, self._wall(), self.per_min, self.per_s)
                if allowed:
                    row.payload = counts
                    row.save(update_fields=["payload"])
                return allowed
        except Exception as error:  # noqa: BLE001 - no count, no call
            logger.warning("wmata budget: could not be counted: %s", type(error).__name__)
            return False


# --- Words ------------------------------------------------------------------------------


def elevator_words(station_name: str) -> str:
    """The one-line warning (the owner, 2026-10-13 11:17 UTC)."""
    return f"Elevator out at {station_name}: carry your bike on the stairs."


def spare_elevator_words(station_name: str) -> str:
    """An elevator out where another street elevator works: said, never ranked down."""
    return f"A street elevator is out at {station_name}: use another one."


def train_minutes(train: Train) -> str:
    if train.boarding:
        return "boarding"
    if train.arriving or train.minutes == 0:
        return "arriving"
    return f"{train.minutes} min"


def wall_iso(wall: float) -> str:
    """A reading's time, local ISO."""
    from routemaker.ridetime import ZONE

    return datetime.fromtimestamp(wall, UTC).astimezone(ZONE).isoformat(timespec="seconds")


def as_of_iso(snapshot: Snapshot) -> str:
    return wall_iso(snapshot.as_of)


# The one cache of the process; its reading is shared by every worker.
client = Live(store=DatabaseStore())
