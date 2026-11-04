"""Reach: where a rider can be in 15, 30, 45 and 60 minutes (isochrones).

Stephen, 2026-11-04: "have a full set of isochrone tools. Like where can I be in 15, 30, 45
min, 1 hr by bike. Then we'd change things by traffic tolerance, etc."; "Allow isochrones from
several points too."; "Allow different modalities too, such as mass ride, fast, etc."; "It
should be sharable too". The plan is the doc "Visualization toolkit plan" (phase 1: bike reach).

Each ring is Valhalla's own isochrone (`/isochrone`, polygons) on the graph and with the costing
the ride type's route would use (`stoporder.ride_graph`): the same variant, stress dial
(`use_roads`), hills, speed, assist and trails-off switch as a plan, and the same closures left
out (`stoporder.ride_exclusions`). The time is the riding time along the least-cost way, so a low
traffic tolerance shrinks the rings to where the calm ways reach in that time. It is the router's
preference, not a hard cap: a ring at Low-stress still crosses a busy road where the router would.
Above Low-stress (`presets.STRESS_TODAYS_TOP`) the plan's calm detour search takes over, which an
isochrone cannot run; there the rings are Low-stress's (`use_roads` 0), and the answer says so
(`stress_used`).

Walk and Run go on foot (Valhalla's pedestrian costing on the standard graph, at a walk or the
runner's pace). The transit ride types are not here yet (phase 2): Bikeshare rides as a plain
bike, as the nearest-place search does.

Several points (up to MAX_POINTS) combine one of three ways: `any` (anywhere within the time of
at least one point: the union), `all` (anywhere within the time of every point: the overlap) and
`each` (one set of rings per point). The calm layer is the same rings at Low-stress, for one
point or a combined answer, so the page can lay "calm streets" over the rider's own setting.

Nothing is stored and only the variant and the router's error are logged, never the points (a
plan's privacy, OWNER-DECISIONS 395).
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from django.contrib.gis.geos import GEOSGeometry, Point

from . import presets, routing, run_plan, stoporder

logger = logging.getLogger(__name__)

MINUTES = (15, 30, 45, 60)
MIN_MINUTES = 5
MAX_MINUTES = 60
# Valhalla's `service_limits.isochrone.max_contours` in every valhalla/*.json.
MAX_RINGS = 4
MAX_POINTS = 5

FROM = "from"
TO = "to"
DIRECTIONS = (FROM, TO)
ANY = "any"
ALL = "all"
EACH = "each"
COMBINES = (ANY, ALL, EACH)

# The calm layer: the slider's Low-stress, where `use_roads` reaches 0 (presets' rescale).
CALM_STRESS = presets.STRESS_TODAYS_TOP

# One budget for the whole answer, as a plan's; one isochrone call at most this long.
REACH_BUDGET_S = routing.PLAN_BUDGET_S
ISOCHRONE_TIMEOUT_S = 20

# Valhalla's polygon options: drop pieces under a fifth of the largest (a few stray blocks
# reached along one path), and simplify to about 20 m, well under a block.
DENOISE = 0.2
GENERALIZE_M = 20
# Coordinates in the answer: 5 decimals, about a metre.
DECIMALS = 5

SQ_M_PER_SQ_MI = 2_589_988.11
M_PER_DEG_LAT = 110_574.0
M_PER_DEG_LON_EQUATOR = 111_320.0

# The places counted inside each ring: the files the page's own layers read.
METRO_PATH = Path(__file__).resolve().parents[2] / "frontend/src/rail-data/metro-stations.geojson"
RACKS_PATH = Path(__file__).resolve().parents[2] / "frontend/src/amenity-data/bike-parking.json"
FOOD_PATH = Path(__file__).resolve().parents[2] / "frontend/src/amenity-data/food.json"
SIGHTS_PATH = Path(__file__).resolve().parents[2] / "frontend/src/amenity-data/places.json"

ON_FOOT = frozenset({presets.WALK, presets.RUN})
NOT_YET = frozenset({presets.BIKE_TRANSIT, presets.BIKESHARE_TRANSIT, presets.WALK_TRANSIT})


class ReachRefused(Exception):
    """No ring could be drawn: every point is off the ride type's map. Said to the rider."""


