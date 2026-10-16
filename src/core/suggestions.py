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

Before the decision, a second reviewer (`reviewed_closures.may_review`: an instance admin for now)
may mark a waiting suggestion agree or disagree, with an optional one-line reason (`review`). It is
advice: the list shows the tallies, and approving still takes Approve now. A rider who suggested
sees their suggestion's status in the road panel (`mine`), never the reviewers' tallies or words.

Every action is one `audit_log` entry. The suggester's account is kept on the row for the admin
only; it is never in the post, the tiles or anything a rider reads.
"""

from __future__ import annotations

from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from . import audit, road_names, segment_info, stress_edits, suggestion_post
from .models import AuditLogEntry, StressSuggestion, StressSuggestionReview, SuggestionSettings

REASON_MAX = 500
# Suggestions one account may have waiting at once (the hourly count is
# ratelimit.SUGGEST_WRITES).
OPEN_MAX = 20
CATEGORY = "other"
# The spot a suggestion records is the nearest point on the road, never the rider's own; a spot
# farther than this from the road is refused (98 ft).
SNAP_MAX_M = 30.0
# The map link in the poll is the road piece's middle, rounded to this many decimals (about
# 11 m), never the spot the rider clicked.
LINK_DECIMALS = 4


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
    return next(iter(rows.values())), road_names.name_of(schema, way_id)


def cross_streets(way_id: int, name: str) -> tuple[str, str] | None:
    """The names of the roads at the way's two ends, where each end has one of another name
    (the router's names, as the road panel shows them, else the table's)."""
    schema = stress_edits.live_schema()
    names = road_names.Names()
    own = road_names.key(name)
    found: list[str] = []
    for point in road_names.ends(schema, [way_id]).get(way_id, []):
        others = sorted(
            {
                n
                for m in road_names.touching(schema, point)
                if m["way"] != way_id
                and (n := names.name(m["way"], point, m["table_name"]))
                and road_names.key(n) != own
            }
        )
        if not others:
            return None
        found.append(others[0])
    if len(found) == 2 and road_names.key(found[0]) != road_names.key(found[1]):
        return (found[0], found[1])
    return None


def snap(way_id: int, lat: float, lon: float) -> tuple[float, float]:
    """The nearest point on the way to (lat, lon), as (lat, lon); refused beyond SNAP_MAX_M.

    Privacy (the review of step 4): the poll could otherwise publish a spot near the rider's
    home to a metre. Only the road is kept."""
    schema = stress_edits.live_schema()
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            WITH way AS (SELECT ST_Collect(geometry) AS g FROM {schema}.segment
                         WHERE osm_way_id = %s),
                 spot AS (SELECT ST_SetSRID(ST_MakePoint(%s, %s), 4326) AS p),
                 near AS (SELECT ST_ClosestPoint(way.g, spot.p) AS c, spot.p FROM way, spot
                          WHERE way.g IS NOT NULL)
            SELECT ST_Y(c), ST_X(c), ST_Distance(c::geography, p::geography) FROM near
            """,
            [way_id, float(lon), float(lat)],
        )
        row = cursor.fetchone()
    if row is None:
        raise stress_edits.NotFound("That road is not in the data.")
    if float(row[2]) > SNAP_MAX_M:
        raise stress_edits.Invalid(
            "That spot is more than 98 ft (30 m) from this road. "
            "Open the panel on the road itself.",
            "lat",
            "off_the_road",
        )
    return round(float(row[0]), 6), round(float(row[1]), 6)


