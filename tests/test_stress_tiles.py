"""GET /tiles/stress/{z}/{x}/{y}.pbf, per the SHARED API CONTRACT.

Against a real live segment table (the `segment_schemas` fixture), because the
tiles are PostGIS's ST_AsMVT and a stand-in would test nothing about them. The
tiles are decoded with `tests/mvt.py` and asserted on what they carry: the
layer, each feature's properties, where its lines fall, and which classes of
segment each zoom level keeps.
"""

from __future__ import annotations

import math
from collections import Counter

import pytest
from django.conf import settings
from django.db import connection
from mvt import decode
from test_ratelimit import in_one_window

from core import ratelimit, stress_tiles
from pipeline.schema import create_segment_schema, drop_segment_schema
from routemaker.classes import SIDEWALK_CLASS_HIGHWAY, TRAIL_CLASS_HIGHWAY, TRAIL_NETWORK_HIGHWAY
from routemaker.stress import classify, trail_rule

db = pytest.mark.django_db(transaction=True)

FAR_AWAY = (-80.0, 40.44)  # Pittsburgh, outside the box


def tile_of(lon: float, lat: float, z: int) -> tuple[int, int, int]:
    n = 2**z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return z, x, y


def _centre_of_z16_tile(lon: float, lat: float) -> tuple[float, float]:
    west, south, east, north = stress_tiles.tile_bounds(*tile_of(lon, lat, 16))
    return (west + east) / 2, (south + north) / 2


# The middle of the z16 tile near the White House. Tiles nest, so every line
# drawn around it (inside about 0.0043 degrees of latitude and 0.0055 of
# longitude) is inside the tile containing it at every zoom from 10 to 16.
CENTRE = _centre_of_z16_tile(-77.0300, 38.8990)


def url(z: int, x: int, y: int) -> str:
    return f"/tiles/stress/{z}/{x}/{y}.pbf"


# (label, tier, rule, trail, unpaved): one of each class the levels treat
# differently. Each is a 170 m east-west line at its own latitude, 33 m apart.
# The trail network's ways are unpaved here and the sidewalk class's paved, so
# the two kinds carry different properties: a level that kept one kind in
# place of the other would not draw the same classes.
CLASSES = [
    ("quiet street", 1, "mixed traffic, 20 mph or below, single lane", False, False),
    ("unpaved street", 1, "mixed traffic, 20 mph or below, single lane", False, True),
    ("unknown surface", 1, "mixed traffic, 20 mph or below, single lane", False, None),
    ("residential", 2, "mixed traffic, 25 mph, single lane", False, False),
    ("collector", 3, "mixed traffic, 30 mph, single lane", False, False),
    ("arterial", 4, "mixed traffic, 35 mph or above", False, False),
    *[(h, 1, trail_rule(h), True, h in TRAIL_NETWORK_HIGHWAY) for h in sorted(TRAIL_CLASS_HIGHWAY)],
]


def props(tier, trail, unpaved) -> tuple:
    return (tier, trail, unpaved)


def insert(schema: str, rows) -> None:
    with connection.cursor() as cursor:
        for i, (_label, tier, rule, trail, unpaved) in enumerate(rows):
            lon, lat = CENTRE[0] - 0.001, CENTRE[1] - 0.0018 + i * 0.0003
            cursor.execute(
                f"INSERT INTO {schema}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                "stress_rule, is_trail_class, is_unpaved) VALUES "
                "(%s, 0, ST_MakeLine(ST_MakePoint(%s, %s), ST_MakePoint(%s, %s)), %s, %s, %s, %s)",
                [1000 + i, lon, lat, lon + 0.002, lat, tier, rule, trail, unpaved],
            )


@pytest.fixture
def live(segment_schemas):
    live, _staging = segment_schemas
    insert(live, CLASSES)
    return live


