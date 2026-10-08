"""GET /tiles/mass/{z}/{x}/{y}.pbf: the Mass Ride map's own tiles (OWNER-DECISIONS 415, 417, 418).

Against a real live segment table, as tests/test_stress_tiles.py, decoded with `tests/mvt.py`.
What is held here: every road with a capacity at z12-13 (busy ones too, where the stress tiles
are the ride layer), no trail, nothing outside the District (each line clipped to its
boundary), the cache shared with the stress tiles without either evicting the other, and the
pre-draw drawing the District's tiles. Then the bands each zoom holds (421, 422: Wide open
only at z10-11, and only in a run of half a mile; Good and up at z12-13; every band from
z14) and the border roads drawn as inside (420).
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest
from django.db import connection
from django.test import override_settings
from mvt import decode
from shapely.geometry import MultiLineString, Point, shape
from shapely.ops import nearest_points

from core import mass_tiles, stress_tiles, tile_cache
from routemaker import flow

db = pytest.mark.django_db(transaction=True)

WHITE_HOUSE = (-77.0365, 38.8977)
# Rosslyn, Virginia: across the Potomac from Georgetown, outside the District.
ROSSLYN = (-77.0720, 38.8960)
# Georgetown's waterfront, inside the District, about 2.5 km (1.6 mi) from Rosslyn's line below.
GEORGETOWN = (-77.0600, 38.9030)
BALTIMORE = (-76.6122, 39.2904)


def tile_of(lon: float, lat: float, z: int) -> tuple[int, int, int]:
    n = 2**z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return z, x, y


def url(z: int, x: int, y: int, kind: str = "mass") -> str:
    return f"/tiles/{kind}/{z}/{x}/{y}.pbf"


def road(
    schema, way, start, end, tier=3, rpm=150.0, trail=False, facility="none", ordinal=0
) -> None:
    line(schema, way, [start, end], tier, rpm, trail, facility, ordinal)


def line(
    schema,
    way,
    points,
    tier=3,
    rpm=150.0,
    trail=False,
    facility="none",
    ordinal=0,
    map_class="road",
) -> None:
    width = None if rpm is None else rpm / flow.level_riders_per_min(1.0)
    wkt = "LINESTRING(" + ", ".join(f"{lon} {lat}" for lon, lat in points) + ")"
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {schema}.segment (osm_way_id, ordinal, geometry, stress_tier, "
            "stress_rule, is_trail_class, facility, mass_usable_width_m, calm_run_m, map_class) "
            "VALUES (%s, %s, ST_GeomFromText(%s, 4326), %s, 'x', %s, %s, %s, 0, %s)",
            [way, ordinal, wkt, tier, trail, facility, width, map_class],
        )


def east_of(point, metres=150.0):
    return (point[0] + metres / 86_700, point[1])


def features(client, z, at=WHITE_HOUSE, kind="mass"):
    response = client.get(url(*tile_of(*at, z), kind=kind))
    assert response.status_code == 200
    return decode(response.content).get("stress", None)


DC = shape(mass_tiles.json.loads(mass_tiles.DC_BOUNDARY_PATH.read_text())["geometry"])


def lonlat(z, x, y, px, py, extent=4096):
    """A tile coordinate back to degrees."""
    n = 2**z
    lon = (x + px / extent) / n * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + py / extent) / n))))
    return lon, lat


class TestBoundary:
    def test_the_two_copies_are_the_same_bytes(self) -> None:
        from pathlib import Path

        front = Path(__file__).resolve().parents[1] / "frontend/src/massride-data/dc-boundary.json"
        assert front.read_bytes() == mass_tiles.DC_BOUNDARY_PATH.read_bytes()

    def test_it_is_the_district(self) -> None:
        assert DC.contains(Point(WHITE_HOUSE)) and DC.contains(Point(GEORGETOWN))
        assert not DC.contains(Point(ROSSLYN)) and not DC.contains(Point(BALTIMORE))
        # About the District's 68 square miles (177 km²), land and water.
        k = math.cos(math.radians(38.9))
        area_km2 = DC.area * 111.32 * k * 110.95
        assert 170 < area_km2 < 185

    def test_its_source_is_credited(self) -> None:
        from pathlib import Path

        repo = Path(__file__).resolve().parents[1]
        sources = (repo / "docs/SOURCES.md").read_text()
        assert "dc-boundary" in sources and "ISO3166-2=US-DC" in sources
        props = mass_tiles.json.loads(mass_tiles.DC_BOUNDARY_PATH.read_text())["properties"]
        assert props["credit"] == "© OpenStreetMap contributors (ODbL)"

    def test_the_box_is_the_polygons(self) -> None:
        west, south, east, north = mass_tiles.dc_boundary()[1]
        assert (west, south, east, north) == pytest.approx(DC.bounds)


@db
class TestTiles:
    def test_busy_roads_carry_their_capacity_at_z12_and_13(self, client, segment_schemas):
        """415: the stress tiles' z12-13 is the ride layer, with no busy road; these have them."""
        live, _ = segment_schemas
        road(live, 1, WHITE_HOUSE, east_of(WHITE_HOUSE), tier=4, rpm=150)
        for z in (12, 13):
            mass = features(client, z)
            assert [(f.properties["tier"], f.properties["rpm"]) for f in mass.features] == [
                (4, 150)
            ]
            stress = features(client, z, kind="stress")
            assert stress is None or not stress.features, "the stress map's ride layer is unchanged"

    def test_every_zoom_the_map_asks_for_draws_and_deeper_is_empty(self, client, segment_schemas):
        live, _ = segment_schemas
        # Wide open and a kilometre long: every zoom holds it (421, 422).
        road(live, 1, WHITE_HOUSE, east_of(WHITE_HOUSE, 1000), tier=2, rpm=250)
        for z in range(mass_tiles.MIN_ZOOM, mass_tiles.MAX_ZOOM + 1):
            assert [f.properties["rpm"] for f in features(client, z).features] == [250], z
        assert client.get(url(*tile_of(*WHITE_HOUSE, 15))).content == b""
        assert mass_tiles.MAX_ZOOM == 14 == tile_cache.PREDRAW_MAX_ZOOM

    def test_no_trail_path_or_road_without_a_capacity(self, client, segment_schemas):
        """417, 417a: trails and protected lanes are not drawn on the Mass Ride map."""
        live, _ = segment_schemas
        y = WHITE_HOUSE[1]
        road(live, 1, WHITE_HOUSE, east_of(WHITE_HOUSE), rpm=150)
        road(
            live, 2, (WHITE_HOUSE[0], y + 0.0003), east_of((WHITE_HOUSE[0], y + 0.0003)), trail=True
        )
        road(
            live,
            3,
            (WHITE_HOUSE[0], y + 0.0006),
            east_of((WHITE_HOUSE[0], y + 0.0006)),
            facility="path",
        )
        road(live, 4, (WHITE_HOUSE[0], y + 0.0009), east_of((WHITE_HOUSE[0], y + 0.0009)), rpm=None)
        for z in (12, 14):
            layer = features(client, z)
            assert sum(len(f.lines) for f in layer.features) == 1, z

    def test_a_barred_road_or_an_alley_with_a_width_is_not_drawn(self, client, segment_schemas):
        """A motorway or a bicycle=no road has a mass width (the lane count's default), and
        an alley a width too; only a `road` is the Mass Ride map's."""
        live, _ = segment_schemas
        y = WHITE_HOUSE[1]
        road(live, 1, WHITE_HOUSE, east_of(WHITE_HOUSE), rpm=150)
        for way, map_class in ((2, "barred"), (3, "alley"), (4, "hidden")):
            start = (WHITE_HOUSE[0], y + 0.0003 * (way - 1))
            line(live, way, [start, east_of(start)], rpm=250, map_class=map_class)
        for z in (12, 14):
            assert rpms(features(client, z)) == [(3, 150)], z

    def test_a_barred_line_or_a_trail_is_no_part_of_a_run(self, client, segment_schemas):
        """422: 300 m of Wide open road with a barred line, a trail and an Avoid line
        joined on, each longer than the run's half mile, is still a short block (z10-11)."""
        live, _ = segment_schemas
        road(live, 1, WHITE_HOUSE, east_of(WHITE_HOUSE, 300), rpm=250)
        barred = [east_of(WHITE_HOUSE, 300), east_of(WHITE_HOUSE, 900)]
        line(live, 2, barred, rpm=250, map_class="barred")
        line(live, 3, [WHITE_HOUSE, east_of(WHITE_HOUSE, -600)], rpm=250, trail=True)
        line(live, 4, [WHITE_HOUSE, north_of(WHITE_HOUSE, 600)], tier=5, rpm=250)
        for z in (10, 11):
            assert rpms(features(client, z)) == [(5, 250)], z

    def test_a_run_is_measured_inside_the_district(self, client, segment_schemas):
        """422: a 300 m stretch of Wide open road inside the District that goes on for a mile
        outside it is a short block, not a run: Maryland's length does not count."""
        live, _ = segment_schemas
        inside = GEORGETOWN
        edge = nearest_points(DC.boundary, Point(inside))[0]
        k = math.cos(math.radians(38.9))
        dx, dy = (edge.x - inside[0]) * 111_320 * k, (edge.y - inside[1]) * 110_950
        n = math.hypot(dx, dy)

        def along(metres):
            return (
                edge.x + dx / n * metres / (111_320 * k),
                edge.y + dy / n * metres / 110_950,
            )

        line(live, 1, [along(-300), along(1500)], rpm=250)
        assert DC.contains(Point(along(-300))) and not DC.contains(Point(along(1500)))
        for z in (10, 11):
            assert rpms(features(client, z, at=inside)) == [], z
        assert rpms(features(client, 12, at=inside)) == [(3, 250)]

    def test_nothing_outside_the_district(self, client, segment_schemas):
        """418: no capacity colour outside DC; a tile that misses its box is empty."""
        live, _ = segment_schemas
        road(live, 1, ROSSLYN, east_of(ROSSLYN, -150))
        road(live, 2, BALTIMORE, east_of(BALTIMORE))
        layer = features(client, 14, at=ROSSLYN)
        assert layer is None or not layer.features
        assert mass_tiles.outside_dc(*tile_of(*BALTIMORE, 12))
        assert client.get(url(*tile_of(*BALTIMORE, 12))).content == b""
        # The stress map still draws them.
        assert features(client, 14, at=ROSSLYN, kind="stress").features

    def test_a_road_across_the_boundary_is_cut_at_it(self, client, segment_schemas):
        live, _ = segment_schemas
        road(live, 1, GEORGETOWN, ROSSLYN)
        z = 13
        _, x, y = tile_of(*GEORGETOWN, z)
        assert tile_of(*ROSSLYN, z)[1:] == (x, y), "both ends in one tile, for the test"
        layer = features(client, z, at=GEORGETOWN)
        points = [
            lonlat(z, x, y, px, py) for f in layer.features for line in f.lines for px, py in line
        ]
        assert points
        near = DC.buffer(0.0003)  # a tile unit and the boundary's own simplification
        assert all(near.contains(Point(p)) for p in points)
        assert max(p[0] for p in points) > GEORGETOWN[0] - 0.001, "the District's part is drawn"

    def test_a_table_without_the_capacity_draws_nothing(self, client, segment_schemas):
        live, _ = segment_schemas
        road(live, 1, WHITE_HOUSE, east_of(WHITE_HOUSE))
        with connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE {live}.segment DROP COLUMN mass_usable_width_m")
        response = client.get(url(*tile_of(*WHITE_HOUSE, 12)))
        assert response.status_code == 200 and response.content == b""
        assert "w" not in response["ETag"].split("-")[1]

    def test_no_build_is_a_404_and_a_bad_address_a_400(self, client, segment_schemas):
        from pipeline.schema import drop_segment_schema

        assert client.get("/tiles/mass/3/9/0.pbf").status_code == 400
        drop_segment_schema(segment_schemas[0])
        assert client.get(url(*tile_of(*WHITE_HOUSE, 12))).status_code == 404


