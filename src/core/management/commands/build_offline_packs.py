"""`manage.py build_offline_packs` - build the region packs for off-grid riding from the live map.

A rebuild run on this host builds them after its swap, and `import_cloud_build` does since
2026-11-15. This is for a map that went live without them (a cloud build imported before
then): it builds the packs of the build the standard graph serves, from the live
`offline_way` table, into `TILES_DIR/offline-packs/`, and then the manifest that names them.
It writes only there; a build whose packs are already written is not written again.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.offline_packs import packs_dir
from pipeline import offline_packs, tiles
from pipeline.variants import Variant


class Command(BaseCommand):
    help = "Build the offline region packs from the live map (the build the standard graph serves)."

    def handle(self, *args, **options) -> None:
        build_id = tiles.promoted_build_id(settings.TILES_DIR, Variant.STANDARD)
        if not build_id:
            raise CommandError(f"no build is served from {settings.TILES_DIR}; nothing to pack")
        found = offline_packs.build_packs(
            settings.SEGMENT_SCHEMA_LIVE, packs_dir(), build_id, settings.COVERAGE_BBOX
        )
        for pack in found["packs"]:
            self.stdout.write(f"{pack['id']}: {pack['ways']} ways, {pack['bytes']} bytes")
        self.stdout.write(f"built: {found['dir']} for build {build_id}")
