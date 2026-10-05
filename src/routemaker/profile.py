"""The route's elevation profile, as the route chart draws it (OWNER-DECISIONS 322, 323).

The router samples elevation every `ELEVATION_INTERVAL_M` along each leg
(`core.routing`), so a route's profile is those samples laid end to end by the
metres each leg takes. The chart wants three things from them beyond the heights:

- a grade at each sample, steady enough to read. 3DEP at 1 arc-second is about 30 m
  on the ground and good to a few metres, so the grade between two neighbouring
  samples is mostly noise (3 m over 30 m is 10%). The grade here is the rise over
  a window of `GRADE_SPAN_SAMPLES` samples either side of the sample (four
  samples, 120 m, at the router's 30 m spacing), which a real 5% hill shows
  through and a one-cell blip does not;
- the climbs, for the text alternative: where each starts, how long, how much it
  gains, its average and steepest grade, and the highest stress on it. They are
  the sustained climbs `routemaker.climbs` finds (the same dip and flat
  tolerances the hills slider prices), kept where they average
  `MIN_CLIMB_GRADE` or are steep somewhere;
- the grade bands the chart highlights.

A gap in the profile (a leg whose elevation was not returned) is a None height:
nothing is drawn or computed across it.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Sequence
from dataclasses import dataclass

from . import climbs, flow

# Samples either side of a sample that its grade is read across (the rise from the
# sample this many before to the one this many after, over the metres between).
GRADE_SPAN_SAMPLES = 2

# The chart's grade bands (OWNER-DECISIONS 322: "e.g. 5-8% and 8% or more"). A
# climb or a descent is in a band by the size of its grade.
BAND_STEEP_GRADE = 0.05
BAND_STEEPER_GRADE = 0.08

# A sustained climb is listed where it averages this grade, or is this steep
# somewhere on it (a short pitch in a long gentle climb).
MIN_CLIMB_GRADE = 0.03
MIN_CLIMB_PEAK_GRADE = 0.05


def band_of(grade: float | None) -> int:
    """0: under 5%, 1: 5-8%, 2: 8% or more, by the size of the grade either way."""
    if grade is None:
        return 0
    size = abs(grade)
    if size >= BAND_STEEPER_GRADE:
        return 2
    return 1 if size >= BAND_STEEP_GRADE else 0


@dataclass(frozen=True)
class Leg:
    """One routed leg's samples: where it begins along the route, how long it is, and
    the heights the router gave (metres, None where it had none), every `interval_m`."""

    start_m: float
    length_m: float
    heights: Sequence[float | None]


def sample_positions(legs: Sequence[Leg], interval_m: float) -> list[tuple[float, float | None]]:
    """(metres along the route, height) for every sample, in the order ridden.

    A leg's last sample never lies past the leg's end; the first sample of the next
    leg is at that same distance, so the joint is a pair of samples at one place. A leg
    the router gave no heights for is a gap: a None height at its start and its end, so
    nothing (a grade, a climb, a line) is read across it (as `core.routing.grade_profile`
    does).
    """
    out: list[tuple[float, float | None]] = []
    for leg in legs:
        if not leg.heights:
            out.append((leg.start_m, None))
            out.append((leg.start_m + max(leg.length_m, 0.0), None))
            continue
        for i, height in enumerate(leg.heights):
            out.append((leg.start_m + min(i * interval_m, leg.length_m), height))
    return out


def grades(samples: Sequence[tuple[float, float | None]]) -> list[float | None]:
    """The grade (rise over run, signed: positive uphill) at each sample, or None.

    Read across `GRADE_SPAN_SAMPLES` samples either side, stopping at a gap in the
    heights and at the ends of the route; a sample with no neighbour on either side
    has none.
    """
    out: list[float | None] = []
    n = len(samples)
    for i, (_m, height) in enumerate(samples):
        if height is None:
            out.append(None)
            continue
        lo = i
        while lo > 0 and i - lo < GRADE_SPAN_SAMPLES and samples[lo - 1][1] is not None:
            lo -= 1
        hi = i
        while hi < n - 1 and hi - i < GRADE_SPAN_SAMPLES and samples[hi + 1][1] is not None:
            hi += 1
        run = samples[hi][0] - samples[lo][0]
        if hi == lo or run <= 0:
            out.append(None)
            continue
        out.append((samples[hi][1] - samples[lo][1]) / run)
    return out


@dataclass(frozen=True)
class Climb:
    """One sustained climb of the profile."""

    from_m: float
    to_m: float
    gain_m: float
    avg_grade: float
    max_grade: float
    # The highest stress tier of the route's sections it rides over (1-5), or None.
    tier: int | None


def _worst_tier(spans: Sequence[dict], from_m: float, to_m: float) -> int | None:
    tiers = [
        span["tier"]
        for span in spans
        if span.get("tier") is not None and span["from_m"] < to_m and span["to_m"] > from_m
    ]
    return max(tiers) if tiers else None


def inside(sample_m: Sequence[float], from_m: float, to_m: float) -> range:
    """The indices of the samples from `from_m` to `to_m` (both included), for sample
    positions in route order (they never decrease): two bisections, not a scan."""
    return range(bisect.bisect_left(sample_m, from_m), bisect.bisect_right(sample_m, to_m))


def climb_list(
    samples: Sequence[tuple[float, float | None]],
    grade_at: Sequence[float | None],
    spans: Sequence[dict] = (),
    runs: Sequence[climbs.Run] | None = None,
) -> list[Climb]:
    """The route's sustained climbs worth listing, in the order ridden. `runs` is the
    profile's `climbs.runs`, computed here when not given."""
    if runs is None:
        runs = climbs.runs(list(samples))
    sample_m = [m for m, _h in samples]
    found = []
    for run in runs:
        if run.rise_m <= 0:
            continue
        on = [
            grade_at[i] for i in inside(sample_m, run.start_m, run.end_m) if grade_at[i] is not None
        ]
        peak = max(max(on, default=run.grade), run.grade)
        if run.grade < MIN_CLIMB_GRADE and peak < MIN_CLIMB_PEAK_GRADE:
            continue
        found.append(
            Climb(
                from_m=run.start_m,
                to_m=run.end_m,
                gain_m=run.rise_m,
                avg_grade=run.grade,
                max_grade=peak,
                tier=_worst_tier(spans, run.start_m, run.end_m),
            )
        )
    return found


