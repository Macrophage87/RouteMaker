"""Re-matching an override whose way left the extract (OWNER-DECISIONS 282).

An override row names an OSM way by id, and OSM ids are not stable: a mapper
splits a way, merges two, or redraws a junction, and the way a row was written
for is gone from the next extract. `apply_stress` and `apply_access` then listed
the id as "matched no way" in a log line, and the owner's correction was not in
force. The Harford Road row (way 424993005, Baltimore) was the first to go this
way: the fresh extract split it into ways 1562097553, 1562097555 and
1562097556.

Each override therefore carries a fingerprint of the way it was written for -
its street name, its highway class, its length and its line - stored beside the
row in the reviewed file under `fixtures/overrides/` (the database row holds no
geometry, so the rebuild reads the fingerprint from its image by kind and way
id; a row typed into the admin has none and cannot be re-matched). When a row's
way is missing, `resolve` looks for the ways that now lie along the stored line.

A re-match is applied only when it is unambiguous, and a way is never guessed
at. Every one of these must hold:

- the candidates have the same street name (without its quadrant) and highway
  class as the fingerprint, and each lies along the stored line: at least 90% of
  its length within `tolerance_m` of it, so the way does not run on past it;
- together they cover at least 90% of the stored line, so a split is a match and
  half a street is not;
- no two candidates run parallel to each other along the line (two
  carriageways within tolerance of one centreline are two answers, not one);
- no other way of that name and class overlaps the line by more than an end-on
  neighbour would (more than 1.25 tolerances: the old way was merged into a
  longer one, or the junction was redrawn, and applying the row to the rest
  would be a guess);
- no target way already carries a row of the same kind with a different value,
  and no two missing rows of one kind claim the same way with different values.

The row then applies to every candidate. A row that fails any test is left
exactly as it was, so the appliers still list its way id as unmatched, and the
failure is named with its reason in the rebuild report. Nothing is dropped
quietly: `RematchReport` has an entry for every row that was missing, and the
rebuild writes it to `<DATA_ROOT>/rebuild/reports/override-rematch.md`.
"""

from __future__ import annotations

import csv
import io
import json
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from routemaker.geo import EARTH_RADIUS_M
from routemaker.streets import street_key

OVERRIDES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "overrides"
TOLERANCE_M = 6.0
MIN_CONTAINED = 0.9
MIN_COVERAGE = 0.9
SAMPLE_M = 2.0
# Two ways overlapping for longer than this many tolerances are side by side,
# not end to end: pieces of one split meet at a node and overlap by about one
# tolerance at each end.
PARALLEL_TOLERANCES = 2.5
# A way that is not along the line but overlaps it by more than this many
# tolerances is more than an end-on neighbour (which overlaps by about one).
NEIGHBOUR_TOLERANCES = 1.25
SIMPLIFY_M = 1.0
CELL_DEG = 0.005

OUTCOME_REMATCHED = "rematched"
OUTCOME_COVERED = "covered"
OUTCOME_FAILED = "failed"
OUTCOME_DRIFTED = "drifted"


class FingerprintRefused(ValueError):
    """A fixture's fingerprint is malformed."""


# --- Fingerprints -----------------------------------------------------------


def _local(lat0: float):
    kx = math.radians(1.0) * EARTH_RADIUS_M * math.cos(math.radians(lat0))
    ky = math.radians(1.0) * EARTH_RADIUS_M

    def project(lon: float, lat: float) -> tuple[float, float]:
        return (lon * kx, lat * ky)

    return project


def _length_m(coords: Sequence[Sequence[float]]) -> float:
    if len(coords) < 2:
        return 0.0
    project = _local(coords[0][1])
    pts = [project(c[0], c[1]) for c in coords]
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:], strict=False))


def _simplify(pts: list[tuple[float, float]], tolerance: float) -> list[int]:
    """Indexes of the points Douglas-Peucker keeps."""
    keep = {0, len(pts) - 1}
    stack = [(0, len(pts) - 1)]
    while stack:
        lo, hi = stack.pop()
        if hi <= lo + 1:
            continue
        ax, ay = pts[lo]
        bx, by = pts[hi]
        far, far_d = lo, -1.0
        for i in range(lo + 1, hi):
            px, py = pts[i]
            dx, dy = bx - ax, by - ay
            seg2 = dx * dx + dy * dy
            t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
            d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            if d > far_d:
                far, far_d = i, d
        if far_d > tolerance:
            keep.add(far)
            stack.extend([(lo, far), (far, hi)])
    return sorted(keep)


