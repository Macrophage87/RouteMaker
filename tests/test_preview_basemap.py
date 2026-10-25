"""The base map behind the link preview's route (core.preview_basemap): reading a PMTiles archive
of vector tiles, and drawing it under the line with the credits it owes."""

from __future__ import annotations

import gzip
import struct
import time
import zlib

import pytest

from core import preview_basemap, share_preview

# ---- A tiny archive, written here: one tile of zoom 0 holding the world ----


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _field(number: int, payload: bytes) -> bytes:
    return _varint(number << 3 | 2) + _varint(len(payload)) + payload


def _uint(number: int, value: int) -> bytes:
    return _varint(number << 3) + _varint(value)


def _zig(n: int) -> int:
    return (n << 1) ^ (n >> 31)


def _commands(parts, closed: bool) -> list[int]:
    out, x, y = [], 0, 0
    for part in parts:
        pts = part[:-1] if closed else part
        out += [1 | 1 << 3, _zig(pts[0][0] - x), _zig(pts[0][1] - y)]
        x, y = pts[0]
        out.append(2 | (len(pts) - 1) << 3)
        for px, py in pts[1:]:
            out += [_zig(px - x), _zig(py - y)]
            x, y = px, py
        if closed:
            out.append(7 | 1 << 3)
    return out


def _layer(name: str, features: list[tuple[int, dict, list]]) -> bytes:
    keys: list[str] = []
    values: list[str] = []
    body = b""
    for kind, props, parts in features:
        tags = []
        for k, v in props.items():
            if k not in keys:
                keys.append(k)
            if v not in values:
                values.append(v)
            tags += [keys.index(k), values.index(v)]
        geometry = _commands(parts, closed=kind == 3)
        body += _field(
            2,
            _field(2, b"".join(_varint(t) for t in tags))
            + _uint(3, kind)
            + _field(4, b"".join(_varint(c) for c in geometry)),
        )
    return _field(
        3,
        _uint(15, 2)
        + _field(1, name.encode())
        + body
        + b"".join(_field(3, k.encode()) for k in keys)
        + b"".join(_field(4, _field(1, v.encode())) for v in values)
        + _uint(5, EXTENT),
    )


# One tile holds the world, so its grid is made fine enough for a few streets.
EXTENT = 1 << 28


def _world_px(lon: float, lat: float) -> tuple[int, int]:
    x, y = preview_basemap.world_xy(lon, lat)
    return round(x * EXTENT), round(y * EXTENT)


def write_archive(path, tile: bytes) -> None:
    """A PMTiles v3 archive of one gzipped tile at zoom 0, its directory gzipped too."""
    data = gzip.compress(tile)
    directory = gzip.compress(
        _varint(1) + _varint(0) + _varint(1) + _varint(len(data)) + _varint(1)
    )
    root_offset = 127
    data_offset = root_offset + len(directory)
    header = (
        b"PMTiles"
        + bytes([3])
        + struct.pack(
            "<11Q",
            root_offset,
            len(directory),
            data_offset,
            0,
            data_offset,
            0,
            data_offset,
            len(data),
            1,
            1,
            1,
        )
    )
    header += bytes([1, 2, 2, 1, 0, 0]) + b"\0" * (127 - len(header) - 6)
    assert len(header) == 127
    path.write_bytes(header + directory + data)


# A lake east of the line, a road across it, and a town.
LINE = [(-77.05 + i * 0.002, 38.9) for i in range(20)]
LAKE = [
    (-77.035, 38.906),
    (-77.025, 38.906),
    (-77.025, 38.902),
    (-77.035, 38.902),
    (-77.035, 38.906),
]
ROAD = [(-77.05, 38.895), (-76.98, 38.895)]
TOWN = (-77.045, 38.905)


def _tile() -> bytes:
    lake = [[_world_px(*p) for p in LAKE]]
    road = [[_world_px(*p) for p in ROAD]]
    return (
        _layer("water", [(3, {"kind": "lake"}, lake)])
        + _layer("roads", [(2, {"kind": "highway"}, road)])
        + _layer("places", [(1, {"kind": "locality", "name": "Testville"}, [[_world_px(*TOWN)]])])
        + _layer("buildings", [(3, {"kind": "building"}, lake)])
    )


@pytest.fixture
def basemap(tmp_path, settings):
    path = tmp_path / "region.pmtiles"
    write_archive(path, _tile())
    settings.BASEMAP_PMTILES = path
    preview_basemap._archive.cache_clear()
    yield path
    preview_basemap._archive.cache_clear()


def _pixels(png: bytes) -> bytes:
    raw = zlib.decompress(png[png.index(b"IDAT") + 4 : png.index(b"IEND") - 8])
    stride = share_preview.WIDTH * 3 + 1
    return b"".join(raw[y * stride + 1 : (y + 1) * stride] for y in range(share_preview.HEIGHT))


def _at(px: bytes, x: float, y: float) -> tuple[int, int, int]:
    i = (int(y) * share_preview.WIDTH + int(x)) * 3
    return tuple(px[i : i + 3])


