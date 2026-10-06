"""What the zoomed-out long trails are read from (OWNER-DECISIONS 375).

The route relations a way is in, read from the extract, and the length of a
named run, derived in the staging schema; `tests/test_stress_tiles.py` holds
what the tiles then keep.
"""

from __future__ import annotations

import osmium
import pytest
from django.db import connection, utils

from pipeline import calm_roads, trail_routes
from pipeline.run import ValidationFailed, assert_calm_runs, assert_long_trails
from pipeline.schema import CALM_PATH_GAP_M, TRAIL_RUN_GAP_M
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
        # Several values, as OSM separates them: the highest, and never an mtb one.
        ("bicycle;hiking", "rcn", 3),
        ("hiking;mtb", "rwn", 0),
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
    for way_id in range(1, 9):
        writer.add_way(osmium.osm.mutable.Way(id=way_id, nodes=[1, 2], version=1))
    relations = [
        (
            {"type": "route", "route": "bicycle", "network": "lcn", "name": "Local Loop"},
            [("w", 1, ""), ("w", 2, "")],
        ),
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
        # A walking route that is a mountain-bike route as well (Fort Circle Park).
        ({"type": "route", "route": "hiking;mtb", "network": "rwn"}, [("w", 7, "")]),
        # A local route's name and a national route's on one way: the national one's.
        (
            {"type": "route", "route": "bicycle", "network": "lcn", "name": "Local"},
            [("w", 8, "")],
        ),
        (
            {"type": "route", "route": "bicycle", "network": "ncn", "name": "National"},
            [("w", 8, "")],
        ),
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
    assert routes.levels == {1: 1, 2: 3, 3: 2, 8: 3}
    assert routes.mountain_bike == {5, 7}, "the ways in an mtb route, whatever its network"
    # The long routes' names, the highest level's; a local route names nothing
    # (377), so way 1 has none.
    assert routes.names == {2: "Alpha Route", 3: "Beta Walk", 8: "National"}


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

    def test_the_gap_is_400_metres(self) -> None:
        # Measured: at 200 m Cabin John Trail kept 0.1 mi of 5.3 (ZOOMED-TRAILS).
        assert TRAIL_RUN_GAP_M == 400


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

    def test_extn_connection_and_a_bracket_chain_too(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        piece(staging, 1, "Foo Trail", 0, 1000)
        piece(staging, 2, "Foo Trail Extn", 1000, 1000)
        piece(staging, 3, "Foo Trail Connection", 2000, 1000)
        piece(staging, 4, "Foo Trail [north]", 3000, 1000)
        trail_routes.derive_trail_runs(staging)
        got = runs(staging)
        assert set(got.values()) == {got[1]}
        assert got[1] == pytest.approx(4000, abs=60)

    def test_a_suffix_counts_only_at_the_end_of_the_name(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        piece(staging, 1, "Foo Trail", 0, 1000)
        piece(staging, 2, "Foo Connector Trail", 1000, 1000)
        trail_routes.derive_trail_runs(staging)
        assert runs(staging)[1] == pytest.approx(1000, abs=20)

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

    def test_the_cap_is_on_the_bridge_and_its_boundary_holds(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        piece(staging, 1, "T", 0, 1500)
        bridge(staging, 2, "T", 1500, 95)
        piece(staging, 3, "T", 1595, 1500)
        piece(staging, 4, "U", 0, 1500, lat=LAT + 0.1)
        bridge(staging, 5, "U", 1500, 120, lat=LAT + 0.1)
        piece(staging, 6, "U", 1620, 1500, lat=LAT + 0.1)
        trail_routes.derive_trail_runs(staging)
        assert bridge_state(staging, 2)[0] == 1
        assert bridge_state(staging, 5)[0] == 0

    def test_the_run_is_the_lower_ends(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        piece(staging, 1, "Long Trail", 0, 3000)
        bridge(staging, 2, None, 3000, 50)
        piece(staging, 3, "Short Trail", 3050, 500)
        trail_routes.derive_trail_runs(staging)
        assert bridge_state(staging, 2)[2] == pytest.approx(500, abs=20)

    def test_an_unpaved_far_end_makes_the_bridge_unpaved(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        piece(staging, 1, "D", 0, 1500)
        bridge(staging, 2, "D", 1500, 50)
        piece(staging, 3, "D", 1550, 1500)
        set_trail(staging, 3, 0, True)
        trail_routes.derive_trail_runs(staging)
        assert bridge_state(staging, 2)[0] == 2

    def test_the_same_named_end_is_preferred(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        piece(staging, 1, "Mine", 0, 1500)
        spur(staging, 9, "Spur", 1500)
        bridge(staging, 2, "Mine", 1500, 50)
        piece(staging, 3, "Mine", 1550, 1500)
        set_trail(staging, 9, 3)
        set_trail(staging, 3, 3)
        trail_routes.derive_trail_runs(staging)
        assert bridge_state(staging, 2)[1] == 0, "the route-3 spur is not its trail"

    def test_an_unnamed_bridge_prefers_the_named_trail_to_an_unnamed_link(
        self, segment_schemas
    ) -> None:
        # Correctness review NIT 2: an unnamed connector at the abutment ranked
        # first and dropped the bridge.
        _live, staging = segment_schemas
        piece(staging, 1, "Long Trail", 0, 1500)
        spur(staging, 9, None, 1500)
        bridge(staging, 2, None, 1500, 50)
        piece(staging, 3, "Long Trail", 1550, 1500)
        trail_routes.derive_trail_runs(staging)
        flag, _route, run = bridge_state(staging, 2)
        assert flag == 1 and run == pytest.approx(3000, abs=60)

    def test_an_end_must_touch(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        piece(staging, 1, "T", 0, 1500)
        bridge(staging, 2, "T", 1500, 50)
        piece(staging, 3, "T", 1560, 1500)  # 10 m short of the bridge's end
        trail_routes.derive_trail_runs(staging)
        assert bridge_state(staging, 2)[0] == 0

    def test_an_end_must_be_a_trail(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        piece(staging, 1, "T", 0, 1500)
        bridge(staging, 2, "T", 1500, 50)
        street = "mixed traffic, 25 mph, single lane"
        piece(staging, 3, "A Street", 1550, 1500, rule=street, facility="none")
        set_trail(staging, 1, 3)
        set_trail(staging, 3, 3)
        trail_routes.derive_trail_runs(staging)
        assert bridge_state(staging, 2)[0] == 0, "a street on a route hands a bridge nothing"

    def test_two_touching_wooden_bridges_are_judged_as_one(self, segment_schemas) -> None:
        # Correctness review SF1: each one's inner end met only the other
        # candidate, so a boardwalk mapped as two ways left a hole.
        _live, staging = segment_schemas
        piece(staging, 1, "Boardwalk Trail", 0, 1500)
        bridge(staging, 2, "Boardwalk Trail", 1500, 40)
        bridge(staging, 3, None, 1540, 40)
        piece(staging, 4, "Boardwalk Trail", 1580, 1500)
        trail_routes.derive_trail_runs(staging)
        for way in (2, 3):
            flag, _route, run = bridge_state(staging, way)
            assert flag == 1, way
            assert run == pytest.approx(3080, abs=60), "the trail's run, the deck's in it"

    def test_a_chain_is_capped_in_all(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        piece(staging, 1, "Boardwalk Trail", 0, 1500)
        bridge(staging, 2, "Boardwalk Trail", 1500, 60)
        bridge(staging, 3, "Boardwalk Trail", 1560, 60)
        piece(staging, 4, "Boardwalk Trail", 1620, 1500)
        trail_routes.derive_trail_runs(staging)
        assert (bridge_state(staging, 2)[0], bridge_state(staging, 3)[0]) == (0, 0)

    def test_a_bridge_keeps_its_own_route(self, segment_schemas) -> None:
        # Spec review SF3: a bridge on a regional route is not lowered by an end.
        _live, staging = segment_schemas
        piece(staging, 1, "R", 0, 1500)
        bridge(staging, 2, "R", 1500, 50)
        piece(staging, 3, None, 1550, 300)
        set_trail(staging, 1, 3)
        set_trail(staging, 2, 3, True)
        trail_routes.derive_trail_runs(staging)
        assert bridge_state(staging, 2)[1] == 3

    def test_an_end_kept_by_its_route_sets_no_bar_on_the_run(self, segment_schemas) -> None:
        # Correctness review NIT 3: where a trail leaves its regional route at a
        # bridge, the far end's long run keeps it.
        _live, staging = segment_schemas
        piece(staging, 1, None, 0, 1500)
        bridge(staging, 2, None, 1500, 50)
        piece(staging, 3, "Run Trail", 1550, 5000)
        set_trail(staging, 1, 3)
        trail_routes.derive_trail_runs(staging)
        flag, route, run = bridge_state(staging, 2)
        assert (flag, route) == (1, 0)
        assert run == pytest.approx(5000, abs=60)

    def test_no_candidate_is_left_unjudged(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        bridge(staging, 1, "Lone Bridge", 0, 50)
        bridge(staging, 2, "Long Bridge", 0, 500, lat=LAT + 0.1)
        trail_routes.derive_trail_runs(staging)
        summary = trail_routes.long_trail_summary(staging, (), 4023)
        assert summary.unjudged_bridges == 0


def spur(schema, way, name, at_m) -> None:
    """A path of 330 m running north from `at_m` along the test latitude."""
    x = -77.0 + at_m * DEG_PER_METRE
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {schema}.segment (osm_way_id, ordinal, geometry, stress_tier, "
            "stress_rule, is_trail_class, facility, trail_name) VALUES "
            "(%s, 0, ST_MakeLine(ST_MakePoint(%s, %s), ST_MakePoint(%s, %s)), 1, 'Y', true, "
            "'path', %s)",
            [way, x, LAT, x, LAT + 0.003, name],
        )


@pytest.mark.parametrize(
    ("facility", "trail", "car_free", "drawn"),
    [
        ("path", True, (), True),
        ("path", False, (), True),
        ("protected", True, (), True),
        ("protected", False, (), False),
        ("lane", False, (), False),
        ("none", False, ("weekend",), True),
        ("none", False, (), False),
    ],
)
def test_only_the_ways_the_zoomed_out_map_draws_are_long_trail_ways(
    facility, trail, car_free, drawn
) -> None:
    assert trail_routes.is_zoomed_out_trail(facility, trail, car_free) is drawn


@db
class TestValidation:
    """What VALIDATE reads back before a promotion (operations review SF-1)."""

    def summary(self, staging, ways=(7,)):
        return trail_routes.long_trail_summary(staging, ways, 4023)

    def test_the_summary_counts_the_columns(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        piece(staging, 7, "Sentinel Trail", 0, 14_000)
        piece(staging, 8, "Short", 0, 100, lat=LAT + 0.1)
        set_trail(staging, 7, 3)
        trail_routes.derive_trail_runs(staging)
        got = self.summary(staging)
        assert (got.on_long_route, got.in_long_run, got.unjudged_bridges) == (1, 1, 0)
        assert got.sentinels[7][0] == 3 and got.sentinels[7][1] == pytest.approx(14_000, abs=100)
        assert_long_trails(got, (7,), (1, 1))

    def test_a_sentinel_off_its_route_or_short_is_refused(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        piece(staging, 7, "Sentinel Trail", 0, 14_000)
        trail_routes.derive_trail_runs(staging)
        with pytest.raises(ValidationFailed, match="route level 0"):
            assert_long_trails(self.summary(staging), (7,), (0, 0))
        set_trail(staging, 7, 3)
        with connection.cursor() as cursor:
            cursor.execute(f"UPDATE {staging}.segment SET trail_run_m = 12000")
        with pytest.raises(ValidationFailed, match="a run of 12000 m"):
            assert_long_trails(self.summary(staging), (7,), (0, 0))

    def test_a_missing_sentinel_is_refused(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        with pytest.raises(ValidationFailed, match="not in the segment table"):
            assert_long_trails(self.summary(staging), (7,), (0, 0))

    def test_too_few_rows_are_refused(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        piece(staging, 7, "Sentinel Trail", 0, 14_000)
        set_trail(staging, 7, 3)
        trail_routes.derive_trail_runs(staging)
        with pytest.raises(ValidationFailed, match="under the floors"):
            assert_long_trails(self.summary(staging), (7,), (2, 0))
        with pytest.raises(ValidationFailed, match="under the floors"):
            assert_long_trails(self.summary(staging), (7,), (0, 2))

    def test_an_unjudged_bridge_is_refused(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        bridge(staging, 1, "Lone Bridge", 0, 50)
        with pytest.raises(ValidationFailed, match="trail_bridge 3"):
            assert_long_trails(self.summary(staging, ()), (), (0, 0))


# ---- THE CALM RUNS (OWNER-DECISIONS 391, 402, 402a) ----------------------------------------

STREET = "mixed traffic, 25 mph, single lane, low volume"
DEG_PER_METRE_LAT = 1 / 110_574


def calm_piece(
    schema, way, name, start_m, length_m, *, path=False, calm=0, lat=LAT, trail_run=None
) -> None:
    """A candidate for the ride layer: a street (LTS 1, no facility) or, with `path`, a path,
    `length_m` metres east of -77.0, `start_m` along, with `calm_run_m` `calm` (0: a candidate
    the derive has not reached; None: not one)."""
    west = -77.0 + start_m * DEG_PER_METRE
    east = west + length_m * DEG_PER_METRE
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {schema}.segment (osm_way_id, ordinal, geometry, stress_tier, "
            "stress_rule, is_trail_class, facility, trail_name, calm_run_m, trail_run_m) VALUES "
            "(%s, 0, ST_MakeLine(ST_MakePoint(%s, %s), ST_MakePoint(%s, %s)), 1, %s, %s, %s, %s, "
            "%s, %s)",
            [
                way, west, lat, east, lat, "Y" if path else STREET, path,
                "path" if path else "none", name, calm, trail_run,
            ],
        )  # fmt: skip


def road(schema, way, name, *points, tier=1, calm=0, unsmoothed=None, map_class="road") -> None:
    """A road through `points`, (east, north) in metres from (-77.0, LAT), at `tier`, a calm
    candidate (`calm` 0) or not (None). The same metres give the same vertex, so two roads
    given one point share it, as OSM's ways share a node."""
    coords = [(-77.0 + x * DEG_PER_METRE, LAT + y * DEG_PER_METRE_LAT) for x, y in points]
    wkt = "LINESTRING(" + ",".join(f"{lon!r} {lat!r}" for lon, lat in coords) + ")"
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {schema}.segment (osm_way_id, ordinal, geometry, stress_tier, "
            "stress_rule, is_trail_class, facility, trail_name, calm_run_m, "
            "stress_unsmoothed_tier, map_class) VALUES "
            "(%s, 0, ST_GeomFromText(%s, 4326), %s, %s, false, 'none', %s, %s, %s, %s)",
            [way, wkt, tier, STREET, name, calm, unsmoothed, map_class],
        )


def busy(schema, way, *points, tier=3, map_class="road") -> None:
    """A road at LTS 3 or above: never a candidate, and the junctions with it are stressful."""
    road(schema, way, "Busy Pike", *points, tier=tier, calm=None, map_class=map_class)


def calm_runs(schema) -> dict:
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT osm_way_id, calm_run_m FROM {schema}.segment ORDER BY 1")
        return dict(cursor.fetchall())


def test_the_gap_and_the_turns_are_named_constants() -> None:
    # A path network chains across a road crossing (100 ft). A calm road's run goes on along
    # its own name through a turn of up to 100 degrees, along another name up to 45.
    assert CALM_PATH_GAP_M == 30
    assert (calm_roads.SAME_NAME_TURN_DEG, calm_roads.STRAIGHT_ON_DEG) == (100.0, 45.0)
    # The junction model's busy tier (396): the one test of a stressful junction.
    assert calm_roads.BUSY_TIER == 3


@pytest.mark.parametrize(
    ("kwargs", "candidate"),
    [
        # A path or trail the zoomed-out map draws, a road at LTS 1 or LTS 2 ("LTS2 counts").
        ({"zoomed_out_trail": True}, True),
        ({"stress_tier": 1}, True),
        ({"stress_tier": 2}, True),
        ({"zoomed_out_trail": True, "stress_tier": 2}, True),
        # Never a mountain-bike trail, in either way of knowing it, nor an undrawn way.
        ({"zoomed_out_trail": True, "mountain_bike": True}, False),
        ({"zoomed_out_trail": True, "mtb_only": True}, False),
        ({"stress_tier": 1, "mountain_bike": True}, False),
        ({"stress_tier": 2, "mtb_only": True}, False),
        ({"zoomed_out_trail": True, "map_class": "hidden"}, False),
        ({"zoomed_out_trail": True, "map_class": "barred"}, False),
        ({"stress_tier": 1, "map_class": "alley"}, False),
        # A road at LTS 3 or above is not a calm road; a trail-class way the map does not
        # draw (a footway with no bicycle access, say) is not a path.
        ({"stress_tier": 3}, False),
        ({"stress_tier": 5}, False),
        ({"stress_tier": 1, "is_trail_class": True}, False),
        ({"stress_tier": 2, "is_trail_class": True}, False),
    ],
)
def test_which_ways_can_be_in_the_ride_layer(kwargs, candidate) -> None:
    base = {
        "zoomed_out_trail": False,
        "mountain_bike": False,
        "mtb_only": False,
        "is_trail_class": False,
        "stress_tier": 9,
        "map_class": "road",
    }
    assert trail_routes.is_calm_candidate(**{**base, **kwargs}) is candidate


# The pure part: how a run goes through a junction.


@pytest.mark.parametrize(
    ("a", "b", "turn"),
    [
        (0.0, 180.0, 0.0),  # in from the north, out to the south: straight on
        (90.0, 270.0, 0.0),
        (0.0, 90.0, 90.0),  # a right angle
        (350.0, 170.0, 0.0),  # across north
        (10.0, 150.0, 40.0),
        (0.0, 0.0, 180.0),  # back the way it came
        (None, 90.0, 180.0),  # two vertices in one place: no bearing, a full turn
        (90.0, None, 180.0),
    ],
)
def test_the_turn_at_a_junction(a, b, turn) -> None:
    assert calm_roads.turn_deg(a, b) == pytest.approx(turn)


def test_two_ends_always_go_on_and_one_never_does() -> None:
    # A way split for a tag, a name that changes, a sharp bend: where only two calm roads
    # meet the run goes on, whatever the angle.
    assert calm_roads.pairs([(0, 0.0, 1), (3, 10.0, 2)]) == [(0, 3)]
    assert calm_roads.pairs([(0, 0.0, 1)]) == []
    assert calm_roads.pairs([]) == []


def test_at_a_crossing_the_straight_roads_go_on() -> None:
    # A four-way junction of Main (east-west) and Cross (north-south): each goes straight on.
    ends = [(0, 270.0, 1), (2, 90.0, 1), (4, 0.0, 2), (6, 180.0, 2)]
    assert sorted(calm_roads.pairs(ends)) == [(0, 2), (4, 6)]


def test_the_own_name_goes_on_round_a_corner_before_a_straighter_other_name() -> None:
    # Oak comes in from the west and turns north; Pine carries straight on east. Oak's own
    # name wins at 90 degrees (within SAME_NAME_TURN_DEG); Pine starts a run of its own.
    ends = [(0, 270.0, 1), (2, 0.0, 1), (4, 90.0, 2)]
    assert calm_roads.pairs(ends) == [(0, 2)]
    # Past the same-name limit, the straight road of another name goes on instead.
    ends = [(0, 270.0, 1), (2, 270.0 - 180 + 110, 1), (4, 90.0, 2)]
    assert calm_roads.pairs(ends) == [(0, 4)]


def test_another_name_goes_on_only_nearly_straight() -> None:
    # A T of three names: the stem meets the bar at a right angle, so only the bar goes on,
    # and a road of another name 50 degrees off straight is not the same run.
    ends = [(0, 270.0, 1), (2, 90.0, 2), (4, 180.0, 3)]
    assert calm_roads.pairs(ends) == [(0, 2)]
    ends = [(0, 270.0, 1), (2, 40.0, 2), (4, 155.0, 3)]
    assert calm_roads.pairs(ends) == []
    ends = [(0, 270.0, 1), (2, 135.0, 2), (4, 180.0, 3)]  # 45 degrees: at the limit
    assert calm_roads.pairs(ends) == [(0, 2)]


def test_each_end_goes_on_into_one_other_at_most() -> None:
    # Three roads of one name almost in a line: the straightest pair goes on, the third ends.
    ends = [(0, 270.0, 1), (2, 90.0, 1), (4, 95.0, 1)]
    assert calm_roads.pairs(ends) == [(0, 2)]


def junction(row, node, at_m, back=None, fwd=None, busy=False, name=1):
    return calm_roads.Junction(row, node, at_m, back, fwd, busy, name)


def test_runs_join_at_a_calm_node_and_end_at_a_busy_one() -> None:
    # Row 1 runs from node 10 to 11 (500 m), row 2 from 11 to 12 (700 m): one run of 1,200 m.
    calm = [
        junction(1, 10, 0.0, fwd=90.0),
        junction(1, 11, 500.0, back=270.0),
        junction(2, 11, 0.0, fwd=90.0),
        junction(2, 12, 700.0, back=270.0),
    ]
    assert calm_roads.runs_of(calm) == {1: 1200, 2: 1200}
    # A busy road meets them at node 11: two runs.
    stressful = [*calm[:2], calm[2]._replace(busy=True), calm[3]]
    assert calm_roads.runs_of(stressful) == {1: 500, 2: 700}


def test_a_row_a_busy_road_crosses_keeps_its_longer_side() -> None:
    # Row 1 is crossed at 300 m (node 21, a busy road's vertex): its sides are 300 and 900 m.
    rows = [
        junction(1, 20, 0.0, fwd=90.0),
        junction(1, 21, 300.0, back=270.0, fwd=90.0, busy=True),
        junction(1, 22, 1200.0, back=270.0),
    ]
    assert calm_roads.runs_of(rows) == {1: 900}


# Through the derive, on the staging schema.


@db
class TestCalmRoads:
    """A calm road's run (OWNER-DECISIONS 402a): continuous LTS 1 and 2 road, across names,
    ended at every junction with a road at LTS 3 or above."""

    def test_same_named_rows_that_meet_are_one_run(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        road(staging, 1, "Lakeview Drive", (0, 0), (800, 0))
        road(staging, 2, "LAKEVIEW DRIVE", (800, 0), (1300, 0))
        road(staging, 3, "Lakeview Drive", (1400, 0), (1800, 0))  # 100 m on: not touching
        trail_routes.derive_calm_runs(staging)
        got = calm_runs(staging)
        assert got[1] == got[2] == pytest.approx(1300, abs=5)
        assert got[3] == pytest.approx(400, abs=5), "a gap ends a run: it is continuous"

    def test_a_run_goes_on_across_a_change_of_name_and_counts_lts_2(self, segment_schemas):
        _live, staging = segment_schemas
        road(staging, 1, "River Road", (0, 0), (1500, 0))
        road(staging, 2, "Seneca Road", (1500, 0), (2600, 100), tier=2)
        road(staging, 3, "Elm Street", (2600, 100), (3600, 100))
        trail_routes.derive_calm_runs(staging)
        got = calm_runs(staging)
        assert got[1] == got[2] == got[3] == pytest.approx(3604, abs=10)

    def test_a_busy_road_crossing_at_a_shared_node_breaks_the_run(self, segment_schemas):
        _live, staging = segment_schemas
        road(staging, 1, "Oak Street", (0, 0), (500, 0), (1500, 0))
        busy(staging, 9, (500, -200), (500, 0), (500, 200))
        trail_routes.derive_calm_runs(staging)
        got = calm_runs(staging)
        assert got[1] == pytest.approx(1000, abs=5), "the longer side of the crossing"
        assert got[9] is None, "the busy road is not a candidate"

    def test_joining_a_busy_road_ends_the_run_whatever_the_name(self, segment_schemas):
        _live, staging = segment_schemas
        road(staging, 1, "Oak Street", (0, 0), (500, 0))
        road(staging, 2, "Oak Street", (500, 0), (1500, 0))
        busy(staging, 9, (500, 0), (500, 400))  # a T: the busy road joins at the node
        trail_routes.derive_calm_runs(staging)
        got = calm_runs(staging)
        assert (got[1], got[2]) == (pytest.approx(500, abs=5), pytest.approx(1000, abs=5))

    @pytest.mark.parametrize(
        ("tier", "unsmoothed", "map_class", "breaks"),
        [
            (3, None, "road", True),
            (4, None, "road", True),
            (5, None, "road", True),  # Avoid
            (4, None, "barred", True),  # a road bikes may not use is still a busy junction
            (2, 3, "road", True),  # smoothed to LTS 2, but the junction model reads 3 (285)
            (2, None, "road", False),  # a junction of calm roads does not
            (2, None, "hidden", False),  # nor a driveway or a parking aisle
        ],
    )
    def test_which_junctions_are_stressful(
        self, segment_schemas, tier, unsmoothed, map_class, breaks
    ) -> None:
        _live, staging = segment_schemas
        road(staging, 1, "Oak Street", (0, 0), (500, 0), (1500, 0))
        road(
            staging, 9, "Side Road", (500, -200), (500, 0), (500, 200),
            tier=tier, calm=None, unsmoothed=unsmoothed, map_class=map_class,
        )  # fmt: skip
        trail_routes.derive_calm_runs(staging)
        assert calm_runs(staging)[1] == pytest.approx(1000 if breaks else 1500, abs=5)

    def test_a_road_passing_over_without_a_shared_node_does_not_break_it(self, segment_schemas):
        # A bridge or an underpass: the busy road crosses the line but shares no vertex.
        _live, staging = segment_schemas
        road(staging, 1, "Oak Street", (0, 0), (1500, 0))
        busy(staging, 9, (500, -200), (500, 200))
        trail_routes.derive_calm_runs(staging)
        assert calm_runs(staging)[1] == pytest.approx(1500, abs=5)

    def test_a_grid_is_many_short_runs_not_one_network(self, segment_schemas) -> None:
        # Main Street east-west and Cross Street north-south meet at (500, 0): each goes
        # straight on, and neither is lengthened by the other.
        _live, staging = segment_schemas
        road(staging, 1, "Main Street", (0, 0), (500, 0))
        road(staging, 2, "Main Street", (500, 0), (1000, 0))
        road(staging, 3, "Cross Street", (500, -300), (500, 0))
        road(staging, 4, "Cross Street", (500, 0), (500, 300))
        trail_routes.derive_calm_runs(staging)
        got = calm_runs(staging)
        assert got[1] == got[2] == pytest.approx(1000, abs=5)
        assert got[3] == got[4] == pytest.approx(600, abs=5)

    def test_a_road_keeps_its_name_round_a_corner(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        road(staging, 1, "Oak Lane", (0, 0), (500, 0))
        road(staging, 2, "Oak Lane", (500, 0), (500, 400))  # turns north, keeps its name
        road(staging, 3, "Pine Lane", (500, 0), (1000, 0))  # straight on, another name
        trail_routes.derive_calm_runs(staging)
        got = calm_runs(staging)
        assert got[1] == got[2] == pytest.approx(900, abs=5)
        assert got[3] == pytest.approx(500, abs=5)

    def test_the_turn_is_measured_on_the_ground_not_in_degrees(self, segment_schemas) -> None:
        # Elm Street runs north and Ash Street bends 40 degrees east on the ground: straight on
        # (under STRAIGHT_ON_DEG), so the run goes on. In degrees of lon/lat at this latitude the
        # same bend reads about 47 degrees, which would have broken it (correctness review, nit 4).
        _live, staging = segment_schemas
        road(staging, 1, "Elm Street", (0, 0), (0, 500))
        road(staging, 2, "Ash Street", (0, 500), (321, 883))
        road(staging, 3, "Fir Street", (0, 500), (-500, 500))  # a third road, so the turn decides
        trail_routes.derive_calm_runs(staging)
        got = calm_runs(staging)
        assert got[1] == got[2] == pytest.approx(1000, abs=5)
        assert got[3] == pytest.approx(500, abs=5)

    def test_the_back_bearing_is_on_the_ground_too(self, segment_schemas) -> None:
        # The same bend, with Ash Street drawn the other way so that its row ENDS at the
        # junction: the bearing back along it, 40 degrees east of north on the ground (about
        # 47 in degrees of lon/lat), is the one that decides.
        _live, staging = segment_schemas
        road(staging, 1, "Elm Street", (0, 0), (0, 500))
        road(staging, 2, "Ash Street", (321, 883), (0, 500))
        road(staging, 3, "Fir Street", (0, 500), (-500, 500))
        trail_routes.derive_calm_runs(staging)
        got = calm_runs(staging)
        assert got[1] == got[2] == pytest.approx(1000, abs=5)
        assert got[3] == pytest.approx(500, abs=5)

    def test_an_unnamed_road_has_no_run_and_does_not_join_one(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        road(staging, 1, "Birch Road", (0, 0), (500, 0))
        road(staging, 2, None, (500, 0), (1000, 0))  # a service road: stays 0
        road(staging, 3, "Birch Road", (1000, 0), (1500, 0))
        road(staging, 4, "Birch Road", (1500, 0), (2000, 0), calm=None)  # not a candidate
        trail_routes.derive_calm_runs(staging)
        got = calm_runs(staging)
        assert got[1] == pytest.approx(500, abs=5) and got[3] == pytest.approx(500, abs=5)
        assert got[2] == 0
        assert got[4] is None, "a way that is not a candidate stays null"

    def test_a_road_that_is_hidden_has_no_run(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        calm_piece(staging, 1, "Maple Street", 0, 900)
        with connection.cursor() as cursor:
            cursor.execute(f"UPDATE {staging}.segment SET map_class = 'alley'")
        trail_routes.derive_calm_runs(staging)
        assert calm_runs(staging) == {1: 0}

    def test_connected_paths_are_one_network_whatever_their_names(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        calm_piece(staging, 1, "Alpha Trail", 0, 600, path=True)
        calm_piece(staging, 2, None, 600, 500, path=True)  # unnamed, touching
        calm_piece(staging, 3, "Beta Trail", 1100 + CALM_PATH_GAP_M - 10, 400, path=True)
        calm_piece(staging, 4, "Gamma Trail", 1500 + 2 * CALM_PATH_GAP_M, 300, path=True)
        trail_routes.derive_calm_runs(staging)
        got = calm_runs(staging)
        assert got[1] == got[2] == got[3] and got[1] == pytest.approx(1500, abs=30)
        assert got[4] == pytest.approx(300, abs=20), "an isolated stub is its own"

    def test_a_path_keeps_its_named_run_if_that_is_longer(self, segment_schemas) -> None:
        # trail_run_m chains by name across 400 m, which the network's 30 m does not.
        _live, staging = segment_schemas
        calm_piece(staging, 1, "Delta Trail", 0, 600, path=True, trail_run=2400)
        calm_piece(staging, 2, "Delta Trail", 600 + 300, 600, path=True, trail_run=2400)
        trail_routes.derive_calm_runs(staging)
        got = calm_runs(staging)
        assert got[1] == got[2] == 2400

    def test_roads_and_paths_do_not_chain_together(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        calm_piece(staging, 1, "Rose Lane", 0, 600)
        calm_piece(staging, 2, "Rose Lane", 600, 600, path=True)
        trail_routes.derive_calm_runs(staging)
        got = calm_runs(staging)
        assert got[1] == pytest.approx(600, abs=20) and got[2] == pytest.approx(600, abs=20)

    def test_it_returns_what_it_set_and_a_schema_name_is_validated(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        calm_piece(staging, 1, "Rose Lane", 0, 600)
        calm_piece(staging, 2, None, 0, 600, path=True)
        calm_piece(staging, 3, "Rose Lane", 600, 600, calm=None)
        assert trail_routes.derive_calm_runs(staging) == (1, 1)
        with pytest.raises(ValueError):
            trail_routes.derive_calm_runs("live; DROP SCHEMA public")
        with pytest.raises(ValueError):
            calm_roads.junctions_sql("live; DROP SCHEMA public")

    def test_an_empty_table_sets_nothing(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        assert trail_routes.derive_calm_runs(staging) == (0, 0)


@db
class TestAssertCalmRuns:
    """VALIDATE's check on the ride layer's column (the same idea as `assert_long_trails`)."""

    def summary(self, staging, sentinels=(), path_floor=400, street_floor=3219):
        return trail_routes.calm_run_summary(staging, sentinels, path_floor, street_floor)

    def test_a_good_table_passes(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        calm_piece(staging, 7, "Alpha Trail", 0, 13_500, path=True)
        calm_piece(staging, 8, "Elmer School Road", 0, 3500, lat=LAT + 0.1)
        trail_routes.derive_calm_runs(staging)
        got = self.summary(staging, (7, 8))
        assert (got.path_rows, got.street_rows, got.unset_named) == (1, 1, 0)
        assert_calm_runs(got, (7,), (8,), (1, 1))

    def test_a_sentinel_that_is_missing_or_short_stops_the_build(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        calm_piece(staging, 7, "Alpha Trail", 0, 1000, path=True)
        calm_piece(staging, 8, "Elmer School Road", 0, 3000, lat=LAT + 0.1)
        trail_routes.derive_calm_runs(staging)
        got = self.summary(staging, (7, 8, 9))
        with pytest.raises(ValidationFailed, match="path sentinel way 9 is not in"):
            assert_calm_runs(got, (9,), (), (0, 0))
        with pytest.raises(ValidationFailed, match="path sentinel way 7 came out"):
            assert_calm_runs(got, (7,), (), (0, 0))  # 1 km, not the 8 mi a trail sentinel is
        with pytest.raises(ValidationFailed, match="road sentinel way 8 came out"):
            assert_calm_runs(got, (), (8,), (0, 0))  # 3 km, under the 2 mi (3.2 km) bar

    def test_the_floors_stop_the_build(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        calm_piece(staging, 7, "Alpha Trail", 0, 1000, path=True)
        trail_routes.derive_calm_runs(staging)
        got = self.summary(staging, (), 400, 800)
        assert_calm_runs(got, (), (), (1, 0))
        with pytest.raises(ValidationFailed, match="floors of 2 and 0"):
            assert_calm_runs(got, (), (), (2, 0))
        with pytest.raises(ValidationFailed, match="floors of 1 and 1"):
            assert_calm_runs(got, (), (), (1, 1))

    def test_a_derive_that_did_not_run_stops_the_build(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        calm_piece(staging, 7, "Lakeview Drive", 0, 1000)  # still 0: never derived
        got = self.summary(staging)
        assert got.unset_named == 1
        with pytest.raises(ValidationFailed, match="did not run to the end"):
            assert_calm_runs(got, (), (), (0, 0))


# ---- TRAILS BESIDE A ROAD (OWNER-DECISIONS 403) ----------------------------------------------


@pytest.mark.parametrize(
    ("tags", "said"),
    [
        ({"highway": "footway", "footway": "sidewalk"}, True),
        ({"highway": "path", "path": "sidewalk", "bicycle": "yes"}, True),
        ({"highway": "cycleway", "cycleway": "sidewalk"}, True),
        ({"highway": "cycleway", "is_sidepath": "yes"}, True),
        ({"highway": "cycleway", "is_sidepath:of": "secondary"}, True),
        ({"highway": "cycleway", "is_sidepath:of:name": "Veirs Mill Road"}, True),
        ({"highway": "cycleway", "is_sidepath": "no"}, False),
        ({"highway": "cycleway", "is_sidepath": "no", "footway": "sidewalk"}, False),
        ({"highway": "cycleway"}, None),  # the geometry decides
        ({"highway": "path", "surface": "asphalt"}, None),
    ],
)
def test_what_a_trails_tags_say_about_a_road_beside_it(tags, said) -> None:
    from routemaker import facility

    assert facility.roadside_by_tags(tags) is said


@pytest.mark.parametrize(
    ("tags", "facility_class", "drawn", "start"),
    [
        ({"highway": "cycleway"}, "path", True, None),  # ask the geometry
        ({"highway": "cycleway"}, "protected", True, True),  # already the facility beside a road
        ({"highway": "cycleway", "is_sidepath": "no"}, "protected", True, False),
        ({"highway": "cycleway", "is_sidepath": "yes"}, "path", True, True),
        ({"highway": "cycleway", "is_sidepath": "yes"}, "path", False, False),  # not drawn
        ({"highway": "residential"}, "none", False, False),  # a road is never a roadside trail
    ],
)
def test_what_the_rebuild_writes_before_the_geometry(tags, facility_class, drawn, start) -> None:
    from routemaker import facility

    assert facility.roadside_start(tags, facility_class, drawn_trail=drawn) is start


def trail(schema, way, *points, roadside=None) -> None:
    """A drawn trail with no surface, through `points` (metres, as `road` takes them)."""
    coords = [(-77.0 + x * DEG_PER_METRE, LAT + y * DEG_PER_METRE_LAT) for x, y in points]
    wkt = "LINESTRING(" + ",".join(f"{lon!r} {lat!r}" for lon, lat in coords) + ")"
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {schema}.segment (osm_way_id, ordinal, geometry, stress_tier, "
            "stress_rule, is_trail_class, facility, roadside) VALUES "
            "(%s, 0, ST_GeomFromText(%s, 4326), 1, 'Y', true, 'path', %s)",
            [way, wkt, roadside],
        )


def roadsides(schema) -> dict:
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT osm_way_id, roadside FROM {schema}.segment ORDER BY 1")
        return dict(cursor.fetchall())


@db
class TestRoadside:
    def test_a_trail_along_a_road_is_beside_it_and_one_away_is_not(self, segment_schemas):
        _live, staging = segment_schemas
        road(staging, 1, "Veirs Mill Road", (0, 0), (2000, 0), tier=4, calm=None)
        trail(staging, 2, (0, 12), (1000, 12))  # 12 m off the centreline, all along
        trail(staging, 3, (0, 24), (1000, 24))  # 24 m: still within ROADSIDE_M
        trail(staging, 4, (0, 40), (1000, 40))  # 40 m: a trail of its own
        trail(staging, 5, (0, 12), (500, 12), (500, 400), (1000, 400))  # leaves the road
        trail(staging, 6, (3000, 0), (4000, 0))  # a park trail far from any road
        assert trail_routes.derive_roadside(staging) == 2
        got = roadsides(staging)
        assert (got[2], got[3], got[4], got[5], got[6]) == (True, True, False, False, False)
        assert got[1] is False, "the road itself is not a roadside trail"

    def test_the_tags_answer_stands(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        road(staging, 1, "Veirs Mill Road", (0, 0), (2000, 0), tier=4, calm=None)
        trail(staging, 2, (0, 12), (1000, 12), roadside=False)  # is_sidepath=no
        trail(staging, 3, (3000, 0), (4000, 0), roadside=True)  # footway=sidewalk
        trail_routes.derive_roadside(staging)
        got = roadsides(staging)
        assert (got[2], got[3]) == (False, True)

    def test_only_a_road_counts_as_the_road_beside_it(self, segment_schemas) -> None:
        _live, staging = segment_schemas
        trail(staging, 1, (0, 0), (2000, 0), roadside=False)  # another trail
        road(staging, 2, None, (0, -500), (2000, -500), calm=None, map_class="hidden")
        trail(staging, 3, (0, 12), (1000, 12))
        trail(staging, 4, (0, -488), (1000, -488))  # beside a parking aisle, not a road
        trail_routes.derive_roadside(staging)
        got = roadsides(staging)
        assert (got[3], got[4]) == (False, False)

    def test_a_schema_name_is_validated(self) -> None:
        with pytest.raises(ValueError):
            trail_routes.roadside_sql("live; DROP SCHEMA public")

    def test_the_constants(self) -> None:
        from pipeline import schema

        assert (schema.ROADSIDE_M, schema.ROADSIDE_FRACTION, schema.ROADSIDE_SAMPLE_M) == (
            25.0,
            0.6,
            20.0,
        )
