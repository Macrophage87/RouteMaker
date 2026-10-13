"""Hill seek: a candidate generator that goes looking for climbs near the line.

Why. Right of the hills detent on Mountain Goat (`presets.Preset.hills_tolerate`
False, OWNER-DECISIONS 242) the planner picks the route that climbs most within the
distance budget (`routing.choose_climb`, `presets.seek_distance_ratio`). Before this
module it chose only among the router's own three alternatives, and those are the
router's near-ties on time: they rarely go out of their way for a hill.
OWNER-DECISIONS 205, FOLLOWUP-HILL-SEEK: "a candidate generator that finds climbs
near the line and routes through them, like the trail seek" (`core.trailseek`).

What it does. It reads the Climbs layer's file (frontend/src/climb-data/climbs.json,
every categorised climb on the routable network, Cat 5 to HC: `pipeline.climb_layer`,
`routemaker.climb_categories`). That file is written at build time and committed, so
nothing here needs a map rebuild; a host without it (or with a file it cannot read)
plans as before, and the answer says so. The climbs it looks at are those inside the
distance budget's corridor: an ellipse round the straight line from the start to the
end, the set of climbs a route could ride and still be within the budget,

    CIRCUITY x (start to the climb's foot + the climb's summit to the end)
        + the climb's length <= ratio x the direct route's length

where the direct route is the router's own at the detent and `ratio` the dial's
(1.05 at 10, 1.5 at 100), so the corridor widens as the dial goes right. A climb the
router's own routes already ride is left out (it adds nothing), as is a mostly
unpaved one when the rider has asked to avoid gravel. They are ranked by category
(HC first, Cat 5 last), then by height gained, then by the shortest estimate.

From the ranking it proposes, as the trail seek does: the best climb with the best
other one that fits the budget beside it (both ridden, in the order that is
shorter), the best alone, then the next best alone, at most `MAX_CANDIDATES` router
calls in all. Each climb is asked for as `through` locations along its line from
its foot to its summit (`via_points`), in that order, so the router rides it uphill.
This module only proposes; `core.routing` asks the router and adds what it answers
to the router's own routes, and `choose_climb` picks among them all, with the same
budget and the same measure of climbing as before.

Naming. `ridden` finds the climbs a route rides uphill - the front end's rule for its
"climbs on your route" list (`climbsAlongRoute`, frontend/src/lib/climbs.ts), kept
the same - and `entries` words each as a description entry: category, length and
height gained, US units first and the metric in brackets.

Everything here is pure (no database, no router), so that it can be tested alone;
`load` is the one place that reads a file.
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from routemaker import climb_categories, climb_exclusions
from routemaker.describe import point_words
from routemaker.geo import Point, haversine

from .trailseek import Plane, RouteLine

logger = logging.getLogger(__name__)

# The Climbs layer's file, as committed (docker/api.Dockerfile copies it into the
# api image beside the source).
CLIMBS_FILE = (
    Path(__file__).resolve().parents[2] / "frontend" / "src" / "climb-data" / "climbs.json"
)
# The file's format (`pipeline.climb_layer.FORMAT_VERSION`); another is not read.
FORMAT_VERSION = 1

# Roads run about this much longer than the straight line between two points (a
# typical detour index for a street grid): the corridor's estimate of the way to a
# climb's foot and from its summit.
CIRCUITY = 1.2
# The most router calls one plan makes for the seek, as the trail seek's
# `SEEK_MAX_CANDIDATES`.
MAX_CANDIDATES = 3
# The seek's own budget (seconds), from when it starts.
SEEK_BUDGET_S = 8.0
# The least a router call is started with (seconds): a /route with through points.
ROUND_MIN_S = 2.0
# What is kept back from the plan's budget for the answer's own traces (seconds), as
# the traffic-wins check keeps (`routing.MIDDLE_TRACE_RESERVE_S`).
TRACE_RESERVE_S = 8.0
# The via points sit this far in from the climb's foot and summit (metres), so that
# the router snaps to the climb and not to the road across its end (the trail
# seek's `VIA_INSET_M`) ...
VIA_INSET_M = 25.0
# ... and about this far apart up it (metres), with at least a middle one and no
# more than MAX_VIAS on one climb, so that a long climb is not cut short by a road
# that leaves and rejoins it.
VIA_SPACING_M = 1_500.0
MAX_VIAS = 6
# Two climbs ridden in one route must be this far apart (metres) at their feet and
# at their summits: two sides of one hill are a climb and a descent of each other.
PAIR_GAP_M = 300.0
# How close the route must pass every point of a climb's line to ride it, and the
# ridden stretch's length against the climb's (the front end's ON_CLIMB_M and its
# 0.8 to 1.3).
ON_CLIMB_M = 50.0
RIDDEN_MIN = 0.8
RIDDEN_MAX = 1.3
# The route's grid (`trailseek.RouteLine`) keeps a point every 25 m
# (`trailseek.ROUTE_STEP_M`), so its quick test of a climb's ends reaches this much
# further than the exact one.
GRID_SLACK_M = 25.0

METRES_PER_MILE = 1609.344
FEET_PER_METRE = 3.28084

LonLat = tuple[float, float]
# Higher is better: HC, then 1 to 5.
CATEGORY_RANK = {
    name: len(climb_categories.CATEGORIES) - i
    for i, (name, _score) in enumerate(climb_categories.CATEGORIES)
}


class OutOfTime(Exception):
    """The router or the plan's budget ran out during the seek."""


