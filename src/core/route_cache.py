"""A short-term cache of route answers (v0.7.0, "Faster routing" step 5).

Re-opening a plan, Undo, the Home chip and Go's early start (step 4) ask for the same
route again within minutes; each used to be a whole plan. An answer is kept here for
`TTL_S` (2 minutes) and given again for an identical request, so those are instant.

**At most 2 minutes** (Stephen 2026-10-29): a route's start is often "From my location", which
counts as a live location, and nothing of that kind stays on the server longer than 2 minutes
(core.ride_presence, the same rule). The cache cannot tell such a start from any other, so
every answer goes at 2 minutes, and no setting keeps one longer (`ttl_s`).

**The key** is everything the answer is made from:

- the whole request as validated (`RouteIn`: the points, the ride type and every dial,
  the closures routed through, the via points), less `quick`, which only says how much
  of the plan to wait for (a full answer kept answers a quick request too); the points
  are rounded to 1e-4 degrees (about 10 m), the plan's "same points rounded to ~10 m";
- whether it was planned as a long ride, or a long calm plan;
- the ride time: the setting asked for, or the one of the moment where none was (so a
  plan made just before the evening rush is not given once the rush starts), and the
  instant the router is asked about (`routing.planning_time`), and whether the closures
  are matched at now or at that instant (`workzones.ride_moment`);
- the live segment table and its edit generation (`stress_tiles.live_state`): a
  promotion, or any road-panel edit or undo (`stress_edits.bump_generation`), is a new
  key, so no answer from before it is given again;
- the closures (`core.workzones.snapshot`): every zone with its kind and window, each
  feed's status and read time, and the notices, so a refresh that changes any of them
  is a new key; and an answer is not kept past the next moment a zone starts or ends
  (`valid_until`), nor past the next local midnight (the closures' "today" words);
- the approved Avoid junctions, junction ratings and Mass Ride hazards, which the plan
  reads at request time.

**Not kept:** Bikeshare and the transit ride types (live availability and departures);
an answer from another graph than the ride's own (a weekend or off-road router that was
down: it is answered again once that router is back); and an answer the budget cut short
(a router call that failed for want of time or an answer, `timing.Timings.failures`, or
a search that stopped for time), so a retry can do better; nor a plan the rider cancelled
(`core.plan_cancel`), which is answered 409 and may have been cut short by the cancel.

**Where it is kept.** Where `settings.CACHES` has a `routes` cache
(`ROUTE_CACHE_LOCATION`, a memcached the api's workers share; audit S14, the owner's
sign-off of 2026-10-27 for a ~16 MB memcached on beta), every worker reads and keeps
answers there, so a repeat finds the answer whichever worker takes it. The answer is kept
as compressed JSON, never pickle (anything on the compose network can write to memcached);
one whose stored form is past memcached's 1 MB item limit is not kept there (it is planned
again when asked), and a cache that is down, full or slow is passed over in silence: the
plan is made as if nothing were kept. Its keys also carry the running code's fingerprint,
so an answer made by the release before a deploy is never given by the one after it.
memcached runs with no disk and logs nothing, so nothing in it is a location in a log or
on disk.

Without one (the tests, a stack with no memcached), one cache per process as before
(gunicorn's workers do not share it), at most `MAX_ENTRIES` answers, least recently
used first out. Nothing in it is a location in a log or on disk; it lives only in the
worker's memory, like the request it answers.
"""

from __future__ import annotations

import contextvars
import functools
import hashlib
import json
import logging
import threading
import time
import zlib
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

TTL_S = 2 * 60
MAX_ENTRIES = 128
# Points are compared at this many decimal places of a degree: 1e-4 is about 11 m of
# latitude and 9 m of longitude here.
POINT_PLACES = 4

FULL = "full"
QUICK = "quick"

# The shared cache's alias in `settings.CACHES` (config.settings.caches_for).
SHARED = "routes"
# memcached's largest item is 1 MB (its `-I` default); a stored answer past this, which
# leaves room for the key and the item's header, is not sent at all.
MAX_SHARED_BYTES = 1024 * 1024 - 4096


@dataclass
class _Entry:
    body: dict
    expires: float


_lock = threading.Lock()
_entries: OrderedDict[tuple[str, str], _Entry] = OrderedDict()


