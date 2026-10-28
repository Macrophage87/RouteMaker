"""DC's closures, read for the planner: DDOT's TOPS permits, MPD traffic advisories,
AlertDC's traffic items and the National Park Service's alerts (v0.7.0 plan, "DC
closures source").

The WZDx registry has no DC feed (`routemaker.workzones`), so DC's closures come from
four sources of four kinds. Each becomes either a `workzones.Zone` (the same closure
model the Maryland and Virginia feeds fill) or a `Notice`, a line of text with a link
shown under "Check before you go" and never routed round:

- **DDOT occupancy permits (TOPS)**, source "dc", CC BY 4.0 (confirmed by the owner,
  2026-10-15). One representative point a permit (DDOT's own note: no extent; start
  and end times unreliable). A permit marked `IsRoadClosed` closes the block its point
  is snapped to (`block_of`: the way, between the two junctions either side of the
  point). `BikeLaneLength` > 0 without a road closure is a "Bike lane blocked" warning
  (`workzones.LANE`), not a closure. Lane-only travel closures are ignored. Active
  permits only (`ACTIVE_STATUSES`, and not past `ExpirationDate`).
- **MPD "TRAFFIC ADVISORY" releases** (mpdc.dc.gov) and **AlertDC traffic items**
  (trainingtrack.hsema.dc.gov/NRss), sources "mpd" and "alertdc": text. Each "X from A
  to B" (or "between A and B") under a time window becomes a `Segment`, which
  `core.closure_sources` matches to the ways of X between the two cross streets. A line
  that will not parse, a segment with no window, or one whose streets cannot be found
  is kept as text with the link (`Notice`), never guessed. Only traffic and road items
  are read (`is_traffic`, `traffic_advisory_links`): every other alert type, crime
  first, is dropped before its text is looked at, and is never stored, logged or shown.
- **NPS alerts** (developer.nps.gov/api/v1/alerts), source "nps": text with a category
  and no geometry, so each becomes a park-level notice (`PARKS`), never a closure.

Pure: no network, no database. `core.closure_sources` fetches and resolves.

None of the four hosts answers through the proxy this was written behind: the parsers
were built on saved sample pages shaped as the plan and DDOT's wiki describe them
(tests/data/closures), not on live downloads. docs/OPERATIONS.md, "DC closures", has the
first check to run on a machine that reaches them.
"""

from __future__ import annotations

import html
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urlencode
from xml.etree import ElementTree

from . import workzones as wz
from .ridetime import ZONE

# --- Notices ("Check before you go") ----------------------------------------------


@dataclass(frozen=True)
class Area:
    """Where a notice applies: a park (by NPS park code) or the District."""

    name: str
    # Where its marker goes on the map; None for the District (no marker).
    point: tuple[float, float] | None
    # (west, south, east, north) boxes that together cover it, roughly: a route with a
    # point in any of them passes through it.
    boxes: tuple[tuple[float, float, float, float], ...]
    url: str


DC_AREA = "dc"
# The District, its bounding box.
DC_BOX = (-77.1198, 38.7916, -76.9094, 38.9955)

# The parks along the region's routes (the plan: Rock Creek, the National Mall, the GW
# Parkway with the Mount Vernon Trail, the C&O Canal, Anacostia Park). The boxes are a
# rough cover drawn by hand from the parks' published maps: a route that passes near,
# not only through, a park may be shown its notice, which is only text to check.
PARKS: dict[str, Area] = {
    "rocr": Area(
        "Rock Creek Park",
        (-77.0525, 38.9406),
        ((-77.065, 38.905, -77.025, 38.992),),
        "https://www.nps.gov/rocr/planyourvisit/conditions.htm",
    ),
    "nama": Area(
        "National Mall and Memorial Parks",
        (-77.0353, 38.8895),
        ((-77.056, 38.878, -77.008, 38.894),),
        "https://www.nps.gov/nama/planyourvisit/conditions.htm",
    ),
    "gwmp": Area(
        "George Washington Memorial Parkway",
        (-77.0405, 38.8650),
        (
            (-77.100, 38.705, -77.035, 38.800),
            (-77.060, 38.800, -77.030, 38.885),
            (-77.205, 38.880, -77.060, 38.975),
        ),
        "https://www.nps.gov/gwmp/planyourvisit/conditions.htm",
    ),
    "choh": Area(
        "C&O Canal National Historical Park",
        (-77.1012, 38.9187),
        ((-77.255, 38.900, -77.055, 39.005), (-77.560, 38.990, -77.250, 39.160)),
        "https://www.nps.gov/choh/planyourvisit/conditions.htm",
    ),
    "anac": Area(
        "Anacostia Park",
        (-76.9745, 38.8780),
        ((-77.000, 38.860, -76.940, 38.920),),
        "https://www.nps.gov/anac/planyourvisit/conditions.htm",
    ),
}
AREAS: dict[str, Area] = {
    **PARKS,
    DC_AREA: Area("Washington, DC", None, (DC_BOX,), "https://dc.gov/"),
}


@dataclass(frozen=True)
class Notice:
    """A closure or alert with no place the router can use: shown as text with its link."""

    notice_id: str
    source: str  # "nps", "mpd" or "alertdc"
    title: str
    text: str
    url: str | None
    area: str  # a key of AREAS
    start: datetime | None = None
    end: datetime | None = None
    published: datetime | None = None
    category: str | None = None

    def to_json(self) -> dict:
        return {
            "id": self.notice_id,
            "source": self.source,
            "title": self.title,
            "text": self.text,
            "url": self.url,
            "area": self.area,
            "start": _iso(self.start),
            "end": _iso(self.end),
            "published": _iso(self.published),
            "category": self.category,
        }

    @classmethod
    def from_json(cls, row: Mapping) -> Notice:
        return cls(
            notice_id=row["id"],
            source=row["source"],
            title=row["title"],
            text=row.get("text") or "",
            url=row.get("url"),
            area=row["area"],
            start=wz._when(row.get("start")),
            end=wz._when(row.get("end")),
            published=wz._when(row.get("published")),
            category=row.get("category"),
        )


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def notice_active(notice: Notice, at: datetime) -> bool:
    if notice.start is not None and at < notice.start - timedelta(hours=12):
        return False
    return not (notice.end is not None and at >= notice.end)


