"""Rider suggestions for a junction's danger level (FOLLOWUP-STRESS-SUGGEST, OWNER-DECISIONS 232).

The owner, 2026-10-03: "add a mechanism for intersections as well. In some times the road is
fine, but the intersection can be especially dangerous." The road suggestions' twin
(`core.suggestions`), for a node:

- A rider the settings allow (`suggestions.may_suggest`, the same setting) picks a junction (its
  marker on the route, or the road panel opened on it) and suggests a level in the poll's plain
  words (`suggestion_post.JUNCTION_WORDS`: easy, takes patience, hard, Avoid) and/or "more or
  less dangerous than shown", with a reason of at most 500 characters. A comparison alone means
  one level from the shown one.
- Only the junction is kept: the node where two ways meet nearest the spot, within
  `SNAP_MAX_M` (`locate`), never the spot the rider clicked or stood at.
- The same limits as the roads': one open suggestion per rider per junction (held by the
  database), `suggestions.OPEN_MAX` waiting per rider across roads and junctions, and the same
  hourly count (`ratelimit.SUGGEST_WRITES`, roads and junctions together); the admin's review
  shares the roads' budget (`ratelimit.SUGGEST_REVIEW_WRITES`).
- The instance admin's three actions are the roads': approve now (a `JunctionOverride` the
  intersection model applies at the next plan, `approved_ratings`; Avoid becomes an approved
  `AvoidJunction`), delete, and send to Discord (a ready-to-paste plain-English poll, no LTS,
  the junction's two roads in words and a map link to the node at `LINK_DECIMALS`).

Every action is one `audit_log` entry. The suggester's account is never in the post, the
review list or anything a rider reads.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.utils import timezone

from routemaker.intersections import RATING_MATCH_M, Rating

from . import audit, road_names, stress_edits, suggestion_post, suggestions
from .models import (
    AuditLogEntry,
    AvoidJunction,
    JunctionOverride,
    JunctionSuggestion,
    StressSuggestion,
)

logger = logging.getLogger(__name__)

REASON_MAX = suggestions.REASON_MAX
# The junction kept is the nearest node where two ways meet within this of the spot asked
# about (82 ft): the road panel's own reach for an Avoid junction (frontend AVOID_SPOT_M).
SNAP_MAX_M = 25.0
SNAP_WORDS = "82 ft (25 m)"
# The poll's map link is the node rounded to this many decimals (about 11 m).
LINK_DECIMALS = 4
# The levels, as the poll says them; 2 is also "not marked" (the model sees nothing there).
LEVELS = (2, 3, 4, 5)
LEVEL_WORDS = suggestion_post.JUNCTION_WORDS
AVOID = 5
# What the map showed on the rider's route (its marker), as a level.
SHOWN_LEVELS = {"none": 2, "orange": 3, "red": 4, "avoid": AVOID}
# What an approved Avoid junction says to riders: the rider's own reason stays private.
AVOID_REASON = "Riders rate it too dangerous to cross"
OPEN_STATUSES = (JunctionSuggestion.Status.PENDING, JunctionSuggestion.Status.SENT)


class Forbidden(suggestions.Forbidden):
    pass


class Conflict(suggestions.Conflict):
    pass


@dataclass(frozen=True)
class Node:
    """A junction: where two or more ways meet, and the roads there as riders know them."""

    lon: float
    lat: float
    roads: tuple[str, ...]

    @property
    def key(self) -> str:
        return f"{self.lon:.6f},{self.lat:.6f}"

    @property
    def name(self) -> str:
        return " and ".join(self.roads[:2]) if self.roads else "An unnamed junction"


def _schema() -> str:
    schema = stress_edits.live_schema()
    if stress_edits.live_oid(schema) is None:
        raise stress_edits.NotFound("There is no road data yet.")
    return schema


def locate(lat: float, lon: float) -> Node:
    """The junction nearest (lat, lon): a vertex of a road shared with another way (OSM ways
    meet at a shared node; a bridge over a road shares none), within SNAP_MAX_M. Refused where
    there is none, or where the only two ways there are one road's pieces (a bend, not a
    junction)."""
    schema = _schema()
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            WITH spot AS (SELECT ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326) AS p),
                 near AS (SELECT s.osm_way_id AS w, s.geometry AS g
                          FROM {schema}.segment s, spot
                          WHERE s.map_class = 'road'
                            AND s.geometry && ST_Expand(spot.p, 0.0006)
                            AND ST_DWithin(s.geometry::geography, spot.p::geography, %(snap)s)),
                 pts AS (SELECT w, (ST_DumpPoints(g)).geom AS v FROM near)
            SELECT ST_X(c.v), ST_Y(c.v), ST_Distance(c.v::geography, spot.p::geography) AS d
            FROM pts c, spot
            WHERE ST_DWithin(c.v::geography, spot.p::geography, %(snap)s)
              AND EXISTS (SELECT 1 FROM pts o WHERE o.w <> c.w
                          AND ST_DWithin(o.v::geography, c.v::geography, %(touch)s))
            ORDER BY d LIMIT 1
            """,
            {"lon": float(lon), "lat": float(lat), "snap": SNAP_MAX_M, "touch": road_names.TOUCH_M},
        )
        row = cursor.fetchone()
    if row is None:
        raise stress_edits.Invalid(
            f"There is no junction within {SNAP_WORDS} of that spot. "
            "Open the panel on the junction itself.",
            "lat",
            "no_junction",
        )
    point = (round(float(row[0]), 6), round(float(row[1]), 6))
    ways = road_names.touching(schema, point)
    if len(ways) < 2:
        raise stress_edits.Invalid(
            "The road data does not say which roads meet there. Try another junction.",
            "lat",
            "no_junction",
        )
    names = road_names.Names()
    ways.sort(key=lambda m: (-m["level"], m["way"]))
    found: list[str] = []
    for m in ways:
        name = names.name(m["way"], point, m["table_name"])
        if name and road_names.key(name) not in {road_names.key(n) for n in found}:
            found.append(name)
    # Two ways and no second name: one road's two pieces meeting at a bend, whether both carry
    # the same name or, ending there end to end, neither has one. (A named road meeting an
    # unnamed one, such as a service road, is a junction, and so is an unnamed road ending on
    # another's side.)
    if len(ways) == 2 and len(found) <= 1:
        named = [names.name(m["way"], point, m["table_name"]) for m in ways]
        if all(named) or (not any(named) and _both_end_at(schema, point)):
            road = found[0] if found else "an unnamed road"
            raise stress_edits.Invalid(
                f"That is a bend in {road}, not a junction. Open the panel on a junction.",
                "lat",
                "no_junction",
            )
    return Node(point[0], point[1], tuple(found))


