"""Novice and Nervous: walk the bike past a short busy stretch (v0.11.0).

The owner, 2026-10-21: "For the Novice or Nervous mode, walk a bike on sidewalk mode should
definitely be a consideration." He chose "Walk the bad stretch": where a Novice route still
rides a road of real LTS 4 or worse for a stretch of up to about half a mile, and a sidewalk
or path runs beside it, the rider walks the bike there instead, timed at walking pace.

No map rebuild: the walk is asked of the standard graph's pedestrian costing at plan time
(`routing.walk_leg`) and kept only where it stays beside the road (`DETOUR_RATIO`) and off
the main roads' carriageways (`routing.walk_roadside_m`, `ROADSIDE_SLACK_M`). The route's
line is unchanged, the sidewalk being beside it: the walk is drawn on the map, is a "walk"
entry of the directions (so the ride says it ahead), and the route's time takes the walk's
time in place of the ride's. A longer stretch is left to the transit offer
(`routing.novice_note`).
"""

from __future__ import annotations

from collections.abc import Callable

from routemaker.describe import point_words
from routemaker.geo import Point, haversine

# Real LTS 4, 4.5 and Avoid (the stress keys "4" and "5"): what a Novice walks past. LTS 3
# is ridden, read one level up as it already is (`presets.EXPOSURE_NOVICE`).
WALK_TIERS = frozenset({"4", "5"})
# Shorter than this is a crossing of the road, not riding on it (`routing.NOVICE_BUSY_SLACK_M`).
MIN_M = 80.0
# About half a mile (the decision card: "up to about 0.5 mi of walking per stretch"); the
# walk's own cap is `routing.WALK_IN_MAX_M`, the same.
MAX_M = 800.0
# Two busy runs this close are one stretch: a side street's mouth does not end the walk.
JOIN_GAP_M = 25.0
# The most stretches one route asks walks for, so the plan's time is not spent on them.
MOST = 3
# A walk longer than this many times the stretch (or than the stretch and DETOUR_SLACK_M)
# goes the long way round rather than along the sidewalk, and is not offered.
DETOUR_RATIO = 1.5
DETOUR_SLACK_M = 150.0
# A walk may cross main roads, and step along one for a few metres, but not follow one
# that has no sidewalk: past this the walk is on the carriageway, and is not offered.
ROADSIDE_SLACK_M = 80.0
METRES_PER_MILE = 1609.344
FEET_PER_METRE = 3.28084


def stretches(leg_runs: list, pieces: list, classes: list) -> list[dict]:
    """The runs of real LTS 4 or worse the route rides, in riding order, in metres along
    the traced pieces (`route_hazards.along`'s measure): {from_m, to_m, road, pieces}, the
    road being the name most of it is on (None where none), `pieces` the indices of the
    busy pieces. Runs JOIN_GAP_M apart on one leg are one; a stop ends a run."""
    out: list[dict] = []
    at = 0.0
    for run in leg_runs:
        if not isinstance(run, tuple):
            at += float(run)
            continue
        open_: dict | None = None
        for i in range(run[0], run[1]):
            piece = pieces[i]
            start, at = at, at + piece.metres
            tier = classes[i][0] if i < len(classes) else "unknown"
            if tier not in WALK_TIERS:
                continue
            if open_ is None or start - open_["to_m"] > JOIN_GAP_M:
                open_ = {"from_m": start, "to_m": at, "names": {}, "pieces": []}
                out.append(open_)
            open_["to_m"] = at
            open_["pieces"].append(i)
            names = getattr(piece, "names", None) or ()
            name = names[0] if names else None
            open_["names"][name] = open_["names"].get(name, 0.0) + piece.metres
    for found in out:
        named = {k: v for k, v in found.pop("names").items() if k}
        found["road"] = max(named, key=named.get) if named else None
    return out


def _measure(line: list) -> list[float]:
    along = [0.0]
    for a, b in zip(line, line[1:], strict=False):
        along.append(along[-1] + haversine(Point(*a[:2]), Point(*b[:2])))
    return along


def point_at(line: list, along: list[float], metres: float) -> list[float]:
    """The point `metres` along `line` (its cumulative measure `along`), as [lon, lat]."""
    metres = max(0.0, min(metres, along[-1]))
    for i in range(1, len(along)):
        if along[i] >= metres:
            span = along[i] - along[i - 1]
            t = (metres - along[i - 1]) / span if span > 0 else 0.0
            a, b = line[i - 1], line[i]
            return [
                round(a[0] + (b[0] - a[0]) * t, 6),
                round(a[1] + (b[1] - a[1]) * t, 6),
            ]
    return [round(line[-1][0], 6), round(line[-1][1], 6)]


