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
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from pipeline.promotion import RollbackUnavailable, rollback, rollback_target
from pipeline.variants import Variant

RESTART_HINT = (
    "The routers keep serving the build they started against, so finish the "
    "rollback on the deploy host: docker compose restart valhalla-standard "
    "valhalla-no-trail valhalla-ebike"
)


class Command(BaseCommand):
    help = (
        "Report, or perform, the rollback of the last completed swap: the previous "
        "build's schema, tiles and settings rows, together."
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

        tiles_dir = settings.TILES_DIR
        try:
            # Read before anything is renamed or moved, and read again inside
            # `rollback` for the same reason: this is the check that a previous
            # deployment exists in all three of its parts. `rollback_swap`'s own
            # gate is "a retired schema exists", which is true forever after the
            # first swap and says nothing about what is in it.
            target = rollback_target(tiles_dir)
        except RollbackUnavailable as unavailable:
            raise CommandError(str(unavailable)) from unavailable

        for variant in Variant:
            self.stdout.write(f"{variant.value}: would go back to build {target[variant]}")
        self.stdout.write(f"live segments would come from {settings.SEGMENT_SCHEMA_RETIRED}")

        if not options["confirm"]:
            self.stdout.write("dry run: nothing was changed. Re-run with --confirm to roll back.")
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