# --- places ---------------------------------------------------------------------------------


def _points_file(path: Path) -> list[tuple[float, float, str]]:
    """(lon, lat, name) of an amenity-data file's points; none if it is not there."""
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError):
        logger.warning("reach: %s could not be read; its places are not counted", path.name)
        return []
    out = []
    for p in doc.get("points", []):
        if isinstance(p.get("x"), int | float) and isinstance(p.get("y"), int | float):
            out.append((float(p["x"]), float(p["y"]), str(p.get("n") or "")))
    return out


@lru_cache(maxsize=1)
def places() -> dict[str, list[tuple[float, float, str]]]:
    """Every kind of place a ring counts, loaded once a worker."""
    metro: list[tuple[float, float, str]] = []
    try:
        doc = json.loads(METRO_PATH.read_text())
        for feature in doc.get("features", []):
            lon, lat = feature["geometry"]["coordinates"][:2]
            metro.append((float(lon), float(lat), str(feature["properties"].get("NAME", ""))))
    except (OSError, ValueError, KeyError, TypeError):
        logger.warning("reach: the Metro stations could not be read; they are not counted")
    return {
        "metro": metro,
        "racks": _points_file(RACKS_PATH),
        "food": _points_file(FOOD_PATH),
        "sights": _points_file(SIGHTS_PATH),
    }


def _count(rings: list[GEOSGeometry]) -> tuple[list[dict], list[str]]:
    """How many of each kind of place lie inside each ring (cumulative: a ring holds the
    smaller ones), and the Metro stations inside the largest, nearest ring first."""
    counts = [{kind: 0 for kind in places()} for _ in rings]
    stations: list[tuple[int, str]] = []
    if not rings:
        return counts, []
    largest = rings[-1]
    if largest.empty:
        return counts, []
    west, south, east, north = largest.extent
    prepared = [ring.prepared for ring in rings]
    for kind, points in places().items():
        for lon, lat, name in points:
            if not (west <= lon <= east and south <= lat <= north):
                continue
            here = Point(lon, lat, srid=4326)
            for index, ring in enumerate(prepared):
                if ring.contains(here):
                    for later in range(index, len(rings)):
                        counts[later][kind] += 1
                    if kind == "metro":
                        stations.append((index, name))
                    break
    stations.sort()
    return counts, [name for _, name in stations]


# --- geometry -------------------------------------------------------------------------------


def _map_coords(coords, fn):
    if coords and isinstance(coords[0], int | float):
        return fn(coords)
    return [_map_coords(c, fn) for c in coords]


def area_sq_m(geom: GEOSGeometry) -> float:
    """The ground area of a lon/lat polygon, square metres: projected about its middle
    latitude (equirectangular), well within a percent across a 60 minute ring."""
    if geom.empty:
        return 0.0
    lat0 = math.radians(geom.centroid.y)
    kx = M_PER_DEG_LON_EQUATOR * math.cos(lat0)
    doc = json.loads(geom.json)
    doc["coordinates"] = _map_coords(
        doc["coordinates"], lambda c: [c[0] * kx, c[1] * M_PER_DEG_LAT]
    )
    return GEOSGeometry(json.dumps(doc)).area


def _valid(geom: GEOSGeometry) -> GEOSGeometry:
    # Valhalla's simplification can cross a ring over itself (its docs say so). make_valid
    # always, never `.valid` first: GEOS logs why a shape is invalid with a coordinate in it,
    # and the rider's places stay out of the logs. A fixed ring can come back as a collection
    # with stray lines, so only its areas are kept.
    return _polygons_only(geom.make_valid())


