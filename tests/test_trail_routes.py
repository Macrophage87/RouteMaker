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
        (
            {"type": "route", "route": "bicycle", "network": "ncn", "name": "Alpha Route"},
            [("w", 2, ""), ("n", 1, "")],
        ),
        (
            {"type": "route", "route": "hiking", "network": "nwn", "name": "Beta Walk"},
            [("w", 3, "")],
        ),
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
    routes = trail_routes.read_routes(path)
    assert routes.levels == {1: 1, 2: 3, 3: 2}
    assert routes.mountain_bike == {5}, "the way in the mtb route, whatever its network"
    assert routes.names == {2: "Alpha Route", 3: "Beta Walk"}, "the named routes' ways, by name"


def test_a_way_is_named_by_its_osm_name() -> None:
    assert trail_routes.way_name({"name": "Sligo Creek Trail"}) == "Sligo Creek Trail"
    assert trail_routes.way_name({"name": "  "}) is None
    assert trail_routes.way_name({"highway": "path"}) is None
    # A way with no name of its own takes its route's; its own name wins.
    assert trail_routes.way_name({"highway": "path"}, "Grist Mill Trail") == "Grist Mill Trail"
    assert trail_routes.way_name({"name": "Pigs Run"}, "Grist Mill Trail") == "Pigs Run"


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


@pytest.mark.parametrize(
    ("tags", "mountain_bike"),
    [
        ({"highway": "path", "mtb:scale": "2"}, True),
        ({"highway": "path", "mtb:scale": "1-"}, True),
        ({"highway": "path", "mtb:scale:imba": "3"}, True),
        ({"highway": "path", "mtb": "designated"}, True),
        ({"highway": "path", "mtb:type": "xc"}, True),
        ({"highway": "path", "surface": "dirt", "mtb:scale": "2"}, True),
        # A zero is a trail anyone rides (the C&O towpath).
        ({"highway": "path", "surface": "dirt", "mtb:scale:imba": "0"}, False),
        # A paved way is not a mountain-bike trail (Upper Rock Creek, Cross County).
        ({"highway": "path", "surface": "asphalt", "mtb:scale": "1"}, False),
        ({"highway": "cycleway", "surface": "paved", "mtb": "designated"}, False),
        ({"highway": "path", "mtb": "yes"}, False),
        ({"highway": "path", "name": "Mount Vernon Trail"}, False),
    ],
)
def test_a_mountain_bike_way_is_read_from_its_tags(tags, mountain_bike) -> None:
    assert trail_routes.is_mountain_bike_way(tags) is mountain_bike


@db
class TestNameVariants:
    """One trail is often several OSM names: an extension, a connector, a colour."""

    def test_an_extension_a_connector_and_a_parenthetical_chain_with_the_trail(
        self, segment_schemas
    ) -> None:
        _live, staging = segment_schemas
        piece(staging, 1, "Grist Mill Trail", 0, 1500)
        piece(staging, 2, "Grist Mill Trail Extension", 1500, 1000)
        piece(staging, 3, "Grist Mill Trail (Extension)", 2500, 800)
        piece(staging, 4, "grist mill  trail connector", 3300, 700)
        trail_routes.derive_trail_runs(staging)
        got = runs(staging)
        assert set(got.values()) == {got[1]}
        assert got[1] == pytest.approx(4000, abs=60)

    def test_different_trails_are_still_different(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        piece(staging, 1, "Alpha Trail", 0, 1000)
        piece(staging, 2, "Alpha Trail Loop", 1000, 1000)
        piece(staging, 3, "Beta Connector", 2000, 1000)
        trail_routes.derive_trail_runs(staging)
        got = runs(staging)
        assert [round(got[i], -2) for i in (1, 2, 3)] == [1000, 1000, 1000]

    def test_a_way_the_route_relation_names_chains_with_its_trail(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        piece(staging, 1, "Grist Mill Trail", 0, 1500)
        piece(staging, 2, "Grist Mill Trail", 1500, 1000)  # the name the pipeline fills in
        trail_routes.derive_trail_runs(staging)
        assert runs(staging)[1] == pytest.approx(2500, abs=40)


def bridge(schema, way, name, start_m, length_m, unpaved=True, **kw):
    """A bridge candidate (what the pipeline writes for a bridge=* way)."""
    piece(schema, way, name, start_m, length_m, **kw)
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {schema}.segment SET trail_bridge = 3, is_unpaved = %s WHERE osm_way_id = %s",
            [unpaved, way],
        )


def bridge_state(schema, way) -> tuple:
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT trail_bridge, trail_route, trail_run_m FROM {schema}.segment "
            "WHERE osm_way_id = %s",
            [way],
        )
        return cursor.fetchone()


