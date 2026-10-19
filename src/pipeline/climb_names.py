"""A name for every climb on the Climbs layer, from its roads and the hill it runs up.

The owner, 2026-10-19: "have them named, by a combination of road names and mountain names
(if named)". Named at build time by `manage.py build_climbs` (`pipeline.climb_layer`), from
the rebuild's own extract (`<DATA_ROOT>/extracts/source.osm.pbf`), so it needs no network.

**The roads.** Each segment carries its way's OSM `name`, else its `ref` ("MD 77"), else the
names the rebuild already gives an unnamed way (`mtb_name`, `trail_name`, `sidepath_name`;
`pipeline.schema`). A climb's roads are the names that carry at least `ROAD_SHARE` (a
quarter) of its length, in the order a rider meets them, at most `MAX_ROADS` of them (the
longest): "Snider Lane", "Hollow Road and Ridge Road". A road with no name carries none, so a
climb mostly on an unnamed track or driveway has no road name.

**The hill.** OSM's named `natural=saddle` (or `mountain_pass=yes`), `natural=peak`, `hill`
or `volcano`, and `natural=ridge` or `arete` (<https://wiki.openstreetmap.org/wiki/Key:natural>,
<https://wiki.openstreetmap.org/wiki/Key:mountain_pass>). A climb runs up one when all of:

- its summit is within the kind's reach of it (`REACH_M`: a gap 1,000 ft (300 m), a ridge's
  line 0.3 mi (500 m), a peak or hill 0.6 mi (1 km));
- its summit is nearer to it than its foot is (it climbs toward it);
- it gets at least half way up from its foot to the landmark's ground (USGS 3DEP, the same
  tiles the climbs are found on), so a short ramp at a big hill's foot is not named for it.

A gap wins over a peak and a peak over a ridge (the most particular place), then the nearest.
The climb is named "<roads> up <hill>" ("Foxville Road up Catoctin Mountain"), or "<roads> to
<gap>" ("Gapland Road to Crampton Gap"); the hill is left off when a road's name already has
it ("Sugarloaf Mountain Road").

**Fallbacks.** With no road name: "<hill> climb" ("Sugarloaf Mountain climb"), else "Climb
near <place>" for the nearest named `place` of a city, town, village, hamlet, suburb or
neighbourhood within 3 mi (5 km) of its foot (<https://wiki.openstreetmap.org/wiki/Key:place>),
else no name (the map then says "Category 4 climb").

Names are ODbL 1.0 data from OpenStreetMap contributors, as the rest of the file is.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

LonLat = tuple[float, float]

# A road names the climb when it carries this share of its length; at most this many do.
ROAD_SHARE = 0.25
MAX_ROADS = 2

SADDLE = "saddle"
PEAK = "peak"
RIDGE = "ridge"
# Most particular first: the gap a road crosses, then the top, then the ridge it runs along.
KIND_ORDER = (SADDLE, PEAK, RIDGE)
REACH_M = {SADDLE: 300.0, PEAK: 1_000.0, RIDGE: 500.0}
# The climb gets at least this share of the way up from its foot to the landmark.
UP_SHARE = 0.5

PLACE_KINDS = frozenset({"city", "town", "village", "hamlet", "suburb", "neighbourhood"})
PLACE_REACH_M = 5_000.0

NATURAL_KINDS = {
    "saddle": SADDLE,
    "peak": PEAK,
    "hill": PEAK,
    "volcano": PEAK,
    "ridge": RIDGE,
    "arete": RIDGE,
}

M_PER_DEG_LAT = 111_320.0
# The grid the landmarks and places are kept in, degrees: wider than every reach east-west
# across the region (0.07 degrees of longitude is 3.7 mi (6 km) at 40 N).
CELL_DEG = 0.07


def _metres(a: LonLat, b: LonLat) -> float:
    kx = M_PER_DEG_LAT * math.cos(math.radians((a[1] + b[1]) / 2))
    return math.hypot((b[0] - a[0]) * kx, (b[1] - a[1]) * M_PER_DEG_LAT)


def _nearest_on_line(point: LonLat, line: Sequence[LonLat]) -> tuple[float, LonLat]:
    """The distance from `point` to `line`, metres, and the nearest point on it."""
    if len(line) == 1:
        return _metres(point, line[0]), line[0]
    kx = M_PER_DEG_LAT * math.cos(math.radians(point[1]))
    px, py = point[0] * kx, point[1] * M_PER_DEG_LAT
    best = (math.inf, line[0])
    for a, b in zip(line, line[1:], strict=False):
        ax, ay = a[0] * kx, a[1] * M_PER_DEG_LAT
        bx, by = b[0] * kx, b[1] * M_PER_DEG_LAT
        dx, dy = bx - ax, by - ay
        norm = dx * dx + dy * dy
        t = 0.0 if norm == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / norm))
        d = math.hypot(ax + t * dx - px, ay + t * dy - py)
        if d < best[0]:
            best = (d, (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
    return best


# --- What the extract gives -------------------------------------------------------


def way_name(tags: dict[str, str]) -> str | None:
    """A way's name: `name`, else its first `ref` ("MD 77;US 15" is "MD 77")."""
    name = (tags.get("name") or "").strip()
    if name:
        return name
    ref = (tags.get("ref") or "").split(";")[0].strip()
    return ref or None


