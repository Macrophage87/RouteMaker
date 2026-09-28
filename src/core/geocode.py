"""Place search and place names: the self-hosted Photon, and our own route network.

PLAN.md:60 and :65: Photon is reachable only through the API, which proxies it
under a per-client limit, since Photon has no notion of a client and cannot
limit anyone itself. Both endpoints work signed out (PLAN.md's owner
amendments of 2026-09-27).

This module is the proxy's client and its answer's shape. It is not an open
proxy: the Photon URL is built here from a fixed path and from nothing but the
parameters named below - the query, an optional location bias, a result count
and a language this index was imported with - and every search is fenced to
`settings.COVERAGE_BBOX` by Photon's own `bbox` parameter, with each result
checked against the box again on the way out. What comes back is a small list
of `{name, label, lon, lat, kind, osm_type, osm_id, osm_key, osm_value}`, never
Photon's own GeoJSON, so nothing Photon adds to its answer reaches a visitor by
accident.

Naming a route point is not Photon's nearest object. Photon keeps a way as one
point at its centroid, so the nearest object to a point on a trail is as often
a house on the next street (round-1 review: eight trail points, none named for
their trail). A point is named from the road or trail it snaps to on our own
graph - the standard router's `/locate`, which gives each edge's OSM names -
and only when no named edge is within `EDGE_NAME_RADIUS_M` does Photon supply
a nearby place, worded "near X".
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

from routemaker.geo import Point, haversine

# Photon's data is OpenStreetMap's (ODbL); the geocoder itself is Photon.
ATTRIBUTION = (
    "© OpenStreetMap contributors, ODbL",
    "Place search: Photon (komoot), Apache 2.0",
)

# More than a typeahead can show and a small, bounded answer.
MAX_RESULTS = 10
DEFAULT_RESULTS = 6
# Photon is asked for a few more than are shown, since near-identical rows
# (one street's several ways) are folded into one; Photon's own ceiling is
# compose's `-max-results 10`.
PHOTON_MAX_RESULTS = 10
OVERFETCH = 4

# Two results with the same name and the same kind of OSM tag (its key) this
# close together are one place to a rider: a street split into ways tagged
# tertiary and unclassified ("Union Station Drive Northeast" twice), a
# station's twin nodes. The same name on another kind of place - a park and
# its notice board - stays a row of its own.
SAME_PLACE_M = 300

# How far from the point Photon may look for a place to say it is near, in km.
REVERSE_RADIUS_KM = 0.25

# How far from the point a named edge of the route network may be and still
# name it. A point dropped on a trail snaps within a few metres; past 25 m the
# nearest named edge is as likely the street beside the trail.
EDGE_NAME_RADIUS_M = 25
# The router's own answer is small and quick - tens of milliseconds warm - but
# on a loaded host its first answers took up to 2 s (2026-09-28), and a point
# whose lookup times out falls back to "near X".
LOCATE_TIMEOUT_S = 3.0

# A sidepath and the road it runs beside are drawn a few metres apart, so a
# point dropped on the pair cannot say which it meant; within this much of the
# nearest named edge, a named trail is preferred, as the more particular name
# (the Custis Trail beside Washington Boulevard, 2.6 m apart at one sample).
TRAIL_PREFERENCE_M = 5

# A route number ("US 29", "VA 237", "I 66") is listed with the street's name
# on many edges, often first; the name is what a rider calls it.
_ROUTE_REF = re.compile(
    r"^(?:US|I|VA|MD|DC|SR|CR|Route|Rte)[ -]?\d+[A-Z]?(?: (?:Alt|Bus|Business|Truck))?$"
)

# Edge uses that are a crossing of water, not a place on land to be named for.
FERRY_USES = frozenset({"ferry", "rail_ferry"})

# Edge uses (Valhalla's classification.use) that are a trail or path to a rider.
TRAIL_USES = frozenset({"cycleway", "path", "footway", "mountain_bike", "bridleway", "pedestrian"})

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
    """GET Photon's `path` with `params`; the one place this module touches Photon."""
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


def _locate(lat: float, lon: float) -> list:
    """The standard router's `/locate` for one point: the one place this module
    touches the router. Raises Unavailable if it does not answer."""
    from . import routing

    payload = {
        "locations": [{"lat": lat, "lon": lon, "radius": EDGE_NAME_RADIUS_M}],
        "costing": "bicycle",
        "verbose": True,
    }
    url = f"{settings.VALHALLA_UPSTREAMS['standard'].rstrip('/')}/locate"
    try:
        answer = routing._transport(url, payload, LOCATE_TIMEOUT_S)
    except (routing.RouterUnavailable, routing.RouterRefused) as error:
        raise Unavailable(str(error)) from error
    if not isinstance(answer, list):
        raise Unavailable("the router's locate answer is not a list")
    return answer


# --- the query -----------------------------------------------------------------

