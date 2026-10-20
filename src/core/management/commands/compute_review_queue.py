"""`manage.py compute_review_queue` - fill Review's queue (core.stress_review) by hand.

`import_cloud_build`'s dry run does this for a cloud build. This is for everything else: after a
rebuild run on this host (`--staging` before its swap, or the live table alone after it), or after
the owner adds a pending agency's ratings file. Each queue it computes replaces its old rows; the
rulings stay.

After a swap the build is live and the one it replaced is in the retired schema (`<live>_old`):
`--build-id <id> --old-schema <live>_old --new-schema <live>` lists that build's changes then.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core import stress_review


class Command(BaseCommand):
    help = "Compute Review's queue of roads to rule on, from the live table (and staging)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--build-id",
            default="",
            help=(
                "The build the staging schema (or --new-schema) holds; with it the build's "
                "changes are listed."
            ),
        )
        parser.add_argument(
            "--reports-dir",
            default="",
            help=(
                "The build's reports (relative to the rebuild's work directory, or absolute). "
                "Without it, the work directory's own: a rebuild run on this host."
            ),
        )
        parser.add_argument(
            "--old-schema",
            default="",
            help=(
                "The schema holding the map before the build (default: the live schema). After "
                "a swap, the retired one (<live>_old)."
            ),
        )
        parser.add_argument(
            "--new-schema",
            default="",
            help=(
                "The schema holding the build (default: the staging schema). After a swap, the "
                "live one."
            ),
        )

    def handle(self, *args, **options) -> None:
        build = options["build_id"]
        old = options["old_schema"] or settings.SEGMENT_SCHEMA_LIVE
        new = options["new_schema"] or settings.SEGMENT_SCHEMA_STAGING
        if not build and (options["old_schema"] or options["new_schema"]):
            raise CommandError(
                "--old-schema and --new-schema list a build's changes: give --build-id"
            )
        for given in (options["old_schema"], options["new_schema"]):
            if not given:
                continue
            if not stress_review._table_exists(given):
                raise CommandError(f"{given}.segment does not exist: check the schema name")
        if build and old == new:
            raise CommandError("--old-schema and --new-schema are the same schema")
        counts = stress_review.compute_all(
            build,
            old,
            new if build else None,
            stress_review.reports_dir(options["reports_dir"], own=True),
        )
        for queue, count in counts.items():
            self.stdout.write(f"{queue}: {stress_review.NO_REPORT if count is None else count}")
