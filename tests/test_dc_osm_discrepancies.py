"""The DC-against-OSM discrepancy report (scripts/analysis/dc_osm_discrepancies.py).

OWNER-DECISIONS 191: "report the discrepancies when you see them". Each way where the
District's record and OSM's tags disagree is listed by type, with whether the District's
value was applied (OWNER-DECISIONS 190) or not, and why not.
"""

from __future__ import annotations

import csv
import importlib.util
import json

import pytest
from rebuild_fixtures import REPO

SCRIPT = REPO / "scripts" / "analysis" / "dc_osm_discrepancies.py"


@pytest.fixture(scope="module")
def report():
    spec = importlib.util.spec_from_file_location("dc_osm_discrepancies", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def row(**kwargs) -> dict:
    base = {
        "way": "1",
        "region": "dc",
        "state": "DC",
        "matched": "1",
        "name": "R Street Northwest",
        "highway": "residential",
        "m": "200",
        "blocks": "dc-1-0,dc-2-0",
        "tier0": "2",
        "tier1": "2",
        "disagree": "",
        "agree": "",
        "sources": "{}",
        "tags": "{}",
        "tags1": "{}",
        "facts": "{}",
    }
    for key, value in kwargs.items():
        base[key] = json.dumps(value) if isinstance(value, dict) else value
    return base


def test_an_osm_lane_the_district_does_not_record_is_a_presence_item(report) -> None:
    found = list(
        report.items(
            [
                row(
                    tags={"cycleway:right": "lane"},
                    tags1={},
                    facts={"bike": {}, "bike_recorded": False},
                    tier0="2",
                    tier1="1",
                )
            ]
        )
    )
    assert [i["type"] for i in found] == ["presence"]
    assert found[0]["applied"] is True
    assert found[0]["dc"] == "none recorded"


def test_a_separate_facility_is_not_applied_and_says_why(report) -> None:
    """Irving Street's pattern: the motor carriageway OSM tags with nothing, on a
    block whose protected lane OSM maps as its own way beside the other one."""
    found = list(
        report.items(
            [
                row(
                    tags={},
                    tags1={},
                    facts={"bike": {"ib": 3, "ob": 3}, "bike_recorded": True},
                    agree="bike facility: OSM maps it as a separate way",
                )
            ]
        )
    )
    assert [i["type"] for i in found] == ["presence"]
    assert found[0]["applied"] is False
    assert report._reason(found[0]["disagree"], found[0]["agree"], "presence").startswith(
        "separate"
    )


def test_a_way_osm_marks_separate_agrees_with_a_district_facility(report) -> None:
    agreeing = row(
        tags={"cycleway:right": "separate"},
        tags1={"cycleway:right": "separate"},
        facts={"bike": {"ib": 3, "ob": 3}, "bike_recorded": True},
        agree="bike facility: OSM maps it as a separate way",
    )
    assert list(report.items([agreeing])) == []
    silent = row(
        tags={"cycleway:right": "separate"},
        tags1={"cycleway:right": "separate"},
        facts={"bike": {}, "bike_recorded": False},
    )
    found = list(report.items([silent]))
    assert [(i["type"], i["applied"], i["own_separate"]) for i in found] == [
        ("presence", False, True)
    ]


def test_one_way_lanes_and_speed_items(report) -> None:
    found = {
        i["type"]: i
        for i in report.items(
            [
                row(
                    tags={"oneway": "yes", "lanes": "2", "maxspeed": "25 mph"},
                    tags1={"oneway": "yes", "lanes": "2", "maxspeed": "20 mph"},
                    facts={"one_way": False, "lanes_per_dir": 1, "speed_mph": 20},
                    sources={"lanes": "osm"},
                    disagree="oneway: agency two-way, OSM one-way, kept (divided carriageway)",
                )
            ]
        )
    }
    assert found["oneway"]["applied"] is False
    assert report._reason(found["oneway"]["disagree"], "", "oneway") == "divided carriageway"
    assert found["lanes"]["applied"] is False
    assert found["speed"]["applied"] is True
    assert (found["speed"]["osm"], found["speed"]["dc"]) == ("25 mph", "20 mph")


def test_the_report_and_csv_are_written(report, tmp_path, monkeypatch) -> None:
    tsv = tmp_path / "dcbal.tsv"
    rows = [
        row(
            tags={"cycleway:left": "opposite_lane", "oneway": "yes"},
            tags1={"cycleway:right": "lane", "oneway": "yes"},
            facts={"bike": {"ob": 1}, "bike_recorded": True, "contraflow": False, "one_way": True},
        )
    ]
    with tsv.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    monkeypatch.setattr("sys.argv", ["x", "--dcbal", str(tsv), "--out", str(tmp_path)])
    assert report.main() == 0
    text = (tmp_path / "dc-osm-discrepancies.md").read_text()
    assert "https://www.openstreetmap.org/way/1" in text
    assert "licence waiver" in text
    with (tmp_path / "dc-osm-discrepancies.csv").open() as handle:
        written = list(csv.DictReader(handle))
    assert {r["type"] for r in written} == {"contraflow"}
    assert written[0]["applied"] == "1"
