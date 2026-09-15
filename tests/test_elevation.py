from __future__ import annotations

import pytest

from pipeline.elevation import (
    HGT_1ARCSEC_SIDE,
    expected_bytes,
    gdalwarp_command,
    tile_for,
    tiles_covering,
    validate_size,
)


def test_tile_naming_for_the_dc_area() -> None:
    assert tile_for(-77.03, 38.90).stem == "N38W078"


def test_reader_needs_a_latitude_band_subdirectory() -> None:
    """A flat directory reads as no coverage rather than as an error, and every
    route then reports zero gain."""
    tile = tile_for(-77.03, 38.90)
    assert tile.path("/data/elevation") == "/data/elevation/N38/N38W078.hgt"


def test_coverage_box_includes_its_edges() -> None:
    tiles = tiles_covering(west=-78.0, south=38.0, east=-76.0, north=39.0)
    assert len(tiles) == 3 * 2
    assert tile_for(-77.0, 38.5) in tiles


def test_resample_produces_a_pixel_is_point_grid() -> None:
    """HGT samples sit on arc-second nodes, so the extent is outset by half a
    pixel. Warping to exactly one degree across 3601 columns gives a pixel size
    of 1/3601 and displaces every sample by up to half an arc-second - about 12 m
    here - which GDAL writes with only a corner-alignment warning.

    The values are asserted, not just the flags: the earlier version checked that
    the string "-te" appeared in the argv and never looked at the numbers.
    """
    command = gdalwarp_command("in.tif", "out.hgt", tile_for(-77.03, 38.90))

    size_index = command.index("-ts")
    assert command[size_index + 1 : size_index + 3] == ["3601", "3601"]

    extent = [float(v) for v in command[command.index("-te") + 1 :][:4]]
    west, south, east, north = extent
    half = 0.5 / 3600

    assert west == pytest.approx(-78 - half, abs=1e-9)
    assert south == pytest.approx(38 - half, abs=1e-9)
    assert east == pytest.approx(-77 + half, abs=1e-9)
    assert north == pytest.approx(39 + half, abs=1e-9)

    # The property all of that exists for: pixel size is exactly one arc-second
    # and the first sample centre lands on the tile's own corner.
    pixel = (east - west) / 3601
    assert pixel == pytest.approx(1 / 3600, rel=1e-9)
    assert west + pixel / 2 == pytest.approx(-78, abs=1e-9)

    assert "SRTMHGT" in command


def test_truncated_file_is_rejected_not_read_as_flat() -> None:
    """Zeroes from a short read are indistinguishable from flat terrain.

    The size is a literal rather than the module's own arithmetic fed back into
    its own validator: 3601 * 3601 * 2. Changing expected_bytes to use four-byte
    samples left the earlier version of this test green.
    """
    assert validate_size(25_934_402) == HGT_1ARCSEC_SIDE
    assert expected_bytes() == 25_934_402
    with pytest.raises(ValueError, match="matches no supported HGT grid"):
        validate_size(25_934_400)


def test_three_arcsecond_tiles_are_accepted() -> None:
    """The reader takes 1201 square as well, so rejecting them would be wrong."""
    assert validate_size(1201 * 1201 * 2) == 1201
