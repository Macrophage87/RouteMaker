"""Draw the installable app's icons from the favicon (OWNER-DECISIONS 465b: "default
for now"; WEB-NAV-plan.md section 8, "Manifest").

    python3 scripts/make_app_icons.py /path/to/chrome-headless-shell

Run once, by hand, when frontend/public/favicon.svg changes; the PNGs it writes
under frontend/public/icons/ are committed (OWNER-DECISIONS 436: no npm package
for this, and nothing drawn at build time). It needs Chromium's headless shell
(`chrome-headless-shell`, or Playwright's `headless_shell`) and nothing else: each
icon is a small page holding the favicon's own SVG, screenshotted at the icon's
size with a transparent background. (A full Chrome's `--headless=new` screenshot
is the window, not the page, and cuts the bottom off; the size check below
refuses nothing in that case, so look at the PNGs.)

- icon-192.png, icon-512.png ("any"): the favicon as it is, rounded corners and all.
- icon-maskable-192.png, icon-maskable-512.png ("maskable"): the favicon's blue
  edge to edge, with the bicycle drawn inside the middle 60 %, so a launcher's
  circle or squircle (which may keep only the middle 80 %) never cuts it.
- apple-touch-icon.png (180): full bleed like the maskable one (iOS rounds the
  corners itself and fills any transparency with black), the bicycle a little
  larger.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PUBLIC = REPO / "frontend" / "public"
FAVICON = PUBLIC / "favicon.svg"
OUT = PUBLIC / "icons"


def glyph(svg: str) -> str:
    """The favicon's drawing without its background square."""
    inner = re.search(r"<svg[^>]*>(.*)</svg>", svg, re.S).group(1)
    return re.sub(r"<rect[^>]*/>", "", inner, count=1)


def background(svg: str) -> str:
    return re.search(r'<rect[^>]*fill="(#[0-9a-fA-F]{3,6})"', svg).group(1)


def full_bleed(svg: str, glyph_share: float) -> str:
    """A square of the favicon's blue with its drawing scaled to `glyph_share` of the side."""
    scale = glyph_share
    offset = 16 * (1 - scale)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        f'<rect width="32" height="32" fill="{background(svg)}"/>'
        f'<g transform="translate({offset:.3f} {offset:.3f}) scale({scale:.3f})">{glyph(svg)}</g>'
        "</svg>"
    )


def render(chrome: str, svg: str, size: int, out: Path) -> None:
    with tempfile.TemporaryDirectory() as work:
        page = Path(work) / "icon.html"
        page.write_text(
            "<!doctype html><html><head><style>html,body{margin:0;background:transparent}"
            f"svg{{display:block;width:{size}px;height:{size}px}}</style></head><body>{svg}</body></html>"
        )
        subprocess.run(
            [
                chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                f"--user-data-dir={work}/profile", "--default-background-color=00000000",
                f"--window-size={size},{size}", f"--screenshot={out}", page.as_uri(),
            ],
            check=True, capture_output=True, stdin=subprocess.DEVNULL, timeout=120,
        )  # fmt: skip
    head = out.read_bytes()[:24]
    width, height = int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
    if head[:8] != b"\x89PNG\r\n\x1a\n" or (width, height) != (size, size):
        raise SystemExit(f"{out.name}: expected a {size} px PNG, got {width}x{height}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    chrome = sys.argv[1]
    svg = FAVICON.read_text()
    OUT.mkdir(exist_ok=True)
    for size in (192, 512):
        render(chrome, svg, size, OUT / f"icon-{size}.png")
        render(chrome, full_bleed(svg, 0.6), size, OUT / f"icon-maskable-{size}.png")
    render(chrome, full_bleed(svg, 0.8), 180, OUT / "apple-touch-icon.png")
    for made in sorted(OUT.iterdir()):
        print(f"{made.relative_to(REPO)}  {made.stat().st_size} bytes")


if __name__ == "__main__":
    main()
