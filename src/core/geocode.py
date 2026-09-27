"""Place search and place names, from the self-hosted Photon.

PLAN.md:60 and :65: Photon is reachable only through the API, which proxies it
under a per-client limit, since Photon has no notion of a client and cannot
limit anyone itself. The owner's decision of 2026-09-27 (OWNER-DECISIONS
2026-09-26b items 11-12, and the follow-up asking for human place names on the
start and end) is that both work signed out, like the rest of planning.

This module is the proxy's client and its answer's shape. It is not an open
proxy: the Photon URL is built here from a fixed path and from nothing but the
parameters named below - the query, an optional location bias, a result count
and a language this index was imported with - and every search is fenced to
`settings.COVERAGE_BBOX` by Photon's own `bbox` parameter, with each result
checked against the box again on the way out. What comes back is a small list
of `{name, label, lon, lat, kind}`, never Photon's own GeoJSON, so nothing
Photon adds to its answer reaches a visitor by accident.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

# Photon's data is OpenStreetMap's (ODbL); the geocoder itself is Photon.
ATTRIBUTION = (
    "© OpenStreetMap contributors, ODbL",
    "Place search: Photon (komoot), Apache 2.0",
)

# More than a typeahead can show and a small, bounded answer.
MAX_RESULTS = 10
DEFAULT_RESULTS = 6

# How far from the point Photon may look for something to name it by, in km.
# A route point is placed on a road; 250 m finds the road or the place it is
# on, and past that a name would describe somewhere else.
REVERSE_RADIUS_KM = 0.25

# The most of Photon's answer that is read. Ten results with full address
# fields are a few kilobytes.
MAX_ANSWER_BYTES = 256 * 1024


class Unavailable(Exception):
    """Photon did not answer, or answered with something that is not a result."""


def _bbox_param() -> str:
    west, south, east, north = settings.COVERAGE_BBOX
    return f"{west},{south},{east},{north}"


def inside(lon: float, lat: float) -> bool:
    west, south, east, north = settings.COVERAGE_BBOX
    return west <= lon <= east and south <= lat <= north


def _get(path: str, params: dict) -> dict:
    """GET Photon's `path` with `params`; the one place this module touches the network."""
    url = f"{settings.PHOTON_URL.rstrip('/')}{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=settings.PHOTON_TIMEOUT_S) as response:  # noqa: S310
            body = response.read(MAX_ANSWER_BYTES + 1)
    except (TimeoutError, urllib.error.URLError, ConnectionError, OSError) as error:
        raise Unavailable(str(error)) from error
    if len(body) > MAX_ANSWER_BYTES:
        raise Unavailable("the geocoder's answer is larger than expected")
    try:
        answer = json.loads(body)
    except ValueError as error:
        raise Unavailable("the geocoder did not answer with JSON") from error
    if not isinstance(answer, dict) or not isinstance(answer.get("features"), list):
        raise Unavailable("the geocoder's answer has no features")
    return answer


def search(
    q: str, *, lat: float | None = None, lon: float | None = None, limit: int, lang: str
) -> list[dict]:
    """Places matching `q` inside the coverage box, nearest `lat, lon` first when given."""
    params: dict = {"q": q, "limit": limit, "lang": lang, "bbox": _bbox_param()}
    if lat is not None and lon is not None:
        params["lat"] = lat
        params["lon"] = lon
    return results(_get("/api", params), reverse=False)[:limit]


def reverse(lat: float, lon: float, *, lang: str) -> list[dict]:
    """What the point is on or at: at most one result, inside the coverage box."""
    params = {"lat": lat, "lon": lon, "lang": lang, "limit": 1, "radius": REVERSE_RADIUS_KM}
    return results(_get("/reverse", params), reverse=True)[:1]


def _text(properties: dict, key: str) -> str:
    value = properties.get(key)
    return value.strip() if isinstance(value, str) else ""


def _point(feature: dict) -> tuple[float, float] | None:
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") != "Point":
        return None
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        return None
    try:
        lon, lat = float(coordinates[0]), float(coordinates[1])
    except (TypeError, ValueError):
        return None
    return lon, lat


def describe(properties: dict, *, reverse: bool) -> tuple[str, str]:
    """A short name and a one-line label for a Photon result's properties.

    Search shows what was asked for: a place's own name, or the address with
    its house number. Naming a route point (`reverse`) says what the point is
    on - a named place, or the street - and never a house number, since the
    nearest house to a point on a road is a neighbour's, not the point's.
    """
    name = _text(properties, "name")
    street = _text(properties, "street")
    number = _text(properties, "housenumber")
    if not name and street:
        name = street if reverse or not number else f"{number} {street}"
    area = [_text(properties, key) for key in ("district", "locality", "city", "county", "state")]
    if not name:
        name = next((part for part in area if part), "")
    seen = {name.casefold()}
    rest = []
    for part in area:
        if part and part.casefold() not in seen:
            seen.add(part.casefold())
            rest.append(part)
    # A neighbourhood and a town, or a town and a state, is enough to place it.
    label = ", ".join([name, *rest[:2]]) if name else ", ".join(rest[:2])
    return name, label


def results(answer: dict, *, reverse: bool) -> list[dict]:
    """Photon's GeoJSON as the API's list: in the box, named, one per label."""
    out: list[dict] = []
    labels: set[str] = set()
    for feature in answer.get("features", []):
        if not isinstance(feature, dict):
            continue
        point = _point(feature)
        if point is None or not inside(*point):
            continue
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            continue
        name, label = describe(properties, reverse=reverse)
        if not name or label.casefold() in labels:
            continue
        labels.add(label.casefold())
        out.append(
            {
                "name": name,
                "label": label,
                "lon": round(point[0], 6),
                "lat": round(point[1], 6),
                "kind": _text(properties, "type") or "other",
            }
        )
    return out
