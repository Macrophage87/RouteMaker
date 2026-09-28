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
        drawn, cached = tile_cache.predraw()
        assert (drawn, cached) == (4, 0)  # one tile at each zoom holds the fixture
        with connection.cursor() as cursor:
            cursor.execute("SELECT z FROM stress_tile_cache ORDER BY z")
            assert [z for (z,) in cursor.fetchall()] == [10, 11, 12, 13]
        assert tile_cache.predraw() == (0, 4)

    def test_predraw_draws_nothing_before_any_build(self, segment_schemas) -> None:
        from pipeline.schema import drop_segment_schema

        drop_segment_schema(segment_schemas[0])
        assert tile_cache.predraw() == (0, 0)

    def test_predraw_clears_what_an_earlier_table_left(self, live) -> None:
        tile_cache.put('W/"stress-1-v1"', 10, 0, 0, b"old")
        tile_cache.predraw()
        assert rows('W/"stress-1-v1"') == 0

    def test_the_predraw_command_says_what_it_did(self, live) -> None:
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("predraw_stress_tiles", stdout=out)
        assert "drew 4" in out.getvalue()

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

    def test_the_pool_leaves_room_for_routing_and_healthz(self) -> None:
        from config.settings import routing_concurrency, tile_concurrency

        for workers in range(1, 17):
            assert tile_concurrency(str(workers)) >= 1
            if workers >= 4:
                assert tile_concurrency(str(workers)) <= workers - 2
                assert tile_concurrency(str(workers)) < routing_concurrency(str(workers))

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
