"""Signed-out LTS suggestions (v0.7.0).

The owner, 2026-10-13 14:14 UTC: "let even users that aren't signed into the app suggest changes
to LTS. Just have the slider with description and a brief panel of options with a catch all
other. It should be relatively simple to filter out meaningless data." And 14:16: "Half steps
too!"; 14:17: "2 people are unlikely right now, I'll review each until it gets larger".

Anyone the full form is not open to (`core.suggestions.may_suggest`) gets the road panel's short
form: the level slider in half steps (1 to 4.5 and Avoid), one-tap reasons (`REASONS`, "Other"
with up to `OTHER_MAX` characters), and Send. A send that passes the filters joins the existing
review queue (`core.suggestions`) marked `signed_out`; nothing changes on the map until an instance
admin reviews it, as with a signed-in suggestion.

The filters, so the review list stays useful:

- dropped: no change from the road's level, no reason, the hidden honeypot field filled in
  (answered as if sent, so a bot learns nothing), and a send without a ticket from opening the
  form on that road (`ticket`, signed by the server, `TICKET_MAX_AGE_S`);
- at most `DAILY_MAX` sends a day per device, and one per road: a device is a salted hash of its
  address and the day (`device_hash`; `models.SignedOutSend`), kept 24 hours; the address itself
  is never stored;
- Other's words are screened for e-mail addresses and phone numbers (`screen`), which are taken
  out before anything is stored.

The review list (`core.suggestions.open_suggestions`) groups sends by road with how many agree,
sorted by agreement and the size of the gap. A road's signed-out sends show once
`settings.SUGGEST_SIGNED_OUT_MIN_AGREE` of them agree (1, so every send shows: the threshold of two
is built but off until volume grows).

Privacy: no account, address, location trail or device id is stored with a suggestion; the spot
kept is the nearest point on the road (`core.suggestions.snap`), never the one clicked.

From the ride summary (`from_ride`; frontend lib/rideFeedback.ts, the 2026-11-12 backlog item 7): a
send there says where the rider just was, so it keeps less (the owner's rule: nothing identifying
stays on the server longer than two minutes). The suggestion keeps the day, never the time
(`created_at` is midnight, Washington's day, as the 311 log keeps it); the per-device count row
is dated by the day too and keeps the road only as a one-way code mixed with the device's
(`ride_road_code`), so the row names no road, yet one-a-road still holds, whichever form sent it
(a ride's retry, or Keep riding and End ride again, is refused as "already sent", not counted
twice); and the audit row names no suggestion and is dated by the day. Rows of each kind are
made one a send, in step, so a row's exact time would otherwise date the suggestion.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.utils import timezone

from . import audit, stress_edits, suggestions
from .models import AuditLogEntry, SignedOutSend, StressSuggestion

CLOSED = "closed"
# The one-tap reasons, in the form's order: key -> words.
REASONS = {
    "fast_traffic": "Fast traffic",
    "heavy_traffic": "Heavy traffic",
    "narrow": "No shoulder or narrow",
    "bike_lane": "Bike lane missing or blocked",
    "calmer": "Feels calmer than rated",
    # v0.7.0 closures: a report that the road is closed, reviewed with the closures
    # (core.reviewed_closures), with or without a level.
    CLOSED: "Closed (works, an event, fenced off)",
    "other": "Other",
}
OTHER_MAX = 200
DAILY_MAX = 10
KEEP = timedelta(hours=24)
TICKET_SALT = "routemaker/signed-out-suggestion/v1"
TICKET_MAX_AGE_S = 2 * 3600
DEVICE_SALT = b"routemaker/signed-out-device/v1"
RIDE_ROAD_SALT = b"routemaker/signed-out-ride-road/v1"
REMOVED = "[removed]"
# A ride's send keeps the day in Washington's time (core.report_log.DAY_ZONE, the 311 log's).
DAY_ZONE = ZoneInfo("America/New_York")

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# A phone number: 7 or more digits, with the usual separators between them ("2019-2021" is two
# years, not a number: fewer than 7 digits).
PHONE = re.compile(r"(?<!\w)\+?\(?\d[\d\s().-]{5,}\d(?!\w)")
PHONE_DIGITS = 7


class Dropped(Exception):
    """A send the filters drop without a word to the sender (the honeypot)."""


class Limited(stress_edits.EditRefused):
    status = 429
    code = "limited"


class Again(stress_edits.EditRefused):
    status = 409
    code = "conflict"


def prune(now=None) -> int:
    """Delete the per-device send rows older than `KEEP`; how many. Run at every send
    (`create`), and nightly by the backup task, so a quiet server drops them too."""
    now = now or timezone.now()
    deleted, _ = SignedOutSend.objects.filter(created_at__lt=now - KEEP).delete()
    return deleted


def ticket(way_id: int) -> str:
    """What the form carries back: proof it was opened on this road, signed and dated."""
    return signing.dumps({"w": int(way_id)}, salt=TICKET_SALT, compress=True)


def ticket_ok(value: str | None, way_id: int) -> bool:
    if not value:
        return False
    try:
        found = signing.loads(value, salt=TICKET_SALT, max_age=TICKET_MAX_AGE_S)
    except signing.BadSignature:
        return False
    return isinstance(found, dict) and found.get("w") == way_id


def device_hash(address: str, day=None) -> str:
    """A salted hash of the address and the day: one device for a day, never reversible, and
    not matchable across days. The key is derived from the server's secret."""
    day = day or timezone.now().date()
    key = hmac.new(settings.SECRET_KEY.encode(), DEVICE_SALT, hashlib.sha256).digest()
    return hmac.new(key, f"{day.isoformat()}|{address}".encode(), hashlib.sha256).hexdigest()


