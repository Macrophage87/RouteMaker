"""The beta's staging swap (receive-data.sh db --update-data) against a real PostgreSQL.

The owner, 2026-11-02: "We've got several terabytes of extra space on the server so in the future
do the staging swap". The update restores the bundle's `live` schema beside the served one while
the beta serves, then renames it in with one short transaction, as pipeline.swap does at home.

These run the script itself, with beta-compose.sh replaced by a stand-in that runs `exec -T
postgis <command>` on this machine against the test server (PGHOST and friends, as CI sets them),
in a database of their own. They are skipped where no server answers.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "beta" / "receive-data.sh"
BETA_DB = "rm_staging_swap_beta"
HOME_DB = "rm_staging_swap_home"

STUB = r"""#!/usr/bin/env bash
# beta-compose.sh's stand-in: postgis, api and worker are "running"; exec runs here.
while [ "${1:-}" = --profile ]; do shift 2; done
case "$1" in
  ps)
    case "$*" in
      *Health*) echo healthy ;;
      *) printf 'postgis\napi\nworker\n' ;;
    esac ;;
  exec)
    shift; [ "$1" = -T ] && shift
    shift  # the service
    exec "$@" ;;
  *) echo "stub: $*" >&2 ;;
esac
"""


def psql(db: str, sql: str, check: bool = True) -> str:
    done = subprocess.run(
        ["psql", "-d", db, "-v", "ON_ERROR_STOP=1", "-AtX", "-c", sql],
        capture_output=True,
        text=True,
        check=False,
    )
    if check and done.returncode != 0:
        raise AssertionError(done.stderr)
    return done.stdout.strip()


def server_answers() -> bool:
    if not (shutil.which("psql") and shutil.which("pg_restore") and shutil.which("pg_dump")):
        return False
    try:
        return psql("postgres", "select 1", check=False) == "1"
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not server_answers(), reason="no PostgreSQL server to run against")

# The public tables the update writes, as far as it needs them (the real ones are checked against
# the head schema by tests/test_beta_update_sql.py).
PUBLIC = """
create table django_migrations (id serial primary key, app text);
create table app_user (id serial primary key, name text);
create table override (id serial primary key, kind text);
create table stress_edit (id serial primary key, override_id int references override(id));
create table stress_suggestion (id serial primary key, edit_id int references stress_edit(id));
create table review_ruling (id serial primary key, edit_id int references stress_edit(id),
    access_override_id int references override(id));
create table stress_tile_cache (id serial primary key, tile text);
create table junction_override (id serial primary key, name text);
create table avoid_junction (id serial primary key, name text);
create table junction_suggestion (id serial primary key,
    override_id int references junction_override(id), avoid_id int references avoid_junction(id));
