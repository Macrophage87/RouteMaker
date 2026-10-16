#!/usr/bin/env python3
"""Build the topo lines' contour archive (docs/MTB-TOPO-PLAN.md, slice 4; OWNER-DECISIONS 454).

The owner, 2026-10-10 (5:34 pm): "For topo, have the lines scale with zoom." So the
contours are drawn at a spacing that follows the zoom:

- zoom 12 and below: every 100 ft (30 m), every 500 ft an index line;
- zoom 13: every 40 ft (12 m), every 200 ft an index line;
- zoom 14 and in: every 20 ft (6 m), every 100 ft an index line;

every fifth line an index line, heavier and labelled in feet (metres in brackets). The
front end draws them (frontend/src/lib/topoLines.ts); this script makes the data.

Source: USGS 3DEP 1/3 arc-second DEM (about 33 ft (10 m) a pixel), one GeoTIFF per
one-degree cell on The National Map's public bucket
(https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/current/, read
2026-10-11: the four cells over the coverage are 370 to 500 MB each, last modified
April and May 2026). U.S. public domain (docs/SOURCES.md, "USGS 3D Elevation Program").

What it does, in a work directory (default `<out>/.contours-work`, which the edge refuses like
any unlisted path; deleted at the end, downloads and all, unless `--keep-work`, because
scripts/beta/ship-data.sh copies the whole basemap directory; a kept one makes a re-run download
nothing):

1. downloads the cells covering `settings.COVERAGE_BBOX`, each checked against the
   bucket's Content-Length (3DEP publishes no checksum) and opened with `gdalinfo`;
2. mosaics them (`gdalbuildvrt`) and clips to the coverage (`gdal_translate`);
3. traces every 20 ft contour with `gdal_contour`, at fixed levels given in metres
   (the DEM's unit) so each line is exactly a whole number of feet;
4. splits the lines into three layers by the coarsest spacing each belongs to (`c100`:
   multiples of 100 ft; `c40`: of 40 ft but not 100; `c20`: the rest), each tiled only
   from the zoom it is first drawn at, so the zoomed-out tiles carry the 100 ft lines
   alone; and
5. writes `contours.pmtiles` (GDAL's PMTiles driver, zoom 10 to 14; MapLibre overzooms
   past 14) into the output directory, through a temporary name, so the edge never
   serves half a file.

Each feature has one property, `ele_ft` (an integer). The layer split and the tile
zooms are this file's; the drawing (which lines show at which zoom, which are index
lines, widths and labels) is topoLines.ts's, and tests/test_build_contours.py holds the
two to the same numbers.

Needs GDAL 3.8 or later with the PMTiles driver (`ogr2ogr --formats` lists "PMTiles"),
for instance Ubuntu 24.04's gdal-bin (3.8.4) or the pinned container below. Runs on the
owner's host as the last step before a release reaches the beta (the owner: "Rebuild
should be the last step before it's on the beta"); docs/OPERATIONS.md, "Topo lines",
has the commands, the disk and the time.

Usage:
    python3 scripts/build_contours.py --out ${DATA_ROOT}/basemap [--work DIR] [--keep-work]
    python3 scripts/build_contours.py --print-plan     # the cells, URLs and levels; no network
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import urllib.request
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

# settings.COVERAGE_BBOX (west, south, east, north); tests/test_build_contours.py holds
# the two equal, as tests/test_basemap.py does for scripts/fetch_basemap.sh.
BBOX = (-78.05, 38.2, -76.02, 39.72)

THREEDEP_13_URL = (
    "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/current/"
    "{cell}/USGS_13_{cell}.tif"
)

FEET_PER_METRE = 1 / 0.3048
METRES_PER_FOOT = 0.3048

# The finest spacing traced, and the coarser ones the zooms draw (feet).
BASE_INTERVAL_FT = 20
# Lowest and highest line traced. The coverage runs from tidewater to about 2,300 ft
# (700 m) on the Blue Ridge at its western edge; the top leaves room, and a level with no
# ground at it yields no line. Zero is left out: it traces the shoreline of every tidal
# river, which the base map already draws.
MIN_LEVEL_FT = 20
MAX_LEVEL_FT = 4000


@dataclass(frozen=True)
class Band:
    """One tile layer: the lines whose coarsest spacing is `interval_ft`, tiled from `minzoom`."""

    layer: str
    interval_ft: int
    minzoom: int


# Coarsest first: a line goes in the first band whose spacing divides its elevation.
BANDS = (
    Band("c100", 100, 10),
    Band("c40", 40, 13),
    Band("c20", 20, 14),
)
MAXZOOM = 14
# The archive's metadata. The look is drawn in topoLines.ts, written for this app; the
# map's attribution credits "USGS 3DEP" already (frontend/src/lib/credits.json).
NAME = "RouteMaker contours"
ATTRIBUTION = "USGS 3DEP"
DESCRIPTION = (
    "Contours every 20 ft from the USGS 3DEP 1/3 arc-second DEM; "
    "ele_ft is the elevation in feet. Layers c100, c40 and c20 by coarsest spacing."
)
OUTPUT_NAME = "contours.pmtiles"


def cells(bbox: Sequence[float] = BBOX) -> list[str]:
    """The 3DEP one-degree cells covering `bbox`, named by their north-west corner
    (`n39w078` covers 38-39 N, 78-77 W), north to south, west to east."""
    west, south, east, north = bbox
    out = []
    for top in range(math.ceil(north), math.floor(south), -1):
        if top - 1 >= north:
            continue
        for left in range(math.floor(west), math.ceil(east)):
            ns = "n" if top >= 0 else "s"
            ew = "w" if left < 0 else "e"
            out.append(f"{ns}{abs(top):02d}{ew}{abs(left):03d}")
    return out


def cell_url(cell: str) -> str:
    return THREEDEP_13_URL.format(cell=cell)


def levels_ft(
    lo: int = MIN_LEVEL_FT, hi: int = MAX_LEVEL_FT, step: int = BASE_INTERVAL_FT
) -> list[int]:
    return list(range(lo, hi + 1, step))


def levels_m(feet: Iterable[int]) -> list[float]:
    """The levels in the DEM's metres, to the micrometre, so a traced line rounds back to
    its whole number of feet."""
    return [round(ft * METRES_PER_FOOT, 6) for ft in feet]


def band_of(ele_ft: int) -> Band:
    """The layer a line goes in: the coarsest spacing that divides its elevation."""
    for band in BANDS:
        if ele_ft % band.interval_ft == 0:
            return band
    raise ValueError(f"{ele_ft} ft is not on the {BASE_INTERVAL_FT} ft grid")


def band_sql(band: Band, source_layer: str = "contour") -> str:
    """The OGR SQL (SQLite dialect) that picks one band's lines and gives them `ele_ft`."""
    ele = f"CAST(ROUND({source_layer}.ele_m * {FEET_PER_METRE!r}) AS INTEGER)"
    coarser = [b.interval_ft for b in BANDS[: BANDS.index(band)]]
    where = [f"({ele}) % {band.interval_ft} = 0"]
    where += [f"({ele}) % {c} != 0" for c in coarser]
    return f"SELECT {ele} AS ele_ft, geom FROM {source_layer} WHERE " + " AND ".join(where)


