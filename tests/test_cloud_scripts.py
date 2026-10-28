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
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SEND = REPO / "scripts" / "cloud" / "send-inputs.sh"
BOX = REPO / "scripts" / "cloud" / "box-rebuild.sh"
IMPORT = REPO / "scripts" / "cloud" / "import-result.sh"
BUILD = "20261011T093012Z"
COMMIT = "a" * 40
VARIANTS = ("standard", "no-trail", "ebike", "weekend", "offroad", "mtb")

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")

FAKE_AWS = r"""#!/usr/bin/env bash
printf 'aws %s\n' "$*" >>"$FAKE_DIR/calls.log"
[ "$1" = --profile ] && shift 2
map() { case "$1" in s3://*) echo "$FAKE_S3/${1#s3://}" ;; *) echo "$1" ;; esac; }
[ "$1" = s3 ] || exit 1
# A box that has powered off sends nothing more.
[ -e "$FAKE_DIR/powered_off" ] && exit 1
case "$2" in
  ls)
    target=$(map "$3")
    case "$3" in
      */) [ -d "$target" ] || exit 1
          for entry in "$target"*; do
            [ -e "$entry" ] || continue
            if [ -d "$entry" ]; then echo "                           PRE ${entry##*/}/"
            else echo "2026-10-11 07:00:00          5 ${entry##*/}"; fi
          done ;;
      *) [ -e "$target" ] ;;
    esac ;;
  rm) if [ "$4" = --recursive ]; then rm -rf "$(map "$3")"; else rm -f "$(map "$3")"; fi ;;
  sync)
    src=$(map "$3"); dst=$(map "$4"); shift 4
    exclude=""
    [ "$1" = --exclude ] && exclude=$2
    [ -d "$src" ] || exit 0
    mkdir -p "$dst"
    (cd "$src" && find . -type f | sed 's|^\./||') | while IFS= read -r rel; do
      # shellcheck disable=SC2254
      case "$rel" in $exclude) continue ;; esac
      mkdir -p "$(dirname "$dst/$rel")"; cp "$src/$rel" "$dst/$rel"
    done ;;
  cp)
    src=$(map "$3"); dst=$(map "$4"); shift 4
    recursive=0 excludes=" "
    while [ $# -gt 0 ]; do
      case "$1" in
        --recursive) recursive=1 ;;
        --exclude) excludes="$excludes$2 "; shift ;;
      esac; shift
    done
    if [ "$recursive" = 1 ]; then
      [ -d "$src" ] || exit 1
      [ -e "$FAKE_DIR/cp_fails" ] && exit 1
      mkdir -p "$dst"
      # Like the real one: every file under src, links followed, excludes matched on the
      # path relative to src.
      (cd "$src" && find -L . -type f | sed 's|^\./||' | sort) | while IFS= read -r rel; do
        case "$excludes" in *" $rel "*) continue ;; esac
        mkdir -p "$(dirname "$dst/$rel")"
        cp -L "$src/$rel" "$dst/$rel"
        echo "${dst#"$FAKE_S3"/}$rel" >>"$FAKE_DIR/s3-order.log"
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
      *"max(build_id)"*) echo BUILD ;;
      *"to_regnamespace('live') IS NOT NULL"*) echo t ;;
      *"to_regclass('staging.segment')"*) echo t ;;
      *"to_regnamespace('staging') IS NULL"*)
        cat "$FAKE_DIR/staging_absent" 2>/dev/null || echo t ;;
      *"string_agg"*) cat "$FAKE_DIR/in_flight" 2>/dev/null ;;
      *"to_regclass('live.segment')"*)
        [ ! -e "$FAKE_DIR/psql_fails" ] || { echo "psql: connection refused" >&2; exit 2; }
        cat "$FAKE_DIR/live_table" 2>/dev/null || echo t ;;
      *"DISTINCT volume_source"*) cat "$FAKE_DIR/live_sources" 2>/dev/null ;;
      *"cat > /tmp/cloud.use"*) cat >"$FAKE_DIR/cloud.use" ;;
      *" -q -1 "*) cat >>"$FAKE_DIR/blanked.sql" ;;
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


# ship-data.sh's db part, as send-inputs.sh runs it: the stripped dump and one blanked table.
FAKE_SHIP_DB = r"""#!/usr/bin/env bash
printf 'ship-db %s\n' "$*" >>"$FAKE_DIR/calls.log"
while [ $# -gt 0 ]; do [ "$1" = --stage ] && stage=$2; shift; done
[ -e "$FAKE_DIR/ship_db_fails" ] && exit 2
mkdir -p "$stage/db/blanked"
echo "stripped dump" >"$stage/db/routemaker.dump"
printf 'id\tosm_way_id\tcreated_by_id\n1\t5\t\\N\n' >"$stage/db/blanked/override.copy"
printf 'live.segment\t1\n' >"$stage/db/row-counts.tsv"
"""


AGENCY_LTS = (
    '[{"id": "m", "agency": "moco"}, {"id": "d", "agency": "ddot"}, {"agency": "mdot-sha"}]'
)

SCENIC = '[{"id":"r","source":"moco-rustic"},{"id":"b","source":"md-byways"}]'


@pytest.fixture
def home(fake):
    """A live checkout (its .env), a DATA_ROOT with a nightly backup and the three inputs,
    and the fake ship-data.sh that makes the run's own dump."""
    live = fake.root / "live"
    live.mkdir()
    data = fake.root / "data"
    (live / ".env").write_text(f"TAG=dev\nDATA_ROOT={data}\nPGUSER=routemaker\n")
    (data / "backups").mkdir(parents=True)
    (data / "backups" / "routemaker-20261011T070000Z.dump").write_text("nightly, with accounts")
    for part in ("reference", "elevation", "extracts"):
        (data / part).mkdir()
        (data / part / f"{part}.file").write_text(part)
    (data / "reference" / "agency-lts.json").write_text(AGENCY_LTS)
    (data / "reference" / "scenic.json").write_text(SCENIC)
    (data / "reference" / "bikeshare-trips.json").write_text('{"stations":[],"pairs":[],"days":1}')
    ship = fake.root / "bin" / "ship-db"
    ship.write_text(FAKE_SHIP_DB)
    ship.chmod(0o755)
    return live, data


def send(fake, home, *extra: str):
    live, _ = home
    return fake.run(
        SEND,
        "--live-dir",
        str(live),
        *extra,
        fake.url,
        CLOUD_SHIP_DATA=str(fake.root / "bin" / "ship-db"),
    )


# --- send-inputs.sh ------------------------------------------------------------------


def test_send_uploads_a_stripped_dump_and_the_three_inputs_checksums_last(fake, home) -> None:
    done = send(fake, home)
    assert done.returncode == 0, done.stderr

    sent = fake.in_bucket("in")
    names = sorted(p.name for p in sent.iterdir())
    assert names == [
        "MANIFEST.txt",
        "SHA256SUMS",
        "db.tar",
        "elevation.tar",
        "extracts.tar",
        "reference.tar",
    ], "never the nightly backup, which carries accounts and Homes"
    ship = next(line for line in fake.calls().splitlines() if line.startswith("ship-db"))
    assert "--no-transfer" in ship and f"--live-dir {home[0]}" in ship
    for part in ("tiles", "elevation", "basemap", "photon", "transit", "frontend"):
        assert f"--without {part}" in ship
    assert "--without db" not in ship
    packed = subprocess.run(["tar", "-tf", str(sent / "db.tar")], capture_output=True, text=True)
    assert set(packed.stdout.split()) >= {"db/routemaker.dump", "db/blanked/override.copy"}
    manifest = (sent / "MANIFEST.txt").read_text()
    assert f"commit={COMMIT}" in manifest and "backup=db.tar" in manifest
    assert re.search(r"^read_at=\d{8}T\d{6}Z$", manifest, re.M)
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


def test_send_refuses_when_ship_data_makes_no_dump(fake, home) -> None:
    (fake.dir / "ship_db_fails").touch()

    done = send(fake, home)

    assert done.returncode == 2 and "no database dump" in done.stderr
    assert not fake.in_bucket("in").exists()


def test_send_refuses_a_reference_folder_missing_a_live_count_source(fake, home) -> None:
    """The v0.7.0 staging run was sent a folder without MDOT SHA's counts: 5,954 busy
    roads lost their count and their volume step-ups."""
    _, data = home
    (fake.dir / "live_sources").write_text("ddot\nmdot-sha\nvdot\n")
    (data / "reference" / "volume.json").write_text(
        '[{"id": "a", "agency": "vdot"}, {"id": "b", "agency":"ddot"}]'
    )

    done = send(fake, home)

    assert done.returncode == 2 and "no traffic counts from mdot-sha" in done.stderr
    assert not fake.in_bucket("in").exists()

    (data / "reference" / "volume.json").write_text(
        '[{"agency": "vdot"}, {"agency": "ddot"}, {"agency": "mdot-sha"}]'
    )
    assert send(fake, home).returncode == 0


@pytest.mark.parametrize(
    "body, message",
    [
        (None, "agency-lts.json is missing or empty"),
        ("", "agency-lts.json is missing or empty"),
        ('[{"agency": "moco"}, {"agency": "ddot"}]', "no stress ratings from mdot-sha"),
    ],
)
def test_send_refuses_a_reference_folder_without_every_agencys_ratings(
    fake, home, body, message
) -> None:
    """v0.8.0 was built where agency-lts.json had never been installed; the box's rebuild
    now refuses such a folder, so the send refuses it first, before any upload."""
    _, data = home
    path = data / "reference" / "agency-lts.json"
    if body is None:
        path.unlink()
    else:
        path.write_text(body)

    done = send(fake, home)

    assert done.returncode == 2 and message in done.stderr
    assert not fake.in_bucket("in").exists()


@pytest.mark.parametrize("body", [None, ""])
def test_send_refuses_a_reference_folder_without_the_bikeshare_trips(fake, home, body) -> None:
    """The popular corridors' trip counts are optional to the rebuild, which only warns, as
    the Scenic layer's were; the send refuses a folder without them before any upload."""
    _, data = home
    path = data / "reference" / "bikeshare-trips.json"
    if body is None:
        path.unlink()
    else:
        path.write_text(body)

    done = send(fake, home)

    assert done.returncode == 2 and "bikeshare-trips.json is missing or empty" in done.stderr
    assert not fake.in_bucket("in").exists()


def test_the_sends_agency_list_is_the_approved_agencies() -> None:
    from routemaker.agency_lts import AGENCIES

    script = SEND.read_text()
    (line,) = [x for x in script.splitlines() if x.startswith("AGENCY_LTS_AGENCIES=(")]
    assert line.removeprefix("AGENCY_LTS_AGENCIES=(").rstrip(")").split() == list(AGENCIES)


@pytest.mark.parametrize(
    "body, message",
    [
        (None, "scenic.json is missing or empty"),
        ("", "scenic.json is missing or empty"),
        ('[{"id":"b","source":"md-byways"}]', "no lines from moco-rustic"),
    ],
)
def test_send_refuses_a_reference_folder_without_the_scenic_lines(
    fake, home, body, message
) -> None:
    """v0.8.0 was built where scenic.json had never been installed, so the Scenic layer had
    no Rustic Road; the send refuses such a folder before any upload."""
    _, data = home
    path = data / "reference" / "scenic.json"
    if body is None:
        path.unlink()
    else:
        path.write_text(body)

    done = send(fake, home)

    assert done.returncode == 2 and message in done.stderr
    assert not fake.in_bucket("in").exists()


def test_the_sends_scenic_list_is_the_scenic_sources() -> None:
    from routemaker.scenic import SOURCES

    script = SEND.read_text()
    (line,) = [x for x in script.splitlines() if x.startswith("SCENIC_SOURCES=(")]
    assert line.removeprefix("SCENIC_SOURCES=(").rstrip(")").split() == list(SOURCES)


def test_a_first_deployment_with_no_live_map_skips_the_count_check(fake, home) -> None:
    (fake.dir / "live_table").write_text("f\n")
    (fake.dir / "live_sources").write_text("mdot-sha\n")

    done = send(fake, home)

    assert done.returncode == 0, done.stderr
    assert "no live segment table here" in done.stdout


def test_a_database_that_does_not_answer_is_said_not_swallowed(fake, home) -> None:
    (fake.dir / "psql_fails").touch()

    done = send(fake, home)

    assert done.returncode == 2
    assert "psql: connection refused" in done.stderr and "is it running" in done.stderr
    assert not fake.in_bucket("in").exists()


def test_send_takes_another_reference_folder_only_with_the_live_builds_files(fake, home) -> None:
    _, data = home
    (data / "reference" / "agency").mkdir()
    (data / "reference" / "agency" / "layer.json").write_text("live layer")
    other = fake.root / "other-reference"
    (other / "agency").mkdir(parents=True)
    (other / "reference.file").write_text("an older copy")
    (other / "agency-lts.json").write_text(AGENCY_LTS)
    (other / "scenic.json").write_text(SCENIC)
    (other / "bikeshare-trips.json").write_text('{"stations":[],"pairs":[],"days":1}')
    (other / "agency" / "layer.json").write_text("live layer")

    done = send(fake, home, "--reference-dir", str(other))
    assert done.returncode == 2 and "reference.file differs from" in done.stderr

    (other / "reference.file").write_text("reference")
    (other / "agency" / "layer.json").write_text("an older layer")
    done = send(fake, home, "--reference-dir", str(other))
    assert done.returncode == 2 and "agency/layer.json differs from" in done.stderr, "recursive"

    (other / "agency" / "layer.json").unlink()
    done = send(fake, home, "--reference-dir", str(other))
    assert done.returncode == 2 and "has no agency/layer.json" in done.stderr

    (other / "agency" / "layer.json").write_text("live layer")
    (other / "volume.json").write_text("[]")
    done = send(fake, home, "--reference-dir", str(other))
    assert done.returncode == 0, done.stderr
    packed = subprocess.run(
        ["tar", "-tf", str(fake.in_bucket("in") / "reference.tar")], capture_output=True, text=True
    )
    assert {"reference/reference.file", "reference/volume.json"} <= {
        name.rstrip("/") for name in packed.stdout.split()
    }


def test_send_runs_git_with_the_checkout_marked_safe(fake, home) -> None:
    live, _ = home
    assert send(fake, home).returncode == 0
    gits = [line for line in fake.calls().splitlines() if line.startswith("git ")]
    assert gits and all(f"-c safe.directory={live} " in line for line in gits)


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
        "pg_restore --list",
        "pg_restore --no-owner --no-privileges -U routemaker -d routemaker -L /tmp/cloud.use",
        "psql -U routemaker -d routemaker -q -1",
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
    assert "createdb" not in calls, "the fresh volume's database, with its postgis extensions"
    blanked = (fake.dir / "blanked.sql").read_text()
    assert blanked.startswith("COPY public.override (id,osm_way_id,created_by_id) FROM stdin")
    assert "setval(pg_get_serial_sequence('public.override', 'id')" in blanked
    assert " SCHEMA - public " not in (fake.dir / "cloud.use").read_text()
    run_in = fake.root / "home" / "cloud-runs" / "cloud-20261011" / "in"
    assert (run_in / "db.tar").exists() and not (run_in / "db").exists(), (
        "this run's dump is kept; only its unpacked copy goes"
    )

    out = fake.in_bucket("out")
    names = {p.name for p in out.iterdir()}
    assert {f"tiles-{v}.tar" for v in VARIANTS} <= names
    assert {"staging.dump", "MANIFEST.txt", "SHA256SUMS"} <= names
    manifest = (out / "MANIFEST.txt").read_text()
    sent = (fake.in_bucket("in") / "MANIFEST.txt").read_text()
    read_at = re.search(r"^read_at=(\S+)$", sent, re.M).group(1)
    assert f"build={BUILD}" in manifest and f"read_at={read_at}" in manifest
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
    [log] = (fake.root / "home" / "cloud-runs" / "cloud-20261011").glob("rebuild-*.log.gz")
    # Sent before the power-off, to be read from home without starting the box.
    assert (fake.in_bucket("failed") / log.name).read_bytes() == log.read_bytes()
    order = fake.calls()
    assert order.index(f"failed/{log.name}") < order.index("sudo poweroff")


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


def test_a_resumed_run_refuses_inputs_sent_again_since_it_fetched(fake, home) -> None:
    # Review pipeline-7: once fetched, the bucket's checksums were never read again.
    assert send(fake, home).returncode == 0
    (fake.dir / "job_status").write_text("doing\nfailed\n")
    box(fake, "--no-stop")
    sums = fake.in_bucket("in") / "SHA256SUMS"
    sums.write_text(sums.read_text() + "0" * 64 + "  another.tar\n")

    done, _ = box(fake)

    assert done.returncode == 2 and "other inputs than this run fetched" in done.stderr


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


def test_a_finished_run_deletes_older_runs_dumps_and_keeps_its_own(fake, home) -> None:
    """The owner's rule (2026-10-16): the newest run's dump stays on the box and in S3; an
    older run's goes, in both places, once a newer run has succeeded. Its other files stay."""
    transfer = fake.bucket / "bucket" / "rebuild-checkpoints" / "transfer"
    old_s3 = transfer / "cloud-20261001" / "in"
    old_s3.mkdir(parents=True)
    for name in ("db.tar", "routemaker-20261001T070000Z.dump", "reference.tar"):
        (old_s3 / name).write_text("old")
    # An older run (its read_at) that finished: its result is in out/.
    (old_s3 / "MANIFEST.txt").write_text("read_at=20261001T070000Z\n")
    (old_s3.parent / "out").mkdir()
    (old_s3.parent / "out" / "SHA256SUMS").write_text("x\n")
    old_box = fake.root / "home" / "cloud-runs" / "cloud-20261001" / "in"
    old_box.mkdir(parents=True)
    for name in ("routemaker-20261001T070000Z.dump", "reference.tar"):
        (old_box / name).write_text("old")
    assert send(fake, home).returncode == 0

    (fake.dir / "job_status").write_text("failed\n")
    assert box(fake, "--no-stop")[0].returncode == 1
    assert (old_s3 / "db.tar").exists() and (
        old_box / "routemaker-20261001T070000Z.dump"
    ).exists(), "a failed run deletes nothing"

    (fake.dir / "job_status").write_text("succeeded\n")
    built_tiles(fake.root / "box" / "data")
    done, _ = box(fake, "--refire")

    assert done.returncode == 0, done.stdout + done.stderr
    assert sorted(p.name for p in old_s3.iterdir()) == ["MANIFEST.txt", "reference.tar"]
    assert sorted(p.name for p in old_box.iterdir()) == ["reference.tar"]
    assert (fake.in_bucket("in") / "db.tar").exists()
    assert (fake.root / "home" / "cloud-runs" / "cloud-20261011" / "in" / "db.tar").exists()


def test_a_newer_runs_dump_and_a_waiting_runs_inputs_are_never_pruned(fake, home) -> None:
    """Review round 2, S2: a run newer than this one (its read_at) keeps its dump, finished or
    not, and an older run that has not finished (inputs sent, never built) keeps its inputs."""
    transfer = fake.bucket / "bucket" / "rebuild-checkpoints" / "transfer"
    runs = fake.root / "home" / "cloud-runs"
    kept = {"cloud-20991231": "20991231T000000Z", "cloud-20261002": "20261002T070000Z"}
    for name, read_at in kept.items():
        s3_in = transfer / name / "in"
        s3_in.mkdir(parents=True)
        (s3_in / "db.tar").write_text("dump")
        (s3_in / "MANIFEST.txt").write_text(f"read_at={read_at}\n")
    # The newer one has finished, on the box and in S3; the older one is still waiting.
    (transfer / "cloud-20991231" / "out").mkdir()
    (transfer / "cloud-20991231" / "out" / "SHA256SUMS").write_text("x\n")
    newer_box = runs / "cloud-20991231"
    (newer_box / "in").mkdir(parents=True)
    (newer_box / "state").mkdir()
    (newer_box / "in" / "db.tar").write_text("dump")
    (newer_box / "in" / "MANIFEST.txt").write_text("read_at=20991231T000000Z\n")
    (newer_box / "state" / "upload.done").write_text("x\n")
    assert send(fake, home).returncode == 0
    (fake.dir / "job_status").write_text("succeeded\n")
    built_tiles(fake.root / "box" / "data")

    done, _ = box(fake)

    assert done.returncode == 0, done.stdout + done.stderr
    for name in kept:
        assert (transfer / name / "in" / "db.tar").exists(), name
    assert (newer_box / "in" / "db.tar").exists()
    assert "keeping run cloud-20991231's dump: it is not older" in done.stdout
    assert "keeping run cloud-20261002's dump: that run has not finished" in done.stdout


def test_a_second_copy_on_the_box_refuses_while_the_first_runs(fake, home) -> None:
    assert send(fake, home).returncode == 0
    runs = fake.root / "home" / "cloud-runs"
    runs.mkdir(parents=True, exist_ok=True)
    (fake.dir / "calls.log").unlink()
    holder = subprocess.Popen(["flock", str(runs / ".box-rebuild.lock"), "sleep", "30"])
    try:
        for _ in range(50):
            if subprocess.run(["flock", "-n", str(runs / ".box-rebuild.lock"), "true"]).returncode:
                break
            time.sleep(0.1)
        done, _ = box(fake)
    finally:
        holder.kill()
        holder.wait()

    assert done.returncode == 2 and "already running on this box" in done.stderr
    assert fake.calls() == "", "nothing fetched, restored or fired"


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
    # Run as root on the owner's checkout, git refuses it as "dubious ownership" without this.
    assert f"git -c safe.directory={result[0]} -C {result[0]} rev-parse HEAD" in calls
    assert "import-result: installed." in done.stdout, "launch.sh reads this line"


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


def test_the_dry_run_reads_the_boxs_reports_and_never_an_older_copy(fake, result) -> None:
    out = fake.in_bucket("out")
    box_reports = fake.root / "boxreports"
    (box_reports / "reports").mkdir(parents=True)
    (box_reports / "reports" / "stress-changes.csv").write_text("osm_way_id\n5\n")
    subprocess.run(
        ["tar", "-C", str(box_reports), "-cf", str(out / "reports.tar"), "reports"], check=True
    )
    subprocess.run(
        "sha256sum -- MANIFEST.txt staging.dump tiles-*.tar reports.tar > SHA256SUMS",
        shell=True,
        cwd=out,
        check=True,
    )
    _, data = result
    unpacked = data / "rebuild" / "cloud-reports" / BUILD / "reports"
    unpacked.mkdir(parents=True)
    (unpacked / "left-from-an-earlier-run.csv").write_text("old")

    done = importing(fake, result)

    assert done.returncode == 0, done.stdout + done.stderr
    assert sorted(p.name for p in unpacked.iterdir()) == ["stress-changes.csv"]
    assert f"--review-reports-dir cloud-reports/{BUILD}/reports" in fake.calls()

    # A run whose box sent no reports: none are read, and the earlier ones are gone.
    (fake.dir / "calls.log").unlink()
    (out / "reports.tar").unlink()
    subprocess.run(
        "sha256sum -- MANIFEST.txt staging.dump tiles-*.tar > SHA256SUMS",
        shell=True,
        cwd=out,
        check=True,
    )
    stage = fake.root / "home" / "cloud-runs" / "cloud-20261011" / "out"
    (stage / "reports.tar").unlink(missing_ok=True)

    done = importing(fake, result)

    assert done.returncode == 0, done.stdout + done.stderr
    assert not (data / "rebuild" / "cloud-reports" / BUILD).exists()
    assert "--review-reports-dir" not in fake.calls()


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


def test_the_swap_refuses_an_install_that_did_not_finish(fake, result) -> None:
    (fake.dir / "restore_rc").write_text("1")
    assert importing(fake, result).returncode == 2
    (fake.dir / "calls.log").unlink()

    done = importing(fake, result, "--swap")

    assert done.returncode == 2 and "did not finish" in done.stderr
    assert "import_cloud_build" not in fake.calls()


def test_a_second_run_does_not_download_removed_graph_tars_again(fake, result) -> None:
    assert importing(fake, result, "--remove-tars").returncode == 0
    stage = fake.root / "home" / "cloud-runs" / "cloud-20261011" / "out"
    assert not list(stage.glob("tiles-*.tar"))
    (fake.dir / "staging_absent").write_text("f\n")

    done = importing(fake, result)

    assert done.returncode == 0, done.stdout + done.stderr
    assert "--exclude tiles-*.tar" in fake.calls()
    assert not list(stage.glob("tiles-*.tar"))


def test_the_swap_restarts_the_off_road_router_where_it_runs(fake, result) -> None:
    assert importing(fake, result).returncode == 0
    (fake.dir / "offroad_running").write_text("abc123\n")

    done = importing(fake, result, "--swap")

    assert done.returncode == 0, done.stderr
    assert "compose --profile offroad ps -q valhalla-offroad" in fake.calls()
    assert "compose --profile offroad restart valhalla-offroad" in fake.calls()
    # The Mountain Bike router, behind the same profile, the same way (slice 6).
    assert "compose --profile offroad ps -q valhalla-mtb" in fake.calls()
    assert "compose --profile offroad restart valhalla-mtb" in fake.calls()


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


# --- the beta's bundle ---------------------------------------------------------------

FAKE_SHIP_DATA = r"""#!/usr/bin/env bash
printf 'ship-data %s\n' "$*" >>"$FAKE_DIR/calls.log"
stage=""
while [ $# -gt 0 ]; do [ "$1" = --stage ] && stage=$2; shift; done
mkdir -p "$stage/tiles/standard/BUILD" "$stage/db"
echo graph >"$FAKE_DIR/graph.tar"
ln -s "$FAKE_DIR/graph.tar" "$stage/tiles/standard/BUILD/tiles.tar"
echo dump >"$stage/db/routemaker.dump"
(cd "$stage" && sha256sum tiles/standard/BUILD/tiles.tar db/routemaker.dump >SHA256SUMS)
graphs=""
for v in standard no-trail ebike weekend offroad mtb; do
  graphs="$graphs $v=${FAKE_SHIPPED:-BUILD}"
done
printf 'bundle_format=1\ntiles=%s\n' "${graphs# }" >"$stage/MANIFEST.txt"
[ ! -e "$FAKE_DIR/ship_fails" ]
""".replace("BUILD", BUILD)


@pytest.fixture
def ship_data(fake) -> Path:
    path = fake.root / "bin" / "ship-data"
    path.write_text(FAKE_SHIP_DATA)
    path.chmod(0o755)
    return path


def test_the_box_makes_the_betas_bundle_before_the_export_and_sends_it_last(
    fake, home, ship_data
) -> None:
    assert send(fake, home).returncode == 0
    fake.in_bucket("beta").mkdir(parents=True)
    (fake.in_bucket("beta") / "stray-from-an-earlier-run").write_text("old")
    (fake.dir / "job_status").write_text("succeeded\n")
    built_tiles(fake.root / "box" / "data")

    done = fake.run(
        BOX,
        "--build-dir",
        str(fake.root / "box" / "build"),
        "--data-root",
        str(fake.root / "box" / "data"),
        "--beta-bundle",
        fake.url,
        CLOUD_SHIP_DATA=str(ship_data),
    )

    assert done.returncode == 0, done.stdout + done.stderr
    calls = fake.calls()
    ship = next(line for line in calls.splitlines() if line.startswith("ship-data"))
    for arg in (
        f"--live-dir {fake.root / 'box' / 'build'}",
        "--no-transfer",
        "--without elevation --without basemap --without photon --without frontend",
    ):
        assert arg in ship
    assert calls.index("ship-data") < calls.index("ALTER SCHEMA live RENAME TO staging")
    beta = fake.in_bucket("beta")
    graph = beta / "tiles" / "standard" / BUILD / "tiles.tar"
    assert graph.is_file() and not graph.is_symlink() and graph.read_text() == "graph\n"
    order = [
        line for line in (fake.dir / "s3-order.log").read_text().splitlines() if "/beta/" in line
    ]
    names = [line.rsplit("/", 1)[1] for line in order]
    assert names[-2:] == ["SHA256SUMS", "MANIFEST.txt"]
    assert names.count("SHA256SUMS") == 1 and names.count("MANIFEST.txt") == 1, "and only last"
    assert subprocess.run(["sha256sum", "-c", "SHA256SUMS"], cwd=beta).returncode == 0
    assert calls.index("beta/MANIFEST.txt") < calls.index("sudo poweroff")
    every = (fake.dir / "s3-order.log").read_text().splitlines()
    assert every.index(next(x for x in every if x.endswith("out/SHA256SUMS"))) < every.index(
        order[0]
    ), "home's result goes up first"
    assert not (beta / "stray-from-an-earlier-run").exists()


def test_a_resumed_run_remembers_the_beta_bundle(fake, home, ship_data) -> None:
    assert send(fake, home).returncode == 0
    (fake.dir / "job_status").write_text("failed\n")
    box(fake, "--no-stop", "--beta-bundle")
    assert "ship-data" not in fake.calls(), "a failed rebuild makes no bundle"
    (fake.dir / "job_status").write_text("succeeded\n")
    built_tiles(fake.root / "box" / "data")

    done = fake.run(
        BOX,
        "--build-dir",
        str(fake.root / "box" / "build"),
        "--data-root",
        str(fake.root / "box" / "data"),
        "--refire",
        fake.url,
        CLOUD_SHIP_DATA=str(ship_data),
    )

    assert done.returncode == 0, done.stdout + done.stderr
    assert "ship-data" in fake.calls()
    assert (fake.in_bucket("beta") / "MANIFEST.txt").is_file()


def run_box_with_bundle(fake, ship_data, **more: str):
    return fake.run(
        BOX,
        "--build-dir",
        str(fake.root / "box" / "build"),
        "--data-root",
        str(fake.root / "box" / "data"),
        "--beta-bundle",
        fake.url,
        CLOUD_SHIP_DATA=str(ship_data),
        **more,
    )


@pytest.mark.parametrize("trouble", ["ship_fails", "another_build", "empty_stage"])
def test_a_beta_bundle_that_fails_never_holds_up_homes_result(
    fake, home, ship_data, trouble
) -> None:
    assert send(fake, home).returncode == 0
    (fake.dir / "job_status").write_text("succeeded\n")
    built_tiles(fake.root / "box" / "data")
    more = {}
    if trouble == "ship_fails":
        (fake.dir / "ship_fails").touch()
    elif trouble == "empty_stage":
        empty = fake.root / "bin" / "ship-nothing"
        empty.write_text("#!/usr/bin/env bash\nexit 0\n")
        empty.chmod(0o755)
        ship_data = empty
    else:
        more["FAKE_SHIPPED"] = "20261004T080000Z"

    done = run_box_with_bundle(fake, ship_data, **more)

    assert done.returncode == 0, done.stdout + done.stderr
    assert "no bundle for the beta" in done.stdout
    assert (fake.in_bucket("out") / "SHA256SUMS").is_file(), "home's result went up"
    assert not fake.in_bucket("beta").exists()


FAKE_BETA_TOOL = r"""#!/usr/bin/env bash
printf 'NAME %s\n' "$*" >>"$FAKE_DIR/calls.log"
case "NAME $*" in
  *"receive "*" db "*) exit "$(cat "$FAKE_DIR/receive_db_rc" 2>/dev/null || echo 0)" ;;
  "smoke "*)
    left=$(cat "$FAKE_DIR/smoke_fails" 2>/dev/null || echo 0)
    if [ "$left" -gt 0 ]; then echo $((left - 1)) >"$FAKE_DIR/smoke_fails"; exit 1; fi ;;
esac
exit 0
"""


@pytest.fixture
def beta(fake):
    """The beta's checkout (its .env and scripts/beta/ stand-ins) and the box's beta/ folder."""
    live = fake.root / "beta"
    data = fake.root / "beta-data"
    data.mkdir()
    (live / "scripts" / "beta").mkdir(parents=True)
    (live / ".env").write_text(f"DATA_ROOT={data}\nCOMPOSE_PROJECT_NAME=routemaker-beta\n")
    tools = {}
    for name in ("receive", "beta-compose", "smoke"):
        path = fake.root / "bin" / name
        path.write_text(FAKE_BETA_TOOL.replace("NAME", name))
        path.chmod(0o755)
        tools[name] = path
    bundle = fake.in_bucket("beta")
    (bundle / "tiles" / "standard" / BUILD).mkdir(parents=True)
    (bundle / "tiles" / "standard" / BUILD / "tiles.tar").write_text("graph")
    (bundle / "db").mkdir()
    (bundle / "db" / "routemaker.dump").write_text("dump")
    (bundle / "SHA256SUMS").write_text("sums")
    (bundle / "MANIFEST.txt").write_text("bundle_format=1\n")

    class Beta:
        incoming = fake.root / "incoming"
        state = fake.root / "beta-state"

        def run(self, *args: str):
            return fake.run(
                IMPORT,
                "--beta",
                "--live-dir",
                str(live),
                "--incoming",
                str(self.incoming),
                "--state",
                str(self.state),
                *args,
                fake.url,
                CLOUD_RECEIVE=str(tools["receive"]),
                CLOUD_BETA_COMPOSE=str(tools["beta-compose"]),
                CLOUD_SMOKE=str(tools["smoke"]),
                CLOUD_SMOKE_TRIES="3",
                CLOUD_SMOKE_WAIT_S="0",
            )

    Beta.live, Beta.data = live, data
    return Beta()


def test_on_the_beta_it_downloads_and_verifies_and_installs_nothing(fake, beta) -> None:
    done = beta.run()

    assert done.returncode == 0, done.stdout + done.stderr
    assert (beta.incoming / "tiles" / "standard" / BUILD / "tiles.tar").read_text() == "graph"
    calls = fake.calls()
    assert f"receive --bundle {beta.incoming} --env-file {beta.live / '.env'} verify" in calls
    assert " files" not in calls and "db --update-data" not in calls and "beta-compose" not in calls


def test_on_the_beta_an_unfinished_bundle_is_refused(fake, beta) -> None:
    (fake.in_bucket("beta") / "MANIFEST.txt").unlink()

    done = beta.run()

    assert done.returncode == 2 and "no finished bundle" in done.stderr
    assert "receive" not in fake.calls()


def test_on_the_beta_the_swap_is_the_runbooks_new_data_update(fake, beta) -> None:
    assert beta.run().returncode == 0
    (fake.dir / "calls.log").unlink()

    done = beta.run("--swap")

    assert done.returncode == 0, done.stdout + done.stderr
    calls = fake.calls()
    order = [
        "receive --bundle",
        "sudo " + str(fake.root / "bin" / "receive"),
        "beta-compose stop api worker",
        "db --update-data",
        "beta-compose up -d api worker",
        "beta-compose restart valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend",
        "smoke --local",
    ]
    positions = [calls.index(step) for step in order]
    assert positions == sorted(positions), calls
    assert " files" in calls and "--replace-db" not in calls
    assert (beta.state / "predraw.log").exists()
    assert "valhalla-offroad" not in calls and "valhalla-mtb" not in calls


def test_on_the_beta_the_swap_starts_the_trail_routers_whose_tiles_are_there(fake, beta) -> None:
    # A restart never starts a router that is not running: without this the beta planned
    # Mountain Bike on the standard graph after every map swap.
    (beta.data / "tiles" / "mtb" / BUILD).mkdir(parents=True, exist_ok=True)
    (beta.data / "tiles" / "mtb" / "current").symlink_to(BUILD)
    assert beta.run().returncode == 0
    (fake.dir / "calls.log").unlink()

    done = beta.run("--swap")

    assert done.returncode == 0, done.stdout + done.stderr
    calls = fake.calls()
    restart = "beta-compose restart valhalla-standard valhalla-no-trail valhalla-ebike valhalla-weekend"
    start = "beta-compose up -d --force-recreate valhalla-mtb"
    assert calls.index(restart) < calls.index(start) < calls.index("smoke --local"), calls
    assert "valhalla-offroad" not in calls


def test_on_the_beta_the_swap_waits_for_deployment_to_be_paused(fake, beta) -> None:
    assert beta.run().returncode == 0
    (beta.state / "cd" / "bin").mkdir(parents=True)
    (fake.dir / "calls.log").unlink()

    done = beta.run("--swap")

    assert done.returncode == 2 and "pause --wait" in done.stderr
    assert "receive" not in fake.calls()

    (beta.state / "cd" / "PAUSED").write_text("cloud data\n")
    assert beta.run("--swap").returncode == 0


def test_on_the_beta_a_failed_database_update_starts_the_app_again(fake, beta) -> None:
    assert beta.run().returncode == 0
    (fake.dir / "receive_db_rc").write_text("1")

    done = beta.run("--swap")

    assert done.returncode == 2 and "database is as it was" in done.stderr
    calls = fake.calls()
    assert calls.index("db --update-data") < calls.rindex("beta-compose up -d api worker")
    assert "restart valhalla" not in calls


def test_on_the_beta_a_sha_mismatch_is_passed_to_receive_data(fake, beta) -> None:
    done = beta.run("--allow-sha-mismatch")

    assert done.returncode == 0, done.stderr
    assert "--allow-sha-mismatch verify" in fake.calls()


def test_on_the_beta_incoming_may_not_be_inside_data_root(fake, beta) -> None:
    beta.incoming = beta.data / "incoming"

    done = beta.run()

    assert done.returncode == 2 and "inside DATA_ROOT" in done.stderr
    assert not beta.incoming.exists()


def test_on_the_beta_a_run_with_no_bundle_leaves_incoming_alone(fake, beta) -> None:
    shutil.rmtree(fake.in_bucket("beta"))
    beta.incoming.mkdir()
    (beta.incoming / "MANIFEST.txt").write_text("the bundle sent from home\n")

    done = beta.run()

    assert done.returncode == 2 and "no finished bundle" in done.stderr
    assert (beta.incoming / "MANIFEST.txt").read_text() == "the bundle sent from home\n"


def test_on_the_beta_the_swap_installs_only_this_runs_bundle(fake, beta) -> None:
    beta.incoming.mkdir()
    (beta.incoming / "MANIFEST.txt").write_text("the bundle sent from home\n")

    done = beta.run("--swap")

    assert done.returncode == 2 and "does not hold this run's bundle" in done.stderr
    assert "receive" not in fake.calls()


def test_on_the_beta_the_swap_waits_for_a_running_pass(fake, beta) -> None:
    import fcntl

    assert beta.run().returncode == 0
    cd = beta.state / "cd"
    (cd / "bin").mkdir(parents=True)
    (cd / "PAUSED").write_text("cloud data\n")
    (fake.dir / "calls.log").unlink()
    with (cd / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        done = beta.run("--swap")

    assert done.returncode == 2 and "still running" in done.stderr
    assert "receive" not in fake.calls()


def test_on_the_beta_the_smoke_test_is_retried_while_the_app_starts(fake, beta) -> None:
    assert beta.run().returncode == 0
    (fake.dir / "smoke_fails").write_text("2")

    done = beta.run("--swap")

    assert done.returncode == 0, done.stdout + done.stderr
    assert fake.calls().count("smoke --local") == 3


def test_on_the_beta_a_smoke_test_that_keeps_failing_is_reported(fake, beta) -> None:
    assert beta.run().returncode == 0
    (fake.dir / "smoke_fails").write_text("9")

    done = beta.run("--swap")

    assert done.returncode == 1
    assert "still fails" in done.stdout and "--public" in done.stdout


def test_a_refired_run_makes_its_beta_bundle_again(fake, home, ship_data) -> None:
    assert send(fake, home).returncode == 0
    (fake.dir / "job_status").write_text("succeeded\n")
    built_tiles(fake.root / "box" / "data")
    assert run_box_with_bundle(fake, ship_data, CLOUD_POWEROFF="true").returncode == 0

    done = fake.run(
        BOX,
        "--build-dir",
        str(fake.root / "box" / "build"),
        "--data-root",
        str(fake.root / "box" / "data"),
        "--refire",
        fake.url,
        CLOUD_SHIP_DATA=str(ship_data),
    )

    assert done.returncode == 0, done.stdout + done.stderr
    assert fake.calls().count("ship-data --live-dir") == 2, "not the earlier build's stage"


def test_a_bundle_asked_for_after_the_export_is_not_made(fake, home, ship_data) -> None:
    assert send(fake, home).returncode == 0
    (fake.dir / "job_status").write_text("succeeded\n")
    built_tiles(fake.root / "box" / "data")
    box(fake, "--no-stop")
    (fake.root / "home" / "cloud-runs" / "cloud-20261011" / "state" / "upload.done").unlink()

    done = run_box_with_bundle(fake, ship_data)

    assert done.returncode == 0, done.stdout + done.stderr
    assert "export already renamed" in done.stdout
    assert "ship-data" not in fake.calls() and not fake.in_bucket("beta").exists()


def test_on_the_beta_the_swap_passes_a_sha_mismatch_to_every_step(fake, beta) -> None:
    assert beta.run("--allow-sha-mismatch").returncode == 0
    (fake.dir / "calls.log").unlink()

    done = beta.run("--allow-sha-mismatch", "--swap")

    assert done.returncode == 0, done.stdout + done.stderr
    receive = fake.root / "bin" / "receive"
    tail = f"--bundle {beta.incoming} --env-file {beta.live / '.env'} --allow-sha-mismatch"
    calls = fake.calls()
    assert f"sudo {receive} {tail} files" in calls
    assert f"sudo {receive} {tail} db --update-data" in calls


def test_on_the_beta_the_swap_refuses_a_deploy_left_half_done(fake, beta) -> None:
    assert beta.run().returncode == 0
    cd = beta.state / "cd"
    (cd / "bin").mkdir(parents=True)
    (cd / "PAUSED").write_text("cloud data\n")
    (cd / "in-progress").write_text("step 3\n")
    (fake.dir / "calls.log").unlink()

    done = beta.run("--swap")

    assert done.returncode == 2 and "half done" in done.stderr
    assert "receive" not in fake.calls()


def test_on_the_beta_incoming_may_not_be_inside_the_checkout(fake, beta) -> None:
    beta.incoming = beta.live / "incoming"

    done = beta.run()

    assert done.returncode == 2 and "inside DATA_ROOT or the checkout" in done.stderr
    assert not beta.incoming.exists()
