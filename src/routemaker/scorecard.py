"""The route scorecard: the same trips, planned at every release and map rebuild, scored and
compared with the last run (backlog 2026-11-12, item 1; docs/SCORECARD.md).

Pure functions, no Django and no network: `plans` turns the trip list
(fixtures/scorecard/trips.json) into POST /api/route bodies, `score` reads one answer
into a row of figures, `run_of` gathers rows into a run, and `compare` diffs two runs
into findings. scripts/route_scorecard.py does the planning (through the PC route-check
service, or over HTTP) and the writing.

Every threshold below is OUR DEFAULT, UNMEASURED: chosen so that a change a rider would
notice is listed, and nothing smaller. The scorecard reports; it never fails a build
(the owner has not made it a gate).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

METRES_PER_MILE = 1609.344
METRES_PER_FOOT = 0.3048

# The stability check moves the start this far (150 ft, the backlog's figure; our default).
STABILITY_SHIFT_M = 150 * METRES_PER_FOOT
# A point of one route "follows" the other within this distance (about 80 ft; our default,
# unmeasured: wider than a divided road, narrower than the next street over).
OVERLAP_NEAR_M = 25.0
# Sample the route every this many metres when measuring overlap.
OVERLAP_STEP_M = 20.0

# What makes a finding when a trip is compared with its last run (all our defaults, unmeasured).
MILES_PCT = 0.10
MILES_ABS = 0.25
MINUTES_PCT = 0.10
MINUTES_ABS = 2.0
TURNS_ABS = 3
TURNS_PCT = 0.25
RED_ABS = 1
LTS3_MI_ABS = 0.25
PATH_SHARE_ABS = 0.10
UNPAVED_MI_ABS = 0.5
SIGNALS_ABS = 3
# Under this share of the new route on the old one, the trip "changed corridor".
CORRIDOR_MIN_OVERLAP = 0.70
# Stability: the moved-start route should share at least this much with the base route.
STABLE_MIN_OVERLAP = 0.70
# Contrast: two ride types sharing at least this much of the route plan the same thing.
CONTRAST_SAME_OVERLAP = 0.90

TURN_MOVEMENTS = frozenset({"left", "right", "bear_left", "bear_right", "uturn"})

# The figures of a row, in the order a table shows them: (key, heading, places).
COLUMNS = (
    ("miles", "Miles", 2),
    ("minutes", "Min", 0),
    ("turns", "Turns", 0),
    ("turns_per_mi", "Turns/mi", 1),
    ("red", "Red", 0),
    ("orange", "Orange", 0),
    ("signals", "Signals", 0),
    ("junction_wait_min", "Wait min", 1),
    ("lts3_mi", "LTS 3 mi", 2),
    ("lts4_mi", "LTS 4+ mi", 2),
    ("path_share", "Path %", 0),
    ("unpaved_mi", "Unpaved mi", 2),
    ("detour_ratio", "Detour x", 2),
)


# --- the trip list -----------------------------------------------------------------------


def shift_north(point: Sequence[float], metres: float) -> list[float]:
    """`point` ([lon, lat]) moved `metres` due north."""
    lat = point[1] + metres / 111_320.0
    return [round(point[0], 6), round(lat, 6)]


def key_of(trip_id: str, preset: str, variant: str = "base") -> str:
    return f"{trip_id}|{preset}|{variant}"


def plans(
    trips: dict,
    *,
    extra: dict | None = None,
    contrast: bool = True,
    stability: bool = True,
    only: Iterable[str] | None = None,
) -> list[dict]:
    """Every plan of a run, as {"key", "trip", "preset", "variant", "body"}.

    `extra` is added to every body (for example {"stress": 70} for a before/after at one
    setting). A trip's own `presets` always run; `contrast` adds the trip list's
    `contrast_presets` on trips marked `contrast`; `stability` adds the trip with the
    start moved north `STABILITY_SHIFT_M` on trips marked `stability`, on the first preset.
    """
    wanted = set(only) if only else None
    when = trips.get("when")
    contrast_presets = list(trips.get("contrast_presets", ()))
    out: list[dict] = []
    seen: set[str] = set()

    def add(trip: dict, preset: str, variant: str, points: list) -> None:
        key = key_of(trip["id"], preset, variant)
        if key in seen:
            return
        seen.add(key)
        body: dict = {"points": [list(p) for p in points], "preset": preset}
        if when:
            body["when"] = when
        body.update(extra or {})
        out.append(
            {"key": key, "trip": trip["id"], "preset": preset, "variant": variant, "body": body}
        )

    for trip in trips["trips"]:
        if wanted is not None and trip["id"] not in wanted:
            continue
        points = trip["points"]
        for preset in trip["presets"]:
            add(trip, preset, "base", points)
        if contrast and trip.get("contrast"):
            for preset in contrast_presets:
                add(trip, preset, "base", points)
        if stability and trip.get("stability"):
            moved = [shift_north(points[0], STABILITY_SHIFT_M), *points[1:]]
            add(trip, trip["presets"][0], "moved", moved)
    return out


# --- one answer --------------------------------------------------------------------------


def _coords(answer: dict) -> list[list[float]] | None:
    geometry = answer.get("geometry") or {}
    coords = geometry.get("coordinates")
    if isinstance(coords, list) and coords and isinstance(coords[0], list):
        return coords
    return None


def turn_count(description: list[dict] | None) -> int | None:
    """Turn cues: stretches entered by a turn (left, right, bear, U-turn), not a fork that
    stays on the same way. None where the answer has no description."""
    if description is None:
        return None
    turns = 0
    for entry in description:
        if entry.get("kind") != "stretch":
            continue
        turn = entry.get("turn") or {}
        if turn.get("movement") in TURN_MOVEMENTS and not turn.get("stay"):
            turns += 1
    return turns


def straight_line_m(points: Sequence[Sequence[float]]) -> float:
    total = 0.0
    for a, b in zip(points, points[1:], strict=False):
        total += _haversine(a, b)
    return total


def score(answer: dict, body: dict | None = None) -> dict:
    """One answer's figures. Missing parts of an answer give None, never a guess."""
    distance = float(answer.get("distance_m") or 0.0)
    miles = distance / METRES_PER_MILE
    stress = answer.get("stress_m") or {}
    facility = answer.get("facility_m") or {}
    spans = answer.get("stress_spans") or []
    intersections = answer.get("intersections")
    junctions = answer.get("junctions_debug")
    turns = turn_count(answer.get("description"))
    detour = answer.get("detour") or {}
    ratio = detour.get("ratio")
    if ratio is None and body and distance:
        straight = straight_line_m(body.get("points") or [])
        ratio = distance / straight if straight else None
    unpaved = sum(
        float(s.get("to_m", 0)) - float(s.get("from_m", 0)) for s in spans if s.get("unpaved")
    )
    calm = answer.get("calm_search") or {}
    row = {
        "miles": miles,
        "minutes": float(answer.get("duration_s") or 0.0) / 60.0,
        "turns": turns,
        "turns_per_mi": (turns / miles) if (turns is not None and miles) else None,
        "red": None
        if intersections is None
        else sum(1 for i in intersections if i.get("severity") == "red"),
        "orange": None
        if intersections is None
        else sum(1 for i in intersections if i.get("severity") == "orange"),
        "signals": None
        if junctions is None
        else sum(1 for j in junctions if j.get("control") == "signal"),
        "junction_wait_min": float(answer.get("junction_delay_s") or 0.0) / 60.0,
        "lts3_mi": float(stress.get("3") or 0.0) / METRES_PER_MILE,
        "lts4_mi": (float(stress.get("4") or 0.0) + float(stress.get("5") or 0.0))
        / METRES_PER_MILE,
        "path_share": (float(facility.get("path") or 0.0) / distance) if distance else None,
        "unpaved_mi": unpaved / METRES_PER_MILE,
        "detour_ratio": ratio,
        "limited": calm.get("limited"),
        "graph": answer.get("variant"),
    }
    return row


