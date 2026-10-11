"""The topo lines' contour build (scripts/build_contours.py; docs/MTB-TOPO-PLAN.md, slice 4).

No network and no GDAL: the cells, URLs, levels, the layer split's SQL (run on SQLite here,
the dialect ogr2ogr is told to use) and the command list are checked as data; the front end's
reading of the same numbers is frontend/src/lib/topoLines.test.ts. An end-to-end run on a
real 3DEP window is recorded in docs/OPERATIONS.md, "Topo lines".
"""

from __future__ import annotations

import importlib.util
import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "build_contours.py"
FRONTEND = REPO / "frontend" / "src" / "lib" / "topoLines.ts"

spec = importlib.util.spec_from_file_location("build_contours", SCRIPT)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules["build_contours"] = mod
spec.loader.exec_module(mod)


def test_the_box_is_the_coverage() -> None:
    settings = (REPO / "src" / "config" / "settings.py").read_text()
    found = re.search(r"^COVERAGE_BBOX = \(([^)]*)\)", settings, re.M)
    assert found
    assert mod.BBOX == tuple(float(v) for v in found.group(1).split(","))


def test_the_cells_cover_the_box_and_nothing_more() -> None:
    assert mod.cells() == ["n40w078", "n40w077", "n39w078", "n39w077"]
    # A box on whole degrees takes exactly its own cells.
    assert mod.cells((-78.0, 38.0, -77.0, 39.0)) == ["n39w078"]
    assert mod.cells((-77.5, 38.5, -76.5, 39.5)) == ["n40w078", "n40w077", "n39w078", "n39w077"]
    assert (
        mod.cell_url("n39w078")
        == "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/current/n39w078/USGS_13_n39w078.tif"
    )


def test_levels_are_whole_feet_every_20_ft_from_20() -> None:
    feet = mod.levels_ft()
    assert (
        feet[0] == 20
        and feet[-1] == 4000
        and all(b - a == 20 for a, b in zip(feet, feet[1:], strict=False))
    )
    for ft, m in zip(feet, mod.levels_m(feet), strict=True):
        assert round(m / 0.3048) == ft


def test_each_line_goes_in_the_layer_of_its_coarsest_spacing() -> None:
    assert [b.layer for b in mod.BANDS] == ["c100", "c40", "c20"]
    assert mod.band_of(500).layer == "c100"
    assert mod.band_of(200).layer == "c100"
    assert mod.band_of(120).layer == "c40"
    assert mod.band_of(60).layer == "c20"
    with pytest.raises(ValueError):
        mod.band_of(30)


def test_the_layer_sql_splits_the_lines_as_band_of_does() -> None:
    """The SQL ogr2ogr runs (SQLite dialect), on a table shaped like gdal_contour's output."""
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE contour (ele_m REAL, geom BLOB)")
    feet = mod.levels_ft(20, 2000)
    db.executemany("INSERT INTO contour VALUES (?, x'00')", [(m,) for m in mod.levels_m(feet)])
    seen: dict[int, str] = {}
    for band in mod.BANDS:
        for ele_ft, _geom in db.execute(mod.band_sql(band)):
            assert ele_ft not in seen, f"{ele_ft} ft in two layers"
            seen[ele_ft] = band.layer
    assert seen == {ft: mod.band_of(ft).layer for ft in feet}


def test_the_tiles_carry_each_layer_from_its_own_zoom() -> None:
    conf = mod.tile_conf()
    assert conf == {
        "c100": {"target_name": "c100", "minzoom": 10, "maxzoom": 14},
        "c40": {"target_name": "c40", "minzoom": 13, "maxzoom": 14},
        "c20": {"target_name": "c20", "minzoom": 14, "maxzoom": 14},
    }


def test_the_commands_trace_split_and_tile_through_a_temporary_name(tmp_path: Path) -> None:
    cells = [tmp_path / "a.tif", tmp_path / "b.tif"]
    cmds = mod.commands(tmp_path / "work", tmp_path / "out", cells)
    tools = [c[0] for c in cmds]
    assert tools == [
        "gdalbuildvrt",
        "gdal_translate",
        "gdal_contour",
        "ogr2ogr",
        "ogr2ogr",
        "ogr2ogr",
        "ogr2ogr",
    ]
    contour = cmds[2]
    levels = contour[contour.index("-fl") + 1 : -2]
    assert len(levels) == len(mod.levels_ft()) and float(levels[0]) == pytest.approx(6.096)
    assert "GEOMETRY_NAME=geom" in contour
    # The first band creates the GeoPackage, the others add to it.
    assert "-update" not in cmds[3] and "-update" in cmds[4] and "-update" in cmds[5]
    tiles = cmds[-1]
    assert tiles[tiles.index("-f") + 1] == "PMTiles"
    conf = next(o for o in tiles if o.startswith("CONF="))
    assert json.loads(conf.removeprefix("CONF=")) == mod.tile_conf()
    assert "MINZOOM=10" in tiles and "MAXZOOM=14" in tiles
    assert tiles[-2] == str(tmp_path / "out" / ".contours.pmtiles.part"), (
        "never half a file under the served name"
    )
    projwin = cmds[1][cmds[1].index("-projwin") + 1 : cmds[1].index("-projwin") + 5]
    west, south, east, north = mod.BBOX
    assert [float(v) for v in projwin] == [west, north, east, south]


def test_the_front_end_reads_the_same_layers_and_file() -> None:
    text = FRONTEND.read_text()
    for band in mod.BANDS:
        assert (
            f'{{ layer: "{band.layer}", intervalFt: {band.interval_ft}, minzoom: {band.minzoom} }}'
            in text
        )
    assert f'TOPO_PATH = "/basemap/{mod.OUTPUT_NAME}"' in text
    assert f"TOPO_MAX_ZOOM = {mod.MAXZOOM}" in text


def test_print_plan_needs_no_network(capsys: pytest.CaptureFixture[str]) -> None:
    assert mod.main(["--print-plan"]) == 0
    out = capsys.readouterr().out
    assert "n39w078" in out and "200 levels" in out


def test_the_work_directory_may_not_be_the_output_or_above_it(tmp_path: Path) -> None:
    """The work directory is deleted at the end (scripts/beta/ship-data.sh copies the whole
    basemap directory), so it may never be the basemap directory or one above it."""
    out = tmp_path / "basemap"
    for work in (out, tmp_path):
        with pytest.raises(SystemExit):
            mod.main(["--out", str(out), "--work", str(work)])
    assert not out.exists(), "refused before anything is made"
