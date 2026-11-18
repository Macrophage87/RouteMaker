"""The Intervals map layer's file: stretches an interval effort can run unbroken, found once
at build time.

The owner, 2026-11-16: "I'd want a layer that could identify interval-capable segments.
Basically we're looking for long segments that have limited turns, no intersections, and are
either flat or uphill. We'd have this in the Plan panel and available for the MCP." Run on the
build host after a rebuild has promoted the live table, by `manage.py build_intervals`
(docs/OPERATIONS.md, "The Intervals layer"), as the Climbs layer's file is; the file it writes
is committed as frontend/src/interval-data/intervals.json.

It reuses the Climbs layer's network, strokes and ground (`pipeline.climb_layer`): a stretch
lies on one stroke, a road as a rider follows it across its cross streets, so it never turns
more than `climb_layer.MAX_DEFLECTION_DEG` at a junction. Along each stroke, read both ways,
an effort is broken by (the connector's interval check's own rules, mcp/routemaker_mcp.py
`_breaks`, from the owner's 2026-10-25 ask: "places with limited needs to turn, go downhill, or
stop during the on sets"):

- **a stop**: a signal, a stop or give-way sign, a mini roundabout, a railway crossing or a
  barrier (a gate, a chain, a cycle barrier) on a node of the stroke, from the extract's node
  tags (a bollard or block is ridden through and only counted, `k`); and a
  roundabout (`junction=roundabout`), whose ways are never part of a stretch;
- **an intersection** (`JUNCTION_RULE`): where the stroke is a road, a road crossing it (arms on
  both sides) that is busy (LTS 3 or higher); where it is a path, any road it meets. With
  `JUNCTION_RULE = "every"` every road joining it breaks it. A driveway, a parking aisle, a
  footway or a track joining never does;
- **a sharp turn**: `SHARP_TURN_DEG` or more within `TURN_REACH_M` either side of a vertex;
- **a descent**: ground falling `DESCENT_PCT` or steeper, held `DESCENT_MIN_M`. A climb is the
  same descent ridden the other way, so a stretch may hold one way only ("flat or uphill");
- **an LTS 4 road or Avoid** (`NEVER_TIER`), a mountain-bike trail, ground the tiles do not
  have, and a one-way road ridden against its traffic (that way only).

A stop, an intersection or a sharp turn cuts `PAD_M` either side: the slowing before and the
getting going after. What is left is a stretch when riding it takes at least `MIN_EFFORT_MIN`
minutes at `EFFORT_PACE_MPH` on the flat, slowed on a climb as the connector's interval check
slows it (`effort_minutes`): the owner, 2026-11-17, "It's the distance with the elevation gain
that would add it ... if it's a continuous uphill, you don't need as much distance". A stretch
that holds both ways is written once with `w`, its minutes the quicker way's.

Every threshold here is the interval check's, or our default (unmeasured), as marked.

The file, one stretch per entry, short keys (frontend/src/lib/intervals.ts reads it):

    id   stable id from its ends and `w` (10 hex digits)
    l    length, m (whole)
    r    net rise along `line`, m (whole; a one-way stretch may fall a little overall, never
         2% for 150 m; a both-ways stretch reads either sign)
    g    average grade along `line`, % to a tenth
    line the stretch in its riding direction (the direction it holds, or either for `w`),
         simplified to `climb_layer.SIMPLIFY_M`
    w    1 when it holds both ways (left out otherwise)
    n    its name from its roads (`climb_names.roads`); left out when it has none
    s    "p" a paved traffic-free path, "g" mostly unpaved; left out on a road
    b    1 when most of it is on roads rated LTS 3 (left out otherwise)
    t    minutes to ride it at EFFORT_PACE_MPH, to a tenth (the quicker way for `w`)
    k    how many bollards or blocks it passes (left out when none)
"""

from __future__ import annotations

import hashlib
import json
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from . import climb_layer, climb_names
from .climb_layer import HgtElevation, Sample, SegmentLine, Stroke