def ttl_s() -> float:
    """How long an answer is kept: `settings.ROUTE_CACHE_TTL_S`, `TTL_S` unless set, and
    never past `TTL_S` (the 2-minute rule); 0 turns the cache off (the test suite, whose
    tests change the segment table under a plan directly, without the edit generation an
    edit bumps)."""
    from django.conf import settings

    try:
        return min(float(TTL_S), max(0.0, float(getattr(settings, "ROUTE_CACHE_TTL_S", TTL_S))))
    except (TypeError, ValueError):
        return float(TTL_S)


def clear() -> None:
    """Forget every answer (the tests; an operator's shell): the shared cache's too."""
    with _lock:
        _entries.clear()
    shared = _shared()
    if shared is not None:
        try:
            shared.clear()
        except Exception:  # noqa: BLE001 - a cache that is down holds nothing to clear
            logger.info("the shared route cache could not be cleared", exc_info=True)


def size() -> int:
    """The answers this process keeps itself (none where the cache is shared)."""
    with _lock:
        return len(_entries)


def _shared():
    """The shared cache (`SHARED` in `settings.CACHES`), or None where there is none."""
    from django.conf import settings
    from django.core.exceptions import ImproperlyConfigured

    try:
        if SHARED not in settings.CACHES:
            return None
    except ImproperlyConfigured:  # a module that never loads Django (the tests' teardown)
        return None
    from django.core.cache import caches

    try:
        return caches[SHARED]
    except Exception:  # noqa: BLE001 - an image without pymemcache: each worker keeps its own
        if not _unusable:
            _unusable.append(True)
            logger.warning(
                "the shared route cache cannot be used; each worker keeps its own", exc_info=True
            )
        return None


# Set once the shared cache could not be made, so that is logged once a process.
_unusable: list[bool] = []


_code_memo: list[str] = []


def _code() -> str:
    """A fingerprint of the running code (`core` and `routemaker`), made once a process:
    the shared cache outlives a deploy, and an answer is the code's as much as the
    request's."""
    if not _code_memo:
        digest = hashlib.sha256()
        root = Path(__file__).resolve().parent.parent
        for package in ("core", "routemaker"):
            for path in sorted((root / package).rglob("*.py")):
                digest.update(str(path.relative_to(root)).encode())
                digest.update(path.read_bytes())
        _code_memo.append(digest.hexdigest()[:16])
    return _code_memo[0]


def _shared_name(key: str, kind: str) -> str:
    return f"{_code()}:{key}:{kind}"


def _shared_get(shared, key: str, kinds: tuple[str, ...]) -> dict | None:
    try:
        found = shared.get_many([_shared_name(key, kind) for kind in kinds])
        for kind in kinds:
            stored = found.get(_shared_name(key, kind))
            if isinstance(stored, bytes):
                return json.loads(zlib.decompress(stored))
    except Exception:  # noqa: BLE001 - a cache that fails is passed over: the plan is made
        logger.info("the shared route cache could not be read", exc_info=True)
    return None


def _shared_put(shared, key: str, kind: str, body: dict, ttl: float) -> None:
    # memcached keeps whole seconds; never past the answer's life.
    timeout = int(ttl)
    try:
        if kind == FULL:
            # The full plan supersedes its first route.
            shared.delete(_shared_name(key, QUICK))
        if timeout < 1:
            return
        stored = zlib.compress(json.dumps(body, separators=(",", ":")).encode(), 1)
        if len(stored) > MAX_SHARED_BYTES:
            logger.info(
                "an answer of %d bytes is too large for the shared route cache", len(stored)
            )
            return
        shared.set(_shared_name(key, kind), stored, timeout)
    except Exception:  # noqa: BLE001 - an answer not kept is planned again when asked
        logger.info("the shared route cache could not keep an answer", exc_info=True)


def _clock() -> float:
    return time.monotonic()


def _later(delay: float, run: Callable[[], None]) -> None:
    timer = threading.Timer(delay, run)
    timer.daemon = True
    timer.start()


# A sweep is due: one at a time, so a busy worker starts no pile of timers.
_sweep_due = False


def _prune(now: float) -> None:
    """Drop every expired answer (called with the lock held)."""
    for gone in [k for k, e in _entries.items() if e.expires <= now]:
        del _entries[gone]


def _sweep() -> None:
    """Drop what has expired even when nothing asks again, so a quiet worker keeps no route,
    and its start, past its 2 minutes (as core.weather and core.ride_presence sweep)."""
    global _sweep_due
    with _lock:
        _sweep_due = False
        now = _clock()
        _prune(now)
        if _entries:
            _schedule(max(0.0, min(e.expires for e in _entries.values()) - now))


