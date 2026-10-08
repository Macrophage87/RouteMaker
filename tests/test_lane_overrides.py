"""Connecticut Ave NW's lanes (OWNER-DECISIONS 412, with 405, 411, 413, 414, 416)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.rematch import fingerprint_problem
from routemaker import agency_roads as A
from routemaker import lane_overrides as L
from routemaker import massflow
from routemaker.agency_roads import DC_AGENCY, RoadFacts
from routemaker.stress import Stress, classify

REPO = Path(__file__).resolve().parents[1]
FT = 0.3048
CALVERT = 38.9235
R_ST = 38.9126

STALE = {"ib": 1, "ob": 1, "reversible": 2}


def block(name="CONNECTICUT AVE NW", lanes=None, **extra) -> RoadFacts:
    return RoadFacts(
        agency=DC_AGENCY,
        name=name,
        speed_mph={"ob": 30},
        lanes=dict(STALE if lanes is None else lanes),
        way="both",
        parking_lanes=2,
        lane_width_ft=9.0,
        **extra,
    )


def line(lat: float) -> list[list[float]]:
    return [[-77.05, lat - 0.0005], [-77.05, lat + 0.0005]]


@pytest.fixture(scope="module")
def overrides() -> list[L.LaneOverride]:
    return L.load()


def test_the_fixture_cites_decision_412(overrides) -> None:
    (override,) = overrides
    assert override.street == "CONNECTICUT AVE NW" and override.north_of_lat == CALVERT
    assert override.travel_lanes_per_direction == 3
    assert override.part_time_parking_lanes_per_direction == 1
    assert "OWNER-DECISIONS 412" in override.source
    assert "OWNER-DECISIONS 412" in (REPO / "docs" / "SOURCES.md").read_text()


def test_a_block_north_of_calvert_reads_three_lanes_each_way(overrides) -> None:
    out = L.apply(block(), line(38.935), overrides)
    assert out.lanes == {"ib": 3, "ob": 3}
    assert A.lanes_per_direction(out) == 3
    assert out.part_time_parking_lanes == 1


def test_dc_s_own_higher_count_is_kept(overrides) -> None:
    out = L.apply(block(lanes={"ib": 4, "ob": 2}), line(38.93), overrides)
    assert out.lanes == {"ib": 4, "ob": 3}


@pytest.mark.parametrize(
    ("lat", "name"),
    [
        (38.9096, "CONNECTICUT AVE NW"),  # the Dupont underpass (414): not touched
        (R_ST + 0.001, "CONNECTICUT AVE NW"),  # R St to Calvert St
        (38.9212, "CONNECTICUT AVE NW"),  # just south of Calvert St
        (CALVERT - 0.0001, "CONNECTICUT AVE NW"),  # 11 m south of the cut
        (CALVERT - 0.001, "CONNECTICUT AVE NW"),  # 110 m south: the cut has not moved south
        (CALVERT - 0.0019, "CONNECTICUT AVE NW"),  # 210 m south, inside a 0.002 degree slip
        (38.95, "16TH ST NW"),  # another street keeps 405's zero
    ],
)
def test_nothing_else_is_touched(overrides, lat, name) -> None:
    original = block(name=name)
    assert L.apply(original, line(lat), overrides) is original


def test_other_reversible_blocks_count_for_the_classifier_and_zero_for_the_width(overrides) -> None:
    # 425: the classifier counts another street's reversible lanes in each direction; the
    # Mass Ride width keeps 405's zero; the override touches Connecticut alone.
    other = block(name="16TH ST NW")
    assert A.counted_reversible(other) == 0
    assert A.lanes_per_direction(L.apply(other, line(38.95), overrides)) == 3


def test_the_classifier_reads_three_lanes_and_stays_lts4(overrides) -> None:
    facts = L.apply(block(), line(38.935), overrides)
    way = A.aggregate([("a", facts)])
    assert way.lanes_per_direction == 3
    tags = A.overlay({"highway": "primary", "name": "Connecticut Avenue Northwest"}, way).tags
    # 20,831 vehicles a day (DC's count on the block) at 30 mph, three lanes each way.
    after = classify(tags, aadt=20831, aadt_source=DC_AGENCY, jurisdiction="DC")
    assert after.tier >= Stress.LTS4
    one_lane = A.aggregate([("a", block(lanes={"ib": 1, "ob": 1}))])
    tags = A.overlay({"highway": "primary", "name": "Connecticut Avenue Northwest"}, one_lane).tags
    before = classify(tags, aadt=20831, aadt_source=DC_AGENCY, jurisdiction="DC")
    assert before.tier >= Stress.LTS4  # 405's one lane was already LTS 4


def test_the_mass_ride_width_is_two_lanes_the_curb_lane_being_parking(overrides) -> None:
    osm = {"highway": "primary"}
    stale = massflow.usable_width_m(osm, None, [block()]) / FT
    assert stale == pytest.approx(9.0, abs=0.01)  # 405's zero reversible: one lane
    out = L.apply(block(), line(38.935), overrides)
    assert massflow.usable_width_m(osm, None, [out]) / FT == pytest.approx(18.0, abs=0.01)


def test_the_override_round_trips_through_the_installed_json(overrides) -> None:
    out = L.apply(block(), line(38.935), overrides)
    assert RoadFacts.from_json(out.to_json()).part_time_parking_lanes == 1
    assert "part_time_parking_lanes" not in block().to_json()


def test_a_bad_file_is_refused(tmp_path) -> None:
    with pytest.raises(L.LaneOverrideRefused, match="does not exist"):
        L.load(tmp_path / "nope")
    entry = {
        "id": "x",
        "agency": DC_AGENCY,
        "street": "X ST",
        "north_of_lat": 38.9,
        "travel_lanes_per_direction": 3,
        "part_time_parking_lanes_per_direction": 3,
        "source": "s",
    }
    with pytest.raises(L.LaneOverrideRefused, match="parking lanes"):
        L.parse({"overrides": [entry]})
    with pytest.raises(L.LaneOverrideRefused, match="bad entry"):
        L.parse({"overrides": [{"id": "x"}]})


# --- the Dupont underpass (414, 416) ----------------------------------------------

UNDERPASS = {
    123824236, 6051409, 24220748, 123824240, 123824220, 123824227, 123824223, 123819573,
    123819563, 130285091,
}  # fmt: skip


def test_the_underpass_is_opened_and_lts4_and_the_surface_is_not_named() -> None:
    path = REPO / "fixtures" / "overrides" / "2026-10-05-owner-dupont-underpass.json"
    rows = json.loads(path.read_text())["rows"]
    ways = {w["id"]: w for w in json.loads((REPO / "tests/data/connecticut_ways.json").read_text())}
    assert {r["osm_way_id"] for r in rows} == UNDERPASS
    for row in rows:
        assert "OWNER-DECISIONS 416" in row["reason"] or "Owner decision 416" in row["reason"]
        assert fingerprint_problem(row["fingerprint"]) is None
        # Every one is a way OSM tags bicycle=no, and the south end is under R St.
        assert ways[row["osm_way_id"]]["tags"]["bicycle"] == "no"
        if row["kind"] == "access":
            assert row["value"] == {"bicycle": "yes"}
        else:
            assert row["kind"] == "stress" and row["value"]["tier"] == 4
    assert sorted(r["kind"] for r in rows) == ["access"] * 10 + ["stress"] * 10
    # The surface roadway north of R St (414) is none of them.
    assert not UNDERPASS & {130285106, 1120314163}
