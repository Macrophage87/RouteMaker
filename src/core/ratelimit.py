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
is purged once it has been idle for `RETENTION` by the worker's membership
sweep (every six hours, `config.procrastinate.membership_sweep`), so no row
outlives about thirty hours. PLAN, Privacy and retention, sets 30 days as the
ceiling for client addresses in the rate-limit store. The table is also
excluded from the nightly dump (`config.procrastinate.BACKUP_EXCLUDED_TABLES`),
since a backup outlives the retention. The digest is keyed with SECRET_KEY, so
it hides the address from a dump but not from someone holding the key, who can
try every IPv4 address; that is the same party that can read the database.

A count per minute does not bound how many of a client's requests run at once,
and a routing request holds a gunicorn worker for as long as the router takes.
So routing also takes an in-flight slot (`in_flight_limited`): a session-level
PostgreSQL advisory lock, one of `total` for the deployment and one of
`per_client` for the client, held for the request and released after it. The
lock lives on the worker's database connection, so it is correct across
workers and dies with a killed worker; a lock that cannot be released closes
that connection, which ends it. `total` is the worker count less two
(`config.settings.routing_concurrency`), so from three workers up, however the
router is loaded, two workers are free for `/healthz`, the tiles, sign-in and
the admin; one or two workers still get one slot, and keep fewer free.
"""

from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.utils.crypto import salted_hmac

logger = logging.getLogger(__name__)

# Rows idle longer than this are deleted. Inside the plan's 30-day ceiling.
RETENTION = timedelta(days=1)

_KEY_SALT = "routemaker/rate-limit/v1"

# The first key of every advisory lock this module takes, so nothing else in
# the database that uses advisory locks can collide with these.
_LOCK_CLASS_TOTAL = 0x524D0000
_LOCK_CLASS_CLIENT = 0x524D1000

# How long a refused client is told to wait for a slot. An ordinary route takes
# about a second, one near 150 km from a few seconds to over twenty under load,
# and a long ride from a few seconds warm to over forty cold (review round 3:
# 22.15 s and 26.73 s measured, and one cold /route 43.9 s); two seconds is a
# short first wait rather than the expected time, and the whole-deployment
# case asks for longer because it means every slot is busy.
CLIENT_BUSY_RETRY_S = 2
DEPLOYMENT_BUSY_RETRY_S = 5


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

# The stress tiles, counted apart from routing so that looking at the map never
# spends the routing budget (nor routing the tiles'). PLAN's 60 per minute is a
# figure for requests a person makes one at a time; a map makes them by the
# screenful. A 1920x1080 view of 512-pixel tiles is up to 5 x 4 = 20 tiles,
# and every zoom step or long pan fetches most of a screenful again: a minute
# of zooming in and out four levels and panning, in a 1920x1080 window with an
# empty cache, fetched 87 (2026-09-27, against the first promoted build). 600
# a minute is several times that, for a household or an office behind one
# address; the browser's cache (an hour, then a 304 that draws nothing) keeps
# a return to a place from counting twice in the hour. This is above PLAN's
# 60 for unauthenticated paths, which a map could not work inside.
TILES = Limit(scope="tiles", requests=600, window_s=60)


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
    if hits <= limit.requests:
        return Decision(allowed=True, retry_after_s=0)
    return Decision(allowed=False, retry_after_s=min(limit.window_s, max(1, int(remaining))))


def purge_expired() -> int:
    """Delete rows idle for longer than `RETENTION`; returns how many.

    Called by the worker's membership sweep, every six hours.
    """
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


@dataclass(frozen=True)
class InFlight:
    """At most `per_client` requests per client, and at most the deployment's
    `settings.<total_setting>` requests in all, running at once under `scope_id`.

    A client's slots beyond its first are granted only while the pool is
    roomy: a further slot is taken only if at least `ROOM_FOR_OTHERS` of the
    deployment's slots would still be free after it. On a pool of three - the
    compose default - that means one route per client, so filling the pool
    takes three addresses rather than two; on a larger host a household behind
    one NAT address gets a second route while the pool has room for everyone
    else.
    """

    scope_id: int
    per_client: int
    total_setting: str
    client_busy: str = "This address already has a route being planned; try again shortly."
    deployment_busy: str = "The planner is busy; try again in a few seconds."

    @property
    def total(self) -> int:
        return int(getattr(settings, self.total_setting))


# A client's second slot must leave at least this many deployment slots free.
ROOM_FOR_OTHERS = 2

# Up to two per client while the pool is roomy (see InFlight). The front end
# keeps one route in flight and sends the next only when it has an answer, so a
# single visitor never needs the second; it is there for several people behind
# one address.
ROUTING_IN_FLIGHT = InFlight(scope_id=1, per_client=2, total_setting="ROUTING_CONCURRENCY")

# Long rides (owner decision of 2026-09-26: planned, with a signed-out visitor
# asked to confirm first) hold a worker for up to 50 s each. How many run at
# once is the implementation's choice, not the owner's: at most one per client
# and one in the whole deployment, on top of the ordinary slots.
LONG_ROUTING_IN_FLIGHT = InFlight(
    scope_id=2,
    per_client=1,
    total_setting="LONG_ROUTING_CONCURRENCY",
    client_busy="A long ride is already being planned from this address; try again shortly.",
    deployment_busy="A long ride is already being planned; try again in a few seconds.",
)


def _client_lock_id(client: str) -> int:
    """The client's key as a signed 32-bit integer, the advisory lock's second key."""
    value = int(client[:8], 16)
    return value - (1 << 32) if value >= 1 << 31 else value


def _try(cursor, pair) -> bool:
    cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", list(pair))
    return bool(cursor.fetchone()[0])


def _take_one(cursor, candidates) -> tuple[int, int] | None:
    for pair in candidates:
        if _try(cursor, pair):
            return pair
    return None


def _held_in_class(cursor, lock_class: int) -> int:
    """How many advisory locks of `lock_class` are held in this database, by
    anyone. pg_locks shows the whole server's, and an advisory lock is per
    database, so another database's locks in the same class are not ours."""
    cursor.execute(
        "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND granted "
        "AND objsubid = 2 AND classid = %s::oid "
        "AND database = (SELECT oid FROM pg_database WHERE datname = current_database())",
        [lock_class],
    )
    return int(cursor.fetchone()[0])