insert into app_user (name) values ('beta rider'), ('beta admin');
insert into override (kind) values ('beta''s own');
insert into stress_tile_cache (tile) values ('stale');
"""


def live_schema_sql(names: list[str]) -> str:
    rows = ", ".join(f"('{n}')" for n in names)
    return (
        "create schema live;"
        "create table live.segment (id serial primary key, name text);"
        "create index segment_name on live.segment (name);"
        f"insert into live.segment (name) values {rows};"
        # a second table, read beside segment (the swap must hold both)
        "create table live.node (id int);"
        f"insert into live.node values ({len(names)});"
    )


@pytest.fixture
def beta(tmp_path: Path):
    for db in (BETA_DB, HOME_DB, f"{BETA_DB}_stage"):
        psql("postgres", f"drop database if exists {db}")
    psql("postgres", f"create database {BETA_DB}")
    psql("postgres", f"create database {HOME_DB}")
    psql(BETA_DB, PUBLIC + live_schema_sql(["old road"]))
    psql(HOME_DB, live_schema_sql(["new road", "newer road", "newest road"]))

    bundle = tmp_path / "incoming"
    (bundle / "db" / "blanked").mkdir(parents=True)
    dump = bundle / "db" / "routemaker.dump"
    subprocess.run(["pg_dump", "-d", HOME_DB, "--format=custom", "-f", str(dump)], check=True)
    (bundle / "db" / "row-counts.tsv").write_text("live.segment\t3\npublic.override\t2\n")
    (bundle / "db" / "blanked" / "override.copy").write_text("id\tkind\n7\thome\n8\thome too\n")
    sums = ""
    for f in sorted(p for p in (bundle / "db").rglob("*") if p.is_file()):
        sums += f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.relative_to(bundle)}\n"
    (bundle / "SHA256SUMS").write_text(sums)
    (bundle / "MANIFEST.txt").write_text(
        "bundle_format=1\nparts=db\ngit_sha=elsewhere\nlive_schema=live\nfiles=3\nbytes=1\n"
    )

    checkout = tmp_path / "checkout"
    (checkout / "scripts" / "beta").mkdir(parents=True)
    stub = checkout / "scripts" / "beta" / "beta-compose.sh"
    stub.write_text(STUB)
    stub.chmod(0o755)
    data = tmp_path / "data"
    (data / "backups").mkdir(parents=True)
    env = checkout / ".env"
    user = os.environ.get("PGUSER") or psql("postgres", "select current_user")
    env.write_text(f"DATA_ROOT={data}\nPGDATABASE={BETA_DB}\nPGUSER={user}\n")

    def run(*args: str, **more: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(SCRIPT), "--bundle", str(bundle), "--env-file", str(env),
             "--allow-sha-mismatch", "db", "--update-data", *args],
            capture_output=True, text=True, check=False, timeout=300,
            env={**os.environ, "RECEIVE_DATA_REPO": str(checkout), **more},
        )  # fmt: skip

    yield run
    for db in (BETA_DB, HOME_DB, f"{BETA_DB}_stage"):
        psql("postgres", f"drop database if exists {db} with (force)", check=False)


def segments(schema: str) -> list[str]:
    return psql(BETA_DB, f"select name from {schema}.segment order by id").splitlines()


def schemas() -> set[str]:
    return set(psql(BETA_DB, "select nspname from pg_namespace where nspname like 'live%'").split())


def test_the_update_stages_beside_the_served_tables_and_renames_them_in(beta) -> None:
    done = beta()

    assert done.returncode == 0, done.stderr
    assert segments("live") == ["new road", "newer road", "newest road"]
    assert segments("live_old") == ["old road"]  # the replaced tables, kept until the next update
    assert schemas() == {"live", "live_old"}
    # its indexes came with it, and the scratch database is gone
    assert psql(BETA_DB, "select count(*) from pg_indexes where schemaname = 'live'") == "2"
    scratch = f"select count(*) from pg_database where datname = '{BETA_DB}_stage'"
    assert psql("postgres", scratch) == "0"
    # the public tables from home replaced, the beta's own left alone
    kinds = psql(BETA_DB, "select string_agg(kind, ',' order by id) from override")
    assert kinds == "home,home too"
    assert psql(BETA_DB, "select count(*) from stress_tile_cache") == "0"
    assert psql(BETA_DB, "select count(*) from app_user") == "2"
    assert "beta accounts untouched: 2" in done.stderr
    assert "the swap is committed" in done.stderr
    # never asked the app to stop
    assert "stop api worker" not in done.stderr


def test_stage_only_renames_nothing_and_the_update_reuses_it(beta) -> None:
    done = beta("--stage-only")

    assert done.returncode == 0, done.stderr
    assert segments("live") == ["old road"]
    assert segments("live_next") == ["new road", "newer road", "newest road"]
    assert psql(BETA_DB, "select count(*) from override") == "1"

    done = beta()

    assert done.returncode == 0, done.stderr
    assert "reusing live_next" in done.stderr
    assert segments("live") == ["new road", "newer road", "newest road"]
    # the bundle mark does not follow it into live, so a later bundle never mistakes live for staged
    assert psql(BETA_DB, "select coalesce(obj_description('live'::regnamespace), '')") == ""


HOLDER = "rm-staging-swap-reader"


def until(sql: str, ready, what: str, limit_s: float = 60.0) -> str:
    """Poll `sql` on the beta database until `ready(its answer)`; the answer."""
    ends = time.monotonic() + limit_s
    while True:
        got = psql(BETA_DB, sql)
        if ready(got):
            return got
        assert time.monotonic() < ends, what
        time.sleep(0.02)


class Reader:
    """An open transaction that has read `table` and keeps its lock until `release`. Made once
    the server shows the lock held, however long psql took to get there; released by the test,
    never by a clock, so a slow machine cannot end it before the rename has met it."""

    def __init__(self, table: str) -> None:
        sql = f"begin; select count(*) from {table}; select pg_sleep(600); commit;"
        self.proc = subprocess.Popen(
            ["psql", "-d", BETA_DB, "-Atq", "-c", sql],
            env={**os.environ, "PGAPPNAME": HOLDER},
            stderr=subprocess.DEVNULL,
        )
        holding = (
            "select count(*) from pg_locks l join pg_stat_activity a using (pid)"
            f" where a.application_name = '{HOLDER}' and l.relation = '{table}'::regclass"
            " and l.mode = 'AccessShareLock' and l.granted"
        )

        def held(count: str) -> bool:
            assert self.proc.poll() is None, f"the reader of {table} ended before it held it"
            return count == "1"

        until(holding, held, f"the reader never held {table}")

    def release(self) -> None:
        mine = f"from pg_stat_activity where application_name = '{HOLDER}'"
        psql(BETA_DB, f"select pg_cancel_backend(pid) {mine}")
        self.proc.wait(timeout=30)


def waiting_for(table: str, other_than: str = "") -> str:
    """The server process of a lock request on `table` still waiting (another than `other_than`):
    an attempt of the rename, met by the reader."""
    waiting = (
        "select coalesce(string_agg(pid::text, ' '), '') from pg_locks"
        f" where relation = '{table}'::regclass and not granted"
    )
    pids = until(
        waiting,
        lambda got: any(pid != other_than for pid in got.split()),
        f"no attempt of the rename waited for {table}",
    )
    return next(pid for pid in pids.split() if pid != other_than)


@pytest.mark.parametrize("table", ["live.segment", "live.node"])
def test_a_reader_holding_a_served_table_delays_the_rename_but_does_not_fail_it(
    beta, table: str
) -> None:
    assert beta("--stage-only").returncode == 0
    # A long reader holds a lock the rename's ACCESS EXCLUSIVE waits for; lock_timeout makes
    # that an attempt, tried again. Every live table is locked, not segment alone: a join that
    # opened node first would otherwise read the old node beside the new segment.
    reader = Reader(table)
    ran: dict = {}
    swap = threading.Thread(target=lambda: ran.update(done=beta()))
    swap.start()
    try:
        # The reader goes once a second attempt is waiting for it: the first has given up.
        waiting_for(table, other_than=waiting_for(table))
    finally:
        reader.release()
        swap.join(120)
    done = ran["done"]

    assert done.returncode == 0, done.stderr
    assert "trying again" in done.stderr
    assert segments("live") == ["new road", "newer road", "newest road"]
    assert psql(BETA_DB, "select id from live.node") == "3"


def test_when_every_attempt_waits_too_long_nothing_changes(beta) -> None:
    assert beta("--stage-only").returncode == 0
    reader = Reader("live.segment")
    try:
        done = beta(RECEIVE_DATA_SWAP_TRIES="2", RECEIVE_DATA_LOCK_TIMEOUT_MS="500")
    finally:
        reader.release()

    assert done.returncode == 2 and "still serves the old live" in done.stderr
    assert segments("live") == ["old road"]
    assert segments("live_next") == ["new road", "newer road", "newest road"]
    assert psql(BETA_DB, "select count(*) from override") == "1"
    # and the next try reuses what was staged
    done = beta()
    assert done.returncode == 0 and "reusing live_next" in done.stderr, done.stderr


def test_a_second_update_retires_the_first(beta) -> None:
    assert beta().returncode == 0
    # the next bundle (the same rows here; a different dump, so it stages afresh)
    psql(BETA_DB, "comment on schema live_old is 'a mark that must not matter'")
    psql(BETA_DB, "create schema live_next; comment on schema live_next is 'bundle 0000'")

    done = beta()

    assert done.returncode == 0, done.stderr
    assert "reusing" not in done.stderr
    assert segments("live") == ["new road", "newer road", "newest road"]
    assert segments("live_old") == ["new road", "newer road", "newest road"]  # the first update's
    assert schemas() == {"live", "live_old"}


def test_two_updates_at_once_are_refused(beta, tmp_path: Path) -> None:
    # another run holding the lock, DATA_ROOT itself (flock(1) takes the kind of lock the
    # script does); nothing in /tmp another user could make or hold
    held = subprocess.Popen(["flock", "--shared", str(tmp_path / "data"), "sleep", "3"])
    time.sleep(0.5)
    done = beta("--stage-only")
    held.wait()

    assert done.returncode == 2 and "another receive-data.sh" in done.stderr
    assert schemas() == {"live"}


def test_a_road_panel_edit_during_the_swap_is_not_deadlocked(beta) -> None:
    """A road panel edit writes live.segment, then the stress tile cache (core.stress_edits
    and core.tile_cache). The swap takes its locks in that order, so the two queue rather
    than deadlock: both finish, the edit first."""
    assert beta("--stage-only").returncode == 0
    sql = (
        "begin; update live.segment set name = name; select pg_sleep(2);"
        " insert into stress_tile_cache (tile) values ('edit'); commit;"
    )
    edit = subprocess.Popen(
        ["psql", "-d", BETA_DB, "-Atq", "-v", "ON_ERROR_STOP=1", "-c", sql],
        stderr=subprocess.PIPE, text=True,
    )  # fmt: skip
    time.sleep(0.5)
    done = beta()
    _, edit_err = edit.communicate(timeout=60)

    assert edit.returncode == 0 and "deadlock" not in edit_err, edit_err
    assert done.returncode == 0 and "deadlock" not in done.stderr, done.stderr
    assert segments("live") == ["new road", "newer road", "newest road"]


def test_a_short_staged_table_is_refused_before_anything_is_renamed(beta, tmp_path: Path) -> None:
    counts = tmp_path / "incoming" / "db" / "row-counts.tsv"
    counts.write_text("live.segment\t4\npublic.override\t2\n")
    sums = tmp_path / "incoming" / "SHA256SUMS"
    digest = hashlib.sha256(counts.read_bytes()).hexdigest()
    sums.write_text(
        "\n".join(
            f"{digest}  db/row-counts.tsv" if line.endswith("row-counts.tsv") else line
            for line in sums.read_text().splitlines()
        )
        + "\n"
    )

    done = beta()

    assert done.returncode == 2 and "MISMATCH live_next.segment" in done.stderr
    assert segments("live") == ["old road"]
    assert psql(BETA_DB, "select count(*) from override") == "1"


# The release review of v0.18.0 (S6): the ways the update fails, each leaving the beta serving
# what it served.


def resum(tmp_path: Path) -> None:
    """The bundle's SHA256SUMS written again after a test changed a file in it."""
    bundle = tmp_path / "incoming"
    sums = ""
    for f in sorted(p for p in (bundle / "db").rglob("*") if p.is_file()):
        sums += f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.relative_to(bundle)}\n"
    (bundle / "SHA256SUMS").write_text(sums)