def set_trail(schema, way, route=0, unpaved=False) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {schema}.segment SET trail_route = %s, is_unpaved = %s WHERE osm_way_id = %s",
            [route, unpaved, way],
        )


@db
class TestBridges:
    """A short bridge inside a kept trail takes its trail's status."""

    def test_a_bridge_between_paved_ways_is_judged_as_the_trail(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        piece(staging, 1, "Grist Mill Trail", 0, 1500)
        bridge(staging, 2, "Grist Mill Trail", 1500, 50)
        piece(staging, 3, "Grist Mill Trail", 1550, 1500)
        set_trail(staging, 1, 3)
        set_trail(staging, 3, 3)
        trail_routes.derive_trail_runs(staging)
        flag, route, run = bridge_state(staging, 2)
        assert (flag, route) == (1, 3)
        assert run == pytest.approx(3050, abs=60)

    def test_a_bridge_next_to_an_unpaved_way_is_judged_unpaved(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        piece(staging, 1, "Dirt Trail", 0, 1500)
        bridge(staging, 2, "Dirt Trail", 1500, 50)
        piece(staging, 3, "Dirt Trail", 1550, 1500)
        set_trail(staging, 1, 0, True)
        trail_routes.derive_trail_runs(staging)
        assert bridge_state(staging, 2)[0] == 2

    def test_the_bridge_takes_the_lower_of_its_two_ends(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        piece(staging, 1, "Same Trail", 0, 3000)
        bridge(staging, 2, "Same Trail", 3000, 50)
        piece(staging, 3, "Same Trail", 3050, 3000)
        set_trail(staging, 1, 3)
        trail_routes.derive_trail_runs(staging)
        assert bridge_state(staging, 2)[1] == 0

    def test_a_bridge_at_the_end_of_a_trail_extends_nothing(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        piece(staging, 1, "Long Trail", 0, 3000)
        bridge(staging, 2, "Long Trail", 3000, 50)
        trail_routes.derive_trail_runs(staging)
        assert bridge_state(staging, 2)[0] == 0

    def test_a_bridge_on_its_own_is_not_kept(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        bridge(staging, 1, "Lone Bridge", 0, 50)
        trail_routes.derive_trail_runs(staging)
        assert bridge_state(staging, 1)[0] == 0

    def test_a_long_bridge_is_not_a_short_one(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        piece(staging, 1, "Trail", 0, 1500)
        bridge(staging, 2, "Trail", 1500, 150)
        piece(staging, 3, "Trail", 1650, 1500)
        trail_routes.derive_trail_runs(staging)
        assert bridge_state(staging, 2)[0] == 0

    @pytest.mark.parametrize(
        ("tags", "candidate"),
        [
            ({"bridge": "yes"}, True),
            ({"bridge": "boardwalk"}, True),
            ({"bridge": "viaduct"}, True),
            ({"bridge": "no"}, False),
            ({}, False),
        ],
    )
    def test_a_bridge_way_is_read_from_its_tag(self, tags, candidate) -> None:
        assert trail_routes.is_bridge_way(tags) is candidate

    def test_the_cap_is_100_metres(self) -> None:
        from pipeline.schema import TRAIL_BRIDGE_MAX_M

        assert TRAIL_BRIDGE_MAX_M == 100
