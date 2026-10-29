"""The road panel's street photo (v0.7.0): the newest Mapillary photo of the road at a spot.

The owner, 2026-10-13 14:02 UTC: "Yes. Do that. Some of the photos are older, so make sure the date
is listed too." The photo is the newest Mapillary image within `NEAR_M` (about 100 ft) of the spot
on the road that faces along the road (within `FACING_DEG` of its bearing, either way); a
panorama is left out (its picture is a flattened sphere). The answer gives its image URL (this
server's `/api/street-photo/image/<id>`, which fetches the file from Mapillary's image host, so the
page's CSP stays same-origin and the rider's browser never contacts Mapillary), the month it was
taken, its creator where Mapillary names one, and the
link to Mapillary's own viewer at that image (opened in a new tab: no embedded viewer, no
MapillaryJS; the owner, 14:51 UTC: "Site would be fine").

The client token (`settings.MAPILLARY_ACCESS_TOKEN`, Mapillary's `MLY|...` client access token, set
on the server by the owner) is used here only: sent in the `Authorization` header to
`graph.mapillary.com`, never in a URL, a log line or an answer. With no token there is no photo,
and the panel says nothing of one.

What Mapillary is sent: a box about 200 ft (60 m) across around the point on the road (never the
rider's own position, and nothing of the rider). The answer is kept in this process's memory for
`KEEP_S` (2 minutes), so the same road asked again soon asks Mapillary once; it is keyed by the
spot asked about, so a sweep drops it at that age even when nothing else is asked (Stephen
2026-10-29: nothing that could identify a person's location stays on the server for more than
2 minutes). A photo's signed file URL is kept by its image id for `CACHE_S`: an image id is not
where anyone was. Only photos inside the covered area
(`settings.COVERAGE_BBOX`) are looked up or served, and neither fetch follows a redirect, so
every request goes to the host it names.

Licence: Mapillary's imagery is CC BY-SA 4.0 (<https://www.mapillary.com/terms>); the panel
credits "Mapillary" with a link, and the creator's name where given (docs/SOURCES.md).
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime

from django.conf import settings
from django.db import connection

from pipeline.schema import validate_schema_name

logger = logging.getLogger(__name__)

API_URL = "https://graph.mapillary.com/images"
# One image's record, to find its file again in a process that did not show it (StreetPhoto.image),
# with where it was taken, so only a photo of the covered area is served.
IMAGE_API_URL = "https://graph.mapillary.com/{id}?fields=thumb_1024_url,geometry"
API_HOSTS = frozenset({"graph.mapillary.com"})
# Where Mapillary serves its image files (its CDN), the only hosts an image URL may name. This
# server fetches the file (`StreetPhoto.image`); the page's CSP names no other host.
IMAGE_HOST_SUFFIXES = (".fbcdn.net", ".mapillary.com")
VIEWER_URL = "https://www.mapillary.com/app/?pKey={id}&focus=photo"
FIELDS = (
    "id,captured_at,compass_angle,computed_compass_angle,thumb_1024_url,geometry,is_pano,creator"
)
CREDIT = "Mapillary"
LICENCE = "CC BY-SA"
LICENCE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"
CREDIT_URL = "https://www.mapillary.com/"

NEAR_M = 30.0  # about 100 ft
FACING_DEG = 45.0
LIMIT = 100
TIMEOUT_S = 4.0
MAX_BYTES = 2_000_000
CACHE_S = 3600.0  # Mapillary's image URLs are signed for a while; an hour stays inside it
KEEP_S = 120.0  # an answer keyed by the spot asked about, as core.weather keeps its cells
CACHE_SIZE = 2000
IMAGE_CACHE_SIZE = 64  # image files held in memory, the most recently shown
IMAGE_PATH = "/api/street-photo/image/{id}"
USER_AGENT = "RouteMaker-street-photo"
NONE_WORDS = "No street photo here."

Fetch = Callable[[str, dict, float], bytes]


class Unavailable(Exception):
    """Mapillary did not answer."""


def token() -> str:
    return (getattr(settings, "MAPILLARY_ACCESS_TOKEN", "") or "").strip()


def configured() -> bool:
    return bool(token())


class _NoFollow(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # urllib then raises HTTPError: a redirect is no answer


_OPENER = urllib.request.build_opener(_NoFollow)


def in_area(lon: float, lat: float) -> bool:
    """Whether a point is inside the covered area (`settings.COVERAGE_BBOX`)."""
    west, south, east, north = settings.COVERAGE_BBOX
    return west <= lon <= east and south <= lat <= north


def http_get(url: str, headers: dict, timeout: float) -> bytes:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in API_HOSTS:
        raise Unavailable("not a Mapillary API URL")
    request = urllib.request.Request(url, headers=headers)
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            body = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise Unavailable(f"HTTP {error.code}") from None
    except (TimeoutError, urllib.error.URLError, ConnectionError, OSError) as error:
        raise Unavailable(type(error).__name__) from None
    if len(body) > MAX_BYTES:
        raise Unavailable("larger than expected")
    return body


def image_get(url: str, headers: dict, timeout: float) -> bytes:
    """One image file from Mapillary's image host (no token: the URL is signed)."""
    if not image_url_ok(url):
        raise Unavailable("not a Mapillary image URL")
    request = urllib.request.Request(url, headers=headers)
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            body = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise Unavailable(f"HTTP {error.code}") from None
    except (TimeoutError, urllib.error.URLError, ConnectionError, OSError) as error:
        raise Unavailable(type(error).__name__) from None
    if len(body) > MAX_BYTES:
        raise Unavailable("larger than expected")
    return body


