"""Turn-by-turn on foot (Stephen, 2026-11-02: "turn by turn directions for walking"): a
walk's turns from the router's own maneuvers on Valhalla's pedestrian costing, each as its
movement, the street it turns onto (None: a path or sidewalk with no name) and where.

The app says them in the rider's language with the words it says a ride's turns with
(frontend/src/lib/walkCues.ts, navigate.ts turnWords), so the API sends no sentences here.

A walk crossing a road at a crosswalk turns onto it and off it a few yards apart; those
unnamed jogs are not said (`JOG_M`): a turn with no street name is kept only where the walk
then goes on that way at least that far."""

from __future__ import annotations

import contextvars
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from . import walk_pricing

# Valhalla's maneuver types that turn (valhalla/odin/maneuver.h): the movement each is said as.
MOVEMENTS = {
    9: "bear_right",  # slight right
    10: "right",
    11: "right",  # sharp right
    12: "uturn",  # U-turn right
    13: "uturn",  # U-turn left
    14: "left",  # sharp left
    15: "left",
    16: "bear_left",  # slight left
}
# An unnamed turn followed by less than this on that way is a crosswalk's jog, not said.
JOG_M = 30.0
# The most turns a walk carries: a walk is short (a station or a dock away).
MAX_TURNS = 40


# Avoid stairs (Stephen, 2026-11-02: "Add the option to avoid stairs for walking"): a walk
# onto a flight of steps costs this many seconds more (Valhalla's pedestrian `step_penalty`,
# 30 s by default), so a step-free way is taken wherever one is anywhere near; where there
# is none (a station's only entrance up a stair), the steps are still walked.
STEP_FREE_PENALTY_S = 1800
_avoid_stairs: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "walk_turns_avoid_stairs", default=False
)


@contextmanager
def stairs_avoided(on: bool) -> Iterator[None]:
    """Within the block, the plan's walks avoid stairs where `on` (the rider's Avoid stairs)."""
    token = _avoid_stairs.set(bool(on))
    try:
        yield
    finally:
        _avoid_stairs.reset(token)


def avoiding_stairs() -> bool:
    return _avoid_stairs.get()


def step_free(pedestrian: dict) -> dict:
    """Valhalla pedestrian costing options that keep off stairs where a step-free way is near."""
    return {**pedestrian, "step_penalty": STEP_FREE_PENALTY_S}


def directions(payload: dict) -> dict:
    """The pedestrian request `payload` asking for the maneuvers too (no narrative) and the
    router's other ways (`walk_pricing.ALTERNATES`, for `walked`), kept off stairs where the
    rider asked (`stairs_avoided`)."""
    out = {**payload, "directions_type": "maneuvers", "alternates": walk_pricing.ALTERNATES}
    if avoiding_stairs():
        options = dict(out.get("costing_options") or {})
        options["pedestrian"] = step_free(options.get("pedestrian") or {})
        out["costing_options"] = options
    return out


def walked(answer: dict, ask: walk_pricing.Ask, payload: dict) -> tuple[dict, list[dict]] | None:
    """The walk taken of the router's `answer` to a `directions` request (`walk_pricing.choose`:
    its crossings and the roads it walks without a sidewalk priced) and the crossings it says
    (`walk_pricing.crossing_turns`, for `turns_of`); None where the answer has no leg. `ask`
    asks the router (`walk_pricing.Ask`); `payload` is the request answered, whose costing
    options its traces walk by."""
    chosen = walk_pricing.choose(answer, ask, payload.get("costing_options"))
    if chosen is None:
        return None
    return chosen.leg, walk_pricing.crossing_turns(chosen.crossings, ask)


def turns_of(leg: dict, shape, crossings: Sequence[dict] = ()) -> list[dict]:
    """A routed walk's turns: [{"movement", "street", "point": [lon, lat]}], in order. `leg`
    is the router's leg (its `maneuvers`, lengths in kilometres) and `shape` its decoded line.
    `crossings` are the crossings it says (`walk_pricing.crossing_turns`, movement "cross"),
    placed among the turns where they fall along the line."""
    out: list[dict] = []
    points = list(shape)
    for maneuver in leg.get("maneuvers") or []:
        movement = MOVEMENTS.get(maneuver.get("type"))
        if movement is None:
            continue
        index = maneuver.get("begin_shape_index")
        if not isinstance(index, int) or not 0 <= index < len(points):
            continue
        names = [n for n in maneuver.get("street_names") or [] if isinstance(n, str) and n]
        street = names[0] if names else None
        if street is None and float(maneuver.get("length") or 0.0) * 1000.0 < JOG_M:
            continue
        point = points[index]
        out.append(
            {
                "movement": movement,
                "street": street,
                "point": [round(float(point[0]), 6), round(float(point[1]), 6)],
            }
        )
        if len(out) >= MAX_TURNS:
            break
    if not crossings:
        return out
    return _in_order(out + list(crossings), points)


def _in_order(turns: list[dict], points: list) -> list[dict]:
    """`turns` by where each falls along the line `points` (its nearest vertex); a stable sort,
    so two at one place keep their order."""
    if len(points) < 2:
        return turns

    def nearest(point) -> int:
        lon, lat = float(point[0]), float(point[1])
        return min(
            range(len(points)),
            key=lambda i: (float(points[i][0]) - lon) ** 2 + (float(points[i][1]) - lat) ** 2,
        )

    return [
        turn for _i, turn in sorted(enumerate(turns), key=lambda p: (nearest(p[1]["point"]), p[0]))
    ]
