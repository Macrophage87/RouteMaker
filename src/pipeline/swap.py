"""Swapping a freshly built segment schema into place.

Ordering matters and is the opposite of the obvious one. The Valhalla upstreams
are repointed *first* and the schema renamed *second*, so the inconsistency
window is a live segment table describing the older graph rather than a graph
nobody is serving. Reconciliation tolerates that direction; it does not tolerate
the other.

The rename itself is three steps, not one: `live` has to move out of the way
before `staging` can take the name. It takes an ACCESS EXCLUSIVE lock, so it
runs under a `lock_timeout` with bounded retry rather than queueing behind an
in-flight read and then blocking every later one. Persistent connections cache
query plans against the renamed relations, so the pool is flushed immediately
after the commit; without that the first post-swap request on each connection
fails with a stale relation.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from django.db import connection, transaction

logger = logging.getLogger(__name__)

DEFAULT_LOCK_TIMEOUT_MS = 3_000
DEFAULT_ATTEMPTS = 5
DEFAULT_BACKOFF_S = 2.0


class SwapLockTimeout(RuntimeError):
    """The rename could not take its lock within the allowed attempts."""


@dataclass(frozen=True)
class SwapResult:
    live: str
    staging: str
    retired: str
    attempts: int


def _retired_name(live: str) -> str:
    return f"{live}_old"


def swap_schemas(
    live: str = "live",
    staging: str = "staging",
    lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS,
    attempts: int = DEFAULT_ATTEMPTS,
    backoff_s: float = DEFAULT_BACKOFF_S,
) -> SwapResult:
    """Rename `staging` into `live`, retiring the current `live`.

    Callers repoint the Valhalla upstreams before calling this; see the module
    docstring for why that order and not the reverse.
    """
    retired = _retired_name(live)
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    # Scoped to this transaction, so a slow reader costs this
                    # swap an attempt rather than blocking every later query.
                    cursor.execute(f"SET LOCAL lock_timeout = '{lock_timeout_ms}ms'")
                    cursor.execute(f"DROP SCHEMA IF EXISTS {retired} CASCADE")
                    cursor.execute(f"ALTER SCHEMA {live} RENAME TO {retired}")
                    cursor.execute(f"ALTER SCHEMA {staging} RENAME TO {live}")
            break
        except Exception as error:  # noqa: BLE001 - re-raised below if terminal
            last_error = error
            if "lock" not in str(error).lower() or attempt == attempts:
                if attempt == attempts:
                    raise SwapLockTimeout(
                        f"could not acquire the rename lock in {attempts} attempts"
                    ) from error
                raise
            logger.warning("swap attempt %d could not take its lock, retrying", attempt)
            time.sleep(backoff_s * attempt)
    else:  # pragma: no cover - the loop always breaks or raises
        raise SwapLockTimeout("rename exhausted its attempts") from last_error

    # Persistent connections hold plans against the relations just renamed.
    connection.close()
    return SwapResult(live=live, staging=staging, retired=retired, attempts=attempt)


def rollback_swap(live: str = "live", staging: str = "staging") -> None:
    """Undo a swap by putting the retired schema back.

    Pairs with repointing the settings table back to the previous tile extracts;
    this half only restores the database.
    """
    retired = _retired_name(live)
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(f"SET LOCAL lock_timeout = '{DEFAULT_LOCK_TIMEOUT_MS}ms'")
        cursor.execute(f"ALTER SCHEMA {live} RENAME TO {staging}")
        cursor.execute(f"ALTER SCHEMA {retired} RENAME TO {live}")
    connection.close()
