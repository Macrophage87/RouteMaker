"""Closures on a rider's saved routes (v0.7.0 closures, "saved-route alerts").

A saved route keeps its line verbatim, so a closure that comes in after it was saved is not routed
round. When a closure in force now - a feed's (`core.workzones`, `core.closure_sources`) or one a
reviewer confirmed (`core.reviewed_closures`) - runs along a signed-in rider's saved route, the
rider sees it the next time they open My routes: "Closed on your route: Oak Street, until Oct 20,
2026." Opening the route itself runs the closure check (`workzones.closures_on`, POST
/api/closures/check) as before. No e-mail and no push.

The worker's `check_saved_route_closures` task (config.procrastinate, every fifteen minutes,
after the feeds' refreshes) checks every saved route against the snapshot (`refresh_all`) and
writes each one's alerts to `SavedRoute.closure_alerts` where they changed; a route just saved is
checked when it is saved (`check`). An ended closure leaves at the next check.
"""

from __future__ import annotations

import logging
from datetime import datetime

from django.utils import timezone

logger = logging.getLogger(__name__)

# Saved routes read a batch at a time.
BATCH = 200
# At most this many alerts are kept for one route, in line order.
MOST = 5


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
        out.append(
            {
                "id": row["id"],
                "title": row["title"],
                "road": row["road"],
                "end": row["end"],
                "source": row["source_name"],
                "text": f"Closed on your route: {where}, {_until(row['end'])}.",
            }
        )
    return out


def _until(end: str | None) -> str:
    from routemaker import ridetime

    if not end:
        return "no end date given"
    local = datetime.fromisoformat(end).astimezone(ridetime.ZONE)
    return f"until {local.strftime('%b')} {local.day}, {local.year}"


def check(route, now: datetime | None = None) -> None:
    """Check one saved route now and keep its alerts. A failure keeps what it had."""
    now = now or timezone.now()
    try:
        alerts = alerts_for(route.line, now)
    except Exception:  # noqa: BLE001 - a route is saved whether or not the check ran
        logger.warning("saved-route closures: a route could not be checked", exc_info=True)
        return
    route.closure_alerts = alerts
    route.closures_checked_at = now
    route.save(update_fields=["closure_alerts", "closures_checked_at"])


def refresh_all(now: datetime | None = None) -> str:
    """Check every saved route against the closures in force now. Returns a line for the run
    row: how many routes were checked and how many have a closure on them."""
    from . import workzones
    from .models import SavedRoute

    now = now or timezone.now()
    workzones.forget()  # this check reads the closures as they are now, not a minute ago
    checked = changed = closed = 0
    last = 0
    while True:
        rows = list(
            SavedRoute.objects.filter(pk__gt=last)
            .order_by("pk")
            .only("pk", "line", "closure_alerts")[:BATCH]
        )
        if not rows:
            break
        for row in rows:
            last = row.pk
            alerts = alerts_for(row.line, now)
            checked += 1
            closed += bool(alerts)
            if alerts != (row.closure_alerts or []):
                changed += 1
                SavedRoute.objects.filter(pk=row.pk).update(
                    closure_alerts=alerts, closures_checked_at=now
                )
    return f"saved routes: {checked} checked, {closed} with a closure on them, {changed} changed"


__all__ = ["alerts_for", "check", "refresh_all"]
