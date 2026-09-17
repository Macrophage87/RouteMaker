from __future__ import annotations

import pytest

from pipeline.elevation import (
    HGT_1ARCSEC_SIDE,
    THREEDEP_URL,
    ElevationTileInvalid,
    ensure_tiles,
    expected_bytes,
    gdalwarp_command,
    threedep_cell,
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

    # The resampling kernel, pinned. `near` writes a file GDAL is equally happy
    # with and the same size, so nothing downstream can tell: it takes the
    # nearest 3DEP sample instead of interpolating, which on a one-arcsecond
    # source resampled to one-arcsecond nodes displaces every value by up to
    # half a pixel - the same 12 to 15 m shift the half-pixel outset above
    # exists to remove, reintroduced by the kernel. On a 15 percent pitch that
    # is nearly 2 m of elevation error against a 3 m gain hysteresis and a grade
    # cap a mass ride is planned around.
    assert command[command.index("-r") + 1] == "bilinear"


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


def test_a_three_arcsecond_tile_is_rejected_because_skadi_reads_one_dimension() -> None:
    """1201 square is a valid HGT grid and skadi does not read it.

    `src/skadi/sample.cc:27` is `constexpr size_t HGT_DIM = 3601;`, HGT_BYTES
    follows from it, and :74 refuses any RAW tile of another size outright:
    `if (format == format_t::RAW && size != HGT_BYTES) return false;`. That
    refusal is not an error - :626 logs "Corrupt elevation data: <file>" and the
    tile is left out of the cache - so accepting one here produced a cell with
    no elevation that this module had already called ready.
    """
    with pytest.raises(ValueError) as caught:
        validate_size(1201 * 1201 * 2)
    message = str(caught.value)
    assert "1201 x 1201" in message, "the message has to name what was rejected"
    assert str(1201 * 1201 * 2) in message
    assert "3601" in message, "and what was wanted"

    assert expected_bytes(3601) == 25_934_402
    with pytest.raises(ValueError, match="unsupported HGT side length: 1201"):
        expected_bytes(1201)


# --- The stage -------------------------------------------------------------------


def warp_writing(side: int):
    """A gdalwarp that leaves a grid of the given side on disk."""

    def run(command):
        assert command[0] == "gdalwarp"
        from pathlib import Path

        Path(command[-1]).write_bytes(b"\0" * (side * side * 2))
        return ""

    return run


def fetch_recording(seen: list):
    def fetch(tile, into):
        seen.append(tile.stem)
        into.mkdir(parents=True, exist_ok=True)
        source = into / f"{tile.stem}.tif"
        source.write_bytes(b"tif")
        return source

    return fetch


def test_the_stage_puts_every_tile_the_box_touches_in_the_band_layout(tmp_path) -> None:
    seen: list = []
    ready = ensure_tiles(
        tmp_path, (-77.5, 38.5, -76.5, 39.2), fetch_recording(seen), warp_writing(3601)
    )
    assert sorted(seen) == ["N38W077", "N38W078", "N39W077", "N39W078"]
    assert {p.relative_to(tmp_path).as_posix() for p in ready} == {
        "N38/N38W077.hgt",
        "N38/N38W078.hgt",
        "N39/N39W077.hgt",
        "N39/N39W078.hgt",
    }
    assert all(p.stat().st_size == 3601 * 3601 * 2 for p in ready)


def test_a_valid_cached_tile_is_kept_and_not_fetched_again(tmp_path) -> None:
    """Built once and cached on the tiles volume; the weekly rebuild reuses it."""
    seen: list = []
    ensure_tiles(tmp_path, (-77.5, 38.5, -77.5, 38.5), fetch_recording(seen), warp_writing(3601))
    assert seen == ["N38W078"]
    ensure_tiles(tmp_path, (-77.5, 38.5, -77.5, 38.5), fetch_recording(seen), warp_writing(3601))
    assert seen == ["N38W078"], "the second rebuild fetched nothing"


def test_a_truncated_cached_tile_is_replaced_not_trusted(tmp_path) -> None:
    """A short file reads as flat terrain, not as an error; the reader would
    have served zero gain for the cell for as long as the file sat there."""
    short = tmp_path / "N38" / "N38W078.hgt"
    short.parent.mkdir()
    short.write_bytes(b"\0" * 100)
    seen: list = []
    ensure_tiles(tmp_path, (-77.5, 38.5, -77.5, 38.5), fetch_recording(seen), warp_writing(3601))
    assert seen == ["N38W078"]
    assert short.stat().st_size == 3601 * 3601 * 2


def test_a_resample_that_produces_a_bad_grid_leaves_no_tile_behind(tmp_path) -> None:
    with pytest.raises(ElevationTileInvalid, match="matches no supported HGT grid"):
        ensure_tiles(tmp_path, (-77.5, 38.5, -77.5, 38.5), fetch_recording([]), warp_writing(3600))
    assert not (tmp_path / "N38" / "N38W078.hgt").exists()
    assert not (tmp_path / "N38" / "N38W078.hgt.part").exists()


def test_the_stage_refuses_a_three_arcsecond_tile_rather_than_calling_it_ready(tmp_path) -> None:
    """The level it takes effect: a stage that accepted 1201 wrote the tile,
    validated it, returned it as ready, and the tile build then ignored it. The
    rebuild has to stop here instead."""
    with pytest.raises(ElevationTileInvalid, match="1201 x 1201"):
        ensure_tiles(tmp_path, (-77.5, 38.5, -77.5, 38.5), fetch_recording([]), warp_writing(1201))
    assert not (tmp_path / "N38" / "N38W078.hgt").exists()


def test_a_cached_three_arcsecond_tile_is_replaced_rather_than_trusted(tmp_path) -> None:
    """And one already on disk from before this was fixed is not kept."""
    stale = tmp_path / "N38" / "N38W078.hgt"
    stale.parent.mkdir()
    stale.write_bytes(b"\0" * (1201 * 1201 * 2))
    seen: list = []
    ensure_tiles(tmp_path, (-77.5, 38.5, -77.5, 38.5), fetch_recording(seen), warp_writing(3601))
    assert seen == ["N38W078"], "the stale tile was kept"
    assert stale.stat().st_size == 3601 * 3601 * 2


def test_the_3dep_cell_is_named_by_its_north_west_corner() -> None:
    """3DEP names a cell by its north-west corner; HGT names the same cell by its
    south-west one. N38W078 is the cell whose 3DEP product is n39w078."""
    assert threedep_cell(tile_for(-77.03, 38.90)) == "n39w078"
    assert THREEDEP_URL.format(cell="n39w078") == (
        "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/1/TIFF/current/"
        "n39w078/USGS_1_n39w078.tif"
    )
