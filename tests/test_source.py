"""The source extract: what is downloaded, what is merged, what is clipped.

Nothing here runs curl or osmium - neither is on PATH in this environment and
there is no route to Geofabrik - so what these tests hold are the command lines
and the rules around them: which file each command reads and writes, that a
partial download is never mistaken for a finished one, and when a rebuild is
allowed to reuse last week's extract instead of pulling 1-2 GB again.

The command lines themselves are asserted argument by argument for the same
reason `pipeline/tiles.py`'s are: a flag that is wrong here is not visible until
a real rebuild, and `-s smart -S types=any` in particular is the difference
between boundary relations that survive the clip and admin polygons with false
edges in them (PLAN:13).
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pipeline import source
from pipeline.tiles import CommandOutput

BBOX = (-78.0, 38.2, -76.3, 39.5)


class FakeOsmium:
    """curl, osmium merge and osmium extract, as far as the disk sees them.

    Every command is recorded, and each one writes the file named by its `-o`
    argument with content derived from its inputs, so a test can assert that the
    clip was taken from the merged file rather than from one state's download.
    """

    def __init__(self, write: bool = True) -> None:
        self.commands: list[list[str]] = []
        self.write = write

    def __call__(self, command) -> CommandOutput:
        command = list(command)
        self.commands.append(command)
        if not self.write:
            return CommandOutput("", "")
        output = Path(command[command.index("-o") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        if command[0] == "curl":
            output.write_text(f"osm:{source.download_name(command[-1])}")
        else:
            inputs = [
                Path(argument)
                for argument in command
                if argument.endswith(".osm.pbf") and Path(argument) != output
            ]
            joined = "+".join(path.read_text() for path in inputs)
            output.write_text(joined if command[1] == "merge" else f"clip({joined})")
        return CommandOutput("", "")

    def named(self, *first_arguments: str) -> list[list[str]]:
        return [c for c in self.commands if tuple(c[: len(first_arguments)]) == first_arguments]


def age_file(path: Path, days: float) -> None:
    """Backdate a file's mtime, which is what the freshness rule reads."""
    when = time.time() - days * 24 * 3600
    os.utime(path, (when, when))


# --- What is downloaded -------------------------------------------------------


def test_the_three_geofabrik_extracts_are_the_plans_three_states() -> None:
    """PLAN:13: "Geofabrik extracts for DC, Maryland, and Virginia". Virginia
    matters most of the three and is the one an abbreviated list would drop:
    without it the coverage polygon's whole western and southern half - Loudoun,
    Fairfax, Prince William, Fredericksburg - is absent from the map rather than
    absent from the tiles, which is a rebuild that succeeds."""
    assert source.GEOFABRIK_EXTRACTS == (
        "https://download.geofabrik.de/north-america/us/district-of-columbia-latest.osm.pbf",
        "https://download.geofabrik.de/north-america/us/maryland-latest.osm.pbf",
        "https://download.geofabrik.de/north-america/us/virginia-latest.osm.pbf",
    )


def test_a_download_is_written_to_a_part_name_and_moved_into_place(tmp_path) -> None:
    """A 1-2 GB transfer that dies partway must not leave a file under the name
    the next rebuild's freshness check reads: a truncated PBF is not an error
    downstream, it is a smaller region."""
    run = FakeOsmium()
    url = source.GEOFABRIK_EXTRACTS[0]
    destination = tmp_path / "district-of-columbia-latest.osm.pbf"

    assert source.download(url, destination, run) == destination
    assert run.commands == [
        [
            "curl",
            "-fsSL",
            "--retry",
            "3",
            "-o",
            f"{destination}.part",
            url,
        ]
    ]
    assert destination.read_text() == "osm:district-of-columbia-latest.osm.pbf"
    assert not Path(f"{destination}.part").exists(), "the partial name is gone"


def test_a_download_that_leaves_nothing_is_a_failure_rather_than_an_empty_file(
    tmp_path,
) -> None:
    """curl exiting zero having written nothing - a proxy answering 200 with an
    empty body, a full volume - would otherwise produce a zero-byte extract that
    osmium reads as a region with no ways in it."""
    run = FakeOsmium(write=False)
    destination = tmp_path / "virginia-latest.osm.pbf"
    with pytest.raises(source.SourceExtractFailed, match="curl left nothing"):
        source.download(source.GEOFABRIK_EXTRACTS[2], destination, run)
    assert not destination.exists()


def test_a_part_file_left_by_a_killed_download_is_not_treated_as_a_download(
    tmp_path,
) -> None:
    """The `.part` from an interrupted run carries an unknown amount of a real
    extract. It is removed and re-fetched rather than resumed or renamed, and
    the finished file is what curl wrote this time."""
    destination = tmp_path / "maryland-latest.osm.pbf"
    Path(f"{destination}.part").write_text("half of last week's maryland")

    source.download(source.GEOFABRIK_EXTRACTS[1], destination, FakeOsmium())

    assert destination.read_text() == "osm:maryland-latest.osm.pbf"
    assert not Path(f"{destination}.part").exists()


# --- What is merged and clipped ------------------------------------------------


