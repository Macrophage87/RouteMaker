"""Mass Ride routing by road capacity: what a route's riders a minute cost a group of the
anticipated ride size, and the figures an organiser (or an assistant) improves a route from.

PLAN, "Mass Ride map and mode": the route's number is its bottleneck, roads too narrow for
the chosen ride size are "flagged on the map and penalised in routing, so the same road can
be fine for 100 riders and a problem for 1,500" (item 128), and "every place the route moves
between roads of different throughput costs a transition penalty, up or down", quadratic in
the size of the change (items 120 to 123: "It tends to scatter the group", "maybe square the
penalty"), step-down heavier than step-up.

The price, in seconds, is added to the router's own cost when a Mass Ride chooses among the
router's routes (`core.routing.choose_by_capacity`):

- Narrow: a road carries `riders_per_min(width)` (`routemaker.flow`, the level figure the
  capacity map colours by; grade is the hill price's). A road needs the ride size over a
  `HOLD_MINUTES` hold (the riders chart's dashed line, `frontend/src/lib/profileChart.ts`
  `rideNeed`): riders / 5 a minute. Where a road carries less, the flow through it is held to
  what it carries, so the group crosses it slower by the shortfall: each metre costs its time
  at cruise times (need / carried - 1), at most `NARROW_RATIO_CAP`. A stretch marked Avoid
  carries nothing (OWNER-DECISIONS 325) and pays the cap.
- Outside the District: not priced but measured (`outside_m`, the route's `outside_dc`
  stretches). The choice takes the route that leaves DC least before any price (the owner,
  2026-10-29: "Don't leave DC on a mass ride. The laws in other jurisdictions are too
  different for us to accommodate a multi-jurisdiction mass ride."; `core.routing
  .choose_by_capacity`).
- Transitions: at each change between roads whose figures differ by `STEP_IGNORED` or more,
  weight x (|before - after| / the larger)^2, `STEP_DOWN_S` stepping down and `STEP_UP_S`
  stepping up, scaled for the group as the plan's intersection penalties are (item 171: the
  ride size over 500, between one half and three times). Stretches shorter than
  `STEP_MIN_M` (a junction's own few metres) are not a change of road.

The weights are this module's proposals, for the owner to confirm (PLAN, "Parameters for the
owner to confirm": the transition weights and threshold, the hold). Not priced here: signal
waits, pavement and tight turns (PLAN's other reductions) and the busy-road crossings
(items 133-136), which the route answer reports but the choice does not yet weigh.

The corker load (`corker_load`) is the front end's (`profileChart.ts` `corkerLoad`, PLAN item
139, the owner 2026-10-10) in Python, so the API and the assistants' tool can say it too; the
two are held to the same figures by tests/test_mass_route.py.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from . import flow

# The ride size slider (PLAN items 128, 129): 100 to 2,000 riders, 500 by default; the front
# end's RIDE_SIZE_MIN, RIDE_SIZE_MAX and RIDE_SIZE_DEFAULT (`frontend/src/lib/dials.ts`).
RIDE_SIZE_MIN = 100
RIDE_SIZE_MAX = 2_000
RIDE_SIZE_DEFAULT = 500
# The longest hold at a junction accepted (`profileChart.ts` RIDE_HOLD_MINUTES; a proposal).
HOLD_MINUTES = 5

NARROW_RATIO_CAP = 3.0
OUTSIDE_DC_NOTE = "outside_dc"
STEP_DOWN_S = 60.0
STEP_UP_S = 30.0
STEP_IGNORED = 0.15
STEP_MIN_M = 25.0
# The group scale (PLAN item 171's proposal): the base is 500 riders, bounded to 0.5-3x.
GROUP_BASE_RIDERS = 500
GROUP_SCALE_MIN = 0.5
GROUP_SCALE_MAX = 3.0

# The corker count (`profileChart.ts`): the rotation factor and the approaches.
ROTATION_FACTOR = 2
CORKERS_TWO_WAY = 2
CORKERS_ONE_WAY = 1

AVOID_NOTE = "avoid"


def fit_ride_size(riders: int | None) -> int:
    """The ride size in force: the rider's, held to the slider's range, else the default."""
    if riders is None:
        return RIDE_SIZE_DEFAULT
    return min(RIDE_SIZE_MAX, max(RIDE_SIZE_MIN, int(riders)))


def need_per_min(riders: int) -> int:
    """Riders a minute a road needs for the group to pass within HOLD_MINUTES (`rideNeed`)."""
    return math.ceil(riders / HOLD_MINUTES)


def group_scale(riders: int) -> float:
    return min(GROUP_SCALE_MAX, max(GROUP_SCALE_MIN, riders / GROUP_BASE_RIDERS))


def _rpm(stretch: Sequence) -> float | None:
    """A stretch's level riders a minute: None where not known (untraced, outside DC), 0 on
    a stretch marked Avoid."""
    width = stretch[1]
    if width is not None:
        return flow.level_riders_per_min(width)
    note = stretch[2] if len(stretch) > 2 else None
    return 0.0 if note == AVOID_NOTE else None


@dataclass
class CapacityPrice:
    """A route's capacity price for a ride size, seconds, and what it is made of."""

    riders: int
    need_per_min: int
    narrow_s: float = 0.0
    outside_m: float = 0.0
    transition_s: float = 0.0
    transitions: int = 0
    below_need_m: float = 0.0
    narrowest_riders_per_min: float | None = None
    narrowest_m: float | None = None

    @property
    def total_s(self) -> float:
        return self.narrow_s + self.transition_s


