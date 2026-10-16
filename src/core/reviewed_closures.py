"""Closures a RouteMaker reviewer entered or confirmed (v0.7.0 closures).

The feeds (`core.workzones`, `core.closure_sources`) cover Maryland's and Virginia's work zones and
DC's permits and advisories. What they miss - a trail closed for a bridge repair, a street a rider
found fenced off - a reviewer enters here, or confirms from a rider's report:

- **Who.** A reviewer: an instance admin, or an account holding a reviewer role in a configured
  Discord server (`RoleMapping.Permission.REVIEWER`, read per request by `attach_standing`).
- **Entering.** The road panel's "Mark closed": the road piece or its whole named stretch
  (`stress_edits.named_stretch`), or a drawn line through the API, with a reason, start and end
  dates (the region's days: from the start of the first to the end of the last) and a source
  link. The ways' lines are kept as the segment table has them then (`ReviewedClosure.lines`).
- **Reports.** A rider reports a closure through the existing short Suggest form, its "Closed"
  reason (`signed_out_suggestions.REASONS`): a `StressSuggestion` of kind `closure`, listed here
  for a reviewer (`open_reports`), never with the levels. Confirming makes the closure from the
  report's road piece; rejecting deletes the report.
- **Using.** `zones()` gives each closure not ended as `routemaker.workzones.Zone`s, source
  `reviewer` (credited "Confirmed by a RouteMaker reviewer"), kind closed: the snapshot adds them
  beside the feeds' (`core.workzones._load`), so the planner routes round them and the closure
  check and saved-route alerts name them exactly as a feed's.

Every write is one audit row. A rider's report keeps no account (it comes from the short form);
the reviewer's account is on the row for the admin, never in what a rider reads.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, time, timedelta
from urllib.parse import urlparse

from django.db import connection, transaction
from django.utils import timezone

from routemaker import workzones as rules

from . import accounts, audit, road_names, stress_edits
from .models import AuditLogEntry, ReviewedClosure, StressSuggestion

SOURCE = "reviewer"
REASON_MAX = 500
URL_MAX = 500
# A drawn line: at most this many points and this long (6.2 mi).
LINE_MAX_POINTS = 200
LINE_MAX_M = 10_000.0
# At most this many closures in force at once, so the router's limits are not swamped by entries.
OPEN_MAX = 200
# At most this far ahead a closure may be entered to start or end (about two years).
AHEAD_MAX = timedelta(days=750)


class Forbidden(stress_edits.EditRefused):
    status = 403
    code = "not_reviewer"


class Conflict(stress_edits.EditRefused):
    status = 409
    code = "conflict"


def may_review(user) -> bool:
    """An active instance admin, or an account with a reviewer role in a usable server."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if not getattr(user, "is_active", False):
        return False
    if getattr(user, "is_banned", False) or getattr(user, "is_deleted", False):
        return False
    if getattr(user, "is_instance_admin", False):
        return True
    return bool(getattr(user, "_reviewer_guild_ids", frozenset()))


# --- What a reviewer sends ---------------------------------------------------------------


def _zone_info():
    from routemaker import ridetime

    return ridetime.ZONE


def _day(value, field: str) -> date | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise stress_edits.Invalid("Give the date as YYYY-MM-DD.", field)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise stress_edits.Invalid("Give the date as YYYY-MM-DD.", field) from None


def window(start_day, end_day, now: datetime | None = None) -> tuple[datetime, datetime | None]:
    """The closure's window from its dates in the region's days: from the start of the first
    (today where none is given) to the end of the last (None: until a reviewer ends it)."""
    now = now or timezone.now()
    zone = _zone_info()
    first = _day(start_day, "start") or now.astimezone(zone).date()
    last = _day(end_day, "end")
    start = datetime.combine(first, time(0), zone)
    end = None if last is None else datetime.combine(last + timedelta(days=1), time(0), zone)
    if end is not None and end <= start:
        raise stress_edits.Invalid("The last day is before the first.", "end")
    if end is not None and end <= now:
        raise stress_edits.Invalid("That closure is over already: the last day is past.", "end")
    if start > now + AHEAD_MAX or (end is not None and end > now + AHEAD_MAX):
        raise stress_edits.Invalid("A closure can be entered up to two years ahead.", "start")
    return start, end


def clean_reason(reason) -> str:
    reason = " ".join(str(reason or "").split())
    if not reason:
        raise stress_edits.Invalid("Say why it is closed, in a few words.", "reason")
    if len(reason) > REASON_MAX:
        raise stress_edits.Invalid(f"The reason is at most {REASON_MAX} characters.", "reason")
    return reason


def clean_url(url) -> str:
    url = str(url or "").strip()
    if not url:
        return ""
    parsed = urlparse(url)
    if len(url) > URL_MAX or parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise stress_edits.Invalid("The source link must be a web address (https://...).", "url")
    return url


