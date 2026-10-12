"""Maryland's traffic counts (FOLLOWUP-MDOT-AADT, OWNER-DECISIONS 429).

The fixture is hand-made in the shape MDOT SHA's AADT Segments layer has (its
field list read from the service's metadata on 2026-10-11): `AADT` the current
year both ways, `AADT_<year>` the earlier years, `LOC_ERROR` "NO ERROR". The
MD 185 row carries the count the layer showed that day for the stretch from the
DC line to MD 410 (OBJECTID 161492, 39,141), so the test reads like the case it
is for. Nothing here downloads anything: the real layer arrives at rebuild time.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from pipeline.conflation import AgencyFeature, conflate, share_with_carriageways
from pipeline.extract import Way
from routemaker import divided, mdot_aadt

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "install_reference_data.py"


def mdot_feature(object_id: int, coordinates, aadt, loc_error="NO ERROR", **extra) -> dict:
    properties = {
        "OBJECTID": object_id,
        "ROADNAME": "CONNECTICUT AVE",
        "ID_PREFIX": "MD",
        "ID_RTE_NO": 185,
        "STATION_DESC": "MD185-.10 MI S OF MD410",
        "AADT_2015": 38000,
        "AADT_2022": 37100,
        "AADT_2023": 38200,
        "AADT": aadt,
        "AAWDT_2023": 41000,
        "LOC_ERROR": loc_error,
        **extra,
    }
    return {
        "type": "Feature",
        "id": object_id,
        "properties": properties,
        "geometry": {"type": "LineString", "coordinates": coordinates},
    }


class TestTheYearAndTheRows:
    def test_the_current_count_is_the_year_after_the_newest_dated_field(self) -> None:
        # The layer's description, 2026-10-11: "This data is for the year 2024",
        # with AADT_2015 ... AADT_2023 beside it.
        names = ["OBJECTID", "AADT_2015", "AADT_2023", "AADT", "AAWDT_2023"]
        assert mdot_aadt.current_year(names) == 2024

    def test_weekday_and_text_fields_do_not_date_it(self) -> None:
        assert mdot_aadt.current_year(["AAWDT_2030", "AADT_2030_ANNO", "AADT"]) is None

    @pytest.mark.parametrize(
        ("aadt", "flag", "ok"),
        [
            (39141, "NO ERROR", True),
            (39141, None, True),
            (39141, "no error ", True),
            (39141, "LOCATION ERROR", False),
            (0, "NO ERROR", False),
            (None, "NO ERROR", False),
            ("n/a", "NO ERROR", False),
        ],
    )
    def test_a_row_is_used_only_with_a_count_and_a_placed_line(self, aadt, flag, ok) -> None:
        assert mdot_aadt.usable({"AADT": aadt, "LOC_ERROR": flag}) is ok


def install(tmp_path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--data-root", str(tmp_path / "data"), *args],
        capture_output=True,
        text=True,
    )


class TestTheInstall:
    def write(self, tmp_path) -> str:
        layer = tmp_path / "mdot-sha-aadt.geojson"
        features = [
            mdot_feature(161492, [[-77.0773, 38.9680], [-77.0775, 38.9879]], 39141),
            mdot_feature(2, [[-77.0, 39.0], [-77.0, 39.01]], 5000, loc_error="LOCATION ERROR"),
            mdot_feature(3, [[-77.1, 39.0], [-77.1, 39.01]], 0),
        ]
        layer.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
        return str(layer)

    def test_the_rows_are_marylands_dated_and_the_misplaced_ones_left_out(self, tmp_path) -> None:
        done = install(tmp_path, "--volume", self.write(tmp_path), "--volume-source", "mdot-sha")
        assert "unknown --volume-source" not in done.stderr, done.stderr
        assert "2 rows not installed" in done.stdout
        (row,) = json.loads((tmp_path / "data" / "reference" / "volume.json").read_text())
        assert row["aadt"] == 39141
        assert row["agency"] == "mdot-sha" and row["source"] == "state"
        assert row["year"] == 2024, "read from the layer's fields, not typed"
        assert row["id"].startswith("mdot-sha-mdot-sha-aadt-161492-")

    def test_a_typed_year_still_wins(self, tmp_path) -> None:
        install(
            tmp_path,
            "--volume", self.write(tmp_path), "--volume-source", "mdsha", "--volume-year", "2023",
        )  # fmt: skip
        (row,) = json.loads((tmp_path / "data" / "reference" / "volume.json").read_text())
        assert row["year"] == 2023

    def test_another_agencys_rows_are_not_filtered_on_marylands_flag(self, tmp_path) -> None:
        install(tmp_path, "--volume", self.write(tmp_path), "--volume-source", "vdot")
        rows = json.loads((tmp_path / "data" / "reference" / "volume.json").read_text())
        # VDOT's layer has no LOC_ERROR; a zero count is still installed as before.
        assert len(rows) == 3
        assert {row["year"] for row in rows} == {None}


# Two one-way carriageways of one street, about 80 ft (24 m) apart (0.00028 deg
# of longitude at 39 N), one running north and one south, and a count line drawn
# between them. MD 185 north of Chevy Chase Circle has this shape.
WEST = [(-77.07760, 38.9700), (-77.07760, 38.9790)]
EAST = [(-77.07732, 38.9790), (-77.07732, 38.9700)]
MIDDLE = [(-77.07746, 38.9700), (-77.07746, 38.9790)]


def carriageway(osm_id, coordinates, name="Connecticut Avenue", highway="primary") -> Way:
    return Way(
        osm_id=osm_id,
        tags={"highway": highway, "name": name, "oneway": "yes"},
        node_ids=list(range(len(coordinates))),
        coordinates=list(coordinates),
    )


def count(agency: str, aadt: int = 39141) -> AgencyFeature:
    return AgencyFeature(
        feature_id=f"{agency}-1", coordinates=MIDDLE, aadt=aadt, source="state", year=2024,
        agency=agency,
    )  # fmt: skip


class TestBothCarriageways:
    def shared(self, ways, agency, agencies=(mdot_aadt.AGENCY,)):
        result = conflate([(w.osm_id, w.coordinates, False) for w in ways], [count(agency)])
        added = share_with_carriageways(
            result,
            divided.carriageways(ways),
            {w.osm_id: w.name for w in ways},
            agencies,
        )
        return result, added

    def test_the_carriageway_conflation_turned_away_takes_marylands_count(self) -> None:
        ways = [carriageway(1, WEST), carriageway(2, EAST)]
        result, added = self.shared(ways, mdot_aadt.AGENCY)
        assert len(result.matched) == 1, "conflation alone counts one carriageway"
        (other,) = {1, 2} - set(result.matched)
        assert set(added) == {other}
        assert added[other].aadt == 39141 and added[other].agency == "mdot-sha"

    def test_another_agencys_count_is_left_as_conflation_placed_it(self) -> None:
        ways = [carriageway(1, WEST), carriageway(2, EAST)]
        _result, added = self.shared(ways, "vdot")
        assert added == {}

    def test_a_way_of_another_name_alongside_does_not_take_it(self) -> None:
        ways = [carriageway(1, WEST), carriageway(2, EAST, name="Service Drive")]
        result, added = self.shared(ways, mdot_aadt.AGENCY)
        assert added == {}, (result.matched, added)

    def test_a_two_way_road_beside_it_is_not_a_carriageway(self) -> None:
        two_way = Way(
            osm_id=2,
            tags={"highway": "primary", "name": "Connecticut Avenue"},
            node_ids=[0, 1],
            coordinates=list(EAST),
        )
        _result, added = self.shared([carriageway(1, WEST), two_way], mdot_aadt.AGENCY)
        assert added == {}