def midpoint(way_id: int) -> tuple[float, float] | None:
    """The middle of the road piece, as (lat, lon): where the poll's map link points."""
    schema = stress_edits.live_schema()
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            WITH way AS (SELECT ST_LineMerge(ST_Collect(geometry ORDER BY ordinal)) AS g
                         FROM {schema}.segment WHERE osm_way_id = %s)
            SELECT ST_Y(m), ST_X(m) FROM (
                SELECT CASE WHEN GeometryType(g) = 'LINESTRING'
                            THEN ST_LineInterpolatePoint(g, 0.5)
                            ELSE ST_ClosestPoint(g, ST_Centroid(g)) END AS m
                FROM way WHERE g IS NOT NULL) t
            """,
            [way_id],
        )
        row = cursor.fetchone()
    return (float(row[0]), float(row[1])) if row else None


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
    if half and stress_edits.HALF_COLUMN not in row:
        raise stress_edits.Invalid(
            "Half steps arrive with the next data update. Choose a whole step for now.",
            "step",
            "half_unavailable",
        )
    lat, lon = snap(way_id, lat, lon)
    now_step = stress_edits.current_step(row)
    if float(now_step) == tier + (0.5 if half else 0.0):
        raise stress_edits.Invalid("That is the road's level already.", "step")
    try:
        suggestion = _record(user, way_id, lat, lon, name, row, tier, half, reason)
    except IntegrityError as error:
        # The open-suggestion constraint: two sends at once for one road.
        raise Conflict(
            "You have a suggestion for this road waiting already. An admin will look at it."
        ) from error
    audit.record(
        user, "stress_suggest", "stress_suggestion", suggestion.pk, AuditLogEntry.Outcome.ALLOWED
    )
    return suggestion


def _record(user, way_id, lat, lon, name, row, tier, half, reason) -> StressSuggestion:
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
    return suggestion


# A reviewer's agree or disagree: its reason is one line, at most this long.
REVIEW_REASON_MAX = 200


def review(reviewer, suggestion_id: int, agree: bool, reason: str = "") -> StressSuggestion:
    """Mark a waiting road suggestion agree or disagree (again: the reviewer's earlier mark is
    replaced). Advice only: nothing is applied. Raises SuggestionRefused / EditRefused."""
    from . import reviewed_closures

    if not reviewed_closures.may_review(reviewer):
        raise Forbidden("Only a RouteMaker reviewer can review a suggestion.")
    reason = " ".join((reason or "").split())
    if len(reason) > REVIEW_REASON_MAX:
        raise stress_edits.Invalid(
            f"The reason is one line of at most {REVIEW_REASON_MAX} characters.", "reason"
        )
    with transaction.atomic():
        suggestion = _open(suggestion_id)
        if suggestion.suggester_user_id is not None and suggestion.suggester_user_id == reviewer.pk:
            raise Forbidden("You sent this suggestion: another reviewer weighs it.")
        StressSuggestionReview.objects.update_or_create(
            suggestion=suggestion,
            reviewer_user_id=reviewer.pk,
            defaults={
                "reviewer": reviewer,
                "agree": bool(agree),
                "reason": reason,
                "updated_at": timezone.now(),
            },
        )
    audit.record(
        reviewer, "stress_suggest_review", "stress_suggestion", suggestion.pk,
        AuditLogEntry.Outcome.ALLOWED, detail="agree" if agree else "disagree",
    )  # fmt: skip
    return suggestion


def tallies(suggestion: StressSuggestion, viewer=None) -> dict:
    """The reviewers' marks on a suggestion: how many agree and disagree, the viewer's own
    ("agree", "disagree" or None) and the one-line reasons given, oldest first, without names."""
    rows = list(suggestion.reviews.all())
    me = getattr(viewer, "pk", None)
    own = next((r for r in rows if me is not None and r.reviewer_user_id == me), None)
    return {
        "agree": sum(1 for r in rows if r.agree),
        "disagree": sum(1 for r in rows if not r.agree),
        "mine": None if own is None else ("agree" if own.agree else "disagree"),
        "notes": [{"agree": r.agree, "reason": r.reason} for r in rows if r.reason],
    }


def tallies_words(tallies: dict) -> str:
    """The counts in words, as the review list says them (frontend lib/suggestions.ts
    `talliesLine`): "Reviewers: 1 agrees, 0 disagree"."""
    agree, disagree = tallies["agree"], tallies["disagree"]
    return (
        f"Reviewers: {agree} {'agrees' if agree == 1 else 'agree'}, "
        f"{disagree} {'disagrees' if disagree == 1 else 'disagree'}"
    )


# What a rider reads of their own suggestion's status (`mine`).
RIDER_STATUS = {
    StressSuggestion.Status.PENDING: "Waiting for review.",
    StressSuggestion.Status.SENT: "Sent to riders for a poll; waiting for a decision.",
    StressSuggestion.Status.APPROVED: "Approved: the map uses it.",
    StressSuggestion.Status.DELETED: "Reviewed, and not taken up.",
}


def mine(user, way_id: int) -> dict | None:
    """The rider's latest level suggestion for the road, as the road panel says it, or None."""
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    suggestion = (
        StressSuggestion.objects.filter(
            suggester_user_id=user.pk, osm_way_id=int(way_id), kind=StressSuggestion.Kind.ROAD
        )
        .order_by("-created_at", "-pk")
        .first()
    )
    if suggestion is None:
        return None
    return {
        "id": suggestion.pk,
        "osm_way_id": suggestion.osm_way_id,
        "step": suggestion.step,
        "words": segment_info.words_for(suggestion.tier, suggestion.half),
        "status": suggestion.status,
        "status_words": RIDER_STATUS.get(suggestion.status, ""),
        "created_at": suggestion.created_at.isoformat(),
        "decided_at": suggestion.decided_at.isoformat() if suggestion.decided_at else None,
    }


