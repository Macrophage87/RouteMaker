"""The land managers' trail-use records onto the ways (`routemaker.trail_uses`).

`<reference>/trail-uses.json`, one row per line, `{"id", "source", "uses", "name",
"site", "coordinates"}`, written by `scripts/install_reference_data.py
--fl-trail-uses`. Optional: without it no trail is opened this way, and the load logs
that it is absent. A way that lies along a biking trail's line (`conflation.
conflate_blocks`, the street blocks' geometry rules, with no name veto: the layer names
the trail, OSM names its segments) and that OSM is silent about for bicycles is given
`bicycle=yes` before the trail rules run, so it rides and is drawn like any trail OSM
opens itself.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from pathlib import Path

from routemaker import agency_roads, trail_uses

from . import conflation

logger = logging.getLogger(__name__)

FILE_NAME = "trail-uses.json"


class TrailUsesInvalid(ValueError):
    """The installed file names a source the rebuild does not know, or a row is incomplete."""


def load(path: Path) -> tuple[conflation.RoadFeature, ...]:
    if not path.exists():
        logger.warning(
            "%s is absent, so no land manager's trail-use record is read: trails OSM is "
            "silent about keep the trail rules' reading. Install it with "
            "scripts/install_reference_data.py --fl-trail-uses",
            path,
        )
        return ()
    features = []
    for row in json.loads(path.read_text()):
        missing = [key for key in ("id", "source", "coordinates") if key not in row]
        if missing:
            raise TrailUsesInvalid(f"{path}: record {row.get('id')!r}: no {', '.join(missing)}")
        if row["source"] not in trail_uses.SOURCES:
            raise TrailUsesInvalid(f"{path}: record {row['id']}: unknown source {row['source']!r}")
        features.append(
            conflation.RoadFeature(
                feature_id=row["id"],
                coordinates=[tuple(c) for c in row["coordinates"]],
                facts=agency_roads.RoadFacts(agency=row["source"], name=row.get("name")),
            )
        )
    return tuple(features)


def open_listed(ways: Sequence, features: Sequence[conflation.RoadFeature]) -> dict[int, str]:
    """Give `bicycle=yes` to each silent trail way a biking record lies along; the ways
    opened, with the record's source."""
    if not features:
        return {}
    entries = [(way.osm_id, way.coordinates, False) for way in trail_uses.candidates(ways)]
    result = conflation.conflate_blocks(entries, features, None)
    source_of = {feature.feature_id: feature.facts.agency for feature in features}
    by_id = {way.osm_id: way for way in ways}
    opened: dict[int, str] = {}
    for way_id, shares in result.matched.items():
        source = source_of[shares[0].feature_id]
        way = by_id[way_id]
        way.tags["bicycle"] = "yes"
        opened[way_id] = source
    logger.info(
        "trail-use records: %d of %d lines matched, %d silent trail ways opened to bicycles",
        len(features) - len(result.unmatched_features),
        len(features),
        len(opened),
    )
    return opened
