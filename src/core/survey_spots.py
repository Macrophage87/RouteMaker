"""Survey spots on the map, the answers riders give there, and each rider's count.

The owner, 2026-11-25: riders tap a highlighted stretch whose rating was a low-confidence call (or
pass one on a ride) and answer a few questions about it; "If you've put in the survey once, it
doesn't show up any more for that spot"; the count of spots filled in is for a Freezing Saddles
side prize, on the honor system: a spot counts when the rider says they were there today.

The spot list is `fixtures/survey/spots.json` (scripts/make_survey_spots.py; questions in
`routemaker.survey`). A spot's point is the middle of its `point_way` on the live map, read from
the live segment table once per map (the table's oid changes when a rebuild swaps it in).

What is kept:
- An answer (`SurveyAnswer`): the spot, the day (never the time) and the answers. No account.
- A rider's done list (`SurveyDone`): the spot ids they answered and whether each counted, so the
  layer hides them on every device and the count can be shown. No day, no ride, no point.
Answers are evidence for the next re-rate, never a rating by themselves.
"""

from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError, connection, transaction

from pipeline.schema import validate_schema_name
from routemaker.survey import QUESTIONS, WHEN, answer_problems

SPOTS_FILE = Path(__file__).resolve().parents[2] / "fixtures" / "survey" / "spots.json"
METRES_PER_MILE = 1609.344
# The whole list fits one answer (about 6,000 points): the layer fetches it once.
MAX_IN_BOX = 10_000
MAX_NEAR = 50
MAX_RADIUS_MI = 15.0
#: The answer that makes a spot count toward the rider's total (the honor system).
COUNTS_WHEN = "today"


class Unavailable(Exception):
    """This host has no spot file, or no live map to place the spots on."""


@dataclass(frozen=True, slots=True)
class Spot:
    id: str
    road: str
    state: str
    county: str
    questions: tuple[str, ...]
    point_way: int
    level: tuple[float, float]


@cache
def spots() -> dict[str, Spot]:
    try:
        doc = json.loads(SPOTS_FILE.read_text())
    except FileNotFoundError as e:
        raise Unavailable("no survey spot file") from e
    return {
        s["id"]: Spot(
            id=s["id"],
            road=s["road"],
            state=s["state"],
            county=s["county"],
            questions=tuple(s["questions"]),
            point_way=int(s["point_way"]),
            level=(float(s["level"][0]), float(s["level"][1])),
        )
        for s in doc["spots"]
    }


_lock = threading.Lock()
_points: dict[str, tuple[int, dict[str, tuple[float, float]]]] = {}


def points() -> dict[str, tuple[float, float]]:
    """Each spot's (lon, lat) on the live map; a spot whose way is gone from the map is left out."""
    schema = validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)::oid", [f"{schema}.segment"])
        oid = cursor.fetchone()[0]
    if oid is None:
        raise Unavailable("no live map")
    known = _points.get(schema)
    if known is not None and known[0] == oid:
        return known[1]
    with _lock:
        by_way: dict[int, list[str]] = {}
        for s in spots().values():
            by_way.setdefault(s.point_way, []).append(s.id)
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT DISTINCT ON (osm_way_id) osm_way_id,
                       ST_X(ST_LineInterpolatePoint(geometry, 0.5)),
                       ST_Y(ST_LineInterpolatePoint(geometry, 0.5))
                FROM {schema}.segment
                WHERE osm_way_id = ANY(%s)
                ORDER BY osm_way_id, ST_Length(geometry::geography) DESC
                """,
                [list(by_way)],
            )
            found = {
                spot_id: (float(x), float(y))
                for way, x, y in cursor.fetchall()
                for spot_id in by_way[way]
            }
        _points[schema] = (oid, found)
        return found


def _metres(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat = math.radians((a[1] + b[1]) / 2)
    dx = (a[0] - b[0]) * 111_320 * math.cos(lat)
    dy = (a[1] - b[1]) * 110_574
    return math.hypot(dx, dy)


def _out(s: Spot, p: tuple[float, float]) -> dict:
    return {
        "id": s.id,
        "road": s.road,
        "county": s.county,
        "lon": round(p[0], 6),
        "lat": round(p[1], 6),
        "level": list(s.level),
        "questions": list(s.questions),
    }


def in_box(west: float, south: float, east: float, north: float, hide=frozenset()) -> list[dict]:
    """The spots in a map view as the layer draws them (id, road, point), leaving out `hide`."""
    table = spots()
    got = [
        {"id": i, "road": table[i].road, "lon": round(p[0], 6), "lat": round(p[1], 6)}
        for i, p in points().items()
        if i not in hide and west <= p[0] <= east and south <= p[1] <= north
    ]
    got.sort(key=lambda s: s["id"])
    return got[:MAX_IN_BOX]


def near(lon: float, lat: float, miles: float, hide=frozenset()) -> list[dict]:
    """The spots within `miles` of a point, nearest first, at most `MAX_NEAR`, less `hide`."""
    table = spots()
    reach = min(miles, MAX_RADIUS_MI) * METRES_PER_MILE
    got = []
    for i, p in points().items():
        if i in hide:
            continue
        d = _metres((lon, lat), p)
        if d <= reach:
            got.append((d, i, p))
    got.sort()
    return [
        {**_out(table[i], p), "away_mi": round(d / METRES_PER_MILE, 2)}
        for d, i, p in got[:MAX_NEAR]
    ]


def questions_for(spot_id: str) -> list[dict]:
    """The spot's questions as the card shows them, "When were you last here?" first."""
    s = spots()[spot_id]
    return [
        {
            "key": q.key,
            "text": q.text,
            "options": [{"value": v, "label": label} for v, label in q.options],
        }
        for q in (WHEN, *(QUESTIONS[k] for k in s.questions))
    ]


def done_ids(user) -> frozenset[str]:
    from .models import SurveyDone

    if user is None or not user.is_authenticated:
        return frozenset()
    return frozenset(SurveyDone.objects.filter(user=user).values_list("spot_id", flat=True))


def mine(user) -> dict:
    from .models import SurveyDone

    rows = SurveyDone.objects.filter(user=user)
    return {
        "done": sorted(rows.values_list("spot_id", flat=True)),
        "count": rows.filter(counted=True).count(),
    }


def record(spot_id: str, answers: object, user, day) -> tuple[str | None, dict | None]:
    """Keep one rider's answers at a spot. (problem, None) when refused, else (None, mine(user)).

    A rider answers a spot once: a second answer is refused, so the count cannot be run up.
    """
    from .models import SurveyAnswer, SurveyDone

    table = spots()
    if spot_id not in table:
        return "no such survey spot", None
    if not isinstance(answers, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in answers.items()
    ):
        return "answers must be an object of choices", None
    problems = answer_problems(table[spot_id].questions, answers)
    if problems:
        return "; ".join(problems), None
    try:
        with transaction.atomic():
            SurveyDone.objects.create(
                user=user, spot_id=spot_id, counted=answers[WHEN.key] == COUNTS_WHEN
            )
    except IntegrityError:
        return "you have already answered this spot", None
    # Its own transaction and a random key: nothing ties this row to the rider's done row but the
    # spot (the privacy policy says so).
    with transaction.atomic():
        SurveyAnswer.objects.create(spot_id=spot_id, day=day, answers=answers)
    return None, mine(user)
