"""`manage.py rollback_rebuild` - the operator's undo for a completed swap.

`pipeline.promotion.rollback` has existed since the swap did and had no caller
at all: the one procedure the plan names for a bad promotion - put last week's
graph, tiles and settings rows back - could only be run by opening a shell,
importing the module and knowing to pass it the tiles directory. That is the
worst possible interface for the thing an operator reaches for at three in the
morning, and it is why this command is one flag wide.

Dry by default, because a rollback is destructive in the direction nobody
wants twice: it retires the graph being served. Run with no arguments it prints
`rollback_target`'s verdict - the build each variant would go back to, or the
refusal naming every part of a previous deployment that is missing - and
changes nothing. `--confirm` is the whole of the difference.

It refuses outright while a rebuild is in flight, which `run_rebuild_now` did
and this did not. `rollback_swap` drops any staging schema `CASCADE` - the
comment on it says "left behind by a rebuild that did not swap" - so running
this against a rebuild that is halfway through deletes the rows that rebuild is
still writing into. What follows is not a clean refusal: the build fails later
as a plain `RebuildFailed`, is retried five times, and each retry writes into a
schema this command may drop again. The worse interleaving is narrower and
quieter - a rollback landing between `perform_swap`'s repoint of the upstream
rows and the schema rename leaves the tiles naming one build and the schema
another, with nothing raising anywhere. So the pre-flight is first, before
`rollback_target` and on the dry run as well: an operator reading "would go
back to build X" while a rebuild runs is being told about a plan that is not
safe to carry out.

The second pre-flight is the container. The rollback rewrites the promotion
links under `TILES_DIR`, which `rebuild` binds read-write and `api` and
`worker` bind read-only, so anywhere but `rebuild` it refuses - dry run
included - on a real write probe, before anything is renamed or moved.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from pipeline.promotion import (
    RollbackUnavailable,
    refuse_unwritable_tiles,
    rollback,
    rollback_target,
)
from pipeline.variants import Variant

RESTART_HINT = (
    "The routers keep serving the build they started against, so finish the "
    "rollback on the deploy host: docker compose restart valhalla-standard "
    "valhalla-no-trail valhalla-ebike"
)


class Command(BaseCommand):
    help = (
        "Report, or perform, the rollback of the last completed swap: the previous "
        "build's schema, tiles and settings rows, together. Refuses while a rebuild is "
        "queued or running, on the dry run as well."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--confirm",
            action="store_true",
            help=(
                "Actually roll back. Without it this prints what would happen and touches nothing."
            ),
        )

    def handle(self, *args, **options) -> None:
        # Imported inside the handler, like the pipeline imports above are used:
        # this reaches the ORM, and a management command that touched models at
        # import time would do it during `manage.py help` as well.
        from core.audit import record
        from core.models import AuditLogEntry
        from core.runs import jobs_in_flight

        # Before `rollback_target`, and before anything is printed. A rollback
        # drops the staging schema a running rebuild is writing into, and it
        # repoints the upstream rows the swap is about to repoint itself; the
        # dry run is refused too because its whole output is advice about an
        # action that must not be taken while this is true.
        in_flight = jobs_in_flight("weekly_rebuild")
        if in_flight:
            job = in_flight[0]
            raise CommandError(
                f"a rebuild is in flight - job {job.id} is {job.status} on the "
                f"{job.queue_name} queue - so nothing was rolled back. A rollback drops the "
                "staging schema a running rebuild is writing into and repoints the upstream "
                "rows it is about to repoint itself, and neither one raises: the rebuild "
                "fails later, or succeeds having written a build the settings rows do not "
                "name. Let it finish, or stop it first - `docker compose logs -f rebuild` "
                "shows a running one, the operations page and `manage.py check_operations` "
                "show a queued or wedged one - then run this again."
            )

        tiles_dir = settings.TILES_DIR
        try:
            # Read before anything is renamed or moved, and read again inside
            # `rollback` for the same reason: this is the check that a previous
            # deployment exists in all three of its parts. `rollback_swap`'s own
            # gate is "a retired schema exists", which is true forever after the
            # first swap and says nothing about what is in it.
            target = rollback_target(tiles_dir)
            # A write probe of every variant's tile directory, and on the dry
            # run as well. `api` and `worker` bind the tiles read-only, and in
            # either the dry run used to report "would go back to build X" for
            # a rollback whose first `demote` was going to fail - after, until
            # round 10, the schemas had already been renamed. After
            # `rollback_target`, so a deployment with nothing to go back to
            # says that first: it is true in every container.
            refuse_unwritable_tiles(tiles_dir)
        except RollbackUnavailable as unavailable:
            raise CommandError(str(unavailable)) from unavailable

        for variant in Variant:
            self.stdout.write(f"{variant.value}: would go back to build {target[variant]}")
        self.stdout.write(f"live segments would come from {settings.SEGMENT_SCHEMA_RETIRED}")

        if not options["confirm"]:
            self.stdout.write("dry run: nothing was changed. Re-run with --confirm to roll back.")
            # The restart is half the procedure, and the dry run is where an
            # operator reads what the procedure is. Printing it only on the
            # confirmed path meant the rehearsal did not mention the step that
            # makes the rollback take effect - and the routers keep serving the
            # build they started against until they are restarted.
            self.stdout.write(RESTART_HINT)
            return

        rollback(tiles_dir)
        # The audit log's account of the most destructive thing an operator can
        # do to this deployment from a shell: it repoints every ValhallaUpstream
        # row and retires the graph being served. Nothing under src/pipeline or
        # in these commands wrote an audit row before, so a rollback left the
        # settings rows changed and no record of who changed them or when - the
        # one question asked afterwards.
        #
        # The actor is None because there is honestly no actor: this runs in a
        # container with no request and no session, and the log's own convention
        # is that a null actor with a null numeric id means the worker or the
        # host operator rather than an account that was since deleted.
        #
        # On the confirmed path only. A dry run changes nothing, and an audit
        # log that records reads is one nobody reads.
        record(
            None,
            "rollback_rebuild",
            "valhallaupstream",
            "",
            AuditLogEntry.Outcome.ALLOWED,
            detail=(
                "rolled back to "
                + ", ".join(f"{variant.value}={target[variant]}" for variant in Variant)
                + f"; live segments restored from {settings.SEGMENT_SCHEMA_RETIRED}"
            ),
        )
        for variant in Variant:
            self.stdout.write(f"{variant.value}: serving build {target[variant]}")
        self.stdout.write(RESTART_HINT)
