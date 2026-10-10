"""The bikeshare operator's GBFS feeds: discovery, one shared short-lived cache, parsing.

FOLLOWUP-BIKESHARE (OWNER-DECISIONS 243-245, 299, 300, 466, 466a). The operator's
Data License Agreement, read for 299 (item 300), shapes this module:

- Only the official GBFS endpoints are fetched: the discovery feed at
  `DISCOVERY_URL`, and the feeds it lists, on the hosts in `ALLOWED_HOSTS` over
  https. A feed URL on any other host is refused, and so is a redirect off them.
- What is fetched is a live copy, good for about `CACHE_TTL_S` seconds (the
  feeds' own ttl), and it is one copy for the whole deployment: the first API
  worker that finds it out of date reads the feeds, and the others use what it
  kept (`DatabaseStore`: one row, replaced in place at every refresh, that holds
  only the latest feeds as the operator published them). Nothing is ever stored
  as history: no earlier reading is kept, no counts over time, no row per
  station or per reading, no file, no export, no endpoint that hands the data on;
  the one row is overwritten, never added to. `Gbfs.snapshot()` is read by the
  planner and by the nearest-stations list, and by nothing else. A refresh that
  fails serves the last copy for at most `STALE_GRACE_S` more, and then the
  planner says availability is unknown.
- A station that has not reported for `STATION_STALE_S` (30 minutes) is treated
  as unavailable: its counts are not trusted (`Snapshot.reporting_stale`).
- The requests carry nothing of the visitor: no address, no cookie, no plan;
  the same request is made whoever asked, and a visitor's own location is never
  in it. `User-Agent` names this software only.
- Nothing here names the operator in the UI beyond `CREDIT`, the one plain
  source citation (OWNER-DECISIONS 301); no logo, no wording of affiliation.

Feeds the operator publishes (checked 2026-10-04): GBFS 1.1, ttl 60 s;
station_information, station_status (with `num_ebikes_available`,
`num_bikes_disabled`, `num_docks_disabled` and `last_reported`),
free_bike_status (every free bike `electric_bike`), system_pricing_plans (one
plan, the e-bike single ride), system_alerts. It publishes no
`geofencing_zones`, and its pricing plan carries no out-of-dock fee. Both are
handled as absent, never guessed (`core.bikeshare`).
"""

from __future__ import annotations

import json
import logging
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
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

logger = logging.getLogger(__name__)

DISCOVERY_URL = "https://gbfs.capitalbikeshare.com/gbfs/gbfs.json"
# The discovery feed lists the feeds on the operator's data host.
ALLOWED_HOSTS = frozenset({"gbfs.capitalbikeshare.com", "gbfs.lyft.com"})
LANGUAGE = "en"

# How long a snapshot is used (the feeds' own ttl is 60 s), how much longer one
# is served when the refresh fails, and how long a failed refresh is not tried
# again (so a down feed costs one timeout in fifteen seconds, not one a request).
CACHE_TTL_S = 60.0
STALE_GRACE_S = 120.0
FAILURE_PAUSE_S = 15.0
# A station whose last report is older than this is treated as unavailable: a dock
# that has been silent for half an hour may be broken, and its counts are guesses.
STATION_STALE_S = 30 * 60
# While another API worker is reading the feeds, how long this one waits for its
# result before serving what it has, and how often it looks.
SHARED_WAIT_S = 6.0
SHARED_POLL_S = 0.25
# One request's limit, and the limit on all of a refresh.
TIMEOUT_S = 4.0
REFRESH_BUDGET_S = 8.0
# station_information is about 0.5 MB for the whole system; nothing is larger.
MAX_BYTES = 4_000_000

USER_AGENT = "RouteMaker-bikeshare-availability"

# The feeds a snapshot reads, beyond discovery. station_information is the one a
# snapshot cannot do without; each of the rest is optional and its absence is
# worded, not an error.
REQUIRED_FEED = "station_information"
OPTIONAL_FEEDS = (
    "station_status",
    "free_bike_status",
    "system_pricing_plans",
    "geofencing_zones",
    "system_alerts",
)