@db
class TestCaching:
    def test_the_tag_is_its_own(self, client, segment_schemas):
        live, _ = segment_schemas
        road(live, 1, WHITE_HOUSE, east_of(WHITE_HOUSE))
        mass = client.get(url(*tile_of(*WHITE_HOUSE, 14)))
        stress = client.get(url(*tile_of(*WHITE_HOUSE, 14), kind="stress"))
        tag = mass["ETag"]
        assert tag.startswith('W/"mass-') and tag != stress["ETag"]
        assert f"-{mass_tiles.dc_boundary()[2]}-v{mass_tiles.FORMAT_VERSION}" in tag
        assert "+fmw-" in tag
        assert len(mass_tiles.etag_for(10**10 - 1, frozenset(mass_tiles.TAG_COLUMNS))) == 33 < 64
        again = client.get(url(*tile_of(*WHITE_HOUSE, 14)), HTTP_IF_NONE_MATCH=tag)
        assert again.status_code == 304

    def test_a_drawn_tile_is_kept_and_served_from_the_cache(self, client, segment_schemas):
        live, _ = segment_schemas
        road(live, 1, WHITE_HOUSE, east_of(WHITE_HOUSE))
        first = client.get(url(*tile_of(*WHITE_HOUSE, 13)))
        oid, optional = stress_tiles.live_table()
        assert (
            tile_cache.get(mass_tiles.etag_for(oid, optional), *tile_of(*WHITE_HOUSE, 13))
            == first.content
        )

    def test_neither_tile_set_evicts_the_other(self, segment_schemas):
        oid, optional = stress_tiles.live_table()
        stress, mass = stress_tiles.etag_for(oid, optional), mass_tiles.etag_for(oid, optional)
        tile_cache.put(mass, 12, 1, 1, b"m")
        tile_cache.put(stress, 12, 1, 1, b"s")
        tile_cache.put('W/"stress-1-v1"', 12, 1, 1, b"old")
        tile_cache.evict(stress, also_keep=(mass,))
        assert tile_cache.get(mass, 12, 1, 1) == b"m" and tile_cache.get(stress, 12, 1, 1) == b"s"
        assert tile_cache.get('W/"stress-1-v1"', 12, 1, 1) is None

    def test_a_stress_tile_drawn_on_request_does_not_evict_the_mass_tiles(
        self, client, segment_schemas, monkeypatch
    ):
        """The stress tiles' own cache write, past the pre-draw zooms, evicts stale versions
        every time (EVICT_EVERY made 1): the Mass Ride tiles' tag is not stale."""
        live, _ = segment_schemas
        road(live, 1, WHITE_HOUSE, east_of(WHITE_HOUSE))
        oid, optional = stress_tiles.live_table()
        mass = mass_tiles.etag_for(oid, optional)
        tile_cache.put(mass, 12, 1, 1, b"m")
        tile_cache.put('W/"stress-1-v1"', 12, 1, 1, b"old")
        monkeypatch.setattr(tile_cache, "EVICT_EVERY", 1)
        z = tile_cache.PREDRAW_MAX_ZOOM + 1
        assert features(client, z, kind="stress").features
        assert tile_cache.get('W/"stress-1-v1"', 12, 1, 1) is None, "the eviction ran"
        assert tile_cache.get(mass, 12, 1, 1) == b"m"

    def test_the_predraw_draws_the_districts_tiles_too(self, segment_schemas, monkeypatch):
        live, _ = segment_schemas
        road(live, 1, WHITE_HOUSE, east_of(WHITE_HOUSE))
        box = (
            WHITE_HOUSE[0] - 0.0005,
            WHITE_HOUSE[1] - 0.0005,
            WHITE_HOUSE[0] + 0.0005,
            WHITE_HOUSE[1] + 0.0005,
        )
        monkeypatch.setattr(
            mass_tiles,
            "tiles_over_dc",
            lambda max_zoom=14: [tile_of(*WHITE_HOUSE, z) for z in range(10, max_zoom + 1)],
        )
        with override_settings(COVERAGE_BBOX=box):
            both = len(tile_cache.tiles_in_coverage(14)) + 5
            assert tile_cache.predraw() == (both, 0, 0, 0)
            assert tile_cache.predraw() == (0, both, 0, 0)
        oid, optional = stress_tiles.live_table()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM stress_tile_cache WHERE version = %s",
                [mass_tiles.etag_for(oid, optional)],
            )
            assert cursor.fetchone()[0] == 5

    def test_the_districts_tiles_are_few(self) -> None:
        """What the pre-draw adds: z10-14 over the District's box, a few hundred tiles
        beside the stress tiles' 11,068 (docs/OPERATIONS.md)."""
        tiles = mass_tiles.tiles_over_dc()
        by_zoom = {z: sum(1 for t in tiles if t[0] == z) for z in range(10, 15)}
        assert sum(by_zoom.values()) == len(set(tiles)) < 300
        assert all(not mass_tiles.outside_dc(*t) for t in tiles)