def format_line(coords: Iterable[Sequence[float]]) -> str:
    return " ".join(f"{c[0]:.6f},{c[1]:.6f}" for c in coords)


def parse_line(text: str) -> list[tuple[float, float]]:
    pts = []
    for part in text.split():
        lon, lat = part.split(",")
        pts.append((float(lon), float(lat)))
    return pts


def fingerprint_of(tags: Mapping[str, str], coordinates: Sequence[Sequence[float]]) -> dict:
    """The fingerprint of a way: what is needed to find it again."""
    coords = [(c[0], c[1]) for c in coordinates]
    project = _local(coords[0][1])
    keep = _simplify([project(*c) for c in coords], SIMPLIFY_M)
    return {
        "name": tags.get("name") or None,
        "highway": tags.get("highway") or None,
        "length_m": round(_length_m(coords), 1),
        "line": format_line(coords[i] for i in keep),
    }


def fingerprint_problem(value: object) -> str | None:
    """Why `value` is not a fingerprint, or None if it is."""
    if not isinstance(value, dict):
        return "a fingerprint is an object"
    if set(value) != {"name", "highway", "length_m", "line"}:
        return "a fingerprint has exactly name, highway, length_m and line"
    for key in ("name", "highway"):
        if value[key] is not None and (not isinstance(value[key], str) or not value[key].strip()):
            return f"fingerprint {key} is text or null"
    length = value["length_m"]
    if not isinstance(length, int | float) or isinstance(length, bool) or length <= 0:
        return "fingerprint length_m is a positive number"
    if not isinstance(value["line"], str):
        return "fingerprint line is a string of lon,lat pairs"
    try:
        pts = parse_line(value["line"])
    except ValueError:
        return "fingerprint line is a string of lon,lat pairs"
    if len(pts) < 2 or not all(-180 <= lon <= 180 and -90 <= lat <= 90 for lon, lat in pts):
        return "fingerprint line has two or more points on the earth"
    return None


def load_fingerprints(directory: Path | str | None = None) -> dict[tuple[str, int], dict]:
    """{(kind, way id): fingerprint} from every override file in `directory`:
    a row's own `fingerprint`, and the `superseded` list's entries for ways a
    file re-pointed (a row already loaded in the database still names them)."""
    found: dict[tuple[str, int], dict] = {}
    for path in sorted(Path(directory or OVERRIDES_DIR).glob("*.json")):
        document = json.loads(path.read_text())
        if not isinstance(document, dict):
            continue
        entries = [*document.get("rows", []), *document.get("superseded", [])]
        for index, entry in enumerate(entries):
            fingerprint = entry.get("fingerprint") if isinstance(entry, dict) else None
            if fingerprint is None:
                continue
            where = f"{path.name} entry {index}"
            problem = fingerprint_problem(fingerprint)
            if problem:
                raise FingerprintRefused(f"{where}: {problem}")
            kind, way_id = entry.get("kind"), entry.get("osm_way_id")
            if not isinstance(way_id, int) or isinstance(way_id, bool) or not isinstance(kind, str):
                raise FingerprintRefused(f"{where}: a fingerprint needs the row's kind and way id")
            found[(kind, way_id)] = fingerprint
    return found


# --- Matching ---------------------------------------------------------------


