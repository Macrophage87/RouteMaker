#!/usr/bin/env python3
"""Draw the app's icon where a link preview shows it (core.share_preview; the owner, 2026-10-20:
"Is there a way to have the icon when shared?"):

- frontend/public/icons/share-card.png, 1200 x 630: the preview image of the app's own address
  (core.share_preview.site_page): the icon, "RouteMaker" and what it does.
- src/core/preview_icon.py: the icon at ICON px as RGBA, which a shared route's preview image
  draws beside "RouteMaker" (core.share_preview.render_png).

Both are made from frontend/public/icons/icon-512.png (scripts/make_app_icons.py) and the page's
own faces (frontend/src/fonts, SIL Open Font License, frontend/src/fonts/OFL.txt). Run by hand
when the icon changes; what it writes is committed. Needs Pillow, on the developer's machine only:

    python3 scripts/make_share_images.py && ruff format src/core/preview_icon.py
"""

from __future__ import annotations

import base64
import textwrap
import zlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[1]
ICON_PNG = REPO / "frontend" / "public" / "icons" / "icon-512.png"
FONTS = REPO / "frontend" / "src" / "fonts"
CARD = REPO / "frontend" / "public" / "icons" / "share-card.png"
MODULE = REPO / "src" / "core" / "preview_icon.py"
# The icon in a shared route's preview: a little taller than the band's text (preview_glyphs).
ICON = 56
WIDTH, HEIGHT = 1200, 630
BACKGROUND = (255, 255, 255)
TEXT = (31, 41, 51)
QUIET = (75, 85, 99)
TAGLINE = ("Bike route planning tool", "around Washington, DC and Baltimore")


def card(icon: Image.Image) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    side = 400
    top = (HEIGHT - side) // 2
    image.paste(icon.resize((side, side), Image.LANCZOS), (80, top), icon.resize((side, side)))
    draw = ImageDraw.Draw(image)
    bold = ImageFont.truetype(str(FONTS / "atkinson-hyperlegible-bold.woff2"), 104)
    regular = ImageFont.truetype(str(FONTS / "atkinson-hyperlegible-regular.woff2"), 38)
    x = 80 + side + 56
    draw.text((x, top + 40), "RouteMaker", font=bold, fill=TEXT)
    for i, line in enumerate(TAGLINE):
        draw.text((x, top + 210 + i * 54), line, font=regular, fill=QUIET)
    return image


def module(icon: Image.Image) -> str:
    small = icon.resize((ICON, ICON), Image.LANCZOS)
    data = base64.b64encode(zlib.compress(small.tobytes(), 9)).decode()
    lines = "\n".join(f'    "{chunk}"' for chunk in textwrap.wrap(data, 88))
    return (
        '"""The app\'s icon for the link preview image (core.share_preview), written by\n'
        "scripts/make_share_images.py from frontend/public/icons/icon-512.png. Do not edit by "
        'hand."""\n\n'
        f"SIZE = {ICON}\n"
        "# SIZE x SIZE pixels of RGBA, row by row, zlib-compressed and base64-encoded.\n"
        f"DATA = (\n{lines}\n)\n"
    )


def main() -> None:
    icon = Image.open(ICON_PNG).convert("RGBA")
    card(icon).save(CARD, optimize=True)
    MODULE.write_text(module(icon))
    for out in (CARD, MODULE):
        print(f"{out.relative_to(REPO)}  {out.stat().st_size} bytes")


if __name__ == "__main__":
    main()
