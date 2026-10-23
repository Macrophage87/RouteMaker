"""The popular bike corridors (the owner, 2026-10-21: "use the Cabi heatmap if you can, and make
those streets show more pronounced than other roads"): the trips routed over the segment table
(`pipeline.bikeshare_corridors`), the owner's named corridors (`pipeline.major_corridors`) and the
trip counts' writer (`scripts/build_bikeshare_trips.py`)."""

from __future__ import annotations

import csv
import importlib.util
import io
import json
import math
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from django.db import connection

from pipeline import bikeshare_corridors as bc
from pipeline import major_corridors as mc

G = 10_000_000
LON, LAT = -77.03, 38.90
STEP = 0.001  # about 285 ft (87 m) east-west, 365 ft (111 m) north-south


def vertex(row, i, j, at_m, tier=2, path=False):
    return bc.Vertex(
        row, round((LON + i * STEP) * G), round((LAT + j * STEP) * G), at_m, tier, path
    )


def ladder(busy_tier=4):
    """Two parallel east-west streets, 0-4 along, joined at both ends by short north-south
    links: the south street (rows 1-4) at `busy_tier`, the north one (rows 11-14) LTS 1, a
    block further round."""
    rows = []
    for k in range(4):
        rows += [vertex(1 + k, k, 0, 0, busy_tier), vertex(1 + k, k + 1, 0, 87, busy_tier)]
        rows += [vertex(11 + k, k, 1, 0, 1), vertex(11 + k, k + 1, 1, 87, 1)]
    rows += [vertex(21, 0, 0, 0, 1), vertex(21, 0, 1, 111, 1)]
    rows += [vertex(22, 4, 0, 0, 1), vertex(22, 4, 1, 111, 1)]
    return rows


def docks_at(*cells):
    return [(LON + i * STEP, LAT + j * STEP) for i, j in cells]


class TestRouting:
    def test_a_trip_takes_the_calm_street_when_it_is_not_much_further(self) -> None:
        trips = bc.Trips(docks_at((0, 0), (4, 0)), [(0, 1, 365 * 50)], 365)
        rows, stats = bc.corridor_trips(ladder(busy_tier=4), trips)
        # 4 blocks at LTS 4 cost 4 x 87 x 2.2 = 766; by the calm street 2 x 111 + 4 x 87 = 570.
        assert {row for row in rows if row < 10} == set()
        assert all(rows[row] == pytest.approx(50) for row in (11, 12, 13, 14, 21, 22))
        assert stats["docks placed"] == 2 and stats["pairs no route reached"] == 0

    def test_a_trip_stays_on_a_quiet_enough_direct_street(self) -> None:
        trips = bc.Trips(docks_at((0, 0), (4, 0)), [(0, 1, 365 * 50)], 365)
        rows, _ = bc.corridor_trips(ladder(busy_tier=2), trips)
        assert set(rows) == {1, 2, 3, 4}

    def test_loads_add_up_along_a_shared_street(self) -> None:
        trips = bc.Trips(
            docks_at((0, 0), (2, 0), (4, 0)), [(0, 1, 365 * 10), (0, 2, 365 * 30)], 365
        )
        rows, _ = bc.corridor_trips(ladder(busy_tier=2), trips)
        assert rows[1] == pytest.approx(40) and rows[2] == pytest.approx(40)
        assert rows[3] == pytest.approx(30) and rows[4] == pytest.approx(30)

    def test_a_dock_far_from_any_street_is_left_out_and_counted(self) -> None:
        trips = bc.Trips(docks_at((0, 0), (40, 40)), [(0, 1, 365 * 5)], 365)
        rows, stats = bc.corridor_trips(ladder(), trips)
        assert rows == {}
        assert stats["docks placed"] == 1 and stats["trips a day at unplaced docks"] == 5

    def test_a_dock_unreachable_on_the_graph_is_counted(self) -> None:
        island = [vertex(99, 10, 10, 0), vertex(99, 11, 10, 87)]
        trips = bc.Trips(docks_at((0, 0), (10, 10)), [(0, 1, 365)], 365)
        rows, stats = bc.corridor_trips(ladder() + island, trips)
        assert rows == {} and stats["pairs no route reached"] == 1

    def test_a_junction_east_of_a_dock_within_reach_is_found(self) -> None:
        # 240 m due east: inside SNAP_M, but past one grid cell east-west at DC's latitude.
        east = 240 / (111_320 * math.cos(math.radians(LAT)))
        graph = bc.Graph(
            [bc.Vertex(1, round((LON + east) * G), round(LAT * G), 0, 2, False),
             bc.Vertex(1, round((LON + east + 0.01) * G), round(LAT * G), 860, 2, False)]
        )  # fmt: skip
        assert graph.nearest(LON, LAT) == 0

    @pytest.mark.parametrize(
        ("a_day", "level"), [(0, 0), (24.9, 0), (25, 1), (74.9, 1), (75, 2), (200, 3), (900, 3)]
    )
    def test_the_classes(self, a_day, level) -> None:
        assert bc.popular_class(a_day) == level


