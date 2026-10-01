"""Installing the agency street layers, and loading what was installed.

The script is run as an operator would run it, on layers shaped as
`scripts/fetch_agency_layer.py` stores them; the result is read back with the
production loader (`ReferenceData.load_road_blocks`) and conflated, so a field
the installer writes and the loader cannot read fails here.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys

import pytest
from rebuild_fixtures import REPO

from pipeline.conflation import conflate_blocks
from pipeline.run import ReferenceData
from routemaker import agency_roads as A

SCRIPT = REPO / "scripts" / "install_reference_data.py"

K_STREET = [[-77.0560, 38.9025], [-77.0540, 38.9025]]
CHARLES = [[-76.6150, 39.2900], [-76.6150, 39.2920]]


def collection(features: list[dict]) -> str:
    return json.dumps({"type": "FeatureCollection", "features": features})


def dc_feature(object_id: int, geometry: dict, **properties) -> dict:
    record = {
        "OBJECTID": object_id,
        "ROUTENAME": "K ST NW",
        "TOTALTRAVELLANESINBOUND": 1,
        "TOTALTRAVELLANESOUTBOUND": 1,
        "TOTALTRAVELLANES": 2,
        "TOTALPARKINGLANES": 0,
        "SPEEDLIMITS_OB": 25,
        "SUMMARYDIRECTION": "BD",
    }
    record.update(properties)
    return {"type": "Feature", "id": object_id, "geometry": geometry, "properties": record}


def line(coordinates) -> dict:
    return {"type": "LineString", "coordinates": coordinates}


def baltimore_feature(object_id: int, geometry: dict, **properties) -> dict:
    record = {
        "OBJECTID": object_id,
        "feanme": "CHARLES",
        "featype": "ST",
        "subtype": "STRPRD",
        "feat_status": "A",
        "drivable": "Y",
        "speed": 25,
    }
    record.update(properties)
    return {"type": "Feature", "geometry": geometry, "properties": record}


def install(tmp_path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--data-root", str(tmp_path / "data"), *args],
        capture_output=True,
        text=True,
    )


@pytest.fixture
def layers(tmp_path):
    dc = tmp_path / "dc.geojson"
    dc.write_text(
        collection(
            [
                dc_feature(1, line(K_STREET)),
                # A block carrying nothing the classifier reads is not stored.
                dc_feature(
                    2,
                    line([[-77.0, 38.9], [-77.001, 38.9]]),
                    TOTALTRAVELLANES=0,
                    TOTALTRAVELLANESINBOUND=0,
                    TOTALTRAVELLANESOUTBOUND=0,
                    TOTALPARKINGLANES=None,
                    SPEEDLIMITS_OB=None,
                    SUMMARYDIRECTION=None,
                ),
            ]
        )
    )
    balt = tmp_path / "balt.geojson"
    balt.write_text(
        collection(
            [
                baltimore_feature(1, line(CHARLES)),
                baltimore_feature(2, line(CHARLES), feat_status="P"),
                baltimore_feature(3, line(CHARLES), drivable="N"),
                baltimore_feature(4, line(CHARLES), speed=1),
                baltimore_feature(
                    5,
                    {"type": "MultiLineString", "coordinates": [CHARLES, K_STREET]},
                    oneway="FT",
                ),
            ]
        )
    )
    return dc, balt


def test_the_installer_writes_the_blocks_the_loader_reads(tmp_path, layers) -> None:
    dc, balt = layers
    done = install(tmp_path, "--roadway-block", str(dc), "--baltimore-centerline", str(balt))
    assert "street blocks" in done.stdout
    path = tmp_path / "data" / "reference" / "roadway.json"
    blocks = ReferenceData.load_road_blocks(path)
    ids = {block.feature_id for block in blocks}
    # DC block 1, Baltimore 1 (speed), 5 twice (one-way, two parts); the rest dropped.
    assert ids == {"dc-1-0", "baltimore-1-0", "baltimore-5-0", "baltimore-5-1"}
    by_id = {block.feature_id: block for block in blocks}
    assert by_id["dc-1-0"].facts == A.parse_dc_roadway_block(layers_properties(dc, 1))
    assert by_id["dc-1-0"].facts.parking_lanes == 0, "no parking is recorded, not omitted"
    assert by_id["baltimore-5-1"].facts.way == "one"
    assert by_id["baltimore-1-0"].facts.speed_mph == {"centerline": 25}


def layers_properties(path, object_id: int) -> dict:
    for feature in json.loads(path.read_text())["features"]:
        if feature["properties"]["OBJECTID"] == object_id:
            return feature["properties"]
    raise AssertionError(object_id)


def test_what_is_installed_conflates_onto_a_way_along_it(tmp_path, layers) -> None:
    dc, balt = layers
    install(tmp_path, "--roadway-block", str(dc))
    blocks = ReferenceData.load_road_blocks(tmp_path / "data" / "reference" / "roadway.json")
    way = (7, [(-77.0558, 38.90252), (-77.0542, 38.90252)], False)
    result = conflate_blocks([way], blocks, {7: "K Street Northwest"})
    assert [share.feature_id for share in result.matched[7]] == ["dc-1-0"]


def test_without_a_street_flag_no_file_is_written(tmp_path) -> None:
    install(tmp_path)
    assert not (tmp_path / "data" / "reference" / "roadway.json").exists()


def test_one_layer_alone_is_installed(tmp_path, layers) -> None:
    _dc, balt = layers
    install(tmp_path, "--baltimore-centerline", str(balt))
    blocks = ReferenceData.load_road_blocks(tmp_path / "data" / "reference" / "roadway.json")
    assert {block.facts.agency for block in blocks} == {A.BALTIMORE_AGENCY}


def test_two_blocks_with_one_object_id_are_refused(tmp_path) -> None:
    dc = tmp_path / "dc.geojson"
    dc.write_text(collection([dc_feature(1, line(K_STREET)), dc_feature(1, line(K_STREET))]))
    done = install(tmp_path, "--roadway-block", str(dc))
    assert done.returncode == 2
    assert "share an id" in done.stderr


def test_the_loader_warns_and_returns_nothing_where_no_blocks_are_installed(
    tmp_path, caplog
) -> None:
    with caplog.at_level(logging.WARNING, logger="pipeline.run"):
        blocks = ReferenceData.load_road_blocks(tmp_path / "roadway.json")
    assert blocks == ()
    assert "roadway.json is absent" in caplog.text