def _metres(line) -> float:
    lat0 = line[0][1]
    points = [rules._xy(p[0], p[1], lat0) for p in line]
    return sum(math.dist(a, b) for a, b in zip(points, points[1:], strict=False))


def clean_line(line) -> list[list[float]]:
    """A drawn line: 2 to `LINE_MAX_POINTS` points, every one inside the map, at most
    `LINE_MAX_M` long."""
    if not isinstance(line, list) or not 2 <= len(line) <= LINE_MAX_POINTS:
        raise stress_edits.Invalid(
            f"A drawn closure is a line of 2 to {LINE_MAX_POINTS} points.", "line"
        )
    problem = accounts.line_problem(line)
    if problem:
        raise stress_edits.Invalid(problem, "line")
    out = [[float(p[0]), float(p[1])] for p in line]
    if not all(accounts._inside(lon, lat) for lon, lat in out):
        raise stress_edits.Invalid("The line runs outside the area this map covers.", "line")
    if _metres(out) > LINE_MAX_M:
        raise stress_edits.Invalid("A drawn closure is at most 6.2 mi (10 km) long.", "line")
    return out


def way_lines(way_ids: list[int]) -> list[list[list[float]]]:
    """Each way's line from the live segment table, in its pieces' order; NotFound for a way
    the table does not have."""
    schema = stress_edits.live_schema()
    lines = []
    with connection.cursor() as cursor:
        for way_id in way_ids:
            cursor.execute(
                f"SELECT ST_AsGeoJSON(geometry) FROM {schema}.segment "
                "WHERE osm_way_id = %s ORDER BY ordinal",
                [way_id],
            )
            line: list = []
            for (geometry,) in cursor.fetchall():
                coordinates = json.loads(geometry)["coordinates"]
                line.extend(coordinates[1:] if line else coordinates)
            if len(line) < 2:
                raise stress_edits.NotFound("That road is not in the data.")
            lines.append([[round(float(p[0]), 7), round(float(p[1]), 7)] for p in line])
    return lines


def _ways(way_ids) -> list[int]:
    if not isinstance(way_ids, list) or not way_ids:
        raise stress_edits.Invalid("Choose the road that is closed.", "osm_way_ids")
    if len(way_ids) > stress_edits.MAX_STRETCH_WAYS:
        raise stress_edits.Invalid(
            f"A closure is at most {stress_edits.MAX_STRETCH_WAYS} road pieces.", "osm_way_ids"
        )
    if not all(isinstance(w, int) and not isinstance(w, bool) and w > 0 for w in way_ids):
        raise stress_edits.Invalid("A road piece is named by its OSM way id.", "osm_way_ids")
    return list(dict.fromkeys(way_ids))


# --- Entering, confirming, ending --------------------------------------------------------


def _forget() -> None:
    from . import workzones

    workzones.forget()


def _check(user) -> None:
    if not may_review(user):
        raise Forbidden("Only a RouteMaker reviewer can enter or confirm a closure.")


def _make(user, way_ids, line, reason, start, end, url, report=None) -> ReviewedClosure:
    reason = clean_reason(reason)
    url = clean_url(url)
    begins, ends = window(start, end)
    if line is not None and way_ids:
        raise stress_edits.Invalid("Send the road pieces or a drawn line, not both.", "line")
    if line is not None:
        ways, lines, road = [], [clean_line(line)], ""
    else:
        ways = _ways(way_ids)
        lines = way_lines(ways)
        road = road_names.name_of(stress_edits.live_schema(), ways[0])[:200]
    now = timezone.now()
    with transaction.atomic():
        live = ReviewedClosure.objects.select_for_update().filter(ended_at__isnull=True)
        if live.exclude(end__lte=now).count() >= OPEN_MAX:
            raise Conflict(f"{OPEN_MAX} closures are in force already. End one first.")
        return ReviewedClosure.objects.create(
            created_by=user,
            osm_way_ids=ways,
            lines=lines,
            road=road,
            reason=reason,
            start=begins,
            end=ends,
            source_url=url,
            report=report,
        )


def create(
    user, way_ids=None, reason="", start=None, end=None, url="", line=None
) -> ReviewedClosure:
    """A closure a reviewer enters. Raises EditRefused."""
    _check(user)
    closure = _make(user, way_ids, line, reason, start, end, url)
    audit.record(
        user, "closure_enter", "reviewed_closure", closure.pk, AuditLogEntry.Outcome.ALLOWED
    )
    _forget()
    return closure


def _open_report(report_id: int) -> StressSuggestion:
    report = (
        StressSuggestion.objects.select_for_update()
        .filter(pk=report_id, kind=StressSuggestion.Kind.CLOSURE)
        .first()
    )
    if report is None:
        raise stress_edits.NotFound("That closure report is not there.")
    if report.status not in (StressSuggestion.Status.PENDING, StressSuggestion.Status.SENT):
        raise Conflict(f"That report was {report.get_status_display().lower()} already.")
    return report


