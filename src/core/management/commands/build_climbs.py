"""Write the Climbs map layer's file from the live table and the elevation tiles.

Run on the build host in the rebuild container after a rebuild has promoted (it reads the
live segment table and `<DATA_ROOT>/elevation`, both of which that container has):

    docker compose run --rm rebuild ./manage.py build_climbs

It writes `<DATA_ROOT>/rebuild/climbs.json` (`/data/rebuild/climbs.json` inside the
container) and prints the count per category; copy the file to
frontend/src/climb-data/climbs.json and commit it. It reads only, and is safe to re-run. See
docs/OPERATIONS.md, "The Climbs layer", and `pipeline.climb_layer` for what counts.
"""

from __future__ import annotations

import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from pipeline import climb_layer


class Command(BaseCommand):
    help = "Write the Climbs map layer's file (every categorised climb) from the live table."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--out",
            type=Path,
            default=Path(settings.DATA_ROOT) / "rebuild" / "climbs.json",
            help="Where to write the file (default <DATA_ROOT>/rebuild/climbs.json).",
        )
        parser.add_argument(
            "--elevation-dir",
            type=Path,
            default=Path(settings.ELEVATION_DIR),
            help="The HGT tiles in skadi's layout (default <DATA_ROOT>/elevation).",
        )
        parser.add_argument(
            "--schema",
            default=settings.SEGMENT_SCHEMA_LIVE,
            help="The segment schema to read (default the live one).",
        )

    def handle(self, *args, out: Path, elevation_dir: Path, schema: str, **options) -> None:
        started = time.monotonic()
        segments = climb_layer.read_segments(schema)
        self.stdout.write(f"climbs: read {len(segments):,} segments from {schema}.segment")
        found = climb_layer.find_all(segments, climb_layer.HgtElevation(elevation_dir))
        doc = climb_layer.document(found)
        climb_layer.write(out, doc)
        counts = ", ".join(f"{name} {n:,}" for name, n in doc["counts"].items())
        self.stdout.write(
            f"climbs: {len(doc['climbs']):,} written to {out} ({counts}), "
            f"in {time.monotonic() - started:.0f} s"
        )
