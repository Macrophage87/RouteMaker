"""A draft's map and graphs as one picture, to share (the owner, 2026-11-10: "Also allow for an
image if requested so it can be shared", of the connector's route view, mcp/route_view.html).

The picture is the view drawn flat: the route on the app's base map coloured by traffic stress,
with its start, stops, finish, stressful junctions and closures; the stress ribbon with trail and
bike lane rails, the elevation profile and, on a Mass Ride, the riders a minute the road carries
and the junctions needing corkers, on one mile axis; a key, the figures and the credits the base
map owes. It is drawn from the view's own data (mcp/routemaker_mcp.py `route_view`), with the
standard library only as the link preview is (core.share_preview), in memory for each ask:
nothing is written or cached (the privacy rule: nothing identifying stays on the server).
"""

from __future__ import annotations

import math

from . import preview_basemap, preview_glyphs, preview_glyphs_small, route_view_map
from .share_preview import _glyph_data, text_width

WIDTH = 1200
PAD = 40
MAP_MIN_H, MAP_MAX_H = 420, 760
BACKGROUND = (255, 255, 255)
MAP_BACKGROUND = (238, 242, 236)
INK = (31, 30, 28)
MUTED = (91, 88, 82)
RULE = (217, 213, 202)
WHITE = (255, 255, 255)
# The app's default palette and its half steps (frontend/src/stressStyle.js), as the view's.
LEVEL = {
    1: ("#9ed3ac", "#2f5d47"),
    1.5: ("#7bb98c", "#2f5d47"),
    2: ("#57a06c", "#1a2638"),
    2.5: ("#968c49", "#1a2638"),
    3: ("#bf730b", "#45290a"),
    3.5: ("#c54d14", "#ffffff"),
    4: ("#c80018", "#ffffff"),
    4.5: ("#670d16", "#ffffff"),
    5: ("#14040a", "#ee3b2c"),
}
UNKNOWN = ("#9ca3af", "#374151")
RAIL = {"path": "#4c1d95", "protected": "#a21caf", "lane": "#9370f0"}
RAIL_WORDS = {"path": "Trail or path", "protected": "Protected bike lane", "lane": "Painted lane"}
FLOW_BANDS = (
    (0, "#d7191c", "bottleneck"),
    (60, "#f28e2b", "tight"),
    (120, "#1a9850", "good"),
    (200, "#6a3d9a", "wide open"),
)
ELEV_FILL = (199, 210, 254)
ELEV_LINE = (55, 48, 163)
CORKER = (30, 58, 138)
START, FINISH, STOP = (21, 128, 61), (185, 28, 28), (37, 99, 235)
JUNCTION = {"very high": (220, 38, 38), "higher": (249, 115, 22)}
CLOSURE = {"closure": (220, 38, 38), "possible": (250, 204, 21)}
CREDIT = preview_basemap.CREDIT
EARTH_RADIUS_MI = 3958.8


def rgb(colour) -> tuple[int, int, int]:
    if isinstance(colour, tuple):
        return colour
    return tuple(int(colour[i : i + 2], 16) for i in (1, 3, 5))


def flow_band(riders: float) -> tuple:
    found = FLOW_BANDS[0]
    for band in FLOW_BANDS:
        if riders >= band[0]:
            found = band
    return found


