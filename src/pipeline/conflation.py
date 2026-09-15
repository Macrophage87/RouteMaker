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
* overlap, as a fraction of the shorter feature, so a brief crossing is not a
  match;
* exclusivity, one agency feature to one OSM way, so a single count cannot be
  claimed by both carriageways of a divided road and double the volume on each.

Precedence when several sources cover the same way is explicit rather than
incidental: a local agency's own layer, then the state's, then the OSM-derived
value. The losers are recorded rather than discarded, because a disagreement
between two agencies about the same road is a thing a reviewer needs to see.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from routemaker.geo import Point, bearing, bearing_delta, haversine

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


def _overlap_fraction(
    a: Sequence[tuple[float, float]],
    b: Sequence[tuple[float, float]],
    tolerance_m: float,
) -> float:
    """Share of the shorter feature that runs within `tolerance_m` of the other.

    Sampled along the shorter line rather than computed exactly: the inputs are
    survey lines with their own error, and an exact measure would imply a
    precision neither side has.
    """
    shorter, longer = (a, b) if _length_m(a) <= _length_m(b) else (b, a)
    if len(shorter) < 2:
        return 0.0
    near = 0
    for point in shorter:
        probe = Point(*point)
        if any(haversine(probe, Point(*other)) <= tolerance_m for other in longer):
            near += 1
    return near / len(shorter)


def conflate(
    ways: Sequence[tuple[int, Sequence[tuple[float, float]]]],
    features: Sequence[AgencyFeature],
    bearing_tolerance_deg: float = BEARING_TOLERANCE_DEG,
    min_overlap: float = MIN_OVERLAP_FRACTION,
    max_separation_m: float = MAX_SEPARATION_M,
) -> ConflationResult:
    """Attach agency features to OSM ways, one feature to one way."""
    candidates: list[tuple[float, int, AgencyFeature]] = []

    for way_id, coordinates in ways:
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
            overlap = _overlap_fraction(coordinates, feature.coordinates, max_separation_m)
            if overlap < min_overlap:
                continue
            candidates.append((overlap, way_id, feature))

    # Best first: precedence, then overlap. Exclusivity is enforced by consuming
    # both the way and the feature, so one count cannot be claimed twice.
    def rank(candidate: tuple[float, int, AgencyFeature]) -> tuple[int, float]:
        overlap, _, feature = candidate
        try:
            precedence = SOURCE_PRECEDENCE.index(feature.source)
        except ValueError:
            precedence = len(SOURCE_PRECEDENCE)
        return (precedence, -overlap)

    matched: dict[int, Match] = {}
    rejected: list[tuple[int, Match]] = []
    used_features: set[str] = set()

    for overlap, way_id, feature in sorted(candidates, key=rank):
        match = Match(
            osm_way_id=way_id,
            feature_id=feature.feature_id,
            aadt=feature.aadt,
            source=feature.source,
            year=feature.year,
            score=overlap,
        )
        if way_id in matched or feature.feature_id in used_features:
            rejected.append((way_id, match))
            continue
        matched[way_id] = match
        used_features.add(feature.feature_id)

    unmatched = [f.feature_id for f in features if f.feature_id not in used_features]
    return ConflationResult(matched=matched, rejected=rejected, unmatched_features=unmatched)
