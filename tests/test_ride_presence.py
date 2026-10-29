"""Mass Ride and Group Ride links: dots and alerts (v0.7.0 plan; core.ride_presence).

Every ride is sealed (Stephen 2026-10-29: "All rides should have a key."; frontend/src/lib/
rideSeal.ts): a live ride takes only sealed dots, paths and alerts and refuses plain numbers.
They are kept in memory for 2 minutes, never in the database or a log; a rider sees the others,
not themselves; updates and alerts are limited per token; alerts last 2 minutes or until the
sender clears them.
"""

from __future__ import annotations

import json
import logging
import random
from types import SimpleNamespace

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from core import ride_presence as rp

RIDE = "a" * 64
ME, YOU, THEM = "1" * 32, "2" * 32, "3" * 32
SPOT = (-77.03651, 38.89768)
SEALED_DOT = "A" * 40
SEALED_ALERT = "B" * 60
SEALED_PATH = "C" * 4000


class Clock:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def clock() -> Clock:
    return Clock()


def _dot(n: int = 0) -> str:
    """A sealed dot, distinct per `n`."""
    return f"{n:024x}" + "D" * 16


def _post(api, ride: str, path: str, body: dict, **headers):
    return api.post(
        f"/api/rides/{ride}/{path}",
        data=json.dumps(body),
        content_type="application/json",
        **headers,
    )


# ---- plain numbers are refused ----


def test_a_live_ride_takes_only_sealed_positions(clock) -> None:
    with pytest.raises(rp.Refused) as dot:
        rp.post_position(RIDE, ME, None, now=clock)
    assert dot.value.status == 400 and "sealed" in dot.value.message
    with pytest.raises(rp.Refused) as path:
        rp.post_path(RIDE, ME, None, now=clock)
    assert path.value.status == 400 and path.value.message == rp.PLAIN_REFUSED
    with pytest.raises(rp.Refused) as alert:
        rp.send_alert(RIDE, ME, None, now=clock)
    assert alert.value.status == 400 and alert.value.message == rp.PLAIN_REFUSED
    # Nothing was kept of any of them.
    assert rp.store()._rides == {}


@pytest.mark.django_db
def test_a_live_ride_refuses_plain_numbers_over_the_api(client) -> None:
    plain = {"token": ME, "lon": SPOT[0], "lat": SPOT[1], "role": "sweep"}
    here = _post(client, RIDE, "here", plain)
    assert here.status_code == 400 and here.json()["error"] == rp.PLAIN_REFUSED
    path = _post(client, RIDE, "path", {"token": ME, "route": [list(SPOT)], "trail": []})
    assert path.status_code == 400
    alert = _post(
        client, RIDE, "alerts", {"token": ME, "ride_type": "group-ride", "kind": "crash", **plain}
    )
    assert alert.status_code == 400
    assert client.get(f"/api/rides/{RIDE}", HTTP_X_RIDE_TOKEN=YOU).json()["dots"] == []


def test_the_server_keeps_no_rounding_or_plain_alert_code() -> None:
    # The phones send their position as measured, sealed: the server has nothing to round, check
    # or merge.
    for gone in ("rounded", "GRID_M", "ALERT_KINDS", "MERGE_WITHIN_M", "ROLES", "_line"):
        assert not hasattr(rp, gone), gone


# ---- dots ----


def test_others_see_my_dot_with_its_age_and_i_do_not_see_my_own(clock) -> None:
    rp.post_position(RIDE, ME, SEALED_DOT, now=clock)
    clock.t += 40
    assert rp.read(RIDE, ME, now=clock)["dots"] == []
    # No token, no id, no name: the sealed text and its age.
    assert rp.read(RIDE, YOU, now=clock)["dots"] == [{"sealed": SEALED_DOT, "age_s": 40}]


def test_a_newer_dot_replaces_the_older(clock) -> None:
    rp.post_position(RIDE, ME, _dot(1), now=clock)
    clock.t += rp.MIN_POST_INTERVAL_S
    rp.post_position(RIDE, ME, _dot(2), now=clock)
    assert [d["sealed"] for d in rp.read(RIDE, YOU, now=clock)["dots"]] == [_dot(2)]


