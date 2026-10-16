"""Mass Ride and Group Ride links: dots and alerts (v0.7.0 plan; core.ride_presence).

Positions are rounded to 20 m, kept in memory for 2 minutes, never in the database or a log;
a rider sees the others, not themselves; updates and alerts are limited per token; alerts use the
plan's lists, merge the same issue near the same spot within 2 minutes, and last 10 minutes or
until the sender clears them.
"""

from __future__ import annotations

import json
import logging

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
    rp.read(RIDE, YOU, now=clock)
    with pytest.raises(rp.Refused):
        rp.read(RIDE, YOU, now=clock)


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
        "Other",
    ]
    assert group == [
        "Rider off the back",
        "Crash",
        "Mechanical or flat, stopping",
        "Wrong turn",
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


def test_a_directory_not_on_a_tmpfs_is_never_used(tmp_path, settings) -> None:
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
    # Not one write to the database, nor a read: dots and alerts never touch it.
    assert [q["sql"] for q in queries.captured_queries] == []


def test_a_foreign_page_is_refused(client) -> None:
    r = client.get(f"/api/rides/{RIDE}", HTTP_X_RIDE_TOKEN=ME, HTTP_SEC_FETCH_SITE="cross-site")
    assert r.status_code == 403
