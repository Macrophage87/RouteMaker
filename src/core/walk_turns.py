"""Turn-by-turn on foot (Stephen, 2026-11-02: "turn by turn directions for walking"): a
walk's turns from the router's own maneuvers on Valhalla's pedestrian costing, each as its
movement, the street it turns onto (None: a path or sidewalk with no name) and where.

The app says them in the rider's language with the words it says a ride's turns with
(frontend/src/lib/walkCues.ts, navigate.ts turnWords), so the API sends no sentences here.

A walk crossing a road at a crosswalk turns onto it and off it a few yards apart; those
unnamed jogs are not said (`JOG_M`): a turn with no street name is kept only where the walk
then goes on that way at least that far."""

from __future__ import annotations

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


def directions(payload: dict) -> dict:
    """The pedestrian request `payload` asking for the maneuvers too (no narrative)."""
    return {**payload, "directions_type": "maneuvers"}


def turns_of(leg: dict, shape) -> list[dict]:
    """A routed walk's turns: [{"movement", "street", "point": [lon, lat]}], in order. `leg`
    is the router's leg (its `maneuvers`, lengths in kilometres) and `shape` its decoded line."""
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
    return out