def price(stretches: Sequence[Sequence], riders: int) -> CapacityPrice:
    """The capacity price of a route of (metres, usable width or None, note) stretches in the
    order ridden (`core.routing._flow_stretches`) for a group of `riders`."""
    need = need_per_min(riders)
    out = CapacityPrice(riders=riders, need_per_min=need)
    scale = group_scale(riders)
    at = 0.0
    last: float | None = None
    for stretch in stretches:
        metres = float(stretch[0])
        rpm = _rpm(stretch)
        if rpm is None and len(stretch) > 2 and stretch[2] == OUTSIDE_DC_NOTE:
            out.outside_m += metres
        if rpm is not None:
            if out.narrowest_riders_per_min is None or rpm < out.narrowest_riders_per_min:
                out.narrowest_riders_per_min, out.narrowest_m = rpm, at
            if rpm < need:
                ratio = NARROW_RATIO_CAP if rpm <= 0 else min(need / rpm - 1, NARROW_RATIO_CAP)
                out.narrow_s += metres / flow.CRUISE_PACE_MS * ratio
                out.below_need_m += metres
            if rpm > 0 and metres >= STEP_MIN_M:
                if last is not None:
                    change = abs(last - rpm) / max(last, rpm)
                    if change >= STEP_IGNORED:
                        weight = STEP_DOWN_S if rpm < last else STEP_UP_S
                        out.transition_s += weight * change * change * scale
                        out.transitions += 1
                last = rpm
        at += metres
    return out


# ---- The corker load (`profileChart.ts`, "The corker load") --------------------------------


def approaches_of(crossing: dict) -> int:
    """1 on a one-way road, otherwise 2 (two-way, divided, or not known)."""
    if crossing.get("oneway") is True and crossing.get("divided") is not True:
        return CORKERS_ONE_WAY
    return CORKERS_TWO_WAY


def corkers_for(crossing: dict) -> int:
    """One corker for each approach lane, or one an approach at a traffic signal (PLAN 139)."""
    approaches = approaches_of(crossing)
    if crossing.get("control") == "signal":
        return approaches
    lanes = crossing.get("approach_lanes")
    good = (
        isinstance(lanes, (int, float))
        and not isinstance(lanes, bool)
        and math.isfinite(lanes)
        and lanes >= 1
    )
    # Rounded half up, as the front end's Math.round.
    return approaches * (math.floor(lanes + 0.5) if good else 1)


@dataclass
class _Road:
    riders: int
    m: list[float]
    density: list[float]
    held: list[float] = field(default_factory=list)


