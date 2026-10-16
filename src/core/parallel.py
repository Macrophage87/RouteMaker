"""A small bounded pool for a plan's independent router calls (v0.7.0, "Faster routing").

`core.routing.plan` used to make every router call one after another: the leg traces of
one route, the traces of the router's alternatives before they are ranked, the middle
check's /route beside the trace of the route it is weighed against, and the closures'
delay probes. Those calls do not depend on each other, so they are now started together
here and read where they were read before, in the same order, by the same code.

The rules:

- Only router calls (HTTP to Valhalla) run on the pool, with one exception: a transit
  trip's later rides (`api._later_rides`), each a whole plan, which reads the database
  from the pool thread on that thread's own connection and closes it when done. Every
  other database read stays on the request's own thread.
- One pool per process, `settings.ROUTER_PARALLEL_CALLS` threads (3 unless set). A plan
  run on a pool thread makes its own calls in turn (a pool thread never submits). gunicorn's
  workers are sync processes, one request each, so the router sees at most
  ROUTER_PARALLEL_CALLS + 1 calls per routing slot (`settings.ROUTING_CONCURRENCY`): the
  pool's threads and the request's own thread. Each call keeps the request's own deadline
  (`routing.Deadline`): the budget is unchanged.
- At 1 (or below) nothing is submitted: each call runs where it is asked for, as before.
- A task never waits on the pool from inside the pool (that could deadlock a full pool):
  a submit from a pool thread runs inline.
- The request's context (its `core.timing` recorder) goes with each task.
"""

from __future__ import annotations

import contextvars
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from django.conf import settings

DEFAULT_PARALLEL_CALLS = 3

_lock = threading.Lock()
_pool: ThreadPoolExecutor | None = None
_pool_size = 0
_local = threading.local()


def size() -> int:
    """The pool's bound: `settings.ROUTER_PARALLEL_CALLS`, at least 1."""
    try:
        return max(1, int(getattr(settings, "ROUTER_PARALLEL_CALLS", DEFAULT_PARALLEL_CALLS)))
    except (TypeError, ValueError):
        return DEFAULT_PARALLEL_CALLS


def inside() -> bool:
    """Whether this thread is one of the pool's."""
    return bool(getattr(_local, "inside", False))


def enabled() -> bool:
    """Whether calls go to the pool at all (not at a bound of 1, nor from a pool thread)."""
    return size() > 1 and not inside()


def _executor() -> ThreadPoolExecutor:
    global _pool, _pool_size
    wanted = size()
    with _lock:
        if _pool is None or _pool_size != wanted:
            old = _pool
            _pool = ThreadPoolExecutor(max_workers=wanted, thread_name_prefix="router")
            _pool_size = wanted
            if old is not None:
                old.shutdown(wait=False)
        return _pool


def _inside(fn: Callable[..., Any], *args: Any) -> Any:
    _local.inside = True
    try:
        return fn(*args)
    finally:
        _local.inside = False


def done(value: Any = None, error: BaseException | None = None) -> Future:
    """A future already settled, for a call run inline."""
    future: Future = Future()
    if error is not None:
        future.set_exception(error)
    else:
        future.set_result(value)
    return future


def submit(fn: Callable[..., Any], *args: Any) -> Future:
    """Run `fn(*args)` on the pool, with the caller's context; inline (already settled)
    where the pool is off or this is a pool thread. Never raises: the future holds it."""
    if not enabled():
        try:
            return done(fn(*args))
        except Exception as error:  # noqa: BLE001 - the future carries it to the reader
            return done(error=error)
    context = contextvars.copy_context()
    return _executor().submit(context.run, _inside, fn, *args)
