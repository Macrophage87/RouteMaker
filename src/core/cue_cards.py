"""A route's turn cues as phone-sized pictures, an arrow beside each (the owner, 2026-11-10: "some
people perfer to just navigate by a static image can you make a series of turn cues that are sized
for a phone from the mcp and also exportable from plan. Basically show the arrows"; "make sure
stops are listed").

The pictures are the Plan export's ("Cue sheet image, for a phone lock screen",
frontend/src/lib/lockScreen.ts and lib/cueArrow.ts), drawn here for the connector from the route's
description: 1179 by 2556 pixels, the top 28% and bottom 12% kept clear for a lock screen's clock
and controls, the route's name and figures small, then a row per cue (the miles from the start,
the picture, the turn, the road, a jog's later turns), the credits at the foot, "Part 2 of 3" where
the cues need more than one. Stops are rows of their own with their number, and their name where
the plan has one, and each starts a new image. Through (via) points are not cues, as in Ride.
Dark on white. Drawn with the standard library only, in memory for each ask: nothing is written
or kept.

The rows follow Ride's cues (frontend/src/lib/navigate.ts) closely, not exactly: a turn, a jog of
turns each within JOG_M of the one before (JOG_TURNS at most), a crossing between turns, a stop, a
walk, and the cautions the strip keeps (an Avoid-rated junction, a work zone Ride warns of, a
flagged crossing).
"""

from __future__ import annotations

import math

from . import (
    cue_glyphs_head,
    cue_glyphs_miles,
    cue_glyphs_road,
    cue_glyphs_small,
    cue_glyphs_turn,
)
from .route_picture import Canvas
from .share_preview import _glyph_data

WIDTH, HEIGHT = 1179, 2556
CLEAR_TOP = round(HEIGHT * 0.28)
CLEAR_BOTTOM = round(HEIGHT * 0.12)
INK = (17, 17, 17)
PAPER = (255, 255, 255)
SIDE, PAD = 56, 14
COL_MILES, COL_ARROW = 230, 160
ARROW_PX = 128
TEXT_X = SIDE + COL_MILES + COL_ARROW
# At most this many images: a longer route's cues past them are left to the app's own export.
MAX_PAGES = 12
METRES_PER_MILE = 1609.344
JOG_M = 100.0
JOG_TURNS = 3
TURN_WORDS = {
    "left": "Left",
    "right": "Right",
    "bear_left": "Bear left",
    "bear_right": "Bear right",
    "uturn": "U-turn",
}
STREET_WORDS = {
    "street": "St",
    "avenue": "Ave",
    "road": "Rd",
    "drive": "Dr",
    "boulevard": "Blvd",
    "parkway": "Pkwy",
    "place": "Pl",
    "court": "Ct",
    "lane": "Ln",
    "terrace": "Ter",
    "trail": "Trl",
    "highway": "Hwy",
    "circle": "Cir",
    "square": "Sq",
    "northwest": "NW",
    "northeast": "NE",
    "southwest": "SW",
    "southeast": "SE",
    "bridge": "Br",
    "service": "Svc",
}
NAMELESS = ("", "unnamed road", "path")


def abbreviate(street: str) -> str:
    """ "R Street Northwest" as "R St NW" (course.ts abbreviateStreet)."""
    words = street.strip()
    for lead in ("service road", "sidewalk", "path"):
        if words.startswith(f"{lead} beside "):
            words = lead
    return " ".join(STREET_WORDS.get(w.lower(), w) for w in words.split())


def _named(street) -> str:
    s = str(street or "").strip()
    return "" if s.lower().startswith("unnamed") else s


# --- the rows ----------------------------------------------------------------------------------


