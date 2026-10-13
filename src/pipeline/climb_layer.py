"""The Climbs map layer's file: every categorised climb on the network, found once at build time.

OWNER-DECISIONS 454 ("Three map layers for everyone ... topo lines, climbs, mountain-bike
trails") and the owner's climb scale (`routemaker.climb_categories`; docs/MTB-TOPO-PLAN.md,
slice 5). Run on the build host after a rebuild has promoted the live table, by
`manage.py build_climbs` (docs/OPERATIONS.md, "The Climbs layer"); the file it writes is
committed as frontend/src/climb-data/climbs.json, as the water and restrooms file is.

What it reads:

- **The network**: the live segment table's ways the map draws as routable (`map_class` =
  `road`), less the mountain-bike-only ways (closed for every ride type today; 291) and the
  walk-your-bike connectors. Access is the rebuild's, overrides and all, so a way a bicycle
  may not use (barred, hidden, err closed) never carries a climb. And only a way the
  segment panel calls open (`segment.bike_access_reason` empty or an open reason in
  `core.segment_info.ACCESS_WORDS`): a way with a closing reason, or one this release
  does not know, is left out (unclear access is closed, OWNER-DECISIONS 330). A way inside
  a quarry, a landfill or an industrial area closes at the rebuild
  (`pipeline.restricted_areas.works_closures`, owner report 2026-10-12); until a rebuild
  carries that, a climb found on one is listed by hand (`routemaker.climb_exclusions`)
  and never written.
- **The ground**: the same 3DEP one-arcsecond HGT tiles the routers read
  (`<DATA_ROOT>/elevation/N38/N38W077.hgt`; `pipeline.elevation`), bilinear between posts.

How:

1. **Strokes.** A climb runs through junctions, so the segments are joined into strokes: at
   every node each way end is paired with the end that continues it most nearly straight,
   the closest pairs first, and only within `MAX_DEFLECTION_DEG` (the "good continuity"
   rule of Thomson and Richardson, "The 'good continuation' principle of perceptual
   organization applied to the generalization of road networks", ICA 1999). A stroke is a
   road as a rider follows it, across its cross streets.
2. **Profiles.** Each stroke is sampled every `SAMPLE_STEP_M` (30 m, the DEM's post spacing,
   as the owner's 2026-10-10 scan did) and read both ways.
3. **Climbs.** `routemaker.climb_categories.find_in_piece` on each profile: net gain with
   short dips and flats as breaks, at least 500 m at 1% and a Cat 5 score.
4. **One-way.** A climb that rides any one-way segment against its drawn direction is left
   out. The table's `road_oneway` has no direction, so a way drawn against its traffic
   (OSM `oneway=-1`, rare) is read as one-way along its geometry, and contraflow bike lanes
   are not read: both can only drop a climb, never draw one a rider may not ride.

The file, one climb per entry, short keys (frontend/src/lib/climbs.ts reads it):

    id   stable id from the start and summit (10 hex digits)
    c    category: "5", "4", "3", "2", "1" or "HC"
    l    length, m (whole)
    r    net gain, m (whole)
    g    average grade, % to a tenth
    x, y the summit, longitude and latitude (5 decimals, about 3 ft (1 m))
    line the climb's line from its start to the summit, simplified to SIMPLIFY_M
    u    1 when most of it is unpaved (left out otherwise)
    n    the long trail's name, when one carries most of it (`segment.trail_name`)
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from array import array
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from routemaker import climb_categories, climb_exclusions
from routemaker.climb_categories import Climb

from .elevation import HGT_1ARCSEC_SIDE, TileName, tile_for

FORMAT_VERSION = 1
SAMPLE_STEP_M = 30.0
# Ends meeting at an angle sharper than this are not one road: a right-angle turn at a
# junction ends the stroke. 45 degrees keeps a road through a bend or a skewed crossing.
MAX_DEFLECTION_DEG = 45.0
# The bearing at a way's end is read this far in, so a last short kink does not set it.
BEARING_REACH_M = 20.0
# The line is simplified to this (Douglas-Peucker), well under a lane's width at the zooms
# the layer draws lines (12 and in).
SIMPLIFY_M = 5.0
COORD_DECIMALS = 5
VOID = -32768
M_PER_DEG_LAT = 111_320.0


# --- The ground -------------------------------------------------------------------


class HgtElevation:
    """Bilinear elevation from one-arcsecond HGT tiles in skadi's layout, loaded on first use.

    A tile that is missing, the wrong size or a void post reads as None (no elevation),
    which splits the profile there rather than inventing ground.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self._tiles: dict[TileName, array | None] = {}

    def _tile(self, name: TileName) -> array | None:
        if name not in self._tiles:
            path = self.root / name.path()
            data: array | None = None
            try:
                raw = path.read_bytes()
            except OSError:
                raw = b""
            if len(raw) == HGT_1ARCSEC_SIDE * HGT_1ARCSEC_SIDE * 2:
                data = array("h")
                data.frombytes(raw)
                if data.itemsize != 2:
                    raise RuntimeError("array('h') is not 16-bit on this platform")
                # HGT is big-endian.
                if sys.byteorder == "little":
                    data.byteswap()
            self._tiles[name] = data
        return self._tiles[name]

    @property
    def tiles_read(self) -> int:
        """How many tiles have been read with ground in them (0: the directory gave nothing)."""
        return sum(1 for data in self._tiles.values() if data is not None)

    @property
    def tiles_missing(self) -> list[str]:
        """The tiles asked for that were missing or the wrong size, by name."""
        return sorted(name.stem for name, data in self._tiles.items() if data is None)

    def at(self, lon: float, lat: float) -> float | None:
        name = tile_for(lon, lat)
        data = self._tile(name)
        if data is None:
            return None
        n = HGT_1ARCSEC_SIDE - 1
        # Row 0 is the north edge; posts sit on whole arc-seconds.
        fx = (lon - name.lon) * n
        fy = (name.lat + 1 - lat) * n
        x0 = min(int(math.floor(fx)), n - 1)
        y0 = min(int(math.floor(fy)), n - 1)
        tx = fx - x0
        ty = fy - y0
        side = HGT_1ARCSEC_SIDE
        corners = (
            data[y0 * side + x0],
            data[y0 * side + x0 + 1],
            data[(y0 + 1) * side + x0],
            data[(y0 + 1) * side + x0 + 1],
        )
        if VOID in corners:
            return None
        a, b, c, d = corners
        top = a + (b - a) * tx
        bottom = c + (d - c) * tx
        return top + (bottom - top) * ty


