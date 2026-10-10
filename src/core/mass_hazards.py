"""Rider-marked hazards on the Mass Ride map (FOLLOWUP-MASSRIDE-MAP part 3; OWNER-DECISIONS
325, 326, 327).

"Some stretches can be marked as a caution or warning where we've had problems. They go along
side like a trail or pbl. If we've marked it avoid, It should be just marked avoid with no
carrying capacity. These hazards will be marked by riders and will be for this mode only."
(325). Two levels, Caution and Warning, chosen by the reporter with a reason (326: "Severity
only"; both stay routable). Drawn as near-black side rails, Caution dotted and Warning
dash-dot (327), on the Mass Ride map only.

A signed-in rider the suggestion setting allows (`core.suggestions.may_suggest`) marks the road
piece they opened the road panel on. Nothing shows until an instance admin reviews it, with the
rider suggestions' three actions (the owner, 2026-10-10): approve now (on the Mass Ride map at
once), delete, or send to Discord (a ready-to-paste plain-English poll,
`core.suggestion_post.build_hazard`; the report is marked as sent and decided later). The same
hourly count as suggestions (`ratelimit.SUGGEST_WRITES`), one open report per rider per road
piece, at most `OPEN_MAX` open per rider, and every action one `audit_log` entry.

Privacy: stored by OSM way id. The spot the rider clicked is checked against the road (refused
beyond 98 ft (30 m), as suggestions are) and then dropped; the poll's link points at the road
piece's middle. The reporter's account is kept for the admin only.

The approved hazards reach the map as a small GeoJSON layer (`GET /api/mass-hazards`,
`approved_layer`), not in the vector tiles: the list is short and changes at review time, so a
layer of its own keeps the tiles' ETags and caches untouched (docs/OPERATIONS.md, "Mass Ride
hazards"). A piece of road marked Avoid is left out of it: there the map shows only Avoid (325).
"""

from __future__ import annotations

import hashlib
import json
import logging

from django.db import DatabaseError, IntegrityError, connection, transaction
from django.utils import timezone

from . import audit, stress_edits, suggestion_post, suggestions
from .models import AuditLogEntry, MassHazard

logger = logging.getLogger(__name__)

REASON_MAX = suggestions.REASON_MAX
OPEN_MAX = suggestions.OPEN_MAX
LEVELS = tuple(MassHazard.Level.values)
# The words a rider reads for each level (the legend, the road panel and the description say
# the same; frontend/src/lib/massHazards.ts HAZARD_LEVELS).
LEVEL_WORDS = {
    "caution": "Caution: riders have had problems here; take care",
    "warning": "Warning: riders have had serious problems here",
}
_OPEN = (MassHazard.Status.PENDING, MassHazard.Status.SENT)


class Conflict(suggestions.Conflict):
    pass


def create(user, way_id: int, lat: float, lon: float, level: str, reason: str) -> MassHazard:
    """Record a rider's hazard report. Raises EditRefused (and its subclasses)."""
    if not suggestions.may_suggest(user):
        raise suggestions.Forbidden("Hazard reports are not open to your account.")
    if level not in LEVELS:
        raise stress_edits.Invalid("Choose Caution or Warning.", "level")
    reason = (reason or "").strip()
    if not reason:
        raise stress_edits.Invalid("Say what happened here, in a sentence or two.", "reason")
    if len(reason) > REASON_MAX:
        raise stress_edits.Invalid(f"The reason is at most {REASON_MAX} characters.", "reason")
    row, name = suggestions._road(way_id)
    if int(row[stress_edits.TIER_COLUMN]) == 5:
        raise stress_edits.Invalid(
            "This road is marked Avoid already, so the Mass Ride map shows only Avoid here.",
            "level",
            "avoid",
        )
    # Checked, then dropped: only the road is kept.
    suggestions.snap(way_id, lat, lon)
    if MassHazard.objects.filter(
        osm_way_id=way_id, status=MassHazard.Status.APPROVED, level=level
    ).exists():
        raise stress_edits.Invalid(
            f"This road piece is marked {MassHazard.Level(level).label} already.",
            "level",
            "same",
        )
    try:
        hazard = _record(user, way_id, name, level, reason)
    except IntegrityError as error:
        raise Conflict(
            "You have a hazard report for this road waiting already. An admin will look at it."
        ) from error
    audit.record(
        user, "mass_hazard_report", "mass_hazard", hazard.pk, AuditLogEntry.Outcome.ALLOWED
    )
    return hazard


