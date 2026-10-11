"""DDOT's Pavement Condition Index as a District street's smoothness reading (DC-PCI).

The fixture is hand-made in the layer's shape (tests/data/pavement); two of its
records carry the values the FY-25 layer returned on 2026-10-11. Nothing here
downloads anything: the layer arrives at rebuild time on the home PC.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from pipeline.conflation import RoadFeature, conflate_blocks
from routemaker import pavement
from routemaker.agency_roads import RoadFacts

REPO = Path(__file__).resolve().parents[1]
SAMPLE = REPO / "tests" / "data" / "pavement" / "dc-pci-fy25-sample.geojson"
INSTALL = REPO / "scripts" / "install_reference_data.py"


def blocks() -> list[pavement.Block]:
    return pavement.parse_layer(json.loads(SAMPLE.read_text()))


class TestTheReading:
    @pytest.mark.parametrize(
        ("pci", "expected"),
        [(100, "good"), (70, "good"), (69.9, "fair"), (55, "fair"), (54.9, "poor"), (0, "poor")],
    )
    def test_the_owners_bands(self, pci, expected) -> None:
        # Owner's default reading: 70+ good, 55-69 a small penalty, under 55 rough.
        assert pavement.band(pci) == expected

    def test_no_score_no_band(self) -> None:
        assert pavement.band(None) is None


class TestTheLayer:
    def test_each_scored_line_is_a_block_and_an_unscored_one_is_not(self) -> None:
        found = {block.feature_id: block for block in blocks()}
        assert sorted(found) == sorted(
            [
                "ddot-pci-fy25-72922-0",
                "ddot-pci-fy25-72923-0",
                "ddot-pci-fy25-90001-0",
                "ddot-pci-fy25-90002-0",
                "ddot-pci-fy25-90004-0",
                "ddot-pci-fy25-90004-1",
            ]
        )
        l_street = found["ddot-pci-fy25-72922-0"]
        assert l_street.pci == 81.1 and l_street.category == "Good"
        assert l_street.name == "L ST NW" and l_street.route_id == "11053492"
        assert (l_street.from_street, l_street.to_street) == ("PENNSYLVANIA AVE NW", "26TH ST NW")
        # DATE1 in milliseconds since 1970, UTC: 2026-02-27.
        assert l_street.surveyed == date(2026, 2, 27)
        # The elevation the service sends with each vertex is dropped.
        assert all(len(point) == 2 for point in l_street.coordinates)

    def test_an_empty_survey_date_is_the_fiscal_years_last_day(self) -> None:
        found = {block.feature_id: block for block in blocks()}
        assert found["ddot-pci-fy25-90002-0"].surveyed == date(2025, 9, 30)

    def test_a_block_survives_the_round_trip_through_the_installed_file(self) -> None:
        for block in blocks():
            assert pavement.Block.from_json(json.loads(json.dumps(block.to_json()))) == block

    def test_a_score_outside_0_to_100_is_not_a_score(self) -> None:
        feature = {
            "properties": {"OBJECTID": 1, "PCI": 140},
            "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
        }
        assert pavement.parse_feature(feature, 0) == []


def block(pci: float, surveyed=date(2026, 2, 27), feature_id="b") -> pavement.Block:
    return pavement.Block(feature_id, [(0, 0), (1, 0)], pci, "EXAMPLE ST NW", surveyed)


STREET = {"highway": "residential", "name": "Example Street Northwest"}


class TestWhoWins:
    def test_the_district_score_wins_over_osm(self) -> None:
        reading = pavement.resolve(1, {**STREET, "smoothness": "excellent"}, [(block(41.5), 1.0)])
        assert (reading.applied, reading.why) == ("poor", "pci")

    def test_the_way_takes_the_mean_of_its_blocks_by_share(self) -> None:
        reading = pavement.resolve(
            1, STREET, [(block(80, feature_id="a"), 0.25), (block(60, feature_id="b"), 0.75)]
        )
        assert reading.pci == 65.0 and reading.applied == "fair"
        assert reading.blocks == ("a", "b")

    def test_an_alley_or_a_trail_keeps_osm(self) -> None:
        for tags in ({"highway": "service", "service": "alley"}, {"highway": "cycleway"}):
            reading = pavement.resolve(1, tags, [(block(30), 1.0)])
            assert (reading.applied, reading.why) == (None, "not_street")

    def test_an_unpaved_street_keeps_osm(self) -> None:
        reading = pavement.resolve(1, {**STREET, "surface": "gravel"}, [(block(30), 1.0)])
        assert (reading.applied, reading.why) == (None, "unpaved")

    def test_a_newer_osm_smoothness_wins(self) -> None:
        edited = datetime(2026, 5, 1, tzinfo=UTC)
        reading = pavement.resolve(
            1, {**STREET, "smoothness": "good"}, [(block(41.5), 1.0)], edited=edited
        )
        assert (reading.applied, reading.why) == (None, "osm_newer")

    def test_an_older_osm_edit_or_no_smoothness_does_not(self) -> None:
        older = datetime(2025, 1, 1, tzinfo=UTC)
        newer = datetime(2026, 5, 1, tzinfo=UTC)
        tagged = {**STREET, "smoothness": "good"}
        assert pavement.resolve(1, tagged, [(block(41.5), 1.0)], edited=older).applied == "poor"
        assert pavement.resolve(1, STREET, [(block(41.5), 1.0)], edited=newer).applied == "poor"
        # No timestamp in the file: the District's score stands.
        assert pavement.resolve(1, tagged, [(block(41.5), 1.0)], edited=None).applied == "poor"

    def test_an_osm_edit_on_the_survey_day_is_not_newer(self) -> None:
        same_day = datetime(2026, 2, 27, 18, 0, tzinfo=UTC)
        tagged = {**STREET, "smoothness": "good"}
        reading = pavement.resolve(1, tagged, [(block(41.5), 1.0)], edited=same_day)
        assert (reading.applied, reading.why) == ("poor", "pci")

    def test_an_approved_correction_wins_over_both(self) -> None:
        keep = pavement.Override(1, pavement.KEEP_OSM, "owner rode it 2026-10")
        set_good = pavement.Override(1, "good", "repaved 2026-09 (owner)")
        newer = datetime(2026, 5, 1, tzinfo=UTC)
        tagged = {**STREET, "smoothness": "bad"}
        assert pavement.resolve(1, STREET, [(block(30), 1.0)], override=keep).applied is None
        assert pavement.resolve(1, tagged, [(block(30), 1.0)], newer, set_good).applied == "good"
        assert pavement.resolve(1, STREET, [(block(30), 1.0)], override=keep).why == "override"

    def test_no_block_no_reading(self) -> None:
        assert pavement.resolve(1, STREET, []) is None


class TestCorrections:
    def test_the_shipped_file_is_empty_and_loads(self) -> None:
        assert pavement.load_overrides() == {}

    def test_a_row_without_a_reason_or_with_an_unknown_reading_is_refused(self, tmp_path) -> None:
        path = tmp_path / "overrides.json"
        path.write_text(json.dumps({"rows": [{"osm_way_id": 5, "reading": "fine", "reason": "x"}]}))
        with pytest.raises(ValueError, match="unknown reading"):
            pavement.load_overrides(path)
        path.write_text(json.dumps({"rows": [{"osm_way_id": 5, "reading": "osm", "reason": " "}]}))
        with pytest.raises(ValueError, match="needs its reason"):
            pavement.load_overrides(path)

    def test_a_good_row_loads(self, tmp_path) -> None:
        path = tmp_path / "overrides.json"
        path.write_text(
            json.dumps({"rows": [{"osm_way_id": 5, "reading": "osm", "reason": "owner, 2026-10"}]})
        )
        assert pavement.load_overrides(path)[5].reading == "osm"


class TestTheMatch:
    """The layer's blocks reach the ways the rebuild's own matcher puts them on:
    both carriageways of a street, and not a cross street or an alley beside it."""

    def test_the_blocks_land_on_the_street_and_not_beside_it(self) -> None:
        sample = blocks()
        features = [
            RoadFeature(b.feature_id, b.coordinates, RoadFacts(agency=pavement.AGENCY, name=b.name))
            for b in sample
        ]
        ways = [
            # Example Street NW along blocks 90001 and 90002, drawn as one way.
            (1, [(-77.0300, 38.91001), (-77.0260, 38.91001)], False),
            # An alley 15 m north with no name, which needs an agreeing name.
            (2, [(-77.0300, 38.91014), (-77.0260, 38.91014)], False),
            # A cross street.
            (3, [(-77.0280, 38.9090), (-77.0280, 38.9110)], False),
            # A trail on the same line: never a candidate.
            (4, [(-77.0300, 38.91000), (-77.0260, 38.91000)], True),
        ]
        names = {1: "Example Street Northwest", 2: None, 3: "B Street Northwest", 4: None}
        result = conflate_blocks(ways, features, names, name_required={2})
        assert set(result.matched) == {1}
        by_id = {b.feature_id: b for b in sample}
        reading = pavement.resolve(
            1,
            {"highway": "residential"},
            [(by_id[s.feature_id], s.share) for s in result.matched[1]],
        )
        # Half fair (62) and half poor (41.5): about 51.75, poor.
        assert reading.applied == "poor" and 50 < reading.pci < 54


def test_the_report_has_a_line_a_way() -> None:
    readings = [
        pavement.resolve(2, STREET, [(block(80), 1.0)]),
        pavement.resolve(1, {"highway": "service"}, [(block(30), 1.0)]),
    ]
    lines = pavement.report_csv(readings).splitlines()
    assert lines[0] == pavement.REPORT_HEADER
    assert lines[1] == "1,30.0,,not_street,2026-02-27,b"
    assert lines[2] == "2,80.0,good,pci,2026-02-27,b"


def test_the_installer_refuses_the_layer_until_the_licence_is_confirmed(tmp_path) -> None:
    """The service states no licence: nothing is written, not even the crossings."""
    done = subprocess.run(
        [sys.executable, str(INSTALL), "--data-root", str(tmp_path), "--dc-pci", str(SAMPLE)],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 2
    assert "--dc-pci refused" in done.stderr and "no licence" in done.stderr
    assert not (tmp_path / "reference").exists()


def load_installer():
    spec = importlib.util.spec_from_file_location("install_reference_data_pci", INSTALL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_installer_writes_what_the_rebuild_loads(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(pavement, "LICENCE_CONFIRMED", True)
    load_installer().main(["--data-root", str(tmp_path), "--dc-pci", str(SAMPLE)])
    out = capsys.readouterr().out
    assert "wrote" in out and "6 pavement blocks (FY2025)" in out
    rows = json.loads((tmp_path / "reference" / "pavement.json").read_text())
    assert [pavement.Block.from_json(row) for row in rows] == blocks()
