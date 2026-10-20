"""The major road an unnamed service road, path or sidewalk of a route runs beside (the
owner, 2026-10-20, on a frontage road beside East-West Highway: "When going on a service
road, especially next to a major road, say so").

Read at plan time from the router, so it needs no rebuild: for each such way of the route,
Valhalla's `/locate` (auto costing, verbose; one request for all of them) at the middle of
the route's run along it answers the drivable edges within BESIDE_M; the nearest of a
major class (MAJOR_CLASSES, not a ramp) with a name, running within BESIDE_ANGLE of
parallel to the way there, is the road beside it. The route description then calls the way
"service road beside East-West Highway" (`routemaker.describe.beside_words`), on the
ride's card, in its voice and in the directions.

A path the rebuild already named for its street (`sidepath_names_of`: "9th Street
Northwest protected bike lane") keeps that name, and a way with a name of its own is never
asked. The router has BUDGET_S for all of a route's ways together (less when the plan is
short of time); a way it does not answer in time, or answers with no such road, is just
"service road" or "path".
"""

from __future__ import annotations

import logging

from django.conf import settings

from routemaker import describe
from routemaker.geo import Point, bearing, bearing_delta, haversine

logger = logging.getLogger(__name__)

# How far from the way the road's centreline may be: a frontage road or a sidepath and the
# carriageway it runs beside, a divided road's far side aside.
BESIDE_M = 30
# How near parallel the road must run to the way there.
BESIDE_ANGLE = 30.0
# Valhalla's classifications of a road a rider would call major.
MAJOR_CLASSES = frozenset({"motorway", "trunk", "primary", "secondary", "tertiary"})
# The shortest run of a way worth naming: shorter ones are folded into a neighbour anyway.
MIN_RUN_M = 40.0
# The most ways asked about for one route. All of them are asked in one `/locate`, given
# at most BUDGET_S, and never more than a quarter of what the plan has left.
MAX_WAYS = 12
BUDGET_S = 1.0
# What the router answered, by way and spot: a road beside a way changes only at a rebuild.
_CACHE_MAX = 4096
_cache: dict[tuple[int, float, float], str | None] = {}
_MISSING = object()


def _wanted(use: str) -> bool:
    return describe.beside_words(use, "x") is not None


def _spot(pieces: list, indices: list[int]) -> tuple[float, float, float] | None:
    """(lon, lat, bearing) at the middle of the route's run along one way: the piece there,
    and the bearing between the pieces either side of it on the way."""
    total = sum(pieces[i].metres for i in indices)
    at, k = 0.0, 0
    while k < len(indices) - 1 and at + pieces[indices[k]].metres < total / 2:
        at += pieces[indices[k]].metres
        k += 1
    a = pieces[indices[max(k - 1, 0)]]
    b = pieces[indices[min(k + 1, len(indices) - 1)]]
    middle = pieces[indices[k]]
    if a is not b and haversine(Point(a.lon, a.lat), Point(b.lon, b.lat)) > 1.0:
        heading = bearing(Point(a.lon, a.lat), Point(b.lon, b.lat))
    elif middle.heading_in is not None:
        heading = middle.heading_in
    else:
        return None
    return middle.lon, middle.lat, heading


