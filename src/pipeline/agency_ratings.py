"""Agency bicycle stress layers onto the ways they rate (`routemaker.agency_lts`).

The installed file is `<reference>/agency-lts.json`: one row per agency record,
`{"id", "agency", "level", "name", "coordinates"}`, the level already on our scale
(1 to 5 in half steps; an agency's "no rating" dropped by the installer).
`scripts/install_agency_lts.py` writes it.

The weekly rebuild requires it (`required=True`): a file that is absent or empty, or
that lacks an agency of `agency_lts.AGENCIES`, is refused (`AgencyRatingsMissing`).
v0.8.0 was built on a host where it had never been installed, the absence was only
logged, and no road carried an agency's rating (found 2026-10-17).
`REBUILD_ALLOW_NO_AGENCY_LTS=1` turns the refusal back into a warning, for a rebuild
that knowingly goes without; tests and other callers pass `required=False`.

Each agency is matched on its own, with the street blocks' matching rules
(`conflation.conflate_blocks`; a service or track way needs an agreeing name, a
differently named record is vetoed), so a county's record and the state's record
for one road do not compete for it: the way takes one level from each, the level
of the record it lies along most, and `agency_lts.chosen` picks between them.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from routemaker import agency_roads, facility
from routemaker.agency_lts import (
    AGENCIES,
    PROHIBITED_NO_BICYCLE,
    AgencyRating,
    level_problem,
    prohibiting,
)
from routemaker.classes import TRAIL_CLASS_HIGHWAY

from . import conflation

logger = logging.getLogger(__name__)

FILE_NAME = "agency-lts.json"


class AgencyRatingsInvalid(ValueError):
    """The installed file names an agency or a level the rebuild may not use."""


class AgencyRatingsMissing(FileNotFoundError):
    """The installed file is absent or empty, or lacks an approved agency."""


INSTALL = (
    "scripts/install_agency_lts.py --datasets <DATA_ROOT>/datasets --out "
    "<DATA_ROOT>/reference/agency-lts.json moco ddot mdot-sha (docs/OPERATIONS.md, "
    '"Agency stress ratings (agency-lts.json)"), or set REBUILD_ALLOW_NO_AGENCY_LTS=1 to '
    "build without them"
)


def missing_agencies(rows: list[dict]) -> list[str]:
    """The agencies of `AGENCIES` with no record in the file's rows."""
    held = {row.get("agency") for row in rows}
    return sorted(agency for agency in AGENCIES if agency not in held)


def load(
    path: Path, *, required: bool = False
) -> tuple[tuple[conflation.RoadFeature, ...], dict[str, AgencyRating]]:
    """The records as features, and each record's rating by feature id.

    With `required`, an absent or empty file, or one without every agency of
    `AGENCIES`, raises `AgencyRatingsMissing`; without it, each is logged."""
    if not path.exists():
        if required:
            raise AgencyRatingsMissing(
                f"{path} is absent, so no road would carry an agency's stress rating; "
                f"refused. Install it: {INSTALL}"
            )
        logger.warning(
            "%s is absent, so no agency stress rating is used: every way keeps the "
            "classifier's tier (the owner's order, 2026-10-13: owner, then local "
            "government, then the formula)",
            path,
        )
        return (), {}
    rows = json.loads(path.read_text())
    missing = missing_agencies(rows)
    if missing:
        what = "is empty" if not rows else "has no record from " + ", ".join(missing)
        if required:
            raise AgencyRatingsMissing(
                f"{path} {what}, so those roads would keep the formula's tier; refused. "
                f"Reinstall it: {INSTALL}"
            )
        logger.warning("%s %s: those roads keep the formula's tier", path, what)
    features, ratings = [], {}
    for row in rows:
        agency, level = row["agency"], float(row["level"])
        if agency not in AGENCIES:
            # Arlington's layer is internal-only and is refused here as well as by
            # the installer (OWNER-DECISIONS 152, 155). Alexandria publishes no
            # rating (`agency_lts.AGENCIES`), so a row naming it is refused too.
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


