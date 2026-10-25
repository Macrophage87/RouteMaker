"""Draw the installable app's icons and the Android app's icons and splash screens from the
favicon (OWNER-DECISIONS 465b; WEB-NAV-plan.md section 8, "Manifest"; the owner's new icon,
2026-10-18: the route line running into a bicycle with a map pin in the front wheel).

    python3 scripts/make_app_icons.py /path/to/chrome-headless-shell

Run once, by hand, when frontend/public/favicon.svg changes; everything it writes is
committed (OWNER-DECISIONS 436: no npm package for this, and nothing drawn at build time).
It needs Chromium's headless shell (`chrome-headless-shell`, or Playwright's
`headless_shell`) and nothing else: each PNG is a small page holding the favicon's own
drawing, screenshotted at the icon's size with a transparent background. (A full Chrome's
`--headless=new` screenshot is the window, not the page, and cuts the bottom off; the size
check below refuses nothing in that case, so look at the PNGs.)

The favicon is a background square (its first `<rect>`) and, after it, the drawing. Its
`<style>` thickens the strokes when it is drawn 40 px or smaller (a browser tab), where the
full-size lines would blur; every icon drawn here is larger, so none of them uses it.

Web, under frontend/public/icons/:
- icon-192.png, icon-512.png ("any"): the favicon as it is, rounded corners and all.
- icon-maskable-192.png, icon-maskable-512.png ("maskable"): the favicon's blue edge to
  edge, the drawing scaled to MASKABLE of the side, so a launcher's circle (which keeps the
  middle 80 %) never cuts it.
- apple-touch-icon.png (180): full bleed like the maskable one (iOS rounds the corners
  itself and fills any transparency with black), the drawing a little larger.

And frontend/public/favicon.ico: the favicon at 16, 32 and 48 px (its thick strokes), each a PNG
inside the .ico. Google's favicon service, which is where claude.ai's connector list gets a
connector's icon, looks for a raster favicon at the domain's root.

Android, under mobile/android/app/src/main/res/:
- drawable/ic_launcher_foreground.xml: the drawing as a vector, white on transparent,
  scaled to ADAPTIVE of the 108 dp canvas so it stays inside the 66 dp safe circle. The
  adaptive icon (mipmap-anydpi-v26) uses it as its foreground and as its monochrome layer
  (Android 13 themed icons tint its shape).
- values/ic_launcher_background.xml: the favicon's blue, the adaptive icon's background.
- mipmap-*/ic_launcher.png and ic_launcher_round.png: the launcher icons for Android 7
  (before adaptive icons), the favicon as it is and a blue circle.
- drawable*/splash.png: the launch screen, the drawing on the favicon's blue, each at the
  size the one it replaces had.
"""

from __future__ import annotations

import re
import struct
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PUBLIC = REPO / "frontend" / "public"
FAVICON = PUBLIC / "favicon.svg"
OUT = PUBLIC / "icons"
RES = REPO / "mobile" / "android" / "app" / "src" / "main" / "res"

MASKABLE = 0.75  # the drawing reaches 42 % of its side from the centre: 32 % here, inside 40 %
APPLE = 0.85
ADAPTIVE = 0.70  # 32 dp from the centre on the 108 dp canvas, inside the 33 dp safe circle
ROUND = 0.75
SPLASH = 0.4  # of the screen's shorter side
DENSITIES = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}
SVG_NS = "http://www.w3.org/2000/svg"


def side(svg: str) -> float:
    return float(re.search(r'viewBox="0 0 ([\d.]+) [\d.]+"', svg).group(1))


def glyph(svg: str) -> str:
    """The favicon's drawing without its background square."""
    inner = re.search(r"<svg[^>]*>(.*)</svg>", svg, re.S).group(1)
    return re.sub(r"<rect[^>]*/>", "", inner, count=1)


def background(svg: str) -> str:
    return re.search(r'<rect[^>]*fill="(#[0-9a-fA-F]{3,6})"', svg).group(1)


