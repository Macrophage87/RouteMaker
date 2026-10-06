"""Curated bike lanes: a painted lane the map is missing, read at classify time.

OWNER-DECISIONS 433, of Veirs Mill Road (MD 586) from Twinbrook Parkway east to
about 77.088 W: "Yes, it should be marked" (the wide painted bike lane), and "It's
not an avoid. It might not be great, but it's not that bad." OSM tags no
`cycleway*` key on any Veirs Mill carriageway (VEIRS-MILL-lane-side), so the
classifier had no lane to credit, and Montgomery Planning's LTS 5 rows pinned the
stretch at Avoid until 433 retired them.

Why a checked-in file and not an override row, as for the curated speeds
(`routemaker.speed_corrections`): an access override is applied after
classification, and may not write a `cycleway` key, and a stress row writes a
tier where the owner's answer is a facility and the tier should follow from it by
the same tables as every other road. So the lane is a reviewed file under
`fixtures/bike_lanes/`: a row per way, the side (`right`, the kerb side of a
one-way carriageway; `left`; or `both`), and the owner's words and the map
evidence. It adds `cycleway:<side>=lane` to the tags the classifier and the
facility class read, never to the graph's tags.

A row fills a gap and never overrules the map: a way that now carries any
`cycleway` key of its own (the owner's OSM edit, once it is in the extract) is
read as OSM has it, and the row is reported as unused.

The owner's own reading of the lane is kept over the tables' (`owner_tier`): "about
LTS 3 at 35-40 mph with 2 lanes, LTS 4 at 45 mph or 3+ lanes" (433), and of the 3- and
4-lane Veirs Mill carriageways, "LTS4. Bikeable, but problematic." (437.4). Furth's
table gives a painted lane LTS 3 at 35 mph whatever the lane count, so a curated lane
on three or more through lanes a direction, or at 45 mph and more, is held at LTS 4.
Only on a way a row's lane was used: the classifier's tables are unchanged elsewhere.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from .stress import Stress, StressResult
from .tags import lanes_per_direction

BIKE_LANES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "bike_lanes"
SIDES = ("right", "left", "both")


class BikeLaneRefused(ValueError):
    """A bike-lane file is malformed, or two rows disagree about one way."""


def load(directory: Path | None = None) -> dict[int, str]:
    """{way id: side} from every file in `directory` (BIKE_LANES_DIR)."""
    sides: dict[int, str] = {}
    for path in sorted(Path(directory or BIKE_LANES_DIR).glob("*.json")):
        document = json.loads(path.read_text())
        if not isinstance(document, dict) or document.get("version") != 1:
            raise BikeLaneRefused(f"{path.name} is not a version 1 bike-lane file")
        rows = document.get("rows")
        if not isinstance(rows, list) or not rows:
            raise BikeLaneRefused(f"{path.name} has no rows")
        for index, row in enumerate(rows):
            where = f"{path.name} row {index}"
            way = row.get("osm_way_id") if isinstance(row, dict) else None
            if not isinstance(way, int) or isinstance(way, bool) or way <= 0:
                raise BikeLaneRefused(f"{where}: osm_way_id must be a positive integer")
            side = row.get("side")
            if side not in SIDES:
                raise BikeLaneRefused(f"{where}: side must be one of {list(SIDES)}")
            for field in ("reason", "evidence"):
                if not isinstance(row.get(field), str) or not row[field].strip():
                    raise BikeLaneRefused(f"{where}: {field} is required")
            if sides.get(way, side) != side:
                raise BikeLaneRefused(f"{where}: way {way} is also given a lane on {sides[way]}")
            sides[way] = side
    return sides


def corrected(tags: dict[str, str], side: str | None) -> tuple[dict[str, str], bool]:
    """The tags the classifier reads, and whether the row was used. Any `cycleway`
    key on the way wins."""
    if side is None or any(key == "cycleway" or key.startswith("cycleway:") for key in tags):
        return tags, False
    return {**tags, f"cycleway:{side}": "lane"}, True


# The owner's reading of a curated lane (433, 437.4): LTS 4 from this many through
# lanes a direction, or from this speed.
OWNER_LTS4_LANES = 3
OWNER_LTS4_MPH = 45.0


def owner_tier(result: StressResult, tags: dict[str, str]) -> StressResult:
    """The classifier's result for a way a curated lane was used on, held at LTS 4
    on three or more through lanes a direction or at 45 mph and more (437.4)."""
    lanes = lanes_per_direction(tags) or 0
    speed = result.speed_mph or 0.0
    if result.tier >= Stress.LTS4 or (lanes < OWNER_LTS4_LANES and speed < OWNER_LTS4_MPH):
        return result
    why = f"{lanes} lanes" if lanes >= OWNER_LTS4_LANES else f"{speed:g} mph"
    return replace(
        result,
        tier=Stress.LTS4,
        rule=f"{result.rule}; curated lane at {why}: LTS 4 (OWNER-DECISIONS 433, 437.4)",
    )