def geojson(geom: GEOSGeometry) -> dict | None:
    """The ring's outline as GeoJSON, coordinates rounded; None for an empty ring."""
    if geom.empty:
        return None
    doc = json.loads(geom.json)
    doc["coordinates"] = _map_coords(
        doc["coordinates"], lambda c: [round(c[0], DECIMALS), round(c[1], DECIMALS)]
    )
    return {"type": doc["type"], "coordinates": doc["coordinates"]}


def _polygons_only(geom: GEOSGeometry) -> GEOSGeometry:
    """A ring's areas alone: an overlap of two rings can add stray lines and points."""
    if geom.geom_type in ("Polygon", "MultiPolygon"):
        return geom
    if geom.geom_type == "GeometryCollection":
        kept = [g for g in geom if g.geom_type in ("Polygon", "MultiPolygon")]
        if not kept:
            return GEOSGeometry("POLYGON EMPTY", srid=4326)
        out = kept[0]
        for g in kept[1:]:
            out = out.union(g)
        return out
    return GEOSGeometry("POLYGON EMPTY", srid=4326)


# --- the router -----------------------------------------------------------------------------


def _ride(
    preset_name: str, dials: routing.Dials, run_pace_kmh: float | None
) -> tuple[str, str, dict]:
    """(variant, costing, costing_options) for a ride type's rings."""
    if preset_name in ON_FOOT:
        speed = (
            run_plan.pace_of(run_pace_kmh)
            if preset_name == presets.RUN
            else routing.WALK_IN_SPEED_KMH
        )
        return (
            routing.Variant.STANDARD.value,
            "pedestrian",
            {"pedestrian": {"walking_speed": speed}},
        )
    variant, costing = stoporder.ride_graph(preset_name, dials)
    return variant, "bicycle", costing


def _rings_from(answer: dict, minutes: list[int]) -> list[GEOSGeometry]:
    """One polygon per minute asked, smallest first, from an /isochrone answer."""
    by_minute: dict[int, GEOSGeometry] = {}
    for feature in answer.get("features", []) if isinstance(answer, dict) else []:
        geometry = feature.get("geometry") or {}
        if geometry.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        contour = (feature.get("properties") or {}).get("contour")
        if not isinstance(contour, int | float):
            continue
        geom = _valid(GEOSGeometry(json.dumps(geometry), srid=4326))
        key = round(contour)
        by_minute[key] = by_minute[key].union(geom) if key in by_minute else geom
    return [by_minute.get(m, GEOSGeometry("POLYGON EMPTY", srid=4326)) for m in minutes]


def _isochrone(
    variant: str,
    costing: str,
    options: dict,
    point: list[float],
    minutes: list[int],
    reverse: bool,
    exclude: list,
    deadline: routing.Deadline,
) -> list[GEOSGeometry] | None:
    """One point's rings; None where the router could not place the point on its map."""
    payload: dict = {
        "locations": [{"lon": point[0], "lat": point[1], "radius": routing.STOP_RADIUS_M}],
        "costing": costing,
        "costing_options": options,
        "contours": [{"time": m} for m in minutes],
        "polygons": True,
        "denoise": DENOISE,
        "generalize": GENERALIZE_M,
    }
    if reverse:
        payload["reverse"] = True
    if exclude:
        payload["exclude_polygons"] = list(exclude)
    try:
        answer = stoporder.ask_isochrone(variant, payload, deadline)
    except routing.RouterRefused as refusal:
        if refusal.code in routing.NO_EDGE_CODES:
            return None
        raise
    return _rings_from(answer, minutes)


def _combine(sets: list[list[GEOSGeometry]], how: str) -> list[GEOSGeometry]:
    out = []
    for rings in zip(*sets, strict=True):
        geom = rings[0]
        for other in rings[1:]:
            geom = geom.union(other) if how == ANY else geom.intersection(other)
        out.append(_polygons_only(geom))
    return out


