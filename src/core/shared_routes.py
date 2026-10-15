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
whole body is at most `MAX_BYTES`. Models: `core.models.SharedRoute`; endpoints in `core.api`.
"""

from __future__ import annotations

import re
from datetime import timedelta

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
SOURCES = ("plan", "gpx")
KEYS = frozenset({"id", "name", "source", "line", "distance_m", "inputs", "answer", "gpx"})


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


def body_problem(body) -> tuple[str, str | None] | None:
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
    return None