def classes_in(body: bytes) -> Counter:
    """How many lines the tile draws of each class. Lines, not features: a
    merged tile draws a class as one feature, and a sidewalk and a cycleway
    carry the same properties, so only the count tells them apart."""
    layers = decode(body)
    assert set(layers) == {"stress"}
    drawn = Counter()
    for f in layers["stress"].features:
        key = props(
            f.properties.get("tier"), f.properties.get("trail"), f.properties.get("unpaved")
        )
        drawn[key] += len(f.lines)
    return drawn


def expected(keep) -> Counter:
    return Counter(
        props(tier, trail, unpaved)
        for _label, tier, rule, trail, unpaved in CLASSES
        if keep(tier, rule)
    )


SIDEWALK_RULES = {trail_rule(h) for h in SIDEWALK_CLASS_HIGHWAY}
NETWORK_RULES = {trail_rule(h) for h in TRAIL_NETWORK_HIGHWAY}


class TestClasses:
    def test_the_two_trail_kinds_partition_trail_class(self) -> None:
        assert TRAIL_NETWORK_HIGHWAY | SIDEWALK_CLASS_HIGHWAY == TRAIL_CLASS_HIGHWAY
        assert not TRAIL_NETWORK_HIGHWAY & SIDEWALK_CLASS_HIGHWAY
        assert {"cycleway", "path"} <= TRAIL_NETWORK_HIGHWAY
        assert "footway" in SIDEWALK_CLASS_HIGHWAY

    @pytest.mark.parametrize("highway", sorted(TRAIL_CLASS_HIGHWAY))
    def test_the_classifier_records_the_rule_the_tiles_select_on(self, highway) -> None:
        assert classify({"highway": highway}).rule == trail_rule(highway)