def _both_end_at(schema: str, point: tuple[float, float]) -> bool:
    """Whether every road way at `point` ends there (its piece's first or last vertex), as two
    pieces of one road meeting end to end do; a way that runs on through the point does not."""
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            WITH spot AS (SELECT ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326) AS p)
            SELECT bool_and(ST_DWithin(ST_StartPoint(s.geometry)::geography, spot.p::geography,
                                       %(touch)s)
                            OR ST_DWithin(ST_EndPoint(s.geometry)::geography,
                                          spot.p::geography, %(touch)s))
            FROM {schema}.segment s, spot
            WHERE s.map_class = 'road'
              AND s.geometry && ST_Expand(spot.p, 0.0001)
              AND ST_DWithin(s.geometry::geography, spot.p::geography, %(touch)s)
            """,
            {"lon": point[0], "lat": point[1], "touch": road_names.TOUCH_M},
        )
        row = cursor.fetchone()
    return bool(row and row[0])


def _near(lon: float, lat: float) -> dict:
    return {"location__distance_lte": (Point(lon, lat, srid=4326), D(m=RATING_MATCH_M))}


# The grid the approvals lock by (`_lock_near`), in degrees: two rating matches across, so
# two places within RATING_MATCH_M of each other are in the same or neighbouring cells
# (east-west too, south of 60 degrees north).
LOCK_CELL_DEG = 2 * RATING_MATCH_M / 111_000


def lock_cells(lon: float, lat: float) -> list[tuple[int, int]]:
    """The grid cells around a place, its own and its eight neighbours, in one order."""
    x, y = int(lon // LOCK_CELL_DEG), int(lat // LOCK_CELL_DEG)
    return sorted((x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1))


def _lock_near(lon: float, lat: float) -> None:
    """Hold, to the end of the transaction, the cells around a place: two approvals at
    one junction take turns, so the second sees the first's Avoid junction before it looks
    (review api-3; a row lock cannot hold a row not made yet). Two places within
    RATING_MATCH_M share a cell, and each takes its cells in one order, so two never wait
    on each other. The two-key form: its keys never meet the one-key locks of
    `core.stress_edits`."""
    with connection.cursor() as cursor:
        for x, y in lock_cells(lon, lat):
            cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [x & 0x7FFFFFFF, y & 0x7FFFFFFF])


def shown_now(node: Node, shown: str | None) -> int:
    """The level the map shows at the junction: an approved override's, else Avoid where an
    approved Avoid junction is there, else what the rider's route showed (its marker; "none"
    or nothing: 2, not marked). A route that showed Avoid where none is approved now is
    refused: the rider's map is out of date."""
    override = (
        JunctionOverride.objects.filter(active=True, **_near(node.lon, node.lat))
        .order_by("-created_at")
        .first()
    )
    if override is not None:
        return int(override.level)
    if AvoidJunction.objects.filter(approved=True, **_near(node.lon, node.lat)).exists():
        return AVOID
    if shown is not None and shown not in SHOWN_LEVELS:
        raise stress_edits.Invalid("The map's level for that junction is not one we know.", "shown")
    if shown == "avoid":
        raise stress_edits.Invalid(
            "That junction is no longer rated Avoid. Plan the route again and try once more.",
            "shown",
            "stale",
        )
    return SHOWN_LEVELS.get(shown or "none", 2)


