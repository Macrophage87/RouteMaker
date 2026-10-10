"""Rider suggestions for a road's traffic stress (441h, 460.4, 460.5; HALF-STEP-EDITOR phase 4).

A signed-in rider the settings allow (`SuggestionSettings`: nobody by default) suggests a level
for the road piece they clicked, with a reason. Nothing changes on the map: the suggestion waits
for an instance admin, who has three actions (the owner, 2026-10-10 13:57 UTC: "I know that that
road probably should be rescheduled, so I'll make it happen immediately; that request seems
absurd, so I delete it; or I don't know enough about the road or the area, so I'll let the
community decide."):

- approve now: applied at once as the admin's own edit (`stress_edits.apply`, the editor's path);
- delete;
- send to Discord: the answer is a ready-to-paste poll (`core.suggestion_post`), and the
  suggestion records that it was sent. The admin approves or deletes it later. There is no
  in-app voting ("I meant discord itself").

Every action is one `audit_log` entry. The suggester's account is kept on the row for the admin
only; it is never in the post, the tiles or anything a rider reads.
"""

from __future__ import annotations

from django.db import connection, transaction
from django.utils import timezone

from . import audit, segment_info, stress_edits, suggestion_post
from .models import AuditLogEntry, StressSuggestion, SuggestionSettings

REASON_MAX = 500
# Suggestions one account may have waiting at once, and a day.
OPEN_MAX = 20
# A road's cross streets: the names of other roads within this many metres of its ends.
CROSS_STREET_M = 2.0
CATEGORY = "other"


class SuggestionRefused(stress_edits.EditRefused):
    pass


class Forbidden(SuggestionRefused):
    status = 403
    code = "not_allowed"


class Conflict(SuggestionRefused):
    status = 409
    code = "conflict"


def may_suggest(user) -> bool:
    """Whether this account may suggest: by the setting, never an instance admin (who edits)."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if not getattr(user, "is_active", False) or getattr(user, "is_instance_admin", False):
        return False
    if getattr(user, "is_banned", False) or getattr(user, "is_deleted", False):
        return False
    who = SuggestionSettings.current().who
    if who == SuggestionSettings.Who.SIGNED_IN:
        return True
    if who == SuggestionSettings.Who.MEMBERS:
        return bool(getattr(user, "_member_guild_ids", frozenset()))
    return False


def _road(way_id: int) -> tuple[dict, str]:
    """The way's first row (the edit columns) and its name, or NotFound."""
    schema = stress_edits.live_schema()
    columns = stress_edits.edit_columns(schema)
    if stress_edits.live_oid(schema) is None or not columns:
        raise stress_edits.NotFound("There is no road data yet.")
    rows = stress_edits.read_rows(schema, columns, [way_id])
    if not rows:
        raise stress_edits.NotFound("That road is not in the data.")
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT trail_name FROM {schema}.segment WHERE osm_way_id = %s "
            "ORDER BY ordinal LIMIT 1",
            [way_id],
        )
        row = cursor.fetchone()
    return next(iter(rows.values())), (row[0] or "") if row else ""


def cross_streets(way_id: int, name: str) -> tuple[str, str] | None:
    """The names of the roads at the way's two ends, where each end has one of another name."""
    schema = stress_edits.live_schema()
    sql = f"""
        WITH way AS (
            SELECT ST_LineMerge(ST_Union(geometry ORDER BY ordinal)) AS g
            FROM {schema}.segment WHERE osm_way_id = %s
        ), ends AS (
            SELECT 1 AS n, ST_StartPoint(ST_GeometryN(g, 1)) AS p FROM way
            UNION ALL
            SELECT 2, ST_EndPoint(ST_GeometryN(g, ST_NumGeometries(g))) FROM way
        )
        SELECT e.n, min(s.trail_name)
        FROM ends AS e
        JOIN {schema}.segment AS s
          ON ST_DWithin(s.geometry::geography, e.p::geography, %s)
        WHERE s.osm_way_id <> %s AND s.map_class = 'road' AND s.trail_name IS NOT NULL
          AND lower(s.trail_name) <> lower(%s)
        GROUP BY e.n
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [way_id, CROSS_STREET_M, way_id, name or ""])
        found = dict(cursor.fetchall())
    if found.get(1) and found.get(2) and found[1] != found[2]:
        return (found[1], found[2])
    return None


def create(user, way_id: int, lat: float, lon: float, step, reason: str) -> StressSuggestion:
    """Record a rider's suggestion. Raises SuggestionRefused / EditRefused."""
    if not may_suggest(user):
        raise Forbidden("Suggestions are not open to your account.")
    tier, half = stress_edits.split_step(step)
    reason = (reason or "").strip()
    if not reason:
        raise stress_edits.Invalid("Say why, in a sentence or two.", "reason")
    if len(reason) > REASON_MAX:
        raise stress_edits.Invalid(f"The reason is at most {REASON_MAX} characters.", "reason")
    row, name = _road(way_id)
    now_step = stress_edits.current_step(row)
    if float(now_step) == tier + (0.5 if half else 0.0):
        raise stress_edits.Invalid("That is the road's level already.", "step")
    with transaction.atomic():
        mine = StressSuggestion.objects.select_for_update().filter(
            suggester=user,
            status__in=(StressSuggestion.Status.PENDING, StressSuggestion.Status.SENT),
        )
        if mine.filter(osm_way_id=way_id).exists():
            raise Conflict(
                "You have a suggestion for this road waiting already. An admin will look at it."
            )
        if mine.count() >= OPEN_MAX:
            raise Conflict(
                f"You have {OPEN_MAX} suggestions waiting. Wait for an admin to look at them."
            )
        suggestion = StressSuggestion.objects.create(
            suggester=user,
            suggester_user_id=user.pk,
            osm_way_id=way_id,
            lat=float(lat),
            lon=float(lon),
            road_name=name,
            current_tier=int(row[stress_edits.TIER_COLUMN]),
            current_half=row.get(stress_edits.HALF_COLUMN) is True,
            tier=tier,
            half=half,
            reason=reason,
        )
    audit.record(
        user, "stress_suggest", "stress_suggestion", suggestion.pk, AuditLogEntry.Outcome.ALLOWED
    )
    return suggestion


