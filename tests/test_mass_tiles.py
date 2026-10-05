"""GET /tiles/mass/{z}/{x}/{y}.pbf: the Mass Ride map's own tiles (OWNER-DECISIONS 415, 417, 418).

Against a real live segment table, as tests/test_stress_tiles.py, decoded with `tests/mvt.py`.
What is held here: every road with a capacity at z12-13 (busy ones too, where the stress tiles
are the ride layer), no trail, nothing outside the District (each line clipped to its
boundary), the cache shared with the stress tiles without either evicting the other, and the
pre-draw drawing the District's tiles.
"""

from __future__ import annotations

import math

import pytest
from django.db import connection
from django.test import override_settings
from mvt import decode
from shapely.geometry import Point, shape

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


def road(schema, way, start, end, tier=3, rpm=150.0, trail=False, facility="none") -> None:
    width = None if rpm is None else rpm / flow.level_riders_per_min(1.0)
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {schema}.segment (osm_way_id, ordinal, geometry, stress_tier, "
            "stress_rule, is_trail_class, facility, mass_usable_width_m, calm_run_m) VALUES "
            "(%s, 0, ST_MakeLine(ST_MakePoint(%s, %s), ST_MakePoint(%s, %s)), %s, 'x', %s, %s, "
            "%s, 0)",
            [way, *start, *end, tier, trail, facility, width],
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
        road(live, 1, WHITE_HOUSE, east_of(WHITE_HOUSE), tier=2, rpm=90)
        for z in range(mass_tiles.MIN_ZOOM, mass_tiles.MAX_ZOOM + 1):
            assert [f.properties["rpm"] for f in features(client, z).features] == [90], z
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
