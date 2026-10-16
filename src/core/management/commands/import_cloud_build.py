"""`manage.py import_cloud_build` - swap in a build made on the cloud rebuild box.

The cloud box (docs/OPERATIONS.md, "Rebuilding on the cloud box") runs the ordinary
rebuild against a copy of this deployment's database, swaps it into its own copy,
and sends back two things: the five graphs' dated tile
directories and its new segment schema, renamed to the staging name. Once
`scripts/cloud/import-result.sh` has put the tiles under `TILES_DIR` and restored
that schema here as `staging`, this command does what the rebuild's SWAP stage
does: `pipeline.promotion.perform_swap`, the same function and the same undo, so
`rollback_rebuild` works afterwards exactly as after a rebuild run on this host.
RECONCILE follows it, as in the rebuild.

Dry by default, like `rollback_rebuild`: it checks everything and prints what it
would do. `--confirm` is the whole of the difference. Every check runs on the
dry run as well, and before anything is moved:

- no rebuild queued or running here (a rebuild resets the same staging schema
  and repoints the same rows);
- the build id is one a rebuild writes, every graph has its `tiles.tar` under
  it, and no graph is already serving it;
- a staging schema with a non-empty segment table is waiting;
- this container can write the promotion links (only `rebuild` can);
- `--overrides-read-at` is a real UTC instant in the past. It is when the box's
  copy of the database was taken (the backup's name). Where the swap re-applies
  the road panel's edits (from v0.4.0, the stress editor), the ones made after
  it are re-applied, as a rebuild does for edits made while it ran. Before that
  release nothing re-applies them, so an access override approved after it is
  not in the box's map: the command names them and refuses the swap unless
  `--accept-later-overrides` says they can wait for the next rebuild. A road reopened by a
  ruling in Review (`core.stress_review`) is meant for the next rebuild and is only counted.

The dry run also precomputes Review's queue (`core.stress_review.compute_all`): the roads whose
level or access the build changes, the rating disagreements and the rebuild reports' lists, from
`--review-reports-dir` (the build's reports, as import-result.sh unpacks them). Both runs say how
many changed roads have no ruling yet; that never blocks the swap.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import models

from core import stress_changes
from pipeline import promotion, reconcile, retention, tiles
from pipeline.variants import RESTART_OFFROAD_WHERE_IT_RUNS, RESTART_ROUTERS, Variant

PREDRAW = "docker compose exec -T api python manage.py predraw_stress_tiles"


def parse_read_at(value: str) -> datetime:
    """`2026-10-11T07:00:00Z`, `2026-10-11T07:00:00+00:00`, or the backup's own
    `20261011T070000Z`. A time with no zone is refused rather than guessed: the
    re-applied edits are the ones after it, and a local time read as UTC moves
    that line by hours."""
    text = value.strip()
    try:
        if retention.BUILD_ID.match(text) and "-" not in text:
            parsed = datetime.strptime(text, retention.BUILD_ID_FORMAT).replace(tzinfo=UTC)
        else:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise CommandError(f"--overrides-read-at {value!r} is not a time: {error}") from error
    if parsed.tzinfo is None:
        raise CommandError(
            f"--overrides-read-at {value!r} has no time zone; give it in UTC, "
            "e.g. 2026-10-11T07:00:00Z or the backup's 20261011T070000Z"
        )
    parsed = parsed.astimezone(UTC)
    if parsed > datetime.now(UTC):
        raise CommandError(f"--overrides-read-at {value!r} is in the future")
    return parsed


def staging_segments(staging: str) -> int | None:
    """Rows in `<staging>.segment`, or None when there is no such table."""
    from django.db import connection

    from pipeline.schema import validate_schema_name

    validate_schema_name(staging)
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)", [f"{staging}.segment"])
        if cursor.fetchone()[0] is None:
            return None
        cursor.execute(f"SELECT count(*) FROM {staging}.segment")
        return cursor.fetchone()[0]


def later_overrides(read_at: datetime, *, panel_reapplied: bool = False) -> list[int]:
    """Approved overrides whose approval is newer than the box's copy, but for Review's
    reopenings (`review_reopenings`), which are listed apart and do not hold the swap. Where the
    swap re-applies the road panel's edits, the overrides those edits wrote are left out:
    only they are re-applied, so any other later approval is still missing from the build."""
    from core.models import Override, StressEdit

    later = list(
        Override.objects.filter(approved=True, approved_at__gt=read_at)
        .exclude(kind=Override.Kind.ACCESS, source=Override.Source.REVIEW)
        .order_by("id")
        .values_list("id", flat=True)
    )
    if not panel_reapplied or not later:
        return later
    # A named stretch's edit keeps every way's row in `override_rows`; `override` is
    # only the first way's.
    panel: set[int] = set()
    for first, pairs in StressEdit.objects.filter(
        models.Q(override_id__in=later) | models.Q(at__gt=read_at)
    ).values_list("override_id", "override_rows"):
        if first is not None:
            panel.add(first)
        panel.update(p["override"] for p in pairs or [] if p.get("override") is not None)
    return [pk for pk in later if pk not in panel]


def review_reopenings(read_at: datetime) -> tuple[list[int], list[int]]:
    """Review's reopenings of closed roads (access overrides of source `review`) that this build
    does not reflect: (approved after the box's copy, so not in it yet; undone after the box's
    copy although approved before it, so still open in it). Both are told apart by the row's
    source, never by its words. Neither holds the swap: the ruling was made on this build's
    changes, and the next rebuild reads the row as it then stands."""
    from core.models import Override, ReviewRuling

    reopened = list(
        Override.objects.filter(
            kind=Override.Kind.ACCESS,
            source=Override.Source.REVIEW,
            approved=True,
            approved_at__gt=read_at,
        )
        .order_by("id")
        .values_list("id", flat=True)
    )
    undone = list(
        ReviewRuling.objects.filter(
            access_override__source=Override.Source.REVIEW,
            at__lte=read_at,
            undone_at__gt=read_at,
        )
        .order_by("access_override_id")
        .values_list("access_override_id", flat=True)
    )
    return reopened, undone


class Command(BaseCommand):
    help = (
        "Swap in a build made on the cloud rebuild box: its tiles already under "
        "TILES_DIR and its segment schema restored as the staging schema. Dry unless "
        "--confirm. Refuses while a rebuild is queued or running."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("build_id", help="The box's build id, e.g. 20261011T093012Z.")
        parser.add_argument(
            "--overrides-read-at",
            required=True,
            help=(
                "When the box's copy of the database was taken, in UTC (the backup's "
                "name, e.g. 20261011T070000Z). Road panel edits made after it are "
                "re-applied to the new table."
            ),
        )
        parser.add_argument(
            "--accept-later-overrides",
            action="store_true",
            help=(
                "Swap even though access overrides were approved after the box's copy was "
                "taken and nothing re-applies them; they wait for the next rebuild."
            ),
        )
        parser.add_argument(
            "--review-reports-dir",
            default="",
            help=(
                "The build's rebuild reports, for Review's queues: a directory, relative to "
                "the rebuild's work directory or absolute. Without it the queues read from "
                "reports say the build had none (never this computer's own reports)."
            ),
        )
        parser.add_argument(
            "--confirm",
            action="store_true",
            help=(
                "Actually swap. Without it this checks and prints, and changes nothing served "
                "(it fills Review's queue)."
            ),
        )

    def review_queue(self, build_id: str, live: str, staging: str, reports: str) -> None:
        """Precompute Review's queue against the build waiting in staging. A failure is said and
        the dry run goes on: the review is a help to the swap, never a condition of it."""
        from core import stress_review

        try:
            counts = stress_review.compute_all(
                build_id, live, staging, stress_review.reports_dir(reports, own=False)
            )
        except Exception as error:  # noqa: BLE001 - said, and the dry run goes on
            self.stderr.write(f"Review's queue was not computed: {error}")
            return
        wired = [f"{n} {q.replace('_', ' ')}" for q, n in counts.items() if n is not None]
        missing = [q.replace("_", " ") for q, n in counts.items() if n is None]
        # Roads, not the stress change report's segments: a way counts once, at its highest
        # piece's level with half steps, and a change of bicycle access counts as well.
        self.stdout.write(
            "review queue, in roads (whole ways; the stress changes above count segments): "
            + ", ".join(wired)
            + (f"; {stress_review.NO_REPORT.lower()} for: {', '.join(missing)}" if missing else "")
        )

    def review_status(self) -> None:
        from core import stress_review

        try:
            unruled, total, build = stress_review.unruled_rebuild_changes()
        except Exception as error:  # noqa: BLE001 - a note, never a condition of the swap
            self.stderr.write(f"Review's status could not be read: {error}")
            return
        if total:
            self.stdout.write(
                f"review: {unruled} of {total} changed roads in build {build} have no ruling yet "
                "(Review mode, Rebuild changes); this does not block the swap"
            )

    def handle(self, *args, **options) -> None:
        from core.audit import record
        from core.models import AuditLogEntry
        from core.runs import jobs_in_flight

        build_id = options["build_id"]
        in_flight = jobs_in_flight("weekly_rebuild")
        if in_flight:
            job = in_flight[0]
            raise CommandError(
                f"a rebuild is in flight - job {job.id} is {job.status} on the "
                f"{job.queue_name} queue - so nothing was imported. A rebuild resets the "
                "staging schema this import swaps in and repoints the same settings rows. "
                "Let it finish, or stop it first, then run this again."
            )

        if not retention.BUILD_ID.match(build_id):
            raise CommandError(
                f"{build_id!r} is not a build id a rebuild writes (e.g. 20261011T093012Z)"
            )
        read_at = parse_read_at(options["overrides_read_at"])

        tiles_dir = settings.TILES_DIR
        problems = []
        for variant in Variant:
            if not (tiles_dir / variant.value / build_id / "tiles.tar").is_file():
                problems.append(f"{variant.value} has no {variant.value}/{build_id}/tiles.tar")
            elif tiles.promoted_build_id(tiles_dir, variant) == build_id:
                problems.append(f"{variant.value} is already serving {build_id}")
        staging = settings.SEGMENT_SCHEMA_STAGING
        segments = staging_segments(staging)
        if segments is None:
            problems.append(f"there is no {staging}.segment table to swap in")
        elif segments == 0:
            problems.append(f"{staging}.segment is empty")
        if problems:
            raise CommandError(
                "nothing was imported: " + "; ".join(problems) + ". "
                "scripts/cloud/import-result.sh installs the tiles and restores the schema "
                "before it runs this."
            )
        unwritable = tiles.unwritable_link_dirs(tiles_dir)
        if unwritable:
            raise CommandError(
                "nothing was imported: this container cannot write the promotion links under "
                f"{tiles_dir} - " + "; ".join(unwritable) + ". Run it where the tiles are "
                "mounted read-write: docker compose exec -T rebuild ./manage.py "
                "import_cloud_build"
            )

        live = settings.SEGMENT_SCHEMA_LIVE
        live_segments = staging_segments(live)
        for variant in Variant:
            serving = tiles.promoted_build_id(tiles_dir, variant) or "nothing"
            self.stdout.write(f"{variant.value}: {serving} -> {build_id}")
        self.stdout.write(
            f"segments: {live} has {live_segments if live_segments is not None else 'no table'}"
            f", {staging} has {segments}; {live} becomes {settings.SEGMENT_SCHEMA_RETIRED}"
        )
        if live_segments:
            # The owner's review before promotion (2026-10-16): what changed, by county.
            try:
                for line in stress_changes.report(live, staging, settings.REBUILD_REFERENCE_DIR):
                    self.stdout.write(line)
            except Exception as error:  # noqa: BLE001 - a report, never a reason to refuse
                self.stderr.write(f"the stress change report was not made: {error}")
        reapplies = "overrides_read_at" in inspect.signature(promotion.perform_swap).parameters
        if reapplies:
            self.stdout.write(
                f"road panel edits made after {read_at:%Y-%m-%d %H:%M:%S} UTC are re-applied"
            )
        later = later_overrides(read_at, panel_reapplied=reapplies)
        if later:
            self.stdout.write(
                f"{len(later)} access override(s) approved after "
                f"{read_at:%Y-%m-%d %H:%M:%S} UTC are not in this build (ids "
                + ", ".join(map(str, later))
                + "); they take effect at the next rebuild"
            )

        reopened, undone = review_reopenings(read_at)
        if reopened:
            self.stdout.write(
                f"{len(reopened)} Review reopening(s) approved after "
                f"{read_at:%Y-%m-%d %H:%M:%S} UTC are not in this build (access override ids "
                + ", ".join(map(str, reopened))
                + "); they take effect at the next rebuild and do not hold the swap"
            )
        if undone:
            self.stdout.write(
                f"warning: {len(undone)} Review reopening(s) undone after "
                f"{read_at:%Y-%m-%d %H:%M:%S} UTC are still open to bicycles in this build "
                "(access override ids "
                + ", ".join(map(str, undone))
                + "); they close again at the next rebuild"
            )

        if later and not options["accept_later_overrides"]:
            message = (
                "access overrides approved after the box's copy was taken would not be in the "
                "new map until the next rebuild. Run a fresh cloud rebuild, or pass "
                "--accept-later-overrides to swap anyway."
            )
            if options["confirm"]:
                raise CommandError("nothing was imported: " + message)
            self.stdout.write("note: --confirm alone will refuse: " + message)

        if not options["confirm"]:
            self.review_queue(build_id, live, staging, options["review_reports_dir"])
        self.review_status()

        if not options["confirm"]:
            self.stdout.write("dry run: nothing was changed. Re-run with --confirm to swap.")
            return

        # The road panel's re-apply arrived with the stress editor (v0.4.0); on a
        # release before it, `perform_swap` has no such parameter and there are no
        # panel edits to re-apply.
        extra = {"overrides_read_at": read_at} if reapplies else {}
        try:
            outcome = promotion.perform_swap(
                tiles_dir, build_id, settings.VALHALLA_UPSTREAMS, **extra
            )
        except promotion.SwapUndoIncomplete as error:
            raise CommandError(
                f"the swap failed and its undo did not finish: {error}. The deployment is "
                'half on each build; see OPERATIONS.md, "A SwapUndoIncomplete alert".'
            ) from error
        except Exception as error:
            raise CommandError(
                f"the swap failed and was undone, so the deployment is still on the build it "
                f"was serving: {error}. The {staging} schema and the tiles are still there "
                "for another try."
            ) from error

        record(
            None,
            "import_cloud_build",
            "valhallaupstream",
            "",
            AuditLogEntry.Outcome.ALLOWED,
            detail=(
                f"swapped in cloud build {build_id}; overrides read at {read_at.isoformat()}; "
                f"edits re-applied: {getattr(outcome, 'edits_reapplied', None)}"
            ),
        )
        try:
            reconcile.drift_report(build_id, live, settings.SEGMENT_SCHEMA_RETIRED)
        except Exception as error:  # noqa: BLE001 - the swap stands; the report is a record
            self.stderr.write(f"the drift report was not written: {error}")
        self.stdout.write(f"swapped: every graph is now {build_id}; {live} is the new table")
        self.stdout.write(
            "The routers keep serving the build they started against, so finish on the "
            f"deploy host: {RESTART_ROUTERS}; {RESTART_OFFROAD_WHERE_IT_RUNS}. "
            f"Then draw the stress tiles again: {PREDRAW}"
        )
