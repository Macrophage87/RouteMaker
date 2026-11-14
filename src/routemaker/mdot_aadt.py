"""Maryland's traffic counts: MDOT SHA's AADT segments (FOLLOWUP-MDOT-AADT, OWNER-DECISIONS 429).

The owner, 2026-10-05: "yes" to adding MDOT SHA traffic counts to the classifier
where OSM and the agency layers have none. The first case is MD 185 (Connecticut
Ave) from Chevy Chase Circle to about 38.988 N, LTS 3 only for want of a count.
The download was approved for the v0.5.0 rebuild (plans/v0.5.0-plan.md, Track B,
"Approved by Stephen 2026-10-10").

The layer is "MDOT SHA Annual Average Daily Traffic (AADT)", ArcGIS item
`ITEM_ID`, layer 1 ("... (AADT) Segments", polylines). Read 2026-10-11 from the
service's own metadata (`LAYER_URL?f=pjson`): pages of 2,000, pagination
supported, and these fields among others:

- `AADT` ("AADT (Current)"): the latest year's count, both directions together.
  The layer's `NORTH_EAST_SPLIT` and `SOUTH_WEST_SPLIT` give each direction's
  share of it, so `AADT` is the bidirectional figure the classifier reads.
- `AADT_2015` ... `AADT_2023`: the earlier years. The layer's description says
  the current figure "is for the year 2024", one after the newest dated field,
  and it gains a field a year; so the year is read from the fields
  (`current_year`) rather than typed at install time.
- `LOC_ERROR`: "NO ERROR" on every row read (MD 185's seven state segments and
  two county roads numbered 185, 2026-10-11). Anything else says the count's
  line was not placed on the road and the row is not installed (`usable`).

Licence: Maryland iMAP's terms, recorded verbatim in docs/SOURCES.md (and PLAN.md,
Licensing): "The Data can be freely distributed as long as the metadata entry is
not modified or deleted. Any data derived from the Data must acknowledge the
State of Maryland in the metadata." So the counts are credited to the State of
Maryland wherever a credit is shown (`CREDIT`), and the segment table names each
segment they reached (`volume_source = 'mdot-sha'`), which is what keeps them out
of any published derivative until the waiver PLAN.md asks for is in hand.

Pure: nothing here reads a file or the network.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence

AGENCY = "mdot-sha"
ITEM_ID = "77010abe7558425997b4fcdab02e2b64"
LAYER_URL = (
    "https://services.arcgis.com/njFNhDsUCentVYJW/arcgis/rest/services/"
    "MDOT_SHA_Annual_Average_Daily_Traffic/FeatureServer/1"
)
AADT_PROPERTY = "AADT"
CREDIT = "State of Maryland (MDOT SHA)"

# A dated count field: `AADT_2023`. Not `AAWDT_2023` (weekday traffic) and not
# the `_ANNO` text copies the older MapServer layer carried.
_DATED_FIELD = re.compile(r"^AADT_(\d{4})$")

# What `LOC_ERROR` says on a row whose line is where the count is.
NO_ERROR = frozenset({"", "NO ERROR", "NONE", "0"})


def current_year(field_names: Iterable[str]) -> int | None:
    """The year `AADT` is for: one after the newest `AADT_<year>` field.

    None where the layer has no dated field to read it from, which leaves the
    count undated rather than guessed (`volume_year` is nullable for that).
    """
    years = [int(match.group(1)) for name in field_names if (match := _DATED_FIELD.match(name))]
    return max(years) + 1 if years else None


def usable(properties: Mapping[str, object]) -> bool:
    """Whether a row's count may be installed: it has one above zero, and the
    agency does not flag its line as misplaced."""
    value = properties.get(AADT_PROPERTY)
    try:
        if value in (None, "") or float(value) <= 0:  # type: ignore[arg-type]
            return False
    except (TypeError, ValueError):
        return False
    flag = properties.get("LOC_ERROR")
    return flag is None or str(flag).strip().upper() in NO_ERROR


# The route systems OSM tags with a `ref` MDOT SHA's `ID_PREFIX` can be read against:
# interstates ("IS" to OSM's "I 95"), US and Maryland routes. County ("CO"), municipal
# ("MU"), ramp ("RP") and the other prefixes number roads OSM does not.
_REF_PREFIXES = {"IS": "I", "US": "US", "MD": "MD"}


def road_name(properties: Mapping[str, object]) -> str | None:
    """The street a count's section is named for: `ROADNAME` ("THIRD AVE")."""
    value = properties.get("ROADNAME")
    text = str(value).strip() if value is not None else ""
    return text or None


