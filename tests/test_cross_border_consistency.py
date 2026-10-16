"""The read-only cross-border consistency report (scripts/analysis/cross_border_consistency.py).

Two small counties meet at 77.0 W. Like roads near the line are compared by
length-weighted level; the report flags a gap of a step or more where each
side holds at least half a mile.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import sys

import pytest
from rebuild_fixtures import REPO

SCRIPT = REPO / "scripts" / "analysis" / "cross_border_consistency.py"


def box(name, west, east):
    return {
        "type": "Feature",
        "properties": {"name": name},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[west, 38.9], [east, 38.9], [east, 39.0], [west, 39.0], [west, 38.9]]],
        },
    }


AREAS = {
    "type": "FeatureCollection",
    "features": [box("Westco", -77.1, -77.0), box("Eastco", -77.0, -76.9)],
}

HEADER = "osm_way_id,tier,half,facility,road_speed_mph,road_lanes,road_oneway,is_trail_class,wkt"


def north_south(lon, south=38.92, north=38.9345):
    """About 1 mi (1.6 km) of road running north-south at `lon`."""
    return f'"LINESTRING({lon} {south}, {lon} {north})"'


ROWS = [
    # 30 mph two-lane roads, each about a mile, near the line: LTS 2 west, 3.5 east.
    f"1,2,f,none,30,2,f,f,{north_south(-77.005)}",
    f"2,3,t,none,31,2,f,f,{north_south(-76.995)}",
    # The same profile 3 mi (5 km) west of the line: out of reach, so not counted.
    f"3,5,f,none,30,2,f,f,{north_south(-77.06)}",
    # Painted lanes: rated alike on both sides.
    f"4,2,f,lane,25,2,f,f,{north_south(-77.004)}",
    f"5,2,t,lane,25,2,f,f,{north_south(-76.996)}",
    # Trails 1 vs 3, but only 0.2 mi on the east side: too little to judge.
    f"6,1,f,none,,,f,t,{north_south(-77.003)}",
    f"7,3,f,none,,,f,t,{north_south(-76.997, 38.92, 38.923)}",
]


@pytest.fixture(scope="module")
def report():
    spec = importlib.util.spec_from_file_location("cross_border_consistency", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def inputs(tmp_path):
    areas = tmp_path / "areas.geojson"
    areas.write_text(json.dumps(AREAS))
    segments = tmp_path / "segments.csv"
    segments.write_text("\n".join([HEADER, *ROWS]) + "\n")
    return segments, areas


def test_like_roads_a_step_apart_across_the_line_are_flagged(report, inputs) -> None:
    segments, areas = inputs
    project = report.projector(38.95)
    with segments.open(newline="") as handle:
        rows = report.load_segments(csv.DictReader(handle), project)
    found = report.compare(rows, report.load_areas(json.loads(areas.read_text()), "name", project))
    assert len(found) == 1
    (f,) = found
    assert (f.side_a, f.side_b) == ("Eastco", "Westco")
    assert f.profile == ("road", "none", 30, 2, False)
    # A half step counts as +0.5; the far-off LTS 5 is out of reach.
    assert (f.level_a, f.level_b) == (3.5, 2.0)
    assert (f.ways_a, f.ways_b) == ((2,), (1,))
    assert 0.95 < f.miles_a < 1.05


def test_a_smaller_gap_threshold_and_shorter_minimum_find_the_trail(report, inputs) -> None:
    segments, areas = inputs
    project = report.projector(38.95)
    with segments.open(newline="") as handle:
        rows = report.load_segments(csv.DictReader(handle), project)
    areas_m = report.load_areas(json.loads(areas.read_text()), "name", project)
    found = report.compare(rows, areas_m, min_m=0.1 * report.M_PER_MI)
    assert [f.profile[0] for f in found] == ["trail", "road"]
    assert found[0].gap == 2.0


def test_the_command_writes_markdown_and_csv_in_us_units_first(report, inputs, tmp_path) -> None:
    segments, areas = inputs
    out = tmp_path / "out"
    code = report.main(["--segments", str(segments), "--areas", str(areas), "--out", str(out)])
    assert code == 0
    text = (out / "cross-border.md").read_text()
    assert "Like roads within 2 mi (3.2 km) of a border" in text
    assert "1 finding(s)." in text
    assert "| Eastco / Westco | road, facility none, 30 mph (48 km/h), 2 lanes " in text
    assert "| LTS 3.5 over 1.00 mi (1.60 km) | LTS 2.0 over 1.00 mi (1.60 km) | 1.5 |" in text
    with (out / "cross-border.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [(r["side_a"], r["gap"], r["ways_a"], r["ways_b"]) for r in rows] == [
        ("Eastco", "1.50", "2", "1")
    ]
    assert 0.95 < float(rows[0]["miles_a"]) < 1.05
    assert 1.55 < float(rows[0]["km_a"]) < 1.65
