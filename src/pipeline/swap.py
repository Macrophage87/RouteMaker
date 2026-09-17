"""Swapping a freshly built segment schema into place.

Ordering matters and is the opposite of the obvious one. The Valhalla upstreams
are repointed *first* and the schema renamed *second*, so the inconsistency
window is a live segment table describing the older graph rather than a graph
nobody is serving. Reconciliation tolerates that direction; it does not tolerate
the other.

The rename is three steps, not one: `live` has to move out of the way before
`staging` can take the name.

Two things an earlier draft of this module got wrong, both corrected here and in
the plan after being tested against a live server rather than reasoned about.

`ALTER SCHEMA ... RENAME` does *not* take a lock on the tables inside the
schema; it updates one `pg_namespace` row and commits against open readers. The
statement that actually blocks is `DROP SCHEMA ... CASCADE` on the retired
schema, which does take ACCESS EXCLUSIVE on its tables. That is what the
`lock_timeout` and the bounded retry are for.

And because a bare rename serializes nothing, a single READ COMMITTED request
could read `live.segment` twice in one transaction and see old rows then new
rows. So the swap takes an explicit ACCESS EXCLUSIVE on the live table inside
its transaction: in-flight readers finish before the rename commits, later ones
queue for the moment it takes. That is the lock the design assumed it was
getting for free.

The plan's claim that persistent connections would serve stale query plans after
the rename was also wrong - PostgreSQL's plancache invalidates correctly - so
nothing here closes connections to work around it.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from django.db import connection, transaction

from .schema import (
    create_segment_schema,
    drop_segment_schema,
    schema_exists,
    validate_schema_name,
)

logger = logging.getLogger(__name__)

# PostgreSQL SQLSTATEs for lock contention. Classified by code rather than by
# matching "lock" in the message: that substring also appears in Django's
# "end of the 'atomic' block" error, and the message text is locale-dependent,
# so a non-English server would never have matched a genuine timeout.
LOCK_SQLSTATES = frozenset({"55P03", "40P01"})


def _is_lock_error(error: BaseException) -> bool:
    for candidate in (error, error.__cause__, error.__context__):
        sqlstate = getattr(candidate, "sqlstate", None) or getattr(candidate, "pgcode", None)
        if sqlstate in LOCK_SQLSTATES:
            return True
    return False


DEFAULT_LOCK_TIMEOUT_MS = 3_000
DEFAULT_ATTEMPTS = 5
DEFAULT_BACKOFF_S = 2.0


class SwapLockTimeout(RuntimeError):
    """The swap could not take its lock within the allowed attempts."""


class SwapRollbackUnavailable(RuntimeError):
    """There is no retired schema to roll back to."""


class SwapInsideTransaction(RuntimeError):
    """The swap was called from inside an enclosing transaction."""


@dataclass(frozen=True)
class SwapResult:
    live: str
    staging: str
    retired: str
    attempts: int


def _live() -> str:
    from django.conf import settings

    return settings.SEGMENT_SCHEMA_LIVE


def _staging() -> str:
    from django.conf import settings

    return settings.SEGMENT_SCHEMA_STAGING


def _retired_name(live: str) -> str:
    return f"{live}_old"


def swap_schemas(
    live: str | None = None,
    staging: str | None = None,
    lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS,
    attempts: int = DEFAULT_ATTEMPTS,
    backoff_s: float = DEFAULT_BACKOFF_S,
) -> SwapResult:
    """Rename `staging` into `live`, retiring the current `live`.

    Callers repoint the Valhalla upstreams before calling this; see the module
    docstring for why that order and not the reverse.
    """
    if connection.in_atomic_block:
        # A schema swap inside someone else's transaction is not something to do
        # quietly: it would commit or roll back with work it knows nothing about.
        raise SwapInsideTransaction("swap_schemas must not run inside an enclosing transaction")

    live = live or _live()
    staging = staging or _staging()
    validate_schema_name(live)
    validate_schema_name(staging)
    retired = _retired_name(live)
    last_error: Exception | None = None

    # A fresh deployment has staging but no live yet, and the rename of a
    # non-existent schema is not a lock error, so the first rebuild would have
    # raised and never completed.
    if not schema_exists(live):
        create_segment_schema(live)

    for attempt in range(1, attempts + 1):
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    # Scoped to this transaction, so a slow reader costs this
                    # swap an attempt rather than blocking every later query.
                    cursor.execute(f"SET LOCAL lock_timeout = '{lock_timeout_ms}ms'")
                    # The rename alone serializes nothing, so readers could tear
                    # across the boundary. This is the lock that stops them.
                    cursor.execute(f"LOCK TABLE {live}.segment IN ACCESS EXCLUSIVE MODE")
                    cursor.execute(f"DROP SCHEMA IF EXISTS {retired} CASCADE")
                    cursor.execute(f"ALTER SCHEMA {live} RENAME TO {retired}")
                    cursor.execute(f"ALTER SCHEMA {staging} RENAME TO {live}")
            break
        except Exception as error:  # noqa: BLE001 - re-raised below if terminal
            last_error = error
            if not _is_lock_error(error):
                # Anything that is not lock contention is raised as itself. The
                # earlier version relabelled every terminal failure as a lock
                # timeout, so an operator reading the alert for a missing schema
                # or a full disk was told the swap could not get a lock.
                raise
            if attempt == attempts:
                raise SwapLockTimeout(
                    f"could not take the swap lock in {attempts} attempts"
                ) from error
            logger.warning("swap attempt %d could not take its lock, retrying", attempt)
            time.sleep(backoff_s * attempt)
    else:  # pragma: no cover - the loop always breaks or raises
        raise SwapLockTimeout("rename exhausted its attempts") from last_error

    return SwapResult(live=live, staging=staging, retired=retired, attempts=attempt)


def rollback_swap(
    live: str | None = None,
    staging: str | None = None,
    lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS,
    attempts: int = DEFAULT_ATTEMPTS,
    backoff_s: float = DEFAULT_BACKOFF_S,
) -> None:
    """Undo a swap by putting the retired schema back.

    Pairs with repointing the settings table back to the previous tile extracts;
    this half only restores the database. `promotion.rollback` is the caller
    that decides whether there is a previous build to go back to at all; this
    function's own gate - that a retired schema exists - is true forever after
    the first swap and says nothing about what is in it.
    """
    if connection.in_atomic_block:
        # The same refusal as the forward path, and for the same reason: a
        # rename that commits or rolls back with an enclosing transaction's
        # work is not something to do quietly. The plan requires it of the
        # swap; there is no argument that makes the emergency path the
        # exception.
        raise SwapInsideTransaction("rollback_swap must not run inside an enclosing transaction")

    live = live or _live()
    staging = staging or _staging()
    validate_schema_name(live)
    validate_schema_name(staging)
    retired = _retired_name(live)
    if not schema_exists(retired):
        raise SwapRollbackUnavailable(
            f"there is no {retired} schema to roll back to; a rollback ran already "
            "or no swap has happened"
        )
    if schema_exists(staging):
        # A rebuild that fails at the swap leaves its staging schema behind, and
        # the first rename below needs that name free. The leftover is that
        # failed rebuild's own output - a successful swap renames staging away -
        # so it is dropped rather than raising a raw "schema already exists"
        # from the middle of a rename the operator has already committed to.
        logger.warning(
            "dropping the %s schema left behind by a rebuild that did not swap; "
            "the rollback's rename needs the name",
            staging,
        )
        drop_segment_schema(staging)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(f"SET LOCAL lock_timeout = '{lock_timeout_ms}ms'")
                # The same lock the forward path takes, and for the same reason:
                # a bare rename serializes nothing, so readers would tear across
                # the boundary. Every argument for it applies here with more
                # force, since a rollback runs when something is already wrong.
                cursor.execute(f"LOCK TABLE {live}.segment IN ACCESS EXCLUSIVE MODE")
                cursor.execute(f"ALTER SCHEMA {live} RENAME TO {staging}")
                cursor.execute(f"ALTER SCHEMA {retired} RENAME TO {live}")
            return
        except Exception as error:  # noqa: BLE001 - re-raised below if terminal
            # The emergency path needs the retry more than the forward one does,
            # not less: it runs when something is already wrong.
            last_error = error
            if not _is_lock_error(error):
                raise
            if attempt == attempts:
                # Classified the way the forward path classifies it. Re-raising
                # the raw psycopg error told an operator whose rollback lost a
                # race with a reader that the database had failed, in the one
                # path where knowing it is worth retrying matters most.
                raise SwapLockTimeout(
                    f"could not take the rollback lock in {attempts} attempts"
                ) from error
            logger.warning("rollback attempt %d could not take its lock, retrying", attempt)
            time.sleep(backoff_s * attempt)
    else:  # pragma: no cover - the loop always returns or raises
        raise SwapLockTimeout("the rollback rename exhausted its attempts") from last_error