def cue_rows(answer: dict, vias: list[int] | tuple = (), names: dict | None = None) -> list[dict]:
    """The route's cue rows, in order, Start first and Finish last: each {at_m, turn, reason,
    road, then, arrow}, `arrow` the picture's kind and its own fields (lib/cueArrow.ts CueArrow)."""
    names = {int(k): str(v) for k, v in (names or {}).items()}
    through = {int(v) for v in vias or ()}
    entries = sorted(answer.get("description") or [], key=lambda e: e.get("from_m") or 0)
    length = float(answer.get("distance_m") or 0.0)
    first_street = next(
        (_named(e.get("street")) for e in entries if e.get("kind") == "stretch"), ""
    )
    rows: list[dict] = [_row(0.0, "Start", abbreviate(first_street), {"kind": "start"})]
    for e in entries:
        at = float(e.get("from_m") or 0.0)
        kind = e.get("kind")
        turn = e.get("turn") or {}
        if kind == "via" and e.get("via") is not None:
            point = int(e["via"])
            if point in through:
                continue
            number = point - sum(1 for v in through if v < point)
            name = names.get(point)
            rows.append(
                _row(at, name or f"Stop {number}", "", {"kind": "stop", "number": number})
                | {"reason": f"Stop {number}" if name else ""}
            )
        elif kind == "walk":
            rows.append(_row(at, "Walk", _named(e.get("street")), {"kind": "walk"}))
        elif kind == "avoid":
            rows.append(_caution(at, "Avoid-rated", e))
        elif kind == "workzone" and e.get("severity"):
            rows.append(_caution(at, "Work zone", e))
        elif kind == "hazard":
            rows.append(_caution(at, "", e))
        elif kind == "junction" and (e.get("severity") or e.get("group")) and not turn:
            rows.append(_caution(at, "Crossing", e))
        elif kind == "stretch" and turn.get("cross"):
            rows.append(
                _row(at, "Cross", abbreviate(_named(turn["cross"])), {"kind": "cross"})
                | {"_cross": True}
            )
        elif kind == "stretch" and turn.get("movement") in TURN_WORDS:
            road = _named(turn.get("onto") or e.get("street"))
            rows.append(
                _row(
                    at,
                    TURN_WORDS[turn["movement"]],
                    abbreviate(road) if road else "",
                    {
                        "kind": "turn",
                        "moves": [turn["movement"]],
                        "across": bool(turn.get("across")),
                    },
                )
                | {"_move": turn["movement"], "_road": road}
            )
    rows.append(_row(length, "Finish", "", {"kind": "finish"}))
    return _jogs(rows)


def _row(at: float, turn: str, road: str, arrow: dict) -> dict:
    return {"at_m": at, "turn": turn, "reason": "", "road": road, "then": "", "arrow": arrow}


def _caution(at: float, reason: str, entry: dict) -> dict:
    street = _named(entry.get("street"))
    return _row(at, "Caution", abbreviate(street) if street else "", {"kind": "caution"}) | {
        "reason": reason
    }


def _jogs(rows: list[dict]) -> list[dict]:
    """A turn's later turns each within JOG_M of the one before, JOG_TURNS at most, in its row
    and its arrow (navigate.ts joinJogs): a crossing may lead one, a turn across a road never."""
    out: list[dict] = []
    i = 0
    while i < len(rows):
        first = rows[i]
        jog = [first]
        leads = "_move" in first and not first["arrow"].get("across") or first.get("_cross")
        if leads:
            for nxt in rows[i + 1 :]:
                if len(jog) >= JOG_TURNS or "_move" not in nxt or nxt["arrow"].get("across"):
                    break
                if nxt["at_m"] - jog[-1]["at_m"] > JOG_M:
                    break
                jog.append(nxt)
        if len(jog) > 1:
            later = jog[1:]
            first["then"] = ", ".join(
                f"then {TURN_WORDS[t['_move']].lower()}"
                + (f" onto {abbreviate(t['_road'])}" if t["_road"] else "")
                for t in later
            )
            moves = [t["_move"] for t in later]
            if first.get("_cross"):
                first["arrow"] = {"kind": "turn", "moves": moves, "across": True}
            else:
                first["arrow"] = {
                    "kind": "turn",
                    "moves": [first["_move"], *moves],
                    "across": False,
                }
        out.append({k: v for k, v in first.items() if not k.startswith("_")})
        i += len(jog)
    return out


# --- the pictures (lib/cueArrow.ts) ------------------------------------------------------------

ARROW_STROKE, EDGE_STROKE = 11, 4
TURN_DEG = {"left": -90, "right": 90, "bear_left": -45, "bear_right": 45}
STEM, LEG, LAST, UTURN_R, HEAD_LEN, HEAD_HALF = 40, 28, 30, 16, 22, 20
FIT = (8, 92, 6, 94)  # left, right, top, bottom
MAX_SCALE = 1.6


