"""The tile directories: dated builds, promotion, and the disk gate."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from pipeline import tiles
from pipeline.variants import Variant

REPO = Path(__file__).resolve().parents[1]
GIB = 1024**3


def test_the_build_config_retargets_every_tile_path_to_the_dated_directory(tmp_path) -> None:
    """The serving config names the graph being served, which is mounted
    read-only and is not where a build may write. The build config is the same
    file with each tile path moved under the dated directory, and nothing else
    changed."""
    path, config = tiles.build_config(
        REPO / "valhalla", tmp_path / "tiles", Variant.NO_TRAIL, "20260917T080000Z"
    )
    build = tmp_path / "tiles" / "no-trail" / "20260917T080000Z"
    assert path == build / "build-config.json"
    assert config["mjolnir"]["tile_dir"] == str(build / "tiles")
    assert config["mjolnir"]["tile_extract"] == str(build / "tiles.tar")
    assert config["mjolnir"]["admin"] == str(build / "admin.sqlite")
    assert config["mjolnir"]["timezone"] == str(build / "tz_world.sqlite")

    serving = json.loads((REPO / "valhalla" / "valhalla-no-trail.json").read_text())
    for section in serving:
        if section == "mjolnir":
            continue
        assert config[section] == serving[section], f"{section} must be untouched"
    assert config["mjolnir"]["graph_lua_name"] == serving["mjolnir"]["graph_lua_name"]


def test_a_config_whose_tile_paths_are_not_its_own_variants_is_refused(tmp_path) -> None:
    """Three configs naming one directory are three builds overwriting each
    other, and only the last variant's graph survives. The retarget refuses to
    proceed from such a config rather than building somewhere shared."""
    shared = tmp_path / "conf"
    shared.mkdir()
    config = json.loads((REPO / "valhalla" / "valhalla-ebike.json").read_text())
    config["mjolnir"]["tile_dir"] = "/data/valhalla"
    (shared / "valhalla-ebike.json").write_text(json.dumps(config))
    with pytest.raises(tiles.TilePathsNotPerVariant, match="another variant"):
        tiles.build_config(shared, tmp_path / "tiles", Variant.EBIKE, "b1")


def make_build(root: Path, variant: Variant, build_id: str) -> Path:
    build = root / variant.value / build_id
    build.mkdir(parents=True)
    (build / "tiles.tar").write_bytes(b"tar")
    return build


def test_promotion_replaces_current_atomically_and_keeps_the_previous(tmp_path) -> None:
    make_build(tmp_path, Variant.STANDARD, "b1")
    make_build(tmp_path, Variant.STANDARD, "b2")

    assert tiles.promote(tmp_path, Variant.STANDARD, "b1") is None
    assert os.readlink(tmp_path / "standard" / "current") == "b1"
    assert not (tmp_path / "standard" / "previous").exists()

    assert tiles.promote(tmp_path, Variant.STANDARD, "b2") == "b1"
    assert os.readlink(tmp_path / "standard" / "current") == "b2"
    assert os.readlink(tmp_path / "standard" / "previous") == "b1"
    assert not (tmp_path / "standard" / "current.new").exists(), "the temporary link is gone"

    assert tiles.demote(tmp_path, Variant.STANDARD) == "b1"
    assert os.readlink(tmp_path / "standard" / "current") == "b1"
    assert not (tmp_path / "standard" / "previous").exists(), (
        "after a rollback there is no build before the one served, and the settings row says so too"
    )


def test_a_build_without_an_extract_cannot_be_promoted(tmp_path) -> None:
    (tmp_path / "ebike" / "b1").mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="tiles.tar"):
        tiles.promote(tmp_path, Variant.EBIKE, "b1")


def test_the_empty_directory_docker_creates_for_a_missing_mount_is_replaced(tmp_path) -> None:
    """A bind mount of a path that does not exist yet makes Docker create an
    empty directory there, so on a first deploy `current` is a real directory.
    Promotion has to get past that; a non-empty one is not ours to remove."""
    make_build(tmp_path, Variant.STANDARD, "b1")
    (tmp_path / "standard" / "current").mkdir()
    tiles.promote(tmp_path, Variant.STANDARD, "b1")
    assert os.readlink(tmp_path / "standard" / "current") == "b1"

    make_build(tmp_path, Variant.EBIKE, "b1")
    (tmp_path / "ebike" / "current").mkdir()
    (tmp_path / "ebike" / "current" / "something").write_text("x")
    with pytest.raises(FileExistsError):
        tiles.promote(tmp_path, Variant.EBIKE, "b1")


def usage(total: int, used: int):
    return lambda path: shutil._ntuple_diskusage(total=total, used=used, free=total - used)


def test_the_gate_sizes_a_second_set_from_the_served_one(tmp_path) -> None:
    """Two full sets: the served tiles again, plus the variant extracts the
    build writes from the source and the source once more for scratch."""
    for variant in Variant:
        build = make_build(tmp_path, variant, "b1")
        (build / "tiles.tar").write_bytes(b"\0" * (3 * GIB // 1024))  # 3 MiB each
        tiles.promote(tmp_path, variant, "b1")
    served = tiles.current_set_bytes(tmp_path)
    assert served == 3 * 3 * GIB // 1024

    gate = tiles.check_disk_gate(
        tmp_path,
        source_bytes=GIB,
        minimum_free=0,
        fraction=0.8,
        disk_usage=usage(100 * GIB, 10 * GIB),
    )
    assert gate.required == served + 4 * GIB
    assert gate.fraction_after == pytest.approx((10 * GIB + served + 4 * GIB) / (100 * GIB))


def test_the_floor_applies_until_a_first_set_has_been_measured(tmp_path) -> None:
    gate = tiles.check_disk_gate(
        tmp_path,
        source_bytes=GIB,
        minimum_free=20 * GIB,
        fraction=0.8,
        disk_usage=usage(100 * GIB, 10 * GIB),
    )
    assert gate.required == 20 * GIB


def test_the_gate_is_the_eighty_percent_alert_made_hard(tmp_path) -> None:
    """Enough free space in absolute terms, but the build would take the volume
    past the alert threshold: refused, with the remedy named."""
    with pytest.raises(tiles.DiskGateRefused, match="online resize"):
        tiles.check_disk_gate(
            tmp_path,
            source_bytes=GIB,
            minimum_free=20 * GIB,
            fraction=0.8,
            disk_usage=usage(100 * GIB, 65 * GIB),
        )
    # And refused outright when the set simply does not fit.
    with pytest.raises(tiles.DiskGateRefused):
        tiles.check_disk_gate(
            tmp_path,
            source_bytes=GIB,
            minimum_free=20 * GIB,
            fraction=1.0,
            disk_usage=usage(100 * GIB, 90 * GIB),
        )
    # Passes when both hold.
    tiles.check_disk_gate(
        tmp_path,
        source_bytes=GIB,
        minimum_free=20 * GIB,
        fraction=0.8,
        disk_usage=usage(100 * GIB, 50 * GIB),
    )


def test_a_build_landing_exactly_on_the_gate_is_allowed(tmp_path) -> None:
    """The boundary itself, which the cases above stand a long way from.

    "The build may not take the volume *past* it" - so a build that would leave
    the volume at exactly the configured fraction is inside the gate and runs,
    and the comparison is `>` rather than `>=`. The difference is not academic:
    the gate is configured at the alert threshold, so the two readings that
    matter most are the one at it and the one a byte over it, and between them
    lies "the rebuild refuses to start" against "the rebuild starts and the
    alert fires when it finishes".

    Chosen so the arithmetic is exact rather than nearly so: a 100 GiB volume
    20 GiB used, and a required 60 GiB, is 80 percent after, in floating point
    as well as on paper.
    """
    at_the_gate = tiles.check_disk_gate(
        tmp_path,
        source_bytes=15 * GIB,
        minimum_free=0,
        fraction=0.8,
        disk_usage=usage(100 * GIB, 20 * GIB),
    )
    assert at_the_gate.required == 60 * GIB
    assert at_the_gate.fraction_after == 0.8, "the case is the boundary, not near it"

    # And a byte past it is past it.
    with pytest.raises(tiles.DiskGateRefused):
        tiles.check_disk_gate(
            tmp_path,
            source_bytes=15 * GIB,
            minimum_free=0,
            fraction=0.8,
            disk_usage=usage(100 * GIB, 20 * GIB + 1),
        )


def test_trace_attributes_parses_stdout_and_never_the_log_on_stderr(tmp_path) -> None:
    """`valhalla_service <config> <action> <json>` answers one request without
    starting the server, and in that mode it forces logging to stderr so that
    "the program output goes only to stdout" (src/valhalla_service.cc:42-44).
    The response is stdout; stderr is log and must not reach the parser.

    The earlier version of this test returned the log *before* the JSON on one
    combined string, which is an ordering one-shot mode cannot produce, and so
    it passed a parse that raised "Extra data" against every real build - at
    VALIDATE, the first stage that reads a build back, so nothing could ever
    have promoted.
    """
    seen = []

    def run(command):
        seen.append(list(command))
        return tiles.CommandOutput(
            json.dumps(
                {"edges": [{"weighted_grade": -4.5, "cycle_lane": "separated", "way_id": 100}]}
            ),
            # Never empty on a successful read: the extract's tile count
            # (src/baldr/graphreader.cc:110) and the two warnings about the
            # traffic extract every generated config names (:121-159).
            "2026/09/17 [INFO] Tile extract successfully loaded with tile count: 12\n"
            "2026/09/17 [WARN] Traffic tile extract could not be loaded\n",
        )

    config = tmp_path / "build-config.json"
    edge = ((-77.10, 38.93), (-77.11, 38.94))
    assert tiles.sample_grade(run, config, edge) == 4.5
    assert tiles.sample_cycle_lane(run, config, edge) == "separated"

    for command in seen:
        assert command[:3] == ["valhalla_service", str(config), "trace_attributes"]
        request = json.loads(command[3])
        assert request["shape_match"] == "map_snap"
        assert request["costing"] == "bicycle"
        assert request["shape"] == [{"lon": -77.10, "lat": 38.93}, {"lon": -77.11, "lat": 38.94}]
    assert "edge.weighted_grade" in json.loads(seen[0][3])["filters"]["attributes"]
    assert "edge.cycle_lane" in json.loads(seen[1][3])["filters"]["attributes"]


def test_a_line_after_the_response_on_stdout_does_not_break_the_parse(tmp_path) -> None:
    """The response is bounded rather than read to the end of the stream, so
    anything that did not honour the logging configuration cannot turn a good
    answer into a parse error."""

    def run(command):
        return tiles.CommandOutput(
            json.dumps({"edges": [{"weighted_grade": 7.25}]}) + "\nsomething trailing\n",
            "",
        )

    assert tiles.sample_grade(run, tmp_path / "c.json", ((0, 0), (1, 1))) == 7.25


def test_a_response_that_is_only_log_is_an_error_rather_than_an_empty_answer(tmp_path) -> None:
    """A read that answered nothing must not read as an edge with no grade,
    which is the same value a graph built without elevation reports."""

    def run(command):
        return tiles.CommandOutput("", "2026/09/17 [ERROR] failed to parse request\n")

    with pytest.raises(ValueError, match="no JSON on stdout"):
        tiles.sample_grade(run, tmp_path / "c.json", ((0, 0), (1, 1)))

    def truncated(command):
        return tiles.CommandOutput('{"edges": [{"weighted_gra', "")

    with pytest.raises(ValueError, match="not a JSON response"):
        tiles.sample_grade(truncated, tmp_path / "c.json", ((0, 0), (1, 1)))


def test_an_edge_with_no_grade_reads_as_zero_not_as_missing(tmp_path) -> None:
    """The validation compares against zero; a graph built without elevation
    reports no grade key at all, which must read as zero and fail, not as an
    exception in the sampler."""

    def run(command):
        return tiles.CommandOutput(json.dumps({"edges": [{"way_id": 100}]}), "")

    assert tiles.sample_grade(run, tmp_path / "c.json", ((0, 0), (1, 1))) == 0.0
    assert tiles.sample_cycle_lane(run, tmp_path / "c.json", ((0, 0), (1, 1))) is None


# --- The build commands ----------------------------------------------------------


def write_config(tmp_path: Path) -> tuple[Path, dict]:
    path = tiles.write_build_config(
        REPO / "valhalla", tmp_path / "tiles", Variant.STANDARD, "20260917T080000Z"
    )
    return path, json.loads(path.read_text())


def test_the_admin_and_timezone_databases_are_built_before_the_tiles(tmp_path) -> None:
    """`mjolnir.admin` and `mjolnir.timezone` are retargeted into the dated
    build directory with every other tile path, and only these commands ever
    write there. Without them 3.5.1 warns and carries on
    (src/mjolnir/graphbuilder.cc:431-444), so the graph has no timezone and
    every `date_time` request - which PLAN:82 builds the request design on -
    evaluates its conditional restrictions against nothing.
    """
    config_path, config = write_config(tmp_path)
    commands = tiles.tile_build_commands(
        config_path,
        tmp_path / "standard.osm.pbf",
        admin_pbf=tmp_path / "merged.osm.pbf",
        admin_db=Path(config["mjolnir"]["admin"]),
        timezone_db=Path(config["mjolnir"]["timezone"]),
    )
    programs = [Path(c[0]).name for c in commands]
    assert programs.index("valhalla_build_admins") < programs.index("valhalla_build_tiles")
    assert programs.index("sh") < programs.index("valhalla_build_tiles")

    # -c <config> plus the PBFs positionally: valhalla_build_admins.cc:31-37.
    # The output path is not on the command line at all - adminbuilder.cc:373
    # reads `admin` out of the config's mjolnir subtree - so the config it is
    # given has to be the retargeted one.
    admins = commands[programs.index("valhalla_build_admins")]
    assert admins == [
        "valhalla_build_admins",
        "-c",
        str(config_path),
        str(tmp_path / "merged.osm.pbf"),
    ]
    # And the *merged* extract, which is neither the variant's nor the clip.
    # Not the variant's, because a variant drops ways and a dropped boundary
    # member is a broken admin polygon; not the clip, because the clip cuts
    # boundary relations at the coverage edge, which PLAN:13 says in as many
    # words by building admin data from the merged extract before clipping.
    assert str(tmp_path / "standard.osm.pbf") not in admins


def test_the_admin_database_is_built_once_and_copied(tmp_path) -> None:
    """Three variants used to mean three `valhalla_build_admins` runs, and all
    three were the same run: the command's only inputs are `-c <config>` and the
    merged PBF, the merged PBF is one file for the whole rebuild (it is read
    *because* admin polygons are a fact about the region rather than about which
    ways a variant keeps), and the configs differ only in which `mjolnir.admin`
    path they name. So the pipeline parsed 1-2 GB of OSM and rebuilt the same
    boundary polygons three times to write three identical databases, inside a
    rebuild that is killed at six hours.

    The same shape the timezone database already had: the first variant builds
    it, the rest copy the file.
    """
    config_path, config = write_config(tmp_path)
    first = tmp_path / "standard" / "admin.sqlite"
    commands = tiles.tile_build_commands(
        config_path,
        tmp_path / "ebike.osm.pbf",
        admin_pbf=tmp_path / "merged.osm.pbf",
        admin_db=Path(config["mjolnir"]["admin"]),
        timezone_db=Path(config["mjolnir"]["timezone"]),
        admin_source=first,
        timezone_source=tmp_path / "standard-tz.sqlite",
    )

    assert not any(Path(c[0]).name == "valhalla_build_admins" for c in commands), (
        "the merged extract is parsed again for a database the first variant already wrote"
    )
    assert ["cp", str(first), config["mjolnir"]["admin"]] in commands
    # And the copy still lands before the tiles that read it.
    programs = [Path(c[0]).name for c in commands]
    copy_index = commands.index(["cp", str(first), config["mjolnir"]["admin"]])
    assert copy_index < programs.index("valhalla_build_tiles")


def test_the_timezone_script_writes_to_stdout_so_the_pipeline_redirects_it(tmp_path) -> None:
    """valhalla_build_timezones takes no arguments and `cat`s the finished
    SQLite database to stdout (scripts/valhalla_build_timezones:38), so the
    redirect is the only thing that names its output. It also `rm -rf dist` and
    unzips into the working directory (:21-22, :28), so it is given one of its
    own.

    Run for real against a stub on PATH, because the thing that can be wrong
    here is the shell, not the pipeline: a quoting or ordering mistake would
    leave the database somewhere else and be invisible to a fake that only
    matched on the program name.
    """
    config_path, config = write_config(tmp_path)
    timezone_db = Path(config["mjolnir"]["timezone"])
    commands = tiles.tile_build_commands(
        config_path,
        tmp_path / "standard.osm.pbf",
        admin_pbf=tmp_path / "source.osm.pbf",
        admin_db=Path(config["mjolnir"]["admin"]),
        timezone_db=timezone_db,
    )
    shell = next(c for c in commands if c[0] == "sh")

    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    stub = stub_dir / "valhalla_build_timezones"
    stub.write_text(
        "#!/bin/sh\n"
        'echo "downloading timezone polygon file." 1>&2\n'
        "touch ./dist-marker\n"
        "printf 'SQLite format 3'\n"
    )
    stub.chmod(0o755)

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    subprocess.run(
        shell,
        check=True,
        cwd=elsewhere,
        env={**os.environ, "PATH": f"{stub_dir}:{os.environ['PATH']}"},
    )

    assert timezone_db.read_bytes() == b"SQLite format 3"
    assert not (timezone_db.parent / f"{timezone_db.name}.part").exists(), "moved, not left behind"
    assert (timezone_db.parent / "dist-marker").exists(), "the script ran in the build directory"
    assert not (elsewhere / "dist-marker").exists(), "and not in the rebuild's own directory"


def test_a_failed_timezone_build_leaves_no_database_behind(tmp_path) -> None:
    """`>` truncates before the script runs, so a redirect straight onto the
    configured path would leave an empty file exactly where the build config
    says the database is - which 3.5.1 opens, finds unusable, and carries on
    from."""
    config_path, config = write_config(tmp_path)
    timezone_db = Path(config["mjolnir"]["timezone"])
    timezone_db.write_bytes(b"")
    timezone_db.unlink()
    shell = next(
        c
        for c in tiles.tile_build_commands(
            config_path,
            tmp_path / "standard.osm.pbf",
            admin_pbf=tmp_path / "source.osm.pbf",
            admin_db=Path(config["mjolnir"]["admin"]),
            timezone_db=timezone_db,
        )
        if c[0] == "sh"
    )

    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    stub = stub_dir / "valhalla_build_timezones"
    stub.write_text("#!/bin/sh\necho 'error: curl failed' 1>&2\nexit 1\n")
    stub.chmod(0o755)

    result = subprocess.run(
        shell, cwd=tmp_path, env={**os.environ, "PATH": f"{stub_dir}:{os.environ['PATH']}"}
    )
    assert result.returncode != 0, "the rebuild has to see this fail"
    assert not timezone_db.exists()


def test_the_timezone_database_is_downloaded_once_and_copied(tmp_path) -> None:
    """It is a function of the world rather than of the extract, and building it
    downloads about a hundred megabytes, so the second and third variants of a
    rebuild copy the first's rather than fetching it twice more."""
    config_path, config = write_config(tmp_path)
    commands = tiles.tile_build_commands(
        config_path,
        tmp_path / "ebike.osm.pbf",
        admin_pbf=tmp_path / "source.osm.pbf",
        admin_db=Path(config["mjolnir"]["admin"]),
        timezone_db=Path(config["mjolnir"]["timezone"]),
        timezone_source=tmp_path / "standard-tz.sqlite",
    )
    assert not any(c[0] == "sh" for c in commands), "nothing is downloaded a second time"
    assert ["cp", str(tmp_path / "standard-tz.sqlite"), config["mjolnir"]["timezone"]] in commands


