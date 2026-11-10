#!/usr/bin/env python3
"""Write src/core/preview_glyphs.py: the letters the link preview image draws (core.share_preview).

The server draws the preview with the standard library only (no imaging package is a dependency),
so its text is a table of glyph coverage made here once, from the page's own bold face
(frontend/src/fonts/atkinson-hyperlegible-bold.woff2, SIL Open Font License, frontend/src/fonts/
OFL.txt). Needs Pillow, on the developer's machine only:

    python3 scripts/make_preview_glyphs.py && ruff format src/core/preview_glyphs*.py
"""

from __future__ import annotations

import base64
import json
import textwrap
import zlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[1]
FONT = REPO / "frontend" / "src" / "fonts" / "atkinson-hyperlegible-bold.woff2"
CHARS = "".join(chr(c) for c in range(32, 127)) + "·"
# Each table: its module, its size, its letters. The small one draws the base map's place names and
# credits (core.preview_basemap), so it has the copyright sign too.
REGULAR = REPO / "frontend" / "src" / "fonts" / "atkinson-hyperlegible-regular.woff2"
TABLES = (
    (REPO / "src" / "core" / "preview_glyphs.py", 34, CHARS, FONT),
    (REPO / "src" / "core" / "preview_glyphs_small.py", 18, CHARS + "©", FONT),
    # The phone cue images (core.cue_cards): the miles large, the turn, the road, the small words.
    (REPO / "src" / "core" / "cue_glyphs_miles.py", 88, "0123456789.,", FONT),
    (REPO / "src" / "core" / "cue_glyphs_turn.py", 60, CHARS, FONT),
    (REPO / "src" / "core" / "cue_glyphs_road.py", 52, CHARS, REGULAR),
    (REPO / "src" / "core" / "cue_glyphs_small.py", 30, CHARS + "©", REGULAR),
    (REPO / "src" / "core" / "cue_glyphs_head.py", 36, CHARS, FONT),
)


def main() -> None:
    for out, size, chars, face in TABLES:
        write(out, size, chars, face)


def write(out: Path, size: int, chars: str, face: Path = FONT) -> None:
    font = ImageFont.truetype(str(face), size)
    ascent, descent = font.getmetrics()
    height = ascent + descent
    table = {}
    data = bytearray()
    for ch in chars:
        advance = round(font.getlength(ch))
        left, _top, right, _bottom = font.getbbox(ch)
        left = min(left, 0)
        width = max(right - left, 1)
        image = Image.new("L", (width, height), 0)
        ImageDraw.Draw(image).text((-left, 0), ch, font=font, fill=255)
        table[ch] = (advance, left, width, len(data))
        data += image.tobytes()
    packed = base64.b64encode(zlib.compress(bytes(data), 9)).decode()
    rows = "\n".join(f"    {json.dumps(ch, ensure_ascii=False)}: {v!r}," for ch, v in table.items())
    body = "\n".join(f'    "{line}"' for line in textwrap.wrap(packed, 92))
    out.write_text(
        '"""Glyph coverage for the link preview image (core.share_preview), written by\n'
        f"scripts/make_preview_glyphs.py from frontend/src/fonts/{face.name}\n"
        '(SIL Open Font License: frontend/src/fonts/OFL.txt). Do not edit by hand."""\n\n'
        f"SIZE = {size}\nHEIGHT = {height}\nASCENT = {ascent}\n"
        "# char: (advance, left offset, width, offset into the coverage bytes); each glyph is\n"
        "# width x HEIGHT bytes of coverage, 0 to 255, row by row.\n"
        f"GLYPHS = {{\n{rows}\n}}\nDATA = (\n{body}\n)\n"
    )


if __name__ == "__main__":
    main()
