"""The federal-land overlay's build step (scripts/build_federal_land.py).

Synthetic layers check the rules (the more specific kind wins where kinds
overlap, GSA and retired lots are left out, names and agencies), and the
checked-in file the front end loads is held to the GeoJSON it must be.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest
from rebuild_fixtures import REPO
from shapely.geometry import Point, shape

SCRIPT = REPO / "scripts" / "build_federal_land.py"
CHECKED_IN = REPO / "frontend" / "src" / "federal-data" / "federal-land.json"

spec = importlib.util.spec_from_file_location("build_federal_land", SCRIPT)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules["build_federal_land"] = mod
spec.loader.exec_module(mod)


def square(x: float, y: float, size: float = 0.002) -> dict:
    """A square near the Mall, about 170 m a side by default."""
    x0, y0 = -77.03 + x, 38.89 + y
    ring = [[x0, y0], [x0 + size, y0], [x0 + size, y0 + size], [x0, y0 + size], [x0, y0]]
    return {"type": "Polygon", "coordinates": [ring]}


def feature(geometry: dict, **props) -> dict:
    return {"type": "Feature", "properties": props, "geometry": geometry}


def collection(*features: dict) -> dict:
    return {"type": "FeatureCollection", "features": list(features)}


def write(path: Path, *features: dict) -> Path:
    path.write_text(json.dumps(collection(*features)), encoding="utf-8")
    return path


@pytest.fixture
def inputs(tmp_path: Path) -> Namespace:
    return Namespace(
        nps=write(
            tmp_path / "nps.json",
            feature(square(0, 0), NAME="Mall", SOURCE="NPS", RESERVE="0332"),
            feature(square(0.01, 0), NAME="Triangle", SOURCE="NPS", RESERVE="0077"),
            feature(square(0.02, 0), NAME=None, LABEL="Glover Parkway", SOURCE=None, RESERVE=None),
            feature(square(0.03, 0), NAME=None, LABEL=None, SOURCE="NPS", RESERVE="0104"),
        ),
        reservations=write(
            tmp_path / "res.json",
            # inside the Mall polygon: clipped away entirely
            feature(square(0.0005, 0.0005, 0.0005), RES="0332", KILL_DT=None),
            # beside it: kept
            feature(square(0.05, 0), RES="0064A", KILL_DT=None),
            # retired: left out
            feature(square(0.06, 0), RES="0099", KILL_DT=1_000_000),
        ),
        military=write(
            tmp_path / "mil.json",
            # overlaps the Mall's east half: the military kind wins there
            feature(square(0.001, 0), NAME="Fort Example"),
        ),
        capitol=write(tmp_path / "cap.json", feature(square(0.07, 0))),
        federal=None,
    )


def build(inputs: Namespace) -> list[dict]:
    return mod.build(mod.collect(inputs))["features"]


def by_name(features: list[dict], name: str) -> list[dict]:
    return [f for f in features if f["properties"]["name"] == name]


def test_every_area_has_a_known_kind_and_a_name(inputs):
    features = build(inputs)
    assert features
    for f in features:
        assert f["properties"]["kind"] in mod.KINDS
        assert f["properties"]["name"]
        assert shape(f["geometry"]).is_valid


def test_the_kinds_the_inputs_make(inputs):
    kinds = {f["properties"]["kind"] for f in build(inputs)}
    assert kinds == {"capitol", "military", "nps", "reservation"}


def test_the_more_specific_kind_wins_where_they_overlap(inputs):
    features = build(inputs)
    military = shape(by_name(features, "Fort Example")[0]["geometry"])
    mall = shape(by_name(features, "Mall")[0]["geometry"])
    assert military.intersection(mall).area < 1e-12, "the Mall is clipped around the base"
    assert mall.area > 0
    # a point in the overlap belongs to the base alone
    inside = Point(-77.03 + 0.0015, 38.89 + 0.001)
    owners = [f["properties"]["name"] for f in features if shape(f["geometry"]).covers(inside)]
    assert owners == ["Fort Example"]


def test_a_reservation_inside_a_park_is_not_drawn_twice(inputs):
    names = [f["properties"]["name"] for f in build(inputs)]
    assert "U.S. Reservation 332" not in names
    assert "U.S. Reservation 64A" in names


def test_a_retired_reservation_lot_is_left_out(inputs):
    assert not by_name(build(inputs), "U.S. Reservation 99")


def test_park_names_and_agencies(inputs):
    features = build(inputs)
    assert by_name(features, "Mall")[0]["properties"]["agency"] == "National Park Service"
    # a generic name gets its reservation number, so a popup can tell triangles apart
    assert by_name(features, "Triangle (Reservation 77)")
    # a missing name falls back to the label; a missing source does not claim the NPS
    glover = by_name(features, "Glover Parkway")[0]["properties"]
    assert "agency" in glover and glover["agency"] != "National Park Service"
    assert by_name(features, "National Park Service land (Reservation 104)")


def test_military_names_no_agency_the_source_does_not_give(inputs):
    assert "agency" not in by_name(build(inputs), "Fort Example")[0]["properties"]


def test_the_capitol_names_the_architect_of_the_capitol(inputs):
    cap = by_name(build(inputs), "U.S. Capitol grounds")[0]["properties"]
    assert cap == {
        "kind": "capitol",
        "name": "U.S. Capitol grounds",
        "agency": "Architect of the Capitol",
    }


def test_gsa_buildings_are_left_out_of_an_optional_federal_layer(inputs, tmp_path):
    inputs.federal = write(
        tmp_path / "fed.json",
        feature(square(0.1, 0), OWNERNAME="UNITED STATES OF AMERICA GSA", PREMISEADD="1 MAIN ST"),
        feature(
            square(0.11, 0), OWNERNAME="GENERAL SERVICES ADMINISTRATION", PREMISEADD="2 MAIN ST"
        ),
        feature(square(0.12, 0), OWNERNAME="DEPARTMENT OF THE INTERIOR", PREMISEADD="3 MAIN ST"),
    )
    federal = [f for f in build(inputs) if f["properties"]["kind"] == "federal"]
    assert [f["properties"]["name"] for f in federal] == ["3 MAIN ST"]
    assert federal[0]["properties"]["agency"] == "Department Of The Interior"


def test_slivers_are_dropped_and_geometry_is_simplified(inputs, tmp_path):
    inputs.reservations = write(
        tmp_path / "res2.json", feature(square(0.2, 0, 0.00002), RES="0001", KILL_DT=None)
    )
    assert not by_name(build(inputs), "U.S. Reservation 1"), "a 2 m square is a sliver"
    wiggly = [[-77.03 + i * 0.0002, 38.89 + (0.00002 if i % 2 else 0)] for i in range(10)]
    ring = [*wiggly, [-77.03 + 0.002, 38.892], [-77.03, 38.892], wiggly[0]]
    inputs.nps = write(
        tmp_path / "nps2.json",
        feature({"type": "Polygon", "coordinates": [ring]}, NAME="Wiggle", SOURCE="NPS"),
    )
    out = by_name(build(inputs), "Wiggle")[0]["geometry"]["coordinates"][0]
    assert len(out) <= 6, "the survey wiggle within 3 m is simplified away"


def test_the_script_writes_valid_geojson_with_a_kind(inputs, tmp_path):
    out = tmp_path / "out" / "federal-land.json"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--nps",
            str(inputs.nps),
            "--reservations",
            str(inputs.reservations),
            "--military",
            str(inputs.military),
            "--capitol",
            str(inputs.capitol),
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["type"] == "FeatureCollection" and data["features"]
    assert all(f["properties"]["kind"] in mod.KINDS for f in data["features"])
    assert out.read_text(encoding="utf-8") == out.read_text(encoding="utf-8").strip() + "\n"
    again = tmp_path / "again.json"
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--nps",
            str(inputs.nps),
            "--reservations",
            str(inputs.reservations),
            "--military",
            str(inputs.military),
            "--capitol",
            str(inputs.capitol),
            "--out",
            str(again),
        ],
        check=True,
        capture_output=True,
    )
    assert again.read_bytes() == out.read_bytes(), "the same inputs give the same file"


# ---------- the file the front end loads ----------


@pytest.fixture(scope="module")
def checked_in() -> dict:
    return json.loads(CHECKED_IN.read_text(encoding="utf-8"))


def kinds_at(data: dict, lon: float, lat: float) -> list[str]:
    point = Point(lon, lat)
    return [f["properties"]["kind"] for f in data["features"] if shape(f["geometry"]).covers(point)]


def test_the_checked_in_file_is_valid_geojson_with_kinds(checked_in):
    assert checked_in["type"] == "FeatureCollection"
    kinds = set()
    for f in checked_in["features"]:
        assert f["properties"]["kind"] in mod.KINDS
        assert f["properties"]["name"].strip()
        geom = shape(f["geometry"])
        assert geom.is_valid and not geom.is_empty
        minx, miny, maxx, maxy = geom.bounds
        assert -77.2 < minx and maxx < -76.9 and 38.78 < miny and maxy < 39.0, "inside the District"
        kinds.add(f["properties"]["kind"])
    assert kinds == {"capitol", "military", "nps", "reservation"}


def test_known_places_are_where_they_should_be(checked_in):
    assert kinds_at(checked_in, -77.0090, 38.8899) == ["capitol"], "the Capitol"
    assert kinds_at(checked_in, -77.0353, 38.8895) == ["nps"], "the Washington Monument grounds"
    assert kinds_at(checked_in, -77.0366, 38.8977) == ["nps"], "President's Park"
    assert kinds_at(checked_in, -77.0170, 38.8350) == ["military"], "Joint Base Anacostia-Bolling"
    assert kinds_at(checked_in, -77.0209, 38.8981) == [], "Capital One Arena is not federal land"


def test_no_patch_is_shaded_twice(checked_in):
    shapes = [(f["properties"]["kind"], shape(f["geometry"])) for f in checked_in["features"]]
    military = [g for k, g in shapes if k == "military"]
    capitol = [g for k, g in shapes if k == "capitol"]
    nps = [g for k, g in shapes if k == "nps"]
    for lower, upper in ((nps, military + capitol), (military, capitol)):
        for a in lower:
            for b in upper:
                assert a.intersection(b).area < 1e-9


def test_the_file_is_small(checked_in):
    assert CHECKED_IN.stat().st_size < 700_000