# Open suggestions read before they are grouped and sorted (v0.7.0).
OPEN_READ = 1000


def _direction(suggestion: StressSuggestion) -> int:
    """1 for a suggestion that the road is busier than rated, -1 calmer."""
    return 1 if suggestion.step > suggestion.current_step else -1


def open_suggestions(limit: int = 100) -> list[StressSuggestion]:
    """The suggestions waiting, grouped by road and sorted by how many agree (the same way up
    or down) and the size of the gap (v0.7.0). Each carries `agree`: how many open sends for its
    road agree with it, itself included. A road's signed-out sends show once
    `settings.SUGGEST_SIGNED_OUT_MIN_AGREE` of them agree (1: every one)."""
    from django.conf import settings

    # A rider's closure report is reviewed with the closures (core.reviewed_closures), not here.
    rows = list(
        StressSuggestion.objects.filter(
            status__in=(StressSuggestion.Status.PENDING, StressSuggestion.Status.SENT)
        )
        .exclude(kind=StressSuggestion.Kind.CLOSURE)
        .prefetch_related("reviews")
        .order_by("created_at")[:OPEN_READ]
    )
    by_road: dict[int, list[StressSuggestion]] = {}
    for row in rows:
        by_road.setdefault(row.osm_way_id, []).append(row)
    minimum = getattr(settings, "SUGGEST_SIGNED_OUT_MIN_AGREE", 1)
    groups = []
    for road in by_road.values():
        for row in road:
            row.agree = sum(1 for other in road if _direction(other) == _direction(row))
        signed_out_agree = max(
            (
                sum(1 for o in road if o.signed_out and _direction(o) == _direction(r))
                for r in road
                if r.signed_out
            ),
            default=0,
        )
        if signed_out_agree < minimum:
            road = [r for r in road if not r.signed_out]
        if not road:
            continue
        road.sort(key=lambda r: (-r.agree, -abs(r.step - r.current_step), r.created_at))
        groups.append(road)
    groups.sort(key=lambda g: (-g[0].agree, -abs(g[0].step - g[0].current_step), g[0].created_at))
    return [row for group in groups for row in group][:limit]