FORMAT_VERSION = 1
# The owner's shortest interval, 2026-11-17 ("a 3', 5', 8', etc interval stretch").
MIN_EFFORT_MIN = 3.0
# The connector's (mcp/routemaker_mcp.py, pace_mph's default and CLIMB_SLOWING): an effort's
# speed on the flat, and how a grade slows it: pace / (1 + CLIMB_SLOWING * grade %).
EFFORT_PACE_MPH = 18.0
CLIMB_SLOWING = 0.12
METRES_PER_MILE = 1609.344
# Our default: no piece shorter than this is looked at (three minutes is longer even at 15%).
MIN_LENGTH_M = 400.0
# The interval check's (mcp/routemaker_mcp.py): a turn this sharp slows an effort, a descent
# this steep held this far breaks one, and the slowing and getting going round a stop or turn
# (0.05 mi).
SHARP_TURN_DEG = 60.0
DESCENT_PCT = 2.0
DESCENT_MIN_M = 150.0
PAD_M = 80.0
# Our default: the bearing either side of a vertex is read this far out, as the climbs' is.
TURN_REACH_M = 20.0
# The interval check's: a road this busy to cross breaks an effort; one this stressful is
# never ridden in one (LTS 4 and Avoid).
BUSY_TIER = 3
NEVER_TIER = 4
# "stops": break only where a rider may have to stop or yield (the default, pending the
# owner's pick on 2026-11-16); "every": at every road that joins.
JUNCTION_RULE = "stops"
# An arm within this of the stroke's own heading runs along it (a merge), on neither side.
ALONG_DEG = 20.0

# Node tags that stop or slow an effort wherever they are on the stroke.
STOP_HIGHWAY = {
    "traffic_signals": "signal",
    "stop": "stop sign",
    "give_way": "yield sign",
    "mini_roundabout": "roundabout",
}
STOP_RAILWAY = frozenset({"level_crossing", "crossing"})
STOP_BARRIERS = frozenset(
    {
        "gate",
        "lift_gate",
        "swing_gate",
        "sliding_gate",
        "cycle_barrier",
        "kissing_gate",
        "stile",
        "chain",
        "turnstile",
    }
)
# Bollards and blocks keep cars out and are ridden through, so they do not break a stretch;
# a stretch notes how many it passes (the owner, 2026-11-18: "Mark bollards on the interval
# card and have it noted ... You'll be going at like 6 mph up a steep hill, you're unlikely
# to have issues with bollards"). The connector's interval check never counted them.
PASS_BARRIERS = frozenset({"bollard", "block"})
BOLLARD = "bollard"
# Ways that join without breaking an effort, whatever the rule: no one on them has priority.
MINOR_HIGHWAYS = frozenset(
    {"footway", "steps", "path", "cycleway", "bridleway", "pedestrian", "track", "corridor"}
)
MINOR_SERVICE = frozenset({"driveway", "parking_aisle", "drive-through", "emergency_access"})
ROUNDABOUT = frozenset({"roundabout", "circular"})

# A stop or yield sign on a junction's own node may be for the cross road only (OSM often
# tags `stop=minor`, or nothing): there it breaks a stroke only when the stroke is not the
# busier road. An all-way stop always does.
PRIORITY_SIGNS = frozenset({"stop sign", "yield sign"})
ALL_WAY = "all-way stop"

PATH = climb_layer.PATH
GRAVEL = climb_layer.GRAVEL


# --- The extract ------------------------------------------------------------------


@dataclass
class ExtractFacts:
    """What the stretches need from the extract beyond the segment table."""

    # Node key (`node_key`) -> why it stops an effort.
    stops: dict[int, str] = field(default_factory=dict)
    # Ways that never break one (driveways, footways ...), and roundabouts.
    minor: set[int] = field(default_factory=set)
    roundabouts: set[int] = field(default_factory=set)


def node_stop(tags: dict[str, str]) -> str | None:
    """Why a node's tags stop an effort, or None."""
    why = STOP_HIGHWAY.get(tags.get("highway", ""))
    if why in PRIORITY_SIGNS and tags.get("stop") == "all":
        return ALL_WAY
    if why:
        return why
    if tags.get("crossing") == "traffic_signals" or tags.get("crossing:signals") == "yes":
        return "signal"
    if tags.get("railway") in STOP_RAILWAY:
        return "railway crossing"
    if tags.get("barrier") in STOP_BARRIERS:
        return "barrier"
    if tags.get("barrier") in PASS_BARRIERS:
        return BOLLARD
    return None


