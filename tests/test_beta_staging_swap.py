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

    def run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(SCRIPT), "--bundle", str(bundle), "--env-file", str(env),
             "--allow-sha-mismatch", "db", "--update-data", *args],
            capture_output=True, text=True, check=False, timeout=300,
            env={**os.environ, "RECEIVE_DATA_REPO": str(checkout)},
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


def test_a_reader_holding_the_served_table_delays_the_rename_but_does_not_fail_it(beta) -> None:
    assert beta("--stage-only").returncode == 0
    # A long reader: an open transaction that has read live.segment holds a lock the rename's
    # ACCESS EXCLUSIVE waits for; lock_timeout makes that an attempt, tried again.
    held = threading.Event()

    def reader() -> None:
        sql = "begin; select count(*) from live.segment; select pg_sleep(5); commit;"
        proc = subprocess.Popen(["psql", "-d", BETA_DB, "-Atq", "-c", sql])
        time.sleep(1)
        held.set()
        proc.wait()

    t = threading.Thread(target=reader)
    t.start()
    held.wait()
    done = beta()
    t.join()

    assert done.returncode == 0, done.stderr
    assert "trying again" in done.stderr
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
