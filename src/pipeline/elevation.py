"""Elevation tiles in the layout Valhalla's skadi reader expects.

Two details cost a rebuild each if they are wrong, and both are easy to get
wrong from memory.

The reader wants latitude-band subdirectories, so a tile lives at
`<dir>/N38/N38W077.hgt` and not at `<dir>/N38W077.hgt`. A flat directory reads as
no coverage at all rather than as an error, and every route then reports zero
gain.

And 3DEP one-arcsecond tiles are 3612 by 3612 with a six-pixel overlap per side,
so trimming the overlap by hand yields 3600 by 3600 while the HGT format needs
3601. The resample with an explicit extent and size is what produces the right
grid; the trim is not a step.
"""

from __future__ import annotations

import math
import shutil
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

HGT_1ARCSEC_SIDE = 3601
HGT_3ARCSEC_SIDE = 1201
SUPPORTED_SIDES = (HGT_1ARCSEC_SIDE, HGT_3ARCSEC_SIDE)


@dataclass(frozen=True)
class TileName:
    """The one-degree tile containing a coordinate."""

    lat: int
    lon: int

    @property
    def stem(self) -> str:
        ns = "N" if self.lat >= 0 else "S"
        ew = "E" if self.lon >= 0 else "W"
        return f"{ns}{abs(self.lat):02d}{ew}{abs(self.lon):03d}"

    @property
    def band(self) -> str:
        """The latitude-band subdirectory the reader expects."""
        ns = "N" if self.lat >= 0 else "S"
        return f"{ns}{abs(self.lat):02d}"

    def path(self, root: str = "", suffix: str = ".hgt") -> str:
        prefix = f"{root.rstrip('/')}/" if root else ""
        return f"{prefix}{self.band}/{self.stem}{suffix}"


def tile_for(lon: float, lat: float) -> TileName:
    """The tile whose south-west corner contains this coordinate."""
    return TileName(lat=math.floor(lat), lon=math.floor(lon))


def tiles_covering(west: float, south: float, east: float, north: float) -> list[TileName]:
    """Every tile needed for a bounding box, inclusive of its edges."""
    return [
        TileName(lat=lat, lon=lon)
        for lat in range(math.floor(south), math.floor(north) + 1)
        for lon in range(math.floor(west), math.floor(east) + 1)
    ]


# HGT is pixel-is-point: the samples sit *on* arc-second nodes, so the raster
# extent is outset by half a pixel on every side. GDAL's reader computes the
# origin as `swLon - 0.5/(N-1)`, giving a pixel size of exactly 1/3600 across
# 3601 columns.
HALF_PIXEL_DEG = 0.5 / 3600


def gdalwarp_command(source: str, destination: str, tile: TileName) -> list[str]:
    """The resample that produces a correct HGT grid.

    Explicit extent and size rather than a trim: the source carries a six-pixel
    overlap per side, and removing it arithmetically lands on 3600 rather than
    the 3601 the format requires.

    The extent is outset by half a pixel because HGT is pixel-is-point. Warping
    to exactly one degree across 3601 columns gives a pixel size of 1/3601 and
    puts every sample up to half an arc-second from its nominal node - about
    15 m north-south and 12 m east-west here, with the error reversing sign
    across the tile. GDAL writes that file anyway with only a corner-alignment
    warning, so it is exactly the quiet failure this module exists to prevent:
    on a 15 percent pitch a 12 m horizontal shift is nearly 2 m of elevation
    error, against a 3 m gain hysteresis and a grade cap a mass ride is planned
    around.
    """
    return [
        "gdalwarp",
        "-t_srs",
        "EPSG:4326",
        "-te",
        f"{tile.lon - HALF_PIXEL_DEG:.10f}",
        f"{tile.lat - HALF_PIXEL_DEG:.10f}",
        f"{tile.lon + 1 + HALF_PIXEL_DEG:.10f}",
        f"{tile.lat + 1 + HALF_PIXEL_DEG:.10f}",
        "-ts",
        str(HGT_1ARCSEC_SIDE),
        str(HGT_1ARCSEC_SIDE),
        "-r",
        "bilinear",
        "-ot",
        "Int16",
        "-of",
        "SRTMHGT",
        source,
        destination,
    ]


