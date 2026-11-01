"""The bike racks' build step (scripts/build_bike_parking.py): what counts, DC first."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "build_bike_parking.py"

spec = importlib.util.spec_from_file_location("build_bike_parking", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["build_bike_parking"] = mod
spec.loader.exec_module(mod)


def test_ddot_feature_is_a_rack_with_its_count():
    r = mod.ddot_rack(
        {"attributes": {"OBJECTID": 7, "NUMBERRACKS": 3}, "geometry": {"x": -77.03, "y": 38.9}}
    )
    assert r == mod.Rack(id="dc7", lon=-77.03, lat=38.9, racks=3)
    assert (
        mod.ddot_rack(
            {
                "attributes": {"OBJECTID": 8, "NUMBERRACKS": None},
                "geometry": {"x": -77.03, "y": 38.9},
            }
        ).racks
        is None
    )
    assert mod.ddot_rack({"attributes": {"OBJECTID": 9}, "geometry": {}}) is None
    assert (
        mod.ddot_rack({"attributes": {"OBJECTID": 9}, "geometry": {"x": -80.0, "y": 38.9}}) is None
    )


def test_osm_public_racks_only_in_use():
    at = (-77.1, 38.95)
    assert mod.osm_rack("n1", {"amenity": "bicycle_parking"}, *at).kind == "s"
    lockers = mod.osm_rack(
        "n2",
        {
            "amenity": "bicycle_parking",
            "bicycle_parking": "lockers",
            "capacity": "12",
            "covered": "yes",
            "name": " Station ",
        },
        *at,
    )
    assert (lockers.kind, lockers.capacity, lockers.covered, lockers.name) == (
        "l",
        12,
        True,
        "Station",
    )
    assert (
        mod.osm_rack("n3", {"amenity": "bicycle_parking", "bicycle_parking": "shed"}, *at).kind
        == "b"
    )
    assert (
        mod.osm_rack("n4", {"amenity": "bicycle_parking", "access": "permissive"}, *at) is not None
    )
    # Unclear access is closed, as for water and restrooms.
    for access in ("private", "customers", "no", "permit"):
        assert mod.osm_rack("n5", {"amenity": "bicycle_parking", "access": access}, *at) is None
    assert mod.osm_rack("n6", {"amenity": "bicycle_parking", "disused": "yes"}, *at) is None
    assert mod.osm_rack("n7", {"amenity": "bench"}, *at) is None
    assert (
        mod.osm_rack("n8", {"amenity": "bicycle_parking", "capacity": "lots"}, *at).capacity is None
    )


def test_dc_wins_within_25_m():
    ddot = [mod.Rack(id="dc1", lon=-77.03, lat=38.9)]
    same = mod.Rack(id="n1", lon=-77.0302, lat=38.9)  # about 17 m
    apart = mod.Rack(id="n2", lon=-77.0305, lat=38.9)  # about 43 m
    assert [r.id for r in mod.drop_same([same, apart], ddot)] == ["n2"]


def test_file_round_trip_keeps_the_other_source(tmp_path: Path):
    out = tmp_path / "bike-parking.json"
    doc = mod.document(
        [mod.Rack(id="dc2", lon=-77.03, lat=38.9, racks=2)],
        [mod.Rack(id="n9", lon=-77.2, lat=39.0, kind="l", capacity=4)],
    )
    mod.write_document(doc, out)
    data = json.loads(out.read_text())
    assert data["source"] == f"{mod.SOURCE_DDOT}; {mod.SOURCE_OSM}"
    assert data["points"] == [
        {"id": "dc2", "x": -77.03, "y": 38.9, "r": 2},
        {"id": "n9", "x": -77.2, "y": 39.0, "c": 4, "k": "l"},
    ]
    kept = [mod.from_point(p) for p in data["points"]]
    assert kept[0].id == "dc2" and kept[1].kind == "l"


def test_committed_file_is_ddot_and_in_the_box():
    data = json.loads(mod.OUT.read_text())
    assert "CC BY 4.0" in data["source"]
    assert len(data["points"]) > 4000
    for p in data["points"]:
        assert mod.inside(p["x"], p["y"])
