#!/usr/bin/env python3
"""Write the trail mile markers and the long trails' lines, from the OSM extract.

OWNER-DECISIONS 465 (2026-10-09): "some trails like the MBT and CCT should have
mile markers as they can go a distance without crossing a road." On a long
trail between road crossings the Ride-mode 311 report, "Where am I?" and the
road panel name the nearest trail mile marker where OSM maps one, else the
distance along the named trail from its start ("Capital Crescent Trail, about
mile 3.2"), worked out on the rider's own device (the position never goes to
the server for it). Stephen, 2026-10-16: "Make sure the mile markers are added
to 311 when built." The front end is frontend/src/lib/trailMiles.ts.

What counts as a mile marker, from the OSM wiki
(<https://wiki.openstreetmap.org/wiki/Tag:highway%3Dmilestone>,
<https://wiki.openstreetmap.org/wiki/Tag:waterway%3Dmilestone>,
<https://wiki.openstreetmap.org/wiki/Key:distance>):

- a node tagged highway=milestone, or waterway=milestone (the C&O Canal's
  mileposts stand on the towpath and count the canal's miles from Georgetown),
  with its posted figure in distance=*; failing that, in ref, name or
  inscription as "Mile 3", "MM 3", "MP 3", "Mile Marker 3" or "Milepost 3";
- a node with no milestone tag whose name or ref says so in the same words
  ("Mile 3"; trail mappers often use tourism=information or marker=post);
- railway=milestone (railway:position, a railway's chainage) and
  historic=milestone alone (an old road's stone) are not trail markers and are
  left out; so is any marker more than MARKER_TRAIL_M from a named trail.

distance=* defaults to kilometres on the wiki, but posts on the region's
trails count miles and mappers copy the post, so a figure with no unit is read
as miles; one with a unit ("4.8 km", "3 mi", "800 m") is converted to miles.
The figure kept is the post's, to two decimals.

What counts as a trail: a way tagged highway=cycleway, path, track or
bridleway with a name, or highway=footway with a name and bicycle=yes,
designated or permissive; bicycle=no and area=yes are left out. A marker
belongs to the nearest such way within MARKER_TRAIL_M, about 80 ft (25 m), and
takes its name.

The lines (for the computed mile where no marker is near): the ways of one
name joined at shared nodes, pieces whose ends lie within JOIN_M, about a
quarter mile (400 m, the stress tiles' trail-run gap), of each other joined
across the gap (a trail that runs on a street for a block), and the longest
path through each joined group taken as the trail's line. A line shorter than
TRAIL_MIN_M (2 miles, 3.2 km) is dropped: a short trail meets a road soon
enough. The line is simplified to about 30 ft (10 m) and rounded to 5
decimals, about 3 ft (1 m).

Where mile 0 is: with two or more of the trail's markers within
LINE_MARKER_M (100 ft, 30 m) of its line, the line runs the way their figures
grow, and `s` (the metres at the line's first point) is set so the computed
mile agrees with the posts (the median of each marker's posted metres less
its metres along). With one marker, the line runs from the end that makes its
figure closest to its distance along, and `s` is 0. With none, the line starts
at the end nearer the US Capitol: the region's long trails (the CCT, the MBT,
the W&OD, the C&O towpath, the Anacostia and Mount Vernon trails) count their
miles out from the city. A rider's computed mile is said as "about mile 3.2",
never as a post.

Run from the repository root with the development venv (osmium is in
requirements-dev.txt):

    .venv311/bin/python scripts/build_trail_miles.py \\
        --pbf <DATA_ROOT>/extracts/source.osm.pbf

It writes frontend/src/amenity-data/trail-miles.json
(frontend/src/amenity-data/README.md, "Trail mile markers").
"""

from __future__ import annotations

import argparse
import heapq
import json
import math
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_water_restrooms as water  # noqa: E402  (shared box and text rules)

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "frontend" / "src" / "amenity-data" / "trail-miles.json"
SOURCE = "OpenStreetMap contributors, ODbL 1.0"
COVERAGE_BBOX = water.COVERAGE_BBOX

METRES_PER_MILE = 1609.344
EARTH_M = 6_371_008.8
MARKER_TRAIL_M = 25.0  # about 80 ft
LINE_MARKER_M = 30.0  # about 100 ft
JOIN_M = 400.0  # about a quarter mile; pipeline.schema.TRAIL_RUN_GAP_M
TRAIL_MIN_M = 2 * METRES_PER_MILE
SIMPLIFY_M = 10.0  # about 30 ft
# The US Capitol: with no markers, a line starts at its end nearer here.
CAPITOL = (-77.00905, 38.88990)
# Over this the front end's offline copy grows too much; the build warns.
SIZE_WARN = 600_000

