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
"""

from __future__ import annotations

import sys

from django.core.management.base import BaseCommand

from core.runs import (
    disk_headroom,
    failed_job_count,
    failed_jobs,
    stale_task_details,
    wedged_jobs,
)

# Deliberately the shell convention rather than a richer set: monitoring tools
# read "zero or not zero", and a scheme with more codes in it invites a check
# that treats one kind of breakage as success.
EXIT_OK = 0
EXIT_ALERT = 1


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
        wedged = wedged_jobs()
        jobs = failed_jobs(options["failed_job_limit"])
        failed_total = failed_job_count()
        # The fourth check. The disk gate is a hard refusal with "grow the
        # volume" as its only remedy, and nothing reported the volume before
        # that refusal arrived - so the first an operator heard of it was a
        # rebuild that did not run, a week after it could have been fixed.
        headroom = disk_headroom()

        for entry in stale:
            last = entry["last_success_at"] or "never"
            self.stdout.write(
                f"stale: {entry['task']} has no success inside {entry['window_s']}s "
                f"(last success: {last})"
            )
        # The row that did not exist. A worker killed mid-job leaves its job
        # `doing` forever - the process that would have written `failed` is
        # gone - so a rebuild killed at hour three was on no surface at all
        # until `weekly_rebuild` went stale eight days later, while the job
        # holding the rebuild queue's only slot was never going to move.
        for entry in wedged:
            self.stdout.write(
                f"wedged job: {entry['id']} {entry['task']} on {entry['queue']} has been "
                f"running for {entry['age_s']:.0f}s, past its {entry['budget_s']:.0f}s budget "
                f"(started: {entry['started_at']}) - {entry['remedy']}"
            )
        for job in jobs:
            self.stdout.write(
                f"failed job: {job.id} {job.task_name} on {job.queue_name} "
                f"after {job.attempts} attempts (last event: {job.last_event_at or 'unknown'})"
            )
        if headroom is not None:
            self.stdout.write(
                f"disk: {headroom['path']} has "
                f"{headroom['free_bytes'] / 1024**3:.1f} GiB free of "
                f"{headroom['total_bytes'] / 1024**3:.1f} GiB; a rebuild reserving the "
                f"{headroom['minimum_free_bytes'] / 1024**3:.1f} GiB floor would leave it "
                f"{headroom['fraction_after']:.0%} full, against the "
                f"{headroom['fraction']:.0%} disk gate. Grow the volume before the next "
                "rebuild refuses to start."
            )
        if len(jobs) < failed_total:
            self.stdout.write(
                f"(listing the {len(jobs)} newest of {failed_total} failed jobs; "
                "--failed-job-limit lists more)"
            )
        if not stale and not wedged and not failed_total and headroom is None:
            self.stdout.write(
                "ok: no stale tasks, no wedged jobs, no failed jobs, room for a rebuild"
            )
            sys.exit(EXIT_OK)
        # The total rather than the length of the list above it. Reporting the
        # length reported the limit: 400 failed jobs and a limit of 25 printed
        # "25 failed job(s)" every run, which reads as a number that has
        # stopped moving rather than one that is off the end of the page.
        self.stdout.write(
            f"{len(stale)} stale task(s), {len(wedged)} wedged job(s), "
            f"{failed_total} failed job(s), "
            f"{0 if headroom is None else 1} volume(s) short of room for a rebuild"
        )
        sys.exit(EXIT_ALERT)