def _open(suggestion_id: int, *, lock: bool = True, level: bool = True) -> StressSuggestion:
    """An open suggestion; `level`: one of a level, not a closure report (which is confirmed or
    rejected with the closures, core.reviewed_closures)."""
    rows = StressSuggestion.objects.all()
    if lock:
        rows = rows.select_for_update()
    suggestion = rows.filter(pk=suggestion_id).first()
    if suggestion is None:
        raise stress_edits.NotFound("That suggestion is not there.")
    if suggestion.status not in (StressSuggestion.Status.PENDING, StressSuggestion.Status.SENT):
        raise Conflict(f"That suggestion was {suggestion.get_status_display().lower()} already.")
    if level and suggestion.kind == StressSuggestion.Kind.CLOSURE:
        raise Conflict("That is a closure report: confirm or reject it under Closures.")
    return suggestion


def approve(admin, suggestion_id: int) -> tuple[StressSuggestion, stress_edits.EditResult]:
    """Apply the suggested level now, as the admin's own edit."""
    with transaction.atomic():
        suggestion = _open(suggestion_id)
        way = suggestion.osm_way_id
        schema = stress_edits.live_schema()
        columns = stress_edits.edit_columns(schema)
        expected = stress_edits.token_of(stress_edits.read_rows(schema, columns, [way]), [way])
        private = f"Rider suggestion {suggestion.pk}, approved: {suggestion.reason}"
        spec = stress_edits.Spec(
            tier=suggestion.tier,
            half=suggestion.half,
            at_least=False,
            category=CATEGORY,
            reason=private[: stress_edits.REASON_MAX],
        )
        result = stress_edits.apply(admin, [way], spec, expected)
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
        suggestion = _open(suggestion_id, level=False)
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
    """The road on RouteMaker's map (`#at=lon,lat`, read by the front end's planHash): the road
    piece's middle, rounded to LINK_DECIMALS, never the spot the rider clicked."""
    middle = midpoint(suggestion.osm_way_id) or (suggestion.lat, suggestion.lon)
    d = LINK_DECIMALS
    return f"{origin.rstrip('/')}/#at={middle[1]:.{d}f},{middle[0]:.{d}f}"


def post_for(suggestion: StressSuggestion, origin: str) -> suggestion_post.Post:
    return suggestion_post.build(
        kind="road",
        road=suggestion.road_name or None,
        between=cross_streets(suggestion.osm_way_id, suggestion.road_name),
        current=suggestion.current_step,
        suggested=suggestion.step,
        reason=suggestion.reason,
        map_url=map_url(origin, suggestion),
    )


def send_to_discord(
    admin, suggestion_id: int, origin: str
) -> tuple[StressSuggestion, suggestion_post.Post]:
    """The poll to paste, and the suggestion marked as sent (again, for a second copy).

    The post is built before the row is locked: it asks the router for names."""
    post = post_for(_open(suggestion_id, lock=False), origin)
    with transaction.atomic():
        suggestion = _open(suggestion_id)
        suggestion.status = StressSuggestion.Status.SENT
        suggestion.sent_at = timezone.now()
        suggestion.save(update_fields=["status", "sent_at"])
    audit.record(
        admin, "stress_suggest_discord", "stress_suggestion", suggestion.pk,
        AuditLogEntry.Outcome.ALLOWED,
    )  # fmt: skip
    return suggestion, post


def summary(suggestion: StressSuggestion, viewer=None) -> dict:
    """One suggestion as the admin's review list shows it (no account details); `reviews` are
    the reviewers' tallies, with `viewer`'s own mark."""
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
        # v0.7.0: sent from the short form by someone not signed in, its one-tap reasons, and how
        # many open sends for the road agree with it (itself included).
        "signed_out": suggestion.signed_out,
        "reasons": list(suggestion.reasons or []),
        "agree": getattr(suggestion, "agree", 1),
        "reviews": tallies(suggestion, viewer),
        "status": suggestion.status,
        "created_at": suggestion.created_at.isoformat(),
        "sent_at": suggestion.sent_at.isoformat() if suggestion.sent_at else None,
    }
