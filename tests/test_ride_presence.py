"""Mass Ride and Group Ride links: dots and alerts (v0.7.0 plan; core.ride_presence).

Positions are rounded to 20 m, kept in memory for 2 minutes, never in the database or a log;
a rider sees the others, not themselves; updates and alerts are limited per token; alerts use the
plan's lists, merge the same issue near the same spot within 2 minutes, and last 10 minutes or
until the sender clears them.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from core import ride_presence as rp

RIDE = "a" * 64
ME, YOU, THEM = "1" * 32, "2" * 32, "3" * 32
SPOT = (-77.03651, 38.89768)


class Clock:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def clock() -> Clock:
    return Clock()


def test_a_position_is_rounded_to_about_20_m() -> None:
    lon, lat = rp.rounded(*SPOT)
    assert rp._distance_m((lon, lat), SPOT) <= 15  # half the grid's diagonal
    # Two readings a few metres apart land on the same kept spot.
    assert rp.rounded(SPOT[0] + 0.00002, SPOT[1] + 0.00002) == (lon, lat)


def test_others_see_my_dot_with_its_age_and_i_do_not_see_my_own(clock) -> None:
    rp.post_position(RIDE, ME, *SPOT, now=clock)
    clock.t += 40
    mine = rp.read(RIDE, ME, now=clock)
    assert mine["dots"] == []
    theirs = rp.read(RIDE, YOU, now=clock)
    assert len(theirs["dots"]) == 1
    dot = theirs["dots"][0]
    assert dot["age_s"] == 40
    assert (dot["lon"], dot["lat"]) == rp.rounded(*SPOT)
    assert set(dot) == {"lon", "lat", "age_s", "role"}  # no token, no id, no name
    assert dot["role"] == "participant"  # none sent: a participant


@pytest.mark.parametrize("role", ["participant", "lead", "sweep", "corker"])
def test_a_dot_carries_its_rider_s_role(clock, role) -> None:
    rp.post_position(RIDE, ME, *SPOT, role=role, now=clock)
    assert [d["role"] for d in rp.read(RIDE, YOU, now=clock)["dots"]] == [role]


@pytest.mark.parametrize("role", ["Lead", "marshal", 1, ["sweep"], {"r": "corker"}])
def test_a_role_not_of_the_four_is_refused(clock, role) -> None:
    with pytest.raises(rp.Refused) as refused:
        rp.post_position(RIDE, ME, *SPOT, role=role, now=clock)
    assert refused.value.status == 400
    assert rp.read(RIDE, YOU, now=clock)["dots"] == []


def test_a_changed_role_shows_on_the_next_reading(clock) -> None:
    rp.post_position(RIDE, ME, *SPOT, role="corker", now=clock)
    clock.t += rp.MIN_POST_INTERVAL_S
    rp.post_position(RIDE, ME, *SPOT, role="sweep", now=clock)
    assert rp.read(RIDE, YOU, now=clock)["dots"][0]["role"] == "sweep"


def test_a_dot_is_gone_after_2_minutes(clock) -> None:
    rp.post_position(RIDE, ME, *SPOT, now=clock)
    clock.t += rp.DOT_TTL_S + 1
    assert rp.read(RIDE, YOU, now=clock)["dots"] == []


def test_leaving_drops_the_dot_at_once(clock) -> None:
    rp.post_position(RIDE, ME, *SPOT, now=clock)
    rp.leave(RIDE, ME, now=clock)
    assert rp.read(RIDE, YOU, now=clock)["dots"] == []


def test_updates_are_limited_per_token(clock) -> None:
    rp.post_position(RIDE, ME, *SPOT, now=clock)
    clock.t += 5
    with pytest.raises(rp.Refused) as refused:
        rp.post_position(RIDE, ME, *SPOT, now=clock)
    assert refused.value.status == 429
    clock.t += 10
    rp.post_position(RIDE, ME, *SPOT, now=clock)
    rp.read(RIDE, ME, now=clock)
    with pytest.raises(rp.Refused):
        rp.read(RIDE, ME, now=clock)


def test_a_read_keeps_nothing_of_a_reader_before_its_first_position(clock) -> None:
    # A ride nobody has written to is not kept for a read.
    assert rp.read(RIDE, YOU, now=clock) == {"dots": [], "alerts": []}
    assert rp.store()._rides == {}
    # On a kept ride, the reader is not made a rider either.
    rp.post_position(RIDE, ME, *SPOT, now=clock)
    rp.read(RIDE, YOU, now=clock)
    rp.read(RIDE, THEM, now=clock)
    assert set(rp.store()._rides[RIDE]["riders"]) == {ME}


def test_live_alerts_on_a_ride_are_capped_and_the_oldest_goes(clock) -> None:
    first = None
    for n in range(rp.LIVE_ALERTS_PER_RIDE + 1):
        clock.t += 1
        sent = rp.send_alert(
            RIDE, f"{n:032x}", rp.MASS_RIDE, "spread", "", SPOT[0] + n * 0.01, SPOT[1], now=clock
        )
        first = first or sent["id"]
    alerts = rp.read(RIDE, ME, now=clock)["alerts"]
    assert len(alerts) == rp.LIVE_ALERTS_PER_RIDE
    assert first not in {a["id"] for a in alerts}


def _ride(n: int) -> str:
    return f"{n:064x}"


def _fill(clock) -> None:
    for n in range(rp.MAX_RIDES):
        rp.post_position(_ride(n), ME, *SPOT, now=clock)


def test_a_full_store_makes_room_from_rides_with_no_recent_position(clock, monkeypatch) -> None:
    monkeypatch.setattr(rp, "MAX_RIDES", 3)
    monkeypatch.setattr(rp, "time", SimpleNamespace(time=clock))
    _fill(clock)
    with pytest.raises(rp.Refused) as refused:
        rp.post_position(_ride(9), ME, *SPOT, now=clock)
    assert refused.value.status == 503
    # Two minutes on, with one ride still riding: the other two make room.
    clock.t += rp.DOT_TTL_S + 1
    rp.post_position(_ride(0), ME, *SPOT, now=clock)
    rp.post_position(_ride(9), ME, *SPOT, now=clock)
    assert set(rp.store()._rides) == {_ride(0), _ride(9)}


def test_the_tmpfs_store_makes_room_the_same_way(tmp_path, clock, monkeypatch) -> None:
    monkeypatch.setattr(rp, "MAX_RIDES", 2)
    monkeypatch.setattr(rp, "time", SimpleNamespace(time=clock))
    monkeypatch.setattr(rp, "store", lambda: store)
    store = rp.TmpfsStore(str(tmp_path))
    _fill(clock)
    with pytest.raises(rp.Refused):
        rp.post_position(_ride(9), ME, *SPOT, now=clock)
    # A read of a ride not kept takes no room and writes no file.
    rp.read(_ride(8), YOU, now=clock)
    assert len(list(tmp_path.iterdir())) == 2
    clock.t += rp.DOT_TTL_S + 1
    rp.post_position(_ride(1), ME, *SPOT, now=clock)
    rp.post_position(_ride(9), ME, *SPOT, now=clock)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == [f"{_ride(1)}.json", f"{_ride(9)}.json"]


@pytest.mark.parametrize(
    "ride,token,spot",
    [("nope", ME, SPOT), (RIDE, "short", SPOT), (RIDE, ME, (-80.5, 40.0)), (RIDE, ME, ("x", 1))],
)
def test_bad_requests_are_refused(clock, ride, token, spot) -> None:
    with pytest.raises(rp.Refused):
        rp.post_position(ride, token, *spot, now=clock)


def test_the_alert_lists_are_the_plan_s() -> None:
    mass = [k.label for k in rp.ALERT_KINDS[rp.MASS_RIDE]]
    group = [k.label for k in rp.ALERT_KINDS[rp.GROUP_RIDE]]
    assert mass == [
        "Extensive rider spread",
        "Emergency vehicle coming through",
        "Aggressive person",
        "Medical emergency or crash",
        "Rerouting, road closed",
        "Lost, separated from the ride",
        "Other",
    ]
    assert group == [
        "Rider off the back",
        "Crash",
        "Mechanical or flat, stopping",
        "Wrong turn",
        "Lost, separated from the group",
        "Wait up, regroup",
        "Other",
    ]
    confirm = {k.id for ks in rp.ALERT_KINDS.values() for k in ks if k.confirm}
    assert confirm == {"medical", "crash"}


def test_an_alert_reaches_everyone_and_the_same_issue_nearby_merges(clock) -> None:
    sent = rp.send_alert(RIDE, ME, rp.GROUP_RIDE, "off_back", "", *SPOT, now=clock)
    assert sent["count"] == 1 and sent["mine"] and sent["label"] == "Rider off the back"
    clock.t += 30
    # Another rider, 50 m away, 30 s later: one alert, "2 riders reported".
    merged = rp.send_alert(
        RIDE, YOU, rp.GROUP_RIDE, "off_back", "", SPOT[0] + 0.0005, SPOT[1], now=clock
    )
    assert merged["id"] == sent["id"] and merged["count"] == 2
    seen = rp.read(RIDE, THEM, now=clock)["alerts"]
    assert len(seen) == 1 and seen[0]["count"] == 2 and seen[0]["age_s"] == 0
    assert not seen[0]["mine"]
    # Far away, or another issue: a separate alert.
    clock.t += 61
    rp.send_alert(RIDE, ME, rp.GROUP_RIDE, "off_back", "", SPOT[0] + 0.05, SPOT[1], now=clock)
    assert len(rp.read(RIDE, THEM, now=clock)["alerts"]) == 2


def test_merging_stops_after_2_minutes(clock) -> None:
    first = rp.send_alert(RIDE, ME, rp.MASS_RIDE, "spread", "", *SPOT, now=clock)
    clock.t += rp.MERGE_WITHIN_S + 1
    later = rp.send_alert(RIDE, YOU, rp.MASS_RIDE, "spread", "", *SPOT, now=clock)
    assert later["id"] != first["id"]


def test_alert_limits_one_a_minute_and_ten_a_ride(clock) -> None:
    rp.send_alert(RIDE, ME, rp.MASS_RIDE, "spread", "", *SPOT, now=clock)
    with pytest.raises(rp.Refused) as refused:
        rp.send_alert(RIDE, ME, rp.MASS_RIDE, "spread", "", *SPOT, now=clock)
    assert refused.value.status == 429 and refused.value.retry_after_s
    for _ in range(9):
        clock.t += 61
        rp.send_alert(RIDE, ME, rp.MASS_RIDE, "aggressive", "", *SPOT, now=clock)
    clock.t += 61
    with pytest.raises(rp.Refused) as refused:
        rp.send_alert(RIDE, ME, rp.MASS_RIDE, "aggressive", "", *SPOT, now=clock)
    assert "10 alerts" in refused.value.message


def test_other_takes_up_to_80_characters_and_kinds_follow_the_ride_type(clock) -> None:
    with pytest.raises(rp.Refused):
        rp.send_alert(RIDE, ME, rp.MASS_RIDE, "other", "x" * 81, *SPOT, now=clock)
    with pytest.raises(rp.Refused):
        rp.send_alert(RIDE, ME, rp.MASS_RIDE, "off_back", "", *SPOT, now=clock)
    sent = rp.send_alert(RIDE, ME, rp.MASS_RIDE, "other", "Pothole at the bridge", *SPOT, now=clock)
    assert sent["text"] == "Pothole at the bridge"


def test_medical_and_crash_carry_call_911(clock) -> None:
    sent = rp.send_alert(RIDE, ME, rp.MASS_RIDE, "medical", "", *SPOT, now=clock)
    assert sent["call_911"] is True
    clock.t += 61
    other = rp.send_alert(RIDE, ME, rp.MASS_RIDE, "spread", "", *SPOT, now=clock)
    assert other["call_911"] is False


def test_alerts_last_10_minutes_or_until_the_sender_clears_them(clock) -> None:
    sent = rp.send_alert(RIDE, ME, rp.MASS_RIDE, "spread", "", *SPOT, now=clock)
    with pytest.raises(rp.Refused) as refused:
        rp.clear_alert(RIDE, YOU, sent["id"], now=clock)
    assert refused.value.status == 403
    rp.clear_alert(RIDE, ME, sent["id"], now=clock)
    assert rp.read(RIDE, YOU, now=clock)["alerts"] == []
    clock.t += 61
    rp.send_alert(RIDE, ME, rp.MASS_RIDE, "spread", "", *SPOT, now=clock)
    clock.t += rp.ALERT_TTL_S + 1
    assert rp.read(RIDE, THEM, now=clock)["alerts"] == []


def test_a_directory_not_on_a_tmpfs_is_never_used(tmp_path, settings, monkeypatch) -> None:
    monkeypatch.setattr(rp, "_start_sweeper", lambda _store: None)
    settings.RIDE_PRESENCE_DIR = str(tmp_path)
    rp._store = None
    store = rp.store()
    if rp._on_tmpfs(str(tmp_path)):
        pytest.skip("the test's temporary directory is itself a tmpfs here")
    assert isinstance(store, rp.MemoryStore)
    rp.post_position(RIDE, ME, *SPOT)
    assert list(tmp_path.iterdir()) == []


def test_the_tmpfs_store_shares_state_and_removes_an_empty_ride(tmp_path) -> None:
    store = rp.TmpfsStore(str(tmp_path))
    with store.ride(RIDE) as state:
        state["riders"][ME] = {"since": 1.0, "lon": 1.0, "lat": 2.0, "at": 1.0}
    with rp.TmpfsStore(str(tmp_path)).ride(RIDE) as again:
        assert again["riders"][ME]["lon"] == 1.0
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
        state["riders"][ME] = {"since": 1.0, "lon": 1.0, "lat": 2.0, "at": 1.0}
    assert len(calls) == 2
    monkeypatch.setattr(rp.fcntl, "flock", real)
    with rp.TmpfsStore(str(tmp_path)).ride(RIDE) as again:
        assert again["riders"][ME]["lon"] == 1.0


@pytest.mark.django_db
def test_the_endpoints_keep_positions_out_of_the_database_and_logs(client, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    headers = {"HTTP_X_FORWARDED_FOR": "198.51.100.9"}
    queries = CaptureQueriesContext(connection)
    queries.__enter__()
    wrong = client.post(
        f"/api/rides/{RIDE}/here",
        data=json.dumps({"token": ME, "lon": SPOT[0], "lat": SPOT[1], "role": "captain"}),
        content_type="application/json",
        **headers,
    )
    assert wrong.status_code == 400
    r = client.post(
        f"/api/rides/{RIDE}/here",
        data=json.dumps({"token": ME, "lon": SPOT[0], "lat": SPOT[1], "role": "sweep"}),
        content_type="application/json",
        **headers,
    )
    assert r.status_code == 200
    r = client.get(f"/api/rides/{RIDE}", HTTP_X_RIDE_TOKEN=YOU, **headers)
    assert r.status_code == 200 and [d["role"] for d in r.json()["dots"]] == ["sweep"]
    assert r["Cache-Control"] == "no-store"
    alert = client.post(
        f"/api/rides/{RIDE}/alerts",
        data=json.dumps(
            {
                "token": ME,
                "ride_type": "group-ride",
                "kind": "crash",
                "lon": SPOT[0],
                "lat": SPOT[1],
            }
        ),
        content_type="application/json",
        **headers,
    )
    assert alert.status_code == 200 and alert.json()["call_911"] is True
    clear = client.post(
        f"/api/rides/{RIDE}/alerts/{alert.json()['id']}/clear",
        data=json.dumps({"token": ME}),
        content_type="application/json",
        **headers,
    )
    assert clear.status_code == 200
    too_soon = client.post(
        f"/api/rides/{RIDE}/here",
        data=json.dumps({"token": ME, "lon": SPOT[0], "lat": SPOT[1]}),
        content_type="application/json",
        **headers,
    )
    assert too_soon.status_code == 429 and too_soon["Retry-After"]
    logged = " ".join(record.getMessage() for record in caplog.records)
    assert "38.89" not in logged and "-77.03" not in logged
    queries.__exit__(None, None, None)
    # The database sees only the rate limits' counts, by keyed digest: never a position, a
    # token or a ride.
    sql = [str(q["sql"]) for q in queries.captured_queries]
    assert sql and all("rate_limit_window" in q for q in sql)
    assert not any(v in q for q in sql for v in ("38.89", "-77.03", ME, RIDE))


@pytest.mark.django_db
def test_the_endpoints_are_limited_per_address_and_writes_per_ride(client, monkeypatch) -> None:
    from core import ratelimit

    seen = []
    refuse = {"ride-write"}

    def hit(limit, key):
        seen.append(limit.scope)
        allowed = limit.scope not in refuse
        return ratelimit.Decision(allowed=allowed, retry_after_s=0 if allowed else 7)

    monkeypatch.setattr(ratelimit, "hit", hit)
    body = json.dumps({"token": ME, "lon": SPOT[0], "lat": SPOT[1]})
    busy = client.post(f"/api/rides/{RIDE}/here", data=body, content_type="application/json")
    assert busy.status_code == 429 and busy["Retry-After"] == "7"
    assert seen == ["ride-link", "ride-write"]
    assert rp.store()._rides == {}
    refuse.clear()
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


def test_a_broadcast_links_leader_key_marks_the_sharers_dot_only(clock) -> None:
    rp.post_position(RIDE, ME, *SPOT, role="lead", now=clock)
    rp.post_position(RIDE, THEM, SPOT[0] + 0.001, SPOT[1], role="lead", now=clock)
    key = rp.leader_key(ME)
    assert rp.LEADER_KEY.match(key) and key != ME  # the link never carries the token itself
    dots = rp.read(RIDE, YOU, now=clock, leader=key)["dots"]
    leaders = [d for d in dots if d.get("leader")]
    assert len(leaders) == 1
    assert (leaders[0]["lon"], leaders[0]["lat"]) == rp.rounded(*SPOT)
    # Without a key, or with one that is not 32 hex digits, no dot is marked.
    assert not any(d.get("leader") for d in rp.read(RIDE, THEM, now=clock)["dots"])
    clock.t += 5
    assert not any(d.get("leader") for d in rp.read(RIDE, YOU, now=clock, leader="x" * 32)["dots"])


@pytest.mark.django_db
def test_the_api_reads_the_leader_key_from_its_header(client, clock, monkeypatch) -> None:
    monkeypatch.setattr(rp.time, "time", clock)
    client.post(
        f"/api/rides/{RIDE}/here",
        data=json.dumps({"token": ME, "lon": SPOT[0], "lat": SPOT[1], "role": "lead"}),
        content_type="application/json",
    )
    r = client.get(
        f"/api/rides/{RIDE}", HTTP_X_RIDE_TOKEN=YOU, HTTP_X_RIDE_LEADER=rp.leader_key(ME)
    )
    assert r.status_code == 200
    assert r.json()["dots"][0]["leader"] is True


ROUTE = [[-77.03651, 38.89768], [-77.03, 38.9], [-77.02, 38.91]]


def test_the_leaders_path_reaches_only_readers_with_its_key_and_goes_after_2_minutes(clock) -> None:
    rp.post_path(RIDE, ME, ROUTE, [list(SPOT), [SPOT[0] + 0.001, SPOT[1]]], now=clock)
    key = rp.leader_key(ME)
    path = rp.read(RIDE, YOU, now=clock, leader=key)["leader_path"]
    assert path["route"] == [[round(x, 5), round(y, 5)] for x, y in ROUTE]
    # The ridden path is on the dots' 20 m grid.
    assert path["trail"][0] == list(rp.rounded(*SPOT))
    assert path["age_s"] == 0
    # No key, or another rider's key: no path.
    assert "leader_path" not in rp.read(RIDE, THEM, now=clock)
    clock.t += 5
    assert "leader_path" not in rp.read(RIDE, THEM, now=clock, leader=rp.leader_key(YOU))
    # Gone 2 minutes after it was sent: the phone sends it again before then.
    clock.t += rp.PATH_TTL_S
    assert "leader_path" not in rp.read(RIDE, YOU, now=clock, leader=key)


def test_a_path_is_bounded_checked_and_not_sent_too_often(clock) -> None:
    rp.post_path(RIDE, ME, ROUTE, [], now=clock)
    with pytest.raises(rp.Refused) as soon:
        rp.post_path(RIDE, ME, ROUTE, [], now=clock)
    assert soon.value.status == 429
    clock.t += rp.MIN_PATH_INTERVAL_S
    rp.post_path(RIDE, ME, ROUTE[:2], None, now=clock)
    # Points outside the map's area are left out, not refused.
    rp.post_path(RIDE, THEM, [[0, 0], ROUTE[0]], [], now=clock)
    key = rp.leader_key(THEM)
    assert rp.read(RIDE, YOU, now=clock, leader=key)["leader_path"]["route"] == [ROUTE[0]]
    for bad in ([[1, "x"]], [[-77.0, 38.9, 3]], "nope", [[-77.0, 38.9]] * (rp.PATH_MAX_POINTS + 1)):
        with pytest.raises(rp.Refused) as refused:
            rp.post_path(RIDE, YOU, bad, [], now=clock)
        assert refused.value.status == 400
    # Leaving drops the path at once.
    rp.leave(RIDE, ME, now=clock)
    assert "leader_path" not in rp.read(RIDE, YOU, now=clock, leader=rp.leader_key(ME))


def test_a_ride_holds_a_few_paths_at_most(clock) -> None:
    for i in range(rp.PATHS_PER_RIDE):
        rp.post_path(RIDE, f"{i:032x}", ROUTE, [], now=clock)
    with pytest.raises(rp.Refused) as full:
        rp.post_path(RIDE, "f" * 32, ROUTE, [], now=clock)
    assert full.value.status == 503


@pytest.mark.django_db
def test_the_api_takes_a_path_in_a_post_body(client, clock, monkeypatch) -> None:
    monkeypatch.setattr(rp.time, "time", clock)
    r = client.post(
        f"/api/rides/{RIDE}/path",
        data=json.dumps({"token": ME, "route": ROUTE, "trail": [list(SPOT)]}),
        content_type="application/json",
    )
    assert r.status_code == 200
    key = rp.leader_key(ME)
    r = client.get(f"/api/rides/{RIDE}", HTTP_X_RIDE_TOKEN=YOU, HTTP_X_RIDE_LEADER=key)
    assert len(r.json()["leader_path"]["route"]) == 3


def test_nothing_about_a_ride_stays_past_2_minutes(clock) -> None:
    # Stephen 2026-10-22: "For privacy, nothing stays on the server for more than 2 min".
    rp.post_position(RIDE, ME, *SPOT, now=clock)
    rp.post_path(RIDE, ME, ROUTE, [list(SPOT)], now=clock)
    rp.send_alert(RIDE, ME, rp.GROUP_RIDE, "lost", "", *SPOT, now=clock)
    clock.t += rp.KEEP_S + 1
    rp.read(RIDE, YOU, now=clock)  # a read prunes
    with rp.store().ride(RIDE, create=False) as state:
        assert state == {"riders": {}, "alerts": []}


def _left_behind(clock) -> None:
    """A leader's dot, path and alert, then 2 minutes in which nobody opens the ride."""
    rp.post_position(RIDE, ME, *SPOT, now=clock)
    rp.post_path(RIDE, ME, ROUTE, [list(SPOT)], now=clock)
    rp.send_alert(RIDE, ME, rp.GROUP_RIDE, "lost", "", *SPOT, now=clock)