def way_minor(tags: dict[str, str]) -> bool:
    return tags.get("highway") in MINOR_HIGHWAYS or tags.get("service") in MINOR_SERVICE


def read_extract(pbf: Path | str, way_ids: Iterable[int]) -> ExtractFacts:
    """The stops on nodes, and which of `way_ids` are minor or roundabouts: one pass."""
    import osmium

    wanted = set(way_ids)
    out = ExtractFacts()
    processor = osmium.FileProcessor(str(pbf), osmium.osm.NODE | osmium.osm.WAY).with_filter(
        osmium.filter.KeyFilter("highway", "crossing", "crossing:signals", "railway", "barrier")
    )
    for obj in processor:
        tags = {tag.k: tag.v for tag in obj.tags}
        if obj.is_way():
            if obj.id in wanted:
                if way_minor(tags):
                    out.minor.add(obj.id)
                if tags.get("junction") in ROUNDABOUT:
                    out.roundabouts.add(obj.id)
            continue
        why = node_stop(tags)
        if why and obj.location.valid():
            out.stops[node_key((obj.location.lon, obj.location.lat))] = why
    return out


# --- Junctions --------------------------------------------------------------------


def node_key(point: tuple[float, float]) -> int:
    """A node's place as one int (1e-7 degrees, as `climb_layer._node`): a fifth of a tuple's
    memory, which matters over the network's millions of vertices."""
    return (round(point[0] * 1e7) + 1_800_000_000) << 32 | (round(point[1] * 1e7) + 900_000_000)


def shared_vertices(segments: Sequence[SegmentLine]) -> dict[int, list[tuple[int, int]]]:
    """Every node two or more segment vertices share: (segment index, vertex index) at each.
    The segments are cut by length, not at junctions, so a road crossing another mid-way
    shares a vertex with it and no end. Counted first, so only shared nodes are held; a
    later piece's first vertex is its way's previous piece's last, so it is not counted."""
    keys = sorted(
        node_key(point)
        for segment in segments
        for point in (segment.coords[1:] if segment.key[1] > 0 else segment.coords)
    )
    shared = {a for a, b in zip(keys, keys[1:], strict=False) if a == b}
    del keys
    out: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for index, segment in enumerate(segments):
        for j, point in enumerate(segment.coords):
            key = node_key(point)
            if key in shared:
                out[key].append((index, j))
    return out


def _is_road(segment: SegmentLine, facts: ExtractFacts) -> bool:
    return not segment.trail and not segment.mtb and segment.key[0] not in facts.minor


def _arms(segment: SegmentLine, j: int) -> list[float]:
    """The bearings leaving vertex j along the segment, one or two."""
    coords = segment.coords
    out = []
    if j > 0:
        out.append(climb_layer._outward(coords[j::-1]))
    if j < len(coords) - 1:
        out.append(climb_layer._outward(coords[j:]))
    return out


def _side(heading: float, arm: float) -> int:
    """+1 right of the heading, -1 left, 0 along it (within ALONG_DEG ahead or behind)."""
    rel = (arm - heading) % 360.0
    if rel < ALONG_DEG or rel > 360.0 - ALONG_DEG or abs(rel - 180.0) < ALONG_DEG:
        return 0
    return 1 if rel < 180.0 else -1


