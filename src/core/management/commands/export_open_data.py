"""Write the public data download from the live map (`core.open_data_export`).

Read-only: it reads the live segment table and the bike-parking file and writes files under
`--out`, nothing else. Run after a map swap, then upload the zips to a GitHub data release
once the owner has looked at them. See docs/OPERATIONS.md, "The open data download".
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
            "--date", default=None, help="The date the files are named for (default today, UTC)."
        )

    def handle(self, *args, out: Path, racks: Path, date: str | None, **options) -> None:
        started = time.monotonic()
        result = open_data_export.export(out, date or built_stamp(), racks)
        self.stdout.write(f"open data: {result.summary()}, in {time.monotonic() - started:.0f} s")
