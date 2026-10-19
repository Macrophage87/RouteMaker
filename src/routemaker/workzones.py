"""Live work zones from the state DOTs' WZDx feeds, read for the planner (FOLLOWUP-WORKZONES).

The owner, 2026-10-04 (OWNER-DECISIONS 341): "We should separate construction into
2 parts: where the road is rideable but would have rough surfaces or hazards, it
should get some penalty, and where the road is closed, route around." Sources (342,
346): Maryland's MDOT SHA WZDx feed (CC0) and VDOT's WZDx feed through SmarterRoads
(the owner's key, on the server only). DC's TOPS permits are left out (the owner,
2026-10-11: too much data).

The reading of each zone (342(3) and 342(4)):

- **closed**: every lane closed and bicycles known to be barred (the feed lists a
  bike lane, and every lane it lists is closed). The planner routes round it
  (Valhalla's `exclude_polygons`).
- **unknown**: every lane closed, bicycles not mentioned. "Penalize only": a heavy
  penalty (`UNKNOWN_PENALTY_S`) and a red warning, never a hard exclusion; a
  deliberate exception to 330's err-closed rule for these temporary closures.
- **penalty**: rideable, with a heads-up. +60 s where only the shoulder is closed
  (or every lane is open with work beside it), +120 s for a lane closed (or an
  impact the feed does not state), +180 s for a flagger, a temporary signal or
  alternating one-way traffic.

A zone counts only while the ride is inside its window (`active`): the planner's
ride time ("when" dial) against the feed's `start_date` and `end_date`.

Pure: no network, no database. `core.workzones` fetches and keeps the snapshot,
and `core.routing` asks `for_plan` and `along`.

WZDx v4.x, as published by the feeds (field names from the WZDx v4.2 specification,
github.com/usdot-jpo-ode/wzdx, read 2026-10-11; Maryland's feed is v4.1, VDOT's v4).
The proxy this was written behind could not reach either feed, so the parser was
built against the specification and hand-made fixtures (tests/data/workzones), not
against a live download: docs/OPERATIONS.md has the check to run once it is live.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

CLOSED, UNKNOWN, PENALTY = "closed", "unknown", "penalty"
# A bike lane blocked with the road open (DDOT's TOPS permits, v0.7.0 "DC closures
# source"): a warning on the route, never a closure, no penalty.
LANE = "lane"
KINDS = (CLOSED, UNKNOWN, PENALTY, LANE)

SHOULDER_PENALTY_S = 60.0
LANE_PENALTY_S = 120.0
FLAGGER_PENALTY_S = 180.0
# All lanes closed, bicycles unspecified (342(3)): heavy enough that a reasonable way
# round is taken, but a route still goes through where there is none.
UNKNOWN_PENALTY_S = 600.0

# `vehicle_impact` values (WZDx v4.x VehicleImpact) that mean one-way alternating
# traffic under a flagger or a temporary signal.
FLAGGED_IMPACTS = frozenset({"alternating-one-way", "flagging", "temporary-traffic-signal"})
# Lane types that are not a travel lane: closing only these leaves the road as it was.
SIDE_LANES = frozenset({"shoulder", "parking", "median"})

SOURCES = {
    "md": "Maryland DOT SHA work zones (WZDx, CC0)",
    "va": "VDOT work zones (WZDx, SmarterRoads)",
    # The DC sources (v0.7.0 plan, "DC closures source"; `routemaker.dc_closures`).
    "dc": "DDOT occupancy permits (TOPS, CC BY 4.0)",
    "mpd": "MPD traffic advisory",
    "alertdc": "AlertDC (HSEMA)",
    "nps": "NPS alerts",
    # Entered or confirmed by a reviewer (v0.7.0; `core.reviewed_closures`).
    "reviewer": "Confirmed by a RouteMaker reviewer",
}

# Where a rider reads more, for a zone that carries no link of its own.
SOURCE_LINKS = {
    "md": "https://filter.ritis.org/wzdx_v4.1/mdot.geojson",
    "va": "https://www.511virginia.org/",
    "dc": "https://catalog.data.gov/dataset/occupancy-permits-via-ddot-tops",
    "mpd": "https://mpdc.dc.gov/newsroom",
    "alertdc": "https://alertdc.dc.gov/",
    "nps": "https://www.nps.gov/",
}

DISCLAIMER = (
    "Work zones are the transportation agencies' own data, read every few minutes. "
    "They may be out of date or wrong, and are not a guarantee the way is open or closed."
)

_EARTH_M = 6_371_008.8
# How near the route a zone's line must lie to be on it, and how much of the zone.
ALONG_M = 15.0
ALONG_SHARE = 0.6
# A zone's ends are trimmed by this much before it is excluded, so the cross streets
# at each end stay open; and the half width of the strip excluded either side.
TRIM_M = 20.0
HALF_WIDTH_M = 6.0
# The router's limits (valhalla/*.json): the total perimeter of the polygons, metres,
# and the vertices, counted over all of them.
MAX_PERIMETER_M = 50_000.0
MAX_VERTICES = 100
# A polygon is at most this many vertices along each side.
MAX_LINE_POINTS = 5
# A closure within this distance of a point the rider placed is not excluded (the
# router could not start or stop there); it is warned of instead.
NEAR_POINT_M = 50.0
# How far beyond the box of the rider's points a closure may lie and still matter.
BOX_MARGIN_M = 5_000.0


@dataclass(frozen=True)
class Zone:
    """One work zone as the planner needs it."""

    zone_id: str
    source: str  # a key of SOURCES
    kind: str  # CLOSED, UNKNOWN or PENALTY
    penalty_s: float
    line: tuple[tuple[float, float], ...]
    road: str | None
    description: str | None
    start: datetime | None
    end: datetime | None
    impact: str | None = None
    reason: str = ""
    # The DC sources' extras (v0.7.0): what is closed, in a line ("Constitution Ave NW,
    # 14th St to 18th St"); the source's own page; when the source published it.
    title: str | None = None
    url: str | None = None
    published: datetime | None = None

    @property
    def firm_end(self) -> bool:
        """Whether the source gives an end: one without "may still apply" on a later ride. A
        reviewer's closure with no end lasts until a reviewer ends it (`core.reviewed_closures`)."""
        return self.end is not None or self.source == "reviewer"

    def to_json(self) -> dict:
        return {
            "id": self.zone_id,
            "source": self.source,
            "kind": self.kind,
            "penalty_s": self.penalty_s,
            "line": [list(p) for p in self.line],
            "road": self.road,
            "description": self.description,
            "start": None if self.start is None else self.start.isoformat(),
            "end": None if self.end is None else self.end.isoformat(),
            "impact": self.impact,
            "reason": self.reason,
            "title": self.title,
            "url": self.url,
            "published": None if self.published is None else self.published.isoformat(),
        }

    @classmethod
    def from_json(cls, row: Mapping) -> Zone:
        return cls(
            zone_id=row["id"],
            source=row["source"],
            kind=row["kind"],
            penalty_s=float(row["penalty_s"]),
            line=tuple((float(p[0]), float(p[1])) for p in row["line"]),
            road=row.get("road"),
            description=row.get("description"),
            start=_when(row.get("start")),
            end=_when(row.get("end")),
            impact=row.get("impact"),
            reason=row.get("reason") or "",
            title=row.get("title"),
            url=row.get("url"),
            published=_when(row.get("published")),
        )


