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
from pipeline.schema import (
    busy_predicate,
    create_segment_schema,
    drop_segment_schema,
    trails_predicate,
)
from routemaker.classes import (
    SIDEWALK_CLASS_HIGHWAY,
    TRAIL_CLASS_HIGHWAY,
    TRAIL_NETWORK_HIGHWAY,
    TrailKind,
    trail_kind,
)
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


OPEN, SIDEPATH, CLOSED = TrailKind.OPEN, TrailKind.SIDEPATH, TrailKind.CLOSED

# (label, tier, rule, trail, unpaved): one of each class the levels treat
# differently. Each is a 170 m east-west line at its own latitude, 28 m apart.
# The plain trail texts are a table from before the rebuild recorded what a
# bicycle may do on a trail (`trail_kind`); the kinds follow. Unpaved differs
# between kinds the levels treat differently, so a level that kept one in
# place of the other would not draw the same classes.
CLASSES = [
    ("quiet street", 1, "mixed traffic, 20 mph or below, single lane", False, False),
    ("unpaved street", 1, "mixed traffic, 20 mph or below, single lane", False, True),
    ("unknown surface", 1, "mixed traffic, 20 mph or below, single lane", False, None),
    ("residential", 2, "mixed traffic, 25 mph, single lane", False, False),
    ("collector", 3, "mixed traffic, 30 mph, single lane", False, False),
    ("arterial", 4, "mixed traffic, 35 mph or above", False, False),
    *[(h, 1, trail_rule(h), True, h in TRAIL_NETWORK_HIGHWAY) for h in sorted(TRAIL_CLASS_HIGHWAY)],
    ("open path", 1, trail_rule("path", OPEN), True, True),
    ("footway open to bicycles", 1, trail_rule("footway", OPEN), True, True),
    ("sidepath", 1, trail_rule("footway", SIDEPATH), True, False),
    ("hiking trail, no bicycles", 1, trail_rule("path", CLOSED), True, False),
]


def props(tier, trail, unpaved) -> tuple:
    return (tier, trail, unpaved)


def insert(schema: str, rows) -> None:
    """The rows, each with the facility the rebuild writes for its rule (the
    stand-in's, FACILITY_OF, which a test holds to routemaker.facility)."""
    with connection.cursor() as cursor:
        for i, (_label, tier, rule, trail, unpaved) in enumerate(rows):
            lon, lat = CENTRE[0] - 0.001, CENTRE[1] - 0.0018 + i * 0.00025
            cursor.execute(
                f"INSERT INTO {schema}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                "stress_rule, is_trail_class, is_unpaved, facility) VALUES "
                "(%s, 0, ST_MakeLine(ST_MakePoint(%s, %s), ST_MakePoint(%s, %s)), %s, %s, %s, %s, "
                "%s)",
                [
                    1000 + i, lon, lat, lon + 0.002, lat, tier, rule, trail, unpaved,
                    FACILITY_OF.get(rule, "none"),
                ],
            )  # fmt: skip


@pytest.fixture
def segment_schemas(segment_schemas):
    """The schemas as the other fixtures see them, with every way on a long route.

    The zoomed-out tiles keep only the long trails (OWNER-DECISIONS 375), by
    columns the rows of the tests below do not set; a way on a long route
    (`trail_route` 3) is kept at every zoom, so these tests are about the
    classes and not the rule. TestLongTrails sets the columns itself.
    """
    for name in segment_schemas[:2]:
        with connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE {name}.segment ALTER COLUMN trail_route SET DEFAULT 3")
    return segment_schemas


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


# Written out rather than read from pipeline.schema, so the tests hold the
# schema's sets to the rule rather than to themselves.
SIDEWALK_RULES = {trail_rule(h) for h in ("footway", "pedestrian", "steps")}
BIKE_TRAILS = ("bridleway", "cycleway", "footway", "path", "pedestrian")
FACILITY_OF = {
    **{trail_rule(h, OPEN): "path" for h in BIKE_TRAILS},
    trail_rule("cycleway"): "path",
    **{trail_rule(h, SIDEPATH): "protected" for h in BIKE_TRAILS},
}
# What the zoomed-out tiles draw from a table without the facility column: the
# rules the stand-in calls a path (owner, 2026-09-28: "Zoomed out just show the
# trails.").
PATH_RULES = {rule for rule, facility in FACILITY_OF.items() if facility == "path"}
# And the roadside trails (owner, 2026-09-29: "Show roadside trails
# (Recommended)"): the protected ways that are trails of their own - every
# protected rule the stand-in has is a sidepath, a trail-class way.
TRAILS_RULES = PATH_RULES | {r for r, facility in FACILITY_OF.items() if facility == "protected"}