def prohibited_ways(rated: Mapping[int, Sequence[AgencyRating]]) -> set[int]:
    """The ways an agency says bicycles may not use (`agency_lts.prohibiting`), whatever
    level the map takes for them."""
    return {way_id for way_id, ratings in rated.items() if prohibiting(ratings) is not None}


# A path is never closed by a road record matched onto it: MDOT SHA rates roads, so its
# 5 on a trail-class way (or a track) is more likely a conflation slip than a ban, and it
# is listed for the owner instead (the owner's rule: unclear bike access is closed, but a
# path is not made unclear by a road layer).
NOT_CLOSED_HIGHWAY = TRAIL_CLASS_HIGHWAY | {"track"}

PROHIBITED_REPORT_NAME = "agency-prohibited.csv"
PROHIBITED_COLUMNS = ("way_id", "highway", "name", "bicycle", "length_m", "outcome")
CLOSED = "closed"
CLOSED_OSM_OPEN = "closed; OpenStreetMap says bicycles are allowed"
NOT_CLOSED_PATH = "not closed: a path or track, check the match"
NOT_CLOSED_OVERRIDE = "not closed: an owner override opens it"


@dataclass(frozen=True)
class ProhibitedRow:
    way_id: int
    highway: str
    name: str
    bicycle: str
    length_m: float
    outcome: str


def prohibited_closures(
    ways: Iterable,
    prohibited: Collection[int],
    reasons: Mapping[int, str],
    reopened: Collection[int],
) -> tuple[dict[int, str], list[ProhibitedRow]]:
    """The `rm:no_bicycle` reasons the agencies' prohibitions add, and the report's rows.

    A way of `prohibited` is closed (`PROHIBITED_NO_BICYCLE`) when nothing closes it
    already: no closure rule's reason in `reasons`, and its own tags leave it on the map
    as a way to ride (`facility.map_class`; a freeway, `bicycle=no` or a private road
    keeps its own reason). Not closed, and listed: a path or track
    (`NOT_CLOSED_HIGHWAY`), and a way an approved access override wrote a bicycle key on
    (`reopened`: the owner's Review call outranks the agency). Closed and listed with a
    note: a way OpenStreetMap tags as open to bicycles. Every closed way is listed, so the
    owner sees each road the rule takes off the map."""
    added: dict[int, str] = {}
    rows: list[ProhibitedRow] = []
    for way in ways:
        if way.osm_id not in prohibited or way.osm_id in reasons:
            continue
        tags = way.tags
        highway = tags.get("highway", "")
        if highway in NOT_CLOSED_HIGHWAY:
            outcome = NOT_CLOSED_PATH
        elif way.osm_id in reopened:
            outcome = NOT_CLOSED_OVERRIDE
        elif facility.map_class(tags) not in (facility.MapClass.ROAD, facility.MapClass.ALLEY):
            continue
        else:
            added[way.osm_id] = PROHIBITED_NO_BICYCLE
            outcome = CLOSED_OSM_OPEN if tags.get("bicycle") in facility.BICYCLE_ALLOWED else CLOSED
        rows.append(
            ProhibitedRow(
                way.osm_id,
                highway,
                tags.get("name", ""),
                tags.get("bicycle", ""),
                facility._length_m(way.coordinates),
                outcome,
            )
        )
    return added, rows


def prohibited_report_csv(rows: Iterable[ProhibitedRow]) -> str:
    """`PROHIBITED_REPORT_NAME`, ordered by way."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(PROHIBITED_COLUMNS)
    for row in sorted(rows, key=lambda r: r.way_id):
        writer.writerow(
            [row.way_id, row.highway, row.name, row.bicycle, f"{row.length_m:.0f}", row.outcome]
        )
    return out.getvalue()
