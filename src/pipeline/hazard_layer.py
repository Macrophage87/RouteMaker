"""Known road hazards onto the ways and segments they cover (v0.10.0; `routemaker.hazards`).

Three inputs, one column (`segment.hazard`, the kinds):

- the way's own tags (`hazards.way_kinds`): a cobbled surface, `embedded_rails`;
- the extract's street-running rails (`read_rails`): a tram line, or an embedded or
  disused tram railway, matched onto the roads it lies along with the agency blocks'
  rules (`conflation.conflate_blocks`; never a trail, a service or track way never,
  since a rail line has no street name to agree with);
- the reviewed list (`fixtures/hazards/`, `hazards.load`): way ids, or a street between
  two cross streets, applied to each segment piece whose middle lies between them.

Never read by the classifier: a marked road keeps its stress rating. The graph prices a
way with a hazard anywhere on it as LTS 4 (`way_has_hazard`, `rm:hazard`; the owner,
2026-10-19: "Roads with hazards like this should get a major penalty. You only need to show
it if it's routed on"), and the route marks the stretches it rides (`core.route_hazards`).
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

import osmium

from routemaker import agency_roads, hazards

from . import conflation, extract

logger = logging.getLogger(__name__)

RAIL_AGENCY = "osm-street-rail"
# The box round two junctions is widened by this much, so a straight street's pieces
# between them are inside it however it is drawn.
BETWEEN_MARGIN_M = 30.0


class _Rails(osmium.SimpleHandler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[tuple[int, list[tuple[float, float]]]] = []

    def way(self, w) -> None:  # noqa: N802 - osmium's callback name
        tags = {tag.k: tag.v for tag in w.tags}
        if not hazards.is_street_rail(tags):
            return
        points = [(n.lon, n.lat) for n in w.nodes if n.location.valid()]
        if len(points) >= 2:
            self.lines.append((w.id, points))


def read_rails(pbf: str | Path) -> list[tuple[int, list[tuple[float, float]]]]:
    """Every street-running rail line of the extract, (way id, line)."""
    handler = _Rails()
    handler.apply_file(str(pbf), locations=True)
    return handler.lines


def rail_ways(
    ways: Sequence,
    rails: Sequence[tuple[int, Sequence[tuple[float, float]]]],
    trail_ways: frozenset[int] = frozenset(),
) -> set[int]:
    """The roads a street-running rail line lies along."""
    if not rails:
        return set()
    features = [
        conflation.RoadFeature(
            feature_id=f"rail/{way_id}",
            coordinates=[tuple(c) for c in line],
            facts=agency_roads.RoadFacts(agency=RAIL_AGENCY, name=None),
        )
        for way_id, line in rails
    ]
    entries = [
        (way.osm_id, way.coordinates, way.osm_id in trail_ways)
        for way in ways
        if way.tags.get("highway") not in agency_roads.UNBUILT_HIGHWAYS
    ]
    required = {
        way.osm_id for way in ways if way.tags.get("highway") in agency_roads.NAME_REQUIRED_HIGHWAYS
    }
    result = conflation.conflate_blocks(
        entries, features, {way.osm_id: way.name for way in ways}, name_required=required
    )
    logger.info(
        "street rails: %d lines, %d matched onto %d roads",
        len(features),
        len(features) - len(result.unmatched_features),
        len(result.matched),
    )
    return set(result.matched)


Box = tuple[float, float, float, float]


def _box(a: tuple[float, float], b: tuple[float, float], margin_m: float) -> Box:
    dlat = margin_m / 111_320.0
    dlon = margin_m / (111_320.0 * max(0.1, math.cos(math.radians((a[1] + b[1]) / 2))))
    return (
        min(a[0], b[0]) - dlon,
        min(a[1], b[1]) - dlat,
        max(a[0], b[0]) + dlon,
        max(a[1], b[1]) + dlat,
    )


def _junction(street_ways: Sequence, cross_ways: Sequence) -> tuple[float, float] | None:
    """Where the street meets the cross street: the mean of the nodes they share."""
    cross_nodes = {node for way in cross_ways for node in way.node_ids}
    points = []
    for way in street_ways:
        # A way built by hand (a test) may leave `located` empty with every node located.
        located_at = way.located or (
            range(len(way.coordinates)) if len(way.coordinates) == len(way.node_ids) else ()
        )
        for index, located in enumerate(located_at):
            if way.node_ids[located] in cross_nodes:
                points.append(way.coordinates[index])
    if not points:
        return None
    return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))


def listed_by_way(
    ways: Sequence, entries: Iterable[hazards.ListedHazard]
) -> dict[int, list[tuple[Box | None, tuple[str, ...]]]]:
    """Each listed way's (box or None for the whole way, kinds). A street whose cross
    street is not found is logged and left out, never guessed."""
    by_name: dict[str, list] = defaultdict(list)
    for way in ways:
        if way.name:
            by_name[way.name].append(way)
    out: dict[int, list[tuple[Box | None, tuple[str, ...]]]] = defaultdict(list)
    for entry in entries:
        for way_id in entry.ways:
            out[way_id].append((None, entry.kinds))
        if not entry.street or not entry.between:
            continue
        street = by_name.get(entry.street, [])
        ends = [_junction(street, by_name.get(cross, [])) for cross in entry.between]
        if not street or None in ends:
            logger.warning(
                "hazard list %s: %s between %s and %s not found in the extract; left out",
                entry.id,
                entry.street,
                *entry.between,
            )
            continue
        box = _box(ends[0], ends[1], BETWEEN_MARGIN_M)  # type: ignore[arg-type]
        for way in street:
            out[way.osm_id].append((box, entry.kinds))
    return dict(out)


def _in(box: Box, point: Sequence[float]) -> bool:
    return box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]


def _middle(piece: Sequence[tuple[float, float]]) -> tuple[float, float]:
    return (sum(p[0] for p in piece) / len(piece), sum(p[1] for p in piece) / len(piece))


def piece_hazard(
    tags: Mapping[str, str],
    on_rails: bool,
    listed: Sequence[tuple[Box | None, tuple[str, ...]]],
    piece: Sequence[tuple[float, float]],
) -> str | None:
    """`segment.hazard` for one piece of a way."""
    osm = hazards.way_kinds(tags)
    if on_rails:
        osm.add(hazards.RAILS)
    hand: set[str] = set()
    if listed:
        middle = _middle(piece)
        for box, kinds in listed:
            # Its middle in the box, or half its vertices: a long piece the box covers half of.
            inside = sum(_in(box, p) for p in piece) if box is not None else 0
            if box is None or _in(box, middle) or inside * 2 >= len(piece):
                hand.update(kinds)
    return hazards.encode(osm, hand)


def way_has_hazard(
    way, on_rails: bool, listed: Sequence[tuple[Box | None, tuple[str, ...]]]
) -> bool:
    """Whether any piece of the way has a hazard: what the graph prices (`rm:hazard`)."""
    if on_rails or hazards.way_kinds(way.tags):
        return True
    if not listed:
        return False
    # Or any vertex inside a box but the way's two ends: an edge the street's listed stretch
    # runs along is priced, one that only meets it at a junction is not.
    inner = way.coordinates[1:-1]
    if any(box is not None and any(_in(box, p) for p in inner) for box, _ in listed):
        return True
    return any(piece_hazard({}, False, listed, piece) for _, piece in extract.iter_segments(way))
