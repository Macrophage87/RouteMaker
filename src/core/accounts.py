"""Saved settings and saved routes for signed-in riders (v0.7.0 plan, "Discord sign-in on, with
saved settings and routes", items 2 and 3).

The pure checks the API applies before anything is written: the settings document's shape and
size, and a saved route's line, inputs and answer. The models are `core.models.AccountSettings`
and `core.models.SavedRoute`; the endpoints are in `core.api` beside My Go.

Nothing here is shared between accounts, nothing is put in a log, and a route's line is kept as
it was sent: the point of a saved route is that it reopens unchanged.
"""

from __future__ import annotations

import json
import math

from django.conf import settings

# The settings document: one JSON object of the planning choices the device remembers
# (frontend/src/lib/accountSettings.ts). Only these keys are kept; anything else is refused, so
# the row cannot become a place to keep something the plan did not ask for.
SETTINGS_KEYS = frozenset(
    {
        "v",  # the document's version
        "plan",  # the ride type and dials, as a plan link's fragment with no points
        "water",  # the Water layer's switches
        "climbs",  # the Climbs layer on or off
        "climbsFrom",  # the smallest climb category shown
        "topo",  # contour lines on or off
        "sections",  # which Layers sections' switches were on
        "bikeshare",  # the bikeshare and micromobility service switches
        "favorites",  # the favorite ride types, listed first in the ride type pickers
        "weight",  # the rider and bike weight (frontend lib/weight.ts); personal, never logged
    }
)
SETTINGS_MAX_BYTES = 16 * 1024
SETTINGS_MAX_DEPTH = 4
# A list of short ride type names, each once; room for every ride type and some to come.
FAVORITES_MAX = 32
# The rider and bike weight's total, as the planner takes it (frontend lib/dials.ts
# SYSTEM_WEIGHT_MIN_KG and SYSTEM_WEIGHT_MAX_KG), and its parts' keys.
WEIGHT_MIN_KG = 25
WEIGHT_MAX_KG = 700
WEIGHT_PARTS = ("riderKg", "bikeKg", "cargoKg")
WEIGHT_KEYS = frozenset({"name", "totalKg", "parts", "setAt"})

# A saved route.
NAME_MAX = 120
# A planned route's line is a few thousand vertices; a long GPX track can be far more. The GPX
# import keeps at most 100,000 points (frontend lib/gpx.ts MAX_GPX_POINTS).
LINE_MAX_POINTS = 100_000
# The whole save, line and answer together. A day's ride with its full answer is a few hundred
# kilobytes; the cap keeps 200 of them per account within reason.
ROUTE_MAX_BYTES = 4 * 1024 * 1024
INPUT_POINTS_MAX = 25
HASH_MAX = 2048


def _depth(value, level: int = 0) -> int:
    if isinstance(value, dict):
        return max([level + 1, *(_depth(v, level + 1) for v in value.values())])
    if isinstance(value, list):
        return max([level + 1, *(_depth(v, level + 1) for v in value)])
    return level


def settings_problem(data) -> str | None:
    """Why a settings document cannot be kept, or None."""
    if not isinstance(data, dict):
        return "Settings must be an object."
    unknown = sorted(set(data) - SETTINGS_KEYS)
    if unknown:
        return f"Not a setting this planner keeps: {unknown[0]}."
    if _depth(data) > SETTINGS_MAX_DEPTH:
        return "Settings are nested too deeply."
    if len(json.dumps(data, separators=(",", ":"))) > SETTINGS_MAX_BYTES:
        return f"Settings are larger than {SETTINGS_MAX_BYTES // 1024} KB."
    plan = data.get("plan")
    if plan is not None and (not isinstance(plan, str) or len(plan) > HASH_MAX or "p=" in plan):
        # The ride type and dials only: a plan's points are a route, not a setting.
        return "The saved ride type and dials are not in the expected form."
    favorites = data.get("favorites")
    if favorites is not None and (
        not isinstance(favorites, list)
        or len(favorites) > FAVORITES_MAX
        or not all(isinstance(f, str) and len(f) <= 40 for f in favorites)
        or len(set(favorites)) != len(favorites)
    ):
        return "The favorite ride types are not in the expected form."
    weight = data.get("weight")
    if weight is not None and not _weight_ok(weight):
        # Never echo the value: the weight is personal.
        return "The saved weight is not in the expected form."
    return None


