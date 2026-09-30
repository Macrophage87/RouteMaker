"""Draw the z10-14 stress tiles of the live table into the tile cache: every
tile the map asks for.

The weekly rebuild does this after every promotion (config.procrastinate); run
it by hand on a deployment whose live table was promoted before the cache
existed, and after `rollback_rebuild`, which puts back a table whose tiles the
last pre-draw cleared. It is safe to run at any time and to re-run: tiles
already cached are skipped. See docs/OPERATIONS.md, "The stress tiles".
"""

from __future__ import annotations

import time

from django.core.management.base import BaseCommand

from core import tile_cache


class Command(BaseCommand):
    help = "Draw the z10-14 stress tiles of the live table into the tile cache."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--budget-s",
            type=float,
            default=tile_cache.PREDRAW_BUDGET_S,
            help="Stop after this many seconds; what is left is drawn on first request.",
        )

    def handle(self, *args, budget_s: float, **options) -> None:
        started = time.monotonic()
        result = tile_cache.predraw(budget_s=budget_s)
        self.stdout.write(
            f"stress tiles: {result.summary()}, in {time.monotonic() - started:.0f} s"
        )