# US street-type abbreviations, and the directions. OSM spells names out
# ("Wilson Boulevard", "North Glebe Road"), and Photon matched "1100 Wilson
# Blvd" to bus stops rather than the address (round-1 review), so the query is
# spelled out before it is sent.
STREET_TYPES = {
    "blvd": "Boulevard",
    "st": "Street",
    "ave": "Avenue",
    "rd": "Road",
    "dr": "Drive",
    "pkwy": "Parkway",
    "hwy": "Highway",
    "ct": "Court",
    "ln": "Lane",
    "pl": "Place",
    "sq": "Square",
    "ter": "Terrace",
}
DIRECTIONS = {"n": "North", "s": "South", "e": "East", "w": "West"}
QUADRANTS = {"ne": "Northeast", "nw": "Northwest", "se": "Southeast", "sw": "Southwest"}

_TOKEN = re.compile(r"^(?P<word>[A-Za-z]+)\.?(?P<tail>,?)$")


def _word(token: str | None) -> str | None:
    if token is None:
        return None
    match = _TOKEN.match(token)
    return match.group("word").lower() if match else None


def expand_abbreviations(query: str) -> str:
    """The query with US street abbreviations spelled out, where they are
    unambiguously one.

    A street type is expanded after another word, never first: "St Elmo" is a
    saint. "St" in the middle needs more: it is a street at the end of the
    query, before a direction or a comma, or after a number or a letter ("14th
    St", "E St NW") - "Mount St Mary's" keeps its saint. A single-letter
    direction is expanded before a name ("N Glebe Rd") or after a street type
    ("Maple Ave E"), and never before a street type, since "E St" is E Street.
    NE, NW, SE and SW are the District's quadrants wherever they come after a
    word.
    """
    tokens = query.split()
    out = []
    for i, token in enumerate(tokens):
        match = _TOKEN.match(token)
        if not match:
            out.append(token)
            continue
        word, tail = match.group("word").lower(), match.group("tail")
        before = tokens[i - 1] if i else None
        after = tokens[i + 1] if i + 1 < len(tokens) else None
        prev_word, next_word = _word(before), _word(after)
        spelled = None
        if word in STREET_TYPES and i > 0:
            if word != "st":
                spelled = STREET_TYPES[word]
            elif (
                after is None
                or tail
                or next_word in DIRECTIONS
                or next_word in QUADRANTS
                or (before is not None and (before[0].isdigit() or len(before.rstrip(".,")) == 1))
            ):
                spelled = STREET_TYPES[word]
        elif word in DIRECTIONS:
            if after is not None and next_word not in STREET_TYPES and next_word is not None:
                spelled = DIRECTIONS[word]
            elif prev_word in STREET_TYPES and i > 1:
                spelled = DIRECTIONS[word]
        elif word in QUADRANTS and i > 0:
            spelled = QUADRANTS[word]
        out.append(f"{spelled}{tail}" if spelled else token)
    return " ".join(out)


# --- search ----------------------------------------------------------------------


def search(
    q: str, *, lat: float | None = None, lon: float | None = None, limit: int, lang: str
) -> list[dict]:
    """Places matching `q` inside the coverage box, nearest `lat, lon` first when given."""
    params: dict = {
        "q": expand_abbreviations(q),
        "limit": min(limit + OVERFETCH, PHOTON_MAX_RESULTS),
        "lang": lang,
        "bbox": _bbox_param(),
    }
    if lat is not None and lon is not None:
        params["lat"] = lat
        params["lon"] = lon
    return results(_get("/api", params), reverse=False)[:limit]


# --- names for points ---------------------------------------------------------------


def edge_name(located: list) -> dict | None:
    """The name for a point from a `/locate` answer: {name, kind, way_id}.

    The nearest named edge within EDGE_NAME_RADIUS_M, a named trail winning
    within TRAIL_PREFERENCE_M of it. Ferry edges are not what a point on the
    water is on (round-1 review: a point in the Potomac was named for the
    Georgetown ferry). And when the point is on an unnamed trail - the nearest
    edge of all is a path with no name - a street further off is only what it
    is near: kind "near", which the caller words "near <street>" (round-1
    review: an unnamed cycleway at 0 m took the name of a street 13 m away).
    """
    edges = []
    for location in located[:1]:
        for edge in (location or {}).get("edges") or []:
            info = edge.get("edge_info") or {}
            distance = edge.get("distance")
            if not isinstance(distance, (int, float)) or distance > EDGE_NAME_RADIUS_M:
                continue
            use = ((edge.get("edge") or {}).get("classification") or {}).get("use", "")
            if use in FERRY_USES:
                continue
            names = [n.strip() for n in info.get("names") or [] if isinstance(n, str) and n.strip()]
            name = next((n for n in names if not _ROUTE_REF.match(n)), names[0]) if names else None
            edges.append((float(distance), use in TRAIL_USES, name, info.get("way_id")))
    named = [e for e in edges if e[2]]
    if not named:
        return None
    nearest = min(d for d, *_ in named)
    trails = [e for e in named if e[1] and e[0] <= nearest + TRAIL_PREFERENCE_M]
    distance, trail, name, way_id = min(trails or named, key=lambda e: e[0])
    closest = min(edges, key=lambda e: e[0])
    # The nearest edge is a trail and the name is a street further off. (A
    # named trail as the nearest edge would itself be the name: a trail within
    # TRAIL_PREFERENCE_M of the nearest named edge wins.)
    on_unnamed_trail = closest[1] and distance > closest[0] + TRAIL_PREFERENCE_M
    return {
        "name": name,
        "kind": "near" if on_unnamed_trail else "trail" if trail else "street",
        "way_id": way_id if isinstance(way_id, int) and not isinstance(way_id, bool) else None,
    }