def test_a_dot_is_gone_after_2_minutes(clock) -> None:
    rp.post_position(RIDE, ME, SEALED_DOT, now=clock)
    clock.t += rp.DOT_TTL_S + 1
    assert rp.read(RIDE, YOU, now=clock)["dots"] == []
    assert ME not in rp.store()._rides.get(RIDE, {"riders": {}})["riders"]


def test_leaving_drops_the_dot_at_once(clock) -> None:
    rp.post_position(RIDE, ME, SEALED_DOT, now=clock)
    rp.leave(RIDE, ME, now=clock)
    assert rp.read(RIDE, YOU, now=clock)["dots"] == []
    assert "sealed" not in rp.store()._rides[RIDE]["riders"][ME]


def test_dots_come_in_a_fresh_order_on_every_read(clock, monkeypatch) -> None:
    # A dot's place in the list never ties it to one rider from read to read: the server
    # shuffles them each time, from the system's random source.
    assert isinstance(rp._SHUFFLE, random.SystemRandom)
    calls = []

    def reverse(dots):
        calls.append(len(dots))
        dots.reverse()

    monkeypatch.setattr(rp, "_SHUFFLE", SimpleNamespace(shuffle=reverse))
    rp.post_position(RIDE, ME, _dot(1), now=clock)
    rp.post_position(RIDE, YOU, _dot(2), now=clock)
    seen = [d["sealed"] for d in rp.read(RIDE, THEM, now=clock)["dots"]]
    assert calls == [2]
    # The stub's reversal: the order is the shuffle's, not who posted first.
    assert seen == [_dot(2), _dot(1)]


def test_updates_are_limited_per_token(clock) -> None:
    rp.post_position(RIDE, ME, SEALED_DOT, now=clock)
    clock.t += 5
    with pytest.raises(rp.Refused) as refused:
        rp.post_position(RIDE, ME, SEALED_DOT, now=clock)
    assert refused.value.status == 429
    clock.t += 10
    rp.post_position(RIDE, ME, SEALED_DOT, now=clock)
    rp.read(RIDE, ME, now=clock)
    with pytest.raises(rp.Refused):
        rp.read(RIDE, ME, now=clock)


def test_a_read_keeps_nothing_of_a_reader_before_its_first_position(clock) -> None:
    # A ride nobody has written to is not kept for a read.
    assert rp.read(RIDE, YOU, now=clock) == {"dots": [], "alerts": []}
    assert rp.store()._rides == {}
    # On a kept ride, the reader is not made a rider either.
    rp.post_position(RIDE, ME, SEALED_DOT, now=clock)
    rp.read(RIDE, YOU, now=clock)
    rp.read(RIDE, THEM, now=clock)
    assert set(rp.store()._rides[RIDE]["riders"]) == {ME}


def test_a_dot_keeps_the_leader_mark(clock) -> None:
    rp.post_position(RIDE, ME, _dot(1), now=clock)
    rp.post_position(RIDE, THEM, _dot(2), now=clock)
    key = rp.leader_key(ME)
    assert rp.LEADER_KEY.match(key) and key != ME  # the link never carries the token itself
    dots = rp.read(RIDE, YOU, now=clock, leader=key)["dots"]
    assert [d["sealed"] for d in dots if d.get("leader")] == [_dot(1)]
    # Without a key, or with one that is not 32 hex digits, no dot is marked.
    assert not any(d.get("leader") for d in rp.read(RIDE, THEM, now=clock)["dots"])
    clock.t += 5
    assert not any(d.get("leader") for d in rp.read(RIDE, YOU, now=clock, leader="x" * 32)["dots"])