class Canvas:
    """RGB pixels of any size, with the few shapes the picture needs."""

    def __init__(self, width: int, height: int, background=BACKGROUND) -> None:
        self.w, self.h = width, height
        self.px = bytearray(bytes(background) * (width * height))

    def blend(self, x: int, y: int, colour, alpha: float) -> None:
        if alpha <= 0 or not (0 <= x < self.w and 0 <= y < self.h):
            return
        i = (y * self.w + x) * 3
        if alpha >= 1:
            self.px[i : i + 3] = bytes(colour)
            return
        for k in range(3):
            self.px[i + k] = round(self.px[i + k] + (colour[k] - self.px[i + k]) * alpha)

    def rect(self, x0: float, y0: float, x1: float, y1: float, colour) -> None:
        colour = bytes(rgb(colour))
        xa, xb = max(0, round(x0)), min(self.w, max(round(x1), round(x0) + 1))
        for y in range(max(0, round(y0)), min(self.h, round(y1))):
            i = (y * self.w + xa) * 3
            self.px[i : i + 3 * (xb - xa)] = colour * (xb - xa)

    def disc(self, cx: float, cy: float, r: float, colour) -> None:
        colour = rgb(colour)
        for y in range(int(cy - r - 1), int(cy + r + 2)):
            for x in range(int(cx - r - 1), int(cx + r + 2)):
                d = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
                self.blend(x, y, colour, min(1.0, r + 0.5 - d))

    def text(self, x: float, baseline: float, words: str, colour=INK, small: bool = True) -> int:
        """`words` from `x` at `baseline`; the x it ends at."""
        g = preview_glyphs_small if small else preview_glyphs
        data = _glyph_data(g.__name__)
        colour = rgb(colour)
        x, top = round(x), round(baseline) - g.ASCENT
        for ch in words:
            advance, left, width, offset = g.GLYPHS.get(ch) or g.GLYPHS["?"]
            for row in range(g.HEIGHT):
                base = offset + row * width
                for col in range(width):
                    c = data[base + col]
                    if c:
                        self.blend(x + left + col, top + row, colour, c / 255)
            x += advance
        return x

    def centred(self, cx: float, baseline: float, words: str, colour=INK) -> None:
        self.text(cx - text_width(words, preview_glyphs_small) / 2, baseline, words, colour)

    def stroke(self, path: list[tuple[float, float]], radius: float, colour) -> None:
        """A round-capped line `radius` either side of `path`, antialiased."""
        colour = rgb(colour)
        cover: dict[int, float] = {}
        reach = radius + 1
        for (ax, ay), (bx, by) in zip(path, path[1:], strict=False):
            dx, dy = bx - ax, by - ay
            q = dx * dx + dy * dy
            for y in range(
                max(0, int(min(ay, by) - reach)), min(self.h, int(max(ay, by) + reach) + 1)
            ):
                py = y + 0.5
                for x in range(
                    max(0, int(min(ax, bx) - reach)), min(self.w, int(max(ax, bx) + reach) + 1)
                ):
                    px = x + 0.5
                    t = 0.0 if q == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / q))
                    c = radius + 0.5 - math.hypot(px - ax - dx * t, py - ay - dy * t)
                    if c > 0:
                        i = y * self.w + x
                        if c > cover.get(i, 0):
                            cover[i] = min(1.0, c)
        for i, c in cover.items():
            self.blend(i % self.w, i // self.w, colour, c)

    def png(self) -> bytes:
        return route_view_map.png(bytes(self.px), self.w, self.h)


def _miles(a, b) -> float:
    la, lb = math.radians(a[1]), math.radians(b[1])
    h = (
        math.sin((lb - la) / 2) ** 2
        + math.cos(la) * math.cos(lb) * math.sin(math.radians(b[0] - a[0]) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MI * math.asin(min(1.0, math.sqrt(h)))


def _along(line: list, total: float):
    """`at(mile)` on the line and `piece(a, b)`, the line's points between two miles, the
    line's own miles scaled to the route's."""
    cum = [0.0]
    for p, q in zip(line, line[1:], strict=False):
        cum.append(cum[-1] + _miles(p, q))
    k = total / cum[-1] if cum[-1] else 1.0
    cum = [c * k for c in cum]

    def at(mi: float):
        lo, hi = 0, len(cum) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if cum[mid] <= mi:
                lo = mid
            else:
                hi = mid
        span = cum[hi] - cum[lo]
        t = 0.0 if span <= 0 else min(1.0, max(0.0, (mi - cum[lo]) / span))
        a, b = line[lo], line[hi]
        return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))

    def piece(a: float, b: float) -> list:
        return [at(a), *[line[i] for i, c in enumerate(cum) if a < c < b], at(b)]

    return at, piece


# Corker marks closer than this, in pixels, are drawn as one with their corkers added up: two
# junctions a few yards apart are one place to stand for the marshals (our default).
GATHER_PX = 24


def _gathered(marks: list[tuple[float, float, int]]) -> list[tuple[float, float, int]]:
    """Marks (x, y, count) in route order, those within GATHER_PX of the last kept one joined."""
    out: list[list] = []
    for x, y, n in marks:
        if out and math.hypot(x - out[-1][0], y - out[-1][1]) < GATHER_PX:
            out[-1][2] += n
        else:
            out.append([x, y, n])
    return [(x, y, n) for x, y, n in out]


def draw(view: dict, line: list) -> bytes | None:
    """The picture of a draft, from its route view (`view`) and its line ([lon, lat] points):
    a PNG, or None where there is no line to draw."""
    if len(line) < 2:
        return None
    total = float(view.get("miles") or 0) or 1.0
    at, piece = _along(line, total)
    spans = view.get("spans") or [[0, total, None, None]]
    profile = view.get("profile") or []
    mass = view.get("mass") or None
    flow = (mass or {}).get("steps") or []
    corkers = (mass or {}).get("corkers")

    # The map's size: as tall as the route needs at the picture's width, within bounds.
    world = [preview_basemap.world_xy(p[0], p[1]) for p in line]
    xs, ys = [p[0] for p in world], [p[1] for p in world]
    span_x, span_y = max(xs) - min(xs) or 1e-9, max(ys) - min(ys) or 1e-9
    map_w = WIDTH - 2 * PAD
    inner = map_w - 2 * PAD
    map_h = round(min(MAP_MAX_H, max(MAP_MIN_H, inner * span_y / span_x + 2 * PAD)))
    scale = min(inner / span_x, (map_h - 2 * PAD) / span_y, 256 * 2**17)
    centre = ((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2)

    head_h = 96
    ribbon_h = 34
    elev_h = 150 if len(profile) > 1 else 0
    flow_h = 100 if flow else 0
    cork_h = 40 if corkers is not None else 0
    graph_h = ribbon_h + 30 + (elev_h + 30 if elev_h else 0) + (flow_h + 50 if flow_h else 0)
    graph_h += cork_h + 40
    key_h, foot_h = 76, 50
    height = head_h + map_h + 24 + graph_h + key_h + foot_h
    c = Canvas(WIDTH, height)

    # ---- Head ----
    c.text(PAD, 56, str(view.get("name") or "RouteMaker route")[:48], INK, small=False)
    figures = view.get("figures") or {}
    words = " · ".join(
        w
        for w in (
            figures.get("distance"),
            figures.get("time"),
            figures.get("climb") and f"{figures['climb']} climb",
        )
        if w
    )
    c.text(PAD, 86, words, MUTED)

    # ---- Map ----
    top = head_h

    def px(p):
        x, y = preview_basemap.world_xy(p[0], p[1])
        return (
            PAD + map_w / 2 + (x - centre[0]) * scale,
            top + map_h / 2 + (y - centre[1]) * scale,
        )

    tile = Canvas(map_w, map_h, MAP_BACKGROUND)
    places = preview_basemap.paint(tile.px, map_w, map_h, centre, scale)
    for y in range(map_h):
        i, j = y * map_w * 3, ((top + y) * WIDTH + PAD) * 3
        c.px[j : j + map_w * 3] = tile.px[i : i + map_w * 3]
    for place_x, place_y, name in places or []:
        w = text_width(name, preview_glyphs_small)
        x0 = PAD + place_x - w / 2
        # Only a name that fits: one cut off at the edge reads as a different name.
        if 16 < place_y < map_h - 30 and PAD + 4 < x0 and x0 + w < PAD + map_w - 4:
            for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
                c.text(x0 + dx, top + place_y + dy, name, WHITE)
            c.text(x0, top + place_y, name, MUTED)
    paths = [(s, [px(p) for p in piece(s[0], max(s[1], s[0] + total / 600))]) for s in spans]
    for s, path in paths:
        c.stroke(path, 7, LEVEL.get(s[2], UNKNOWN)[1])
    for s, path in paths:
        c.stroke(path, 4.5, LEVEL.get(s[2], UNKNOWN)[0])
    for j in view.get("junctions") or []:
        x, y = px(at(j["mi"]))
        c.disc(x, y, 9, INK)
        c.disc(x, y, 7, JUNCTION.get(j.get("level"), JUNCTION["higher"]))
    for row in view.get("closures") or []:
        x, y = px(at(row["mi"]))
        c.rect(x - 9, y - 9, x + 9, y + 9, INK)
        c.rect(x - 7, y - 7, x + 7, y + 7, CLOSURE.get(row.get("kind"), CLOSURE["possible"]))
        c.centred(x, y + 6, "!", WHITE if row.get("kind") == "closure" else INK)
    for x, y, count in _gathered(
        [(*px(at(r["mi"])), r.get("corkers") or 0) for r in corkers or []]
    ):
        c.disc(x, y, 11, WHITE)
        c.disc(x, y, 9, CORKER)
        c.centred(x, y + 6, str(count), WHITE)
    points = view.get("points") or []
    stops = [p for i, p in enumerate(points) if 0 < i < len(points) - 1 and not p.get("via")]
    for k, stop in enumerate(stops, 1):
        x, y = px(stop["lon_lat"])
        c.disc(x, y, 13, WHITE)
        c.disc(x, y, 11, STOP)
        c.centred(x, y + 6, str(k), WHITE)
    if points:
        first, last = points[0]["lon_lat"], points[-1]["lon_lat"]
        if len(points) > 1 and not view.get("loop") and _miles(first, last) >= 0.03:
            x, y = px(last)
            c.disc(x, y, 15, WHITE)
            c.disc(x, y, 13, FINISH)
            c.centred(x, y + 6, "B", WHITE)
        x, y = px(first)
        c.disc(x, y, 15, WHITE)
        c.disc(x, y, 13, START)
        c.centred(x, y + 6, "A", WHITE)
    if places is not None:
        w = text_width(CREDIT, preview_glyphs_small)
        c.rect(PAD + map_w - w - 16, top + map_h - 28, PAD + map_w, top + map_h, WHITE)
        c.text(PAD + map_w - w - 8, top + map_h - 8, CREDIT, MUTED)

    # ---- Graphs, on one mile axis ----
    left, right = PAD + 90, WIDTH - PAD

    def gx(mi: float) -> float:
        return left + (right - left) * mi / total

    y = top + map_h + 24 + 6
    c.text(PAD, y + 24, "LTS", MUTED)
    for s in spans:
        a, b = gx(s[0]), max(gx(s[1]), gx(s[0]) + 2)
        c.rect(a, y, b, y + ribbon_h, LEVEL.get(s[2], UNKNOWN)[0])
        rail = RAIL.get(s[3])
        if rail:
            c.rect(a, y - 5, b, y, rail)
            c.rect(a, y + ribbon_h, b, y + ribbon_h + 5, rail)
        if s[2] is not None and b - a > 30:
            c.centred((a + b) / 2, y + 24, str(s[2]), WHITE if s[2] >= 3.5 else INK)
    for j in view.get("junctions") or []:
        c.disc(gx(j["mi"]), y - 12, 6, JUNCTION.get(j.get("level"), JUNCTION["higher"]))
    y += ribbon_h + 30

    if elev_h:
        heights = [ft for _mi, ft in profile]
        lo, hi = min(heights), max(heights)
        step = next((s for s in (10, 20, 50, 100, 200, 250, 500, 1000) if (hi - lo) / s <= 3), 1000)
        lo = math.floor(lo / step) * step
        hi = max(lo + step, math.ceil(hi / step) * step)

        def ey(ft: float) -> float:
            return y + elev_h - (ft - lo) / (hi - lo) * elev_h

        k = 0
        for col in range(round(left), round(right)):
            mi = (col - left) / (right - left) * total
            while k < len(profile) - 2 and profile[k + 1][0] < mi:
                k += 1
            (m0, f0), (m1, f1) = profile[k], profile[min(k + 1, len(profile) - 1)]
            ft = f0 if m1 <= m0 else f0 + (f1 - f0) * min(1.0, max(0.0, (mi - m0) / (m1 - m0)))
            c.rect(col, ey(ft), col + 1, y + elev_h, ELEV_FILL)
            c.rect(col, ey(ft) - 1.5, col + 1, ey(ft) + 1.5, ELEV_LINE)
        ft = lo
        while ft <= hi + 0.5:
            c.rect(left, ey(ft), right, ey(ft) + 1, RULE)
            label = str(round(ft))
            c.text(left - 8 - text_width(label, preview_glyphs_small), ey(ft) + 6, label, MUTED)
            ft += step
        c.text(PAD, y + 12, "feet", MUTED)
        y += elev_h + 30

    if flow_h:
        y += 20  # room for the graph's name above it
        need = (mass or {}).get("need") or 0
        top_r = max(150, need, *(f[2] for f in flow))

        def fy(r: float) -> float:
            return y + flow_h - r / top_r * flow_h

        for a, b, r in flow:
            c.rect(gx(a), fy(r), max(gx(b), gx(a) + 1), y + flow_h, flow_band(r)[1])
        for r in (60, 120, 200):
            if r <= top_r:
                c.rect(left, fy(r), right, fy(r) + 1, RULE)
                c.text(
                    left - 8 - text_width(str(r), preview_glyphs_small), fy(r) + 6, str(r), MUTED
                )
        if need:
            for x0 in range(round(left), round(right), 12):
                c.rect(x0, fy(need) - 1, x0 + 7, fy(need) + 1, INK)
            label = f"need {round(need)}"
            w = text_width(label, preview_glyphs_small)
            c.rect(right - w - 8, fy(need) - 22, right, fy(need) - 3, WHITE)
            c.text(right - w - 4, fy(need) - 7, label, INK)
        c.text(PAD, y - 8, "riders a minute", MUTED)
        y += flow_h + 30

    if cork_h:
        c.text(PAD, y + 12, "Corkers", MUTED)
        c.rect(left, y + 5, right, y + 6, RULE)
        for x, _y, count in _gathered(
            [(gx(r["mi"]), 0, r.get("corkers") or 0) for r in corkers or []]
        ):
            c.disc(x, y + 5, 11, CORKER)
            c.centred(x, y + 11, str(count), WHITE)
        y += cork_h

    # The mile axis.
    c.rect(left, y, right, y + 1, MUTED)
    tick = next((s for s in (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 25, 50) if total / s <= 10), 50)
    m = 0.0
    while m <= total + 1e-9:
        c.rect(gx(m), y, gx(m) + 1, y + 6, MUTED)
        label = f"{m:.1f}" if tick < 1 else str(round(m))
        if m + tick > total + 1e-9:
            label += " mi"
        c.centred(gx(m), y + 26, label, MUTED)
        m += tick
    y += 40

    # ---- Key ----
    x, row_y = PAD, y

    def room(x: float, words: str) -> float:
        """Where the next key item starts: on a second row when this one would run off."""
        nonlocal row_y
        if x + 60 + text_width(words, preview_glyphs_small) > WIDTH - PAD:
            row_y += 34
            return PAD
        return x

    levels = sorted({s[2] for s in spans if s[2] is not None})
    for t in levels:
        words = "Avoid" if t == 5 else f"LTS {t}"
        x = room(x, words)
        c.rect(x, row_y + 4, x + 26, row_y + 26, LEVEL.get(t, UNKNOWN)[0])
        c.centred(x + 13, row_y + 21, str(t), WHITE if t >= 3.5 else INK)
        x = c.text(x + 32, row_y + 21, words, MUTED) + 18
    for facility in ("path", "protected", "lane"):
        if any(s[3] == facility for s in spans):
            x = room(x, RAIL_WORDS[facility])
            c.rect(x, row_y + 12, x + 24, row_y + 18, RAIL[facility])
            x = c.text(x + 30, row_y + 21, RAIL_WORDS[facility], MUTED) + 18
    if flow:
        for floor, colour, word in FLOW_BANDS:
            if any(flow_band(f[2])[0] == floor for f in flow):
                label = f"{word} ({floor}+ riders a minute)"
                x = room(x, label)
                c.rect(x, row_y + 8, x + 18, row_y + 24, colour)
                x = c.text(x + 24, row_y + 21, label, MUTED) + 16
    if corkers:
        label = "corkers needed"
        x = room(x, label)
        c.disc(x + 10, row_y + 15, 9, CORKER)
        x = c.text(x + 26, row_y + 21, label, MUTED) + 16
    y += key_h

    # ---- Foot ----
    c.rect(0, y, WIDTH, y + 1, RULE)
    c.text(PAD, y + 34, "Planned with RouteMaker", MUTED)
    return c.png()
