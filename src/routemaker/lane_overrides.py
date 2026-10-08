"""Lane overrides: owner-known lane counts where the District's Roadway Block is stale.

OWNER-DECISIONS 412 (with 405, 413, 414). Connecticut Avenue NW north of Calvert St has
three travel lanes each way today ("Connect is 3 but one is sometimes used for parking,
though double and even triple parking also happens."): the old reversible lanes became
ordinary lanes, so DC's 1 + 1 plus 2 reversible is out of date. Each override is a
reviewed entry in `fixtures/lane_overrides/`, with the owner's words as its source.

It is applied to a District block as the blocks are loaded (`pipeline.run`), where the
block's own geometry is known: the block's street name matches and its middle is at or
north of `north_of_lat`. The block then reads `travel_lanes_per_direction` lanes each
way (never fewer than DC records), no reversible lanes (405's zero still holds
everywhere else), and `part_time_parking_lanes` per direction: the classifier and
crossing stress count all the lanes, the Mass Ride width (`routemaker.massflow`) leaves
the part-time parking lane out. Double and triple parking is a known hazard, not modelled.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from .agency_roads import RoadFacts

LANE_OVERRIDES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "lane_overrides"


class LaneOverrideRefused(ValueError):
    """A lane-override file that is wrong, or a folder that is missing."""


@dataclass(frozen=True)
class LaneOverride:
    id: str
    agency: str
    street: str
    north_of_lat: float
    travel_lanes_per_direction: int
    part_time_parking_lanes_per_direction: int
    source: str

    def covers(self, facts: RoadFacts, coordinates: Sequence[Sequence[float]]) -> bool:
        if facts.agency != self.agency or (facts.name or "").strip().upper() != self.street:
            return False
        if not coordinates:
            return False
        middle = sum(point[1] for point in coordinates) / len(coordinates)
        return middle >= self.north_of_lat

    def apply(self, facts: RoadFacts) -> RoadFacts:
        lanes = {k: v for k, v in facts.lanes.items() if k != "reversible"}
        for label in ("ib", "ob"):
            lanes[label] = max(lanes.get(label, 0), self.travel_lanes_per_direction)
        lanes.pop("total", None)
        return replace(
            facts,
            lanes=lanes,
            part_time_parking_lanes=self.part_time_parking_lanes_per_direction,
        )


def parse(document: dict, name: str = "lane override file") -> list[LaneOverride]:
    out = []
    for entry in document.get("overrides", []):
        try:
            override = LaneOverride(
                id=entry["id"],
                agency=entry["agency"],
                street=entry["street"].strip().upper(),
                north_of_lat=float(entry["north_of_lat"]),
                travel_lanes_per_direction=int(entry["travel_lanes_per_direction"]),
                part_time_parking_lanes_per_direction=int(
                    entry.get("part_time_parking_lanes_per_direction", 0)
                ),
                source=entry["source"],
            )
        except (KeyError, TypeError, ValueError) as error:
            raise LaneOverrideRefused(f"{name}: a bad entry ({error!r})") from error
        if not 1 <= override.travel_lanes_per_direction <= 8 or not override.source.strip():
            raise LaneOverrideRefused(f"{name}: {override.id} needs 1-8 lanes and a source")
        if not (
            0
            <= override.part_time_parking_lanes_per_direction
            < override.travel_lanes_per_direction
        ):
            raise LaneOverrideRefused(f"{name}: {override.id} parking lanes out of range")
        out.append(override)
    return out


def load(directory: Path | str | None = None) -> list[LaneOverride]:
    """Every override in every file of the folder. A missing folder is refused (the
    pipeline image copies `fixtures/`), as for the named corridors."""
    folder = Path(directory or LANE_OVERRIDES_DIR)
    if not folder.is_dir():
        raise LaneOverrideRefused(
            f"the lane-override folder {folder} does not exist; OWNER-DECISIONS 412 would be lost"
        )
    overrides: list[LaneOverride] = []
    for path in sorted(folder.glob("*.json")):
        overrides.extend(parse(json.loads(path.read_text()), path.name))
    ids = [o.id for o in overrides]
    if len(set(ids)) != len(ids):
        raise LaneOverrideRefused("lane override ids must be unique across files")
    return overrides


def apply(
    facts: RoadFacts,
    coordinates: Sequence[Sequence[float]],
    overrides: Iterable[LaneOverride],
) -> RoadFacts:
    """The block's facts with the first override that covers it applied."""
    for override in overrides:
        if override.covers(facts, coordinates):
            return override.apply(facts)
    return facts
