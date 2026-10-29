"""Link previews for shared links (v0.7.0; PLAN's social share card, as OpenGraph and Twitter
card tags, for the chat apps that fetch a link to show it).

A shared link is `/s/<id>#<the plan's inputs>&route=<id>` (frontend/src/lib/sharedRoutes.ts): the
path names the kept route, since a fetcher never sends the fragment. A browser opening it is sent
on to the page (`/?route=<id>`; the browser carries the fragment over the redirect), and a link
fetcher (`is_fetcher`) gets a page of tags only:

- og:title, the ride type and the distance ("Group Ride, 12.4 mi (20.0 km)"), never the route's
  name, which can hold Home's label or a place;
- og:description, the distance and the climb, US units first with metric in brackets;
- og:image, a 1200 x 630 PNG drawn here (`render_png`): the route's line over the base map (the
  owner, 2026-10-25: "Is it possible to add the base map to the route preview?"; core.
  preview_basemap draws it from the app's own archive, with its credits, and the picture is on a
  plain background when there is none), its start, finish and stops, the same stats line, and the
  app's icon beside "RouteMaker". No imaging package (none is a dependency): the map, line and
  pins are drawn into a byte buffer and written with zlib, the text from glyph coverage made once
  from the page's own font (core.preview_glyphs and core.preview_glyphs_small, scripts/
  make_preview_glyphs.py) and the icon from core.preview_icon (scripts/make_share_images.py). The
  view is Web Mercator, as the base map's tiles are.

The app's own address (the owner, 2026-10-20: "Is there a way to have the icon when shared?"):
a link fetcher asking for `/` is handed `site_page` by the edge (the Caddyfile's @link_fetcher,
the beta's nginx `location = /`), which names the app and shows frontend/public/icons/
share-card.png, the icon and what the app does. Every address in the tags is made from the
request's own host, so no host name is written anywhere in the repository. On the beta these,
the shared links and the icons are outside its password, since a fetcher has none.

Home (the owner, 2026-10-16: "If it doesn't start, end, or stop at home keep showing the route.
Also, make this an option, default to censor."): a fetcher has no option, so a preview is always
censored. When the route starts, ends or stops inside the owner's Home circle, nothing of the line
and no pin inside it is drawn; the circle holds everything within 0.2 mi (322 m) of Home, its
centre moved 60 to 150 m from Home in a direction fixed per account by a keyed hash of the
account id (`home_zone`), so its edge never points at Home and the previews of one rider cannot be
averaged out. A route that only passes Home is drawn whole, as Share as image does
(frontend/src/lib/shareCard.ts cardRoute, which this follows). A link shared signed out names no
owner and the server knows no Home: the page sends `preview_image` false when the route starts,
ends or stops at the Home on the device, and no image is drawn; so is a link from before
previews, or from a page that does not say (`preview_image` missing is False).

The censoring is frozen when the link is made (`freeze_zone`): a route that then starts, ends or
stops in the owner's Home circle keeps that circle on the row (`preview_zone`), so moving Home
later never uncovers it. The circle's radius is the same for every account (`ZONE_RADIUS_M`), so
the gap's size says nothing of how far its centre was moved.

Over the base map, the circle keeps the map and loses only the route: a blank disc on a map would
mark Home, where on the plain background it shows nothing.

The image is cached on the row under a key of the line, Home's circle and the base map's archive
(`image_key`; the archive by its size and time, preview_basemap.stamp, so a new base map draws
the picture again), and so is "no image" (an empty `preview_png`), so a route that cannot be
drawn is not tried again. Drawing is bounded: the line is thinned to `MAX_DRAWN_POINTS` and a
stroke longer than `MAX_STROKE_PX` is no image; the base map is at most
preview_basemap.MAX_TILES tiles, its points less than a pixel apart dropped. A turned-off link
(410) or an expired one (404) has no preview. The image is served with an hour's public cache,
so a link turned off can show its old image in a chat app for up to an hour; the page with the
tags is never cached.

The picture is drawn when the link is made (the owner, 2026-10-29, "let's do that"): making or
remaking a link queues `draw_later`, which the worker runs (config.procrastinate.
draw_share_preview), so a chat app's fetch finds it kept. The page of tags never draws: it names
the image whenever one is kept or not yet tried. A fetch of an image not drawn yet (the worker
behind, or a base map that changed) draws it there, one draw at a time in the whole deployment
and never two of one route at once (`_draw_for_fetch`); a fetch that finds a draw running is told
to try again shortly (503) rather than wait.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import re
import struct
import zlib
from functools import lru_cache
from html import escape

from django.conf import settings
from django.http import HttpResponse, HttpResponseRedirect
from django.utils import timezone
from django.utils.cache import patch_vary_headers
from django.views.decorators.http import require_safe

from . import preview_basemap, ratelimit, shared_routes

logger = logging.getLogger(__name__)

METRES_PER_MILE = 1609.344
FEET_PER_METRE = 3.28084
EARTH_RADIUS_M = 6371008.8
M_PER_DEG = EARTH_RADIUS_M * math.pi / 180
# Nothing within this of Home is drawn: 0.2 mi, at least 322 m.
HOME_TRIM_M = max(0.2 * METRES_PER_MILE, 322.0)
ZONE_SHIFT_MIN_M = 60.0
ZONE_SHIFT_MAX_M = 150.0
# One radius for every account: everything within HOME_TRIM_M of Home is inside however far the
# centre moved (shareCard.ts ZONE_RADIUS_M).
ZONE_RADIUS_M = HOME_TRIM_M + ZONE_SHIFT_MAX_M + 1
# Less than this drawn would show little but where Home's circle is (shareCard.ts MIN_DRAWN_M).
MIN_DRAWN_M = HOME_TRIM_M / 2
HOME_ZONE_LABEL = b"routemaker/home-zone/v1"
# Bumped when the drawing changes, so cached images are drawn again.
IMAGE_VERSION = "4"
# The most points drawn, and the longest stroke in pixels: past it, no image (a fair route of a
# hundred miles is a few thousand pixels long; this bounds the drawing's time).
MAX_DRAWN_POINTS = 1500
MAX_STROKE_PX = 20_000

WIDTH, HEIGHT = 1200, 630
BAND = 110
MAP_H = HEIGHT - BAND
PAD = 60
BACKGROUND = (238, 242, 236)
BAND_COLOUR = (255, 255, 255)
RULE = (214, 220, 212)
LINE_COLOUR = (29, 78, 216)
LINE_RADIUS = 5.0
TEXT = (31, 41, 51)
START_COLOUR = (21, 128, 61)
FINISH_COLOUR = (185, 28, 28)
STOP_COLOUR = (31, 41, 51)
BRAND = "RouteMaker"
# The base map's town names (preview_basemap.paint).
PLACE_TEXT = (60, 60, 60)
PLACE_HALO = (255, 255, 255)
# A route of one point: the scale (pixels across the world) of a 512 px tile at zoom 15.
SINGLE_POINT_SCALE = 512.0 * 2**15
# The icon beside it (core.preview_icon, scripts/make_share_images.py).
ICON_SIZE = 56
# The parameter naming the shared line on the page (sharedRoutes.ts SHARED_PARAM).
PARAM = "route"

# The ride types' names (frontend/src/lib/presets.ts `label`, `spoken` where the label has emoji).
RIDE_NAMES = {
    "trailmaxxing": "Trailmaxxing",
    "group-ride": "Group Ride",
    "mass-ride": "Mass Ride",
    "mountain-goat": "Mountain Goat",
    "mountain-bike": "Mountain Bike",
    "gravel": "Gravel",
    "fast": "Fast",
    "cargo": "Cargo Bike",
    "ebike": "E-bike",
    "bikeshare": "Bikeshare",
    "novice": "Novice and Nervous",
    "kids": "Novice and Nervous",
    "bike-transit": "Own bike plus train or bus",
    "bikeshare-transit": "Bikeshare plus walk, train or bus",
    "rebalance": "Rebalance Ride",
}

# Who fetches a link to preview it: chat apps, social sites and search engines. A browser is sent
# on to the page instead.
FETCHER_RE = re.compile(
    r"bot\b|bot/|crawler|spider|facebookexternalhit|facebot|slack|whatsapp|telegram|"
    r"skypeuripreview|embedly|iframely|mastodon|pleroma|pinterest|vkshare|googlemessages|preview",
    re.IGNORECASE,
)


# ---- Words ----


def _round_short(value: float) -> int:
    return round(value / 10) * 10 if value >= 100 else round(value)


def format_distance(metres: float) -> str:
    """As the page says it (frontend/src/lib/format.ts formatDistance): "4.7 mi (7.6 km)", and
    below a tenth of a mile "500 ft (150 m)"."""
    if metres < METRES_PER_MILE / 10:
        return f"{_round_short(metres * FEET_PER_METRE)} ft ({_round_short(metres)} m)"
    return f"{metres / METRES_PER_MILE:.1f} mi ({metres / 1000:.1f} km)"


def format_climb(metres: float) -> str:
    """ "1,234 ft (376 m)" (format.ts formatClimb)."""
    return f"{round(metres * FEET_PER_METRE):,} ft ({round(metres):,} m)"


def climb_of(row) -> float | None:
    """The route's climb: a planned route's own figure, or an opened file's rises (counted past a
    2 m step, so a track's noise is not summed)."""
    answer = row.answer if isinstance(row.answer, dict) else None
    if answer and isinstance(answer.get("climb_m"), int | float):
        return float(answer["climb_m"])
    heights = [p[2] for p in row.line or [] if len(p) > 2 and isinstance(p[2], int | float)]
    if len(heights) < 2:
        return None
    climb, low = 0.0, heights[0]
    for h in heights[1:]:
        if h - low >= 2:
            climb += h - low
            low = h
        elif h < low:
            low = h
    return climb


