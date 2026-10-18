"""Share the identical route (v0.7.0; the owner, 2026-10-15 23:19 UTC: "The ability to share a gpx
identical route should be in too?").

Before this a Share link carried only the plan's inputs, and the route was planned again when the
link was opened, so it could differ. Now the Share button also keeps the exact line shown, verbatim
like a saved route or an opened GPX file (its points in order, elevations and stops, and a planned
route's answer), under an unguessable id that the link carries; the link opens that line unchanged.
The closure check still runs when the link is opened and on Start ride, as for a saved route.

The id is 128 random bits written as 32 hex characters (`ID_RE`). The page makes it with the
browser's own random source and puts it in the link before the line is sent, so the phone's share
sheet still opens inside the press (a share sheet refuses to open after a wait); the id is only
ever stored once (`409` if taken). The link carries the plan's inputs as well, so a link whose line
was never stored, or has since gone, plans its route again from them, as every link did before.

Nothing of the rider is kept but, signed in, the account (`owner`, below): no address (the rate
limit keys on a salted hash, `core.ratelimit`), and no weight (OWNER-DECISIONS 313):
`public_answer` takes the rider's system weight and the effort figure weighed with it out of a
planned route's answer. A row is kept a year after it was last opened (`KEEP`), then deleted at the
next share or open; the sharer may instead keep it permanently or until a date (`KEEP_CHOICES`; the
owner, 2026-10-16: "For the 1 year deletion, make this the default. For other users, we can offer
"keep permanently" and "delete after <date>""). The whole body is at most `MAX_BYTES`. Models:
`core.models.SharedRoute`; endpoints in `core.api`.

Shared signed in, the row names its owner (and nothing else of them), who alone can turn the link
off (`revoke`) or swap it for a new one (`regenerate`: a new random id with the same route and
keeping, the old one turned off), from My routes in Plan. A turned-off link stays as a tombstone
with its route cleared and is kept permanently, so its link keeps saying it was turned off
(`REVOKED`, 410) rather than planning its points again once the row was gone. The link's preview,
for chat apps that fetch it: `core.share_preview`.
"""

from __future__ import annotations

import re
import secrets
from datetime import date, timedelta

from . import accounts

ID_RE = re.compile(r"[0-9a-f]{32}")
# The whole body: a planned route with its answer is a few hundred kilobytes; a long GPX file's
# own text with its track can be more, and is shared as its inputs-only link instead.
MAX_BYTES = 2 * 1024 * 1024
# Kept a year after it was last opened.
KEEP = timedelta(days=365)
# An open writes its time at most once a day.
TOUCH_EVERY = timedelta(days=1)
DEFAULT_NAME = "Shared route"
# How long the sharer keeps it: a year after the last open (the default), permanently, or through
# `delete_after`. The page offers tomorrow or later in the sharer's own time zone, so the server
# (UTC) accepts today or later: a sharer west of UTC in the evening is already on UTC's tomorrow.
KEEP_CHOICES = ("year", "forever", "until")
SOURCES = ("plan", "gpx")
KEYS = frozenset(
    {"id", "name", "source", "line", "distance_m", "inputs", "answer", "gpx"}
    | {"keep", "delete_after", "preview_image"}
)
# What a turned-off link's page and preview say: plainly, with no detail.
REVOKED = "This link was turned off by its owner."


def prune(now=None) -> int:
    """Delete the expired rows (`expired`); how many. Run at every share and open
    (`core.api`), and nightly by the backup task, so a quiet server drops them too."""
    from django.db.models import Q
    from django.utils import timezone

    from .models import SharedRoute

    now = now or timezone.now()
    deleted, _ = SharedRoute.objects.filter(
        Q(keep="year", last_opened_at__lt=now - KEEP)
        | Q(keep="until", delete_after__lt=timezone.localdate(now))
    ).delete()
    return deleted


def expired(row, now) -> bool:
    """Whether a kept row is past its keeping, as `prune` reads it."""
    from django.utils import timezone

    if row.keep == "forever":
        return False
    if row.keep == "until":
        return row.delete_after is None or row.delete_after < timezone.localdate(now)
    return row.last_opened_at < now - KEEP