@pytest.mark.parametrize(
    "sealed", ["", "short", "A" * 39 + "=", "A" * 30 + "+/", 7, ["A" * 40], "A" * 1401]
)
def test_a_sealed_value_that_is_not_one_is_refused(clock, sealed) -> None:
    with pytest.raises(rp.Refused) as refused:
        rp.post_position(RIDE, ME, sealed, now=clock)
    assert refused.value.status == 400 and refused.value.message == "Not a sealed value."
    with pytest.raises(rp.Refused):
        rp.send_alert(RIDE, ME, sealed, now=clock)


@pytest.mark.parametrize("ride,token", [("nope", ME), (RIDE, "short")])
def test_bad_ride_ids_and_tokens_are_refused(clock, ride, token) -> None:
    with pytest.raises(rp.Refused):
        rp.post_position(ride, token, SEALED_DOT, now=clock)


# ---- the store ----


def _ride(n: int) -> str:
    return f"{n:064x}"


def _fill(clock) -> None:
    for n in range(rp.MAX_RIDES):
        rp.post_position(_ride(n), ME, SEALED_DOT, now=clock)


def test_a_full_store_makes_room_from_rides_with_no_recent_position(clock, monkeypatch) -> None:
    monkeypatch.setattr(rp, "MAX_RIDES", 3)
    monkeypatch.setattr(rp, "time", SimpleNamespace(time=clock))
    _fill(clock)
    with pytest.raises(rp.Refused) as refused:
        rp.post_position(_ride(9), ME, SEALED_DOT, now=clock)
    assert refused.value.status == 503
    # Two minutes on, with one ride still riding: the other two make room.
    clock.t += rp.DOT_TTL_S + 1
    rp.post_position(_ride(0), ME, SEALED_DOT, now=clock)
    rp.post_position(_ride(9), ME, SEALED_DOT, now=clock)
    assert set(rp.store()._rides) == {_ride(0), _ride(9)}


def test_the_tmpfs_store_makes_room_the_same_way(tmp_path, clock, monkeypatch) -> None:
    monkeypatch.setattr(rp, "MAX_RIDES", 2)
    monkeypatch.setattr(rp, "time", SimpleNamespace(time=clock))
    monkeypatch.setattr(rp, "store", lambda: store)
    store = rp.TmpfsStore(str(tmp_path))
    _fill(clock)
    with pytest.raises(rp.Refused):
        rp.post_position(_ride(9), ME, SEALED_DOT, now=clock)
    # A read of a ride not kept takes no room and writes no file.
    rp.read(_ride(8), YOU, now=clock)
    assert len(list(tmp_path.iterdir())) == 2
    clock.t += rp.DOT_TTL_S + 1
    rp.post_position(_ride(1), ME, SEALED_DOT, now=clock)
    rp.post_position(_ride(9), ME, SEALED_DOT, now=clock)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == [f"{_ride(1)}.json", f"{_ride(9)}.json"]


def test_a_directory_not_on_a_tmpfs_is_never_used(tmp_path, settings, monkeypatch) -> None:
    monkeypatch.setattr(rp, "_start_sweeper", lambda _store: None)
    settings.RIDE_PRESENCE_DIR = str(tmp_path)
    rp._store = None
    store = rp.store()
    if rp._on_tmpfs(str(tmp_path)):
        pytest.skip("the test's temporary directory is itself a tmpfs here")
    assert isinstance(store, rp.MemoryStore)
    rp.post_position(RIDE, ME, SEALED_DOT)
    assert list(tmp_path.iterdir()) == []


def test_the_tmpfs_store_shares_state_and_removes_an_empty_ride(tmp_path) -> None:
    store = rp.TmpfsStore(str(tmp_path))
    with store.ride(RIDE) as state:
        state["riders"][ME] = {"since": 1.0, "sealed": SEALED_DOT, "at": 1.0}
    with rp.TmpfsStore(str(tmp_path)).ride(RIDE) as again:
        assert again["riders"][ME]["sealed"] == SEALED_DOT
        again["riders"].clear()
    assert list(tmp_path.iterdir()) == []