def tile_conf() -> dict:
    """The MVT/PMTiles driver's CONF: each layer tiled from its own zoom."""
    return {
        band.layer: {"target_name": band.layer, "minzoom": band.minzoom, "maxzoom": MAXZOOM}
        for band in BANDS
    }


def commands(work: Path, out: Path, cell_files: Sequence[Path]) -> list[list[str]]:
    """Every GDAL command after the downloads, in order."""
    west, south, east, north = BBOX
    vrt = work / "mosaic.vrt"
    clip = work / "clip.tif"
    lines = work / "contours.gpkg"
    bands = work / "bands.gpkg"
    temporary = out / f".{OUTPUT_NAME}.part"
    levels = [str(level) for level in levels_m(levels_ft())]
    cmds = [
        ["gdalbuildvrt", "-overwrite", str(vrt), *map(str, cell_files)],
        [
            "gdal_translate",
            "-projwin",
            str(west),
            str(north),
            str(east),
            str(south),
            "-co",
            "TILED=YES",
            "-co",
            "COMPRESS=DEFLATE",
            "-co",
            "BIGTIFF=IF_SAFER",
            str(vrt),
            str(clip),
        ],
        [
            "gdal_contour",
            "-a",
            "ele_m",
            "-nln",
            "contour",
            "-f",
            "GPKG",
            "-lco",
            "GEOMETRY_NAME=geom",
            "-fl",
            *levels,
            str(clip),
            str(lines),
        ],
    ]
    for index, band in enumerate(BANDS):
        cmds.append(
            [
                "ogr2ogr",
                "-f",
                "GPKG",
                *([] if index == 0 else ["-update"]),
                "-dialect",
                "SQLite",
                "-sql",
                band_sql(band),
                "-nln",
                band.layer,
                str(bands),
                str(lines),
            ]
        )
    cmds.append(
        [
            "ogr2ogr",
            "-f",
            "PMTiles",
            "-dsco",
            f"MINZOOM={min(b.minzoom for b in BANDS)}",
            "-dsco",
            f"MAXZOOM={MAXZOOM}",
            "-dsco",
            f"CONF={json.dumps(tile_conf(), separators=(',', ':'))}",
            "-dsco",
            f"NAME={NAME}",
            "-dsco",
            f"DESCRIPTION={DESCRIPTION}",
            "-dsco",
            "TYPE=overlay",
            "-t_srs",
            "EPSG:3857",
            str(temporary),
            str(bands),
        ]
    )
    return cmds


