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

from collections.abc import Sequence
from dataclasses import dataclass

from routemaker.geo import Point, bearing, bearing_delta, distance_to_line, haversine

# A match must run within this many degrees of the OSM way. Generous enough for
# survey noise and a curving road, tight enough to exclude a cross street.
BEARING_TOLERANCE_DEG = 25.0

# As a fraction of the shorter of the two features.
MIN_OVERLAP_FRACTION = 0.5

# Beyond this the features are not the same road, whatever their bearing.
MAX_SEPARATION_M = 20.0

# Highest first. A locality surveys its own streets more densely than the state
# does, which is the whole reason to prefer it.
SOURCE_PRECEDENCE = ("locality", "state", "osm")


@dataclass(frozen=True)
class AgencyFeature:
    """One agency record: a line, a volume, and where it came from."""

    feature_id: str
    coordinates: Sequence[tuple[float, float]]
    aadt: int
    source: str
    year: int | None = None


@dataclass(frozen=True)
class Match:
    osm_way_id: int
    feature_id: str
    aadt: int
    source: str
    year: int | None
    score: float


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

    feature_points = [Point(*point) for point in feature]
    probes = _densify(way, tolerance_m)

    positions = []
    distances = []
    near = 0
    for point in probes:
        distance, along = distance_to_line(Point(*point), feature_points)
        if distance <= tolerance_m:
            near += 1
            positions.append(along)
            distances.append(distance)

    fraction = near / len(probes)
    span = (min(positions), max(positions)) if positions else None
    mean_distance = sum(distances) / len(distances) if distances else float("inf")
    return fraction, span, mean_distance


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
    once the ranking key is exhausted.
    """
    candidates: list[tuple[float, int, AgencyFeature, tuple[float, float] | None, float]] = []

    for entry in ways:
        way_id, coordinates, *rest = entry
        is_trail = rest[0] if rest else False
        if is_trail:
            continue
        way_bearing = _mean_bearing(coordinates)
        if way_bearing is None:
            continue
        for feature in features:
            feature_bearing = _mean_bearing(feature.coordinates)
            if feature_bearing is None:
                continue
            # A one-way pair runs in opposite directions along the same road, so
            # a 180 degree disagreement is still the same alignment.
            delta = bearing_delta(way_bearing, feature_bearing)
            if min(delta, 180.0 - delta) > bearing_tolerance_deg:
                continue
            overlap, span, mean_distance = _overlap(coordinates, feature.coordinates, max_separation_m)
            if overlap < min_overlap:
                continue
            candidates.append((overlap, way_id, feature, span, mean_distance))

    # Best first: precedence, then overlap, then how close the way actually
    # runs to the feature - geometry breaking the tie rather than input order.
    def rank(
        candidate: tuple[float, int, AgencyFeature, tuple[float, float] | None, float],
    ):
        overlap, _, feature, _span, mean_distance = candidate
        try:
            precedence = SOURCE_PRECEDENCE.index(feature.source)
        except ValueError:
            precedence = len(SOURCE_PRECEDENCE)
        return (precedence, -overlap, mean_distance)

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
        )
        if way_id in matched or not _claim(claimed, feature.feature_id, span):
            rejected.append((way_id, match))
            continue
        matched[way_id] = match
        used_features.add(feature.feature_id)

    unmatched = [f.feature_id for f in features if f.feature_id not in used_features]
    return ConflationResult(matched=matched, rejected=rejected, unmatched_features=unmatched)