def _record(user, way_id, name, level, reason) -> MassHazard:
    with transaction.atomic():
        mine = MassHazard.objects.select_for_update().filter(reporter=user, status__in=_OPEN)
        if mine.filter(osm_way_id=way_id).exists():
            raise Conflict(
                "You have a hazard report for this road waiting already. An admin will look at it."
            )
        if mine.count() >= OPEN_MAX:
            raise Conflict(
                f"You have {OPEN_MAX} hazard reports waiting. Wait for an admin to look at them."
            )
        return MassHazard.objects.create(
            reporter=user,
            reporter_user_id=user.pk,
            osm_way_id=way_id,
            road_name=name,
            level=level,
            reason=reason,
        )


def open_reports(limit: int = 100) -> list[MassHazard]:
    return list(MassHazard.objects.filter(status__in=_OPEN).order_by("created_at")[:limit])


def _open(hazard_id: int, *, lock: bool = True) -> MassHazard:
    rows = MassHazard.objects.all()
    if lock:
        rows = rows.select_for_update()
    hazard = rows.filter(pk=hazard_id).first()
    if hazard is None:
        raise stress_edits.NotFound("That hazard report is not there.")
    if hazard.status not in _OPEN:
        raise Conflict(f"That hazard report was {hazard.get_status_display().lower()} already.")
    return hazard


def _decide(admin, hazard: MassHazard, status: str) -> None:
    hazard.status = status
    hazard.decided_at = timezone.now()
    hazard.decided_by = admin
    hazard.save(update_fields=["status", "decided_at", "decided_by"])


def approve(admin, hazard_id: int) -> MassHazard:
    """On the Mass Ride map now. An earlier approved hazard on the same way is taken off it:
    a road piece has one level at a time."""
    with transaction.atomic():
        hazard = _open(hazard_id)
        replaced = list(
            MassHazard.objects.select_for_update()
            .filter(osm_way_id=hazard.osm_way_id, status=MassHazard.Status.APPROVED)
            .values_list("pk", flat=True)
        )
        MassHazard.objects.filter(pk__in=replaced).update(
            status=MassHazard.Status.REMOVED, decided_at=timezone.now(), decided_by=admin
        )
        _decide(admin, hazard, MassHazard.Status.APPROVED)
    detail = f"replaced {', '.join(map(str, replaced))}" if replaced else ""
    audit.record(
        admin, "mass_hazard_approve", "mass_hazard", hazard.pk,
        AuditLogEntry.Outcome.ALLOWED, detail=detail,
    )  # fmt: skip
    return hazard


def delete(admin, hazard_id: int) -> MassHazard:
    with transaction.atomic():
        hazard = _open(hazard_id)
        _decide(admin, hazard, MassHazard.Status.DELETED)
    audit.record(
        admin, "mass_hazard_delete", "mass_hazard", hazard.pk, AuditLogEntry.Outcome.ALLOWED
    )
    return hazard


def remove(admin, hazard_id: int) -> MassHazard:
    """Take an approved hazard off the map (the Django admin's action)."""
    with transaction.atomic():
        hazard = MassHazard.objects.select_for_update().filter(pk=hazard_id).first()
        if hazard is None:
            raise stress_edits.NotFound("That hazard is not there.")
        if hazard.status != MassHazard.Status.APPROVED:
            raise Conflict("Only a hazard on the map can be taken off it.")
        _decide(admin, hazard, MassHazard.Status.REMOVED)
    audit.record(
        admin, "mass_hazard_remove", "mass_hazard", hazard.pk, AuditLogEntry.Outcome.ALLOWED
    )
    return hazard


def map_url(origin: str, hazard: MassHazard) -> str:
    """The road on RouteMaker's map: the road piece's middle, to LINK_DECIMALS, never a spot a
    rider clicked (none is kept)."""
    middle = suggestions.midpoint(hazard.osm_way_id)
    if middle is None:
        return f"{origin.rstrip('/')}/"
    d = suggestions.LINK_DECIMALS
    return f"{origin.rstrip('/')}/#at={middle[1]:.{d}f},{middle[0]:.{d}f}"


def post_for(hazard: MassHazard, origin: str) -> suggestion_post.Post:
    return suggestion_post.build_hazard(
        road=hazard.road_name or None,
        between=suggestions.cross_streets(hazard.osm_way_id, hazard.road_name),
        level=hazard.level,
        reason=hazard.reason,
        map_url=map_url(origin, hazard),
    )