# --- overlap -----------------------------------------------------------------------------


def _haversine(a: Sequence[float], b: Sequence[float]) -> float:
    lat1, lat2 = math.radians(a[1]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = math.radians(b[0] - a[0])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371008.8 * math.asin(math.sqrt(min(1.0, h)))


def _project(coords: Sequence[Sequence[float]], lat0: float) -> list[tuple[float, float]]:
    kx = 111_320.0 * math.cos(math.radians(lat0))
    return [(c[0] * kx, c[1] * 110_574.0) for c in coords]


def _samples(xy: list[tuple[float, float]], step: float) -> list[tuple[float, float]]:
    out = [xy[0]] if xy else []
    carry = 0.0
    for (x1, y1), (x2, y2) in zip(xy, xy[1:], strict=False):
        seg = math.hypot(x2 - x1, y2 - y1)
        if seg == 0:
            continue
        t = step - carry
        while t <= seg:
            out.append((x1 + (x2 - x1) * t / seg, y1 + (y2 - y1) * t / seg))
            t += step
        carry = (carry + seg) % step
    if xy and out[-1] != xy[-1]:
        out.append(xy[-1])
    return out


def _segment_distance(p, a, b) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return math.hypot(p[0] - ax, p[1] - ay)
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / length2))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def overlap(
    a: Sequence[Sequence[float]] | None,
    b: Sequence[Sequence[float]] | None,
    near_m: float = OVERLAP_NEAR_M,
) -> float | None:
    """The share of route `a`'s length that runs within `near_m` of route `b` (0 to 1).
    Not symmetric: a short route inside a long one is 1 from the short one's side."""
    if not a or not b or len(a) < 2 or len(b) < 2:
        return None
    lat0 = a[0][1]
    axy, bxy = _project(a, lat0), _project(b, lat0)
    cell = max(near_m, 1.0) * 2
    grid: dict[tuple[int, int], list[int]] = {}
    for i, ((x1, y1), (x2, y2)) in enumerate(zip(bxy, bxy[1:], strict=False)):
        lo_x, hi_x = sorted((x1, x2))
        lo_y, hi_y = sorted((y1, y2))
        for gx in range(int(math.floor(lo_x / cell)), int(math.floor(hi_x / cell)) + 1):
            for gy in range(int(math.floor(lo_y / cell)), int(math.floor(hi_y / cell)) + 1):
                grid.setdefault((gx, gy), []).append(i)
    samples = _samples(axy, OVERLAP_STEP_M)
    near = 0
    for p in samples:
        gx, gy = int(math.floor(p[0] / cell)), int(math.floor(p[1] / cell))
        hit = False
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for i in grid.get((gx + dx, gy + dy), ()):
                    if _segment_distance(p, bxy[i], bxy[i + 1]) <= near_m:
                        hit = True
                        break
                if hit:
                    break
            if hit:
                break
        near += hit
    return near / len(samples) if samples else None


