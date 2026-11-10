"""The base map behind the connector's route view (mcp/route_view.html; the owner, 2026-11-10: "Is
it possible for the MCP server to return a map and the various relevant graphs?").

The view draws the route itself, over this picture of the app's own base map: the one the link
preview draws (core.preview_basemap), of the box the view asks for. It is drawn from the box alone,
in memory, for one answer: nothing about the route reaches this module, and nothing it draws is
written or cached (the privacy rule: nothing identifying stays on the server).
"""

from __future__ import annotations

import struct
import zlib

from . import preview_basemap

# The colour under the base map where it has no tile (the link preview's background).
BACKGROUND = (238, 242, 236)


def png(px: bytes, width: int, height: int) -> bytes:
    """RGB rows of `width` as a PNG."""
    stride = width * 3
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw += px[y * stride : (y + 1) * stride]

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + chunk(b"IEND", b"")
    )


def draw(
    centre: tuple[float, float], scale: float, width: int, height: int
) -> tuple[bytes, list] | None:
    """The base map of the view centred on `centre` (lon, lat) at `scale` pixels across the
    world, `width` by `height` pixels: (PNG, town names as (x, y, name)), or None when there is
    no base map for it (no archive, too many tiles, a broken tile)."""
    px = bytearray(bytes(BACKGROUND) * (width * height))
    places = preview_basemap.paint(px, width, height, preview_basemap.world_xy(*centre), scale)
    if places is None:
        return None
    return png(bytes(px), width, height), places
