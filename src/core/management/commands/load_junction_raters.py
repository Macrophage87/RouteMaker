"""`manage.py load_junction_raters` - load the junction run's ratings (`JunctionRater`).

The 2026-11-19 junction run rated every junction a bike rides through, per movement, a stress
level and the seconds lost there (reports/bike-infra-guide/junctions-run-FINAL.md). Two files
from its folder:

- `junctions-stress-delay.csv.gz`: one row per junction and movement (`junction`, `movement`,
  `stress`, `delay_s`, `control_tagged`, `oneway_flag`, ...). `stress` and `delay_s` are the
  final values; blank where the movement cannot be made.
- `key.jsonl`: one line per junction with its `lon` and `lat`.

A movement the one-way check flags (`oneway_flag`) is dropped: the router knows which moves
are legal, and a rating for one that cannot be made would be read for a move that can. The
load replaces every row, from the next plan, with no rebuild. Dry unless `--confirm`: it says
how many junctions and movements it would load and what it dropped.

    python manage.py load_junction_raters <csv.gz> <key.jsonl>
    # read what it would do, then the same with --confirm
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import math
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

MOVES = ("cross", "left", "along")
BATCH = 5000


def _number(text: str | None) -> float | None:
    if text is None or not text.strip():
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def read_ratings(lines, counts: Counter) -> dict[str, dict]:
    """By junction id, its control and each movement's (stress, delay_s)."""
    found: dict[str, dict] = {}
    reader = csv.DictReader(lines)
    missing = {"junction", "movement", "stress", "delay_s"} - set(reader.fieldnames or ())
    if missing:
        raise CommandError(f"the ratings file has no {sorted(missing)} column")
    for row in reader:
        move = row["movement"]
        if move not in MOVES:
            counts["unknown movement"] += 1
            continue
        stress = _number(row["stress"])
        if stress is None:
            counts["cannot be made"] += 1
            continue
        if (row.get("oneway_flag") or "").strip():
            counts["one-way flag"] += 1
            continue
        if not 1.0 <= stress <= 5.0:
            counts["stress out of range"] += 1
            continue
        junction = found.setdefault(row["junction"], {"control": ""})
        junction["control"] = (row.get("control_tagged") or "").strip()
        junction[move] = (stress, _number(row["delay_s"]))
        counts["movements"] += 1
    return found


def read_key(lines) -> dict[str, tuple[float, float]]:
    """By junction id, its (lon, lat)."""
    out = {}
    for line in lines:
        if not line.strip():
            continue
        item = json.loads(line)
        lon, lat = _number(str(item.get("lon"))), _number(str(item.get("lat")))
        if lon is not None and lat is not None:
            out[item["junction"]] = (lon, lat)
    return out


def _open(path: Path):
    if path.suffix == ".gz":
        return io.TextIOWrapper(gzip.open(path), encoding="utf-8", newline="")
    return path.open(encoding="utf-8", newline="")


class Command(BaseCommand):
    help = "Load the junction run's ratings (replaces every row). Dry unless --confirm."

    def add_arguments(self, parser):
        parser.add_argument("ratings", help="junctions-stress-delay.csv.gz")
        parser.add_argument("key", help="key.jsonl (each junction's lon and lat)")
        parser.add_argument("--confirm", action="store_true", help="write the rows")

    def handle(self, *args, **options):
        from django.contrib.gis.geos import Point

        from core.models import JunctionRater

        counts: Counter = Counter()
        with _open(Path(options["ratings"])) as lines:
            ratings = read_ratings(lines, counts)
        with _open(Path(options["key"])) as lines:
            key = read_key(lines)
        now = timezone.now()
        rows = []
        for junction, item in ratings.items():
            point = key.get(junction)
            if point is None:
                counts["no position"] += 1
                continue
            fields = {}
            for move in MOVES:
                stress, delay = item.get(move, (None, None))
                fields[f"{move}_stress"] = stress
                fields[f"{move}_delay_s"] = delay
            rows.append(
                JunctionRater(
                    junction=junction,
                    location=Point(*point, srid=4326),
                    control=item["control"][:24],
                    loaded_at=now,
                    **fields,
                )
            )
        self.stdout.write(f"{len(rows):,} junctions, {counts['movements']:,} movements rated")
        for reason in ("cannot be made", "one-way flag", "stress out of range", "unknown movement"):
            if counts[reason]:
                self.stdout.write(f"  dropped {counts[reason]:,} movements: {reason}")
        if counts["no position"]:
            self.stdout.write(f"  dropped {counts['no position']:,} junctions: no position")
        if not options["confirm"]:
            self.stdout.write("Dry run: nothing written. The same with --confirm loads it.")
            return
        with transaction.atomic():
            JunctionRater.objects.all().delete()
            JunctionRater.objects.bulk_create(rows, batch_size=BATCH)
        self.stdout.write(f"Loaded {len(rows):,} junctions (every earlier row replaced).")
