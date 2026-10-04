"""Named corridors: owner-judged stretches of a street, matched by geometry.

OWNER-DECISIONS 284-286, 294-296. North Capitol Street NW/NE is posted 25 mph,
and the classifier reads a posted 25 as LTS 3 whatever the road is. The owner
rates two stretches higher because they are built like a highway ("It may say
25, but it's treated like a highway"): the first underpass, M Street to about P
Street, is Avoid for its through lanes and LTS 4 for the surface side lanes and
the pickup; the second, at Rhode Island Avenue, is LTS 4 for its underpass
lanes and LTS 3 for the narrower side lanes. Decision 294: this is NOT a
generic underpass rule - the circle underpasses (Dupont, Scott, Thomas), K
Street's surface lanes and Virginia Avenue stay as the base classifier rates
them - so each corridor is named in a reviewed file under `fixtures/corridors/`,
with the owner's reason on every entry.

Matched by geometry and name, not by way id. OSM splits and merges ways between
extracts (the Harford Road override of decision 282 lost its way id that way),
and a list of ids would stop applying without a word. A corridor is a street
name (without its quadrant) and an axis, a polyline down the middle of the
road's cross-section. Each way of that name is placed on the axis: how far
along it runs (`along_m`, from the axis's first point) and how far to the side
(`offset`). A way is a *through* lane when its mean offset is within
`through_max_offset_m` of the axis, a *side* lane when it is further out and
within `side_max_offset_m`: by where it lies, not by its `lanes` tag (way
468472149 is tagged lanes=2 and is the western outer side lane). An entry
names a role and an `along_m` range, and takes the ways with at least half
their length in the range.

Exempt: a way with a protected lane, a separate bikeway or a path-class
facility (decision 294: "Virginia Ave goes under the road but is fine due to a
protected bike lane"), and any trail-class way. An entry sets the tier, up or
down, where it applies; an approved stress override row still outranks it, as
it outranks every classified tier (`pipeline.overrides.apply_stress` runs
after).
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from .classes import TRAIL_CLASS_HIGHWAY
from .facility import Facility, facility, has_separate_bikeway
from .geo import EARTH_RADIUS_M
from .streets import street_key

CORRIDORS_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "corridors"
ROLES = ("through", "side")
DEFAULT_THROUGH_MAX_OFFSET_M = 7.0
DEFAULT_SIDE_MAX_OFFSET_M = 20.0
DEFAULT_MAX_BEARING_DEG = 40.0
# A way takes an entry when at least this share of its length is in the range.
MIN_SHARE_IN_RANGE = 0.5
SAMPLE_M = 2.0


class CorridorRefused(ValueError):
    """A corridor file is malformed."""


@dataclass(frozen=True)
class Entry:
    id: str
    role: str
    along_m: tuple[float, float]
    tier: int
    reason: str
    evidence: str


@dataclass(frozen=True)
class Corridor:
    id: str
    streets: frozenset[str]
    axis: tuple[tuple[float, float], ...]
    entries: tuple[Entry, ...]
    reason: str
    through_max_offset_m: float = DEFAULT_THROUGH_MAX_OFFSET_M
    side_max_offset_m: float = DEFAULT_SIDE_MAX_OFFSET_M
    max_bearing_deg: float = DEFAULT_MAX_BEARING_DEG
    source: str = ""


def _text(value, where: str, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CorridorRefused(f"{where}: {what} is required")
    return value


def _number(value, where: str, what: str) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool) or not math.isfinite(value):
        raise CorridorRefused(f"{where}: {what} must be a number")
    return float(value)


def _parse_entry(raw: object, where: str) -> Entry:
    if not isinstance(raw, dict):
        raise CorridorRefused(f"{where} is not an object")
    eid = _text(raw.get("id"), where, "id")
    where = f"{where} ({eid})"
    if raw.get("role") not in ROLES:
        raise CorridorRefused(f"{where}: role must be one of {list(ROLES)}")
    along = raw.get("along_m")
    if not isinstance(along, list) or len(along) != 2:
        raise CorridorRefused(f"{where}: along_m is [from, to] in metres")
    lo, hi = _number(along[0], where, "along_m"), _number(along[1], where, "along_m")
    if not lo < hi:
        raise CorridorRefused(f"{where}: along_m must run from a smaller to a larger value")
    tier = raw.get("tier")
    if not isinstance(tier, int) or isinstance(tier, bool) or not 1 <= tier <= 5:
        raise CorridorRefused(f"{where}: tier is an integer from 1 to 5")
    return Entry(
        id=eid,
        role=raw["role"],
        along_m=(lo, hi),
        tier=tier,
        reason=_text(raw.get("reason"), where, "reason"),
        evidence=_text(raw.get("evidence"), where, "evidence"),
    )


def parse(document: object, name: str = "<corridors>") -> list[Corridor]:
    """The corridors of one file's parsed JSON, validated."""
    if not isinstance(document, dict) or document.get("version") != 1:
        raise CorridorRefused(f"{name} is not a version 1 corridor file")
    rows = document.get("corridors")
    if not isinstance(rows, list) or not rows:
        raise CorridorRefused(f"{name} has no corridors")
    out: list[Corridor] = []
    for index, row in enumerate(rows):
        where = f"{name} corridor {index}"
        if not isinstance(row, dict):
            raise CorridorRefused(f"{where} is not an object")
        cid = _text(row.get("id"), where, "id")
        where = f"{name} corridor {cid}"
        streets = row.get("streets")
        keys = (
            [street_key(s) for s in streets]
            if isinstance(streets, list) and streets and all(isinstance(s, str) for s in streets)
            else None
        )
        if not keys or None in keys:
            raise CorridorRefused(f"{where}: streets is a non-empty list of street names")
        axis = row.get("axis")
        if (
            not isinstance(axis, list)
            or len(axis) < 2
            or not all(isinstance(p, list) and len(p) == 2 for p in axis)
        ):
            raise CorridorRefused(f"{where}: axis is a list of at least two [lon, lat] points")
        points = tuple(
            (_number(p[0], where, "axis lon"), _number(p[1], where, "axis lat")) for p in axis
        )
        if len(set(points)) < 2:
            raise CorridorRefused(f"{where}: axis has zero length")
        entries_raw = row.get("entries")
        if not isinstance(entries_raw, list) or not entries_raw:
            raise CorridorRefused(f"{where}: entries is a non-empty list")
        entries = [_parse_entry(e, f"{where} entry {i}") for i, e in enumerate(entries_raw)]
        ids = [e.id for e in entries]
        if len(set(ids)) != len(ids):
            raise CorridorRefused(f"{where}: entry ids must be unique")
        for role in ROLES:
            ranges = sorted(e.along_m for e in entries if e.role == role)
            for (_, prev_hi), (next_lo, _) in zip(ranges, ranges[1:], strict=False):
                if next_lo < prev_hi:
                    raise CorridorRefused(f"{where}: two {role} entries overlap along the axis")
        through_max = _number(
            row.get("through_max_offset_m", DEFAULT_THROUGH_MAX_OFFSET_M), where, "through offset"
        )
        side_max = _number(
            row.get("side_max_offset_m", DEFAULT_SIDE_MAX_OFFSET_M), where, "side offset"
        )
        if not 0 < through_max < side_max:
            raise CorridorRefused(f"{where}: need 0 < through_max_offset_m < side_max_offset_m")
        out.append(
            Corridor(
                id=cid,
                streets=frozenset(keys),
                axis=points,
                entries=tuple(entries),
                reason=_text(row.get("reason"), where, "reason"),
                through_max_offset_m=through_max,
                side_max_offset_m=side_max,
                max_bearing_deg=_number(
                    row.get("max_bearing_deg", DEFAULT_MAX_BEARING_DEG), where, "max bearing"
                ),
                source=name,
            )
        )
    return out


