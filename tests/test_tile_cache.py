"""The stress tile cache, the draw slots and the draw timeout (revision round 2).

The ops review of round 1 measured one address, inside its tile budget,
holding every gunicorn worker with cold draws: routes took 10-13 s and /healthz
9.7 s for 50 s. What stops that now is here: a tile drawn once is served from
`stress_tile_cache` without a draw, z10-13 are drawn ahead after a promotion, a
draw takes one of a few slots or is refused at once, and a draw is cut off
well before the swap's lock timeout.
"""

from __future__ import annotations

import time

import pytest
from django.db import connection
from django.test import override_settings
from mvt import decode
from test_route_api import hold_slots, our_advisory_locks
from test_stress_tiles import CENTRE, CLASSES, insert, tile_of, url

from core import ratelimit, stress_tiles, tile_cache

db = pytest.mark.django_db(transaction=True)

TILE = tile_of(*CENTRE, 14)


@pytest.fixture
def live(segment_schemas):
    live, _staging = segment_schemas
    insert(live, CLASSES)
    return live


def rows(version: str | None = None) -> int:
    with connection.cursor() as cursor:
        if version is None:
            cursor.execute("SELECT count(*) FROM stress_tile_cache")
        else:
            cursor.execute("SELECT count(*) FROM stress_tile_cache WHERE version = %s", [version])
        return cursor.fetchone()[0]


def version() -> str:
    return stress_tiles.etag_for(*stress_tiles.live_table())


def deployment_slots():
    limit = ratelimit.TILES_IN_FLIGHT
    return [(ratelimit._LOCK_CLASS_TOTAL + limit.scope_id, s) for s in range(limit.total)]


def client_slots(address: str):
    limit = ratelimit.TILES_IN_FLIGHT
    key = ratelimit._client_lock_id(ratelimit.client_key(address))
    return [
        (ratelimit._LOCK_CLASS_CLIENT + limit.scope_id * 64 + slot, key)
        for slot in range(limit.per_client)
    ]


@db
class TestCache:
    def test_a_drawn_tile_is_served_again_without_a_draw(self, client, live, monkeypatch) -> None:
        first = client.get(url(*TILE))
        assert first.status_code == 200 and first.content
        assert rows(version()) == 1

        def no_draw(*args, **kwargs):
            raise AssertionError("a cached tile was drawn again")

        monkeypatch.setattr(stress_tiles, "render", no_draw)
        again = client.get(url(*TILE))
        assert again.status_code == 200
        assert decode(again.content) == decode(first.content)
        assert again["ETag"] == first["ETag"]
        assert "public" in again["Cache-Control"]

    def test_a_hit_takes_no_draw_slot(self, client, live) -> None:
        client.get(url(*TILE))
        other = hold_slots(deployment_slots())
        try:
            again = client.get(url(*TILE))
        finally:
            other.close()
        assert again.status_code == 200

    def test_a_new_table_is_not_served_the_old_tables_tiles(self, client, live) -> None:
        from pipeline.schema import create_segment_schema, drop_segment_schema

        before = client.get(url(*TILE))
        drop_segment_schema(live)
        create_segment_schema(live)
        after = client.get(url(*TILE))
        assert after.status_code == 200
        assert after.content == b"" and before.content != b""

    def test_the_eviction_drops_stale_rows_and_the_oldest_past_the_budget(self) -> None:
        for n in range(4):
            tile_cache.put("new", 15, n, 0, b"x" * 100)
            time.sleep(0.01)
        # The deepest pre-drawn zoom is kept whatever its size, even newest.
        tile_cache.put("new", tile_cache.PREDRAW_MAX_ZOOM, 0, 0, b"x" * 1000)
        tile_cache.put("old", 15, 9, 9, b"x")
        # Exactly the two newest z15 tiles fit.
        dropped = tile_cache.evict("new", max_bytes=200)
        assert dropped == 3  # the stale row, and the two oldest z15 tiles
        with connection.cursor() as cursor:
            cursor.execute("SELECT version, z, x FROM stress_tile_cache ORDER BY z, x")
            kept = cursor.fetchall()
        assert kept == [
            ("new", tile_cache.PREDRAW_MAX_ZOOM, 0),
            ("new", 15, 2),
            ("new", 15, 3),
        ]

    def test_predraw_draws_z10_to_13_once(self, live) -> None:
        result = tile_cache.predraw()
        assert result == (4, 0, 0, 0)  # one tile at each zoom holds the fixture
        with connection.cursor() as cursor:
            cursor.execute("SELECT z FROM stress_tile_cache ORDER BY z")
            assert [z for (z,) in cursor.fetchall()] == [10, 11, 12, 13]
        assert tile_cache.predraw() == (0, 4, 0, 0)

    def test_predraw_draws_nothing_before_any_build(self, segment_schemas) -> None:
        from pipeline.schema import drop_segment_schema

        drop_segment_schema(segment_schemas[0])
        assert tile_cache.predraw() == (0, 0, 0, 0)

    def test_predraw_clears_what_an_earlier_table_left(self, live) -> None:
        tile_cache.put('W/"stress-1-v1"', 10, 0, 0, b"old")
        tile_cache.predraw()
        assert rows('W/"stress-1-v1"') == 0

    def test_the_predraw_command_says_what_it_did(self, live) -> None:
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("predraw_stress_tiles", stdout=out)
        assert "4 drawn" in out.getvalue()

    def test_the_cache_is_left_out_of_the_nightly_dump(self) -> None:
        from config.procrastinate import BACKUP_EXCLUDED_TABLES
        from core.models import StressTileCache

        assert StressTileCache._meta.db_table in BACKUP_EXCLUDED_TABLES


