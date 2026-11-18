"""The interval-capable stretches near a point (the Intervals layer's file, read only).

The owner, 2026-11-16: "a layer that could identify interval-capable segments ... available
for the MCP." The connector's `intervals_near` tool (mcp/routemaker_mcp.py) asks this for the
stretches within reach of a point, each with its start, end and points along it for a plan
that rides it, in its riding direction. What counts is `pipeline.interval_layer`'s docstring.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# The file as committed (docker/api.Dockerfile copies it into the api image beside the source).
INTERVALS_FILE = (
    Path(__file__).resolve().parents[2] / "frontend" / "src" / "interval-data" / "intervals.json"
)
FORMAT_VERSION = 1
METRES_PER_MILE = 1609.344
FEET_PER_METRE = 3.28084
MAX_RADIUS_MI = 15.0
MAX_STRETCHES = 25
# Points along a stretch handed back as via points: enough to keep a plan on it.
THROUGH_POINTS = 3
SURFACES = {"p": "path", "g": "gravel"}


class Unavailable(Exception):
    """This host has no Intervals layer file."""


@dataclass(frozen=True, slots=True)
class Stretch:
    id: str
    length_m: float
    rise_m: float
    grade_pct: float
    line: tuple[tuple[float, float], ...]
    both_ways: bool = False
    name: str | None = None
    surface: str = ""
    busy: bool = False
    # Minutes to ride it at the build's pace (the file's `t`; pipeline.interval_layer).
    minutes: float = 0.0
    # Bollards or blocks it passes, ridden through (the file's `k`).
    bollards: int = 0


_cache: dict[str, tuple[tuple[int, int], tuple[Stretch, ...] | None]] = {}


def parse(doc: object) -> tuple[Stretch, ...] | None:
    # The file ships unbuilt ("built": null) until the build host writes it: that is no file,
    # not a map with no stretches.
    if not isinstance(doc, dict) or doc.get("version") != FORMAT_VERSION or not doc.get("built"):
        return None
    rows = doc.get("intervals")
    if not isinstance(rows, list):
        return None
    out = []
    for row in rows:
        try:
            line = tuple((float(lon), float(lat)) for lon, lat in row["line"])
            stretch = Stretch(
                id=str(row["id"]),
                length_m=float(row["l"]),
                rise_m=float(row["r"]),
                grade_pct=float(row["g"]),
                line=line,
                both_ways=bool(row.get("w")),
                name=row.get("n") or None,
                surface=str(row.get("s") or ""),
                busy=bool(row.get("b")),
                minutes=float(row.get("t") or 0.0),
                bollards=int(row.get("k") or 0),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if len(line) >= 2 and stretch.length_m > 0:
            out.append(stretch)
    return tuple(out)


def load(path: Path | str | None = None) -> tuple[Stretch, ...] | None:
    """The file's stretches, read again only when it changes; None without a readable file."""
    path = Path(path or INTERVALS_FILE)
    try:
        stat = path.stat()
    except OSError:
        return None
    key = (stat.st_mtime_ns, stat.st_size)
    cached = _cache.get(str(path))
    if cached is not None and cached[0] == key:
        return cached[1]
    try:
        stretches = parse(json.loads(path.read_bytes()))
    except (OSError, ValueError):
        stretches = None
    if stretches is None:
        logger.warning("the intervals file %s is unbuilt or could not be read", path)
    _cache[str(path)] = (key, stretches)
    return stretches


def _away_m(point: tuple[float, float], line) -> float:
    """The metres from `point` to the line (its nearest segment, on a local plane)."""
    lon, lat = point
    k = math.cos(math.radians(lat))
    xy = [((a - lon) * k, b - lat) for a, b in line]
    best = min(x * x + y * y for x, y in xy)
    for (x0, y0), (x1, y1) in zip(xy, xy[1:], strict=False):
        dx, dy = x1 - x0, y1 - y0
        length = dx * dx + dy * dy
        if length <= 0:
            continue
        t = max(0.0, min(1.0, -(x0 * dx + y0 * dy) / length))
        best = min(best, (x0 + t * dx) ** 2 + (y0 + t * dy) ** 2)
    return math.sqrt(best) * 111_320


def _through(line) -> list[list[float]]:
    """THROUGH_POINTS vertices spread along the line between its ends."""
    inner = line[1:-1]
    if not inner:
        return []
    picks = sorted(
        {round((k + 1) * len(inner) / (THROUGH_POINTS + 1)) for k in range(THROUGH_POINTS)}
    )
    return [[round(inner[i][0], 6), round(inner[i][1], 6)] for i in picks if i < len(inner)]


def surface(stretch: Stretch) -> str:
    return SURFACES.get(stretch.surface, "road")


def near(
    lon: float,
    lat: float,
    miles: float,
    min_miles: float = 0.0,
    paved_only: bool = False,
    quiet_only: bool = False,
    longest: bool = False,
    no_bollards: bool = False,
) -> list[dict]:
    """The stretches within `miles` (at most MAX_RADIUS_MI) of the point, at least `min_miles`
    long, paved only, off busy roads only or without bollards only where asked; nearest first,
    or longest first. Raises Unavailable without the file."""
    stretches = load()
    if stretches is None:
        raise Unavailable("there is no intervals file")
    reach_m = min(miles, MAX_RADIUS_MI) * METRES_PER_MILE
    dlat = (reach_m + 5_000) / 111_320
    dlon = dlat / max(0.1, math.cos(math.radians(lat)))
    found = []
    for s in stretches:
        if s.length_m < min_miles * METRES_PER_MILE:
            continue
        if paved_only and s.surface == "g":
            continue
        if quiet_only and s.busy:
            continue
        if no_bollards and s.bollards:
            continue
        if not any(abs(a - lon) <= dlon and abs(b - lat) <= dlat for a, b in s.line):
            continue
        away = _away_m((lon, lat), s.line)
        if away <= reach_m:
            found.append((away, s))
    found.sort(key=(lambda p: (-p[1].length_m, p[0])) if longest else (lambda p: p[0]))
    return [
        {
            "id": s.id,
            "name": s.name,
            "miles": round(s.length_m / METRES_PER_MILE, 2),
            "rise_ft": round(s.rise_m * FEET_PER_METRE),
            "grade_pct": s.grade_pct,
            "both_ways": s.both_ways,
            "start": [round(s.line[0][0], 6), round(s.line[0][1], 6)],
            "end": [round(s.line[-1][0], 6), round(s.line[-1][1], 6)],
            "through": _through(s.line),
            "surface": surface(s),
            "busy": s.busy,
            "bollards": s.bollards,
            "away_mi": round(away / METRES_PER_MILE, 1),
        }
        for away, s in found[:MAX_STRETCHES]
    ]
