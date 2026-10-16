"""Closures on a rider's saved routes (v0.7.0 closures, "saved-route alerts").

A saved route keeps its line verbatim, so a closure that comes in after it was saved is not routed
round. When a closure in force now - a feed's (`core.workzones`, `core.closure_sources`) or one an
admin confirmed (`core.reviewed_closures`) - runs along a signed-in rider's saved route, the rider
sees it the next time they open My routes: "Closed on your route: Oak Street, until Oct 20, 2026."
Opening the route itself runs the closure check (`workzones.closures_on`, POST
/api/closures/check) as before. No e-mail and no push.

The worker's `check_saved_route_closures` task (config.procrastinate, every fifteen minutes, after
the feeds' refreshes) runs `refresh_all`, kept cheap:

- **Nothing changed, nothing read.** The closures in force are hashed (`digest`); where the hash
  is the last finished pass's, only the routes never checked are (`closures_checked_at` null).
- **A pass at a time.** Where it changed, every route is checked from the start, at most
  `MOST_PER_RUN` a run in batches of `BATCH`, the place reached kept (`STATE_KEY`'s cursor) so
  the next run goes on from there; a hash that changes again mid-pass starts it over.
- **Lines only where they could meet.** Each route's box (`SavedRoute.bbox_*`, set when it is
  saved, filled in here for older rows) is compared with the closures' boxes before its line is
  read; a route clear of them all has no alerts.

A route just saved is checked when it is saved (`check`); a closure an admin ends leaves the
routes' alerts at once (`drop`).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime

from django.utils import timezone

logger = logging.getLogger(__name__)

# Saved routes read a batch at a time, and at most this many checked a run.
BATCH = 50
MOST_PER_RUN = 2000
# At most this many alerts are kept for one route, in line order.
MOST = 5
# The job's own state: its row in `bikeshare_feed_cache` (the hash and the place reached).
STATE_KEY = "saved_alerts"
# How far a closure's box is widened (degrees, about 220 m): the closure check's own margin.
BOX_MARGIN = 0.002


def alerts_for(line, now: datetime | None = None) -> list[dict]:
    """The closures in force now that `line` runs along: closed to bicycles, or every lane closed
    with bicycles not mentioned (the closure check's closures, `workzones.closures_on`)."""
    from . import workzones

    now = now or timezone.now()
    coordinates = [p[:2] for p in line or [] if isinstance(p, list) and len(p) >= 2]
    if len(coordinates) < 2:
        return []
    found = workzones.closures_on(coordinates, at=now, now=now)
    out = []
    for row in found["closures"][:MOST]:
        where = row["road"] or row["title"]
        until = _until(row["end"], row.get("source_key") == "reviewer")
        out.append(
            {
                "id": row["id"],
                "title": row["title"],
                "road": row["road"],
                "end": row["end"],
                "source": row["source_name"],
                "text": f"Closed on your route: {where}, {until}.",
            }
        )
    return out


def _until(end: str | None, reviewer: bool = False) -> str:
    from routemaker import ridetime

    if not end:
        return "until a reviewer ends it" if reviewer else "no end date given"
    local = datetime.fromisoformat(end).astimezone(ridetime.ZONE)
    return f"until {local.strftime('%b')} {local.day}, {local.year}"


def box_of(line) -> tuple[float, float, float, float] | None:
    points = [p for p in line or [] if isinstance(p, list) and len(p) >= 2]
    if not points:
        return None
    lons = [float(p[0]) for p in points]
    lats = [float(p[1]) for p in points]
    return min(lons), min(lats), max(lons), max(lats)


def set_box(route) -> None:
    """The route's box from its line, on the object (saved by the caller)."""
    box = box_of(route.line)
    route.bbox_west, route.bbox_south, route.bbox_east, route.bbox_north = box or (None,) * 4


def check(route, now: datetime | None = None) -> None:
    """Check one saved route now and keep its alerts and box. A failure keeps what it had."""
    now = now or timezone.now()
    try:
        alerts = alerts_for(route.line, now)
    except Exception:  # noqa: BLE001 - a route is saved whether or not the check ran
        logger.warning("saved-route closures: a route could not be checked", exc_info=True)
        return
    set_box(route)
    route.closure_alerts = alerts
    route.closures_checked_at = now
    route.save(
        update_fields=[
            "closure_alerts",
            "closures_checked_at",
            "bbox_west",
            "bbox_south",
            "bbox_east",
            "bbox_north",
        ]
    )


def drop(zone_ids) -> int:
    """Take these closures out of every saved route's alerts now (a closure an admin ended).
    Returns how many routes changed."""
    from django.db.models import Q

    from .models import SavedRoute

    ids = set(zone_ids)
    if not ids:
        return 0
    match = Q()
    for zone_id in ids:
        match |= Q(closure_alerts__contains=[{"id": zone_id}])
    changed = 0
    for row in SavedRoute.objects.filter(match).only("pk", "closure_alerts"):
        kept = [a for a in row.closure_alerts or [] if a.get("id") not in ids]
        SavedRoute.objects.filter(pk=row.pk).update(closure_alerts=kept)
        changed += 1
    return changed


def _in_force(now: datetime) -> list:
    from routemaker import workzones as rules

    from . import workzones

    return [
        z
        for z in workzones.snapshot().zones
        if z.kind in (rules.CLOSED, rules.UNKNOWN) and rules.active(z, now)
    ]


def digest(zones) -> str:
    """The closures in force, hashed: what they are, where, and until when."""
    rows = sorted(
        (z.zone_id, None if z.end is None else z.end.isoformat(), [list(p) for p in z.line])
        for z in zones
    )
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


def _boxes(zones) -> list[tuple[float, float, float, float]]:
    out = []
    for zone in zones:
        box = box_of([list(p) for p in zone.line])
        if box is not None:
            m = BOX_MARGIN
            out.append((box[0] - m, box[1] - m, box[2] + m, box[3] + m))
    return out


def _meets(row, boxes) -> bool:
    west, south, east, north = row.bbox_west, row.bbox_south, row.bbox_east, row.bbox_north
    return any(west <= b[2] and east >= b[0] and south <= b[3] and north >= b[1] for b in boxes)


def _check_rows(rows, boxes, now: datetime) -> tuple[int, int]:
    """Check these routes (loaded without their lines); (how many changed, how many closed)."""
    from .models import SavedRoute

    changed = closed = 0
    for row in rows:
        fields: dict = {"closures_checked_at": now}
        if row.bbox_west is None:
            full = SavedRoute.objects.only("pk", "line").get(pk=row.pk)
            box = box_of(full.line) or (None,) * 4
            row.bbox_west, row.bbox_south, row.bbox_east, row.bbox_north = box
            fields.update(bbox_west=box[0], bbox_south=box[1], bbox_east=box[2], bbox_north=box[3])
        alerts: list = []
        if row.bbox_west is not None and _meets(row, boxes):
            line = SavedRoute.objects.values_list("line", flat=True).get(pk=row.pk)
            alerts = alerts_for(line, now)
        closed += bool(alerts)
        if alerts != (row.closure_alerts or []):
            changed += 1
            fields["closure_alerts"] = alerts
        SavedRoute.objects.filter(pk=row.pk).update(**fields)
    return changed, closed


LIGHT = ("pk", "closure_alerts", "bbox_west", "bbox_south", "bbox_east", "bbox_north")


def refresh_all(now: datetime | None = None, most: int = MOST_PER_RUN) -> str:
    """Check the saved routes against the closures in force now (the module's three rules).
    Returns a line for the run row."""
    from . import workzones
    from .models import BikeshareFeedCache, SavedRoute

    now = now or timezone.now()
    workzones.forget()  # this check reads the closures as they are now, not a minute ago
    zones = _in_force(now)
    found = digest(zones)
    boxes = _boxes(zones)
    row = BikeshareFeedCache.objects.filter(key=STATE_KEY).first()
    state = row.payload if row is not None and isinstance(row.payload, dict) else {}
    if state.get("digest") == found and state.get("cursor") is None:
        rows = list(
            SavedRoute.objects.filter(closures_checked_at__isnull=True)
            .order_by("pk")
            .only(*LIGHT)[:most]
        )
        changed, closed = _check_rows(rows, boxes, now)
        return f"saved routes: closures unchanged; {len(rows)} new checked, {closed} closed"
    cursor = state.get("cursor") if state.get("digest") == found else 0
    cursor = int(cursor or 0)
    checked = changed = closed = 0
    finished = False
    while checked < most:
        rows = list(
            SavedRoute.objects.filter(pk__gt=cursor)
            .order_by("pk")
            .only(*LIGHT)[: min(BATCH, most - checked)]
        )
        if not rows:
            finished = True
            break
        more_changed, more_closed = _check_rows(rows, boxes, now)
        changed += more_changed
        closed += more_closed
        checked += len(rows)
        cursor = rows[-1].pk
    else:
        finished = not SavedRoute.objects.filter(pk__gt=cursor).exists()
    BikeshareFeedCache.objects.update_or_create(
        key=STATE_KEY,
        defaults={
            "payload": {"digest": found, "cursor": None if finished else cursor},
            "fetched_at": now,
            "failed_at": None,
        },
    )
    left = "pass finished" if finished else f"going on from route {cursor} next run"
    return (
        f"saved routes: {checked} checked, {closed} with a closure on them, {changed} changed;"
        f" {left}"
    )


__all__ = ["alerts_for", "check", "drop", "refresh_all"]