def revoke(row, now) -> None:
    """Turn the link off: keep only the tombstone (its id, owner and time), permanently."""
    row.revoked_at = now
    row.name = ""
    row.source = ""
    row.distance_m = 0
    row.line = []
    row.inputs = {}
    row.answer = None
    row.gpx = ""
    row.keep = "forever"
    row.delete_after = None
    row.preview_png = None
    row.preview_key = ""
    row.preview_zone = None
    row.save()


def regenerate(row, now):
    """A new link for the same route and keeping, the old one turned off; the new row."""
    from django.db import transaction

    from .models import SharedRoute

    with transaction.atomic():
        fresh = SharedRoute.objects.create(
            id=secrets.token_hex(16),
            name=row.name,
            source=row.source,
            line=row.line,
            distance_m=row.distance_m,
            inputs=row.inputs,
            answer=row.answer,
            gpx=row.gpx,
            created_at=now,
            last_opened_at=now,
            keep=row.keep,
            delete_after=row.delete_after,
            owner=row.owner,
            preview_image=row.preview_image,
            preview_zone=row.preview_zone,
        )
        revoke(row, now)
    return fresh


def link_of(row, origin: str) -> str:
    """The link Share gives for a kept row: its preview path, then the plan's inputs and the id
    (frontend/src/lib/sharedRoutes.ts withSharedId)."""
    fragment = str((row.inputs or {}).get("hash", "")).lstrip("#")
    return f"{origin}/s/{row.pk}#{fragment + '&' if fragment else ''}route={row.pk}"


def delete_after_of(value, today: date) -> date | None:
    """A "delete after" date as sent ("YYYY-MM-DD"), or None when it is not today or later."""
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        day = date.fromisoformat(value)
    except ValueError:
        return None
    return day if day >= today else None


def id_ok(value) -> bool:
    return isinstance(value, str) and ID_RE.fullmatch(value) is not None


def public_answer(answer: dict) -> dict:
    """A planned route's answer as it may be shared: without the other candidates, and without
    the rider's system weight or the effort figure weighed with it."""
    out = {**answer, "candidates": None, "avoid_alternate": None, "closure_through": None}
    dials = out.get("dials")
    if isinstance(dials, dict) and dials.get("system_weight_kg") is not None:
        out["dials"] = {**dials, "system_weight_kg": None}
        out["effort_m"] = None
    return out


def body_problem(body, today: date | None = None) -> tuple[str, str | None] | None:
    """Why a shared route cannot be kept, as (message, field), or None."""
    if not isinstance(body, dict):
        return "Send the route as an object.", None
    unknown = sorted(set(body) - KEYS)
    if unknown:
        return f"Not part of a shared route: {unknown[0]}.", unknown[0]
    if not id_ok(body.get("id")):
        return "The route's id is 32 hexadecimal characters.", "id"
    name = body.get("name", "")
    if not isinstance(name, str) or len(name.strip()) > accounts.NAME_MAX:
        return f"The route's name is up to {accounts.NAME_MAX} characters.", "name"
    source = body.get("source", "plan")
    if source not in SOURCES:
        return "Not a kind of route this planner shares.", "source"
    problem = accounts.line_problem(body.get("line"))
    if problem:
        return problem, "line"
    distance = body.get("distance_m")
    if not accounts._finite(distance) or distance <= 0:
        return "The route's distance is missing.", "distance_m"
    problem = accounts.inputs_problem(body.get("inputs", {}))
    if problem:
        return problem, "inputs"
    # An opened file keeps its answer too (v0.9.0, "share the exact route"): the route shown for it,
    # followed by its ride type's rules or exactly (`follows_exactly`), so the link opens that line.
    answer = body.get("answer")
    if answer is not None and not isinstance(answer, dict):
        return "Send the route's answer as an object.", "answer"
    gpx = body.get("gpx", "") or ""
    if not isinstance(gpx, str) or (gpx and source != "gpx"):
        return "Only an opened GPX file keeps its text.", "gpx"
    if not isinstance(body.get("preview_image", True), bool):
        return "Say whether the link may have a preview image.", "preview_image"
    keep = body.get("keep", "year")
    if keep not in KEEP_CHOICES:
        return "Keep a shared route for a year, permanently, or until a date.", "keep"
    if keep == "until":
        from django.utils import timezone

        if delete_after_of(body.get("delete_after"), today or timezone.localdate()) is None:
            return "Pick a later date to delete the shared route.", "delete_after"
    elif body.get("delete_after") not in (None, ""):
        return "Only a route kept until a date has a date to delete it.", "delete_after"
    return None