def _when(value) -> datetime | None:
    """A WZDx date-time (RFC 3339), as an aware datetime; None where absent or unreadable.
    A time with no offset is read as UTC."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _lanes(properties: Mapping) -> list[tuple[str, str]]:
    out = []
    for lane in properties.get("lanes") or []:
        if isinstance(lane, Mapping):
            out.append((str(lane.get("type") or "general"), str(lane.get("status") or "")))
    return out


def classify(properties: Mapping) -> tuple[str, float, str]:
    """(kind, penalty seconds, why) for a road event's properties (342(3), 342(4))."""
    impact = str(properties.get("vehicle_impact") or "unknown")
    lanes = _lanes(properties)
    if impact == "all-lanes-closed":
        bike = [status for kind, status in lanes if kind == "bike-lane"]
        if bike and all(status == "closed" for _, status in lanes):
            return CLOSED, 0.0, "every lane closed, the bike lane included"
        return UNKNOWN, UNKNOWN_PENALTY_S, "every lane closed; bicycles not mentioned"
    if impact in FLAGGED_IMPACTS or any(status == "alternating-flow" for _, status in lanes):
        return PENALTY, FLAGGER_PENALTY_S, "flagger or alternating one-way traffic"
    closed = [kind for kind, status in lanes if status == "closed"]
    if closed and all(kind in SIDE_LANES for kind in closed):
        return PENALTY, SHOULDER_PENALTY_S, "shoulder closed"
    if closed or impact.startswith("some-lanes-closed"):
        return PENALTY, LANE_PENALTY_S, "a lane closed"
    if impact.startswith("all-lanes-open"):
        return PENALTY, SHOULDER_PENALTY_S, "work beside the road, every lane open"
    return PENALTY, LANE_PENALTY_S, "lane closures not stated"


