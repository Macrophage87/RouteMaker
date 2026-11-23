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
    # the coverage box less every other region (Southern Maryland).
    outline: tuple[tuple[float, float], ...] | None
    # Whether the Beltway region is cut out of it (the regions outside it).
    outside_beltway: bool = True
    # The whole map in one pack (the coverage box), offered beside the areas (Stephen,
    # 2026-11-13: "Offer everything too to download").
    whole: bool = False


# Our draft borders, approximate, drawn along the Beltway, the Potomac and the county lines
# riders cross least; the one-mile overlap covers a border's roads on both sides. Our default,
# unmeasured: sizes are measured after the first rebuild that builds them.
# Northern Virginia: the Virginia and West Virginia shore of the Potomac, then the coverage box.
# fmt: off
_POTOMAC_SOUTH = (
    (-78.050, 39.645), (-78.036, 39.636), (-78.010, 39.603), (-77.977, 39.600),
    (-77.958, 39.609), (-77.951, 39.604), (-77.952, 39.593), (-77.946, 39.585),
    (-77.939, 39.587), (-77.936, 39.595), (-77.935, 39.608), (-77.944, 39.615),
    (-77.942, 39.619), (-77.933, 39.618), (-77.923, 39.605), (-77.888, 39.597),
    (-77.881, 39.603), (-77.885, 39.616), (-77.834, 39.603), (-77.830, 39.587),
    (-77.836, 39.566), (-77.878, 39.563), (-77.889, 39.556), (-77.865, 39.538),
    (-77.864, 39.515), (-77.842, 39.518), (-77.837, 39.532), (-77.825, 39.529),
    (-77.826, 39.517), (-77.845, 39.506), (-77.846, 39.499), (-77.802, 39.489),
    (-77.792, 39.491), (-77.782, 39.499), (-77.766, 39.496), (-77.769, 39.490),
    (-77.797, 39.480), (-77.796, 39.471), (-77.778, 39.462), (-77.798, 39.461),
    (-77.786, 39.445), (-77.803, 39.437), (-77.793, 39.431), (-77.755, 39.425),
    (-77.740, 39.402), (-77.736, 39.388), (-77.754, 39.380), (-77.744, 39.360),
    (-77.746, 39.353), (-77.760, 39.344), (-77.760, 39.337), (-77.727, 39.322),
    (-77.693, 39.318), (-77.676, 39.324), (-77.651, 39.311), (-77.616, 39.303),
    (-77.593, 39.301), (-77.567, 39.306), (-77.562, 39.302), (-77.561, 39.286),
    (-77.541, 39.265), (-77.487, 39.248), (-77.458, 39.225), (-77.474, 39.208),
    (-77.479, 39.189), (-77.505, 39.182), (-77.516, 39.171), (-77.527, 39.146),
    (-77.520, 39.121), (-77.486, 39.109), (-77.458, 39.074), (-77.386, 39.062),
    (-77.340, 39.063), (-77.248, 39.027), (-77.245, 39.020), (-77.256, 39.002),
    (-77.245, 38.983), (-77.212, 38.969), (-77.147, 38.964), (-77.103, 38.913),
    (-77.090, 38.904), (-77.068, 38.900), (-77.058, 38.880), (-77.049, 38.871),
    (-77.045, 38.875), (-77.041, 38.871), (-77.032, 38.851), (-77.035, 38.840),
    (-77.045, 38.839), (-77.039, 38.832), (-77.037, 38.814), (-77.043, 38.719),
    (-77.053, 38.710), (-77.080, 38.713), (-77.080, 38.709), (-77.122, 38.686),
    (-77.133, 38.674), (-77.136, 38.650), (-77.130, 38.635), (-77.158, 38.637),
    (-77.169, 38.625), (-77.202, 38.618), (-77.216, 38.637), (-77.203, 38.640),
    (-77.194, 38.653), (-77.201, 38.658), (-77.236, 38.660), (-77.224, 38.646),
    (-77.228, 38.638), (-77.241, 38.639), (-77.248, 38.632), (-77.245, 38.621),
    (-77.256, 38.599), (-77.247, 38.591), (-77.258, 38.583), (-77.264, 38.585),
    (-77.265, 38.580), (-77.257, 38.560), (-77.277, 38.547), (-77.287, 38.519),
    (-77.298, 38.515), (-77.296, 38.507), (-77.310, 38.494), (-77.323, 38.467),
    (-77.326, 38.444), (-77.311, 38.398), (-77.317, 38.395), (-77.317, 38.384),
    (-77.296, 38.370), (-77.280, 38.339), (-77.265, 38.332), (-77.240, 38.331),
    (-77.163, 38.346), (-77.138, 38.368), (-77.085, 38.368), (-77.071, 38.378),
    (-77.053, 38.399), (-77.042, 38.400), (-77.012, 38.375), (-77.016, 38.371),
    (-77.015, 38.333), (-77.025, 38.322), (-77.040, 38.319), (-77.054, 38.323),
    (-77.056, 38.317), (-77.043, 38.309), (-77.029, 38.311), (-77.026, 38.303),
    (-77.002, 38.282), (-77.001, 38.275), (-76.981, 38.274), (-76.962, 38.256),
    (-76.957, 38.237), (-76.967, 38.227), (-76.962, 38.214), (-76.937, 38.202),
    (-76.918, 38.200), (-78.050, 38.200), (-78.050, 39.645),
)
# fmt: on
# The northwest exurbs: its eastern border, then the Maryland bank of the Potomac (the river is
# Maryland's), then the coverage box.
# fmt: off
_NW_EXURBS = (
    (-77.000, 39.720), (-76.950, 39.200), (-76.980, 39.040), (-77.120, 38.940),
    (-77.120, 38.933), (-77.147, 38.964), (-77.212, 38.969), (-77.245, 38.983),
    (-77.256, 39.002), (-77.245, 39.020), (-77.248, 39.027), (-77.340, 39.063),
    (-77.386, 39.062), (-77.458, 39.074), (-77.486, 39.109), (-77.520, 39.121),
    (-77.527, 39.146), (-77.516, 39.171), (-77.505, 39.182), (-77.479, 39.189),
    (-77.474, 39.208), (-77.458, 39.225), (-77.487, 39.248), (-77.541, 39.265),
    (-77.561, 39.286), (-77.562, 39.302), (-77.567, 39.306), (-77.593, 39.301),
    (-77.616, 39.303), (-77.651, 39.311), (-77.676, 39.324), (-77.693, 39.318),
    (-77.727, 39.322), (-77.760, 39.337), (-77.760, 39.344), (-77.746, 39.353),
    (-77.744, 39.360), (-77.754, 39.380), (-77.736, 39.388), (-77.740, 39.402),
    (-77.755, 39.425), (-77.793, 39.431), (-77.803, 39.437), (-77.786, 39.445),
    (-77.798, 39.461), (-77.778, 39.462), (-77.796, 39.471), (-77.797, 39.480),
    (-77.769, 39.490), (-77.766, 39.496), (-77.782, 39.499), (-77.792, 39.491),
    (-77.802, 39.489), (-77.846, 39.499), (-77.845, 39.506), (-77.826, 39.517),
    (-77.825, 39.529), (-77.837, 39.532), (-77.842, 39.518), (-77.864, 39.515),
    (-77.865, 39.538), (-77.889, 39.556), (-77.878, 39.563), (-77.836, 39.566),
    (-77.830, 39.587), (-77.834, 39.603), (-77.885, 39.616), (-77.881, 39.603),
    (-77.888, 39.597), (-77.923, 39.605), (-77.933, 39.618), (-77.942, 39.619),
    (-77.944, 39.615), (-77.935, 39.608), (-77.936, 39.595), (-77.939, 39.587),
    (-77.946, 39.585), (-77.952, 39.593), (-77.951, 39.604), (-77.958, 39.609),
    (-77.977, 39.600), (-78.010, 39.603), (-78.036, 39.636), (-78.050, 39.645),
    (-78.050, 39.720), (-77.000, 39.720),
)
# fmt: on

