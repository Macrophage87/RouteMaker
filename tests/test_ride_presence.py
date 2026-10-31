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
    clock.t += rp.MIN_POST_INTERVAL_S - 0.5
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
    assert rp.read(RIDE, YOU, now=clock) == {"dots": [], "alerts": [], "every_s": 5}
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


def test_a_read_takes_a_shared_lock_and_leaves_the_ride_unwritten(
    tmp_path, clock, monkeypatch
) -> None:
    """Dots every few seconds (Stephen 2026-10-31): a read no longer rewrites the whole ride to
    stamp its poll, and the ride's readers share its lock rather than queue on it."""
    store = rp.TmpfsStore(str(tmp_path))
    monkeypatch.setattr(rp, "_store", store)
    monkeypatch.setattr(rp, "_store_for", "")
    monkeypatch.setattr(rp, "store", lambda: store)
    rp.post_position(RIDE, ME, SEALED_DOT, now=clock)
    rp.post_position(RIDE, YOU, _dot(1), now=clock)
    rp.read(RIDE, ME, now=clock)  # the first read notes the phone in the ride
    path = tmp_path / f"{RIDE}.json"
    before = (path.read_text(), path.stat().st_mtime_ns)
    ops = []
    real = rp.fcntl.flock
    monkeypatch.setattr(rp.fcntl, "flock", lambda fd, op: (ops.append(op), real(fd, op))[1])
    clock.t += rp.MIN_POLL_INTERVAL_S
    assert len(rp.read(RIDE, ME, now=clock)["dots"]) == 1
    assert ops == [rp.fcntl.LOCK_SH]
    assert (path.read_text(), path.stat().st_mtime_ns) == before
    # Too soon again from the same phone, though nothing was written.
    with pytest.raises(rp.Refused):
        rp.read(RIDE, ME, now=clock)
    # A ride never written is read as empty, and no file is made for it.
    assert rp.read("b" * 64, ME, now=clock) == {"dots": [], "alerts": [], "every_s": 5}
    assert not (tmp_path / f"{'b' * 64}.json").exists()
    # Now and then (POLL_STAMP_S) the read notes in the ride that its phone still reads.
    clock.t += rp.POLL_STAMP_S
    rp.read(RIDE, ME, now=clock)
    assert json.loads(path.read_text())["riders"][ME]["polled"] == clock.t


def test_a_write_takes_the_ride_lock_once(tmp_path, clock, monkeypatch) -> None:
    """The ride's write count is kept in the same locked turn as the write (it took two)."""
    store = rp.TmpfsStore(str(tmp_path))
    monkeypatch.setattr(rp, "store", lambda: store)
    ops = []
    real = rp.fcntl.flock
    monkeypatch.setattr(rp.fcntl, "flock", lambda fd, op: (ops.append(op), real(fd, op))[1])
    rp.post_position(RIDE, ME, SEALED_DOT, now=clock)
    assert ops == [rp.fcntl.LOCK_EX]
    assert json.loads((tmp_path / f"{RIDE}.json").read_text())["writes"][1] == 1


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
    assert rp.read(RIDE, YOU, now=clock) == {"dots": [], "alerts": [], "every_s": 5}
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
    # The post counts itself, in the same locked turn as its write.
    rp.post_position(RIDE, ME, SEALED_DOT, now=clock)
    assert rp.count_write(RIDE, now=clock) == 0
    assert rp.count_write(RIDE, now=clock) == 40  # the rest of the minute
    with pytest.raises(rp.Refused) as busy:
        rp.send_alert(RIDE, YOU, SEALED_ALERT, now=clock)
    assert busy.value.status == 429 and busy.value.retry_after_s == 40
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
    # The ride's write count is kept with the ride, never as a database row; a write counts
    # against the address's own write limit.
    assert seen == ["ride-post"]
    assert rp.store()._rides == {}
    monkeypatch.setattr(rp, "RIDE_WRITES_PER_MINUTE", 7500)
    seen.clear()
    assert client.get(f"/api/rides/{RIDE}", HTTP_X_RIDE_TOKEN=YOU).status_code == 200
    assert seen == ["ride-link"]
    refuse.add("ride-link")
    assert client.get(f"/api/rides/{RIDE}", HTTP_X_RIDE_TOKEN=YOU).status_code == 429
    # Generous: a whole ride's phones can share one carrier address: 20 marshals at 2 s and 100
    # watching at 5 s read...
    marshals, fastest = rp.PACE_S[0]
    assert ratelimit.RIDE_LINKS.requests >= marshals * 60 // fastest + 100 * 60 // rp.WATCH_PACE_S
    # ...and the 20 marshals post, with room for alerts...
    assert ratelimit.RIDE_POSTS.requests >= marshals * 60 // fastest + 60
    # ...yet one address cannot make a full ride of riders in a dot's 2 minutes.
    assert (
        ratelimit.RIDE_POSTS.requests * rp.KEEP_S // ratelimit.RIDE_POSTS.window_s
        < rp.MAX_RIDERS_PER_RIDE
    )


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