def resolve(current: int, level: int | None, direction: str) -> int:
    """The level suggested, from a level and/or a comparison with the shown level."""
    if direction not in ("", "more", "less"):
        raise stress_edits.Invalid("Choose more dangerous or less dangerous.", "direction")
    if level is not None and level not in LEVELS:
        raise stress_edits.Invalid("Choose one of the levels listed.", "level")
    if level is None and not direction:
        raise stress_edits.Invalid(
            "Choose a level, or say whether it is more or less dangerous than shown.", "level"
        )
    if level is None:
        target = current + (1 if direction == "more" else -1)
        if target > AVOID:
            raise stress_edits.Invalid(
                "The map rates it Avoid already, the most dangerous level.", "direction"
            )
        if target < LEVELS[0]:
            raise stress_edits.Invalid(
                "The map shows it as easy already, the least dangerous level.", "direction"
            )
        return target
    if level == current:
        raise stress_edits.Invalid("That is how the map shows it already.", "level")
    if direction == "more" and level < current or direction == "less" and level > current:
        raise stress_edits.Invalid(
            "The level and the comparison disagree. Choose one, or make them match.", "direction"
        )
    return level


def create(
    user, lat: float, lon: float, level: int | None, direction: str, shown: str | None, reason: str
) -> JunctionSuggestion:
    """Record a rider's suggestion for the junction nearest (lat, lon)."""
    if not suggestions.may_suggest(user):
        raise Forbidden("Suggestions are not open to your account.")
    reason = (reason or "").strip()
    if not reason:
        raise stress_edits.Invalid("Say why, in a sentence or two.", "reason")
    if len(reason) > REASON_MAX:
        raise stress_edits.Invalid(f"The reason is at most {REASON_MAX} characters.", "reason")
    direction = direction or ""
    node = locate(lat, lon)
    current = shown_now(node, shown)
    target = resolve(current, level, direction)
    try:
        suggestion = _record(user, node, current, level, direction, target, reason)
    except IntegrityError as error:
        raise Conflict(
            "You have a suggestion for this junction waiting already. An admin will look at it."
        ) from error
    audit.record(
        user, "junction_suggest", "junction_suggestion", suggestion.pk,
        AuditLogEntry.Outcome.ALLOWED,
    )  # fmt: skip
    return suggestion


