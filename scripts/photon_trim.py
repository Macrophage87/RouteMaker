"""Trim a Photon JSON dump to the coverage box, streaming.

PLAN.md:60 fills the geocoder "from GraphHopper's per-country Photon dump
filtered to the coverage bounding box". Photon's own `import` has no box
filter - only `-country-codes`, and the US dump is one country - so the filter
is this: read the dump line by line and pass on the lines Photon needs.

The dump is JSON lines (Photon 1.x "NominatimDumpFile"). The first line is the
header, then `CountryInfo` lines, then one `Place` line per place, whose
`content` is a list of documents each carrying a `"centroid": [lon, lat]`.
Every line that is not a `Place` is passed through unchanged, and a `Place`
line is kept when any of its centroids lies inside the box (edges included).
A line is never re-serialised, only copied, so what Photon reads is byte for
byte what GraphHopper published. The centroid is found by text rather than by
parsing the whole line, which is what makes a pass over the ~40 GB US dump a
matter of minutes rather than hours; a `Place` line whose centroid cannot be
read is dropped and counted, never guessed at.

Usage (inside the pinned photon image, which ships python and zstandard; see
scripts/import_photon.sh, which is the documented way to run it):

    python photon_trim.py DUMP.jsonl.zst --bbox W,S,E,N > trimmed.jsonl

or with `-` for an uncompressed dump on stdin. Counts go to stderr.
"""

from __future__ import annotations

import argparse
import io
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

PLACE_MARK = b'{"type":"Place"'
CENTROID_MARK = b'"centroid":['


@dataclass
class Counts:
    read: int = 0
    kept: int = 0
    passed: int = 0
    unreadable: int = 0


def centroids(line: bytes) -> Iterator[tuple[float, float]]:
    """Every `[lon, lat]` that follows a `"centroid":[` in the line."""
    start = 0
    while True:
        at = line.find(CENTROID_MARK, start)
        if at < 0:
            return
        begin = at + len(CENTROID_MARK)
        end = line.find(b"]", begin)
        if end < 0:
            return
        parts = line[begin:end].split(b",")
        start = end
        if len(parts) != 2:
            continue
        try:
            yield float(parts[0]), float(parts[1])
        except ValueError:
            continue


def is_place(line: bytes) -> bool:
    # The type is the first key the generator writes, so a place line starts
    # with it; a nested object that happens to say the same is not a place.
    return line.lstrip().startswith(PLACE_MARK)


def inside(point: tuple[float, float], bbox: tuple[float, float, float, float]) -> bool:
    west, south, east, north = bbox
    lon, lat = point
    return west <= lon <= east and south <= lat <= north


def trim(
    lines: Iterable[bytes], bbox: tuple[float, float, float, float], counts: Counts | None = None
) -> Iterator[bytes]:
    """The lines of a dump that a box-trimmed import needs, in order."""
    counts = counts if counts is not None else Counts()
    for line in lines:
        counts.read += 1
        if not line.strip():
            continue
        if not is_place(line):
            counts.passed += 1
            yield line
            continue
        points = list(centroids(line))
        if not points:
            counts.unreadable += 1
            continue
        if any(inside(p, bbox) for p in points):
            counts.kept += 1
            yield line


def parse_bbox(text: str) -> tuple[float, float, float, float]:
    parts = [float(p) for p in text.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("--bbox is west,south,east,north")
    west, south, east, north = parts
    if not (west < east and south < north):
        raise argparse.ArgumentTypeError("--bbox must have west < east and south < north")
    return west, south, east, north


def _open(path: str):
    if path == "-":
        return sys.stdin.buffer
    raw = open(path, "rb")  # noqa: SIM115 - closed with the process
    if path.endswith(".zst"):
        import zstandard  # the pinned photon image ships it; the host need not

        return io.BufferedReader(zstandard.ZstdDecompressor().stream_reader(raw), 1 << 20)
    return raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dump", help="the .jsonl.zst dump, a .jsonl file, or - for stdin")
    parser.add_argument("--bbox", type=parse_bbox, required=True)
    args = parser.parse_args(argv)

    counts = Counts()
    out = sys.stdout.buffer
    for line in trim(_open(args.dump), args.bbox, counts):
        out.write(line if line.endswith(b"\n") else line + b"\n")
    out.flush()
    print(
        f"photon_trim: read {counts.read} lines, kept {counts.kept} places, passed "
        f"{counts.passed} other lines, dropped {counts.unreadable} places with no "
        "readable centroid",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