def _in_boxes(lon: float, lat: float, boxes) -> bool:
    return any(w <= lon <= e and s <= lat <= n for w, s, e, n in boxes)


def area_of(key: str) -> Area | None:
    """A notice's area: a park, the District, or a deer-management closure's
    (`routemaker.deer_closures`)."""
    from . import deer_closures

    return AREAS.get(key) or deer_closures.areas().get(key)


def notices_along(
    notices: Iterable[Notice], coordinates: Sequence[Sequence[float]], at: datetime
) -> list[Notice]:
    """The notices in force at `at` whose area the line passes through, parks first. A
    deer-management closure's (v0.12.3) counts only inside its window and where the line runs
    along the roads or trails it closes."""
    from . import deer_closures

    found, deer = [], []
    for notice in notices:
        area = area_of(notice.area)
        if area is None:
            continue
        if notice.source in deer_closures.SOURCES:
            if deer_closures.in_force(notice, at):
                deer.append(notice)
            continue
        if not notice_active(notice, at):
            continue
        if any(_in_boxes(c[0], c[1], area.boxes) for c in coordinates):
            found.append(notice)
    found += [
        n for n in deer_closures.first_each(deer) if deer_closures.runs_along(n.area, coordinates)
    ]
    return sorted(found, key=lambda n: (n.area == DC_AREA, n.source, n.notice_id))


def notice_when_text(notice: Notice, now: datetime | None, future: bool) -> str:
    if notice.start is not None and notice.end is not None:
        if _local(notice.start).date() == _local(notice.end).date():
            return (
                f"{wz.day_text(notice.start, now)} {wz.clock_text(notice.start)} to "
                f"{wz.clock_text(notice.end)}"
            )
        # A whole day ("All day Sat, Nov 14"), or a night ("today 6:45 pm to tomorrow 4 am").
        start, end = _local(notice.start), _local(notice.end)
        if start.time() == end.time() == time(0) and end.date() - start.date() == timedelta(days=1):
            return f"All day {wz.day_text(notice.start, now)}"
        if (notice.end - notice.start) < timedelta(hours=36):
            return (
                f"{wz.day_text(notice.start, now)} {wz.clock_text(notice.start)} to "
                f"{wz.day_text(notice.end, now)} {wz.clock_text(notice.end)}"
            )
        return f"{wz.date_text(notice.start, now)} to {wz.date_text(notice.end, now)}"
    # With the year where it is not this one (P11): a notice posted in 2023 does not read as new.
    posted = f"Posted {wz.date_text(notice.published, now)}" if notice.published else "No dates given"
    return f"{posted}; it may still apply on your ride day" if future else posted


# --- DDOT's TOPS occupancy permits --------------------------------------------------

# The permit statuses that mean "in force" (DDOT's wiki lists `Status`; the values are
# read case-blind). Anything else (applied, cancelled, expired, closed) is left out.
ACTIVE_STATUSES = frozenset({"active", "issued", "approved"})


@dataclass(frozen=True)
class Permit:
    permit_id: str
    point: tuple[float, float]
    road_closed: bool
    bike_lane_ft: float
    start: datetime | None
    end: datetime | None
    street: str | None
    description: str | None
    # This permit's own record on DC's map server (the owner, 2026-10-17: "can the link take
    # you directly to the permit?"); TOPS itself has no public link to one permit.
    url: str | None = None


# DDOT's "Occupancy Permits (via DDOT TOPS)" layer, as read by core.closure_sources.
TOPS_LAYER = "https://maps2.dcgis.dc.gov/dcgis/rest/services/DDOT/TOPS/MapServer/1"
_ID_FIELDS = ("PERMITNUMBER", "PERMIT_NUMBER", "TRACKINGNUMBER")


def permit_url(field: str | None, value) -> str:
    """The permit's record on the TOPS layer, as a page: by its number where the answer
    named the field, else by its object id."""
    if field is None:
        query = {"objectIds": str(value)}
    else:
        quoted = str(value).replace("'", "''")
        query = {"where": f"{field}='{quoted}'"}
    return f"{TOPS_LAYER}/query?{urlencode({**query, 'outFields': '*', 'f': 'html'})}"


def _field_name(attributes: Mapping, *names: str) -> str | None:
    """The answer's own spelling of the first of `names` it has a value for, case-blind."""
    for name in names:
        for key, value in attributes.items():
            if str(key).lower() == name.lower() and value not in (None, ""):
                return str(key)
    return None


def _field(attributes: Mapping, *names: str):
    """The first of `names` present in `attributes`, case-blind."""
    lowered = {str(k).lower(): v for k, v in attributes.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value not in (None, ""):
            return value
    return None


def _tops_date(value) -> datetime | None:
    """An ArcGIS date (epoch milliseconds), an ISO date, or MM/DD/YYYY; local DC time
    where no zone is given."""
    if value in (None, ""):
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value) / 1000.0, UTC)
    text = str(value).strip()
    for pattern in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=ZONE).astimezone(UTC)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=ZONE).astimezone(UTC)


