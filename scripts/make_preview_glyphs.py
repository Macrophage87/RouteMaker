#!/usr/bin/env python3
"""Write src/core/preview_glyphs.py: the letters the link preview image draws (core.share_preview).

The server draws the preview with the standard library only (no imaging package is a dependency),
so its text is a table of glyph coverage made here once, from the page's own bold face
(frontend/src/fonts/atkinson-hyperlegible-bold.woff2, SIL Open Font License, frontend/src/fonts/
OFL.txt). Needs Pillow, on the developer's machine only:

    python3 scripts/make_preview_glyphs.py && ruff format src/core/preview_glyphs.py
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
OUT = REPO / "src" / "core" / "preview_glyphs.py"
SIZE = 34
CHARS = "".join(chr(c) for c in range(32, 127)) + "·"


def main() -> None:
    font = ImageFont.truetype(str(FONT), SIZE)
    ascent, descent = font.getmetrics()
    height = ascent + descent
    table = {}
    data = bytearray()
    for ch in CHARS:
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
    OUT.write_text(
        '"""Glyph coverage for the link preview image (core.share_preview), written by\n'
        "scripts/make_preview_glyphs.py from frontend/src/fonts/atkinson-hyperlegible-bold.woff2\n"
        '(SIL Open Font License: frontend/src/fonts/OFL.txt). Do not edit by hand."""\n\n'
        f"SIZE = {SIZE}\nHEIGHT = {height}\nASCENT = {ascent}\n"
        "# char: (advance, left offset, width, offset into the coverage bytes); each glyph is\n"
        "# width x HEIGHT bytes of coverage, 0 to 255, row by row.\n"
        f"GLYPHS = {{\n{rows}\n}}\nDATA = (\n{body}\n)\n"
    )


if __name__ == "__main__":
    main()