def ride_name(row) -> str:
    if row.source == "gpx":
        return "GPX route"
    preset = str((row.inputs or {}).get("preset", ""))
    return RIDE_NAMES.get(preset, "Bike ride")


def stats_line(row) -> str:
    climb = climb_of(row)
    distance = format_distance(row.distance_m)
    return f"{distance} · {format_climb(climb)} climb" if climb and climb >= 1 else distance


def title(row) -> str:
    """The ride type and the distance; never the route's name (it can hold Home or a place)."""
    return f"{ride_name(row)}, {format_distance(row.distance_m)}"


def description(row) -> str:
    climb = climb_of(row)
    distance = format_distance(row.distance_m)
    if climb and climb >= 1:
        return f"{distance} with {format_climb(climb)} of climbing. Planned with {BRAND}."
    return f"{distance}. Planned with {BRAND}."


# ---- Home ----


def _haversine(a, b) -> float:
    lat1, lat2 = math.radians(a[1]), math.radians(b[1])
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(math.radians(b[0] - a[0]) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(min(1.0, h)))


def zone_jitter(user_id: int) -> tuple[float, float]:
    """Two numbers from 0 to 1, fixed per account and unguessable without the server's secret."""
    key = hmac.new(settings.SECRET_KEY.encode(), HOME_ZONE_LABEL, hashlib.sha256).digest()
    digest = hmac.new(key, f"user:{user_id}".encode(), hashlib.sha256).digest()
    return (
        int.from_bytes(digest[:4], "big") / 2**32,
        int.from_bytes(digest[4:8], "big") / 2**32,
    )