def box(lon: float, lat: float, metres: float = NEAR_M) -> tuple[float, float, float, float]:
    dlat = metres / 110_540.0
    dlon = metres / (111_320.0 * max(0.2, math.cos(math.radians(lat))))
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat)


def search_url(lon: float, lat: float) -> str:
    west, south, east, north = box(lon, lat)
    query = urllib.parse.urlencode(
        {
            "fields": FIELDS,
            "bbox": f"{west:.6f},{south:.6f},{east:.6f},{north:.6f}",
            "limit": LIMIT,
        }
    )
    return f"{API_URL}?{query}"


def _metres(a, b) -> float:
    lat = math.radians((a[1] + b[1]) / 2)
    return math.hypot((a[0] - b[0]) * 111_320.0 * math.cos(lat), (a[1] - b[1]) * 110_540.0)


def _angle_off(a: float, b: float) -> float:
    """How far apart two compass bearings are, 0 to 180 degrees."""
    d = abs(a - b) % 360.0
    return 360.0 - d if d > 180.0 else d


def facing_along(compass: float, bearing: float | None) -> bool:
    """Whether a camera bearing looks along a road of `bearing`, either way (any, with no
    bearing known)."""
    if bearing is None:
        return True
    return min(_angle_off(compass, bearing), _angle_off(compass, bearing + 180.0)) <= FACING_DEG


def image_url_ok(url: object) -> bool:
    if not isinstance(url, str):
        return False
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    return parts.scheme == "https" and any(host.endswith(s) for s in IMAGE_HOST_SUFFIXES)


def month_words(when: datetime) -> str:
    return f"{when:%B} {when.year}"