# The plain source citation (OWNER-DECISIONS 301: "Even if the license doesn't
# require crediting them, sources need citing."), worded by OWNER-DECISIONS 304 as
# the operator's name alone ("don't clog up the map with extra words"): text only,
# no mark, no wording of affiliation. The controls stay "Bikeshare". What it is a
# citation of (the official GBFS feed, operated by Lyft, under its data licence) is
# in docs/OPERATIONS.md and docs/DEVELOPMENT.md, not on the map.
CREDIT = "Capital Bikeshare"


class Unavailable(Exception):
    """The station list could not be had: no bikeshare plan can be made."""


Fetch = Callable[[str, float], bytes]


# --- The one place this module touches the network -----------------------------


def allowed_url(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    return parts.scheme == "https" and parts.hostname in ALLOWED_HOSTS and not parts.username


class _SameHostsOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_url(newurl):
            raise urllib.error.URLError(f"redirect off the operator's hosts refused: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SameHostsOnly)


def http_get(url: str, timeout: float) -> bytes:
    """GET one official GBFS URL: https, on `ALLOWED_HOSTS`, no cookies, no body."""
    if not allowed_url(url):
        raise Unavailable(f"not an official GBFS endpoint: {url}")
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": USER_AGENT}
    )
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            body = response.read(MAX_BYTES + 1)
    except (TimeoutError, urllib.error.URLError, ConnectionError, OSError) as error:
        raise Unavailable(str(error)) from error
    if len(body) > MAX_BYTES:
        raise Unavailable("a feed was larger than expected")
    return body


# --- Parsed feeds -------------------------------------------------------------


@dataclass(frozen=True)
class Station:
    station_id: str
    name: str
    lon: float
    lat: float
    capacity: int | None = None


@dataclass(frozen=True)
class StationStatus:
    station_id: str
    bikes: int  # every bike, e-bikes included (GBFS num_bikes_available)
    ebikes: int
    docks: int  # free slots
    renting: bool
    returning: bool
    installed: bool
    # The operator's own counts of out-of-order bikes and docks, kept as published
    # (they are neither available nor free), and when the station last reported
    # (epoch seconds, as published; None where the feed has none).
    bikes_disabled: int = 0
    docks_disabled: int = 0
    last_reported: int | None = None

    @property
    def classic(self) -> int:
        return max(0, self.bikes - self.ebikes)

    def bikes_of(self, bike: str) -> int:
        return min(self.ebikes, self.bikes) if bike == "ebike" else self.classic

    @property
    def can_rent(self) -> bool:
        return self.installed and self.renting

    @property
    def can_return(self) -> bool:
        return self.installed and self.returning and self.docks > 0

    @property
    def fullness(self) -> float | None:
        """Bikes as a share of the bikes and the free docks, 0 to 1 (OWNER-DECISIONS 466):
        out-of-order bikes and docks are in neither count. None where both are zero."""
        total = self.bikes + self.docks
        return None if total <= 0 else self.bikes / total


@dataclass(frozen=True)
class FreeBike:
    bike_id: str
    lon: float
    lat: float


@dataclass(frozen=True)
class PricingPlan:
    plan_id: str
    name: str
    currency: str
    price: str  # as published: a decimal string
    description: str


@dataclass(frozen=True)
class Zones:
    """Geofencing zones, from GBFS 2.1's `geofencing_zones` where published."""

    # (rings of [lon, lat] for one polygon, outer first; rules)
    polygons: tuple[tuple[tuple[tuple[tuple[float, float], ...], ...], tuple[dict, ...]], ...]
    global_rules: tuple[dict, ...] = ()

    def allows_ending(self, lon: float, lat: float) -> bool:
        """Whether a ride may end outside a station at this point: in no zone that
        bars ending a ride (`ride_allowed` false) or says to park at a station
        (`station_parking` true), and no global rule barring it."""
        for rule in self.global_rules:
            if _bars_ending(rule):
                return False
        for rings, rules in self.polygons:
            if _in_polygon(lon, lat, rings) and any(_bars_ending(rule) for rule in rules):
                return False
        return True


def _bars_ending(rule: dict) -> bool:
    return rule.get("ride_allowed") is False or rule.get("station_parking") is True


def _in_ring(lon: float, lat: float, ring: tuple[tuple[float, float], ...]) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _in_polygon(lon: float, lat: float, rings: tuple[tuple[tuple[float, float], ...], ...]) -> bool:
    if not rings or not _in_ring(lon, lat, rings[0]):
        return False
    return not any(_in_ring(lon, lat, hole) for hole in rings[1:])


def _number(value, low: float, high: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if low <= value <= high else None


def _count(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _reported(value) -> int | None:
    """A `last_reported` time: whole epoch seconds after 2000, as published, else None."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(value) if value > 946_684_800 else None


def _flag(value) -> bool:
    return value is True or value == 1


def _doc_list(doc, key: str) -> list:
    data = doc.get("data") if isinstance(doc, dict) else None
    items = data.get(key) if isinstance(data, dict) else None
    return items if isinstance(items, list) else []


def parse_discovery(doc, language: str = LANGUAGE) -> dict[str, str]:
    """Feed name to URL, for the language, keeping only official https URLs."""
    data = doc.get("data") if isinstance(doc, dict) else None
    if not isinstance(data, dict):
        return {}
    entry = data.get(language) or next(iter(data.values()), None)
    feeds = entry.get("feeds") if isinstance(entry, dict) else None
    found: dict[str, str] = {}
    for feed in feeds if isinstance(feeds, list) else []:
        if not isinstance(feed, dict):
            continue
        name, url = feed.get("name"), feed.get("url")
        if isinstance(name, str) and isinstance(url, str) and allowed_url(url):
            found[name] = url
    return found


def parse_stations(doc) -> list[Station]:
    stations = []
    for item in _doc_list(doc, "stations"):
        if not isinstance(item, dict):
            continue
        lon = _number(item.get("lon"), -180, 180)
        lat = _number(item.get("lat"), -90, 90)
        station_id, name = item.get("station_id"), item.get("name")
        if lon is None or lat is None or not isinstance(station_id, str) or not station_id:
            continue
        capacity = item.get("capacity")
        stations.append(
            Station(
                station_id=station_id,
                name=" ".join(name.split()) if isinstance(name, str) and name.strip() else "dock",
                lon=lon,
                lat=lat,
                capacity=capacity if isinstance(capacity, int) else None,
            )
        )
    return stations


def parse_status(doc) -> dict[str, StationStatus]:
    status = {}
    for item in _doc_list(doc, "stations"):
        if not isinstance(item, dict) or not isinstance(item.get("station_id"), str):
            continue
        status[item["station_id"]] = StationStatus(
            station_id=item["station_id"],
            bikes=_count(item.get("num_bikes_available")),
            ebikes=_count(item.get("num_ebikes_available")),
            docks=_count(item.get("num_docks_available")),
            renting=_flag(item.get("is_renting", 1)),
            returning=_flag(item.get("is_returning", 1)),
            installed=_flag(item.get("is_installed", 1)),
            bikes_disabled=_count(item.get("num_bikes_disabled")),
            docks_disabled=_count(item.get("num_docks_disabled")),
            last_reported=_reported(item.get("last_reported")),
        )
    return status


# GBFS 1.1's free_bike_status has no vehicle type id; this operator's `type` is
# "electric_bike". A bike that is neither reserved nor disabled can be taken.
EBIKE_TYPES = frozenset({"electric_bike", "ebike", "electric"})


def parse_free_bikes(doc) -> list[FreeBike]:
    bikes = []
    for item in _doc_list(doc, "bikes"):
        if not isinstance(item, dict):
            continue
        lon = _number(item.get("lon"), -180, 180)
        lat = _number(item.get("lat"), -90, 90)
        kind = item.get("type")
        if (
            lon is None
            or lat is None
            or (isinstance(kind, str) and kind.lower() not in EBIKE_TYPES)
            or _flag(item.get("is_reserved"))
            or _flag(item.get("is_disabled"))
        ):
            continue
        bikes.append(FreeBike(str(item.get("bike_id", "")), lon, lat))
    return bikes


def parse_pricing(doc) -> list[PricingPlan]:
    plans = []
    for item in _doc_list(doc, "plans"):
        if not isinstance(item, dict):
            continue
        price = item.get("price")
        try:
            price_text = f"{Decimal(str(price)):.2f}"
        except (InvalidOperation, ValueError):
            continue
        plans.append(
            PricingPlan(
                plan_id=str(item.get("plan_id", "")),
                name=" ".join(str(item.get("name", "")).split()),
                currency=str(item.get("currency", "USD"))[:3].upper(),
                price=price_text,
                description=" ".join(str(item.get("description", "")).split())[:300],
            )
        )
    return plans


# A plan that is the fee for ending a ride outside a station, by what it says.
# Nothing is assumed about a fee the feed does not name; with no such plan the
# answer says the fee is not in the operator's data.
OUT_OF_DOCK = re.compile(
    r"out[\s-]*of[\s-]*(?:a[\s-]*)?(?:dock|station)|outside\s+(?:of\s+)?(?:a\s+)?(?:dock|station)"
    r"|non[\s-]*(?:dock|station)|(?:not|away)\s+(?:at|in|from)\s+a\s+(?:dock|station)"
    r"|(?:free|dockless)[\s-]*(?:floating\s+)?(?:parking|park)|lock[\s-]*to|drop[\s-]*off",
    re.I,
)


def out_of_dock_fee(plans: list[PricingPlan]) -> PricingPlan | None:
    """The plan that names an out-of-dock fee, if the feed has one."""
    for plan in plans:
        if OUT_OF_DOCK.search(f"{plan.plan_id} {plan.name} {plan.description}"):
            return plan
    return None


def parse_zones(doc) -> Zones | None:
    """Geofencing zones, or None where the feed is not that (GBFS 2.1: a GeoJSON
    FeatureCollection under `data.geofencing_zones`)."""
    data = doc.get("data") if isinstance(doc, dict) else None
    collection = data.get("geofencing_zones") if isinstance(data, dict) else None
    features = collection.get("features") if isinstance(collection, dict) else None
    if not isinstance(features, list):
        return None
    polygons = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        geometry = feature.get("geometry") or {}
        rules = tuple(
            r for r in (feature.get("properties") or {}).get("rules", []) if isinstance(r, dict)
        )
        coordinates = geometry.get("coordinates")
        if geometry.get("type") == "Polygon":
            shapes = [coordinates]
        elif geometry.get("type") == "MultiPolygon":
            shapes = coordinates
        else:
            continue
        for shape in shapes if isinstance(shapes, list) else []:
            try:
                rings = tuple(tuple((float(x), float(y)) for x, y, *_ in ring) for ring in shape)
            except (TypeError, ValueError):
                continue
            polygons.append((rings, rules))
    global_rules = tuple(r for r in collection.get("global_rules", []) if isinstance(r, dict))
    if not global_rules and isinstance(data.get("global_rules"), list):
        global_rules = tuple(r for r in data["global_rules"] if isinstance(r, dict))
    return Zones(tuple(polygons), global_rules)


def parse_alerts(doc) -> list[str]:
    """The operator's own one-line summaries of its current alerts."""
    summaries = []
    for item in _doc_list(doc, "alerts"):
        if isinstance(item, dict):
            text = item.get("summary") or item.get("description")
            if isinstance(text, str) and text.strip():
                summaries.append(" ".join(text.split())[:200])
    return summaries


# --- A snapshot, and the cache that holds it -----------------------------------


@dataclass(frozen=True)
class Snapshot:
    fetched_at: float  # the cache's clock, for its age
    stations: list[Station]
    # None: that feed could not be read (or is not published): never "empty".
    status: dict[str, StationStatus] | None = None
    free_bikes: list[FreeBike] | None = None
    pricing: list[PricingPlan] | None = None
    zones: Zones | None = None
    alerts: list[str] | None = None
    # Feeds the discovery feed did not list, and feeds that were listed and failed.
    unlisted: frozenset[str] = frozenset()
    failed: frozenset[str] = frozenset()
    stale: bool = False
    notes: tuple[str, ...] = field(default=())
    # When the feeds were read, in epoch seconds (the wall clock): what a station's
    # `last_reported` is measured against. None: not judged (a snapshot built by hand).
    as_of: float | None = None

    def reporting_stale(self, status: StationStatus) -> bool:
        """Whether the station has not reported for `STATION_STALE_S` (OWNER-DECISIONS 466:
        live data only; a long silent station is unavailable). With no reading time on the
        snapshot nothing is judged; with one, a station that gave no `last_reported`
        cannot be shown to be fresh, so it counts as stale."""
        if self.as_of is None:
            return False
        if status.last_reported is None:
            return True
        return self.as_of - status.last_reported > STATION_STALE_S


_PARSERS = {
    "station_information": parse_stations,
    "station_status": parse_status,
    "free_bike_status": parse_free_bikes,
    "system_pricing_plans": parse_pricing,
    "geofencing_zones": parse_zones,
    "system_alerts": parse_alerts,
}


def _json(body: bytes):
    try:
        return json.loads(body)
    except ValueError as error:
        raise Unavailable("a feed was not JSON") from error


@dataclass(frozen=True)
class Stored:
    """The latest feeds as the operator published them, as one shared copy holds them."""

    fetched_wall: float | None  # epoch seconds when they were read; None: no copy yet
    docs: dict[str, Any]
    unlisted: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    failed_wall: float | None = None  # the last failed refresh, so workers do not all retry


class SharedStore(Protocol):
    """Where the one live copy is kept so the API's workers share it. It holds the latest
    reading only (it is replaced, never added to): no history (OWNER-DECISIONS 466)."""

    def load(self) -> Stored | None: ...

    def save(self, stored: Stored) -> None: ...

    def mark_failed(self, wall: float) -> None: ...

    def refresh_turn(self) -> Any:
        """A context manager that yields True to the one worker allowed to read the feeds now,
        and False to the others."""
        ...


class DatabaseStore:
    """The shared copy in PostgreSQL: one row of `core.models.BikeshareFeedCache`, replaced
    at every refresh. The turn to refresh is a session advisory lock, so only one worker
    reads the operator's feeds however many are running."""

    LOCK_KEY = 0x62696B65  # "bike"

    def load(self) -> Stored | None:
        from .models import BikeshareFeedCache

        row = BikeshareFeedCache.objects.filter(key=BikeshareFeedCache.CURRENT).first()
        if row is None:
            return None
        payload = row.payload if isinstance(row.payload, dict) else {}
        docs = payload.get("docs")
        return Stored(
            fetched_wall=None if row.fetched_at is None else row.fetched_at.timestamp(),
            docs=docs if isinstance(docs, dict) else {},
            unlisted=tuple(payload.get("unlisted") or ()),
            failed=tuple(payload.get("failed") or ()),
            failed_wall=None if row.failed_at is None else row.failed_at.timestamp(),
        )

    def save(self, stored: Stored) -> None:
        from datetime import UTC, datetime

        from .models import BikeshareFeedCache

        BikeshareFeedCache.objects.update_or_create(
            key=BikeshareFeedCache.CURRENT,
            defaults={
                "payload": {
                    "docs": stored.docs,
                    "unlisted": list(stored.unlisted),
                    "failed": list(stored.failed),
                },
                "fetched_at": (
                    None
                    if stored.fetched_wall is None
                    else datetime.fromtimestamp(stored.fetched_wall, UTC)
                ),
                "failed_at": None,
            },
        )

    def mark_failed(self, wall: float) -> None:
        from datetime import UTC, datetime

        from .models import BikeshareFeedCache

        BikeshareFeedCache.objects.update_or_create(
            key=BikeshareFeedCache.CURRENT,
            defaults={"failed_at": datetime.fromtimestamp(wall, UTC)},
        )

    @contextmanager
    def refresh_turn(self) -> Iterator[bool]:
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [self.LOCK_KEY])
            got = bool(cursor.fetchone()[0])
        try:
            yield got
        finally:
            if got:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(%s)", [self.LOCK_KEY])


class Gbfs:
    """The cache: one live copy for all workers, refreshed at most once in `CACHE_TTL_S`.

    A worker looks first at its own memory, then at the shared copy (`store`), and only when
    both are out of date does it read the operator's feeds, if it is the worker whose turn it
    is; the others wait a few seconds for that reading. With no `store` the copy is this
    process's alone (tests; one process)."""

    def __init__(
        self,
        fetch: Fetch = http_get,
        clock: Callable[[], float] = time.monotonic,
        discovery_url: str = DISCOVERY_URL,
        store: SharedStore | None = None,
        wall: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._fetch = fetch
        self._clock = clock
        self._wall = wall
        self._sleep = sleep
        self._discovery_url = discovery_url
        self._store = store
        self._lock = threading.Lock()
        self._snapshot: Snapshot | None = None
        self._failed_at: float | None = None
        self.refreshes = 0  # feed readings this process made (not the ones it borrowed)

    def age(self) -> float | None:
        return None if self._snapshot is None else self._clock() - self._snapshot.fetched_at

    def snapshot(self) -> Snapshot:
        """The current snapshot. Raises Unavailable if there is none to use."""
        with self._lock:
            now = self._clock()
            held = self._snapshot
            if held is not None and now - held.fetched_at < CACHE_TTL_S:
                return held
            stored = self._load()
            borrowed = self._adopt(stored, now)
            if borrowed is not None:
                return borrowed
            paused = (self._failed_at is not None and now - self._failed_at < FAILURE_PAUSE_S) or (
                stored is not None
                and stored.failed_wall is not None
                and 0 <= self._wall() - stored.failed_wall < FAILURE_PAUSE_S
            )
            if not paused:
                fresh = self._refresh_or_borrow(now)
                if fresh is not None:
                    return fresh
            if held is not None and now - held.fetched_at < CACHE_TTL_S + STALE_GRACE_S:
                return Snapshot(**{**held.__dict__, "stale": True})
            # Another worker's copy, if it is not too old to say so.
            late = self._adopt(stored, now, grace=True)
            if late is not None:
                return late
            raise Unavailable("the bikeshare data is not available right now")

    # -- the shared copy --

    def _load(self) -> Stored | None:
        if self._store is None:
            return None
        try:
            return self._store.load()
        except Exception as error:  # noqa: BLE001 - a store that fails is no store
            logger.warning("bikeshare feeds: the shared copy could not be read: %s", error)
            return None

    def _adopt(self, stored: Stored | None, now: float, grace: bool = False) -> Snapshot | None:
        """The snapshot a shared copy makes, if it is fresh (or, with `grace`, not too old)."""
        if stored is None or stored.fetched_wall is None or not stored.docs:
            return None
        age = self._wall() - stored.fetched_wall
        limit = CACHE_TTL_S + STALE_GRACE_S if grace else CACHE_TTL_S
        if age < 0 or age >= limit:
            return None
        try:
            snapshot = self._build(
                stored.docs,
                frozenset(stored.unlisted),
                set(stored.failed),
                fetched_at=now - age,
                as_of=stored.fetched_wall,
            )
        except Unavailable:
            return None
        if grace and age >= CACHE_TTL_S:
            return Snapshot(**{**snapshot.__dict__, "stale": True})
        self._snapshot = snapshot
        return snapshot

    def _refresh_or_borrow(self, now: float) -> Snapshot | None:
        """Read the feeds if it is this worker's turn; otherwise wait for the worker whose
        turn it is. None: no fresh copy came of it."""
        if self._store is None:
            return self._read(now)
        try:
            with self._store.refresh_turn() as mine:
                if mine:
                    # Someone may have refreshed between the look and the turn.
                    borrowed = self._adopt(self._load(), now)
                    return borrowed if borrowed is not None else self._read(now)
        except Exception as error:  # noqa: BLE001 - a store that fails is no store
            logger.warning("bikeshare feeds: the shared copy could not be used: %s", error)
            return self._read(now)
        waited = 0.0
        while waited < SHARED_WAIT_S:
            self._sleep(SHARED_POLL_S)
            waited += SHARED_POLL_S
            borrowed = self._adopt(self._load(), self._clock())
            if borrowed is not None:
                return borrowed
        return None

    def _read(self, now: float) -> Snapshot | None:
        """Read the operator's feeds and keep them (in memory, and in the shared copy)."""
        try:
            docs, unlisted, failed = self._download()
            wall = self._wall()
            snapshot = self._build(docs, unlisted, failed, fetched_at=now, as_of=wall)
        except Unavailable as error:
            logger.warning("bikeshare feeds: %s", error)
            self._failed_at = now
            if self._store is not None:
                try:
                    self._store.mark_failed(self._wall())
                except Exception as store_error:  # noqa: BLE001
                    logger.warning("bikeshare feeds: could not note the failure: %s", store_error)
            return None
        self._snapshot = snapshot
        self._failed_at = None
        if self._store is not None:
            try:
                self._store.save(Stored(wall, docs, tuple(sorted(unlisted)), tuple(sorted(failed))))
            except Exception as error:  # noqa: BLE001
                logger.warning("bikeshare feeds: could not keep the shared copy: %s", error)
        return snapshot

    def _download(self) -> tuple[dict[str, Any], frozenset[str], set[str]]:
        """The feeds' JSON, by name; the names not listed; the names that failed."""
        self.refreshes += 1
        discovery = parse_discovery(_json(self._fetch(self._discovery_url, TIMEOUT_S)))
        if REQUIRED_FEED not in discovery:
            raise Unavailable("the discovery feed does not list station_information")
        wanted = [REQUIRED_FEED, *(n for n in OPTIONAL_FEEDS if n in discovery)]
        docs: dict[str, Any] = {}
        failed: set[str] = set()
        pool = ThreadPoolExecutor(max_workers=len(wanted))
        try:
            futures = {
                name: pool.submit(lambda u=discovery[name]: _json(self._fetch(u, TIMEOUT_S)))
                for name in wanted
            }
            deadline = self._clock() + REFRESH_BUDGET_S
            for name, future in futures.items():
                try:
                    docs[name] = future.result(timeout=max(0.1, deadline - self._clock()))
                except (Unavailable, FutureTimeout):
                    failed.add(name)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        unlisted = frozenset(n for n in OPTIONAL_FEEDS if n not in discovery)
        return docs, unlisted, failed

    def _build(
        self,
        docs: dict[str, Any],
        unlisted: frozenset[str],
        failed: set[str],
        fetched_at: float,
        as_of: float,
    ) -> Snapshot:
        results: dict[str, object] = {}
        failed = set(failed)
        for name, doc in docs.items():
            parser = _PARSERS.get(name)
            if parser is None:
                continue
            parsed = parser(doc)
            if parsed is None:  # listed, but not the feed it should be
                failed.add(name)
                continue
            results[name] = parsed
        stations = results.get(REQUIRED_FEED)
        if not stations:
            raise Unavailable("station_information could not be read")
        return Snapshot(
            fetched_at=fetched_at,
            stations=stations,  # type: ignore[arg-type]
            status=results.get("station_status"),  # type: ignore[arg-type]
            free_bikes=results.get("free_bike_status"),  # type: ignore[arg-type]
            pricing=results.get("system_pricing_plans"),  # type: ignore[arg-type]
            zones=results.get("geofencing_zones"),  # type: ignore[arg-type]
            alerts=results.get("system_alerts"),  # type: ignore[arg-type]
            unlisted=frozenset(unlisted),
            failed=frozenset(failed - {REQUIRED_FEED}),
            as_of=as_of,
        )


# The one cache of the process, which the API reads; its copy is shared by every worker.
client = Gbfs(store=DatabaseStore())
