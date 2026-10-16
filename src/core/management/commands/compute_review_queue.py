"""`manage.py compute_review_queue` - fill Review's queue (core.stress_review) by hand.

`import_cloud_build`'s dry run does this for a cloud build. This is for everything else: after a
rebuild run on this host (`--staging` before its swap, or the live table alone after it), or after
the owner adds a pending agency's ratings file. Each queue it computes replaces its old rows; the
rulings stay.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand

from core import stress_review


class Command(BaseCommand):
    help = "Compute Review's queue of roads to rule on, from the live table (and staging)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--build-id",
            default="",
            help="The build the staging schema holds; with it the rebuild's changes are listed.",
        )
        parser.add_argument(
            "--reports-dir",
            default="",
            help="The rebuild's reports (relative to its work directory, or absolute).",
        )

    def handle(self, *args, **options) -> None:
        build = options["build_id"]
        counts = stress_review.compute_all(
            build,
            settings.SEGMENT_SCHEMA_LIVE,
            settings.SEGMENT_SCHEMA_STAGING if build else None,
            stress_review.reports_dir(options["reports_dir"]),
        )
        for queue, count in counts.items():
            self.stdout.write(f"{queue}: {'no report, left as it was' if count is None else count}")