def open_suggestions(limit: int = 100) -> list[StressSuggestion]:
    return list(
        StressSuggestion.objects.filter(
            status__in=(StressSuggestion.Status.PENDING, StressSuggestion.Status.SENT)
        ).order_by("created_at")[:limit]
    )


def _open(suggestion_id: int, *, lock: bool = True) -> StressSuggestion:
    rows = StressSuggestion.objects.all()
    if lock:
        rows = rows.select_for_update()
    suggestion = rows.filter(pk=suggestion_id).first()
    if suggestion is None:
        raise stress_edits.NotFound("That suggestion is not there.")
    if suggestion.status not in (StressSuggestion.Status.PENDING, StressSuggestion.Status.SENT):
        raise Conflict(f"That suggestion was {suggestion.get_status_display().lower()} already.")
    return suggestion


def approve(admin, suggestion_id: int) -> tuple[StressSuggestion, stress_edits.EditResult]:
    """Apply the suggested level now, as the admin's own edit."""
    with transaction.atomic():
        suggestion = _open(suggestion_id)
        state = stress_edits.editor_state(admin, suggestion.osm_way_id)
        private = f"Rider suggestion {suggestion.pk}, approved: {suggestion.reason}"
        spec = stress_edits.Spec(
            tier=suggestion.tier,
            half=suggestion.half,
            at_least=False,
            category=CATEGORY,
            reason=private[: stress_edits.REASON_MAX],
        )
        result = stress_edits.apply(admin, [suggestion.osm_way_id], spec, state["expected"])
        suggestion.status = StressSuggestion.Status.APPROVED
        suggestion.decided_at = timezone.now()
        suggestion.decided_by = admin
        suggestion.edit = result.edit
        suggestion.save(update_fields=["status", "decided_at", "decided_by", "edit"])
    audit.record(
        admin, "stress_suggest_approve", "stress_suggestion", suggestion.pk,
        AuditLogEntry.Outcome.ALLOWED, detail=f"edit {result.edit.pk}",
    )  # fmt: skip
    return suggestion, result


def delete(admin, suggestion_id: int) -> StressSuggestion:
    with transaction.atomic():
        suggestion = _open(suggestion_id)
        suggestion.status = StressSuggestion.Status.DELETED
        suggestion.decided_at = timezone.now()
        suggestion.decided_by = admin
        suggestion.save(update_fields=["status", "decided_at", "decided_by"])
    audit.record(
        admin, "stress_suggest_delete", "stress_suggestion", suggestion.pk,
        AuditLogEntry.Outcome.ALLOWED,
    )  # fmt: skip
    return suggestion


def map_url(origin: str, suggestion: StressSuggestion) -> str:
    """The spot on RouteMaker's map (`#at=lon,lat`, read by the front end's planHash)."""
    return f"{origin.rstrip('/')}/#at={suggestion.lon:.5f},{suggestion.lat:.5f}"


def post_for(suggestion: StressSuggestion, origin: str) -> suggestion_post.Post:
    return suggestion_post.build(
        kind="road",
        road=suggestion.road_name or None,
        between=cross_streets(suggestion.osm_way_id, suggestion.road_name),
        lat=suggestion.lat,
        lon=suggestion.lon,
        current=suggestion.current_step,
        suggested=suggestion.step,
        reason=suggestion.reason,
        map_url=map_url(origin, suggestion),
    )


def send_to_discord(
    admin, suggestion_id: int, origin: str
) -> tuple[StressSuggestion, suggestion_post.Post]:
    """The poll to paste, and the suggestion marked as sent (again, for a second copy)."""
    with transaction.atomic():
        suggestion = _open(suggestion_id)
        post = post_for(suggestion, origin)
        suggestion.status = StressSuggestion.Status.SENT
        suggestion.sent_at = timezone.now()
        suggestion.save(update_fields=["status", "sent_at"])
    audit.record(
        admin, "stress_suggest_discord", "stress_suggestion", suggestion.pk,
        AuditLogEntry.Outcome.ALLOWED,
    )  # fmt: skip
    return suggestion, post


def summary(suggestion: StressSuggestion) -> dict:
    """One suggestion as the admin's review list shows it (no account details)."""
    return {
        "id": suggestion.pk,
        "osm_way_id": suggestion.osm_way_id,
        "road": suggestion.road_name or "An unnamed road",
        "lat": suggestion.lat,
        "lon": suggestion.lon,
        "current_step": suggestion.current_step,
        "current_words": segment_info.words_for(suggestion.current_tier, suggestion.current_half),
        "step": suggestion.step,
        "words": segment_info.words_for(suggestion.tier, suggestion.half),
        "reason": suggestion.reason,
        "status": suggestion.status,
        "created_at": suggestion.created_at.isoformat(),
        "sent_at": suggestion.sent_at.isoformat() if suggestion.sent_at else None,
    }