def confirm_report(
    user, report_id: int, reason="", start=None, end=None, url=""
) -> ReviewedClosure:
    """Confirm a rider's report: the closure on its road piece, and the report approved."""
    _check(user)
    with transaction.atomic():
        report = _open_report(report_id)
        closure = _make(
            user, [report.osm_way_id], None, reason or report.reason, start, end, url, report
        )
        report.status = StressSuggestion.Status.APPROVED
        report.decided_at = timezone.now()
        report.decided_by = user
        report.save(update_fields=["status", "decided_at", "decided_by"])
    audit.record(
        user, "closure_confirm", "reviewed_closure", closure.pk, AuditLogEntry.Outcome.ALLOWED,
        detail=f"report {report.pk}",
    )  # fmt: skip
    _forget()
    return closure


def reject_report(user, report_id: int) -> StressSuggestion:
    _check(user)
    with transaction.atomic():
        report = _open_report(report_id)
        report.status = StressSuggestion.Status.DELETED
        report.decided_at = timezone.now()
        report.decided_by = user
        report.save(update_fields=["status", "decided_at", "decided_by"])
    audit.record(
        user, "closure_reject", "stress_suggestion", report.pk, AuditLogEntry.Outcome.ALLOWED
    )
    return report


def end_now(user, closure_id: int) -> ReviewedClosure:
    """End a closure at once: it leaves routing within a minute (the snapshot's read)."""
    _check(user)
    with transaction.atomic():
        closure = ReviewedClosure.objects.select_for_update().filter(pk=closure_id).first()
        if closure is None:
            raise stress_edits.NotFound("That closure is not there.")
        if closure.ended_at is not None:
            raise Conflict("That closure was ended already.")
        closure.ended_at = timezone.now()
        closure.ended_by = user
        closure.save(update_fields=["ended_at", "ended_by"])
    audit.record(user, "closure_end", "reviewed_closure", closure.pk, AuditLogEntry.Outcome.ALLOWED)
    _forget()
    return closure


# --- What the planner and the reviewer read -----------------------------------------------


def live_rows(now: datetime | None = None):
    """The closures not ended and not past, in force now or later."""
    from django.db.models import Q

    now = now or timezone.now()
    return ReviewedClosure.objects.filter(ended_at__isnull=True).filter(
        Q(end__isnull=True) | Q(end__gt=now)
    )


def zones_of(closure: ReviewedClosure) -> list[rules.Zone]:
    road = closure.road or None
    title = f"{road}: closed" if road else "Closed"
    out = []
    for index, line in enumerate(closure.lines or []):
        if not isinstance(line, list) or len(line) < 2:
            continue
        out.append(
            rules.Zone(
                zone_id=f"{SOURCE}-{closure.pk}-{index}",
                source=SOURCE,
                kind=rules.CLOSED,
                penalty_s=0.0,
                line=tuple((float(p[0]), float(p[1])) for p in line),
                road=road,
                description=closure.reason,
                start=closure.start,
                end=closure.end,
                reason=closure.reason,
                title=title,
                url=closure.source_url or None,
                published=closure.created_at,
            )
        )
    return out


def zones(now: datetime | None = None) -> list[rules.Zone]:
    return [zone for row in live_rows(now).order_by("pk") for zone in zones_of(row)]


def summary(closure: ReviewedClosure, now: datetime | None = None) -> dict:
    """One closure as the reviewer's list shows it (no account)."""
    now = now or timezone.now()
    shown = zones_of(closure)
    return {
        "id": closure.pk,
        "road": closure.road or "A drawn stretch",
        "osm_way_ids": list(closure.osm_way_ids or []),
        "reason": closure.reason,
        "start": None if closure.start is None else closure.start.isoformat(),
        "end": None if closure.end is None else closure.end.isoformat(),
        "url": closure.source_url or None,
        "when_text": rules.when_text(shown[0], now, False) if shown else "",
        "from_report": closure.report_id is not None,
        "point": None if not shown else list(shown[0].line[len(shown[0].line) // 2]),
    }


def open_reports(limit: int = 100) -> list[StressSuggestion]:
    return list(
        StressSuggestion.objects.filter(
            kind=StressSuggestion.Kind.CLOSURE,
            status__in=(StressSuggestion.Status.PENDING, StressSuggestion.Status.SENT),
        ).order_by("created_at")[:limit]
    )


def report_summary(report: StressSuggestion) -> dict:
    return {
        "id": report.pk,
        "osm_way_id": report.osm_way_id,
        "road": report.road_name or "An unnamed road",
        "reason": report.reason,
        "lat": report.lat,
        "lon": report.lon,
        "created_at": report.created_at.isoformat(),
    }


__all__ = [
    "SOURCE",
    "confirm_report",
    "create",
    "end_now",
    "may_review",
    "open_reports",
    "reject_report",
    "zones",
]