def test_the_pace_is_2_s_on_a_small_ride_and_slower_only_on_a_big_one(clock, monkeypatch) -> None:
    """Stephen 2026-10-31: "15 seconds is not enough to see slowdowns", "try to get it down", "If
    we limit to maybe 20 people at once, how low could that get?". A ride of up to 20 sharing goes
    every 2 s, one up to 300 every 5 s; the ride's lock sets a slower pace past 300 and 1,000
    riders, and the read says the pace so the phones follow it."""
    sizes = (1, 20, 21, 300, 301, 1000, 1001, rp.MAX_RIDERS_PER_RIDE)
    assert [rp.pace_s(n) for n in sizes] == [2, 2, 5, 5, 10, 10, 15, 15]
    rp.post_position(RIDE, ME, SEALED_DOT, now=clock)
    # The one sharing reads at the ride's pace; one only watching, at 5 s.
    assert rp.read(RIDE, ME, now=clock)["every_s"] == 2
    assert rp.read(RIDE, YOU, now=clock)["every_s"] == rp.WATCH_PACE_S == 5
    clock.t += 2
    rp.post_position(RIDE, ME, SEALED_DOT, now=clock)
    # A big ride: the read says the slower pace, and a phone that has not read it yet is not
    # refused for posting at 2 s (only the 1 s floor holds, on every ride).
    monkeypatch.setattr(rp, "PACE_S", ((0, 2), (1, 10)))
    clock.t += 2
    rp.post_position(RIDE, ME, SEALED_DOT, now=clock)
    clock.t += 0.25
    with pytest.raises(rp.Refused) as refused:
        rp.post_position(RIDE, ME, SEALED_DOT, now=clock)
    assert rp.MIN_POST_INTERVAL_S == 0.5 and refused.value.retry_after_s == 1
    clock.t += 1
    assert rp.read(RIDE, YOU, now=clock)["every_s"] == 10
    assert rp.read(RIDE, ME, now=clock)["every_s"] == 10
    # The pace counts dots, not tokens: 20 sharing and a watcher who sends an alert stay at 2 s.
    monkeypatch.setattr(rp, "PACE_S", ((1, 2), (300, 5)))
    clock.t += rp.ALERT_MIN_INTERVAL_S
    rp.send_alert(RIDE, THEM, SEALED_DOT, now=clock)
    rp.post_position(RIDE, ME, SEALED_DOT, now=clock)
    assert rp.read(RIDE, ME, now=clock)["every_s"] == 2
    assert rp.read(RIDE, THEM, now=clock)["every_s"] == rp.WATCH_PACE_S
    # Positions at that pace fit the ride's own write count.
    assert rp.MAX_RIDERS_PER_RIDE * 60 // rp.SLOWEST_PACE_S <= rp.RIDE_WRITES_PER_MINUTE
    assert max(most * 60 // every for most, every in rp.PACE_S) <= rp.RIDE_WRITES_PER_MINUTE


def _tmpfs(tmp_path, monkeypatch):
    store = rp.TmpfsStore(str(tmp_path))
    monkeypatch.setattr(rp, "store", lambda: store)
    return store


def test_a_tmpfs_read_drops_what_has_expired_from_the_file(tmp_path, clock, monkeypatch) -> None:
    """A read under the shared lock writes nothing, but what is past its 2 minutes is dropped
    from the ride's file at once, never left for the sweeper alone."""
    _tmpfs(tmp_path, monkeypatch)
    rp.post_position(RIDE, ME, SEALED_DOT, now=clock)
    rp.post_position(RIDE, YOU, _dot(1), now=clock)
    rp.send_alert(RIDE, ME, SEALED_DOT, now=clock)
    clock.t += rp.DOT_TTL_S - 10
    rp.post_position(RIDE, YOU, _dot(2), now=clock)
    clock.t += 11
    assert rp.read(RIDE, YOU, now=clock)["dots"] == []
    kept = json.loads((tmp_path / f"{RIDE}.json").read_text())
    assert ME not in kept["riders"] and kept["alerts"] == []
    assert SEALED_DOT not in (tmp_path / f"{RIDE}.json").read_text()


def test_a_refused_write_on_tmpfs_still_counts_against_the_ride(
    tmp_path, clock, monkeypatch
) -> None:
    """As in memory: a post refused as too soon still took the ride's lock, so it counts."""
    _tmpfs(tmp_path, monkeypatch)
    rp.post_position(RIDE, ME, SEALED_DOT, now=clock)
    for _ in range(3):
        with pytest.raises(rp.Refused):
            rp.post_position(RIDE, ME, SEALED_DOT, now=clock)
    assert json.loads((tmp_path / f"{RIDE}.json").read_text())["writes"][1] == 4


def test_the_poll_note_forgets_a_token_within_seconds(clock, monkeypatch) -> None:
    """Each process's note of a token's last read is kept only as long as the poll limit (never
    the 2 minutes, nor past them); a reader that never posted is not noted at all."""
    rp._polls.clear()
    rp.read(RIDE, YOU, now=clock)
    assert rp._polls == {}
    rp.post_position(RIDE, ME, SEALED_DOT, now=clock)
    rp.read(RIDE, ME, now=clock)
    assert (RIDE, ME) in rp._polls
    rp._forget_polls(clock.t + rp.MIN_POLL_INTERVAL_S - 1)
    assert (RIDE, ME) in rp._polls
    rp._forget_polls(clock.t + rp.MIN_POLL_INTERVAL_S)
    assert rp._polls == {}
    # Full of fresh notes: no more are kept (the limit falls back to the ride's own stamp).
    monkeypatch.setattr(rp, "POLLS_KEPT", 1)
    rp._note_poll(RIDE, ME, clock.t)
    rp._note_poll(RIDE, YOU, clock.t)
    assert list(rp._polls) == [(RIDE, ME)]