def rpms(layer) -> list[tuple[int, int]]:
    return sorted(
        (f.properties["tier"], f.properties["rpm"]) for f in (layer.features if layer else [])
    )


def north_of(point, metres):
    return (point[0], point[1] + metres / 111_000)


@db
class TestFocusByZoom:
    """421, 422: z10-11 Wide open only, in a run of at least half a mile; z12-13 Good and
    Wide open; z14 every band. Avoid at every zoom."""

    def test_the_settings(self) -> None:
        assert mass_tiles.WIDE_OPEN_RPM == 200 and mass_tiles.GOOD_RPM == 120
        assert mass_tiles.WIDE_RUN_MI == 0.5 and mass_tiles.WIDE_RUN_M == 805
        assert [mass_tiles.min_rpm_for(z) for z in range(10, 17)] == [
            200,
            200,
            120,
            120,
            None,
            None,
            None,
        ]

    def test_the_map_style_and_legend_say_the_same(self) -> None:
        """massStyle.js's band edges and first zooms, and the run the legend says."""
        front = Path(__file__).resolve().parents[1] / "frontend/src"
        style = (front / "massStyle.js").read_text()
        bands = {
            key: (int(low), int(zoom))
            for key, low, zoom in re.findall(r'key: "(\w+)".*?min: (\d+),.*?minzoom: (\d+)', style)
        }
        assert bands == {
            "bottleneck": (0, mass_tiles.EVERY_BAND_MIN_ZOOM),
            "tight": (60, mass_tiles.EVERY_BAND_MIN_ZOOM),
            "good": (mass_tiles.GOOD_RPM, mass_tiles.GOOD_MIN_ZOOM),
            "wide": (mass_tiles.WIDE_OPEN_RPM, mass_tiles.MIN_ZOOM),
        }
        run = re.search(r"export const MASS_WIDE_RUN_MI = ([\d.]+);", style)
        assert run and float(run.group(1)) == mass_tiles.WIDE_RUN_MI

    def test_each_zoom_holds_its_bands(self, client, segment_schemas):
        live, _ = segment_schemas
        rows = [(1, 3, 250), (2, 3, 150), (3, 3, 90), (4, 3, 40), (5, 5, 90)]
        for i, (way, tier, rpm) in enumerate(rows):
            start = north_of(WHITE_HOUSE, 60 * i)
            road(live, way, start, east_of(start, 1000), tier=tier, rpm=rpm)
        avoid = (5, 90)
        for z in (10, 11):
            assert rpms(features(client, z)) == [(3, 250), avoid], z
        for z in (12, 13):
            assert rpms(features(client, z)) == [(3, 150), (3, 250), avoid], z
        assert rpms(features(client, 14)) == [(3, 40), (3, 90), (3, 150), (3, 250), avoid]

    def test_an_isolated_wide_open_block_is_no_speck(self, client, segment_schemas):
        """422: a short Wide open block on its own shows from z12, not at z10-11."""
        live, _ = segment_schemas
        road(live, 1, WHITE_HOUSE, east_of(WHITE_HOUSE, 300), rpm=250)
        for z in (10, 11):
            assert rpms(features(client, z)) == [], z
        assert rpms(features(client, 12)) == [(3, 250)]

    def test_blocks_that_join_make_a_run(self, client, segment_schemas):
        """Three 300 m blocks end to end (900 m) are a run; two 350 m blocks (700 m) are not."""
        live, _ = segment_schemas
        west = WHITE_HOUSE
        for i in range(3):
            road(live, 1, east_of(west, 300 * i), east_of(west, 300 * (i + 1)), rpm=250, ordinal=i)
        short = north_of(WHITE_HOUSE, 200)
        for i in range(2):
            road(
                live, 2, east_of(short, 350 * i), east_of(short, 350 * (i + 1)), rpm=260, ordinal=i
            )
        # A Good block between two Wide open ones breaks the run.
        broken = north_of(WHITE_HOUSE, 400)
        road(live, 3, broken, east_of(broken, 450), rpm=270)
        road(live, 3, east_of(broken, 450), east_of(broken, 500), rpm=150, ordinal=1)
        road(live, 3, east_of(broken, 500), east_of(broken, 950), rpm=270, ordinal=2)
        for z in (10, 11):
            assert rpms(features(client, z)) == [(3, 250)], z
        assert (3, 260) in rpms(features(client, 12)) and (3, 270) in rpms(features(client, 12))

    def test_a_bridge_over_a_road_does_not_join_its_run(self, client, segment_schemas):
        """Two 450 m Wide open roads that cross with no shared node (one bridges the other)
        are two runs, each under half a mile."""
        live, _ = segment_schemas
        west = WHITE_HOUSE
        road(live, 1, west, east_of(west, 450), rpm=250)
        middle = east_of(west, 225)
        road(live, 2, north_of(middle, -225), north_of(middle, 225), rpm=260)
        for z in (10, 11):
            assert rpms(features(client, z)) == [], z
        # Joined at a shared node they would be one run: test_blocks_that_join_make_a_run.

    def test_a_tile_edge_does_not_cut_a_run(self, client, segment_schemas):
        """The run is found over the whole District: 433 m each side of a z10 and z11 edge."""
        live, _ = segment_schemas
        edge = -180 + 360 * 586 / 2**11  # -76.992, east of the Capitol, inside DC
        assert edge == -180 + 360 * 293 / 2**10
        lat = 38.8900
        road(live, 1, (edge - 0.005, lat), (edge, lat), rpm=250)
        road(live, 1, (edge, lat), (edge + 0.005, lat), rpm=250, ordinal=1)
        for z in (10, 11):
            west = features(client, z, at=(edge - 0.003, lat))
            east = features(client, z, at=(edge + 0.003, lat))
            assert rpms(west) and rpms(east), z