def test_the_merge_command_names_every_input_and_overwrites(tmp_path) -> None:
    """osmium refuses to write a file that exists (the same refusal
    `pipeline/extract.py:152` meets from the bindings), and this directory is
    written into every week."""
    inputs = [tmp_path / f"{name}.osm.pbf" for name in ("dc", "md", "va")]
    command = source.merge_command(inputs, tmp_path / "merged.osm.pbf.part")
    assert command == [
        "osmium",
        "merge",
        "--overwrite",
        *[str(path) for path in inputs],
        "-o",
        str(tmp_path / "merged.osm.pbf.part"),
    ]


def test_the_clip_command_is_the_plans_strategy_and_its_option(tmp_path) -> None:
    """PLAN:13 names both halves - `-s smart -S types=any` - and the option is
    the half that is easy to drop. Without `types=any` the strategy keeps
    multipolygon relations complete and cuts every other type at the region's
    edge, which is exactly the administrative boundaries this project builds
    admin data from.
    """
    command = source.clip_command(
        tmp_path / "merged.osm.pbf", tmp_path / "source.osm.pbf.part", BBOX
    )
    assert command == [
        "osmium",
        "extract",
        "--overwrite",
        "-s",
        "smart",
        "-S",
        "types=any",
        "--bbox",
        "-78.0,38.2,-76.3,39.5",
        "-o",
        str(tmp_path / "source.osm.pbf.part"),
        str(tmp_path / "merged.osm.pbf"),
    ]


def test_a_coverage_polygon_is_clipped_to_in_preference_to_the_box(tmp_path) -> None:
    """The plan's region is a polygon; the box around it reaches past
    Fredericksburg and Frederick. There is no polygon file in the repository
    yet, so this is the path a deployment takes when one is drawn."""
    polygon = tmp_path / "coverage.geojson"
    command = source.clip_command(tmp_path / "merged.osm.pbf", tmp_path / "out.part", polygon)
    assert "--polygon" in command
    assert command[command.index("--polygon") + 1] == str(polygon)
    assert "--bbox" not in command


def test_the_merge_and_the_clip_both_go_through_a_part_name(tmp_path) -> None:
    """A killed osmium leaves no file under the name the freshness check reads,
    the same way a killed curl does not."""
    run = FakeOsmium()
    inputs = [tmp_path / f"{name}.osm.pbf" for name in ("dc", "md")]
    for path in inputs:
        path.write_text(f"osm:{path.name}")

    merged = source.merge(inputs, tmp_path / "merged.osm.pbf", run)
    clipped = source.clip(merged, tmp_path / "source.osm.pbf", BBOX, run)

    assert [c[c.index("-o") + 1] for c in run.commands] == [
        f"{merged}.part",
        f"{clipped}.part",
    ]
    assert not Path(f"{merged}.part").exists() and not Path(f"{clipped}.part").exists()
    assert merged.read_text() == "osm:dc.osm.pbf+osm:md.osm.pbf"
    assert clipped.read_text() == "clip(osm:dc.osm.pbf+osm:md.osm.pbf)"


def test_an_osmium_run_that_leaves_nothing_is_a_failure(tmp_path) -> None:
    run = FakeOsmium(write=False)
    with pytest.raises(source.SourceExtractFailed, match="merge left nothing"):
        source.merge([tmp_path / "dc.osm.pbf"], tmp_path / "merged.osm.pbf", run)
    with pytest.raises(source.SourceExtractFailed, match="extract left nothing"):
        source.clip(tmp_path / "merged.osm.pbf", tmp_path / "source.osm.pbf", BBOX, run)


# --- The freshness rule --------------------------------------------------------


def test_a_missing_extract_is_a_reason_to_build_one(tmp_path) -> None:
    reason = source.refresh_reason(tmp_path / "merged.osm.pbf", tmp_path / "source.osm.pbf")
    assert "source.osm.pbf is absent" in reason


def test_a_merged_extract_that_was_deleted_is_rebuilt_even_when_the_clip_is_fresh(
    tmp_path,
) -> None:
    """The merged file is not scratch left over from making the clip: it is what
    `valhalla_build_admins` reads (PLAN:13), so a deployment that has the clip
    and not the merge has no working extract."""
    (tmp_path / "source.osm.pbf").write_text("clipped")
    reason = source.refresh_reason(tmp_path / "merged.osm.pbf", tmp_path / "source.osm.pbf")
    assert "merged extract" in reason and "is absent" in reason


def test_an_extract_from_earlier_this_week_is_reused(tmp_path) -> None:
    """The whole point of the rule: a retry, or a second rebuild fired by hand
    after a validation failure, must not pull 1-2 GB again."""
    for name in (source.MERGED_NAME, source.CLIPPED_NAME):
        (tmp_path / name).write_text("last Tuesday")
        age_file(tmp_path / name, days=3)
    assert (
        source.refresh_reason(tmp_path / source.MERGED_NAME, tmp_path / source.CLIPPED_NAME) is None
    )