def landmark_kind(tags: dict[str, str]) -> str | None:
    """The kind of hill a named OSM element is, or None."""
    if not (tags.get("name") or "").strip():
        return None
    if tags.get("mountain_pass") == "yes":
        return SADDLE
    return NATURAL_KINDS.get(tags.get("natural", ""))


@dataclass(frozen=True, slots=True)
class Landmark:
    name: str
    kind: str
    # One point for a node, the line for a ridge drawn as a way.
    points: tuple[LonLat, ...]


@dataclass(frozen=True, slots=True)
class Place:
    name: str
    at: LonLat


class _Grid:
    """Items bucketed by the cells their points fall in, for nearby lookups."""

    def __init__(self) -> None:
        self.cells: dict[tuple[int, int], list] = defaultdict(list)

    @staticmethod
    def cell(p: LonLat) -> tuple[int, int]:
        return (math.floor(p[0] / CELL_DEG), math.floor(p[1] / CELL_DEG))

    def add(self, item, points: Iterable[LonLat]) -> None:
        for c in {self.cell(p) for p in points}:
            self.cells[c].append(item)

    def near(self, p: LonLat) -> list:
        """Every item in the cell of `p` and the eight around it (a reach under one cell)."""
        cx, cy = self.cell(p)
        seen: dict[int, object] = {}
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for item in self.cells.get((cx + dx, cy + dy), ()):
                    seen[id(item)] = item
        return list(seen.values())


@dataclass
class Gazetteer:
    """The extract's names: each way's (by OSM id), the hills and the places."""

    ways: dict[int, str] = field(default_factory=dict)
    landmarks: list[Landmark] = field(default_factory=list)
    places: list[Place] = field(default_factory=list)
    _landmark_grid: _Grid | None = None
    _place_grid: _Grid | None = None

    def landmarks_near(self, p: LonLat) -> list[Landmark]:
        if self._landmark_grid is None:
            self._landmark_grid = _Grid()
            for lm in self.landmarks:
                self._landmark_grid.add(lm, _densify(lm.points))
        return self._landmark_grid.near(p)

    def places_near(self, p: LonLat) -> list[Place]:
        if self._place_grid is None:
            self._place_grid = _Grid()
            for place in self.places:
                self._place_grid.add(place, [place.at])
        return self._place_grid.near(p)


def _densify(points: Sequence[LonLat]) -> list[LonLat]:
    """The points of a line with extra ones under a cell apart, so a long ridge drawn with few
    vertices is in every cell it crosses."""
    out = [points[0]]
    for a, b in zip(points, points[1:], strict=False):
        steps = max(1, math.ceil(max(abs(b[0] - a[0]), abs(b[1] - a[1])) / (CELL_DEG / 2)))
        out.extend(
            (a[0] + (b[0] - a[0]) * k / steps, a[1] + (b[1] - a[1]) * k / steps)
            for k in range(1, steps + 1)
        )
    return out