def no_scratch() -> bool:
    scratch = f"select count(*) from pg_database where datname = '{BETA_DB}_stage'"
    return psql("postgres", scratch) == "0"


def test_a_step_failing_inside_the_swap_rolls_the_rename_back_and_is_not_tried_again(
    beta, tmp_path: Path
) -> None:
    """'Rolls back cleanly if a step fails': a bad override row fails the one transaction
    after the rename; only lock contention is tried again."""
    assert beta("--stage-only").returncode == 0
    (tmp_path / "incoming" / "db" / "blanked" / "override.copy").write_text(
        "id\tkind\nnot-a-number\thome\n"
    )
    resum(tmp_path)

    done = beta()

    assert done.returncode != 0
    assert "the swap failed and was rolled back" in done.stderr
    assert "trying again" not in done.stderr
    assert "the swap is committed" not in done.stderr
    assert segments("live") == ["old road"]
    assert segments("live_next") == ["new road", "newer road", "newest road"]
    assert schemas() == {"live", "live_next"}
    assert psql(BETA_DB, "select string_agg(kind, ',') from override") == "beta's own"
    assert psql(BETA_DB, "select count(*) from stress_tile_cache") == "1"


def test_a_dump_cut_short_is_refused_and_nothing_is_staged(beta, tmp_path: Path) -> None:
    dump = tmp_path / "incoming" / "db" / "routemaker.dump"
    data = dump.read_bytes()
    dump.write_bytes(data[: len(data) - 200])
    resum(tmp_path)

    done = beta()

    assert done.returncode != 0
    assert segments("live") == ["old road"]
    assert schemas() == {"live"}
    assert no_scratch()
    assert psql(BETA_DB, "select count(*) from override") == "1"


