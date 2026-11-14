"""How built up the land around a road is: people, homes and jobs within half a mile.

The road panel's Setting line (the owner, 2026-11-13: "We can include setting as something
for everything. Maybe just tag in it how urban/rural/suburban it appears (as well as a
remote level where there's not a lot of people at all there)", "we could use the census
data and build one from houses and jobs", "Urban might have higher levels", "Setting can
have in it people and jobs within a half mile"). A label for riders only: it never
changes a stress level. The level's own urban/rural switch stays the Census urban area
(`urban-areas.json`).

Inputs, both U.S. Census Bureau, public domain:

- 2020 Census block people (`POP20`) and homes (`HOUSING20`) with each block's internal
  point, from the TIGER/Line 2020 `TABBLOCK20` files, one per state.
- Jobs located in each block (`C000`, all jobs) from LEHD LODES 8, Workplace Area
  Characteristics (`wac`, all jobs `S000`, job type `JT00`), one per state and year.

A block counts toward a road when its internal point lies within half a mile of the road.
The counts are kept whole with the area they were counted over, so the panel says them
for a typical half-mile circle on the road (`per_circle`) and the band is read from the
density (`band`), and changing a cutoff needs no rebuild.
"""

from __future__ import annotations

import csv
import gzip
import io
import math
import struct
import zipfile
from collections.abc import Iterable, Iterator
from pathlib import Path

FILE_NAME = "setting.json"

# Half a mile, in metres: the owner's "within a half mile".
RADIUS_M = 804.672
SQ_M_PER_SQ_MI = 2_589_988.110336
# The area of a half-mile circle, in square miles (pi / 4).
CIRCLE_SQ_MI = math.pi * 0.25

# Bands by people plus jobs per square mile. 500 is the Census Bureau's urban-fringe
# density from 2000 and 2010 (Federal Register 75 FR 52174, 2010); 50 and 4,000 are our
# default, unmeasured. A dense core is 25,000 jobs or more per square mile, our default,
# unmeasured: it picks out downtown Washington and central Baltimore.
REMOTE_BELOW = 50
RURAL_BELOW = 500
SUBURBAN_BELOW = 4_000
DENSE_CORE_JOBS = 25_000

BAND_WORDS = {
    "remote": "Remote",
    "rural": "Rural",
    "suburban": "Suburban",
    "urban": "Urban",
    "dense": "Dense core",
}

# Highway classes with no traffic facts in the road panel, so no Setting line: left out of
# `setting.json` to keep the rebuild's copy small.
NOT_ROADS = frozenset(
    {
        "footway",
        "path",
        "cycleway",
        "steps",
        "pedestrian",
        "bridleway",
        "corridor",
        "elevator",
        "platform",
        "proposed",
        "construction",
        "abandoned",
        "razed",
    }
)

# The census vintages the panel names.
BLOCKS_YEAR = 2020
LODES_VERSION = "LODES 8"
LODES_YEAR = 2023


def band(people: float, jobs: float, sq_mi: float) -> str | None:
    """The setting's band from the counts and the area they were counted over."""
    if not sq_mi or sq_mi <= 0:
        return None
    if jobs / sq_mi >= DENSE_CORE_JOBS:
        return "dense"
    density = (people + jobs) / sq_mi
    if density < REMOTE_BELOW:
        return "remote"
    if density < RURAL_BELOW:
        return "rural"
    if density < SUBURBAN_BELOW:
        return "suburban"
    return "urban"


def per_circle(count: float, sq_mi: float) -> float:
    """A count over a road's half-mile corridor said for a typical half-mile circle on it,
    so a ten-mile road and a one-block street read on one scale."""
    return count * CIRCLE_SQ_MI / sq_mi if sq_mi and sq_mi > 0 else 0.0


def about(count: float) -> str:
    """A count rounded to two significant figures, said as a rider reads it."""
    if count < 10:
        return "under 10"
    digits = int(math.floor(math.log10(count))) - 1
    rounded = int(round(count, -digits))
    return f"about {rounded:,}"


# --- reading the Census files ----------------------------------------------------------


def read_dbf(data: bytes) -> Iterator[dict[str, str]]:
    """The records of a dBASE III table (a shapefile's attributes), as stripped strings.

    The TIGER/Line block files are read for their attributes alone; the format is a
    32-byte header, 32-byte field descriptors ending in 0x0D, then fixed-width records
    each led by a deletion flag."""
    count, header_len, record_len = struct.unpack("<IHH", data[4:12])
    fields = []
    offset = 32
    while data[offset] != 0x0D:
        name = data[offset : offset + 11].split(b"\0", 1)[0].decode("ascii")
        width = data[offset + 16]
        fields.append((name, width))
        offset += 32
    for index in range(count):
        start = header_len + index * record_len
        record = data[start : start + record_len]
        if not record or record[:1] == b"*":
            continue
        values = {}
        position = 1
        for name, width in fields:
            values[name] = record[position : position + width].decode("latin-1").strip()
            position += width
        yield values


