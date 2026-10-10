"""One read of the operator's feeds for the whole deployment (core.gbfs `SharedStore`).

Each API worker has its own `Gbfs`; the shared copy is what stops them each reading the feeds.
Here two or three `Gbfs` objects stand for workers: a fake in-memory store for the logic, and the
database store (one row, `core.models.BikeshareFeedCache`) for the real thing. The feeds are the
sampled fixtures through a counting fake network; nothing reaches the operator.
"""

from __future__ import annotations

import threading

import pytest
from test_gbfs import FEED_NOW, Clock, FakeNetwork, doc

from core import gbfs
from core.models import BikeshareFeedCache

db = pytest.mark.django_db(transaction=True)


class Wall:
    """The wall clock, shared by every worker of a test (they are on one host)."""

    def __init__(self) -> None:
        self.now = float(FEED_NOW)

    def __call__(self) -> float:
        return self.now


class FakeStore:
    """An in-memory shared copy with the database store's behaviour: one value, replaced; a turn
    to refresh that one caller holds."""

    def __init__(self) -> None:
        self.stored: gbfs.Stored | None = None
        self.saves = 0
        self.failures: list[float] = []
        self.turn_held_by_another = False
        self.breaks = False

    def load(self):
        if self.breaks:
            raise RuntimeError("database down")
        return self.stored

    def save(self, stored) -> None:
        if self.breaks:
            raise RuntimeError("database down")
        self.stored = stored
        self.saves += 1

    def mark_failed(self, wall: float) -> None:
        self.failures.append(wall)
        old = self.stored
        self.stored = gbfs.Stored(
            old.fetched_wall if old else None,
            old.docs if old else {},
            old.unlisted if old else (),
            old.failed if old else (),
            wall,
        )

    def refresh_turn(self):
        store = self

        class Turn:
            def __enter__(self):
                return not store.turn_held_by_another

            def __exit__(self, *exc):
                return False

        return Turn()


def worker(net, store, wall, clock=None, sleep=None):
    return gbfs.Gbfs(net, clock or Clock(), store=store, wall=wall, sleep=sleep or (lambda s: None))


def test_the_second_worker_uses_the_first_workers_reading_and_asks_the_operator_nothing() -> None:
    net, store, wall = FakeNetwork(), FakeStore(), Wall()
    a, b = worker(net, store, wall), worker(net, store, wall)
    first = a.snapshot()
    asked = len(net.calls)
    second = b.snapshot()
    assert len(net.calls) == asked == 6
    assert a.refreshes == 1 and b.refreshes == 0
    assert len(second.stations) == len(first.stations) == 27
    assert second.status is not None and second.as_of == wall.now


def test_seven_workers_make_one_reading_a_minute() -> None:
    net, store, wall = FakeNetwork(), FakeStore(), Wall()
    workers = [worker(net, store, wall) for _ in range(7)]
    for w in workers:
        w.snapshot()
    assert len(net.calls) == 6 and sum(w.refreshes for w in workers) == 1
    # A minute and a bit later the first worker to ask reads again; the rest borrow that.
    wall.now += gbfs.CACHE_TTL_S + 1
    for w in workers:
        w._clock.now += gbfs.CACHE_TTL_S + 1
        w.snapshot()
    assert len(net.calls) == 12 and sum(w.refreshes for w in workers) == 2


def test_the_workers_agree_on_what_the_station_counts_are() -> None:
    net, store, wall = FakeNetwork(), FakeStore(), Wall()
    a, b = worker(net, store, wall), worker(net, store, wall)
    assert a.snapshot().status == b.snapshot().status


def test_the_shared_copy_is_one_value_replaced_never_a_history() -> None:
    net, store, wall = FakeNetwork(), FakeStore(), Wall()
    a = worker(net, store, wall)
    for _ in range(5):
        a.snapshot()
        a._clock.now += gbfs.CACHE_TTL_S + 1
        wall.now += gbfs.CACHE_TTL_S + 1
    assert store.saves == 5
    assert isinstance(store.stored, gbfs.Stored) and store.stored.fetched_wall == wall.now - 61


def fixture_docs() -> dict:
    return {
        name: doc(name) for name in ("station_information", "station_status", "free_bike_status")
    }


def test_a_worker_waits_for_the_one_whose_turn_it_is_and_then_borrows_its_reading() -> None:
    net, store, wall = FakeNetwork(), FakeStore(), Wall()
    polls: list[float] = []

    def sleep(seconds: float) -> None:
        polls.append(seconds)
        if len(polls) == 3:  # the worker whose turn it was finishes its reading
            store.save(gbfs.Stored(wall.now, fixture_docs()))

    store.turn_held_by_another = True
    waiter = worker(net, store, wall, sleep=sleep)
    snap = waiter.snapshot()
    assert len(polls) == 3 and waiter.refreshes == 0 and net.calls == []
    assert len(snap.stations) == 27 and snap.status is not None


def test_a_worker_that_waits_in_vain_serves_what_it_has_or_says_unavailable() -> None:
    net, store, wall = FakeNetwork(), FakeStore(), Wall()
    store.turn_held_by_another = True
    polls = []
    waiter = worker(net, store, wall, sleep=polls.append)
    with pytest.raises(gbfs.Unavailable):
        waiter.snapshot()
    assert sum(polls) >= gbfs.SHARED_WAIT_S and waiter.refreshes == 0 and net.calls == []


