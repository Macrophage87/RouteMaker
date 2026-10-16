"""DC's closures: fetched by the worker, placed on the map, kept beside the work zones.

The v0.7.0 plan, "DC closures source". `routemaker.dc_closures` reads each source; this
module is the part that touches the network and the database, as `core.workzones` is
for the WZDx feeds, and it feeds the same closure model (`routemaker.workzones.Zone`).

- **Fetching.** The worker's `refresh_dc_closures` task (config.procrastinate, every
  `REFRESH_MINUTES` minutes) calls `refresh()`, which reads each source when it is due
  (`EVERY_S`): AlertDC and MPD every 15 minutes, NPS every 30, DDOT's permits every hour
  (DDOT refreshes them nightly). Each read has up to `TRIES` tries, and a source that
  fails keeps its last good copy. NPS needs the owner's key, read from `NPS_API_KEY` on
  the worker only and sent in the `X-Api-Key` header; without it NPS is off and nothing
  is asked of the NPS. No message names a URL or the key.
- **Placing.** A permit's point is snapped to its block, and an advisory's "X from A to
  B" to the ways of X between the two cross streets (`DatabasePlacer`): the live segment
  table's geometry, the self-hosted Photon for the streets' ways, and the router to
  check that the way from one junction to the other runs along X all the way. What
  cannot be placed is kept as text with its link (a `Notice`), never guessed. Each place
  is remembered with the source's copy, so a refresh places only what is new.
- **Keeping.** One row of `core.models.BikeshareFeedCache` under `KEY`, replaced at each
  refresh: the zones and notices as parsed, never the raw pages, and never an item of
  another kind (crime alerts are dropped before they are read: `dc_closures.is_traffic`).
  `core.workzones.snapshot` reads it beside the work zones' row.

The proxy this was written behind answers 403 for all four hosts, so the readers were
built and tested on saved sample pages (tests/data/closures); docs/OPERATIONS.md, "DC
closures", has the first check to run where they are reachable.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime

from routemaker import dc_closures as dc
from routemaker import workzones as rules

from .workzones import FeedError

logger = logging.getLogger(__name__)

KEY = "closures"  # its row in `bikeshare_feed_cache`: BikeshareFeedCache.CLOSURES
REFRESH_MINUTES = 15
TRIES = 3
RETRY_WAIT_S = 2.0
TIMEOUT_S = 20.0
# The whole refresh's time (v0.7.0 review): every 15 minutes on a maintenance slot, so it stops
# starting work past this. A fetch is cut to what is left, no retry or place look-up starts after
# it, and a source not reached keeps its last good copy and is due again next time. The task's
# hard deadline (config.procrastinate.DC_CLOSURES_TIMEOUT_S, 6 minutes) is the backstop.
REFRESH_BUDGET_S = 5 * 60.0
MAX_BYTES = 20_000_000
USER_AGENT = "RouteMaker-closures"
NPS_KEY_ENV = "NPS_API_KEY"

DC, MPD, ALERTDC, NPS = "dc", "mpd", "alertdc", "nps"
PUBLIC = frozenset({DC, MPD, ALERTDC})

# How often each source is read, and how old its copy may be before it is labelled
# stale, and before it is not used at all.
EVERY_S = {DC: 60 * 60.0, MPD: 15 * 60.0, ALERTDC: 15 * 60.0, NPS: 30 * 60.0}
STALE_AFTER_S = {DC: 3 * 60 * 60.0, MPD: 45 * 60.0, ALERTDC: 45 * 60.0, NPS: 90 * 60.0}
DROP_AFTER_S = {DC: 26 * 60 * 60.0, MPD: 6 * 60 * 60.0, ALERTDC: 3 * 60 * 60.0, NPS: 6 * 60 * 60.0}

URLS = {
    # DDOT's "Occupancy Permits (via DDOT TOPS)" layer (data.gov's record of it).
    DC: "https://maps2.dcgis.dc.gov/dcgis/rest/services/DDOT/TOPS/MapServer/1/query",
    MPD: "https://mpdc.dc.gov/newsroom",
    ALERTDC: "https://trainingtrack.hsema.dc.gov/NRss",
    NPS: "https://developer.nps.gov/api/v1/alerts",
}
# The TOPS layer is asked a page at a time (an ArcGIS server returns at most its
# maxRecordCount a request), up to this many pages.
TOPS_PAGE = 2000
TOPS_MAX_PAGES = 25
# At most this many MPD releases are read a refresh, newest first.
MPD_MAX_RELEASES = 8
# A place that could not be found is looked for again after this long.
RETRY_PLACE_S = 6 * 60 * 60.0
# At most this many new places are looked for a refresh, per source.
MAX_NEW_PLACES = {DC: 3000, MPD: 40, ALERTDC: 40}

Fetch = Callable[[str, float, dict], bytes]


def nps_key() -> str:
    return os.environ.get(NPS_KEY_ENV, "").strip()


def wanted() -> list[str]:
    """The sources to read: the public three always, NPS where the worker has the key."""
    return [DC, MPD, ALERTDC] + ([NPS] if nps_key() else [])


def http_get(url: str, timeout: float, headers: dict | None = None) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "*/*", **(headers or {})}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise FeedError(f"HTTP {error.code}") from None
    except Exception as error:  # noqa: BLE001 - every failure is a FeedError
        # The type only: the text can repeat the URL (and NPS's key is in a header, but
        # nothing about the request is ever said).
        raise FeedError(type(error).__name__) from None
    if len(body) > MAX_BYTES:
        raise FeedError("larger than expected")
    return body


def _get(fetch: Fetch, url: str, headers: dict, sleep) -> bytes:
    last: Exception | None = None
    for attempt in range(TRIES):
        if attempt:
            sleep(RETRY_WAIT_S * attempt)
        try:
            return fetch(url, TIMEOUT_S, headers)
        except FeedError as error:
            last = error
    raise FeedError(str(last))


def _now() -> datetime:
    return datetime.now(UTC)


# --- Placing ---------------------------------------------------------------------------


class Places:
    """One source's remembered places: key -> {"line": [[lon, lat], ...] or None, "at"}."""

    def __init__(
        self,
        kept: dict | None,
        now: datetime,
        most: int,
        out_of_time: Callable[[], bool] = lambda: False,
    ) -> None:
        self.kept = dict(kept or {})
        self.used: dict = {}
        self.now = now
        self.left = most
        self.out_of_time = out_of_time

    def get(self, key: str, find: Callable[[], list | None]) -> list | None:
        row = self.kept.get(key)
        if row is not None:
            at = rules._when(row.get("at"))
            fresh = at is not None and (self.now - at).total_seconds() < RETRY_PLACE_S
            if row.get("line") or fresh:
                self.used[key] = row
                return row.get("line")
        if self.left <= 0 or self.out_of_time():
            # Past the refresh's budget: not looked for, nor remembered as not found, so the
            # next refresh looks for it.
            return None
        self.left -= 1
        try:
            line = find()
        except Exception:  # noqa: BLE001 - a place not found is text, never a failed refresh
            logger.info("closures: a place could not be looked up", exc_info=True)
            line = None
        line = [list(map(float, p)) for p in line] if line and len(line) >= 2 else None
        self.used[key] = {"line": line, "at": self.now.isoformat()}
        return line


