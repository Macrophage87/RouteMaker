"""Reach: where a rider can be in 15, 30, 45 and 60 minutes (isochrones).

Stephen, 2026-11-04: "have a full set of isochrone tools. Like where can I be in 15, 30, 45
min, 1 hr by bike. Then we'd change things by traffic tolerance, etc."; "Allow isochrones from
several points too."; "Allow different modalities too, such as mass ride, fast, etc."; "It
should be sharable too". The plan is the doc "Visualization toolkit plan" (phase 1: bike reach).

Each ring is Valhalla's own isochrone (`/isochrone`, polygons) on the graph and with the costing
the ride type's route would use (`stoporder.ride_graph`): the same variant, stress dial
(`use_roads`), hills, speed, assist and trails-off switch as a plan, and the same closures left
out (`stoporder.ride_exclusions`), looked up as far out as the largest ring can reach
(`zones_reach_m`), not only near the points. The time is the riding time along the least-cost
way, so a low traffic tolerance shrinks the rings to where the calm ways reach in that time. It
is the router's preference, not a hard cap: a ring at Low-stress still crosses a busy road
where the router would. Above Low-stress (`presets.STRESS_TODAYS_TOP`) the plan's calm detour
search takes over, which an isochrone cannot run; there the rings are Low-stress's (`use_roads`
0), and the answer says so (`stress_used`).

Walk and Run go on foot (Valhalla's pedestrian costing on the standard graph, at a walk or the
runner's pace, a run with its plan's own settings, `run_plan.costing_options`), round the
closures that close the way on foot and the roads marked closed, as their plans go
(`workzones.foot_zones`). Bikeshare rides the share bike, as its plan does: the classic's pace,
stress and hills, or with `assist` the e-bike's on the e-bike graph. Mountain Bike's trail
level is held by its plan after the router answers (`core.mtb`), which an isochrone cannot do:
the answer says so (`trail_level_applied`). The transit ride types are not here yet (phase 2).

Several points (up to MAX_POINTS) combine one of three ways: `any` (anywhere within the time of
at least one point: the union), `all` (anywhere within the time of every point: the overlap) and
`each` (one set of rings per point). The calm layer is the same rings at Low-stress, for one
point or a combined answer, so the page can lay "calm streets" over the rider's own setting.

Nothing is stored and only the variant and the router's error are logged, never the points (a
plan's privacy, OWNER-DECISIONS 395), but for a short while: each router answer is kept in the
routes cache (`core.route_cache`) for KEEP_S, under a digest of everything the call asks, so
turning a ring off and on again, Calm streets, or closing and reopening the sheet does not ask
the router again. KEEP_S is under the two minutes a rider's position may be kept.

Each isochrone call is counted as it is made (`reach`'s `charge`: Reach's own limits,
`ratelimit.REACH_ISOCHRONES`, apart from a plan's), and a call answered from the cache costs
nothing. A request that names itself (`X-Plan-Id`, as a plan, `core.plan_cancel`) stops at its
next router call once the page has replaced it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from collections.abc import Callable
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from django.contrib.gis.geos import GEOSGeometry, Point

from . import mtb, presets, route_cache, routing, run_plan, stoporder
from . import workzones as work_zones

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

# How long a router answer for rings is kept (`core.route_cache`): under the two minutes a
# rider's position may be kept, which the points can be (the owner, 2026-10-22).
KEEP_S = 90

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
# How much further than its pace on the flat a ring may reach (a long descent is ridden faster):
# the closures are looked up this much past minutes x speed (`zones_reach_m`).
REACH_SLACK = 1.25
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
    if preset_name == presets.RUN:
        # The run's own settings (hills, tracks, living streets, lit ways after dark), as
        # `run_plan` asks for its legs.
        when = dials.when or routing.default_when()
        ask = run_plan.RunAsk(
            pace_kmh=run_plan.pace_of(run_pace_kmh),
            hills=0 if dials.hills is None else dials.hills,
            dark=run_plan.is_dark(work_zones.ride_moment(when), when),
        )
        return routing.Variant.STANDARD.value, "pedestrian", run_plan.costing_options(ask)
    if preset_name in ON_FOOT:
        return (
            routing.Variant.STANDARD.value,
            "pedestrian",
            {"pedestrian": {"walking_speed": routing.WALK_IN_SPEED_KMH}},
        )
    variant, costing = stoporder.ride_graph(preset_name, dials)
    return variant, "bicycle", costing


def share_bike_dials(dials: routing.Dials) -> routing.Dials:
    """A Bikeshare ride's dials as its plan sets them (`api._bikeshare_body`): the share bike's
    own hills start and assist, the e-bike where `assist` is asked, else the classic."""
    bike = presets.BIKE_EBIKE if dials.assist else presets.BIKE_CLASSIC
    profile = presets.BIKESHARE_BIKES[bike]
    return replace(
        dials,
        hills=profile.hills if dials.hills is None else dials.hills,
        assist=profile.assist,
        cycling_speed_kmh=None,
    )


def zones_reach_m(options: dict, minutes: list[int]) -> float:
    """How far the largest ring can reach from its point (minutes x the pace on the flat, with
    `REACH_SLACK`): how far out the closures are looked up (audit 2026-11-05)."""
    block = options.get("pedestrian") or options.get("bicycle") or {}
    if "walking_speed" in block:
        kmh = float(block["walking_speed"])
    else:
        kmh = float(
            block.get("cycling_speed")
            or presets.VALHALLA_DEFAULT_SPEED_KMH[block.get("bicycle_type", "Hybrid")]
        )
    return max(minutes) / 60.0 * kmh * 1000.0 * REACH_SLACK


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


def asked_minutes(minutes: list[int]) -> list[int]:
    """The contours asked of the router for the rings `minutes`: those, and each of MINUTES
    inside the largest, which the largest's search reaches anyway; so a ring turned off and on
    again is one the router has already drawn (KEEP_S). Only `minutes` where that would be
    past MAX_RINGS."""
    top = max(minutes)
    asked = sorted(set(minutes) | {m for m in MINUTES if m <= top})
    return asked if len(asked) <= MAX_RINGS else sorted(set(minutes))


def _payload(
    costing: str,
    options: dict,
    point: list[float],
    contours: list[int],
    reverse: bool,
    exclude: list,
) -> dict:
    payload: dict = {
        # Matched as a plan's start is, never to the tunnel under a DC circle park, which
        # grew the rings from the underpass (the second 2026-11-08 hunt, P6).
        "locations": [
            {
                "lon": point[0],
                "lat": point[1],
                "radius": routing.STOP_RADIUS_M,
                **routing.circle_park_filter(point[0], point[1]),
            }
        ],
        "costing": costing,
        "costing_options": options,
        "contours": [{"time": m} for m in contours],
        "polygons": True,
        "denoise": DENOISE,
        "generalize": GENERALIZE_M,
    }
    if reverse:
        payload["reverse"] = True
    if exclude:
        payload["exclude_polygons"] = list(exclude)
    return payload


def _keep_key(variant: str, payload: dict) -> str | None:
    """The routes cache's key for one isochrone call: the graph, the whole call, and the live
    segment table's state (as a plan's key, `route_cache.key_for`). None where the cache is off
    or that state cannot be read: the call is made, and not kept."""
    if route_cache.ttl_s() <= 0:
        return None
    try:
        made = {"reach": variant, "payload": payload, "edits": route_cache._edits_part()}
        return (
            "reach:"
            + hashlib.sha256(json.dumps(made, sort_keys=True, default=str).encode()).hexdigest()
        )
    except Exception:  # noqa: BLE001 - rings are never refused for want of a key
        logger.warning("reach: the cache key could not be made", exc_info=True)
        return None


class _Ask:
    """One point's isochrone call on one layer, and the router's answer where it is kept."""

    def __init__(self, variant: str, payload: dict, wider: dict | None) -> None:
        self.variant = variant
        self.payload = payload
        self.key = _keep_key(variant, payload)
        self.kept = None if self.key is None else route_cache.get(self.key)
        if self.kept is None and wider is not None:
            # The same call for more rings (`reach`'s `wider`) holds these too.
            key = _keep_key(variant, wider)
            self.kept = None if key is None else route_cache.get(key)

    def rings(
        self,
        minutes: list[int],
        deadline: routing.Deadline,
        charge: Callable[[], None] | None = None,
    ) -> list[GEOSGeometry] | None:
        """The point's rings; None where the router could not place the point on its map.
        `charge()` just before the router is asked: never for a kept answer, nor once the
        request has been cancelled."""
        answer = self.kept
        if answer is None:
            routing.check_cancel()
            if charge is not None:
                charge()
            try:
                answer, graph = stoporder.ask_isochrone(self.variant, self.payload, deadline)
            except routing.RouterRefused as refusal:
                if refusal.code in routing.NO_EDGE_CODES:
                    return None
                raise
            # An answer from another graph (a twin router that was down) is not kept, as a
            # plan's is not (`route_cache.keepable`).
            if self.key is not None and graph == self.variant:
                route_cache.put(self.key, answer, KEEP_S)
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
    charge: Callable[[], None] | None = None,
) -> dict:
    """The rings, as the API's body. Raises ReachRefused when no point is on the map,
    DeadlineExceeded past the budget, and RouterUnavailable / RouterRefused as a plan does.
    `charge()`, just before each isochrone call the cache does not answer (it may raise, and
    then that call and those after it are not made)."""
    if preset_name in NOT_YET:
        raise ValueError(f"{preset_name} has no reach yet")
    if preset_name == presets.BIKESHARE:
        dials = share_bike_dials(dials)
    minutes = sorted(set(minutes))
    if started is None:
        started = routing.clock()
    deadline = routing.Deadline(
        started + REACH_BUDGET_S - routing.ANSWER_RESERVE_S, ISOCHRONE_TIMEOUT_S
    )
    moved, _ = routing.move_zoo_points(points)
    reverse = direction == TO
    used = stress_of(preset_name, dials)
    own = dials if used is None or used == dials.stress else _with_stress(dials, used)
    own_options = _ride(preset_name, own, run_pace_kmh)[2]

    def exclusions(rings: list[int]) -> list:
        reach_m = zones_reach_m(own_options, rings)
        if preset_name in ON_FOOT:
            # The closures that close the way on foot and the roads marked closed, as a Walk or
            # a Run plan leaves out (`workzones.foot_zones`).
            _zones, found = work_zones.foot_zones(
                moved,
                dials.when or routing.default_when(),
                blocked_lines=dials.blocked,
                bypass=dials.closure_bypass,
                now_only=dials.closures_now,
                reach_m=reach_m,
            )
            return found
        return stoporder.ride_exclusions(moved, dials, reach_m)

    exclude = exclusions(minutes)
    contours = asked_minutes(minutes)
    # The four standard rings, as the page first asks for them: a kept answer for those holds
    # any of them (a ring turned off since). Its closures are looked up as far as its largest
    # ring reaches; one past a smaller ring's reach changes nothing inside that ring.
    wider = sorted(set(minutes) | set(MINUTES))
    wider_exclude = (
        exclusions(wider)
        if len(wider) <= MAX_RINGS and wider != contours and route_cache.ttl_s() > 0
        else None
    )

    def asks(layer_dials: routing.Dials) -> list[_Ask]:
        variant, costing, options = _ride(preset_name, layer_dials, run_pace_kmh)
        return [
            _Ask(
                variant,
                _payload(costing, options, point, contours, reverse, exclude),
                None
                if wider_exclude is None
                else _payload(costing, options, point, wider, reverse, wider_exclude),
            )
            for point in moved
        ]

    def layer(layer_asks: list[_Ask]) -> tuple[list[dict], list[int]]:
        sets, placed, unplaced = [], [], []
        for index, ask in enumerate(layer_asks):
            rings = ask.rings(minutes, deadline, charge)
            if rings is None:
                logger.info("reach: the %s router could not place point %d", ask.variant, index)
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

    own_asks = asks(own)
    single = len(points) == 1 or combine != EACH
    calm_asks = (
        asks(_with_stress(dials, CALM_STRESS))
        if calm and single and calm_offered(preset_name, dials)
        else None
    )
    groups, unplaced = layer(own_asks)
    calm_groups = None if calm_asks is None else layer(calm_asks)[0]
    return {
        "preset": preset_name,
        "minutes": minutes,
        "direction": direction,
        "combine": combine,
        "stress_used": used,
        "groups": groups,
        "calm": None if calm_groups is None else {"stress": CALM_STRESS, "groups": calm_groups},
        # Whether Calm streets can show anything here (the page hides it if not).
        "calm_offered": calm_offered(preset_name, dials),
        "unplaced": unplaced,
        # Mountain Bike's trail level is held by its plan, not by the rings (`core.mtb`).
        "trail_level_applied": False if preset_name == mtb.PRESET else None,
    }


def _with_stress(dials: routing.Dials, stress: int) -> routing.Dials:
    return replace(dials, stress=stress)
