"""`manage.py sync_upstreams` - the settings rows, written from the tile links.

The beta installs a map by moving each variant's `current` and `previous` links
(`scripts/beta/receive-data.sh files`) and never runs a swap, so nothing there
wrote `valhalla_upstream`: its rows were the four its first database load from
home carried, with none for `offroad` or `mtb`. The API serves a twin variant
only once its row exists (`core.routing._promoted_row`), so Mountain Bike,
Gravel and Mountain Goat were planned on the standard graph with both trail
routers up (2026-10-28). This writes every row from the links, in one
transaction (`pipeline.promotion.sync_upstreams`), and is safe to run again.

It only reads `TILES_DIR`, so it runs in the api container, which binds the
tiles read-only. It refuses, writing nothing, when the standard graph has no `current`
link (an unmounted tiles folder would otherwise delete every row).
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.models import ValhallaUpstream
from pipeline.promotion import sync_upstreams
from pipeline.variants import Variant


class Command(BaseCommand):
    help = "Write each variant's valhalla_upstream row from its tile links (current, previous)."

    def handle(self, *args, **options) -> None:
        try:
            before = sync_upstreams(settings.TILES_DIR, settings.VALHALLA_UPSTREAMS)
        except FileNotFoundError as error:
            raise CommandError(f"nothing written: {error}") from error
        rows = {row.variant: row for row in ValhallaUpstream.objects.all()}
        for variant in Variant:
            row = rows.get(variant.value)
            now = _says(row.build_id, row.previous_build_id) if row else "no row"
            was = before[variant.value]
            then = _says(was.build_id, was.previous_build_id) if was.existed else "no row"
            self.stdout.write(f"{variant.value}: {now}" + ("" if now == then else f", was {then}"))


def _says(build_id: str, previous_build_id: str) -> str:
    return f"{build_id or 'no build'} (previous {previous_build_id or 'none'})"