# Real stretches of the border roads, from the 2026-10-03 build (live.segment, read-only):
# the Western Ave one lies just inside the simplified boundary; the Eastern and Southern Ave
# ones have vertices 9.4 m and 19.5 m outside it, the farthest of each road.
WESTERN_AVE = [
    (-77.084214, 38.961965),
    (-77.083929, 38.962188),
    (-77.083631, 38.96242),
    (-77.082658, 38.963182),
    (-77.082163, 38.963568),
    (-77.080491, 38.964888),
    (-77.080377, 38.964977),
]
EASTERN_AVE = [
    (-77.007528, 38.969892),
    (-77.008622, 38.970748),
    (-77.008838, 38.970918),
    (-77.010836, 38.972481),
]
SOUTHERN_AVE = [
    (-76.94002, 38.868768),
    (-76.939425, 38.86923),
    (-76.938852, 38.86968),
    (-76.938585, 38.869881),
    (-76.938382, 38.870041),
    (-76.938249, 38.870143),
]
BORDER_ROADS = {
    "Western Ave": WESTERN_AVE,
    "Eastern Ave": EASTERN_AVE,
    "Southern Ave": SOUTHERN_AVE,
}


def drawn_points(client, z, at):
    _, x, y = tile_of(*at, z)
    layer = features(client, z, at=at)
    return [
        lonlat(z, x, y, px, py)
        for f in (layer.features if layer else [])
        for part in f.lines
        for px, py in part
    ]