def test_a_lock_on_a_file_unlinked_while_waiting_is_taken_again(tmp_path, monkeypatch) -> None:
    """A worker that waited on the lock while the holder emptied the ride and unlinked its file
    would write to an orphan no other worker sees: after the lock the inode is compared with
    the path's, and the file opened again."""
    real = rp.fcntl.flock
    calls = []

    def flock(fd, op):
        calls.append(fd)
        real(fd, op)
        if len(calls) == 1:  # the holder emptied the ride while this one waited
            (tmp_path / f"{RIDE}.json").unlink()

    monkeypatch.setattr(rp.fcntl, "flock", flock)
    with rp.TmpfsStore(str(tmp_path)).ride(RIDE) as state:
        state["riders"][ME] = {"since": 1.0, "sealed": SEALED_DOT, "at": 1.0}
    assert len(calls) == 2
    monkeypatch.setattr(rp.fcntl, "flock", real)
    with rp.TmpfsStore(str(tmp_path)).ride(RIDE) as again:
        assert again["riders"][ME]["sealed"] == SEALED_DOT


def test_a_plain_dot_an_older_server_kept_is_never_shown_and_goes_at_2_minutes(clock) -> None:
    with rp.store().ride(RIDE) as state:
        state["riders"][ME] = {
            "since": clock.t,
            "lon": 1.0,
            "lat": 2.0,
            "role": "lead",
            "at": clock.t,
        }
        state["alerts"].append({"id": "x", "kind": "crash", "last": clock.t, "sender": ME})
    assert rp.read(RIDE, YOU, now=clock) == {"dots": [], "alerts": []}
    clock.t += rp.DOT_TTL_S + 1
    rp.post_position(RIDE, YOU, SEALED_DOT, now=clock)  # keeps the ride and ME's token
    with rp.store().ride(RIDE) as state:
        assert not {"lon", "lat", "role"} & set(state["riders"].get(ME, {}))
        assert state["alerts"] == []


# ---- alerts ----


def test_a_sealed_alert_reaches_everyone_and_is_never_merged(clock) -> None:
    mine = rp.send_alert(RIDE, ME, SEALED_ALERT, now=clock)
    assert set(mine) == {"id", "sealed", "age_s", "mine"} and mine["mine"] is True
    yours = rp.send_alert(RIDE, YOU, SEALED_ALERT, now=clock)
    assert yours["id"] != mine["id"]
    seen = rp.read(RIDE, THEM, now=clock)["alerts"]
    assert [a["sealed"] for a in seen] == [SEALED_ALERT, SEALED_ALERT]
    assert all(a["mine"] is False for a in seen)


def test_live_alerts_on_a_ride_are_capped_and_the_oldest_goes(clock) -> None:
    first = None
    for n in range(rp.LIVE_ALERTS_PER_RIDE + 1):
        clock.t += 1
        sent = rp.send_alert(RIDE, f"{n:032x}", SEALED_ALERT, now=clock)
        first = first or sent["id"]
    alerts = rp.read(RIDE, ME, now=clock)["alerts"]
    assert len(alerts) == rp.LIVE_ALERTS_PER_RIDE
    assert first not in {a["id"] for a in alerts}


def test_alert_limits_one_a_minute_and_ten_a_ride(clock) -> None:
    rp.send_alert(RIDE, ME, SEALED_ALERT, now=clock)
    with pytest.raises(rp.Refused) as refused:
        rp.send_alert(RIDE, ME, SEALED_ALERT, now=clock)
    assert refused.value.status == 429 and refused.value.retry_after_s
    for _ in range(9):
        clock.t += 61
        rp.send_alert(RIDE, ME, SEALED_ALERT, now=clock)
    clock.t += 61
    with pytest.raises(rp.Refused) as refused:
        rp.send_alert(RIDE, ME, SEALED_ALERT, now=clock)
    assert "10 alerts" in refused.value.message