def _area(properties: dict, name: str) -> list[str]:
    seen = {name.casefold()}
    rest = []
    for key in ("district", "locality", "city", "county", "state"):
        part = _text(properties, key)
        if part and part.casefold() not in seen:
            seen.add(part.casefold())
            rest.append(part)
    return rest[:2]


def reverse(lat: float, lon: float, *, lang: str) -> list[dict]:
    """What the point is on: the named road or trail it snaps to, or failing
    that "near" a place Photon knows. At most one result.

    Raises Unavailable only when neither the router nor Photon answered.
    """
    try:
        edge = edge_name(_locate(lat, lon))
        router_answered = True
    except Unavailable:
        edge, router_answered = None, False
    try:
        answer = _get(
            "/reverse",
            {"lat": lat, "lon": lon, "lang": lang, "limit": 1, "radius": REVERSE_RADIUS_KM},
        )
        feature = next(
            (
                f
                for f in answer.get("features", [])
                if isinstance(f, dict)
                and (p := _point(f)) is not None
                and inside(*p)
                and isinstance(f.get("properties"), dict)
            ),
            None,
        )
    except Unavailable:
        if not router_answered:
            raise
        feature = None
    properties = feature["properties"] if feature else {}
    point = {"lon": round(lon, 6), "lat": round(lat, 6)}
    if edge is not None:
        name = f"near {edge['name']}" if edge["kind"] == "near" else edge["name"]
        return [
            {
                "name": name,
                "label": ", ".join([name, *_area(properties, edge["name"])]),
                **point,
                "kind": edge["kind"],
                "osm_type": "W" if edge["way_id"] else None,
                "osm_id": edge["way_id"],
                "osm_key": "highway",
                "osm_value": None,
            }
        ]
    if feature is None:
        return []
    name, _label = describe(properties, reverse=True)
    if not name:
        return []
    return [
        {
            "name": f"near {name}",
            "label": ", ".join([f"near {name}", *_area(properties, name)]),
            **point,
            "kind": "near",
            **_osm(properties),
        }
    ]


# --- Photon's answer ------------------------------------------------------------------


def _text(properties: dict, key: str) -> str:
    value = properties.get(key)
    return value.strip() if isinstance(value, str) else ""


def _osm(properties: dict) -> dict:
    """The OSM identity and tag of a result, for a client that matches it to
    its own data (a station's bike entrance) or shows what the place is."""
    osm_type = _text(properties, "osm_type")
    osm_id = properties.get("osm_id")
    return {
        "osm_type": osm_type if osm_type in ("N", "W", "R") else None,
        "osm_id": osm_id if isinstance(osm_id, int) and not isinstance(osm_id, bool) else None,
        "osm_key": _text(properties, "osm_key") or None,
        "osm_value": _text(properties, "osm_value") or None,
    }


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
    its house number. A nearby place named for a route point (`reverse`) never
    carries a house number, since the nearest house to a point on a road is a
    neighbour's, not the point's.
    """
    name = _text(properties, "name")
    street = _text(properties, "street")
    number = _text(properties, "housenumber")
    if not name and street:
        name = street if reverse or not number else f"{number} {street}"
    if not name:
        name = next(
            (
                _text(properties, key)
                for key in ("district", "locality", "city", "county", "state")
                if _text(properties, key)
            ),
            "",
        )
    # A neighbourhood and a town, or a town and a state, is enough to place it.
    return name, ", ".join([name, *_area(properties, name)]) if name else ""


def results(answer: dict, *, reverse: bool) -> list[dict]:
    """Photon's GeoJSON as the API's list: in the box, named, one row per place."""
    out: list[dict] = []
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
        if not name:
            continue
        osm = _osm(properties)
        # Only one name, one kind of tag and 300 m make a row a repeat: two
        # Starbucks 417 m apart share a label and are two places (round-1
        # review), so a label alone folds nothing.
        if any(_same_place(row, name, osm, point) for row in out):
            continue
        out.append(
            {
                "name": name,
                "label": label,
                "lon": round(point[0], 6),
                "lat": round(point[1], 6),
                "kind": _text(properties, "type") or "other",
                **osm,
            }
        )
    return out


def _same_place(row: dict, name: str, osm: dict, point: tuple[float, float]) -> bool:
    return (
        row["name"].casefold() == name.casefold()
        and row["osm_key"] == osm["osm_key"]
        and haversine(Point(row["lon"], row["lat"]), Point(*point)) <= SAME_PLACE_M
    )