def _schedule(delay: float) -> None:
    """A sweep in `delay` seconds, unless one is due (called with the lock held)."""
    global _sweep_due
    if not _sweep_due:
        _sweep_due = True
        _later(delay, _sweep)


def get(key: str, quick: bool = False) -> dict | None:
    """The answer kept for `key`: the full plan's, or for a quick request the first
    route's where no full plan is kept. None where neither is, or it has expired."""
    kinds = (FULL, QUICK) if quick else (FULL,)
    shared = _shared()
    if shared is not None:
        return _shared_get(shared, key, kinds)
    now = _clock()
    with _lock:
        _prune(now)
        for kind in kinds:
            entry = _entries.get((key, kind))
            if entry is None:
                continue
            if entry.expires <= now:
                del _entries[(key, kind)]
                continue
            _entries.move_to_end((key, kind))
            return entry.body
    return None


def put(key: str, body: dict, valid_s: float = TTL_S) -> None:
    """Keep `body` for `key`, for `valid_s` seconds at most (never past `TTL_S`)."""
    kind = QUICK if body.get("provisional") else FULL
    ttl = max(0.0, min(float(valid_s), ttl_s()))
    if ttl <= 0:
        return
    shared = _shared()
    if shared is not None:
        _shared_put(shared, key, kind, body, ttl)
        return
    with _lock:
        now = _clock()
        _prune(now)
        _entries[(key, kind)] = _Entry(body, now + ttl)
        _schedule(ttl)
        _entries.move_to_end((key, kind))
        if kind == FULL:
            # The full plan supersedes its first route.
            _entries.pop((key, QUICK), None)
        while len(_entries) > MAX_ENTRIES:
            _entries.popitem(last=False)


# --- The key -------------------------------------------------------------------------


def _rounded(points: list) -> list:
    return [
        [round(float(lon), POINT_PLACES), round(float(lat), POINT_PLACES)] for lon, lat in points
    ]


def request_part(fields: dict) -> dict:
    """The request's own part of the key: every field but `quick`, points rounded."""
    part = {k: v for k, v in fields.items() if k != "quick"}
    part["points"] = _rounded(part.get("points") or [])
    return part


def _edits_part() -> list:
    """The live table, its optional columns and its edit generation."""
    from . import stress_tiles

    oid, columns, generation = stress_tiles.live_state()
    return [oid, sorted(columns), generation]


_closures_memo: tuple[object, str, tuple] | None = None


def _closures_part(now: datetime) -> tuple[str, datetime | None]:
    """A digest of the closures the planner reads, and the next moment after `now` at
    which one of them starts or ends (None: none does)."""
    global _closures_memo
    from routemaker import deer_closures

    from . import workzones

    found = workzones.snapshot()
    memo = _closures_memo
    if memo is not None and memo[0] is found:
        digest, moments = memo[1], memo[2]
    else:
        rows = sorted(
            json.dumps(zone.to_json(), sort_keys=True, default=str) for zone in found.zones
        )
        made = {
            "zones": rows,
            "status": sorted(found.status.items()),
            "read_at": sorted((k, str(v)) for k, v in found.read_at.items()),
            "notices": [repr(notice) for notice in found.notices],
        }
        digest = hashlib.sha256(json.dumps(made, sort_keys=True).encode()).hexdigest()
        moments = tuple(
            sorted(
                {
                    moment
                    for zone in found.zones
                    for moment in (zone.start, zone.end)
                    if isinstance(moment, datetime)
                }
                # A deer-management notice comes in an hour before its window (v0.12.3).
                | deer_closures.moments(found.notices)
            )
        )
        _closures_memo = (found, digest, moments)
    upcoming = next((m for m in moments if m > now), None)
    return digest, upcoming


# The approvals one request has read (`approval`), by name: the key and the plan it misses
# read the same ones, once. None outside `reads_approvals_once`.
_approvals_read: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "approvals_read", default=None
)


def reads_approvals_once(fn):
    """`fn` (one route request) with each approval read at most once in it (`approval`)."""

    @functools.wraps(fn)
    def run(*args, **kwargs):
        token = _approvals_read.set({})
        try:
            return fn(*args, **kwargs)
        finally:
            _approvals_read.reset(token)

    return run


