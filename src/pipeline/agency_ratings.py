"""Agency bicycle stress layers onto the ways they rate (`routemaker.agency_lts`).

The installed file is `<reference>/agency-lts.json`: one row per agency record,
`{"id", "agency", "level", "name", "coordinates"}`, the level already on our scale
(1 to 5 in half steps; an agency's "no rating" dropped by the installer). It is
optional: without it every way keeps the classifier's tier, as every rebuild did
before v0.7.0, and the load logs that it is absent.

Each agency is matched on its own, with the street blocks' matching rules
(`conflation.conflate_blocks`; a service or track way needs an agreeing name, a
differently named record is vetoed), so a county's record and the state's record
for one road do not compete for it: the way takes one level from each, the level
of the record it lies along most, and `agency_lts.chosen` picks between them.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

from routemaker import agency_roads
from routemaker.agency_lts import AGENCIES, AgencyRating, level_problem

from . import conflation

logger = logging.getLogger(__name__)

FILE_NAME = "agency-lts.json"


class AgencyRatingsInvalid(ValueError):
    """The installed file names an agency or a level the rebuild may not use."""


def load(path: Path) -> tuple[tuple[conflation.RoadFeature, ...], dict[str, AgencyRating]]:
    """The records as features, and each record's rating by feature id."""
    if not path.exists():
        logger.warning(
            "%s is absent, so no agency stress rating is used: every way keeps the "
            "classifier's tier (the owner's order, 2026-10-13: owner, then local "
            "government, then the formula)",
            path,
        )
        return (), {}
    features, ratings = [], {}
    for row in json.loads(path.read_text()):
        agency, level = row["agency"], float(row["level"])
        if agency not in AGENCIES:
            # Arlington's and Alexandria's layers are internal-only and are refused
            # here as well as by the installer (OWNER-DECISIONS 152, 153, 155).
            raise AgencyRatingsInvalid(f"{path}: record {row['id']}: unknown agency {agency!r}")
        problem = level_problem(level)
        if problem:
            raise AgencyRatingsInvalid(f"{path}: record {row['id']}: {problem}")
        features.append(
            conflation.RoadFeature(
                feature_id=row["id"],
                coordinates=[tuple(c) for c in row["coordinates"]],
                facts=agency_roads.RoadFacts(agency=agency, name=row.get("name")),
            )
        )
        ratings[row["id"]] = AgencyRating(agency, level)
    return tuple(features), ratings


def ratings_by_way(
    ways: Sequence,
    entries: Sequence[conflation.WayEntry],
    features: Sequence[conflation.RoadFeature],
    ratings: dict[str, AgencyRating],
) -> dict[int, tuple[AgencyRating, ...]]:
    """Each way's ratings, at most one per agency."""
    unbuilt = {
        way.osm_id for way in ways if way.tags.get("highway") in agency_roads.UNBUILT_HIGHWAYS
    }
    entries = [entry for entry in entries if entry[0] not in unbuilt]
    names = {way.osm_id: way.name for way in ways}
    required = {
        way.osm_id for way in ways if way.tags.get("highway") in agency_roads.NAME_REQUIRED_HIGHWAYS
    }
    free = {
        way.osm_id for way in ways if way.tags.get("highway") in agency_roads.NAME_FREE_HIGHWAYS
    }
    by_agency: dict[str, list[conflation.RoadFeature]] = defaultdict(list)
    for feature in features:
        by_agency[ratings[feature.feature_id].agency].append(feature)
    found: dict[int, list[AgencyRating]] = defaultdict(list)
    for agency, own in sorted(by_agency.items()):
        result = conflation.conflate_blocks(
            entries, own, names, name_required=required, name_free=free
        )
        for way_id, shares in result.matched.items():
            # The record the way lies along most (`conflate_blocks` orders them).
            found[way_id].append(ratings[shares[0].feature_id])
        logger.info(
            "agency stress ratings: %s, %d of %d records matched, %d ways",
            agency,
            len(own) - len(result.unmatched_features),
            len(own),
            len(result.matched),
        )
    return {way_id: tuple(found_) for way_id, found_ in found.items()}
