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
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, time, timedelta

from routemaker.lang import spanish, t

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
    # The parks' deer-management closures (v0.12.3; `routemaker.deer_closures`), notices only.
    "nps_deer": "NPS, Rock Creek Park deer management",
    "mcparks": "Montgomery Parks deer management schedule",
    # Entered or confirmed by a reviewer (v0.7.0; `core.reviewed_closures`).
    "reviewer": "Confirmed by a RouteMaker reviewer",
    # DDOT's project traffic advisories, read by hand (v0.12.4; `routemaker.ddot_advisories`).
    "ddot_advisory": "DDOT project traffic advisory",
    # The Purple Line's construction updates, read by hand (v0.13.0; `routemaker.purple_line`).
    "purple_line": "Purple Line construction update",
    # The Fairfax County Park Authority's Park Alerts, read by hand (v0.22.0; `routemaker.fcpa`).
    "fcpa": "Fairfax County Park Authority park alert",
    # The park agencies' trail alerts, read by hand (v0.26.0; `routemaker.park_alerts`).
    "park_alert": "Park agency trail alert",
    # Planned work that may close a road some day in its window (v0.17.0; Plan's Potential
    # closures layer only; `routemaker.planned_work`).
    "protrack": "DDOT capital projects (ProTrack+, CC BY 4.0)",
    "dcwater": "DC Water active work zones",
    "wssc": "WSSC Water water main construction",
    # Maryland's counties' and towns' closures (v0.17.0; `routemaker.md_closures`), routed round.
    "sha": "Maryland Road Closure Reporter (MDOT SHA)",
    # Montgomery County DOT's own road closures (v0.26.0; `routemaker.md_closures`).
    "moco": "Montgomery County DOT road closures",
}

# Where a rider reads more, for a zone that carries no link of its own.
SOURCE_LINKS = {
    "md": "https://filter.ritis.org/wzdx_v4.1/mdot.geojson",
    "va": "https://www.511virginia.org/",
    "dc": "https://catalog.data.gov/dataset/occupancy-permits-via-ddot-tops",
    "mpd": "https://mpdc.dc.gov/newsroom",
    "alertdc": "https://alertdc.dc.gov/",
    "nps": "https://www.nps.gov/",
    "ddot_advisory": "https://projects.ddot.dc.gov/",
    "purple_line": "https://purplelinemd.com/updates",
    "fcpa": "https://www.fairfaxcounty.gov/parks/park-alerts",
    # Each park closure carries its own agency's page (`park-closures.json`'s `page`, required by
    # tests/test_park_alerts.py); this is only a fallback.
    "park_alert": "https://www.nps.gov/choh/planyourvisit/conditions.htm",
    "protrack": "https://opendata.dc.gov/",
    "dcwater": "https://www.dcwater.com/projects",
    "wssc": "https://www.wsscwater.com/what-we-do/constructionin-your-neighborhood-map",
    "sha": "https://data.imap.maryland.gov/datasets/maryland-road-closures",
    "moco": "https://www.montgomerycountymd.gov/dot/",
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
# The router's limits (valhalla/*.json, `service_limits.max_exclude_polygons_length` and
# `max_exclude_polygons_vertices`, set in scripts/build_valhalla_configs.py): the total
# perimeter of the polygons, metres, and the vertices, counted over all of them. A test pins
# these to the configs.
MAX_PERIMETER_M = 50_000.0
MAX_VERTICES = 1000
# The router measures that perimeter its own way (Valhalla 3.9.1, loki/polygon_search.cc
# `edges_in_rings`: `PointLL::Distance`, haversine on a radius of 6,378,160.187 m), about 0.11%
# longer than our own mean-radius plane, and refuses the whole request over it (error 167),
# so a plan packed to the cap by our count was refused outright (hunt Q1, 2026-11-08: 24 of 50
# busy plans). The rings are measured as the router measures them (`ring_perimeter_m`), and
# packed only to `PERIMETER_BUDGET_M`, a small margin under the cap.
VALHALLA_EARTH_M = 6_378_160.187
PERIMETER_BUDGET_M = MAX_PERIMETER_M * 0.99
# A polygon is at most this many vertices along each side. The line is thinned to within
# `THIN_M` of the road, so a 6 m strip still covers a curved road with half its width to
# spare (audit 2026-10-29: thinned to 5 points, a closed road on a long curve drifted 50 to
# 80 ft off its strip, and the blocks in the middle of the curve stayed routable). A line
# that needs more than `MAX_LINE_POINTS` at that tolerance is thinned further, and its strip
# widened by as much, so it still covers the whole road.
MAX_LINE_POINTS = 12
THIN_M = HALF_WIDTH_M / 2
# The part of a closure within this distance of the start is not excluded (the router could
# not start there); the rest of it is (hunt K3, 2026-11-08: a 1 mi trail
# closure whose end was 130 ft from the start was ridden whole). A closure wholly that near, or
# that near a destination or via (whose edge the router can never arrive on), is warned of.
NEAR_POINT_M = 50.0
# Where a way crosses a closure's strip mid-zone (a cross street, a trail on a bridge over the
# closed road or in a tunnel under it), the strip is cut for this far either side of the
# crossing, so the router, which leaves out every edge that meets a strip whole, junction to
# junction and both ways (Valhalla 3.9.1 `line_intersects_ring`, no layer test), keeps the
# crossing way (hunt K4/Q2, 2026-11-08). The closed road's own edges still meet the pieces
# either side. A way crossing at under `CROSS_MIN_DEG` runs along the road, not across it.
# Valhalla's `exclude_levels` does not help: it reads the indoor `level` tag, not
# `layer`/`bridge`/`tunnel`, so nothing on a road's edge says which layer it is on.
CROSS_GAP_M = 2 * HALF_WIDTH_M
CROSS_MIN_DEG = 35.0
# A piece of a closure's strip shorter than this, left between two cuts, is not sent.
MIN_PIECE_M = 4.0
# How far beyond the box of the rider's points a closure may lie and still matter, at least:
# a plan that can go further from them (a loop sized to a target, a climb search, Reach's
# rings) widens it to its own reach (`for_plan`'s `reach_m`, `detour_reach_m`). The closures
# still fit the router's polygon budget nearest first (`fit_polygons`).
BOX_MARGIN_M = 5_000.0

# Lines a feed gives as only their ends (Maryland's MultiPoint: WZDx's start and end points)
# are put on the road between them (`core.workzones.place`), so the map draws the road and
# the planner matches the route against it, not a straight line across the blocks (the
# owner, 2026-10-25, Georgia Ave from Wheaton to Silver Spring: "This should follow the
# road, not be a straight line"). A gap longer than this between two of a line's points is
# routed.
SNAP_GAP_M = 100.0
# The router's way between two ends is taken as the road only when it is at most this much
# longer than the straight line, and, where the feed and the router both name the roads,
# at least `SNAP_NAMED_SHARE` of it is on a road the feed names.
SNAP_RATIO = 1.25
SNAP_SLACK_M = 200.0
SNAP_NAMED_SHARE = 0.5
# A gap that could not be put on its road and is longer than this is not drawn as a straight
# line: the closure's marker stands at the first point the feed gives (`approximate`).
DRAW_STRAIGHT_M = 400.0
# A placed road is kept to within this of the router's shape (Douglas-Peucker), so a long
# zone stays a few dozen points in the stored copy and the map's answer.
PLACED_TOLERANCE_M = 4.0

# Roads a bicycle may not use (the owner, 2026-10-25: "It's not worth mentioning closures on
# roads bikes can't use", of construction on I-97): an Interstate by the feed's name, or a
# line at least `BARRED_SHARE` of whose samples have, as their nearest road within
# `BARRED_NEAR_M`, one the map bars (`core.workzones.without_barred`). Such a zone is not kept.
# One that only starts or ends on a barred road keeps the stretch between its first and last
# open sample (`open_part`; the owner, 2026-10-26, of US 340's zone drawn along the freeway
# past Frederick: "It's also showing construction now on highways not open to bikes"). The
# samples are about `BARRED_STEP_M` apart, at least `BARRED_SAMPLES` and at most `BARRED_MOST`.
# "I-97", "I 495", "Interstate 95", "I-97A", any dash, and a direction before it as MDOT SHA's
# Road Closure Reporter writes one ("WB I 695"); never "I-70 Business", a town street.
INTERSTATE = re.compile(
    r"^\s*(?:(?:nb|sb|eb|wb|northbound|southbound|eastbound|westbound)\s+)?"
    r"(i|ih|is|interstate)[\s\-\u2010-\u2015]*\d+[a-z]?\b(?!.*\bbus(iness)?\b)",
    re.IGNORECASE,
)
BARRED_NEAR_M = 15.0
BARRED_SHARE = 0.6
BARRED_SAMPLES = 20
BARRED_STEP_M = 100.0
BARRED_MOST = 200


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
    # The road names the feed gives (WZDx `road_names`), for putting its line on the road.
    roads: tuple[str, ...] = ()
    # Its line is still a long straight line between points the feed gives, not the road.
    approximate: bool = False
    # The feed gave only its two ends (a MultiPoint, or a line of two points): its line is
    # put on the road between them (`core.workzones.place`).
    from_ends: bool = False
    # Whether the source says the closure holds for people on foot too (Run, Walk and Walk +
    # transit; `for_plan`'s `on_foot`): True, it closes the way on foot as well (a closed
    # sidewalk, a trail closed to walking and biking); False, people on foot are let through
    # (a kept walkway); None, the source does not say. A closure to traffic is not one to
    # people on foot unless its source says so.
    on_foot: bool | None = None
    # The hours of each day it holds, in the region's time, where the source gives a daily or
    # nightly window inside its days ("Nov 14 through Nov 22, 9 pm to 5 am nightly"): (start
    # hour, minute, end hour, minute), an end at or before the start running past midnight.
    # None: it holds the whole of its window (hunt K6, 2026-11-08: a week of nights was read
    # as one week-long closure, and daytime rides went round an open street).
    daily: tuple[int, int, int, int] | None = None
    # An area, not a line (Stephen 2026-11-12: police activity is avoided "by a wide margin";
    # a closure at one corner closes the junction): `line` is then the area's outline, a closed
    # ring, already `margin_m` out from the closed corners or blocks (`dc_closures.area_ring`),
    # and the router leaves out the whole ring (`polygon`), not a strip along a line.
    margin_m: float = 0.0
    # An area's closed corners and blocks themselves ([lon, lat]): where a rider is already in
    # or by the wide area, a re-plan still leaves out `CORE_M` round these (review of #1175).
    core: tuple[tuple[float, float], ...] = ()

    @property
    def area(self) -> bool:
        """Whether the zone is an area (`margin_m`): its `line` is a closed ring."""
        return self.margin_m > 0 and len(self.line) >= 4 and self.line[0] == self.line[-1]

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
            "roads": list(self.roads),
            "approximate": self.approximate,
            "from_ends": self.from_ends,
            "on_foot": self.on_foot,
            "daily": None if self.daily is None else list(self.daily),
            "margin_m": self.margin_m,
            "core": [list(p) for p in self.core],
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
            roads=tuple(str(r) for r in row.get("roads") or ()),
            approximate=bool(row.get("approximate")),
            from_ends=bool(row.get("from_ends")),
            on_foot=_on_foot(row.get("on_foot")),
            daily=_daily(row.get("daily")),
            margin_m=_margin(row.get("margin_m")),
            core=_core(row.get("core")),
        )