def approval(name: str, read: Callable[[], object]):
    """`read()`, the approval `name`, as this request first read it (`reads_approvals_once`);
    read afresh outside one."""
    memo = _approvals_read.get()
    if memo is None:
        return read()
    if name not in memo:
        memo[name] = read()
    return memo[name]


def avoid_list() -> tuple:
    """The approved Avoid junctions (`avoid_junctions.approved`)."""
    from . import avoid_junctions

    return approval("avoid", avoid_junctions.approved)


def junction_ratings() -> tuple:
    """The approved rider ratings of junctions (`junction_suggestions.approved_ratings`)."""
    from .junction_suggestions import approved_ratings

    return approval("ratings", approved_ratings)


def mass_ride_hazards() -> dict:
    """A Mass Ride's approved hazards (`mass_hazards.approved`)."""
    from . import mass_hazards

    return approval("hazards", mass_hazards.approved)


def beacons() -> tuple:
    """The active flashing beacons (`flashing_signals.active`)."""
    from . import flashing_signals

    return approval("beacons", flashing_signals.active)


def _approved_part(preset: str) -> list:
    """The approvals the plan reads at request time, read as the plan reads them."""
    hazards = []
    if preset == "mass-ride":
        for way, hazard in sorted(mass_ride_hazards().items()):
            fields = {k: str(v) for k, v in vars(hazard).items() if not k.startswith("_")}
            hazards.append([way, sorted(fields.items())])
    return [
        [repr(item) for item in avoid_list()],
        [repr(item) for item in junction_ratings()],
        hazards,
        [repr(item) for item in beacons()],
    ]


@dataclass(frozen=True)
class Key:
    key: str
    # Seconds the answer may be kept: TTL_S, or less where a closure starts or ends,
    # or the day turns, before then.
    valid_s: float


def key_for(
    fields: dict, when: str, planning_at: str, long_plan: str, now: datetime | None = None
) -> Key | None:
    """The key for a request (`fields`: the validated request), planned with the ride
    time `when` (the setting used) and `planning_at` (the router's instant), as
    `long_plan` ("", "long_ride" or "long_calm"). None where the state it depends on
    cannot be read: that request is planned, and not kept."""
    from routemaker import ridetime

    if ttl_s() <= 0:
        return None
    now = now or datetime.now(UTC)
    try:
        closures, next_change = _closures_part(now)
        made = {
            "request": request_part(fields),
            "when": when,
            "planning_at": planning_at,
            # The moment closures are matched at (`workzones.ride_moment`): now while the dial
            # is on the setting of the moment, else `planning_at`. A dial set to "weekday peak"
            # is now at 8:55 and next Tuesday's 8:00 at 9:05, with the same `when`.
            "ride_now": ridetime.when_at(now) == when,
            "long": long_plan,
            "edits": _edits_part(),
            "closures": closures,
            "approved": _approved_part(str(fields.get("preset"))),
        }
        digest = hashlib.sha256(json.dumps(made, sort_keys=True, default=str).encode()).hexdigest()
    except Exception:  # noqa: BLE001 - a plan is never refused for want of its key
        logger.warning("the route cache key could not be made", exc_info=True)
        return None
    valid_s = ttl_s()
    if next_change is not None:
        valid_s = min(valid_s, (next_change - now).total_seconds())
    local = now.astimezone(ridetime.ZONE)
    midnight = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    valid_s = min(valid_s, (midnight - local).total_seconds())
    return Key(digest, valid_s)


def keepable(body: dict, own_variant: str, failures: int) -> bool:
    """Whether an answer may be kept: planned on the ride's own graph, and not cut short
    by the budget (a failed or skipped router call, or a search or pass that stopped for
    time)."""
    if failures:
        return False
    if body.get("variant") != own_variant:
        return False
    calm_search = body.get("calm_search") or {}
    if calm_search.get("limited") == "time":
        return False
    for field in ("hills_seek", "hills_avoid", "hills_tolerate"):
        if (body.get(field) or {}).get("limited") == "timed_out":
            return False
    # The passes that give up on the clock without a router call to fail: the router's
    # alternatives, the dodge pass, the hill seek and the way round an Avoid junction.
    stopped = (
        (calm_search.get("alternates") or {}).get("limited"),
        (body.get("dodges") or {}).get("limited"),
        ((body.get("hills_seek") or {}).get("climb_seek") or {}).get("limited"),
        (body.get("avoid_search") or {}).get("alternate"),
    )
    return "time" not in stopped
