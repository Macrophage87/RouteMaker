"""The beach path along the tide line (`routemaker.beaches`, `pipeline.beaches`; the owner,
2026-11-23: "you can ride your bike on the beach here, but generally only adviseable in low
tide below the high tide lines"; "we'd have that as a specific beach biking path")."""

from __future__ import annotations

import osmium
import pytest
from shapely.geometry import Polygon

from pipeline import beaches as read_beaches
from pipeline.extract import Way
from routemaker import beaches

# A straight north-south shore at Bonita Beach, the Gulf to the west; one point every ~111 m.
LON = -81.85
SHORE = [(LON, 26.30 + i * 0.001) for i in range(11)]
# The beach lies between the shore and 60 m inland, from the 3rd point to the 8th.
BEACH = Polygon([(LON, 26.302), (LON + 0.0006, 26.302), (LON + 0.0006, 26.307), (LON, 26.307)])


def test_the_tide_line_is_the_coastline_beside_a_beach() -> None:
    flags = beaches.beside_beach(SHORE, [BEACH])
    assert flags == [False, False, True, True, True, True, True, True, False, False, False]
    run = beaches.longest_run(SHORE, flags)
    assert (run.start, run.stop) == (2, 7)
    assert run.length_m == pytest.approx(556, abs=5)


def test_a_short_stretch_is_not_a_path() -> None:
    flags = [False, True, True, False, False, False, False, False, False, False, False]
    assert beaches.longest_run(SHORE, flags).length_m == pytest.approx(111, abs=1)
    assert beaches.longest_run(SHORE, flags, min_m=200) is None
    assert beaches.longest_run(SHORE, [True] + [False] * 10) is None  # one point is no line


def test_of_two_stretches_the_longer_is_kept_and_both_are_counted() -> None:
    flags = [True, True, False, True, True, True, True, False, False, False, False]
    run = beaches.longest_run(SHORE, flags)
    assert (run.start, run.stop) == (3, 6)
    assert beaches.runs_length_m(SHORE, flags) == pytest.approx(4 * 111.3, abs=5)


def test_a_beach_closed_to_bicycles_is_not_ridden() -> None:
    assert beaches.closed_to_bicycles({"natural": "beach", "bicycle": "no"})
    assert beaches.closed_to_bicycles({"natural": "beach", "access": "private"})
    assert not beaches.closed_to_bicycles({"natural": "beach", "name": "Bonita Beach"})


def test_a_beach_access_is_carried_on_to_the_tide_line() -> None:
    tide = [(100 + i, lon, lat) for i, (lon, lat) in enumerate(SHORE[2:8])]
    inland_end = (LON + 0.0006, 26.3041)  # the boardwalk's end at the beach's inland edge
    far_end = (LON + 0.01, 26.3041)  # a kilometre inland: not on the beach
    joins = beaches.access_joins(
        [(7, False, 70, inland_end), (8, True, 80, far_end), (9, True, 103, SHORE[3])],
        [BEACH],
        tide,
    )
    assert [(j.way_id, j.at_start, j.node_id) for j in joins] == [(7, False, 102)]


def _write_extract(path, beach_tags=None) -> None:
    writer = osmium.SimpleWriter(str(path))
    try:
        for i, (lon, lat) in enumerate(SHORE):
            writer.add_node(osmium.osm.mutable.Node(id=1 + i, location=(lon, lat), version=1))
        corners = [
            (LON, 26.302),
            (LON + 0.0006, 26.302),
            (LON + 0.0006, 26.307),
            (LON, 26.307),
        ]
        for i, (lon, lat) in enumerate(corners):
            writer.add_node(osmium.osm.mutable.Node(id=50 + i, location=(lon, lat), version=1))
        writer.add_node(osmium.osm.mutable.Node(id=60, location=(LON + 0.003, 26.3041), version=1))
        writer.add_node(osmium.osm.mutable.Node(id=61, location=(LON + 0.0006, 26.3041), version=1))
        writer.add_way(
            osmium.osm.mutable.Way(
                id=1000, nodes=list(range(1, 12)), tags={"natural": "coastline"}, version=1
            )
        )
        writer.add_way(
            osmium.osm.mutable.Way(
                id=2000,
                nodes=[50, 51, 52, 53, 50],
                tags={"natural": "beach", "name": "Bonita Beach", **(beach_tags or {})},
                version=1,
            )
        )
        writer.add_way(
            osmium.osm.mutable.Way(id=3000, nodes=[60, 61], tags={"highway": "footway"}, version=1)
        )
    finally:
        writer.close()