def _daily(value) -> tuple[int, int, int, int] | None:
    """A stored `daily`: four whole numbers in range, else None."""
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        hours = tuple(int(v) for v in value)
    except (TypeError, ValueError):
        return None
    if not (
        0 <= hours[0] < 24 and 0 <= hours[1] < 60 and 0 <= hours[2] < 24 and 0 <= hours[3] < 60
    ):
        return None
    return hours  # type: ignore[return-value]


def _margin(value) -> float:
    """A stored `margin_m`: a number from 0 to 2 km, else 0 (a line)."""
    try:
        margin = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return margin if 0.0 < margin <= 2000.0 else 0.0


def _core(value) -> tuple[tuple[float, float], ...]:
    """A stored `core`: [lon, lat] pairs, at most 200; anything else is none."""
    try:
        return tuple((float(p[0]), float(p[1])) for p in (value or ())[:200])
    except (TypeError, ValueError, IndexError):
        return ()


def _on_foot(value) -> bool | None:
    """A stored `on_foot`: True or False as said, None where it is not."""
    return value if isinstance(value, bool) else None


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


def sidewalk_closed(properties: Mapping) -> bool | None:
    """Whether a road event says its sidewalk is closed (a WZDx lane of type "sidewalk"):
    True closed, False open, None where it lists no sidewalk."""
    walks = [status for kind, status in _lanes(properties) if kind == "sidewalk"]
    if not walks:
        return None
    return any(status == "closed" for status in walks)


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
        roads=tuple(roads),
        from_ends=len(line) == 2,
        on_foot=sidewalk_closed(properties),
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
    is in force now; one with no end has not been said to end. One with daily hours
    (`Zone.daily`) holds only in those hours of each of its days, in the region's time."""
    if zone.start is not None and at < zone.start:
        return False
    if zone.end is not None and at >= zone.end:
        return False
    if zone.daily is None:
        return True
    local = _local(at)
    now_min = local.hour * 60 + local.minute
    first, last = zone.daily[0] * 60 + zone.daily[1], zone.daily[2] * 60 + zone.daily[3]
    if first < last:
        return first <= now_min < last
    return now_min >= first or now_min < last


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