class DatabasePlacer:
    """Places permits and segments on the live segment table's ways (`dc_closures`)."""

    SNAP_M = 30.0

    def __init__(self, schema: str | None = None) -> None:
        from django.conf import settings

        from pipeline.schema import validate_schema_name

        self.schema = validate_schema_name(schema or settings.SEGMENT_SCHEMA_LIVE)

    # A permit's block.
    def permit_line(self, point: tuple[float, float]) -> list | None:
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                WITH spot AS (SELECT ST_SetSRID(ST_MakePoint(%s, %s), 4326) AS g)
                SELECT s.osm_way_id FROM spot, {self.schema}.segment AS s
                WHERE s.map_class = 'road'
                  AND s.geometry && ST_Expand(spot.g, 0.0005)
                  AND ST_DWithin(s.geometry::geography, spot.g::geography, %s)
                ORDER BY s.geometry <-> spot.g LIMIT 1
                """,
                [point[0], point[1], self.SNAP_M],
            )
            row = cursor.fetchone()
            if row is None:
                return None
            way_id = int(row[0])
            way = self._way_line(cursor, way_id)
            cursor.execute(
                f"""
                WITH way AS (
                    SELECT ST_Collect(geometry) AS g FROM {self.schema}.segment
                    WHERE osm_way_id = %s
                )
                SELECT ST_AsGeoJSON(s.geometry) FROM way, {self.schema}.segment AS s
                WHERE s.osm_way_id <> %s AND s.map_class IN ('road', 'alley')
                  AND s.geometry && ST_Expand(way.g, 0.0002)
                  AND ST_DWithin(s.geometry, way.g, 0.00003)
                """,
                [way_id, way_id],
            )
            others = [json.loads(r[0])["coordinates"] for r in cursor.fetchall()]
        return dc.block_of(point, way, others)

    def _way_line(self, cursor, way_id: int) -> list:
        cursor.execute(
            f"SELECT ST_AsGeoJSON(geometry) FROM {self.schema}.segment "
            "WHERE osm_way_id = %s ORDER BY ordinal",
            [way_id],
        )
        line: list = []
        for (geometry,) in cursor.fetchall():
            coordinates = json.loads(geometry)["coordinates"]
            line.extend(coordinates[1:] if line else coordinates)
        return line

    # A segment between two cross streets.
    def _ways(self, name: str, bias: tuple[float, float] | None = None) -> list[tuple]:
        """Photon's ways named `name` in the District: (way id, (lon, lat))."""
        from . import geocode

        west, south, east, north = dc.DC_BOX
        params: dict = {
            "q": f"{name}, Washington, DC",
            "limit": geocode.PHOTON_MAX_RESULTS,
            "lang": "en",
            "bbox": f"{west},{south},{east},{north}",
            "osm_tag": "highway",
        }
        if bias is not None:
            params.update(lon=bias[0], lat=bias[1], zoom=16, location_bias_scale=geocode.BIAS_SCALE)
        answer = geocode._get("/api", params)
        out = []
        for feature in answer.get("features") or []:
            properties = feature.get("properties") or {}
            point = (feature.get("geometry") or {}).get("coordinates") or []
            if properties.get("osm_type") != "W" or len(point) < 2:
                continue
            if not dc.names_match(str(properties.get("name") or ""), name):
                continue
            out.append((int(properties["osm_id"]), (float(point[0]), float(point[1]))))
        return out

    def _lines(self, way_ids: list[int]) -> list[list]:
        from django.db import connection

        if not way_ids:
            return []
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT ST_AsGeoJSON(geometry) FROM {self.schema}.segment "
                "WHERE osm_way_id = ANY(%s) ORDER BY osm_way_id, ordinal",
                [sorted(set(way_ids))],
            )
            return [json.loads(r[0])["coordinates"] for r in cursor.fetchall()]

    def segment_line(self, segment: dc.Segment) -> list | None:
        starts = self._ways(segment.from_street)
        ends = self._ways(segment.to_street)
        if not starts or not ends:
            return None
        main = self._ways(segment.street)
        for _way, point in starts[:1] + ends[:1]:
            main += self._ways(segment.street, bias=point)
        lines = self._lines([w for w, _p in main])
        if not lines:
            return None
        pair = dc.pick_ends(
            dc.meeting_points(lines, self._lines([w for w, _p in starts])),
            dc.meeting_points(lines, self._lines([w for w, _p in ends])),
        )
        if pair is None:
            return None
        return self._along(pair, segment.street)

    def _along(self, pair, street: str) -> list | None:
        """The router's way from one end to the other, kept only if every step of it is
        on `street` (asked both ways round, for a one-way street)."""
        from django.conf import settings

        from . import routing

        url = f"{settings.VALHALLA_UPSTREAMS['standard'].rstrip('/')}/route"
        for a, b in (pair, pair[::-1]):
            payload = {
                "locations": [{"lon": a[0], "lat": a[1]}, {"lon": b[0], "lat": b[1]}],
                "costing": "auto",
                "directions_type": "maneuvers",
                "units": "kilometers",
            }
            try:
                answer = routing._transport(url, payload, TIMEOUT_S)
            except (routing.RouterUnavailable, routing.RouterRefused):
                continue
            legs = (answer.get("trip") or {}).get("legs") or []
            if len(legs) != 1:
                continue
            steps = [m for m in legs[0].get("maneuvers") or [] if m.get("type") not in (4, 5, 6)]
            if steps and all(
                any(dc.names_match(str(n), street) for n in m.get("street_names") or [])
                for m in steps
            ):
                return [list(p) for p in routing.decode_polyline6(legs[0].get("shape", ""))]
        return None


