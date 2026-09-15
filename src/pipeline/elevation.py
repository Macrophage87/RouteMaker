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
from dataclasses import dataclass

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
