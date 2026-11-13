"""Whether a live feed's read makes sense (backlog 2026-11-12, data sources item 2).

A feed that is down is announced: the read fails, the last good copy is kept, and past its
"stale" age the run fails, so the operations page shows it. A feed that still answers but has
stopped making sense was a quiet success: AlertDC's RSS turned into an HTML page in 2026 and
read as nothing, and nobody noticed until a survey. Two things are checked here, for the
closure sources (`core.closure_sources`) and the work-zone feeds (`core.workzones`):

- The count of items a read gave, against the source's usual count (the median of its last
  `COUNTS_KEPT` good reads, once there are `USUAL_AFTER_READS`). None from a source that
  usually has `EMPTY_USUAL` or more, or under `SHRUNK_SHARE` of the usual from one that
  usually has `SHRUNK_USUAL` or more, is doubted: a parser that broke on a changed page, or
  a layer that now returns a fraction of its records. A source that is often empty or small
  (Montgomery County's closures) never trips it.
- How old the feed says its own data is (WZDx's `feed_info.update_date`): a feed still
  served but past `FROZEN_AFTER_S` since its publisher last updated it has stopped being
  fed.

A doubted read is not taken: the caller keeps its last good copy (which ages out as any copy
does) and fails the run, so the operations page names the source the same day. A frozen feed's
read is taken (it is still the publisher's word) and fails the run too. Every number here is
our default, unmeasured.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime

COUNTS_KEPT = 8
USUAL_AFTER_READS = 3
EMPTY_USUAL = 5
SHRUNK_USUAL = 20
SHRUNK_SHARE = 0.2
FROZEN_AFTER_S = 3 * 24 * 3600.0


def usual_count(counts: Iterable | None) -> int | None:
    """The median of the kept counts, or None with too few reads to say."""
    kept = sorted(c for c in counts or () if isinstance(c, int) and not isinstance(c, bool))
    if len(kept) < USUAL_AFTER_READS:
        return None
    return kept[len(kept) // 2]


def doubt(counts: Iterable | None, found: int) -> str | None:
    """Why a read of `found` items is not to be believed against the kept `counts`, or None."""
    usual = usual_count(counts)
    if usual is None:
        return None
    if found == 0 and usual >= EMPTY_USUAL:
        return f"read as nothing (usually {usual} items)"
    if found and usual >= SHRUNK_USUAL and found < usual * SHRUNK_SHARE:
        return f"read only {found} items (usually {usual})"
    return None


def remember(counts: Iterable | None, found: int) -> list[int]:
    """The kept counts with a taken read's added."""
    return [*(c for c in counts or () if isinstance(c, int)), found][-COUNTS_KEPT:]


def frozen(document: Mapping, now: datetime) -> str | None:
    """Why a WZDx feed's own update date says it has stopped being fed, or None. A feed with
    no date, or one that cannot be read, is not judged."""
    info = document.get("feed_info")
    stamp = info.get("update_date") if isinstance(info, Mapping) else None
    if not isinstance(stamp, str):
        return None
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    age = (now - when).total_seconds()
    if age <= FROZEN_AFTER_S:
        return None
    return f"not updated by its publisher since {when.date().isoformat()}"