class _Line:
    """A polyline in local metres, with distance and sampling."""

    def __init__(self, coords: Sequence[Sequence[float]], lat0: float) -> None:
        project = _local(lat0)
        self.pts = [project(c[0], c[1]) for c in coords]
        self.segs = [(a, b) for a, b in zip(self.pts, self.pts[1:], strict=False)]

    def distance(self, p: tuple[float, float]) -> float:
        best = math.inf
        for (ax, ay), (bx, by) in self.segs:
            dx, dy = bx - ax, by - ay
            seg2 = dx * dx + dy * dy
            t = (
                0.0
                if seg2 == 0
                else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / seg2))
            )
            best = min(best, math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy)))
        return best

    def samples(self, step: float = SAMPLE_M) -> list[tuple[float, float]]:
        out: list[tuple[float, float]] = []
        for (ax, ay), (bx, by) in self.segs:
            n = max(1, int(math.dist((ax, ay), (bx, by)) // step))
            out.extend((ax + (bx - ax) * i / n, ay + (by - ay) * i / n) for i in range(n))
        if self.pts:
            out.append(self.pts[-1])
        return out


def _share_within(samples: list[tuple[float, float]], line: _Line, tolerance: float) -> float:
    if not samples:
        return 0.0
    return sum(1 for s in samples if line.distance(s) <= tolerance) / len(samples)


def _bbox(coords: Sequence[Sequence[float]]) -> tuple[float, float, float, float]:
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return min(lons), min(lats), max(lons), max(lats)


def _cells(box: tuple[float, float, float, float], pad: float):
    x0, y0, x1, y1 = box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad
    for i in range(int(x0 // CELL_DEG), int(x1 // CELL_DEG) + 1):
        for j in range(int(y0 // CELL_DEG), int(y1 // CELL_DEG) + 1):
            yield (i, j)


@dataclass(frozen=True)
class Match:
    """What `find` concluded for one fingerprint."""

    way_ids: tuple[int, ...]
    reason: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.way_ids)


def find(
    fingerprint: Mapping,
    nearby: Iterable,
    tolerance_m: float = TOLERANCE_M,
) -> Match:
    """The ways in `nearby` that now stand for the fingerprinted way, if that
    is unambiguous (see the module's rules). `nearby` is any iterable of ways
    with `osm_id`, `tags` and `coordinates`; it need not be pre-filtered."""
    points = parse_line(fingerprint["line"])
    lat0 = points[0][1]
    target = _Line(points, lat0)
    target_samples = target.samples()
    pad = tolerance_m / 111_000.0
    box = _bbox(points)
    want_name = street_key(fingerprint["name"])
    want_highway = fingerprint["highway"]
    candidates: list[tuple[object, _Line, list[tuple[float, float]]]] = []
    overreach: list[int] = []
    for way in nearby:
        if len(way.coordinates) < 2:
            continue
        if street_key(way.tags.get("name")) != want_name:
            continue
        if (way.tags.get("highway") or None) != want_highway:
            continue
        wbox = _bbox(way.coordinates)
        if (
            wbox[2] < box[0] - pad
            or wbox[0] > box[2] + pad
            or wbox[3] < box[1] - pad
            or wbox[1] > box[3] + pad
        ):
            continue
        line = _Line(way.coordinates, lat0)
        samples = line.samples()
        near = sum(1 for s in samples if target.distance(s) <= tolerance_m)
        if near / len(samples) >= MIN_CONTAINED:
            candidates.append((way, line, samples))
        elif near * SAMPLE_M > NEIGHBOUR_TOLERANCES * tolerance_m:
            overreach.append(way.osm_id)
    if overreach:
        return Match(
            (),
            "way "
            + ", ".join(str(i) for i in sorted(overreach))
            + " of that name runs along part of it without lying along it (merged into a longer "
            "way, or redrawn); applying the row to the rest would guess",
        )
    if not candidates:
        return Match((), "no way of that name and highway class lies along the stored line")
    covered = sum(
        1
        for s in target_samples
        if any(line.distance(s) <= tolerance_m for _, line, _ in candidates)
    )
    if covered / len(target_samples) < MIN_COVERAGE:
        return Match(
            (),
            f"the ways along it cover only {covered / len(target_samples):.0%} of the stored line",
        )
    for i, (a, _, a_samples) in enumerate(candidates):
        for b, b_line, _ in candidates[i + 1 :]:
            overlap = sum(1 for s in a_samples if b_line.distance(s) <= tolerance_m)
            if overlap * SAMPLE_M > PARALLEL_TOLERANCES * tolerance_m:
                return Match(
                    (),
                    f"ways {a.osm_id} and {b.osm_id} both lie along it, side by side, so it is "
                    "not one answer",
                )
    return Match(tuple(sorted(way.osm_id for way, _, _ in candidates)))


def still_matches(fingerprint: Mapping, way, tolerance_m: float = TOLERANCE_M) -> bool:
    """Whether a present way is still the fingerprinted one: same name and
    class, and its line and the stored line within tolerance of each other."""
    if street_key(way.tags.get("name")) != street_key(fingerprint["name"]):
        return False
    if (way.tags.get("highway") or None) != fingerprint["highway"]:
        return False
    if len(way.coordinates) < 2:
        return False
    points = parse_line(fingerprint["line"])
    target = _Line(points, points[0][1])
    line = _Line(way.coordinates, points[0][1])
    return (
        _share_within(line.samples(), target, tolerance_m) >= MIN_CONTAINED
        and _share_within(target.samples(), line, tolerance_m) >= MIN_COVERAGE
    )


# --- Resolving a rebuild's rows ---------------------------------------------


@dataclass(frozen=True)
class Entry:
    kind: str
    old_way_id: int
    outcome: str
    new_way_ids: tuple[int, ...] = ()
    reason: str = ""
    name: str | None = None


@dataclass(frozen=True)
class RematchReport:
    """One entry per override row whose way was missing, plus the rows whose way
    is present but no longer looks like the way they were written for."""

    entries: tuple[Entry, ...] = ()
    rows: int = 0
    with_fingerprint: int = 0

    def of(self, outcome: str) -> tuple[Entry, ...]:
        return tuple(e for e in self.entries if e.outcome == outcome)

    @property
    def rematched(self) -> tuple[Entry, ...]:
        return self.of(OUTCOME_REMATCHED)

    @property
    def failed(self) -> tuple[Entry, ...]:
        return self.of(OUTCOME_FAILED)

    def summary(self) -> str:
        failed = self.failed
        named = ", ".join(f"{e.kind} {e.old_way_id}" for e in failed[:20])
        if len(failed) > 20:
            named += f" and {len(failed) - 20} more"
        return (
            f"override re-match: {self.rows} rows, {self.with_fingerprint} with a fingerprint; "
            f"{len(self.rematched)} re-matched, {len(self.of(OUTCOME_COVERED))} already covered, "
            f"{len(failed)} failed"
            + (f" ({named})" if failed else "")
            + (
                f"; {len(self.of(OUTCOME_DRIFTED))} present rows drifted"
                if self.of(OUTCOME_DRIFTED)
                else ""
            )
        )

    def to_csv(self) -> str:
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["kind", "old_way_id", "outcome", "new_way_ids", "name", "reason"])
        for e in self.entries:
            writer.writerow(
                [
                    e.kind,
                    e.old_way_id,
                    e.outcome,
                    " ".join(map(str, e.new_way_ids)),
                    e.name or "",
                    e.reason,
                ]
            )
        return out.getvalue()

    def to_markdown(self) -> str:
        lines = [
            "# Override re-match report",
            "",
            "Written by the rebuild (`pipeline.rematch`, OWNER-DECISIONS 282). An approved "
            "override row names a way by id; where the id is no longer in the extract, the row "
            "is re-matched by the stored geometry and street name, and only when that is "
            "unambiguous. Every row that was missing is listed; a failed row is left unapplied "
            "and still counted as unmatched.",
            "",
            f"- Rows read: {self.rows}; with a stored fingerprint: {self.with_fingerprint}",
            f"- Re-matched: {len(self.rematched)}; already covered by a row on the new way: "
            f"{len(self.of(OUTCOME_COVERED))}; failed: {len(self.failed)}; present but drifted: "
            f"{len(self.of(OUTCOME_DRIFTED))}",
            "",
        ]
        if not self.entries:
            lines.append("Every override row's way is in the extract.")
        else:
            lines += [
                "| Kind | Old way | Outcome | New ways | Street | Reason |",
                "|---|---|---|---|---|---|",
            ]
            for e in self.entries:
                lines.append(
                    f"| {e.kind} | {e.old_way_id} | {e.outcome} "
                    f"| {' '.join(map(str, e.new_way_ids))} | {e.name or ''} | {e.reason} |"
                )
        return "\n".join(lines) + "\n"


def resolve(
    rows: Sequence,
    ways_by_id: Mapping[int, object],
    fingerprints: Mapping[tuple[str, int], dict] | None = None,
    tolerance_m: float = TOLERANCE_M,
) -> tuple[list, RematchReport]:
    """`rows` with every row whose way is missing from the extract re-pointed at
    the ways that now stand for it, where that is unambiguous; and the report.
    Rows are `pipeline.overrides.Override` values (a `fingerprint` of their own
    wins over the fixtures'). A failed row is returned unchanged."""
    fingerprints = fingerprints if fingerprints is not None else {}

    def fingerprint_for(row):
        own = getattr(row, "fingerprint", None)
        if own is not None:
            return own
        return fingerprints.get((row.kind, row.osm_way_id))

    entries: list[Entry] = []
    with_fingerprint = sum(1 for row in rows if fingerprint_for(row) is not None)
    missing = [row for row in rows if row.osm_way_id not in ways_by_id]

    for row in rows:
        fp = fingerprint_for(row)
        way = ways_by_id.get(row.osm_way_id)
        if way is not None and fp is not None and not still_matches(fp, way, tolerance_m):
            entries.append(
                Entry(
                    row.kind,
                    row.osm_way_id,
                    OUTCOME_DRIFTED,
                    (row.osm_way_id,),
                    "the way is in the extract but its name, class or line no longer match the "
                    "fingerprint the row was written for; the row still applies to it",
                    fp["name"],
                )
            )

    # One pass over the extract for every missing row's neighbourhood.
    wanted: dict[tuple[int, int], list[int]] = defaultdict(list)
    prints: dict[int, dict] = {}
    for index, row in enumerate(missing):
        fp = fingerprint_for(row)
        if fp is None:
            continue
        prints[index] = fp
        for cell in _cells(_bbox(parse_line(fp["line"])), tolerance_m / 111_000.0):
            wanted[cell].append(index)
    nearby: dict[int, list] = defaultdict(list)
    if wanted:
        for way in ways_by_id.values():
            if len(way.coordinates) < 2:
                continue
            hit: set[int] = set()
            for cell in _cells(_bbox(way.coordinates), 0.0):
                hit.update(wanted.get(cell, ()))
            for index in hit:
                nearby[index].append(way)

    found: dict[int, Match] = {}
    for index in range(len(missing)):
        fp = prints.get(index)
        if fp is None:
            continue
        found[index] = find(fp, nearby.get(index, ()), tolerance_m)

    # Targets, to refuse a re-match that would collide with another row.
    present: dict[tuple[str, int], object] = {
        (row.kind, row.osm_way_id): row for row in rows if row.osm_way_id in ways_by_id
    }
    claims: dict[tuple[str, int], list[int]] = defaultdict(list)
    for index, match in found.items():
        for way_id in match.way_ids:
            claims[(missing[index].kind, way_id)].append(index)

    out: list = []
    resolved: dict[int, list] = {}
    for index, row in enumerate(missing):
        fp = prints.get(index)
        name = fp["name"] if fp else None
        if fp is None:
            entries.append(
                Entry(
                    row.kind,
                    row.osm_way_id,
                    OUTCOME_FAILED,
                    (),
                    "no fingerprint is stored for this row; it cannot be re-matched",
                    None,
                )
            )
            continue
        match = found[index]
        if not match.ok:
            entries.append(Entry(row.kind, row.osm_way_id, OUTCOME_FAILED, (), match.reason, name))
            continue
        problem = ""
        for way_id in match.way_ids:
            other = present.get((row.kind, way_id))
            if other is not None and other.value != row.value:
                problem = f"way {way_id} already carries a {row.kind} row with a different value"
                break
            rivals = [i for i in claims[(row.kind, way_id)] if i != index]
            if any(missing[i].value != row.value for i in rivals):
                problem = (
                    f"way {way_id} is also claimed by another missing {row.kind} row "
                    "with a different value"
                )
                break
        if problem:
            entries.append(Entry(row.kind, row.osm_way_id, OUTCOME_FAILED, (), problem, name))
            continue
        new_ids = tuple(way_id for way_id in match.way_ids if (row.kind, way_id) not in present)
        if not new_ids:
            entries.append(
                Entry(
                    row.kind,
                    row.osm_way_id,
                    OUTCOME_COVERED,
                    match.way_ids,
                    "every way along it already carries an identical row",
                    name,
                )
            )
            resolved[index] = []
            continue
        entries.append(Entry(row.kind, row.osm_way_id, OUTCOME_REMATCHED, match.way_ids, "", name))
        resolved[index] = [replace(row, osm_way_id=way_id) for way_id in new_ids]

    by_row = {id(row): index for index, row in enumerate(missing)}
    emitted: set[tuple[str, int]] = set()
    for row in rows:
        index = by_row.get(id(row))
        if index is None or index not in resolved:
            out.append(row)
            continue
        for new in resolved[index]:
            key = (new.kind, new.osm_way_id)
            if key not in emitted:
                emitted.add(key)
                out.append(new)
    report = RematchReport(
        entries=tuple(sorted(entries, key=lambda e: (e.outcome, e.kind, e.old_way_id))),
        rows=len(rows),
        with_fingerprint=with_fingerprint,
    )
    return out, report
