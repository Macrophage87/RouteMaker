"""One climb's elevation profile, for the map's climb card (the owner, 2026-10-12: "You
should be able to click on a climb to see more about that climb, such as elevation
profile").

The Climbs layer's file (frontend/src/climb-data/climbs.json, `pipeline.climb_layer`)
carries each climb's line, length, gain and average grade, but no heights along it. The
heights come the way the route chart's do (`routing.profile_of`): the router samples the
USGS 3DEP tiles it already serves every `routing.ELEVATION_INTERVAL_M` along a /route,
here one from the climb's foot to its summit through the same `through` points the hill
seek asks a climb with (`hillseek.via_points`), so it rides the climb uphill. Nothing new
is shipped or rebuilt: the file is in the api image already (`docker/api.Dockerfile`) and
the elevation is the router's.

Only a climb in the file can be asked for, by its id, so the endpoint draws no line a
caller chose. The answer for a climb does not change until the file does, so it is kept
(`_kept`, by id and the file's identity) and served with a long cache life.
"""

from __future__ import annotations

import logging
from collections import OrderedDict

from routemaker import profile as profile_rules

from . import hillseek, routing

logger = logging.getLogger(__name__)

# The router a climb is measured on, then the one with every trail, for a climb the
# first has no way up (a mostly unpaved one).
VARIANTS = ("standard", "offroad")
# Any road will do: this is a measurement, not a recommendation, so the costing is
# told not to steer off busy roads or hills, nor off rough surfaces.
COSTING = {
    "bicycle": {
        "bicycle_type": "Hybrid",
        "use_roads": 1.0,
        "use_hills": 1.0,
        "avoid_bad_surfaces": 0.0,
    }
}
# The whole look-up's time (seconds), and the most one router call may take.
BUDGET_S = 8.0
PER_CALL_S = 6.0
# Climbs kept in memory (each a few hundred numbers).
KEEP = 512

_kept: OrderedDict[tuple[str, int], dict | None] = OrderedDict()


class Unavailable(Exception):
    """The climbs file or the router could not be read for the profile."""


def find(climb_id: str) -> hillseek.Climb | None:
    """The climb of that id in the file, or None. Raises Unavailable without a file."""
    climbs = hillseek.load()
    if climbs is None:
        raise Unavailable("there is no climbs file")
    for climb in climbs:
        if climb.id == climb_id:
            return climb
    return None


def request_for(climb: hillseek.Climb) -> dict:
    """The /route that rides `climb` from its foot to its summit, with heights."""
    return {
        "locations": [
            {"lon": climb.foot[0], "lat": climb.foot[1], "type": "break"},
            *(
                {"lon": lon, "lat": lat, "type": "through"}
                for lon, lat in hillseek.via_points(climb)
            ),
            {"lon": climb.summit[0], "lat": climb.summit[1], "type": "break"},
        ],
        "costing": "bicycle",
        "costing_options": COSTING,
        "elevation_interval": routing.ELEVATION_INTERVAL_M,
        "directions_type": "none",
        "units": "kilometers",
    }


def body_of(climb: hillseek.Climb, trip: dict) -> dict | None:
    """The answer for one climb from the router's trip: its samples (metres from the
    foot, height, grade read as the route chart reads it), the steepest grade, and the
    climb's own figures from the file. None where the router gave no heights."""
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
        "id": climb.id,
        "category": climb.category,
        "length_m": round(climb.length_m),
        "gain_m": round(climb.gain_m, 1),
        "avg_grade_pct": round(climb.grade_pct, 1),
        "max_grade_pct": None if steepest is None else round(max(steepest, 0.0) * 100, 1),
        "interval_m": routing.ELEVATION_INTERVAL_M,
        "m": [round(m) for m, _h in samples],
        "elevation_m": [None if h is None else round(h, 1) for _m, h in samples],
        "grade_pct": [None if g is None else round(g * 100, 1) for g in grade_at],
    }


def profile(climb: hillseek.Climb) -> dict | None:
    """The climb's profile (`body_of`), asked of the router once per climb and file.

    None where no router has a way up it or none gave heights; raises Unavailable
    where the router did not answer (not kept, so the next ask tries again)."""
    key = (climb.id, hash(climb.line))
    if key in _kept:
        _kept.move_to_end(key)
        return _kept[key]
    deadline = routing.Deadline(routing.clock() + BUDGET_S, PER_CALL_S)
    request = request_for(climb)
    answer: dict | None = None
    for variant in VARIANTS:
        try:
            trip = routing._call(variant, "route", request, deadline).get("trip") or {}
        except routing.RouterRefused:
            continue
        except (routing.RouterUnavailable, routing.DeadlineExceeded) as error:
            raise Unavailable(str(error)) from error
        answer = body_of(climb, trip)
        if answer is not None:
            break
    _kept[key] = answer
    while len(_kept) > KEEP:
        _kept.popitem(last=False)
    return answer