def _release(pairs) -> None:
    """Unlock each pair; if one cannot be unlocked, close the connection.

    A session lock lasts as long as its connection, and with CONN_MAX_AGE the
    connection outlives the request, so a slot that could not be released
    would stay taken for that worker's next requests. Closing the connection
    ends every lock it still holds - whether the failure was a lost connection,
    which has released them already, or anything else - and Django opens a new
    one on next use.
    """
    for pair in pairs:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s, %s)", list(pair))
        except Exception:  # noqa: BLE001 - whatever failed, closing ends the locks
            logger.warning(
                "could not release in-flight slots %s; closing the connection to end them",
                pairs,
                exc_info=True,
            )
            try:
                connection.close()
            except Exception:  # noqa: BLE001 - Django has dropped the connection anyway
                logger.warning("closing the connection failed too", exc_info=True)
            return


def _busy(status: int, retry_after_s: int, message: str) -> JsonResponse:
    response = JsonResponse({"error": message}, status=status)
    response["Retry-After"] = str(retry_after_s)
    return response


def acquire(request, limit: InFlight) -> tuple[list, JsonResponse | None]:
    """Take a deployment slot and a client slot for `request` under `limit`.

    Returns the pairs held, to hand to `release`, and a refusal to send
    instead of running the request, or None. On a refusal nothing is held.
    The deployment slot is taken first, so the count of what is free already
    includes this request.
    """
    client = _client_lock_id(client_key(client_address(request)))
    held: list = []
    try:
        if _take(limit, client, held):
            return held, None
    except BaseException:
        # A failure between the two takes would otherwise leave the first
        # held on a connection that outlives the request.
        release(held)
        raise
    deployment_full = not held
    release(held)
    if deployment_full:
        return [], _busy(503, DEPLOYMENT_BUSY_RETRY_S, limit.deployment_busy)
    return [], _busy(429, CLIENT_BUSY_RETRY_S, limit.client_busy)


def _take(limit: InFlight, client: int, held: list) -> bool:
    """Take the slots into `held`; true if the request may run. False with
    nothing held means the deployment is full, false with the deployment slot
    held means the client is."""
    total_class = _LOCK_CLASS_TOTAL + limit.scope_id
    client_class = _LOCK_CLASS_CLIENT + limit.scope_id * 64
    with connection.cursor() as cursor:
        shared = _take_one(cursor, [(total_class, slot) for slot in range(limit.total)])
        if shared is None:
            return False
        held.append(shared)
        if _try(cursor, (client_class, client)):
            held.append((client_class, client))
            return True
        free_after = limit.total - _held_in_class(cursor, total_class)
        if free_after >= ROOM_FOR_OTHERS:
            mine = _take_one(
                cursor,
                [(client_class + slot, client) for slot in range(1, limit.per_client)],
            )
            if mine is not None:
                held.append(mine)
                return True
    return False


def release(held) -> None:
    _release(held)


def in_flight_limited(limit: InFlight):
    """A view decorator: hold `limit`'s slots for the request, or refuse it -
    429 when this client already has its routes running, 503 when the
    deployment has `total` running."""

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            held, refusal = acquire(request, limit)
            if refusal is not None:
                return refusal
            try:
                return view(request, *args, **kwargs)
            finally:
                release(held)

        return wrapped

    return decorator