def home_zone(home, jitter) -> tuple[tuple[float, float], float] | None:
    """Home's hidden circle, (centre, radius in metres), as shareCard.ts homeZone: the centre moved
    60 to 150 m from Home, and one radius for all (ZONE_RADIUS_M), so all within HOME_TRIM_M is
    inside."""
    if home is None:
        return None
    shift = ZONE_SHIFT_MIN_M + min(max(jitter[1], 0.0), 1.0) * (ZONE_SHIFT_MAX_M - ZONE_SHIFT_MIN_M)
    angle = jitter[0] * 2 * math.pi
    lon, lat = home
    centre = (
        lon + math.cos(angle) * shift / (M_PER_DEG * math.cos(math.radians(lat))),
        lat + math.sin(angle) * shift / M_PER_DEG,
    )
    return centre, ZONE_RADIUS_M


def owner_zone(row):
    """The owner's Home circle, or None (signed out, or no Home)."""
    from .models import MyGo

    if row.owner_id is None:
        return None
    go = MyGo.objects.filter(user_id=row.owner_id).first()
    if go is None or go.home_lat is None or go.home_lon is None:
        return None
    return home_zone((go.home_lon, go.home_lat), zone_jitter(row.owner_id))


def row_zone(row):
    """The circle a row's image is censored with: the one frozen when the link was made, else
    the owner's Home circle now (a Home set later can only hide more)."""
    frozen = row.preview_zone
    if isinstance(frozen, list) and len(frozen) == 3:
        return (float(frozen[0]), float(frozen[1])), float(frozen[2])
    return owner_zone(row)


def at_home(line, points, zone) -> bool:
    """Whether the route starts, ends or stops in the circle."""
    line = line or []
    return bool(line) and (
        _in_zone(line[0], zone)
        or _in_zone(line[-1], zone)
        or any(_in_zone(p, zone) for p in points)
    )


def freeze_zone(row) -> None:
    """At the link's making: keep the owner's Home circle on the row when the route starts, ends
    or stops in it, so a later Home never uncovers it (not saved here)."""
    zone = owner_zone(row)
    if zone is not None and at_home(row.line, route_points(row), zone):
        row.preview_zone = [zone[0][0], zone[0][1], zone[1]]


def _in_zone(p, zone) -> bool:
    return p is not None and zone is not None and _haversine(p[:2], zone[0]) <= zone[1]


