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


def test_resample_uses_explicit_extent_and_size() -> None:
    """3DEP tiles are 3612 square with a six-pixel overlap per side, so trimming
    by hand yields 3600 where the format needs 3601. The resample is what
    produces the grid."""
    command = gdalwarp_command("in.tif", "out.hgt", tile_for(-77.03, 38.90))
    assert "-ts" in command
    size_index = command.index("-ts")
    assert command[size_index + 1 : size_index + 3] == [str(HGT_1ARCSEC_SIDE)] * 2
    assert "-te" in command
    assert "SRTMHGT" in command


def test_truncated_file_is_rejected_not_read_as_flat() -> None:
    """Zeroes from a short read are indistinguishable from flat terrain."""
    assert validate_size(expected_bytes()) == HGT_1ARCSEC_SIDE
    with pytest.raises(ValueError, match="matches no supported HGT grid"):
        validate_size(expected_bytes() - 2)


def test_three_arcsecond_tiles_are_accepted() -> None:
    """The reader takes 1201 square as well, so rejecting them would be wrong."""
    assert validate_size(1201 * 1201 * 2) == 1201