def placed(svg: str, width: float, height: float, share: float, shape: str = "square") -> str:
    """The drawing at `share` of the shorter side, centred on a `width` x `height` field of
    the favicon's blue (`shape` "circle" for a round icon, "none" for no background)."""
    n = side(svg)
    scale = share * min(width, height) / n
    dx, dy = (width - n * scale) / 2, (height - n * scale) / 2
    blue, r = background(svg), min(width, height) / 2
    field = {
        "square": f'<rect width="{width}" height="{height}" fill="{blue}"/>',
        "circle": f'<circle cx="{width / 2}" cy="{height / 2}" r="{r}" fill="{blue}"/>',
        "none": "",
    }[shape]
    return (
        f'<svg xmlns="{SVG_NS}" viewBox="0 0 {width} {height}">{field}'
        f'<g transform="translate({dx:.3f} {dy:.3f}) scale({scale:.5f})">{glyph(svg)}</g></svg>'
    )


def render(chrome: str, svg: str, width: int, height: int, out: Path) -> None:
    with tempfile.TemporaryDirectory() as work:
        page = Path(work) / "icon.html"
        page.write_text(
            "<!doctype html><html><head><style>html,body{margin:0;background:transparent}"
            f"svg{{display:block;width:{width}px;height:{height}px}}</style></head><body>{svg}</body></html>"
        )
        subprocess.run(
            [
                chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                f"--user-data-dir={work}/profile", "--default-background-color=00000000",
                f"--window-size={width},{height}", f"--screenshot={out}", page.as_uri(),
            ],
            check=True, capture_output=True, stdin=subprocess.DEVNULL, timeout=120,
        )  # fmt: skip
    head = out.read_bytes()[:24]
    got = struct.unpack(">II", head[16:24])
    if head[:8] != b"\x89PNG\r\n\x1a\n" or got != (width, height):
        raise SystemExit(f"{out}: expected a {width}x{height} PNG, got {got[0]}x{got[1]}")


ICO_SIZES = (16, 32, 48)


def ico(pngs: list[bytes]) -> bytes:
    """An .ico holding each PNG as it is (Windows Vista's PNG frames, which every browser reads)."""
    head = struct.pack("<HHH", 0, 1, len(pngs))
    offset = len(head) + 16 * len(pngs)
    entries, data = b"", b""
    for png in pngs:
        width, height = struct.unpack(">II", png[16:24])
        entries += struct.pack(
            "<BBBBHHII", width % 256, height % 256, 0, 0, 1, 32, len(png), offset + len(data)
        )
        data += png
    return head + entries + data


def vector(svg: str) -> str:
    """The drawing as an Android vector drawable on the 108 dp adaptive-icon canvas.

    Handles what the favicon uses: `<g>`s with a translate and inherited presentation
    attributes, and `<path>`s with a stroke or a fill."""
    n = side(svg)
    root = ET.fromstring(svg)
    scale = ADAPTIVE * 108 / n
    offset = 54 - n / 2 * scale
    paths = []

    def walk(node: ET.Element, inherited: dict[str, str], tx: float, ty: float) -> None:
        for child in node:
            tag = child.tag.removeprefix(f"{{{SVG_NS}}}")
            attrs = {**inherited, **child.attrib}
            if tag == "g":
                move = re.fullmatch(
                    r"translate\(([-\d.]+)[ ,]+([-\d.]+)\)",
                    child.get("transform", "translate(0 0)"),
                )
                if not move:
                    raise SystemExit(
                        f"favicon: a <g> may only translate(), not {child.get('transform')}"
                    )
                attrs.pop("transform", None)
                walk(child, attrs, tx + float(move[1]), ty + float(move[2]))
            elif tag == "path":
                paths.append((attrs, tx, ty))
            elif tag == "style":
                pass  # the favicon's heavier strokes for a browser tab; not drawn here
            elif tag != "rect" or node is not root:
                raise SystemExit(
                    f"favicon: only <g> and <path> are handled in the drawing, not <{tag}>"
                )

    walk(root, {}, 0.0, 0.0)
    lines = []
    for attrs, tx, ty in paths:
        props = [f'android:pathData="{attrs["d"]}"']
        if attrs.get("fill", "black") != "none":
            props.append(f'android:fillColor="{colour(attrs["fill"])}"')
            if attrs.get("fill-rule") == "evenodd":
                props.append('android:fillType="evenOdd"')
        if attrs.get("stroke", "none") != "none":
            props += [
                f'android:strokeColor="{colour(attrs["stroke"])}"',
                f'android:strokeWidth="{attrs.get("stroke-width", "1")}"',
                f'android:strokeLineCap="{attrs.get("stroke-linecap", "butt")}"',
                f'android:strokeLineJoin="{attrs.get("stroke-linejoin", "miter")}"',
            ]
        x, y = tx * scale + offset, ty * scale + offset
        lines.append(
            f'    <group android:scaleX="{scale:.5f}" android:scaleY="{scale:.5f}"'
            f' android:translateX="{x:.4f}" android:translateY="{y:.4f}">\n'
            f"        <path\n            " + "\n            ".join(props) + " />\n    </group>"
        )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<!-- Drawn by scripts/make_app_icons.py from frontend/public/favicon.svg;"
        " edit the favicon, not this. -->\n"
        '<vector xmlns:android="http://schemas.android.com/apk/res/android"\n'
        '    android:width="108dp"\n    android:height="108dp"\n'
        '    android:viewportWidth="108"\n    android:viewportHeight="108">\n'
        + "\n".join(lines)
        + "\n</vector>\n"
    )


