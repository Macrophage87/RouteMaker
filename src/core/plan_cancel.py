"""Cancelling a plan the rider has replaced (routing audit S7, option B).

Go shows its first route at once and then asks for the full plan (frontend
lib/routeScheduler.ts, `refine`). A rider who moves a pin or a slider while that full plan
runs wants a new plan, and the old one's answer is thrown away. The scheduler used to wait
for it all the same, because aborting a fetch does not stop gunicorn computing it, nor free
its routing slot. The owner, 2026-10-27, approved reversing the scheduler's "one request at
a time" rule for this: the page names each plan (`X-Plan-Id`), and when it replaces a full
plan in flight it says so (POST /api/route/cancel) and sends the new plan at once, naming
the plan it replaces (`X-Plan-Replaces`).

How a cancel reaches the plan: gunicorn's workers share no memory, and this deployment has
no shared cache (Django's default cache is per process; there is no Redis, by design: see
`core.ratelimit`). So the flag is a row of the one shared store the limits already use,
`rate_limit_window`, under scope `plan-cancel`: a keyed digest of the client's address and
the plan id (never either of them), stamped with the database's clock and good for
CANCEL_TTL_S. The digest takes the address the request came from, as the limits count it,
so a client can only ever cancel its own plans: another client's cancel of the same id
writes a different row. Rows are purged with the limits' (`ratelimit.purge_expired`) and
are left out of the backups with that table.

The plan sees the flag between router calls: `routing._call` asks first (`Watch.check`),
at most every POLL_S, from the request's own thread (the pool's threads read only what that
thread found), and raises `routing.PlanCancelled`, a DeadlineExceeded, so the plan winds
down the way it does when its time runs out, with no further router calls. One call already
running finishes; nothing interrupts it. The answer is then a 409 `plan_cancelled`, which
the page drops unread, and the slots are released as for any request.

The new plan and the slots: on beta's routing pool of two, the old plan still holds the
client's slot when the new plan arrives, and the new plan would be refused (429, or 503
when another rider holds the other slot) and waited out for Retry-After. A plan that names
the plan it replaces records that plan's cancel itself (so a lost cancel still lands) and
may wait up to REPLACE_WAIT_S for a slot, polling as geocoding's wait does, with one such
waiter in the deployment (`ratelimit.replacing`); past that it is refused as before.
"""

from __future__ import annotations

import logging
import re

from django.db import DatabaseError, connection
from django.http import JsonResponse

from . import parallel, ratelimit, routing

logger = logging.getLogger(__name__)

# The header that names a plan, and the one that names the plan a request replaces.
PLAN_ID_HEADER = "HTTP_X_PLAN_ID"
REPLACES_HEADER = "HTTP_X_PLAN_REPLACES"
# What a plan id may be: the page makes 32 hex digits; anything from 8 to 64 of these.
PLAN_ID = re.compile(r"[A-Za-z0-9_-]{8,64}")

SCOPE = "plan-cancel"
# How long a cancel stands: a plan runs at most 50 s from its arrival (a long ride's
# budget), and a cancel can arrive before the plan it cancels has started.
CANCEL_TTL_S = 60
# How often a running plan asks whether it has been cancelled: one indexed read, so a calm
# search that makes dozens of router calls asks a few times a second at most.
POLL_S = 0.1
# How long a replacing plan may wait for the slot the plan it replaces still holds. A
# second, as geocoding's wait (the owner's answer of 2026-09-28, "Free within ~1 s"): the
# waiter holds one of the workers the slots leave free, for no longer than that.
REPLACE_WAIT_S = 1.0

CANCELLED_CODE = "plan_cancelled"


def plan_id(value: str | None) -> str | None:
    """`value` where it is a plan id, else None."""
    if value is None:
        return None
    value = value.strip()
    return value if PLAN_ID.fullmatch(value) else None


def _key(request, plan: str) -> str:
    """The flag's key: a keyed digest of this client's address and the plan id. Another
    client's request for the same id gets another key."""
    return ratelimit.client_key(f"{ratelimit.client_address(request)}\n{plan}")


_RECORD = """
INSERT INTO rate_limit_window AS w (scope, client, window_start, hits)
VALUES (%(scope)s, %(client)s, clock_timestamp(), 1)
ON CONFLICT (scope, client) DO UPDATE SET window_start = clock_timestamp(), hits = 1
"""

_FLAGGED = """
SELECT 1 FROM rate_limit_window
WHERE scope = %(scope)s AND client = %(client)s
  AND window_start > clock_timestamp() - make_interval(secs => %(ttl)s)
"""


def record(request, plan: str) -> None:
    """Flag this client's plan `plan` as cancelled, for CANCEL_TTL_S."""
    with connection.cursor() as cursor:
        cursor.execute(_RECORD, {"scope": SCOPE, "client": _key(request, plan)})


def flagged(key: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(_FLAGGED, {"scope": SCOPE, "client": key, "ttl": CANCEL_TTL_S})
        return cursor.fetchone() is not None


class Watch:
    """One plan's cancel flag, as `routing.check_cancel` asks it."""

    def __init__(self, key: str) -> None:
        self.key = key
        # Once seen, for good: every later ask raises at once, on any thread.
        self.cancelled = False
        self._next_poll = 0.0

    def check(self, poll: bool = True) -> None:
        if self.cancelled:
            raise routing.PlanCancelled("the rider replaced this plan")
        # The pool's threads never read the database (core.parallel); nor is a read made
        # inside a transaction, where a failed one would spoil what follows.
        if not poll or parallel.inside() or connection.in_atomic_block:
            return
        now = routing.clock()
        if now < self._next_poll:
            return
        self._next_poll = now + POLL_S
        try:
            found = flagged(self.key)
        except DatabaseError:
            # The plan goes on as if never cancelled: the rider's newer plan is unaffected.
            logger.warning("could not read a plan's cancel flag", exc_info=True)
            return
        if found:
            self.cancelled = True
            raise routing.PlanCancelled("the rider replaced this plan")


def watch_for(request) -> Watch | None:
    """The watch for a request that names its plan (X-Plan-Id), else None."""
    plan = plan_id(request.META.get(PLAN_ID_HEADER))
    return None if plan is None else Watch(_key(request, plan))


def replaces(request) -> str | None:
    """The plan this request replaces (X-Plan-Replaces), where it names one."""
    return plan_id(request.META.get(REPLACES_HEADER))


def cancelled_answer() -> JsonResponse:
    """What a cancelled plan answers: nothing the page reads (it has moved on), and no
    Retry-After, which would hold the newer plan back."""
    return JsonResponse(
        {"error": "This plan was replaced by a newer one.", "code": CANCELLED_CODE}, status=409
    )