# --- The sources -------------------------------------------------------------------------


def read_dc(fetch: Fetch, placer, places: Places, now: datetime, sleep) -> tuple[list, list]:
    """DDOT's active permits that close a road or block a bike lane, each on its block."""
    day = now.astimezone(dc.ZONE).date().isoformat()
    permits: list[dc.Permit] = []
    for page in range(TOPS_MAX_PAGES):
        query = urllib.parse.urlencode(
            {
                "where": f"EXPIRATIONDATE >= DATE '{day}'",
                "outFields": "*",
                "outSR": "4326",
                "f": "geojson",
                "resultOffset": page * TOPS_PAGE,
                "resultRecordCount": TOPS_PAGE,
            }
        )
        document = json.loads(_get(fetch, f"{URLS[DC]}?{query}", {}, sleep))
        if isinstance(document, dict) and document.get("error"):
            raise FeedError("the layer refused the query")
        permits.extend(dc.parse_permits(document, now))
        features = document.get("features") or []
        more = document.get("exceededTransferLimit") or (document.get("properties") or {}).get(
            "exceededTransferLimit"
        )
        if not more or len(features) < TOPS_PAGE:
            break
    zones = []
    for permit in permits:
        key = f"permit:{permit.permit_id}:{permit.point[0]:.6f},{permit.point[1]:.6f}"
        line = places.get(key, lambda p=permit: placer.permit_line(p.point))
        if line:
            zones.append(dc.permit_zone(permit, line))
    return zones, []


