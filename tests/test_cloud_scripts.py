"""scripts/cloud/: the cloud rebuild's three scripts, against fake aws, docker, sudo and git.

Nothing here reaches AWS or Docker. The fake `aws` maps s3://bucket/... onto a local
directory, the fake `docker` answers the handful of compose commands and SQL the scripts
send and records every call, and the fake `sudo` runs its command without privilege
(prepare_data_root.sh becomes a mkdir). What is asserted is the order of the steps, what
is refused, and what reaches the bucket: the commands themselves are each the documented
one (OPERATIONS.md, "Restoring one", "Firing a rebuild by hand").
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SEND = REPO / "scripts" / "cloud" / "send-inputs.sh"
BOX = REPO / "scripts" / "cloud" / "box-rebuild.sh"
IMPORT = REPO / "scripts" / "cloud" / "import-result.sh"
BUILD = "20261011T093012Z"
COMMIT = "a" * 40
VARIANTS = ("standard", "no-trail", "ebike", "weekend", "offroad")

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")

FAKE_AWS = r"""#!/usr/bin/env bash
printf 'aws %s\n' "$*" >>"$FAKE_DIR/calls.log"
[ "$1" = --profile ] && shift 2
map() { case "$1" in s3://*) echo "$FAKE_S3/${1#s3://}" ;; *) echo "$1" ;; esac; }
[ "$1" = s3 ] || exit 1
# A box that has powered off sends nothing more.
[ -e "$FAKE_DIR/powered_off" ] && exit 1
case "$2" in
  rm) if [ "$4" = --recursive ]; then rm -rf "$(map "$3")"; else rm -f "$(map "$3")"; fi ;;
  sync)
    src=$(map "$3"); dst=$(map "$4")
    [ -d "$src" ] || exit 0
    mkdir -p "$dst"; cp "$src"/* "$dst/" ;;
  cp)
    src=$(map "$3"); dst=$(map "$4"); shift 4
    recursive=0 exclude=""
    while [ $# -gt 0 ]; do
      case "$1" in --recursive) recursive=1 ;; --exclude) exclude=$2; shift ;; esac; shift
    done
    if [ "$recursive" = 1 ]; then
      [ -d "$src" ] || exit 1
      [ -e "$FAKE_DIR/cp_fails" ] && exit 1
      mkdir -p "$dst"
      for f in "$src"/*; do
        [ -f "$f" ] || continue
        [ -n "$exclude" ] && [ "$(basename "$f")" = "$exclude" ] && continue
        cp "$f" "$dst/"
        echo "${dst#"$FAKE_S3"/}$(basename "$f")" >>"$FAKE_DIR/s3-order.log"
      done
    else
      [ -f "$src" ] || exit 1
      mkdir -p "$(dirname "$dst")"; cp "$src" "$dst"
      echo "${dst#"$FAKE_S3"/}" >>"$FAKE_DIR/s3-order.log"
    fi ;;
esac
"""

FAKE_DOCKER = r"""#!/usr/bin/env bash
printf 'docker %s\n' "$*" >>"$FAKE_DIR/calls.log"
[ "$1" = compose ] || exit 0
shift
[ "$1" = --profile ] && shift 2
case "$1" in
  ps) cat "$FAKE_DIR/offroad_running" 2>/dev/null; exit 0 ;;
  logs) echo "rebuild | stage tiles"; exit 0 ;;
  exec)
    # Under nohup there is no terminal, and docker refuses an exec without -T.
    shift; [ "$1" = -T ] || exit 1; shift
    service=$1; shift
    all="$*"
    case "$all" in
      *"SELECT status FROM procrastinate_jobs"*)
        if [ -s "$FAKE_DIR/job_status" ]; then
          head -n1 "$FAKE_DIR/job_status"
          [ "$(wc -l <"$FAKE_DIR/job_status")" -gt 1 ] && sed -i 1d "$FAKE_DIR/job_status"
        fi ;;
      *"count(DISTINCT build_id)"*) cat "$FAKE_DIR/builds" 2>/dev/null || echo "1 BUILD" ;;
      *"to_regnamespace('live') IS NOT NULL"*) echo t ;;
      *"to_regclass('staging.segment')"*) echo t ;;
      *"to_regnamespace('staging') IS NULL"*)
        cat "$FAKE_DIR/staging_absent" 2>/dev/null || echo t ;;
      *"string_agg"*) cat "$FAKE_DIR/in_flight" 2>/dev/null ;;
      *run_rebuild_now*)
        [ -e "$FAKE_DIR/rebuild_now_fails" ] && { echo "already in flight" >&2; exit 1; }
        echo "queued weekly_rebuild as job 7 on the rebuild queue. The rebuild service runs it." ;;
      *unwedge_job*) echo "requeued" ;;
      *pg_restore*) cat >/dev/null; exit "$(cat "$FAKE_DIR/restore_rc" 2>/dev/null || echo 0)" ;;
      *pg_dump*) echo "DUMP of $all" ;;
      *import_cloud_build*) echo "import_cloud_build $all" ;;
    esac ;;
esac
exit 0
""".replace("BUILD", BUILD)

FAKE_SUDO = r"""#!/usr/bin/env bash
printf 'sudo %s\n' "$*" >>"$FAKE_DIR/calls.log"
case "$*" in
  *prepare_data_root.sh*)
    root=$(sed -n 's/^DATA_ROOT=//p' .env | tail -n1)
    mkdir -p "$root/tiles" "$root/postgres" "$root/rebuild" ;;
  poweroff*) touch "$FAKE_DIR/powered_off" ;;
  *) "$@" ;;
esac
"""

FAKE_GIT = r"""#!/usr/bin/env bash
printf 'git %s\n' "$*" >>"$FAKE_DIR/calls.log"
case "$*" in
  clone*) dir="${@: -1}"; mkdir -p "$dir/.git" "$dir/scripts"
          cp "$REPO/.env.example" "$dir/.env.example" ;;
  *rev-parse*) cat "$FAKE_DIR/head" 2>/dev/null || echo COMMIT ;;
  *status*) cat "$FAKE_DIR/dirty" 2>/dev/null ;;
  *"branch -r --contains"*) cat "$FAKE_DIR/remote" 2>/dev/null || echo "  origin/main" ;;
esac
exit 0
""".replace("COMMIT", COMMIT)


@pytest.fixture
def fake(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (
        ("aws", FAKE_AWS),
        ("docker", FAKE_DOCKER),
        ("sudo", FAKE_SUDO),
        ("git", FAKE_GIT),
    ):
        path = bin_dir / name
        path.write_text(body)
        path.chmod(0o755)
    state = tmp_path / "fake"
    state.mkdir()
    s3 = tmp_path / "s3"
    s3.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    env = {
        **os.environ,
        "HOME": str(home),
        "FAKE_DIR": str(state),
        "FAKE_S3": str(s3),
        "REPO": str(REPO),
        "CLOUD_AWS": str(bin_dir / "aws"),
        "CLOUD_DOCKER": str(bin_dir / "docker"),
        "CLOUD_SUDO": str(bin_dir / "sudo"),
        "CLOUD_GIT": str(bin_dir / "git"),
        "CLOUD_POLL_S": "0",
        "CLOUD_DEADLINE_S": "",
        "CLOUD_POWEROFF": f"{bin_dir / 'sudo'} poweroff",
        "AWS_DEFAULT_REGION": "us-west-2",
    }

    class Fake:
        root = tmp_path
        dir = state
        bucket = s3
        url = "s3://bucket/rebuild-checkpoints/transfer/cloud-20261011"

        def run(self, script: Path, *args: str, cwd: Path | None = None, **more: str):
            return subprocess.run(
                ["bash", str(script), *args],
                env={**env, **more},
                cwd=cwd or tmp_path,
                capture_output=True,
                text=True,
                timeout=60,
            )

        def calls(self) -> str:
            log = state / "calls.log"
            return log.read_text() if log.exists() else ""

        def in_bucket(self, part: str) -> Path:
            return s3 / "bucket/rebuild-checkpoints/transfer/cloud-20261011" / part

    return Fake()


@pytest.fixture
def home(fake):
    """A live checkout (its .env) and a DATA_ROOT with two backups and the three inputs."""
    live = fake.root / "live"
    live.mkdir()
    data = fake.root / "data"
    (live / ".env").write_text(f"TAG=dev\nDATA_ROOT={data}\nPGUSER=routemaker\n")
    (data / "backups").mkdir(parents=True)
    (data / "backups" / "routemaker-20261010T070000Z.dump").write_text("older")
    (data / "backups" / "routemaker-20261011T070000Z.dump").write_text("newest")
    for part in ("reference", "elevation", "extracts"):
        (data / part).mkdir()
        (data / part / f"{part}.file").write_text(part)
    return live, data


def send(fake, home, *extra: str):
    live, _ = home
    return fake.run(SEND, "--live-dir", str(live), *extra, fake.url)


# --- send-inputs.sh ------------------------------------------------------------------


def test_send_uploads_the_newest_backup_and_the_three_inputs_checksums_last(fake, home) -> None:
    done = send(fake, home)
    assert done.returncode == 0, done.stderr

    sent = fake.in_bucket("in")
    names = sorted(p.name for p in sent.iterdir())
    assert names == [
        "MANIFEST.txt",
        "SHA256SUMS",
        "elevation.tar",
        "extracts.tar",
        "reference.tar",
        "routemaker-20261011T070000Z.dump",
    ]
    manifest = (sent / "MANIFEST.txt").read_text()
    assert f"commit={COMMIT}" in manifest
    assert "read_at=20261011T070000Z" in manifest
    order = (fake.dir / "s3-order.log").read_text().splitlines()
    assert order[-1].endswith("in/SHA256SUMS"), "the checksums go last"
    assert sum(line.endswith("SHA256SUMS") for line in order) == 1, "and only last"
    check = subprocess.run(["sha256sum", "-c", "SHA256SUMS"], cwd=sent, capture_output=True)
    assert check.returncode == 0


def test_send_clears_an_earlier_send_so_a_stopped_upload_leaves_no_checksums(fake, home) -> None:
    sent = fake.in_bucket("in")
    sent.mkdir(parents=True)
    (sent / "SHA256SUMS").write_text("from an earlier send")
    (sent / "routemaker-20261001T070000Z.dump").write_text("an earlier backup")
    (fake.dir / "cp_fails").touch()

    done = send(fake, home)

    assert done.returncode != 0
    assert not sent.exists() or not list(sent.iterdir()), "nothing the box would build from"


def test_send_refuses_a_commit_that_is_not_pushed(fake, home) -> None:
    (fake.dir / "remote").write_text("")

    done = send(fake, home)

    assert done.returncode == 2 and "push it first" in done.stderr
    assert not fake.in_bucket("in").exists()


@pytest.mark.parametrize(
    "key", ["COVERAGE_POLYGON", "ROUTEMAKER_LIVE_SCHEMA", "ROUTEMAKER_STAGING_SCHEMA"]
)
def test_send_refuses_a_deployment_the_box_would_build_differently(fake, home, key) -> None:
    live, _ = home
    with (live / ".env").open("a") as env:
        env.write(f"{key}=custom-value\n")

    done = send(fake, home)

    assert done.returncode == 2 and key in done.stderr
    assert "custom-value" not in done.stdout + done.stderr, "only whether it is set is read"


def test_send_refuses_a_checkout_with_uncommitted_changes(fake, home) -> None:
    (fake.dir / "dirty").write_text(" M src/pipeline/run.py\n")

    done = send(fake, home)

    assert done.returncode == 2
    assert "uncommitted changes" in done.stderr
    assert not fake.in_bucket("in").exists()


def test_send_refuses_when_there_is_no_backup(fake, home) -> None:
    _, data = home
    for dump in (data / "backups").iterdir():
        dump.unlink()

    done = send(fake, home)

    assert done.returncode == 2 and "no backup" in done.stderr


def test_send_refuses_a_stage_inside_data_root(fake, home) -> None:
    _, data = home
    done = send(fake, home, "--stage", str(data / "stage"))

    assert done.returncode == 2 and "inside DATA_ROOT" in done.stderr
    assert not (data / "stage").exists(), "refused before anything is written there"


@pytest.mark.parametrize(
    "url", ["s3://bucket", "https://bucket/x", "s3://bucket/transfer/Cloud_Run", "/tmp/x"]
)
def test_send_refuses_a_run_url_it_cannot_name_a_run_from(fake, home, url) -> None:
    live, _ = home
    done = fake.run(SEND, "--live-dir", str(live), url)

    assert done.returncode == 2


# --- box-rebuild.sh -------------------------------------------------------------------


def box(fake, *extra: str):
    data = fake.root / "box" / "data"
    return fake.run(
        BOX,
        "--build-dir",
        str(fake.root / "box" / "build"),
        "--data-root",
        str(data),
        *extra,
        fake.url,
    ), data


def built_tiles(data: Path) -> None:
    for variant in VARIANTS:
        build = data / "tiles" / variant / BUILD
        build.mkdir(parents=True, exist_ok=True)
        (build / "tiles.tar").write_text(variant)


def test_the_box_runs_restore_rebuild_export_upload_and_powers_off(fake, home) -> None:
    assert send(fake, home).returncode == 0
    (fake.dir / "job_status").write_text("todo\ndoing\nsucceeded\n")
    built_tiles(fake.root / "box" / "data")

    done, data = box(fake)

    assert done.returncode == 0, done.stdout + done.stderr
    calls = fake.calls()
    order = [
        "compose build api rebuild",
        "compose down",
        "compose up -d --wait postgis",
        "dropdb",
        "createdb -U routemaker -T template0",
        "pg_restore --no-owner",
        "SET status = 'cancelled' WHERE status IN ('todo', 'doing')",
        "compose up -d rebuild",
        "run_rebuild_now --fresh",
        "ALTER SCHEMA live RENAME TO staging",
        "pg_dump -U routemaker -d routemaker -Fc -n staging",
        "out/SHA256SUMS",
        "sudo poweroff",
    ]
    positions = [calls.index(step) for step in order]
    assert positions == sorted(positions), f"steps out of order:\n{calls}"

    out = fake.in_bucket("out")
    names = {p.name for p in out.iterdir()}
    assert {f"tiles-{v}.tar" for v in VARIANTS} <= names
    assert {"staging.dump", "MANIFEST.txt", "SHA256SUMS"} <= names
    manifest = (out / "MANIFEST.txt").read_text()
    assert f"build={BUILD}" in manifest and "read_at=20261011T070000Z" in manifest
    upload = [
        line for line in (fake.dir / "s3-order.log").read_text().splitlines() if "/out/" in line
    ]
    assert upload[-1].endswith("out/SHA256SUMS")
    assert subprocess.run(["sha256sum", "-c", "SHA256SUMS"], cwd=out).returncode == 0

    env = (fake.root / "box" / "build" / ".env").read_text()
    assert "change-me" not in "".join(
        line
        for line in env.splitlines()
        if line.startswith(
            ("PGPASSWORD", "DJANGO_SECRET_KEY", "KEY_ENCRYPTION_KEY", "BOT_INTERNAL_SECRET")
        )
    ), "the box gets its own secrets"
    assert "WEEKLY_REBUILD_PAUSED=1" in env and f"DATA_ROOT={data}" in env
    override = (fake.root / "box" / "build" / "compose.override.yaml").read_text()
    assert "memory: 26G" in override


def test_a_failed_rebuild_saves_its_log_uploads_nothing_and_powers_off(fake, home) -> None:
    assert send(fake, home).returncode == 0
    (fake.dir / "job_status").write_text("doing\nfailed\n")

    done, _ = box(fake)

    assert done.returncode == 1
    assert "ended failed" in done.stdout
    assert "sudo poweroff" in fake.calls()
    assert not fake.in_bucket("out").exists()
    assert list((fake.root / "home" / "cloud-runs" / "cloud-20261011").glob("rebuild-*.log.gz"))


def test_after_a_reclaim_it_carries_on_and_unwedges_the_job_the_dead_worker_held(
    fake, home
) -> None:
    assert send(fake, home).returncode == 0
    (fake.dir / "job_status").write_text("doing\nfailed\n")
    box(fake, "--no-stop")
    assert "poweroff" not in fake.calls(), "--no-stop keeps the box up"
    (fake.dir / "calls.log").unlink()

    # The box came back: the state says fired, and the job is `doing` with no worker.
    state = fake.root / "home" / "cloud-runs" / "cloud-20261011" / "state"
    (state / "wait.done").unlink(missing_ok=True)
    (fake.dir / "job_status").write_text("doing\ndoing\nsucceeded\n")
    built_tiles(fake.root / "box" / "data")
    done, _ = box(fake)

    assert done.returncode == 0, done.stdout + done.stderr
    calls = fake.calls()
    assert "pg_restore" not in calls and "compose build" not in calls, "done steps are skipped"
    assert "run_rebuild_now" not in calls, "the same job, not a second rebuild"
    assert "unwedge_job 7" in calls


def test_the_box_refuses_a_folder_whose_upload_did_not_finish(fake, home) -> None:
    assert send(fake, home).returncode == 0
    (fake.in_bucket("in") / "SHA256SUMS").unlink()

    done, _ = box(fake)

    assert done.returncode == 2 and "no SHA256SUMS" in done.stderr
    assert "poweroff" not in fake.calls(), "a failure before the rebuild leaves the box up"


def test_the_box_refuses_a_file_that_does_not_match_its_checksum(fake, home) -> None:
    assert send(fake, home).returncode == 0
    (fake.in_bucket("in") / "reference.tar").write_text("tampered")

    done, _ = box(fake)

    assert done.returncode == 2 and "does not match" in done.stderr


def test_a_swap_that_did_not_finish_on_the_box_is_not_exported(fake, home) -> None:
    assert send(fake, home).returncode == 0
    (fake.dir / "job_status").write_text("succeeded\n")
    (fake.dir / "builds").write_text(f"2 {BUILD}\n")

    done, _ = box(fake)

    assert done.returncode == 2 and "more than one build" in done.stderr
    assert not fake.in_bucket("out").exists()
    assert "sudo poweroff" in fake.calls(), "after the rebuild is fired, any failure powers off"


def test_a_job_that_never_finishes_is_given_up_on_and_the_box_powers_off(fake, home) -> None:
    assert send(fake, home).returncode == 0
    (fake.dir / "job_status").write_text("doing\n")

    done, _ = (
        fake.run(
            BOX,
            "--build-dir",
            str(fake.root / "box" / "build"),
            "--data-root",
            str(fake.root / "box" / "data"),
            fake.url,
            CLOUD_DEADLINE_S="1",
        ),
        None,
    )

    assert done.returncode == 1 and "giving up" in done.stdout
    assert "sudo poweroff" in fake.calls()
    assert not fake.in_bucket("out").exists()


def test_refire_fires_a_new_job_after_a_failed_one(fake, home) -> None:
    assert send(fake, home).returncode == 0
    (fake.dir / "job_status").write_text("failed\n")
    box(fake, "--no-stop")
    (fake.dir / "calls.log").unlink()
    (fake.dir / "job_status").write_text("succeeded\n")
    built_tiles(fake.root / "box" / "data")

    done, _ = box(fake, "--refire")

    assert done.returncode == 0, done.stdout + done.stderr
    calls = fake.calls()
    assert "run_rebuild_now --fresh" in calls and "pg_restore" not in calls


def test_a_refused_fire_leaves_the_box_up(fake, home) -> None:
    assert send(fake, home).returncode == 0
    (fake.dir / "rebuild_now_fails").touch()

    done, _ = box(fake)

    assert done.returncode != 0
    assert "poweroff" not in fake.calls(), "nothing was fired, so somebody is still watching"


# --- import-result.sh -----------------------------------------------------------------


@pytest.fixture
def result(fake, home):
    """The box's out/ folder in the bucket, as box-rebuild.sh leaves it."""
    out = fake.in_bucket("out")
    out.mkdir(parents=True)
    work = fake.root / "boxtiles"
    for variant in VARIANTS:
        (work / variant / BUILD).mkdir(parents=True)
        (work / variant / BUILD / "tiles.tar").write_text(variant)
        subprocess.run(
            [
                "tar",
                "-C",
                str(work),
                "-cf",
                str(out / f"tiles-{variant}.tar"),
                f"{variant}/{BUILD}",
            ],
            check=True,
        )
    (out / "staging.dump").write_text("dump")
    (out / "MANIFEST.txt").write_text(
        f"run=cloud-20261011\ncommit={COMMIT}\nbuild={BUILD}\nread_at=20261011T070000Z\n"
    )
    subprocess.run(
        "sha256sum -- MANIFEST.txt staging.dump tiles-*.tar > SHA256SUMS",
        shell=True,
        cwd=out,
        check=True,
    )
    _, data = home
    (data / "tiles").mkdir()
    return home


def importing(fake, home, *extra: str):
    live, _ = home
    return fake.run(IMPORT, "--live-dir", str(live), *extra, fake.url)


def test_the_import_installs_restores_and_dry_runs_without_swapping(fake, result) -> None:
    done = importing(fake, result)

    assert done.returncode == 0, done.stdout + done.stderr
    _, data = result
    for variant in VARIANTS:
        assert (data / "tiles" / variant / BUILD / "tiles.tar").is_file()
    calls = fake.calls()
    assert "pg_dump -U routemaker -d routemaker -Fc" in calls, "the safety dump"
    assert "pg_restore --no-owner" in calls
    assert f"import_cloud_build {BUILD} --overrides-read-at 20261011T070000Z" in calls
    assert "--confirm" not in calls and "restart" not in calls


def test_the_swap_confirms_restarts_the_routers_and_predraws(fake, result) -> None:
    assert importing(fake, result).returncode == 0
    (fake.dir / "calls.log").unlink()

    done = importing(fake, result, "--swap")

    assert done.returncode == 0, done.stderr
    calls = fake.calls()
    assert f"import_cloud_build {BUILD} --overrides-read-at 20261011T070000Z --confirm" in calls
    assert "restart valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend" in calls
    assert "--profile offroad restart" not in calls, "no off-road router runs here"
    assert "predraw_stress_tiles" in calls
    assert calls.index("--confirm") < calls.index("restart") < calls.index("predraw")


def assert_nothing_installed(fake, data: Path) -> None:
    calls = fake.calls()
    assert "pg_dump" not in calls and "pg_restore" not in calls and "sudo tar" not in calls
    assert not list((data / "tiles").glob(f"*/{BUILD}"))