# Baltimore and suburbs: the coverage box less Northern Virginia, the northwest exurbs and
# Southern Maryland (Charles, Calvert and St. Mary's Counties and Prince George's south of Upper
# Marlboro's latitude, 38.816, by the Census Bureau's 2023 cartographic county boundaries).
# fmt: off
_BALTIMORE = (
    (-76.020, 38.200), (-76.369, 38.200), (-76.385, 38.218), (-76.399, 38.259),
    (-76.394, 38.278), (-76.375, 38.300), (-76.400, 38.310), (-76.409, 38.305),
    (-76.423, 38.305), (-76.430, 38.295), (-76.442, 38.292), (-76.459, 38.295),
    (-76.476, 38.314), (-76.468, 38.328), (-76.456, 38.316), (-76.451, 38.323),
    (-76.438, 38.325), (-76.421, 38.319), (-76.387, 38.361), (-76.390, 38.375),
    (-76.381, 38.385), (-76.402, 38.395), (-76.415, 38.415), (-76.492, 38.483),
    (-76.506, 38.505), (-76.517, 38.536), (-76.516, 38.590), (-76.511, 38.616),
    (-76.532, 38.678), (-76.528, 38.713), (-76.535, 38.722), (-76.616, 38.721),
    (-76.622, 38.727), (-76.623, 38.768), (-76.647, 38.769), (-76.673, 38.756),
    (-76.685, 38.757), (-76.687, 38.749), (-76.696, 38.750), (-76.701, 38.769),
    (-76.714, 38.778), (-76.712, 38.784), (-76.702, 38.788), (-76.710, 38.796),
    (-76.710, 38.816), (-77.008, 38.816), (-77.038, 38.793), (-77.039, 38.832),
    (-77.045, 38.839), (-77.035, 38.840), (-77.032, 38.851), (-77.041, 38.871),
    (-77.045, 38.875), (-77.049, 38.871), (-77.058, 38.880), (-77.068, 38.900),
    (-77.090, 38.904), (-77.103, 38.913), (-77.147, 38.964), (-77.120, 38.933),
    (-77.120, 38.940), (-76.980, 39.040), (-76.950, 39.200), (-77.000, 39.720),
    (-76.020, 39.720), (-76.020, 38.200),
)
# fmt: on

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
        # Everything south of the Potomac in the coverage box: Virginia and the West Virginia
        # panhandle (Martinsburg, Charles Town), the river being the line riders cross least
        # outside DC (Stephen, 2026-11-15: "Divide the map along the Potomac. There are so few
        # crossings outside DC that it's reasonable to divide there"). The Virginia and West
        # Virginia shore from the Census Bureau's 2023 cartographic state boundaries (1:500,000,
        # public domain), simplified to about 300 m; the packs' one-mile overlap covers the
        # river and the far bank's roads.
        outline=_POTOMAC_SOUTH,
    ),
    Region(
        id="nw-exurbs",
        name="Northwest exurbs",
        # Montgomery outside the Beltway (Potomac and Great Falls too), Frederick and Washington
        # Counties, Carroll and western Howard: north of the Potomac (the river itself, which is
        # Maryland's, included) and west of about Columbia. Drawn into the Beltway, which is cut
        # out of it. The river shore is Northern Virginia's, above.
        outline=_NW_EXURBS,
    ),
    Region(
        id="baltimore",
        name="Baltimore and suburbs",
        # Baltimore City and County, eastern Howard, Harford, all of Anne Arundel, Prince George's
        # north of Upper Marlboro (Bowie, Laurel, Greenbelt outside the Beltway) and the Eastern
        # Shore across the Bay Bridge: the Maryland side less the northwest exurbs and Southern
        # Maryland (Stephen, 2026-11-15: "Bowie and the like should be nearer to Baltimore. The
        # dividing line would be somewhere around Upper Marlboro ... Or just use county borders").
        outline=_BALTIMORE,
    ),
    Region(
        id="rest",
        name="Southern Maryland",
        # Charles, Calvert and St. Mary's Counties and Prince George's south of Upper Marlboro (the
        # map less every other area, the river south of DC with it): one riding area, named, not
        # "the rest of the map" (Stephen, 2026-11-15: "rest of map doesn't make a lot of sense").
        outline=None,
    ),
    Region(
        id="all",
        name="Everything",
        outline=None,
        whole=True,
    ),
)