def _walk_path(moves: list[str], stem: float):
    x = y = 0.0
    heading = -90.0
    points = [(x, y)]

    def go(length: float) -> None:
        nonlocal x, y
        x += length * math.cos(math.radians(heading))
        y += length * math.sin(math.radians(heading))
        points.append((x, y))

    go(stem)
    for i, m in enumerate(moves):
        last = i == len(moves) - 1
        if m == "uturn":
            cx = x + UTURN_R * math.cos(math.radians(heading - 90))
            cy = y + UTURN_R * math.sin(math.radians(heading - 90))
            start = heading + 90
            for k in range(1, 9):
                a = math.radians(start - 180 * k / 8)
                points.append((cx + UTURN_R * math.cos(a), cy + UTURN_R * math.sin(a)))
            x, y = points[-1]
            heading -= 180
            go(STEM * 0.5 if last else LEG)
            continue
        heading += TURN_DEG[m]
        go(LAST if last else LEG)
    return points, heading


def _head(tip, heading: float):
    dx, dy = math.cos(math.radians(heading)), math.sin(math.radians(heading))
    bx, by = tip[0] - dx * HEAD_LEN, tip[1] - dy * HEAD_LEN
    return [
        tip,
        (bx - dy * HEAD_HALF, by + dx * HEAD_HALF),
        (bx + dy * HEAD_HALF, by - dx * HEAD_HALF),
    ]


def _dashes(line):
    out = []
    for a, b in zip(line, line[1:], strict=False):
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        s = 0.0
        while s < length:
            e = min(length, s + 12)
            out.append(
                [
                    (a[0] + (b[0] - a[0]) * s / length, a[1] + (b[1] - a[1]) * s / length),
                    (a[0] + (b[0] - a[0]) * e / length, a[1] + (b[1] - a[1]) * e / length),
                ]
            )
            s += 21
    return out


def _arrow(moves: list[str], edges: bool, dashed: bool = False) -> dict:
    stem = STEM + (22 if edges else 0) if moves else STEM + LAST + 10
    points, heading = _walk_path(moves, stem)
    tip = points[-1]
    fill = _head(tip, heading)
    a = math.radians(heading)
    shaft = [
        *points[:-1],
        (tip[0] - math.cos(a) * (HEAD_LEN - 2), tip[1] - math.sin(a) * (HEAD_LEN - 2)),
    ]
    xs = [p[0] for p in points + fill]
    ys = [p[1] for p in points + fill]
    k = min(
        MAX_SCALE,
        (FIT[1] - FIT[0]) / ((max(xs) - min(xs)) or 1),
        (FIT[3] - FIT[2]) / ((max(ys) - min(ys)) or 1),
    )
    ox = 50 - (min(xs) + max(xs)) / 2 * k
    oy = FIT[3] - max(ys) * k

    def at(p):
        return (p[0] * k + ox, p[1] * k + oy)

    line = [at(p) for p in shaft]
    shape = {
        "strokes": _dashes(line) if dashed else [line],
        "thin": [],
        "fills": [[at(p) for p in fill]],
        "discs": [],
    }
    if edges:
        y1, y2 = oy - stem * 0.2 * k, oy - stem * 0.6 * k
        shape["thin"] = [[(2, y1), (98, y1)], [(2, y2), (98, y2)]]
    return shape


def arrow_shape(arrow: dict) -> dict:
    """The picture for a cue, in a 100 by 100 box (lib/cueArrow.ts arrowShape)."""
    kind = arrow["kind"]
    empty = {"strokes": [], "thin": [], "fills": [], "discs": []}
    if kind == "turn":
        return _arrow(list(arrow["moves"]), bool(arrow.get("across")))
    if kind == "cross":
        return _arrow([], True)
    if kind == "walk":
        return _arrow([], False, dashed=True)
    if kind == "start":
        return empty | {"discs": [(50, 50, 36, ARROW_STROKE), (50, 50, 14, None)]}
    if kind == "finish":
        left, top, size = 32, 12, 13
        fills = [
            [(x, y), (x + size, y), (x + size, y + size), (x, y + size)]
            for row in range(3)
            for col in range(4)
            if not (row + col) % 2
            for x, y in [(left + col * size, top + row * size)]
        ]
        right, bottom = left + 4 * size, top + 3 * size
        return empty | {
            "strokes": [[(left - 4, top - 2), (left - 4, 94)]],
            "thin": [[(left, top), (right, top), (right, bottom), (left, bottom), (left, top)]],
            "fills": fills,
        }
    if kind == "stop":
        shape = empty | {"discs": [(50, 50, 42, None)]}
        if arrow.get("number") is not None:
            shape["label"] = str(arrow["number"])
        return shape
    if kind == "caution":
        return empty | {
            "strokes": [[(50, 8), (94, 88), (6, 88), (50, 8)], [(50, 38), (50, 62)]],
            "discs": [(50, 75, 6, None)],
        }
    return empty | {
        "strokes": [[(50, 46), (50, 72)]],
        "discs": [(50, 50, 40, ARROW_STROKE * 0.8), (50, 32, 6, None)],
    }


