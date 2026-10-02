"""How much longer a calm route is than the direct one, and what to say.

OWNER-DECISIONS item 164 (2026-10-01): "The 10-20 miles is just an example, but
the upper end could be much greater than straight line distance, just warn
people." The existing detour notice becomes this warning, in tiers taken from
"Bicycle stress literature in depth" (reports/LTS-literature-review-2.md), "The
stress slider's top end: let it run long, warn at 1.5x and 2x": observed utility
riders rarely exceed 1.5 times the shortest route, and the standard low-stress
allowance is the larger of 1.25
times or 0.33 mi (Furth, now also the BNA). The tiers are judgement anchored on
those distributions; there is no cap, only words.

The comparison is with the most direct legal route (the router at the traffic
tolerant end of the slider), not the straight line: a street grid is never the
straight line, and 1.25 times the crow's flight would flag nearly every ride.
Where the direct route could not be had in time the answer says it compared
with the straight line, and then only the old rule applies (at least twice as
long and at least 3 km more).
"""

from __future__ import annotations

METRES_PER_MILE = 1609.344

# "no note within the larger of 1.25x or +0.33 mi"
SILENT_RATIO = 1.25
SILENT_EXTRA_M = 0.33 * METRES_PER_MILE
# "a note up to 1.5x; a warning above 1.5x; a strong warning above 2x"
NOTE_MAX_RATIO = 1.5
STRONG_RATIO = 2.0

# The fallback against the straight line: the old notice's rule.
STRAIGHT_LINE_RATIO = 2.0
STRAIGHT_LINE_EXTRA_M = 3000.0

NOTE = "note"
WARNING = "warning"
STRONG = "strong"

DIRECT_ROUTE = "direct_route"
STRAIGHT_LINE = "straight_line"


def level(route_m: float, direct_m: float) -> str | None:
    """None where the route is within the allowance, else note, warning or strong."""
    if direct_m <= 0 or route_m <= 0:
        return None
    if route_m <= max(direct_m * SILENT_RATIO, direct_m + SILENT_EXTRA_M):
        return None
    ratio = route_m / direct_m
    if ratio > STRONG_RATIO:
        return STRONG
    if ratio > NOTE_MAX_RATIO:
        return WARNING
    return NOTE


def straight_line_level(route_m: float, straight_m: float) -> str | None:
    """The fallback: only a route at least twice the straight line and 3 km
    more is said to be a detour at all, and then as a warning."""
    if straight_m <= 0 or route_m <= 0:
        return None
    if (
        route_m / straight_m >= STRAIGHT_LINE_RATIO
        and route_m - straight_m >= STRAIGHT_LINE_EXTRA_M
    ):
        return WARNING
    return None


def describe(
    route_m: float,
    reference_m: float,
    basis: str,
    avoided_m: float | None = None,
) -> dict:
    """The answer's `detour` block."""
    lvl = (
        level(route_m, reference_m)
        if basis == DIRECT_ROUTE
        else straight_line_level(route_m, reference_m)
    )
    return {
        "basis": basis,
        "reference_m": round(reference_m, 1),
        "ratio": round(route_m / reference_m, 2) if reference_m > 0 else None,
        "extra_m": round(route_m - reference_m, 1),
        "level": lvl,
        "avoided_m": None if avoided_m is None else round(avoided_m, 1),
    }
