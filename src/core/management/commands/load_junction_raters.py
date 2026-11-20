"""`manage.py load_junction_raters` - load the junction run's ratings (`JunctionRater`).

The 2026-11-19 junction run rated every junction a bike rides through, per movement, a stress
level and the seconds lost there (reports/bike-infra-guide/junctions-run-FINAL.md). Two files
from its folder:

- `junctions-stress-delay.csv.gz`: one row per junction and movement (`junction`, `movement`,
  `stress`, `delay_s`, `control_tagged`, `oneway_flag`, ...). `stress` and `delay_s` are the
  final values; blank where the movement cannot be made.
- `junction-nodes.tsv`: one line per node of each junction (`junction`, `node`, `lon`, `lat`,
  tab-separated, with a header). A junction of several nodes (a divided road's carriageways)
  is one rating at each of its nodes, which a route's node is matched to
  (`intersections.RATER_MATCH_M`). The positions are the run's extract's: a node the live
  map has moved or dropped is simply not matched.

A movement the one-way check flags (`oneway_flag`) is dropped: the router knows which moves
are legal, and a rating for one that cannot be made would be read for a move that can. The
load replaces every row, from the next plan, with no rebuild. Dry unless `--confirm`: it says
how many junctions and movements it would load and what it dropped.

    python manage.py load_junction_raters <csv.gz> <junction-nodes.tsv>
    # read what it would do, then the same with --confirm
"""

from __future__ import annotations

import csv
import gzip
import io
import math
from collections import Counter
from collections.abc import Iterator
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


def read_ratings(lines, counts: Counter) -> dict[str, tuple]:
    """By junction id, (control, cross stress, cross delay, left stress, left delay, along
    stress, along delay): a tuple, as some 600,000 are held at once."""
    found: dict[str, list] = {}
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
        junction = found.setdefault(row["junction"], [""] + [None] * (2 * len(MOVES)))
        junction[0] = (row.get("control_tagged") or "").strip()[:24]
        at = 1 + 2 * MOVES.index(move)
        junction[at : at + 2] = [stress, _number(row["delay_s"])]
        counts["movements"] += 1
    return {junction: tuple(item) for junction, item in found.items()}


def read_nodes(lines) -> Iterator[tuple[str, int, float, float]]:
    """Each node of the nodes file as (junction id, node id, lon, lat), streamed."""
    reader = csv.DictReader(lines, delimiter="\t")
    missing = {"junction", "node", "lon", "lat"} - set(reader.fieldnames or ())
    if missing:
        raise CommandError(f"the nodes file has no {sorted(missing)} column")
    for row in reader:
        lon, lat = _number(row["lon"]), _number(row["lat"])
        try:
            node = int(row["node"])
        except (TypeError, ValueError):
            continue
        if row["junction"] and lon is not None and lat is not None:
            yield row["junction"], node, lon, lat


def _open(path: Path):
    if path.suffix == ".gz":
        return io.TextIOWrapper(gzip.open(path), encoding="utf-8", newline="")
    return path.open(encoding="utf-8", newline="")


class Command(BaseCommand):
    help = "Load the junction run's ratings (replaces every row). Dry unless --confirm."

    def add_arguments(self, parser):
        parser.add_argument("ratings", help="junctions-stress-delay.csv.gz")
        parser.add_argument("nodes", help="junction-nodes.tsv (each junction's nodes)")
        parser.add_argument("--confirm", action="store_true", help="write the rows")

    def handle(self, *args, **options):
        from django.contrib.gis.geos import Point

        from core.models import JunctionRater

        counts: Counter = Counter()
        with _open(Path(options["ratings"])) as lines:
            ratings = read_ratings(lines, counts)
        now = timezone.now()
        confirm = options["confirm"]
        placed: set[str] = set()
        seen: set[int] = set()
        batch: list = []
        written = 0

        def flush() -> None:
            nonlocal written
            if batch:
                JunctionRater.objects.bulk_create(batch)
                written += len(batch)
                batch.clear()

        # Streamed, a batch at a time: the nodes file holds over a million rows, and the dry
        # run only counts them (v0.29.0 release review).
        with transaction.atomic(), _open(Path(options["nodes"])) as lines:
            if confirm:
                JunctionRater.objects.all().delete()
            for junction, node, lon, lat in read_nodes(lines):
                item = ratings.get(junction)
                if item is None:
                    counts["unrated node"] += 1
                    continue
                if node in seen:
                    # One node in two junctions: the first keeps it (the column is unique).
                    counts["duplicate node"] += 1
                    continue
                seen.add(node)
                placed.add(junction)
                if not confirm:
                    continue
                fields = {}
                for at, move in enumerate(MOVES):
                    fields[f"{move}_stress"] = item[1 + 2 * at]
                    fields[f"{move}_delay_s"] = item[2 + 2 * at]
                batch.append(
                    JunctionRater(
                        junction=junction,
                        node=node,
                        location=Point(lon, lat, srid=4326),
                        control=item[0],
                        loaded_at=now,
                        **fields,
                    )
                )
                if len(batch) >= BATCH:
                    flush()
            flush()
        junctions = len(placed)
        counts["no position"] = len(ratings) - junctions
        self.stdout.write(
            f"{junctions:,} junctions at {len(seen):,} nodes, "
            f"{counts['movements']:,} movements rated"
        )
        for reason in ("cannot be made", "one-way flag", "stress out of range", "unknown movement"):
            if counts[reason]:
                self.stdout.write(f"  dropped {counts[reason]:,} movements: {reason}")
        if counts["no position"]:
            self.stdout.write(f"  dropped {counts['no position']:,} junctions: no nodes")
        for reason in ("duplicate node", "unrated node"):
            if counts[reason]:
                self.stdout.write(f"  skipped {counts[reason]:,} nodes: {reason}")
        if not confirm:
            self.stdout.write("Dry run: nothing written. The same with --confirm loads it.")
            return
        self.stdout.write(
            f"Loaded {junctions:,} junctions at {written:,} nodes (every earlier row replaced)."
        )