def walks(
    found: list[dict],
    line: list,
    measured_m: float,
    route_m: float,
    walk: Callable[[list[float], list[float]], dict | None],
    roadside_m: Callable[[list], float | None],
) -> list[dict]:
    """The walks to offer past the stretches `found` (`stretches`): each stretch between
    MIN_M and MAX_M long, up to MOST of them, whose walk on foot (`walk(a, b)`, as
    `routing.walk_leg`) stays beside the road and off main roads' carriageways
    (`roadside_m(coordinates)`). `measured_m` is the pieces' whole measure and `route_m`
    the route's length as the router states it, which the directions are in; `line` is
    the route's coordinates. Each walk: {from_m, to_m (the directions' metres), road,
    ride_m, geometry, distance_m, duration_s, pieces}."""
    if len(line) < 2 or measured_m <= 0:
        return []
    along = _measure(line)
    to_line = along[-1] / measured_m
    to_route = route_m / measured_m if route_m > 0 else 1.0
    out: list[dict] = []
    asked = 0
    for stretch in found:
        ride_m = (stretch["to_m"] - stretch["from_m"]) * to_route
        if not MIN_M <= ride_m <= MAX_M:
            continue
        if asked >= MOST:
            break
        asked += 1
        a = point_at(line, along, stretch["from_m"] * to_line)
        b = point_at(line, along, stretch["to_m"] * to_line)
        leg = walk(a, b)
        if leg is None:
            continue
        if leg["distance_m"] > max(ride_m * DETOUR_RATIO, ride_m + DETOUR_SLACK_M):
            continue
        roadside = roadside_m(leg["geometry"]["coordinates"])
        if roadside is None or roadside > ROADSIDE_SLACK_M:
            continue
        out.append(
            {
                "from_m": round(stretch["from_m"] * to_route),
                "to_m": round(stretch["to_m"] * to_route),
                "road": stretch["road"],
                "ride_m": round(ride_m, 1),
                "geometry": leg["geometry"],
                "distance_m": leg["distance_m"],
                "duration_s": leg["duration_s"],
                "pieces": stretch["pieces"],
            }
        )
    return out


def _distance_words(metres: float) -> str:
    """US units first, metric in brackets: "0.3 mi (480 m)", or feet under a tenth."""
    if metres < METRES_PER_MILE / 10:
        feet = metres * FEET_PER_METRE
        feet = int(round(feet, -1)) if feet >= 100 else int(round(feet))
        return f"{feet} ft ({round(metres)} m)"
    return f"{metres / METRES_PER_MILE:.1f} mi ({round(metres, -1):.0f} m)"


def line(found: dict) -> str:
    """The directions' line: "At 1.2 mi (1.9 km): walk your bike on the sidewalk along
    Redland Road for 0.3 mi (480 m), about 6 min. The road is too busy to ride." """
    road = found["road"] or "the busy road"
    minutes = max(1, round(found["duration_s"] / 60))
    return (
        f"At {point_words(found['from_m'])}: walk your bike on the sidewalk along {road} "
        f"for {_distance_words(found['distance_m'])}, about {minutes} min. "
        "The road is too busy to ride."
    )


def _entry(found: dict) -> dict:
    """`routemaker.describe._entry`'s shape, kind "walk", which the ride says ahead."""
    return {
        "kind": "walk",
        "from_m": found["from_m"],
        "to_m": found["to_m"],
        "from_mi": round(found["from_m"] / METRES_PER_MILE, 2),
        "to_mi": round(found["to_m"] / METRES_PER_MILE, 2),
        "street": found["road"],
        "tier": None,
        "facility": None,
        "turn": None,
        "severity": None,
        "via": None,
        "group": None,
        "surface": None,
        "text": line(found),
        "text_lanes_hidden": None,
        "relation_name": False,
    }


def with_entries(description: list[dict] | None, found: list[dict]) -> list[dict] | None:
    """A description list with the walks' entries in route order (each before the entry
    that starts where it does); None stays None."""
    if description is None or not found:
        return description
    pending = sorted((_entry(walk) for walk in found), key=lambda e: e["from_m"])
    out: list[dict] = []
    for entry in description:
        while pending and pending[0]["from_m"] <= entry["from_m"]:
            out.append(pending.pop(0))
        out.append(entry)
    out.extend(pending)
    return out


def time_change_s(found: list[dict], route_m: float, route_s: float) -> float:
    """What the walks add to the route's time: each walk's time less the time the route
    took to ride the stretch (its share of the route's riding time)."""
    if route_m <= 0:
        return 0.0
    per_m = route_s / route_m
    return sum(walk["duration_s"] - walk["ride_m"] * per_m for walk in found)


def public(found: list[dict]) -> list[dict]:
    """The walks as the answer carries them (`api.NoviceWalkOut`)."""
    return [
        {
            key: walk[key]
            for key in ("from_m", "to_m", "road", "ride_m", "geometry", "distance_m", "duration_s")
        }
        | {"text": line(walk)}
        for walk in found
    ]
