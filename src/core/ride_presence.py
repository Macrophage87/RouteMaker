"""Mass Ride and Group Ride links: the other riders as dots, and tap-to-send alerts (v0.7.0 plan,
"Mass ride and Group Ride: see the others on the route" and "... tap to send an issue").

Every ride is sealed end to end (Stephen 2026-10-29: "Encrypted rides send GPS accurate numbers.
All rides should have a key."; frontend/src/lib/rideSeal.ts). Every ride link carries a secret in
its fragment, which no browser sends to a server. Each phone seals its dot (with its role), its
alerts and the leader's path with a key from that secret before sending, and the ride id is
derived from it one way. Here each is opaque text: nothing in it can be read or checked, and a
post in plain numbers is refused. The phones keep to the map's area and merge matching alerts
themselves. What they seal: a dot and an alert's spot to 6 decimals of a degree (about 4 in,
0.1 m; rideSeal.ts `sealedSpot`), the leader's route and ridden path thinned to at most
600 points at 5 decimals (about 3 ft, 1 m; rideGroup.ts `thinLine`, `PATH_MAX_POINTS`).

The server reads none of it, except on a ride whose key it made or was given and keeps: a ride
post's ride (core.route_posts) and a ride link the site's assistant planned or opened (its
drafts, core.connector).

Privacy is the shape of this module:

- A sealed value is kept only in memory and dropped 2 minutes after it was sent. It is never
  written to the database, to a file on disk or to a log: nothing here logs at all, and the
  endpoints take it in a POST body (the access log carries no body).
- A rider is a random per-ride token the device makes (it changes each ride); no account, name or
  address is kept with it. A ride is an id derived from the link's secret, so the server never
  holds the route either.
- Nothing stays longer than 2 minutes (Stephen 2026-10-22: "For privacy, nothing stays on the
  server for more than 2 min"): a dot, a leader's path and an alert each 2 minutes after it was
  sent, and a rider's token and counts 2 minutes after its phone last asked or sent anything.
  Each api process sweeps every ride for this every `SWEEP_S`, so a ride nobody opens again is
  emptied as well.
- What the server still does: the limits (per token and per ride), the leader's mark on a
  broadcast's sharer, a fresh order of the dots on every read, and caps on each sealed value's
  size.

"Memory" across the api's gunicorn workers: each worker is its own process, so a dict in one is
not seen by the others. The shared store is a directory on a tmpfs (by default /dev/shm, which is
RAM, never disk), one small JSON file per ride under an exclusive lock. `RIDE_PRESENCE_DIR`
names it; empty (the test suite) keeps everything in this process's memory. A directory that is
not on a tmpfs is refused and the process falls back to its own memory, so a misconfiguration can
make dots split between workers but can never put a position on disk.
"""

from __future__ import annotations

import contextlib
import copy
import fcntl
import hashlib
import json
import math
import os
import re
import secrets
import threading
import time
from collections.abc import Callable, Iterator
from random import SystemRandom