def vertex_break(
    stroke: Stroke,
    i: int,
    segments: Sequence[SegmentLine],
    at_vertex: dict[int, list[tuple[int, int]]],
    facts: ExtractFacts,
    rule: str = JUNCTION_RULE,
) -> str | None:
    """Why the stroke's interior vertex i breaks an effort, or None."""
    coords = stroke.coords
    key = node_key(coords[i])
    own = {stroke.parts[stroke.edge_part[i - 1]][0], stroke.parts[stroke.edge_part[i]][0]}
    others = [(s, j) for s, j in at_vertex.get(key, ()) if s not in own]
    roads = [(s, j) for s, j in others if _is_road(segments[s], facts)]
    here = segments[stroke.parts[stroke.edge_part[i]][0]]
    why = facts.stops.get(key)
    if why == BOLLARD:
        why = None  # ridden through; the stretch notes it (`Stretch.bollards`)
    if why in PRIORITY_SIGNS and roads:
        # On the junction's own node: the cross road's sign where the stroke is the busier road.
        if (here.tier or 0) <= max(segments[s].tier or 0 for s, _ in roads):
            return why
    elif why:
        return why
    if not others:
        return None
    if any(segments[s].key[0] in facts.roundabouts for s, _ in others):
        return "roundabout"
    if not roads:
        return None
    if not _is_road(here, facts):
        return "road crossing"  # a path meeting a road: the path gives way
    if rule == "every":
        return "junction"
    heading = climb_layer._outward(coords[i:])
    sides: set[int] = set()
    busy = False
    for s, j in roads:
        for arm in _arms(segments[s], j):
            side = _side(heading, arm)
            if side:
                sides.add(side)
        busy = busy or (segments[s].tier or 0) >= BUSY_TIER
    if sides == {1, -1} and busy:
        return "busy road to cross"
    return None


def sharp_turn(coords: Sequence[tuple[float, float]], i: int) -> bool:
    back = _outward_within(coords[i::-1])
    ahead = _outward_within(coords[i:])
    return climb_layer._deflection(back, ahead) >= SHARP_TURN_DEG