def _metres(a: Sequence[float], b: Sequence[float]) -> float:
    return haversine(Point(a[0], a[1]), Point(b[0], b[1]))


@dataclass(frozen=True)
class Climb:
    """One categorised climb from the file, its line from its foot to its summit."""

    id: str
    category: str
    length_m: float
    gain_m: float
    grade_pct: float
    line: tuple[LonLat, ...]
    unpaved: bool = False
    name: str | None = None

    @property
    def foot(self) -> LonLat:
        return self.line[0]

    @property
    def summit(self) -> LonLat:
        return self.line[-1]

    @property
    def rank(self) -> int:
        return CATEGORY_RANK.get(self.category, 0)


# --- The file ----------------------------------------------------------------------

_cache: dict[str, tuple[tuple[int, int], tuple[Climb, ...] | None]] = {}
# The paths found missing, so that a host without the file logs it once, not every plan.
_missing: set[str] = set()


def parse(doc: object) -> tuple[Climb, ...] | None:
    """The climbs of the file's document, or None where it is not the file's shape. An
    entry that is not a categorised climb with a line is left out, and so is one taken
    off by hand for not being a public way open to bikes (`routemaker.climb_exclusions`)."""
    if not isinstance(doc, dict) or doc.get("version") != FORMAT_VERSION:
        return None
    rows = doc.get("climbs")
    if not isinstance(rows, list):
        return None
    out: list[Climb] = []
    for row in rows:
        try:
            line = tuple((float(lon), float(lat)) for lon, lat in row["line"])
            climb = Climb(
                id=str(row["id"]),
                category=str(row["c"]),
                length_m=float(row["l"]),
                gain_m=float(row["r"]),
                grade_pct=float(row["g"]),
                line=line,
                unpaved=bool(row.get("u")),
                name=row.get("n") or None,
            )
        except (KeyError, TypeError, ValueError):
            continue
        if climb_exclusions.is_excluded(climb.id):
            continue
        if len(line) >= 2 and climb.category in CATEGORY_RANK and climb.length_m > 0:
            out.append(climb)
    return tuple(out)


def load(path: Path | str | None = None) -> tuple[Climb, ...] | None:
    """The climbs in the Climbs layer's file, read once and again only when it
    changes; None where there is no file or it cannot be read (the seek then does
    not run)."""
    path = Path(path or CLIMBS_FILE)
    try:
        stat = path.stat()
    except OSError:
        if str(path) not in _missing:
            _missing.add(str(path))
            logger.warning("there is no climbs file at %s; the hill seek is off", path)
        return None
    # Back again: should it go missing later, that is said again.
    _missing.discard(str(path))
    key = (stat.st_mtime_ns, stat.st_size)
    cached = _cache.get(str(path))
    if cached is not None and cached[0] == key:
        return cached[1]
    try:
        climbs = parse(json.loads(path.read_bytes()))
    except (OSError, ValueError):
        climbs = None
    if climbs is None:
        logger.warning("the climbs file %s could not be read; the hill seek is off", path)
    _cache[str(path)] = (key, climbs)
    return climbs


# --- The corridor ------------------------------------------------------------------


def estimate_m(start: LonLat, end: LonLat, climbs: Sequence[Climb]) -> float:
    """How long a route from `start` to `end` riding `climbs` in order is estimated
    to be: CIRCUITY times the straight lines between them, plus the climbs."""
    way = 0.0
    at = start
    for climb in climbs:
        way += _metres(at, climb.foot)
        at = climb.summit
    way += _metres(at, end)
    return CIRCUITY * way + sum(c.length_m for c in climbs)


def preference(climb: Climb, start: LonLat, end: LonLat) -> tuple[float, float, float]:
    """The ranking's key, smallest first: higher categories, then more height
    gained, then the shorter estimate."""
    return (-climb.rank, -climb.gain_m, estimate_m(start, end, (climb,)))