# How long a dot lives after its last reading (the plan: "kept only in server memory for 2
# minutes"; the front end draws it gone at the same age).
DOT_TTL_S = 120
# How often a phone sends its dot and asks for the others: every 2 s while 20 or fewer share
# (Stephen 2026-10-31, "If we limit to maybe 20 people at once, how low could that get?": below 2 s
# the dot moves less than its GPS wanders), every 5 s up to 300, slower on a very big ride
# (Stephen 2026-10-31: "15 seconds is not enough to see slowdowns", "Make as cheap as possible and
# try to get it down", "settle where it makes sense"). Each write rewrites the
# ride's whole file under its one lock, and its cost grows with the riders in it (measured
# 2026-10-31 on tmpfs: about 0.03 ms at 50 riders, 1 ms at 300, 3 ms at 1,000, 10 ms at 3,000;
# the size of a dot hardly counts), so the pace keeps the lock well under half busy. The read
# answer carries the pace ("every_s") and the phone follows it.
PACE_S = ((20, 2), (300, 5), (1000, 10))
SLOWEST_PACE_S = 15
# One who only watches (no dot of its own: on a big ride, most riders while its marshals share,
# Stephen 2026-10-31) reads no faster than this: each read is a request to the api (about 1 ms of
# its CPU measured, before nginx), so 1,000 watching at 5 s is some 200 a second.
WATCH_PACE_S = 5
# A position sooner than this after the last is refused (429), at any pace: well under the 2 s
# pace, so a post held up on a phone's network is not refused when the next arrives quickly (the
# ride's own write count and the address limit bound a phone that posts this often).
MIN_POST_INTERVAL_S = 0.5
# A device asks for the dots no sooner than this (429).
MIN_POLL_INTERVAL_S = 1
# The most anything is kept: a token (and its counts) is forgotten this long after its phone last
# read or sent anything; a phone in front reads every 2 to 15 s, so its limits hold while it rides.
KEEP_S = 120
# How often a read writes the ride's own note that its phone still reads (well inside KEEP_S).
POLL_STAMP_S = 60
# Bounds on memory and on the ride's lock, whatever a client sends: 3,000 riders kept one ride's
# lock busier than its time even at 15 s (the measures above). At 1,500 and 15 s positions alone
# hold it about half the time (100 a second at about 5 ms); reads (shared, but writers wait for
# them), poll stamps and prunes come on top, so this is the most, not a comfortable size.
MAX_RIDERS_PER_RIDE = 1500
MAX_RIDES = 500
# A broadcast's leader path (Stephen 2026-10-22: "Rebroadcast the route every 2 min or when it
# changes, not keeping it on the server"): the leader's phone sends the route it is riding and
# the path it has ridden, about every 2 minutes and whenever the route changes; each is dropped
# 2 minutes after it was sent, as a dot is, so a phone that stops sending leaves nothing behind.
PATH_TTL_S = DOT_TTL_S
MIN_PATH_INTERVAL_S = 20
PATHS_PER_RIDE = 3
PATH_BODY_BYTES = 48 * 1024
# A sealed dot, alert or path (frontend/src/lib/rideSeal.ts): base64url of the nonce and the
# ciphertext, at most this long.
SEALED = re.compile(r"^[A-Za-z0-9_-]{24,}$")
SEALED_MAX = 1400
SEALED_PATH_MAX = PATH_BODY_BYTES - 256
# Alerts live on one ride at a time; a newer one past this drops the oldest.
LIVE_ALERTS_PER_RIDE = 20

# Alerts (the plan's limits; the phones merge matching ones, frontend rideSeal.ts mergeAlerts).
ALERT_TTL_S = KEEP_S
ALERT_MIN_INTERVAL_S = 60
ALERTS_PER_RIDE = 10
# Writes to one ride (positions, paths, alerts), counted in the ride's own state so the count goes
# with the ride rather than outliving it in the database: at the pace above a ride's positions are
# at most 6,000 a minute (1,000 riders every 10 s, 1,500 every 15 s; 300 every 5 s is 3,600), so
# 7,500 leaves room for alerts and paths.
RIDE_WRITES_PER_MINUTE = 7500
RIDE_WRITES_WINDOW_S = 60
# How often each api process sweeps every ride for what has outlived its 2 minutes, so a ride
# nobody opens again is emptied too, not only one a phone still reads (v0.12.0 end review).
SWEEP_S = 10

_SHUFFLE = SystemRandom()

RIDE_ID = re.compile(r"^[0-9a-f]{64}$")
TOKEN = re.compile(r"^[0-9a-f]{32}$")
LEADER_KEY = TOKEN


