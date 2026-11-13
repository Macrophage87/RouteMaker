"""Region packs for off-grid riding: the whole road network of one riding area, an optional
download beside the mile-wide corridor each ride already fetches (Stephen, 2026-11-12: "the
one mile would be a default, with a whole region pack an optional download. Potentially split
it by subregion"; "Probably Beltway, NoVA, NW exurbs, Baltimore and suburbs, etc. There's a
lot of county to county crossing. These are more natural borders").

The packs are built after each map swap (`pipeline.offline_packs`) as gzip JSON files in the
format frontend lib/offlineRouter.ts reads (v1), one per region, under
`TILES_DIR/offline-packs/packs-<build id>/`, named by `TILES_DIR/offline-packs/manifest.json`.
The build host makes them and the beta ship script carries them (`scripts/beta/ship-data.sh`,
part `packs`). The web
server serves the files (Caddyfile and the beta nginx template, `/offline-packs/`), and
`GET /api/offline/packs` lists them. Map data only: nothing about a rider.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

PACKS_VERSION = 1
# Each region's pack takes the ways within this distance of its border too, so a ride across a
# border is still covered for a mile on the other side (the same mile as the corridor's).
OVERLAP_M = 1609


@dataclass(frozen=True)
class Region:
    id: str
    name: str
    # The border, [lon, lat] around, the first point repeated last. None: the rest of the map,
    # the coverage box less every other region.
    outline: tuple[tuple[float, float], ...] | None
    # Whether the Beltway region is cut out of it (the regions outside it).
    outside_beltway: bool = True


# Our draft borders, approximate, drawn along the Beltway, the Potomac and the county lines
# riders cross least; the one-mile overlap covers a border's roads on both sides. Our default,
# unmeasured: sizes are measured after the first rebuild that builds them.
BELTWAY = Region(
    id="beltway",
    name="Inside the Beltway",
    outline=(
        (-77.040, 39.020),
        (-76.950, 39.020),
        (-76.920, 39.000),
        (-76.870, 38.960),
        (-76.840, 38.890),
        (-76.860, 38.840),
        (-76.920, 38.800),
        (-77.020, 38.785),
        (-77.080, 38.795),
        (-77.170, 38.780),
        (-77.230, 38.860),
        (-77.220, 38.920),
        (-77.180, 38.970),
        (-77.120, 39.020),
        (-77.040, 39.020),
    ),
    outside_beltway=False,
)
REGIONS: tuple[Region, ...] = (
    BELTWAY,
    Region(
        id="nova",
        name="Northern Virginia",
        # Down the Potomac from the Blue Ridge to the coverage box's south edge.
        outline=(
            (-78.050, 38.200),
            (-76.950, 38.200),
            (-77.000, 38.400),
            (-77.250, 38.550),
            (-77.120, 38.650),
            (-77.040, 38.750),
            (-77.030, 38.840),
            (-77.070, 38.900),
            (-77.120, 38.940),
            (-77.250, 39.000),
            (-77.450, 39.070),
            (-77.520, 39.180),
            (-77.580, 39.290),
            (-77.720, 39.320),
            (-77.800, 39.330),
            (-78.050, 39.100),
            (-78.050, 38.200),
        ),
    ),
    Region(
        id="nw-exurbs",
        name="Northwest exurbs",
        # Montgomery outside the Beltway (Potomac and Great Falls too), Frederick and Washington
        # Counties, Carroll and western Howard: north of the Potomac and west of about Columbia.
        # Drawn into the Beltway, which is cut out of it.
        outline=(
            (-77.120, 38.940),
            (-77.250, 39.000),
            (-77.450, 39.070),
            (-77.520, 39.180),
            (-77.580, 39.290),
            (-77.720, 39.320),
            (-77.820, 39.600),
            (-78.050, 39.650),
            (-78.050, 39.720),
            (-77.000, 39.720),
            (-76.950, 39.200),
            (-76.980, 39.040),
            (-77.040, 39.000),
            (-77.120, 38.940),
        ),
    ),
    Region(
        id="baltimore",
        name="Baltimore and suburbs",
        # Baltimore City and County, eastern Howard, Harford and Anne Arundel to about Annapolis.
        outline=(
            (-76.980, 39.040),
            (-76.950, 39.200),
            (-77.000, 39.720),
            (-76.020, 39.720),
            (-76.020, 38.900),
            (-76.400, 38.900),
            (-76.750, 39.020),
            (-76.980, 39.040),
        ),
    ),
    Region(
        id="rest",
        name="The rest of the map",
        # Southern Maryland, Prince George's outside the Beltway, the West Virginia panhandle.
        outline=None,
    ),
)


def packs_dir() -> Path:
    return Path(settings.TILES_DIR) / "offline-packs"


def manifest() -> dict | None:
    """The newest packs' manifest, or None before any rebuild has built them."""
    path = packs_dir() / "manifest.json"
    try:
        found = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(found, dict) or found.get("v") != PACKS_VERSION or "dir" not in found:
        return None
    return found