def test_a_failed_reading_is_noted_for_every_worker_so_they_do_not_all_retry() -> None:
    net, store, wall = FakeNetwork(), FakeStore(), Wall()
    net.down = True
    a, b = worker(net, store, wall), worker(net, store, wall)
    with pytest.raises(gbfs.Unavailable):
        a.snapshot()
    asked = len(net.calls)
    assert store.failures == [wall.now]
    wall.now += 1
    with pytest.raises(gbfs.Unavailable):
        b.snapshot()
    assert len(net.calls) == asked  # b was paused by a's failure
    wall.now += gbfs.FAILURE_PAUSE_S
    b._clock.now += gbfs.FAILURE_PAUSE_S
    net.down = False
    assert len(b.snapshot().stations) == 27


def test_when_the_feed_goes_down_a_worker_serves_the_shared_copy_for_the_grace_only() -> None:
    net, store, wall = FakeNetwork(), FakeStore(), Wall()
    worker(net, store, wall).snapshot()
    net.down = True
    late = worker(net, store, wall)  # a worker that has nothing of its own
    wall.now += gbfs.CACHE_TTL_S + 30
    snap = late.snapshot()
    assert snap.stale and len(snap.stations) == 27
    wall.now += gbfs.STALE_GRACE_S
    with pytest.raises(gbfs.Unavailable):
        worker(net, store, wall).snapshot()


def test_a_stored_copy_from_the_future_or_long_ago_is_not_used() -> None:
    net, store, wall = FakeNetwork(), FakeStore(), Wall()
    worker(net, store, wall).snapshot()
    asked = len(net.calls)
    wall.now -= 600  # the clock went backwards: the copy is "from the future"
    other = worker(net, store, wall)
    other.snapshot()
    assert len(net.calls) > asked and other.refreshes == 1


def test_a_store_that_fails_is_no_store_and_the_worker_reads_the_feeds_itself() -> None:
    net, store, wall = FakeNetwork(), FakeStore(), Wall()
    store.breaks = True
    w = worker(net, store, wall)
    assert len(w.snapshot().stations) == 27 and w.refreshes == 1


def test_the_staleness_of_a_station_is_judged_against_when_the_feeds_were_read() -> None:
    net, store, wall = FakeNetwork(), FakeStore(), Wall()
    a = worker(net, store, wall)
    snap = a.snapshot()
    silent = [s for s in snap.status.values() if snap.reporting_stale(s)]
    assert len(silent) == 2  # the sample's two stations quiet for hours
    borrowed = worker(net, store, wall).snapshot()
    assert [s.station_id for s in silent] == [
        s.station_id for s in borrowed.status.values() if borrowed.reporting_stale(s)
    ]


# --- The database store: one row ----------------------------------------------------------------


@db
def test_the_database_holds_one_row_however_many_readings() -> None:
    net, wall = FakeNetwork(), Wall()
    a = worker(net, gbfs.DatabaseStore(), wall)
    for _ in range(4):
        a.snapshot()
        a._clock.now += gbfs.CACHE_TTL_S + 1
        wall.now += gbfs.CACHE_TTL_S + 1
    assert a.refreshes == 4
    assert BikeshareFeedCache.objects.count() == 1
    row = BikeshareFeedCache.objects.get()
    assert row.key == "current" and row.fetched_at.timestamp() == pytest.approx(wall.now - 61)
    assert set(row.payload) == {"docs", "unlisted", "failed"}
    assert set(row.payload["docs"]) <= set(gbfs.OPTIONAL_FEEDS) | {gbfs.REQUIRED_FEED}


@db
def test_a_second_worker_reads_the_first_workers_row_through_the_database() -> None:
    net, wall = FakeNetwork(), Wall()
    a = worker(net, gbfs.DatabaseStore(), wall)
    b = worker(net, gbfs.DatabaseStore(), wall)
    first = a.snapshot()
    asked = len(net.calls)
    second = b.snapshot()
    assert len(net.calls) == asked and b.refreshes == 0
    assert second.stations == first.stations and second.status == first.status
    assert second.free_bikes == first.free_bikes and second.pricing == first.pricing
    assert second.as_of == pytest.approx(first.as_of, abs=0.01)


@db
def test_a_failure_is_remembered_in_the_row_without_losing_the_last_reading() -> None:
    net, wall = FakeNetwork(), Wall()
    store = gbfs.DatabaseStore()
    worker(net, store, wall).snapshot()
    net.down = True
    wall.now += gbfs.CACHE_TTL_S + 1
    other = worker(net, store, wall)
    other.snapshot()  # served from the grace
    row = BikeshareFeedCache.objects.get()
    assert row.failed_at is not None and row.payload["docs"]
    assert BikeshareFeedCache.objects.count() == 1


@db
def test_only_one_connection_holds_the_turn_to_read_the_feeds() -> None:
    store = gbfs.DatabaseStore()
    seen: list[bool] = []

    def other() -> None:
        from django.db import connection

        try:
            with gbfs.DatabaseStore().refresh_turn() as got:
                seen.append(got)
        finally:
            connection.close()

    with store.refresh_turn() as mine:
        assert mine is True
        thread = threading.Thread(target=other)
        thread.start()
        thread.join()
    assert seen == [False]
    with store.refresh_turn() as again:  # released
        assert again is True


@db
def test_a_row_that_is_not_what_it_should_be_is_no_copy() -> None:
    BikeshareFeedCache.objects.create(key="current", payload=["not", "a", "dict"], fetched_at=None)
    assert gbfs.DatabaseStore().load().docs == {}
    net, wall = FakeNetwork(), Wall()
    w = worker(net, gbfs.DatabaseStore(), wall)
    assert len(w.snapshot().stations) == 27 and w.refreshes == 1