def remote_size(url: str) -> int | None:
    request = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 (a fixed https URL)
        length = response.headers.get("Content-Length")
    return int(length) if length else None


def download(cell: str, into: Path) -> Path:
    """One cell, resumable only by starting again: a file whose size matches the bucket's
    is kept; anything else is fetched afresh through a `.part` name."""
    url = cell_url(cell)
    into.mkdir(parents=True, exist_ok=True)
    target = into / f"USGS_13_{cell}.tif"
    size = remote_size(url)
    if target.exists() and size is not None and target.stat().st_size == size:
        print(f"  {cell}: have it ({size:,} bytes)")
        return target
    partial = target.with_name(target.name + ".part")
    print(f"  {cell}: downloading {url}")
    with urllib.request.urlopen(url, timeout=120) as response, partial.open("wb") as handle:  # noqa: S310
        shutil.copyfileobj(response, handle, length=1 << 20)
    if size is not None and partial.stat().st_size != size:
        partial.unlink()
        raise SystemExit(f"{cell}: got {partial.stat().st_size} bytes, the bucket says {size}")
    partial.replace(target)
    return target


def run(cmd: Sequence[str]) -> None:
    print("  $ " + " ".join(cmd[:4]) + (" ..." if len(cmd) > 4 else ""))
    subprocess.run(cmd, check=True)


def check_gdal() -> None:
    for tool in ("gdalinfo", "gdalbuildvrt", "gdal_translate", "gdal_contour", "ogr2ogr"):
        if shutil.which(tool) is None:
            raise SystemExit(
                f"{tool} is not on PATH: install GDAL 3.8+ (docs/OPERATIONS.md, 'Topo lines')"
            )
    formats = subprocess.run(["ogr2ogr", "--formats"], check=True, capture_output=True, text=True)
    if "PMTiles" not in formats.stdout:
        raise SystemExit("this GDAL has no PMTiles driver: GDAL 3.8 or later is needed")


def print_plan() -> None:
    print(f"coverage {BBOX}")
    for cell in cells():
        print(f"  {cell}  {cell_url(cell)}")
    feet = levels_ft()
    print(f"levels {feet[0]}-{feet[-1]} ft every {BASE_INTERVAL_FT} ft ({len(feet)} levels)")
    for band in BANDS:
        print(
            f"  layer {band.layer}: coarsest spacing {band.interval_ft} ft,"
            f" tiled from zoom {band.minzoom}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--out", type=Path, help="the directory contours.pmtiles goes in (${DATA_ROOT}/basemap)"
    )
    parser.add_argument(
        "--work", type=Path, help="the work directory (default <out>/.contours-work)"
    )
    parser.add_argument(
        "--keep-work",
        action="store_true",
        help="keep the work directory (the downloads, the clipped DEM and the line files)",
    )
    parser.add_argument(
        "--print-plan", action="store_true", help="print the cells, URLs and levels, and exit"
    )
    args = parser.parse_args(argv)
    if args.print_plan:
        print_plan()
        return 0
    if args.out is None:
        parser.error("--out is required")
    out: Path = args.out
    work: Path = args.work or out / ".contours-work"
    if out.resolve().is_relative_to(work.resolve()):
        parser.error(
            "--work must be its own directory, not --out or above it: it is deleted at the end"
        )
    check_gdal()
    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    print("1. 3DEP 1/3 arc-second cells")
    files = [download(cell, work / "src") for cell in cells()]
    for path in files:
        subprocess.run(["gdalinfo", str(path)], check=True, capture_output=True)
    print("2-5. mosaic, clip, contours, layers, tiles")
    temporary = out / f".{OUTPUT_NAME}.part"
    for stale in (temporary, work / "contours.gpkg", work / "bands.gpkg"):
        if stale.exists():
            stale.unlink()
    for cmd in commands(work, out, files):
        run(cmd)
    os.chmod(temporary, 0o644)
    temporary.replace(out / OUTPUT_NAME)
    print(f"wrote {out / OUTPUT_NAME} ({(out / OUTPUT_NAME).stat().st_size:,} bytes)")
    if not args.keep_work:
        shutil.rmtree(work)
    return 0


if __name__ == "__main__":
    sys.exit(main())
