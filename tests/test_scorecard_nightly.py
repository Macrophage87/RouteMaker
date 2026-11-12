"""The nightly route scorecard on the live routers (core.scorecard_nightly, docs/SCORECARD.md):
it plans one trip at a time, gives a busy slot one more try, keeps one trip's failure to that
trip, stops at its budget, compares with the night before, keeps a bounded history, skips a
night with a map rebuild running, and hands the alert script one short post."""

from __future__ import annotations

from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from core import scorecard_nightly
from core.models import ScheduledRun, ScorecardRun
from routemaker import scorecard

MI = scorecard.METRES_PER_MILE


def answer(miles: float = 2.0) -> dict:
    k = 111_320.0 * 0.7771
    coords = [[-77.0 + i * 50 / k, 38.9] for i in range(int(miles * MI / 50) + 1)]
    return {
        "distance_m": miles * MI,
        "duration_s": miles * 300,
        "junction_delay_s": 30.0,
        "geometry": {"type": "LineString", "coordinates": coords},
        "stress_m": {"1": miles * MI, "2": 0, "3": 0, "4": 0, "5": 0, "unknown": 0},
        "facility_m": {"path": 0, "protected": 0, "lane": 0, "none": miles * MI, "unknown": 0},
        "stress_spans": [],
        "intersections": [],
        "junctions_debug": [],
        "description": [],
        "detour": {"ratio": 1.1, "basis": "direct_route"},
        "calm_search": None,
    }


ENTRIES = [
    {
        "key": f"t{i}|default|base",
        "trip": f"t{i}",
        "preset": "default",
        "variant": "base",
        "body": {"points": [[-77.0, 38.9], [-76.97, 38.9]], "preset": "default"},
    }
    for i in range(3)
]


def test_a_busy_slot_gets_one_more_try_and_a_crash_stays_with_its_trip():
    calls = []

    def plan(body):
        calls.append(body)
        n = len(calls)
        if n == 1:
            return {"status": 429, "body": {"error": "busy"}}
        if n == 3:
            raise RuntimeError("router fell over")
        return {"status": 200, "body": answer()}

    slept = []
    answers = scorecard_nightly.plan_all(ENTRIES, plan=plan, sleep=slept.append)
    assert answers["t0|default|base"]["status"] == 200
    assert answers["t1|default|base"]["status"] == -1
    assert "router fell over" in answers["t1|default|base"]["body"]["error"]
    assert answers["t2|default|base"]["status"] == 200
    assert scorecard_nightly.BUSY_RETRY_S in slept
    assert slept.count(scorecard_nightly.PAUSE_S) == 3


def test_the_budget_stops_new_plans():
    ticks = iter([0, 0, scorecard_nightly.BUDGET_S + 1, scorecard_nightly.BUDGET_S + 2])
    answers = scorecard_nightly.plan_all(
        ENTRIES,
        plan=lambda body: {"status": 200, "body": answer()},
        sleep=lambda s: None,
        clock=lambda: next(ticks),
    )
    assert list(answers) == ["t0|default|base"]


@pytest.fixture
def few_trips(monkeypatch):
    trips = {
        "when": "weekday_rush",
        "contrast_presets": [],
        "trips": [
            {
                "id": "a",
                "setting": "urban",
                "points": [[-77.0, 38.9], [-76.97, 38.9]],
                "presets": ["default"],
            },
            {
                "id": "b",
                "setting": "urban",
                "points": [[-77.0, 38.91], [-76.97, 38.91]],
                "presets": ["default"],
            },
        ],
    }
    monkeypatch.setattr(scorecard_nightly, "trips", lambda: trips)
    return trips


@pytest.mark.django_db
def test_two_nights_compare_and_the_findings_reach_the_alert_script(few_trips):
    detail = scorecard_nightly.run_nightly(
        plan=lambda body: {"status": 200, "body": answer(2.0)}, sleep=lambda s: None
    )
    assert detail == "2 of 2 planned, 0 failed, 0 moved; first run, nothing to compare with"
    out = StringIO()
    call_command("route_scorecard", "--latest-findings", stdout=out)
    assert out.getvalue() == "", "nothing moved: nothing to post"

    def second(body):
        miles = 3.0 if body["points"][0][1] == 38.9 else 2.0
        return {"status": 200, "body": answer(miles)}

    detail = scorecard_nightly.run_nightly(plan=second, sleep=lambda s: None)
    assert detail == "2 of 2 planned, 0 failed, 1 moved"
    newest = ScorecardRun.objects.order_by("-made_at").first()
    assert newest.findings_count == 1
    assert "a · default · base: miles 2.00 -> 3.00" in newest.findings
    out = StringIO()
    call_command("route_scorecard", "--latest-findings", stdout=out)
    first, *rest = out.getvalue().splitlines()
    assert first == str(newest.pk)
    assert "1 trips moved" in rest[0] and "miles 2.00 -> 3.00" in "\n".join(rest)

    # A day old, it is not posted again.
    ScorecardRun.objects.filter(pk=newest.pk).update(made_at=timezone.now() - timedelta(days=1))
    out = StringIO()
    call_command("route_scorecard", "--latest-findings", stdout=out)
    assert out.getvalue() == ""

    out = StringIO()
    call_command("route_scorecard", "--report", stdout=out)
    assert "# Route scorecard" in out.getvalue()


@pytest.mark.django_db
def test_history_is_bounded(few_trips, monkeypatch):
    monkeypatch.setattr(scorecard_nightly, "KEEP_RUNS", 2)
    for _ in range(3):
        scorecard_nightly.run_nightly(
            plan=lambda body: {"status": 200, "body": answer()}, sleep=lambda s: None
        )
    assert ScorecardRun.objects.count() == 2


@pytest.mark.django_db
def test_a_night_with_a_rebuild_running_is_skipped(few_trips):
    ScheduledRun.objects.create(task="weekly_rebuild", started_at=timezone.now())

    def never(body):
        raise AssertionError("planned during a rebuild")

    assert scorecard_nightly.run_nightly(plan=never) == "skipped: a map rebuild is running"
    assert ScorecardRun.objects.count() == 0