def _advisory_zones(advisories, placer, places: Places, now: datetime) -> tuple[list, list]:
    zones, notices = [], []
    for advisory in advisories:
        if advisory.end is not None and advisory.end <= now:
            continue
        unplaced = list(advisory.unparsed)
        for index, segment in enumerate(advisory.segments):
            if segment.end is not None and segment.end <= now:
                continue
            key = "segment:" + "|".join(
                dc.street_key(s) for s in (segment.street, segment.from_street, segment.to_street)
            )
            line = places.get(key, lambda s=segment: placer.segment_line(s))
            if line:
                zones.append(dc.segment_zone(advisory, index, segment, line))
            else:
                unplaced.append(segment.text)
        if unplaced or not advisory.segments:
            notice = advisory.notice(unplaced)
            if notice.end is None or notice.end > now:
                notices.append(notice)
    return zones, notices


def read_mpd(fetch: Fetch, placer, places: Places, now: datetime, sleep) -> tuple[list, list]:
    """MPD's traffic advisories, newest first: their segments placed, the rest as text.
    Every other release is passed over on its title and never fetched."""
    listing = _get(fetch, URLS[MPD], {"Accept": "text/html"}, sleep).decode("utf-8", "replace")
    advisories = []
    for title, url in dc.traffic_advisory_links(listing)[:MPD_MAX_RELEASES]:
        try:
            page = _get(fetch, url, {"Accept": "text/html"}, sleep).decode("utf-8", "replace")
        except FeedError as error:
            logger.info("closures: an MPD release could not be read (%s)", error)
            continue
        advisory = dc.parse_mpd_release(page, url, title)
        if advisory is not None:
            advisories.append(advisory)
    return _advisory_zones(advisories, placer, places, now)


def read_alertdc(fetch: Fetch, placer, places: Places, now: datetime, sleep) -> tuple[list, list]:
    """AlertDC's traffic and road items; every other item is dropped unread."""
    feed = _get(fetch, URLS[ALERTDC], {"Accept": "application/rss+xml"}, sleep)
    advisories = dc.parse_alertdc(feed.decode("utf-8", "replace"), now)
    return _advisory_zones(advisories, placer, places, now)


def read_nps(fetch: Fetch, placer, places: Places, now: datetime, sleep) -> tuple[list, list]:
    """The NPS alerts for the region's parks, as park-level notices (never closures)."""
    query = urllib.parse.urlencode({"parkCode": ",".join(dc.NPS_PARKS), "limit": 100})
    body = _get(
        fetch,
        f"{URLS[NPS]}?{query}",
        {"X-Api-Key": nps_key(), "Accept": "application/json"},
        sleep,
    )
    return [], dc.parse_nps(json.loads(body))


READERS = {DC: read_dc, MPD: read_mpd, ALERTDC: read_alertdc, NPS: read_nps}


def _due(feed: dict, source: str, now: datetime) -> bool:
    last = rules._when(feed.get("failed_at")) or rules._when(feed.get("read_at"))
    # A minute's grace, so a fifteen-minute source is read at every fifteen-minute tick.
    return last is None or (now - last).total_seconds() >= EVERY_S[source] - 60