def test_a_restore_that_fails_partway_leaves_no_scratch_database(beta, tmp_path: Path) -> None:
    """A dump whose table of contents reads but whose restore fails (a column of a type the
    dump's live entries do not carry): the scratch database is dropped on the way out."""
    psql(HOME_DB, "create type public.mood as enum ('calm')")
    psql(HOME_DB, "alter table live.node add m public.mood")
    dump = tmp_path / "incoming" / "db" / "routemaker.dump"
    subprocess.run(["pg_dump", "-d", HOME_DB, "--format=custom", "-f", str(dump)], check=True)
    resum(tmp_path)

    done = beta()

    assert done.returncode != 0
    assert "staging failed (above) and was discarded" in done.stderr
    assert no_scratch()
    assert segments("live") == ["old road"]
    assert schemas() == {"live"}
    assert psql(BETA_DB, "select count(*) from override") == "1"


def test_not_enough_room_to_stage_is_refused_and_changes_nothing(beta, tmp_path: Path) -> None:
    # df's stand-in: the data disk is full.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    df = bin_dir / "df"
    df.write_text("#!/usr/bin/env bash\necho Avail\necho 0\n")
    df.chmod(0o755)

    done = beta(PATH=f"{bin_dir}:{os.environ['PATH']}")

    assert done.returncode == 2 and "not enough room" in done.stderr, done.stderr
    assert segments("live") == ["old road"]
    assert schemas() == {"live"}
    assert no_scratch()
    assert psql(BETA_DB, "select count(*) from override") == "1"