def _thin(points: list[tuple[float, float]], most: int) -> tuple[list[tuple[float, float]], float]:
    """At most `most` points, by Douglas-Peucker from `THIN_M`, the tolerance raised until
    they fit; with the tolerance used (0 for a line of two points). Every point of the line
    is within that tolerance of the thinned line."""
    if len(points) <= 2:
        return points, 0.0

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

    tolerance = THIN_M
    out = simplify(points, tolerance)
    if len(out) <= most:
        return out, tolerance
    while len(out) > most:
        tolerance *= 2
        out = simplify(points, tolerance)
    # Back down towards the least tolerance that fits, so the strip is no wider than it needs.
    low = tolerance / 2
    for _ in range(6):
        middle = (low + tolerance) / 2
        tried = simplify(points, middle)
        if len(tried) <= most:
            tolerance, out = middle, tried
        else:
            low = middle
    return out, tolerance


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
    pairs (Valhalla's `exclude_polygons` entry). None for a line under 1 m. An area's ring is
    its outline itself (`Zone.area`)."""
    if zone.area:
        return [[float(p[0]), float(p[1])] for p in zone.line]
    return line_ring(zone.line, TRIM_M)


def line_ring(line: Sequence[Sequence[float]], trim_m: float = 0.0) -> list[list[float]] | None:
    """`polygon`'s strip round any line of [lon, lat] pairs, `trim_m` cut from each end:
    a closed ring, or None for a line under 1 m. A road a rider marked closed (v0.8.2,
    `blocked_lines`) is trimmed as a closure is and cut where a way crosses it (`line_rings`,
    `core.workzones.blocked_rings`; hunt K4/Q2). The strip is `HALF_WIDTH_M` either side,
    wider where the line had to be thinned more than `THIN_M` to fit (`_thin`), and mitred
    at each bend so a turn does not narrow it."""
    lat0 = line[0][1]
    points = [_xy(lon, lat, lat0) for lon, lat in line]
    if _length(points) < 1.0:
        return None
    if trim_m > 0:
        points = _trim(points, trim_m)
    return _strip(points, lat0)


def _strip(points: list[tuple[float, float]], lat0: float) -> list[list[float]] | None:
    """`line_ring`'s strip round a line already on the plane at `lat0` (and trimmed)."""
    points = [p for i, p in enumerate(points) if i == 0 or p != points[i - 1]]
    if len(points) < 2:
        return None
    points, tolerance = _thin(points, MAX_LINE_POINTS)
    half = max(HALF_WIDTH_M, tolerance + THIN_M)

    def normal(a, b) -> tuple[float, float]:
        dx, dy = b[0] - a[0], b[1] - a[1]
        norm = math.hypot(dx, dy) or 1.0
        return -dy / norm, dx / norm

    left, right = [], []
    for i, p in enumerate(points):
        before = normal(points[max(i - 1, 0)], points[max(i, 1)])
        after = normal(points[min(i, len(points) - 2)], points[min(i + 1, len(points) - 1)])
        nx, ny = before[0] + after[0], before[1] + after[1]
        norm = math.hypot(nx, ny)
        if norm < 1e-9:  # the line turns straight back: square across it
            nx, ny, norm = before[0], before[1], 1.0
        nx, ny = nx / norm, ny / norm
        # The mitre: as far out as keeps `half` from both segments, at most twice it.
        reach = half / max(nx * before[0] + ny * before[1], 0.5)
        left.append((p[0] + nx * reach, p[1] + ny * reach))
        right.append((p[0] - nx * reach, p[1] - ny * reach))
    ring = left + right[::-1]
    ring.append(ring[0])
    return [[round(c, 6) for c in _lonlat(x, y, lat0)] for x, y in ring]


def ring_perimeter_m(ring: Sequence[Sequence[float]]) -> float:
    """A ring's perimeter as the router counts it against its limit: haversine on Valhalla's
    own Earth radius (`VALHALLA_EARTH_M`), segment by segment, as Valhalla 3.9.1's
    `edges_in_rings` sums `PointLL::Distance`."""
    total = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(ring, ring[1:], strict=False):
        p1, p2 = math.radians(lat1), math.radians(lat2)
        h = (
            math.sin((p2 - p1) / 2) ** 2
            + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
        )
        total += VALHALLA_EARTH_M * 2 * math.asin(math.sqrt(min(1.0, max(0.0, h))))
    return total


def fits_budget(used_m: float, used_vertices: int, ring: Sequence[Sequence[float]]) -> bool:
    """Whether `ring` fits the router's polygon limits beside what is already used: its
    perimeter within `PERIMETER_BUDGET_M` (the margin under the router's cap), its vertices
    within `MAX_VERTICES`."""
    return (
        used_m + ring_perimeter_m(ring) <= PERIMETER_BUDGET_M
        and used_vertices + len(ring) <= MAX_VERTICES
    )


def over_budget(rings: Sequence[Sequence[Sequence[float]]]) -> bool:
    """Whether `rings` pass the router's polygon limits as this module packs them."""
    perimeter, vertices = budget_used(rings)
    return perimeter > PERIMETER_BUDGET_M or vertices > MAX_VERTICES


def _spans_near(
    line: list[tuple[float, float]], point: tuple[float, float], radius: float
) -> list[tuple[float, float]]:
    """The stretches of `line` (on the plane), as metres along it, within `radius` of `point`."""
    out = []
    run = 0.0
    for a, b in zip(line, line[1:], strict=False):
        seg = math.dist(a, b)
        if seg == 0:
            continue
        dx, dy = (b[0] - a[0]) / seg, (b[1] - a[1]) / seg
        # |a + t (b - a) - p| <= r, with t in metres along the segment.
        px, py = point[0] - a[0], point[1] - a[1]
        along = px * dx + py * dy
        off2 = px * px + py * py - along * along
        if off2 <= radius * radius:
            half = math.sqrt(radius * radius - off2)
            lo, hi = max(0.0, along - half), min(seg, along + half)
            if lo <= hi:
                out.append((run + lo, run + hi))
        run += seg
    return out


def _subtract(
    spans: list[tuple[float, float]], holes: Iterable[tuple[float, float]]
) -> list[tuple[float, float]]:
    """`spans` (metres along a line, in order) less `holes`."""
    out = list(spans)
    for lo, hi in holes:
        cut = []
        for a, b in out:
            if hi <= a or lo >= b:
                cut.append((a, b))
                continue
            if lo > a:
                cut.append((a, lo))
            if hi < b:
                cut.append((hi, b))
        out = cut
    return out


def line_rings(
    line: Sequence[Sequence[float]],
    trim_m: float = 0.0,
    points: Sequence[Sequence[float]] = (),
    crossings: Sequence[float] = (),
) -> list[list[list[float]]]:
    """The strips the router is to leave out for a closed line of [lon, lat] pairs: as
    `line_ring` (`trim_m` cut from each end), less the stretches within `NEAR_POINT_M` of any
    of `points` (the rider's), and cut `CROSS_GAP_M` either side of each of `crossings`
    (metres along the line where a way crosses it: `crossing_cuts`). Empty where nothing is
    left to leave out: a line under 1 m, or one wholly near the points. The crossing cuts never
    leave a line with nothing to leave out; a piece under `MIN_PIECE_M` is not sent. With no
    point near and no crossing, the one ring `line_ring` gives."""
    if len(line) < 2:
        return []
    lat0 = line[0][1]
    xy = [_xy(p[0], p[1], lat0) for p in line]
    total = _length(xy)
    if total < 1.0:
        return []
    cut = 0.0 if trim_m <= 0 else (trim_m if total > 3 * trim_m else total / 3)
    span = [(cut, total - cut)]
    near = [hole for p in points for hole in _spans_near(xy, _xy(p[0], p[1], lat0), NEAR_POINT_M)]
    kept = [s for s in _subtract(span, near) if s[1] - s[0] >= MIN_PIECE_M]
    if near and not kept:
        return []
    gaps = [(c - CROSS_GAP_M, c + CROSS_GAP_M) for c in crossings if cut < c < total - cut]
    pieces = [s for s in _subtract(kept, gaps) if s[1] - s[0] >= MIN_PIECE_M] or kept
    if pieces == span:
        ring = line_ring(line, trim_m)
        return [] if ring is None else [ring]
    rings = []
    for start, end in pieces:
        ring = _strip(_between(xy, start, end), lat0)
        if ring is not None:
            rings.append(ring)
    return rings


# Round an area's closed corners and blocks themselves (`Zone.core`), what is still left out
# where the rider is in or by the wide area: the junction, as a crash's is.
CORE_M = 30.0


def zone_rings(
    zone: Zone, points: Sequence[Sequence[float]] = (), crossings: Sequence[float] = ()
) -> list[list[list[float]]]:
    """A closure's strips (`line_rings`): its line trimmed `TRIM_M` at both ends, less the
    stretches near the rider's `points`, cut at its `crossings`. An area is its one ring; where
    one of `points` lies in it or within `NEAR_POINT_M` of it, the ring `CORE_M` round its
    closed corners and blocks instead (a rider a block from a police cordon is still sent round
    the closed junctions), or none where a point is by those too (warned of, not left out)."""
    if zone.area:
        if not any(near_area(zone, p) for p in points):
            ring = polygon(zone)
            return [] if ring is None else [ring]
        core = area_ring(zone.core, CORE_M) if zone.core else None
        if core is None:
            return []
        inner = replace(zone, line=core, margin_m=CORE_M, core=())
        if any(near_area(inner, p) for p in points):
            return []
        return [[[p[0], p[1]] for p in core]]
    return line_rings(zone.line, TRIM_M, points, crossings)


def area_ring(
    points: Sequence[Sequence[float]], margin_m: float, sides: int = 16
) -> tuple[tuple[float, float], ...] | None:
    """The outline round `points` ([lon, lat]) at `margin_m`: the convex hull of a circle
    of `sides` sides round each, a closed ring; None with no points."""
    if not points or margin_m <= 0:
        return None
    lat0 = float(points[0][1])
    # Out to the corners' circle, so the polygon's sides keep `margin_m` clear too.
    reach = margin_m / math.cos(math.pi / sides)
    around = []
    for lon, lat in points:
        x, y = _xy(float(lon), float(lat), lat0)
        for k in range(sides):
            turn = 2 * math.pi * k / sides
            around.append((x + reach * math.cos(turn), y + reach * math.sin(turn)))
    hull = _hull(around)
    ring = [tuple(round(c, 7) for c in _lonlat(x, y, lat0)) for x, y in hull]
    ring.append(ring[0])
    return tuple((float(p[0]), float(p[1])) for p in ring)


def _hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """The convex hull, anticlockwise (Andrew's monotone chain)."""
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def turn(o, a, b) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and turn(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and turn(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _in_ring(point: tuple[float, float], ring: Sequence[tuple[float, float]]) -> bool:
    """Whether a point lies inside a closed ring (both on the same plane): even-odd rule."""
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:], strict=False):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def near_area(zone: Zone, point: Sequence[float], near_m: float = NEAR_POINT_M) -> bool:
    """Whether a [lon, lat] point lies in an area zone, or within `near_m` of its outline."""
    lat0 = zone.line[0][1]
    ring = [_xy(lon, lat, lat0) for lon, lat in zone.line]
    at = _xy(point[0], point[1], lat0)
    return _in_ring(at, ring) or _distance_to_line(at, ring) <= near_m


def crossing_cuts(
    line: Sequence[Sequence[float]], parts: Iterable[Sequence[Sequence[float]]]
) -> tuple[float, ...]:
    """Metres along `line` ([lon, lat] pairs) where a way crosses it: `parts` are the map's
    ways clipped to the line's strip (`core.workzones.crossings`), and one that runs across
    the line at `CROSS_MIN_DEG` or more, a cross street or a bridge or tunnel over or under
    it, crosses where its middle lies. A way running along the line (the closed road itself,
    a sidepath beside it) does not. In order, those within a metre of another made one."""
    if len(line) < 2:
        return ()
    lat0 = line[0][1]
    xy = [_xy(p[0], p[1], lat0) for p in line]
    cumulative = [0.0]
    for a, b in zip(xy, xy[1:], strict=False):
        cumulative.append(cumulative[-1] + math.dist(a, b))
    found = []
    for part in parts:
        if len(part) < 2:
            continue
        pts = [_xy(p[0], p[1], lat0) for p in part]
        first, last = pts[0], pts[-1]
        length = math.dist(first, last)
        if length < 1.0:
            continue
        middle = ((first[0] + last[0]) / 2, (first[1] + last[1]) / 2)
        best, at, index = math.inf, 0.0, 0
        for i, (a, b) in enumerate(zip(xy, xy[1:], strict=False)):
            d = _to_segment(middle, a, b)
            if d < best:
                seg = math.dist(a, b)
                t = 0.0
                if seg > 0:
                    t = (middle[0] - a[0]) * (b[0] - a[0]) + (middle[1] - a[1]) * (b[1] - a[1])
                    t = max(0.0, min(1.0, t / seg**2))
                best, at, index = d, cumulative[i] + t * seg, i
        a, b = xy[index], xy[index + 1]
        seg = math.dist(a, b)
        if seg == 0:
            continue
        cos = abs(
            ((last[0] - first[0]) * (b[0] - a[0]) + (last[1] - first[1]) * (b[1] - a[1]))
            / (length * seg)
        )
        if math.degrees(math.acos(min(1.0, cos))) >= CROSS_MIN_DEG:
            found.append(at)
    out: list[float] = []
    for at in sorted(found):
        if not out or at - out[-1] > 1.0:
            out.append(at)
    return tuple(round(at, 1) for at in out)


def _segments_cross(a, b, c, d) -> bool:
    """Whether segment a-b meets segment c-d (touching counts)."""

    def side(p, q, r) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    def on(p, q, r) -> bool:
        return min(p[0], q[0]) <= r[0] <= max(p[0], q[0]) and min(p[1], q[1]) <= r[1] <= max(
            p[1], q[1]
        )

    d1, d2, d3, d4 = side(c, d, a), side(c, d, b), side(a, b, c), side(a, b, d)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 and d2 and d3 and d4:
        return True
    return (
        (d1 == 0 and on(c, d, a))
        or (d2 == 0 and on(c, d, b))
        or (d3 == 0 and on(a, b, c))
        or (d4 == 0 and on(a, b, d))
    )


def _in_ring(point, ring) -> bool:
    x, y = point[0], point[1]
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:], strict=False):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def line_meets_ring(line: Sequence[Sequence[float]], ring: Sequence[Sequence[float]]) -> bool:
    """Whether the router leaves out an edge of shape `line` ([lon, lat] pairs) for `ring`:
    any of its segments meets one of the ring's, or its first point is inside the ring
    (Valhalla 3.9.1, loki/polygon_search.cc `line_intersects_ring`)."""
    if len(line) < 2 or len(ring) < 4:
        return False
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    west, east, south, north = min(lons), max(lons), min(lats), max(lats)
    for a, b in zip(line, line[1:], strict=False):
        if max(a[0], b[0]) < west or min(a[0], b[0]) > east:
            continue
        if max(a[1], b[1]) < south or min(a[1], b[1]) > north:
            continue
        for c, d in zip(ring, ring[1:], strict=False):
            if _segments_cross(a, b, c, d):
                return True
    return _in_ring(line[0], ring)


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