def choose(doc, lon: float, lat: float, bearing: float | None) -> dict | None:
    """The newest photo within `NEAR_M` facing along the road, as the API answers it."""
    items = doc.get("data") if isinstance(doc, dict) else None
    best: tuple[int, dict] | None = None
    for item in items if isinstance(items, list) else ():
        if not isinstance(item, dict) or item.get("is_pano") is True:
            continue
        try:
            point = item["geometry"]["coordinates"]
            here = (float(point[0]), float(point[1]))
            captured = int(item["captured_at"])
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        if _metres(here, (lon, lat)) > NEAR_M or not image_url_ok(item.get("thumb_1024_url")):
            continue
        compass = item.get("computed_compass_angle", item.get("compass_angle"))
        if not isinstance(compass, int | float) or not facing_along(float(compass), bearing):
            continue
        image_id = str(item.get("id") or "")
        if not image_id.isdigit():
            continue
        if best is None or captured > best[0]:
            best = (captured, item)
    if best is None:
        return None
    captured, item = best
    when = datetime.fromtimestamp(captured / 1000.0, UTC)
    creator = item.get("creator")
    name = creator.get("username") if isinstance(creator, dict) else None
    return {
        "found": True,
        "image_id": str(item["id"]),
        "image_url": item["thumb_1024_url"],
        "viewer_url": VIEWER_URL.format(id=item["id"]),
        "captured": when.date().isoformat(),
        "date_words": f"Photo from {month_words(when)}",
        "creator": name if isinstance(name, str) and name.strip() else None,
        "credit": CREDIT,
        "credit_url": CREDIT_URL,
        "licence": LICENCE,
        "licence_url": LICENCE_URL,
    }


NONE = {"found": False, "words": NONE_WORDS}


