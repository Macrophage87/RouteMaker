"""Send to Garmin through the rider's connection (core.garmin): the route shown, added to their
Garmin Connect account as a course with Garmin's Courses API, which syncs it to their Edge or
watch. Garmin works out the turn directions from the line itself, so only the line is sent: its
points, their elevations, the distance, the climb and descent, the name and the kind of ride.

A saved route sent again updates its course in place (GarminLink.courses), so the rider's list in
Garmin Connect does not fill with copies; a route not saved is a new course each time.

The line is thinned first (points closer than `MIN_STEP_M` to the last one kept add nothing a
unit can show), then filled in so no two points are more than `MAX_GAP_M` apart, as Garmin asks.
A course is at most `MAX_POINTS` points, about 600 miles (965 km); a longer route is refused with
a line saying to split it. HTTP goes through `garmin.Transport`, replaced in the tests.
"""

from __future__ import annotations

import logging
import math

from django.db import transaction

from . import garmin

log = logging.getLogger(__name__)

COURSE_URL = "https://apis.garmin.com/training-api/courses/v1/course"
MAX_GAP_M = 100.0
MIN_STEP_M = 5.0
MAX_POINTS = 10_000
MAX_NAME = 100
# What the request may carry before filling in: generous for a planned line, which is denser.
MAX_LINE_POINTS = 50_000
EARTH_M = 6_371_008.8

# Ride types (frontend lib/presets.ts) whose courses are mountain biking or gravel on the unit;
# every other is road cycling.
ACTIVITY = {
    "mountain-bike": "MOUNTAIN_BIKING",
    "mountain-goat": "MOUNTAIN_BIKING",
    "trailmaxxing": "MOUNTAIN_BIKING",
    "gravel": "GRAVEL_CYCLING",
}

TOO_LONG = "This route has too many points for one Garmin course. Split it, then send each part."
NO_PERMISSION = (
    "Garmin Connect has not allowed RouteMaker to add courses. Allow it in Garmin Connect, "
    "under your connected apps, then send again."
)
BUSY = "Garmin is taking too many courses just now. Try again in a few minutes."
REFUSED = "Garmin did not take the course. Try again later."
NOT_TAKEN = "Garmin could not read this route as a course. Send it as a file instead."


class BadLine(ValueError):
    """The line sent is not one a course can be made from; the message says why."""