def test_alerts_last_2_minutes_or_until_the_sender_clears_them(clock) -> None:
    sent = rp.send_alert(RIDE, ME, SEALED_ALERT, now=clock)
    with pytest.raises(rp.Refused) as refused:
        rp.clear_alert(RIDE, YOU, sent["id"], now=clock)
    assert refused.value.status == 403
    rp.clear_alert(RIDE, ME, sent["id"], now=clock)
    assert rp.read(RIDE, YOU, now=clock)["alerts"] == []
    clock.t += rp.ALERT_MIN_INTERVAL_S
    rp.send_alert(RIDE, ME, SEALED_ALERT, now=clock)
    clock.t += rp.ALERT_TTL_S + 1
    assert rp.read(RIDE, THEM, now=clock)["alerts"] == []


def test_writes_are_counted_per_ride_and_the_count_goes_with_its_minute(clock, monkeypatch) -> None:
    monkeypatch.setattr(rp, "RIDE_WRITES_PER_MINUTE", 2)
    clock.t = 1_000_040.0  # 20 s into a minute
    rp.post_position(RIDE, ME, SEALED_DOT, now=clock)
    assert rp.count_write(RIDE, now=clock) == 0
    assert rp.count_write(RIDE, now=clock) == 0
    assert rp.count_write(RIDE, now=clock) == 40  # the rest of the minute
    clock.t += 40
    assert rp.count_write(RIDE, now=clock) == 0
    clock.t += rp.RIDE_WRITES_WINDOW_S
    rp.store().sweep(clock.t)
    assert "writes" not in rp.store()._rides[RIDE]


# ---- a leader's path ----


def test_a_sealed_path_reaches_only_readers_with_the_leader_key(clock) -> None:
    rp.post_path(RIDE, ME, SEALED_PATH, now=clock)
    assert "leader_path" not in rp.read(RIDE, YOU, now=clock)
    clock.t += 5
    path = rp.read(RIDE, YOU, now=clock, leader=rp.leader_key(ME))["leader_path"]
    assert path == {"sealed": SEALED_PATH, "age_s": 5}
    clock.t += 5
    assert "leader_path" not in rp.read(RIDE, THEM, now=clock, leader=rp.leader_key(YOU))
    clock.t += rp.PATH_TTL_S
    assert "leader_path" not in rp.read(RIDE, THEM, now=clock, leader=rp.leader_key(ME))


def test_a_path_is_bounded_and_not_sent_too_often(clock) -> None:
    with pytest.raises(rp.Refused) as big:
        rp.post_path(RIDE, ME, "C" * (rp.SEALED_PATH_MAX + 1), now=clock)
    assert big.value.status == 400
    rp.post_path(RIDE, ME, SEALED_PATH, now=clock)
    with pytest.raises(rp.Refused) as soon:
        rp.post_path(RIDE, ME, SEALED_PATH, now=clock)
    assert soon.value.status == 429
    clock.t += rp.MIN_PATH_INTERVAL_S
    rp.post_path(RIDE, ME, SEALED_PATH, now=clock)
    # Leaving drops the path at once.
    rp.leave(RIDE, ME, now=clock)
    assert "leader_path" not in rp.read(RIDE, YOU, now=clock, leader=rp.leader_key(ME))


def test_a_ride_holds_a_few_paths_at_most(clock) -> None:
    for i in range(rp.PATHS_PER_RIDE):
        rp.post_path(RIDE, f"{i:032x}", SEALED_PATH, now=clock)
    with pytest.raises(rp.Refused) as full:
        rp.post_path(RIDE, "f" * 32, SEALED_PATH, now=clock)
    assert full.value.status == 503


# ---- 2 minutes, then nothing ----


def _left_behind(clock) -> None:
    """A leader's dot, path and alert, then 2 minutes in which nobody opens the ride."""
    rp.post_position(RIDE, ME, SEALED_DOT, now=clock)
    rp.post_path(RIDE, ME, SEALED_PATH, now=clock)
    rp.send_alert(RIDE, ME, SEALED_ALERT, now=clock)


def test_nothing_about_a_ride_stays_past_2_minutes(clock) -> None:
    # Stephen 2026-10-22: "For privacy, nothing stays on the server for more than 2 min".
    _left_behind(clock)
    clock.t += rp.KEEP_S + 1
    rp.read(RIDE, YOU, now=clock)  # a read prunes
    with rp.store().ride(RIDE, create=False) as state:
        assert state == {"riders": {}, "alerts": []}