class RouteGrid:
    """A line of (lon, lat) pairs' segments in a coarse grid of lon/lat cells, so a zone is
    measured against the few segments near it, not the whole line (core.workzones._RouteIndex,
    and `along`). Segment i, from point i to i+1, is in every cell its box touches, so a box
    that overlaps the segment's box shares a cell with it. Built once per line: one int per
    segment per cell it touches (a few hundred KB for a 100 mi route, freed with the call)."""

    CELL_DEG = 0.01  # about 0.7 mi of longitude here, 0.7 mi of latitude

    def __init__(self, coordinates: Sequence[Sequence[float]]):
        self.coordinates = coordinates
        self.cells: dict[tuple[int, int], list[int]] = {}
        for i, (a, b) in enumerate(zip(coordinates, coordinates[1:], strict=False)):
            for cell in self._cells(
                min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])
            ):
                self.cells.setdefault(cell, []).append(i)

    def _cells(self, west: float, south: float, east: float, north: float):
        size = self.CELL_DEG
        for x in range(math.floor(west / size), math.floor(east / size) + 1):
            for y in range(math.floor(south / size), math.floor(north / size) + 1):
                yield (x, y)

    def segments(self, west: float, south: float, east: float, north: float) -> list[int]:
        """The indices, in order, of the segments in the cells the box touches: every
        segment whose box overlaps it, and some that only share a cell with it."""
        found: set[int] = set()
        for cell in self._cells(west, south, east, north):
            found.update(self.cells.get(cell, ()))
        return sorted(found)


@dataclass(frozen=True)
class Passage:
    """The route passing along a zone, from `from_m` to `to_m` metres along its line."""

    zone: Zone
    from_m: float
    to_m: float


