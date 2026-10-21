"""One mountain-bike trail's elevation profile, for the road panel (the owner, 2026-10-19:
"Include an elevation profile of the trail if possible").

A tap on the mountain-bike trail layer opens the road panel for that trail (`core.
segment_info`, `trail`); this draws the heights along it. The trail is named by its OSM
way id and read from the live segment table, so the endpoint draws no line a caller chose,
and only a way the trail layer draws (`segment_info.is_mtb_trail`) is answered. The
heights are the router's (`/height`, the USGS 3DEP tiles every route's chart reads),
sampled every `routing.ELEVATION_INTERVAL_M` along the way, or further apart on a long
one so a profile is at most MAX_SAMPLES points. The answer for a way does not change until
the table does, so it is kept by way and table (`_kept`).

One OSM way is the trail's piece between two junctions, or the whole trail where it is
mapped as one: the panel says "this section" (frontend/src/lib/trailProfile.ts).
"""

from __future__ import annotations

import json
from collections import OrderedDict

from django.conf import settings
from django.db import connection

from pipeline.schema import validate_schema_name
from routemaker import profile as profile_rules
from routemaker.geo import Point, haversine

from . import routing, segment_info

# The router whose `/height` is asked: every router serves the same elevation tiles.
VARIANT = "standard"
BUDGET_S = 6.0
PER_CALL_S = 5.0
# The most samples one profile has (a 30 m step to about 12 km, then wider).
MAX_SAMPLES = 400
KEEP = 512

_kept: OrderedDict[tuple[int, int | None], dict | None] = OrderedDict()


class Unavailable(Exception):
    """The router did not answer for the heights."""


def way_line(way_id: int) -> tuple[list[tuple[float, float]], int | None] | None:
    """The way's line (lon, lat), its pieces joined in order, and the live table's oid;
    None where the way is not a trail the layer draws."""
    schema = validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
    have = segment_info.live_columns(schema)
    wanted = [c for c in ("mtb_only", "map_class", "bike_access_reason") if c in have]
    if "mtb_only" not in wanted:
        return None
    select = ", ".join(wanted)
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)::oid", [f"{schema}.segment"])
        oid = cursor.fetchone()[0]
        cursor.execute(
            f"SELECT {select}, ST_AsGeoJSON(geometry) FROM {schema}.segment "
            "WHERE osm_way_id = %s ORDER BY ordinal",
            [way_id],
        )
        rows = cursor.fetchall()
    if not rows:
        return None
    first = dict(zip(wanted, rows[0][:-1], strict=True))
    if not segment_info.is_mtb_trail(first):
        return None
    line: list[tuple[float, float]] = []
    for row in rows:
        for lon, lat in json.loads(row[-1])["coordinates"]:
            point = (float(lon), float(lat))
            if not line or line[-1] != point:
                line.append(point)
    return (line, oid) if len(line) >= 2 else None


def samples(line: list[tuple[float, float]]) -> tuple[list[float], list[tuple[float, float]], int]:
    """Points along the line every step (metres from its start, and where), its ends
    included, and the step: ELEVATION_INTERVAL_M, wider on a long line (MAX_SAMPLES)."""
    lengths = [haversine(Point(*a), Point(*b)) for a, b in zip(line, line[1:], strict=False)]
    total = sum(lengths)
    step = max(routing.ELEVATION_INTERVAL_M, int(total / (MAX_SAMPLES - 1)) + 1)
    at: list[float] = []
    where: list[tuple[float, float]] = []
    walked = 0.0
    next_m = 0.0
    for (a, b), length in zip(zip(line, line[1:], strict=False), lengths, strict=True):
        while length > 0 and next_m <= walked + length:
            t = (next_m - walked) / length
            at.append(next_m)
            where.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            next_m += step
        walked += length
    if not at or at[-1] < total:
        at.append(total)
        where.append(line[-1])
    return at, where, step


def body_of(way_id: int, at: list[float], heights: list[float | None], step: int) -> dict | None:
    """The answer: the samples, the climbing and descending, the steepest grade either
    way. None where the router gave no heights."""
    pairs = list(zip(at, heights, strict=True))
    if not any(h is not None for h in heights):
        return None
    grade_at = profile_rules.grades(pairs)
    # The route chart's climbing and descending (`routing.climb_and_descent`, with its
    # hysteresis): a bare sum of 30 m steps turns the elevation tiles' noise into climbing.
    gain, loss = routing.climb_and_descent(heights)
    steepest = max((abs(g) for g in grade_at if g is not None), default=None)
    return {
        "way": way_id,
        "length_m": round(at[-1]),
        "gain_m": round(gain, 1),
        "loss_m": round(loss, 1),
        "max_grade_pct": None if steepest is None else round(steepest * 100, 1),
        "interval_m": step,
        "m": [round(m) for m in at],
        "elevation_m": [None if h is None else round(h, 1) for h in heights],
        "grade_pct": [None if g is None else round(g * 100, 1) for g in grade_at],
    }


def profile(way_id: int) -> dict | None:
    """The trail's profile, or None (not a trail the layer draws, or no heights). Raises
    Unavailable where the router did not answer (not kept, so the next ask tries again)."""
    found = way_line(way_id)
    if found is None:
        return None
    line, oid = found
    key = (way_id, oid)
    if key in _kept:
        _kept.move_to_end(key)
        return _kept[key]
    at, where, step = samples(line)
    deadline = routing.Deadline(routing.clock() + BUDGET_S, PER_CALL_S)
    try:
        answer = routing._call(
            VARIANT, "height", {"shape": [{"lon": p[0], "lat": p[1]} for p in where]}, deadline
        )
    except routing.RouterRefused:
        # Not kept: a refusal (a router mid-restart, say) is no answer for the table's life.
        return None
    except (routing.RouterUnavailable, routing.DeadlineExceeded) as error:
        raise Unavailable(str(error)) from error
    raw = answer.get("height")
    heights: list[float | None] = (
        [h if isinstance(h, (int, float)) and h > -1000 else None for h in raw]
        if isinstance(raw, list) and len(raw) == len(where)
        else [None] * len(where)
    )
    body = body_of(way_id, at, heights, step)
    if body is not None:
        # The way's two ends, so the chart can say which way it runs (the owner, 2026-10-20: "If the
        # trail goes from N to S put those directions on each end").
        body["start"] = [round(line[0][0], 6), round(line[0][1], 6)]
        body["end"] = [round(line[-1][0], 6), round(line[-1][1], 6)]
    _kept[key] = body
    while len(_kept) > KEEP:
        _kept.popitem(last=False)
    return body