@db
class TestContract:
    def test_a_street_zoom_tile_carries_every_segment_with_its_properties(
        self, client, live
    ) -> None:
        response = client.get(url(*tile_of(*CENTRE, 14)))
        assert response.status_code == 200
        assert response["Content-Type"] == stress_tiles.CONTENT_TYPE
        layer = decode(response.content)["stress"]
        assert len(layer.features) == len(CLASSES)
        assert classes_in(response.content) == expected(lambda tier, rule: True)
        for feature in layer.features:
            assert feature.type == 2  # LINESTRING
            assert set(feature.properties) <= {"tier", "trail", "unpaved"}
            assert isinstance(feature.properties["trail"], bool)

    def test_an_unknown_surface_is_left_out_rather_than_called_paved(self, client, live) -> None:
        features = decode(client.get(url(*tile_of(*CENTRE, 14))).content)["stress"].features
        unknown = [f for f in features if "unpaved" not in f.properties]
        assert len(unknown) == 1
        assert unknown[0].properties == {"tier": 1, "trail": False}

    def test_lines_are_drawn_where_the_segments_are(self, client, live) -> None:
        z, x, y = tile_of(*CENTRE, 14)
        layer = decode(client.get(url(z, x, y)).content)["stress"]
        west, south, east, north = stress_tiles.tile_bounds(z, x, y)
        lon0 = CENTRE[0] - 0.001
        want_x = (lon0 - west) / (east - west) * layer.extent
        want_x_end = (lon0 + 0.002 - west) / (east - west) * layer.extent
        starts = sorted(line[0][0] for f in layer.features for line in f.lines)
        ends = sorted(line[-1][0] for f in layer.features for line in f.lines)
        assert all(abs(s - want_x) <= 2 for s in starts)
        assert all(abs(e - want_x_end) <= 2 for e in ends)

        def mercator(lat):
            return math.asinh(math.tan(math.radians(lat)))

        # Tile y runs north to south. Row 0 is the quiet street, row 5 the arterial.
        for row, tier in ((0, 1), (5, 4)):
            lat = CENTRE[1] - 0.0018 + row * 0.0003
            want_y = (mercator(north) - mercator(lat)) / (mercator(north) - mercator(south))
            (feature,) = [
                f
                for f in layer.features
                if f.properties == {"tier": tier, "trail": False, "unpaved": False}
            ]
            assert abs(feature.lines[0][0][1] - want_y * layer.extent) <= 2

    @pytest.mark.parametrize("z", [stress_tiles.MIN_ZOOM - 1, stress_tiles.MAX_ZOOM + 1, 3])
    def test_outside_the_zooms_served_the_tile_is_empty_not_missing(self, client, live, z) -> None:
        response = client.get(url(*tile_of(*CENTRE, z)))
        assert response.status_code == 200
        assert response.content == b""
        assert "public" in response["Cache-Control"]

    # Just past one side of the box and inside the other three.
    BEYOND = {
        "west": (-78.3, 39.0),
        "east": (-75.7, 39.0),
        "south": (-77.0, 37.85),
        "north": (-77.0, 40.05),
        "far away": FAR_AWAY,
    }

    @pytest.mark.parametrize("side", list(BEYOND))
    @pytest.mark.parametrize("z", [10, 14, 16])
    def test_outside_the_coverage_box_the_tile_is_empty(
        self, client, segment_schemas, side, z
    ) -> None:
        live, _ = segment_schemas
        lon, lat = self.BEYOND[side]
        west, south, east, north = stress_tiles.tile_bounds(*tile_of(lon, lat, z))
        c_west, c_south, c_east, c_north = settings.COVERAGE_BBOX
        beyond = {
            "west": east < c_west,
            "east": west > c_east,
            "south": north < c_south,
            "north": south > c_north,
        }
        if side != "far away":
            assert [k for k, v in beyond.items() if v] == [side]
        # A segment there would be drawn if the box were not consulted.
        with connection.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO {live}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                "stress_rule) VALUES (1, 0, ST_MakeLine(ST_MakePoint(%s, %s), "
                "ST_MakePoint(%s, %s)), 4, 'x')",
                [lon, lat, lon + 0.001, lat],
            )
        response = client.get(url(*tile_of(lon, lat, z)))
        assert response.status_code == 200
        assert response.content == b""

    def test_a_tile_on_the_coverage_edge_is_drawn(self, client, segment_schemas) -> None:
        """The box test is an overlap, not containment: a tile straddling the
        edge still has the segments inside it."""
        live, _ = segment_schemas
        west, south, _east, _north = settings.COVERAGE_BBOX
        lon, lat = west + 0.0005, south + 0.3
        with connection.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO {live}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                "stress_rule) VALUES (1, 0, ST_MakeLine(ST_MakePoint(%s, %s), "
                "ST_MakePoint(%s, %s)), 4, 'x')",
                [lon, lat, lon + 0.002, lat],
            )
        z, x, y = tile_of(lon, lat, 14)
        assert stress_tiles.tile_bounds(z, x, y)[0] < west
        assert classes_in(client.get(url(z, x, y)).content) == {(4, False, None): 1}

    @pytest.mark.parametrize("address", [(14, 2**14, 0), (14, 0, 2**14), (31, 0, 0)])
    def test_a_coordinate_that_is_not_a_tile_is_400(self, client, live, address) -> None:
        response = client.get(url(*address))
        assert response.status_code == 400
        assert response.json()["error"]

    def test_no_sign_in_and_only_get_or_head(self, client, live) -> None:
        path = url(*tile_of(*CENTRE, 14))
        assert client.get(path).status_code == 200
        assert client.head(path).status_code == 200
        assert client.post(path).status_code == 405

    def test_before_any_build_is_promoted_it_is_404(self, client, segment_schemas) -> None:
        """The front end hides the overlay while tiles 404."""
        live, _ = segment_schemas
        drop_segment_schema(live)
        response = client.get(url(*tile_of(*CENTRE, 14)))
        assert response.status_code == 404
        assert response.json()["error"]