def _yes(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value != 0
    return str(value or "").strip().lower() in ("y", "yes", "true", "t", "1")


def _number(value) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _point_of(feature: Mapping, attributes: Mapping) -> tuple[float, float] | None:
    geometry = feature.get("geometry") or {}
    point = None
    if isinstance(geometry, Mapping):
        if geometry.get("type") == "Point":
            coordinates = geometry.get("coordinates") or []
            if len(coordinates) >= 2:
                point = (coordinates[0], coordinates[1])
        elif "x" in geometry and "y" in geometry:
            point = (geometry["x"], geometry["y"])
    if point is None:
        lon = _field(attributes, "LONGITUDE", "LON", "X")
        lat = _field(attributes, "LATITUDE", "LAT", "Y")
        if lon is not None and lat is not None:
            point = (lon, lat)
    try:
        lon, lat = float(point[0]), float(point[1])  # type: ignore[index]
    except (TypeError, ValueError, IndexError):
        return None
    if not (-78.5 <= lon <= -76 and 38 <= lat <= 40):
        return None  # not in the region (a projected coordinate, or none)
    return (lon, lat)


def parse_permits(document: Mapping, now: datetime) -> list[Permit]:
    """The active permits of a TOPS query answer (GeoJSON or ArcGIS JSON) that matter to
    a bicycle: a road closed, or a bike lane blocked. Lane-only travel closures, and
    permits not active or past their expiration, are left out."""
    features = document.get("features")
    if not isinstance(features, list):
        raise ValueError("not a TOPS answer: no features")
    permits = []
    for feature in features:
        if not isinstance(feature, Mapping):
            continue
        attributes = feature.get("properties") or feature.get("attributes") or {}
        if not isinstance(attributes, Mapping):
            continue
        status = str(_field(attributes, "STATUS", "PERMITSTATUS") or "").strip().lower()
        if status not in ACTIVE_STATUSES:
            continue
        road_closed = _yes(_field(attributes, "ISROADCLOSED", "IS_ROAD_CLOSED"))
        bike_lane = _number(_field(attributes, "BIKELANELENGTH", "BIKE_LANE_LENGTH"))
        if not road_closed and bike_lane <= 0:
            continue
        end = _tops_date(_field(attributes, "EXPIRATIONDATE", "EXPIRATION_DATE"))
        if end is not None and end <= now:
            continue
        point = _point_of(feature, attributes)
        if point is None:
            continue
        permit_id = _field(
            attributes, "PERMITNUMBER", "PERMIT_NUMBER", "TRACKINGNUMBER", "OBJECTID"
        ) or feature.get("id")
        if permit_id is None:
            continue
        id_field = _field_name(attributes, *_ID_FIELDS)
        start = _tops_date(_field(attributes, "EFFECTIVEDATE", "ISSUEDDATE", "ISSUED_DATE"))
        street = _field(
            attributes, "STREETNAME", "STREET_NAME", "FULLSTREETNAME", "STNAME", "STREET"
        )
        description = _field(attributes, "WORKDESCRIPTION", "DESCRIPTION", "PERMITTYPE")
        permits.append(
            Permit(
                permit_id=str(permit_id),
                point=point,
                road_closed=road_closed,
                bike_lane_ft=bike_lane,
                start=start,
                end=end,
                street=_tidy(str(street)) if street else None,
                description=_tidy(str(description))[:200] if description else None,
                url=permit_url(id_field, permit_id),
            )
        )
    return permits


def permit_zone(permit: Permit, line: Sequence[Sequence[float]]) -> wz.Zone:
    """The permit as a zone along `line` (its block): a closure where the road is closed,
    else a bike lane blocked."""
    closed = permit.road_closed
    what = "road closed" if closed else "bike lane blocked"
    title = f"{permit.street}: {what}" if permit.street else what.capitalize()
    return wz.Zone(
        zone_id=f"dc-{permit.permit_id}",
        source="dc",
        kind=wz.CLOSED if closed else wz.LANE,
        penalty_s=0.0,
        line=tuple((float(p[0]), float(p[1])) for p in line),
        road=permit.street,
        description=permit.description,
        start=permit.start,
        end=permit.end,
        reason="road closed by a DDOT permit" if closed else "bike lane blocked by a DDOT permit",
        title=f"{title} (permit {permit.permit_id})",
        url=permit.url or wz.SOURCE_LINKS["dc"],
    )


# --- A permit's block ---------------------------------------------------------------

# Two lines meet where they come this close (OSM ways share a node).
MEET_M = 2.0
# A block shorter than this is widened to it, centred on the point, so a permit at a
# junction still marks a stretch the router can leave out.
MIN_BLOCK_M = 30.0


def _xy(lon: float, lat: float, lat0: float) -> tuple[float, float]:
    return wz._xy(lon, lat, lat0)


def _project(point, line_xy) -> tuple[float, float]:
    """(distance from the line, metres along it) of `point`'s nearest place on it."""
    best, at, run = math.inf, 0.0, 0.0
    for a, b in zip(line_xy, line_xy[1:], strict=False):
        seg = math.dist(a, b)
        if seg > 0:
            t = max(
                0.0,
                min(
                    1.0,
                    ((point[0] - a[0]) * (b[0] - a[0]) + (point[1] - a[1]) * (b[1] - a[1]))
                    / seg**2,
                ),
            )
            near = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
            d = math.dist(point, near)
            if d < best:
                best, at = d, run + t * seg
        run += seg
    return best, at


def _crossings(line_xy, other_xy) -> list[float]:
    """Metres along `line_xy` where `other_xy` meets it: a vertex of either within
    MEET_M of the other, or two segments crossing."""
    found = []
    for p in other_xy:
        d, at = _project(p, line_xy)
        if d <= MEET_M:
            found.append(at)
    run = 0.0
    for a, b in zip(line_xy, line_xy[1:], strict=False):
        seg = math.dist(a, b)
        for c, d in zip(other_xy, other_xy[1:], strict=False):
            hit = _segment_cross(a, b, c, d)
            if hit is not None:
                found.append(run + hit * seg)
        run += seg
    return found


def _segment_cross(a, b, c, d) -> float | None:
    """Where segment a-b crosses c-d, as a fraction of a-b; None if they do not."""
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    denominator = r[0] * s[1] - r[1] * s[0]
    if abs(denominator) < 1e-9:
        return None
    q = (c[0] - a[0], c[1] - a[1])
    t = (q[0] * s[1] - q[1] * s[0]) / denominator
    u = (q[0] * r[1] - q[1] * r[0]) / denominator
    if 0 <= t <= 1 and 0 <= u <= 1:
        return t
    return None


def _point_at(line_xy, distance: float) -> tuple[float, float]:
    run = 0.0
    for a, b in zip(line_xy, line_xy[1:], strict=False):
        seg = math.dist(a, b)
        if seg > 0 and run + seg >= distance:
            t = max(0.0, (distance - run) / seg)
            return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
        run += seg
    return line_xy[-1]


def _cut(line_xy, start: float, end: float) -> list[tuple[float, float]]:
    """The part of the line from `start` to `end` metres along it."""
    out = [_point_at(line_xy, start)]
    run = 0.0
    for a, b in zip(line_xy, line_xy[1:], strict=False):
        run += math.dist(a, b)
        if start < run < end:
            out.append(b)
    out.append(_point_at(line_xy, end))
    return [p for i, p in enumerate(out) if i == 0 or p != out[i - 1]]


def block_of(
    point: Sequence[float],
    way: Sequence[Sequence[float]],
    others: Iterable[Sequence[Sequence[float]]],
) -> list[tuple[float, float]] | None:
    """The block of `way` (lon, lat pairs) that `point` lies on: from the nearest
    junction before it to the nearest after it, a junction being where another road
    (`others`) meets the way, or the way's end. None for a way under 1 m."""
    if len(way) < 2:
        return None
    lat0 = way[0][1]
    line = [_xy(p[0], p[1], lat0) for p in way]
    total = wz._length(line)
    if total < 1.0:
        return None
    _d, at = _project(_xy(point[0], point[1], lat0), line)
    stops = {0.0, total}
    for other in others:
        if len(other) < 2:
            continue
        stops.update(_crossings(line, [_xy(p[0], p[1], lat0) for p in other]))
    before = max((s for s in stops if s <= at - 0.5), default=0.0)
    after = min((s for s in stops if s >= at + 0.5), default=total)
    if after - before < MIN_BLOCK_M:
        half = min(MIN_BLOCK_M, total) / 2
        before = max(0.0, at - half)
        after = min(total, before + 2 * half)
        before = max(0.0, after - 2 * half)
    cut = _cut(line, before, after)
    if len(cut) < 2:
        return None
    return [tuple(round(c, 7) for c in wz._lonlat(x, y, lat0)) for x, y in cut]  # type: ignore[misc]


# --- Text: "X from A to B" under a time window ------------------------------------------


@dataclass(frozen=True)
class Segment:
    """One street closed between two cross streets, for a window."""

    street: str
    from_street: str
    to_street: str
    start: datetime | None
    end: datetime | None
    text: str  # the line as published


@dataclass
class Advisory:
    """One MPD release or AlertDC item, read: its segments, and what would not parse."""

    advisory_id: str
    source: str  # "mpd" or "alertdc"
    title: str
    url: str | None
    published: datetime | None
    segments: list[Segment]
    unparsed: list[str]
    start: datetime | None = None
    end: datetime | None = None

    def notice(self, lines: Sequence[str] | None = None) -> Notice:
        """The advisory as text under "Check before you go": `lines` (its unparsed ones,
        or the segments that could not be placed), else its title alone."""
        said = [line for line in (self.unparsed if lines is None else lines) if line][:6]
        return Notice(
            notice_id=f"{self.advisory_id}-text",
            source=self.source,
            title=self.title,
            text=" ".join(_sentence(line) for line in said),
            url=self.url,
            area=DC_AREA,
            # Shown from its publication (a line may be for another day of the event)
            # to its last window's end, or for `NOTICE_TTL` where it gives none.
            start=self.published,
            end=max(e for e in (self.end, _notice_end(self)) if e is not None)
            if (self.end or self.published)
            else None,
            published=self.published,
        )


# A text notice with no window of its own is shown for this long after it was published.
NOTICE_TTL = {"mpd": timedelta(days=7), "alertdc": timedelta(hours=12)}


def _notice_end(advisory: Advisory) -> datetime | None:
    if advisory.published is None:
        return None
    return advisory.published + NOTICE_TTL.get(advisory.source, timedelta(days=1))


def _sentence(line: str) -> str:
    line = line.strip()
    return line if line.endswith((".", "!", "?", ":")) else f"{line}."


def _tidy(text: str) -> str:
    return " ".join(html.unescape(text).replace("\xa0", " ").split())


_MONTH_NAMES = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_DATE = re.compile(
    r"(?:(?:mon|tues|wednes|thurs|fri|satur|sun)day,?\s+)?"
    r"(?P<month>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?\s+"
    r"(?P<day>\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s+(?P<year>\d{4}))?",
    re.I,
)
_TIME = re.compile(
    r"\b(?:(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<half>a\.?\s?m\b\.?|p\.?\s?m\b\.?)"
    r"|(?P<word>noon|midnight))",
    re.I,
)
_OPEN_END = re.compile(r"until further notice|until (?:the )?(?:scene|area|road) is clear", re.I)


def _dates(text: str, year: int) -> list[date]:
    out = []
    for match in _DATE.finditer(text):
        month = _MONTH_NAMES[match.group("month")[:3].lower()]
        try:
            out.append(date(int(match.group("year") or year), month, int(match.group("day"))))
        except ValueError:
            continue
    return out


def _times(text: str) -> list[tuple[int, int]]:
    out = []
    for match in _TIME.finditer(text):
        word = (match.group("word") or "").lower()
        if word:
            out.append((12, 0) if word == "noon" else (0, 0))
            continue
        hour, minute = int(match.group("hour")), int(match.group("minute") or 0)
        if not (1 <= hour <= 12 and 0 <= minute < 60):
            continue
        pm = match.group("half").lower().startswith("p")
        out.append(((hour % 12) + (12 if pm else 0), minute))
    return out


def _at(day: date, hm: tuple[int, int]) -> datetime:
    return datetime(day.year, day.month, day.day, hm[0], hm[1], tzinfo=ZONE).astimezone(UTC)


def _year_for(published: datetime | None) -> int:
    return (_local(published) if published else datetime.now(ZONE)).year


def _local(moment: datetime) -> datetime:
    return moment.astimezone(ZONE)


@dataclass
class _Context:
    day: date | None = None
    start: datetime | None = None
    end: datetime | None = None
    windowed: bool = False
    parking: bool = False


def _window(text: str, context: _Context, year: int) -> bool:
    """Read the dates and times in `text` into `context`; whether it held a time."""
    days = _dates(text, year)
    if days:
        context.day = days[0]
    times = _times(text)
    if not times:
        if days:
            context.windowed = False
        return False
    if context.day is None:
        context.windowed = False
        return True
    start = _at(days[0] if days else context.day, times[0])
    end = None
    if len(times) >= 2 and not _OPEN_END.search(text):
        end_day = days[1] if len(days) >= 2 else (days[0] if days else context.day)
        end = _at(end_day, times[1])
        if end <= start:
            end += timedelta(days=1)
    context.start, context.end, context.windowed = start, end, True
    return True


_QUADRANT = re.compile(r"\b(N\.?W|N\.?E|S\.?W|S\.?E)\.?$", re.I)
_DIRECTION = re.compile(
    r"^(?:(?:north|south|east|west)bound|inbound|outbound|both directions of|all lanes of"
    r"|the (?:north|south|east|west)bound lanes of)\s+",
    re.I,
)
_SEGMENT = re.compile(
    r"^(?P<street>[A-Za-z0-9][^:;]*?)\s*,?\s+(?:(?:is|are|will be)\s+(?:closed|blocked)"
    r"(?:\s+(?:in both directions|to (?:all |vehicular )?traffic))?\s+)?"
    r"(?:from|between)\s+(?P<a>[^;]+?)\s+(?:to|and|through)\s+(?P<b>[^;]+?)$",
    re.I,
)


def _clean_part(text: str) -> str:
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" ,.;-–•*")
    text = re.sub(r",\s*(N\.?W|N\.?E|S\.?W|S\.?E)\.?\b", r" \1", text, flags=re.I)
    return text.strip(" ,.")