def test_tile_ids_follow_the_hilbert_curve_of_the_specification() -> None:
    # The PMTiles v3 specification's own examples.
    assert preview_basemap.tile_id(0, 0, 0) == 0
    assert preview_basemap.tile_id(1, 0, 0) == 1
    assert preview_basemap.tile_id(1, 0, 1) == 2
    assert preview_basemap.tile_id(1, 1, 1) == 3
    assert preview_basemap.tile_id(1, 1, 0) == 4
    assert preview_basemap.tile_id(2, 0, 0) == 5
    assert preview_basemap.tile_id(12, 3423, 1763) == 19078479


def test_the_archive_gives_its_tile_and_its_wanted_layers(basemap) -> None:
    arc = preview_basemap.archive()
    assert arc is not None and arc.max_zoom == 0
    assert arc.tile(0, 0, 0) == _tile()
    assert arc.tile(1, 0, 0) is None
    found = preview_basemap.layers(arc.tile(0, 0, 0))
    # Buildings are never drawn, so never decoded.
    assert set(found) == {"water", "roads", "places"}
    kind, props, parts = found["roads"][0]
    assert kind == 2 and props == {"kind": "highway"} and len(parts[0]) == 2
    kind, _props, parts = found["water"][0]
    assert kind == 3 and parts[0][0] == parts[0][-1]


def test_the_preview_draws_the_base_map_under_the_line_with_its_credits(basemap) -> None:
    drawn = share_preview.drawn_route(LINE, [LINE[0], LINE[-1]], None)
    png = share_preview.render_png(drawn, "1.0 mi (1.6 km)")
    px = _pixels(png)
    _centre, _scale, at = share_preview.view(drawn)
    # Land where nothing else is, the lake's water, the road's white, the line's blue over all.
    lake_x, lake_y = at((-77.03, 38.904))
    assert _at(px, lake_x, lake_y) == preview_basemap.WATER
    road_x, road_y = at((-77.045, 38.895))
    assert _at(px, road_x, road_y) == preview_basemap.ROAD
    land_x, land_y = at((-77.015, 38.898))
    assert _at(px, land_x, land_y) == preview_basemap.EARTH
    line_x, line_y = at(LINE[10])
    assert _at(px, line_x, line_y) == share_preview.LINE_COLOUR
    # The credit, dark text on its pale box, at the map's foot on the right.
    from core import preview_glyphs_small as small

    credit_w = share_preview.text_width(preview_basemap.CREDIT, small)
    row = share_preview.MAP_H - 6 - small.HEIGHT + 3 + small.ASCENT - 6
    dark = [
        x
        for x in range(share_preview.WIDTH - credit_w - 8, share_preview.WIDTH - 8)
        if sum(_at(px, x, row)) < 300
    ]
    assert len(dark) > 20
    assert "©" in preview_basemap.CREDIT and "OpenStreetMap" in preview_basemap.CREDIT
    assert "Protomaps" in preview_basemap.CREDIT


def test_without_a_base_map_the_preview_is_on_the_plain_background(tmp_path, settings) -> None:
    settings.BASEMAP_PMTILES = tmp_path / "none.pmtiles"
    assert preview_basemap.stamp() == "" and preview_basemap.archive() is None
    drawn = share_preview.drawn_route(LINE, [], None)
    px = _pixels(share_preview.render_png(drawn, "x"))
    assert _at(px, 5, 5) == share_preview.BACKGROUND
    # A file that is no archive is the same.
    bad = tmp_path / "bad.pmtiles"
    bad.write_bytes(b"not a map" * 40)
    settings.BASEMAP_PMTILES = bad
    preview_basemap._archive.cache_clear()
    px = _pixels(share_preview.render_png(drawn, "x"))
    assert _at(px, 5, 5) == share_preview.BACKGROUND


def test_a_new_base_map_draws_the_pictures_again(basemap) -> None:
    before = preview_basemap.stamp()
    assert before
    write_archive(basemap, _tile() + _layer("landuse", []))
    assert preview_basemap.stamp() != before


def test_homes_circle_hides_the_base_map_too(basemap) -> None:
    home = LINE[0]
    zone = share_preview.home_zone(home, (0.0, 0.0))
    drawn = share_preview.drawn_route(LINE, [LINE[0], LINE[-1]], zone)
    assert drawn is not None and drawn["zone"] == zone
    px = _pixels(share_preview.render_png(drawn, "x"))
    _centre, scale, at = share_preview.view(drawn)
    cx, cy = at(zone[0])
    r = share_preview.zone_radius_px(zone, scale)
    inside = 0
    for y in range(int(cy - r), int(cy + r) + 1):
        for x in range(int(cx - r), int(cx + r) + 1):
            if 0 <= x < share_preview.WIDTH and 0 <= y < share_preview.MAP_H:
                if (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2 <= r * r:
                    inside += 1
                    assert _at(px, x, y) == share_preview.BACKGROUND
    assert inside > 100


def test_a_long_route_over_the_base_map_is_drawn_in_bounded_time(basemap) -> None:
    long = [(-77.3 + i * 0.00003, 38.8 + 0.01 * (i % 7)) for i in range(20_000)]
    started = time.monotonic()
    png = share_preview.render_png(share_preview.drawn_route(long, [], None), "x")
    assert png is not None and time.monotonic() - started < 5
