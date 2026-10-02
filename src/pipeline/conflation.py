"""Matching agency layers onto OSM ways.

Traffic volume is the one classifier input OpenStreetMap structurally lacks, so
every jurisdiction's count layer has to be attached to OSM geometry before the
stress classifier can read it. Plain buffer overlap is not good enough for that,
and fails on exactly the geometries this region is full of: a divided boulevard
whose two carriageways are separate ways, and a sidepath running parallel to the
road it follows. Both put an agency feature within a few metres of two different
OSM ways.

So a match needs three things to agree, not one:

* bearing, so a sidepath running alongside matches the road it parallels only
  when the agency feature actually runs that way too, and a cross street never
  matches;
* overlap, as a fraction of *the way*, so a brief stub of an agency line lying
  on a long road does not describe that road - while a corridor feature running
  well past a short block still describes the block completely;
* exclusivity along the feature, so a single count cannot be claimed by both
  carriageways of a divided road and double the volume on each - while a count
  covering a corridor still reaches every OSM way strung along it, because OSM
  splits a road at every intersection and a global one-feature-one-way rule
  would give the corridor's volume to one block and leave the rest unmeasured.

Precedence when several sources cover the same way is explicit rather than
incidental: a local agency's own layer, then the state's, then the OSM-derived
value. The losers are recorded rather than discarded, because a disagreement
between two agencies about the same road is a thing a reviewer needs to see.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from routemaker import agency_roads
from routemaker.agency_roads import RoadFacts, WayFacts, names_agree
from routemaker.geo import (
    EARTH_RADIUS_M,
    Point,
    bearing,
    bearing_delta,
    cumulative_distances,
    haversine,
    project_onto_segment,
)

# A match must run within this many degrees of the OSM way. Generous enough for
# survey noise and a curving road, tight enough to exclude a cross street.
BEARING_TOLERANCE_DEG = 25.0

# As a fraction of *the way*, which is what `_overlap` measures and is not the
# same thing as a fraction of the shorter of the two features: a twenty-metre
# agency stub lying on a two-kilometre road scores 1.0 as a fraction of the
# shorter line and 0.01 as a fraction of the way, and it is the way that the
# count is being asked to describe. See `_overlap` for the other direction.
MIN_OVERLAP_FRACTION = 0.5

# Beyond this the features are not the same road, whatever their bearing.
MAX_SEPARATION_M = 20.0

# Highest first. A locality surveys its own streets more densely than the state
# does, which is the whole reason to prefer it.
SOURCE_PRECEDENCE = ("locality", "state", "osm")


@dataclass(frozen=True)
class AgencyFeature:
    """One agency record: a line, a volume, and where it came from.

    `source` and `agency` are two different facts and both are needed. `source`
    is the *precedence tier* - one of `SOURCE_PRECEDENCE` - and it exists only
    so that two counts covering the same road can be ranked against each other;
    it says that DDOT outranks VDOT on a District street, and nothing else.
    `agency` is who published the count: `ddot`, `vdot`, `mdot-sha`. The
    installer decides both from one `--volume-source` flag and writes both into
    `volume.json`.

    Only the tier was carried for a while, and the derivative paid for it: the
    segment table's `volume_source` column held "state", so an MDOT SHA count
    and a VDOT count were the same string in the published output, and PLAN:31-34
    asks the derivative to be able to say which segments a conditionally
    licensed source influenced. It could not. `agency` is what answers that
    question and `source` is what ranks; neither substitutes for the other.
    """

    feature_id: str
    coordinates: Sequence[tuple[float, float]]
    aadt: int
    source: str
    year: int | None = None
    agency: str | None = None


@dataclass(frozen=True)
class Match:
    """One agency feature attached to one OSM way, with everything it carries.

    Everything, because the pipeline stage downstream of this is where the
    provenance stops being recoverable: the feature list is not kept and the
    segment table is the published artefact. `year` and `agency` travelled this
    far and were dropped at the assignment into `aadt_by_way`, which took
    `(aadt, source)` - the volume and its precedence tier - and left a segment
    table that could not name the agency or the vintage of any count in it.
    """

    osm_way_id: int
    feature_id: str
    aadt: int
    source: str
    year: int | None
    score: float
    agency: str | None = None


@dataclass(frozen=True)
class ConflationResult:
    matched: dict[int, Match]
    # Agency features that lost a contest for a way, kept so a reviewer can see
    # two agencies disagreeing about the same road rather than only the winner.
    rejected: list[tuple[int, Match]]
    unmatched_features: list[str]


def _mean_bearing(coordinates: Sequence[tuple[float, float]]) -> float | None:
    if len(coordinates) < 2:
        return None
    first, last = coordinates[0], coordinates[-1]
    return bearing(Point(*first), Point(*last))


def _length_m(coordinates: Sequence[tuple[float, float]]) -> float:
    return sum(
        haversine(Point(*a), Point(*b)) for a, b in zip(coordinates, coordinates[1:], strict=False)
    )


def _densify(
    coordinates: Sequence[tuple[float, float]], spacing_m: float
) -> list[tuple[float, float]]:
    """Add points along each segment so sampling does not depend on vertex count.

    An agency line drawn with two vertices and an OSM way drawn with forty
    describe the same road; sampling raw vertices would weight them differently
    and, on a two-vertex line, would test two points for a kilometre of road.
    """
    if len(coordinates) < 2:
        return list(coordinates)
    out: list[tuple[float, float]] = [coordinates[0]]
    for a, b in zip(coordinates, coordinates[1:], strict=False):
        length = haversine(Point(*a), Point(*b))
        steps = max(1, int(length // spacing_m))
        for step in range(1, steps + 1):
            t = step / steps
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def _overlap(
    way: Sequence[tuple[float, float]],
    feature: Sequence[tuple[float, float]],
    tolerance_m: float,
) -> tuple[float, tuple[float, float] | None, float]:
    """How much of the way runs near the feature, and where on the feature.

    Returns (fraction of the way within `tolerance_m` of the feature, the span of
    the feature the way covers as a pair of fractions, the mean distance of the
    near probes from the feature). The span is what makes exclusivity work along
    a corridor rather than across it; the mean distance is what lets `conflate`
    break a tie on geometry - which of two equally-plausible candidates actually
    runs closer to the feature - rather than on the order `ways` happened to be
    listed in.

    Measured over the way rather than over the shorter of the two, which is what
    the module claimed and is not the same thing. The question being decided is
    whether this count describes this way: a corridor running well past a short
    block describes the block completely, while a twenty-metre stub lying on a
    two-kilometre road does not describe the road - and as a fraction of the
    shorter line that stub scored 1.0. The earlier test for it passed only
    because the distance measure was broken in the opposite direction.

    Distance is measured to the line, not to its nearest vertex. The first
    version compared vertex against vertex, which real data never satisfies: an
    agency survey line and an OSM way describe the same road with entirely
    different vertices, so a coincident pair scored 0.0 unless someone had built
    both fixtures from one coordinate list - which every test did.
    """
    if len(way) < 2 or len(feature) < 2:
        return 0.0, None, float("inf")

    return _PreparedFeature(feature, tolerance_m).overlap(
        _probes(way, tolerance_m), _bounds(way), tolerance_m
    )


def _overlap_fraction(
    way: Sequence[tuple[float, float]],
    feature: Sequence[tuple[float, float]],
    tolerance_m: float,
) -> float:
    """The fraction alone, for tests that state the measure without the span."""
    return _overlap(way, feature, tolerance_m)[0]


# How much of a stretch of an agency feature a second way may also claim before
# the two are taken to be lying alongside each other rather than end to end.
# Generous, because two OSM ways meeting at an intersection legitimately share
# the junction itself.
MAX_SPAN_REUSE = 0.25


def _claim(
    claimed: dict[str, list[tuple[float, float]]],
    feature_id: str,
    span: tuple[float, float] | None,
) -> bool:
    """Whether this way may take this feature, recording the stretch if so.

    The rule the module docstring states, and the one the first version got
    wrong. That version consumed the whole feature on the first match, so a
    corridor count reached one block of the road and every other block along it
    went unmeasured - which on an arterial is most of it. Consuming nothing would
    be worse in the other direction: both carriageways of a divided road would
    each take the full count and double the volume.

    So what is consumed is the stretch of the feature the way runs along. A way
    end to end with the first takes a different stretch and matches; a way lying
    alongside it wants the same stretch and does not.
    """
    if span is None:
        return False
    taken = claimed.setdefault(feature_id, [])
    low, high = span
    width = high - low
    for other_low, other_high in taken:
        shared = min(high, other_high) - max(low, other_low)
        if shared > 0 and (width == 0.0 or shared / width > MAX_SPAN_REUSE):
            return False
    taken.append(span)
    return True


# The index's cell, about a kilometre: small against the region, large
# against the forty-metre tolerance, so a way falls in a handful of cells.
INDEX_CELL_DEG = 0.01

# Metres per degree of latitude on the sphere `routemaker.geo` measures on.
_METRES_PER_DEGREE = EARTH_RADIUS_M * math.pi / 180.0

# The widening is doubled. It only has to be at least the tolerance; a
# generous one costs a few extra exact measurements and a tight one would
# silently drop a real match, so the error is put on the cheap side.
_INDEX_SLACK = 2.0


def _bounds(coordinates: Sequence[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [x for x, _ in coordinates]
    ys = [y for _, y in coordinates]
    return min(xs), min(ys), max(xs), max(ys)


def _margins(south: float, north: float, tolerance_m: float) -> tuple[float, float]:
    """How far to widen a box, in degrees of (longitude, latitude), so that
    anything within `tolerance_m` of it lies inside: in latitude the tolerance
    in degrees, in longitude that divided by the cosine of the box's latitude
    furthest from the equator, where a degree of longitude is shortest - both
    times `_INDEX_SLACK`."""
    margin_lat = _INDEX_SLACK * tolerance_m / _METRES_PER_DEGREE
    widest = max(abs(south), abs(north)) + margin_lat
    margin_lon = margin_lat / max(math.cos(math.radians(min(widest, 89.0))), 1e-6)
    return margin_lon, margin_lat


def _probes(coordinates: Sequence[tuple[float, float]], tolerance_m: float) -> list[Point]:
    """The points along a way that `_overlap` measures, every `tolerance_m`."""
    return [Point(*point) for point in _densify(coordinates, tolerance_m)]


# The shortest stretch a heading is taken over: a one-metre segment in a curve
# points anywhere.
_MIN_HEADING_SPAN_M = 8.0


def _probes_with_headings(
    coordinates: Sequence[tuple[float, float]], spacing_m: float
) -> tuple[list[Point], list[float]]:
    """`_probes` and, for each, the bearing of the way there.

    The bearing of the segment the probe lies on, widened to the neighbouring
    vertices where the segment is shorter than `_MIN_HEADING_SPAN_M`.
    """
    points = [Point(*point) for point in coordinates]
    probes: list[Point] = []
    headings: list[float] = []
    for number in range(len(points) - 1):
        low, high = number, number + 1
        while haversine(points[low], points[high]) < _MIN_HEADING_SPAN_M and (
            low > 0 or high < len(points) - 1
        ):
            if low > 0:
                low -= 1
            if (
                high < len(points) - 1
                and haversine(points[low], points[high]) < _MIN_HEADING_SPAN_M
            ):
                high += 1
        heading = bearing(points[low], points[high])
        a, b = coordinates[number], coordinates[number + 1]
        length = haversine(points[number], points[number + 1])
        steps = max(1, int(length // spacing_m))
        if number == 0:
            probes.append(points[0])
            headings.append(heading)
        for step in range(1, steps + 1):
            t = step / steps
            probes.append(Point(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            headings.append(heading)
    return probes, headings


class _PreparedFeature:
    """An agency line made ready to be measured against many ways.

    `distance_to_line` is the measure, and on the real data it was the whole
    cost of the stage: it recomputes the line's cumulative length on every
    call - hundreds of haversines for a many-vertex VDOT line, once per probe
    of every candidate way - and then projects the probe onto every segment,
    kilometres of them, to find the few within the tolerance.

    This computes the same answer. The cumulative lengths are computed once,
    by the same function. And a probe is projected only onto the segments
    whose box, widened by `_margins`, contains it. The distance measured is a
    haversine from the probe to a point inside the segment's own box, and a
    haversine is never less than the latitude between its two points in
    metres, nor - to well inside the doubled margin - the longitude scaled by
    the cosine of the latitude. So a segment outside that widened box is
    further than the tolerance from the probe, and can never be the
    probe's nearest segment *and* within the tolerance. If the nearest segment
    is within the tolerance it is therefore among those measured, with every
    other segment that ties it, in the same order - so the first nearest is the
    same segment, measured by the same `project_onto_segment`, giving the same
    distance and the same position along the line. If it is not within the
    tolerance, the nearest of the measured segments is no nearer, and the
    probe is not near either way. Which is the only thing `_overlap` asks.
    """

    __slots__ = ("cumulative", "segments", "total")

    def __init__(self, coordinates: Sequence[tuple[float, float]], tolerance_m: float) -> None:
        points = [Point(*point) for point in coordinates]
        self.cumulative = cumulative_distances(points)
        self.total = self.cumulative[-1]
        self.segments = []
        for position, (a, b) in enumerate(zip(points, points[1:], strict=False)):
            south, north = min(a.lat, b.lat), max(a.lat, b.lat)
            margin_lon, margin_lat = _margins(south, north, tolerance_m)
            self.segments.append(
                (
                    min(a.lon, b.lon) - margin_lon,
                    south - margin_lat,
                    max(a.lon, b.lon) + margin_lon,
                    north + margin_lat,
                    position,
                    a,
                    b,
                )
            )

    def measure(
        self, probes: Sequence[Point], box: tuple[float, float, float, float]
    ) -> list[tuple[float, float, float]] | None:
        """(distance to the line, position along it as a fraction, bearing of
        the nearest segment) for each probe, or None when no segment of the
        line can be near any probe.

        The distance is the nearest measured segment's, whether or not it is
        within the tolerance; the caller applies the tolerance. A probe that no
        measured segment's widened box holds is at infinity.
        """
        west, south, east, north = box
        # The segments that can be near any probe at all: every probe lies in
        # the way's box, so a segment whose widened box misses it is out.
        segments = [
            segment
            for segment in self.segments
            if segment[0] <= east
            and segment[2] >= west
            and segment[1] <= north
            and segment[3] >= south
        ]
        if not segments:
            return None

        cumulative, total = self.cumulative, self.total
        measured = []
        for probe in probes:
            lon, lat = probe[0], probe[1]
            best, best_along, best_segment = float("inf"), 0.0, None
            for seg_west, seg_south, seg_east, seg_north, index, a, b in segments:
                if lon < seg_west or lon > seg_east or lat < seg_south or lat > seg_north:
                    continue
                distance, t = project_onto_segment(probe, a, b)
                if distance < best:
                    along = cumulative[index] + (cumulative[index + 1] - cumulative[index]) * t
                    best, best_along = distance, along / total if total else 0.0
                    best_segment = (a, b)
            heading = bearing(*best_segment) if best_segment else 0.0
            measured.append((best, best_along, heading))
        return measured

    def overlap(
        self,
        probes: Sequence[Point],
        box: tuple[float, float, float, float],
        tolerance_m: float,
    ) -> tuple[float, tuple[float, float] | None, float]:
        """`_overlap` of the way whose probes these are and whose box `box` is."""
        measured = self.measure(probes, box)
        if measured is None:
            return 0.0, None, float("inf")

        positions = []
        distances = []
        near = 0
        for best, best_along, _heading in measured:
            if best <= tolerance_m:
                near += 1
                positions.append(best_along)
                distances.append(best)

        fraction = near / len(probes)
        span = (min(positions), max(positions)) if positions else None
        mean_distance = sum(distances) / len(distances) if distances else float("inf")
        return fraction, span, mean_distance


class _FeatureIndex:
    """Which features lie within a distance of a line's bounding box.

    A grid of `INDEX_CELL_DEG` cells. Each feature is entered in every cell
    its bounding box covers once widened by the tolerance: in latitude by the
    tolerance in degrees, in longitude by that divided by the cosine of the
    box's latitude furthest from the equator, where a degree of longitude is
    shortest. `near` returns the features entered in any cell the line's box
    covers, in input order.
    """

    def __init__(self, features: Sequence[AgencyFeature], tolerance_m: float) -> None:
        self._cells: dict[tuple[int, int], list[int]] = {}
        for position, feature in enumerate(features):
            if len(feature.coordinates) < 2:
                continue
            west, south, east, north = _bounds(feature.coordinates)
            margin_lon, margin_lat = _margins(south, north, tolerance_m)
            for cell in self._covered(
                west - margin_lon, south - margin_lat, east + margin_lon, north + margin_lat
            ):
                self._cells.setdefault(cell, []).append(position)

    @staticmethod
    def _covered(west: float, south: float, east: float, north: float):
        for column in range(
            math.floor(west / INDEX_CELL_DEG), math.floor(east / INDEX_CELL_DEG) + 1
        ):
            for row in range(
                math.floor(south / INDEX_CELL_DEG), math.floor(north / INDEX_CELL_DEG) + 1
            ):
                yield column, row

    def near(self, coordinates: Sequence[tuple[float, float]]) -> list[int]:
        if len(coordinates) < 2:
            return []
        found: set[int] = set()
        for cell in self._covered(*_bounds(coordinates)):
            found.update(self._cells.get(cell, ()))
        return sorted(found)


WayEntry = (
    tuple[int, Sequence[tuple[float, float]]] | tuple[int, Sequence[tuple[float, float]], bool]
)


def conflate(
    ways: Sequence[WayEntry],
    features: Sequence[AgencyFeature],
    bearing_tolerance_deg: float = BEARING_TOLERANCE_DEG,
    min_overlap: float = MIN_OVERLAP_FRACTION,
    max_separation_m: float = MAX_SEPARATION_M,
) -> ConflationResult:
    """Attach agency features to OSM ways.

    One count may reach several ways along a corridor and may not reach two ways
    lying alongside each other. See `_claim` for where that line is drawn.

    `ways` takes an optional third element per entry: whether the way is trail
    class. A motor-vehicle AADT is not an attribute of a shared-use path, so a
    trail is excluded from the candidate set outright rather than being left to
    win or lose a tie - with the Mount Vernon Trail 15 m from the GW Parkway
    (well inside `max_separation_m`), a trail included as an ordinary candidate
    could out-rank the roadway on bearing and overlap alone, and exclusivity
    would then deny the count to both real roadway blocks. The flag defaults to
    False for the two-element form, which is why an existing caller that has not
    been updated to pass it does not fail outright - the exclusion, and the
    fix, simply do not apply until it does. Callers should pass
    `variants.is_trail_class(way.tags)` here.

    Remaining ties - same precedence, same overlap - are broken by which
    candidate runs geometrically closer to the feature, not by the order `ways`
    was given in. The defect this replaces: reversing the order of two
    equally-plausible candidates in the input list used to reverse which one
    won, because Python's stable sort otherwise falls through to input order
    once the ranking key is exhausted. The key now ends in the way id and the
    feature id, so it is never exhausted: candidates alike on geometry as well
    are decided by id, which is arbitrary but is the same arbitrary answer on
    every rebuild of the same extract.
    """
    candidates: list[tuple[float, int, AgencyFeature, tuple[float, float] | None, float]] = []

    # Every way was measured against every feature, which on the real region is
    # a million ways by forty-five thousand count lines: the first rebuild on a
    # real host spent hours here and would have spent weeks. A pair can only
    # score if some probe on the way lies within `max_separation_m` of the
    # feature, so a feature whose box, widened by that distance, misses the
    # way's box cannot be a candidate. The index answers exactly that question
    # and only ever answers it generously, so the candidates are the ones the
    # exhaustive loop found; they are sorted by a total key below, so the order
    # the index returns them in cannot matter either.
    bearings = [_mean_bearing(feature.coordinates) for feature in features]
    index = _FeatureIndex(features, max_separation_m)
    # Built on first use and kept: a feature is a candidate for every way along
    # it, and a way's probes are the same whichever feature they are measured
    # against. What `_PreparedFeature` saves is described there.
    prepared: list[_PreparedFeature | None] = [None] * len(features)

    for entry in ways:
        way_id, coordinates, *rest = entry
        is_trail = rest[0] if rest else False
        if is_trail:
            continue
        way_bearing = _mean_bearing(coordinates)
        if way_bearing is None:
            continue
        probes = box = None
        for position in index.near(coordinates):
            feature = features[position]
            feature_bearing = bearings[position]
            if feature_bearing is None:
                continue
            # A one-way pair runs in opposite directions along the same road, so
            # a 180 degree disagreement is still the same alignment.
            delta = bearing_delta(way_bearing, feature_bearing)
            if min(delta, 180.0 - delta) > bearing_tolerance_deg:
                continue
            if prepared[position] is None:
                prepared[position] = _PreparedFeature(feature.coordinates, max_separation_m)
            if probes is None:
                probes = _probes(coordinates, max_separation_m)
                box = _bounds(coordinates)
            overlap, span, mean_distance = prepared[position].overlap(probes, box, max_separation_m)
            if overlap < min_overlap:
                continue
            candidates.append((overlap, way_id, feature, span, mean_distance))

    # Best first: precedence, then overlap, then how close the way actually
    # runs to the feature - geometry breaking the tie rather than input order.
    #
    # And the ids last, so the key is never exhausted. Three candidates alike on
    # all three measures is not a contrived case: a divided carriageway plus a
    # ramp drawn from the same survey line, or one agency's line lying over a
    # block split into equal ways, gives identical overlap and identical mean
    # distance, and the sort then fell through to input order - which is the
    # order `read_ways` happened to return the extract in, so the same data
    # clipped twice could attach the count to a different way. The ids decide it
    # instead: arbitrary, but the same arbitrary answer every rebuild.
    def rank(
        candidate: tuple[float, int, AgencyFeature, tuple[float, float] | None, float],
    ):
        overlap, way_id, feature, _span, mean_distance = candidate
        try:
            precedence = SOURCE_PRECEDENCE.index(feature.source)
        except ValueError:
            precedence = len(SOURCE_PRECEDENCE)
        return (precedence, -overlap, mean_distance, way_id, feature.feature_id)

    matched: dict[int, Match] = {}
    rejected: list[tuple[int, Match]] = []
    used_features: set[str] = set()
    claimed: dict[str, list[tuple[float, float]]] = {}

    for overlap, way_id, feature, span, _mean_distance in sorted(candidates, key=rank):
        match = Match(
            osm_way_id=way_id,
            feature_id=feature.feature_id,
            aadt=feature.aadt,
            source=feature.source,
            year=feature.year,
            score=overlap,
            agency=feature.agency,
        )
        if way_id in matched or not _claim(claimed, feature.feature_id, span):
            rejected.append((way_id, match))
            continue
        matched[way_id] = match
        used_features.add(feature.feature_id)

    unmatched = [f.feature_id for f in features if f.feature_id not in used_features]
    return ConflationResult(matched=matched, rejected=rejected, unmatched_features=unmatched)


# -- block layers: a road's facts, not a count ------------------------------------
#
# `conflate` attaches one number to one way and lets a count be claimed once,
# which is right for a bidirectional AADT and wrong for everything else an
# agency's block layer says. A posted speed or a lane count describes every way
# along the block: both carriageways of a divided boulevard are drawn as a
# single block, and each of them is that speed. And OSM ways and agency blocks
# do not break at the same places - a way can run for three blocks - so "the
# fraction of the way near this one feature" is not the question either, and a
# way matched to three blocks at a third apiece would match none.
#
# So the question put here is per stretch of the way: for each probe along it,
# which block is the one it is running along? The nearest, preferring a block
# whose street name agrees. A way's blocks are those that won enough of its
# probes to be a block it lies along rather than one it merely crosses, and the
# way is matched when they between them cover it.

# A block must win at least this many of a way's probes - one every
# `MAX_SEPARATION_M`, so about two spans of that, forty metres of the way - to
# count as one of its blocks. Not a fraction of the way: a way can run past
# twenty blocks and each is a twentieth of it, and still every one of them is
# the road the way lies along. What the count excludes is a block that only
# touches the way's end, as a way ending beside a block's end shares a probe or
# two with it.
MIN_BLOCK_PROBES = 2

# Of a way's length, how much the blocks it lies along must cover for the way to
# count as matched. The same half as `MIN_OVERLAP_FRACTION`.
MIN_BLOCK_COVERAGE = 0.5

# A name that agrees outranks one nobody has, which outranks one that
# disagrees; geometry then decides between candidates of equal rank.
_NAME_AGREES, _NAME_UNKNOWN, _NAME_DISAGREES = 0, 1, 2


@dataclass(frozen=True)
class RoadFeature:
    """One agency block: a line, a name and the facts it records."""

    feature_id: str
    coordinates: Sequence[tuple[float, float]]
    facts: RoadFacts


@dataclass(frozen=True)
class BlockShare:
    """One block a way lies along, and how much of the way it covers."""

    feature_id: str
    share: float
    names_agree: bool | None
    # Whether the way runs with the block's digitising direction (most of the
    # probes the block won point the way the block's line does) or against it.
    # DC's outbound is the line's direction, so this says which of the block's
    # two directions is the way's (`routemaker.agency_roads.aggregate`).
    along: bool | None = None


@dataclass(frozen=True)
class BlockConflation:
    # Way id -> the blocks it lies along, most covering first.
    matched: dict[int, tuple[BlockShare, ...]]
    # Way id -> the fraction of the way those blocks cover.
    coverage: dict[int, float]
    # Blocks that won no probe on any matched way: the agency's miles that OSM
    # does not have a way for, or that the geometry did not reconcile.
    unmatched_features: list[str]


def conflate_blocks(
    ways: Sequence[WayEntry],
    features: Sequence[RoadFeature],
    way_names: Mapping[int, str | None] | None = None,
    name_required: Collection[int] = (),
    name_free: Collection[int] | None = None,
    bearing_tolerance_deg: float = BEARING_TOLERANCE_DEG,
    min_coverage: float = MIN_BLOCK_COVERAGE,
    min_probes: int = MIN_BLOCK_PROBES,
    max_separation_m: float = MAX_SEPARATION_M,
) -> BlockConflation:
    """Attach agency blocks to the OSM ways that lie along them.

    A block is not claimed once: a one-way carriageway of a divided road and its
    opposite carriageway each take the block, and each share says whether its
    way runs with the block's line or against it (`BlockShare.along`), so each
    carriageway is given its own direction's facts. Trail-class ways are never candidates,
    for the reason given at `conflate`.

    `name_required` is the ways that may take a block only where its street name
    agrees with the way's: a service road or a farm track, which runs beside a
    street all the time (a parking aisle, a driveway, an alley behind the
    houses) and is not that street. Measured on Baltimore, where the unnamed
    service ways beside streets took 118 miles of the street's 25 mph.

    `name_free` is the ways a block naming a different street does *not* veto;
    every other way may not take such a block. A frontage road lies beside a
    freeway with the same heading a few metres away, and without the veto a
    large mistake follows: DC's 36th Place NE, beside New York Avenue, took that
    avenue's 45 mph, three lanes and 53,745 vehicles a day and went from LTS 1
    to LTS 4. A way whose block has no name, or that has none itself, is not
    vetoed (nothing contradicts it). The free ways are the classes agencies and
    OSM name differently on purpose - `agency_roads.NAME_FREE_HIGHWAYS`: an
    interstate is "Anacostia Freeway" to OSM and "INTERSTATE 295" to DC - and a
    way left unmatched falls back to OSM's own tags, the safe answer. The few
    free ways are passed rather than the many vetoed ones (review r1: a vetoed
    set held nearly every way id in the region). `None` vetoes nothing, for a
    layer whose names are not worth comparing.

    Where one of a way's blocks has a name that agrees, a block naming a
    different street is dropped from its shares even though it won probes
    (review r1: a free way kept a cross street's block beside its own). And a
    free way takes a block naming a different street only where the block is
    itself a freeway by the agency's class (`agency_roads.FREEWAY_CLASSES`;
    review r2: Canal Road NW, a trunk road, took the block of M Street NW, the
    arterial it runs into, and went from 35 to 20 mph).
    """
    required = frozenset(name_required)
    veto = name_free is not None
    free = frozenset(name_free or ())
    names = way_names or {}
    index = _FeatureIndex(features, max_separation_m)  # type: ignore[arg-type]
    prepared: list[_PreparedFeature | None] = [None] * len(features)

    matched: dict[int, tuple[BlockShare, ...]] = {}
    coverage: dict[int, float] = {}
    used: set[str] = set()
    # Only the matched ways' lines are kept, for the leftover-block pass below.
    lines_by_id: dict[int, Sequence[tuple[float, float]]] = {}

    for entry in ways:
        way_id, coordinates, *rest = entry
        if rest and rest[0]:
            continue
        if len(coordinates) < 2:
            continue
        near = index.near(coordinates)
        if not near:
            continue
        way_name = names.get(way_id)
        vetoed = veto and way_id not in free
        probes, headings = _probes_with_headings(coordinates, max_separation_m)
        box = _bounds(coordinates)

        # Per probe: the best (rank, distance, id, with) among the blocks near
        # it. "Near" includes running the same way: the probe's heading and the
        # block's at its nearest point agree to within the tolerance, taken
        # locally, because a long way that bends has no single bearing and a
        # block meeting a way at a junction crosses it rather than lying along it.
        # `with` is whether the way's heading there is the block's, not its reverse.
        best: list[tuple[int, float, str, bool] | None] = [None] * len(probes)
        agreement: dict[str, bool | None] = {}
        for position in near:
            feature = features[position]
            if prepared[position] is None:
                prepared[position] = _PreparedFeature(feature.coordinates, max_separation_m)
            measured = prepared[position].measure(probes, box)
            if measured is None:
                continue
            agrees = names_agree(way_name, feature.facts.name)
            if way_id in required and agrees is not True:
                continue
            if veto and agrees is False and (vetoed or not _freeway_block(feature)):
                continue
            agreement[feature.feature_id] = agrees
            rank = _NAME_UNKNOWN if agrees is None else _NAME_AGREES if agrees else _NAME_DISAGREES
            for slot, (distance, _along, heading) in enumerate(measured):
                if distance > max_separation_m:
                    continue
                delta = bearing_delta(headings[slot], heading)
                if min(delta, 180.0 - delta) > bearing_tolerance_deg:
                    continue
                candidate = (rank, distance, feature.feature_id, delta <= 90.0)
                if best[slot] is None or candidate < best[slot]:
                    best[slot] = candidate

        wins: dict[str, list[int]] = {}
        for choice in best:
            if choice is not None:
                tally = wins.setdefault(choice[2], [0, 0])
                tally[0] += 1
                tally[1] += int(choice[3])
        shares = [
            BlockShare(block, count / len(probes), agreement.get(block), with_line * 2 >= count)
            for block, (count, with_line) in wins.items()
            if count >= min(min_probes, len(probes))
        ]
        if any(share.names_agree is True for share in shares):
            shares = [share for share in shares if share.names_agree is not False]
        covered = sum(share.share for share in shares)
        if covered < min_coverage:
            continue
        shares.sort(key=lambda share: (-share.share, share.feature_id))
        matched[way_id] = tuple(shares)
        coverage[way_id] = min(1.0, covered)
        lines_by_id[way_id] = coordinates
        used.update(share.feature_id for share in shares)

    # A block that won no probe may still lie along a matched way: a twelve-metre
    # connector between two long blocks falls between the way's probes and is
    # described by its neighbours. So the blocks left over are measured the other
    # way round, by probes along the block, against the ways that were matched:
    # it is covered if half of it runs along one with the heading its own has.
    leftover = [f for f in features if f.feature_id not in used and len(f.coordinates) >= 2]
    if leftover and matched:
        used.update(
            _covered_blocks(
                leftover,
                lines_by_id,
                matched,
                max_separation_m,
                bearing_tolerance_deg,
                min_coverage,
            )
        )

    unmatched = [f.feature_id for f in features if f.feature_id not in used]
    return BlockConflation(matched=matched, coverage=coverage, unmatched_features=unmatched)


def _freeway_block(feature: RoadFeature) -> bool:
    """Whether a differently named block may still be a free way's: always for a
    layer that classes no road (Montgomery's stress records, a city's facility
    lines), and for the street-block layers only where the block is a freeway."""
    if feature.facts.agency not in agency_roads.CLASSED_AGENCIES:
        return True
    return feature.facts.functional_class in agency_roads.FREEWAY_CLASSES


def road_facts_by_way(
    ways: Sequence, entries: Sequence[WayEntry], blocks: Sequence[RoadFeature]
) -> tuple[dict[int, WayFacts], BlockConflation]:
    """What the agency street blocks say about each way they lie along.

    `ways` are the extract's ways (`osm_id`, `tags`, `name`) and `entries` the
    same ways as `conflate_blocks` takes them. The one place the matching rules
    are wired - service and track ways need an agreeing name, every class but a
    freeway's is vetoed by a disagreeing one - shared by the rebuild and the
    analysis scripts so the two cannot drift apart.
    """
    result = conflate_blocks(
        entries,
        blocks,
        {way.osm_id: way.name for way in ways},
        name_required={
            way.osm_id
            for way in ways
            if way.tags.get("highway") in agency_roads.NAME_REQUIRED_HIGHWAYS
        },
        name_free={
            way.osm_id for way in ways if way.tags.get("highway") in agency_roads.NAME_FREE_HIGHWAYS
        },
    )
    by_id = {block.feature_id: block for block in blocks}
    facts: dict[int, WayFacts] = {}
    for way_id, shares in result.matched.items():
        agreements = [share.names_agree for share in shares]
        names = (
            None if all(a is None for a in agreements) else all(a is not False for a in agreements)
        )
        facts[way_id] = agency_roads.aggregate(
            [(share.feature_id, by_id[share.feature_id].facts, share.along) for share in shares],
            names,
        )
    return facts, result


def overlay_road_facts(
    ways: Sequence,
    facts_by_way: Mapping[int, WayFacts],
    divided_ways: Collection[int] = (),
    separate_roads: Collection[int] = (),
    rows: Collection[str] = agency_roads.ROWS_190,
) -> dict[int, agency_roads.Overlay]:
    """The overlay (`agency_roads.overlay`) for each way a block reached, with
    what the ways sharing a block say about each other (`agency_roads.
    block_context`), each way's divided-road flag and its length. The one place
    the overlay is wired, shared by the rebuild and the analysis scripts.

    `ways` are the extract's ways (`osm_id`, `tags`, `coordinates`);
    `divided_ways` is `routemaker.divided.carriageways`' result and
    `separate_roads` `routemaker.facility.separate_pairs`' second. `rows` is
    the OWNER-DECISIONS 190 rows applied (`agency_roads.overlay`).
    """
    tags_of = {way.osm_id: way.tags for way in ways if way.osm_id in facts_by_way}
    separate, paired = agency_roads.block_context(facts_by_way, tags_of, separate_roads)
    overlays: dict[int, agency_roads.Overlay] = {}
    for way in ways:
        facts = facts_by_way.get(way.osm_id)
        if facts is None:
            continue
        overlays[way.osm_id] = agency_roads.overlay(
            dict(way.tags),
            facts,
            separate_road=way.osm_id in separate or way.osm_id in separate_roads,
            divided=way.osm_id in divided_ways,
            paired=way.osm_id in paired,
            length_m=_length_m(way.coordinates),
            rows=rows,
        )
    return overlays


def block_count(
    way_id: int, tags, facts: WayFacts, result: BlockConflation, counted: Collection[int]
) -> Match | None:
    """The block's daily count as the way's count, where it may stand for it:
    the block has one, no count layer reached the way (`counted`; DDOT's own
    counts are the newer survey and are never replaced), and the way is not a
    slip road (`agency_roads.block_count_applies`)."""
    if not facts.aadt or way_id in counted or not agency_roads.block_count_applies(tags):
        return None
    return Match(
        osm_way_id=way_id,
        feature_id=result.matched[way_id][0].feature_id,
        aadt=facts.aadt,
        source="inventory",
        year=facts.aadt_year,
        score=result.coverage[way_id],
        agency=facts.agency,
    )


class _Line:
    """A way's line, for the index that finds ways near a block."""

    __slots__ = ("coordinates",)

    def __init__(self, coordinates: Sequence[tuple[float, float]]) -> None:
        self.coordinates = coordinates