# --- The network ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SegmentLine:
    """One segment of the network, as drawn: its line in the way's own direction."""

    key: tuple[int, int]
    coords: tuple[tuple[float, float], ...]
    oneway: bool = False
    unpaved: bool | None = None
    trail_name: str | None = None


@dataclass(slots=True)
class Stroke:
    """Segments joined end to end: each part a segment index and whether it is walked along
    its own direction, and the stroke's vertices with the part each edge belongs to."""

    parts: list[tuple[int, bool]] = field(default_factory=list)
    coords: list[tuple[float, float]] = field(default_factory=list)
    # edge_part[i] is the index into `parts` of the edge coords[i] -> coords[i + 1].
    edge_part: list[int] = field(default_factory=list)


def _metres(a: tuple[float, float], b: tuple[float, float]) -> float:
    kx = M_PER_DEG_LAT * math.cos(math.radians((a[1] + b[1]) / 2))
    return math.hypot((b[0] - a[0]) * kx, (b[1] - a[1]) * M_PER_DEG_LAT)


def _bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    kx = math.cos(math.radians((a[1] + b[1]) / 2))
    return math.degrees(math.atan2((b[0] - a[0]) * kx, b[1] - a[1])) % 360.0


def _outward(coords: Sequence[tuple[float, float]]) -> float:
    """The bearing leaving coords[0] along the line, read BEARING_REACH_M in."""
    travelled = 0.0
    for i in range(1, len(coords)):
        travelled += _metres(coords[i - 1], coords[i])
        if travelled >= BEARING_REACH_M:
            return _bearing(coords[0], coords[i])
    return _bearing(coords[0], coords[-1])


def _node(point: tuple[float, float]) -> tuple[int, int]:
    return (round(point[0] * 1e7), round(point[1] * 1e7))


def _deflection(out_a: float, out_b: float) -> float:
    """How far from straight on two way ends meeting at a node are, in degrees (0 straight)."""
    between = abs(out_a - out_b) % 360.0
    between = min(between, 360.0 - between)
    return 180.0 - between