# The most samples a route answer carries (operations review, SHOULD-FIX 3): every
# sample up to about 60 km (37 mi) at 30 m, and on a longer route close to this many
# (never more than a window's picks over it: `thin`). The
# chart is 300-700 px wide, so more would be many samples to a pixel.
MAX_SAMPLES = 2000


def _window_picks(
    heights: Sequence[float | None],
    grade_at: Sequence[float | None],
    riders: Sequence[float | None] | None,
    window: int,
) -> set[int]:
    n = len(heights)
    keep = {0, n - 1}
    for start in range(0, n, window):
        part = range(start, min(start + window, n))
        graded = [i for i in part if grade_at[i] is not None]
        keep.add(max(graded, key=lambda i: abs(grade_at[i])) if graded else part[0])
        known = [i for i in part if heights[i] is not None]
        if known:
            keep.add(max(known, key=lambda i: heights[i]))
            keep.add(min(known, key=lambda i: heights[i]))
        gaps = [i for i in part if heights[i] is None]
        if gaps:
            keep.add(gaps[0])
        if riders is not None:
            known = [i for i in part if riders[i] is not None]
            if known:
                keep.add(min(known, key=lambda i: riders[i]))
            unknown = [i for i in part if riders[i] is None]
            if unknown:
                keep.add(unknown[0])
    return keep


# At most this fraction (1 / N) of the samples sent go to the bottleneck runs' ends.
BOTTLENECK_END_SHARE = 4


def _bottleneck_ends(riders: Sequence[float | None] | None) -> set[int]:
    """The first and last sample of each run of riders figures under the first band's
    edge (a bottleneck: flow.BAND_EDGES), as the front end's bottlenecks table reads a
    run (profileChart.ts bottleneckRows: a known figure under 60 starts or continues one,
    anything else ends it). The figure is rounded first, as the answer sends it
    (routing._int_or_none), so 59.6 is not a bottleneck here either."""
    if riders is None:
        return set()
    edge = flow.BAND_EDGES[0]
    ends: set[int] = set()
    start: int | None = None
    for i, r in enumerate(riders):
        if r is not None and round(r) < edge:
            if start is None:
                start = i
                ends.add(i)
        elif start is not None:
            ends.add(i - 1)
            start = None
    if start is not None:
        ends.add(len(riders) - 1)
    return ends


# The most picks one window makes: its steepest grade, its highest and lowest heights and
# its first gap; on a Mass Ride its lowest riders figure and its first unknown one too.
WINDOW_PICKS = 4
WINDOW_PICKS_MASS = 6


def thin(
    heights: Sequence[float | None],
    grade_at: Sequence[float | None],
    riders: Sequence[float | None] | None = None,
    limit: int = MAX_SAMPLES,
) -> list[int]:
    """The indices of the samples to send, in order: all of them up to `limit`, and on
    a longer route close to `limit`, window by window. Each window keeps its steepest
    grade (so the grade bands survive), its highest and lowest heights (so a summit and
    a valley floor do, where the grade is near 0: correctness re-review R2), on a Mass
    Ride its lowest riders figure (so a bottleneck does), and its first gap in the
    heights or the riders (so a gap stays a gap); the route's first and last samples are
    always kept. On a Mass Ride the first and last sample of every run under the first
    band's edge (60 riders a minute, a bottleneck) are kept too, so the chart's
    bottlenecks table measures each run from its own ends, not from the window picks
    inside it (r3 correctness, N1). The grades, climbs and riders are worked out on every
    sample before this, so no figure changes.

    The window is first sized for the most picks a window can make, which keeps the
    answer within `limit` (and a window's picks over it at most). Most windows make
    fewer (the steepest sample is often the highest or lowest too, and gaps are rare),
    so the window is then narrowed to the narrowest that keeps the picks actually made
    within `limit` (operations re-review A)."""
    n = len(heights)
    if n <= limit:
        return list(range(n))
    most = WINDOW_PICKS_MASS if riders is not None else WINDOW_PICKS
    ends = _bottleneck_ends(riders)
    # The windows share what the bottleneck ends leave. A route with more than a quarter of
    # the limit in run ends (hundreds of separate bottlenecks: not a real Mass Ride) keeps
    # none, so the answer stays within the limit and a window's picks.
    if len(ends) > limit // BOTTLENECK_END_SHARE:
        ends = set()
    room = limit - len(ends)
    window = math.ceil(n * most / room)
    keep = _window_picks(heights, grade_at, riders, window) | ends
    # The narrowest window that stays within `limit`, by bisection (a few passes, each one
    # pass over the samples): no narrower than one pick a window could fit.
    lo, hi = math.ceil(n / room), window
    while lo < hi:
        mid = (lo + hi) // 2
        again = _window_picks(heights, grade_at, riders, mid) | ends
        if len(again) <= limit:
            hi, keep = mid, again
        else:
            lo = mid + 1
    return sorted(keep)