def drawn_route(line, points, zone) -> dict | None:
    """What the image draws (shareCard.ts cardRoute): the whole line, or, when it starts, ends or
    stops in Home's circle, the pieces outside it and the pins outside it. None when too little
    is left to draw."""
    line = [(float(p[0]), float(p[1])) for p in line or []]
    points = [(float(p[0]), float(p[1])) for p in points or []]
    if len(line) < 2:
        return None
    # Thinned before the cut, so no chord of the drawn line can cut into Home's circle.
    line = _thinned([line])[0]
    zone = zone if at_home(line, points, zone) else None
    clon, clat = zone[0] if zone else (0.0, 0.0)
    kx = M_PER_DEG * math.cos(math.radians(clat))
    r2 = zone[1] ** 2 if zone else -1.0

    def xy(p):
        return (p[0] - clon) * kx, (p[1] - clat) * M_PER_DEG

    pieces: list[list[tuple[float, float]]] = []
    piece: list[tuple[float, float]] | None = None
    drawn_m = 0.0
    for a, b in zip(line, line[1:], strict=False):
        ax, ay = xy(a)
        bx, by = xy(b)
        dx, dy = bx - ax, by - ay
        ts = [0.0, 1.0]
        qa = dx * dx + dy * dy
        if zone and qa > 0:
            qb = 2 * (ax * dx + ay * dy)
            disc = qb * qb - 4 * qa * (ax * ax + ay * ay - r2)
            if disc > 0:
                for t in ((-qb - math.sqrt(disc)) / (2 * qa), (-qb + math.sqrt(disc)) / (2 * qa)):
                    if 0 < t < 1:
                        ts.append(t)
        ts.sort()
        seg = _haversine(a, b)
        for t0, t1 in zip(ts, ts[1:], strict=False):
            mid = (t0 + t1) / 2
            mx, my = ax + dx * mid, ay + dy * mid
            if zone and mx * mx + my * my <= r2:
                piece = None
                continue
            p0 = (a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0)
            p1 = (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1)
            if piece is None:
                piece = [p0]
                pieces.append(piece)
            piece.append(p1)
            drawn_m += seg * (t1 - t0)
    if not pieces or drawn_m < MIN_DRAWN_M:
        return None
    first, last = line[0], line[-1]
    return {
        "pieces": pieces,
        # The circle cut, or None: the drawing leaves it blank whatever its stroke and pins reach.
        "zone": zone,
        "start": None if _in_zone(first, zone) or (points and _in_zone(points[0], zone)) else first,
        "finish": None if _in_zone(last, zone) or (points and _in_zone(points[-1], zone)) else last,
        "stops": [p for p in points[1:-1] if not _in_zone(p, zone)],
    }


def route_points(row) -> list:
    points = (row.inputs or {}).get("points") or []
    return [p for p in points if isinstance(p, list | tuple) and len(p) >= 2]


def image_key(row, zone) -> str:
    """What the cached image was drawn from: the line, the stops and Home's circle."""
    body = json.dumps(
        [
            IMAGE_VERSION,
            preview_basemap.stamp(),
            row.line,
            route_points(row),
            stats_line(row),
            zone,
        ],
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode()).hexdigest()


# ---- Drawing ----


@lru_cache(maxsize=2)
def _glyph_data(module: str) -> bytes:
    import base64
    import importlib

    return zlib.decompress(base64.b64decode("".join(importlib.import_module(module).DATA)))


@lru_cache(maxsize=1)
def _icon_data() -> bytes:
    import base64

    from . import preview_icon

    assert preview_icon.SIZE == ICON_SIZE
    return zlib.decompress(base64.b64decode("".join(preview_icon.DATA)))


class _Canvas:
    def __init__(self) -> None:
        self.px = bytearray(
            bytes(BACKGROUND) * (WIDTH * MAP_H) + bytes(BAND_COLOUR) * (WIDTH * BAND)
        )

    def blend(self, x: int, y: int, colour, alpha: float) -> None:
        if alpha <= 0 or not (0 <= x < WIDTH and 0 <= y < HEIGHT):
            return
        i = (y * WIDTH + x) * 3
        px = self.px
        if alpha >= 1:
            px[i : i + 3] = bytes(colour)
            return
        for k in range(3):
            px[i + k] = round(px[i + k] + (colour[k] - px[i + k]) * alpha)

    def disc(self, cx: float, cy: float, r: float, colour) -> None:
        for y in range(int(cy - r - 1), int(cy + r + 2)):
            for x in range(int(cx - r - 1), int(cx + r + 2)):
                d = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
                self.blend(x, y, colour, min(1.0, r + 0.5 - d))

    def text(self, x: int, baseline: int, words: str, colour, g=None) -> None:
        from . import preview_glyphs

        g = g or preview_glyphs
        data = _glyph_data(g.__name__)
        top = baseline - g.ASCENT
        for ch in words:
            glyph = g.GLYPHS.get(ch) or g.GLYPHS["?"]
            advance, left, width, offset = glyph
            for row in range(g.HEIGHT):
                base = offset + row * width
                for col in range(width):
                    c = data[base + col]
                    if c:
                        self.blend(x + left + col, top + row, colour, c / 255)
            x += advance

    def image(self, x: int, y: int, size: int, rgba: bytes) -> None:
        for row in range(size):
            for col in range(size):
                i = (row * size + col) * 4
                self.blend(x + col, y + row, rgba[i : i + 3], rgba[i + 3] / 255)

    def png(self) -> bytes:
        raw = bytearray()
        stride = WIDTH * 3
        for y in range(HEIGHT):
            raw.append(0)
            raw += self.px[y * stride : (y + 1) * stride]

        def chunk(kind: bytes, body: bytes) -> bytes:
            crc = zlib.crc32(kind + body) & 0xFFFFFFFF
            return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

        header = struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0)
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
            + chunk(b"IEND", b"")
        )


def text_width(words: str, g=None) -> int:
    from . import preview_glyphs

    g = g or preview_glyphs
    return sum((g.GLYPHS.get(ch) or g.GLYPHS["?"])[0] for ch in words)