def read_extract(pbf: Path | str, way_ids: Iterable[int]) -> Gazetteer:
    """The names the climbs need from the extract: those of `way_ids`, and every named hill
    and place. Two passes over the file and no location index: the first reads the tagged
    nodes and ways, the second only the nodes of the ridges drawn as ways."""
    import osmium

    wanted = set(way_ids)
    out = Gazetteer()
    ridge_ways: list[tuple[str, str, list[int]]] = []
    processor = osmium.FileProcessor(str(pbf), osmium.osm.NODE | osmium.osm.WAY).with_filter(
        osmium.filter.KeyFilter("name", "ref")
    )
    for obj in processor:
        tags = {tag.k: tag.v for tag in obj.tags}
        if obj.is_way():
            if obj.id in wanted:
                name = way_name(tags)
                if name:
                    out.ways[obj.id] = name
            kind = landmark_kind(tags)
            if kind is not None:
                ridge_ways.append((tags["name"].strip(), kind, [n.ref for n in obj.nodes]))
            continue
        location = obj.location
        if not location.valid():
            continue
        at = (location.lon, location.lat)
        kind = landmark_kind(tags)
        if kind is not None:
            out.landmarks.append(Landmark(tags["name"].strip(), kind, (at,)))
        elif tags.get("place") in PLACE_KINDS and (tags.get("name") or "").strip():
            out.places.append(Place(tags["name"].strip(), at))
    if ridge_ways:
        refs = {ref for _name, _kind, nodes in ridge_ways for ref in nodes}
        located: dict[int, LonLat] = {}
        for node in osmium.FileProcessor(str(pbf), osmium.osm.NODE).with_filter(
            osmium.filter.IdFilter(refs)
        ):
            if node.location.valid():
                located[node.id] = (node.location.lon, node.location.lat)
        for name, kind, nodes in ridge_ways:
            points = tuple(located[ref] for ref in nodes if ref in located)
            if points:
                out.landmarks.append(Landmark(name, kind, points))
    return out


# --- Naming -----------------------------------------------------------------------


def roads(names: Sequence[str | None]) -> list[str]:
    """The roads that name a climb, from the name under each of its samples in riding order:
    those carrying `ROAD_SHARE` of it, the `MAX_ROADS` longest, in the order met."""
    if not names:
        return []
    counts: dict[str, int] = {}
    shown: dict[str, str] = {}
    for name in names:
        if not name:
            continue
        key = name.casefold()
        counts[key] = counts.get(key, 0) + 1
        shown.setdefault(key, name)
    kept = [key for key, n in counts.items() if n / len(names) >= ROAD_SHARE]
    longest = set(sorted(kept, key=lambda k: -counts[k])[:MAX_ROADS])
    # `counts` keeps the order the names were first met.
    return [shown[key] for key in counts if key in longest]


def landmark(foot: LonLat, summit: LonLat, gazetteer: Gazetteer, ground=None) -> Landmark | None:
    """The named hill the climb from `foot` to `summit` runs up, if any (see the module)."""
    best: tuple[int, float, Landmark] | None = None
    foot_ele = summit_ele = None
    if ground is not None:
        foot_ele, summit_ele = ground.at(*foot), ground.at(*summit)
    for lm in gazetteer.landmarks_near(summit):
        distance, nearest = _nearest_on_line(summit, lm.points)
        if distance > REACH_M[lm.kind]:
            continue
        if _nearest_on_line(foot, lm.points)[0] <= distance:
            continue
        if foot_ele is not None and summit_ele is not None:
            top = ground.at(*nearest)
            if top is not None and (
                top <= foot_ele or summit_ele - foot_ele < UP_SHARE * (top - foot_ele)
            ):
                continue
        rank = (KIND_ORDER.index(lm.kind), distance, lm)
        if best is None or rank[:2] < best[:2]:
            best = rank
    return best[2] if best else None


def nearest_place(point: LonLat, gazetteer: Gazetteer) -> Place | None:
    found = [
        (d, p) for p in gazetteer.places_near(point) if (d := _metres(point, p.at)) <= PLACE_REACH_M
    ]
    return min(found, key=lambda dp: dp[0])[1] if found else None


def climb_name(
    road_names: Sequence[str], hill: Landmark | None, place: Place | None = None
) -> str | None:
    """The climb's name from its roads, the hill it runs up and the place it starts near."""
    if road_names:
        name = " and ".join(road_names)
        if hill is not None and hill.name.casefold() not in name.casefold():
            name += f" {'to' if hill.kind == SADDLE else 'up'} {hill.name}"
        return name
    if hill is not None:
        return f"{hill.name} climb"
    if place is not None:
        return f"Climb near {place.name}"
    return None