@db
class TestDrawSlots:
    def test_a_draw_with_the_pool_full_is_refused_at_once(self, client, live) -> None:
        other = hold_slots(deployment_slots())
        try:
            started = time.monotonic()
            refused = client.get(url(*TILE), HTTP_X_FORWARDED_FOR="198.51.100.70")
            took = time.monotonic() - started
        finally:
            other.close()
        assert refused.status_code == 503
        assert refused["Retry-After"] == "1"
        assert "no-store" in refused["Cache-Control"]
        assert took < 1
        assert rows() == 0
        assert our_advisory_locks() == 0

    def test_a_client_with_its_slots_taken_is_429_and_others_are_drawn(self, client, live) -> None:
        other = hold_slots(client_slots("198.51.100.71"))
        try:
            refused = client.get(url(*TILE), HTTP_X_FORWARDED_FOR="198.51.100.71")
            drawn = client.get(url(*TILE), HTTP_X_FORWARDED_FOR="198.51.100.72")
        finally:
            other.close()
        assert refused.status_code == 429
        assert refused["Retry-After"] == "1"
        assert "no-store" in refused["Cache-Control"]
        assert drawn.status_code == 200
        assert our_advisory_locks() == 0, "the slot is given back after the draw"

    def test_routing_geocoding_and_tile_draws_leave_a_worker_free_within_a_second(
        self,
    ) -> None:
        """The owner's answer of 2026-09-28, "Free within ~1 s (Recommended)":
        routes, lookups and draws together leave a worker, and the one geocoding
        request allowed to wait (at most a second) is all that may take it."""
        from django.conf import settings

        from config.settings import routing_concurrency, tile_concurrency

        lookups = settings.GEOCODE_CONCURRENCY
        waiters = ratelimit.GEOCODE_IN_FLIGHT.max_waiters
        assert ratelimit.GEOCODE_IN_FLIGHT.wait_s <= 1.0
        for workers in range(1, 17):
            tiles, routes = tile_concurrency(str(workers)), routing_concurrency(str(workers))
            assert tiles >= 1
            if workers >= 5:
                assert routes + lookups + tiles <= workers - 1, workers
                assert routes + lookups + tiles + waiters <= workers, workers
        assert (routing_concurrency(None), lookups, waiters, tile_concurrency(None)) == (
            3,
            2,
            1,
            1,
        ), "compose's seven workers: 3 routes, 2 lookups, 1 waiter, 1 draw"

    def test_a_tile_draw_is_not_refused_while_routing_is_full(self, client, live) -> None:
        """The tiles' slots are their own: a full routing pool does not refuse a
        draw (review cm2)."""
        limit = ratelimit.ROUTING_IN_FLIGHT
        routing = hold_slots(
            [(ratelimit._LOCK_CLASS_TOTAL + limit.scope_id, s) for s in range(limit.total)]
        )
        try:
            drawn = client.get(url(*TILE), HTTP_X_FORWARDED_FOR="198.51.100.90")
        finally:
            routing.close()
        assert drawn.status_code == 200

    @override_settings(TILE_CONCURRENCY=1)
    def test_the_pool_size_is_the_setting(self, client, live) -> None:
        other = hold_slots([(ratelimit._LOCK_CLASS_TOTAL + ratelimit.TILES_IN_FLIGHT.scope_id, 0)])
        try:
            refused = client.get(url(*TILE))
        finally:
            other.close()
        assert refused.status_code == 503