def refresh(
    fetch: Fetch = http_get,
    sleep=time.sleep,
    now: Callable[[], datetime] = _now,
    placer=None,
    force: bool = False,
    budget_s: float = REFRESH_BUDGET_S,
    clock: Callable[[], float] = time.monotonic,
) -> str:
    """Read every source that is due and replace the shared copy. A source that fails
    keeps its last good copy. Nothing starts past `budget_s` (`REFRESH_BUDGET_S`): a source
    not reached in time keeps its copy and is read next time. Returns a line for the run row."""
    from . import workzones
    from .models import BikeshareFeedCache

    end = clock() + budget_s

    def out_of_time() -> bool:
        return clock() >= end

    def bounded_fetch(url: str, timeout: float, headers: dict) -> bytes:
        left = end - clock()
        if left <= 0:
            raise FeedError("out of time")
        return fetch(url, min(timeout, left), headers)

    def bounded_sleep(seconds: float) -> None:
        sleep(max(0.0, min(seconds, end - clock())))

    row = BikeshareFeedCache.objects.filter(key=KEY).first()
    payload = row.payload if row is not None and isinstance(row.payload, dict) else {}
    feeds = dict(payload.get("feeds") or {})
    said = []
    sources = wanted()
    for source in list(feeds):
        if source not in sources:
            del feeds[source]  # NPS's key removed: its notices go with it
    placer = placer if placer is not None else DatabasePlacer()
    for source in sources:
        kept = feeds.get(source) or {}
        if not force and not _due(kept, source, now()):
            continue
        if out_of_time():
            said.append(f"{source} not reached in time")
            continue
        moment = now()
        places = Places(kept.get("placed"), moment, MAX_NEW_PLACES.get(source, 0), out_of_time)
        try:
            zones, notices = READERS[source](bounded_fetch, placer, places, moment, bounded_sleep)
        except (FeedError, ValueError) as error:
            logger.warning("closures: the %s source could not be read (%s)", source, error)
            feeds[source] = {**kept, "failed_at": moment.isoformat()}
            said.append(f"{source} failed")
            continue
        feeds[source] = {
            "read_at": moment.isoformat(),
            "failed_at": None,
            "zones": [zone.to_json() for zone in zones],
            "notices": [notice.to_json() for notice in notices],
            "placed": places.used,
        }
        said.append(f"{source} {len(zones)} closures, {len(notices)} notices")
    BikeshareFeedCache.objects.update_or_create(
        key=KEY,
        defaults={"payload": {"feeds": feeds}, "fetched_at": now(), "failed_at": None},
    )
    workzones.forget()
    return "closures: " + (", ".join(said) if said else "nothing due")


def status_of(source: str, read_at: datetime | None, now: datetime) -> str:
    """CURRENT, STALE or UNAVAILABLE for a source's copy read at `read_at`."""
    from .workzones import CURRENT, STALE, UNAVAILABLE

    if read_at is None:
        return UNAVAILABLE
    age = (now - read_at).total_seconds()
    if age > DROP_AFTER_S[source]:
        return UNAVAILABLE
    return CURRENT if age <= STALE_AFTER_S[source] else STALE


def load(payload: dict, now: datetime) -> tuple[list, list, dict, dict]:
    """The row's zones, notices, each source's status and read time, as the planner uses
    them: a source past `DROP_AFTER_S` contributes nothing."""
    feeds = payload.get("feeds") or {}
    zones: list[rules.Zone] = []
    notices: list[dc.Notice] = []
    status: dict[str, str] = {}
    read_at: dict[str, str | None] = {}
    for source in sorted(set(feeds) | PUBLIC):
        feed = feeds.get(source) or {}
        read_at[source] = feed.get("read_at")
        status[source] = status_of(source, rules._when(feed.get("read_at")), now)
        if status[source] == "unavailable":
            continue
        for row in feed.get("zones") or []:
            try:
                zones.append(rules.Zone.from_json(row))
            except (KeyError, TypeError, ValueError):
                continue
        for row in feed.get("notices") or []:
            try:
                notices.append(dc.Notice.from_json(row))
            except (KeyError, TypeError, ValueError):
                continue
    return zones, notices, status, read_at


__all__ = ["KEY", "DatabasePlacer", "load", "refresh", "wanted"]