@db
class TestLevels:
    """Which segments each level of detail keeps, by class."""

    @pytest.mark.parametrize("z", [14, 15, 16])
    def test_from_z14_every_class(self, client, live, z) -> None:
        assert classes_in(client.get(url(*tile_of(*CENTRE, z))).content) == expected(
            lambda tier, rule: True
        )

    @pytest.mark.parametrize("z", [12, 13])
    def test_at_street_zoom_every_class_but_the_sidewalks(self, client, live, z) -> None:
        got = classes_in(client.get(url(*tile_of(*CENTRE, z))).content)
        assert got == expected(lambda tier, rule: rule not in SIDEWALK_RULES)

    @pytest.mark.parametrize("z", [10, 11])
    def test_zoomed_out_busy_roads_and_the_trail_network(self, client, live, z) -> None:
        got = classes_in(client.get(url(*tile_of(*CENTRE, z))).content)
        assert got == expected(lambda tier, rule: tier >= 3 or rule in NETWORK_RULES)

    @pytest.mark.parametrize("z", [10, 12])
    def test_below_z14_one_feature_per_class(self, client, segment_schemas, z) -> None:
        """What keeps the zoomed-out tiles small: a class's segments are one
        feature, not one each, and they keep that class's properties."""
        live, _ = segment_schemas
        insert(live, [CLASSES[5]] * 4 + [CLASSES[4]] * 3)
        layer = decode(client.get(url(*tile_of(*CENTRE, z))).content)["stress"]
        by_class = {}
        for f in layer.features:
            key = (f.properties["tier"], f.properties["trail"], f.properties["unpaved"])
            by_class.setdefault(key, []).append(len(f.lines))
        assert by_class == {(4, False, False): [4], (3, False, False): [3]}

    def test_each_zoom_has_one_level(self) -> None:
        levels = [stress_tiles.level_for(z) for z in range(stress_tiles.MIN_ZOOM, 17)]
        assert levels[0] is stress_tiles.OVERVIEW
        assert levels[-1] is stress_tiles.FULL
        assert [lv.min_zoom for lv in dict.fromkeys(levels)] == sorted(
            lv.min_zoom for lv in stress_tiles.LEVELS
        )

    @pytest.mark.parametrize("z", [10, 12, 14])
    def test_a_tier_the_tiles_have_not_met_is_carried_as_the_table_holds_it(
        self, client, segment_schemas, z
    ) -> None:
        """Nothing in the tiles enumerates the tiers, so a new one - a
        traffic-free path category, say - reaches the map unchanged, and a
        trail-network way keeps its place zoomed out whatever its tier."""
        live, _ = segment_schemas
        with connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE {live}.segment DROP CONSTRAINT segment_stress_tier_check")
        insert(live, [("traffic-free path", 0, trail_rule("cycleway"), True, False)])
        assert classes_in(client.get(url(*tile_of(*CENTRE, z))).content) == {(0, True, False): 1}

    def test_below_z14_detail_finer_than_the_tile_grid_is_not_drawn(
        self, client, segment_schemas
    ) -> None:
        """A 170 m line with forty vertices wobbling 1.7 m off straight - under
        one tile unit at z12 (2.4 m), nearly three at z14. Its two ends are all
        a zoomed-out tile needs, and all it gets; at z14 it keeps its vertices."""
        live, _ = segment_schemas
        lon0, lat = CENTRE[0] - 0.001, CENTRE[1]
        wkt = (
            "LINESTRING("
            + ", ".join(
                f"{lon0 + 0.002 * i / 40} {lat + (0.000015 if i % 2 else 0)}" for i in range(41)
            )
            + ")"
        )
        with connection.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO {live}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                "stress_rule) VALUES (1, 0, ST_GeomFromText(%s, 4326), 4, 'x')",
                [wkt],
            )

        def points(z):
            (feature,) = decode(client.get(url(*tile_of(*CENTRE, z))).content)["stress"].features
            return sum(len(line) for line in feature.lines)

        assert points(10) == points(12) == 2
        assert points(14) > 10

    @pytest.mark.parametrize("z", [10, 12, 14])
    def test_a_line_just_past_the_edge_is_drawn_in_the_buffer(
        self, client, segment_schemas, z
    ) -> None:
        """So a line along a tile edge is not cut short at it, casing and all,
        at every level."""
        live, _ = segment_schemas
        level = stress_tiles.level_for(z)
        z, x, y = tile_of(*CENTRE, z)
        west, south, east, north = stress_tiles.tile_bounds(z, x, y)
        lon = east + level.buffer / 2 * (east - west) / level.extent
        with connection.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO {live}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                "stress_rule) VALUES (1, 0, ST_MakeLine(ST_MakePoint(%s, %s), "
                "ST_MakePoint(%s, %s)), 4, 'x')",
                [lon, south + 0.3 * (north - south), lon, south + 0.7 * (north - south)],
            )
        layer = decode(client.get(url(z, x, y)).content)["stress"]
        (feature,) = layer.features
        xs = {px for line in feature.lines for px, _py in line}
        assert xs
        assert all(layer.extent < px <= layer.extent + level.buffer for px in xs)