def block_rows(path: Path) -> Iterator[tuple[str, float, float, int, int]]:
    """(block GEOID, longitude, latitude, people, homes) from a TABBLOCK20 zip or .dbf."""
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if name.lower().endswith(".dbf")]
            if len(names) != 1:
                raise ValueError(f"{path} holds {len(names)} .dbf files, not one")
            data = archive.read(names[0])
    else:
        data = path.read_bytes()
    for row in read_dbf(data):
        yield (
            row["GEOID20"],
            float(row["INTPTLON20"]),
            float(row["INTPTLAT20"]),
            int(row["POP20"] or 0),
            int(row["HOUSING20"] or 0),
        )


def wac_jobs(path: Path) -> dict[str, int]:
    """Jobs per block GEOID from a LODES WAC file (.csv or .csv.gz)."""
    opener = gzip.open if path.suffix.lower() == ".gz" else open
    with opener(path, "rb") as raw:
        reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8"))
        return {row["w_geocode"]: int(row["C000"]) for row in reader}


# --- counting around each way ---------------------------------------------------------


def _projector(latitude: float):
    """Degrees to local metres, east and north, about one latitude: within a fraction of
    a percent over a few kilometres, which a two-figure label does not see."""
    north = 111_132.954
    east = north * math.cos(math.radians(latitude))
    return lambda lon, lat: (lon * east, lat * north)


def count_around(
    ways: Iterable[tuple[int, list[tuple[float, float]]]],
    blocks: Iterable[tuple[float, float, int, int, int]],
    reference_latitude: float = 39.0,
) -> dict[int, list]:
    """For each way (id, [(lon, lat), ...]): [people, homes, jobs, square miles] within
    half a mile, counting each block whose internal point (lon, lat, people, homes, jobs)
    lies within half a mile of the way.

    One projection about `reference_latitude` for the whole region: across the DC to
    Baltimore box the east-west scale drifts about 2 percent from it, below the label's
    two figures."""
    import numpy as np
    import shapely

    project = _projector(reference_latitude)
    xs, ys, counts = [], [], []
    for lon, lat, people, homes, jobs in blocks:
        if people or homes or jobs:
            x, y = project(lon, lat)
            xs.append(x)
            ys.append(y)
            counts.append((people, homes, jobs))
    index = shapely.STRtree(shapely.points(xs, ys))
    values = np.array(counts, dtype=np.int64).reshape(-1, 3)
    out: dict[int, list] = {}
    # In batches: one bulk query a batch is many times faster than a query a way.
    batch_ids: list[int] = []
    batch_lines: list = []

    def flush() -> None:
        corridors = shapely.buffer(np.array(batch_lines, dtype=object), RADIUS_M, quad_segs=8)
        sums = np.zeros((len(batch_ids), 3), dtype=np.int64)
        ways_at, blocks_at = index.query(corridors, predicate="contains")
        np.add.at(sums, ways_at, values[blocks_at])
        areas = shapely.area(corridors) / SQ_M_PER_SQ_MI
        for way_id, (people, homes, jobs), area in zip(batch_ids, sums, areas, strict=True):
            out[way_id] = [int(people), int(homes), int(jobs), round(float(area), 4)]
        batch_ids.clear()
        batch_lines.clear()

    for way_id, coordinates in ways:
        if len(coordinates) < 2:
            continue
        line = shapely.LineString([project(lon, lat) for lon, lat in coordinates])
        if line.length == 0:
            continue
        batch_ids.append(way_id)
        batch_lines.append(line)
        if len(batch_ids) >= 20_000:
            flush()
    if batch_ids:
        flush()
    return out


def join_jobs(
    rows: Iterable[tuple[str, float, float, int, int]], jobs: dict[str, int]
) -> list[tuple[float, float, int, int, int]]:
    """The block rows with each block's jobs attached (0 where LODES lists none)."""
    return [
        (lon, lat, people, homes, jobs.get(geoid, 0)) for geoid, lon, lat, people, homes in rows
    ]


def panel_columns(row: list | None) -> dict:
    """The segment table's setting columns for one way's counts (none where uncounted)."""
    if not row:
        return {
            "setting_people": None,
            "setting_homes": None,
            "setting_jobs": None,
            "setting_sq_mi": None,
        }
    people, homes, jobs, sq_mi = row
    return {
        "setting_people": int(people),
        "setting_homes": int(homes),
        "setting_jobs": int(jobs),
        "setting_sq_mi": float(sq_mi),
    }