def along(
    coordinates: Sequence[Sequence[float]], zones: Iterable[Zone], near_m: float = ALONG_M
) -> list[Passage]:
    """The zones the route's line (lon, lat pairs, in order) runs along, in route
    order: at least `ALONG_SHARE` of the zone's trimmed line within `near_m` (`ALONG_M`) of it.
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
    # The route's segments in a grid (audit round 3, S27), built for the first zone near it:
    # each zone then looks only at the segments in the cells round its box, not the whole
    # line, and the same box test as before picks the ones it measures against.
    grid: RouteGrid | None = None
    # A hair over the box when it is turned back into degrees, so rounding never drops a
    # segment the box test would keep.
    slack = 1e-7
    found = []
    for zone in zones:
        points = [_xy(lon, lat, lat0) for lon, lat in zone.line]
        if not any(box[0] <= x <= box[2] and box[1] <= y <= box[3] for x, y in points):
            continue
        if _length(points) < 1.0:
            continue
        if zone.area:
            inside = _through_area(route, cumulative, points)
            if inside is not None:
                found.append(Passage(zone, inside[0], inside[1]))
            continue
        samples = _samples(_trim(points, TRIM_M))
        # Only the route's segments near the zone are measured against.
        zx = [x for x, _ in points]
        zy = [y for _, y in points]
        near_box = (min(zx) - near_m, min(zy) - near_m, max(zx) + near_m, max(zy) + near_m)
        if grid is None:
            grid = RouteGrid(coordinates)
        west, south = _lonlat(near_box[0], near_box[1], lat0)
        east, north = _lonlat(near_box[2], near_box[3], lat0)
        nearby = [
            i
            for i in grid.segments(west - slack, south - slack, east + slack, north + slack)
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
            if best <= near_m:
                near.append(at)
        if near and len(near) >= ALONG_SHARE * len(samples):
            found.append(Passage(zone, min(near), max(near)))
    return sorted(found, key=lambda p: (p.from_m, p.zone.zone_id))


def _through_area(
    route: Sequence[tuple[float, float]],
    cumulative: Sequence[float],
    ring: Sequence[tuple[float, float]],
) -> tuple[float, float] | None:
    """Where a route (on the plane, with its metres along) is inside an area's ring: the
    first and last metres along it that are, counting where it crosses the outline; None
    where it never enters. A route that only touches the outline from outside is not in it."""
    marks: list[float] = []
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    box = (min(xs), min(ys), max(xs), max(ys))
    for i, (a, b) in enumerate(zip(route, route[1:], strict=False)):
        if max(a[0], b[0]) < box[0] or min(a[0], b[0]) > box[2]:
            continue
        if max(a[1], b[1]) < box[1] or min(a[1], b[1]) > box[3]:
            continue
        seg = cumulative[i + 1] - cumulative[i]
        if _in_ring(a, ring):
            marks.append(cumulative[i])
        if _in_ring(b, ring):
            marks.append(cumulative[i + 1])
        for c, d in zip(ring, ring[1:], strict=False):
            t = _cross_at(a, b, c, d)
            if t is not None:
                marks.append(cumulative[i] + t * seg)
    if not marks:
        return None
    first, last = min(marks), max(marks)
    if last - first < 1.0:
        return None  # touched, not entered
    return first, last


def _cross_at(a, b, c, d) -> float | None:
    """How far along a-b (0 to 1) it crosses c-d; None where it does not."""
    rx, ry = b[0] - a[0], b[1] - a[1]
    sx, sy = d[0] - c[0], d[1] - c[1]
    den = rx * sy - ry * sx
    if abs(den) < 1e-12:
        return None
    t = ((c[0] - a[0]) * sy - (c[1] - a[1]) * sx) / den
    u = ((c[0] - a[0]) * ry - (c[1] - a[1]) * rx) / den
    return t if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0 else None


# --- Putting a line given by its ends on the road ---------------------------------


def line_m(line: Sequence[Sequence[float]]) -> float:
    """A line of [lon, lat] pairs' length, metres."""
    if len(line) < 2:
        return 0.0
    lat0 = line[0][1]
    return _length([_xy(p[0], p[1], lat0) for p in line])


def gaps(line: Sequence[Sequence[float]]) -> list[int]:
    """The indices i where the line runs more than `SNAP_GAP_M` straight from point i to i+1."""
    return [i for i in range(len(line) - 1) if line_m(line[i : i + 2]) > SNAP_GAP_M]


_ROAD_WORDS = {"maryland": "md", "virginia": "va", "interstate": "i", "route": "", "rte": ""}
_BOUND = {"nb", "sb", "eb", "wb", "northbound", "southbound", "eastbound", "westbound"}
_POINTS = {"north", "south", "east", "west"}
_NUMBERED = re.compile(r"^(md|va|us|i|sr)(\d+[a-z]?)$")


def _road_key(name: str) -> str:
    """A road's name as the feed and the map must share it: "Georgia Ave" and "Georgia
    Avenue" alike, "MD 97", "MD-97", "MD97", "MD 97 NB" and "Maryland Route 97" alike. A
    direction after a route number is the side of the road the work is on, not its name."""
    from . import dc_closures as dc

    words: list[str] = []
    for w in dc.street_key(name, quadrant=False).split():
        w = _ROAD_WORDS.get(w, w)
        numbered = _NUMBERED.match(w)
        words.extend(numbered.groups() if numbered else [w] if w else [])
    while words and (
        words[-1] in _BOUND or (words[-1] in _POINTS and len(words) > 1 and words[-2][:1].isdigit())
    ):
        words.pop()
    return " ".join(words)


def road_named(found: str, roads: Iterable[str]) -> bool:
    """Whether a name the router gives a stretch is one of the feed's road names."""
    key = _road_key(found)
    return bool(key) and any(key == _road_key(road) for road in roads)


def on_interstate(zone: Zone) -> bool:
    """Whether the feed names the zone's road as an Interstate, which no bicycle may use. Every
    name it gives must be one: a zone named "MD 32" and "I-95" may be work on MD 32."""
    return bool(zone.roads) and all(INTERSTATE.match(road) for road in zone.roads)


def samples(line: Sequence[Sequence[float]], most: int = BARRED_SAMPLES) -> list[tuple]:
    """Up to `most` points spread evenly along a line of [lon, lat] pairs, its ends included."""
    lat0 = line[0][1]
    xy = [_xy(p[0], p[1], lat0) for p in line]
    total = _length(xy)
    if total <= 0:
        return [tuple(line[0])]
    out, run, k = [], 0.0, 0
    most = max(most, 2)
    targets = [total * i / (most - 1) for i in range(most)]
    for a, b in zip(xy, xy[1:], strict=False):
        seg = math.dist(a, b)
        while k < len(targets) and targets[k] <= run + seg + 1e-9:
            t = 0.0 if seg == 0 else (targets[k] - run) / seg
            out.append(_lonlat(a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]), lat0))
            k += 1
        run += seg
    return out


def barred_samples(line: Sequence[Sequence[float]]) -> list[tuple]:
    """The points a line is checked for barred roads at: evenly spread, about `BARRED_STEP_M`
    apart, its ends included (`samples`)."""
    wanted = math.ceil(line_m(line) / BARRED_STEP_M) + 1
    return samples(line, min(max(wanted, BARRED_SAMPLES), BARRED_MOST))


def open_part(line: Sequence[Sequence[float]], barred: Sequence[bool]):
    """What is left of a line whose `barred_samples` are, in order, on a barred road or not:
    None when at least `BARRED_SHARE` of them are; otherwise the line from its first open
    sample to its last, so a zone that runs on onto a freeway is drawn and routed only where
    a bicycle may go. A barred stretch between open ones is kept: one line per zone."""
    n = len(barred)
    if n == 0 or sum(barred) >= BARRED_SHARE * n:
        return None if n else line
    first = next(i for i, b in enumerate(barred) if not b)
    last = n - 1 - next(i for i, b in enumerate(reversed(barred)) if not b)
    if first == 0 and last == n - 1:
        return line
    lat0 = line[0][1]
    xy = [_xy(p[0], p[1], lat0) for p in line]
    total = _length(xy)
    step = total / (n - 1) if n > 1 else 0.0
    kept = _between(xy, first * step, last * step)
    return tuple(tuple(round(v, 6) for v in _lonlat(x, y, lat0)) for x, y in kept)