def _covered_blocks(
    blocks: Sequence[RoadFeature],
    lines: Mapping[int, Sequence[tuple[float, float]]],
    matched: Mapping[int, object],
    tolerance_m: float,
    bearing_tolerance_deg: float,
    min_coverage: float,
) -> set[str]:
    """The blocks that run along an already matched way for half their length."""
    ids = sorted(matched)
    index = _FeatureIndex([_Line(lines[way_id]) for way_id in ids], tolerance_m)  # type: ignore[list-item]
    prepared: dict[int, _PreparedFeature] = {}
    covered: set[str] = set()
    spacing = max(tolerance_m / 4.0, 1.0)
    for block in blocks:
        probes, headings = _probes_with_headings(block.coordinates, spacing)
        box = _bounds(block.coordinates)
        along = [False] * len(probes)
        for position in index.near(block.coordinates):
            if position not in prepared:
                prepared[position] = _PreparedFeature(lines[ids[position]], tolerance_m)
            measured = prepared[position].measure(probes, box)
            if measured is None:
                continue
            for slot, (distance, _along, heading) in enumerate(measured):
                if along[slot] or distance > tolerance_m:
                    continue
                delta = bearing_delta(headings[slot], heading)
                if min(delta, 180.0 - delta) <= bearing_tolerance_deg:
                    along[slot] = True
        if sum(along) / len(probes) >= min_coverage:
            covered.add(block.feature_id)
    return covered
