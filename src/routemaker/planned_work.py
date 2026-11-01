"""Planned work that may close a road some day in its window: Plan's Potential closures layer.

Stephen, 2026-11-01: work permits "typically" close a road "one day over the course of a
month", and flagging them as closures "mainly risks people just ignoring all the closures as
unreliable". So, like DDOT's permits (`dc_closures`), these are never routed round and never
named in a route's words, a cue or the closure check: they are drawn dashed, with their own
icon, only where a rider turns on Plan's "Potential closures" layer (off by default). "We have
that for DC. Add everywhere else too."

- **DDOT ProTrack+** (`protrack`, DC open data, CC BY 4.0): DDOT's capital projects by block,
  "Under Construction" and not past their estimated completion (the layer keeps some 2017
  projects "Under Construction", so the date decides). Sidewalk, alley, streetlight and green
  infrastructure work leaves the road open and is left out.
- **DC Water active work zones** (`dcwater`): water-main work by block, with the activity's
  start and finish. Each zone is an area; its middle is put on its block by the same placing
  as a DDOT permit (`core.closure_sources`).
- **WSSC Water water-main construction** (`wssc`, Montgomery and Prince George's): the pipe
  being replaced, with its estimated construction dates. Only the project's name, status,
  dates and line are asked for; the layer's contract managers' names, phones and emails never
  are.

Pure: no network, no database.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

from . import workzones as wz
from .ridetime import ZONE

PROTRACK, DCWATER, WSSC = "protrack", "dcwater", "wssc"
SOURCES = frozenset({PROTRACK, DCWATER, WSSC})

# ProTrack+ work that leaves the road a bicycle uses as it was.
PROTRACK_SKIP = re.compile(
    r"sidewalk|alley|streetlight|street light|green infrastructure|tree|landscap|signage", re.I
)


def _ms(value) -> datetime | None:
    """An ArcGIS date (milliseconds since 1970, UTC)."""
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    try:
        return datetime.fromtimestamp(value / 1000.0, UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _tidy(text) -> str:
    return " ".join(str(text or "").split())


def _name(text) -> str:
    """A street as DDOT's capitals give it, in title case: "3RD ST NW" -> "3rd St NW"."""
    words = [w.capitalize() for w in _tidy(text).lower().split()]
    return " ".join(w.upper() if w in ("Nw", "Ne", "Sw", "Se") else w for w in words)


def _lines(geometry) -> list[tuple[tuple[float, float], ...]]:
    """The lines of a GeoJSON LineString or MultiLineString, each of two points or more."""
    if not isinstance(geometry, Mapping):
        return []
    kind, coords = geometry.get("type"), geometry.get("coordinates")
    parts = [coords] if kind == "LineString" else coords if kind == "MultiLineString" else []
    out = []
    for part in parts or []:
        try:
            line = tuple((float(p[0]), float(p[1])) for p in part)
        except (TypeError, ValueError, IndexError):
            continue
        if len(line) >= 2 and all(math.isfinite(x) and math.isfinite(y) for x, y in line):
            out.append(line)
    return out


def _window_ok(end: datetime | None, now: datetime) -> bool:
    """Whether the work's window has not passed (one with no end is left out)."""
    return end is not None and end >= now


def _zone(zone_id, source, line, road, title, description, start, end) -> wz.Zone:
    return wz.Zone(
        zone_id=zone_id,
        source=source,
        kind=wz.CLOSED,
        penalty_s=0.0,
        line=line,
        road=road or None,
        description=description or None,
        start=start,
        end=end,
        reason="planned work may close it some day in this window",
        title=title,
        url=wz.SOURCE_LINKS[source],
    )


def parse_protrack(document: Mapping, now: datetime) -> list[wz.Zone]:
    """ProTrack+'s line projects under construction now, as possible closures."""
    zones = []
    for feature in document.get("features") or []:
        props = feature.get("properties") or {}
        if _tidy(props.get("ProjectStatus") or "Under Construction") != "Under Construction":
            continue
        work = _tidy(props.get("PrimaryWorkType"))
        if not work or PROTRACK_SKIP.search(work):
            continue
        start = _ms(props.get("ActualStartDate")) or _ms(props.get("EstimatedStartDate"))
        end = _ms(props.get("EstimatedCompletionDate"))
        if not _window_ok(end, now):
            continue
        road = _name(props.get("RouteName"))
        a, b = _name(props.get("FromStreet")), _name(props.get("ToStreet"))
        stretch = (
            f"{road}, {a} to {b}" if road and a and b else road or _tidy(props.get("ProjectName"))
        )
        name = _tidy(props.get("ProjectName"))
        key = props.get("ObjectID") or props.get("OBJECTID") or props.get("GlobalID")
        for n, line in enumerate(_lines(feature.get("geometry"))):
            zones.append(
                _zone(
                    f"protrack-{key}-{n}",
                    PROTRACK,
                    line,
                    road,
                    f"{stretch}: {work.lower()}",
                    f"{name} ({work})" if name else work,
                    start,
                    end,
                )
            )
    return zones


