"""Scenic designations onto the ways they cover (v0.8.0; `routemaker.scenic`).

Three inputs, one column (`segment.scenic`, the designations in words):

- the installed agency lines, `<reference>/scenic.json`: one row per record,
  `{"id", "source", "label", "name", "coordinates"}`, written by
  `scripts/install_reference_data.py --rustic-roads / --scenic-byways`. Optional:
  without it no agency designation is read, and the load logs that it is absent.
  Each source is matched on its own with the street blocks' rules
  (`conflation.conflate_blocks`: never a trail, a service or track way only where
  the record's road name agrees), so a byway and a rustic road on one road both
  reach it.
- the OSM bicycle route relations of the extract: the East Coast Greenway and the
  US Bicycle Routes (`read_routes`), a section relation taking its parent's name.
- the way's own tags: a covered bridge (`bridge=covered`).

A designation never changes a way's stress or its routing: this module's output is
written beside the tier and read by the map and the road panel alone.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

import osmium

from routemaker import agency_roads, scenic

from . import conflation

logger = logging.getLogger(__name__)

FILE_NAME = "scenic.json"

# A byway record names its byway, not its road, so the street blocks' name veto never
# applies to it. Two guards take its place: only the through-road classes a byway runs on
# may take one (a parallel residential street, a ramp, a service road or a track never
# does), and the record must cover most of the way (BYWAY_MIN_COVERAGE, not the blocks'
# half), so a short connector that only touches it does not. An unclassified road beside a
# byway, within MAX_SEPARATION_M and on its bearing, could still take it: rare in the
# byways' rural country, and only words in the panel, never a stress change.
BYWAY_HIGHWAYS = frozenset({"trunk", "primary", "secondary", "tertiary", "unclassified"})
BYWAY_MIN_COVERAGE = 0.7


class ScenicLayerInvalid(ValueError):
    """The installed file names a source or a designation the rebuild does not know."""


def load(path: Path) -> tuple[tuple[conflation.RoadFeature, ...], dict[str, str]]:
    """The records as features, and each record's designation by feature id."""
    if not path.exists():
        logger.warning(
            "%s is absent, so no agency scenic designation is read (Montgomery County "
            "Rustic Roads, Maryland Scenic Byways): the Scenic layer shows the OSM routes "
            "and covered bridges only. Install it with scripts/install_reference_data.py "
            "--rustic-roads / --scenic-byways",
            path,
        )
        return (), {}
    features, labels = [], {}
    for row in json.loads(path.read_text()):
        missing = [key for key in ("id", "source", "label", "coordinates") if key not in row]
        if missing:
            raise ScenicLayerInvalid(f"{path}: record {row.get('id')!r}: no {', '.join(missing)}")
        source, label = row["source"], row["label"]
        if source not in scenic.SOURCES:
            raise ScenicLayerInvalid(f"{path}: record {row['id']}: unknown source {source!r}")
        if not isinstance(label, str) or not label.strip():
            raise ScenicLayerInvalid(f"{path}: record {row['id']}: no designation")
        features.append(
            conflation.RoadFeature(
                feature_id=row["id"],
                coordinates=[tuple(c) for c in row["coordinates"]],
                facts=agency_roads.RoadFacts(agency=source, name=row.get("name")),
            )
        )
        labels[row["id"]] = label
    return tuple(features), labels


def labels_by_way(
    ways: Sequence,
    features: Sequence[conflation.RoadFeature],
    labels: Mapping[str, str],
    trail_ways: frozenset[int] = frozenset(),
) -> dict[int, set[str]]:
    """Each way's agency designations: every record of each source it lies along."""
    if not features:
        return {}
    entries = [
        (way.osm_id, way.coordinates, way.osm_id in trail_ways)
        for way in ways
        if way.tags.get("highway") not in agency_roads.UNBUILT_HIGHWAYS
    ]
    names = {way.osm_id: way.name for way in ways}
    required = {
        way.osm_id for way in ways if way.tags.get("highway") in agency_roads.NAME_REQUIRED_HIGHWAYS
    }
    free = {
        way.osm_id for way in ways if way.tags.get("highway") in agency_roads.NAME_FREE_HIGHWAYS
    }
    by_source: dict[str, list[conflation.RoadFeature]] = defaultdict(list)
    for feature in features:
        by_source[feature.facts.agency].append(feature)
    found: dict[int, set[str]] = defaultdict(set)
    through_roads = {way.osm_id for way in ways if way.tags.get("highway") in BYWAY_HIGHWAYS}
    byway_entries = [entry for entry in entries if entry[0] in through_roads]
    for source, own in sorted(by_source.items()):
        byway = source == scenic.MD_BYWAY_SOURCE
        result = conflation.conflate_blocks(
            byway_entries if byway else entries,
            own,
            names,
            name_required=required,
            name_free=free,
            min_coverage=BYWAY_MIN_COVERAGE if byway else conflation.MIN_BLOCK_COVERAGE,
        )
        for way_id, shares in result.matched.items():
            found[way_id].update(labels[share.feature_id] for share in shares)
        logger.info(
            "scenic designations: %s, %d of %d records matched, %d ways",
            source,
            len(own) - len(result.unmatched_features),
            len(own),
            len(result.matched),
        )
    return dict(found)


class _Routes(osmium.SimpleHandler):
    """Every bicycle route relation's own designation, its ways and its child relations."""

    def __init__(self) -> None:
        super().__init__()
        self.labels: dict[int, str] = {}
        self.ways: dict[int, list[int]] = {}
        self.children: dict[int, list[int]] = {}

    def relation(self, r) -> None:  # noqa: N802 - osmium's callback name
        tags = {tag.k: tag.v for tag in r.tags}
        if "bicycle" not in {part.strip() for part in (tags.get("route") or "").split(";")}:
            return
        label = scenic.route_label(r.id, tags)
        if label:
            self.labels[r.id] = label
        self.ways[r.id] = [m.ref for m in r.members if m.type == "w"]
        self.children[r.id] = [m.ref for m in r.members if m.type == "r"]


def route_labels(
    labels: Mapping[int, str],
    ways: Mapping[int, Sequence[int]],
    children: Mapping[int, Sequence[int]],
) -> dict[int, set[str]]:
    """Each way's route designations: of every relation it is in, and of every relation
    above that one (a state section of the Greenway is the Greenway), cycles cut."""
    found: dict[int, set[str]] = defaultdict(set)
    for root, label in labels.items():
        seen: set[int] = set()
        stack = [root]
        while stack:
            relation = stack.pop()
            if relation in seen:
                continue
            seen.add(relation)
            for way_id in ways.get(relation, ()):
                found[way_id].add(label)
            stack.extend(children.get(relation, ()))
    return dict(found)


def read_routes(pbf: str | Path) -> dict[int, set[str]]:
    """The East Coast Greenway and US Bicycle Route designations of every way, by way id."""
    handler = _Routes()
    handler.apply_file(str(pbf))
    return route_labels(handler.labels, handler.ways, handler.children)


def scenic_by_way(
    ways: Sequence,
    agency: Mapping[int, set[str]],
    routes: Mapping[int, set[str]],
) -> dict[int, str]:
    """Each designated way's words for `segment.scenic`; a way with none is left out."""
    out: dict[int, str] = {}
    for way in ways:
        text = scenic.phrase(
            [
                *agency.get(way.osm_id, ()),
                *routes.get(way.osm_id, ()),
                scenic.covered_bridge_label(way.tags),
            ]
        )
        if text:
            out[way.osm_id] = text
    return out