def leader_key(token: str) -> str:
    """The ride leader's mark in a broadcast link: the first 32 hex digits of the SHA-256 of the
    sharer's token. A reader holding it learns which dot is the sharer's, and nothing else; only the
    sharer, who holds the token, can post as that dot (Stephen 2026-10-22: "the ride leader is the
    person who shared")."""
    return hashlib.sha256(token.encode("ascii")).hexdigest()[:32]


class Refused(Exception):
    """A request this module will not take, with its status and a sentence for the rider."""

    def __init__(self, status: int, message: str, retry_after_s: int | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.retry_after_s = retry_after_s


# ---- the store -----------------------------------------------------------------------------


def _on_tmpfs(path: str) -> bool:
    """Whether `path` is on a tmpfs (RAM), by the longest matching mount point."""
    try:
        with open("/proc/mounts", encoding="utf-8") as mounts:
            best, kind = "", ""
            real = os.path.realpath(path)
            for line in mounts:
                parts = line.split()
                if len(parts) < 3:
                    continue
                point = parts[1]
                inside = real == point or real.startswith(point.rstrip("/") + "/")
                if inside and len(point) > len(best):
                    best, kind = point, parts[2]
            return kind == "tmpfs"
    except OSError:
        return False


class MemoryStore:
    """This process's memory: the test suite, and the fallback."""

    def __init__(self) -> None:
        self._rides: dict[str, dict] = {}
        self._lock = threading.Lock()

    @contextlib.contextmanager
    def ride(self, ride_id: str, create: bool = True) -> Iterator[dict]:
        """The ride's state to change. Without `create`, a ride not kept yet is an empty state
        that is not kept afterwards either (a read takes no room)."""
        with self._lock:
            if ride_id not in self._rides:
                if not create:
                    yield _empty()
                    return
                if len(self._rides) >= MAX_RIDES:
                    _prune_rides(self._rides)
                    if len(self._rides) >= MAX_RIDES:
                        raise _full()
            state = self._rides.setdefault(ride_id, _empty())
            try:
                yield state
            finally:
                if _is_empty(state):
                    self._rides.pop(ride_id, None)

    @contextlib.contextmanager
    def peek(self, ride_id: str) -> Iterator[dict]:
        """The ride's state to read only (a ride not kept yet is an empty state): nothing done to
        it is kept."""
        with self._lock:
            state = self._rides.get(ride_id)
            yield copy.deepcopy(state) if state is not None else _empty()

    def clear(self) -> None:
        with self._lock:
            self._rides.clear()
        with _polls_lock:
            _polls.clear()

    def sweep(self, now: float | None = None) -> None:
        """Prune every ride, and drop each one left empty."""
        now = time.time() if now is None else now
        with self._lock:
            for ride_id in list(self._rides):
                _prune(self._rides[ride_id], now)
                if _is_empty(self._rides[ride_id]):
                    del self._rides[ride_id]


def _full() -> Refused:
    return Refused(503, "Too many rides are sharing right now; try again shortly.")


def _idle(state: dict) -> bool:
    """A pruned ride with no rider's position from the last 2 minutes: the first to go when the
    store is full, so a new ride takes the place of one nobody is riding."""
    return not any("at" in r for r in state["riders"].values())


def _prune_rides(rides: dict[str, dict]) -> None:
    now = time.time()
    for ride_id in list(rides):
        _prune(rides[ride_id], now)
        if _is_empty(rides[ride_id]) or _idle(rides[ride_id]):
            del rides[ride_id]


class TmpfsStore:
    """One JSON file per ride in a tmpfs directory, read and written under an exclusive lock, so
    every gunicorn worker sees the same dots. RAM only: the directory must be on a tmpfs."""

    # Opens of a ride's file a lock may take, where each one it got was of a file unlinked under it.
    LOCK_TRIES = 5

    def __init__(self, directory: str) -> None:
        self.directory = directory

    @classmethod
    def _locked(cls, path: str, shared: bool = False) -> int:
        """`path` opened and locked: a descriptor of the file at `path` now. A process that
        waited for the lock while its holder emptied the ride and unlinked the file would hold
        an orphan no other process can see; so after the lock the descriptor's inode is compared
        with the path's, and the open is tried again where they differ."""
        for _ in range(cls.LOCK_TRIES):
            fd = os.open(path, os.O_RDONLY if shared else os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
                try:
                    same = os.fstat(fd).st_ino == os.stat(path).st_ino
                except FileNotFoundError:
                    same = False
            except BaseException:
                os.close(fd)
                raise
            if same:
                return fd
            os.close(fd)
        raise Refused(503, "The ride is busy; try again shortly.")

    def _count(self) -> int:
        try:
            return sum(1 for n in os.listdir(self.directory) if n.endswith(".json"))
        except OSError:
            return 0

    def _evict_idle(self) -> None:
        """Drop each ride with no position from the last 2 minutes, each under its own lock."""
        try:
            names = [n for n in os.listdir(self.directory) if n.endswith(".json")]
        except OSError:
            return
        now = time.time()
        for name in names:
            path = os.path.join(self.directory, name)
            try:
                fd = self._locked(path)
            except (OSError, Refused):
                continue
            try:
                with os.fdopen(os.dup(fd), "r", encoding="utf-8") as handle:
                    try:
                        state = json.loads(handle.read() or "null") or _empty()
                    except ValueError:
                        state = _empty()
                _prune(state, now)
                if _is_empty(state) or _idle(state):
                    os.unlink(path)
            except (OSError, KeyError, TypeError, AttributeError):
                pass
            finally:
                os.close(fd)

    def sweep(self, now: float | None = None) -> None:
        """Prune every ride's file, each under its own lock: a file left empty is unlinked, and
        one that lost anything is written back without it."""
        try:
            names = [n for n in os.listdir(self.directory) if n.endswith(".json")]
        except OSError:
            return
        now = time.time() if now is None else now
        for name in names:
            path = os.path.join(self.directory, name)
            try:
                fd = self._locked(path)
            except (OSError, Refused):
                continue
            try:
                with os.fdopen(os.dup(fd), "r+", encoding="utf-8") as handle:
                    raw = handle.read()
                    try:
                        state = json.loads(raw or "null") or _empty()
                    except ValueError:
                        state = _empty()
                    _prune(state, now)
                    if _is_empty(state):
                        os.unlink(path)
                        continue
                    out = json.dumps(state, separators=(",", ":"))
                    if out != raw:
                        handle.seek(0)
                        handle.truncate()
                        handle.write(out)
                        handle.flush()
            except (OSError, KeyError, TypeError, AttributeError):
                pass
            finally:
                os.close(fd)

    @contextlib.contextmanager
    def ride(self, ride_id: str, create: bool = True) -> Iterator[dict]:
        """As MemoryStore.ride."""
        path = os.path.join(self.directory, f"{ride_id}.json")
        if not os.path.exists(path):
            if not create:
                yield _empty()
                return
            if self._count() >= MAX_RIDES:
                self._evict_idle()
                if self._count() >= MAX_RIDES:
                    raise _full()
        fd = self._locked(path)
        try:
            with os.fdopen(os.dup(fd), "r+", encoding="utf-8") as handle:
                raw = handle.read()
                try:
                    state = json.loads(raw) if raw else _empty()
                except ValueError:
                    state = _empty()
                try:
                    yield state
                except Refused:
                    # Refused after counting (too soon, too many alerts): the count is kept, as in
                    # MemoryStore, so refused posts still count against the ride's lock budget.
                    self._write_back(path, handle, raw, state)
                    raise
                self._write_back(path, handle, raw, state)
        finally:
            os.close(fd)

    @staticmethod
    def _write_back(path: str, handle, raw: str, state: dict) -> None:
        if _is_empty(state):
            os.unlink(path)
        else:
            out = json.dumps(state, separators=(",", ":"))
            if out != raw:
                handle.seek(0)
                handle.truncate()
                handle.write(out)
                handle.flush()

    @contextlib.contextmanager
    def peek(self, ride_id: str) -> Iterator[dict]:
        """As MemoryStore.peek: under a shared lock, so the ride's readers never wait on one
        another, and the file is never written (2026-10-31: a read used to rewrite the whole ride
        to stamp its poll)."""
        path = os.path.join(self.directory, f"{ride_id}.json")
        try:
            fd = self._locked(path, shared=True)
        except FileNotFoundError:
            yield _empty()
            return
        try:
            with os.fdopen(os.dup(fd), "r", encoding="utf-8") as handle:
                raw = handle.read()
            try:
                state = json.loads(raw) if raw else _empty()
            except ValueError:
                state = _empty()
        finally:
            os.close(fd)
        yield state


_store: MemoryStore | TmpfsStore | None = None
_store_for: str | None = None


def _sweep_forever(target: MemoryStore | TmpfsStore) -> None:
    """Sweep `target` every `SWEEP_S` while it is still this process's store."""
    import time as clock  # not this module's `time`, which the suite swaps for a fake clock

    while True:
        clock.sleep(SWEEP_S)
        if _store is not target:
            return
        try:
            target.sweep(clock.time())
        except Exception:  # noqa: BLE001 - the sweeper must outlive any one bad sweep
            pass
        _forget_polls(clock.time())


def _start_sweeper(target: MemoryStore | TmpfsStore) -> None:
    """A daemon thread, so it never holds the process open; one per gunicorn worker, each
    started with the worker's first store, after the fork."""
    threading.Thread(
        target=_sweep_forever, args=(target,), name="ride-presence-sweep", daemon=True
    ).start()


def store():
    """The store for `settings.RIDE_PRESENCE_DIR`: a tmpfs directory, or this process's memory."""
    from django.conf import settings

    global _store, _store_for
    directory = getattr(settings, "RIDE_PRESENCE_DIR", "") or ""
    if _store is None or _store_for != directory:
        chosen: MemoryStore | TmpfsStore = MemoryStore()
        if directory:
            try:
                os.makedirs(directory, mode=0o700, exist_ok=True)
                if _on_tmpfs(directory):
                    chosen = TmpfsStore(directory)
            except OSError:
                pass
        _store, _store_for = chosen, directory
        with _polls_lock:
            _polls.clear()
        if directory:
            # The deployed api (the test suite, with no directory, sweeps by hand).
            _start_sweeper(chosen)
    return _store


# ---- a ride's state --------------------------------------------------------------------------


def _empty() -> dict:
    return {"riders": {}, "alerts": []}


def _is_empty(state: dict) -> bool:
    return not state["riders"] and not state["alerts"]


def _prune(state: dict, now: float) -> bool:
    """Drop what has outlived its time; answers whether anything went."""
    changed = False
    for token, rider in list(state["riders"].items()):
        last = max(rider.get(k, 0) for k in ("since", "posted", "polled", "alerted", "path_posted"))
        if now - last > KEEP_S:
            del state["riders"][token]
            changed = True
            continue
        if "at" in rider and now - rider["at"] > DOT_TTL_S:
            # The position goes at 2 minutes; the token's counts stay for the ride's limits.
            # (lon, lat and role: what a server before every ride was sealed kept in plain.)
            for key in ("at", "sealed", "lon", "lat", "role"):
                rider.pop(key, None)
            changed = True
        if "path" in rider and now - rider["path"]["at"] > PATH_TTL_S:
            del rider["path"]
            changed = True
    # An alert lasts 2 minutes from when it was sent.
    kept = [a for a in state["alerts"] if now - a["last"] <= ALERT_TTL_S]
    if len(kept) != len(state["alerts"]):
        state["alerts"] = kept
        changed = True
    writes = state.get("writes")
    if writes and now - writes[0] >= RIDE_WRITES_WINDOW_S:
        del state["writes"]
        changed = True
    return changed


def _count_in(state: dict, t: float) -> int:
    """Count one write against the ride whose state this is: 0 when it may go ahead, else the
    seconds to wait. The count lives in the ride's state for its one-minute window and goes with
    the ride."""
    window = math.floor(t / RIDE_WRITES_WINDOW_S) * RIDE_WRITES_WINDOW_S
    writes = state.get("writes")
    if not writes or writes[0] != window:
        writes = [window, 0]
    writes[1] += 1
    state["writes"] = writes
    if writes[1] > RIDE_WRITES_PER_MINUTE:
        return max(1, math.ceil(window + RIDE_WRITES_WINDOW_S - t))
    return 0


def count_write(ride_id: str, now: Callable[[], float] = time.time) -> int:
    """As `_count_in`, under the ride's own lock (for a write counted on its own)."""
    t = now()
    with store().ride(ride_id) as state:
        _prune(state, t)
        return _count_in(state, t)


def _counted(state: dict, t: float) -> None:
    """Count this write in the same locked turn as the write itself (2026-10-31: a write used to
    take the ride's lock twice, once to count and once to write); refused once the ride is busy."""
    wait = _count_in(state, t)
    if wait:
        raise Refused(429, "This ride is busy; try again shortly.", wait)


def pace_s(riders: int) -> int:
    """Seconds between a phone's dots, and between its reads, on a ride with this many riders."""
    for most, every in PACE_S:
        if riders <= most:
            return every
    return SLOWEST_PACE_S


def _rider(state: dict, token: str, now: float) -> dict:
    rider = state["riders"].get(token)
    if rider is None:
        if len(state["riders"]) >= MAX_RIDERS_PER_RIDE:
            raise Refused(503, "This ride has too many riders sharing right now.")
        rider = state["riders"][token] = {"since": now}
    return rider


def _check(ride_id: str, token: str) -> None:
    if not RIDE_ID.match(ride_id or ""):
        raise Refused(404, "Not a ride link.")
    if not TOKEN.match(token or ""):
        raise Refused(400, "The ride token is missing.")


# A post in plain numbers (an older page): refused, since every ride link now carries a key.
PLAIN_REFUSED = (
    "This ride now shares only sealed positions and alerts. Reload the ride link to update the"
    " app, then share again."
)


def _sealed(text, most: int) -> str:
    """The sealed text as sent; a body without one (plain lon and lat, an older page) is
    refused."""
    if text is None:
        raise Refused(400, PLAIN_REFUSED)
    if not isinstance(text, str) or len(text) > most or not SEALED.match(text):
        raise Refused(400, "Not a sealed value.")
    return text


def post_position(ride_id: str, token: str, sealed, now: Callable[[], float] = time.time) -> None:
    """Keep this rider's dot, as its phone sealed it, for 2 minutes."""
    _check(ride_id, token)
    kept = _sealed(sealed, SEALED_MAX)
    t = now()
    with store().ride(ride_id) as state:
        _prune(state, t)
        _counted(state, t)
        rider = _rider(state, token, t)
        last = rider.get("posted", 0)
        # One floor on every ride: a bigger ride is slowed by the pace its reads say, never by
        # refusing the posts of phones that have not read the new pace yet.
        if t - last < MIN_POST_INTERVAL_S:
            raise Refused(429, "Too soon; the next position goes in a few seconds.", 1)
        rider.update(sealed=kept, at=t, posted=t)


def post_path(ride_id: str, token: str, sealed, now: Callable[[], float] = time.time) -> None:
    """Keep this rider's route and ridden path, as its phone sealed them, for 2 minutes (a
    broadcast's leader sends them; a reader gets them only with the link's leader key)."""
    _check(ride_id, token)
    kept = _sealed(sealed, SEALED_PATH_MAX)
    t = now()
    with store().ride(ride_id) as state:
        _prune(state, t)
        _counted(state, t)
        rider = _rider(state, token, t)
        if t - rider.get("path_posted", 0) < MIN_PATH_INTERVAL_S:
            raise Refused(429, "Too soon; the path goes again shortly.", MIN_PATH_INTERVAL_S)
        others = sum(1 for k, r in state["riders"].items() if k != token and "path" in r)
        if "path" not in rider and others >= PATHS_PER_RIDE:
            raise Refused(503, "This ride has too many paths shared right now.")
        rider["path_posted"] = t
        rider["path"] = {"sealed": kept, "at": t}


def leave(ride_id: str, token: str, now: Callable[[], float] = time.time) -> None:
    """Drop this rider's dot at once (sharing turned off)."""
    _check(ride_id, token)
    t = now()
    with store().ride(ride_id, create=False) as state:
        _prune(state, t)
        _counted(state, t)
        rider = state["riders"].get(token)
        if rider is not None:
            for key in ("at", "sealed", "path"):
                rider.pop(key, None)


def _alert_out(alert: dict, token: str, t: float) -> dict:
    # What it is, where and its words only its riders read; they merge matching reports too.
    return {
        "id": alert["id"],
        "sealed": alert["sealed"],
        "age_s": max(0, int(t - alert["last"])),
        "mine": alert["sender"] == token,
    }


def read(ride_id: str, token: str, now: Callable[[], float] = time.time, leader: str = "") -> dict:
    """The other riders' sealed dots (not this one's own) with their ages, and the ride's sealed
    alerts. With a broadcast link's `leader` key, the sharer's dot carries "leader": true and the
    sharer's sealed path comes too."""
    _check(ride_id, token)
    if not LEADER_KEY.match(leader or ""):
        leader = ""
    t = now()
    stamp = False
    # Read only, under a shared lock: the ride's readers never wait on one another and the file
    # is not rewritten (2026-10-31, for dots every few seconds).
    with store().peek(ride_id) as state:
        # Something past its 2 minutes is dropped from the ride itself too, below (never left
        # for the sweeper alone).
        stale = _prune(state, t)
        # A reader becomes a rider only with its first position or alert: a read keeps nothing
        # of a token it has not seen (the address limit covers those reads).
        rider = state["riders"].get(token)
        if rider is not None:
            if t - max(rider.get("polled", 0), _polled_here(ride_id, token)) < MIN_POLL_INTERVAL_S:
                raise Refused(
                    429, "Too soon; the dots update every few seconds.", MIN_POLL_INTERVAL_S
                )
            _note_poll(ride_id, token, t)
            # The ride's own record that this phone still reads, so its counts outlive KEEP_S
            # while it rides: written now and then, not on every read.
            stamp = t - rider.get("polled", 0) >= POLL_STAMP_S
        if stale:
            stamp = stamp or rider is not None
        dots = []
        for other, r in state["riders"].items():
            if other == token or "at" not in r or "sealed" not in r:
                continue
            dot = {"sealed": r["sealed"], "age_s": max(0, int(t - r["at"]))}
            if leader and leader_key(other) == leader:
                dot["leader"] = True
            dots.append(dot)
        alerts = [_alert_out(a, token, t) for a in state["alerts"] if "sealed" in a]
        # The pace counts the dots shared, not every token kept (an alert's sender, one whose
        # dot has gone): 20 marshals sharing stay at 2 s when a watcher sends an alert.
        every = pace_s(sum(1 for r in state["riders"].values() if "sealed" in r))
        if rider is None or "sealed" not in rider:
            every = max(every, WATCH_PACE_S)
        path = None
        if leader:
            for other, r in state["riders"].items():
                p = r.get("path")
                if other != token and p and "sealed" in p and leader_key(other) == leader:
                    path = {"sealed": p["sealed"], "age_s": max(0, int(t - p["at"]))}
    # A fresh order each time: a dot's place in the list never ties it to the same rider
    # from one read to the next (2026-10-29).
    _SHUFFLE.shuffle(dots)
    answer = {"dots": dots, "alerts": alerts, "every_s": every}
    if path is not None:
        answer["leader_path"] = path
    if stamp or stale:
        with store().ride(ride_id, create=False) as state:
            _prune(state, t)
            kept = state["riders"].get(token)
            if kept is not None and stamp:
                kept["polled"] = t
    return answer


# Each process's own note of when a token last read, for the poll limit between the ride's
# written stamps (POLL_STAMP_S), kept only as long as the limit (MIN_POLL_INTERVAL_S). A phone's
# reads may reach any worker, so between stamps the limit holds per process: with W workers a
# token can read about W times a second, still within the address limit (ratelimit.RIDE_LINKS).
_polls: dict[tuple[str, str], float] = {}
_polls_lock = threading.Lock()
POLLS_KEPT = 20000


def _polled_here(ride_id: str, token: str) -> float:
    with _polls_lock:
        return _polls.get((ride_id, token), 0.0)


def _note_poll(ride_id: str, token: str, t: float) -> None:
    with _polls_lock:
        if len(_polls) >= POLLS_KEPT:
            _forget_polls_locked(t)
        # Full of reads all under 3 s old: this one is limited by the ride's own stamp only.
        if len(_polls) < POLLS_KEPT:
            _polls[(ride_id, token)] = t


def _forget_polls(t: float) -> None:
    """Drop every note older than the poll limit, which is all it is for: a token is never kept
    here past a few seconds (the sweeper calls this every SWEEP_S)."""
    with _polls_lock:
        _forget_polls_locked(t)


def _forget_polls_locked(t: float) -> None:
    for key, at in list(_polls.items()):
        if t - at >= MIN_POLL_INTERVAL_S:
            del _polls[key]


def send_alert(ride_id: str, token: str, sealed, now: Callable[[], float] = time.time) -> dict:
    """Send an alert, as its phone sealed it, to everyone on the ride link; kept as it is (its
    riders merge matching reports, not this). Answers the alert as others see it."""
    _check(ride_id, token)
    kept = _sealed(sealed, SEALED_MAX)
    t = now()
    with store().ride(ride_id) as state:
        _prune(state, t)
        _counted(state, t)
        rider = _rider(state, token, t)
        if rider.get("alerts", 0) >= ALERTS_PER_RIDE:
            raise Refused(
                429,
                f"You have sent {ALERTS_PER_RIDE} alerts on this ride, the most one phone sends.",
            )
        if t - rider.get("alerted", 0) < ALERT_MIN_INTERVAL_S:
            wait = int(ALERT_MIN_INTERVAL_S - (t - rider.get("alerted", 0))) + 1
            raise Refused(429, "One alert a minute; try again shortly.", wait)
        rider["alerts"] = rider.get("alerts", 0) + 1
        rider["alerted"] = t
        alert = {
            "id": secrets.token_hex(8),
            "sealed": kept,
            "last": t,
            "sender": token,
        }
        _add_alert(state, alert)
        return _alert_out(alert, token, t)


def _add_alert(state: dict, alert: dict) -> None:
    state["alerts"].append(alert)
    if len(state["alerts"]) > LIVE_ALERTS_PER_RIDE:
        state["alerts"].remove(min(state["alerts"], key=lambda a: a["last"]))


def clear_alert(
    ride_id: str, token: str, alert_id: str, now: Callable[[], float] = time.time
) -> None:
    """The sender clears their alert; nobody else can."""
    _check(ride_id, token)
    t = now()
    with store().ride(ride_id, create=False) as state:
        _prune(state, t)
        _counted(state, t)
        for alert in state["alerts"]:
            if alert["id"] == alert_id:
                if alert["sender"] != token:
                    raise Refused(403, "Only the rider who sent an alert can clear it.")
                state["alerts"].remove(alert)
                return
    raise Refused(404, "That alert has already gone.")