def in_corridor(
    climbs: Iterable[Climb],
    start: LonLat,
    end: LonLat,
    budget_m: float,
    avoid_gravel: bool = False,
) -> list[Climb]:
    """The climbs a route within `budget_m` could ride, best first."""
    near = [
        c
        for c in climbs
        if not (avoid_gravel and c.unpaved) and estimate_m(start, end, (c,)) <= budget_m
    ]
    return sorted(near, key=lambda c: preference(c, start, end))


def apart(a: Climb, b: Climb) -> bool:
    """Whether two climbs are far enough apart to be ridden in one route."""
    return _metres(a.foot, b.foot) >= PAIR_GAP_M and _metres(a.summit, b.summit) >= PAIR_GAP_M


def ordered(start: LonLat, end: LonLat, a: Climb, b: Climb) -> tuple[Climb, Climb]:
    """Two climbs in the order that makes the shorter route."""
    if estimate_m(start, end, (b, a)) < estimate_m(start, end, (a, b)):
        return b, a
    return a, b


def propose(
    near: Sequence[Climb],
    start: LonLat,
    end: LonLat,
    budget_m: float,
    limit: int = MAX_CANDIDATES,
) -> list[tuple[Climb, ...]]:
    """What to ask the router for, best bet first:

    - the best climb with the best other one beside it that the budget allows (both
      ridden, in the shorter order), if there is one;
    - the best climb alone;
    - the next best climbs alone, each apart from those already asked for.
    """
    if not near or limit < 1:
        return []
    first = near[0]
    out: list[tuple[Climb, ...]] = []
    for other in near[1:]:
        if not apart(first, other):
            continue
        pair = ordered(start, end, first, other)
        if estimate_m(start, end, pair) <= budget_m:
            out.append(pair)
            break
    out.append((first,))
    # The pair's partner is covered by the pair's route: not asked for again alone.
    asked = [climb for proposal in out for climb in proposal]
    for climb in near[1:]:
        if len(out) >= limit:
            break
        if all(apart(climb, c) for c in asked):
            out.append((climb,))
            asked.append(climb)
    return out[:limit]


def _along(line: Sequence[LonLat], plane: Plane) -> list[float]:
    out = [0.0]
    for a, b in zip(line, line[1:], strict=False):
        out.append(out[-1] + math.dist(plane.xy(*a), plane.xy(*b)))
    return out


def _point_at(line: Sequence[LonLat], along: Sequence[float], metres: float) -> LonLat:
    for i in range(1, len(line)):
        if along[i] >= metres:
            span = along[i] - along[i - 1]
            f = (metres - along[i - 1]) / span if span > 0 else 0.0
            a, b = line[i - 1], line[i]
            return a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
    return line[-1]


def via_points(climb: Climb) -> list[LonLat]:
    """The through points that ask for a climb, from near its foot to near its
    summit: VIA_INSET_M in from each end and at most about VIA_SPACING_M apart
    between, at least three and no more than MAX_VIAS."""
    plane = Plane(climb.foot, climb.summit)
    along = _along(climb.line, plane)
    total = along[-1]
    inset = min(VIA_INSET_M, total / 4)
    inner = total - 2 * inset
    steps = min(MAX_VIAS - 1, max(2, math.ceil(inner / VIA_SPACING_M)))
    return [_point_at(climb.line, along, inset + inner * k / steps) for k in range(steps + 1)]


def vias_of(climbs: Sequence[Climb]) -> list[LonLat]:
    out: list[LonLat] = []
    for climb in climbs:
        out.extend(via_points(climb))
    return out


# --- Along a route -----------------------------------------------------------------


@dataclass(frozen=True)
class Ridden:
    """A climb a route rides uphill, and where along the route (metres, the line's
    own measure) it starts and reaches the summit."""

    climb: Climb
    start_m: float
    summit_m: float