def test_a_rule_that_is_not_plain_text_is_refused_not_pasted() -> None:
    """The level predicates are pasted into DDL and into a query run with
    parameters."""
    from pipeline.schema import _text_list

    for bad in ["it's", "50%", "a{b}", "back\\slash"]:
        with pytest.raises(ValueError):
            _text_list([bad])
    assert _text_list(["b", "a"]) == "'a', 'b'"


@db
class TestOverviewIndex:
    def test_the_rebuild_creates_it(self, segment_schemas) -> None:
        live, _ = segment_schemas
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT indexdef FROM pg_indexes WHERE schemaname = %s "
                "AND indexname = 'segment_overview_geom_idx'",
                [live],
            )
            (definition,) = cursor.fetchone()
        assert "USING gist (geometry)" in definition
        assert "WHERE" in definition

    def test_the_overview_query_can_use_it(self, live) -> None:
        """PostgreSQL uses a partial index only when it proves the query's
        condition implies the index's; the query and the index share one
        predicate so that it can."""
        z, x, y = tile_of(*CENTRE, 10)
        params = {"z": z, "x": x, "y": y, "extent": 2048, "buffer": 16, "margin": 0.01, "unit": 1.0}
        with connection.cursor() as cursor:
            # A handful of rows is a sequential scan otherwise.
            cursor.execute("SET enable_seqscan = off")
            try:
                cursor.execute(f"EXPLAIN {stress_tiles.tile_sql(stress_tiles.OVERVIEW)}", params)
                plan = "\n".join(row[0] for row in cursor.fetchall())
            finally:
                cursor.execute("RESET enable_seqscan")
        assert "segment_overview_geom_idx" in plan

    def test_it_is_built_on_the_predicate_the_tiles_then_use(self, segment_schemas) -> None:
        """Once the schema declares the facility column, the tiles widen the
        overview to keep paths and protected lanes, and the index must be
        built on that wider predicate or the planner cannot use it."""
        from pipeline import schema

        live, _ = segment_schemas
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM information_schema.columns WHERE table_schema = %s "
                "AND table_name = 'segment' AND column_name = %s",
                [live, schema.FACILITY_COLUMN],
            )
            has_column = cursor.fetchone()[0] == 1
            cursor.execute(
                "SELECT indexdef FROM pg_indexes WHERE schemaname = %s "
                "AND indexname = 'segment_overview_geom_idx'",
                [live],
            )
            (definition,) = cursor.fetchone()
        assert has_column == schema.SEGMENT_HAS_FACILITY
        assert (schema.FACILITY_COLUMN in definition) == has_column

    def test_on_a_table_with_the_facility_the_widened_query_can_use_it(self, live) -> None:
        """The predicate the index is built with once the column is declared
        is one the widened overview query is proved to imply."""
        from pipeline import schema

        z, x, y = tile_of(*CENTRE, 10)
        params = {"z": z, "x": x, "y": y, "extent": 2048, "buffer": 16, "margin": 0.01, "unit": 1.0}
        with connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE {live}.segment ADD COLUMN facility text")
            cursor.execute(f"DROP INDEX {live}.segment_overview_geom_idx")
            cursor.execute(
                f"CREATE INDEX segment_overview_geom_idx ON {live}.segment USING gist (geometry) "
                f"WHERE {schema.overview_index_predicate(True)}"
            )
            cursor.execute("SET enable_seqscan = off")
            try:
                sql = stress_tiles.tile_sql(stress_tiles.OVERVIEW, frozenset({"facility"}))
                cursor.execute(f"EXPLAIN {sql}", params)
                plan = "\n".join(row[0] for row in cursor.fetchall())
            finally:
                cursor.execute("RESET enable_seqscan")
        assert "segment_overview_geom_idx" in plan


