"""The base map behind the link preview's route (core.share_preview; the owner, 2026-10-25: "Is it
possible to add the base map to the route preview?").

The preview is drawn with the standard library only, so this reads the app's own base map, the
Protomaps archive scripts/fetch_basemap.sh puts at `settings.BASEMAP_PMTILES` (the file the map in
the app shows, never a tile server's), and draws a plain version of it: land, parks and woods,
water, roads and paths, rail, and a few town names. The archive is PMTiles v3 (its directories
gzipped) holding Mapbox Vector Tiles (protobuf, gzipped); both are read here, the protobuf by a
small decoder of the few fields a tile uses.

The view is Web Mercator, as the tiles are: a point's place on the picture is its world position
(0 to 1 across the world, `world_xy`) times the picture's scale, about the view's centre. The
tiles drawn are of the zoom whose 512 px tile is nearest the picture's scale, no deeper than the
archive goes, and at most `MAX_TILES` of them. No archive, a broken one, or one that has none of
the view, and the picture is drawn as before, on the plain background.

The credits the base map owes (docs/OPERATIONS.md, "Licences, and the credits every map must
carry": OpenStreetMap's and Protomaps') are drawn on the picture by share_preview (`CREDIT`).
"""

from __future__ import annotations

import gzip
import math
import os
import struct
import zlib
from functools import lru_cache

from django.conf import settings

# What the picture owes the base map, drawn on it (stressStyle.js BASEMAP.attribution).
CREDIT = "© OpenStreetMap contributors · © Protomaps"
TILE_PX = 512
MAX_TILES = 16
# The archive's tiles and directories are at most this big; past it, the archive is taken as broken.
MAX_READ = 8 << 20

# The colours: namedFlavor("light") of @protomaps/basemaps, as the app's map, with roads a little
# stronger so they show at a chat app's thumbnail size.
EARTH = (226, 223, 218)
WATER = (128, 222, 234)
PARK = (156, 211, 180)
WOOD = (160, 217, 160)
GREEN_SOFT = (207, 221, 213)
ROAD = (255, 255, 255)
ROAD_CASING = (200, 196, 188)
PATH = (247, 245, 240)
RAIL = (167, 177, 179)

PARK_KINDS = {
    "park",
    "nature_reserve",
    "national_park",
    "protected_area",
    "garden",
    "playground",
    "golf_course",
    "recreation_ground",
    "pitch",
    "dog_park",
    "cemetery",
    "grass",
}
WOOD_KINDS = {"forest", "wood"}
# Roads by kind, biggest last, as the app's map thins them out of view: (the least zoom shown, and
# the stroke's half width in pixels from each zoom up). Paths are the trails, shown close in only.
ROADS = (
    ("path", 13.0, ((13.0, 0.9),)),
    ("minor_road", 12.5, ((12.5, 0.7), (14.0, 1.1))),
    ("medium_road", 12.0, ((12.0, 0.9), (13.0, 1.8))),
    ("major_road", 9.0, ((9.0, 0.6), (10.0, 0.8), (11.0, 1.4), (13.0, 2.4))),
    ("highway", 0.0, ((0.0, 1.0), (10.0, 1.6), (12.0, 3.0))),
)
CASED = {"major_road", "highway"}
RAIL_FROM = 11.0
STREAMS_FROM = 12.0
# Town names: the kinds shown, and at most this many.
PLACE_KINDS = {"locality"}
MAX_PLACES = 6


# ---- Mercator ----


def world_xy(lon: float, lat: float) -> tuple[float, float]:
    """A point's Web Mercator place, 0 to 1 west to east and north to south."""
    lat = max(-85.05112878, min(85.05112878, lat))
    s = math.sin(math.radians(lat))
    return (lon + 180.0) / 360.0, 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)


# ---- PMTiles ----