def test_a_ride_nobody_opens_again_is_swept_after_2_minutes(clock) -> None:
    # The v0.12.0 end review: a prune only on a read left a ride whose phones had all closed
    # the link in memory until someone opened it again.
    _left_behind(clock)
    rp.post_position(_ride(1), YOU, SEALED_DOT, now=clock)
    rp.store().sweep(clock.t + rp.KEEP_S - 1)
    assert set(rp.store()._rides) == {RIDE, _ride(1)}
    rp.store().sweep(clock.t + rp.KEEP_S + 1)
    assert rp.store()._rides == {}


def test_the_tmpfs_store_sweeps_every_ride_too(tmp_path, clock, monkeypatch) -> None:
    store = rp.TmpfsStore(str(tmp_path))
    monkeypatch.setattr(rp, "store", lambda: store)
    _left_behind(clock)
    rp.post_position(_ride(1), YOU, SEALED_DOT, now=clock)
    # A dot past 2 minutes is written out of the file while its token's counts still count.
    clock.t += rp.DOT_TTL_S + 1
    rp.post_position(_ride(1), THEM, SEALED_DOT, now=clock)
    store.sweep(clock.t)
    assert sorted(p.name for p in tmp_path.iterdir()) == [f"{_ride(1)}.json"]
    kept = json.loads((tmp_path / f"{_ride(1)}.json").read_text())
    assert "sealed" not in kept["riders"].get(YOU, {}) and "sealed" in kept["riders"][THEM]
    store.sweep(clock.t + rp.KEEP_S + 1)
    assert list(tmp_path.iterdir()) == []


def test_the_deployed_store_starts_its_sweeper(tmp_path, settings, monkeypatch) -> None:
    started = []
    monkeypatch.setattr(rp, "_start_sweeper", started.append)
    rp._store = None
    rp.store()
    assert started == []  # the suite's store, with no directory, is swept by hand
    settings.RIDE_PRESENCE_DIR = str(tmp_path)
    chosen = rp.store()
    assert started == [chosen]


# ---- the endpoints ----


@pytest.mark.django_db
def test_the_api_takes_sealed_values_in_post_bodies(client, clock, monkeypatch) -> None:
    monkeypatch.setattr(rp.time, "time", clock)
    assert _post(client, RIDE, "here", {"token": ME, "sealed": SEALED_DOT}).status_code == 200
    assert _post(client, RIDE, "path", {"token": ME, "sealed": SEALED_PATH}).status_code == 200
    alert = _post(client, RIDE, "alerts", {"token": ME, "sealed": SEALED_ALERT})
    assert alert.status_code == 200 and alert.json()["sealed"] == SEALED_ALERT
    assert _post(client, RIDE, "here", {"token": YOU, "sealed": "not sealed!"}).status_code == 400
    key = rp.leader_key(ME)
    r = client.get(f"/api/rides/{RIDE}", HTTP_X_RIDE_TOKEN=YOU, HTTP_X_RIDE_LEADER=key).json()
    assert r["dots"] == [{"sealed": SEALED_DOT, "age_s": 0, "leader": True}]
    assert r["leader_path"]["sealed"] == SEALED_PATH
    assert [a["sealed"] for a in r["alerts"]] == [SEALED_ALERT]


@pytest.mark.django_db
def test_a_sealed_body_keeps_no_plain_field_sent_beside_it(client) -> None:
    body = {"token": ME, "sealed": SEALED_DOT, "lon": SPOT[0], "lat": SPOT[1], "role": "sweep"}
    assert _post(client, RIDE, "here", body).status_code == 200
    rider = rp.store()._rides[RIDE]["riders"][ME]
    assert not {"lon", "lat", "role"} & set(rider)
    alert = {**body, "sealed": SEALED_ALERT, "ride_type": "group-ride", "kind": "crash"}
    assert _post(client, RIDE, "alerts", alert).status_code == 200
    kept = rp.store()._rides[RIDE]["alerts"][0]
    assert not {"lon", "lat", "kind", "text"} & set(kept)


