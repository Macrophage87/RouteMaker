"""`manage.py check_operations` - the alert, for something outside Django.

The admin page answers the same question for a person who is already logged in.
This answers it for a cron entry, an uptime check or a container health probe:
it prints what is wrong and exits non-zero if anything is, which is the whole
interface such a thing needs. Without it the plan's alert list - backup not
succeeded in 26 hours, rebuild not completed in 8 days, worker heartbeat silent
for 10 minutes - has no way to reach anyone who is not looking at the admin.

It is read-only and it opens one database connection, so it is safe to run from
a health check every minute. The fourth check - free space on the tiles volume -
is a `statvfs` on the path the rebuild's disk gate measures, which costs the
same nothing.

That fourth check only means anything in a container that has the tiles volume
mounted, and this command is a cron entry whose container is a deployment
choice. So a missing `TILES_DIR` is an alert rather than a silence: it is the
one outcome where the check has no coverage at all, and a monitor that exits 0
while a quarter of it is structurally blind is the same silence the check was
added to break. It is also the cheapest alert there is to clear - mount the
volume, or run the entry where it is mounted - and it clears for good, so it
costs one page rather than a recurring one.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from core import transit
from core.management.commands.unwedge_job import STALLED_WORKER_TIMEOUT_S
from core.runs import (
    DISK_SHORT,
    DISK_UNMEASURED,
    disk_headroom,
    failed_job_count,
    failed_jobs,
    paused_task_details,
    stale_task_details,
    unmeasured_disk_message,
    wedged_jobs,
)

# Deliberately the shell convention rather than a richer set: monitoring tools
# read "zero or not zero", and a scheme with more codes in it invites a check
# that treats one kind of breakage as success.
EXIT_OK = 0
EXIT_ALERT = 1

# How long after a swap the routers may still be on the old build before it is an
# alert: valhalla_service does not reload tiles, so they serve the previous build
# until something restarts them, and an hour leaves the deploy host room to do it.
ROUTER_RESTART_GRACE = timedelta(hours=1)
# A router that does not answer in this long is left to the other checks: this
# one is about a router that answers from the wrong build.
ROUTER_STATUS_TIMEOUT_S = 3.0


def router_tileset_modified(url: str) -> int | None:
    """The `tileset_last_modified` a Valhalla router reports on `/status`, or None
    when it does not answer or does not say."""
    try:
        with urllib.request.urlopen(  # noqa: S310 - a configured router URL
            url.rstrip("/") + "/status", timeout=ROUTER_STATUS_TIMEOUT_S
        ) as response:
            value = json.loads(response.read()).get("tileset_last_modified")
    except (OSError, ValueError, AttributeError):
        return None
    return int(value) if isinstance(value, int | float) and value > 0 else None


def stale_routers(
    rows: Iterable,
    tiles_dir: Path,
    now: datetime,
    status: Callable[[str], int | None] = router_tileset_modified,
) -> list[str]:
    """One line per router still serving a build other than its promoted one.

    A router loads `<variant>/current/tiles.tar` when it starts and reports that
    file's modification time; after a swap or a rollback `current` names another
    file, so a router that was not restarted reports a time that is not the
    promoted file's. Rows changed inside the grace are skipped, and so is a router
    that does not answer, and a variant whose tiles this container cannot see.
    """
    lines = []
    for row in rows:
        if not row.build_id or now - row.updated_at < ROUTER_RESTART_GRACE:
            continue
        try:
            promoted = int(
                os.stat(Path(tiles_dir) / row.variant / "current" / "tiles.tar").st_mtime
            )
        except OSError:
            continue
        loaded = status(row.url)
        if loaded is None or abs(loaded - promoted) <= 1:
            continue
        lines.append(
            f"router: {row.variant} is not serving build {row.build_id}, promoted at "
            f"{row.updated_at:%Y-%m-%d %H:%M} UTC; restart it (docs/OPERATIONS.md, "
            '"After a rebuild: restart the routers")'
        )
    return lines


class Command(BaseCommand):
    help = (
        "Report stale scheduled tasks, wedged jobs, failed jobs and a data volume that is "
        "close to refusing the next rebuild; exit non-zero if any of them is the case."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--failed-job-limit",
            type=int,
            default=25,
            help=(
                "How many failed jobs to list. The count on the last line is all of them, "
                "and the listing says so when it is showing fewer."
            ),
        )

    def handle(self, *args, **options) -> None:
        stale = stale_task_details()
        paused = paused_task_details()
        wedged = wedged_jobs()
        jobs = failed_jobs(options["failed_job_limit"])
        failed_total = failed_job_count()
        # The fourth check. The disk gate is a hard refusal with "grow the
        # volume" as its only remedy, and nothing reported the volume before
        # that refusal arrived - so the first an operator heard of it was a
        # rebuild that did not run, a week after it could have been fixed.
        headroom = disk_headroom()
        # The transit ride types' timetables, when installed: under three weeks left
        # (`transit.STALE_DAYS`) is an alert.
        transit_alert = transit.schedule_alert(settings.TRANSIT_SCHEDULE_PATH)
        # Routers left on last week's graph after a swap: nothing restarts them on
        # its own, and nothing else notices until a new closure is not routed.
        from core.models import ValhallaUpstream

        routers = stale_routers(
            ValhallaUpstream.objects.all(), Path(settings.TILES_DIR), timezone.now()
        )

        for entry in stale:
            last = entry["last_success_at"] or "never"
            self.stdout.write(
                f"stale: {entry['task']} has no success inside {entry['window_s']}s "
                f"(last success: {last})"
            )
        # Paused, not stale (OWNER-DECISIONS 355): said, and not an alert.
        for entry in paused:
            last = entry["last_success_at"] or "never"
            self.stdout.write(
                f"paused: {entry['task']} (WEEKLY_REBUILD_PAUSED; last paused tick "
                f"{entry['paused_at'] or 'none'}, last success: {last})"
            )
        # The row that did not exist. A worker killed mid-job leaves its job
        # `doing` forever - the process that would have written `failed` is
        # gone - so a rebuild killed at hour three was on no surface at all
        # until `weekly_rebuild` went stale eight days later, while the job
        # holding the rebuild queue's only slot was never going to move.
        for entry in wedged:
            why = (
                f"its worker is gone (no heartbeat for over {STALLED_WORKER_TIMEOUT_S:.0f}s) "
                f"after {entry['age_s']:.0f}s of its {entry['budget_s']:.0f}s budget"
                if entry.get("worker_gone") and entry["age_s"] < entry["budget_s"]
                else f"has been running for {entry['age_s']:.0f}s, past its "
                f"{entry['budget_s']:.0f}s budget"
            )
            self.stdout.write(
                f"wedged job: {entry['id']} {entry['task']} on {entry['queue']} {why} "
                f"(started: {entry['started_at']}) - {entry['remedy']}"
            )
        # A rebuild budget the settings could not read: every service runs on the
        # default, and the rebuild refuses to start until it is fixed.
        bad_budget = getattr(settings, "REBUILD_TIMEOUT_INVALID", None)
        if bad_budget is not None:
            self.stdout.write(
                f"config: REBUILD_TIMEOUT_S={bad_budget!r} is not "
                f"{settings.REBUILD_TIMEOUT_RULE}; the rebuild refuses to start until it is "
                "fixed in .env and the services are recreated"
            )
        for job in jobs:
            self.stdout.write(
                f"failed job: {job.id} {job.task_name} on {job.queue_name} "
                f"after {job.attempts} attempts (last event: {job.last_event_at or 'unknown'})"
            )
        if headroom["status"] == DISK_UNMEASURED:
            self.stdout.write(f"disk: {unmeasured_disk_message(headroom)}")
        elif headroom["status"] == DISK_SHORT:
            self.stdout.write(
                f"disk: {headroom['path']} has "
                f"{headroom['free_bytes'] / 1024**3:.1f} GiB free of "
                f"{headroom['total_bytes'] / 1024**3:.1f} GiB; a rebuild reserving the "
                f"{headroom['minimum_free_bytes'] / 1024**3:.1f} GiB floor would leave it "
                f"{headroom['fraction_after']:.0%} full, against the "
                f"{headroom['fraction']:.0%} disk gate. Grow the volume before the next "
                "rebuild refuses to start."
            )
        if transit_alert is not None:
            self.stdout.write(transit_alert)
        for line in routers:
            self.stdout.write(line)
        if len(jobs) < failed_total:
            self.stdout.write(
                f"(listing the {len(jobs)} newest of {failed_total} failed jobs; "
                "--failed-job-limit lists more)"
            )
        if (
            not stale
            and not wedged
            and not failed_total
            and not headroom["alert"]
            and bad_budget is None
            and transit_alert is None
            and not routers
        ):
            # The free-space clause names the path and the figure rather than
            # asserting room in the abstract. "room for a rebuild" was printed
            # on a container that had measured its own root filesystem, and a
            # reassurance with no path and no number in it cannot be read
            # against the volume it is supposed to be about.
            self.stdout.write(
                "ok: no stale tasks, no wedged jobs, no failed jobs, "
                f"{headroom['path']} has {headroom['free_bytes'] / 1024**3:.1f} GiB free "
                "for a rebuild"
            )
            sys.exit(EXIT_OK)
        # The total rather than the length of the list above it. Reporting the
        # length reported the limit: 400 failed jobs and a limit of 25 printed
        # "25 failed job(s)" every run, which reads as a number that has
        # stopped moving rather than one that is off the end of the page.
        volumes = (
            "0 volume(s) short of room for a rebuild"
            if not headroom["alert"]
            else "1 volume(s) short of room for a rebuild"
            if headroom["status"] == DISK_SHORT
            else "1 volume(s) not measured"
        )
        invalid = ", 1 setting(s) invalid" if bad_budget is not None else ""
        invalid += ", 1 transit schedule to rebuild" if transit_alert is not None else ""
        invalid += f", {len(routers)} router(s) on an old build" if routers else ""
        self.stdout.write(
            f"{len(stale)} stale task(s), {len(wedged)} wedged job(s), "
            f"{failed_total} failed job(s), {volumes}{invalid}"
        )
        sys.exit(EXIT_ALERT)
