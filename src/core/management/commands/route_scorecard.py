"""The route scorecard on this deployment (docs/SCORECARD.md, core.scorecard_nightly).

manage.py route_scorecard --now               run tonight's scorecard now (one at a time)
manage.py route_scorecard --report            the newest run, Markdown, against the one before
manage.py route_scorecard --latest-findings   for scripts/beta/alert.sh: the newest run's id
                                              on the first line and what moved after it, only
                                              when that run is under a day old and something
                                              moved; nothing at all otherwise
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

# One Discord post holds at most 2000 characters; the alert script adds its own words.
MAX_LINES = 12
MAX_CHARS = 1500
FRESH = timedelta(hours=20)


class Command(BaseCommand):
    help = "Run or read the route scorecard (docs/SCORECARD.md)."

    def add_arguments(self, parser) -> None:
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--now", action="store_true")
        group.add_argument("--report", action="store_true")
        group.add_argument("--latest-findings", action="store_true")

    def handle(self, *args, **options) -> None:
        from core.models import ScorecardRun

        if options["now"]:
            from core.scorecard_nightly import run_nightly

            self.stdout.write(run_nightly())
            return
        runs = list(ScorecardRun.objects.order_by("-made_at")[:2])
        if options["report"]:
            if not runs:
                self.stdout.write("No scorecard run yet.")
                return
            from routemaker import scorecard

            older = runs[1].data if len(runs) > 1 else None
            self.stdout.write(scorecard.report(runs[0].data, older))
            return
        if not runs or not runs[0].findings:
            return
        newest = runs[0]
        if timezone.now() - newest.made_at > FRESH:
            return
        lines = newest.findings.splitlines()
        shown = []
        for line in lines[:MAX_LINES]:
            if sum(len(s) + 1 for s in shown) + len(line) > MAX_CHARS:
                break
            shown.append(line)
        more = len(lines) - len(shown)
        tail = [f"...and {more} more"] if more else []
        self.stdout.write(str(newest.pk))
        self.stdout.write(
            "\n".join(
                [
                    f"route scorecard {newest.made_at:%Y-%m-%d}: "
                    f"{newest.findings_count} trips moved",
                    *shown,
                    *tail,
                    "Full table: manage.py route_scorecard --report",
                ]
            )
        )
