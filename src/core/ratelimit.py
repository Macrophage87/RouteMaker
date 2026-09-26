"""Per-client request limits for the unauthenticated surface.

PLAN, Moderation and abuse limits: limits are "counted in a PostgreSQL
fixed-window table rather than in process memory, since gunicorn runs a worker
per core and in-memory counters would multiply every stated limit by the worker
count; at this scale a Postgres-backed store is adequate and avoids adding Redis
to the stack". That is the mechanism here, and the reason it is correct across
workers is that a request is counted by one statement: an upsert on
`(scope, client)` that either increments the current window's count or, if the
row holds an older window, restarts it at one, and returns the result. The row
lock the upsert takes serialises concurrent requests for the same client, so N
workers see one budget between them, not N. The window is computed from the
database's clock, so workers whose clocks disagree still agree on the window.

Who the client is: the api is only reachable through Caddy (compose.yaml rule
1: only Caddy publishes a port), and Caddy, trusting no upstream proxy, replaces
whatever X-Forwarded-For a client sent with the peer address it saw. So the last
entry of that header is the one address in the request an outside client cannot
choose. IPv6 clients are counted per /64, because a single subscriber is
routinely handed a whole /64 and per-address counting would give one person an
unbounded number of budgets.

What is stored: a keyed digest of that address, never the address, and the row
is purged once it has been idle for `RETENTION`. PLAN, Privacy and retention,
sets 30 days as the ceiling for client addresses in the rate-limit store; a day
is enough for a limiter whose longest window is a minute. The table is also
excluded from the nightly dump (`config.procrastinate.BACKUP_EXCLUDED_TABLES`),
since a backup outlives the retention.
"""

from __future__ import annotations

import ipaddress
import random
from dataclasses import dataclass
from datetime import timedelta
from functools import wraps

from django.db import connection
from django.http import JsonResponse
from django.utils.crypto import salted_hmac

# Rows idle longer than this are deleted. Inside the plan's 30-day ceiling.
RETENTION = timedelta(days=1)

# Each counted request purges idle rows with this probability. The purge is one
# indexed DELETE; at one request in five hundred it costs nothing measurable
# and needs no scheduled task.
PURGE_PROBABILITY = 1 / 500

_KEY_SALT = "routemaker/rate-limit/v1"


@dataclass(frozen=True)
class Limit:
    """`requests` per `window_s` seconds per client, counted under `scope`."""

    scope: str
    requests: int
    window_s: int


@dataclass(frozen=True)
class Decision:
    allowed: bool
    # Seconds until the current window ends; 0 when allowed.
    retry_after_s: int


# PLAN, Moderation and abuse limits: routing is 60 per minute per user, and the
# unauthenticated paths are 60 per minute per client address. A signed-out
# planner is both, so it is the one figure.
ROUTING = Limit(scope="route", requests=60, window_s=60)


def _normalise(candidate: str) -> str | None:
    try:
        address = ipaddress.ip_address(candidate.strip())
    except ValueError:
        return None
    if address.version == 6:
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address)


def client_address(request) -> str:
    """The client this request is counted against; see the module docstring."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded.strip():
        normalised = _normalise(forwarded.split(",")[-1])
        if normalised is not None:
            return normalised
    return _normalise(request.META.get("REMOTE_ADDR", "")) or "unknown"


def client_key(address: str) -> str:
    """A keyed digest of the address: stable per client, not the address."""
    return salted_hmac(_KEY_SALT, address, algorithm="sha256").hexdigest()


_HIT = """
INSERT INTO rate_limit_window AS w (scope, client, window_start, hits)
VALUES (
    %(scope)s,
    %(client)s,
    to_timestamp(floor(extract(epoch FROM clock_timestamp()) / %(window)s) * %(window)s),
    1
)
ON CONFLICT (scope, client) DO UPDATE SET
    hits = CASE WHEN w.window_start = EXCLUDED.window_start THEN w.hits + 1 ELSE 1 END,
    window_start = EXCLUDED.window_start
RETURNING
    w.hits,
    ceil(extract(epoch FROM w.window_start + make_interval(secs => %(window)s)
                            - clock_timestamp()))::integer
"""


def hit(limit: Limit, client: str) -> Decision:
    """Count one request by `client` against `limit` and say whether it may proceed."""
    with connection.cursor() as cursor:
        cursor.execute(_HIT, {"scope": limit.scope, "client": client, "window": limit.window_s})
        hits, remaining = cursor.fetchone()
    if random.random() < PURGE_PROBABILITY:
        purge_expired()
    if hits <= limit.requests:
        return Decision(allowed=True, retry_after_s=0)
    return Decision(allowed=False, retry_after_s=min(limit.window_s, max(1, int(remaining))))


def purge_expired() -> int:
    """Delete rows idle for longer than `RETENTION`; returns how many."""
    with connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM rate_limit_window WHERE window_start < clock_timestamp() - %s",
            [RETENTION],
        )
        return cursor.rowcount


def rate_limited(limit: Limit):
    """A view decorator: count the request, and answer 429 with Retry-After
    instead of calling the view once the client's budget is spent.

    Applied outside any body parsing, so a refused request costs one upsert and
    nothing else.
    """

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            decision = hit(limit, client_key(client_address(request)))
            if not decision.allowed:
                response = JsonResponse(
                    {"error": "Too many requests from this address; try again shortly."},
                    status=429,
                )
                response["Retry-After"] = str(decision.retry_after_s)
                return response
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