def test_the_links_a_promotion_found_are_what_restoring_puts_back(tmp_path) -> None:
    """The undo of a promotion, which is not the same thing as a demotion.

    `demote` puts `previous` back as `current`, and before a second rebuild has
    ever run there is no `previous` at all - so undoing a first-ever promotion
    that way did nothing and left `current` pointing at a build the rest of the
    swap never completed. Restoring takes the links as they were found, and
    "there was no link" is one of the states it has to be able to put back.
    """
    make_build(tmp_path, Variant.STANDARD, "b1")
    make_build(tmp_path, Variant.STANDARD, "b2")

    fresh = tiles.links(tmp_path, Variant.STANDARD)
    assert (fresh.current, fresh.previous) == (None, None)

    tiles.promote(tmp_path, Variant.STANDARD, "b1")
    tiles.restore_links(tmp_path, Variant.STANDARD, fresh)
    assert not (tmp_path / "standard" / "current").exists(), "nothing is served again"
    assert not (tmp_path / "standard" / "previous").exists()

    tiles.promote(tmp_path, Variant.STANDARD, "b1")
    one_build = tiles.links(tmp_path, Variant.STANDARD)
    assert (one_build.current, one_build.previous) == ("b1", None)

    tiles.promote(tmp_path, Variant.STANDARD, "b2")
    tiles.restore_links(tmp_path, Variant.STANDARD, one_build)
    assert os.readlink(tmp_path / "standard" / "current") == "b1"
    assert not (tmp_path / "standard" / "previous").exists(), "b1 was never anyone's previous"