def _between(
    points: list[tuple[float, float]], start: float, end: float
) -> list[tuple[float, float]]:
    """The part of a line from `start` to `end` metres along it, its cut ends included."""
    out: list[tuple[float, float]] = []
    run = 0.0
    for a, b in zip(points, points[1:], strict=False):
        seg = math.dist(a, b)
        if seg > 0 and not out and start <= run + seg:
            t = (start - run) / seg
            out.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
        if out:
            if end <= run + seg:
                t = (end - run) / seg if seg > 0 else 0.0
                out.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
                return out
            out.append(b)
        run += seg
    return out or points


def simplify_m(line: Sequence[Sequence[float]], tolerance_m: float) -> list[list[float]]:
    """A line of [lon, lat] pairs with every point within `tolerance_m` of it dropped
    (Douglas-Peucker); its ends kept."""
    if len(line) < 3:
        return [list(p) for p in line]
    lat0 = line[0][1]
    xy = [_xy(p[0], p[1], lat0) for p in line]
    keep = {0, len(xy) - 1}
    stack = [(0, len(xy) - 1)]
    while stack:
        i, j = stack.pop()
        best, index = -1.0, None
        for k in range(i + 1, j):
            d = _to_segment(xy[k], xy[i], xy[j])
            if d > best:
                best, index = d, k
        if index is not None and best > tolerance_m:
            keep.add(index)
            stack += [(i, index), (index, j)]
    return [list(line[k]) for k in sorted(keep)]


def road_fits(chord_m: float, routed_m: float, named_m: float, names_known: bool) -> bool:
    """Whether the router's way between a gap's ends (`routed_m` long, `named_m` of it on a
    road the feed names) is the road the feed means: not much longer than the straight
    line, and mostly on that road where the names can be compared."""
    if routed_m > SNAP_RATIO * chord_m + SNAP_SLACK_M:
        return False
    return not names_known or named_m >= SNAP_NAMED_SHARE * routed_m


def join_pieces(
    line: Sequence[Sequence[float]], pieces: Mapping[int, Sequence[Sequence[float]]]
) -> tuple[tuple[float, float], ...]:
    """The line with the gap after point i replaced by `pieces[i]`, the road between the two
    points from the first to the second. A piece starts and ends on the road, so it stands in
    for the feed's own points at its ends."""
    out: list[tuple[float, float]] = []

    def add(p) -> None:
        step = (float(p[0]), float(p[1]))
        if not out or out[-1] != step:
            out.append(step)

    for i, point in enumerate(line):
        if i in pieces:
            for p in pieces[i]:
                add(p)
        elif i - 1 not in pieces:
            add(point)
    return tuple(out)


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
    # v0.9.1, DDOT's permits (`possible`): flagged on the map only, never routed round,
    # never a heading, a spoken cue or the closure dialog (the owner, 2026-10-19: "We
    # should flag, but not necessarily stop anyone", "And turn the notices off").
    possible: list[Zone] = field(default_factory=list)
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
    # A plan on foot (Run, Walk, Walk + transit; `for_plan`'s `on_foot`).
    on_foot: bool = False
    # Each excluded closure's rings, by its id, in `excluded`'s order: one strip, or several
    # where the part near a rider's point is left in or a way crosses it (`zone_rings`).
    # `exclude` starts with them, in that order. A closure missing here has one ring.
    rings: dict[str, list[list[list[float]]]] = field(default_factory=dict)

    def rings_of(self, zone: Zone) -> list[list[list[float]]]:
        """The rings `exclude` holds for an excluded closure."""
        found = self.rings.get(zone.zone_id)
        if found is not None:
            return found
        ring = polygon(zone)
        return [] if ring is None else [ring]

    def closure_ring_count(self) -> int:
        """How many of `exclude`'s first rings are the excluded closures'."""
        return sum(len(self.rings.get(z.zone_id, [None])) for z in self.excluded)

    @property
    def any(self) -> bool:
        return bool(
            self.excluded
            or self.unexcluded
            or self.passable
            or self.bypassed
            or self.uncertain
            or self.lanes
            or self.possible
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
            self.possible,
        ):
            for zone in group:
                seen.setdefault(zone.zone_id, zone)
        return list(seen.values())

    def penalties_s(self, passages: Iterable[Passage]) -> float:
        return sum(p.zone.penalty_s for p in passages)


def detour_reach_m(points: Sequence[Sequence[float]], allowed_m: float) -> float:
    """How far from the straight lines through `points`, in order, a way through them of at
    most `allowed_m` in all can go: on the longest leg (`d`), with all the slack (`e`, what
    `allowed_m` leaves over the straight lines) spent there, the ellipse's half-width,
    sqrt(e * (2d + e)) / 2. A loop from one point reaches half its length."""
    lat0 = points[0][1]
    xy = [_xy(p[0], p[1], lat0) for p in points]
    legs = [math.dist(a, b) for a, b in zip(xy, xy[1:], strict=False)] or [0.0]
    slack = max(float(allowed_m) - sum(legs), 0.0)
    return math.sqrt(slack * (2.0 * max(legs) + slack)) / 2.0


def _box(
    points: Sequence[Sequence[float]], margin_m: float = BOX_MARGIN_M
) -> tuple[float, float, float, float]:
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    lat0 = sum(lats) / len(lats)
    dlat = margin_m / (math.pi / 180 * _EARTH_M)
    dlon = dlat / max(math.cos(math.radians(lat0)), 0.01)
    return min(lons) - dlon, min(lats) - dlat, max(lons) + dlon, max(lats) + dlat


def _in_box(zone: Zone, box) -> bool:
    return any(box[0] <= lon <= box[2] and box[1] <= lat <= box[3] for lon, lat in zone.line)


def fit_polygons(
    zones: Sequence[Zone], near, used_m: float = 0.0, used_vertices: int = 0, rings_of=None
):
    """The zones' polygons, nearest `near` first, as many as fit the router's limits beside
    what is already used. (polygons, fitted zones, left out). `near` is a (lon, lat) point,
    or the rider's points in order: a zone is then ranked by its distance from the line
    through them, so on a long ride the closures by the start and the end count as much as
    those in the middle (audit 2026-10-29: ranked from the points' average, a DC to
    Baltimore ride left out the closures at both ends first). `rings_of(zone)` gives a zone's
    rings where it has several (`zone_rings`): all of them fit, or the zone is left out. The
    budget is the router's own count with a margin (`PERIMETER_BUDGET_M`)."""
    stops = [near] if isinstance(near[0], (int, float)) else list(near)
    rings, fitted, left = [], [], []
    for zone in sorted(zones, key=lambda z: _stops_distance(z, stops)):
        if rings_of is None:
            ring = polygon(zone)
            own = [] if ring is None else [ring]
        else:
            own = list(rings_of(zone))
        if not own:
            left.append(zone)
            continue
        perimeter, vertices = budget_used(own)
        if used_m + perimeter > PERIMETER_BUDGET_M or used_vertices + vertices > MAX_VERTICES:
            left.append(zone)
            continue
        used_m += perimeter
        used_vertices += vertices
        rings.extend(own)
        fitted.append(zone)
    return rings, fitted, left


