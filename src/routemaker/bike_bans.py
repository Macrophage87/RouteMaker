"""The ways in the District a bicycle is kept off, listed for the owner's Review.

The owner, 2026-10-17: "Add to the review map places you think that bikes are not
allowed in DC. I think there's quite a lot of ones that are actually allowed. They
are regularly used by bicycle police and outside of special events have no issues
riding on them."

The rebuild writes `dc-bike-bans.csv` (`report_csv`), which Review reads as its
"DC no-bike ways" queue (`core.stress_review.FILE_QUEUES`). Keep closed is recorded only;
Reopen is an approved `bicycle=yes` access override, in force from the next rebuild,
as for the industrial-area closures. Nothing here closes or opens a way.

Listed, for a way whose midpoint is inside the District (`inside`):

- a closure rule's reason (`rm:no_bicycle`: the trail rules, the Zoo, a long dismount
  connector, a secured or military area, ...), except the CBD's sidewalks, which are
  District law the owner set (OWNER-DECISIONS 104), and the industrial-area closures,
  which Review lists already;
- OSM's own `bicycle=no` on any way but a motorway;
- a footway, pedestrian way or bridleway with no bicycle tag, which Valhalla closes by
  class, where it lies inside a park (`in_park`); sidewalks and crossings are left to
  the streets they belong to, and ways with a closed `access` are not public.

A way no rule closes and that carries a bicycle grant is never listed.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .cbd import NO_BICYCLE as CBD_SIDEWALK
from .cbd import Polygon, in_polygons, is_sidewalk, midpoint

REPORT_NAME = "dc-bike-bans.csv"
DC_BOUNDARY = Path(__file__).resolve().parents[1] / "core" / "geodata" / "dc-boundary.geojson"

CLASS_CLOSED_HIGHWAY = frozenset({"footway", "pedestrian", "bridleway"})
MOTORWAY = frozenset({"motorway", "motorway_link"})
CLOSED_ACCESS = frozenset({"no", "private", "permit", "customers", "restricted"})
NOT_LISTED_FOOTWAY = frozenset({"crossing", "traffic_island", "access_aisle"})
# The CBD's sidewalks are District law the owner set (104); an industrial-area closure
# has its own queue already. The Zoo, military and secured areas close a way whatever
# its own tags say (`restricted_areas`, `zoo.closed_way`), so a Reopen there, a
# `bicycle=yes` override, would change nothing: they are not listed.
UNLISTED_REASONS = frozenset({CBD_SIDEWALK, "works", "zoo", "military", "secured"})

# What the Review card says for each reason; an unknown reason is shown as its code.
WHY = {
    "bicycle_no": "OSM: bicycle=no",
    "footway": "A footway with no bicycle tag (closed by default)",
    "private": "Private or permit access",
    "sac_scale": "Rated as a hiking trail",
    "informal": "An informal path",
    "foot_designated": "A path signed for walkers",
    "trail_visibility": "A faint trail",
    "hiking_route": "Part of a hiking route",
    "natural_surface": "A natural-surface path",
    "park_path": "A park path with no surface or bicycle tag",
    "mtb": "A mountain-bike trail",
    "singletrack": "Rated singletrack",
    "dismount": "A long walk-your-bike connector",
}


@dataclass(frozen=True)
class Listed:
    way_id: int
    highway: str
    name: str
    length_m: float
    reason: str


@lru_cache(maxsize=1)
def dc_polygons() -> list[Polygon]:
    geometry = json.loads(DC_BOUNDARY.read_text())["geometry"]
    parts = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    return [[[(float(x), float(y)) for x, y, *_ in ring] for ring in part] for part in parts]


def inside(coords: Sequence[tuple[float, float]], polygons: list[Polygon] | None = None) -> bool:
    return bool(coords) and in_polygons(midpoint(coords), polygons or dc_polygons())


def reason(tags: dict[str, str], no_bicycle: str | None, in_park: bool) -> str | None:
    """Why the way is listed, or None (see the module docstring); the place is not asked."""
    if no_bicycle is not None:
        return None if no_bicycle in UNLISTED_REASONS else no_bicycle
    highway = tags.get("highway")
    bicycle = tags.get("bicycle")
    if bicycle == "no":
        return None if highway in MOTORWAY else "bicycle_no"
    if (
        bicycle is None
        and in_park
        and highway in CLASS_CLOSED_HIGHWAY
        and tags.get("access") not in CLOSED_ACCESS
        and not is_sidewalk(tags)
        and tags.get("footway") not in NOT_LISTED_FOOTWAY
    ):
        return "footway"
    return None


def report_csv(rows: Iterable[Listed]) -> str:
    """The report Review reads: one row a way, the longest first."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["way_id", "highway", "name", "length_m", "status", "reason", "why"])
    for row in sorted(rows, key=lambda r: (-r.length_m, r.way_id)):
        writer.writerow(
            [
                row.way_id,
                row.highway,
                row.name,
                f"{row.length_m:.1f}",
                "closed",
                row.reason,
                WHY.get(row.reason, row.reason),
            ]
        )
    return out.getvalue()