def _fill_polygon(canvas: Canvas, points, colour) -> None:
    """A filled polygon, its edge antialiased by four samples a pixel across."""
    ys = [p[1] for p in points]
    xs = [p[0] for p in points]
    for y in range(max(0, int(min(ys))), min(canvas.h, int(max(ys)) + 2)):
        for x in range(max(0, int(min(xs))), min(canvas.w, int(max(xs)) + 2)):
            hits = 0
            for sx, sy in ((0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75)):
                if _inside(points, x + sx, y + sy):
                    hits += 1
            if hits:
                canvas.blend(x, y, colour, hits / 4)


def _inside(points, px: float, py: float) -> bool:
    inside = False
    for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1], strict=False):
        if (ay > py) != (by > py) and px < ax + (py - ay) * (bx - ax) / (by - ay):
            inside = not inside
    return inside


def _ring(canvas: Canvas, cx: float, cy: float, r: float, width: float, colour) -> None:
    inner = r - width
    for y in range(int(cy - r - 1), int(cy + r + 2)):
        for x in range(int(cx - r - 1), int(cx + r + 2)):
            d = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
            cover = min(1.0, r + 0.5 - d, d - inner + 0.5)
            canvas.blend(x, y, colour, cover)


def draw_arrow(canvas: Canvas, arrow: dict, left: float, top: float, size: float) -> None:
    shape = arrow_shape(arrow)
    k = size / 100

    def at(p):
        return (left + p[0] * k, top + p[1] * k)

    for line in shape["thin"]:
        canvas.stroke([at(p) for p in line], EDGE_STROKE * k / 2, INK)
    for line in shape["strokes"]:
        canvas.stroke([at(p) for p in line], ARROW_STROKE * k / 2, INK)
    for poly in shape["fills"]:
        _fill_polygon(canvas, [at(p) for p in poly], INK)
    for x, y, r, ring in shape["discs"]:
        cx, cy = at((x, y))
        if ring:
            _ring(canvas, cx, cy, r * k, ring * k, INK)
        else:
            canvas.disc(cx, cy, r * k, INK)
    if shape.get("label"):
        cx, cy = at((50, 50))
        g = cue_glyphs_head
        width = _width(shape["label"], g)
        _text(canvas, g, cx - width / 2, cy + (g.ASCENT - g.HEIGHT / 2) - 6, shape["label"], PAPER)


# --- the text ----------------------------------------------------------------------------------


def _width(words: str, g) -> int:
    return sum((g.GLYPHS.get(ch) or g.GLYPHS["?"])[0] for ch in words)


def _text(canvas: Canvas, g, x: float, baseline: float, words: str, colour=INK) -> None:
    data = _glyph_data(g.__name__)
    x, top = round(x), round(baseline) - g.ASCENT
    for ch in words:
        advance, left, width, offset = g.GLYPHS.get(ch) or g.GLYPHS["?"]
        for row in range(g.HEIGHT):
            base = offset + row * width
            for col in range(width):
                c = data[base + col]
                if c:
                    canvas.blend(x + left + col, top + row, colour, c / 255)
        x += advance


def _wrap(words: str, g, width: float) -> list[str]:
    lines: list[str] = []
    line = ""
    for word in words.split():
        tried = f"{line} {word}" if line else word
        if _width(tried, g) <= width:
            line = tried
            continue
        if line:
            lines.append(line)
        while _width(word, g) > width and len(word) > 1:
            n = len(word) - 1
            while n > 1 and _width(word[:n], g) > width:
                n -= 1
            lines.append(word[:n])
            word = word[n:]
        line = word
    if line:
        lines.append(line)
    return lines


def _figure(metres: float) -> str:
    return f"{metres / METRES_PER_MILE:.1f}"