def _zone_xy(zone: Zone) -> list[tuple[float, float]]:
    """The zone's line on the plane at its first point's latitude."""
    lat0 = zone.line[0][1]
    return [_xy(lon, lat, lat0) for lon, lat in zone.line]


def _stops_distance(zone: Zone, stops: Sequence[Sequence[float]]) -> float:
    """Metres from the zone's nearest point to the line through `stops` (one point or more)."""
    lat0 = stops[0][1]
    line = [_xy(p[0], p[1], lat0) for p in stops]
    if len(line) == 1:
        line = line * 2
    return min(_distance_to_line(_xy(lon, lat, lat0), line) for lon, lat in zone.line)


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
# the go routing, but worth keeping for future ride planning", and of them keeping riders
# off good roads: "it could be closed some time in the next month or so ... I wouldn't
# cancel a solo ride because of it", "We should flag, but not necessarily stop anyone",
# "And turn the notices off". So they are never routed round: a plan flags them on its map
# (`PlanZones.possible`), Go and a ride leave them out (`now_only`), and the closure check
# never asks about them.
POSSIBLE_SOURCES = frozenset({"dc", "protrack", "dcwater", "wssc"})


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
    on_foot: bool = False,
    reach_m: float = 0.0,
    crossings=None,
) -> PlanZones:
    """What a plan through `points` (lon, lat) at ride time `at` does with the zones.

    A closure is left out as its strips (`zone_rings`): the part within `NEAR_POINT_M` of
    the start stays in, so the router can start there, and the rest is left out (hunt K3,
    2026-11-08); one wholly that near, or near a destination or via, is warned of instead.
    `crossings(closures)` gives, by zone id, the metres along each closure's line where a way
    crosses it (`crossing_cuts`), where the strip is cut (`core.workzones.crossings`; none
    without it).

    The zones looked at lie within `BOX_MARGIN_M` of the box round `points`, or within
    `reach_m` where the plan can go further from them than that (a loop sized to a target,
    a climb search, Reach's rings: audit 2026-11-05).

    `on_foot` (Run, Walk, Walk + transit): a closure is routed round only where its source
    says it closes the way on foot too (`Zone.on_foot` True). One whose source does not say
    is warned of on the route and not routed round, as a closure to traffic need not close
    the sidewalk; one whose source says people on foot are let through is left out.

    `reserve` is the router's polygon budget (perimeter, vertices) already taken by the
    roads the rider marked closed (v0.8.2): the closures fit in what is left.

    `now` is when the plan is made: a closure with no end given, on a ride later than
    that (`FUTURE_AFTER_S`), "may still apply" and is warned of, not routed round.
    `bypass` names the closures the rider chose to route through for this plan. The
    closures that may happen (`possible`: DDOT's permits) are only flagged
    (`PlanZones.possible`), and `now_only` (Go and a ride) leaves them out."""
    future = is_future(at, now)
    plan = PlanZones(status=dict(status), at=at, future=future, on_foot=on_foot)
    if not points:
        return plan
    bypassed = set(bypass)
    box = _box(points, max(BOX_MARGIN_M, float(reach_m)))
    closures = []
    for zone in zones:
        if not active(zone, at) or not _in_box(zone, box):
            continue
        if possible(zone):
            if not now_only:
                plan.possible.append(zone)
            continue
        if zone.kind == LANE:
            if not on_foot:
                plan.lanes.append(zone)
            continue
        if on_foot and zone.on_foot is False:
            continue
        if zone.kind in (CLOSED, UNKNOWN) and zone.zone_id in bypassed:
            plan.bypassed.append(zone)
            continue
        if zone.kind == CLOSED and future and not zone.firm_end:
            plan.uncertain.append(zone)
            continue
        if zone.kind == CLOSED and on_foot and zone.on_foot is not True:
            plan.passable.append(zone)
        elif zone.kind == CLOSED:
            closures.append(zone)
        else:
            plan.passable.append(zone)
    lines = [z for z in closures if not z.area]  # an area is left out whole, never cut
    cuts = crossings(lines) if crossings is not None and lines else {}
    pieces: dict[str, list[list[list[float]]]] = {}
    fitting = []
    stops = [list(p) for p in points[1:]]
    for zone in closures:
        # Only the start leaves the part by it in (the router may start on a left-out edge).
        # At a destination or via the rest of the strip would still meet the stop's edge, which
        # the router can never arrive on (Valhalla 3.9.1 `AvoidAsDestinationEdge`), so a closure
        # by one is warned of whole, as before (review of hunt K3, 2026-11-08).
        # An area is looked at with every point: by any of them, only its core is left out
        # (`zone_rings`), and only where no point is by that too.
        if zone.area:
            rings = zone_rings(zone, points)
            if rings:
                pieces[zone.zone_id] = rings
                fitting.append(zone)
            else:
                plan.unexcluded.append(zone)
            continue
        if stops and any(
            _distance_to_line(_xy(p[0], p[1], zone.line[0][1]), _zone_xy(zone)) <= NEAR_POINT_M
            for p in stops
        ):
            plan.unexcluded.append(zone)
            continue
        rings = zone_rings(zone, points[:1], cuts.get(zone.zone_id, ()))
        if rings:
            pieces[zone.zone_id] = rings
            fitting.append(zone)
        else:
            plan.unexcluded.append(zone)  # wholly by a point placed: warned of
    plan.exclude, plan.excluded, left = fit_polygons(
        fitting, points, *reserve, rings_of=lambda z: pieces[z.zone_id]
    )
    plan.rings = {z.zone_id: pieces[z.zone_id] for z in plan.excluded}
    plan.unexcluded.extend(left)
    return plan


# --- The words -----------------------------------------------------------------


def heads_up(zone: Zone) -> str:
    """The description's sentence for a zone on the route: short, as Ride says it on the
    move (the owner, 2026-10-17: "the statement is way too verbose. We can cite our sources
    without all that extra noise"). Where it is, the source and until when are the
    entry's `citation`, shown in small text and not read out."""
    name = zone.road or t("The road")
    on = t(" on {road}", road=zone.road) if zone.road else ""
    if zone.kind == CLOSED:
        return t("{road} marked closed ahead.", road=name)
    if zone.kind == UNKNOWN:
        return t("{road} has every lane closed ahead; bike access unclear.", road=name)
    if zone.kind == LANE:
        return t("Bike lane blocked ahead{on}.", on=on)
    reason = (zone.reason or "").rstrip(".")
    lead = t("Heads-up") if zone.source in DC_SOURCES else t("Work zone ahead")
    return f"{lead}{on}, {reason}." if reason else f"{lead}{on}."


def citation(zone: Zone) -> str:
    """The small print under a zone's sentence: its source, and until when."""
    source = SOURCES.get(zone.source, zone.source)
    if zone.end is None:
        return t("Source: {source}.", source=source)
    last = last_day(zone.source, zone.end)
    if last is not None:
        return t("Source: {source}, through {date}.", source=source, date=cited_date(last))
    return t("Source: {source}, until {date}.", source=source, date=cited_date(zone.end))


def split_words(zone: Zone | None) -> str:
    """Where the route leaves the standard way for a closure it goes round (v0.8.2): the
    owner's "this road/bike path has been marked for closure, detour posted"."""
    name = zone.road if zone is not None and zone.road else t("The road ahead")
    return t("{road} marked closed. Detour posted.", road=name)


# The sources whose zones are DC's closures and blocked lanes, not work zones (v0.7.0).
DC_SOURCES = frozenset({"dc", "mpd", "alertdc", "ddot_advisory"})
# The sources whose closed zones are said as a road closed, not a work zone: DC's, the
# closures a reviewer confirmed, the Purple Line's (v0.13.0) and Fairfax's park alerts (v0.22.0).
CLOSURE_SOURCES = DC_SOURCES | {"reviewer", "purple_line", "fcpa", "park_alert"}


