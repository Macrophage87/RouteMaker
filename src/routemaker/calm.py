"""The rolling stress score along a route, in calm miles per mile (OWNER-DECISIONS 460.12,
461, 461a-e, 469b; docs/DEVELOPMENT.md "The rolling stress chart").

460.12: "A chart of rolling traffic stress makes more sense than a strip. That way, spikes
show up." 461c: build it from the costs the routing already charges, "a sort of hidden
number". 461d: the metric is calm miles per actual mile, junctions included. 461e: a
window of about a mile, centred on each point, cut at the route's ends, each junction
counted once in every window that holds it.

A calm mile is a mile of quiet street (no lane, LTS 1-2), the unit RouteMaker's own score
already prices in (`refine.QUIET_COST_FACTOR`: a quiet metre costs the router 2.2 times its
time). A stretch's multiplier `M` is what a metre of it costs over what a quiet metre
costs, at the rider's preset and slider position:

- **The router's tier cost.** `1 + added / 2.2`, where `added` is the cost a metre of LTS 3
  or LTS 4 adds, as a multiple of its time, for Valhalla's `use_roads` at that slider
  position. Valhalla's figure depends on the road's speed and lanes; the five modelled road
  types of docs/DEVELOPMENT.md "Graded stress" give a range at each position, and the
  middle of the range is used here (`ADDED`), between positions linearly. So the score is
  an **estimate**: it follows the tier and the slider but not each road's own speed and
  lanes (docs/stress/stress-number.md section 4, "Fallback"). Avoid is priced as LTS 4 per
  metre (the router's own rule) and pays its entry charge where the route enters it.
  On the no-trail graph LTS 4 is not graded, so it costs what LTS 3 does.
- **The facility.** At LTS 1-2 a traffic-free path, a protected lane and a painted lane cost
  less than a quiet street (`lua/routemaker_remap.lua` facility classes: `0.1 + 0.9u`,
  `(0.15 + 0.6u) x stress`, `(0.9 + 0.05u) x stress`), so they count below 1. Not on the
  no-trail graph, which has no facility classes. At LTS 3 and up the tier's figure stands.
- **Above 80 on the slider.** The calm rate prices each tier's metres at its exposure weight
  (`refine.Analysis.score`): `+ rate x w(L)`.
- **The top of the slider (100).** There is no per-metre price; the worth rule's exchange
  stands in: `1 + 5 x w(L)` with no target, `1 + 10 x w(L)` with one (the price up to the
  target, 435 "One rule", since the answer is fitted to it), at the standard 1 / 2 / 3
  weights (`refine.WORTH_*`).

A junction counts what the ranking charges for it (461c, 461d: "today's distance-equivalent
penalty ... times its factors and the preset's intersection weight"): the junction model's
cost (`cost_ft`) times `refine.intersection_weight` at the slider position (0.25 at 0, 1
from 70). At the top of the slider the worth rule's exchange stands in, as it does for the
stretches: a red junction counts its cost at the LTS 4 weight, an orange one at the LTS 3
weight, times the exchange (`refine.stress_weight_m`), and an unflagged one nothing.

An unrated stretch has no number: it counts in neither the calm miles nor the miles, a
junction or an Avoid entry inside it is not counted either, and a window that is all
unrated has no value.
"""

from __future__ import annotations

import bisect
from collections.abc import Sequence
from dataclasses import dataclass

# 461e: "a reasonable roll, maybe a mile or so". One setting, so it can be tuned.
WINDOW_M = 1609.344
METRES_PER_FOOT = 0.3048
# A quiet metre's cost over its time (refine.QUIET_COST_FACTOR; restated, as this package
# does not import core).
QUIET_FACTOR = 2.2
# A quiet street's roadway stress term in Valhalla's `time x (1 + accommodation x stress)`:
# the quiet metre's 2.2 less its time.
QUIET_STRESS = QUIET_FACTOR - 1.0