def _quadrant(text: str) -> str | None:
    match = _QUADRANT.search(text.strip())
    return match.group(1).replace(".", "").upper() if match else None


def _tail_cut(text: str) -> str:
    """The segment's last street without what follows it in a sentence."""
    return re.split(
        r"\s+(?:due to|until|for|from \d|beginning|starting"
        r"|on (?:mon|tues|wednes|thurs|fri|satur|sun)day)\b"
        r"|[.;]\s|,\s+(?=\d{1,2}(?::\d{2})?\s*[ap]\.?m)",
        text,
        maxsplit=1,
        flags=re.I,
    )[0]


def parse_segment(line: str) -> tuple[str, str, str] | None:
    """(street, from, to) of "X from A to B" or "X between A and B", quadrants shared from
    the end of the line; None for anything else (a time window included)."""
    text = _tidy(line).strip(" •*-–")
    text = re.sub(r"^\d+\.\s+", "", text)
    # "X, NW" is one name; a lead-in ("The following street is closed: ", "Due to a
    # crash, ") is not part of it.
    text = re.sub(r",\s*(N\.?W|N\.?E|S\.?W|S\.?E)\b\.?", r" \1", text, flags=re.I)
    text = re.split(r":\s+", text)[-1]
    match = _SEGMENT.match(text)
    if match is None:
        return None
    street, a, b = match.group("street"), match.group("a"), _tail_cut(match.group("b"))
    street = _DIRECTION.sub("", _clean_part(street.split(",")[-1]))
    a, b = _clean_part(a), _clean_part(b)
    if not street or not a or not b:
        return None
    if _times(a) or _times(b) or _dates(a, 2000) or _dates(b, 2000):
        return None
    if max(len(street), len(a), len(b)) > 60 or not re.search(r"[A-Za-z]", street):
        return None
    shared = _quadrant(b) or _quadrant(street)
    if shared:
        street = street if _quadrant(street) else f"{street} {shared}"
        a = a if _quadrant(a) else f"{a} {shared}"
    return street, a, b if _quadrant(b) or not shared else f"{b} {shared}"