def _metres(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance between (lon, lat) points, in metres."""
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_M * math.asin(min(1.0, math.sqrt(h)))


def read_line(raw) -> list[tuple[float, float, float | None]]:
    """[[lon, lat] or [lon, lat, ele], ...] as checked (lon, lat, ele) tuples. Raises BadLine."""
    if not isinstance(raw, list) or not 2 <= len(raw) <= MAX_LINE_POINTS:
        raise BadLine(f"Send the line as 2 to {MAX_LINE_POINTS} [lon, lat, ele] points.")
    points = []
    for item in raw:
        if not isinstance(item, list) or len(item) not in (2, 3):
            raise BadLine("Each point is [lon, lat] or [lon, lat, ele].")
        values = [
            v if isinstance(v, int | float) and not isinstance(v, bool) else None for v in item
        ]
        lon, lat = values[0], values[1]
        ele = values[2] if len(values) == 3 else None
        if lon is None or lat is None or not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise BadLine("A point is not a longitude and latitude.")
        # A comparison, not math.isfinite: a JSON integer can be too big for a float (and NaN
        # and infinities fail it too).
        if ele is not None and not -500 <= ele <= 9000:
            ele = None
        points.append((float(lon), float(lat), None if ele is None else float(ele)))
    return points


def _thinned(
    points: list[tuple[float, float, float | None]],
) -> list[tuple[float, float, float | None]]:
    """The line without points closer than MIN_STEP_M to the last one kept (the end is kept)."""
    out = [points[0]]
    for point in points[1:-1]:
        if _metres(out[-1], point) >= MIN_STEP_M:
            out.append(point)
    out.append(points[-1])
    return out


def _with_elevations(
    points: list[tuple[float, float, float | None]],
) -> list[tuple[float, float, float | None]]:
    """Each missing elevation from the nearest known one before it (or after, at the start), so
    every point Garmin gets has one; a line with none known keeps none."""
    first = next((p[2] for p in points if p[2] is not None), None)
    if first is None:
        return points
    out, last = [], first
    for lon, lat, ele in points:
        last = ele if ele is not None else last
        out.append((lon, lat, last))
    return out


def _filled(
    points: list[tuple[float, float, float | None]],
) -> list[tuple[float, float, float | None]]:
    """The line with points added along each step longer than MAX_GAP_M (straight, with the
    elevation in proportion), so Garmin gets one at least every 100 m."""
    out = [points[0]]
    for a, b in zip(points, points[1:], strict=False):
        pieces = math.ceil(_metres(a, b) / MAX_GAP_M)
        for k in range(1, pieces):
            t = k / pieces
            ele = None if a[2] is None or b[2] is None else a[2] + (b[2] - a[2]) * t
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, ele))
            if len(out) > MAX_POINTS:
                raise BadLine(TOO_LONG)
        out.append(b)
        if len(out) > MAX_POINTS:
            raise BadLine(TOO_LONG)
    return out


def build(name: str, preset: str, raw_line) -> dict:
    """The Courses API body for the line. Raises BadLine."""
    points = _filled(_with_elevations(_thinned(read_line(raw_line))))
    distance = sum(_metres(a, b) for a, b in zip(points, points[1:], strict=False))
    known = [p[2] for p in points if p[2] is not None]
    rises = [b - a for a, b in zip(known, known[1:], strict=False)]
    geo = []
    for lon, lat, ele in points:
        point = {"latitude": round(lat, 7), "longitude": round(lon, 7)}
        if ele is not None:
            point["elevation"] = round(ele, 1)
        geo.append(point)
    return {
        "courseName": (str(name).strip() or "RouteMaker route")[:MAX_NAME],
        "description": "Planned in RouteMaker",
        "distance": round(distance, 1),
        "elevationGain": round(sum(r for r in rises if r > 0), 1),
        "elevationLoss": round(-sum(r for r in rises if r < 0), 1),
        "activityType": ACTIVITY.get(preset, "ROAD_CYCLING"),
        "coordinateSystem": "WGS84",
        "geoPoints": geo,
    }


def _call(user, method: str, url: str, body: dict, transport: garmin.Transport) -> tuple[int, dict]:
    """One Courses API call; Garmin refusing the token is answered by one refresh and a retry."""
    from .garmin_views import access_for

    status, answer = transport.send_json(method, url, access_for(user, transport), body)
    if status == 401:
        status, answer = transport.send_json(
            method, url, access_for(user, transport, fresh=True), body
        )
    if status not in (200, 204, 404):
        # What Garmin said, for the operator: never the token, at most the start of its answer.
        log.warning("Garmin Courses %s answered %s: %.300s", method, status, answer)
    if status == 401:
        raise garmin.GarminError(REFUSED)
    if status == 400:
        raise garmin.GarminError(NOT_TAKEN)
    if status == 412:
        raise garmin.GarminError(NO_PERMISSION)
    if status == 429:
        raise garmin.GarminError(BUSY)
    return status, answer


def send(user, course: dict, saved_route_id: int | None, transport: garmin.Transport | None = None):
    """Add the course to the rider's Garmin Connect, or update the one this saved route was sent
    as. Returns ("added" | "updated", course id). Raises NotConnected or GarminError."""
    from .models import GarminLink, SavedRoute

    transport = transport or garmin.Transport()
    key = None
    if (
        saved_route_id is not None
        and SavedRoute.objects.filter(pk=saved_route_id, user=user).exists()
    ):
        key = str(saved_route_id)
    link = GarminLink.objects.filter(user=user).first()
    known = (link.courses or {}).get(key) if link and key else None
    if known is not None:
        status, _ = _call(
            user, "PUT", f"{COURSE_URL}/{known}", {**course, "courseId": known}, transport
        )
        if status in (200, 204):
            return "updated", known
        if status not in (403, 404):
            raise garmin.GarminError(REFUSED)
        # Deleted in Garmin Connect since (404), or not this Garmin account's (403): added again.
    status, answer = _call(user, "POST", COURSE_URL, course, transport)
    course_id = answer.get("courseId") if status == 200 else None
    if not isinstance(course_id, int | str) or isinstance(course_id, bool) or course_id == "":
        raise garmin.GarminError(REFUSED)
    if key is not None:
        _remember(user, key, course_id)
    return "added", course_id


def _remember(user, key: str, course_id) -> None:
    from .models import GarminLink, SavedRoute

    with transaction.atomic():
        link = GarminLink.objects.select_for_update().filter(user=user).first()
        if link is None:
            return
        # Routes deleted since are let go, so the map stays as small as the rider's saved routes.
        live = {
            str(i)
            for i in SavedRoute.objects.filter(
                user=user, pk__in=[int(k) for k in [*(link.courses or {}), key] if str(k).isdigit()]
            ).values_list("pk", flat=True)
        }
        courses = {k: v for k, v in (link.courses or {}).items() if k in live}
        courses[key] = course_id
        link.courses = courses
        link.save(update_fields=["courses"])