@db
class TestDrawTimeout:
    def test_a_draw_past_its_timeout_is_cut_off_and_asked_again(
        self, client, live, monkeypatch
    ) -> None:
        slow = "SELECT pg_sleep(5), NULL::oid, NULL::bytea"
        monkeypatch.setattr(stress_tiles, "tile_sql", lambda *a, **k: slow)
        monkeypatch.setattr(stress_tiles, "DRAW_TIMEOUT_MS", 200)
        started = time.monotonic()
        response = client.get(url(*TILE))
        assert time.monotonic() - started < 3
        assert response.status_code == 503
        assert response["Retry-After"] == "1"
        assert "no-store" in response["Cache-Control"]
        assert rows() == 0
        assert our_advisory_locks() == 0

    def test_the_draw_timeout_is_inside_the_swaps_lock_timeout(self) -> None:
        from pipeline.swap import DEFAULT_LOCK_TIMEOUT_MS

        assert stress_tiles.DRAW_TIMEOUT_MS <= DEFAULT_LOCK_TIMEOUT_MS * 2 // 3

    def test_the_timeout_is_the_draws_own_and_does_not_outlive_it(self, live) -> None:
        stress_tiles.render(*TILE, timeout_ms=1234)
        with connection.cursor() as cursor:
            cursor.execute("SHOW statement_timeout")
            assert cursor.fetchone()[0] in {"0", "0ms"}


@db
def test_a_failed_predraw_is_reported_and_does_not_fail_the_rebuild(monkeypatch) -> None:
    from config import procrastinate

    def broken(**kwargs):
        raise RuntimeError("no")

    monkeypatch.setattr(tile_cache, "predraw", broken)
    note = procrastinate._predraw_stress_tiles()
    assert "predraw_stress_tiles" in note


