"""The Climbs layer's database read and command (`pipeline.climb_layer.read_segments`,
`manage.py build_climbs`) against a real segment table, as tests/test_mass_tiles.py.

What is held here: only the ways the map draws as routable carry a climb (not barred, hidden or
alley ways, not mountain-bike-only ways, not walk-your-bike connectors); the row's one-way,
unpaved and trail name reach the reader; the streaming cursor reads every row in way order; and
the command writes the file from the table and a tile, and refuses to write over a good file
when it read no ground at all.
"""

from __future__ import annotations

import io
import json
import math
import sys
from array import array

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from pipeline import climb_layer

db = pytest.mark.django_db(transaction=True)

LAT = 39.5
WEST = -76.9
# Metres per degree of longitude at LAT.
KX = 111_320.0 * math.cos(math.radians(LAT))


def east(metres: float) -> tuple[float, float]:
    return (WEST + metres / KX, LAT)


def insert(schema, way, points, ordinal=0, **columns) -> None:
    wkt = "LINESTRING(" + ", ".join(f"{lon} {lat}" for lon, lat in points) + ")"
    names = ["osm_way_id", "ordinal", "geometry", "stress_tier", "stress_rule", *columns]
    values = ["%s", "%s", "ST_GeomFromText(%s, 4326)", "2", "'x'", *(["%s"] * len(columns))]
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {schema}.segment ({', '.join(names)}) VALUES ({', '.join(values)})",
            [way, ordinal, wkt, *columns.values()],
        )


def ramp_tile(root) -> None:
    """N39W077 rising 2 m per arc-second going east (about 8.4% at LAT), level north-south."""
    side = climb_layer.HGT_1ARCSEC_SIDE
    row = array("h", [2 * col for col in range(side)])
    data = row * side
    if sys.byteorder == "little":
        data.byteswap()
    (root / "N39").mkdir(parents=True)
    (root / "N39" / "N39W077.hgt").write_bytes(data.tobytes())


@db
def test_read_segments_reads_the_routable_ways_with_their_columns(segment_schemas):
    live, _ = segment_schemas
    insert(live, 10, [east(0), east(300)], ordinal=1, road_oneway=True, is_unpaved=False)
    insert(live, 10, [east(-300), east(0)], ordinal=0, trail_name="Example Trail", is_unpaved=True)
    insert(live, 11, [east(0), (WEST, LAT + 0.003)])
    insert(live, 20, [east(400), east(700)], map_class="barred")
    insert(live, 21, [east(400), east(700)], map_class="hidden")
    insert(live, 22, [east(400), east(700)], map_class="alley")
    insert(live, 23, [east(400), east(700)], mtb_only=True)
    insert(live, 24, [east(400), east(700)], walk_bike=True)

    segments = climb_layer.read_segments(live)

    assert [s.key for s in segments] == [(10, 0), (10, 1), (11, 0)]
    first, second, third = segments
    assert first.trail_name == "Example Trail" and first.unpaved is True and first.oneway is False
    assert second.oneway is True and second.unpaved is False and second.trail_name is None
    assert third.unpaved is None and third.oneway is False
    assert second.coords[0] == pytest.approx(east(0), abs=1e-7)
    assert second.coords[-1] == pytest.approx(east(300), abs=1e-7)


@db
def test_read_segments_reads_only_ways_open_to_bicycles(segment_schemas):
    """Owner report 2026-10-12 (a Cat 4 climb in the Travilah quarry): a climb rides only a
    way the segment panel calls open. A drawn way whose bike-access reason closes it, or
    names a reason this release does not know, carries no climb (unclear access is
    closed); an override that reopened a way, or no reason at all, does."""
    live, _ = segment_schemas
    insert(live, 30, [east(0), east(300)])
    insert(live, 31, [east(0), east(300)], bike_access_reason="override_open")
    insert(live, 32, [east(0), east(300)], bike_access_reason="works")
    insert(live, 33, [east(0), east(300)], bike_access_reason="private")
    insert(live, 34, [east(0), east(300)], bike_access_reason="military")
    insert(live, 35, [east(0), east(300)], bike_access_reason="a_reason_from_the_future")

    segments = climb_layer.read_segments(live)

    assert [s.key[0] for s in segments] == [30, 31]
    # A use_sidepath road with a side path mapped is legal to ride (review RL-1), so it is open too.
    assert sorted(climb_layer.open_access_reasons()) == ["bicycle_use_sidepath", "override_open"]
    # The streaming cursor's transaction is closed again: the connection is back in autocommit.
    assert connection.get_autocommit()


@db
def test_read_segments_takes_a_table_without_the_newer_columns(segment_schemas):
    live, _ = segment_schemas
    insert(live, 10, [east(0), east(300)])
    with connection.cursor() as cursor:
        cursor.execute(f"ALTER TABLE {live}.segment DROP COLUMN road_oneway")
        cursor.execute(f"ALTER TABLE {live}.segment DROP COLUMN trail_name")
    (segment,) = climb_layer.read_segments(live)
    assert segment.oneway is False and segment.trail_name is None


@db
def test_the_command_writes_the_file_from_the_table_and_the_tiles(segment_schemas, tmp_path):
    live, _ = segment_schemas
    # 1.2 km due east up the ramp in two ways, and the same climb on a mountain-bike-only way
    # a little north that must not be drawn.
    insert(live, 10, [east(0), east(600)])
    insert(live, 11, [east(600), east(1200)])
    insert(live, 12, [(WEST, LAT + 0.01), (WEST + 1200 / KX, LAT + 0.01)], mtb_only=True)
    ramp_tile(tmp_path / "elevation")
    out = tmp_path / "rebuild" / "climbs.json"
    stdout = io.StringIO()

    call_command(
        "build_climbs",
        out=out,
        elevation_dir=tmp_path / "elevation",
        schema=live,
        stdout=stdout,
    )

    doc = json.loads(out.read_text())
    (climb,) = doc["climbs"]
    assert climb["c"] == "4"  # about 100 m gained: a score near 10,000
    assert climb["g"] == pytest.approx(8.4, abs=0.2)
    assert climb["l"] == pytest.approx(1200, abs=35)
    assert [climb["x"], climb["y"]] == pytest.approx(list(east(1200)), abs=1e-4)
    assert doc["counts"]["4"] == 1
    assert "read 2 segments" in stdout.getvalue()
    assert "1 written" in stdout.getvalue()


@db
def test_no_ground_writes_nothing(segment_schemas, tmp_path):
    live, _ = segment_schemas
    insert(live, 10, [east(0), east(1200)])
    out = tmp_path / "climbs.json"
    out.write_text("the good file")
    (tmp_path / "elevation").mkdir()
    with pytest.raises(CommandError, match="no elevation tiles"):
        call_command("build_climbs", out=out, elevation_dir=tmp_path / "elevation", schema=live)
    assert out.read_text() == "the good file"


@db
def test_an_empty_table_writes_nothing(segment_schemas, tmp_path):
    live, _ = segment_schemas
    out = tmp_path / "climbs.json"
    with pytest.raises(CommandError, match="no routable segments"):
        call_command("build_climbs", out=out, elevation_dir=tmp_path, schema=live)
    assert not out.exists()