# --- a run -------------------------------------------------------------------------------


def run_of(entries: Sequence[dict], answers: dict[str, dict], meta: dict | None = None) -> dict:
    """A run: `entries` from `plans`, `answers` by key as {"status": int, "body": answer}.
    Keeps each route's line (rounded to about 1 m) for the next run's corridor check."""
    rows: dict[str, dict] = {}
    for entry in entries:
        got = answers.get(entry["key"])
        row = {"trip": entry["trip"], "preset": entry["preset"], "variant": entry["variant"]}
        if got is None:
            row["status"] = None
        else:
            row["status"] = got.get("status")
            body = got.get("body") or {}
            if row["status"] == 200 and isinstance(body, dict):
                row.update(score(body, entry["body"]))
                coords = _coords(body)
                if coords:
                    row["line"] = [[round(c[0], 5), round(c[1], 5)] for c in coords]
            else:
                row["error"] = (body.get("error") if isinstance(body, dict) else None) or str(body)[
                    :200
                ]
        rows[entry["key"]] = row
    run = {"meta": dict(meta or {}), "rows": rows}
    run["checks"] = checks(run)
    return run


def checks(run: dict) -> dict:
    """The stability and contrast checks inside one run."""
    rows = run["rows"]
    stability = []
    for row in rows.values():
        if row.get("variant") != "moved" or "line" not in row:
            continue
        base = rows.get(key_of(row["trip"], row["preset"], "base"))
        if not base or "line" not in base:
            continue
        share = overlap(row["line"], base["line"])
        stability.append(
            {
                "trip": row["trip"],
                "preset": row["preset"],
                "overlap": share,
                "stable": share is not None and share >= STABLE_MIN_OVERLAP,
            }
        )
    contrast = []
    by_trip: dict[str, dict[str, dict]] = {}
    for row in rows.values():
        if row.get("variant") == "base" and "line" in row:
            by_trip.setdefault(row["trip"], {})[row["preset"]] = row
    for trip, presets in by_trip.items():
        names = sorted(presets)
        for i, p in enumerate(names):
            for q in names[i + 1 :]:
                one = overlap(presets[p]["line"], presets[q]["line"])
                two = overlap(presets[q]["line"], presets[p]["line"])
                share = None if one is None or two is None else min(one, two)
                contrast.append(
                    {
                        "trip": trip,
                        "a": p,
                        "b": q,
                        "overlap": share,
                        "same": share is not None and share >= CONTRAST_SAME_OVERLAP,
                    }
                )
    return {"stability": stability, "contrast": contrast}