def read_lines(
    lines: Sequence[str], published: datetime | None, title: str = ""
) -> tuple[list[Segment], list[str], datetime | None, datetime | None]:
    """The segments of an advisory's lines, each under the window it was published
    under, and the lines with a segment that had no window or would not parse. Emergency
    No Parking lists are skipped: parking is not a closure to a bicycle."""
    context = _Context()
    year = _year_for(published)
    _window(title, context, year)
    segments: list[Segment] = []
    unparsed: list[str] = []
    starts, ends = [], []
    for raw in lines:
        line = _tidy(raw)
        if not line:
            continue
        lowered = line.lower()
        found = parse_segment(line)
        if found is None:
            if "parking" in lowered:
                context.parking = True
                _window(line, context, year)
                continue
            if re.search(r"clos|detour|blocked|restrict", lowered):
                context.parking = False
            had_time = _window(line, context, year)
            if not had_time and re.search(r"\b(?:from|between)\b.+\b(?:to|and)\b", lowered):
                if re.search(
                    r"\b(?:street|st|avenue|ave|road|rd|drive|dr|place|pl|bridge|parkway|pkwy|boulevard|blvd|way|circle|court)\b",
                    lowered,
                ):
                    if not context.parking:
                        unparsed.append(line)
            continue
        if context.parking:
            continue
        # A window at the end of the line itself ("..., 4:30 am to 1:30 pm") is its own.
        own = _Context(day=context.day)
        if _times(line) and _window(line, own, year) and own.windowed:
            start, end, windowed = own.start, own.end, True
        else:
            start, end, windowed = context.start, context.end, context.windowed
        if not windowed or start is None:
            unparsed.append(line)
            continue
        street, a, b = found
        segments.append(Segment(street, a, b, start, end, line))
        starts.append(start)
        ends.append(end)
    start = min(starts) if starts else None
    end = max(ends) if ends and all(e is not None for e in ends) else None
    return segments, unparsed, start, end


