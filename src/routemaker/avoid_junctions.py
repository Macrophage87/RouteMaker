"""Avoid-rated junctions (FOLLOWUP-ISECT-AVOID, OWNER-DECISIONS 307-310, 335).

"There's some that are just way too problematic. Would only be added through
community (or my) input." An Avoid junction is never assigned by the model: an
instance admin approves each one (`core.models.AvoidJunction`), with its name and
its reason, and the list ships empty.

This is the pure half: which of them a route passes, and what to say about it. The
router half (`core.avoid_junctions`) reads the approved list and asks the router for
the way round.

Why the route's line and not the junction model's events. The junction model
(`routemaker.intersections`) reads only junctions where a road that can be busy is
involved (`core.junctions.wanted`), and its cost thresholds are being retuned
(PR #38). An Avoid rating is a person's judgement about one place, whatever the
roads there are, so a route passes an Avoid junction where its line comes within
`MATCH_RADIUS_M` of the junction's point. A route that rides through it twice (a
loop) passes it twice and pays twice.

The penalty. 308: "Probably a 30 minute penalty like Avoid." An Avoid road pays
`presets.AVOID_ENTRY_PENALTY_S` (1,800 cost seconds) on entry; an Avoid junction pays
the same, `AVOID_JUNCTION_PENALTY_S`, once for each pass. This package does not import
`core`, so the figure is restated here and `tests/test_avoid_junctions.py` holds the
two equal.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

# 308: the junction equivalent of an Avoid road's entry charge, cost seconds (30 minutes).
AVOID_JUNCTION_PENALTY_S = 1800.0
# A route passes a junction where its line comes this close to the junction's point
# (metres). A junction node is where the roads' centre lines meet; 15 m (49 ft) takes in
# a wide junction's own box and a route that turns through it, and stays short of the
# next junction on a city grid (a DC block is 90-150 m).
MATCH_RADIUS_M = 15.0
# The route has left the junction once it is this far from it again: a second pass
# (a loop back through it) counts from there.
LEAVE_RADIUS_M = 2 * MATCH_RADIUS_M

# The marker's and the text's symbol (310: "Text surfaces (legend, panel,
# description) use the Unicode character itself"), and the name every assistive
# technology hears in its place (309: "its accessible name is 'Avoid-rated junction'
# plus the reason, not 'skull and crossbones'"). The API's sentences carry the name,
# never the symbol: the client draws the symbol beside them, hidden from screen readers.
SYMBOL = "☠"
NOUN = "Avoid-rated junction"

# What every mention says after the name and the reason. The owner, 2026-10-10 15:08 UTC:
# "Yes, also when clicking on the intersection. Make it larger than a normal icon.
# Basically something to say: this is a really bad idea, please reconsider." The front end's
# AVOID_PLEA (frontend/src/lib/avoidJunctions.ts) is the same words (a test holds them equal).
PLEA = "Riding through it is a really bad idea. Please reconsider your route."
PLEA_MANY = "Riding through them is a really bad idea. Please reconsider your route."

_EARTH_M = 6_371_008.8


@dataclass(frozen=True)
class AvoidJunction:
    """One approved Avoid junction, as the planner needs it."""

    id: int
    name: str
    reason: str
    lon: float
    lat: float


@dataclass(frozen=True)
class Passage:
    """The route passing an Avoid junction, `m` metres along its line."""

    junction: AvoidJunction
    m: float


def _xy(lon: float, lat: float, lat0: float) -> tuple[float, float]:
    """Metres east and north on a plane tangent at `lat0` (good to well under a metre
    over a junction's few tens of metres)."""
    k = math.pi / 180 * _EARTH_M
    return lon * k * math.cos(math.radians(lat0)), lat * k


def _segment_m(
    p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
) -> tuple[float, float]:
    """The distance from `p` to the segment a-b, and how far along a-b its nearest
    point is (0 to 1)."""
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / length2))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy)), t


def passages(
    coordinates: Sequence[Sequence[float]],
    junctions: Sequence[AvoidJunction],
    radius_m: float = MATCH_RADIUS_M,
) -> list[Passage]:
    """Each pass of the route's line (lon, lat pairs, in order) through an Avoid
    junction, in route order, with the metres along the line where it comes nearest."""
    if len(coordinates) < 2 or not junctions:
        return []
    found: list[Passage] = []
    degree_m = math.pi / 180 * _EARTH_M
    for junction in junctions:
        lat0 = junction.lat
        here = _xy(junction.lon, junction.lat, lat0)
        # A segment's box, widened by this much, must hold the junction before its
        # distance is worked out: a route nowhere near costs a comparison a vertex.
        lat_margin = (LEAVE_RADIUS_M + 1.0) / degree_m
        lon_margin = lat_margin / max(math.cos(math.radians(lat0)), 0.01)
        along = 0.0
        inside = False
        best: tuple[float, float] = (math.inf, 0.0)  # (distance, metres along)
        prev_lon_lat = coordinates[0]
        previous = _xy(*prev_lon_lat[:2], lat0)
        for lon_lat in coordinates[1:]:
            point = _xy(*lon_lat[:2], lat0)
            seg = math.hypot(point[0] - previous[0], point[1] - previous[1])
            lons = (prev_lon_lat[0], lon_lat[0])
            lats = (prev_lon_lat[1], lon_lat[1])
            if (
                min(lons) - lon_margin <= junction.lon <= max(lons) + lon_margin
                and min(lats) - lat_margin <= junction.lat <= max(lats) + lat_margin
            ):
                distance, t = _segment_m(here, previous, point)
            else:
                distance, t = math.inf, 0.0
            if distance <= radius_m:
                if not inside:
                    inside, best = True, (math.inf, 0.0)
                if distance < best[0]:
                    best = (distance, along + t * seg)
            elif inside and distance > LEAVE_RADIUS_M:
                found.append(Passage(junction, best[1]))
                inside = False
            along += seg
            previous, prev_lon_lat = point, lon_lat
        if inside:
            found.append(Passage(junction, best[1]))
    return sorted(found, key=lambda p: (p.m, p.junction.id))