def strokes(segments: Sequence[SegmentLine]) -> list[Stroke]:
    """Join the segments into strokes by good continuity; every segment is in exactly one."""
    # An end is (segment index, 0 for its start or 1 for its end).
    at_node: dict[tuple[int, int], list[tuple[int, int, float]]] = defaultdict(list)
    for index, segment in enumerate(segments):
        if len(segment.coords) < 2:
            continue
        at_node[_node(segment.coords[0])].append((index, 0, _outward(segment.coords)))
        at_node[_node(segment.coords[-1])].append((index, 1, _outward(segment.coords[::-1])))
    partner: dict[tuple[int, int], tuple[int, int]] = {}
    for ends in at_node.values():
        if len(ends) < 2:
            continue
        pairs = []
        for i in range(len(ends)):
            for j in range(i + 1, len(ends)):
                if ends[i][0] == ends[j][0]:
                    continue  # a ring's own two ends
                deflection = _deflection(ends[i][2], ends[j][2])
                if deflection <= MAX_DEFLECTION_DEG:
                    pairs.append((deflection, i, j))
        for _, i, j in sorted(pairs):
            a = ends[i][:2]
            b = ends[j][:2]
            if a in partner or b in partner:
                continue
            partner[a] = b
            partner[b] = a

    seen: set[int] = set()
    out: list[Stroke] = []

    def walk(first: int, entry: int) -> Stroke:
        stroke = Stroke()
        index, side = first, entry
        while index not in seen:
            seen.add(index)
            coords = segments[index].coords
            forward = side == 0
            ordered = coords if forward else coords[::-1]
            stroke.parts.append((index, forward))
            part = len(stroke.parts) - 1
            if not stroke.coords:
                stroke.coords.append(ordered[0])
            for point in ordered[1:]:
                stroke.coords.append(point)
                stroke.edge_part.append(part)
            leaving = (index, 1 if forward else 0)
            nxt = partner.get(leaving)
            if nxt is None:
                break
            index, side = nxt
        return stroke

    usable = [i for i, s in enumerate(segments) if len(s.coords) >= 2]
    # Start at the free ends first, so each open stroke is walked from one end to the other.
    for index in usable:
        if index in seen:
            continue
        for side in (0, 1):
            if (index, side) not in partner:
                out.append(walk(index, side))
                break
    # What is left is closed rings of strokes.
    for index in usable:
        if index not in seen:
            out.append(walk(index, 0))
    return out


# --- Profiles ---------------------------------------------------------------------


@dataclass(slots=True)
class Sample:
    along_m: float
    lon: float
    lat: float
    part: int
    elevation: float | None