def _road(profile: dict, riders: int) -> _Road | None:
    pace = (profile.get("flow") or {}).get("cruise_pace_ms")
    m = profile.get("m") or []
    if not pace or pace <= 0 or not m:
        return None
    levels = profile.get("level_riders_per_min") or []
    known = sorted(v for v in levels if v is not None and v > 0)
    typical = (
        known[len(known) // 2]
        if known
        else (profile.get("flow") or {}).get("default_level_riders_per_min")
    )
    if not typical or typical <= 0:
        return None
    density = []
    for i in range(len(m)):
        level = levels[i] if i < len(levels) else None
        density.append(((level if level is not None and level > 0 else typical) / 60) / pace)
    held = [0.0]
    for i in range(1, len(m)):
        held.append(held[i - 1] + density[i - 1] * max(m[i] - m[i - 1], 0))
    return _Road(riders, list(m), density, held)


def _held_to(road: _Road, x: float) -> float:
    last = len(road.m) - 1
    if x <= road.m[0]:
        return (x - road.m[0]) * road.density[0]
    if x >= road.m[last]:
        return road.held[last] + (x - road.m[last]) * road.density[last]
    i = bisect.bisect_right(road.m, x) - 1
    return road.held[i] + (x - road.m[i]) * road.density[i]


def _place_holding(road: _Road, riders: float) -> float:
    last = len(road.m) - 1
    if riders <= 0:
        return road.m[0] + riders / road.density[0]
    if riders >= road.held[last]:
        return road.m[last] + (riders - road.held[last]) / road.density[last]
    i = bisect.bisect_right(road.held, riders) - 1
    k = i
    while k < last and road.held[k + 1] == road.held[i] and road.m[k + 1] == road.m[k]:
        k += 1
    return road.m[k] + (riders - road.held[k]) / road.density[k]


def _exit_of(road: _Road, j: float) -> float:
    """Where the head is when the tail passes `j`."""
    return _place_holding(road, _held_to(road, j) + road.riders)


def corker_load(profile: dict | None, total_m: float, riders: int) -> dict | None:
    """The corkers a group of `riders` holds at once along the route (the most at once, the
    ride's headline of that times ROTATION_FACTOR, and each junction needing corkers), or
    None where the intersections were not checked or the profile gives no group length."""
    if not profile or profile.get("crossings") is None:
        return None
    road = _road(profile, riders)
    if road is None:
        return None
    length = max(total_m, 0.0)
    junctions = []
    for crossing in profile["crossings"]:
        at_m = crossing.get("m")
        if not crossing.get("corkers_needed") or not isinstance(at_m, (int, float)):
            continue
        if not math.isfinite(at_m):
            continue
        at = min(max(float(crossing["m"]), 0.0), length)
        junctions.append(
            {
                "m": round(at),
                "street": crossing.get("street"),
                "corkers": corkers_for(crossing),
                "_at": at,
                "_exit": _exit_of(road, at),
            }
        )
    junctions.sort(key=lambda j: j["_at"])
    cuts = sorted({0.0, length, *(j["_at"] for j in junctions), *(j["_exit"] for j in junctions)})
    peak, peak_m, peak_count = 0, None, 0
    for x in cuts:
        if x < 0 or x > length:
            continue
        held = [j for j in junctions if j["_at"] <= x < j["_exit"]]
        corkers = sum(j["corkers"] for j in held)
        if corkers > peak:
            peak, peak_m, peak_count = corkers, x, len(held)
    unchecked = [
        r
        for r in profile.get("unchecked") or []
        if r.get("to_m", 0) > r.get("from_m", 0) and r.get("from_m", 0) < length
    ]
    partial = profile.get("crossings_complete") is False
    return {
        "headline": math.ceil(peak * ROTATION_FACTOR),
        "at_least": partial or bool(unchecked),
        "most_at_once": peak,
        "most_at_once_m": None if peak_m is None else round(peak_m),
        "junctions_held_then": peak_count,
        "rotation_factor": ROTATION_FACTOR,
        "junctions": [{k: v for k, v in j.items() if not k.startswith("_")} for j in junctions],
    }


# ---- The answer's summary --------------------------------------------------------------------

# The most narrow stretches listed in the answer, the longest first.
NARROW_LISTED = 15


def narrow_stretches(stretches: Sequence[Sequence], need: int) -> list[dict]:
    """The runs of the route below the ride size's need, merged where they run on one after
    another on the same street, the longest first (at most NARROW_LISTED): where to look for a
    wider way. A stretch's fourth element is its street name, where given."""
    runs: list[dict] = []
    at = 0.0
    for stretch in stretches:
        metres = float(stretch[0])
        rpm = _rpm(stretch)
        name = stretch[3] if len(stretch) > 3 else None
        if rpm is not None and rpm < need:
            avoid = rpm <= 0
            last = runs[-1] if runs else None
            if last is not None and last["to_m"] == round(at) and last["street"] == name:
                last["to_m"] = round(at + metres)
                last["riders_per_min"] = min(last["riders_per_min"], round(rpm))
                last["avoid"] = last["avoid"] or avoid
            else:
                runs.append(
                    {
                        "from_m": round(at),
                        "to_m": round(at + metres),
                        "street": name,
                        "riders_per_min": round(rpm),
                        "avoid": avoid,
                    }
                )
        at += metres
    runs = [r for r in runs if r["to_m"] > r["from_m"]]
    runs.sort(key=lambda r: r["from_m"] - r["to_m"])
    return sorted(runs[:NARROW_LISTED], key=lambda r: r["from_m"])