def road_bearing(way_id: int, lon: float, lat: float) -> float | None:
    """The road's compass bearing at the spot, from its nearest live segment, or None."""
    schema = validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
    sql = f"""
        WITH spot AS (SELECT ST_SetSRID(ST_MakePoint(%s, %s), 4326) AS g),
             seg AS (SELECT s.geometry AS g FROM {schema}.segment s, spot
                     WHERE s.osm_way_id = %s
                       AND GeometryType(s.geometry) = 'LINESTRING'
                     ORDER BY s.geometry <-> spot.g LIMIT 1),
             at AS (SELECT seg.g, ST_LineLocatePoint(seg.g, spot.g) AS t FROM seg, spot)
        SELECT degrees(ST_Azimuth(
                   ST_LineInterpolatePoint(g, greatest(0.0, t - 0.05))::geography,
                   ST_LineInterpolatePoint(g, least(1.0, t + 0.05))::geography))
        FROM at
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, [lon, lat, way_id])
            row = cursor.fetchone()
    except Exception as error:  # noqa: BLE001 - no bearing is a photo facing any way
        logger.warning("street photo: no road bearing: %s", type(error).__name__)
        return None
    return None if row is None or row[0] is None else float(row[0])


def _daemon_timer(delay: float, run: Callable[[], None]) -> None:
    timer = threading.Timer(delay, run)
    timer.daemon = True
    timer.start()


class StreetPhoto:
    """Looks a road's photo up, and remembers the answer for `KEEP_S`."""

    def __init__(
        self,
        fetch: Fetch = http_get,
        clock: Callable[[], float] = time.monotonic,
        bearing: Callable[[int, float, float], float | None] = road_bearing,
        fetch_image: Fetch = image_get,
        later: Callable[[float, Callable[[], None]], None] | None = None,
    ) -> None:
        self._fetch = fetch
        # Runs a function after a delay: a sweep that drops an answer once it is `KEEP_S` old
        # even when no other spot is asked about (core.weather's sweep, the same way).
        self._later = later or _daemon_timer
        self._sweep_due = False
        self._fetch_image = fetch_image
        # A photo id -> (when, Mapillary's signed URL), shown here or looked up again (`_resolve`).
        self._sources: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._images: OrderedDict[str, bytes] = OrderedDict()
        self._clock = clock
        self._bearing = bearing
        self._lock = threading.Lock()
        self._cache: OrderedDict[tuple, tuple[float, dict]] = OrderedDict()
        self.lookups = 0

    def _sweep(self) -> None:
        with self._lock:
            self._sweep_due = False
            now = self._clock()
            self._prune(now)
            if self._cache:
                # Next when the oldest left turns `KEEP_S` old, so none outlives it.
                oldest = min(at for at, _ in self._cache.values())
                self._schedule(max(0.0, oldest + KEEP_S - now))

    def _schedule(self, delay: float = KEEP_S) -> None:
        """A sweep in `delay` seconds, unless one is due (called with the lock held)."""
        if not self._sweep_due:
            self._sweep_due = True
            self._later(delay, self._sweep)

    def _prune(self, now: float) -> None:
        for key in [k for k, (at, _) in self._cache.items() if now - at >= KEEP_S]:
            del self._cache[key]

    def photo(self, lon: float, lat: float, way_id: int | None) -> dict | None:
        """The photo, `NONE` where there is none, or None where none can be looked up (no
        token, or Mapillary not answering): the panel then says nothing of a photo."""
        if not configured():
            return None
        if not in_area(lon, lat):
            return NONE
        key = (way_id, round(lon, 4), round(lat, 4))
        now = self._clock()
        with self._lock:
            self._prune(now)
            held = self._cache.get(key)
            if held is not None:
                self._cache.move_to_end(key)
                return held[1]
        bearing = self._bearing(way_id, lon, lat) if way_id is not None else None
        headers = {
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "Authorization": f"OAuth {token()}",
        }
        self.lookups += 1
        try:
            doc = json.loads(self._fetch(search_url(lon, lat), headers, TIMEOUT_S))
        except (Unavailable, ValueError) as error:
            logger.warning("street photo: Mapillary did not answer: %s", error)
            return None
        chosen = choose(doc, lon, lat, bearing)
        found = NONE
        if chosen is not None:
            image_id = chosen.pop("image_id")
            source = chosen["image_url"]
            found = {**chosen, "image_url": IMAGE_PATH.format(id=image_id)}
            with self._lock:
                self._sources[image_id] = (now, source)
                while len(self._sources) > CACHE_SIZE:
                    self._sources.popitem(last=False)
        with self._lock:
            self._cache[key] = (now, found)
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
            self._schedule()
        return found

    def _resolve(self, image_id: str) -> str | None:
        """Mapillary's signed file URL for one image, asked of the Graph API (the token in the
        `Authorization` header only), or None. Used when this process did not show the photo:
        gunicorn runs several workers, and the one that showed it may not be this one."""
        if not configured() or not image_id.isdigit():
            return None
        headers = {
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "Authorization": f"OAuth {token()}",
        }
        self.lookups += 1
        try:
            doc = json.loads(self._fetch(IMAGE_API_URL.format(id=image_id), headers, TIMEOUT_S))
        except (Unavailable, ValueError) as error:
            logger.warning("street photo: Mapillary did not answer: %s", error)
            return None
        url = doc.get("thumb_1024_url") if isinstance(doc, dict) else None
        if not image_url_ok(url):
            return None
        try:
            point = doc["geometry"]["coordinates"]
            taken = (float(point[0]), float(point[1]))
        except (KeyError, TypeError, ValueError, IndexError):
            return None
        if not in_area(*taken):
            return None
        with self._lock:
            self._sources[image_id] = (self._clock(), url)
            while len(self._sources) > CACHE_SIZE:
                self._sources.popitem(last=False)
        return url

    def image(self, image_id: str) -> bytes | None:
        """A photo's file, fetched from Mapillary's image host (and kept), or None: no such
        photo, or Mapillary not answering. A photo this process showed within `CACHE_S` is
        fetched from the URL it was given; any other is looked up again first (`_resolve`)."""
        now = self._clock()
        with self._lock:
            held = self._images.get(image_id)
            if held is not None:
                self._images.move_to_end(image_id)
                return held
            source = self._sources.get(image_id)
        url = source[1] if source is not None and now - source[0] < CACHE_S else None
        if url is None:
            url = self._resolve(image_id)
        if url is None:
            return None
        try:
            body = self._fetch_image(url, {"User-Agent": USER_AGENT}, TIMEOUT_S)
        except Unavailable as error:
            logger.warning("street photo: the image did not load: %s", error)
            return None
        with self._lock:
            self._images[image_id] = body
            while len(self._images) > IMAGE_CACHE_SIZE:
                self._images.popitem(last=False)
        return body


client = StreetPhoto()
