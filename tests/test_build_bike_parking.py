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
    assert len(data["points"]) > 3500
    for p in data["points"]:
        assert mod.inside(p["x"], p["y"])


def test_a_row_of_racks_is_one_place():
    row = [mod.Rack(id=f"dc{i}", lon=-77.03 + i * 0.00002, lat=38.9, racks=1) for i in range(5)]
    far = mod.Rack(id="dc9", lon=-77.0295, lat=38.9, racks=2)  # about 43 m on
    merged = mod.one_place([*row, far])
    assert [(r.id, r.racks) for r in merged] == [("dc0", 5), ("dc9", 2)]
    assert abs(merged[0].lon - (-77.03 + 0.00004)) < 1e-9
    # A count missing on one rack of the row: no count rather than too few.
    part = mod.one_place(
        [
            mod.Rack(id="dc1", lon=-77.03, lat=38.9, racks=2),
            mod.Rack(id="dc2", lon=-77.03, lat=38.9),
        ]
    )
    assert part[0].racks is None


def test_baltimore_installed_racks_only_and_no_contacts():
    at = {"x": -76.61, "y": 39.29}
    r = mod.baltimore_installed(
        {"attributes": {"OBJECTID": 3, "Installed": "Yes", "Rack_Count": "2"}, "geometry": at}
    )
    assert r == mod.Rack(id="bc3", lon=-76.61, lat=39.29, racks=2)
    no = {"attributes": {"OBJECTID": 4, "Installed": "No"}, "geometry": at}
    assert mod.baltimore_installed(no) is None
    # The layer holds requesters' names and contacts: the fetch never asks for them.
    import inspect

    fetch = inspect.getsource(mod.fetch_baltimore)
    assert '"OBJECTID,Installed,Rack_Count"' in fetch and "Own" not in fetch


def test_baltimore_corrals_need_bike_racks():
    at = {"x": -76.63, "y": 39.28}
    assert (
        mod.baltimore_corral({"attributes": {"FID": 1, "Rack_Count": 3}, "geometry": at}).racks == 3
    )
    assert mod.baltimore_corral({"attributes": {"FID": 2, "Rack_Count": 0}, "geometry": at}) is None


def test_baltimore_inventory_from_web_mercator():
    web_map = {
        "operationalLayers": [
            {
                "title": "Bike Racks Additional",
                "featureCollection": {
                    "layers": [
                        {
                            "featureSet": {
                                "features": [
                                    {"attributes": {"FID": 0}},
                                    {
                                        "geometry": {"x": -8528454, "y": 4763536},
                                        "attributes": {"FID": 2, "RACK_COUNT": 3, "COVERED": "Y"},
                                    },
                                ]
                            }
                        }
                    ]
                },
            }
        ]
    }
    racks = [r for r in map(mod.baltimore_inventory, mod.inventory_features(web_map)) if r]
    assert len(racks) == 1
    r = racks[0]
    assert (r.id, r.racks, r.covered) == ("ba2", 3, True)
    assert abs(r.lon - -76.6125) < 0.001 and abs(r.lat - 39.2918) < 0.001


def test_baltimore_installed_beats_corral_beats_inventory():
    bc = mod.Rack(id="bc1", lon=-76.61, lat=39.29, racks=1)
    bs = mod.Rack(id="bs1", lon=-76.6101, lat=39.29, racks=2)  # about 9 m from bc1
    ba = mod.Rack(id="ba1", lon=-76.6102, lat=39.29)  # about 17 m from bc1
    far = mod.Rack(id="ba2", lon=-76.62, lat=39.29)
    assert [r.id for r in mod.baltimore([bc], [bs], [ba, far])] == ["bc1", "ba2"]


def test_a_city_rack_beats_an_osm_stand_but_not_lockers():
    bc = mod.Rack(id="bc1", lon=-76.61, lat=39.29)
    stand = mod.Rack(id="n1", lon=-76.6101, lat=39.29, kind="s")
    room = mod.Rack(id="n2", lon=-76.6101, lat=39.29, kind="b")
    doc = mod.document([], [stand, room], [bc])
    assert [p["id"] for p in doc["points"]] == ["bc1", "n2"]
    assert "Baltimore City Department of Transportation" in doc["source"]
    assert mod.city("bc1") == "bc" and mod.city("n1") is None