# --- comparing two runs ------------------------------------------------------------------


def _changed(old, new, pct: float, absolute: float) -> bool:
    if old is None or new is None:
        return False
    delta = abs(new - old)
    return delta >= absolute and (old == 0 or delta / abs(old) >= pct)


def findings_for(old: dict, new: dict) -> list[str]:
    """What moved enough to read, in words, for one trip's two rows."""
    out: list[str] = []
    if old.get("status") == 200 and new.get("status") != 200:
        out.append(f"no longer plans ({new.get('status')}: {new.get('error', '')})".strip())
        return out
    if old.get("status") != 200 and new.get("status") == 200:
        out.append("plans again")
    if new.get("status") != 200 or old.get("status") != 200:
        return out

    def get(row, k):
        return row.get(k)

    if _changed(get(old, "miles"), get(new, "miles"), MILES_PCT, MILES_ABS):
        out.append(f"miles {old['miles']:.2f} -> {new['miles']:.2f}")
    if _changed(get(old, "minutes"), get(new, "minutes"), MINUTES_PCT, MINUTES_ABS):
        out.append(f"minutes {old['minutes']:.0f} -> {new['minutes']:.0f}")
    if _changed(get(old, "turns"), get(new, "turns"), TURNS_PCT, TURNS_ABS):
        out.append(f"turns {old['turns']} -> {new['turns']}")
    if None not in (old.get("red"), new.get("red")) and new["red"] - old["red"] >= RED_ABS:
        out.append(f"red junctions {old['red']} -> {new['red']}")
    if new.get("lts3_mi", 0) - old.get("lts3_mi", 0) >= LTS3_MI_ABS:
        out.append(f"LTS 3 mi {old['lts3_mi']:.2f} -> {new['lts3_mi']:.2f}")
    if new.get("lts4_mi", 0) - old.get("lts4_mi", 0) >= LTS3_MI_ABS:
        out.append(f"LTS 4+ mi {old['lts4_mi']:.2f} -> {new['lts4_mi']:.2f}")
    if None not in (old.get("path_share"), new.get("path_share")) and (
        abs(new["path_share"] - old["path_share"]) >= PATH_SHARE_ABS
    ):
        out.append(f"path {old['path_share']:.0%} -> {new['path_share']:.0%}")
    if abs(new.get("unpaved_mi", 0) - old.get("unpaved_mi", 0)) >= UNPAVED_MI_ABS:
        out.append(f"unpaved mi {old['unpaved_mi']:.2f} -> {new['unpaved_mi']:.2f}")
    if None not in (old.get("signals"), new.get("signals")) and (
        abs(new["signals"] - old["signals"]) >= SIGNALS_ABS
    ):
        out.append(f"signals {old['signals']} -> {new['signals']}")
    if old.get("limited") != new.get("limited"):
        out.append(f"calm search limited {old.get('limited')} -> {new.get('limited')}")
    if "line" in old and "line" in new:
        share = overlap(new["line"], old["line"])
        if share is not None and share < CORRIDOR_MIN_OVERLAP:
            out.append(f"changed corridor ({share:.0%} on the old line)")
    return out


def compare(old: dict, new: dict) -> dict:
    """Findings by key, for keys in both runs, plus keys only in one."""
    found: dict[str, list[str]] = {}
    for key, row in new["rows"].items():
        before = old["rows"].get(key)
        if before is None:
            continue
        lines = findings_for(before, row)
        if lines:
            found[key] = lines
    return {
        "findings": found,
        "added": sorted(set(new["rows"]) - set(old["rows"])),
        "dropped": sorted(set(old["rows"]) - set(new["rows"])),
    }


