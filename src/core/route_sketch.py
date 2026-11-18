"""A saved route's row figures (backlog 2026-11-12, Plan item 9, "Saved routes you can tell apart
at 50+"): a small sketch of its line and its climb and share of quiet riding, so Load route and
My routes can show "the hilly Rockville one" at a glance.

Kept on the row (SavedRoute.figures) when its line or answer is saved, so the list reads a few
hundred bytes a route and never the line, answer or file. The sketch is the line's shape alone,
no base map: the app draws it as a small SVG, so nothing is stored or drawn on the server and no
image is fetched (our default; the server's route pictures, core/route_picture.py, are a whole
map each).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

# The sketch's box: the longer side runs 0..BOX, the shorter centred in it (our default).
BOX = 100
# At most this many points (our default: a 48 px picture shows no more).
MAX_POINTS = 48
# Douglas-Peucker's first tolerance, a share of the box; doubled until the points fit.
FIRST_TOLERANCE = 0.75


def _project(line: Sequence[Sequence[float]]) -> list[tuple[float, float]]:
    """[lon, lat] to local metres east and north (equirectangular at the line's middle
    latitude; a picture this small needs no better)."""
    lats = [p[1] for p in line]
    k = math.cos(math.radians((min(lats) + max(lats)) / 2))
    return [(p[0] * 111_320.0 * k, p[1] * 110_540.0) for p in line]


def _simplify(points: list[tuple[float, float]], tolerance: float) -> list[tuple[float, float]]:
    """Douglas-Peucker, iterative (a long GPX file must not hit the recursion limit)."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = points[a], points[b]
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        far, far_i = -1.0, -1
        for i in range(a + 1, b):
            px, py = points[i]
            if length == 0:
                d = math.hypot(px - ax, py - ay)
            else:
                d = abs(dy * (px - ax) - dx * (py - ay)) / length
            if d > far:
                far, far_i = d, i
        if far > tolerance and far_i > 0:
            keep[far_i] = True
            stack.append((a, far_i))
            stack.append((far_i, b))
    return [p for p, k in zip(points, keep, strict=True) if k]


def sketch(line: Sequence[Sequence[float]] | None) -> list[list[int]] | None:
    """The line's shape as whole-number points in a BOX-wide square, north up (y grows south,
    as SVG draws), at most MAX_POINTS; None for a line too short to draw."""
    pts = [p for p in (line or []) if isinstance(p, (list, tuple)) and len(p) >= 2]
    if len(pts) < 2:
        return None
    try:
        xy = _project(pts)
    except (TypeError, ValueError):
        return None
    xs, ys = [p[0] for p in xy], [p[1] for p in xy]
    width, height = max(xs) - min(xs), max(ys) - min(ys)
    span = max(width, height)
    if span <= 0:
        return None
    scale = BOX / span
    # The shorter side centred in the box.
    ox = (BOX - width * scale) / 2
    oy = (BOX - height * scale) / 2
    boxed = [((x - min(xs)) * scale + ox, (max(ys) - y) * scale + oy) for x, y in xy]
    tolerance = FIRST_TOLERANCE
    kept = _simplify(boxed, tolerance)
    while len(kept) > MAX_POINTS:
        tolerance *= 2
        kept = _simplify(boxed, tolerance)
    out: list[list[int]] = []
    for x, y in kept:
        point = [round(x), round(y)]
        if not out or out[-1] != point:
            out.append(point)
    return out if len(out) >= 2 else None


def climb_m(answer: dict | None) -> float | None:
    """The planned route's climb, metres, as its answer has it; None for a file's line."""
    value = (answer or {}).get("climb_m")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return round(float(value), 1)
    return None


def quiet_pct(answer: dict | None) -> int | None:
    """The share of the route at traffic stress 1 or 2, percent (as Bike loop's shapes say it,
    core/bike_loop.py); None where the answer has no stress."""
    stress = (answer or {}).get("stress_m")
    if not isinstance(stress, dict):
        return None
    metres = {k: float(v) for k, v in stress.items() if isinstance(v, (int, float)) and v > 0}
    total = sum(metres.values())
    if total <= 0:
        return None
    return round(100.0 * (metres.get("1", 0.0) + metres.get("2", 0.0)) / total)


def figures(line: Sequence[Sequence[float]] | None, answer: dict | None) -> dict:
    """What SavedRoute.figures keeps: {"sketch", "climb_m", "quiet_pct"}, each None where not
    known."""
    return {"sketch": sketch(line), "climb_m": climb_m(answer), "quiet_pct": quiet_pct(answer)}