class TestClasses:
    def test_the_two_trail_kinds_partition_trail_class(self) -> None:
        assert TRAIL_NETWORK_HIGHWAY | SIDEWALK_CLASS_HIGHWAY == TRAIL_CLASS_HIGHWAY
        assert not TRAIL_NETWORK_HIGHWAY & SIDEWALK_CLASS_HIGHWAY
        assert {"cycleway", "path", "bridleway"} <= TRAIL_NETWORK_HIGHWAY
        assert "footway" in SIDEWALK_CLASS_HIGHWAY

    @pytest.mark.parametrize(
        ("tags", "kind"),
        [
            ({"highway": "cycleway"}, OPEN),
            ({"highway": "path"}, OPEN),
            ({"highway": "path", "bicycle": "no"}, CLOSED),
            ({"highway": "path", "bicycle": "dismount"}, CLOSED),
            ({"highway": "path", "bicycle": "private"}, CLOSED),
            ({"highway": "path", "access": "private"}, CLOSED),
            ({"highway": "path", "access": "private", "bicycle": "yes"}, OPEN),
            ({"highway": "bridleway"}, CLOSED),
            ({"highway": "bridleway", "bicycle": "permissive"}, OPEN),
            ({"highway": "footway"}, None),
            ({"highway": "footway", "bicycle": "no"}, None),
            ({"highway": "footway", "bicycle": "yes"}, OPEN),
            ({"highway": "footway", "bicycle": "designated"}, OPEN),
            ({"highway": "footway", "footway": "sidewalk", "bicycle": "designated"}, SIDEPATH),
            ({"highway": "footway", "footway": "sidewalk", "bicycle": "yes"}, None),
            ({"highway": "path", "is_sidepath": "yes"}, SIDEPATH),
            ({"highway": "cycleway", "separation": "kerb"}, SIDEPATH),
            ({"highway": "cycleway", "separation": "solid_line"}, OPEN),
            ({"highway": "pedestrian", "bicycle": "yes"}, OPEN),
            ({"highway": "steps", "bicycle": "yes"}, None),
            # A crossing, or its refuge, is not a path away from the road -
            # unless it is signed for bicycles or is a cycleway, when it
            # carries its trail across (routemaker.facility, the merged rule).
            ({"highway": "footway", "footway": "crossing", "bicycle": "yes"}, None),
            ({"highway": "footway", "footway": "crossing", "bicycle": "designated"}, OPEN),
            ({"highway": "footway", "footway": "traffic_island", "bicycle": "yes"}, None),
            ({"highway": "footway", "footway": "traffic_island", "bicycle": "designated"}, None),
            ({"highway": "path", "footway": "crossing"}, TrailKind.NO_FACILITY),
            ({"highway": "path", "path": "traffic_island"}, TrailKind.NO_FACILITY),
            ({"highway": "cycleway", "footway": "crossing"}, OPEN),
            ({"highway": "cycleway", "cycleway": "traffic_island"}, TrailKind.NO_FACILITY),
            ({"highway": "path", "footway": "crossing", "bicycle": "no"}, CLOSED),
            # A trail's own crossing of a road stays the trail's.
            ({"highway": "cycleway", "cycleway": "crossing"}, OPEN),
            # A sidewalk is one whichever key maps it (review cm2).
            ({"highway": "path", "path": "sidewalk", "bicycle": "designated"}, SIDEPATH),
            ({"highway": "cycleway", "cycleway": "sidewalk", "bicycle": "designated"}, SIDEPATH),
            ({"highway": "cycleway", "cycleway": "sidewalk"}, TrailKind.NO_FACILITY),
            ({"highway": "path", "path": "sidewalk", "bicycle": "yes"}, TrailKind.NO_FACILITY),
            # A separation is read one value at a time (review cm2).
            ({"highway": "cycleway", "separation:left": "kerb;flex_post"}, SIDEPATH),
            ({"highway": "cycleway", "separation": "solid_line;kerb"}, SIDEPATH),
            ({"highway": "cycleway", "separation": "solid_line;buffer"}, OPEN),
        ],
    )
    def test_what_a_bicycle_may_do_on_a_trail_is_recorded(self, tags, kind) -> None:
        """The routing lane's rule for trails (routemaker.facility on
        wip/dials), which the stopgap facility has to match."""
        assert trail_kind(tags) == kind
        result = classify(tags)
        assert result.tier == 1
        assert result.rule == trail_rule(tags["highway"], kind)

    @pytest.mark.parametrize(
        "tags",
        [
            {"highway": "path", "bicycle": "no", "name": "Appalachian Trail"},
            {"highway": "footway", "footway": "crossing", "bicycle": "yes"},
            {"highway": "path", "footway": "crossing"},
            {"highway": "cycleway", "cycleway": "sidewalk"},
        ],
    )
    def test_a_barred_trail_a_crossing_or_a_sidewalk_is_neither_network_nor_path(
        self, tags
    ) -> None:
        """Whatever the kind, the recorded rule of these is not one the zoomed-out
        map keeps nor one the stand-in facility calls a path - including the
        plain text a table from before the kinds holds for a cycleway or path."""
        rule = classify(tags).rule
        assert rule not in PATH_RULES
        assert rule not in FACILITY_OF

    @pytest.mark.parametrize(
        "tags",
        [
            {"highway": "cycleway"},
            {"highway": "path"},
            {"highway": "path", "bicycle": "no"},
            {"highway": "footway"},
            {"highway": "footway", "bicycle": "yes"},
            {"highway": "footway", "footway": "sidewalk", "bicycle": "designated"},
            {"highway": "footway", "footway": "sidewalk", "bicycle": "yes"},
            {"highway": "path", "is_sidepath": "yes"},
            {"highway": "cycleway", "separation": "kerb"},
            {"highway": "footway", "footway": "crossing", "bicycle": "designated"},
            {"highway": "footway", "footway": "crossing", "bicycle": "yes"},
            {"highway": "cycleway", "footway": "crossing"},
            {"highway": "path", "footway": "crossing"},
            {"highway": "cycleway", "cycleway": "traffic_island"},
            {"highway": "footway", "footway": "traffic_island", "bicycle": "designated"},
            {"highway": "bridleway", "bicycle": "permissive"},
            {"highway": "pedestrian", "bicycle": "yes"},
            {"highway": "steps", "bicycle": "yes"},
        ],
    )
    def test_the_overlay_draws_the_facility_routing_reads(self, tags) -> None:
        """The facility a table without the column is drawn with (derived from
        the recorded rule) is the one the rebuild writes to the column from
        `routemaker.facility` - the rule routing reads - for every trail-class
        way a path or a protected lane can be (PUBLIC-TILES merge)."""
        from routemaker import facility

        derived = FACILITY_OF.get(classify(tags).rule, "none")
        assert derived == facility.facility(tags).value

    def test_the_schema_holds_the_trail_rules_the_tests_do(self) -> None:
        from pipeline import schema

        assert schema.PATH_RULES == PATH_RULES
        for rule in SIDEWALK_RULES:
            assert rule not in schema.PATH_RULES

    def test_the_trail_network_keeps_its_bridleways(self) -> None:
        assert "bridleway" in TRAIL_NETWORK_HIGHWAY


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
            assert set(feature.properties) <= {
                "tier", "trail", "unpaved", "facility", "car_free", "map_class", "separate_bikeway"
            }  # fmt: skip
            assert isinstance(feature.properties["trail"], bool)

    def test_an_unknown_surface_is_left_out_rather_than_called_paved(self, client, live) -> None:
        features = decode(client.get(url(*tile_of(*CENTRE, 14))).content)["stress"].features
        unknown = [f for f in features if "unpaved" not in f.properties]
        assert len(unknown) == 1
        assert unknown[0].properties == {"tier": 1, "trail": False, "facility": "none"}

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
            lat = CENTRE[1] - 0.0018 + row * 0.00025
            want_y = (mercator(north) - mercator(lat)) / (mercator(north) - mercator(south))
            (feature,) = [
                f
                for f in layer.features
                if f.properties
                == {"tier": tier, "trail": False, "unpaved": False, "facility": "none"}
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
    def test_at_busy_road_zoom_the_trails_and_the_roads_at_lts_3_and_above(self, client, live, z):
        """The owner, 2026-09-29: "12 and 13, show LTS 3+" (OWNER-DECISIONS 73)."""
        got = classes_in(client.get(url(*tile_of(*CENTRE, z))).content)
        assert got == expected(lambda tier, rule: rule in TRAILS_RULES or tier >= 3)
        assert expected(lambda tier, rule: tier >= 3) and not got[(1, False, False)]

    @pytest.mark.parametrize("z", [10, 11])
    def test_zoomed_out_only_the_paths_and_trails(self, client, live, z) -> None:
        """The owner, 2026-09-28: "Zoomed out just show the trails." - no
        road, however busy, and no trail a bicycle may not ride; and
        2026-09-29, "Show roadside trails (Recommended)" - the sidepath is
        kept."""
        got = classes_in(client.get(url(*tile_of(*CENTRE, z))).content)
        assert got == expected(lambda tier, rule: rule in TRAILS_RULES)
        assert expected(lambda tier, rule: rule in TRAILS_RULES and rule not in PATH_RULES)
        assert got

    @pytest.mark.parametrize("level", ["TRAILS", "TRAILS_NEAR"])
    def test_the_trails_levels_draw_at_a_z12_tiles_detail(self, level) -> None:
        """Round-1 mutant P13: 2048 units a side at z12 is a unit of 4.8 m, which
        merges the two carriageways of a trail beside a road into one line."""
        trails = getattr(stress_tiles, level)
        assert (trails.extent, trails.buffer) == (4096, 32)
        assert trails.merged
        assert trails.predicate is trails_predicate

    def test_the_roads_come_in_at_their_named_zooms(self) -> None:
        """ "Zoom less than 12, show just bike paths and the metro/MARC. 12 and
        13, show LTS 3+, 14+ show show the quiet streets." (OWNER-DECISIONS 73)"""
        assert (stress_tiles.BUSY_ROADS_MIN_ZOOM, stress_tiles.QUIET_STREETS_MIN_ZOOM) == (12, 14)
        assert stress_tiles.level_for(10) is stress_tiles.TRAILS
        assert stress_tiles.level_for(11) is stress_tiles.TRAILS_NEAR
        assert stress_tiles.level_for(12) is stress_tiles.level_for(13) is stress_tiles.BUSY
        assert stress_tiles.level_for(14) is stress_tiles.FULL
        assert stress_tiles.BUSY.predicate is busy_predicate

    @pytest.mark.parametrize(
        ("z", "rows", "want"),
        [
            (
                10,
                [("paved path", 1, trail_rule("cycleway", OPEN), True, False)] * 4
                + [("open path", 1, trail_rule("path", OPEN), True, True)] * 3,
                {(1, True, False): [4], (1, True, True): [3]},
            ),
            (
                13,
                [CLASSES[5]] * 4 + [CLASSES[4]] * 3,
                {(4, False, False): [4], (3, False, False): [3]},
            ),
        ],
    )
    def test_below_z14_one_feature_per_class(self, client, segment_schemas, z, rows, want):
        """What keeps the zoomed-out tiles small: a class's segments are one
        feature, not one each, and they keep that class's properties."""
        live, _ = segment_schemas
        insert(live, rows)
        layer = decode(client.get(url(*tile_of(*CENTRE, z))).content)["stress"]
        by_class = {}
        for f in layer.features:
            key = (f.properties["tier"], f.properties["trail"], f.properties["unpaved"])
            by_class.setdefault(key, []).append(len(f.lines))
        assert by_class == want

    def test_each_zoom_has_one_level(self) -> None:
        levels = [stress_tiles.level_for(z) for z in range(stress_tiles.MIN_ZOOM, 17)]
        assert levels[0] is stress_tiles.TRAILS
        assert levels[-1] is stress_tiles.FULL
        assert [lv.min_zoom for lv in dict.fromkeys(levels)] == sorted(
            lv.min_zoom for lv in stress_tiles.LEVELS
        )

    def test_the_legend_names_the_zooms_the_levels_start_at(self) -> None:
        """The front end's legend says what is drawn at which zoom, from
        STRESS_ZOOMS in mapStyle.ts, and its source asks for nothing past the
        deepest zoom drawn ahead; those have to be these."""
        import re
        from pathlib import Path

        from core import tile_cache

        source = (
            Path(__file__).resolve().parents[1] / "frontend" / "src" / "lib" / "mapStyle.ts"
        ).read_text()
        block = re.search(r"STRESS_ZOOMS\s*=\s*\{([^}]*)\}", source)
        assert block, "mapStyle.ts no longer declares STRESS_ZOOMS"
        zooms = {k: int(v) for k, v in re.findall(r"(\w+):\s*(\d+)", block.group(1))}
        assert zooms == {
            "min": stress_tiles.MIN_ZOOM,
            "busy": stress_tiles.BUSY_ROADS_MIN_ZOOM,
            "quiet": stress_tiles.QUIET_STREETS_MIN_ZOOM,
            "max": tile_cache.PREDRAW_MAX_ZOOM,
        }

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
                "stress_rule, facility) VALUES (1, 0, ST_GeomFromText(%s, 4326), 4, 'x', 'path')",
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
                "stress_rule, facility) VALUES (1, 0, ST_MakeLine(ST_MakePoint(%s, %s), "
                "ST_MakePoint(%s, %s)), 4, 'x', 'path')",
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

    def test_the_zoomed_out_query_can_use_it(self, live) -> None:
        """PostgreSQL uses a partial index only when it proves the query's
        condition implies the index's; the query and the index share one
        predicate so that it can."""
        assert "segment_overview_geom_idx" in trails_plan(frozenset({"facility"}))

    def test_it_is_built_on_the_predicate_the_tiles_then_use(self, segment_schemas) -> None:
        """Once the schema declares the facility column, the zoomed-out tiles
        select the paths by it, and the index must be built on that predicate
        or the planner cannot use it."""
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

    def test_on_a_table_without_the_facility_its_own_query_can_use_it(self, live) -> None:
        """A live table promoted before the column: the index built on its
        own predicate (the deploy's hand-built one, docs/OPERATIONS.md) is one
        the query for such a table is proved to imply."""
        drop_facility(live)
        assert "segment_overview_geom_idx" in trails_plan(frozenset())


def trails_plan(optional: frozenset[str]) -> str:
    z, x, y = tile_of(*CENTRE, 10)
    params = {"z": z, "x": x, "y": y, "extent": 4096, "buffer": 32, "margin": 0.01, "unit": 1.0}
    with connection.cursor() as cursor:
        # A handful of rows is a sequential scan otherwise.
        cursor.execute("SET enable_seqscan = off")
        try:
            cursor.execute(
                f"EXPLAIN {stress_tiles.tile_sql(stress_tiles.TRAILS, optional)}", params
            )
            return "\n".join(row[0] for row in cursor.fetchall())
        finally:
            cursor.execute("RESET enable_seqscan")


def drop_facility(schema_name: str) -> None:
    """A live table from before the facility column: the stand-in the tiles
    derive, and the column added in place, are tested on one. Dropping the
    column drops the overview index built on it; the one from before is put
    back."""
    from pipeline import schema

    with connection.cursor() as cursor:
        cursor.execute(f"ALTER TABLE {schema_name}.segment DROP COLUMN {schema.FACILITY_COLUMN}")
        cursor.execute(f"DROP INDEX IF EXISTS {schema_name}.segment_overview_geom_idx")
        cursor.execute(
            f"CREATE INDEX segment_overview_geom_idx ON {schema_name}.segment "
            f"USING gist (geometry) WHERE {schema.overview_index_predicate(False)}"
        )


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
            # The schema's column is NOT NULL; a table whose column was added
            # by hand may hold a null, which the tiles leave out.
            cursor.execute(f"ALTER TABLE {live}.segment ALTER COLUMN facility DROP NOT NULL")
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

    @pytest.mark.parametrize("z", [10, 13, 14])
    def test_without_the_column_the_facility_is_derived_by_the_routing_lanes_rule(
        self, client, live, z
    ) -> None:
        """The stand-in until the routing lane's column: a trail a bicycle may
        ride is a path, a sidepath protected, and nothing else - a hiking trail
        barred to bicycles, a street, a sidewalk - carries a facility."""
        drop_facility(live)
        features = decode(client.get(url(*tile_of(*CENTRE, z))).content)["stress"].features
        drawn = Counter()
        for f in features:
            drawn[f.properties.get("facility", "(absent)")] += len(f.lines)
        level = stress_tiles.level_for(z)
        kept = [
            rule
            for _l, tier, rule, _t, _u in CLASSES
            if level is stress_tiles.FULL
            or (level is stress_tiles.BUSY and (rule in TRAILS_RULES or tier >= 3))
            or (level is stress_tiles.TRAILS and rule in TRAILS_RULES)
        ]
        want = Counter(FACILITY_OF.get(rule, "(absent)") for rule in kept)
        assert drawn == want
        assert drawn["path"] >= 3
        # The sidepath, a roadside trail, is kept at every level.
        assert drawn["protected"] == 1

    def test_the_column_added_in_place_changes_the_etag(self, client, live) -> None:
        """Added by hand to a live table, the column changes the tiles but not
        the table's oid; a client revalidating must not be told its old tile,
        without the facilities, is current."""
        drop_facility(live)
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

    @pytest.mark.parametrize("z", [10, 11, 12, 13])
    def test_zoomed_out_only_the_paths_are_kept(self, client, with_facility, z):
        """The path on a footway is kept by its facility, whatever its kind of
        way; the protected lane tagged on its street is not (owner, 2026-09-28:
        "Zoomed out just show the trails.")."""
        assert self.facilities(client, z) == Counter({"path": 1})

    @pytest.mark.parametrize("z", [10, 11, 12, 13])
    def test_zoomed_out_a_roadside_trail_is_kept_and_a_track_on_the_road_is_not(
        self, client, with_facility, z
    ):
        """The owner, 2026-09-29: "Show roadside trails (Recommended)". A
        protected way that is a way of its own - a cycleway beside a road, a
        sidewalk designated for bicycles - is a trail; the protected lane
        tagged on a quiet road way is not, and waits for z14 with its street."""
        with connection.cursor() as cursor:
            lon, lat = CENTRE[0] - 0.001, CENTRE[1] + 0.0015
            cursor.execute(
                f"INSERT INTO {with_facility}.segment (osm_way_id, ordinal, geometry, "
                "stress_tier, stress_rule, is_trail_class, is_unpaved, facility) VALUES "
                "(3000, 0, ST_MakeLine(ST_MakePoint(%s, %s), ST_MakePoint(%s, %s)), 1, %s, "
                "true, false, 'protected')",
                [lon, lat, lon + 0.002, lat, trail_rule("cycleway")],
            )
        assert self.facilities(client, z) == Counter({"path": 1, "protected": 1})
        assert self.facilities(client, 14)["protected"] == 2

    def test_the_trails_predicate_names_the_roadside_trails(self) -> None:
        from pipeline import schema

        with_column = schema.trails_predicate(True)
        assert with_column == ("(facility = 'path' OR (facility = 'protected' AND is_trail_class))")
        without = schema.trails_predicate(False)
        for rule in TRAILS_RULES:
            assert f"'{rule}'" in without
        for rule in SIDEWALK_RULES:
            assert f"'{rule}'" not in without

    @pytest.mark.parametrize("z", [14])
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


def _line(live: str, start: tuple[float, float], end: tuple[float, float], tier: int = 4) -> None:
    """A line every level draws: a path, which the zoomed-out one keeps too."""
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {live}.segment (osm_way_id, ordinal, geometry, stress_tier, "
            "stress_rule, facility) VALUES (1, 0, ST_MakeLine(ST_MakePoint(%s, %s), "
            "ST_MakePoint(%s, %s)), %s, 'x', 'path')",
            [*start, *end, tier],
        )


@db
class TestCoverageClip:
    """Revision round 2 (correctness review SF1): a tile straddling the edge of
    the coverage box drew every segment in its envelope, so roads beyond the
    edge were coloured in the map's grey area."""

    EDGE_LAT = 39.0

    def east_edge_tile(self, z: int):
        return tile_of(settings.COVERAGE_BBOX[2] - 1e-6, self.EDGE_LAT, z)

    @pytest.mark.parametrize("z", [10, 12, 14])
    def test_a_line_across_the_edge_is_drawn_only_inside_it(self, client, segment_schemas, z):
        live, _ = segment_schemas
        east = settings.COVERAGE_BBOX[2]
        _line(live, (east - 0.004, self.EDGE_LAT), (east + 0.004, self.EDGE_LAT))
        z, x, y = self.east_edge_tile(z)
        layer = decode(client.get(url(z, x, y)).content)["stress"]
        west, _s, tile_east, _n = stress_tiles.tile_bounds(z, x, y)
        edge_x = (east - west) / (tile_east - west) * layer.extent
        xs = [px for f in layer.features for line in f.lines for px, _py in line]
        assert xs, "the part inside the box is drawn"
        assert max(xs) <= edge_x + 1
        assert min(xs) < edge_x - 1

    @pytest.mark.parametrize("z", [10, 12, 14])
    def test_a_line_wholly_beyond_the_edge_is_not_drawn(self, client, segment_schemas, z):
        live, _ = segment_schemas
        east = settings.COVERAGE_BBOX[2]
        # Inside the tile (or its buffer), outside the box.
        _line(live, (east + 0.0002, self.EDGE_LAT), (east + 0.0006, self.EDGE_LAT))
        response = client.get(url(*self.east_edge_tile(z)))
        assert response.status_code == 200
        layer = decode(response.content).get("stress")
        assert layer is None or not layer.features

    def test_a_tile_inside_the_box_is_not_clipped(self) -> None:
        for z in (10, 12, 14):
            level = stress_tiles.level_for(z)
            margin = level.buffer / level.extent
            assert not stress_tiles.straddles_coverage(*tile_of(*CENTRE, z), margin)
            assert stress_tiles.straddles_coverage(*self.east_edge_tile(z), margin)

    def test_an_edge_inside_the_buffer_alone_still_clips(self, client, segment_schemas) -> None:
        """A tile wholly inside the box whose buffer reaches past its edge: a
        line in that part of the buffer is past the edge, and not drawn. (No
        tile of the real box falls so; a box moved to make one does.)"""
        from django.test import override_settings

        live, _ = segment_schemas
        z, x, y = tile_of(*CENTRE, 14)
        level = stress_tiles.level_for(z)
        west, south, east, north = stress_tiles.tile_bounds(z, x, y)
        unit = (east - west) / level.extent
        edge = east + unit * level.buffer / 4
        _line(live, (edge + unit * 2, south + 0.3 * (north - south)),
              (edge + unit * 2, south + 0.7 * (north - south)))  # fmt: skip
        box = (
            settings.COVERAGE_BBOX[0],
            settings.COVERAGE_BBOX[1],
            edge,
            settings.COVERAGE_BBOX[3],
        )
        with override_settings(COVERAGE_BBOX=box):
            layer = decode(client.get(url(z, x, y)).content).get("stress")
        assert layer is None or not layer.features

    @pytest.mark.parametrize(
        ("lon", "lat"), [(-78.0, 39.0), (-76.02, 39.0), (-77.0, 38.2), (-77.0, 39.72)]
    )
    def test_every_edge_of_the_box_clips(self, lon, lat) -> None:
        level = stress_tiles.level_for(12)
        assert stress_tiles.straddles_coverage(*tile_of(lon, lat, 12), level.buffer / level.extent)


@db
class TestProbes:
    """The mutation review of round 1: each holds a property a surviving mutant
    broke (reports/TILES-review-r1-mutation.md, SF1-7)."""

    def test_a_tile_and_the_coverage_stay_fresh_long_enough(self, client, live) -> None:
        import re

        for path in (url(*tile_of(*CENTRE, 14)), "/api/coverage"):
            control = client.get(path)["Cache-Control"]
            assert int(re.search(r"max-age=(\d+)", control)[1]) >= 600, path

    def test_the_trails_only_tiles_are_a_new_format(self) -> None:
        """The live table keeps its oid across the deploy that made the
        zoomed-out tiles the trails alone, so only the format version keeps its
        cached z10-12 tiles - roads and all - from being served, from the tile
        cache or as a browser's 304, for a week."""
        assert stress_tiles.FORMAT_VERSION >= 3

    def test_a_format_bump_changes_the_etag(self, client, live, monkeypatch) -> None:
        path = url(*tile_of(*CENTRE, 14))
        before = client.get(path)["ETag"]
        monkeypatch.setattr(stress_tiles, "FORMAT_VERSION", stress_tiles.FORMAT_VERSION + 1)
        after = client.get(path, HTTP_IF_NONE_MATCH=before)
        assert after.status_code == 200
        assert after["ETag"] != before

    @pytest.mark.parametrize("z", [10, 12, 14])
    def test_a_line_in_the_outer_part_of_the_buffer_is_drawn(self, client, segment_schemas, z):
        live, _ = segment_schemas
        level = stress_tiles.level_for(z)
        z, x, y = tile_of(*CENTRE, z)
        west, south, east, north = stress_tiles.tile_bounds(z, x, y)
        lon = east + 0.9 * level.buffer * (east - west) / level.extent
        _line(live, (lon, south + 0.3 * (north - south)), (lon, south + 0.7 * (north - south)))
        (feature,) = decode(client.get(url(z, x, y)).content)["stress"].features
        assert feature.lines

    @pytest.mark.parametrize("z", [10, 12])
    def test_detail_a_grid_unit_and_a_half_off_straight_is_kept(self, client, segment_schemas, z):
        live, _ = segment_schemas
        level = stress_tiles.level_for(z)
        u = stress_tiles.WORLD_M / 2**z / level.extent
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT ST_X(g), ST_Y(g) FROM "
                "ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 3857) AS g",
                list(CENTRE),
            )
            cx, cy = cursor.fetchone()
            points = [(cx - 60 * u, cy), (cx, cy + 1.5 * u), (cx + 60 * u, cy)]
            line = ", ".join(f"ST_MakePoint({px}, {py})" for px, py in points)
            cursor.execute(
                f"INSERT INTO {live}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                "stress_rule, facility) VALUES (1, 0, ST_Transform(ST_SetSRID(ST_MakeLine(ARRAY["
                f"{line}]), 3857), 4326), 4, 'x', 'path')"
            )
        (feature,) = decode(client.get(url(*tile_of(*CENTRE, z))).content)["stress"].features
        assert sum(len(line) for line in feature.lines) >= 3

    @pytest.mark.parametrize("z", [12, 14])
    def test_a_long_line_is_clipped_to_the_tile_and_its_buffer(self, client, segment_schemas, z):
        live, _ = segment_schemas
        level = stress_tiles.level_for(z)
        _line(live, (CENTRE[0] - 0.5, CENTRE[1]), (CENTRE[0] + 0.5, CENTRE[1]))
        layer = decode(client.get(url(*tile_of(*CENTRE, z))).content)["stress"]
        xs = [px for f in layer.features for line in f.lines for px, _ in line]
        assert xs
        assert all(-level.buffer <= px <= layer.extent + level.buffer for px in xs)

    @pytest.mark.parametrize("name", ["TRAILS", "BUSY", "FULL"])
    @pytest.mark.parametrize("clip", [False, True])
    def test_every_level_filters_by_the_tile_box(self, segment_schemas, name, clip) -> None:
        level = getattr(stress_tiles, name)
        z, x, y = tile_of(*CENTRE, level.min_zoom)
        c_west, c_south, c_east, c_north = settings.COVERAGE_BBOX
        params = {
            "z": z, "x": x, "y": y, "extent": level.extent, "buffer": level.buffer,
            "margin": level.buffer / level.extent, "unit": 1.0,
            "c_west": c_west, "c_south": c_south, "c_east": c_east, "c_north": c_north,
        }  # fmt: skip
        with connection.cursor() as cursor:
            cursor.execute(f"EXPLAIN (VERBOSE) {stress_tiles.tile_sql(level, clip=clip)}", params)
            plan = "\n".join(row[0] for row in cursor.fetchall())
        assert "&&" in plan, plan
        assert ("st_clipbybox2d" in plan.lower()) == clip

    def test_before_any_build_the_404_is_not_cached(self, client, segment_schemas) -> None:
        drop_segment_schema(segment_schemas[0])
        response = client.get(url(*tile_of(*CENTRE, 14)))
        assert response.status_code == 404
        assert "no-store" in response["Cache-Control"]

    def test_a_non_tile_400_is_not_cached(self, client, segment_schemas) -> None:
        response = client.get(url(14, 2**14, 0))
        assert response.status_code == 400
        assert "no-store" in response["Cache-Control"]


@db
class TestCarFree:
    """The owner, 2026-09-29: "One note: Car-free roads should be regarded the
    same as an off-road path on a map." (OWNER-DECISIONS 67). A road closed for
    good is a path in the table (the rebuild's car_free_tier_1); one closed at
    set times carries those ride times, and the map's style draws it as a path
    in them ("Path on weekends only")."""

    ROADS = [
        # (osm way, tier, rule, facility, car_free_when, is_trail_class)
        (
            4001,
            1,
            "mixed traffic, 20 mph or below, single lane",
            "path",
            [],
            False,
        ),  # Beach Drive NW
        (
            4002,
            3,
            "mixed traffic, 30 mph, single lane",
            "none",
            ["weekend"],
            False,
        ),  # Sligo Creek Pkwy
        (
            4003,
            2,
            "mixed traffic, 25 mph, single lane",
            "none",
            ["weekday_rush"],
            False,
        ),  # Clark Pl
        (4004, 1, trail_rule("cycleway", OPEN), "path", [], True),  # a trail
        (4005, 4, "mixed traffic, 35 mph or above", "none", [], False),  # a road
    ]

    @pytest.fixture
    def roads(self, segment_schemas):
        live, _ = segment_schemas
        with connection.cursor() as cursor:
            for i, (way, tier, rule, facility, when, trail) in enumerate(self.ROADS):
                lon, lat = CENTRE[0] - 0.001, CENTRE[1] - 0.0018 + i * 0.0003
                cursor.execute(
                    f"INSERT INTO {live}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                    "stress_rule, is_trail_class, is_unpaved, facility, car_free_when) VALUES "
                    "(%s, 0, ST_MakeLine(ST_MakePoint(%s, %s), ST_MakePoint(%s, %s)), %s, %s, "
                    "%s, false, %s, %s)",
                    [way, lon, lat, lon + 0.002, lat, tier, rule, trail, facility, when],
                )
        return live

    @staticmethod
    def features(client, z):
        layer = decode(client.get(url(*tile_of(*CENTRE, z))).content)["stress"]
        return sorted(
            (
                f.properties.get("tier"),
                f.properties.get("facility"),
                f.properties.get("car_free"),
                f.properties.get("car_free_only"),
            )
            for f in layer.features
            for _line in f.lines
        )

    @pytest.mark.parametrize("z", [14])
    def test_street_level_carries_each_roads_ride_times(self, client, roads, z) -> None:
        assert self.features(client, z) == sorted(
            [
                (1, "path", None, None),  # Beach Drive: a path, whatever the time
                (3, "none", "weekend", None),
                (2, "none", "weekday_rush", None),
                (1, "path", None, None),
                (4, "none", None, None),
            ]
        )

    @pytest.mark.parametrize("z", [12, 13])
    def test_at_busy_road_zoom_a_busy_timed_road_is_a_road_and_a_quiet_one_comes_for_its_times(
        self, client, roads, z
    ):
        assert self.features(client, z) == sorted(
            [
                (1, "path", None, None),
                (1, "path", None, None),
                (3, "none", "weekend", None),  # Sligo Creek Parkway at LTS 3: a busy road
                (2, "none", None, "weekday_rush"),  # Clark Place at LTS 2: only as a path
                (4, "none", None, None),
            ]
        )

    @pytest.mark.parametrize("z", [10, 11])
    def test_zoomed_out_the_timed_roads_come_for_their_times_only(self, client, roads, z):
        """The trails and Beach Drive are paths; the timed closures are there
        to be drawn in their ride times alone (`car_free_only`); a road is not."""
        assert self.features(client, z) == sorted(
            [
                (1, "path", None, None),
                (1, "path", None, None),
                (3, "none", None, "weekend"),
                (2, "none", None, "weekday_rush"),
            ]
        )

    def test_the_trails_predicate_and_its_index_take_the_timed_roads(self, roads) -> None:
        from pipeline import schema

        assert schema.trails_predicate(True, True) == (
            "((facility = 'path' OR (facility = 'protected' AND is_trail_class)) "
            "OR cardinality(car_free_when) > 0)"
        )
        assert schema.OVERVIEW_INDEX_PREDICATE == schema.busy_predicate(True, True)
        assert "segment_overview_geom_idx" in trails_plan(frozenset({"facility", "car_free_when"}))

    def test_the_etag_names_the_column(self, client, roads) -> None:
        etag = client.get(url(*tile_of(*CENTRE, 14)))["ETag"]
        assert "+cfmstl-v" in etag

    def test_one_tile_serves_every_ride_time(self, client, roads) -> None:
        """No ride time in the address or the ETag: the pre-draw draws each
        tile once, and the style chooses."""
        path = url(*tile_of(*CENTRE, 11))
        first, again = client.get(path), client.get(path)
        assert first["ETag"] == again["ETag"] and first.content == again.content


@db
class TestMapClass:
    """Only a road is drawn. The owner, 2026-09-29: "You can just leave the
    public roads where bikes aren't allowed as unmarked, using the base map"
    (OWNER-DECISIONS 89, superseding 73's white line), "For some strange reason
    BWI has TLS 3 inside the terminal." (80) and "Don't show roads that most
    typical people can't ride on, such as within military bases, or the
    pentagon" (88); and "Keep it faint if it parallels a protected bike path."
    (78), which the map draws from `separate_bikeway`."""

    ROWS = [
        # (way, tier, rule, map_class, separate_bikeway)
        (5001, 4, "motor-only classification (motorway)", "barred", False),
        (5002, 4, "mixed traffic, 35 mph or above", "barred", False),  # a parkway, bicycle=no
        (5003, 3, "mixed traffic, 30 mph, single lane", "hidden", False),  # a terminal hallway
        (5004, 4, "mixed traffic, 35 mph or above", "road", True),  # beside its cycle track
        (5005, 5, "legal but avoid: expressway posted 55 mph", "road", False),  # US 340
    ]

    @pytest.fixture
    def ways(self, segment_schemas):
        live, _ = segment_schemas
        with connection.cursor() as cursor:
            for i, (way, tier, rule, map_class, beside) in enumerate(self.ROWS):
                lon, lat = CENTRE[0] - 0.001, CENTRE[1] - 0.0018 + i * 0.0003
                cursor.execute(
                    f"INSERT INTO {live}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                    "stress_rule, map_class, separate_bikeway) VALUES (%s, 0, "
                    "ST_MakeLine(ST_MakePoint(%s, %s), ST_MakePoint(%s, %s)), %s, %s, %s, %s)",
                    [way, lon, lat, lon + 0.002, lat, tier, rule, map_class, beside],
                )
        return live

    @staticmethod
    def drawn(client, z):
        layer = decode(client.get(url(*tile_of(*CENTRE, z))).content)["stress"]
        assert all("map_class" not in f.properties for f in layer.features)
        return sorted(
            (f.properties.get("tier"), f.properties.get("separate_bikeway", False))
            for f in layer.features
            for _line in f.lines
        )  # fmt: skip

    @pytest.mark.parametrize("z", [12, 14])
    def test_only_the_roads_are_drawn(self, client, ways, z) -> None:
        assert self.drawn(client, z) == [(4, True), (5, False)]

    def test_an_alley_is_in_the_street_level_tiles_only_and_marked(self, client, ways) -> None:
        """ "Cut down on showing them, and only use them if nessicary." (OWNER-DECISIONS 100)"""
        with connection.cursor() as cursor:
            lon, lat = CENTRE[0] - 0.001, CENTRE[1] + 0.0012
            cursor.execute(
                f"INSERT INTO {ways}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                "stress_rule, map_class) VALUES (5006, 0, ST_MakeLine(ST_MakePoint(%s, %s), "
                "ST_MakePoint(%s, %s)), 3, 'x', 'alley')",
                [lon, lat, lon + 0.002, lat],
            )
        assert self.drawn(client, 12) == [(4, True), (5, False)]
        layer = decode(client.get(url(*tile_of(*CENTRE, 14))).content)["stress"]
        alleys = [f for f in layer.features if f.properties.get("alley") is True]
        assert [f.properties["tier"] for f in alleys] == [3]
        assert all("alley" not in f.properties for f in layer.features if f not in alleys)

    def test_without_the_column_a_motorway_is_left_out_by_its_recorded_rule(self, client, ways):
        with connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE {ways}.segment DROP COLUMN map_class")
            cursor.execute(f"ALTER TABLE {ways}.segment DROP COLUMN separate_bikeway")
        assert self.drawn(client, 14) == [(3, False), (4, False), (4, False), (5, False)]

    def test_the_columns_are_the_schemas(self) -> None:
        from pipeline import schema

        ddl = schema.SEGMENT_DDL
        assert "map_class       text        NOT NULL DEFAULT 'road'" in ddl
        assert "CHECK (map_class IN ('road', 'barred', 'hidden', 'alley'))" in ddl
        assert "separate_bikeway boolean    NOT NULL DEFAULT false" in ddl


MILE = 1609.344


def insert_trail(schema, unpaved, route=0, run_mi=None, car_free=None) -> None:
    """One open path in the middle of the tile, on route level `route` and in a
    named run of `run_mi` miles (none when it has no name)."""
    lon, lat = CENTRE[0] - 0.001, CENTRE[1]
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {schema}.segment (osm_way_id, ordinal, geometry, stress_tier, "
            "stress_rule, is_trail_class, is_unpaved, facility, trail_name, trail_route, "
            "trail_run_m, car_free_when) VALUES "
            "(7, 0, ST_MakeLine(ST_MakePoint(%s, %s), ST_MakePoint(%s, %s)), 1, %s, true, "
            "%s, 'path', %s, %s, %s, %s)",
            [
                lon, lat, lon + 0.002, lat, trail_rule("path", OPEN), unpaved,
                None if run_mi is None else "A Trail", route,
                None if run_mi is None else round(run_mi * MILE), car_free or [],
            ],
        )  # fmt: skip


def lines_in(body: bytes) -> int:
    return sum(
        len(f.lines) for f in decode(body).get("stress", type("L", (), {"features": []})).features
    )


@db
class TestLongTrails:
    """The zoomed-out tiles keep the long trails (OWNER-DECISIONS 375, 2026-10-04:
    "Also zoomed out, can we stick to mostly the longer trails, it's getting
    messy."): a way on a route, or in a named run of trail long enough, with a
    higher bar for an unpaved way and a higher bar again at z10 than at z11.
    The miles are written out here, so the tests hold the schema's constants to
    them."""

    def test_the_bars_are_the_owners_decision(self) -> None:
        from pipeline import schema

        assert schema.PAVED_ROUTE_MIN == 2  # OWNER-DECISIONS 377: not a local route
        assert stress_tiles.TRAILS.long_trails == schema.LongTrails(5.0, 8.0, 3)
        assert stress_tiles.TRAILS_NEAR.long_trails == schema.LongTrails(2.5, 5.0, 3)
        assert stress_tiles.BUSY.long_trails is stress_tiles.FULL.long_trails is None

    @pytest.mark.parametrize(
        ("unpaved", "route", "run_mi", "at_z10", "at_z11"),
        [
            (False, 0, None, False, False),  # no name, no route: a connector
            (False, 1, None, False, False),  # a local route alone no longer does (377)
            (False, 2, None, True, True),  # and so does a long walking route
            (False, 3, None, True, True),
            (False, 0, 2.4, False, False),
            (False, 0, 2.5, False, True),  # z11's bar for a paved run (380: was 3 mi)
            (False, 0, 2.54, False, True),  # the Grist Mill Trail
            (False, 0, 4.9, False, True),
            (False, 0, 5.0, True, True),  # z10's
            (None, 0, 2.5, False, True),  # an unknown surface is read as paved
            (None, 1, None, False, False),
            (True, 0, None, False, False),
            (True, 1, None, False, False),  # a local route is not enough for a dirt trail
            (True, 2, None, False, False),  # a walking route: paved ways only (378)
            (True, 3, None, True, True),  # a long bicycle route: both
            (True, 0, 4.9, False, False),
            (True, 0, 5.0, False, True),  # z11's bar for an unpaved run
            (True, 0, 7.9, False, True),
            (True, 0, 8.0, True, True),  # z10's
        ],
    )
    def test_each_zoom_keeps_the_ways_that_clear_its_bar(
        self, client, segment_schemas, unpaved, route, run_mi, at_z10, at_z11
    ) -> None:
        live, _ = segment_schemas
        insert_trail(live, unpaved, route, run_mi)
        kept = {z: lines_in(client.get(url(*tile_of(*CENTRE, z))).content) for z in (10, 11)}
        assert kept == {10: int(at_z10), 11: int(at_z11)}

    @pytest.mark.parametrize("z", [12, 13, 14, 16])
    def test_from_z12_nothing_is_dropped_for_being_short(self, client, segment_schemas, z) -> None:
        live, _ = segment_schemas
        insert_trail(live, True, 0, None)
        assert lines_in(client.get(url(*tile_of(*CENTRE, z))).content) == 1

    @pytest.mark.parametrize("z", [10, 11])
    @pytest.mark.parametrize("on_path", [True, False])
    def test_a_road_closed_at_set_times_stays_whatever_its_length(
        self, client, segment_schemas, z, on_path
    ) -> None:
        """OWNER-DECISIONS 377: "Car free roads stay." A timed closure with
        no name, no route and a run of nothing is kept, styled as before:
        `car_free` where the road is a path, `car_free_only` where it is not."""
        live, _ = segment_schemas
        insert_trail(live, False, 0, None, car_free=["weekend"])
        if not on_path:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE {live}.segment SET facility = 'none', is_trail_class = false"
                )
        body = client.get(url(*tile_of(*CENTRE, z))).content
        assert lines_in(body) == 1
        (feature,) = decode(body)["stress"].features
        key = "car_free" if on_path else "car_free_only"
        assert feature.properties.get(key) == "weekend"

    def test_a_way_with_no_closure_is_still_judged_by_the_bar(
        self, client, segment_schemas
    ) -> None:
        live, _ = segment_schemas
        insert_trail(live, False, 0, 0.1)
        assert lines_in(client.get(url(*tile_of(*CENTRE, 11))).content) == 0

    @pytest.mark.parametrize("drop", [["trail_route", "trail_run_m"], ["trail_run_m"]])
    def test_a_table_without_the_columns_draws_every_trail_as_before(
        self, client, segment_schemas, drop
    ) -> None:
        """The columns arrive with a data rebuild; until then (and on a table
        with only one of them) nothing is dropped, and the ETag says which
        table the tiles were drawn from."""
        live, _ = segment_schemas
        insert_trail(live, True, 0, None)
        with connection.cursor() as cursor:
            for column in drop:
                cursor.execute(f"ALTER TABLE {live}.segment DROP COLUMN {column}")
        for z in (10, 11):
            response = client.get(url(*tile_of(*CENTRE, z)))
            assert lines_in(response.content) == 1
            assert "+cfms-v" in response["ETag"] or "+cfmst-v" in response["ETag"]

    def test_the_etag_names_the_columns(self, client, segment_schemas) -> None:
        live, _ = segment_schemas
        insert_trail(live, True, 3, None)
        assert "+cfmstl-v" in client.get(url(*tile_of(*CENTRE, 10)))["ETag"]

    def test_the_overview_index_still_serves_the_long_trails_query(self, live) -> None:
        optional = frozenset({"facility", "car_free_when", *stress_tiles.LONG_TRAIL_COLUMNS})
        for level in (stress_tiles.TRAILS, stress_tiles.TRAILS_NEAR):
            z, x, y = tile_of(*CENTRE, level.min_zoom)
            params = {"z": z, "x": x, "y": y, "extent": 4096, "buffer": 32, "margin": 0.01}
            params["unit"] = 1.0
            with connection.cursor() as cursor:
                cursor.execute("SET enable_seqscan = off")
                try:
                    cursor.execute(f"EXPLAIN {stress_tiles.tile_sql(level, optional)}", params)
                    plan = "\n".join(row[0] for row in cursor.fetchall())
                finally:
                    cursor.execute("RESET enable_seqscan")
            assert "segment_overview_geom_idx" in plan

    def test_the_rule_is_one_expression_in_the_schema(self) -> None:
        from pipeline.schema import LongTrails, long_trails_predicate

        sql = long_trails_predicate(LongTrails(5.0, 8.0, 3))
        assert "COALESCE(trail_run_m, 0) >= 4023" in long_trails_predicate(LongTrails(2.5, 5.0, 3))
        assert "trail_route >= 3 OR COALESCE(trail_run_m, 0) >= 12875" in sql
        assert "trail_route >= 2 OR COALESCE(trail_run_m, 0) >= 8047" in sql
        assert "cardinality(car_free_when) > 0" not in sql
        assert "cardinality(car_free_when) > 0" in long_trails_predicate(
            LongTrails(5.0, 8.0, 3), True
        )
        assert "is_unpaved IS TRUE" in sql