TRAIL_HIGHWAYS = frozenset({"cycleway", "path", "track", "bridleway"})
RIDE_FOOTWAY = frozenset({"yes", "designated", "permissive"})
MILESTONE_KEYS = ("highway", "waterway")
_NUMBER = r"([0-9]+(?:\.[0-9]+)?)"
_DISTANCE = re.compile(rf"^\s*{_NUMBER}\s*(mi|mile|miles|km|m)?\s*$", re.IGNORECASE)
_WORDS = re.compile(
    rf"\b(?:mile\s*(?:marker|post)?|milepost|mm|mp)\s*#?\s*{_NUMBER}\b", re.IGNORECASE
)


@dataclass(frozen=True)
class Marker:
    osm: str
    lon: float
    lat: float
    mile: float
    trail: str = ""


@dataclass(frozen=True)
class Trail:
    name: str
    start_m: int
    line: tuple[tuple[float, float], ...]


def metres(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle metres, as the front end's haversineM measures them."""
    (lon1, lat1), (lon2, lat2) = a, b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_M * math.asin(min(1.0, math.sqrt(h)))


def posted_mile(tags: dict[str, str]) -> float | None:
    """The figure on the post, in miles, or None when the tags give none (see the docstring)."""
    if "railway" in tags:
        return None
    milestone = any(tags.get(k) == "milestone" for k in MILESTONE_KEYS)
    if milestone:
        m = _DISTANCE.match(tags.get("distance", ""))
        if m:
            value, unit = float(m.group(1)), (m.group(2) or "mi").lower()
            if unit == "km":
                value /= METRES_PER_MILE / 1000
            elif unit == "m":
                value /= METRES_PER_MILE
            return round(value, 2)
    elif tags.get("historic") == "milestone" or "highway" in tags:
        # An old road's stone, or a crossing or bus stop that happens to say "Mile".
        return None
    for key in ("ref", "name") + (("inscription",) if milestone else ()):
        m = _WORDS.search(tags.get(key, ""))
        if m:
            return round(float(m.group(1)), 2)
    return None


def is_trail(tags: dict[str, str]) -> bool:
    """A named way a rider can take (see the docstring)."""
    if not water._text(tags.get("name")) or tags.get("area") == "yes":
        return False
    if tags.get("bicycle") == "no":
        return False
    highway = tags.get("highway")
    if highway in TRAIL_HIGHWAYS:
        return True
    return highway == "footway" and tags.get("bicycle") in RIDE_FOOTWAY


def _flat(origin_lat: float):
    kx = math.cos(math.radians(origin_lat)) * math.pi * EARTH_M / 180
    ky = math.pi * EARTH_M / 180
    return lambda p: (p[0] * kx, p[1] * ky)


def project(line, point) -> tuple[float, float]:
    """(metres from the line, metres along it) for the point's nearest place on the line."""
    flat = _flat(point[1])
    px, py = flat(point)
    best = (math.inf, 0.0)
    along = 0.0
    for a, b in pairwise(line):
        (ax, ay), (bx, by) = flat(a), flat(b)
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
        d = math.hypot(ax + t * dx - px, ay + t * dy - py)
        length = metres(a, b)
        if d < best[0]:
            best = (d, along + t * length)
        along += length
    return best


def line_length(line) -> float:
    return sum(metres(a, b) for a, b in pairwise(line))


def simplify(line, tolerance: float = SIMPLIFY_M):
    """Douglas-Peucker in flat metres; the ends always stay."""
    if len(line) < 3:
        return list(line)
    flat = _flat(line[0][1])
    pts = [flat(p) for p in line]
    keep = [False] * len(line)
    keep[0] = keep[-1] = True
    stack = [(0, len(line) - 1)]
    while stack:
        i, j = stack.pop()
        (ax, ay), (bx, by) = pts[i], pts[j]
        dx, dy = bx - ax, by - ay
        seg = math.hypot(dx, dy)
        worst, at = -1.0, -1
        for k in range(i + 1, j):
            px, py = pts[k]
            d = (
                math.hypot(px - ax, py - ay)
                if seg == 0
                else abs(dx * (ay - py) - dy * (ax - px)) / seg
            )
            if d > worst:
                worst, at = d, k
        if worst > tolerance:
            keep[at] = True
            stack += [(i, at), (at, j)]
    return [p for p, k in zip(line, keep, strict=True) if k]


def _farthest(adj, start) -> tuple[object, dict]:
    dist = {start: 0.0}
    prev: dict = {}
    heap = [(0.0, 0, start)]
    tie = 0
    while heap:
        d, _, node = heapq.heappop(heap)
        if d > dist[node]:
            continue
        for nxt, w in adj[node]:
            nd = d + w
            if nd < dist.get(nxt, math.inf):
                dist[nxt] = nd
                prev[nxt] = node
                tie += 1
                heapq.heappush(heap, (nd, tie, nxt))
    far = max(dist, key=lambda n: (dist[n], str(n)))
    return far, prev


def trail_lines(ways: list[list[tuple[int, float, float]]]) -> list[list[tuple[float, float]]]:
    """The longest path through each joined group of one name's ways (see the docstring)."""
    where: dict[int, tuple[float, float]] = {}
    adj: dict[int, list[tuple[int, float]]] = defaultdict(list)
    for way in ways:
        for (r1, x1, y1), (r2, x2, y2) in pairwise(way):
            where[r1], where[r2] = (x1, y1), (x2, y2)
            w = metres((x1, y1), (x2, y2))
            adj[r1].append((r2, w))
            adj[r2].append((r1, w))
    # Connected pieces, then their loose ends joined across a gap of up to JOIN_M.
    piece: dict[int, int] = {}
    for start in adj:
        if start in piece:
            continue
        piece[start] = start
        todo = [start]
        while todo:
            node = todo.pop()
            for nxt, _ in adj[node]:
                if nxt not in piece:
                    piece[nxt] = start
                    todo.append(nxt)
    ends = [n for n in adj if len({m for m, _ in adj[n]}) == 1]
    for i, a in enumerate(ends):
        for b in ends[i + 1 :]:
            if piece[a] != piece[b]:
                gap = metres(where[a], where[b])
                if gap <= JOIN_M:
                    adj[a].append((b, gap))
                    adj[b].append((a, gap))
    seen: set[int] = set()
    out = []
    for start in sorted(adj):
        if start in seen:
            continue
        a, _ = _farthest(adj, start)
        b, prev = _farthest(adj, a)
        group = set(prev) | {a}
        # Everything reached from `a` is this group.
        seen |= group
        path = [b]
        while path[-1] != a:
            path.append(prev[path[-1]])
        out.append([where[n] for n in reversed(path)])
    return out


def orient(line, markers: list[Marker]) -> tuple[list[tuple[float, float]], int]:
    """The line running from mile 0, and the metres at its first point (see the docstring)."""
    near = []
    for m in markers:
        off, along = project(line, (m.lon, m.lat))
        if off <= LINE_MARKER_M:
            near.append((along, m.mile * METRES_PER_MILE))
    total = line_length(line)
    if len(near) >= 2:
        n = len(near)
        ma = sum(a for a, _ in near) / n
        mm = sum(p for _, p in near) / n
        slope = sum((a - ma) * (p - mm) for a, p in near)
        if slope < 0:
            line = list(reversed(line))
            near = [(total - a, p) for a, p in near]
        offsets = sorted(p - a for a, p in near)
        mid = len(offsets) // 2
        start = offsets[mid] if len(offsets) % 2 else (offsets[mid - 1] + offsets[mid]) / 2
        return list(line), round(start)
    if len(near) == 1:
        along, posted = near[0]
        if abs(posted - (total - along)) < abs(posted - along):
            line = list(reversed(line))
        return list(line), 0
    if metres(line[-1], CAPITOL) < metres(line[0], CAPITOL):
        line = list(reversed(line))
    return list(line), 0


class _Grid:
    """Trail segments by 0.005-degree cell (about 500 m), for the nearest-trail test."""

    CELL = 0.005

    def __init__(self) -> None:
        self.cells: dict[tuple[int, int], list] = defaultdict(list)

    def add(self, name: str, a, b) -> None:
        xs = range(
            int(math.floor(min(a[0], b[0]) / self.CELL)),
            int(math.floor(max(a[0], b[0]) / self.CELL)) + 1,
        )
        ys = range(
            int(math.floor(min(a[1], b[1]) / self.CELL)),
            int(math.floor(max(a[1], b[1]) / self.CELL)) + 1,
        )
        for x in xs:
            for y in ys:
                self.cells[(x, y)].append((name, a, b))

    def nearest(self, point, within: float) -> str | None:
        cx, cy = int(math.floor(point[0] / self.CELL)), int(math.floor(point[1] / self.CELL))
        best, name = within, None
        for x in (cx - 1, cx, cx + 1):
            for y in (cy - 1, cy, cy + 1):
                for trail, a, b in self.cells.get((x, y), ()):
                    d, _ = project((a, b), point)
                    if d <= best:
                        best, name = d, trail
        return name


def in_box(lon: float, lat: float) -> bool:
    west, south, east, north = COVERAGE_BBOX
    return west <= lon <= east and south <= lat <= north


def build(
    markers: list[Marker], ways: dict[str, list[list[tuple[int, float, float]]]]
) -> tuple[list[Trail], list[Marker], int]:
    """The trails' lines, the markers kept (each with its trail), and how many no trail took."""
    grid = _Grid()
    for name, parts in ways.items():
        for way in parts:
            for (_, x1, y1), (_, x2, y2) in pairwise(way):
                grid.add(name, (x1, y1), (x2, y2))
    kept: list[Marker] = []
    lost = 0
    for m in markers:
        name = grid.nearest((m.lon, m.lat), MARKER_TRAIL_M)
        if name is None:
            lost += 1
        else:
            kept.append(Marker(m.osm, round(m.lon, 5), round(m.lat, 5), m.mile, name))
    by_trail: dict[str, list[Marker]] = defaultdict(list)
    for m in kept:
        by_trail[m.trail].append(m)
    trails: list[Trail] = []
    for name in sorted(ways):
        for line in trail_lines(ways[name]):
            if line_length(line) < TRAIL_MIN_M:
                continue
            # Simplified first, so the start is measured along the line the front end measures.
            short, start = orient(simplify(line), by_trail.get(name, []))
            trails.append(Trail(name, start, tuple((round(x, 5), round(y, 5)) for x, y in short)))
    return trails, kept, lost


def read_extract(
    path: Path,
) -> tuple[list[Marker], dict[str, list[list[tuple[int, float, float]]]]]:
    """The marker candidates and the named trail ways in the coverage box."""
    import osmium

    markers: list[Marker] = []
    ways: dict[str, list[list[tuple[int, float, float]]]] = defaultdict(list)

    class Handler(osmium.SimpleHandler):
        def node(self, n):
            t = n.tags
            if not ("highway" in t or "waterway" in t or "name" in t or "ref" in t):
                return
            mile = posted_mile(dict(t))
            if mile is None:
                return
            lon, lat = n.location.lon, n.location.lat
            if in_box(lon, lat):
                markers.append(Marker(f"n{n.id}", lon, lat, mile))

        def way(self, w):
            if "highway" not in w.tags or not is_trail(dict(w.tags)):
                return
            nodes = [
                (nd.ref, nd.location.lon, nd.location.lat) for nd in w.nodes if nd.location.valid()
            ]
            if len(nodes) < 2 or not any(in_box(x, y) for _, x, y in nodes):
                return
            ways[water._text(w.tags.get("name"))].append(nodes)

    Handler().apply_file(str(path), locations=True)
    return markers, dict(ways)


def document(trails: list[Trail], markers: list[Marker]) -> dict:
    """The file the front end reads: short keys."""

    def figure(mile: float) -> float | int:
        return int(mile) if mile == int(mile) else mile

    return {
        "source": SOURCE,
        "trails": [{"n": t.name, "s": t.start_m, "l": [list(p) for p in t.line]} for t in trails],
        "markers": [
            {"id": m.osm, "x": m.lon, "y": m.lat, "t": m.trail, "m": figure(m.mile)}
            for m in sorted(markers, key=lambda m: int(m.osm[1:]))
        ],
    }


def write_document(doc: dict, out: Path) -> int:
    """Write the file, one trail or marker per line; its size in bytes."""

    def block(rows: list) -> str:
        lines = [json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in rows]
        return "[\n" + ",\n".join(lines) + ("\n" if lines else "") + "]"

    text = (
        '{"source":'
        + json.dumps(doc["source"])
        + ',"trails":'
        + block(doc["trails"])
        + ',\n"markers":'
        + block(doc["markers"])
        + "}\n"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8")
    out.write_bytes(data)
    return len(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--pbf", type=Path, required=True, help="<DATA_ROOT>/extracts/source.osm.pbf"
    )
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    candidates, ways = read_extract(args.pbf)
    trails, markers, lost = build(candidates, ways)
    size = write_document(document(trails, markers), args.out)
    on = Counter(m.trail for m in markers)
    print(f"{len(trails)} trail lines over {TRAIL_MIN_M / METRES_PER_MILE:g} miles")
    top = ", ".join(f"{name} {n}" for name, n in on.most_common(8)) or "none"
    print(f"{len(markers)} mile markers on {len(on)} trails ({top})")
    print(f"left out, not on a named trail: {lost}")
    print(f"{args.out}: {size:,} bytes")
    if size > SIZE_WARN:
        print(f"warning: over {SIZE_WARN:,} bytes; the front end keeps it offline", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