def _shape_bearing(shape: list[tuple[float, float]], lon: float, lat: float) -> float | None:
    """The bearing of the shape's segment nearest (lon, lat)."""
    best: tuple[float, float] | None = None
    for a, b in zip(shape, shape[1:], strict=False):
        mid = Point((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        d = min(haversine(Point(*a), Point(lon, lat)), haversine(mid, Point(lon, lat)))
        if a != b and (best is None or d < best[0]):
            best = (d, bearing(Point(*a), Point(*b)))
    return best[1] if best else None


def road_beside(
    edges: list[dict], way_id: int, heading: float, same_as: frozenset[str] = frozenset()
) -> str | None:
    """The name of the nearest major road among the router's `edges` (a `/locate`
    answer's) that runs within BESIDE_ANGLE of parallel to `heading`, either way; None
    where there is none. With `same_as` (a named service road's names, lower case), only a
    road of one of those names."""
    from .routing import decode_polyline6

    best: tuple[float, str] | None = None
    for edge in edges:
        info = edge.get("edge_info") or {}
        classification = (edge.get("edge") or {}).get("classification") or {}
        if info.get("way_id") == way_id or classification.get("link"):
            continue
        if classification.get("classification") not in MAJOR_CLASSES:
            continue
        names = [n.strip() for n in info.get("names") or [] if isinstance(n, str) and n.strip()]
        name = describe.street_label(names)
        if not name or (same_as and not same_as & {n.lower() for n in names}):
            continue
        try:
            lon, lat = float(edge["correlated_lon"]), float(edge["correlated_lat"])
            shape = decode_polyline6(str(info.get("shape") or ""))
        except (KeyError, TypeError, ValueError):
            continue
        road = _shape_bearing(shape, lon, lat)
        if road is None:
            continue
        angle = bearing_delta(heading, road)
        if min(angle, 180.0 - angle) > BESIDE_ANGLE:
            continue
        distance = float(edge.get("distance") or 0.0)
        if distance <= BESIDE_M and (best is None or distance < best[0]):
            best = (distance, describe.readable(name))
    return best[1] if best else None


def _locate(spots: list[tuple[float, float]], timeout_s: float) -> list[list[dict]]:
    """The router's drivable edges within BESIDE_M of each (lon, lat), in one `/locate`
    (it takes many locations and answers one item each, in order)."""
    from . import routing

    payload = {
        "locations": [{"lat": lat, "lon": lon, "radius": BESIDE_M} for lon, lat in spots],
        "costing": "auto",
        "verbose": True,
    }
    url = f"{settings.VALHALLA_UPSTREAMS['standard'].rstrip('/')}/locate"
    answer = routing._transport(url, payload, timeout_s)
    if not isinstance(answer, list):
        return [[] for _ in spots]
    out = []
    for k in range(len(spots)):
        item = answer[k] if k < len(answer) and isinstance(answer[k], dict) else {}
        out.append([e for e in item.get("edges") or [] if isinstance(e, dict)])
    return out


def _time_left() -> float:
    """BUDGET_S, or less where the plan has less left (`routing._plan_ends`)."""
    from . import routing

    ends = routing._plan_ends.get()
    if ends is None:
        return BUDGET_S
    return min(BUDGET_S, (ends - routing.clock()) / 4)


def names_of(pieces: list, named: dict[int, str] | None = None) -> dict[int, str]:
    """Each unnamed service road, path or sidewalk of the route that runs beside a major
    road, by way id: its name for the description ("service road beside East-West
    Highway"), a `describe.BesideName`. And a service road mapped with the name of the
    major road it runs beside (the owner, 2026-10-20, on East-West Highway's frontage road,
    told "Turn left onto East-West Highway"): named so too, in place of its own name, which
    would otherwise make it one street with the highway. `named` are the ways already
    named (`sidepath_names_of`), left alone. Empty where the router is silent."""
    named = named or {}
    runs: dict[int, list[int]] = {}
    for i, piece in enumerate(pieces):
        if not piece.way_id or piece.way_id in named:
            continue
        if piece.names and describe.SERVICE_WORDS.get(piece.use) != "service road":
            continue
        if _wanted(piece.use):
            runs.setdefault(piece.way_id, []).append(i)
    ways = sorted(
        (w for w, idx in runs.items() if sum(pieces[i].metres for i in idx) >= MIN_RUN_M),
        key=lambda w: -sum(pieces[i].metres for i in runs[w]),
    )[:MAX_WAYS]
    roads: dict[int, str | None] = {}
    asked: list[tuple[int, tuple[int, float, float], float, float, float]] = []
    for way in ways:
        spot = _spot(pieces, runs[way])
        if spot is None:
            continue
        lon, lat, heading = spot
        key = (way, round(lon, 4), round(lat, 4))
        cached = _cache.get(key, _MISSING)
        if cached is _MISSING:
            asked.append((way, key, lon, lat, heading))
        else:
            roads[way] = cached
    left = _time_left()
    if asked and left > 0.05:
        try:
            answers = _locate([(lon, lat) for _w, _k, lon, lat, _h in asked], left)
        except Exception:  # noqa: BLE001 - the ways are just "service road" or "path"
            logger.info(
                "the roads beside the route's unnamed ways could not be read", exc_info=True
            )
            answers = None
        if answers is not None:
            if len(_cache) >= _CACHE_MAX:
                _cache.clear()
            for (way, key, _lon, _lat, heading), edges in zip(asked, answers, strict=True):
                own = frozenset(n.lower() for n in pieces[runs[way][0]].names)
                road = road_beside(edges, way, heading, own)
                _cache[key] = road
                roads[way] = road
    found: dict[int, str] = {}
    for way, road in roads.items():
        words = describe.beside_words(pieces[runs[way][0]].use, road) if road else None
        if words:
            found[way] = describe.BesideName(words)
    return found
