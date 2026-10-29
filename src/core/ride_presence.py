"""Mass Ride and Group Ride links: the other riders as dots, and tap-to-send alerts (v0.7.0 plan,
"Mass ride and Group Ride: see the others on the route" and "... tap to send an issue").

Every ride is sealed end to end (Stephen 2026-10-29: "Encrypted rides send GPS accurate numbers.
All rides should have a key."; frontend/src/lib/rideSeal.ts). Every ride link carries a secret in
its fragment, which no browser sends to a server. Each phone seals its dot (with its role), its
alerts and the leader's path with a key from that secret before sending, and the ride id is
derived from it one way. Here each is opaque text: nothing in it can be read or checked, and a
post in plain numbers is refused. The phones keep to the map's area and merge matching alerts
themselves.

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
# A device sends its position about every 15 s; one sooner than this is refused (429).
MIN_POST_INTERVAL_S = 10
# A device asks for the dots about every 15 s; one sooner than this is refused (429).
MIN_POLL_INTERVAL_S = 3
# The most anything is kept: a token (and its counts) is forgotten this long after its phone last
# read or sent anything; a phone in front reads every 15 s, so its limits hold while it rides.
KEEP_S = 120
# Bounds on memory, whatever a client sends.
MAX_RIDERS_PER_RIDE = 3000
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
# with the ride rather than outliving it in the database: MAX_RIDERS_PER_RIDE riders each sending
# a position every 15 s is 12,000 a minute, so 15,000.
RIDE_WRITES_PER_MINUTE = 15000
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
            yield state
            if _is_empty(state):
                self._rides.pop(ride_id, None)

    def clear(self) -> None:
        with self._lock:
            self._rides.clear()

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
    def _locked(cls, path: str) -> int:
        """`path` opened and locked: a descriptor of the file at `path` now. A process that
        waited for the lock while its holder emptied the ride and unlinked the file would hold
        an orphan no other process can see; so after the lock the descriptor's inode is compared
        with the path's, and the open is tried again where they differ."""
        for _ in range(cls.LOCK_TRIES):
            fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
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
                yield state
                if _is_empty(state):
                    os.unlink(path)
                else:
                    out = json.dumps(state, separators=(",", ":"))
                    if out != raw:
                        handle.seek(0)
                        handle.truncate()
                        handle.write(out)
                        handle.flush()
        finally:
            os.close(fd)


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
        if directory:
            # The deployed api (the test suite, with no directory, sweeps by hand).
            _start_sweeper(chosen)
    return _store


# ---- a ride's state --------------------------------------------------------------------------


def _empty() -> dict:
    return {"riders": {}, "alerts": []}


def _is_empty(state: dict) -> bool:
    return not state["riders"] and not state["alerts"]


def _prune(state: dict, now: float) -> None:
    for token, rider in list(state["riders"].items()):
        last = max(rider.get(k, 0) for k in ("since", "posted", "polled", "alerted", "path_posted"))
        if now - last > KEEP_S:
            del state["riders"][token]
            continue
        if "at" in rider and now - rider["at"] > DOT_TTL_S:
            # The position goes at 2 minutes; the token's counts stay for the ride's limits.
            # (lon, lat and role: what a server before every ride was sealed kept in plain.)
            for key in ("at", "sealed", "lon", "lat", "role"):
                rider.pop(key, None)
        if "path" in rider and now - rider["path"]["at"] > PATH_TTL_S:
            del rider["path"]
    # An alert lasts 2 minutes from when it was sent.
    state["alerts"] = [a for a in state["alerts"] if now - a["last"] <= ALERT_TTL_S]
    writes = state.get("writes")
    if writes and now - writes[0] >= RIDE_WRITES_WINDOW_S:
        del state["writes"]


def count_write(ride_id: str, now: Callable[[], float] = time.time) -> int:
    """Count one write against the ride: 0 when it may go ahead, else the seconds to wait. The
    count lives in the ride's state for its one-minute window and goes with the ride."""
    t = now()
    window = math.floor(t / RIDE_WRITES_WINDOW_S) * RIDE_WRITES_WINDOW_S
    with store().ride(ride_id) as state:
        _prune(state, t)
        writes = state.get("writes")
        if not writes or writes[0] != window:
            writes = [window, 0]
        writes[1] += 1
        state["writes"] = writes
        if writes[1] > RIDE_WRITES_PER_MINUTE:
            return max(1, math.ceil(window + RIDE_WRITES_WINDOW_S - t))
    return 0


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
        rider = _rider(state, token, t)
        last = rider.get("posted", 0)
        if t - last < MIN_POST_INTERVAL_S:
            raise Refused(
                429, "Too soon; the next position goes in a few seconds.", MIN_POST_INTERVAL_S
            )
        rider.update(sealed=kept, at=t, posted=t)


def post_path(ride_id: str, token: str, sealed, now: Callable[[], float] = time.time) -> None:
    """Keep this rider's route and ridden path, as its phone sealed them, for 2 minutes (a
    broadcast's leader sends them; a reader gets them only with the link's leader key)."""
    _check(ride_id, token)
    kept = _sealed(sealed, SEALED_PATH_MAX)
    t = now()
    with store().ride(ride_id) as state:
        _prune(state, t)
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
    with store().ride(ride_id, create=False) as state:
        _prune(state, now())
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
    with store().ride(ride_id, create=False) as state:
        _prune(state, t)
        # A reader becomes a rider only with its first position or alert: a read keeps nothing
        # of a token it has not seen (the address limit covers those reads).
        rider = state["riders"].get(token)
        if rider is not None:
            if t - rider.get("polled", 0) < MIN_POLL_INTERVAL_S:
                raise Refused(
                    429, "Too soon; the dots update every 15 seconds.", MIN_POLL_INTERVAL_S
                )
            rider["polled"] = t
        dots = []
        for other, r in state["riders"].items():
            if other == token or "at" not in r or "sealed" not in r:
                continue
            dot = {"sealed": r["sealed"], "age_s": max(0, int(t - r["at"]))}
            if leader and leader_key(other) == leader:
                dot["leader"] = True
            dots.append(dot)
        alerts = [_alert_out(a, token, t) for a in state["alerts"] if "sealed" in a]
        path = None
        if leader:
            for other, r in state["riders"].items():
                p = r.get("path")
                if other != token and p and "sealed" in p and leader_key(other) == leader:
                    path = {"sealed": p["sealed"], "age_s": max(0, int(t - p["at"]))}
    # A fresh order each time: a dot's place in the list never ties it to the same rider
    # from one read to the next (2026-10-29).
    _SHUFFLE.shuffle(dots)
    answer = {"dots": dots, "alerts": alerts}
    if path is not None:
        answer["leader_path"] = path
    return answer


def send_alert(ride_id: str, token: str, sealed, now: Callable[[], float] = time.time) -> dict:
    """Send an alert, as its phone sealed it, to everyone on the ride link; kept as it is (its
    riders merge matching reports, not this). Answers the alert as others see it."""
    _check(ride_id, token)
    kept = _sealed(sealed, SEALED_MAX)
    t = now()
    with store().ride(ride_id) as state:
        _prune(state, t)
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
    with store().ride(ride_id, create=False) as state:
        _prune(state, now())
        for alert in state["alerts"]:
            if alert["id"] == alert_id:
                if alert["sender"] != token:
                    raise Refused(403, "Only the rider who sent an alert can clear it.")
                state["alerts"].remove(alert)
                return
    raise Refused(404, "That alert has already gone.")