def send_to_discord(admin, hazard_id: int, origin: str) -> tuple[MassHazard, suggestion_post.Post]:
    """The poll to paste, and the report marked as sent. Built before the row is locked: it
    asks the router for names."""
    post = post_for(_open(hazard_id, lock=False), origin)
    with transaction.atomic():
        hazard = _open(hazard_id)
        hazard.status = MassHazard.Status.SENT
        hazard.sent_at = timezone.now()
        hazard.save(update_fields=["status", "sent_at"])
    audit.record(
        admin, "mass_hazard_discord", "mass_hazard", hazard.pk, AuditLogEntry.Outcome.ALLOWED
    )
    return hazard, post


def summary(hazard: MassHazard) -> dict:
    """One report as the admin's review list shows it (no account details, no position: the
    Show on map link is the road piece's middle)."""
    middle = suggestions.midpoint(hazard.osm_way_id)
    return {
        "id": hazard.pk,
        "osm_way_id": hazard.osm_way_id,
        "road": hazard.road_name or "An unnamed road",
        "lat": round(middle[0], suggestions.LINK_DECIMALS) if middle else None,
        "lon": round(middle[1], suggestions.LINK_DECIMALS) if middle else None,
        "level": hazard.level,
        "level_name": hazard.get_level_display(),
        "words": LEVEL_WORDS[hazard.level],
        "reason": hazard.reason,
        "status": hazard.status,
        "created_at": hazard.created_at.isoformat(),
        "sent_at": hazard.sent_at.isoformat() if hazard.sent_at else None,
    }


def approved() -> dict[int, MassHazard]:
    """The hazards on the map, by way id. Empty when there are none (as shipped) or when the
    table cannot be read: a plan is never refused for want of them."""
    try:
        return {
            h.osm_way_id: h
            for h in MassHazard.objects.filter(status=MassHazard.Status.APPROVED).order_by(
                "decided_at"
            )
        }
    except DatabaseError:
        logger.warning("the Mass Ride hazard list could not be read", exc_info=True)
        return {}


def approved_layer() -> tuple[dict, str]:
    """The approved hazards as a GeoJSON FeatureCollection for the Mass Ride map, and its ETag.

    One feature a way: its pieces not marked Avoid (325: there the map shows only Avoid), with
    the level, its words, the reason and the road's name. Nothing about who reported it."""
    found = approved()
    features: list[dict] = []
    if found:
        schema = stress_edits.live_schema()
        if stress_edits.live_oid(schema) is not None:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT osm_way_id,
                           ST_AsGeoJSON(ST_LineMerge(ST_Collect(geometry ORDER BY ordinal)), 6)
                    FROM {schema}.segment
                    WHERE osm_way_id = ANY(%s) AND stress_tier <> 5
                    GROUP BY osm_way_id ORDER BY osm_way_id
                    """,
                    [list(found)],
                )
                rows = cursor.fetchall()
            for way, geometry in rows:
                hazard = found[int(way)]
                features.append(
                    {
                        "type": "Feature",
                        "id": int(way),
                        "geometry": json.loads(geometry),
                        "properties": {
                            "way": int(way),
                            "level": hazard.level,
                            "level_name": hazard.get_level_display(),
                            "words": LEVEL_WORDS[hazard.level],
                            "reason": hazard.reason,
                            "road": hazard.road_name or "An unnamed road",
                        },
                    }
                )
    body = {"type": "FeatureCollection", "features": features}
    etag = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:32]
    return body, f'"h{etag}"'


def along(leg_runs: list, pieces: list, classes: list, found: dict | None = None) -> list[dict]:
    """The approved hazards a route passes, in riding order: {from_m, to_m, level, level_name,
    words, reason, road}, in metres along the traced route as the stress sections are measured
    (`routing.stress_spans`). A piece marked Avoid carries no hazard (it is said as Avoid), and
    consecutive pieces of one hazard are one entry."""
    found = approved() if found is None else found
    if not found:
        return []
    out: list[dict] = []
    at = 0.0
    last_way = None
    for run in leg_runs:
        if not isinstance(run, tuple):
            at += float(run)
            last_way = None
            continue
        for i in range(run[0], run[1]):
            piece = pieces[i]
            start, at = at, at + piece.metres
            hazard = found.get(getattr(piece, "way_id", None))
            if hazard is None or (classes[i] and classes[i][0] == "5"):
                last_way = None
                continue
            if out and last_way == piece.way_id and round(start) <= out[-1]["to_m"] + 1:
                out[-1]["to_m"] = round(at)
                continue
            last_way = piece.way_id
            out.append(
                {
                    "from_m": round(start),
                    "to_m": round(at),
                    "level": hazard.level,
                    "level_name": hazard.get_level_display(),
                    "words": LEVEL_WORDS[hazard.level],
                    "reason": hazard.reason,
                    "road": hazard.road_name or "An unnamed road",
                }
            )
    return out