# --- MPD's releases -------------------------------------------------------------------

MPD_BASE = "https://mpdc.dc.gov"
TRAFFIC_ADVISORY = re.compile(r"traffic\s+advisory", re.I)


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, _tidy(" ".join(self._text))))
            self._href = None


def traffic_advisory_links(listing: str, base: str = MPD_BASE) -> list[tuple[str, str]]:
    """(title, url) of each "TRAFFIC ADVISORY" release in MPD's newsroom listing (HTML)
    or feed (RSS), newest first as listed. Every other release - crime ones first - is
    passed over on its title, and its page is never fetched."""
    found: list[tuple[str, str]] = []
    if listing.lstrip().startswith("<?xml") or "<rss" in listing[:500]:
        for item in _rss_items(listing):
            if TRAFFIC_ADVISORY.search(item["title"]) and item["link"]:
                found.append((item["title"], item["link"]))
    else:
        parser = _Links()
        parser.feed(listing)
        for href, text in parser.links:
            if href and TRAFFIC_ADVISORY.search(text):
                url = href if href.startswith("http") else f"{base.rstrip('/')}/{href.lstrip('/')}"
                found.append((text, url))
    seen: set[str] = set()
    out = []
    for title, url in found:
        if url.startswith(base) and url not in seen:
            seen.add(url)
            out.append((title, url))
    return out


_BLOCK_TAGS = frozenset(
    {
        "p",
        "li",
        "br",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "tr",
        "ul",
        "ol",
        "table",
        "section",
        "article",
    }
)


