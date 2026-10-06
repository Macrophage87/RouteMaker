"""Curated bike lanes (routemaker.bike_lanes), and the owner's Veirs Mill Road file
(OWNER-DECISIONS 433: "Yes, it should be marked"; "It's not an avoid")."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from routemaker import bike_lanes
from routemaker.facility import Facility, facility
from routemaker.stress import classify

REPO = Path(__file__).resolve().parents[1]
MOCO = REPO / "fixtures" / "overrides" / "2026-10-01-owner-moco-lts5-avoid.json"
# Four of the 23 carriageway ways as the 2026-10-03 extract tags them: two lanes and
# four, three, and the one posted 35 mph.
VEIRS_MILL = {
    128574906: {"highway": "primary", "name": "Veirs Mill Road", "oneway": "yes", "lanes": "2"},
    697039269: {"highway": "primary", "name": "Veirs Mill Road", "oneway": "yes", "lanes": "4"},
    724229765: {"highway": "primary", "name": "Veirs Mill Road", "oneway": "yes", "lanes": "3"},
    968550957: {
        "highway": "primary",
        "name": "Veirs Mill Road",
        "oneway": "yes",
        "lanes": "2",
        "maxspeed": "35 mph",
    },
}


def test_the_owners_file_marks_the_23_ways_the_moco_rows_had():
    sides = bike_lanes.load()
    retired = {r["osm_way_id"] for r in json.loads(MOCO.read_text())["retire"]}
    veirs = {w for w in sides if w in retired}
    assert veirs == retired and len(veirs) == 23
    assert {sides[w] for w in veirs} == {"right"}
    document = json.loads(
        (bike_lanes.BIKE_LANES_DIR / "2026-10-05-owner-veirs-mill-lanes.json").read_text()
    )
    for row in document["rows"]:
        assert "OWNER-DECISIONS 433" in row["reason"] and "it should be marked" in row["reason"]
        assert row["evidence"].strip()


@pytest.mark.parametrize("way_id", sorted(VEIRS_MILL))
def test_the_lane_takes_veirs_mill_from_lts_4_to_lts_3(way_id):
    """Unposted (read at 35 mph) or posted 35: "bike lane, 35 mph", LTS 3, as the
    investigation found; before, mixed traffic at 35 mph, LTS 4 (and Avoid by the
    retired Montgomery Planning row)."""
    tags = VEIRS_MILL[way_id]
    before = classify(tags, aadt=None, urban=True, jurisdiction="MD", divided=True)
    laned, used = bike_lanes.corrected(tags, bike_lanes.load()[way_id])
    after = classify(laned, aadt=None, urban=True, jurisdiction="MD", divided=True)
    assert used and laned["cycleway:right"] == "lane"
    assert (int(before.tier), int(after.tier)) == (4, 3)
    assert after.rule.startswith("bike lane")
    assert facility(laned) is Facility.LANE


def test_a_cycleway_tag_on_the_way_wins_and_nothing_is_added():
    tags = {**VEIRS_MILL[128574906], "cycleway:right": "buffered_lane"}
    assert bike_lanes.corrected(tags, "right") == (tags, False)
    assert bike_lanes.corrected(VEIRS_MILL[128574906], None) == (VEIRS_MILL[128574906], False)


@pytest.mark.parametrize(
    "row, problem",
    [
        ({"osm_way_id": 1, "side": "middle", "reason": "r", "evidence": "e"}, "side"),
        ({"osm_way_id": 0, "side": "right", "reason": "r", "evidence": "e"}, "osm_way_id"),
        ({"osm_way_id": 1, "side": "right", "reason": "", "evidence": "e"}, "reason"),
    ],
)
def test_a_malformed_row_is_refused(tmp_path, row, problem):
    (tmp_path / "a.json").write_text(json.dumps({"version": 1, "rows": [row]}))
    with pytest.raises(bike_lanes.BikeLaneRefused, match=problem):
        bike_lanes.load(tmp_path)


def test_two_files_that_disagree_about_a_way_are_refused(tmp_path):
    for name, side in (("a.json", "right"), ("b.json", "left")):
        row = {"osm_way_id": 5, "side": side, "reason": "r", "evidence": "e"}
        (tmp_path / name).write_text(json.dumps({"version": 1, "rows": [row]}))
    with pytest.raises(bike_lanes.BikeLaneRefused, match="also given a lane"):
        bike_lanes.load(tmp_path)
