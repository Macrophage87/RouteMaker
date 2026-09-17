"""The reference-data producers, and that what they produce is what the
rebuild loads.

`ReferenceData.load` read `<DATA_ROOT>/reference/{urban-areas,crossings,volume}.json`
and nothing in the repository, compose or docs put anything there: the
crossings fixture was checked in and installed by nothing, and the other two
had no producer. The test runs the script as an operator would and then loads
the result with the production loader.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from rebuild_fixtures import REPO, build_toy_extract

SCRIPT = REPO / "scripts" / "install_reference_data.py"


def geojson(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": features}


def test_the_script_installs_every_file_the_loader_requires(tmp_path) -> None:
    from pipeline.extract import read_ways
    from pipeline.run import ReferenceData

    extract = tmp_path / "source.osm.pbf"
    build_toy_extract(extract)

    # An urban area covering the trail and the track but not the road.
    urban = tmp_path / "urban.geojson"
    urban.write_text(
        json.dumps(
            geojson(
                [
                    {
                        "type": "Feature",
                        "properties": {"NAME20": "Washington, DC--VA--MD"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [-77.05, 38.905],
                                    [-77.025, 38.905],
                                    [-77.025, 38.93],
                                    [-77.05, 38.93],
                                    [-77.05, 38.905],
                                ]
                            ],
                        },
                    }
                ]
            )
        )
    )
    volume = tmp_path / "volume.geojson"
    volume.write_text(
        json.dumps(
            geojson(
                [
                    {
                        "type": "Feature",
                        "properties": {"OBJECTID": 7, "AADT": "12500"},
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[-77.02, 38.90], [-76.98, 38.90]],
                        },
                    },
                    {
                        "type": "Feature",
                        "properties": {"OBJECTID": 8, "AADT": None},
                        "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
                    },
                ]
            )
        )
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--data-root",
            str(tmp_path / "data"),
            "--extract",
            str(extract),
            "--urban-areas",
            str(urban),
            "--volume",
            str(volume),
            "--volume-source",
            "vdot",
            "--volume-year",
            "2024",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    reference = tmp_path / "data" / "reference"
    assert (reference / "crossings.json").read_bytes() == (
        REPO / "fixtures" / "crossings" / "potomac-anacostia.json"
    ).read_bytes()

    ways = read_ways(extract)
    loaded = ReferenceData.load(reference, ways)
    assert loaded.urban_way_ids == {200, 300, 400, 500}, "the road outside the area is rural"
    assert len(loaded.volume_features) == 1, "a count with no AADT is not a count"
    feature = loaded.volume_features[0]
    assert (feature.aadt, feature.source, feature.year) == (12500, "vdot", 2024)
    assert feature.coordinates == [(-77.02, 38.90), (-76.98, 38.90)]
    assert loaded.unmatched_crossings, "the toy extract has none of the real bridges"


def test_without_inputs_the_script_installs_the_fixture_and_names_what_is_missing(tmp_path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--data-root", str(tmp_path)], capture_output=True, text=True
    )
    assert result.returncode == 1
    assert (tmp_path / "reference" / "crossings.json").exists()
    assert "MISSING" in result.stderr and "urban-areas.json" in result.stderr
    assert "volume.json" in result.stderr
    assert Path(tmp_path / "reference" / "volume.json").exists() is False


def test_the_loader_separates_unmatched_crossings_from_unverified_names(tmp_path, caplog) -> None:
    """Two warnings, not one. "Not found in the extract" means the sidepath rule
    is inert on that bridge - the clip moved, or the name changed. "Found, but
    nobody has confirmed the spelling" means the match is believed rather than
    checked, which is the state every row in the shipped fixture is in while
    Overpass is blocked. An operator can act on the first and can only queue the
    second, so folding them into one line hides the distinction the fixture's
    `osm_names_verified` column exists to record.

    `unverified_crossing_names` existed and nothing called it.
    """
    import logging

    from pipeline.extract import read_ways
    from pipeline.run import ReferenceData

    extract = tmp_path / "source.osm.pbf"
    build_toy_extract(extract)

    reference = tmp_path / "reference"
    reference.mkdir()
    (reference / "urban-areas.json").write_text("[]")
    (reference / "volume.json").write_text("[]")
    (reference / "crossings.json").write_bytes(
        (REPO / "fixtures" / "crossings" / "potomac-anacostia.json").read_bytes()
    )

    with caplog.at_level(logging.WARNING, logger="pipeline.run"):
        ReferenceData.load(reference, read_ways(extract))

    messages = [record.getMessage() for record in caplog.records]
    unmatched = [m for m in messages if "not found in the extract" in m]
    unverified = [m for m in messages if "not yet verified" in m]
    assert len(unmatched) == 1, messages
    assert len(unverified) == 1, messages
    assert unmatched[0] != unverified[0]
    # Arlington Memorial Bridge is not sidepath-only, so it is never in the
    # unmatched list whatever the extract carries - and it is unverified like
    # every other row. The two lists answer different questions and this is the
    # row that shows it.
    assert "Arlington Memorial Bridge" not in unmatched[0]
    assert "Arlington Memorial Bridge" in unverified[0]