# The added cost per metre of LTS 3 and LTS 4, as a multiple of its time, at each `use_roads`
# the model was read at (docs/DEVELOPMENT.md "Graded stress"; docs/stress/routing-costs.md
# section 1): the middle of the five road types' range. use_roads 1.0, 0.871 and 0.486 are
# positions 0, 10 and 40 today; 0.10 is 70 (Default); 0.0 is 80 and above.
ADDED: tuple[tuple[float, float, float], ...] = (
    # (use_roads, LTS 3, LTS 4)
    (0.0, (4.75 + 12.84) / 2, (32.14 + 40.52) / 2),
    (0.10, (4.13 + 10.54) / 2, (26.08 + 32.62) / 2),
    (0.486, (2.05 + 4.06) / 2, (9.63 + 11.56) / 2),
    (0.871, (0.47 + 0.80) / 2, (2.44 + 2.94) / 2),
    (1.0, 0.0, (0.82 + 1.14) / 2),
)

# The worth rule's exchange at the top of the slider (refine.WORTH_DEFAULT; with a target,
# refine.WORTH_UP_TO_TARGET, the price of the miles up to it, OWNER-DECISIONS 435) and its
# level weights (refine.WORTH_WEIGHTS: the standard 1 / 2 / 3).
WORTH_DEFAULT = 5.0
WORTH_UP_TO_TARGET = 10.0
WORTH_WEIGHTS = {3: 1.0, 4: 2.0, 5: 3.0}

# Avoid's entry charge (presets.AVOID_ENTRY_PENALTY_S), cost seconds.
AVOID_ENTRY_S = 1800.0


@dataclass(frozen=True)
class Pricing:
    """What a ride's slider position charges, as the score needs it."""

    use_roads: float
    # Metres of detour per metre of each tier above 80 (presets.calm_rate_for), and the
    # preset's exposure weights by tier (3, 4, 5).
    rate: float = 0.0
    weights: tuple[float, float, float] = (1.0, 2.0, 3.0)
    # The top of the slider (presets.maxcalm_for), and whether the rider set a target.
    maxcalm: bool = False
    target: bool = False
    # The no-trail graph: no grading and no facility classes.
    no_trail: bool = False
    # The router's cost of a quiet metre at this ride's speed, cost seconds
    # (refine.quiet_cost_per_m), for the Avoid entry charge.
    quiet_cost_s: float = 0.44
    # How much of a junction's cost the ranking counts at this position
    # (refine.intersection_weight).
    junction_weight: float = 1.0


def _added(use_roads: float) -> tuple[float, float]:
    """LTS 3's and LTS 4's added cost per metre at a `use_roads`, linear between the
    modelled positions."""
    u = min(max(use_roads, 0.0), 1.0)
    for (u0, a3, a4), (u1, b3, b4) in zip(ADDED, ADDED[1:], strict=False):
        if u0 <= u <= u1:
            t = 0.0 if u1 == u0 else (u - u0) / (u1 - u0)
            return a3 + t * (b3 - a3), a4 + t * (b4 - a4)
    return ADDED[-1][1], ADDED[-1][2]


def facility_factor(facility: str | None, use_roads: float) -> float:
    """A calm (LTS 1-2) metre's cost over a quiet street's, by its facility class."""
    u = min(max(use_roads, 0.0), 1.0)
    if facility == "path":
        return (1.0 + 0.1 + 0.9 * u) / QUIET_FACTOR
    if facility == "protected":
        return (1.0 + (0.15 + 0.6 * u) * QUIET_STRESS) / QUIET_FACTOR
    if facility == "lane":
        return (1.0 + (0.9 + 0.05 * u) * QUIET_STRESS) / QUIET_FACTOR
    return 1.0


def multiplier(tier: int | None, facility: str | None, pricing: Pricing) -> float | None:
    """Calm metres a metre of this stretch counts for; None where it is not rated."""
    if tier is None:
        return None
    if tier <= 2:
        return 1.0 if pricing.no_trail else facility_factor(facility, pricing.use_roads)
    level = min(tier, 5)
    if pricing.maxcalm:
        worth = WORTH_UP_TO_TARGET if pricing.target else WORTH_DEFAULT
        return 1.0 + worth * WORTH_WEIGHTS[level]
    lts3, lts4 = _added(pricing.use_roads)
    added = lts3 if level == 3 or pricing.no_trail else lts4
    weight = pricing.weights[level - 3]
    return 1.0 + added / QUIET_FACTOR + pricing.rate * weight


def avoid_entry_m(pricing: Pricing) -> float:
    """Avoid's entry charge as quiet metres at this ride's speed."""
    return AVOID_ENTRY_S / pricing.quiet_cost_s if pricing.quiet_cost_s > 0 else 0.0