class _Text(HTMLParser):
    """A page's text as lines, block by block; its <title>, first <h1> and dates."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._line: list[str] = []
        self._skip = 0
        self.h1: str | None = None
        self._in_h1 = False
        self._h1: list[str] = []
        self.published: str | None = None
        self._in_date = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag in ("script", "style", "nav", "header", "footer", "noscript"):
            self._skip += 1
        if tag in _BLOCK_TAGS:
            self._flush()
        if tag == "h1" and self.h1 is None:
            self._in_h1 = True
        if tag == "meta" and attributes.get("property") in (
            "article:published_time",
            "og:updated_time",
        ):
            self.published = self.published or attributes.get("content")
        if "date-display-single" in (attributes.get("class") or "") or tag == "time":
            self._in_date = True
            if attributes.get("datetime"):
                self.published = self.published or attributes["datetime"]

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "header", "footer", "noscript") and self._skip:
            self._skip -= 1
        if tag in _BLOCK_TAGS:
            self._flush()
        if tag == "h1" and self._in_h1:
            self._in_h1 = False
            self.h1 = _tidy(" ".join(self._h1))
        if tag in ("span", "time"):
            self._in_date = False

    def handle_data(self, data):
        if self._skip:
            return
        self._line.append(data)
        if self._in_h1:
            self._h1.append(data)
        if self._in_date and self.published is None and _dates(data, 2000):
            self.published = _tidy(data)

    def _flush(self):
        text = _tidy(" ".join(self._line))
        if text:
            self.lines.append(text)
        self._line = []

    def close(self):
        super().close()
        self._flush()


def _published(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=ZONE)).astimezone(UTC)
    except ValueError:
        pass
    days = _dates(text, datetime.now(ZONE).year)
    if days:
        return datetime(days[0].year, days[0].month, days[0].day, 12, tzinfo=ZONE).astimezone(UTC)
    return None


def parse_mpd_release(page: str, url: str, title: str | None = None) -> Advisory | None:
    """One MPD release page, read: None if it is not a traffic advisory (it is then not
    read further, nor kept)."""
    parser = _Text()
    parser.feed(page)
    parser.close()
    heading = title or parser.h1 or ""
    if not TRAFFIC_ADVISORY.search(heading):
        return None
    published = _published(parser.published)
    lines = parser.lines
    # The release's body: what follows its heading, up to the page's own footer lines.
    if parser.h1 and parser.h1 in lines:
        lines = lines[lines.index(parser.h1) + 1 :]
    stop = next(
        (
            i
            for i, line in enumerate(lines)
            if re.match(r"^(?:###|related content|share this)", line, re.I)
        ),
        len(lines),
    )
    lines = lines[:stop]
    segments, unparsed, start, end = read_lines(lines, published, heading)
    node = re.sub(r"[^A-Za-z0-9]+", "-", url.rsplit("/", 1)[-1]).strip("-") or "release"
    return Advisory(
        advisory_id=f"mpd-{node}",
        source="mpd",
        title=_title(heading),
        url=url,
        published=published,
        segments=segments,
        unparsed=unparsed,
        start=start,
        end=end,
    )


def _title(heading: str) -> str:
    heading = _tidy(heading)
    if heading.isupper():
        heading = heading.title()
    return heading[:160]


# --- AlertDC --------------------------------------------------------------------------

# An item is read only if it is about traffic or a road. These are checked first, on its
# title and categories; an item with any word of `NOT_TRAFFIC` is dropped whatever else
# it says, before its text is read further, and is never stored, logged or shown.
TRAFFIC_WORDS = re.compile(
    r"\b(?:traffic|road(?:way)?s?\s+(?:closure|closed|closing)|road closure"
    r"|street\s+(?:closure|closed)"
    r"|lanes?\s+(?:closure|closed|blocked)|closed to traffic|bridge (?:opening|lift|closure)|detour"
    r"|ddot|closure)\b",
    re.I,
)
NOT_TRAFFIC = re.compile(
    r"\b(?:shoot\w*|stab\w*|robber\w*|homicide|murder|suspect\w*|missing|crime|burglar\w*"
    r"|assault\w*|lookout|armed|weapon\w*|gun\w*|police activity|shelter in place|barricade\w*"
    r"|arrest\w*|carjack\w*|sexual|abduct\w*|amber alert|endangered|wanted)\b",
    re.I,
)
TRAFFIC_CATEGORIES = re.compile(r"traffic|transport|road", re.I)


def is_traffic(title: str, categories: Sequence[str]) -> bool:
    """Whether an AlertDC item is a traffic or road item: a traffic category, or a
    traffic word in its title; never one with a crime word."""
    if NOT_TRAFFIC.search(title) or any(NOT_TRAFFIC.search(c) for c in categories):
        return False
    if categories and any(TRAFFIC_CATEGORIES.search(c) for c in categories):
        return True
    if categories:
        return False
    return bool(TRAFFIC_WORDS.search(title))


def _rss_items(text: str) -> list[dict]:
    try:
        root = ElementTree.fromstring(text.encode("utf-8") if isinstance(text, str) else text)
    except ElementTree.ParseError as error:
        raise ValueError("not an RSS feed") from error
    items = []
    for item in root.iter("item"):
        items.append(
            {
                "title": _tidy(item.findtext("title") or ""),
                "link": (item.findtext("link") or "").strip(),
                "guid": (item.findtext("guid") or "").strip(),
                "description": item.findtext("description") or "",
                "pubDate": (item.findtext("pubDate") or "").strip(),
                "categories": [_tidy(c.text or "") for c in item.findall("category")],
            }
        )
    return items


def _strip_tags(text: str) -> list[str]:
    parser = _Text()
    parser.feed(text)
    parser.close()
    return parser.lines


# AlertDC items older than this, with no end of their own, are past (a crash's closure).
ALERTDC_MAX_AGE = timedelta(hours=12)


def parse_alertdc(feed: str, now: datetime) -> list[Advisory]:
    """AlertDC's traffic and road items as advisories; every other item dropped unread."""
    advisories = []
    for item in _rss_items(feed):
        if not is_traffic(item["title"], item["categories"]):
            continue
        description = item["description"]
        if NOT_TRAFFIC.search(description):
            continue
        try:
            published = parsedate_to_datetime(item["pubDate"]).astimezone(UTC)
        except (TypeError, ValueError):
            published = None
        lines = _strip_tags(description) or [item["title"]]
        sentences = [s for line in lines for s in re.split(r"(?<=[.!?])\s+", line) if s]
        segments, unparsed, _start, _end = [], [], None, None
        for sentence in sentences:
            found = parse_segment(sentence)
            if found is None:
                continue
            start = published
            end = _alert_end(sentence, published)
            segments.append(Segment(*found, start, end, sentence))
        if not segments:
            unparsed = sentences[:4] or [item["title"]]
        ends = [s.end for s in segments]
        end = max(ends) if ends and all(e is not None for e in ends) else None
        if published is not None and end is None and now - published > ALERTDC_MAX_AGE:
            continue
        if end is not None and end <= now:
            continue
        key = item["guid"] or item["link"] or item["title"]
        advisories.append(
            Advisory(
                advisory_id="alertdc-" + re.sub(r"[^A-Za-z0-9]+", "-", key)[-60:].strip("-"),
                source="alertdc",
                title=_title(item["title"]),
                url=item["link"] or None,
                published=published,
                segments=segments,
                unparsed=unparsed,
                start=published,
                end=end,
            )
        )
    return advisories


def _alert_end(sentence: str, published: datetime | None) -> datetime | None:
    """The end an AlertDC sentence gives ("until 6 pm"), on the day it was published."""
    if published is None or _OPEN_END.search(sentence):
        return None
    match = re.search(r"\buntil\b(.*)", sentence, re.I)
    if not match:
        return None
    times = _times(match.group(1))
    if not times:
        return None
    local = _local(published)
    days = _dates(match.group(1), local.year)
    end = _at(days[0] if days else local.date(), times[0])
    if end <= published:
        end += timedelta(days=1)
    return end


# --- Placing a segment on the map -------------------------------------------------------

_WORDS = {
    "st": "street",
    "str": "street",
    "ave": "avenue",
    "av": "avenue",
    "rd": "road",
    "dr": "drive",
    "blvd": "boulevard",
    "pl": "place",
    "ct": "court",
    "ter": "terrace",
    "terr": "terrace",
    "pkwy": "parkway",
    "pky": "parkway",
    "hwy": "highway",
    "sq": "square",
    "cir": "circle",
    "ln": "lane",
    "br": "bridge",
    "brg": "bridge",
    "expy": "expressway",
    "fwy": "freeway",
    "mem": "memorial",
    "nw": "northwest",
    "ne": "northeast",
    "sw": "southwest",
    "se": "southeast",
    "n": "north",
    "s": "south",
    "e": "east",
    "w": "west",
}
QUADRANT_WORDS = frozenset({"northwest", "northeast", "southwest", "southeast"})