def _line(geometry: Mapping) -> tuple[tuple[float, float], ...]:
    """A LineString as given; a MultiPoint (WZDx's start and end points) as the line
    between its first and last point; a MultiLineString's parts joined."""
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if kind == "LineString":
        points = coordinates
    elif kind == "MultiPoint":
        points = [coordinates[0], coordinates[-1]] if len(coordinates) >= 2 else []
    elif kind == "MultiLineString":
        points = [p for part in coordinates for p in part]
    else:
        points = []
    line = []
    for p in points:
        try:
            point = (float(p[0]), float(p[1]))
        except (TypeError, ValueError, IndexError):
            continue
        if -180 <= point[0] <= 180 and -90 <= point[1] <= 90 and (not line or line[-1] != point):
            line.append(point)
    return tuple(line)


def parse_feature(feature: Mapping, source: str) -> Zone | None:
    """One WZDx road event as a Zone, or None: not a work zone, or no line."""
    properties = feature.get("properties") or {}
    # v4.x keeps the shared fields in `core_details`; v3 had them at the top level.
    core = properties.get("core_details") or properties
    if str(core.get("event_type") or "work-zone") != "work-zone":
        return None
    line = _line(feature.get("geometry") or {})
    if len(line) < 2:
        return None
    kind, penalty, why = classify(properties)
    roads = [str(r).strip() for r in core.get("road_names") or [] if str(r).strip()]
    direction = str(core.get("direction") or "").strip()
    road = ", ".join(roads) or None
    if road and direction and direction not in ("unknown", "undefined"):
        road = f"{road} {direction}"
    description = str(core.get("description") or "").strip() or None
    feature_id = feature.get("id") or properties.get("road_event_id") or core.get("name")
    return Zone(
        zone_id=f"{source}-{feature_id}",
        source=source,
        kind=kind,
        penalty_s=penalty,
        line=line,
        road=road,
        description=description[:300] if description else None,
        start=_when(properties.get("start_date")),
        end=_when(properties.get("end_date")),
        impact=properties.get("vehicle_impact"),
        reason=why,
    )


def parse_feed(document: Mapping, source: str) -> list[Zone]:
    """Every work zone of a WZDx WorkZoneFeed (a GeoJSON FeatureCollection)."""
    if document.get("type") != "FeatureCollection":
        raise ValueError("not a WZDx feed: no FeatureCollection")
    zones = []
    for feature in document.get("features") or []:
        if isinstance(feature, Mapping):
            zone = parse_feature(feature, source)
            if zone is not None:
                zones.append(zone)
    return zones


def active(zone: Zone, at: datetime) -> bool:
    """Whether the ride at `at` falls inside the zone's window. A zone with no start
    is in force now; one with no end has not been said to end."""
    if zone.start is not None and at < zone.start:
        return False
    return not (zone.end is not None and at >= zone.end)


# --- Geometry on a local plane -------------------------------------------------


def _xy(lon: float, lat: float, lat0: float) -> tuple[float, float]:
    k = math.pi / 180 * _EARTH_M
    return lon * k * math.cos(math.radians(lat0)), lat * k


def _lonlat(x: float, y: float, lat0: float) -> tuple[float, float]:
    k = math.pi / 180 * _EARTH_M
    return x / (k * math.cos(math.radians(lat0))), y / k


def _length(points: Sequence[tuple[float, float]]) -> float:
    return sum(math.dist(a, b) for a, b in zip(points, points[1:], strict=False))


def _trim(points: list[tuple[float, float]], metres: float) -> list[tuple[float, float]]:
    """The line with `metres` cut from each end; the middle third where it is too short."""
    total = _length(points)
    cut = metres if total > 3 * metres else total / 3

    def at(distance: float) -> tuple[float, float]:
        run = 0.0
        for a, b in zip(points, points[1:], strict=False):
            seg = math.dist(a, b)
            if run + seg >= distance and seg > 0:
                t = (distance - run) / seg
                return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
            run += seg
        return points[-1]

    start, end = cut, total - cut
    middle = []
    run = 0.0
    for a, b in zip(points, points[1:], strict=False):
        run += math.dist(a, b)
        if start < run < end:
            middle.append(b)
    return [at(start), *middle, at(end)]