def test_an_extract_older_than_the_limit_is_rebuilt(tmp_path) -> None:
    """Six days, just under the weekly cadence. At or above seven the ordinary
    weekly rebuild would accept last week's snapshot and the map would age by a
    week every week - which is the state this stage was found in, with one
    hand-made extract re-derived every Tuesday forever."""
    for name in (source.MERGED_NAME, source.CLIPPED_NAME):
        (tmp_path / name).write_text("a fortnight ago")
        age_file(tmp_path / name, days=14)
    reason = source.refresh_reason(tmp_path / source.MERGED_NAME, tmp_path / source.CLIPPED_NAME)
    assert "14 days old" in reason and "6-day limit" in reason
    assert source.DEFAULT_MAX_AGE == timedelta(days=6)


def test_a_forced_refresh_needs_no_reason_of_its_own(tmp_path) -> None:
    for name in (source.MERGED_NAME, source.CLIPPED_NAME):
        (tmp_path / name).write_text("today's")
    assert (
        source.refresh_reason(
            tmp_path / source.MERGED_NAME, tmp_path / source.CLIPPED_NAME, force=True
        )
        == "a refresh was forced"
    )


# --- The stage ------------------------------------------------------------------


def test_the_stage_produces_both_files_from_the_three_downloads(tmp_path) -> None:
    """A fresh deployment: nothing on disk, three downloads, one merge, one
    clip, and both files left behind - the merged one because
    `valhalla_build_admins` reads it and the clipped one because everything else
    does."""
    run = FakeOsmium()
    produced = source.ensure_extract(tmp_path / "extracts", BBOX, run)

    assert produced.refreshed
    assert produced.merged == tmp_path / "extracts" / "merged.osm.pbf"
    assert produced.clipped == tmp_path / "extracts" / "source.osm.pbf"
    assert produced.merged.is_file() and produced.clipped.is_file()
    assert len(run.named("curl")) == 3
    assert [c[-1] for c in run.named("curl")] == list(source.GEOFABRIK_EXTRACTS)
    assert len(run.named("osmium", "merge")) == 1
    assert len(run.named("osmium", "extract")) == 1

    # The clip is taken from the merged file, not from one state's download.
    assert produced.clipped.read_text() == (
        "clip(osm:district-of-columbia-latest.osm.pbf+osm:maryland-latest.osm.pbf"
        "+osm:virginia-latest.osm.pbf)"
    )
    # And the merged file is *not* the clip: it is what admin data is built from
    # before clipping.
    assert "clip(" not in produced.merged.read_text()


def test_the_stage_downloads_nothing_when_the_extract_is_fresh(tmp_path) -> None:
    run = FakeOsmium()
    source.ensure_extract(tmp_path, BBOX, run)
    first = list(run.commands)

    again = source.ensure_extract(tmp_path, BBOX, run)

    assert not again.refreshed
    assert run.commands == first, "a second run in the same week runs no command at all"
    assert again.merged.is_file() and again.clipped.is_file()


def test_the_stage_rebuilds_a_stale_extract(tmp_path) -> None:
    run = FakeOsmium()
    source.ensure_extract(tmp_path, BBOX, run)
    for name in (source.MERGED_NAME, source.CLIPPED_NAME):
        age_file(tmp_path / name, days=7)

    again = source.ensure_extract(tmp_path, BBOX, run)

    assert again.refreshed
    assert len(run.named("curl")) == 6, "the three regions again"


def test_the_stage_rebuilds_when_a_refresh_is_forced(tmp_path) -> None:
    """The operator's lever, for a rebuild that must start from today's
    Geofabrik build. Deleting either file does the same thing."""
    run = FakeOsmium()
    source.ensure_extract(tmp_path, BBOX, run)

    again = source.ensure_extract(tmp_path, BBOX, run, force=True)

    assert again.refreshed and len(run.named("curl")) == 6


def test_the_stage_clips_to_the_region_it_is_given(tmp_path) -> None:
    run = FakeOsmium()
    polygon = tmp_path / "coverage.geojson"
    polygon.write_text("{}")
    source.ensure_extract(tmp_path, polygon, run)
    clip = run.named("osmium", "extract")[0]
    assert clip[clip.index("--polygon") + 1] == str(polygon)


def test_the_stage_takes_the_urls_it_is_given(tmp_path) -> None:
    """A deployment behind a mirror sets SOURCE_EXTRACT_URLS; the module's own
    list is the default rather than the only possibility."""
    run = FakeOsmium()
    source.ensure_extract(tmp_path, BBOX, run, urls=("https://mirror.example/dc.osm.pbf",))
    assert [c[-1] for c in run.named("curl")] == ["https://mirror.example/dc.osm.pbf"]


def test_the_freshness_clock_is_the_files_own_age(tmp_path) -> None:
    """`now` is injectable so this reads a clock rather than a sleep."""
    (tmp_path / source.MERGED_NAME).write_text("x")
    (tmp_path / source.CLIPPED_NAME).write_text("x")
    later = datetime.now(UTC) + timedelta(days=8)
    reason = source.refresh_reason(
        tmp_path / source.MERGED_NAME, tmp_path / source.CLIPPED_NAME, now=later
    )
    assert "8 days old" in reason
