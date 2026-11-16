"""Write the Intervals map layer's file from the live table, the extract and the elevation tiles.

Run on the build host in the running rebuild container after a rebuild has promoted, as
`build_climbs` is, under the heavy-job lock with at least 3,000 MB free:

    flock <heavy.lock> docker compose exec -T rebuild ./manage.py build_intervals </dev/null

It writes `<DATA_ROOT>/rebuild/intervals.json` and prints the counts; copy the file to
frontend/src/interval-data/intervals.json and commit it. It reads only, and is safe to re-run.
See docs/OPERATIONS.md, "The Intervals layer", and `pipeline.interval_layer` for what counts.
"""

from __future__ import annotations

import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from pipeline import climb_layer, climb_names, interval_layer


class Command(BaseCommand):
    help = "Write the Intervals map layer's file (stretches an effort can run unbroken)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--out",
            type=Path,
            default=Path(settings.DATA_ROOT) / "rebuild" / "intervals.json",
            help="Where to write the file (default <DATA_ROOT>/rebuild/intervals.json).",
        )
        parser.add_argument(
            "--elevation-dir",
            type=Path,
            default=Path(settings.ELEVATION_DIR),
            help="The HGT tiles in skadi's layout (default <DATA_ROOT>/elevation).",
        )
        parser.add_argument(
            "--pbf",
            type=Path,
            default=Path(settings.REBUILD_SOURCE_PBF),
            help="The OSM extract the stops and names are read from (default the rebuild's own).",
        )
        parser.add_argument(
            "--schema",
            default=settings.SEGMENT_SCHEMA_LIVE,
            help="The segment schema to read (default the live one).",
        )

    def handle(
        self, *args, out: Path, elevation_dir: Path, pbf: Path, schema: str, **options
    ) -> None:
        started = time.monotonic()
        if not pbf.is_file():
            # Without it no signal or stop sign is known, and every stretch would run through them.
            raise CommandError(f"no extract at {pbf} to read the stops from: nothing written")
        segments = climb_layer.read_segments(schema)
        self.stdout.write(f"intervals: read {len(segments):,} segments from {schema}.segment")
        if not segments:
            raise CommandError(f"no routable segments in {schema}.segment: nothing written")
        ways = {s.key[0] for s in segments}
        gazetteer = climb_names.read_extract(pbf, ways)
        facts = interval_layer.read_extract(pbf, ways)
        self.stdout.write(
            f"intervals: from {pbf}: {len(facts.stops):,} stops, {len(facts.minor):,} minor ways, "
            f"{len(facts.roundabouts):,} roundabout ways"
        )
        segments = climb_layer.with_names(segments, gazetteer.ways)
        segments = climb_layer.with_structures(segments, gazetteer.structures)
        ground = climb_layer.HgtElevation(elevation_dir)
        found = interval_layer.find_all(segments, ground, facts)
        if ground.tiles_read == 0:
            raise CommandError(
                f"no elevation tiles read under {elevation_dir} (expected e.g. N38/N38W077.hgt): "
                "nothing written"
            )
        if ground.tiles_missing:
            self.stderr.write(
                "intervals: no ground in "
                + ", ".join(ground.tiles_missing)
                + "; the stretches there are left out"
            )
        doc = interval_layer.document(found)
        interval_layer.write(out, doc)
        counts = ", ".join(f"{name} {n:,}" for name, n in doc["counts"].items())
        self.stdout.write(
            f"intervals: {len(doc['intervals']):,} written to {out} ({counts}), "
            f"in {time.monotonic() - started:.0f} s"
        )
