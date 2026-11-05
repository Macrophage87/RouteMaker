"""Write the public data download from the live map (`core.open_data_export`).

Read-only: it reads the live segment table and the bike-parking file, and Arlington's Bike
Comfort Index from the county's service for the comparison (miles only; `--no-arlington`
skips it), and writes files under `--out`, nothing else. Run after a map swap, then upload
the zips to a GitHub data release once the owner has looked at them. See docs/OPERATIONS.md,
"The open data download".
"""

from __future__ import annotations

import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from core import open_data_export
from routemaker.open_data_files import built_stamp


class Command(BaseCommand):
    help = "Write the open data download (GeoPackage, CSV, GeoJSON) from the live map."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--out",
            type=Path,
            default=Path(settings.DATA_ROOT) / "exports",
            help="The folder to write into (default DATA_ROOT/exports).",
        )
        parser.add_argument(
            "--racks",
            type=Path,
            default=Path(settings.BASE_DIR) / "frontend/src/amenity-data/bike-parking.json",
            help="The bike-parking file (frontend/src/amenity-data/bike-parking.json).",
        )
        parser.add_argument(
            "--no-arlington",
            action="store_true",
            help="Skip reading Arlington's Bike Comfort Index for the comparison.",
        )
        parser.add_argument(
            "--date", default=None, help="The date the files are named for (default today, UTC)."
        )

    def handle(
        self, *args, out: Path, racks: Path, date: str | None, no_arlington: bool, **options
    ) -> None:
        started = time.monotonic()
        arlington = None
        if not no_arlington:
            try:
                arlington = open_data_export.fetch_arlington()
                self.stdout.write(f"Arlington comfort lines: {len(arlington):,}")
            except OSError as error:  # the county's service is down: the rest still exports
                self.stderr.write(f"Arlington's comfort index not read ({error}); left out")
        result = open_data_export.export(out, date or built_stamp(), racks, arlington=arlington)
        self.stdout.write(f"open data: {result.summary()}, in {time.monotonic() - started:.0f} s")