def street_key(name: str, quadrant: bool = True) -> str:
    """A street's name as two sources must share it: "Constitution Ave., NW" and
    "Constitution Avenue Northwest" are both "constitution avenue northwest". A lone
    letter street ("E St") keeps its letter; a leading "St" is a saint. Without
    `quadrant`, the District's quadrant is left off."""
    tokens = re.findall(r"[a-z0-9]+", name.lower().replace("&", " and "))
    out = []
    for i, token in enumerate(tokens):
        if token == "st" and i == 0 and len(tokens) > 1:
            out.append("saint")
        elif (
            token in ("n", "s", "e", "w")
            and i + 1 < len(tokens)
            and tokens[i + 1]
            in (
                "st",
                "street",
            )
        ):
            out.append(token)  # E Street
        else:
            out.append(_WORDS.get(token, token))
    if not quadrant:
        out = [t for t in out if t not in QUADRANT_WORDS]
    return " ".join(out)


def names_match(found: str, wanted: str) -> bool:
    """Whether a way's name is the wanted street: the same, or the same but for a
    quadrant one of them leaves out."""
    a, b = street_key(found), street_key(wanted)
    if a == b:
        return True
    a_quadrant = set(a.split()) & QUADRANT_WORDS
    b_quadrant = set(b.split()) & QUADRANT_WORDS
    if a_quadrant and b_quadrant and a_quadrant != b_quadrant:
        return False
    return street_key(found, quadrant=False) == street_key(wanted, quadrant=False)


def meeting_points(
    lines: Iterable[Sequence[Sequence[float]]], others: Iterable[Sequence[Sequence[float]]]
) -> list[tuple[float, float]]:
    """Where any of `lines` meets any of `others` (a shared vertex, or a crossing), as
    (lon, lat), one a junction (points within 15 m are one)."""
    others = [o for o in others if len(o) >= 2]
    found: list[tuple[float, float]] = []
    for line in lines:
        if len(line) < 2:
            continue
        lat0 = line[0][1]
        xy = [_xy(p[0], p[1], lat0) for p in line]
        for other in others:
            for at in _crossings(xy, [_xy(p[0], p[1], lat0) for p in other]):
                x, y = _point_at(xy, at)
                point = wz._lonlat(x, y, lat0)
                if all(_metres(point, f) > 15.0 for f in found):
                    found.append(point)
    return found


def _metres(a: Sequence[float], b: Sequence[float]) -> float:
    lat0 = (a[1] + b[1]) / 2
    return math.dist(_xy(a[0], a[1], lat0), _xy(b[0], b[1], lat0))


# A closed stretch between two cross streets is at least this long and at most this.
MIN_SEGMENT_M = 30.0
MAX_SEGMENT_M = 5_000.0


def pick_ends(
    starts: Sequence[Sequence[float]], ends: Sequence[Sequence[float]]
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """The nearest pair of a junction with the first cross street and one with the second,
    within `MIN_SEGMENT_M` to `MAX_SEGMENT_M` of each other; None where there is none."""
    best = None
    for a in starts:
        for b in ends:
            d = _metres(a, b)
            if MIN_SEGMENT_M <= d <= MAX_SEGMENT_M and (best is None or d < best[0]):
                best = (d, (float(a[0]), float(a[1])), (float(b[0]), float(b[1])))
    return None if best is None else (best[1], best[2])


# --- The segments as zones ------------------------------------------------------------


def segment_zone(advisory: Advisory, index: int, segment: Segment, line) -> wz.Zone:
    """A placed segment as a closure."""
    name = wz.SOURCES[advisory.source]
    return wz.Zone(
        zone_id=f"{advisory.advisory_id}-{index}",
        source=advisory.source,
        kind=wz.CLOSED,
        penalty_s=0.0,
        line=tuple((float(p[0]), float(p[1])) for p in line),
        road=segment.street,
        description=advisory.title,
        start=segment.start,
        end=segment.end,
        reason=f"closed ({name})",
        title=f"{segment.street} closed, {segment.from_street} to {segment.to_street}",
        url=advisory.url,
        published=advisory.published,
    )


# --- NPS alerts -----------------------------------------------------------------------

NPS_PARKS = ("rocr", "nama", "gwmp", "choh", "anac")
# The alert categories that can close the way (NPS: Danger, Caution, Information, Park
# Closure); "Information" is left out.
NPS_CATEGORIES = frozenset({"park closure", "danger", "caution"})


def parse_nps(document: Mapping) -> list[Notice]:
    """The NPS API's alerts for the parks in `NPS_PARKS`, as park-level notices."""
    data = document.get("data")
    if not isinstance(data, list):
        raise ValueError("not an NPS alerts answer: no data")
    notices = []
    for alert in data:
        if not isinstance(alert, Mapping):
            continue
        category = _tidy(str(alert.get("category") or ""))
        park = str(alert.get("parkCode") or "").strip().lower()
        if category.lower() not in NPS_CATEGORIES or park not in PARKS:
            continue
        title = _tidy(str(alert.get("title") or ""))
        if not title or alert.get("id") in (None, ""):
            continue
        text = " ".join(_strip_tags(str(alert.get("description") or "")))[:400]
        url = str(alert.get("url") or "").strip() or PARKS[park].url
        notices.append(
            Notice(
                notice_id=f"nps-{alert['id']}",
                source="nps",
                title=title[:160],
                text=text,
                url=url if url.startswith("https://") else PARKS[park].url,
                area=park,
                published=_published(str(alert.get("lastIndexedDate") or "") or None),
                category=category,
            )
        )
    return notices


__all__ = [
    "AREAS",
    "area_of",
    "Advisory",
    "Notice",
    "PARKS",
    "Permit",
    "Segment",
    "block_of",
    "is_traffic",
    "notices_along",
    "parse_alertdc",
    "parse_mpd_release",
    "parse_nps",
    "parse_permits",
    "parse_segment",
    "permit_zone",
    "read_lines",
    "segment_zone",
    "traffic_advisory_links",
]