def screen(text: str) -> str:
    """Other's words with e-mail addresses and phone numbers taken out."""
    text = EMAIL.sub(REMOVED, text)
    return PHONE.sub(
        lambda m: REMOVED if sum(c.isdigit() for c in m.group()) >= PHONE_DIGITS else m.group(),
        text,
    )


def reason_words(reasons: list[str], other: str) -> str:
    """The reasons as the review list and the poll read them: "Fast traffic; Other: ..."."""
    parts = [REASONS[r] for r in reasons if r != "other"]
    if "other" in reasons:
        parts.append(f"Other: {other}" if other else "Other")
    return "; ".join(parts)


def create(
    address: str,
    way_id: int,
    lat: float,
    lon: float,
    step,
    reasons: list[str],
    other: str,
    ticket_value: str | None,
    honeypot: str,
    from_ride: bool = False,
) -> StressSuggestion:
    """Record a signed-out suggestion, or refuse it (EditRefused) or drop it (Dropped).

    `from_ride`: sent from the ride summary; kept with the day only, and no road beside the device.
    """
    if honeypot.strip():
        raise Dropped
    if not ticket_ok(ticket_value, way_id):
        raise stress_edits.Invalid(
            "Open the road's panel again, then send your suggestion.", None, "no_ticket"
        )
    tier, half = stress_edits.split_step(step)
    chosen = list(dict.fromkeys(r for r in reasons if r in REASONS))
    if not chosen or len(chosen) != len(set(reasons)):
        raise stress_edits.Invalid("Pick at least one reason.", "reasons")
    other = " ".join((other or "").split())
    if "other" in chosen and not other:
        raise stress_edits.Invalid("Say what else, in a few words.", "other")
    if len(other) > OTHER_MAX:
        raise stress_edits.Invalid(f"Other is at most {OTHER_MAX} characters.", "other")
    other = screen(other) if "other" in chosen else ""
    row, name = suggestions._road(way_id)
    if half and stress_edits.HALF_COLUMN not in row:
        raise stress_edits.Invalid(
            "Half steps arrive with the next data update. Choose a whole step for now.",
            "step",
            "half_unavailable",
        )
    closure = CLOSED in chosen
    if not closure and float(stress_edits.current_step(row)) == tier + (0.5 if half else 0.0):
        raise stress_edits.Invalid("Choose a level other than the road's own.", "step")
    lat, lon = suggestions.snap(way_id, lat, lon)
    device = device_hash(address)
    now = timezone.now()
    with transaction.atomic():
        SignedOutSend.objects.filter(created_at__lt=now - KEEP).delete()
        # One device's sends at a time: two at once cannot both slip under the limits.
        sends = list(
            SignedOutSend.objects.select_for_update().filter(
                device=device, created_at__gte=now - KEEP
            )
        )
        code = ride_road_code(device, way_id)
        road = code if from_ride else way_id
        # One a road whichever form sent it: the road panel's (the road) or a ride's (its code).
        if any(s.osm_way_id in (way_id, code) for s in sends):
            raise Again("You've sent a suggestion for this road today. Thank you.")
        if len(sends) >= DAILY_MAX:
            raise Limited(f"That's {DAILY_MAX} suggestions today. Thank you; try again tomorrow.")
        # A ride's count row is dated by the day too: rows and suggestions are made one each per
        # send, in step, so a row's time would date the suggestion it was made with.
        SignedOutSend.objects.create(
            device=device, osm_way_id=road, created_at=ride_day(now) if from_ride else now
        )
        suggestion = StressSuggestion.objects.create(
            created_at=ride_day(now) if from_ride else now,
            suggester=None,
            suggester_user_id=None,
            signed_out=True,
            kind=StressSuggestion.Kind.CLOSURE if closure else StressSuggestion.Kind.ROAD,
            osm_way_id=way_id,
            lat=float(lat),
            lon=float(lon),
            road_name=name,
            current_tier=int(row[stress_edits.TIER_COLUMN]),
            current_half=row.get(stress_edits.HALF_COLUMN) is True,
            tier=tier,
            half=half,
            reasons=chosen,
            reason=reason_words(chosen, other),
        )
    # A ride's send: the audit row's time would be the send's, so it names no suggestion.
    entry = audit.record(
        None, "stress_suggest_signed_out", "stress_suggestion", "" if from_ride else suggestion.pk,
        AuditLogEntry.Outcome.ALLOWED,
    )  # fmt: skip
    if from_ride and entry is not None:
        # Its audit row too: one a send, in step with the suggestions, so dated by the day.
        AuditLogEntry.objects.filter(pk=entry.pk).update(at=ride_day(now))
    return suggestion


def ride_road_code(device: str, way_id: int) -> int:
    """A ride's road as its count row keeps it: a one-way code of the device's code and the road,
    negative so it never equals a road id. It says only "this device sent this code today"."""
    key = hmac.new(settings.SECRET_KEY.encode(), RIDE_ROAD_SALT, hashlib.sha256).digest()
    digest = hmac.new(key, f"{device}|{int(way_id)}".encode(), hashlib.sha256).digest()
    return -(int.from_bytes(digest[:8], "big") >> 2) - 1


def ride_day(now: datetime) -> datetime:
    """Midnight of `now`'s day in Washington: what a ride's send keeps instead of its time."""
    return datetime.combine(now.astimezone(DAY_ZONE).date(), time.min, tzinfo=DAY_ZONE)