def test_the_import_refuses_a_build_from_another_commit(fake, result) -> None:
    (fake.dir / "head").write_text("b" * 40 + "\n")

    done = importing(fake, result)

    assert done.returncode == 2 and "deploy that commit first" in done.stderr
    assert_nothing_installed(fake, result[1])


def test_the_import_refuses_while_a_rebuild_is_in_flight(fake, result) -> None:
    (fake.dir / "in_flight").write_text("12 doing\n")

    done = importing(fake, result)

    assert done.returncode == 2 and "12 doing" in done.stderr
    assert_nothing_installed(fake, result[1])


def test_the_import_refuses_when_a_staging_schema_is_waiting(fake, result) -> None:
    (fake.dir / "staging_absent").write_text("f\n")

    done = importing(fake, result)

    assert done.returncode == 2 and "staging schema already exists" in done.stderr
    assert_nothing_installed(fake, result[1])


def test_the_import_refuses_a_build_a_link_already_names(fake, result) -> None:
    _, data = result
    (data / "tiles" / "ebike" / BUILD).mkdir(parents=True)
    (data / "tiles" / "ebike" / "previous").symlink_to(BUILD)

    done = importing(fake, result)

    assert done.returncode == 2 and "previous link already names" in done.stderr
    assert "pg_restore" not in fake.calls()