def _thin(points: list[tuple[float, float]], most: int) -> list[tuple[float, float]]:
    """At most `most` points, by Douglas-Peucker with a growing tolerance."""
    if len(points) <= most:
        return points

    def simplify(pts: list, tolerance: float) -> list:
        if len(pts) < 3:
            return pts
        a, b = pts[0], pts[-1]
        best, index = -1.0, 0
        for i, p in enumerate(pts[1:-1], start=1):
            d = _to_segment(p, a, b)
            if d > best:
                best, index = d, i
        if best <= tolerance:
            return [a, b]
        return simplify(pts[: index + 1], tolerance)[:-1] + simplify(pts[index:], tolerance)

    tolerance = 1.0
    out = simplify(points, tolerance)
    while len(out) > most:
        tolerance *= 2
        out = simplify(points, tolerance)
    return out


def _to_segment(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    t = (
        0.0
        if length2 == 0
        else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2))
    )
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def polygon(zone: Zone) -> list[list[float]] | None:
    """The strip the router is to leave out for a zone: its line trimmed at both
    ends, thinned, and widened `HALF_WIDTH_M` each side; a closed ring of [lon, lat]
    pairs (Valhalla's `exclude_polygons` entry). None for a line under 1 m."""
    return line_ring(zone.line, TRIM_M)