def ridden(
    coordinates: Sequence[LonLat],
    climbs: Iterable[Climb],
    tolerance_m: float = ON_CLIMB_M,
) -> list[Ridden]:
    """The climbs the route rides uphill, in the order it reaches them: every point of
    the climb's line, foot to summit, within `tolerance_m` of the route, each further
    along it than the one before (a descent of the same road does not count), and the
    stretch of route from the foot to the summit RIDDEN_MIN to RIDDEN_MAX times the
    climb's length (a route that leaves the climb and comes back does not ride it).
    The front end's `climbsAlongRoute`, in Python."""
    if len(coordinates) < 2:
        return []
    plane = Plane(coordinates[0], coordinates[-1])
    xy = [plane.xy(lon, lat) for lon, lat in coordinates]
    cumulative = [0.0]
    for a, b in zip(xy, xy[1:], strict=False):
        cumulative.append(cumulative[-1] + math.dist(a, b))
    # The route's grid: which climbs come near it at all, before the ordered walk.
    near = RouteLine(xy, radius=tolerance_m + GRID_SLACK_M)

    def place(x: float, y: float, i: int) -> tuple[float, float] | None:
        """(metres along, metres away) of the nearest point of segment i."""
        ax, ay = xy[i - 1]
        bx, by = xy[i]
        if x < min(ax, bx) - tolerance_m or x > max(ax, bx) + tolerance_m:
            return None
        if y < min(ay, by) - tolerance_m or y > max(ay, by) + tolerance_m:
            return None
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / length2))
        away = math.hypot(x - (ax + t * dx), y - (ay + t * dy))
        if away > tolerance_m:
            return None
        return cumulative[i - 1] + t * math.sqrt(length2), away

    def first_near(x: float, y: float, segment: int, from_m: float) -> tuple[int, float] | None:
        for i in range(max(1, segment), len(xy)):
            hit = place(x, y, i)
            if hit is not None and hit[0] + 1e-6 >= from_m:
                return i, hit[0]
        return None

    def last_near(x: float, y: float, segment: int, to_m: float) -> tuple[int, float] | None:
        for i in range(min(segment, len(xy) - 1), 0, -1):
            hit = place(x, y, i)
            if hit is not None and hit[0] <= to_m + 1e-6:
                return i, hit[0]
        return None

    out: list[Ridden] = []
    for climb in climbs:
        points = [plane.xy(lon, lat) for lon, lat in climb.line]
        if near.nearest(*points[0]) is None or near.nearest(*points[-1]) is None:
            continue
        segment, along = 1, 0.0
        hits: list[tuple[int, float]] = []
        for x, y in points:
            hit = first_near(x, y, segment, along)
            if hit is None:
                break
            hits.append(hit)
            segment, along = hit
        if len(hits) < len(points):
            continue
        # Back from the summit: the last time before it that the route passed each
        # point, so a route that rolls down the climb first starts it at the turn.
        start = hits[-1]
        for x, y in reversed(points[:-1]):
            hit = last_near(x, y, *start)
            if hit is None:
                break
            start = hit
        length = along - start[1]
        if not (RIDDEN_MIN * climb.length_m <= length <= RIDDEN_MAX * climb.length_m):
            continue
        out.append(Ridden(climb, start[1], along))
    return sorted(out, key=lambda r: r.start_m)


def candidates_for_naming(
    climbs: Iterable[Climb], start: LonLat, end: LonLat, route_m: float
) -> list[Climb]:
    """The climbs a route of `route_m` from `start` to `end` could ride: a route
    passes its climbs' feet and summits in order, so they lie within its own length's
    ellipse (the straight lines are no longer than the route between them), give or
    take the tolerance at each end."""
    reach = route_m + 2 * ON_CLIMB_M
    return [
        c
        for c in climbs
        if _metres(start, c.foot) + _metres(c.foot, c.summit) + _metres(c.summit, end) <= reach
    ]


# --- In words ----------------------------------------------------------------------


def _feet(metres: float) -> str:
    return f"{round(metres * FEET_PER_METRE):,} ft ({round(metres):,} m)"


def climb_words(climb: Climb) -> str:
    """ "Category 4 climb, 0.8 miles (1.3 km) at 5.0%, 262 ft (80 m) gained": the
    Climbs layer's name for it (`climb_categories.describe`, the map's accessible
    name) and the height gained, feet and metres each with a thousands separator
    ("2,930 ft (893 m)"), as the front end's `formatClimb` says it. The category and
    grade are the file's: its whole metres would not always score the same category
    again."""
    name = (
        "Hors catégorie (HC) climb"
        if climb.category == "HC"
        else f"Category {climb.category} climb"
    )
    miles = climb.length_m / METRES_PER_MILE
    mi = f"{miles:.1f} {'mile' if math.isclose(round(miles, 1), 1.0) else 'miles'}"
    return (
        f"{name}, {mi} ({climb.length_m / 1000:.1f} km) at {climb.grade_pct:.1f}%, "
        f"{_feet(climb.gain_m)} gained"
    )