def line_length_m(coordinates: Sequence[Sequence[float]]) -> float:
    """The line's length, measured as `passages` measures it."""
    if len(coordinates) < 2:
        return 0.0
    lat0 = coordinates[0][1]
    total = 0.0
    previous = _xy(*coordinates[0][:2], lat0)
    for lon_lat in coordinates[1:]:
        point = _xy(*lon_lat[:2], lat0)
        total += math.hypot(point[0] - previous[0], point[1] - previous[1])
        previous = point
    return total


def penalty_s(found: Sequence[Passage]) -> float:
    """The routing penalty for a route's passes, cost seconds (308)."""
    return AVOID_JUNCTION_PENALTY_S * len(found)


def _said(junction: AvoidJunction) -> str:
    """ "<name>, <reason>", either part left out when empty."""
    parts = [p.strip().rstrip(".") for p in (junction.name, junction.reason) if p and p.strip()]
    return ", ".join(parts)


def label(junction: AvoidJunction) -> str:
    """The marker's and the list row's accessible name (309): "Avoid-rated junction:
    <name>, <reason>"."""
    said = _said(junction)
    return f"{NOUN}: {said}" if said else NOUN


def notice(found: Sequence[Passage]) -> str | None:
    """The panel's notice (335): "This route goes through an Avoid-rated junction:
    <name>, <reason>." Each junction once, in route order; None where there is none."""
    seen: list[AvoidJunction] = []
    for passage in found:
        if passage.junction not in seen:
            seen.append(passage.junction)
    if not seen:
        return None
    if len(seen) == 1:
        said = _said(seen[0])
        return f"This route goes through an {NOUN}{': ' + said if said else ''}. {PLEA}"
    listed = "; ".join(_said(j) or NOUN for j in seen)
    return f"This route goes through {len(seen)} {NOUN}s: {listed}. {PLEA_MANY}"


def _miles(metres: float) -> str:
    return f"{metres / 1609.344:.1f}"


def _km(metres: float) -> str:
    return f"{metres / 1000:.1f}"


def ahead_text(junction: AvoidJunction, at_m: float) -> str:
    """The description's sentence (307: "announced in the description, e.g.
    'Avoid-rated junction ahead'"), US units first and the metric in brackets."""
    said = _said(junction)
    where = f"{_miles(at_m)} mi ({_km(at_m)} km)"
    return f"{NOUN} ahead at {where}{': ' + said if said else ''}. {PLEA}"


def entries(found: Sequence[Passage], scale: float = 1.0) -> list[dict]:
    """The description's entries for the passes (`routemaker.describe._entry`'s shape,
    kind "avoid"), at their metres along the route scaled to the router's length."""
    out = []
    for passage in found:
        at = passage.m * scale
        out.append(
            {
                "kind": "avoid",
                "from_m": round(at),
                "to_m": round(at),
                "from_mi": round(at / 1609.344, 2),
                "to_mi": round(at / 1609.344, 2),
                "street": passage.junction.name or None,
                "tier": None,
                "facility": None,
                "turn": None,
                "severity": "avoid",
                "via": None,
                "group": None,
                "surface": None,
                "text": ahead_text(passage.junction, at),
                "text_lanes_hidden": None,
            }
        )
    return out


def with_entries(description: list[dict] | None, found: Sequence[Passage], scale: float = 1.0):
    """A description list with the passes' entries in route order (each before the
    stretch or junction that starts where it is); None stays None."""
    if description is None or not found:
        return description
    added = entries(found, scale)
    out: list[dict] = []
    pending = sorted(added, key=lambda e: e["from_m"])
    for entry in description:
        while pending and pending[0]["from_m"] <= entry["from_m"]:
            out.append(pending.pop(0))
        out.append(entry)
    out.extend(pending)
    return out


__all__ = [
    "AVOID_JUNCTION_PENALTY_S",
    "AvoidJunction",
    "LEAVE_RADIUS_M",
    "MATCH_RADIUS_M",
    "NOUN",
    "PLEA",
    "PLEA_MANY",
    "Passage",
    "SYMBOL",
    "ahead_text",
    "entries",
    "label",
    "line_length_m",
    "notice",
    "passages",
    "penalty_s",
    "with_entries",
]
