"""Whether a live feed's read makes sense (core.feed_sense; backlog 2026-11-12, data sources
item 2): a feed that still answers but has stopped making sense is an alarm, not a quiet
success."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core import feed_sense as sense

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


def test_too_few_reads_to_say_doubt_nothing() -> None:
    assert sense.usual_count([40, 40]) is None
    assert sense.doubt([40, 40], 0) is None


def test_the_usual_count_is_the_median() -> None:
    assert sense.usual_count([1, 50, 40, 41, 200]) == 41


def test_none_from_a_usually_busy_source_is_doubted() -> None:
    assert sense.doubt([6, 6, 6], 0) == "read as nothing (usually 6 items)"


def test_none_from_an_often_empty_source_is_not() -> None:
    assert sense.doubt([0, 2, 0, 1, 0], 0) is None


def test_a_small_share_of_a_big_usual_count_is_doubted() -> None:
    """A parser that now drops most items (a changed field name) reads as a few, not none."""
    assert sense.doubt([200] * 5, 12) == "read only 12 items (usually 200)"
    assert sense.doubt([200] * 5, 40) is None  # a fifth: a quiet week, not a broken parser
    assert sense.doubt([10] * 5, 1) is None  # too small a source to tell


def test_remember_keeps_the_last_eight() -> None:
    assert sense.remember(list(range(8)), 99) == [1, 2, 3, 4, 5, 6, 7, 99]
    assert sense.remember(None, 3) == [3]


def test_a_wzdx_feed_its_publisher_stopped_updating_is_frozen() -> None:
    old = {"feed_info": {"update_date": (NOW - timedelta(days=4)).isoformat()}}
    assert sense.frozen(old, NOW) == "not updated by its publisher since 2026-11-09"
    fresh = {"feed_info": {"update_date": "2026-11-13T11:59:00Z"}}
    assert sense.frozen(fresh, NOW) is None


def test_a_feed_with_no_date_or_a_bad_one_is_not_judged() -> None:
    assert sense.frozen({}, NOW) is None
    assert sense.frozen({"feed_info": {"update_date": "soon"}}, NOW) is None
    assert sense.frozen({"feed_info": "x"}, NOW) is None


def test_a_read_taken_although_doubted_starts_the_counts_again() -> None:
    """Review: past the drop age a small read is taken; without a fresh start the old median
    would doubt every read for days while the small counts work their way in."""
    assert sense.remember([40] * 8, 3) == [3]
    assert sense.doubt([3], 3) is None
    assert sense.remember([40] * 8, 35) == [40] * 7 + [35]


def test_without_shrink_only_none_is_doubted() -> None:
    assert sense.doubt([200] * 5, 12, shrink=False) is None
    assert sense.doubt([200] * 5, 0, shrink=False) == "read as nothing (usually 200 items)"
    assert sense.remember([200] * 5, 12, shrink=False) == [200] * 5 + [12]
