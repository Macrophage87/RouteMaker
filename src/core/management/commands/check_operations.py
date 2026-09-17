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

from core.runs import failed_jobs, stale_task_details

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
            help="How many failed jobs to list (all of them are still counted).",
        )

    def handle(self, *args, **options) -> None:
        stale = stale_task_details()
        jobs = failed_jobs(options["failed_job_limit"])

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
        if not stale and not jobs:
            self.stdout.write("ok: no stale tasks, no failed jobs")
            sys.exit(EXIT_OK)
        self.stdout.write(f"{len(stale)} stale task(s), {len(jobs)} failed job(s)")
        sys.exit(EXIT_ALERT)
