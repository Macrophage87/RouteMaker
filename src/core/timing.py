"""Where a route request's time goes (v0.7.0, "Faster routing", step 1: measure first).

POST /api/route records each phase of a plan here and answers them in a `Server-Timing`
header (https://www.w3.org/TR/server-timing/), so the browser's network panel on beta
shows where Go's seconds go, and logs one line a request with the same figures. The line
holds step names, milliseconds, the ride type and a distance band: never a location.

A plan's phases (`routing.plan` marks them in order; one that did not run is absent):

- `wait`: from the request's arrival (`core.middleware.RequestClockMiddleware`) to the
  plan: the other middleware, the rate limit, the slots and the parse;
- `cache`: the answer cache's look-up (`core.route_cache`), with `desc` hit or miss;
- `route`: the ride's own /route (and the fallbacks to the standard graph);
- `zones`: the work zones' re-route round penalty zones;
- `choose`: the hill seek, the alternatives' ranking and the middle check;
- `search`: the target fit, the calm search, Mountain Bike's levels, the dodge and Avoid passes;
- `answer`: the traces, the stress join, the description and the detour check;
- `more`: the routes offered beside the answer (Avoid's way round, the candidates);
- `router`: every router call's own time added up, `desc` the number of calls (with
  calls in parallel this can be more than the wall time);
- `total`: arrival to answer.

The Go target (the v0.7.0 plan): p95 under 3 s for trips under 10 mi, read off `total`
by the log line's `band`.
"""

from __future__ import annotations

import contextvars
import logging
import threading
import time

logger = logging.getLogger("core.timing")

_current: contextvars.ContextVar[Timings | None] = contextvars.ContextVar(
    "route_timings", default=None
)

METRES_PER_MILE = 1609.344

# The log line's distance bands, by the plan's straight-line span (miles, upper bounds).
BANDS = ((2, "0-2mi"), (5, "2-5mi"), (10, "5-10mi"), (25, "10-25mi"), (50, "25-50mi"))


def band(span_m: float) -> str:
    """A distance band for the log line: coarse enough to say nothing of where."""
    miles = span_m / METRES_PER_MILE
    for top, name in BANDS:
        if miles < top:
            return name
    return "50mi+"


def now() -> float:
    return time.perf_counter()


class Timings:
    """One request's phases, in milliseconds, in the order first recorded."""

    def __init__(self, started: float | None = None) -> None:
        self.started = now() if started is None else started
        self._mark = self.started
        self.phases: dict[str, float] = {}
        self.notes: dict[str, str] = {}
        self.calls = 0
        self.call_s = 0.0
        # A router call that failed for want of time or an answer: the plan may be a
        # degraded one, which the answer cache does not keep (`core.route_cache`).
        self.failures = 0
        self._lock = threading.Lock()

    def add(self, name: str, seconds: float) -> None:
        with self._lock:
            self.phases[name] = self.phases.get(name, 0.0) + max(0.0, seconds)

    def mark(self, name: str) -> None:
        """The time since the last mark (or the start) is phase `name`'s."""
        at = now()
        self.add(name, at - self._mark)
        self._mark = at

    def restart(self) -> None:
        """Start the next phase from now, leaving the time since the last mark out."""
        self._mark = now()

    def note(self, name: str, desc: str) -> None:
        with self._lock:
            self.notes[name] = desc

    def call(self, seconds: float, failed: bool = False) -> None:
        with self._lock:
            self.calls += 1
            self.call_s += max(0.0, seconds)
            if failed:
                self.failures += 1

    def total_s(self) -> float:
        return now() - self.started

    def header(self) -> str:
        """The `Server-Timing` value: each phase, the router calls, the total."""
        parts = []
        with self._lock:
            phases = dict(self.phases)
            notes = dict(self.notes)
            calls, call_s = self.calls, self.call_s
        for name, seconds in phases.items():
            desc = notes.pop(name, None)
            said = f';desc="{desc}"' if desc else ""
            parts.append(f"{name}{said};dur={seconds * 1000:.1f}")
        for name, desc in notes.items():
            parts.append(f'{name};desc="{desc}"')
        if calls:
            parts.append(f'router;desc="{calls} calls";dur={call_s * 1000:.1f}')
        parts.append(f"total;dur={self.total_s() * 1000:.1f}")
        return ", ".join(parts)

    def log(self, preset: str, span_m: float, status: int) -> None:
        """One line a request: step names, ms, the ride type and a distance band only."""
        with self._lock:
            steps = " ".join(
                f"{name}={seconds * 1000:.0f}" for name, seconds in self.phases.items()
            )
            notes = " ".join(f"{name}:{desc}" for name, desc in self.notes.items())
            calls, call_s = self.calls, self.call_s
        logger.info(
            "route timing preset=%s band=%s status=%s total=%.0f %s router=%.0f calls=%d %s",
            preset,
            band(span_m),
            status,
            self.total_s() * 1000,
            steps,
            call_s * 1000,
            calls,
            notes,
        )


def start(timings: Timings) -> contextvars.Token:
    return _current.set(timings)


def stop(token: contextvars.Token) -> None:
    _current.reset(token)


def current() -> Timings | None:
    return _current.get()


def mark(name: str) -> None:
    """Mark phase `name` on the request's recorder, where there is one."""
    timings = _current.get()
    if timings is not None:
        timings.mark(name)


def restart() -> None:
    timings = _current.get()
    if timings is not None:
        timings.restart()


def record_call(seconds: float, failed: bool = False) -> None:
    timings = _current.get()
    if timings is not None:
        timings.call(seconds, failed)
