"""Climbs taken off the Climbs layer and out of the hill seek by hand, by climb id.

The owner, 2026-10-12: "A marked climb appears to be a quarry, which isn't likely open to the
public. Ensure only public roads open to bikes are marked." The rule that keeps such a climb out
for good is the rebuild's (release v0.7.0 closes the ways inside a quarry, a landfill or an
industrial area, so they leave the map, the routers and the live table the climb builder
reads); this list is for a climb found on a way the live table still carries
until that rebuild, and for any the rule cannot see. Unclear bike access is closed
(OWNER-DECISIONS 330).

Read by three places, so a listed climb is gone everywhere at once without rewriting the
committed file: `pipeline.climb_layer.document` (the builder never writes it again),
`core.hillseek.parse` (Mountain Goat never routes to it) and the front end's
`frontend/src/lib/climbExclusions.ts` (the map never draws it), which must list the same ids
(tests/test_climb_exclusions.py holds them equal).

A climb's id is the hash of its start and summit (`pipeline.climb_layer.climb_id`), so it is
stable across rebuilds while the ways under it are drawn the same.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Excluded:
    reason: str
    source: str


EXCLUDED: dict[str, Excluded] = {
    # Cat 4, 1.2 mi (1,903 m), 512 ft (156 m) at 8.2%, unpaved, summit -77.22397, 39.08333:
    # down into the Travilah quarry pit (Rockville Crushed Stone) off Travilah Rd / Shady
    # Grove Rd, Montgomery County MD, over nine OSM ways (1379220522 to 1379220572) tagged
    # only `highway=track`, inside `landuse=quarry`.
    "bd93dd04dc": Excluded(
        reason="quarry haul road (Travilah quarry, landuse=quarry); not open to the public",
        source="owner report 2026-10-12 (reports/v0.6.0/quarry-climb-screenshot.png)",
    ),
}


def is_excluded(climb_id: str) -> bool:
    return climb_id in EXCLUDED