# --- The card's words (v0.7.0, "Closures on the map") ------------------------------

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS_ES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sept", "oct", "nov", "dic")


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


def date_text(moment: datetime, now: datetime | None = None) -> str:
    """'Oct 20', in the region's time; 'Aug 31, 2027' when that is not `now`'s year, so a
    closure through next summer, or a notice posted years ago, does not read as this
    year's (P11). With no `now`, no year."""
    local = _local(moment)
    text = f"{_MONTHS[local.month - 1]} {local.day}"
    if now is not None and _local(now).year != local.year:
        return f"{text}, {local.year}"
    return text


def cited_date(moment: datetime) -> str:
    """A citation's date in the route's language: 'Oct 20', or '20 de oct' in Spanish.
    Only the citation is worded in Spanish; the cards' when-words stay English."""
    if not spanish():
        return date_text(moment)
    local = _local(moment)
    return f"{local.day} de {_MONTHS_ES[local.month - 1]}"


# The sources whose windows are whole days: a reviewer's, a DDOT project advisory's
# (`routemaker.ddot_advisories`), a Purple Line update's (`routemaker.purple_line`) and a
# Fairfax park alert's (`routemaker.fcpa`).
WHOLE_DAY_SOURCES = frozenset(
    {"reviewer", "ddot_advisory", "purple_line", "fcpa", "park_alert", "dcwater"}
)


def last_day(source: str, end: datetime) -> datetime | None:
    """A reviewer's closure, or a DDOT project advisory's, ends at the midnight after its last
    day (`core.reviewed_closures.window`, `routemaker.ddot_advisories`): that last day, to say
    "through Feb 28" rather than "until Mar 1". None for any other end. The day is taken off in
    the region's time, so a last day that starts or ends daylight saving is not 23 or 25 hours
    long."""
    if source in WHOLE_DAY_SOURCES and _local(end).time() == time(0):
        return _local(end) - timedelta(days=1)
    return None


def day_text(moment: datetime, now: datetime | None) -> str:
    """'today', 'tomorrow', or 'Sat, Oct 17', in the region's time."""
    local = _local(moment)
    if now is not None:
        today = _local(now).date()
        if local.date() == today:
            return "today"
        if (local.date() - today).days == 1:
            return "tomorrow"
    return f"{_DAYS[local.weekday()]}, {date_text(moment, now)}"


def when_text(zone: Zone, now: datetime | None, future: bool, possible: bool = False) -> str:
    """When the closure applies, as the card says it: "Closed today 4:30 am to 1:30 pm",
    "Permit: road closed until Oct 20", "May still apply: no end time given"."""
    verb = "Bike lane blocked" if zone.kind == LANE else "Closed"
    if zone.kind == PENALTY:
        # Rideable (v0.12.0, the map with no route): construction, not a closure.
        verb = "Construction"
    if zone.source == "dc":
        verb = "Permit: bike lane blocked" if zone.kind == LANE else "Permit: road closed"
    if possible:
        # v0.9.1: a permit flagged only says what it allows, never that the road is closed.
        verb = (
            "Permit allows blocking the bike lane" if zone.kind == LANE else "Permit allows closing"
        )
        if zone.source != "dc":
            # v0.17.0: planned work (`routemaker.planned_work`) may close it some day.
            verb = "Planned work may close it some day"
    start, end = zone.start, zone.end
    if zone.daily is not None and start is not None and end is not None:
        # Each day's hours, then the days (hunt K6): "Closed 9 pm to 5 am each day, Nov 14 to
        # Nov 22".
        from .ridetime import ZONE

        first = datetime(2000, 1, 1, zone.daily[0], zone.daily[1], tzinfo=ZONE)
        last = datetime(2000, 1, 1, zone.daily[2], zone.daily[3], tzinfo=ZONE)
        hours = f"{clock_text(first)} to {clock_text(last)} each day"
        # A nightly window's last night starts the day before its end.
        final = end - timedelta(days=1) if last <= first else end
        return f"{verb} {hours}, {date_text(start, now)} to {date_text(final, now)}"
    if end is None:
        lead = f"{verb} from {day_text(start, now)} {clock_text(start)}" if start else verb
        if zone.source == "reviewer":
            return f"{lead} until a reviewer ends it"
        if future:
            return f"{lead}; no end time given, so it may still apply on your ride day"
        return f"{lead}; no end time given"
    last = last_day(zone.source, end)
    if last is not None:
        # Whole days: a one-day closure is not "midnight to midnight".
        if start is not None and now is not None and start > now:
            if _local(start).date() == _local(last).date():
                return f"{verb} {day_text(start, now)}"
            return f"{verb} from {date_text(start, now)} through {date_text(last, now)}"
        return f"{verb} through {date_text(last, now)}"
    if start is not None and _local(start).date() == _local(end).date():
        return f"{verb} {day_text(start, now)} {clock_text(start)} to {clock_text(end)}"
    if start is not None and (end - start).total_seconds() < 36 * 3600:
        return (
            f"{verb} {day_text(start, now)} {clock_text(start)} to "
            f"{day_text(end, now)} {clock_text(end)}"
        )
    if start is not None and now is not None and start > now:
        return f"{verb} from {date_text(start, now)} until {date_text(end, now)}"
    return f"{verb} until {date_text(end, now)}"


# The sources the card dates by when they published it.
DATED_SOURCES = frozenset({"mpd", "alertdc", "ddot_advisory", "purple_line", "fcpa", "park_alert"})


def source_text(zone: Zone, now: datetime | None = None) -> str:
    """The source, named as the card names it: "MPD traffic advisory, Oct 15" (with the
    year where it is not `now`'s)."""
    name = SOURCES.get(zone.source, zone.source)
    if zone.source == "dc":
        name = "DDOT occupancy permit (TOPS)"
    if zone.published is not None and zone.source in DATED_SOURCES:
        return f"{name}, {date_text(zone.published, now)}"
    return name


def minutes_text(seconds: float) -> str:
    minutes = round(seconds / 60)
    if minutes < 1:
        return "under a minute"
    return f"about {minutes} min"


ON_ROUTE, ROUTED_ROUND, BYPASSED, MAY_APPLY, NO_EFFECT, POSSIBLE = (
    "on_route",
    "routed_round",
    "bypassed",
    "may_still_apply",
    "none",
    "possible",
)


def effect_text(zone: Zone, effect: str, delay_s: float | None, on_foot: bool = False) -> str:
    """What the closure does to this route, and the delay its detour adds. `on_foot`: the
    route is a run or a walk (`for_plan`)."""
    if effect == ROUTED_ROUND:
        if delay_s is None:
            return "Your route goes round it."
        return f"Detour adds {minutes_text(delay_s)}"
    if effect == BYPASSED:
        said = "You chose to route through it; a small marker stays on the line."
        if delay_s is not None:
            said += f" Going round would add {minutes_text(delay_s)}."
        return said
    if effect == POSSIBLE:
        what = "blocking the bike lane" if zone.kind == LANE else "closing the road"
        return (
            f"A permit allows {what} some time in this window; it may be open."
            " Your route was not changed."
        )
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
        if on_foot and zone.on_foot is not True:
            return (
                "On your route: closed to traffic; the source does not say whether people on"
                " foot can pass."
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
    "WHOLE_DAY_SOURCES",
    "DISCLAIMER",
    "FLAGGER_PENALTY_S",
    "FUTURE_AFTER_S",
    "KINDS",
    "LANE",
    "POSSIBLE_SOURCES",
    "LANE_PENALTY_S",
    "MAY_APPLY",
    "POSSIBLE",
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
    "crossing_cuts",
    "fits_budget",
    "line_meets_ring",
    "line_rings",
    "over_budget",
    "zone_rings",
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
