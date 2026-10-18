"""The ways in the District a bicycle is kept off, listed for Review
(routemaker.bike_bans; the owner, 2026-10-17)."""

from __future__ import annotations

import csv
import io

from routemaker import bike_bans

DOWNTOWN = [(-77.0330, 38.9025), (-77.0325, 38.9025)]
BETHESDA = [(-77.0950, 38.9850), (-77.0945, 38.9850)]


class TestReason:
    def test_a_closure_rule_is_listed_but_the_cbd_sidewalks_and_works_are_not(self) -> None:
        assert bike_bans.reason({"highway": "path"}, "park_path", False) == "park_path"
        assert bike_bans.reason({"highway": "footway"}, "cbd_sidewalk", False) is None
        assert bike_bans.reason({"highway": "service"}, "works", False) is None

    def test_a_place_a_reopen_cannot_open_is_not_listed(self) -> None:
        for place in ("zoo", "military", "secured"):
            assert bike_bans.reason({"highway": "footway"}, place, False) is None

    def test_osms_own_no_is_listed_except_on_a_motorway(self) -> None:
        assert bike_bans.reason({"highway": "path", "bicycle": "no"}, None, False) == "bicycle_no"
        assert bike_bans.reason({"highway": "motorway", "bicycle": "no"}, None, False) is None

    def test_a_park_footway_closed_by_its_class_is_listed(self) -> None:
        footway = {"highway": "footway"}
        assert bike_bans.reason(footway, None, True) == "footway"
        assert bike_bans.reason(footway, None, False) is None
        for tags in (
            {"highway": "footway", "footway": "sidewalk"},
            {"highway": "footway", "footway": "crossing"},
            {"highway": "footway", "access": "private"},
            {"highway": "footway", "bicycle": "yes"},
            {"highway": "cycleway"},
        ):
            assert bike_bans.reason(tags, None, True) is None, tags


class TestPlace:
    def test_inside_the_district_only(self) -> None:
        assert bike_bans.inside(DOWNTOWN)
        assert not bike_bans.inside(BETHESDA)
        assert not bike_bans.inside([])


def test_the_report_is_what_review_reads_longest_first() -> None:
    text = bike_bans.report_csv(
        [
            bike_bans.Listed(1, "footway", "", 40.0, "footway"),
            bike_bans.Listed(2, "path", "Park Path, East", 90.0, "bicycle_no"),
        ]
    )
    rows = list(csv.DictReader(io.StringIO(text)))
    assert [r["way_id"] for r in rows] == ["2", "1"]
    assert rows[0]["name"] == "Park Path, East" and rows[0]["status"] == "closed"
    assert rows[0]["why"] == "OSM: bicycle=no"
    assert rows[1]["why"].startswith("A footway with no bicycle tag")
