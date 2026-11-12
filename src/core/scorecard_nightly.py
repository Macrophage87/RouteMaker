"""The nightly route scorecard on the live routers (docs/SCORECARD.md; the owner, 2026-11-12,
chose "Both": nightly on beta, and on the PC when he starts it).

Each night the worker plans the fixed trips (fixtures/scorecard/trips.json, public landmarks
only) through the app's own /api/route code, scores them (`routemaker.scorecard`), compares
them with the night before, and keeps the run (`ScorecardRun`). What moved goes on the run
row's detail, which the operations page shows, and `manage.py route_scorecard --latest-findings`
hands it to the beta's alert script for one Discord post a night when anything moved.

Only reads: /api/route saves nothing to any account. One plan at a time, a short pause between
plans, and the long-ride slot is taken as a rider's request takes it: a trip that finds it held
by a rider waits a minute and tries once more, then is recorded as not answered. Nothing runs
while a map rebuild is in progress. Every number here is our default, unmeasured.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from routemaker import scorecard

logger = logging.getLogger(__name__)

TRIPS_PATH = settings.BASE_DIR / "fixtures" / "scorecard" / "trips.json"
# Stop starting new plans after this long; the rest are recorded as not answered (our default).
BUDGET_S = 90 * 60
# Between plans, so the routers keep room for a rider at 3 AM (our default).
PAUSE_S = 2.0
# A plan refused because the slot it needs is busy waits this long and tries once more.
BUSY_RETRY_S = 60.0
BUSY_STATUSES = (429, 503)
# How many nights are kept (our default): two months of history, a few MB.
KEEP_RUNS = 60
# A weekly rebuild row this recent with no finish means a rebuild is running.
REBUILD_RUNNING_WITHIN = timedelta(hours=12)


def trips(path: Path = TRIPS_PATH) -> dict:
    return json.loads(Path(path).read_text())


def rebuild_running() -> bool:
    from core.models import ScheduledRun

    since = timezone.now() - REBUILD_RUNNING_WITHIN
    return ScheduledRun.objects.filter(
        task="weekly_rebuild", finished_at__isnull=True, started_at__gte=since
    ).exists()


def _status_and_data(answered) -> tuple[int, object]:
    """What the view would send: a plain answer is a 200, a ninja Status carries its own."""
    status = getattr(answered, "status_code", 200)
    for attr in ("value", "data", "body"):
        if hasattr(answered, attr) and not callable(getattr(answered, attr)):
            return status, getattr(answered, attr)
    return status, answered


def plan_one(body: dict) -> dict:
    """Plan one trip through the app's own /api/route path, serialized as the view sends it."""
    from django.contrib.auth.models import AnonymousUser
    from django.http import HttpResponse
    from django.test import RequestFactory

    from core import api, routing, walk_turns
    from routemaker import lang

    route_in = api.RouteIn.model_validate(body)
    request = RequestFactory().post("/api/route", content_type="application/json")
    request.user = AnonymousUser()
    request.routing_started = routing.clock()
    with lang.speaking(route_in.lang), walk_turns.stairs_avoided(route_in.avoid_stairs):
        answered = api._route_answer(request, route_in, HttpResponse())
    status, data = _status_and_data(answered)
    if status == 200:
        data = api.RouteOut.model_validate(data).model_dump(by_alias=True, mode="json")
    else:
        data = json.loads(json.dumps(data, default=str))
    return {"status": status, "body": data}


def plan_all(entries: list[dict], *, plan=plan_one, sleep=time.sleep, clock=time.monotonic):
    """Every entry's answer by key. One at a time; past `BUDGET_S` the rest are skipped."""
    started = clock()
    answers: dict[str, dict] = {}
    for entry in entries:
        if clock() - started > BUDGET_S:
            break
        try:
            got = plan(entry["body"])
            if got["status"] in BUSY_STATUSES:
                sleep(BUSY_RETRY_S)
                got = plan(entry["body"])
        except Exception as error:  # one trip's failure is a finding, not the night's
            logger.exception("scorecard plan %s failed", entry["key"])
            got = {"status": -1, "body": {"error": f"{type(error).__name__}: {error}"[:300]}}
        answers[entry["key"]] = got
        sleep(PAUSE_S)
    return answers


def findings_text(diff: dict, run: dict) -> str:
    """The night's findings in words, short enough for one Discord post."""
    lines = [
        f"{key.replace('|', ' · ')}: " + "; ".join(found)
        for key, found in diff.get("findings", {}).items()
    ]
    unstable = [
        f"{s['trip']} · {s['preset']}: start moved 150 ft changed the route"
        for s in run.get("checks", {}).get("stability", [])
        if not s["stable"]
    ]
    return "\n".join(lines + unstable)


def run_nightly(*, plan=plan_one, sleep=time.sleep) -> str:
    """One night's run: plan, score, compare, keep. Returns the run row's detail."""
    from core.models import ScorecardRun

    if rebuild_running():
        return "skipped: a map rebuild is running"
    entries = scorecard.plans(trips(), extra={"debug_junctions": True})
    answers = plan_all(entries, plan=plan, sleep=sleep)
    now = timezone.now()
    run = scorecard.run_of(
        entries,
        answers,
        {"label": f"nightly {now:%Y-%m-%d}", "answered": f"{len(answers)} of {len(entries)}"},
    )
    last = ScorecardRun.objects.order_by("-made_at").first()
    diff = scorecard.compare(last.data, run) if last is not None else {"findings": {}}
    text = findings_text(diff, run)
    failed = sum(1 for row in run["rows"].values() if row.get("status") != 200)
    moved = len(diff.get("findings", {}))
    ScorecardRun.objects.create(
        made_at=now,
        label=run["meta"]["label"],
        data=run,
        findings=text,
        findings_count=moved,
        failed_count=failed,
    )
    keep = ScorecardRun.objects.order_by("-made_at").values_list("pk", flat=True)[:KEEP_RUNS]
    ScorecardRun.objects.exclude(pk__in=list(keep)).delete()
    first = "" if last is not None else "; first run, nothing to compare with"
    return f"{len(answers)} of {len(entries)} planned, {failed} failed, {moved} moved{first}"
