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

import logging
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

    `stderr` is what each command says while doing it, keyed by "curl", "merge"
    or "extract". The real runner captures that stream and hands it back on the
    `CommandOutput`, and what this stage does with it is the subject of the
    tests below.
    """

    def __init__(self, write: bool = True, stderr: dict[str, str] | None = None) -> None:
        self.commands: list[list[str]] = []
        self.write = write
        self.stderr = dict(stderr or {})

    def _output(self, command) -> CommandOutput:
        key = "curl" if command[0] == "curl" else command[1]
        return CommandOutput("", self.stderr.get(key, ""))

    def __call__(self, command) -> CommandOutput:
        command = list(command)
        self.commands.append(command)
        if not self.write:
            return self._output(command)
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
        return self._output(command)

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


def test_a_zero_byte_part_is_not_renamed_into_place(tmp_path) -> None:
    """The other shape of curl writing nothing: it creates the `-o` file and
    then exits zero having put no bytes in it, which is what a proxy answering
    200 with an empty body and a volume that filled at the first write both
    look like from here.

    The `.part` exists, so the file check alone passes it, and the rename then
    puts a zero-byte extract under the real name - which osmium reads as a
    region with no ways in it and the next rebuild reads as fresh. So the size
    is checked as well as the name, and the empty `.part` is cleaned up.
    """
    destination = tmp_path / "virginia-latest.osm.pbf"

    def touch_and_exit_zero(command) -> CommandOutput:
        Path(command[command.index("-o") + 1]).write_bytes(b"")
        return CommandOutput("", "")

    with pytest.raises(source.SourceExtractFailed, match="curl left nothing"):
        source.download(source.GEOFABRIK_EXTRACTS[2], destination, touch_and_exit_zero)

    assert not destination.exists(), "a zero-byte extract is not a download"
    assert not Path(f"{destination}.part").exists(), "and the empty partial is gone"


def test_a_stale_part_is_removed_before_curl_runs_not_after_it(tmp_path) -> None:
    """The removal is what makes the `.part` this run's own work.

    Left in place, last week's half-fetched Maryland is still sitting under the
    partial name when curl exits - and a curl that wrote nothing at all (the
    empty-body and full-volume cases above, or a `--retry` that gave up after
    creating no file) then finds a large, non-empty `.part` and renames half of
    Maryland into place as this week's extract. Resuming it is not available
    either: how much of it is good is unknown.
    """
    destination = tmp_path / "maryland-latest.osm.pbf"
    Path(f"{destination}.part").write_text("half of last week's maryland")

    with pytest.raises(source.SourceExtractFailed, match="curl left nothing"):
        source.download(source.GEOFABRIK_EXTRACTS[1], destination, FakeOsmium(write=False))

    assert not destination.exists(), "last week's partial is not this week's extract"
    assert not Path(f"{destination}.part").exists()


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
        "-f",
        "pbf",
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
        "-f",
        "pbf",
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


def test_every_osmium_output_written_to_a_part_name_states_its_format(tmp_path) -> None:
    """The rule the whole stage lives under, asserted over what it actually
    runs rather than over the two command builders by name.

    osmium takes the output format from the file name's last dot-separated
    element (libosmium `detect_format_from_suffix`, include/osmium/io/file.hpp:
    `gz`/`bz2`, then `pbf`/`xml`/`opl`/..., then `osm`/`osh`/`osc`). Every
    output here is a `.part`, `part` matches none of those, and
    `with_osm_output::check_output_file` (osmium-tool src/io.cpp:157-171) calls
    `File::check()` during *argument setup* - so the command dies with "Could
    not detect file format for filename" before reading a byte. Both commands
    did, which made the first rebuild on a new deployment download three state
    extracts and then fail at the merge.

    `-f/--output-format` is the documented answer ("Can be used to set the
    output file format if it can't be autodetected from the output file name",
    osmium-tool man/output-options.md) and both subcommands take it - the same
    OUTPUT OPTIONS block is included into osmium-merge.md and
    osmium-extract.md, and src/io.cpp:182 registers it for every command that
    writes an OSM file.

    Driven through `ensure_extract` so a third osmium command added later is
    covered by this without anyone remembering to add it here. Nothing runs
    osmium: it is not on PATH in this environment.
    """
    run = FakeOsmium()
    source.ensure_extract(tmp_path / "extracts", BBOX, run)

    osmium = [c for c in run.commands if c[0] == "osmium"]
    assert osmium, "the stage runs osmium; if it stopped, this test is measuring nothing"
    for command in osmium:
        output = command[command.index("-o") + 1]
        assert output.endswith(".part"), (
            f"{command[1]} no longer writes through a .part name; either restore that or "
            "this test is the wrong shape for what it does now"
        )
        assert "-f" in command, (
            f"osmium {command[1]} writes {output} and does not say -f; osmium cannot detect "
            "a format from a .part suffix and exits during argument setup"
        )
        assert command[command.index("-f") + 1] == "pbf", (
            f"osmium {command[1]} names a format that is not pbf for {output}"
        )


def test_the_extract_and_the_tiles_share_the_volume_the_disk_gate_measures() -> None:
    """`tiles.check_disk_gate` is handed `TILES_DIR` and asked whether the
    *extract* will fit, which is only an honest question while `/data/tiles` and
    `/data/extracts` are on one filesystem.

    They are because every mount the rebuild service has under `/data` is
    sourced from `${DATA_ROOT}` - one host volume, however many directories of
    it are bound - and `DATA_ROOT` inside the container is `/data`, so
    `TILES_DIR` is `/data/tiles` and the extract lands at `/data/extracts` on
    that same filesystem. (Its other mounts, the config and the Lua at `/conf`,
    are read-only and nothing writes to them.)

    The service used to bind the whole volume at `/data` and now binds the five
    directories it writes, which is the same filesystem and a narrower reach -
    `${DATA_ROOT}` also holds Caddy's TLS private key, PGDATA and the nightly
    dumps. What this test is about is unchanged by that and is what the
    narrowing must not break: bind any of these from somewhere that is not
    `${DATA_ROOT}` and the gate would be measuring free space on a volume the
    1-2 GB download never touches, so the rebuild that filled the other one
    would pass the gate on its way to ENOSPC.
    """
    # Read from the *rendered* configuration rather than from the YAML, which
    # is what `tests/test_compose_render.py` exists for. Every value in
    # compose.yaml is a `${...}` string, and a mount written the way half that
    # file is - `${SOMEWHERE:-/srv/extracts}:/data/extracts` - has three colons
    # in it: splitting the short syntax on the first one reads the target as
    # `-/srv/extracts}`, which is not under /data, so the second volume this
    # test exists to forbid walked straight past it. Compose does the
    # substitution and hands back source and target as fields.
    from test_compose_render import ENV_EXAMPLE, render

    rebuild = render(ENV_EXAMPLE)["services"]["rebuild"]
    assert rebuild["environment"]["DATA_ROOT"] == "/data"

    data_root = next(
        line.split("=", 1)[1].strip().rstrip("/")
        for line in ENV_EXAMPLE.read_text().splitlines()
        if line.startswith("DATA_ROOT=")
    )
    under_data = [
        volume
        for volume in rebuild["volumes"]
        if volume["target"] == "/data" or volume["target"].startswith("/data/")
    ]
    assert under_data, "the rebuild service binds nothing under /data at all"
    foreign = [v for v in under_data if not str(v["source"]).startswith(data_root)]
    assert not foreign, (
        "the rebuild service binds something under /data from outside ${DATA_ROOT}, so the "
        f"disk gate on TILES_DIR no longer speaks for the extracts directory: {foreign}"
    )
    targets = {v["target"] for v in under_data}
    assert {"/data/tiles", "/data/extracts"} <= targets or targets == {"/data"}, (
        f"neither the whole volume nor both of the directories the gate compares: {targets}"
    )


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


# --- What the commands say ------------------------------------------------------

# The line this stage exists to make visible. osmium-tool warns when a merge of
# non-history files meets two versions of one object; the wording here is
# representative rather than quoted from a run, since nothing in this
# environment has osmium (see the module docstring) - which is why
# `source.MULTIPLE_VERSION_MARKERS` matches the condition by two fragments
# rather than by a message.
MULTIPLE_VERSIONS_WARNING = (
    "WARNING: Multiple versions of the same object found. "
    "Use --with-history to merge history files."
)


def test_the_merge_warning_that_the_files_are_not_one_snapshot_is_logged_at_warning(
    tmp_path, caplog
) -> None:
    """The module docstring's whole same-snapshot argument rests on this
    warning reaching a human being.

    Geofabrik's three state extracts are assumed to be cut from one planet
    snapshot; when they are not - a mirror days out of step, a `SOURCE_EXTRACT_URLS`
    pointed somewhere else - `osmium merge` says so and produces a small history
    file rather than a map, and `valhalla_build_admins` then reads a merged file
    carrying two versions of the objects it builds boundaries from. The runner
    captures stderr, so until this stage logged it the warning existed and
    nobody could ever see it.
    """
    run = FakeOsmium(stderr={"merge": MULTIPLE_VERSIONS_WARNING})

    with caplog.at_level(logging.INFO, logger="pipeline.source"):
        source.ensure_extract(tmp_path / "extracts", BBOX, run)

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1, (
        f"the merge's multiple-version warning is the one thing here that is a warning: "
        f"{[r.getMessage() for r in warnings]}"
    )
    message = warnings[0].getMessage()
    assert "--with-history" in message, "the line osmium wrote is quoted"
    assert "osmium merge" in message, "and the step it came from is named"


def test_a_commands_ordinary_output_is_logged_under_the_step_it_came_from(tmp_path, caplog) -> None:
    """The rest of it, at INFO: osmium's progress and summary, and whatever curl
    says under `-sS` (which is nothing unless something went wrong).

    Named per step because three commands write into one stage's log and a
    download that stalled and a clip that complained are different problems.
    `config/settings.py` puts the `pipeline` logger at INFO, so these records
    reach the console of a real rebuild.
    """
    run = FakeOsmium(
        stderr={
            "curl": "curl: (18) transfer closed with outstanding read data remaining",
            "merge": "[======] 100%",
            "extract": "Sorting objects...\n",
        }
    )

    with caplog.at_level(logging.INFO, logger="pipeline.source"):
        source.ensure_extract(tmp_path / "extracts", BBOX, run)

    info = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert any("transfer closed" in m and "downloading https://" in m for m in info)
    assert any("100%" in m and "osmium merge" in m for m in info)
    assert any("Sorting objects" in m and "osmium extract" in m for m in info)
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING], (
        "ordinary progress is not a warning, or the warning above would mean nothing"
    )


def test_a_runner_that_returns_no_streams_is_not_a_failure(caplog) -> None:
    """The stage takes whatever the injected runner returns and reads `.stderr`
    off it if there is one. A runner without one - a hand-wired one, an older
    test's - must not turn a working download into an exception."""
    with caplog.at_level(logging.INFO, logger="pipeline.source"):
        source.log_command_output("osmium merge", None)
        source.log_command_output("osmium merge", object())
    assert caplog.records == []
