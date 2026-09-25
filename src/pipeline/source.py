"""The source extract: downloaded from Geofabrik, merged, then clipped.

Nothing produced this file before. `FETCH_EXTRACT` checked that
`<DATA_ROOT>/extracts/source.osm.pbf` existed and failed the rebuild when it did
not, so a fresh deployment's first rebuild stopped at stage one with
`ReferenceDataMissing` and no document said how to make the file; wherever
somebody had made one by hand, every weekly rebuild after that re-derived the
whole map from that one frozen snapshot, so the "weekly refresh" refreshed
nothing. This module is the missing step.

PLAN:13 is the specification and it is exact about the order:

    Geofabrik extracts for DC, Maryland, and Virginia, merged then clipped with
    `osmium extract -s smart -S types=any` so boundary relations stay complete.
    Admin data is built with `valhalla_build_admins` from the merged extract
    before clipping.

So two files come out of this stage and both are kept:

    <extracts>/merged.osm.pbf   the three states, merged, *not* clipped
    <extracts>/source.osm.pbf   that file clipped to the coverage region

The merged one is what `valhalla_build_admins` reads. That is not a detail: an
admin polygon is a boundary relation, the clip cuts relations at the region's
edge even under `-s smart -S types=any` (which keeps *referenced* members
complete, not members outside the region), and an admin database built from the
clipped file describes administrative areas that stop at the bounding box. The
tile build then charges a country- or state-crossing cost wherever a real
boundary was truncated. `pipeline/tiles.py` already said the admin build must
not read a variant extract; it read the clipped one instead, and cited PLAN:13
as endorsing that.

ONE POINT IN TIME, ASSUMED. `osmium merge` is for files from the same moment:
its man page says "Do not use this command to merge non-history files with data
from different points in time. It will not work correctly", because two files
carrying different versions of the same object both survive into the output and
the result is a small history file rather than a snapshot. Geofabrik's three
state extracts are three separate files, and they are three separate daily
*runs* of the extractor - but all three are cut from the same daily planet
snapshot, so an object that spans the Potomac carries the same version in the DC
file and the Virginia file and osmium sees one object, not two. That is the
assumption this stage makes, and it is Geofabrik's published arrangement rather
than anything this code enforces. It is acceptable because the three downloads
happen minutes apart in one rebuild, so they are the same day's build; a
deployment pointing `SOURCE_EXTRACT_URLS` at mirrors that are days out of step
with each other would break it. A mismatch is not silent, and this module is
what makes that true: osmium warns on multiple versions of an object unless it
is given `-H/--with-history` (which this does not pass), and the warning goes
to stderr, which the pipeline's command runner captures. Captured and
discarded, the argument above was an assumption nobody could check - the
warning existed and no human being would ever see it. So every command run from
here has its stderr logged, by `log_command_output`, on the `pipeline.source`
logger: osmium's progress at INFO, and a line naming multiple versions or
`--with-history` at WARNING, in the rebuild's own log. That is the place to
look when admin polygons or geometry come out wrong after a refresh.

Nothing here has been executed: this environment has neither `osmium` nor
`curl` on PATH nor any route to Geofabrik, so the command lines are from the
osmium-tool and curl documentation and the first real rebuild is what confirms
them. They are built as argument lists and asserted by tests for that reason.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# Geofabrik's per-state daily extracts. `-latest` is the current build; it moves
# under the same URL, which is what makes the freshness rule below mean
# something.
GEOFABRIK_BASE_URL = "https://download.geofabrik.de/north-america/us/"
GEOFABRIK_REGIONS = ("district-of-columbia", "maryland", "virginia")
GEOFABRIK_EXTRACTS = tuple(
    f"{GEOFABRIK_BASE_URL}{region}-latest.osm.pbf" for region in GEOFABRIK_REGIONS
)

# The two files this stage leaves behind, by fixed name. Fixed rather than
# derived from the configured path because the second one is what the rest of
# the rebuild reads and the first is what the admin build reads, and both have
# to be findable by the next rebuild's freshness check without being told where
# the last one put them.
MERGED_NAME = "merged.osm.pbf"
CLIPPED_NAME = "source.osm.pbf"

# Every osmium output here is written to `<name>.part` and renamed on success,
# and osmium cannot guess a format from that name - so each one says `-f pbf`.
#
# osmium normally takes the format from the output file's suffix. libosmium's
# `detect_format_from_suffix` (include/osmium/io/file.hpp) splits the name on
# dots and looks at the *last* element only: it strips `gz`/`bz2`, then matches
# `pbf`/`xml`/`opl`/..., then `osm`/`osh`/`osc`. `part` is none of those, so the
# format stays `unknown`, and `File::check()` throws "Could not detect file
# format for filename". osmium-tool calls that during argument setup, before it
# reads a byte - `with_osm_output::check_output_file` (src/io.cpp:157-171),
# reached from `setup_output_file` in both command_merge.cpp and
# command_extract.cpp - so `merge` and `extract` both exited non-zero on the
# very first rebuild, at the merge, with three freshly downloaded state files
# on disk and nothing to show for them.
#
# `-f, --output-format=FORMAT` is documented for exactly this: "Can be used to
# set the output file format if it can't be autodetected from the output file
# name" (osmium-tool man/output-options.md, the OUTPUT OPTIONS block that
# `osmium-merge.md` and `osmium-extract.md` both include as
# @MAN_OUTPUT_OPTIONS@, and `src/io.cpp:182` registers `output-format,f` for
# every command that writes an OSM file). It is *ignored* by `osmium extract`
# only when `--config/-c` names an extract config (osmium-extract.md, the -c
# entry), which this clip does not use: it passes `--bbox` or `--polygon` and
# one `-o`.
#
# The alternative - dropping the `.part` discipline and writing straight to the
# final name - is the one this cannot do: a killed merge would leave a
# truncated `merged.osm.pbf` that the next week's freshness check accepts and
# `valhalla_build_admins` reads.
OUTPUT_FORMAT_FLAG = ("-f", "pbf")

# How old the extract may be before it is rebuilt.
#
# Six days rather than seven: the rebuild is weekly (Tuesdays 08:00 UTC), so a
# figure at or above the cadence would let a week-old snapshot through on the
# ordinary path and the map would age by a week every week. Below it, and a
# re-run in the same week - a retry, a hand-fired rebuild, a second attempt
# after a validation failure - reuses the extract instead of pulling 1-2 GB
# again. Six days is the largest value that does both.
DEFAULT_MAX_AGE = timedelta(days=6)

# What the extract is assumed to cost on the data volume before there is one to
# measure. Geofabrik's three state extracts are on the order of 1-2 GB together
# today, the merged file is about the same again and the clip is a fraction of
# it. `tiles.check_disk_gate` reserves four times the source size - for the
# three variant extracts the build writes plus scratch - so charging four times
# this covers the production's own files as well. Approximate by construction:
# it is a pre-flight for a file that does not exist yet, not a measurement.
#
# The gate measures `TILES_DIR` while the extract lands in `<DATA_ROOT>/extracts`,
# which is only the same free-space figure because they are the same volume: the
# rebuild service binds `/data/tiles` and `/data/extracts` (and the other
# directories it writes) each from a subdirectory of the one `${DATA_ROOT}`
# (compose.yaml), so they are two directories on one filesystem.
# Bind either from somewhere else and the gate would be measuring a volume the
# download does not touch. `tests/test_source.py` holds compose to that.
ESTIMATED_BYTES = 2 * 1024**3


# What osmium says when the files it was handed are not one snapshot, matched
# case-insensitively as substrings of a line.
#
# Two fragments rather than one message, because what has to be caught is the
# condition and not a wording: osmium-tool names the remedy (`--with-history`)
# and the symptom ("multiple versions") in the warning it writes when a merge
# of non-history files meets two versions of one object, and a release that
# rephrases one of them is unlikely to drop both. Nothing here has run osmium
# - see the module docstring - so a match that is too narrow would fail in the
# direction of saying nothing, which is the failure this exists to end.
MULTIPLE_VERSION_MARKERS = ("multiple versions", "with-history", "with_history")


def log_command_output(what: str, output: object) -> None:
    """Put a command's stderr in the rebuild's log, one record per line.

    `what` names the step, because three commands write to this log in one
    stage and "downloading" and "merging" are different problems.

    At INFO, since this is ordinary progress - curl says nothing under `-sS`
    unless something went wrong, and osmium's is a progress bar and a summary.
    At WARNING for the one line that changes what the output *is*: a merge that
    saw two versions of an object produced a small history file rather than a
    snapshot, and everything built from it - the admin database above all -
    describes a map that never existed at any one moment.

    `output` is whatever the injected runner returned. Read by attribute rather
    than by type: this module is imported by `config/settings.py` at settings
    time and must not import `pipeline.tiles` (which would import Django's
    settings back), and a runner that returns None - a test's, an operator's
    hand-wired one - is not a reason to fail a download.
    """
    stderr = getattr(output, "stderr", None)
    if not isinstance(stderr, str):
        return
    for line in stderr.splitlines():
        if not line.strip():
            continue
        if any(marker in line.lower() for marker in MULTIPLE_VERSION_MARKERS):
            logger.warning(
                "%s: osmium reports more than one version of an object, so the files it was "
                "given are not one point in time and what came out is a small history file "
                "rather than a snapshot: %s",
                what,
                line,
            )
        else:
            logger.info("%s: %s", what, line)


class SourceExtractFailed(RuntimeError):
    """A download, merge or clip did not leave the file it was asked for.

    Deliberately not one of `config.procrastinate.terminal_causes`: a download
    that dropped or a mirror that was briefly unreachable is exactly the failure
    a retry fixes, which is the opposite of a missing reference file or a failed
    validation.
    """


@dataclass(frozen=True)
class SourceExtract:
    """What the stage produced or reused."""

    merged: Path
    clipped: Path
    downloads: tuple[Path, ...]
    # False when both files were already present and fresh enough to keep.
    refreshed: bool


def download_name(url: str) -> str:
    """The file name a URL is downloaded to."""
    return url.rsplit("/", 1)[-1]


def curl_command(url: str, partial: Path) -> list[str]:
    """`curl`, quiet, failing on an HTTP error, retrying a dropped transfer.

    `-f` so a 404 or a 5xx is a non-zero exit rather than an HTML error page
    written into the file, `-sS` so the progress meter stays out of the log but
    an error message does not, `-L` because Geofabrik redirects to its mirrors,
    and `--retry 3` for the transient half of the failures. The output name is
    a `.part`; see `download`.
    """
    return ["curl", "-fsSL", "--retry", "3", "-o", str(partial), url]


def download(url: str, destination: Path, run: Callable[[Sequence[str]], object]) -> Path:
    """Fetch one extract, through the pipeline's command runner.

    Through the runner rather than `urllib` so the rebuild's own deadline
    applies to it: this is the one stage that can sit for an hour on somebody
    else's bandwidth, and a wedged download has to be killed by the same budget
    that kills a wedged tile build.

    Written to `<name>.part` and moved into place only once curl has exited
    zero. A 1-2 GB transfer interrupted by a killed container, a full volume or
    a dropped connection otherwise leaves a truncated file under the real name,
    and nothing downstream can tell a truncated PBF from a small region: osmium
    would read what there is of it and the rebuild would carry on with part of
    Virginia missing. A `.part` from such a run is removed here rather than
    resumed, because it is unknown how much of it is good.
    """
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    partial.unlink(missing_ok=True)
    log_command_output(f"downloading {url}", run(curl_command(url, partial)))
    if not partial.is_file() or partial.stat().st_size == 0:
        partial.unlink(missing_ok=True)
        raise SourceExtractFailed(f"curl left nothing at {partial} for {url}")
    partial.replace(destination)
    return destination


def merge_command(inputs: Sequence[Path], output: Path) -> list[str]:
    """`osmium merge`, which is the one that keeps the three states one file.

    `--overwrite` because osmium refuses to write a file that exists
    (`pipeline/extract.py:152` is the same refusal met from the Python
    bindings), and this runs every week into the same directory.

    `-f pbf` because the output name is a `.part`. See `OUTPUT_FORMAT_FLAG`.
    """
    return [
        "osmium",
        "merge",
        "--overwrite",
        *OUTPUT_FORMAT_FLAG,
        *[str(path) for path in inputs],
        "-o",
        str(output),
    ]


def merge(inputs: Sequence[Path], merged: Path, run: Callable[[Sequence[str]], object]) -> Path:
    """Merge the state extracts into one file, via a `.part` name."""
    merged = Path(merged)
    partial = merged.with_name(merged.name + ".part")
    partial.unlink(missing_ok=True)
    log_command_output("osmium merge", run(merge_command([Path(p) for p in inputs], partial)))
    if not partial.is_file():
        raise SourceExtractFailed(f"osmium merge left nothing at {partial}")
    partial.replace(merged)
    return merged


def clip_command(merged: Path, output: Path, region: Path | Sequence[float]) -> list[str]:
    """PLAN:13's clip, verbatim: `-s smart -S types=any`.

    The strategy is what keeps boundary relations usable. `complete_ways` alone
    cuts a relation at the region's edge; `smart` keeps multipolygons and
    boundaries whose members reach outside, and `types=any` says which relation
    types that applies to rather than osmium's default of multipolygons only -
    without it the administrative boundaries this project cares about are
    exactly the relations that get cut.

    A coverage polygon is preferred over the bounding box when there is one:
    the plan's region is a polygon - Frederick and Leesburg, Baltimore,
    Annapolis, Fredericksburg - and the box around it reaches well past them.
    The repository carries no polygon file yet, so `settings.COVERAGE_POLYGON`
    is None and `settings.COVERAGE_BBOX` is what is clipped to.

    `-f pbf` because the output name is a `.part`. See `OUTPUT_FORMAT_FLAG`.
    """
    if isinstance(region, (str, Path)):
        bounds = ["--polygon", str(region)]
    else:
        west, south, east, north = region
        bounds = ["--bbox", f"{west},{south},{east},{north}"]
    return [
        "osmium",
        "extract",
        "--overwrite",
        *OUTPUT_FORMAT_FLAG,
        "-s",
        "smart",
        "-S",
        "types=any",
        *bounds,
        "-o",
        str(output),
        str(merged),
    ]


def clip(
    merged: Path,
    clipped: Path,
    region: Path | Sequence[float],
    run: Callable[[Sequence[str]], object],
) -> Path:
    """Clip the merged extract to the coverage region, via a `.part` name."""
    clipped = Path(clipped)
    partial = clipped.with_name(clipped.name + ".part")
    partial.unlink(missing_ok=True)
    log_command_output("osmium extract", run(clip_command(Path(merged), partial, region)))
    if not partial.is_file():
        raise SourceExtractFailed(f"osmium extract left nothing at {partial}")
    partial.replace(clipped)
    return clipped


def age(path: Path, now: datetime) -> timedelta | None:
    """How old a file is, or None when it is not there."""
    path = Path(path)
    if not path.is_file():
        return None
    return now - datetime.fromtimestamp(path.stat().st_mtime, UTC)


def refresh_reason(
    merged: Path,
    clipped: Path,
    *,
    max_age: timedelta = DEFAULT_MAX_AGE,
    now: datetime | None = None,
    force: bool = False,
) -> str | None:
    """Why the extract has to be rebuilt, or None to reuse what is on disk.

    A reason rather than a boolean because it goes in the log: "the extract was
    rebuilt" and "the extract was rebuilt because the merged file somebody
    deleted is the one the admin build reads" are different operational facts.

    Both files are checked. The clipped one is what the rebuild reads and the
    merged one is what `valhalla_build_admins` reads, so a deployment that has
    the second but not the first has no working extract either way.
    """
    now = now or datetime.now(UTC)
    if force:
        return "a refresh was forced"
    for path, what in ((clipped, "clipped"), (merged, "merged")):
        file_age = age(path, now)
        if file_age is None:
            return f"the {what} extract {path} is absent"
        if file_age > max_age:
            return (
                f"the {what} extract {path} is {file_age.days} days old, past the "
                f"{max_age.days}-day limit"
            )
    return None


def ensure_extract(
    directory: Path,
    region: Path | Sequence[float],
    run: Callable[[Sequence[str]], object],
    *,
    urls: Sequence[str] = GEOFABRIK_EXTRACTS,
    max_age: timedelta = DEFAULT_MAX_AGE,
    now: datetime | None = None,
    force: bool = False,
) -> SourceExtract:
    """Make a merged and a clipped extract present and recent enough to build
    from, downloading only when they are not.

    An operator forces a refresh by deleting either file or by setting
    `SOURCE_EXTRACT_FORCE_REFRESH=1`; there is no third mechanism to remember.
    """
    directory = Path(directory)
    merged = directory / MERGED_NAME
    clipped = directory / CLIPPED_NAME

    reason = refresh_reason(merged, clipped, max_age=max_age, now=now, force=force)
    if reason is None:
        logger.info("reusing the source extract at %s; nothing downloaded", clipped)
        return SourceExtract(merged=merged, clipped=clipped, downloads=(), refreshed=False)

    logger.info("rebuilding the source extract: %s", reason)
    directory.mkdir(parents=True, exist_ok=True)
    downloads = tuple(download(url, directory / download_name(url), run) for url in urls)
    merge(downloads, merged, run)
    clip(merged, clipped, region, run)
    logger.info(
        "source extract rebuilt: %s (%.1f GiB) from %d regions, clipped to %s (%.1f GiB)",
        merged,
        merged.stat().st_size / 1024**3,
        len(downloads),
        clipped,
        clipped.stat().st_size / 1024**3,
    )
    return SourceExtract(merged=merged, clipped=clipped, downloads=downloads, refreshed=True)