@db
class TestPredrawProbes:
    """Review cm2's probes of the pre-draw, each against a surviving mutant."""

    def test_the_predraw_uses_its_own_longer_timeout(self, live, monkeypatch) -> None:
        seen = []
        real = stress_tiles.render

        def spy(*args, **kwargs):
            seen.append(kwargs.get("timeout_ms"))
            return real(*args, **kwargs)

        monkeypatch.setattr(stress_tiles, "render", spy)
        tile_cache.predraw()
        assert seen and all(t is not None and t >= 3 * stress_tiles.DRAW_TIMEOUT_MS for t in seen)
        assert stress_tiles.PREDRAW_TIMEOUT_MS >= 3 * stress_tiles.DRAW_TIMEOUT_MS

    def test_a_timed_out_tile_is_counted_and_the_rest_are_drawn(self, live, monkeypatch) -> None:
        real = stress_tiles.render
        calls = []

        def first_times_out(*args, **kwargs):
            calls.append(args)
            if len(calls) == 1:
                raise stress_tiles.DrawTimedOut("probe")
            return real(*args, **kwargs)

        monkeypatch.setattr(stress_tiles, "render", first_times_out)
        result = tile_cache.predraw()
        assert (result.drawn, result.timed_out, result.left) == (3, 1, 0)
        assert "1 timed out" in result.summary()

    def test_a_promotion_mid_predraw_stores_nothing_under_the_old_version(
        self, live, monkeypatch
    ) -> None:
        oid, _ = stress_tiles.live_table()
        monkeypatch.setattr(stress_tiles, "render", lambda *a, **k: (oid + 1, b"new-table"))
        result = tile_cache.predraw()
        assert result.drawn == 0 and result.left == 4
        assert rows() == 0

    def test_a_spent_budget_draws_nothing_and_says_how_much_is_left(self, live) -> None:
        result = tile_cache.predraw(budget_s=-1)
        assert result == (0, 0, 0, 4)
        assert rows() == 0
        assert "stopped at its time budget with 4 left" in result.summary()

    def test_the_rebuild_row_says_when_the_predraw_is_incomplete(self, live, monkeypatch) -> None:
        from config import procrastinate

        monkeypatch.setattr(
            tile_cache, "predraw", lambda **k: tile_cache.Predrawn(10, 2, timed_out=1, left=7)
        )
        note = procrastinate._predraw_stress_tiles()
        assert "10 drawn" in note and "1 timed out" in note and "7 left" in note
        assert "predraw_stress_tiles" in note

    @pytest.mark.parametrize(
        ("result", "hand_run"),
        [((5, 0, 1, 0), True), ((5, 0, 0, 3), True), ((5, 2, 0, 0), False)],
    )
    def test_the_row_asks_for_a_hand_run_when_anything_was_not_drawn(
        self, monkeypatch, result, hand_run
    ) -> None:
        from config import procrastinate

        monkeypatch.setattr(tile_cache, "predraw", lambda **k: tile_cache.Predrawn(*result))
        assert ("predraw_stress_tiles" in procrastinate._predraw_stress_tiles()) == hand_run

    def test_the_rebuild_gives_the_predraw_only_what_is_left_of_its_own_budget(
        self, live, monkeypatch
    ) -> None:
        from config import procrastinate

        budgets = []
        monkeypatch.setattr(
            tile_cache,
            "predraw",
            lambda budget_s: budgets.append(budget_s) or tile_cache.Predrawn(0, 0),
        )
        procrastinate._predraw_stress_tiles(time.monotonic() + 60)
        procrastinate._predraw_stress_tiles(time.monotonic() - 5)
        procrastinate._predraw_stress_tiles(time.monotonic() + 10 * tile_cache.PREDRAW_BUDGET_S)
        assert 55 <= budgets[0] <= 60
        assert budgets[1] == 0
        assert budgets[2] == tile_cache.PREDRAW_BUDGET_S

    def test_a_tile_drawn_from_a_newer_table_carries_its_etag(self, client, live, monkeypatch):
        oid, _ = stress_tiles.live_table()
        monkeypatch.setattr(stress_tiles, "render", lambda *a, **k: (oid + 1, b""))
        response = client.get(url(*TILE))
        assert str(oid + 1) in response["ETag"]
        assert rows() == 0


@pytest.mark.parametrize("result", [(4, 0), (0, 4), (3, 1, 0, 0)])
def test_a_complete_predraw_mentions_no_stop_and_nothing_left(result) -> None:
    summary = tile_cache.Predrawn(*result).summary()
    assert "stopped" not in summary and "left" not in summary and "timed out" not in summary