def load(directory: Path | str | None = None) -> list[Corridor]:
    """Every corridor in every file of `directory` (CORRIDORS_DIR)."""
    corridors: list[Corridor] = []
    for path in sorted(Path(directory or CORRIDORS_DIR).glob("*.json")):
        corridors.extend(parse(json.loads(path.read_text()), path.name))
    ids = [c.id for c in corridors]
    if len(set(ids)) != len(ids):
        raise CorridorRefused("corridor ids must be unique across files")
    return corridors


# --- Geometry ---------------------------------------------------------------


@dataclass(frozen=True)
class Placement:
    """Where a way lies on a corridor's axis: (along, offset) in metres for a
    sample every `SAMPLE_M` of its length, and how far its direction is off the
    axis's."""

    samples: tuple[tuple[float, float], ...]
    bearing_off_deg: float

    @property
    def mean_offset(self) -> float:
        return sum(offset for _, offset in self.samples) / len(self.samples)


def place(corridor: Corridor, coordinates) -> Placement | None:
    """The way placed on the corridor's axis, or None for a way with no length."""
    if len(coordinates) < 2:
        return None
    lon0, lat0 = corridor.axis[0]
    kx = math.radians(1.0) * EARTH_RADIUS_M * math.cos(math.radians(lat0))
    ky = math.radians(1.0) * EARTH_RADIUS_M

    def project(lon: float, lat: float) -> tuple[float, float]:
        return ((lon - lon0) * kx, (lat - lat0) * ky)

    axis = [project(lon, lat) for lon, lat in corridor.axis]
    segs = []
    run = 0.0
    for a, b in zip(axis, axis[1:], strict=False):
        length = math.dist(a, b)
        if length > 0:
            segs.append((a, b, length, run))
        run += length
    pts = [project(lon, lat) for lon, lat in coordinates]
    chord = (pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1])
    if math.hypot(*chord) < 1e-9:
        return None
    samples: list[tuple[float, float]] = []
    for a, b in zip(pts, pts[1:], strict=False):
        n = max(1, int(math.dist(a, b) // SAMPLE_M))
        samples.extend(
            (a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(n)
        )
    samples.append(pts[-1])
    placed: list[tuple[float, float, int]] = []
    for x, y in samples:
        best = None
        for index, ((ax, ay), (bx, by), length, before) in enumerate(segs):
            t = max(0.0, min(1.0, ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / length**2))
            d = math.hypot(x - (ax + (bx - ax) * t), y - (ay + (by - ay) * t))
            if best is None or d < best[1]:
                best = (before + t * length, d, index)
        placed.append(best)
    # The axis direction where the way lies, to compare the way's own with.
    segment = segs[placed[len(placed) // 2][2]]
    axis_dir = (segment[1][0] - segment[0][0], segment[1][1] - segment[0][1])
    cosine = abs(chord[0] * axis_dir[0] + chord[1] * axis_dir[1]) / (
        math.hypot(*chord) * math.hypot(*axis_dir)
    )
    return Placement(
        samples=tuple((along, offset) for along, offset, _ in placed),
        bearing_off_deg=math.degrees(math.acos(min(1.0, cosine))),
    )


def role_of(corridor: Corridor, placement: Placement) -> str | None:
    """`through`, `side`, or None for a way too far out or across the road."""
    if placement.bearing_off_deg > corridor.max_bearing_deg:
        return None
    if placement.mean_offset <= corridor.through_max_offset_m:
        return "through"
    if placement.mean_offset <= corridor.side_max_offset_m:
        return "side"
    return None


def entry_for(corridor: Corridor, placement: Placement) -> Entry | None:
    """The entry that takes the way: its role, and at least half its length in
    the entry's range."""
    role = role_of(corridor, placement)
    if role is None:
        return None
    for entry in corridor.entries:
        if entry.role != role:
            continue
        lo, hi = entry.along_m
        inside = sum(1 for along, _ in placement.samples if lo <= along <= hi)
        if inside / len(placement.samples) >= MIN_SHARE_IN_RANGE:
            return entry
    return None


# --- Applying ---------------------------------------------------------------


@dataclass(frozen=True)
class Applied:
    way_id: int
    corridor: str
    entry: str
    role: str
    before: int
    after: int
    exempt: str = ""


@dataclass
class CorridorReport:
    applied: list[Applied] = field(default_factory=list)
    # Entries that matched no way: the extract moved, or the file is wrong.
    unmatched_entries: list[str] = field(default_factory=list)
    skipped_unclassified: list[int] = field(default_factory=list)

    @property
    def changed(self) -> list[Applied]:
        return [a for a in self.applied if not a.exempt and a.before != a.after]

    def summary(self) -> str:
        exempt = sum(1 for a in self.applied if a.exempt)
        text = (
            f"named corridors: {len(self.applied)} ways matched, {len(self.changed)} re-tiered, "
            f"{exempt} exempt (protected lane, separate bikeway or path)"
        )
        if self.unmatched_entries:
            text += f"; entries that matched no way: {', '.join(self.unmatched_entries)}"
        return text


def exemption(
    tags: Mapping[str, str], way_id: int, separate_roads: Iterable[int] = frozenset()
) -> str:
    """Why a way takes no corridor lift, or ''."""
    if tags.get("highway") in TRAIL_CLASS_HIGHWAY:
        return "trail-class way"
    if has_separate_bikeway(dict(tags)):
        return "separate bikeway"
    if way_id in separate_roads:
        return "bikeway mapped beside it"
    kind = facility(dict(tags))
    if kind in (Facility.PROTECTED, Facility.PATH):
        return f"{kind.value} facility"
    return ""


def apply(
    corridors: Iterable[Corridor],
    ways: Iterable,
    stress_by_way: dict,
    *,
    tags_of: Mapping[int, Mapping[str, str]] | None = None,
    separate_roads: Iterable[int] = frozenset(),
) -> CorridorReport:
    """Set the tier of every classified way an entry names. `ways` need
    `osm_id`, `tags` and `coordinates`; `tags_of` gives the tags the classifier
    read where an agency overlay changed them (a recorded bike lane exempts).
    Replaces entries of `stress_by_way` in place and returns what it did."""
    corridors = list(corridors)
    separate = frozenset(separate_roads)
    report = CorridorReport()
    seen: set[tuple[str, str]] = set()
    for way in ways:
        key = street_key(way.tags.get("name"))
        if key is None:
            continue
        for corridor in corridors:
            if key not in corridor.streets:
                continue
            placement = place(corridor, way.coordinates)
            entry = entry_for(corridor, placement) if placement else None
            if entry is None:
                continue
            seen.add((corridor.id, entry.id))
            current = stress_by_way.get(way.osm_id)
            if current is None:
                report.skipped_unclassified.append(way.osm_id)
                break
            why = exemption((tags_of or {}).get(way.osm_id, way.tags), way.osm_id, separate)
            before = int(current.tier)
            after = before if why else entry.tier
            report.applied.append(
                Applied(way.osm_id, corridor.id, entry.id, entry.role, before, after, why)
            )
            if after != before:
                stress_by_way[way.osm_id] = replace(
                    current,
                    tier=type(current.tier)(after),
                    rule=f"named corridor: {corridor.id}, {entry.id}",
                )
            break
    for corridor in corridors:
        for entry in corridor.entries:
            if (corridor.id, entry.id) not in seen:
                report.unmatched_entries.append(f"{corridor.id}/{entry.id}")
    return report