def _access_way() -> Way:
    way = Way(osm_id=3000, tags={"highway": "footway"}, node_ids=[60, 61])
    way.coordinates = [(LON + 0.003, 26.3041), (LON + 0.0006, 26.3041)]
    way.located = [0, 1]
    return way


BOX = (-82.75, 25.65, -80.70, 27.45)


def test_the_extract_gives_a_sand_path_on_the_tide_line_joined_to_the_boardwalk(tmp_path) -> None:
    pbf = tmp_path / "x.osm.pbf"
    _write_extract(pbf)
    access = _access_way()
    found = read_beaches.read(pbf, [BOX], [access])
    assert [b.name for b in found.beaches] == ["Bonita Beach"]
    (path,) = found.paths
    assert path.osm_id == 1000
    assert path.node_ids == [3, 4, 5, 6, 7, 8]
    assert path.source_tags == {"natural": "coastline"}
    assert path.tags["highway"] == "path" and path.tags["surface"] == "sand"
    assert path.tags["bicycle"] == "yes"
    assert [(j.way_id, j.node_id) for j in found.joins] == [(3000, 5)]
    changed = read_beaches.apply_joins({3000: access}, found.joins)
    assert changed == {3000}
    assert access.node_ids == [60, 61, 5]
    assert access.located_points()[-1] == (2, LON, pytest.approx(26.304))
    assert "1 beach paths" in read_beaches.summary(found)


def test_no_path_beside_a_beach_closed_to_bicycles_or_outside_the_box(tmp_path) -> None:
    pbf = tmp_path / "x.osm.pbf"
    _write_extract(pbf, {"bicycle": "no"})
    assert read_beaches.read(pbf, [BOX]).paths == []
    pbf2 = tmp_path / "y.osm.pbf"
    _write_extract(pbf2)
    home = (-78.05, 38.2, -76.02, 39.72)
    assert read_beaches.read(pbf2, [home]).paths == []
    assert read_beaches.read(pbf2, []).paths == []


def test_the_map_file_holds_the_beach_and_its_path(tmp_path) -> None:
    import importlib.util
    import json
    import sys
    from pathlib import Path

    from django.conf import settings

    script = Path(__file__).resolve().parents[1] / "scripts/build_beaches.py"
    spec = importlib.util.spec_from_file_location("build_beaches", script)
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_beaches"] = module
    spec.loader.exec_module(module)
    assert module.SOUTHWEST_FLORIDA_BBOX == tuple(settings.SOUTHWEST_FLORIDA_BBOX)
    pbf = tmp_path / "x.osm.pbf"
    _write_extract(pbf)
    out = tmp_path / "beaches.json"
    assert module.main(["--pbf", str(pbf), "--out", str(out)]) == 0
    features = json.loads(out.read_text())["features"]
    assert [(f["properties"]["kind"], f["geometry"]["type"]) for f in features] == [
        ("beach", "Polygon"),
        ("path", "LineString"),
    ]
    assert features[0]["properties"]["name"] == "Bonita Beach"
    assert features[1]["properties"]["way"] == 1000


def test_a_coastline_way_that_is_a_highway_already_is_left_as_it_is(tmp_path) -> None:
    pbf = tmp_path / "x.osm.pbf"
    _write_extract(pbf)
    promenade = Way(
        osm_id=1000,
        tags={"natural": "coastline", "highway": "footway"},
        node_ids=list(range(1, 12)),
    )
    promenade.coordinates = list(SHORE)
    promenade.located = list(range(11))
    assert read_beaches.read(pbf, [BOX], [promenade]).paths == []