def junction_m(cost_ft: float, severity: str | None, flagged: bool, pricing: Pricing) -> float:
    """Calm metres a junction counts for at this ride's position."""
    cost_m = max(cost_ft, 0.0) * METRES_PER_FOOT
    if pricing.maxcalm:
        worth = WORTH_UP_TO_TARGET if pricing.target else WORTH_DEFAULT
        level = {"red": 4, "orange": 3}.get(severity or "") if flagged else None
        return worth * WORTH_WEIGHTS[level] * cost_m if level else 0.0
    return cost_m * pricing.junction_weight


# A band edge sits at least this far above a quiet street's 1, so an all-quiet route never
# reads as LTS 3 where LTS 3 costs nothing extra (at 0 on the slider).
MIN_BAND_GAP = 0.05


def bands(pricing: Pricing) -> tuple[float, float]:
    """Where the words change (docs/stress/stress-number.md "Words as a guide"): the
    half-step midpoints 2.5 and 3.5 (461a), from a quiet street's 1. Where LTS 3 costs
    no more than a quiet street (0 on the slider) there is no LTS 3 band: both edges are
    the 3.5 midpoint."""
    m3 = multiplier(3, None, pricing) or 1.0
    m4 = multiplier(4, None, pricing) or 1.0
    high = max((m3 + m4) / 2, 1.0 + MIN_BAND_GAP)
    low = (1.0 + m3) / 2
    if low < 1.0 + MIN_BAND_GAP:
        low = high
    return low, high


@dataclass(frozen=True)
class Step:
    """One stretch of the route at its own multiplier (None: not rated)."""

    from_m: float
    to_m: float
    ratio: float | None
    tier: int | None


@dataclass(frozen=True)
class Point:
    """Calm metres counted at one place: a junction's cost, or Avoid's entry charge."""

    m: float
    calm_m: float
    kind: str  # "junction" or "avoid_entry"
    severity: str | None = None


def steps_of(spans: Sequence[dict], pricing: Pricing) -> list[Step]:
    """The route's stress sections (`routing.stress_spans`) at their multipliers, adjacent
    equal ones joined."""
    out: list[Step] = []
    for span in spans:
        lo, hi = float(span["from_m"]), float(span["to_m"])
        if hi <= lo:
            continue
        tier = span.get("tier")
        ratio = multiplier(tier, span.get("facility"), pricing)
        if out and out[-1].to_m == lo and out[-1].ratio == ratio and out[-1].tier == tier:
            out[-1] = Step(out[-1].from_m, hi, ratio, tier)
        else:
            out.append(Step(lo, hi, ratio, tier))
    return out


def points_of(steps: Sequence[Step], events: Sequence | None, pricing: Pricing) -> list[Point]:
    """The calm metres counted at a place, in route order: every junction the model
    charges for (flagged or not), and each entry into Avoid."""
    out: list[Point] = []
    for event in events or ():
        flagged = bool(getattr(event, "flagged", False))
        severity = getattr(event, "severity", None) if flagged else None
        counted = junction_m(
            float(getattr(event, "cost_ft", 0.0) or 0.0), severity, flagged, pricing
        )
        if counted > 0 and _rated_at(steps, float(event.m)):
            out.append(Point(float(event.m), counted, "junction", severity))
    entry = avoid_entry_m(pricing)
    previous: Step | None = None
    for step in steps:
        joined = previous is not None and previous.tier == 5 and previous.to_m >= step.from_m
        if step.tier == 5 and not joined and entry > 0:
            out.append(Point(step.from_m, entry, "avoid_entry"))
        previous = step
    return sorted(out, key=lambda p: p.m)


def _rated_at(steps: Sequence[Step], m: float) -> bool:
    """Whether a place lies on a rated stretch (either side of a joint will do)."""
    i = bisect.bisect_right([s.from_m for s in steps], m) - 1
    for j in (i, i - 1):
        if 0 <= j < len(steps) and steps[j].from_m <= m <= steps[j].to_m:
            if steps[j].ratio is not None:
                return True
    return False


