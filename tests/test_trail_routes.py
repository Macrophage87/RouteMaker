"""What the zoomed-out long trails are read from (OWNER-DECISIONS 375).

The route relations a way is in, read from the extract, and the length of a
named run, derived in the staging schema; `tests/test_stress_tiles.py` holds
what the tiles then keep.
"""

from __future__ import annotations

import osmium
import pytest
from django.db import connection, utils

from pipeline import trail_routes
from pipeline.schema import TRAIL_RUN_GAP_M
from pipeline.writers import segment_row, write_segments
from routemaker.stress import Stress, StressResult

db = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize(
    ("route", "network", "level"),
    [
        ("bicycle", "icn", 3),
        ("bicycle", "ncn", 3),
        ("bicycle", "rcn", 3),
        ("bicycle", "lcn", 1),
        ("bicycle", None, 1),
        ("hiking", "US:NST", 2),
        ("hiking", "nwn", 2),
        ("foot", "rwn", 2),
        ("hiking", "lwn", 0),
        ("hiking", None, 0),
        ("mtb", "rcn", 0),
        ("mtb", None, 0),
        ("road", "ncn", 0),
        (None, None, 0),
    ],
)
def test_a_route_relation_gives_its_ways_a_level(route, network, level) -> None:
    assert trail_routes.route_level(route, network) == level


def test_the_levels_are_the_schemas() -> None:
    from pipeline import schema

    assert (schema.ROUTE_ANY_BICYCLE, schema.ROUTE_LONG_WALK, schema.ROUTE_LONG_BICYCLE) == (
        1,
        2,
        3,
    )


def write_extract(path) -> None:
    writer = osmium.SimpleWriter(str(path))
    for node_id in (1, 2):
        writer.add_node(
            osmium.osm.mutable.Node(id=node_id, location=(-77.0 + node_id / 100, 38.9), version=1)
        )
    for way_id in range(1, 7):
        writer.add_way(osmium.osm.mutable.Way(id=way_id, nodes=[1, 2], version=1))
    relations = [
        ({"type": "route", "route": "bicycle", "network": "lcn"}, [("w", 1, ""), ("w", 2, "")]),
        ({"type": "route", "route": "bicycle", "network": "ncn"}, [("w", 2, ""), ("n", 1, "")]),
        ({"type": "route", "route": "hiking", "network": "nwn"}, [("w", 3, "")]),
        ({"type": "route", "route": "hiking", "network": "lwn"}, [("w", 4, "")]),
        ({"type": "route", "route": "mtb", "network": "rcn"}, [("w", 5, "")]),
        ({"type": "network", "route": "bicycle", "network": "ncn"}, [("w", 6, "")]),
    ]
    for relation_id, (tags, members) in enumerate(relations, start=1):
        writer.add_relation(
            osmium.osm.mutable.Relation(id=relation_id, members=members, tags=tags, version=1)
        )
    writer.close()


def test_the_extracts_route_relations_are_read_by_member_way(tmp_path) -> None:
    path = tmp_path / "routes.osm.pbf"
    write_extract(path)
    # The highest level wins on a way in two; a node member, a local walking
    # route, a mountain-bike route and a relation that is not a route give nothing.
    assert trail_routes.read_routes(path) == {1: 1, 2: 3, 3: 2}


def test_a_way_is_named_by_its_osm_name() -> None:
    assert trail_routes.way_name({"name": "Sligo Creek Trail"}) == "Sligo Creek Trail"
    assert trail_routes.way_name({"name": "  "}) is None
    assert trail_routes.way_name({"highway": "path"}) is None


LAT = 39.0
DEG_PER_METRE = 1 / (111_320 * 0.7771)  # a degree of longitude at 39 N


