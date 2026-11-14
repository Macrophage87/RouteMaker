"""DDOT's completed bike lane projects: the project's own record, where the District's
street record and OSM disagree about a bike facility.

The owner, 2026-11-13: "When there's a mismatch in data, we search for the project's own
data." DDOT's Bike Lane Projects site (https://bikelanes.ddot.dc.gov/) lists every bikeway
it installed, by year, street and block range, from 2020 (the year of its old LTS layer) to
2026. The Roadway Block layer has no date per field, so where a block records no facility on
a street DDOT says it built one, the block is the stale source: OSM's painted lane stands
there (`agency_roads.overlay`, row A).

The file lists each project with the OSM ways its block range covered on the 2026-11-11
map. Pure apart from reading that file.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

PROJECTS_FILE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "ddot-projects" / "completed-bikeways.json"
)


@cache
def project_lane_ways(path: Path = PROJECTS_FILE) -> frozenset[int]:
    """The ways inside a completed DDOT bikeway project; empty where the file is absent."""
    if not path.exists():
        return frozenset()
    data = json.loads(path.read_text())
    return frozenset(int(way) for project in data["projects"] for way in project["ways"])
