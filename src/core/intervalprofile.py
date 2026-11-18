"""One interval stretch's elevation profile, for its hover card on the map (the owner,
2026-11-18: "Allow a mouseover with elevation profile as well, it should also give distance
and a rough estimate of interval time").

The Intervals layer's file (`core.intervals_near`) carries each stretch's line, length, rise
and minutes, but no heights along it. The heights come as a climb's do (`core.climbprofile`):
the router samples the USGS 3DEP tiles along a /route from the stretch's start to its end
through points along it, so it is ridden the way it holds. Only a stretch in the file can be
asked for, by its id, and its answer is kept until the file changes.
"""

from __future__ import annotations

from collections import OrderedDict

from routemaker import profile as profile_rules

from . import climbprofile, intervals_near, routing

KEEP = 512
_kept: OrderedDict[tuple[str, int], dict | None] = OrderedDict()


class Unavailable(Exception):
    """The intervals file or the router could not be read for the profile."""


def find(stretch_id: str) -> intervals_near.Stretch | None:
    """The stretch of that id in the file, or None. Raises Unavailable without a file."""
    stretches = intervals_near.load()
    if stretches is None:
        raise Unavailable("there is no intervals file")
    return next((s for s in stretches if s.id == stretch_id), None)


def request_for(stretch: intervals_near.Stretch) -> dict:
    """The /route that rides `stretch` from its start to its end, with heights."""
    start, end = stretch.line[0], stretch.line[-1]
    return {
        "locations": [
            {"lon": start[0], "lat": start[1], "type": "break"},
            *(
                {"lon": lon, "lat": lat, "type": "through"}
                for lon, lat in intervals_near._through(stretch.line)
            ),
            {"lon": end[0], "lat": end[1], "type": "break"},
        ],
        "costing": "bicycle",
        "costing_options": climbprofile.COSTING,
        "elevation_interval": routing.ELEVATION_INTERVAL_M,
        "directions_type": "none",
        "units": "kilometers",
    }


def body_of(stretch: intervals_near.Stretch, trip: dict) -> dict | None:
    """The answer for one stretch: its samples (metres from its start, height, grade), the
    steepest grade, and its own figures from the file. None where the router gave no heights."""
    legs = []
    offset = 0.0
    for leg in trip.get("legs") or []:
        length = float((leg.get("summary") or {}).get("length", 0.0)) * 1000.0
        legs.append(profile_rules.Leg(offset, length, leg.get("elevation") or []))
        offset += length
    samples = profile_rules.sample_positions(legs, routing.ELEVATION_INTERVAL_M)
    if not any(height is not None for _m, height in samples):
        return None
    grade_at = profile_rules.grades(samples)
    steepest = max((g for g in grade_at if g is not None), default=None)
    return {
        "id": stretch.id,
        "length_m": round(stretch.length_m),
        "rise_m": round(stretch.rise_m, 1),
        "avg_grade_pct": round(stretch.grade_pct, 1),
        "minutes": round(stretch.minutes, 1),
        "both_ways": stretch.both_ways,
        "bollards": stretch.bollards,
        "max_grade_pct": None if steepest is None else round(max(steepest, 0.0) * 100, 1),
        "interval_m": routing.ELEVATION_INTERVAL_M,
        "m": [round(m) for m, _h in samples],
        "elevation_m": [None if h is None else round(h, 1) for _m, h in samples],
        "grade_pct": [None if g is None else round(g * 100, 1) for g in grade_at],
    }


def profile(stretch: intervals_near.Stretch) -> dict | None:
    """The stretch's profile (`body_of`), asked of the router once per stretch and file.

    None where no router has a way along it or none gave heights; raises Unavailable where
    the router did not answer (not kept, so the next ask tries again)."""
    key = (stretch.id, hash(stretch.line))
    if key in _kept:
        _kept.move_to_end(key)
        return _kept[key]
    deadline = routing.Deadline(routing.clock() + climbprofile.BUDGET_S, climbprofile.PER_CALL_S)
    request = request_for(stretch)
    answer: dict | None = None
    for variant in climbprofile.VARIANTS:
        try:
            trip = routing._call(variant, "route", request, deadline).get("trip") or {}
        except routing.RouterRefused:
            continue
        except (routing.RouterUnavailable, routing.DeadlineExceeded) as error:
            raise Unavailable(str(error)) from error
        answer = body_of(stretch, trip)
        if answer is not None:
            break
    _kept[key] = answer
    while len(_kept) > KEEP:
        _kept.popitem(last=False)
    return answer