def _line_coverage(paths: list[list[tuple[float, float]]], radius: float) -> bytearray:
    """How much of each map pixel the line covers, 0 to 255: each segment as a round-capped
    stroke, taken in pieces of at most 8 px so no box is much bigger than the stroke."""
    cover = bytearray(WIDTH * MAP_H)
    reach = radius + 0.5
    for path in paths:
        for (ax, ay), (bx, by) in zip(path, path[1:], strict=False):
            length = math.hypot(bx - ax, by - ay)
            steps = max(1, math.ceil(length / 8))
            for s in range(steps):
                x0, y0 = ax + (bx - ax) * s / steps, ay + (by - ay) * s / steps
                x1, y1 = ax + (bx - ax) * (s + 1) / steps, ay + (by - ay) * (s + 1) / steps
                dx, dy = x1 - x0, y1 - y0
                q = dx * dx + dy * dy
                for y in range(
                    max(0, int(min(y0, y1) - reach)), min(MAP_H, int(max(y0, y1) + reach) + 1)
                ):
                    py = y + 0.5
                    for x in range(
                        max(0, int(min(x0, x1) - reach)), min(WIDTH, int(max(x0, x1) + reach) + 1)
                    ):
                        px = x + 0.5
                        t = (
                            0.0
                            if q == 0
                            else max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / q))
                        )
                        d = math.hypot(px - x0 - dx * t, py - y0 - dy * t)
                        c = reach - d
                        if c > 0:
                            v = 255 if c >= 1 else int(c * 255)
                            i = y * WIDTH + x
                            if v > cover[i]:
                                cover[i] = v
    return cover


def _thinned(pieces: list[list[tuple[float, float]]]) -> list[list[tuple[float, float]]]:
    """At most about MAX_DRAWN_POINTS points in all, each piece keeping its ends."""
    total = sum(len(piece) for piece in pieces)
    step = max(1, math.ceil(total / MAX_DRAWN_POINTS))
    if step == 1:
        return pieces
    return [piece[::step] + ([piece[-1]] if (len(piece) - 1) % step else []) for piece in pieces]


def view(drawn: dict):
    """The picture's view of the drawn route, in Web Mercator as the base map's tiles are: its
    centre (preview_basemap.world_xy), its scale in pixels across the world, and `at`, a point's
    place on the picture."""
    everything = [preview_basemap.world_xy(*p) for piece in drawn["pieces"] for p in piece]
    xs = [p[0] for p in everything]
    ys = [p[1] for p in everything]
    span_x, span_y = max(xs) - min(xs), max(ys) - min(ys)
    scale = min(
        (WIDTH - 2 * PAD) / span_x if span_x > 0 else math.inf,
        (MAP_H - 2 * PAD) / span_y if span_y > 0 else math.inf,
    )
    if not math.isfinite(scale):
        scale = SINGLE_POINT_SCALE
    centre = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2

    def at(p):
        x, y = preview_basemap.world_xy(p[0], p[1])
        return WIDTH / 2 + (x - centre[0]) * scale, MAP_H / 2 + (y - centre[1]) * scale

    return centre, scale, at


def _place_labels(canvas: _Canvas, places, taken: list, line: bytearray) -> None:
    """The base map's town names, each with a white halo, none over another, a box in `taken`
    or the line (its coverage)."""
    from . import preview_glyphs_small as small

    for x, y, name in places:
        w = text_width(name, small)
        # On the place, else just above or below it (clear of a pin there).
        for at_y in (y, y - 24, y + 30):
            box = (
                x - w / 2 - 4,
                at_y - small.ASCENT - 2,
                x + w / 2 + 4,
                at_y + small.HEIGHT - small.ASCENT + 2,
            )
            if box[0] < 4 or box[2] > WIDTH - 4 or box[1] < 4 or box[3] > MAP_H - 4:
                continue
            if any(
                box[0] < t[2] and t[0] < box[2] and box[1] < t[3] and t[1] < box[3] for t in taken
            ):
                continue
            x0, x1 = int(box[0]), int(box[2]) + 1
            if any(
                any(line[k * WIDTH + x0 : k * WIDTH + x1])
                for k in range(int(box[1]), int(box[3]) + 1)
            ):
                continue
            taken.append(box)
            left = round(x - w / 2)
            for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, 1), (-1, 1), (1, -1)):
                canvas.text(left + dx, round(at_y) + dy, name, PLACE_HALO, small)
            canvas.text(left, round(at_y), name, PLACE_TEXT, small)
            break


