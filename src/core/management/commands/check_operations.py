"""`manage.py check_operations` - the alert, for something outside Django.

The admin page answers the same question for a person who is already logged in.
This answers it for a cron entry, an uptime check or a container health probe:
it prints what is wrong and exits non-zero if anything is, which is the whole
interface such a thing needs. Without it the plan's alert list - backup not
succeeded in 26 hours, rebuild not completed in 8 days, worker heartbeat silent
for 10 minutes - has no way to reach anyone who is not looking at the admin.

It is read-only and it opens one database connection, so it is safe to run from
a health check every minute.
"""

from __future__ import annotations

import sys

from django.core.management.base import BaseCommand

from core.runs import failed_job_count, failed_jobs, stale_task_details

# Deliberately the shell convention rather than a richer set: monitoring tools
# read "zero or not zero", and a scheme with more codes in it invites a check
# that treats one kind of breakage as success.
EXIT_OK = 0
EXIT_ALERT = 1


class Command(BaseCommand):
    help = "Report stale scheduled tasks and failed jobs; exit non-zero if any exist."

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
        jobs = failed_jobs(options["failed_job_limit"])
        failed_total = failed_job_count()

        for entry in stale:
            last = entry["last_success_at"] or "never"
            self.stdout.write(
                f"stale: {entry['task']} has no success inside {entry['window_s']}s "
                f"(last success: {last})"
            )
        for job in jobs:
            self.stdout.write(
                f"failed job: {job.id} {job.task_name} on {job.queue_name} "
                f"after {job.attempts} attempts (last event: {job.last_event_at or 'unknown'})"
            )
        if len(jobs) < failed_total:
            self.stdout.write(
                f"(listing the {len(jobs)} newest of {failed_total} failed jobs; "
                "--failed-job-limit lists more)"
            )
        if not stale and not failed_total:
            self.stdout.write("ok: no stale tasks, no failed jobs")
            sys.exit(EXIT_OK)
        # The total rather than the length of the list above it. Reporting the
        # length reported the limit: 400 failed jobs and a limit of 25 printed
        # "25 failed job(s)" every run, which reads as a number that has
        # stopped moving rather than one that is off the end of the page.
        self.stdout.write(f"{len(stale)} stale task(s), {failed_total} failed job(s)")
        sys.exit(EXIT_ALERT)