def route_ref(properties: Mapping[str, object]) -> str | None:
    """The section's route number as OSM writes a `ref`, "MD 97", or None where OSM
    numbers no such route (a county or municipal road, a ramp)."""
    prefix = _REF_PREFIXES.get(str(properties.get("ID_PREFIX") or "").strip().upper())
    number = str(properties.get("ID_RTE_NO") or "").strip()
    if not prefix or not number:
        return None
    try:
        number = str(int(float(number)))
    except ValueError:
        return None
    return f"{prefix} {number}"


# -- a section's count stops at a busy junction ---------------------------------------
#
# MDOT SHA counts one station per section and draws the section from one route junction to
# another, which can be miles and can pass busy junctions on the way: Bucklodge Road took
# 5,641 a day from a station on the far side of the junction with Barnesville Road (the
# borrowed-counts check, 2026-11-13; the methodology audit, area 04, suggestion 1). The
# traffic past such a junction is not the traffic the station saw. So a section's line is
# cut, at install, to the stretch between the busy junctions either side of its station
# (`cut_at_junctions`); the roads beyond take no count from it and are rated as uncounted
# roads are. Read from the layer's own fields: `ID_MP` (the station's milepoint) between
# `BEGIN_SECTION` and `END_SECTION`.

# A junction is another section's end within this of the section's line,
JUNCTION_REACH_M = 20.0
# at least this far from either end of the section (its own end junctions are the section's
# ends already),
JUNCTION_END_MARGIN_M = 250.0
# carrying at least this share of the section's count, and at least JUNCTION_MIN_AADT: a
# road that adds or takes that much traffic changes what the station measures. The audit's
# test (`reports/borrowed-counts/audit.py`); our defaults, unmeasured.
JUNCTION_MIN_SHARE = 0.25
JUNCTION_MIN_AADT = 500
# The station is placed by milepoint only where the drawn line's length agrees with the
# section's milepoints to within this ratio; elsewhere the line is not cut.
LENGTH_AGREEMENT = (0.8, 1.25)
_METRES_PER_DEGREE = 111_320.0
_METRES_PER_MILE = 1609.344