def test_a_build_refuses_to_write_into_a_build_directory_that_exists(tmp_path) -> None:
    """Build ids are second-resolution. Two fires inside one second took the
    same id, and the second build wrote its tiles into the directory the first
    had already promoted - the graph being served - leaving `current` and
    `previous` pointing at the same directory. The second build refuses instead,
    before it has written anything.
    """
    written = tiles.write_build_config(REPO / "valhalla", tmp_path, Variant.EBIKE, "b1")
    assert written.is_file()

    with pytest.raises(tiles.BuildDirectoryExists, match="b1"):
        tiles.write_build_config(REPO / "valhalla", tmp_path, Variant.EBIKE, "b1")

    # A different variant of the same build is a different directory, and a
    # different build id on the same variant is fine.
    tiles.write_build_config(REPO / "valhalla", tmp_path, Variant.STANDARD, "b1")
    tiles.write_build_config(REPO / "valhalla", tmp_path, Variant.EBIKE, "b2")


def test_the_tail_of_a_run_quotes_the_end_of_both_streams_and_says_which() -> None:
    """What a failed command's report is built from.

    Both streams, because which one carries the diagnosis is the command's
    business: osmium and curl write theirs to stderr, while a Valhalla binary
    under `mjolnir.logging.type: std_out` puts its last words on stdout. The
    end of each, because these are unbounded - a six-hour tile build, a
    retried 1-2 GB transfer - and the reason a command stopped is the last
    thing it wrote. And an empty stream says so, rather than leaving a blank
    the reader has to interpret as "nothing" or as "this was dropped".
    """
    output = tiles.CommandOutput(stdout="", stderr="\n".join(f"line {n}" for n in range(1, 51)))

    tail = output.tail(3)

    assert "line 50" in tail and "line 48" in tail, "the end of the stream"
    assert "line 47" not in tail, "and no more of it than was asked for"
    assert "the last 3 lines of stderr" in tail and "the last 3 lines of stdout" in tail
    assert tail.index("stderr") < tail.index("stdout"), "the diagnosing stream first"
    assert "(nothing)" in tail, "an empty stream is said rather than left blank"