def sentence(item: Ridden, scale: float = 1.0) -> str:
    """One line of the description: "At 3.2 mi (5.1 km): Category 4 climb, 0.8 miles
    (1.3 km) at 5.0%, 262 ft (80 m) gained, to the summit at 4.0 mi (6.4 km)." and,
    where the file says so, the trail it is on and that it is mostly unpaved."""
    climb = item.climb
    text = (
        f"At {point_words(item.start_m * scale)}: {climb_words(climb)}, "
        f"to the summit at {point_words(item.summit_m * scale)}."
    )
    if climb.name:
        text += f" On the {climb.name}."
    if climb.unpaved:
        text += " Mostly unpaved."
    return text


def row(item: Ridden, scale: float = 1.0) -> dict:
    """The answer's `hills_seek.climbs` row for a climb ridden."""
    climb = item.climb
    return {
        "id": climb.id,
        "category": climb.category,
        "length_m": round(climb.length_m),
        "gain_m": round(climb.gain_m),
        "grade_pct": climb.grade_pct,
        "from_m": round(item.start_m * scale),
        "to_m": round(item.summit_m * scale),
        "unpaved": climb.unpaved,
        "name": climb.name,
        "text": climb_words(climb),
        "sought": False,
    }


def entry(item: Ridden, scale: float = 1.0) -> dict:
    """A description entry (`routemaker.describe`'s shape), kind "climb": from the
    climb's foot to its summit along the route, scaled to the router's length."""
    at, to = item.start_m * scale, item.summit_m * scale
    return {
        "kind": "climb",
        "from_m": round(at),
        "to_m": round(to),
        "from_mi": round(at / METRES_PER_MILE, 2),
        "to_mi": round(to / METRES_PER_MILE, 2),
        "street": item.climb.name,
        "tier": None,
        "facility": None,
        "turn": None,
        "severity": None,
        "via": None,
        "group": None,
        "surface": "unpaved" if item.climb.unpaved else None,
        "text": sentence(item, scale),
        "text_lanes_hidden": None,
    }


def with_entries(description: list[dict] | None, added: list[dict]) -> list[dict] | None:
    """The description with `added` in route order, each before the entry that starts
    where it does or after it (so after the stretch it begins in); None stays None."""
    if description is None or not added:
        return description
    out: list[dict] = []
    pending = sorted(added, key=lambda e: e["from_m"])
    for item in description:
        while pending and pending[0]["from_m"] <= item["from_m"]:
            out.append(pending.pop(0))
        out.append(item)
    out.extend(pending)
    return out


# --- The seek ----------------------------------------------------------------------


@dataclass
class Seek:
    """What the seek did: the routes it found (each with the climbs it asked for) and
    the climbs a route might be named for."""

    trips: list[dict] = field(default_factory=list)
    asked_for: list[tuple[Climb, ...]] = field(default_factory=list)
    # The corridor's climbs, for naming the route kept.
    near: list[Climb] = field(default_factory=list)
    asked: int = 0
    limited: str | None = None

    def info(self) -> dict:
        return {
            "near": len(self.near),
            "asked": self.asked,
            "found": len(self.trips),
            "limited": self.limited,
        }


def seek(
    climbs: Sequence[Climb] | None,
    start: LonLat,
    end: LonLat,
    budget_m: float,
    already: Sequence[Sequence[LonLat]],
    ask: Callable[[list[LonLat]], dict | None],
    left: Callable[[], float],
    avoid_gravel: bool = False,
    limit: int = MAX_CANDIDATES,
) -> Seek:
    """Ask the router for routes through the best climbs near the line.

    `climbs` is the file's (None: no file, and nothing is asked: `limited` is
    "no_climbs"); `budget_m` the most a route may be (the dial's ratio times the
    direct route); `already` the router's own routes' lines, whose climbs are not
    asked for again. `ask(vias)` is one router call through the points, answering
    the trip or None where the router has no route, and raising OutOfTime; `left()`
    is the seconds the seek may still spend."""
    out = Seek()
    if climbs is None:
        out.limited = "no_climbs"
        return out
    out.near = in_corridor(climbs, start, end, budget_m, avoid_gravel)
    taken = {r.climb.id for line in already for r in ridden(line, out.near)}
    fresh = [c for c in out.near if c.id not in taken]
    for proposal in propose(fresh, start, end, budget_m, limit):
        if left() < ROUND_MIN_S:
            out.limited = "time"
            break
        out.asked += 1
        try:
            trip = ask(vias_of(proposal))
        except OutOfTime:
            out.limited = "time"
            break
        if trip and trip.get("legs"):
            out.trips.append(trip)
            out.asked_for.append(proposal)
    return out


__all__ = [
    "CLIMBS_FILE",
    "Climb",
    "OutOfTime",
    "Ridden",
    "Seek",
    "entry",
    "in_corridor",
    "load",
    "propose",
    "ridden",
    "seek",
    "via_points",
    "with_entries",
]