def test_an_unpack_that_stopped_is_unpacked_again(fake, result) -> None:
    _, data = result
    leftover = data / "tiles" / "ebike" / BUILD
    leftover.mkdir(parents=True)
    (leftover / "half.tar.part").write_text("stopped here")

    done = importing(fake, result)

    assert done.returncode == 0, done.stdout + done.stderr
    assert sorted(p.name for p in leftover.iterdir()) == ["tiles.tar"]


def test_a_second_run_after_an_install_goes_straight_to_the_dry_run(fake, result) -> None:
    assert importing(fake, result).returncode == 0
    (fake.dir / "calls.log").unlink()
    (fake.dir / "staging_absent").write_text("f\n")

    live, _ = result
    done = fake.run(IMPORT, "--live-dir", str(live), fake.url, "--", "--accept-later-overrides")

    assert done.returncode == 0, done.stdout + done.stderr
    calls = fake.calls()
    assert "pg_restore" not in calls and "pg_dump" not in calls and "sudo tar" not in calls
    assert f"import_cloud_build {BUILD} --overrides-read-at 20261011T070000Z " in calls
    assert "--accept-later-overrides" in calls and "--confirm" not in calls


def test_the_swap_refuses_when_nothing_was_installed(fake, result) -> None:
    done = importing(fake, result, "--swap")

    assert done.returncode == 2 and "without --swap first" in done.stderr
    assert "import_cloud_build" not in fake.calls()