def expected_bytes(side: int = HGT_1ARCSEC_SIDE) -> int:
    """HGT is raw big-endian int16 with no header, so size alone validates shape."""
    if side not in SUPPORTED_SIDES:
        raise ValueError(f"unsupported HGT side length: {side}")
    return side * side * 2


def validate_size(byte_count: int) -> int:
    """Return the side length implied by a file size, or raise.

    A truncated download is otherwise indistinguishable from flat terrain: the
    reader returns zeroes and every route reports no climbing.
    """
    for side in SUPPORTED_SIDES:
        if byte_count == expected_bytes(side):
            return side
    raise ValueError(
        f"{byte_count} bytes matches no supported HGT grid; "
        f"expected {expected_bytes(HGT_1ARCSEC_SIDE)} or {expected_bytes(HGT_3ARCSEC_SIDE)}"
    )


# --- The stage ----------------------------------------------------------------
#
# Everything above describes a correct tile. This is what puts one on disk. It
# is a stage of the weekly rebuild even though the data is cached, because the
# guard that matters - a known steep edge reporting a nonzero grade after the
# build - can only be reached if the directory the build reads was populated
# first, and "populated" has to be checked every week rather than assumed from
# the week before: a truncated file reads as flat terrain, not as an error.

# USGS 3DEP 1 arc-second, as staged on The National Map's public bucket. One
# GeoTIFF per one-degree cell, named by its north-west corner in lower case,
# which is the same cell the HGT tile is named by (its south-west corner plus
# one degree of latitude) - so N38W078 is fetched as n39w078.
THREEDEP_URL = (
    "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/1/TIFF/current/"
    "{cell}/USGS_1_{cell}.tif"
)


class ElevationTileInvalid(RuntimeError):
    """A tile on disk is not a readable HGT grid."""


def threedep_cell(tile: TileName) -> str:
    """The 3DEP product cell that covers an HGT tile."""
    lat = tile.lat + 1
    ns = "n" if lat >= 0 else "s"
    ew = "e" if tile.lon >= 0 else "w"
    return f"{ns}{abs(lat):02d}{ew}{abs(tile.lon):03d}"


def fetch_3dep(tile: TileName, into: Path) -> Path:
    """Download the 3DEP source raster for one tile.

    NOT EXECUTED IN THIS ENVIRONMENT: outbound access to the USGS bucket is
    denied by the network policy, so this has been run against nothing. The URL
    pattern is The National Map's documented staged-products layout.
    """
    cell = threedep_cell(tile)
    into.mkdir(parents=True, exist_ok=True)
    destination = into / f"USGS_1_{cell}.tif"
    if destination.exists():
        return destination
    partial = destination.with_suffix(".tif.part")
    with urllib.request.urlopen(THREEDEP_URL.format(cell=cell)) as response:  # noqa: S310
        with partial.open("wb") as out:
            shutil.copyfileobj(response, out)
    partial.replace(destination)
    return destination


def ensure_tiles(
    directory: Path,
    bbox: Sequence[float],
    fetch: Callable[[TileName, Path], Path],
    run: Callable[[Sequence[str]], str],
) -> list[Path]:
    """Make every HGT tile the coverage box needs present and valid.

    A tile already on disk is validated by size and kept. A missing or
    truncated one is fetched, resampled with `gdalwarp_command` into a
    temporary name, validated, and only then moved into place, so a build that
    starts while a fetch is failing sees either a valid tile or no tile - never
    a short one, which the reader treats as flat terrain.

    Returns the tiles' paths, in the reader's band layout.
    """
    west, south, east, north = bbox
    directory = Path(directory)
    scratch = directory / ".fetch"
    ready: list[Path] = []

    for tile in tiles_covering(west, south, east, north):
        destination = directory / tile.path()
        if destination.exists():
            try:
                validate_size(destination.stat().st_size)
                ready.append(destination)
                continue
            except ValueError:
                destination.unlink()

        destination.parent.mkdir(parents=True, exist_ok=True)
        source = fetch(tile, scratch)
        partial = destination.with_name(destination.name + ".part")
        run(gdalwarp_command(str(source), str(partial), tile))
        if not partial.exists():
            raise ElevationTileInvalid(f"gdalwarp produced nothing at {partial}")
        try:
            validate_size(partial.stat().st_size)
        except ValueError as error:
            partial.unlink()
            raise ElevationTileInvalid(f"{tile.stem}: {error}") from error
        partial.replace(destination)
        ready.append(destination)

    return ready