def render_png(drawn: dict, stats: str) -> bytes | None:
    """The preview: the drawn route over the base map (on a plain background when there is
    none), its pins, and the stats and credit; None when its stroke is too long to draw
    (MAX_STROKE_PX)."""
    centre, scale, at = view(drawn)
    paths = []
    for piece in drawn["pieces"]:
        path = []
        for p in piece:
            q = at(p)
            if not path or math.hypot(q[0] - path[-1][0], q[1] - path[-1][1]) >= 1.5:
                path.append(q)
        last = at(piece[-1])
        if path[-1] != last:
            path.append(last)
        paths.append(path if len(path) > 1 else [path[0], path[0]])
    stroke = sum(
        math.hypot(b[0] - a[0], b[1] - a[1])
        for path in paths
        for a, b in zip(path, path[1:], strict=False)
    )
    if stroke > MAX_STROKE_PX:
        return None
    canvas = _Canvas()
    places = preview_basemap.paint(canvas.px, WIDTH, MAP_H, centre, scale)
    if places is not None:
        from . import preview_glyphs_small as small

        # The credit the base map owes, at the map's foot (docs/OPERATIONS.md).
        credit_w = text_width(preview_basemap.CREDIT, small)
        x0, y0 = WIDTH - credit_w - 16, MAP_H - small.HEIGHT - 6
        for y in range(y0, MAP_H):
            for x in range(x0, WIDTH):
                canvas.blend(x, y, BAND_COLOUR, 0.85)
        canvas.text(x0 + 8, y0 + 3 + small.ASCENT, preview_basemap.CREDIT, TEXT, small)
        # A white edge round the line, as the app's map draws it, so it stands off the roads.
        casing = _line_coverage(paths, LINE_RADIUS + 2.5)
        # No name over the line, a pin or the credit.
        taken = [(x0, y0, WIDTH, MAP_H)]
        for p in [drawn["start"], drawn["finish"], *drawn["stops"]]:
            if p is not None:
                x, y = at(p)
                taken.append((x - 16, y - 16, x + 16, y + 16))
        _place_labels(canvas, places, taken, casing)
    # The map as it is before the route: Home's circle shows it again below.
    under = bytes(canvas.px)
    if places is not None:
        for i, c in enumerate(casing):
            if c:
                canvas.blend(i % WIDTH, i // WIDTH, BAND_COLOUR, c / 255)
    cover = _line_coverage(paths, LINE_RADIUS)
    for i, c in enumerate(cover):
        if c:
            canvas.blend(i % WIDTH, i // WIDTH, LINE_COLOUR, c / 255)
    for stop in drawn["stops"]:
        x, y = at(stop)
        canvas.disc(x, y, 9, BAND_COLOUR)
        canvas.disc(x, y, 6, STOP_COLOUR)
    for end, colour in ((drawn["finish"], FINISH_COLOUR), (drawn["start"], START_COLOUR)):
        if end is not None:
            x, y = at(end)
            canvas.disc(x, y, 14, BAND_COLOUR)
            canvas.disc(x, y, 10, colour)
    zone = drawn.get("zone")
    if zone:
        # Nothing of the route inside Home's circle, not even a round line end or a pin's edge.
        # The base map stays, as Share as image keeps it (shareCard.ts): its streets are anyone's,
        # and a blank disc on it would mark where Home is.
        cx, cy = at(zone[0])
        r = zone_radius_px(zone, scale)
        for y in range(max(0, int(cy - r - 1)), min(MAP_H, int(cy + r + 2))):
            for x in range(max(0, int(cx - r - 1)), min(WIDTH, int(cx + r + 2))):
                if (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2 <= r * r:
                    i = (y * WIDTH + x) * 3
                    canvas.px[i : i + 3] = under[i : i + 3]
    for x in range(WIDTH):
        canvas.blend(x, MAP_H, RULE, 1)
    baseline = MAP_H + (BAND + 24) // 2
    canvas.text(40, baseline, stats, TEXT)
    brand_x = WIDTH - 40 - text_width(BRAND)
    canvas.text(brand_x, baseline, BRAND, LINE_COLOUR)
    size = ICON_SIZE
    canvas.image(brand_x - 14 - size, MAP_H + (BAND - size) // 2, size, _icon_data())
    return canvas.png()


def zone_radius_px(zone, scale: float) -> float:
    """Home's circle's radius on the picture: metres to world units at the circle's latitude
    (Mercator stretches a metre by 1 / cos(latitude))."""
    lat = zone[0][1]
    return zone[1] / (2 * math.pi * EARTH_RADIUS_M * math.cos(math.radians(lat))) * scale


# ---- The row's preview ----


def kept_png(row, zone) -> tuple[bool, bytes | None]:
    """(known, image) without drawing: whether the row's image for `zone` is settled (kept, kept
    as none, or none asked for), and the image when there is one."""
    if not row.preview_image:
        return True, None
    if row.preview_key == image_key(row, zone) and row.preview_png is not None:
        return True, bytes(row.preview_png) or None
    return False, None


def preview_png(row, zone) -> bytes | None:
    """The row's preview image for Home's circle `zone` (row_zone), drawn once and kept on the
    row; None when it has none (the sharer's Home unknown at an end, too little left to draw, or
    too long a stroke), which is kept too (an empty image), so it is not drawn again."""
    from .models import SharedRoute

    known, png = kept_png(row, zone)
    if known:
        return png
    key = image_key(row, zone)
    drawn = drawn_route(row.line, route_points(row), zone)
    png = render_png(drawn, stats_line(row)) if drawn is not None else None
    SharedRoute.objects.filter(pk=row.pk, revoked_at__isnull=True).update(
        preview_png=png or b"", preview_key=key
    )
    return png


# ---- Drawn when the link is made ----

# The first key of the drawing's advisory locks (core.ratelimit's are 0x524D....): a fetch's
# draw holds (_DRAW_LOCK, 0), so one runs at a time in the deployment, and every draw holds
# (_DRAW_LOCK + 1, the route's), so one route is never drawn twice at once. Both are held for
# a transaction, so they end with it however the draw ends.
_DRAW_LOCK = 0x53500000
# How long a fetch that found a draw running is told to wait.
DRAW_BUSY_RETRY_S = 5


def _route_lock(route_id: str) -> tuple[int, int]:
    value = int(route_id[:8], 16)
    return _DRAW_LOCK + 1, value - (1 << 32) if value >= 1 << 31 else value


def draw_later(row) -> None:
    """Queue the worker's draw of a link just made, once its row is saved. A link that asks for
    no image queues nothing; a queue that cannot be reached leaves the draw to the first fetch."""
    if not row.preview_image:
        return
    from django.db import transaction

    route_id = row.pk

    def defer() -> None:
        from config.procrastinate import draw_share_preview

        try:
            draw_share_preview.defer(route_id=route_id)
        except Exception:  # noqa: BLE001 - the link is made; its first fetch draws instead
            logger.warning("could not queue a link preview's drawing", exc_info=True)

    transaction.on_commit(defer)


def draw_now(route_id: str) -> None:
    """The worker's draw of one link's image (config.procrastinate.draw_share_preview): kept on
    the row, and nothing when the link is gone or its image already settled. Waits for a fetch
    drawing the same route, then finds its image kept."""
    from django.db import connection, transaction

    if not shared_routes.id_ok(route_id):
        return
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", list(_route_lock(route_id)))
        row, _status = _live_row(route_id)
        if row is not None:
            preview_png(row, row_zone(row))


_BUSY = object()


def _draw_for_fetch(route_id: str):
    """A fetch's draw of an image not kept yet: the image, None for none, or _BUSY when another
    draw is running (any route's from a fetch, or this route's from the worker)."""
    from django.db import connection, transaction

    with transaction.atomic():
        with connection.cursor() as cursor:
            for pair in ((_DRAW_LOCK, 0), _route_lock(route_id)):
                cursor.execute("SELECT pg_try_advisory_xact_lock(%s, %s)", list(pair))
                if not cursor.fetchone()[0]:
                    return _BUSY
        # Read again under the locks: the worker may have kept it meanwhile.
        row, _status = _live_row(route_id)
        return preview_png(row, row_zone(row)) if row is not None else None


# ---- Views ----


def is_fetcher(request) -> bool:
    """A link fetcher rather than a browser: its User-Agent names one, and it is no navigation a
    browser says it is making."""
    if request.META.get("HTTP_SEC_FETCH_MODE", "").lower() == "navigate":
        return False
    return bool(FETCHER_RE.search(request.META.get("HTTP_USER_AGENT", "")))


def _live_row(route_id: str):
    """(row, status): the kept row and 200, or None and 404 (never kept, or expired) or 410
    (turned off by its owner)."""
    from .models import SharedRoute

    if not shared_routes.id_ok(route_id):
        return None, 404
    row = SharedRoute.objects.filter(pk=route_id).first()
    if row is None or shared_routes.expired(row, timezone.now()):
        return None, 404
    if row.revoked_at is not None:
        return None, 410
    return row, 200


def _plain(status: int, words: str) -> HttpResponse:
    body = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{BRAND}</title></head><body><p>{escape(words)}</p></body></html>"
    )
    response = HttpResponse(body, status=status, content_type="text/html; charset=utf-8")
    response["Cache-Control"] = "no-store"
    response["X-Robots-Tag"] = "noindex"
    return response


@require_safe
@ratelimit.rate_limited(ratelimit.SHARE_PREVIEWS)
def share_page(request, route_id: str):
    """GET /s/<id>: a browser goes on to the page; a link fetcher gets the preview's tags."""
    if not is_fetcher(request):
        if not shared_routes.id_ok(route_id):
            response = HttpResponseRedirect("/")
        else:
            response = HttpResponseRedirect(f"/?{PARAM}={route_id}")
        response["Cache-Control"] = "no-store"
        patch_vary_headers(response, VARY)
        return response
    row, status = _live_row(route_id)
    if status == 410:
        return _varied(_plain(410, shared_routes.REVOKED))
    if row is None:
        return _varied(_plain(404, "That shared route is no longer kept."))
    page_url = request.build_absolute_uri(f"/s/{row.pk}")
    head = [
        ("og:type", "website"),
        ("og:site_name", BRAND),
        ("og:title", title(row)),
        ("og:description", description(row)),
        ("og:url", page_url),
    ]
    zone = row_zone(row)
    # Named without drawing: kept, or not tried yet (the fetch of the image draws it then).
    known, png = kept_png(row, zone)
    image = png is not None if known else True
    if image:
        image_url = request.build_absolute_uri(
            f"/s/{row.pk}/preview.png?v={image_key(row, zone)[:16]}"
        )
        head += [
            ("og:image", image_url),
            ("og:image:type", "image/png"),
            ("og:image:width", str(WIDTH)),
            ("og:image:height", str(HEIGHT)),
            ("og:image:alt", f"Route line, {stats_line(row)}. {BRAND}."),
        ]
    names = [
        ("twitter:card", "summary_large_image" if image else "summary"),
        ("twitter:title", title(row)),
        ("twitter:description", description(row)),
    ]
    if image:
        names.append(("twitter:image", image_url))
    return _varied(_tags_page(title(row), description(row), head, names))


def _tags_page(page_title: str, words: str, head, names) -> HttpResponse:
    """A page of the preview's tags, the app's icons and nothing else, never cached."""
    tags = "".join(f'<meta property="{k}" content="{escape(v)}">' for k, v in head) + "".join(
        f'<meta name="{k}" content="{escape(v)}">' for k, v in names
    )
    body = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{escape(page_title)}</title>"
        f'<meta name="description" content="{escape(words)}">'
        '<meta name="robots" content="noindex">'
        f"{tags}{ICON_LINKS}</head><body><p>{escape(words)}</p></body></html>"
    )
    response = HttpResponse(body, content_type="text/html; charset=utf-8")
    response["Cache-Control"] = "no-store"
    response["X-Robots-Tag"] = "noindex"
    return response


# The app's icons, as frontend/index.html links them: a chat app that shows a site's icon beside
# its preview takes one of these.
ICON_LINKS = (
    '<link rel="icon" href="/favicon.svg" type="image/svg+xml">'
    '<link rel="icon" href="/favicon.ico" sizes="16x16 32x32 48x48">'
    '<link rel="icon" href="/icons/icon-192.png" type="image/png" sizes="192x192">'
    '<link rel="apple-touch-icon" href="/icons/apple-touch-icon.png">'
)
# The app's own preview (frontend/index.html's description, and the card scripts/
# make_share_images.py draws).
SITE_DESCRIPTION = (
    "Bike route planning tool around Washington, DC and Baltimore. No sign-in needed."
)
SITE_CARD = "/icons/share-card.png"
SITE_CARD_ALT = (
    "The RouteMaker icon, a bicycle with a map pin in its front wheel. "
    "Bike route planning tool around Washington, DC and Baltimore."
)


@require_safe
@ratelimit.rate_limited(ratelimit.SHARE_PREVIEWS)
def site_page(request):
    """GET /link-preview: the app's own address as a link fetcher sees it (the edge hands it a
    fetcher's GET /); a browser is sent to the app."""
    if not is_fetcher(request):
        response = HttpResponseRedirect("/")
        response["Cache-Control"] = "no-store"
        return _varied(response)
    image_url = request.build_absolute_uri(SITE_CARD)
    head = [
        ("og:type", "website"),
        ("og:site_name", BRAND),
        ("og:title", BRAND),
        ("og:description", SITE_DESCRIPTION),
        ("og:url", request.build_absolute_uri("/")),
        ("og:image", image_url),
        ("og:image:type", "image/png"),
        ("og:image:width", str(WIDTH)),
        ("og:image:height", str(HEIGHT)),
        ("og:image:alt", SITE_CARD_ALT),
    ]
    names = [
        ("twitter:card", "summary_large_image"),
        ("twitter:title", BRAND),
        ("twitter:description", SITE_DESCRIPTION),
        ("twitter:image", image_url),
    ]
    return _varied(_tags_page(BRAND, SITE_DESCRIPTION, head, names))


# The page answers a browser and a fetcher differently: a cache keys on what tells them apart.
VARY = ("User-Agent", "Sec-Fetch-Mode")


def _varied(response: HttpResponse) -> HttpResponse:
    patch_vary_headers(response, VARY)
    return response


@require_safe
@ratelimit.rate_limited(ratelimit.SHARE_PREVIEWS)
def share_image(request, route_id: str):
    """GET /s/<id>/preview.png: the preview image, or 404 / 410 with none, or 503 while another
    draw runs."""
    row, status = _live_row(route_id)
    png = None
    if row is not None:
        known, png = kept_png(row, row_zone(row))
        if not known:
            png = _draw_for_fetch(row.pk)
            if png is _BUSY:
                response = HttpResponse(status=503)
                response["Retry-After"] = str(DRAW_BUSY_RETRY_S)
                response["Cache-Control"] = "no-store"
                return response
    if png is None:
        response = HttpResponse(status=410 if status == 410 else 404)
        response["Cache-Control"] = "no-store"
        return response
    response = HttpResponse(png, content_type="image/png")
    # An hour, public: a link turned off can show its old image in a chat app for up to an hour.
    response["Cache-Control"] = "public, max-age=3600"
    response["X-Robots-Tag"] = "noindex"
    return response