def _record(user, node, current, level, direction, target, reason) -> JunctionSuggestion:
    with transaction.atomic():
        mine = JunctionSuggestion.objects.select_for_update().filter(
            suggester=user, status__in=OPEN_STATUSES
        )
        if mine.filter(node=node.key).exists():
            raise Conflict(
                "You have a suggestion for this junction waiting already. An admin will look at it."
            )
        roads_open = StressSuggestion.objects.filter(
            suggester=user,
            status__in=(StressSuggestion.Status.PENDING, StressSuggestion.Status.SENT),
        ).count()
        if mine.count() + roads_open >= suggestions.OPEN_MAX:
            raise Conflict(
                f"You have {suggestions.OPEN_MAX} suggestions waiting. "
                "Wait for an admin to look at them."
            )
        return JunctionSuggestion.objects.create(
            suggester=user,
            suggester_user_id=user.pk,
            lon=node.lon,
            lat=node.lat,
            node=node.key,
            roads=list(node.roads),
            current_level=current,
            level=level,
            direction=direction,
            target_level=target,
            reason=reason,
        )


def open_suggestions(limit: int = 100) -> list[JunctionSuggestion]:
    return list(
        JunctionSuggestion.objects.filter(status__in=OPEN_STATUSES).order_by("created_at")[:limit]
    )


def _open(suggestion_id: int, *, lock: bool = True) -> JunctionSuggestion:
    rows = JunctionSuggestion.objects.all()
    if lock:
        rows = rows.select_for_update()
    suggestion = rows.filter(pk=suggestion_id).first()
    if suggestion is None:
        raise stress_edits.NotFound("That suggestion is not there.")
    if suggestion.status not in OPEN_STATUSES:
        raise Conflict(f"That suggestion was {suggestion.get_status_display().lower()} already.")
    return suggestion


def approve(admin, suggestion_id: int) -> JunctionSuggestion:
    """Apply the suggested level now: a junction override the next plan reads (2 to 4), or an
    approved Avoid junction (5). Whatever rated the junction before is withdrawn, audited."""
    now = timezone.now()
    withdrawn: list[str] = []
    with transaction.atomic():
        suggestion = _open(suggestion_id)
        _lock_near(suggestion.lon, suggestion.lat)
        near = _near(suggestion.lon, suggestion.lat)
        point = Point(suggestion.lon, suggestion.lat, srid=4326)
        name = (suggestion.name or "A junction rated by riders")[:200]
        evidence = f"Rider suggestion {suggestion.pk}: {suggestion.reason}"
        for old in JunctionOverride.objects.select_for_update().filter(active=True, **near):
            old.active = False
            old.withdrawn_at = now
            old.save(update_fields=["active", "withdrawn_at"])
            withdrawn.append(f"junction override {old.pk}")
        already = (
            AvoidJunction.objects.select_for_update()
            .filter(approved=True, **near)
            .order_by("pk")
            .first()
            if suggestion.target_level == AVOID
            else None
        )
        if already is not None:
            # Already rated Avoid there (another rider's suggestion, approved first): the
            # one rating is kept, so routes are not charged twice (review api-3).
            suggestion.avoid = already
            made = f"kept avoid junction {already.pk}"
        elif suggestion.target_level == AVOID:
            avoid = AvoidJunction.objects.create(
                name=name,
                location=point,
                reason=AVOID_REASON,
                evidence=evidence,
                source=AvoidJunction.Source.COMMUNITY,
                suggestion_ref=f"junction suggestion {suggestion.pk}",
                approved=True,
                approved_at=now,
                approved_by=admin,
                approved_by_user_id=admin.pk,
                created_by=admin,
                created_by_user_id=admin.pk,
            )
            suggestion.avoid = avoid
            made = f"avoid junction {avoid.pk}"
        else:
            for old in AvoidJunction.objects.select_for_update().filter(approved=True, **near):
                old.approved = False
                old.approved_at = None
                old.approved_by = None
                old.approved_by_user_id = None
                old.save(
                    update_fields=["approved", "approved_at", "approved_by", "approved_by_user_id"]
                )
                withdrawn.append(f"avoid junction {old.pk}")
            override = JunctionOverride.objects.create(
                name=name,
                location=point,
                level=suggestion.target_level,
                evidence=evidence,
                created_by=admin,
                created_by_user_id=admin.pk,
            )
            suggestion.override = override
            made = f"junction override {override.pk}"
        suggestion.status = JunctionSuggestion.Status.APPROVED
        suggestion.decided_at = now
        suggestion.decided_by = admin
        suggestion.save(update_fields=["status", "decided_at", "decided_by", "override", "avoid"])
    detail = made + (f"; withdrew {', '.join(withdrawn)}" if withdrawn else "")
    audit.record(
        admin, "junction_suggest_approve", "junction_suggestion", suggestion.pk,
        AuditLogEntry.Outcome.ALLOWED, detail=detail[:500],
    )  # fmt: skip
    return suggestion