class TestLoad:
    def test_absent_is_none(self, tmp_path) -> None:
        assert bc.load(tmp_path / bc.FILE_NAME) is None

    def test_a_pair_naming_no_dock_is_refused(self, tmp_path) -> None:
        path = tmp_path / bc.FILE_NAME
        path.write_text(
            json.dumps({"stations": [["1", -77, 38.9]], "pairs": [[0, 3, 20]], "days": 30})
        )
        with pytest.raises(ValueError, match="names a dock"):
            bc.load(path)


def _script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "build_bikeshare_trips.py"
    spec = importlib.util.spec_from_file_location("build_bikeshare_trips", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestTripCounts:
    FIELDS = ("start_station_id", "end_station_id", "start_lng", "start_lat", "end_lng", "end_lat")

    def rows(self, *trips):
        return [dict(zip(self.FIELDS, trip, strict=True)) for trip in trips]

    def test_pairs_both_ways_round_trips_dockless_and_rare_pairs(self) -> None:
        script = _script()
        a, b, c = ("1", "-77.0", "38.9"), ("2", "-77.01", "38.91"), ("3", "-77.02", "38.92")

        def trip(x, y):
            return (x[0], y[0], x[1], x[2], y[1], y[2])

        rows = self.rows(
            *[trip(a, b)] * 7,
            *[trip(b, a)] * 6,  # either way round: 13 in all
            *[trip(a, a)] * 50,  # a round trip says nothing about a street
            *[trip(a, c)] * 11,  # under the floor
            ("", "2", "-77.0", "38.9", "-77.01", "38.91"),  # dockless
        )
        stations, pairs = script.aggregate(rows, min_pair_trips=12)
        assert [s[0] for s in stations] == ["1", "2"]
        assert pairs == [(0, 1, 13)]

    def test_months_and_days(self) -> None:
        script = _script()
        assert script.months_between("202511-202602") == ["202511", "202512", "202601", "202602"]
        assert script.days_in(["202602", "202603"]) == 28 + 31

    def test_reads_the_csv_inside_the_zip(self) -> None:
        script = _script()
        body = io.StringIO()
        writer = csv.DictWriter(body, fieldnames=self.FIELDS)
        writer.writeheader()
        writer.writerow(
            dict(zip(self.FIELDS, ("1", "2", "-77", "38.9", "-77.01", "38.91"), strict=True))
        )
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            archive.writestr("202609-capitalbikeshare-tripdata.csv", body.getvalue())
            archive.writestr("__MACOSX/._202609-capitalbikeshare-tripdata.csv", "junk")
        assert [row["start_station_id"] for row in script.trip_rows(data.getvalue())] == ["1"]


class TestInstall:
    def run(self, tmp_path, source):
        script = Path(__file__).resolve().parents[1] / "scripts" / "install_reference_data.py"
        return subprocess.run(
            [sys.executable, str(script), "--data-root", str(tmp_path / "data"),
             "--bikeshare-trips", str(source)],
            check=False, capture_output=True, text=True,
        )  # fmt: skip

    def test_the_file_is_installed_where_the_rebuild_reads_it(self, tmp_path) -> None:
        source = tmp_path / "trips.json"
        source.write_text(
            json.dumps({"stations": [["1", -77, 38.9], ["2", -77.01, 38.9]],
                        "pairs": [[0, 1, 20]], "days": 30})
        )  # fmt: skip
        result = self.run(tmp_path, source)
        assert "2 docks, 1 dock pairs" in result.stdout, result.stderr
        trips = bc.load(tmp_path / "data" / "reference" / bc.FILE_NAME)
        assert trips is not None and trips.pairs == [(0, 1, 20)]

    def test_a_bad_file_is_refused_and_nothing_is_written(self, tmp_path) -> None:
        source = tmp_path / "trips.json"
        source.write_text(json.dumps({"stations": [], "pairs": [[0, 3, 20]], "days": 30}))
        result = self.run(tmp_path, source)
        assert result.returncode != 0 and "names a dock" in result.stderr
        assert not (tmp_path / "data" / "reference" / bc.FILE_NAME).exists()


class TestMajorCorridors:
    def test_the_fixture_loads_and_every_name_compiles(self) -> None:
        corridors = mc.load()
        ids = {c.id for c in corridors}
        assert {
            "rock-creek-trail",
            "capital-crescent-trail",
            "k-street-nw",
            "c-and-o-canal-towpath",
        } <= ids
        assert len(ids) == len(corridors), "one id each"

    def test_a_way_is_matched_by_name_and_place(self) -> None:
        corridors = mc.load()
        ways = [
            (1, {"name": "Capital Crescent Trail", "highway": "cycleway"}, [(-77.09, 38.95)]),
            (2, {"name": "Capital Crescent Trail", "highway": "cycleway"}, [(-76.5, 39.3)]),
            (3, {"name": "Q Street Northwest", "highway": "residential"}, [(-77.04, 38.911)]),
            (4, {"name": "Q Street Southeast", "highway": "residential"}, [(-76.99, 38.87)]),
            # The 15th Street lane: its bike way, by the street it runs beside, not the road.
            (5, {"highway": "cycleway"}, [(-77.035, 38.905)]),
            (6, {"name": "15th Street Northwest", "highway": "primary"}, [(-77.035, 38.905)]),
            # A route relation's name counts.
            (7, {"highway": "path"}, [(-77.4, 39.0)]),
        ]
        ids, counts = mc.way_ids(
            ways,
            {7: "Washington & Old Dominion Railroad Trail"},
            {5: "15th Street Northwest protected bike lane"},
            corridors,
        )
        assert ids == frozenset({1, 3, 5, 7})
        assert counts["capital-crescent-trail"] == 1

    def test_a_corridor_matching_nothing_is_warned_about(self, caplog) -> None:
        mc.way_ids([], {}, {}, mc.load())
        assert "matched no way" in caplog.text and "rock-creek-trail" in caplog.text


@pytest.mark.django_db(transaction=True)
class TestDerive:
    def insert(self, schema, rows) -> None:
        with connection.cursor() as cursor:
            for way, (a, b), tier in rows:
                cursor.execute(
                    f"INSERT INTO {schema}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                    "stress_rule) VALUES (%s, 0, ST_MakeLine(ST_MakePoint(%s, %s), "
                    "ST_MakePoint(%s, %s)), %s, 'x')",
                    [way, LON + a[0] * STEP, LAT + a[1] * STEP, LON + b[0] * STEP,
                     LAT + b[1] * STEP, tier],
                )  # fmt: skip

    def popular(self, schema) -> dict:
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT osm_way_id, bike_trips, bike_popular FROM {schema}.segment")
            return {way: (trips, level) for way, trips, level in cursor.fetchall()}

    def test_the_rows_on_the_way_take_the_trips_and_a_named_corridor_keeps_its_class(
        self, segment_schemas, tmp_path
    ) -> None:
        _, staging = segment_schemas
        self.insert(
            staging,
            [(1, ((0, 0), (1, 0)), 2), (2, ((1, 0), (2, 0)), 2), (3, ((2, 0), (2, 1)), 2),
             (4, ((5, 5), (6, 5)), 2)],
        )  # fmt: skip
        assert mc.apply(staging, frozenset({2})) == 1
        (tmp_path / bc.FILE_NAME).write_text(
            json.dumps(
                {
                    "stations": [["a", LON, LAT], ["b", LON + 2 * STEP, LAT + STEP]],
                    "pairs": [[0, 1, 80 * 30]],
                    "days": 30,
                }
            )
        )
        stats = bc.derive(staging, tmp_path / bc.FILE_NAME)
        assert self.popular(staging) == {
            1: (80, 2),
            2: (80, 3),  # named: never lowered
            3: (80, 2),
            4: (None, 0),
        }
        assert stats["rows with trips"] == 3 and stats["miles by class"]

    def test_no_file_changes_nothing(self, segment_schemas, tmp_path) -> None:
        _, staging = segment_schemas
        self.insert(staging, [(1, ((0, 0), (1, 0)), 2)])
        assert bc.derive(staging, tmp_path / bc.FILE_NAME) == {}
        assert self.popular(staging) == {1: (None, 0)}
