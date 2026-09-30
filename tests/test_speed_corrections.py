"""Curated speed limits (routemaker.speed_corrections), and the owner's file of
2026-09-30: the Montgomery County parkways at 25 mph (OWNER-DECISIONS 131)."""

from __future__ import annotations

import json

import pytest

from routemaker import speed_corrections as sc
from routemaker.stress import Stress, classify

OWNER_FILE = sc.SPEED_DIR / "2026-09-30-owner-md-parkways.json"
PARKWAYS = {"Sligo Creek Parkway", "Little Falls Parkway", "Beach Drive"}
# Typed in from the survey, not read from the file: Sligo Creek Parkway's
# longest unposted way, a Little Falls Parkway carriageway, a Beach Drive way,
# and the Beach Drive service spur that is not the parkway.
SLIGO, LITTLE_FALLS, BEACH, BEACH_SPUR = 981618619, 1455205184, 521153190, 991825926


def write(tmp_path, rows, name="a.json", version=1):
    (tmp_path / name).write_text(json.dumps({"version": version, "rows": rows}))
    return tmp_path


def row(way=1, speed="25 mph", **extra):
    return {"osm_way_id": way, "maxspeed": speed, "reason": "why", "evidence": "what", **extra}


class TestTheOwnersFile:
    def test_it_sets_the_parkways_to_25(self) -> None:
        document = json.loads(OWNER_FILE.read_text())
        speeds = sc.load()
        assert len(document["rows"]) == len(speeds) == 34
        assert set(speeds.values()) == {"25 mph"}
        assert {SLIGO, LITTLE_FALLS, BEACH} <= set(speeds)
        assert BEACH_SPUR not in speeds

    def test_every_row_quotes_the_owner_and_names_a_parkway(self) -> None:
        for r in json.loads(OWNER_FILE.read_text())["rows"]:
            assert '"Set them to 25 mph (Recommended)"' in r["reason"]
            assert any(name in r["evidence"] for name in PARKWAYS), r["osm_way_id"]
            assert "no maxspeed" in r["evidence"]

    def test_sligo_creek_parkway_comes_down_from_lts3_to_lts2(self) -> None:
        way = {"highway": "tertiary", "lanes": "2", "name": "Sligo Creek Parkway"}
        assert classify(way, urban=True, jurisdiction="MD").tier is Stress.LTS3
        tags, applied = sc.corrected(way, sc.load()[SLIGO])
        assert applied
        assert classify(tags, urban=True, jurisdiction="MD").tier is Stress.LTS2


class TestCorrected:
    def test_a_posted_speed_wins(self) -> None:
        tags = {"highway": "tertiary", "maxspeed": "30 mph"}
        assert sc.corrected(tags, "25 mph") == (tags, False)

    def test_no_row_changes_nothing(self) -> None:
        tags = {"highway": "tertiary"}
        assert sc.corrected(tags, None) == (tags, False)

    def test_the_way_itself_is_not_edited(self) -> None:
        tags = {"highway": "tertiary"}
        new, applied = sc.corrected(tags, "25 mph")
        assert applied and new["maxspeed"] == "25 mph"
        assert "maxspeed" not in tags


class TestWhatTheLoaderRefuses:
    def test_a_good_file_loads(self, tmp_path) -> None:
        assert sc.load(write(tmp_path, [row(1), row(2, "15 mph")])) == {1: "25 mph", 2: "15 mph"}

    def test_an_empty_directory_is_no_corrections(self, tmp_path) -> None:
        assert sc.load(tmp_path) == {}

    @pytest.mark.parametrize(
        ("rows", "version", "message"),
        [
            ([row()], 2, "version 1"),
            ([], 1, "no rows"),
            ([row(way=0)], 1, "positive integer"),
            ([row(way=True)], 1, "positive integer"),
            ([row(speed="25")], 1, "with its unit"),
            ([row(speed="fast")], 1, "with its unit"),
            ([row(reason=" ")], 1, "reason is required"),
            ([row(evidence="")], 1, "evidence is required"),
            ([row(1), row(1, "30 mph")], 1, "also corrected"),
        ],
    )
    def test_a_bad_file_is_refused(self, tmp_path, rows, version, message) -> None:
        with pytest.raises(sc.SpeedCorrectionRefused, match=message):
            sc.load(write(tmp_path, rows, version=version))

    def test_two_files_that_disagree_are_refused(self, tmp_path) -> None:
        write(tmp_path, [row(1)], "a.json")
        write(tmp_path, [row(1, "30 mph")], "b.json")
        with pytest.raises(sc.SpeedCorrectionRefused, match="also corrected"):
            sc.load(tmp_path)