@pytest.mark.django_db
def test_the_endpoints_keep_positions_out_of_the_database_and_logs(client, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    headers = {"HTTP_X_FORWARDED_FOR": "198.51.100.9"}
    queries = CaptureQueriesContext(connection)
    queries.__enter__()
    r = _post(client, RIDE, "here", {"token": ME, "sealed": SEALED_DOT}, **headers)
    assert r.status_code == 200
    r = client.get(f"/api/rides/{RIDE}", HTTP_X_RIDE_TOKEN=YOU, **headers)
    assert r.status_code == 200 and [d["sealed"] for d in r.json()["dots"]] == [SEALED_DOT]
    assert r["Cache-Control"] == "no-store"
    alert = _post(client, RIDE, "alerts", {"token": ME, "sealed": SEALED_ALERT}, **headers)
    assert alert.status_code == 200
    clear = _post(client, RIDE, f"alerts/{alert.json()['id']}/clear", {"token": ME}, **headers)
    assert clear.status_code == 200
    too_soon = _post(client, RIDE, "here", {"token": ME, "sealed": SEALED_DOT}, **headers)
    assert too_soon.status_code == 429 and too_soon["Retry-After"]
    logged = " ".join(record.getMessage() for record in caplog.records)
    assert SEALED_DOT not in logged and SEALED_ALERT not in logged
    queries.__exit__(None, None, None)
    # The database sees only the rate limits' counts, by keyed digest: never a dot, a token or a
    # ride.
    sql = [str(q["sql"]) for q in queries.captured_queries]
    assert sql and all("rate_limit_window" in q for q in sql)
    assert not any(v in q for q in sql for v in (SEALED_DOT, SEALED_ALERT, ME, RIDE))


@pytest.mark.django_db
def test_the_endpoints_are_limited_per_address_and_writes_per_ride(client, monkeypatch) -> None:
    from core import ratelimit

    seen = []
    refuse = set()

    def hit(limit, key):
        seen.append(limit.scope)
        allowed = limit.scope not in refuse
        return ratelimit.Decision(allowed=allowed, retry_after_s=0 if allowed else 7)

    monkeypatch.setattr(ratelimit, "hit", hit)
    monkeypatch.setattr(rp, "RIDE_WRITES_PER_MINUTE", 0)
    busy = _post(client, RIDE, "here", {"token": ME, "sealed": SEALED_DOT})
    assert busy.status_code == 429 and int(busy["Retry-After"]) >= 1
    # The ride's write count is kept with the ride, never as a database row.
    assert seen == ["ride-link"]
    assert rp.store()._rides == {}
    monkeypatch.setattr(rp, "RIDE_WRITES_PER_MINUTE", 15000)
    seen.clear()
    assert client.get(f"/api/rides/{RIDE}", HTTP_X_RIDE_TOKEN=YOU).status_code == 200
    assert seen == ["ride-link"]
    refuse.add("ride-link")
    assert client.get(f"/api/rides/{RIDE}", HTTP_X_RIDE_TOKEN=YOU).status_code == 429
    # Generous: a whole ride's phones can share one carrier address.
    assert ratelimit.RIDE_LINKS.requests >= 600


def test_a_foreign_page_is_refused(client) -> None:
    r = client.get(f"/api/rides/{RIDE}", HTTP_X_RIDE_TOKEN=ME, HTTP_SEC_FETCH_SITE="cross-site")
    assert r.status_code == 403


@pytest.mark.django_db
def test_the_api_reads_the_leader_key_from_its_header(client, clock, monkeypatch) -> None:
    monkeypatch.setattr(rp.time, "time", clock)
    _post(client, RIDE, "here", {"token": ME, "sealed": SEALED_DOT})
    r = client.get(
        f"/api/rides/{RIDE}", HTTP_X_RIDE_TOKEN=YOU, HTTP_X_RIDE_LEADER=rp.leader_key(ME)
    )
    assert r.status_code == 200
    assert r.json()["dots"][0]["leader"] is True