@dataclass(frozen=True)
class AreaWork:
    """A DC Water work zone: its area's middle, placed on its block later."""

    work_id: str
    point: tuple[float, float]
    title: str
    description: str
    start: datetime | None
    end: datetime | None


def _middle(geometry) -> tuple[float, float] | None:
    """The mean of a Polygon's (or MultiPolygon's) outer ring points."""
    if not isinstance(geometry, Mapping):
        return None
    kind, coords = geometry.get("type"), geometry.get("coordinates")
    rings = [coords[0]] if kind == "Polygon" and coords else []
    if kind == "MultiPolygon":
        rings = [poly[0] for poly in coords or [] if poly]
    points = []
    for ring in rings:
        for p in ring or []:
            try:
                points.append((float(p[0]), float(p[1])))
            except (TypeError, ValueError, IndexError):
                continue
    points = [p for p in points if math.isfinite(p[0]) and math.isfinite(p[1])]
    if not points:
        return None
    return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))


def _calendar_day(value, after: bool = False) -> datetime | None:
    """DC Water's dates are calendar days stored as midnight UTC (7 pm the evening before in
    DC): the day's start in the region's time, or with `after` the midnight after it, so
    "finish Nov 7" lasts through Nov 7 (the window is whole days: `workzones.WHOLE_DAY_SOURCES`)."""
    moment = _ms(value)
    if moment is None:
        return None
    day = moment.date() + timedelta(days=1 if after else 0)
    return datetime.combine(day, time(0), ZONE).astimezone(UTC)


def parse_dcwater(document: Mapping, now: datetime) -> list[AreaWork]:
    """DC Water's work zones in force or to come within their window."""
    out = []
    for feature in document.get("features") or []:
        props = feature.get("properties") or {}
        start = _calendar_day(props.get("ActivityStart"))
        end = _calendar_day(props.get("ActivityFinish"), after=True)
        if end is None or end < now:
            continue
        point = _middle(feature.get("geometry"))
        if point is None:
            continue
        place = _tidy(props.get("LocationDescription"))
        activity = _tidy(props.get("ActivityType"))
        out.append(
            AreaWork(
                work_id=str(props.get("OBJECTID")),
                point=point,
                title=f"{place}: DC Water work" if place else "DC Water work",
                # The activity often carries the day that matters ("WATER OUTAGE 11/5/2026").
                description="; ".join(
                    t for t in (activity, _tidy(props.get("ProjectLongDescription"))) if t
                ),
                start=start,
                end=end,
            )
        )
    return out


def area_zone(work: AreaWork, line: Iterable[Iterable[float]]) -> wz.Zone:
    """A DC Water work zone along its block's `line`."""
    return _zone(
        f"dcwater-{work.work_id}",
        DCWATER,
        tuple((float(p[0]), float(p[1])) for p in line),
        None,
        work.title,
        work.description,
        work.start,
        work.end,
    )


# WSSC's status for pipe being laid now; the layer also keeps "Construction Completed" and
# "Restoration Completed" projects.
WSSC_ACTIVE = "Construction Started"


def parse_wssc(document: Mapping, now: datetime) -> list[wz.Zone]:
    """WSSC Water's water mains under construction, as possible closures along the pipe."""
    zones = []
    for feature in document.get("features") or []:
        props = feature.get("properties") or {}
        if _tidy(props.get("PROJECT_STATUS")) != WSSC_ACTIVE:
            continue
        start, end = _ms(props.get("EST_CONSTR_START_DATE")), _ms(props.get("EST_CONSTR_END_DATE"))
        if not _window_ok(end, now):
            continue
        name = _tidy(props.get("PROJECT_NAME")) or "Water main replacement"
        key = props.get("OBJECTID") or props.get("FULL_PROJECT_ID")
        for n, line in enumerate(_lines(feature.get("geometry"))):
            zones.append(
                _zone(
                    f"wssc-{key}-{n}",
                    WSSC,
                    line,
                    None,
                    f"{name}: WSSC Water main work",
                    name,
                    start,
                    end,
                )
            )
    return zones


__all__ = [
    "DCWATER",
    "PROTRACK",
    "SOURCES",
    "WSSC",
    "AreaWork",
    "area_zone",
    "parse_dcwater",
    "parse_protrack",
    "parse_wssc",
]