# --- words -------------------------------------------------------------------------------


def _fmt(value, places: int) -> str:
    if value is None:
        return "-"
    if isinstance(value, float) and math.isnan(value):
        return "-"
    return f"{value:.{places}f}"


def _cell(key: str, value, places: int) -> str:
    if key == "path_share" and value is not None:
        return f"{value * 100:.0f}"
    return _fmt(value, places)


def table(run: dict, old: dict | None = None) -> str:
    """The run as a Markdown table; with `old`, each changed figure reads "old -> new"."""
    head = "| Trip | Ride type | " + " | ".join(h for _, h, _ in COLUMNS) + " |"
    rule = "|---|---|" + "---|" * len(COLUMNS)
    lines = [head, rule]
    for key, row in run["rows"].items():
        if row.get("variant") != "base":
            continue
        label = f"| {row['trip']} | {row['preset']} | "
        if row.get("status") != 200:
            lines.append(label + f"failed ({row.get('status')}) |" + " |" * (len(COLUMNS) - 1))
            continue
        before = (old or {}).get("rows", {}).get(key) if old else None
        cells = []
        for k, _, places in COLUMNS:
            now = _cell(k, row.get(k), places)
            if before and before.get("status") == 200:
                was = _cell(k, before.get(k), places)
                cells.append(now if was == now else f"{was} -> {now}")
            else:
                cells.append(now)
        lines.append(label + " | ".join(cells) + " |")
    return "\n".join(lines)


def report(new: dict, old: dict | None = None) -> str:
    """The whole report in Markdown: findings first, then the checks, then the table."""
    meta = new.get("meta", {})
    out = ["# Route scorecard", ""]
    if meta:
        out.append(" · ".join(f"{k}: {v}" for k, v in meta.items()))
        out.append("")
    if old is not None:
        diff = compare(old, new)
        old_meta = old.get("meta", {})
        out.append(f"Compared with: {old_meta.get('label') or old_meta.get('ref') or 'last run'}")
        out.append("")
        out.append("## What moved")
        out.append("")
        if diff["findings"]:
            for key, lines in diff["findings"].items():
                out.append(f"- **{key.replace('|', ' · ')}**: " + "; ".join(lines))
        else:
            out.append("- Nothing past the thresholds.")
        if diff["added"]:
            out.append(f"- New in this run: {len(diff['added'])} plans.")
        if diff["dropped"]:
            out.append(f"- Missing from this run: {len(diff['dropped'])} plans.")
        out.append("")
    failed = [k for k, r in new["rows"].items() if r.get("status") != 200]
    if failed:
        out.append(f"## Failed plans ({len(failed)})")
        out.append("")
        for key in failed:
            row = new["rows"][key]
            out.append(f"- {key.replace('|', ' · ')}: {row.get('status')} {row.get('error', '')}")
        out.append("")
    stab = new.get("checks", {}).get("stability", [])
    if stab:
        out.append("## Stability (start moved 150 ft north)")
        out.append("")
        for s in stab:
            mark = "steady" if s["stable"] else "**changed route**"
            out.append(f"- {s['trip']} · {s['preset']}: {_pct(s['overlap'])} shared, {mark}")
        out.append("")
    con = [c for c in new.get("checks", {}).get("contrast", []) if c["same"]]
    if con:
        out.append("## Ride types that planned the same route (90%+ shared)")
        out.append("")
        for c in con:
            out.append(f"- {c['trip']}: {c['a']} and {c['b']} ({_pct(c['overlap'])})")
        out.append("")
    out.append("## Table")
    out.append("")
    out.append(table(new, old))
    out.append("")
    out.append(
        "Turns are turn cues (left, right, bear, U-turn). Red and Orange are flagged junctions."
        " Signals count signalized junctions; Wait min is all junction waits the time includes."
        " LTS 4+ includes Avoid. Path % is traffic-free share. Detour x is against the most"
        " direct route (the straight line where the answer gave none). Thresholds are our"
        " defaults, unmeasured (src/routemaker/scorecard.py)."
    )
    return "\n".join(out) + "\n"


def _pct(value) -> str:
    return "-" if value is None else f"{value:.0%}"