def sample(stroke: Stroke, ground: HgtElevation, step: float = SAMPLE_STEP_M) -> list[Sample]:
    """Points every `step` metres along the stroke, and its last point."""
    coords = stroke.coords
    lengths = [_metres(coords[i], coords[i + 1]) for i in range(len(coords) - 1)]
    total = sum(lengths)
    out: list[Sample] = []
    edge = 0
    edge_start = 0.0
    targets = [k * step for k in range(int(total // step) + 1)]
    if not targets or total - targets[-1] > 1e-6:
        targets.append(total)
    for target in targets:
        while edge < len(lengths) - 1 and edge_start + lengths[edge] < target:
            edge_start += lengths[edge]
            edge += 1
        length = lengths[edge]
        t = 0.0 if length <= 0 else min(1.0, max(0.0, (target - edge_start) / length))
        a, b = coords[edge], coords[edge + 1]
        lon = a[0] + (b[0] - a[0]) * t
        lat = a[1] + (b[1] - a[1]) * t
        out.append(Sample(target, lon, lat, stroke.edge_part[edge], ground.at(lon, lat)))
    return out


def _pieces(samples: Sequence[Sample]) -> Iterator[list[Sample]]:
    piece: list[Sample] = []
    for s in samples:
        if s.elevation is None:
            if len(piece) >= 2:
                yield piece
            piece = []
        else:
            piece.append(s)
    if len(piece) >= 2:
        yield piece


# --- Output -----------------------------------------------------------------------


def _simplify(points: list[tuple[float, float]], tolerance_m: float) -> list[tuple[float, float]]:
    """Douglas-Peucker in a local flat projection."""
    if len(points) < 3:
        return points
    lat0 = sum(p[1] for p in points) / len(points)
    kx = M_PER_DEG_LAT * math.cos(math.radians(lat0))
    xy = [(p[0] * kx, p[1] * M_PER_DEG_LAT) for p in points]
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        ax, ay = xy[first]
        bx, by = xy[last]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy)
        worst, worst_i = -1.0, -1
        for i in range(first + 1, last):
            px, py = xy[i]
            if norm == 0:
                d = math.hypot(px - ax, py - ay)
            else:
                d = abs(dy * (px - ax) - dx * (py - ay)) / norm
            if d > worst:
                worst, worst_i = d, i
        if worst > tolerance_m:
            keep[worst_i] = True
            stack.append((first, worst_i))
            stack.append((worst_i, last))
    return [p for p, k in zip(points, keep, strict=True) if k]


def _line_between(stroke: Stroke, start_m: float, end_m: float) -> list[tuple[float, float]]:
    """The stroke's own vertices from `start_m` to `end_m` along it (start_m < end_m)."""
    coords = stroke.coords
    out: list[tuple[float, float]] = []
    travelled = 0.0
    for i in range(len(coords) - 1):
        a, b = coords[i], coords[i + 1]
        length = _metres(a, b)
        lo, hi = travelled, travelled + length
        if hi >= start_m and lo <= end_m and length > 0:
            if not out:
                t = max(0.0, (start_m - lo) / length)
                out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            if hi <= end_m:
                out.append(b)
            else:
                t = (end_m - lo) / length
                out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
                break
        travelled = hi
    return out


def _rounded(point: tuple[float, float]) -> list[float]:
    return [round(point[0], COORD_DECIMALS), round(point[1], COORD_DECIMALS)]


def climb_id(start: tuple[float, float], summit: tuple[float, float]) -> str:
    key = json.dumps([_rounded(start), _rounded(summit)])
    return hashlib.sha1(key.encode()).hexdigest()[:10]


@dataclass
class Found:
    climb: Climb
    line: list[tuple[float, float]]
    unpaved_share: float
    trail_name: str | None

    def entry(self) -> dict:
        line = [_rounded(p) for p in _simplify(self.line, SIMPLIFY_M)]
        summit = line[-1]
        out: dict = {
            "id": climb_id(self.line[0], self.line[-1]),
            "c": self.climb.category,
            "l": round(self.climb.length_m),
            "r": round(self.climb.gain_m),
            "g": self.climb.grade_pct,
            "x": summit[0],
            "y": summit[1],
            "line": line,
        }
        if self.unpaved_share > 0.5:
            out["u"] = 1
        if self.trail_name:
            out["n"] = self.trail_name
        return out


def climbs_on_stroke(
    stroke: Stroke, segments: Sequence[SegmentLine], ground: HgtElevation
) -> list[Found]:
    """The categorised climbs along one stroke, both ways, that a rider may ride."""
    samples = sample(stroke, ground)
    if len(samples) < 2:
        return []
    total = samples[-1].along_m
    found: list[Found] = []
    for reverse in (False, True):
        ordered = samples[::-1] if reverse else samples
        for piece in _pieces(ordered):
            profile = [(total - s.along_m if reverse else s.along_m, s.elevation) for s in piece]
            for climb in climb_categories.find_in_piece(profile):  # type: ignore[arg-type]
                used = piece[climb.start_index : climb.end_index + 1]
                parts = sorted({s.part for s in used})
                if not _rideable(stroke, segments, parts, reverse):
                    continue
                a = piece[climb.start_index].along_m
                b = piece[climb.end_index].along_m
                line = _line_between(stroke, min(a, b), max(a, b))
                if reverse:
                    line.reverse()
                if len(line) < 2:
                    continue
                found.append(
                    Found(
                        climb=climb,
                        line=line,
                        unpaved_share=_share(used, stroke, segments, lambda s: s.unpaved is True),
                        trail_name=_trail_name(used, stroke, segments),
                    )
                )
    return found


def _rideable(
    stroke: Stroke, segments: Sequence[SegmentLine], parts: Iterable[int], reverse: bool
) -> bool:
    for part in parts:
        index, forward = stroke.parts[part]
        if segments[index].oneway and forward == reverse:
            return False
    return True


def _share(used: Sequence[Sample], stroke: Stroke, segments: Sequence[SegmentLine], test) -> float:
    if not used:
        return 0.0
    hits = sum(1 for s in used if test(segments[stroke.parts[s.part][0]]))
    return hits / len(used)


def _trail_name(
    used: Sequence[Sample], stroke: Stroke, segments: Sequence[SegmentLine]
) -> str | None:
    names = Counter(segments[stroke.parts[s.part][0]].trail_name for s in used)
    name, count = names.most_common(1)[0]
    return name if name and count * 2 > len(used) else None


def find_all(segments: Sequence[SegmentLine], ground: HgtElevation) -> list[Found]:
    found: list[Found] = []
    for stroke in strokes(segments):
        found.extend(climbs_on_stroke(stroke, segments, ground))
    return found


def document(found: Sequence[Found], built: datetime | None = None) -> dict:
    """The file's contents: the climbs biggest first (so the map draws the biggest on top
    where markers meet), with the counts per category. A climb taken off by hand
    (`routemaker.climb_exclusions`) is not written."""
    entries = [f.entry() for f in sorted(found, key=lambda f: -f.climb.gain_m)]
    # The same climb found twice (a stroke that is a closed ring) is kept once.
    unique: dict[str, dict] = {}
    for entry in entries:
        if climb_exclusions.is_excluded(entry["id"]):
            continue
        unique.setdefault(entry["id"], entry)
    climbs = list(unique.values())
    counts = Counter(entry["c"] for entry in climbs)
    return {
        "version": FORMAT_VERSION,
        "built": (built or datetime.now(UTC)).strftime("%Y-%m-%d"),
        "source": "OpenStreetMap contributors, ODbL 1.0; USGS 3DEP 1 arc-second, public domain",
        "counts": {name: counts.get(name, 0) for name, _ in climb_categories.CATEGORIES},
        "climbs": climbs,
    }


def write(path: Path | str, doc: dict) -> None:
    """Write the file atomically, one climb per line so a diff of a refresh is readable."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    head = {k: v for k, v in doc.items() if k != "climbs"}
    lines = [json.dumps(c, separators=(",", ":"), ensure_ascii=False) for c in doc["climbs"]]
    body = json.dumps(head, ensure_ascii=False)[:-1]
    text = body + ', "climbs": [\n' + ",\n".join(lines) + "\n]}\n"
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


# --- Reading the live table -------------------------------------------------------


SEGMENT_QUERY = """
SELECT osm_way_id, ordinal, ST_AsGeoJSON(geometry, 7), {oneway}, is_unpaved, {trail_name}
FROM {schema}.segment
WHERE map_class = 'road' AND NOT mtb_only AND NOT walk_bike{access}
ORDER BY osm_way_id, ordinal
"""
# The bike-access reasons (`segment.bike_access_reason`) the segment panel calls open
# (`core.segment_info.ACCESS_WORDS`): a way with any other reason carries no climb.
ACCESS_FILTER = " AND (bike_access_reason IS NULL OR bike_access_reason = ANY(%s))"


def open_access_reasons() -> list[str]:
    """The reasons a way open to bicycles may carry; every other one is closed, an unknown
    one included (unclear access is closed, OWNER-DECISIONS 330)."""
    from core.segment_info import ACCESS_WORDS

    return sorted(reason for reason, (is_open, _words) in ACCESS_WORDS.items() if is_open)


def read_segments(schema: str) -> list[SegmentLine]:
    """The routable network from the given segment schema (Django's database)."""
    from django.db import connection, transaction

    from .schema import validate_schema_name

    validate_schema_name(schema)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = 'segment'",
            [schema],
        )
        columns = {row[0] for row in cursor.fetchall()}
    query = SEGMENT_QUERY.format(
        schema=schema,
        oneway="road_oneway" if "road_oneway" in columns else "NULL",
        trail_name="trail_name" if "trail_name" in columns else "NULL",
        access=ACCESS_FILTER if "bike_access_reason" in columns else "",
    )
    params = [open_access_reasons()] if "bike_access_reason" in columns else []
    out: list[SegmentLine] = []
    # A named (server-side) cursor streams the rows instead of holding them all twice; psycopg2
    # allows one only inside a transaction, and Django runs in autocommit.
    with transaction.atomic(), connection.connection.cursor(name="climb_layer_segments") as cursor:
        cursor.itersize = 20_000
        cursor.execute(query, params)
        for way, ordinal, geojson, oneway, unpaved, trail_name in cursor:
            coords = tuple((float(x), float(y)) for x, y in json.loads(geojson)["coordinates"])
            out.append(
                SegmentLine(
                    key=(int(way), int(ordinal)),
                    coords=coords,
                    oneway=bool(oneway),
                    unpaved=unpaved,
                    trail_name=trail_name or None,
                )
            )
    return out