FACILITY_ROWS = [
    # (label, tier, rule, trail, unpaved, facility)
    ("protected lane", 1, "separated track alongside", False, False, "protected"),
    ("painted lane", 2, "bike lane, narrow at 25 mph or below", False, False, "lane"),
    ("sharrow street", 2, "mixed traffic, 25 mph, single lane", False, False, "none"),
    ("off-road path on a footway", 1, trail_rule("footway"), True, False, "path"),
    ("not classified", 1, "mixed traffic, 20 mph or below, single lane", False, False, None),
]


@db
class TestFacility:
    """The bike-facility class, carried from a live table that has the column."""

    @pytest.fixture
    def with_facility(self, segment_schemas):
        live, _ = segment_schemas
        with connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE {live}.segment ADD COLUMN facility text")
            for i, (_label, tier, rule, trail, unpaved, facility) in enumerate(FACILITY_ROWS):
                lon, lat = CENTRE[0] - 0.001, CENTRE[1] - 0.0018 + i * 0.0003
                cursor.execute(
                    f"INSERT INTO {live}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                    "stress_rule, is_trail_class, is_unpaved, facility) VALUES (%s, 0, "
                    "ST_MakeLine(ST_MakePoint(%s, %s), ST_MakePoint(%s, %s)), %s, %s, %s, %s, %s)",
                    [2000 + i, lon, lat, lon + 0.002, lat, tier, rule, trail, unpaved, facility],
                )
        return live

    @staticmethod
    def facilities(client, z) -> Counter:
        features = decode(client.get(url(*tile_of(*CENTRE, z))).content)["stress"].features
        return Counter(
            f.properties.get("facility", "(absent)") for f in features for _line in f.lines
        )

    def test_without_the_column_no_feature_carries_it(self, client, live) -> None:
        for z in (10, 12, 14):
            features = decode(client.get(url(*tile_of(*CENTRE, z))).content)["stress"].features
            assert features
            assert not any("facility" in f.properties for f in features)

    def test_the_column_added_in_place_changes_the_etag(self, client, live) -> None:
        """Added by hand to a live table, the column changes the tiles but not
        the table's oid; a client revalidating must not be told its old tile,
        without the facilities, is current."""
        path = url(*tile_of(*CENTRE, 14))
        before = client.get(path)["ETag"]
        with connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE {live}.segment ADD COLUMN facility text")
        after = client.get(path, HTTP_IF_NONE_MATCH=before)
        assert after.status_code == 200
        assert after["ETag"] != before

    def test_from_z14_every_segment_carries_its_class(self, client, with_facility) -> None:
        assert self.facilities(client, 14) == Counter(
            {"protected": 1, "lane": 1, "none": 1, "path": 1, "(absent)": 1}
        )

    @pytest.mark.parametrize("z", [10, 11])
    def test_zoomed_out_paths_and_protected_lanes_are_kept(self, client, with_facility, z):
        """Neither would be drawn by tier or kind of way at this zoom: an LTS 1
        street and a footway."""
        assert self.facilities(client, z) == Counter({"protected": 1, "path": 1})

    @pytest.mark.parametrize("z", [12, 13])
    def test_at_street_zoom_a_path_on_a_footway_is_kept(self, client, with_facility, z):
        assert self.facilities(client, z) == Counter(
            {"protected": 1, "lane": 1, "none": 1, "path": 1, "(absent)": 1}
        )