def colour(value: str) -> str:
    named = {"#fff": "#FFFFFF", "white": "#FFFFFF"}
    return named.get(value.lower(), value.upper())


def adaptive_icon() -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
        '    <background android:drawable="@color/ic_launcher_background"/>\n'
        '    <foreground android:drawable="@drawable/ic_launcher_foreground"/>\n'
        '    <monochrome android:drawable="@drawable/ic_launcher_foreground"/>\n'
        "</adaptive-icon>\n"
    )


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    chrome = sys.argv[1]
    svg = FAVICON.read_text()
    made: list[Path] = []

    def draw(picture: str, width: int, height: int, out: Path) -> None:
        render(chrome, picture, width, height, out)
        made.append(out)

    def write(out: Path, text: str) -> None:
        out.write_text(text)
        made.append(out)

    OUT.mkdir(exist_ok=True)
    for size in (192, 512):
        draw(svg, size, size, OUT / f"icon-{size}.png")
        draw(placed(svg, size, size, MASKABLE), size, size, OUT / f"icon-maskable-{size}.png")
    draw(placed(svg, 180, 180, APPLE), 180, 180, OUT / "apple-touch-icon.png")
    with tempfile.TemporaryDirectory() as work:
        frames = []
        for size in ICO_SIZES:
            render(chrome, svg, size, size, Path(work) / f"{size}.png")
            frames.append((Path(work) / f"{size}.png").read_bytes())
    (PUBLIC / "favicon.ico").write_bytes(ico(frames))
    made.append(PUBLIC / "favicon.ico")

    write(RES / "drawable" / "ic_launcher_foreground.xml", vector(svg))
    write(
        RES / "values" / "ic_launcher_background.xml",
        '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
        f'    <color name="ic_launcher_background">{background(svg).upper()}</color>\n'
        "</resources>\n",
    )
    for name in ("ic_launcher", "ic_launcher_round"):
        write(RES / "mipmap-anydpi-v26" / f"{name}.xml", adaptive_icon())
    for density, size in DENSITIES.items():
        draw(svg, size, size, RES / f"mipmap-{density}" / "ic_launcher.png")
        draw(
            placed(svg, size, size, ROUND, "circle"),
            size,
            size,
            RES / f"mipmap-{density}" / "ic_launcher_round.png",
        )
    for splash in sorted(RES.glob("drawable*/splash.png")):
        head = splash.read_bytes()[:24]
        width, height = struct.unpack(">II", head[16:24])
        draw(placed(svg, width, height, SPLASH), width, height, splash)

    for out in made:
        print(f"{out.relative_to(REPO)}  {out.stat().st_size} bytes")


if __name__ == "__main__":
    main()