def _box_outline(box) -> tuple[tuple[float, float], ...]:
    west, south, east, north = box
    return ((west, south), (east, south), (east, north), (west, north), (west, south))


def regions() -> tuple[Region, ...]:
    """The packs built: REGIONS, then one pack for each later map area, whose outline is the
    area's box (`routemaker.coverage`; Southwest Florida, the owner, 2026-11-23). Such an area
    is a pack of its own and is in no other: the home regions are drawn inside the home box."""
    from routemaker import coverage

    extra = tuple(
        Region(
            id=name,
            name=AREA_PACK_NAMES.get(name, name),
            outline=_box_outline(box),
            outside_beltway=False,
        )
        for name, box in coverage.areas().items()
        if name != coverage.HOME
    )
    return REGIONS + extra


AREA_PACK_NAMES = {"southwest-florida": "Southwest Florida"}


def area_of(region_id: str) -> dict | None:
    """A region's area for the phone, which draws the areas on a map and opens the kept pack
    that covers the rider: its outline ([lon, lat] around; None for the map less every outlined
    area, or the whole box), whether the Beltway is cut out of it, and whether it is the whole
    map. None for an id no longer built."""
    for region in regions():
        if region.id == region_id:
            return {
                "outline": [list(point) for point in region.outline] if region.outline else None,
                "outside_beltway": region.outside_beltway and region.outline is not None,
                "whole": region.whole,
            }
    return None


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