def _outward_within(coords: Sequence[tuple[float, float]]) -> float:
    """The bearing leaving coords[0], to the point TURN_REACH_M out along the line."""
    travelled = 0.0
    for k in range(1, len(coords)):
        step = climb_layer._metres(coords[k - 1], coords[k])
        if travelled + step >= TURN_REACH_M and step > 0:
            t = (TURN_REACH_M - travelled) / step
            a, b = coords[k - 1], coords[k]
            return climb_layer._bearing(
                coords[0], (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            )
        travelled += step
    return climb_layer._bearing(coords[0], coords[-1])


# --- Stretches --------------------------------------------------------------------


Span = tuple[float, float]


def _merge(spans: Iterable[Span]) -> list[Span]:
    out: list[Span] = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def clear_spans(total: float, cuts: Iterable[Span], min_length: float = MIN_LENGTH_M) -> list[Span]:
    """What of [0, total] no cut covers, in pieces at least `min_length` long."""
    out, at = [], 0.0
    for a, b in _merge(cuts):
        if a - at >= min_length:
            out.append((at, a))
        at = max(at, b)
    if total - at >= min_length:
        out.append((at, total))
    return out


def effort_minutes(length_m: float, rise_m: float, pace_mph: float = EFFORT_PACE_MPH) -> float:
    """The minutes an effort takes over `length_m` rising `rise_m` (a fall rides as flat)."""
    if length_m <= 0:
        return 0.0
    grade = max(0.0, rise_m / length_m * 100.0)
    speed = pace_mph / (1 + CLIMB_SLOWING * grade)
    return length_m / METRES_PER_MILE / speed * 60.0


def descents(samples: Sequence[Sample], sign: int) -> list[Span]:
    """The spans where the ground falls DESCENT_PCT or more over DESCENT_MIN_M, riding along
    the stroke (sign +1) or against it (sign -1)."""
    out = []
    j = 0
    for i, s in enumerate(samples):
        j = max(j, i + 1)
        while j < len(samples) and samples[j].along_m - s.along_m < DESCENT_MIN_M:
            j += 1
        if j >= len(samples):
            break
        e = samples[j]
        if s.elevation is None or e.elevation is None:
            continue
        grade = (e.elevation - s.elevation) / (e.along_m - s.along_m) * 100.0 * sign
        if grade <= -DESCENT_PCT:
            out.append((s.along_m, e.along_m))
    return out


def _vertex_along(coords: Sequence[tuple[float, float]]) -> list[float]:
    out, walked = [0.0], 0.0
    for a, b in zip(coords, coords[1:], strict=False):
        walked += climb_layer._metres(a, b)
        out.append(walked)
    return out


def _height(samples: Sequence[Sample], along: Sequence[float], at: float) -> float | None:
    k = bisect_left(along, at)
    if k <= 0:
        return samples[0].elevation
    if k >= len(samples):
        return samples[-1].elevation
    a, b = samples[k - 1], samples[k]
    if a.elevation is None or b.elevation is None:
        return a.elevation if b.elevation is None else b.elevation
    t = (at - a.along_m) / max(b.along_m - a.along_m, 1e-9)
    return a.elevation + (b.elevation - a.elevation) * t


@dataclass
class Stretch:
    line: list[tuple[float, float]]
    length_m: float
    rise_m: float
    both: bool
    name: str | None = None
    surface: str | None = None
    busy: bool = False
    # Bollards (and blocks) along it, ridden through (PASS_BARRIERS).
    bollards: int = 0

    @property
    def minutes(self) -> float:
        """At EFFORT_PACE_MPH, its riding way; the quicker way where it holds both."""
        rise = -abs(self.rise_m) if self.both else self.rise_m
        return effort_minutes(self.length_m, rise)

    def entry(self) -> dict:
        line = [
            climb_layer._rounded(p)
            for p in climb_layer._simplify(self.line, climb_layer.SIMPLIFY_M)
        ]
        out: dict = {
            "id": stretch_id(self.line[0], self.line[-1], self.both),
            "l": round(self.length_m),
            "r": round(self.rise_m),
            "g": round(self.rise_m / self.length_m * 100.0, 1) if self.length_m else 0.0,
            "line": line,
        }
        if self.both:
            out["w"] = 1
        if self.name:
            out["n"] = self.name
        if self.surface in (PATH, GRAVEL):
            out["s"] = self.surface
        if self.busy:
            out["b"] = 1
        out["t"] = round(self.minutes, 1)
        if self.bollards:
            out["k"] = self.bollards
        return out


def stretch_id(start: tuple[float, float], end: tuple[float, float], both: bool) -> str:
    key = json.dumps([climb_layer._rounded(start), climb_layer._rounded(end), int(both)])
    return hashlib.sha1(key.encode()).hexdigest()[:10]


def stretches_on_stroke(
    stroke: Stroke,
    segments: Sequence[SegmentLine],
    ground: HgtElevation,
    at_vertex: dict[int, list[tuple[int, int]]],
    facts: ExtractFacts,
    rule: str = JUNCTION_RULE,
) -> list[Stretch]:
    coords = stroke.coords
    if len(coords) < 2:
        return []
    along = _vertex_along(coords)
    total = along[-1]
    if total < MIN_LENGTH_M:
        return []
    samples = climb_layer.level_structures(climb_layer.sample(stroke, ground), stroke, segments)
    # Cuts either way: stops, intersections and sharp turns (padded), never-ridden parts, no ground,
    # and the stroke's ends (a junction it turns at, a stop or a dead end), padded as a stop is.
    both: list[Span] = [(0.0, PAD_M), (total - PAD_M, total)]
    for i in range(1, len(coords) - 1):
        if vertex_break(stroke, i, segments, at_vertex, facts, rule) or sharp_turn(coords, i):
            both.append((along[i] - PAD_M, along[i] + PAD_M))
    # One-way parts cut the reading that rides them against their traffic: along the stroke
    # (sign +1) that is a part walked backwards, against it a part walked forwards.
    one_way: dict[int, list[Span]] = {1: [], -1: []}
    for e in range(len(coords) - 1):
        index, forward = stroke.parts[stroke.edge_part[e]]
        segment = segments[index]
        span = (along[e], along[e + 1])
        if segment.mtb or (segment.tier or 0) >= NEVER_TIER or segment.key[0] in facts.roundabouts:
            both.append(span)
        elif segment.oneway:
            one_way[-1 if forward else 1].append(span)
    step = climb_layer.SAMPLE_STEP_M
    both.extend((s.along_m - step, s.along_m + step) for s in samples if s.elevation is None)
    sample_along = [s.along_m for s in samples]
    bollards = [
        along[i] for i in range(len(coords)) if facts.stops.get(node_key(coords[i])) == BOLLARD
    ]
    found: list[Stretch] = []
    reading = {
        sign: clear_spans(total, both + one_way[sign] + descents(samples, sign)) for sign in (1, -1)
    }
    used_back: set[int] = set()
    for a, b in reading[1]:
        twin = next(
            (
                k
                for k, (c, d) in enumerate(reading[-1])
                if k not in used_back and abs(a - c) <= step and abs(b - d) <= step
            ),
            None,
        )
        if twin is not None:
            c, d = reading[-1][twin]
            shared = _stretch(
                stroke, segments, samples, sample_along, bollards, max(a, c), min(b, d), 1, True
            )
            if shared.minutes >= MIN_EFFORT_MIN:
                used_back.add(twin)
                found.append(shared)
                continue
            # The shared part is too short the quicker way: each reading stands alone.
        found.append(_stretch(stroke, segments, samples, sample_along, bollards, a, b, 1, False))
    for k, (c, d) in enumerate(reading[-1]):
        if k not in used_back:
            found.append(
                _stretch(stroke, segments, samples, sample_along, bollards, c, d, -1, False)
            )
    return [s for s in found if s.minutes >= MIN_EFFORT_MIN]


def _stretch(stroke, segments, samples, sample_along, bollards, a, b, sign, both) -> Stretch:
    line = climb_layer._line_between(stroke, a, b)
    start, end = _height(samples, sample_along, a), _height(samples, sample_along, b)
    rise = 0.0 if start is None or end is None else end - start
    if sign < 0:
        line.reverse()
        rise = -rise
    used = [s for s in samples if a <= s.along_m <= b]
    if sign < 0:
        used.reverse()
    roads = climb_names.roads(
        [climb_layer._road_name(segments[stroke.parts[s.part][0]]) for s in used]
    )
    return Stretch(
        line=line,
        length_m=b - a,
        rise_m=rise,
        both=both,
        name=climb_names.climb_name(roads, None),
        surface=climb_layer.surface_class(used, stroke, segments),
        busy=climb_layer.busy(used, stroke, segments),
        bollards=sum(1 for x in bollards if a <= x <= b),
    )


def find_all(
    segments: Sequence[SegmentLine],
    ground: HgtElevation,
    facts: ExtractFacts,
    rule: str = JUNCTION_RULE,
) -> list[Stretch]:
    at_vertex = shared_vertices(segments)
    found: list[Stretch] = []
    for stroke in climb_layer.strokes(segments):
        found.extend(stretches_on_stroke(stroke, segments, ground, at_vertex, facts, rule))
    return found


# --- The file ---------------------------------------------------------------------


def document(found: Sequence[Stretch], built: datetime | None = None) -> dict:
    """The file's contents: the longest first, each once (a ring's stroke can find one twice)."""
    unique: dict[str, dict] = {}
    for stretch in sorted(found, key=lambda s: -s.length_m):
        entry = stretch.entry()
        unique.setdefault(entry["id"], entry)
    entries = list(unique.values())
    both = sum(1 for e in entries if e.get("w"))
    return {
        "version": FORMAT_VERSION,
        "built": (built or datetime.now(UTC)).strftime("%Y-%m-%d"),
        "source": "OpenStreetMap contributors, ODbL 1.0; USGS 3DEP 1 arc-second, public domain",
        "rule": {
            "min_minutes": MIN_EFFORT_MIN,
            "pace_mph": EFFORT_PACE_MPH,
            "sharp_turn_deg": SHARP_TURN_DEG,
            "descent_pct": DESCENT_PCT,
            "descent_m": DESCENT_MIN_M,
            "junctions": JUNCTION_RULE,
        },
        "counts": {"both_ways": both, "one_way": len(entries) - both},
        "intervals": entries,
    }


def write(path: Path | str, doc: dict) -> None:
    """Write the file atomically, one stretch per line so a diff of a refresh is readable."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    head = {k: v for k, v in doc.items() if k != "intervals"}
    lines = [json.dumps(e, separators=(",", ":"), ensure_ascii=False) for e in doc["intervals"]]
    body = json.dumps(head, ensure_ascii=False)[:-1]
    text = body + ', "intervals": [\n' + ",\n".join(lines) + "\n]}\n"
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
