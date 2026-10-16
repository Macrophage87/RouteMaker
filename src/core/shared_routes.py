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

Signed out or in, nothing of the rider is kept: no account, no address (the rate limit keys on a
salted hash, `core.ratelimit`), and no weight (OWNER-DECISIONS 313): `public_answer` takes the
rider's system weight and the effort figure weighed with it out of a planned route's answer. A row
is kept a year after it was last opened (`KEEP`), then deleted at the next share or open; the
sharer may instead keep it permanently or until a date (`KEEP_CHOICES`; the owner, 2026-10-16:
"For the 1 year deletion, make this the default. For other users, we can offer "keep permanently"
and "delete after <date>""). The whole body is at most `MAX_BYTES`. Models:
`core.models.SharedRoute`; endpoints in `core.api`.
"""

from __future__ import annotations

import re
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
    | {"keep", "delete_after"}
)


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
    out = {**answer, "candidates": None, "avoid_alternate": None}
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
    answer = body.get("answer")
    if answer is not None and (source != "plan" or not isinstance(answer, dict)):
        return "Only a planned route keeps its answer.", "answer"
    gpx = body.get("gpx", "") or ""
    if not isinstance(gpx, str) or (gpx and source != "gpx"):
        return "Only an opened GPX file keeps its text.", "gpx"
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
