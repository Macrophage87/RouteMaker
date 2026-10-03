"""Where to cut a long trip into legs the calm search can work on.

OWNER-DECISIONS 256 (FOLLOWUP-LONG-CALM): the calm search is worth running at any
length, but it is bounded in what it can do in one piece. Its exclusions are
capped (`refine.MAX_EXCLUDES`, 60 ways a round), a round's router call and trace
grow with the route, and past 19 mi (30 km) of straight line a cold /route took
33 s. So a trip is cut into legs of about LEG_TARGET_SPAN_M of straight line, each
searched on its own (`refine.refine_long`) and the legs put back together.

The cuts are points on the router's own route, so each leg's first route is, to
the router, the stretch of the whole route it already chose. They are placed
where the search can then work on either side of them: a leg's ends are kept
clear of exclusions (`refine.ENDPOINT_CLEARANCE_M`), so a cut in the middle of a
busy stretch would put that stretch out of reach. Each is the middle of a traced
edge, at least CLEAR_M from any LTS 3, 4 or Avoid stretch where there is such a
place within a window of the even split, and otherwise the place with the most
room. Pure: no database and no router.
"""

from __future__ import annotations

import bisect
import math

# The straight-line span a leg is cut to (metres): about 7.5 mi, which the calm
# search plans in a few seconds (docs/DEVELOPMENT.md, "Long Trailmaxxing trips").
LEG_TARGET_SPAN_M = 12_000.0
# A cut may move this share of a leg's length (route metres) either side of the
# even split, to find a place with room.
WINDOW = 0.25
# The room wanted either side of a cut (metres): the search's own clearance.
CLEAR_M = 500.0
# A cut is not made nearer than this to either end of its trip leg, and not on
# an edge shorter than MIN_EDGE_M (a node's middle, where a through point may snap
# to the road crossing it).
END_MARGIN_M = 400.0
MIN_EDGE_M = 30.0


def leg_count(span_m: float, target_m: float = LEG_TARGET_SPAN_M) -> int:
    """How many legs a stretch of `span_m` metres of straight line is cut into."""
    if span_m <= 0 or target_m <= 0:
        return 1
    return max(1, math.ceil(span_m / target_m))


def busy_runs(metres: list[float], busy: list[bool]) -> list[tuple[float, float]]:
    """The (from, to) metres along of each run of busy pieces, in order, from the
    pieces' lengths and whether each is LTS 3, 4 or Avoid."""
    runs: list[tuple[float, float]] = []
    along = 0.0
    for length, is_busy in zip(metres, busy, strict=False):
        end = along + length
        if is_busy:
            if runs and runs[-1][1] >= along - 1e-6:
                runs[-1] = (runs[-1][0], end)
            else:
                runs.append((along, end))
        along = end
    return runs


def clear_of(
    at: float, runs: list[tuple[float, float]], starts: list[float] | None = None
) -> float:
    """How far `at` is from the nearest busy run (0 inside one; infinity with
    none)."""
    if not runs:
        return math.inf
    starts = starts if starts is not None else [r[0] for r in runs]
    i = bisect.bisect_right(starts, at)
    best = math.inf
    if i:
        best = min(best, max(0.0, at - runs[i - 1][1]))
    if i < len(runs):
        best = min(best, max(0.0, runs[i][0] - at))
    return best


def split_points(
    marks: list[tuple[float, float, float, float]],
    runs: list[tuple[float, float]],
    lo: float,
    hi: float,
    count: int,
) -> list[tuple[float, float, float]]:
    """The (metres along, lon, lat) of the `count` - 1 cuts that make a stretch of
    the route from `lo` to `hi` metres into `count` legs. `marks` are the traced
    edges' middles as (metres along, lon, lat, edge metres) and `runs` the busy
    stretches (`busy_runs`). Fewer cuts than asked where the stretch has no place
    for one."""
    if count < 2 or hi <= lo:
        return []
    starts = [r[0] for r in runs]
    leg = (hi - lo) / count
    window = WINDOW * leg
    margin = min(END_MARGIN_M, leg / 4)
    cuts: list[tuple[float, float, float]] = []
    previous = lo
    for j in range(1, count):
        ideal = lo + leg * j
        choices = [
            (at, lon, lat)
            for at, lon, lat, edge in marks
            if abs(at - ideal) <= window
            and edge >= MIN_EDGE_M
            and at - lo >= margin
            and hi - at >= margin
            and at - previous >= margin
        ]
        if not choices:
            continue
        room = {c[0]: min(clear_of(c[0], runs, starts), CLEAR_M) for c in choices}
        # The most room (up to CLEAR_M), then the nearest the even split.
        best = min(choices, key=lambda c: (-room[c[0]], abs(c[0] - ideal), c[0]))
        cuts.append(best)
        previous = best[0]
    return cuts