def drawn_lines(client, z, at):
    _, x, y = tile_of(*at, z)
    layer = features(client, z, at=at)
    return MultiLineString(
        [
            [lonlat(z, x, y, px, py) for px, py in part]
            for f in (layer.features if layer else [])
            for part in f.lines
        ]
    )


def outward(at, distance):
    """The point `distance` metres outside the District, straight out from its edge nearest `at`."""
    q = nearest_points(DC.boundary, Point(at))[0]
    k = math.cos(math.radians(38.9))
    dx, dy = (q.x - at[0]) * 111_320 * k, (q.y - at[1]) * 110_950
    if not DC.contains(Point(at)):
        dx, dy = -dx, -dy
    n = math.hypot(dx, dy)
    return (q.x + dx / n * distance / (111_320 * k), q.y + dy / n * distance / 110_950), (
        dx / n,
        dy / n,
    )


@db
class TestBorderRoads:
    """420: "Border roads are inside DC". A line wholly within the tolerance is drawn whole."""

    def test_the_tolerance_is_the_simplification_and_a_half_road(self) -> None:
        assert mass_tiles.DC_EDGE_TOLERANCE_M == 22
        front = Path(__file__).resolve().parents[1] / "frontend/src/lib/dcBoundary.ts"
        said = re.search(r"export const DC_EDGE_TOLERANCE_M = (\d+);", front.read_text())
        assert said and int(said.group(1)) == mass_tiles.DC_EDGE_TOLERANCE_M

    def test_the_samples_are_where_they_say(self) -> None:
        def out_m(p):
            return 0.0 if DC.contains(Point(p)) else DC.boundary.distance(Point(p)) * 86_700

        assert max(out_m(p) for p in WESTERN_AVE) == 0
        assert 5 < max(out_m(p) for p in EASTERN_AVE) < mass_tiles.DC_EDGE_TOLERANCE_M
        assert 15 < max(out_m(p) for p in SOUTHERN_AVE) < mass_tiles.DC_EDGE_TOLERANCE_M

    @pytest.mark.parametrize("name", list(BORDER_ROADS))
    def test_a_border_road_is_drawn_whole(self, client, segment_schemas, name):
        live, _ = segment_schemas
        points = BORDER_ROADS[name]
        line(live, 1, points, rpm=150)
        for z in (12, 14):
            drawn = drawn_lines(client, z, points[len(points) // 2])
            assert not drawn.is_empty, (name, z)
            # Every vertex, the ones outside the simplified boundary too, is on the drawn line
            # (a tile unit at z12 is about 2.4 m; a degree is at most 111 km).
            for p in points:
                assert drawn.distance(Point(p)) * 111_000 < 5, (name, z, p)

    def test_a_street_leaving_the_district_is_cut_at_the_line(self, client, segment_schemas):
        """A Maryland street off Western Ave gets no stub past the boundary."""
        live, _ = segment_schemas
        inside = WESTERN_AVE[3]
        far, _ = outward(inside, 200)
        road(live, 1, inside, far, rpm=150)
        drawn = drawn_points(client, 14, inside)
        assert drawn
        assert all(DC.buffer(0.00004).contains(Point(p)) for p in drawn)

    def test_a_road_clearly_outside_is_not_drawn(self, client, segment_schemas):
        live, _ = segment_schemas
        centre, (nx, ny) = outward(WESTERN_AVE[3], 100)
        k = math.cos(math.radians(38.9))
        tx, ty = -ny * 150 / (111_320 * k), nx * 150 / 110_950
        road(live, 1, (centre[0] - tx, centre[1] - ty), (centre[0] + tx, centre[1] + ty), rpm=150)
        assert drawn_points(client, 14, centre) == []