def test_the_swap_restarts_the_off_road_router_where_it_runs(fake, result) -> None:
    assert importing(fake, result).returncode == 0
    (fake.dir / "offroad_running").write_text("abc123\n")

    done = importing(fake, result, "--swap")

    assert done.returncode == 0, done.stderr
    assert "compose --profile offroad ps -q valhalla-offroad" in fake.calls()
    assert "compose --profile offroad restart valhalla-offroad" in fake.calls()


def test_the_safety_dump_leaves_out_what_the_nightly_backup_leaves_out(fake, result) -> None:
    import re

    source = (REPO / "src" / "config" / "procrastinate.py").read_text()
    block = re.search(r"BACKUP_EXCLUDED_TABLES = \((.*?)\)", source, re.S)
    excluded = re.findall(r'"(\w+)"', block.group(1))
    assert excluded

    assert importing(fake, result).returncode == 0

    dump = next(line for line in fake.calls().splitlines() if "pg_dump" in line)
    assert sorted(re.findall(r"--exclude-table-data=\*\.(\w+)", dump)) == sorted(excluded)


def test_the_import_refuses_a_stage_inside_the_checkout(fake, result) -> None:
    live, _ = result

    done = importing(fake, result, "--stage", str(live / "stage"))

    assert done.returncode == 2 and "inside DATA_ROOT or the checkout" in done.stderr
    assert not (live / "stage").exists()


@pytest.mark.parametrize("script", [SEND, BOX, IMPORT], ids=lambda p: p.name)
def test_each_script_parses_and_shellcheck_is_clean_when_available(script: Path) -> None:
    assert subprocess.run(["bash", "-n", str(script)]).returncode == 0
    if shutil.which("shellcheck"):
        done = subprocess.run(
            ["shellcheck", "--severity=warning", str(script)], capture_output=True, text=True
        )
        assert done.returncode == 0, done.stdout