def _group(rings: list[GEOSGeometry], minutes: list[int], point: int | None) -> dict:
    counts, stations = _count(rings)
    return {
        "point": point,
        "rings": [
            {
                "minutes": m,
                "geometry": geojson(ring),
                "area_sq_mi": round(area_sq_m(ring) / SQ_M_PER_SQ_MI, 2),
                "area_km2": round(area_sq_m(ring) / 1e6, 2),
                "places": count,
            }
            for m, ring, count in zip(minutes, rings, counts, strict=True)
        ],
        "metro_stations": stations,
    }


def stress_of(preset_name: str, dials: routing.Dials) -> int | None:
    """The slider position the rings are drawn at (None on foot)."""
    if preset_name in ON_FOOT:
        return None
    stress = (
        presets.stress_start(preset_name, dials.carrying) if dials.stress is None else dials.stress
    )
    return min(stress, CALM_STRESS)


def calm_offered(preset_name: str, dials: routing.Dials) -> bool:
    """Whether a calm layer says anything: a bike ride type that can go calmer than it is set,
    and whose slider is not locked (Mass Ride) or stopped short of Low-stress (Fast)."""
    stress = stress_of(preset_name, dials)
    if stress is None or preset_name == "mass-ride":
        return False
    return presets.PRESETS[preset_name].stress_max >= CALM_STRESS and stress < CALM_STRESS


def reach(
    points: list[list[float]],
    preset_name: str,
    dials: routing.Dials,
    minutes: list[int] | tuple[int, ...] = MINUTES,
    direction: str = FROM,
    combine: str = ANY,
    calm: bool = False,
    run_pace_kmh: float | None = None,
    started: float | None = None,
) -> dict:
    """The rings, as the API's body. Raises ReachRefused when no point is on the map,
    DeadlineExceeded past the budget, and RouterUnavailable / RouterRefused as a plan does."""
    if preset_name in NOT_YET:
        raise ValueError(f"{preset_name} has no reach yet")
    if preset_name == presets.BIKESHARE:
        # Its ride between docks, as the nearest-place search rides it.
        preset_name = "default"
    minutes = sorted(set(minutes))
    if started is None:
        started = routing.clock()
    deadline = routing.Deadline(
        started + REACH_BUDGET_S - routing.ANSWER_RESERVE_S, ISOCHRONE_TIMEOUT_S
    )
    moved, _ = routing.move_zoo_points(points)
    reverse = direction == TO
    exclude = [] if preset_name in ON_FOOT else stoporder.ride_exclusions(moved, dials)
    used = stress_of(preset_name, dials)
    own = dials if used is None or used == dials.stress else _with_stress(dials, used)

    def layer(layer_dials: routing.Dials) -> tuple[list[dict], list[int]]:
        variant, costing, options = _ride(preset_name, layer_dials, run_pace_kmh)
        sets, placed, unplaced = [], [], []
        for index, point in enumerate(moved):
            rings = _isochrone(
                variant, costing, options, point, minutes, reverse, exclude, deadline
            )
            if rings is None:
                logger.info("reach: the %s router could not place point %d", variant, index)
                unplaced.append(index)
                continue
            sets.append(rings)
            placed.append(index)
        if not sets:
            raise ReachRefused(
                "None of the points is on a street or path this ride type rides; move them onto"
                " one and try again."
            )
        if combine == EACH or len(sets) == 1:
            groups = [_group(r, minutes, i) for r, i in zip(sets, placed, strict=True)]
        else:
            groups = [_group(_combine(sets, combine), minutes, None)]
        return groups, unplaced

    groups, unplaced = layer(own)
    calm_groups = None
    single = len(points) == 1 or combine != EACH
    if calm and single and calm_offered(preset_name, dials):
        calm_groups, _ = layer(_with_stress(dials, CALM_STRESS))
    return {
        "preset": preset_name,
        "minutes": minutes,
        "direction": direction,
        "combine": combine,
        "stress_used": used,
        "groups": groups,
        "calm": None if calm_groups is None else {"stress": CALM_STRESS, "groups": calm_groups},
        "unplaced": unplaced,
    }


def _with_stress(dials: routing.Dials, stress: int) -> routing.Dials:
    return replace(dials, stress=stress)