def _row_layout(row: dict) -> tuple[list[tuple], int]:
    """A row's lines (glyphs, x, baseline from the row's top, words) and its height."""
    lines: list[tuple] = []

    def column(x: float, width: float, parts) -> int:
        y = PAD
        for g, words in parts:
            for text in _wrap(words, g, width - PAD):
                y += round(g.SIZE * 1.15)
                lines.append((g, x, y - round(g.SIZE * 0.2), text))
        return y

    text_parts = [(cue_glyphs_turn, row["turn"])]
    if row["reason"]:
        text_parts.append((cue_glyphs_small, row["reason"]))
    if row["road"]:
        text_parts.append((cue_glyphs_road, row["road"]))
    if row["then"]:
        text_parts.append((cue_glyphs_head, row["then"]))
    bottoms = [
        column(
            SIDE,
            COL_MILES,
            [
                (cue_glyphs_miles, _figure(row["at_m"])),
                (cue_glyphs_small, f"mi ({row['at_m'] / 1000:.1f} km)"),
            ],
        ),
        column(TEXT_X, WIDTH - SIDE - TEXT_X, text_parts),
        PAD + ARROW_PX,
    ]
    return lines, max(bottoms) + PAD


def draw(answer: dict, title: str, vias=(), names=None, credit: str = "") -> list[bytes]:
    """The route's phone cue images as PNGs, in order (MAX_PAGES at most)."""
    rows = cue_rows(answer, vias, names)
    laid = [_row_layout(r) for r in rows]
    distance = float(answer.get("distance_m") or 0.0)
    summary = f"Distance {distance / METRES_PER_MILE:.1f} mi ({distance / 1000:.1f} km)." + (
        f" Climb {round(float(answer['climb_m']) * 3.28084):,} ft"
        f" ({round(float(answer['climb_m'])):,} m)."
        if answer.get("climb_m") is not None
        else ""
    )
    credit_lines = _wrap(credit, cue_glyphs_small, WIDTH - 2 * SIDE) if credit else []
    credit_top = HEIGHT - CLEAR_BOTTOM - 16 - len(credit_lines) * round(30 * 1.25)

    def header(part: str | None) -> tuple[list[tuple], int]:
        out: list[tuple] = []
        y = CLEAR_TOP + 8
        for g, words in ((cue_glyphs_head, title), (cue_glyphs_small, summary)) + (
            ((cue_glyphs_head, part),) if part else ()
        ):
            for text in _wrap(words, g, WIDTH - 2 * SIDE):
                y += round(g.SIZE * 1.25)
                out.append((g, SIDE, y, text))
        return out, y

    def fill(cue_top: int) -> list[list[int]]:
        pages: list[list[int]] = [[]]
        y = cue_top
        for i, (_lines, height) in enumerate(laid):
            # Each stop starts an image of its own, the stop at its head (the owner, 2026-11-10:
            # "Have splits at stops").
            stop = rows[i]["arrow"]["kind"] == "stop"
            if (stop or y + height > credit_top - 16) and pages[-1]:
                pages.append([])
                y = cue_top
            pages[-1].append(i)
            y += height
        return pages

    groups = fill(header(None)[1] + 24)
    if len(groups) > 1:
        groups = fill(header("Part 88 of 88")[1] + 24)
    groups = groups[:MAX_PAGES]
    images: list[bytes] = []
    for p, group in enumerate(groups):
        part = f"Part {p + 1} of {len(groups)}" if len(groups) > 1 else None
        canvas = Canvas(WIDTH, HEIGHT, PAPER)
        head_lines, bottom = header(part)
        for g, x, y, text in head_lines:
            _text(canvas, g, x, y, text)
        y = bottom + 24
        canvas.rect(SIDE, y - 1, WIDTH - SIDE, y + 1, INK)
        for i in group:
            lines, height = laid[i]
            for g, x, base, text in lines:
                _text(canvas, g, x, y + base, text)
            draw_arrow(
                canvas,
                rows[i]["arrow"],
                SIDE + COL_MILES + (COL_ARROW - ARROW_PX) // 2 - 10,
                y + PAD,
                ARROW_PX,
            )
            y += height
            canvas.rect(SIDE, y - 1, WIDTH - SIDE, y + 1, INK)
        for n, text in enumerate(credit_lines):
            _text(canvas, cue_glyphs_small, SIDE, credit_top + (n + 1) * round(30 * 1.25), text)
        images.append(canvas.png())
    return images