def _weight_ok(weight) -> bool:
    if not isinstance(weight, dict) or set(weight) - WEIGHT_KEYS:
        return False
    total = weight.get("totalKg")
    if not _finite(total) or not WEIGHT_MIN_KG <= total <= WEIGHT_MAX_KG:
        return False
    name = weight.get("name")
    if name is not None and (not isinstance(name, str) or len(name) > NAME_MAX):
        return False
    set_at = weight.get("setAt")
    if set_at is not None and not _finite(set_at):
        return False
    parts = weight.get("parts")
    if parts is not None and (
        not isinstance(parts, dict)
        or set(parts) != set(WEIGHT_PARTS)
        or not all(_finite(parts[k]) and 0 <= parts[k] <= WEIGHT_MAX_KG for k in WEIGHT_PARTS)
    ):
        return False
    return True


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _inside(lon: float, lat: float) -> bool:
    west, south, east, north = settings.COVERAGE_BBOX
    return west <= lon <= east and south <= lat <= north


def line_problem(line) -> str | None:
    """Why a line cannot be kept, or None. A vertex is [lon, lat] or [lon, lat, elevation]."""
    if not isinstance(line, list) or len(line) < 2:
        return "A saved route needs a line of at least two points."
    if len(line) > LINE_MAX_POINTS:
        return f"The line has more than {LINE_MAX_POINTS:,} points."
    for vertex in line:
        if not isinstance(vertex, list) or len(vertex) not in (2, 3):
            return "Each point of the line is [longitude, latitude] or with an elevation."
        if not all(_finite(v) for v in vertex):
            return "The line has a point that is not a number."
        lon, lat = vertex[0], vertex[1]
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            return "The line has a point off the globe."
    # The line is kept verbatim, so a GPX track may run outside the map's area; at least part of
    # it must be inside, or it is not a route this planner can reopen.
    if not any(_inside(v[0], v[1]) for v in line):
        return "The line is outside the area this map covers."
    return None


def inputs_problem(inputs) -> str | None:
    """Why a route's plan inputs cannot be kept, or None."""
    if not isinstance(inputs, dict):
        return "The plan's inputs must be an object."
    if set(inputs) - {"hash", "points", "preset", "dials"}:
        return "The plan's inputs hold something unexpected."
    hash_ = inputs.get("hash", "")
    if not isinstance(hash_, str) or len(hash_) > HASH_MAX:
        return "The plan's link is not in the expected form."
    points = inputs.get("points", [])
    if not isinstance(points, list) or len(points) > INPUT_POINTS_MAX:
        return f"A plan has at most {INPUT_POINTS_MAX} points."
    for p in points:
        if not (isinstance(p, list) and len(p) == 2 and all(_finite(v) for v in p)):
            return "Each of the plan's points is [longitude, latitude]."
    preset = inputs.get("preset", "")
    if not isinstance(preset, str) or len(preset) > 32:
        return "The plan's ride type is not in the expected form."
    dials = inputs.get("dials", {})
    if not isinstance(dials, dict) or len(json.dumps(dials)) > 4096:
        return "The plan's dials are not in the expected form."
    return None


# Saved-route versions (core.models.SavedRouteVersion): what changed from one version to the
# next, in a phrase. Read from the plan's inputs and the distance only, so the list never reads
# a line or an answer.
def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def change_phrase(older: dict, newer: dict) -> str:
    """What changed from `older` to `newer` (each with source, distance_m and inputs), in a
    phrase: "Stop added", "Ride type changed, start moved", "Line changed"."""
    if older.get("source") != newer.get("source"):
        return "From a GPX file" if newer.get("source") == "gpx" else "Planned in RouteMaker"
    a = older.get("inputs") or {}
    b = newer.get("inputs") or {}
    parts: list[str] = []
    if a.get("preset") != b.get("preset"):
        parts.append("ride type changed")
    pa, pb = a.get("points") or [], b.get("points") or []
    if pa != pb:
        if len(pb) > len(pa):
            parts.append(_plural(len(pb) - len(pa), "stop added", "stops added"))
        elif len(pb) < len(pa):
            parts.append(_plural(len(pa) - len(pb), "stop removed", "stops removed"))
        elif pa[:1] != pb[:1]:
            parts.append("start moved")
        elif pa[-1:] != pb[-1:]:
            parts.append("end moved")
        else:
            parts.append("stops moved")
    elif a.get("dials") != b.get("dials"):
        parts.append("settings changed")
    if not parts:
        same = abs((older.get("distance_m") or 0) - (newer.get("distance_m") or 0)) < 1
        parts.append("same plan" if same else "line changed")
    phrase = ", ".join(parts[:2])
    return phrase[:1].upper() + phrase[1:]