def _uvarint(buf, i: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        b = buf[i]
        i += 1
        value |= (b & 0x7F) << shift
        if b < 0x80:
            return value, i
        shift += 7
        if shift > 63:
            raise ValueError("varint too long")


def tile_id(z: int, x: int, y: int) -> int:
    """The tile's id in the archive: the tiles of lower zooms, then its place on the Hilbert
    curve over its zoom (the PMTiles v3 specification)."""
    acc = ((1 << (2 * z)) - 1) // 3
    d = 0
    s = (1 << z) >> 1
    while s > 0:
        rx = 1 if x & s else 0
        ry = 1 if y & s else 0
        d += s * s * ((3 * rx) ^ ry)
        if ry == 0:
            if rx == 1:
                x, y = s - 1 - x, s - 1 - y
            x, y = y, x
        s >>= 1
    return acc + d


def _directory(raw: bytes) -> list[tuple[int, int, int, int]]:
    """A directory's entries: (tile id, run length, offset, length)."""
    n, i = _uvarint(raw, 0)
    ids, runs, lengths, offsets = [], [], [], []
    last = 0
    for _ in range(n):
        v, i = _uvarint(raw, i)
        last += v
        ids.append(last)
    for _ in range(n):
        v, i = _uvarint(raw, i)
        runs.append(v)
    for _ in range(n):
        v, i = _uvarint(raw, i)
        lengths.append(v)
    for k in range(n):
        v, i = _uvarint(raw, i)
        offsets.append(offsets[k - 1] + lengths[k - 1] if v == 0 and k > 0 else v - 1)
    return list(zip(ids, runs, offsets, lengths, strict=True))


def _unpack(raw: bytes, compression: int) -> bytes:
    if compression in (0, 1):
        return raw
    if compression == 2:
        return gzip.decompress(raw)
    raise ValueError("compression not read")


class Archive:
    """One PMTiles v3 archive on disk, read a tile at a time."""

    def __init__(self, path) -> None:
        self.path = path
        with open(path, "rb") as f:
            head = f.read(127)
        if len(head) < 127 or head[:7] != b"PMTiles" or head[7] != 3:
            raise ValueError("not a PMTiles v3 archive")
        (
            self.root_offset,
            self.root_length,
            _meta_offset,
            _meta_length,
            self.leaf_offset,
            _leaf_length,
            self.data_offset,
        ) = struct.unpack_from("<7Q", head, 8)
        self.internal, self.tile_compression, self.tile_type = head[97], head[98], head[99]
        self.min_zoom, self.max_zoom = head[100], head[101]
        if self.tile_type != 1:
            raise ValueError("not vector tiles")
        self._dirs: dict[tuple[int, int], list] = {}

    def _read(self, f, offset: int, length: int) -> bytes:
        if length > MAX_READ:
            raise ValueError("too big")
        f.seek(offset)
        raw = f.read(length)
        if len(raw) != length:
            raise ValueError("archive cut short")
        return raw

    def _dir(self, f, offset: int, length: int) -> list:
        key = (offset, length)
        if key not in self._dirs:
            self._dirs[key] = _directory(_unpack(self._read(f, offset, length), self.internal))
        return self._dirs[key]

    def tile(self, z: int, x: int, y: int) -> bytes | None:
        """The tile's protobuf, unzipped; None when the archive has none there."""
        target = tile_id(z, x, y)
        with open(self.path, "rb") as f:
            offset, length = self.root_offset, self.root_length
            for _depth in range(4):
                entries = self._dir(f, offset, length)
                lo, hi = 0, len(entries) - 1
                found = None
                while lo <= hi:
                    mid = (lo + hi) // 2
                    if entries[mid][0] <= target:
                        found = entries[mid]
                        lo = mid + 1
                    else:
                        hi = mid - 1
                if found is None:
                    return None
                tid, run, off, ln = found
                if run == 0:
                    offset, length = self.leaf_offset + off, ln
                    continue
                if target >= tid + run:
                    return None
                return _unpack(self._read(f, self.data_offset + off, ln), self.tile_compression)
        return None


@lru_cache(maxsize=2)
def _archive(path: str, stamp: tuple) -> Archive | None:
    try:
        return Archive(path)
    except (OSError, ValueError, IndexError, struct.error):
        return None


def stamp() -> str:
    """What the archive is now (its size and time), for the preview's cache key: a new base map
    draws the pictures again. Empty when there is none."""
    path = getattr(settings, "BASEMAP_PMTILES", None)
    try:
        st = os.stat(path) if path else None
    except OSError:
        st = None
    return f"{st.st_size}:{st.st_mtime_ns}" if st else ""


def archive() -> Archive | None:
    path = getattr(settings, "BASEMAP_PMTILES", None)
    s = stamp()
    return _archive(str(path), (s,)) if s else None


# ---- Vector tiles ----


def _fields(buf):
    """A protobuf message's fields: (number, value), the value an int or a memoryview."""
    i, n = 0, len(buf)
    while i < n:
        key, i = _uvarint(buf, i)
        field, wire = key >> 3, key & 7
        if wire == 0:
            value, i = _uvarint(buf, i)
        elif wire == 2:
            length, i = _uvarint(buf, i)
            value = buf[i : i + length]
            i += length
        elif wire == 1:
            value = bytes(buf[i : i + 8])
            i += 8
        elif wire == 5:
            value = bytes(buf[i : i + 4])
            i += 4
        else:
            raise ValueError("wire type not read")
        yield field, value


def _packed(buf) -> list[int]:
    out, i = [], 0
    while i < len(buf):
        v, i = _uvarint(buf, i)
        out.append(v)
    return out


def _value(buf):
    for field, v in _fields(buf):
        if field == 1:
            return bytes(v).decode("utf-8", "replace")
        if field == 2:
            return struct.unpack("<f", v)[0]
        if field == 3:
            return struct.unpack("<d", v)[0]
        if field in (4, 5):
            return v
        if field == 6:
            return (v >> 1) ^ -(v & 1)
        if field == 7:
            return bool(v)
    return None


def _geometry(commands: list[int]) -> list[list[tuple[int, int]]]:
    """The feature's parts in tile units: each ring or line a list of points."""
    parts: list[list[tuple[int, int]]] = []
    x = y = 0
    i, n = 0, len(commands)
    part: list[tuple[int, int]] | None = None
    while i < n:
        cmd, count = commands[i] & 7, commands[i] >> 3
        i += 1
        if cmd == 7:
            if part:
                part.append(part[0])
            continue
        for _ in range(count):
            if i + 1 >= n:
                break
            dx, dy = commands[i], commands[i + 1]
            i += 2
            x += (dx >> 1) ^ -(dx & 1)
            y += (dy >> 1) ^ -(dy & 1)
            if cmd == 1:
                part = [(x, y)]
                parts.append(part)
            elif part is not None:
                part.append((x, y))
    return parts


WANTED = {"water", "landuse", "landcover", "roads", "places"}


def layers(tile: bytes) -> dict[str, list[tuple[int, dict, list]]]:
    """The tile's wanted layers: name to (geometry type, properties, parts), the parts scaled to
    0 to 1 across the tile."""
    out: dict[str, list] = {}
    for field, layer in _fields(memoryview(tile)):
        if field != 3:
            continue
        name, extent, keys, values, features = None, 4096, [], [], []
        for f, v in _fields(layer):
            if f == 1:
                name = bytes(v).decode()
            elif f == 2:
                features.append(v)
            elif f == 3:
                keys.append(bytes(v).decode())
            elif f == 4:
                values.append(v)
            elif f == 5:
                extent = v
        if name not in WANTED:
            continue
        decoded = [_value(v) for v in values]
        rows = []
        for feature in features:
            kind, tags, geom = 0, [], []
            for f, v in _fields(feature):
                if f == 2:
                    tags = _packed(v)
                elif f == 3:
                    kind = v
                elif f == 4:
                    geom = _packed(v)
            props = {
                keys[tags[k]]: decoded[tags[k + 1]]
                for k in range(0, len(tags) - 1, 2)
                if tags[k] < len(keys) and tags[k + 1] < len(decoded)
            }
            parts = [[(px / extent, py / extent) for px, py in part] for part in _geometry(geom)]
            rows.append((kind, props, parts))
        out[name] = rows
    return out


# ---- Drawing ----


def _fill(
    px: bytearray, width: int, height: int, rings: list[list[tuple[float, float]]], colour
) -> None:
    """The rings filled, even-odd (so holes stay open), a pixel taken when its centre is in."""
    rows: dict[int, list[float]] = {}
    for ring in rings:
        for (ax, ay), (bx, by) in zip(ring, ring[1:], strict=False):
            if ay == by:
                continue
            if ay > by:
                ax, ay, bx, by = bx, by, ax, ay
            y0 = max(0, math.ceil(ay - 0.5))
            y1 = min(height - 1, math.ceil(by - 0.5) - 1)
            slope = (bx - ax) / (by - ay)
            for y in range(y0, y1 + 1):
                rows.setdefault(y, []).append(ax + (y + 0.5 - ay) * slope)
    paint = bytes(colour)
    for y, xs in rows.items():
        xs.sort()
        base = y * width
        for k in range(0, len(xs) - 1, 2):
            x0 = max(0, math.ceil(xs[k] - 0.5))
            x1 = min(width, math.ceil(xs[k + 1] - 0.5))
            if x1 > x0:
                px[(base + x0) * 3 : (base + x1) * 3] = paint * (x1 - x0)


def _run(
    px: bytearray,
    width: int,
    k: int,
    rows: bool,
    lo: float,
    hi: float,
    run: int,
    paint: bytes,
    colour,
) -> None:
    """One step of a stroke: the pixels from `lo` to `hi` across step `k` (a row when `rows`,
    else a column), each covered by how far it is inside the run's ends, which smooths the
    stroke's edges without measuring every pixel's distance to it."""
    for j in range(max(0, int(lo - 0.5)), min(run - 1, int(hi + 0.5)) + 1):
        c = min(j + 0.5 - lo, hi - j - 0.5) + 0.5
        if c <= 0.05:
            continue
        i = ((k * width + j) if rows else (j * width + k)) * 3
        if c >= 0.95:
            px[i : i + 3] = paint
        else:
            for m in range(3):
                px[i + m] = int(px[i + m] + (colour[m] - px[i + m]) * c + 0.5)


def _stroke(px: bytearray, width: int, height: int, lines, radius: float, colour) -> None:
    """The lines drawn as strokes of half width `radius` with round joins and ends. Each segment
    is the band of that width along it, taken a row at a time when it runs more up than across,
    else a column at a time; each point of the line is a disc, which rounds the joins."""
    paint = bytes(colour)
    reach = radius + 1
    for line in lines:
        for (ax, ay), (bx, by) in zip(line, line[1:], strict=False):
            if max(ax, bx) < -reach or min(ax, bx) > width + reach:
                continue
            if max(ay, by) < -reach or min(ay, by) > height + reach:
                continue
            dx, dy = bx - ax, by - ay
            rows = abs(dy) >= abs(dx)
            # Along: the axis stepped through; across: the run within each step.
            if rows:
                a0, a1, b0, b1, steps, run = ax, ay, bx, by, height, width
            else:
                a0, a1, b0, b1, steps, run = ay, ax, by, bx, width, height
            if a1 == b1:
                continue
            slope = (b0 - a0) / (b1 - a1)
            half = radius * math.hypot(dx, dy) / abs(b1 - a1)
            for k in range(
                max(0, math.ceil(min(a1, b1) - 0.5)),
                min(steps - 1, math.floor(max(a1, b1) - 0.5)) + 1,
            ):
                mid = a0 + (k + 0.5 - a1) * slope
                _run(px, width, k, rows, mid - half, mid + half, run, paint, colour)
        for cx, cy in line:
            if not (-reach <= cx <= width + reach and -reach <= cy <= height + reach):
                continue
            for k in range(max(0, int(cy - radius)), min(height - 1, int(cy + radius)) + 1):
                h = radius * radius - (k + 0.5 - cy) ** 2
                if h > 0:
                    w = math.sqrt(h)
                    _run(px, width, k, True, cx - w, cx + w, width, paint, colour)


def _thin(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """The points less than a pixel from the last one kept dropped, the ends kept: a tile drawn
    smaller than its own detail has many."""
    if len(points) < 3:
        return points
    out = [points[0]]
    lx, ly = points[0]
    for x, y in points[1:-1]:
        if abs(x - lx) + abs(y - ly) >= 1.0:
            out.append((x, y))
            lx, ly = x, y
    out.append(points[-1])
    return out


def view_zoom(scale: float, max_zoom: int, min_zoom: int = 0) -> int:
    """The tiles' zoom for a picture of `scale` pixels across the world: the one whose tile is
    nearest TILE_PX on the picture."""
    z = round(math.log2(max(scale, 1.0) / TILE_PX))
    return max(min_zoom, min(max_zoom, z))


def paint(
    px: bytearray, width: int, height: int, centre: tuple[float, float], scale: float
) -> list | None:
    """The base map drawn into `px` (RGB rows of `width`, the first `height` rows drawn), the
    view centred on `centre` (world_xy) at `scale` pixels across the world. Returns the town names
    to draw over the route, as (x, y, name), or None when there was no base map to draw (and `px`
    is untouched)."""
    arc = archive()
    if arc is None:
        return None
    z = view_zoom(scale, arc.max_zoom, arc.min_zoom)
    n = 1 << z
    cx, cy = centre
    left, top = cx - width / 2 / scale, cy - height / 2 / scale
    right, bottom = cx + width / 2 / scale, cy + height / 2 / scale
    tx0, tx1 = max(0, int(left * n)), min(n - 1, int(right * n))
    ty0, ty1 = max(0, int(top * n)), min(n - 1, int(bottom * n))
    if (tx1 - tx0 + 1) * (ty1 - ty0 + 1) > MAX_TILES:
        return None
    tiles = []
    try:
        for ty in range(ty0, ty1 + 1):
            for tx in range(tx0, tx1 + 1):
                raw = arc.tile(z, tx, ty)
                if raw:
                    tiles.append((tx, ty, layers(raw)))
    except (
        OSError,
        ValueError,
        IndexError,
        KeyError,
        struct.error,
        EOFError,
        zlib.error,
        UnicodeDecodeError,
    ):
        return None
    if not tiles:
        return None

    # The view's own zoom, a fraction, as the app's map styles roads by it.
    zoom = math.log2(max(scale, 1.0) / TILE_PX)
    shown = {
        kind: [w for z, w in widths if zoom >= z][-1]
        for kind, least, widths in ROADS
        if zoom >= least
    }

    def drawn(name: str, kind: int, props: dict) -> bool:
        k = props.get("kind")
        if name == "water":
            # Streams and ditches only close in: from afar they are a web of blue hairs.
            return kind == 3 or (kind == 2 and (k == "river" or zoom >= STREAMS_FROM))
        if name == "landcover":
            return kind == 3 and k in {"forest", "grassland", "scrub"}
        if name == "landuse":
            return kind == 3 and (k in WOOD_KINDS or k in PARK_KINDS)
        if name == "roads":
            return kind == 2 and (k in shown or (k == "rail" and zoom >= RAIL_FROM))
        return name == "places" and kind == 1 and k in PLACE_KINDS

    # Each feature drawn, placed on the picture; the rest are never placed.
    by_layer: dict[str, list] = {}
    for tx, ty, found in tiles:
        for name, rows in found.items():
            mine = by_layer.setdefault(name, [])
            for kind, props, parts in rows:
                if drawn(name, kind, props):
                    placed = [
                        _thin(
                            [
                                (((tx + u) / n - left) * scale, ((ty + v) / n - top) * scale)
                                for u, v in part
                            ]
                        )
                        for part in parts
                    ]
                    mine.append((kind, props, placed))

    def polygons(name):
        return [(props, parts) for kind, props, parts in by_layer.get(name, []) if kind == 3]

    # Land everywhere, then the softer green of land cover, parks and woods, and water over them.
    _fill(px, width, height, [[(0, 0), (width, 0), (width, height), (0, height), (0, 0)]], EARTH)
    for _props, parts in polygons("landcover"):
        _fill(px, width, height, parts, GREEN_SOFT)
    for props, parts in polygons("landuse"):
        _fill(px, width, height, parts, WOOD if props.get("kind") in WOOD_KINDS else PARK)
    for _props, parts in polygons("water"):
        _fill(px, width, height, parts, WATER)
    for kind, props, parts in by_layer.get("water", []):
        if kind == 2:
            _stroke(px, width, height, parts, 1.0 if props.get("kind") == "river" else 0.6, WATER)

    lines = by_layer.get("roads", [])
    for _kind, props, parts in lines:
        if props.get("kind") == "rail" and props.get("kind_detail") not in {"subway", "tram"}:
            _stroke(px, width, height, parts, 0.8, RAIL)
    for kind, _least, _widths in ROADS:
        if kind not in shown:
            continue
        half = shown[kind]
        mine = [parts for _k, props, parts in lines if props.get("kind") == kind]
        if kind in CASED:
            for parts in mine:
                _stroke(px, width, height, parts, half + 1.0, ROAD_CASING)
        for parts in mine:
            _stroke(px, width, height, parts, half, PATH if kind == "path" else ROAD)

    places = []
    for _kind, props, parts in by_layer.get("places", []):
        name = props.get("name:en") or props.get("name")
        if not isinstance(name, str):
            continue
        for part in parts:
            for x, y in part:
                if 0 <= x < width and 0 <= y < height:
                    rank = props.get("population_rank")
                    places.append((-(rank if isinstance(rank, int | float) else 0), x, y, name))
    places.sort()
    seen = set()
    picked = []
    for _rank, x, y, name in places:
        if name in seen:
            continue
        seen.add(name)
        picked.append((x, y, name))
        if len(picked) >= MAX_PLACES:
            break
    return picked