def line_ring(line: Sequence[Sequence[float]], trim_m: float = 0.0) -> list[list[float]] | None:
    """`polygon`'s strip round any line of [lon, lat] pairs, `trim_m` cut from each end:
    a closed ring, or None for a line under 1 m. A road a rider marked closed (v0.8.2,
    `blocked_lines`) is left out whole, untrimmed."""
    lat0 = line[0][1]
    points = [_xy(lon, lat, lat0) for lon, lat in line]
    if _length(points) < 1.0:
        return None
    if trim_m > 0:
        points = _trim(points, trim_m)
    points = _thin(points, MAX_LINE_POINTS)
    left, right = [], []
    for i, p in enumerate(points):
        a = points[max(i - 1, 0)]
        b = points[min(i + 1, len(points) - 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        norm = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / norm * HALF_WIDTH_M, dx / norm * HALF_WIDTH_M
        left.append((p[0] + nx, p[1] + ny))
        right.append((p[0] - nx, p[1] - ny))
    ring = left + right[::-1]
    ring.append(ring[0])
    return [[round(c, 6) for c in _lonlat(x, y, lat0)] for x, y in ring]


def ring_perimeter_m(ring: Sequence[Sequence[float]]) -> float:
    lat0 = ring[0][1]
    return _length([_xy(lon, lat, lat0) for lon, lat in ring])


def _distance_to_line(point: tuple[float, float], line_xy: list[tuple[float, float]]) -> float:
    return min(
        (_to_segment(point, a, b) for a, b in zip(line_xy, line_xy[1:], strict=False)),
        default=math.inf,
    )


def _samples(points: list[tuple[float, float]], step: float = 20.0) -> list[tuple[float, float]]:
    out = [points[0]]
    for a, b in zip(points, points[1:], strict=False):
        seg = math.dist(a, b)
        n = max(1, int(seg // step))
        out.extend(
            (a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(1, n + 1)
        )
    return out


@dataclass(frozen=True)
class Passage:
    """The route passing along a zone, from `from_m` to `to_m` metres along its line."""

    zone: Zone
    from_m: float
    to_m: float


def along(coordinates: Sequence[Sequence[float]], zones: Iterable[Zone]) -> list[Passage]:
    """The zones the route's line (lon, lat pairs, in order) runs along, in route
    order: at least `ALONG_SHARE` of the zone's trimmed line within `ALONG_M` of it.
    A street the route only crosses is not along it."""
    if len(coordinates) < 2:
        return []
    lat0 = coordinates[0][1]
    route = [_xy(c[0], c[1], lat0) for c in coordinates]
    cumulative = [0.0]
    for a, b in zip(route, route[1:], strict=False):
        cumulative.append(cumulative[-1] + math.dist(a, b))
    xs = [p[0] for p in route]
    ys = [p[1] for p in route]
    box = (min(xs) - 100, min(ys) - 100, max(xs) + 100, max(ys) + 100)
    found = []
    for zone in zones:
        points = [_xy(lon, lat, lat0) for lon, lat in zone.line]
        if not any(box[0] <= x <= box[2] and box[1] <= y <= box[3] for x, y in points):
            continue
        if _length(points) < 1.0:
            continue
        samples = _samples(_trim(points, TRIM_M))
        # Only the route's segments near the zone are measured against.
        zx = [x for x, _ in points]
        zy = [y for _, y in points]
        near_box = (min(zx) - ALONG_M, min(zy) - ALONG_M, max(zx) + ALONG_M, max(zy) + ALONG_M)
        nearby = [
            i
            for i in range(len(route) - 1)
            if min(xs[i], xs[i + 1]) <= near_box[2]
            and max(xs[i], xs[i + 1]) >= near_box[0]
            and min(ys[i], ys[i + 1]) <= near_box[3]
            and max(ys[i], ys[i + 1]) >= near_box[1]
        ]
        if not nearby:
            continue
        near = []
        for s in samples:
            best, at = math.inf, 0.0
            for i in nearby:
                a, b = route[i], route[i + 1]
                d = _to_segment(s, a, b)
                if d < best:
                    seg = math.dist(a, b)
                    t = (
                        0.0
                        if seg == 0
                        else max(
                            0.0,
                            min(
                                1.0,
                                ((s[0] - a[0]) * (b[0] - a[0]) + (s[1] - a[1]) * (b[1] - a[1]))
                                / seg**2,
                            ),
                        )
                    )
                    best, at = d, cumulative[i] + t * seg
            if best <= ALONG_M:
                near.append(at)
        if near and len(near) >= ALONG_SHARE * len(samples):
            found.append(Passage(zone, min(near), max(near)))
    return sorted(found, key=lambda p: (p.from_m, p.zone.zone_id))


# --- What a plan does with them ------------------------------------------------


@dataclass
class PlanZones:
    """The zones in force for one plan: the closures it routes round (as polygons),
    and the zones it may pass with a penalty."""

    status: dict[str, str]  # source -> "current", "stale" or "unavailable"
    exclude: list[list[list[float]]] = field(default_factory=list)
    excluded: list[Zone] = field(default_factory=list)
    # Closures that could not be excluded (near a point placed, or past the router's
    # limits): they are warned of as unknown-access closures are.
    unexcluded: list[Zone] = field(default_factory=list)
    passable: list[Zone] = field(default_factory=list)
    # Penalty zones the plan chose to route round (`core.routing`).
    avoided: list[Zone] = field(default_factory=list)
    # The v0.7.0 additions ("Closures on the map"). Closures the rider chose to route
    # through ("Route through anyway", for this plan only); closures with no end given
    # on a ride later than now ("may still apply": warned of, never routed round by
    # default); bike lanes blocked with the road open (a warning only).
    bypassed: list[Zone] = field(default_factory=list)
    uncertain: list[Zone] = field(default_factory=list)
    lanes: list[Zone] = field(default_factory=list)
    # The ride's moment the zones were matched against, and whether it is later than now.
    at: datetime | None = None
    future: bool = False
    # What each closure did to this route (`core.workzones.measure_delays`): the closures
    # the route would otherwise have taken, and the seconds the way round adds (None
    # where it was not worked out in time). For a bypassed closure, the seconds going
    # round it would add.
    affecting: set[str] = field(default_factory=set)
    delays: dict[str, float | None] = field(default_factory=dict)
    # The park-level and text-only notices ("Check before you go") in force at the ride.
    notices: list = field(default_factory=list)
    # v0.8.2 (the owner, 2026-10-17: "There are several closures marked that aren't actually
    # closed. We should have both the standard route and the detour"): the router's trip with
    # the closures that changed the route left in (`measure_delays`), offered beside the
    # detour as `closure_through`; None where none changed it or it was not asked in time.
    through: dict | None = None
    # The rings of the roads the rider marked closed on this ride (`blocked_lines`), at the
    # end of `exclude`: kept out of every request, even where the closures are let back in.
    blocked: list[list[list[float]]] = field(default_factory=list)

    @property
    def any(self) -> bool:
        return bool(
            self.excluded
            or self.unexcluded
            or self.passable
            or self.bypassed
            or self.uncertain
            or self.lanes
        )

    def every_zone(self) -> list[Zone]:
        """Every zone in force for the plan, each once."""
        seen: dict[str, Zone] = {}
        for group in (
            self.excluded,
            self.unexcluded,
            self.passable,
            self.avoided,
            self.bypassed,
            self.uncertain,
            self.lanes,
        ):
            for zone in group:
                seen.setdefault(zone.zone_id, zone)
        return list(seen.values())

    def penalties_s(self, passages: Iterable[Passage]) -> float:
        return sum(p.zone.penalty_s for p in passages)


def _box(points: Sequence[Sequence[float]]) -> tuple[float, float, float, float]:
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    lat0 = sum(lats) / len(lats)
    dlat = BOX_MARGIN_M / (math.pi / 180 * _EARTH_M)
    dlon = dlat / max(math.cos(math.radians(lat0)), 0.01)
    return min(lons) - dlon, min(lats) - dlat, max(lons) + dlon, max(lats) + dlat


def _in_box(zone: Zone, box) -> bool:
    return any(box[0] <= lon <= box[2] and box[1] <= lat <= box[3] for lon, lat in zone.line)


def _near_point(zone: Zone, points: Sequence[Sequence[float]]) -> bool:
    lat0 = zone.line[0][1]
    line = [_xy(lon, lat, lat0) for lon, lat in zone.line]
    return any(_distance_to_line(_xy(p[0], p[1], lat0), line) <= NEAR_POINT_M for p in points)


def fit_polygons(zones: Sequence[Zone], centre, used_m: float = 0.0, used_vertices: int = 0):
    """The zones' polygons, nearest `centre` (lon, lat) first, as many as fit the
    router's limits beside what is already used. (polygons, fitted zones, left out)."""
    rings, fitted, left = [], [], []
    for zone in sorted(zones, key=lambda z: _centre_distance(z, centre)):
        ring = polygon(zone)
        if ring is None:
            left.append(zone)
            continue
        perimeter = ring_perimeter_m(ring)
        if used_m + perimeter > MAX_PERIMETER_M or used_vertices + len(ring) > MAX_VERTICES:
            left.append(zone)
            continue
        used_m += perimeter
        used_vertices += len(ring)
        rings.append(ring)
        fitted.append(zone)
    return rings, fitted, left


def _centre_distance(zone: Zone, centre) -> float:
    lat0 = centre[1]
    c = _xy(centre[0], centre[1], lat0)
    return min(math.dist(c, _xy(lon, lat, lat0)) for lon, lat in zone.line)


def budget_used(rings: Sequence[Sequence[Sequence[float]]]) -> tuple[float, int]:
    return sum(ring_perimeter_m(r) for r in rings), sum(len(r) for r in rings)


# A ride more than this after the plan is made is a later ride: a closure with no end
# given "may still apply" then, and is not routed round by default (v0.7.0).
FUTURE_AFTER_S = 2 * 60 * 60.0


def is_future(at: datetime, now: datetime | None) -> bool:
    return now is not None and (at - now).total_seconds() > FUTURE_AFTER_S


# The sources whose zones are closures that may happen, not ones known to be on now: DDOT's
# occupancy permits, which allow a road to be closed in their window (DDOT's own note: start
# and end times unreliable). The owner, 2026-10-19: "The road closures are mostly for roads
# that could potentially be closed in the near future in DC. They aren't as useful for on
# the go routing, but worth keeping for future ride planning." So Go and a ride leave them
# out (`now_only`); Plan keeps them.
POSSIBLE_SOURCES = frozenset({"dc"})


def possible(zone: Zone) -> bool:
    """Whether the zone is a closure that may happen (a permit), not one known to be on."""
    return zone.source in POSSIBLE_SOURCES


def for_plan(
    zones: Iterable[Zone],
    at: datetime,
    points: Sequence[Sequence[float]],
    status: dict[str, str],
    now: datetime | None = None,
    bypass: Iterable[str] = (),
    reserve: tuple[float, int] = (0.0, 0),
    now_only: bool = False,
) -> PlanZones:
    """What a plan through `points` (lon, lat) at ride time `at` does with the zones.

    `reserve` is the router's polygon budget (perimeter, vertices) already taken by the
    roads the rider marked closed (v0.8.2): the closures fit in what is left.

    `now` is when the plan is made: a closure with no end given, on a ride later than
    that (`FUTURE_AFTER_S`), "may still apply" and is warned of, not routed round.
    `bypass` names the closures the rider chose to route through for this plan. `now_only`
    (Go and a ride) leaves out the closures that may happen (`possible`): DDOT's permits."""
    future = is_future(at, now)
    plan = PlanZones(status=dict(status), at=at, future=future)
    if not points:
        return plan
    bypassed = set(bypass)
    box = _box(points)
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    centre = (sum(lons) / len(lons), sum(lats) / len(lats))
    closures = []
    for zone in zones:
        if not active(zone, at) or not _in_box(zone, box):
            continue
        if now_only and possible(zone):
            continue
        if zone.kind == LANE:
            plan.lanes.append(zone)
            continue
        if zone.kind in (CLOSED, UNKNOWN) and zone.zone_id in bypassed:
            plan.bypassed.append(zone)
            continue
        if zone.kind == CLOSED and future and not zone.firm_end:
            plan.uncertain.append(zone)
            continue
        if zone.kind == CLOSED:
            if _near_point(zone, points):
                plan.unexcluded.append(zone)
            else:
                closures.append(zone)
        else:
            plan.passable.append(zone)
    plan.exclude, plan.excluded, left = fit_polygons(closures, centre, *reserve)
    plan.unexcluded.extend(left)
    return plan


# --- The words -----------------------------------------------------------------


def heads_up(zone: Zone) -> str:
    """The description's sentence for a zone on the route: short, as Ride says it on the
    move (the owner, 2026-10-17: "the statement is way too verbose. We can cite our sources
    without all that extra noise"). Where it is, the source and until when are the
    entry's `citation`, shown in small text and not read out."""
    name = zone.road or "The road"
    on = f" on {zone.road}" if zone.road else ""
    if zone.kind == CLOSED:
        return f"{name} marked closed ahead."
    if zone.kind == UNKNOWN:
        return f"{name} has every lane closed ahead; bike access unclear."
    if zone.kind == LANE:
        return f"Bike lane blocked ahead{on}."
    reason = (zone.reason or "").rstrip(".")
    lead = "Heads-up" if zone.source in DC_SOURCES else "Work zone ahead"
    return f"{lead}{on}, {reason}." if reason else f"{lead}{on}."


def citation(zone: Zone) -> str:
    """The small print under a zone's sentence: its source, and until when."""
    source = SOURCES.get(zone.source, zone.source)
    return f"Source: {source}" + (f", until {date_text(zone.end)}." if zone.end else ".")


def split_words(zone: Zone | None) -> str:
    """Where the route leaves the standard way for a closure it goes round (v0.8.2): the
    owner's "this road/bike path has been marked for closure, detour posted"."""
    name = zone.road if zone is not None and zone.road else "The road ahead"
    return f"{name} marked closed. Detour posted."


# The sources whose zones are DC's closures and blocked lanes, not work zones (v0.7.0).
DC_SOURCES = frozenset({"dc", "mpd", "alertdc"})
# The sources whose closed zones are said as a road closed, not a work zone: DC's, and the
# closures a reviewer confirmed.
CLOSURE_SOURCES = DC_SOURCES | {"reviewer"}


# --- The card's words (v0.7.0, "Closures on the map") ------------------------------

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _local(moment: datetime) -> datetime:
    from .ridetime import ZONE

    return moment.astimezone(ZONE)


def clock_text(moment: datetime) -> str:
    """'4:30 am', '1 pm', 'noon', in the region's time."""
    local = _local(moment)
    if local.hour == 12 and local.minute == 0:
        return "noon"
    if local.hour == 0 and local.minute == 0:
        return "midnight"
    hour = local.hour % 12 or 12
    half = "am" if local.hour < 12 else "pm"
    return f"{hour}:{local.minute:02d} {half}" if local.minute else f"{hour} {half}"


def date_text(moment: datetime) -> str:
    """'Oct 20', in the region's time."""
    local = _local(moment)
    return f"{_MONTHS[local.month - 1]} {local.day}"


def day_text(moment: datetime, now: datetime | None) -> str:
    """'today', 'tomorrow', or 'Sat, Oct 17', in the region's time."""
    local = _local(moment)
    if now is not None:
        today = _local(now).date()
        if local.date() == today:
            return "today"
        if (local.date() - today).days == 1:
            return "tomorrow"
    return f"{_DAYS[local.weekday()]}, {date_text(moment)}"


def when_text(zone: Zone, now: datetime | None, future: bool) -> str:
    """When the closure applies, as the card says it: "Closed today 4:30 am to 1:30 pm",
    "Permit: road closed until Oct 20", "May still apply: no end time given"."""
    verb = "Bike lane blocked" if zone.kind == LANE else "Closed"
    if zone.source == "dc":
        verb = "Permit: bike lane blocked" if zone.kind == LANE else "Permit: road closed"
    start, end = zone.start, zone.end
    if end is None:
        lead = f"{verb} from {day_text(start, now)} {clock_text(start)}" if start else verb
        if zone.source == "reviewer":
            return f"{lead} until a reviewer ends it"
        if future:
            return f"{lead}; no end time given, so it may still apply on your ride day"
        return f"{lead}; no end time given"
    if start is not None and _local(start).date() == _local(end).date():
        return f"{verb} {day_text(start, now)} {clock_text(start)} to {clock_text(end)}"
    if start is not None and (end - start).total_seconds() < 36 * 3600:
        return (
            f"{verb} {day_text(start, now)} {clock_text(start)} to "
            f"{day_text(end, now)} {clock_text(end)}"
        )
    if start is not None and now is not None and start > now:
        return f"{verb} from {date_text(start)} until {date_text(end)}"
    return f"{verb} until {date_text(end)}"


def source_text(zone: Zone) -> str:
    """The source, named as the card names it: "MPD traffic advisory, Oct 15"."""
    name = SOURCES.get(zone.source, zone.source)
    if zone.source == "dc":
        name = "DDOT occupancy permit (TOPS)"
    if zone.published is not None and zone.source in ("mpd", "alertdc"):
        return f"{name}, {date_text(zone.published)}"
    return name


def minutes_text(seconds: float) -> str:
    minutes = round(seconds / 60)
    if minutes < 1:
        return "under a minute"
    return f"about {minutes} min"


ON_ROUTE, ROUTED_ROUND, BYPASSED, MAY_APPLY, NO_EFFECT = (
    "on_route",
    "routed_round",
    "bypassed",
    "may_still_apply",
    "none",
)


def effect_text(zone: Zone, effect: str, delay_s: float | None) -> str:
    """What the closure does to this route, and the delay its detour adds."""
    if effect == ROUTED_ROUND:
        if delay_s is None:
            return "Your route goes round it."
        return f"Detour adds {minutes_text(delay_s)}"
    if effect == BYPASSED:
        said = "You chose to route through it; a small marker stays on the line."
        if delay_s is not None:
            said += f" Going round would add {minutes_text(delay_s)}."
        return said
    if effect == MAY_APPLY:
        return (
            "On your route. It may still apply on your ride day; the route was not changed for it."
        )
    if effect == ON_ROUTE:
        if zone.kind == LANE:
            return "On your route: the bike lane is blocked here; the road stays open."
        if zone.kind == UNKNOWN:
            return (
                "On your route: every lane closed; the agency does not say whether bicycles "
                "can pass."
            )
        return "On your route: no way round it was found. Walk through or choose another way."
    return "No effect on your route"


def severity(zone: Zone) -> str:
    """The entry's severity: red for a closure the rider may meet, orange otherwise."""
    return "red" if zone.kind in (CLOSED, UNKNOWN) else "orange"


__all__ = [
    "BYPASSED",
    "CLOSED",
    "DC_SOURCES",
    "DISCLAIMER",
    "FLAGGER_PENALTY_S",
    "FUTURE_AFTER_S",
    "KINDS",
    "LANE",
    "POSSIBLE_SOURCES",
    "LANE_PENALTY_S",
    "MAY_APPLY",
    "NO_EFFECT",
    "ON_ROUTE",
    "ROUTED_ROUND",
    "SOURCE_LINKS",
    "effect_text",
    "is_future",
    "source_text",
    "when_text",
    "PENALTY",
    "Passage",
    "PlanZones",
    "SHOULDER_PENALTY_S",
    "SOURCES",
    "UNKNOWN",
    "UNKNOWN_PENALTY_S",
    "Zone",
    "active",
    "along",
    "budget_used",
    "classify",
    "fit_polygons",
    "for_plan",
    "citation",
    "heads_up",
    "line_ring",
    "parse_feature",
    "parse_feed",
    "polygon",
    "ring_perimeter_m",
    "severity",
    "split_words",
]