class Rolling:
    """The calm metres and rated metres up to any distance, for windows in O(log n)."""

    def __init__(self, steps: Sequence[Step], points: Sequence[Point]) -> None:
        self.edges: list[float] = [0.0]
        self.calm: list[float] = [0.0]
        self.rated: list[float] = [0.0]
        self.ratios: list[float | None] = []
        for step in steps:
            if step.from_m > self.edges[-1]:
                # A hole between sections: not rated.
                self._push(step.from_m, None)
            self._push(step.to_m, step.ratio)
        self.point_m = [p.m for p in points]
        self.point_sum = [0.0]
        for p in points:
            self.point_sum.append(self.point_sum[-1] + p.calm_m)

    def _push(self, to_m: float, ratio: float | None) -> None:
        length = to_m - self.edges[-1]
        self.edges.append(to_m)
        self.ratios.append(ratio)
        self.calm.append(self.calm[-1] + (length * ratio if ratio is not None else 0.0))
        self.rated.append(self.rated[-1] + (length if ratio is not None else 0.0))

    @property
    def end_m(self) -> float:
        return self.edges[-1]

    def _upto(self, x: float) -> tuple[float, float]:
        """(calm metres, rated metres) from the start to `x`."""
        if x <= 0:
            return 0.0, 0.0
        if x >= self.edges[-1]:
            return self.calm[-1], self.rated[-1]
        i = bisect.bisect_right(self.edges, x) - 1
        ratio = self.ratios[i]
        part = x - self.edges[i]
        return (
            self.calm[i] + (part * ratio if ratio is not None else 0.0),
            self.rated[i] + (part if ratio is not None else 0.0),
        )

    def points_between(self, lo: float, hi: float) -> float:
        a = bisect.bisect_left(self.point_m, lo)
        b = bisect.bisect_right(self.point_m, hi)
        return self.point_sum[b] - self.point_sum[a]

    def at(self, x: float, window_m: float = WINDOW_M) -> float | None:
        """Calm miles per mile over the window centred on `x`, cut at the route's ends;
        None where the window holds no rated metre."""
        lo = max(0.0, x - window_m / 2)
        hi = min(self.end_m, x + window_m / 2)
        calm_hi, rated_hi = self._upto(hi)
        calm_lo, rated_lo = self._upto(lo)
        rated = rated_hi - rated_lo
        if rated <= 0:
            return None
        return (calm_hi - calm_lo + self.points_between(lo, hi)) / rated

    def total_calm_m(self) -> float:
        return self.calm[-1] + self.point_sum[-1]

    def total_rated_m(self) -> float:
        return self.rated[-1]


def peak_index(
    spans: Sequence[dict],
    events: Sequence | None,
    pricing: Pricing,
    sample_m: Sequence[float],
    window_m: float = WINDOW_M,
) -> int | None:
    """The sample whose window scores highest (the first of a tie), read over every sample
    before a long route is thinned, so the thinned answer keeps it."""
    steps = steps_of(spans, pricing)
    rolling = Rolling(steps, points_of(steps, events, pricing))
    best: int | None = None
    best_r = -1.0
    for i, m in enumerate(sample_m):
        r = rolling.at(m, window_m)
        if r is not None and r > best_r:
            best, best_r = i, r
    return best


def score(
    spans: Sequence[dict],
    events: Sequence | None,
    pricing: Pricing,
    sample_m: Sequence[float],
    window_m: float = WINDOW_M,
) -> dict:
    """The rolling score at each of `sample_m`, the sections at their own multipliers, the
    points counted, the route's total, and where the words change: the route answer's
    `profile.calm` (core.api.ProfileCalmOut)."""
    steps = steps_of(spans, pricing)
    points = points_of(steps, events, pricing)
    rolling = Rolling(steps, points)
    low, high = bands(pricing)
    ratio = [rolling.at(m, window_m) for m in sample_m]
    return {
        "window_m": round(window_m),
        "ratio": [_round(r) for r in ratio],
        "steps": [
            {
                "from_m": round(s.from_m),
                "to_m": round(s.to_m),
                "ratio": _round(s.ratio),
                "tier": s.tier,
            }
            for s in steps
        ],
        # Only what the chart marks: the flagged junctions and the Avoid entries. Every
        # junction is in `ratio` and the total (operations review: the answer's size).
        "points": [
            {"m": round(p.m), "calm_m": round(p.calm_m), "kind": p.kind, "severity": p.severity}
            for p in points
            if p.kind != "junction" or p.severity is not None
        ],
        "total_calm_m": round(rolling.total_calm_m()),
        "rated_m": round(rolling.total_rated_m()),
        "junctions_counted": events is not None,
        "bands": [_round(low), _round(high)],
        "estimate": True,
    }


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 2)