def piece(schema, way, name, start_m, length_m, rule="Y", facility="path", lat=LAT):
    """A path of `length_m` metres east of -77.0, `start_m` along, named `name`."""
    west = -77.0 + start_m * DEG_PER_METRE
    east = west + length_m * DEG_PER_METRE
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {schema}.segment (osm_way_id, ordinal, geometry, stress_tier, "
            "stress_rule, is_trail_class, facility, trail_name) VALUES "
            "(%s, 0, ST_MakeLine(ST_MakePoint(%s, %s), ST_MakePoint(%s, %s)), 1, %s, true, %s, %s)",
            [way, west, lat, east, lat, rule, facility, name],
        )


def runs(schema) -> dict:
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT osm_way_id, trail_run_m FROM {schema}.segment ORDER BY 1")
        return dict(cursor.fetchall())


@db
class TestRuns:
    def test_same_named_ways_that_chain_are_one_run(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        piece(staging, 1, "Alpha Trail", 0, 2000)
        piece(staging, 2, "Alpha Trail", 2000 + TRAIL_RUN_GAP_M - 50, 1500)  # a road between
        piece(staging, 3, "ALPHA TRAIL", 3500 + 2 * TRAIL_RUN_GAP_M, 1000)  # names are case-blind
        trail_routes.derive_trail_runs(staging)
        got = runs(staging)
        assert got[1] == got[2] and got[1] == pytest.approx(3500, abs=40)
        assert got[3] == pytest.approx(1000, abs=20), "past the gap, a run of its own"

    def test_a_name_in_two_places_is_two_runs(self, segment_schemas) -> None:
        # Red Trail is every park's: a name's whole length is not a trail's.
        _live, staging = segment_schemas
        piece(staging, 1, "Red Trail", 0, 1000)
        piece(staging, 2, "Red Trail", 0, 1200, lat=LAT + 0.2)
        trail_routes.derive_trail_runs(staging)
        got = runs(staging)
        assert got[1] == pytest.approx(1000, abs=20)
        assert got[2] == pytest.approx(1200, abs=20)

    def test_an_unnamed_way_and_a_way_the_map_does_not_draw_have_no_run(
        self, segment_schemas
    ) -> None:
        _live, staging = segment_schemas
        piece(staging, 1, None, 0, 1000)
        street = "mixed traffic, 25 mph, single lane"
        piece(staging, 2, "A Street", 0, 1000, rule=street, facility="none", lat=LAT + 0.1)
        trail_routes.derive_trail_runs(staging)
        assert runs(staging) == {1: None, 2: None}

    def test_a_way_that_is_hidden_does_not_lengthen_a_run(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        piece(staging, 1, "Beta Trail", 0, 1000)
        piece(staging, 2, "Beta Trail", 1000, 5000)
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {staging}.segment SET map_class = 'hidden' WHERE osm_way_id = 2"
            )
        trail_routes.derive_trail_runs(staging)
        got = runs(staging)
        assert got[1] == pytest.approx(1000, abs=20) and got[2] is None

    def test_a_schema_name_is_validated(self) -> None:
        with pytest.raises(ValueError):
            trail_routes.derive_trail_runs("live; DROP SCHEMA public")


@db
class TestColumns:
    def test_the_writer_carries_the_name_and_the_route_level(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        stress = StressResult(Stress.LTS1, "trail")
        line = [(-77.0, 38.9), (-77.01, 38.91)]
        rows = [
            segment_row(1, 0, line, stress, trail_name="Rock Creek Trail", trail_route=3),
            segment_row(2, 0, line, stress),
        ]
        assert write_segments(staging, rows) == 2
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT osm_way_id, trail_name, trail_route, trail_run_m FROM {staging}.segment "
                "ORDER BY 1"
            )
            assert cursor.fetchall() == [(1, "Rock Creek Trail", 3, None), (2, None, 0, None)]

    def test_a_route_level_out_of_range_is_refused(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        stress = StressResult(Stress.LTS1, "trail")
        row = segment_row(1, 0, [(-77.0, 38.9), (-77.01, 38.91)], stress, trail_route=4)
        with pytest.raises(utils.IntegrityError):
            write_segments(staging, [row])