@db
class TestCaching:
    def test_cacheable_with_an_etag(self, client, live) -> None:
        response = client.get(url(*tile_of(*CENTRE, 14)))
        assert "public" in response["Cache-Control"]
        assert "max-age=" in response["Cache-Control"]
        # Weak: two draws of one tile are the same features, not always the
        # same bytes.
        assert response["ETag"].startswith('W/"')

    @pytest.mark.parametrize("form", ["{tag}", "{bare}", '"other", {tag}', '{bare}, "other"', "*"])
    def test_a_client_holding_the_tile_gets_304_and_no_body(self, client, live, form) -> None:
        """The weak comparison: the tag as sent, or as an edge that rewrote it
        without the W/, in a list or alone."""
        path = url(*tile_of(*CENTRE, 14))
        etag = client.get(path)["ETag"]
        header = form.format(tag=etag, bare=etag.removeprefix("W/"))
        again = client.get(path, HTTP_IF_NONE_MATCH=header)
        assert again.status_code == 304
        assert again.content == b""
        assert again["ETag"] == etag

    def test_a_stale_etag_gets_the_tile(self, client, live) -> None:
        path = url(*tile_of(*CENTRE, 14))
        again = client.get(path, HTTP_IF_NONE_MATCH='"stress-1-v0"')
        assert again.status_code == 200
        assert again.content

    def test_a_newly_promoted_table_changes_the_etag(self, client, live) -> None:
        path = url(*tile_of(*CENTRE, 14))
        before = client.get(path)["ETag"]
        drop_segment_schema(live)
        create_segment_schema(live)
        insert(live, CLASSES)
        after = client.get(path, HTTP_IF_NONE_MATCH=before)
        assert after.status_code == 200
        assert after["ETag"] != before

    def test_every_zoom_carries_the_same_etag_for_the_same_table(self, client, live) -> None:
        tags = {client.get(url(*tile_of(*CENTRE, z)))["ETag"] for z in (10, 12, 14)}
        assert len(tags) == 1


@db
class TestRateLimit:
    def test_past_the_tile_budget_is_429_and_routing_is_untouched(self, client, live) -> None:
        limit = ratelimit.TILES
        # Tiles outside the box are the cheapest the endpoint answers, and
        # they are counted all the same.
        path = url(*tile_of(*FAR_AWAY, 14))

        def attempt(n):
            headers = {"HTTP_X_FORWARDED_FOR": f"198.51.100.{40 + 100 * n}"}
            statuses = {client.get(path, **headers).status_code for _ in range(limit.requests)}
            return statuses, client.get(path, **headers), headers

        statuses, refused, headers = in_one_window(limit.window_s, attempt)
        assert statuses == {200}
        assert refused.status_code == 429
        assert 1 <= int(refused["Retry-After"]) <= limit.window_s
        client_key = ratelimit.client_key(headers["HTTP_X_FORWARDED_FOR"])
        assert ratelimit.hit(ratelimit.ROUTING, client_key).allowed
        other = client.get(path, HTTP_X_FORWARDED_FOR="198.51.100.41")
        assert other.status_code == 200

    def test_the_tile_budget_is_its_own_and_larger_than_routings(self) -> None:
        assert ratelimit.TILES.scope != ratelimit.ROUTING.scope
        assert ratelimit.TILES.requests / ratelimit.TILES.window_s > (
            ratelimit.ROUTING.requests / ratelimit.ROUTING.window_s
        )