def _number(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _route_key(properties: Mapping[str, object]) -> tuple[object, ...]:
    return (
        properties.get("ID_PREFIX"),
        properties.get("ID_RTE_NO"),
        properties.get("COUNTY_DESC"),
    )


def cut_at_junctions(
    sections: Sequence[tuple[Sequence[Sequence[float]], Mapping[str, object]]],
) -> list[list[tuple[float, float]]]:
    """Each section's line (lon, lat points) cut to the stretch between the busy junctions
    either side of its station; a line with no such junction, or whose station cannot be
    placed, comes back whole. The same order as `sections`."""
    import math
    from itertools import pairwise

    lat0 = math.radians(39.0)
    scale_x = _METRES_PER_DEGREE * math.cos(lat0)

    def xy(point: Sequence[float]) -> tuple[float, float]:
        return (point[0] * scale_x, point[1] * _METRES_PER_DEGREE)

    cell = 300.0
    projected: list[list[tuple[float, float]]] = []
    along: list[list[float]] = []
    grid: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for number, (line, _properties) in enumerate(sections):
        points = [xy(p) for p in line]
        cumulative = [0.0]
        for a, b in pairwise(points):
            cumulative.append(cumulative[-1] + math.dist(a, b))
        projected.append(points)
        along.append(cumulative)
        for j, (a, b) in enumerate(pairwise(points)):
            for cx in range(int(min(a[0], b[0]) // cell) - 1, int(max(a[0], b[0]) // cell) + 2):
                for cy in range(int(min(a[1], b[1]) // cell) - 1, int(max(a[1], b[1]) // cell) + 2):
                    grid.setdefault((cx, cy), []).append((number, j))

    def near(point: tuple[float, float]) -> dict[int, tuple[float, float]]:
        found: dict[int, tuple[float, float]] = {}
        for number, j in grid.get((int(point[0] // cell), int(point[1] // cell)), ()):
            (ax, ay), (bx, by) = projected[number][j], projected[number][j + 1]
            dx, dy = bx - ax, by - ay
            length2 = dx * dx + dy * dy
            t = (
                0.0
                if not length2
                else max(0.0, min(1.0, ((point[0] - ax) * dx + (point[1] - ay) * dy) / length2))
            )
            distance = math.hypot(point[0] - ax - t * dx, point[1] - ay - t * dy)
            if distance <= JUNCTION_REACH_M:
                position = along[number][j] + t * (along[number][j + 1] - along[number][j])
                if number not in found or distance < found[number][0]:
                    found[number] = (distance, position)
        return found

    # The busy junctions along each section, by position.
    junctions: dict[int, list[float]] = {}
    for other, (_line, other_properties) in enumerate(sections):
        other_count = _number(other_properties.get(AADT_PROPERTY)) or 0.0
        if not projected[other]:
            continue
        for end in (projected[other][0], projected[other][-1]):
            for number, (_d, position) in near(end).items():
                properties = sections[number][1]
                if number == other or _route_key(properties) == _route_key(other_properties):
                    continue
                total = along[number][-1]
                if not JUNCTION_END_MARGIN_M <= position <= total - JUNCTION_END_MARGIN_M:
                    continue
                count = _number(properties.get(AADT_PROPERTY)) or 0.0
                if other_count >= max(JUNCTION_MIN_AADT, JUNCTION_MIN_SHARE * count):
                    junctions.setdefault(number, []).append(position)

    cut: list[list[tuple[float, float]]] = []
    for number, (line, properties) in enumerate(sections):
        whole = [(float(p[0]), float(p[1])) for p in line]
        station = _station_position(properties, along[number][-1] if along[number] else 0.0)
        if station is None or number not in junctions:
            cut.append(whole)
            continue
        before = max((p for p in junctions[number] if p < station), default=0.0)
        after = min((p for p in junctions[number] if p > station), default=along[number][-1])
        cut.append(_slice(whole, along[number], before, after))
    return cut


def _station_position(properties: Mapping[str, object], length_m: float) -> float | None:
    begin = _number(properties.get("BEGIN_SECTION")) or 0.0
    end = _number(properties.get("END_SECTION"))
    station = _number(properties.get("ID_MP"))
    if end is None or end <= begin or station is None or length_m <= 0:
        return None
    ratio = length_m / _METRES_PER_MILE / (end - begin)
    if not LENGTH_AGREEMENT[0] < ratio < LENGTH_AGREEMENT[1]:
        return None
    return max(0.0, min(1.0, (station - begin) / (end - begin))) * length_m


def _slice(
    line: list[tuple[float, float]], cumulative: list[float], start: float, stop: float
) -> list[tuple[float, float]]:
    """The part of `line` from `start` to `stop` metres along it."""

    def at(position: float) -> tuple[float, float]:
        for j in range(len(cumulative) - 1):
            if cumulative[j] <= position <= cumulative[j + 1]:
                span = cumulative[j + 1] - cumulative[j]
                t = 0.0 if not span else (position - cumulative[j]) / span
                (ax, ay), (bx, by) = line[j], line[j + 1]
                return (ax + t * (bx - ax), ay + t * (by - ay))
        return line[-1]

    inside = [p for p, c in zip(line, cumulative, strict=True) if start < c < stop]
    return [at(start), *inside, at(stop)]