def test_a_ride_nobody_opens_again_is_swept_after_2_minutes(clock) -> None:
    # The v0.12.0 end review: a prune only on a read left a ride whose phones had all closed
    # the link in memory until someone opened it again.
    _left_behind(clock)
    rp.post_position(_ride(1), YOU, *SPOT, now=clock)
    rp.store().sweep(clock.t + rp.KEEP_S - 1)
    assert set(rp.store()._rides) == {RIDE, _ride(1)}
    rp.store().sweep(clock.t + rp.KEEP_S + 1)
    assert rp.store()._rides == {}


def test_the_tmpfs_store_sweeps_every_ride_too(tmp_path, clock, monkeypatch) -> None:
    store = rp.TmpfsStore(str(tmp_path))
    monkeypatch.setattr(rp, "store", lambda: store)
    _left_behind(clock)
    rp.post_position(_ride(1), YOU, *SPOT, now=clock)
    # A dot past 2 minutes is written out of the file while its token's counts still count.
    clock.t += rp.DOT_TTL_S + 1
    rp.post_position(_ride(1), THEM, *SPOT, now=clock)
    store.sweep(clock.t)
    assert sorted(p.name for p in tmp_path.iterdir()) == [f"{_ride(1)}.json"]
    kept = json.loads((tmp_path / f"{_ride(1)}.json").read_text())
    assert "lon" not in kept["riders"].get(YOU, {}) and "lon" in kept["riders"][THEM]
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