def delete(admin, suggestion_id: int) -> JunctionSuggestion:
    with transaction.atomic():
        suggestion = _open(suggestion_id)
        suggestion.status = JunctionSuggestion.Status.DELETED
        suggestion.decided_at = timezone.now()
        suggestion.decided_by = admin
        suggestion.save(update_fields=["status", "decided_at", "decided_by"])
    audit.record(
        admin, "junction_suggest_delete", "junction_suggestion", suggestion.pk,
        AuditLogEntry.Outcome.ALLOWED,
    )  # fmt: skip
    return suggestion


def map_url(origin: str, suggestion: JunctionSuggestion) -> str:
    """The junction on RouteMaker's map (`#at=lon,lat`), its node to LINK_DECIMALS."""
    d = LINK_DECIMALS
    return f"{origin.rstrip('/')}/#at={suggestion.lon:.{d}f},{suggestion.lat:.{d}f}"


def post_for(suggestion: JunctionSuggestion, origin: str) -> suggestion_post.Post:
    roads = list(suggestion.roads or [])
    return suggestion_post.build(
        kind="junction",
        road=roads[0] if roads else None,
        crossing=roads[1] if len(roads) > 1 else None,
        current=suggestion.current_level,
        suggested=suggestion.target_level,
        reason=suggestion.reason,
        map_url=map_url(origin, suggestion),
    )


def send_to_discord(
    admin, suggestion_id: int, origin: str
) -> tuple[JunctionSuggestion, suggestion_post.Post]:
    """The poll to paste, and the suggestion marked as sent (again, for a second copy)."""
    with transaction.atomic():
        suggestion = _open(suggestion_id)
        post = post_for(suggestion, origin)
        suggestion.status = JunctionSuggestion.Status.SENT
        suggestion.sent_at = timezone.now()
        suggestion.save(update_fields=["status", "sent_at"])
    audit.record(
        admin, "junction_suggest_discord", "junction_suggestion", suggestion.pk,
        AuditLogEntry.Outcome.ALLOWED,
    )  # fmt: skip
    return suggestion, post


def summary(suggestion: JunctionSuggestion) -> dict:
    """One suggestion as the admin's review list shows it (no account details)."""
    return {
        "id": suggestion.pk,
        "junction": suggestion.name,
        "lat": suggestion.lat,
        "lon": suggestion.lon,
        "current_level": suggestion.current_level,
        "current_words": LEVEL_WORDS[suggestion.current_level],
        "level": suggestion.target_level,
        "words": LEVEL_WORDS[suggestion.target_level],
        "direction": suggestion.direction or None,
        "reason": suggestion.reason,
        "status": suggestion.status,
        "created_at": suggestion.created_at.isoformat(),
        "sent_at": suggestion.sent_at.isoformat() if suggestion.sent_at else None,
        # How many approved Avoid junctions Approve now would withdraw (a level short of Avoid
        # replaces them), so the review can warn before it does.
        "withdraws_avoid": avoid_withdrawn_by(suggestion),
    }


def avoid_withdrawn_by(suggestion: JunctionSuggestion) -> int:
    """The approved Avoid junctions within RATING_MATCH_M that approving `suggestion` would
    withdraw: every one, unless it suggests Avoid itself."""
    if suggestion.target_level >= AVOID:
        return 0
    return AvoidJunction.objects.filter(
        approved=True, **_near(suggestion.lon, suggestion.lat)
    ).count()


def approved_ratings() -> tuple[Rating, ...]:
    """The active junction overrides, for the intersection model. Empty when there are none
    or when the table cannot be read: a plan is never refused for want of them."""
    try:
        rows = JunctionOverride.objects.filter(active=True).only("id", "location", "level")
        return tuple(Rating(row.id, row.location.x, row.location.y, int(row.level)) for row in rows)
    except DatabaseError:
        logger.warning("the junction overrides could not be read", exc_info=True)
        return ()
