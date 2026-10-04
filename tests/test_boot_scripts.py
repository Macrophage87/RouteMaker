"""The boot scripts' wait and abort logic, against a fake `docker` and `curl`.

Nothing here touches Docker, the live stack or the real DATA_ROOT: the script is
pointed at a temporary DATA_ROOT, a temporary log directory and two shims on
BOOT_DOCKER / BOOT_CURL that record every call and answer from files. The fake
`docker run` honours its arguments: it maps each `-v SRC:DST` back to SRC and
runs the entrypoint on the host, so `test -f` and `cat` see the temporary tree.

These are unittest cases so they run under pytest (CI) and under plain
`python3 -m unittest tests.test_boot_scripts` on a host without pytest.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "boot" / "start-stack.sh"
INSTALL = REPO / "scripts" / "boot" / "install-boot-unit.sh"
UNIT_IN = REPO / "scripts" / "boot" / "routemaker-boot.service.in"
BASH = shutil.which("bash")

FAKE_DOCKER = r"""#!/usr/bin/env bash
# Fake docker. State lives in $FAKE_DIR: ps.txt ("service state health" lines),
# ps.fail_n (fail that many `compose ps` first), ps.fail_always,
# psql.out, psql.rc, psql.fail_n (fail that many execs first), psql.hang,
# up.hang_<svc>, up.sleep_<svc> (seconds), stop.hang,
# docker_up (exists = answers), never_healthy (exists), phantom/ (a stale view:
# every bind source S is read from phantom/S instead).
echo "$*" >>"$FAKE_DIR/calls.log"
echo "${RESTART_POLICY-<unset>}" >>"$FAKE_DIR/policy.log"
[ "$1" = info ] && { [ -e "$FAKE_DIR/docker_up" ]; exit; }
if [ "$1" = ps ]; then
  case "$*" in
    *"label=com.docker.compose.project=routemaker"*)
      printf 'aaa111 postgis\nbbb222 api\nccc333 migrate\n' ;;
    *) printf 'aaa111 postgis\nbbb222 api\nccc333 migrate\nzzz999 \n' ;;
  esac
  exit 0
fi
[ "$1" = update ] && exit 0
if [ "$1" = run ]; then
  shift
  ep=""
  maps=()
  while [ $# -gt 0 ]; do
    case "$1" in
      --rm) shift ;;
      --pull | --network) shift 2 ;;
      --entrypoint) ep=$2; shift 2 ;;
      -v) maps+=("$2"); shift 2 ;;
      -*) echo "fake docker run: unexpected $1" >&2; exit 125 ;;
      *) break ;;
    esac
  done
  shift # the image
  [ -n "$ep" ] || exit 125
  args=()
  for a in "$@"; do
    for m in "${maps[@]}"; do
      src=${m%%:*}
      rest=${m#*:}
      dst=${rest%%:*}
      [ -e "$FAKE_DIR/phantom" ] && src="$FAKE_DIR/phantom$src"
      case "$a" in "$dst" | "$dst"/*) a="$src${a#"$dst"}" ;; esac
    done
    args+=("$a")
  done
  exec "$ep" "${args[@]}"
fi
[ "$1" = compose ] || exit 0
shift
while [ $# -gt 0 ]; do
  case "$1" in
    --project-name|--project-directory|--env-file|-f) shift 2 ;;
    *) break ;;
  esac
done
sub=$1; shift
case "$sub" in
  ps)
    [ -e "$FAKE_DIR/ps.fail_always" ] && { echo "Cannot connect to the Docker daemon" >&2; exit 1; }
    if [ -s "$FAKE_DIR/ps.seq" ]; then
      read -r first rest <"$FAKE_DIR/ps.seq"
      printf '%s' "$rest" >"$FAKE_DIR/ps.seq"
      [ "$first" = fail ] && { echo "Cannot connect to the Docker daemon" >&2; exit 1; }
    fi
    n=$(cat "$FAKE_DIR/ps.fail_n" 2>/dev/null || echo 0)
    if [ "$n" -gt 0 ]; then
      echo $((n - 1)) >"$FAKE_DIR/ps.fail_n"
      echo "Cannot connect to the Docker daemon" >&2
      exit 1
    fi
    cat "$FAKE_DIR/ps.txt" ;;
  config) echo "docker.io/library/caddy:2.8-alpine"; echo "docker.io/postgis/postgis:16-3.4" ;;
  exec)
    [ -e "$FAKE_DIR/psql.hang" ] && exec sleep 30
    n=$(cat "$FAKE_DIR/psql.fail_n" 2>/dev/null || echo 0)
    if [ "$n" -gt 0 ]; then
      echo $((n - 1)) >"$FAKE_DIR/psql.fail_n"
      echo "Error response from daemon: container is restarting"
      exit 1
    fi
    cat "$FAKE_DIR/psql.out" 2>/dev/null; exit "$(cat "$FAKE_DIR/psql.rc" 2>/dev/null || echo 0)" ;;
  up)
    svc=${*: -1}
    [ -e "$FAKE_DIR/up.hang_$svc" ] && exec sleep 30
    [ -e "$FAKE_DIR/up.sleep_$svc" ] && sleep "$(cat "$FAKE_DIR/up.sleep_$svc")"
    sed -i "/^$svc /d" "$FAKE_DIR/ps.txt"
    if [ "$svc" = postgis ] && [ -e "$FAKE_DIR/never_healthy" ]; then
      echo "postgis running starting" >>"$FAKE_DIR/ps.txt"
    elif [ "$svc" = postgis ]; then
      echo "postgis running healthy" >>"$FAKE_DIR/ps.txt"
    else
      echo "$svc running " >>"$FAKE_DIR/ps.txt"
    fi ;;
  stop)
    [ -e "$FAKE_DIR/stop.hang" ] && exec sleep 30
    for s in "$@"; do sed -i "/^$s /d" "$FAKE_DIR/ps.txt"; done ;;
esac
exit 0
"""

FAKE_CURL = r"""#!/usr/bin/env bash
# Prints "HTTP_CODE BYTES" from code_<kind> and size_<kind> (200 and 2048 by default).
echo "$*" >>"$FAKE_DIR/curl.log"
case "$*" in
  *api/route*) k=route ;;
  *api/geocode*) k=geocode ;;
  *tiles/*) k=tile ;;
  *) k=other ;;
esac
printf '%s %s' "$(cat "$FAKE_DIR/code_$k" 2>/dev/null || echo 200)" \
  "$(cat "$FAKE_DIR/size_$k" 2>/dev/null || echo 2048)"
"""

REQUIRED = [
    "backups basemap caddy elevation extracts frontend photon postgres rebuild "
    "reference static tiles tiles/standard tiles/no-trail tiles/ebike tiles/weekend"
][0].split()

ALL_SERVICES = [
    "postgis",
    "caddy",
    "valhalla-standard",
    "valhalla-no-trail",
    "valhalla-ebike",
    "valhalla-weekend",
    "api",
    "worker",
    "rebuild",
    "photon",
]

# Variables of the caller's shell that would leak into the script under test.
HOST_LEAKS = ("RESTART_POLICY", "COMPOSE_PROJECT", "COMPOSE_PROJECT_NAME")


def write_exec(path: Path, text: str) -> None:
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class FakeHost(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="boot-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.data = self.tmp / "data"
        self.fake = self.tmp / "fake"
        self.logs = self.tmp / "logs"
        self.fake.mkdir()
        for d in REQUIRED:
            (self.data / d).mkdir(parents=True)
        (self.data / "postgres" / "PG_VERSION").write_text("16\n")
        (self.fake / "docker_up").write_text("")
        (self.fake / "ps.txt").write_text("")
        (self.fake / "psql.out").write_text("68 1359193")
        write_exec(self.fake / "docker", FAKE_DOCKER)
        write_exec(self.fake / "curl", FAKE_CURL)
        self.env_file = self.tmp / ".env"
        self.write_env()

    def write_env(self, data_root: str | None = None, project: str | None = "routemaker") -> None:
        lines = [
            f"DATA_ROOT={data_root if data_root is not None else self.data}",
            "RESTART_POLICY=no",
        ]
        if project is not None:
            lines.insert(0, f"COMPOSE_PROJECT_NAME={project}")
        self.env_file.write_text("\n".join(lines) + "\n")

    def env(self, **overrides: str) -> dict[str, str]:
        base = {k: v for k, v in os.environ.items() if k not in HOST_LEAKS}
        return {
            **base,
            "FAKE_DIR": str(self.fake),
            "BOOT_DOCKER": str(self.fake / "docker"),
            "BOOT_CURL": str(self.fake / "curl"),
            "BOOT_ENV_FILE": str(self.env_file),
            "BOOT_LOG_DIR": str(self.logs),
            "BOOT_POLL_S": "0.2",
            "BOOT_WAIT_PREREQ_S": "1",
            "BOOT_POSTGIS_HEALTHY_S": "1",
            "BOOT_SMOKE_S": "1",
            "BOOT_SANE_GAP_S": "0.1",
            "BOOT_SNAP_GAP_S": "0.1",
            **overrides,
        }

    def calls(self) -> list[str]:
        path = self.fake / "calls.log"
        return path.read_text().splitlines() if path.exists() else []

    def mutating(self) -> list[str]:
        return [
            c
            for c in self.calls()
            if re.search(r" (up|stop|down|rm|restart|kill|update) ", f" {c} ")
        ]

    def ups(self) -> list[str]:
        return [c.split()[-1] for c in self.calls() if " up " in c]


@unittest.skipUnless(BASH, "bash is required")
class StartStackTests(FakeHost):
    def run_script(self, *args: str, **overrides: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [BASH, str(SCRIPT), *args],
            env=self.env(**overrides),
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )

    def status(self) -> str:
        return (self.logs / "last-status").read_text()

    def warm(self) -> None:
        (self.fake / "ps.txt").write_text(
            "postgis running healthy\napi running healthy\nworker running \n"
            "rebuild running \ncaddy running \nvalhalla-standard running \n"
            "valhalla-no-trail running \nvalhalla-ebike running \n"
            "valhalla-weekend running \nphoton running healthy\nmigrate exited \n"
        )

    # ---- waiting

    def test_times_out_when_docker_never_answers(self) -> None:
        (self.fake / "docker_up").unlink()
        done = self.run_script()
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("Docker did not answer", done.stdout)
        self.assertEqual(self.mutating(), [])
        self.assertTrue(self.status().startswith("FAILED"))

    def test_times_out_when_a_bind_dir_is_missing_and_names_it(self) -> None:
        shutil.rmtree(self.data / "tiles" / "ebike")
        done = self.run_script()
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("tiles/ebike", done.stdout)
        self.assertEqual(self.mutating(), [])

    def test_refuses_to_start_postgis_when_docker_sees_no_cluster(self) -> None:
        (self.data / "postgres" / "PG_VERSION").unlink()
        done = self.run_script()
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("PG_VERSION", done.stdout)
        self.assertEqual(
            self.mutating(), [], "nothing is stopped or started when the bind is wrong"
        )

    def test_pg_version_must_be_a_file_not_a_directory(self) -> None:
        (self.data / "postgres" / "PG_VERSION").unlink()
        (self.data / "postgres" / "PG_VERSION").mkdir()
        done = self.run_script()
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertEqual(self.ups(), [])

    def test_the_cluster_check_runs_in_a_throwaway_read_only_container(self) -> None:
        self.run_script()
        runs = [c for c in self.calls() if c.startswith("run ")]
        self.assertEqual(len(runs), 2, runs)
        for r in runs:
            self.assertIn("--pull never", r)
            self.assertIn("--network none", r)
            self.assertIn("--rm", r)
        self.assertIn(":/bootcheck:ro", runs[0])
        self.assertIn(":/pgcheck:ro", runs[1])

    def test_waits_for_paths_that_appear_late(self) -> None:
        shutil.rmtree(self.data / "tiles" / "weekend")
        late = subprocess.Popen([BASH, "-c", f"sleep 1; mkdir -p '{self.data}/tiles/weekend'"])
        self.addCleanup(late.wait)
        done = self.run_script(BOOT_WAIT_PREREQ_S="10", BOOT_SMOKE_S="2")
        self.assertEqual(done.returncode, 0, done.stdout)

    def test_the_bind_check_gets_only_what_is_left_of_the_shared_budget(self) -> None:
        # A path that appears 5 s into a 6 s budget, then a phantom that never
        # clears: the bind check gets the ~1 s that is left, not a fresh 6 s.
        shutil.rmtree(self.data / "tiles" / "weekend")
        self.make_phantom()
        late = subprocess.Popen([BASH, "-c", f"sleep 5; mkdir -p '{self.data}/tiles/weekend'"])
        self.addCleanup(late.wait)
        started = time.monotonic()
        done = self.run_script(BOOT_WAIT_PREREQ_S="6")
        elapsed = time.monotonic() - started
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("is not the real one after 6s", done.stdout)
        self.assertIn("all 16 bind dirs exist", done.stdout)
        self.assertLess(elapsed, 8.5, "the bind check was given a fresh budget")
        self.assertEqual(self.mutating(), [])

    def test_refuses_without_an_env_file(self) -> None:
        self.env_file.unlink()
        done = self.run_script()
        self.assertEqual(done.returncode, 1)
        self.assertIn("no env file", done.stdout)
        self.assertEqual(self.calls(), [])

    # ---- the bind token (a phantom view that already holds a cluster)

    def make_phantom(self) -> Path:
        ghost = self.fake / "phantom" / str(self.data).lstrip("/")
        (ghost / "postgres").mkdir(parents=True)
        (ghost / "postgres" / "PG_VERSION").write_text("16\n")
        (ghost / ".boot-token").write_text("token-from-an-earlier-boot")
        return ghost

    def test_a_phantom_path_with_an_old_cluster_is_refused(self) -> None:
        self.make_phantom()
        done = self.run_script()
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("phantom", done.stdout)
        self.assertEqual(self.mutating(), [])

    def test_a_phantom_that_clears_is_waited_for_not_fatal(self) -> None:
        self.make_phantom()
        clear = subprocess.Popen([BASH, "-c", f"sleep 1; rm -rf '{self.fake}/phantom'"])
        self.addCleanup(clear.wait)
        done = self.run_script(BOOT_WAIT_PREREQ_S="10", BOOT_SMOKE_S="2")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(self.ups(), ALL_SERVICES)

    def test_every_cold_run_writes_a_fresh_token(self) -> None:
        self.run_script()
        first = (self.data / ".boot-token").read_text()
        self.assertRegex(first, r"^[0-9a-f]{32}$")
        (self.fake / "ps.txt").write_text("")
        self.run_script()
        self.assertNotEqual((self.data / ".boot-token").read_text(), first)

    # ---- the bind-race abort

    def test_cold_start_orders_postgis_first_then_the_rest(self) -> None:
        done = self.run_script()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        ups = [c for c in self.calls() if " up " in c]
        self.assertEqual(self.ups(), ALL_SERVICES)
        for line in ups:
            self.assertIn("--no-deps", line)
            self.assertIn("--force-recreate", line)
            self.assertIn("-d", line.split())
        stops = [c for c in self.calls() if " stop " in c]
        self.assertTrue(stops and stops[0].endswith("stop api worker rebuild"))
        calls = self.calls()
        self.assertLess(calls.index(stops[0]), calls.index(ups[0]))
        # The bind checks come before anything is stopped.
        first_run = next(i for i, c in enumerate(calls) if c.startswith("run "))
        self.assertLess(first_run, calls.index(stops[0]))
        self.assertTrue(self.status().startswith("OK"))

    def test_every_compose_call_names_the_env_file_and_project(self) -> None:
        self.run_script()
        compose = [c for c in self.calls() if c.startswith("compose")]
        self.assertTrue(compose)
        for c in compose:
            self.assertIn(f"--env-file {self.env_file}", c)
            self.assertIn("--project-name routemaker", c)

    def test_every_docker_call_sees_restart_policy_no(self) -> None:
        # Even when the caller's shell exports the racy policy.
        done = self.run_script(RESTART_POLICY="unless-stopped")
        self.assertEqual(done.returncode, 0, done.stdout)
        seen = (self.fake / "policy.log").read_text().split()
        self.assertTrue(seen)
        self.assertEqual(set(seen), {"no"})

    def test_never_a_plain_up(self) -> None:
        self.run_script()
        for c in self.calls():
            if " up " in c:
                self.assertIn("--no-deps", c, c)
        self.assertNotIn("down", " ".join(self.calls()).split())
        self.assertNotIn("migrate", " ".join(self.calls()))

    def test_empty_postgis_aborts_and_starts_nothing_else(self) -> None:
        (self.fake / "psql.out").write_text('ERROR:  relation "django_migrations" does not exist')
        (self.fake / "psql.rc").write_text("1")
        done = self.run_script()
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("ABORTED", done.stdout)
        self.assertIn("EMPTY", done.stdout)
        self.assertEqual(self.ups(), ["postgis"])
        self.assertTrue(self.status().startswith("FAILED"))
        self.assertNotIn("postgis running", (self.fake / "ps.txt").read_text())

    def test_short_segment_table_is_the_same_abort(self) -> None:
        (self.fake / "psql.out").write_text("68 60")
        done = self.run_script()
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertEqual(self.ups(), ["postgis"])

    def test_too_few_migrations_aborts(self) -> None:
        (self.fake / "psql.out").write_text("0 1359193")
        done = self.run_script()
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertEqual(self.ups(), ["postgis"])

    def check_threshold(self, numbers: str, ok: bool) -> None:
        (self.fake / "psql.out").write_text(numbers)
        done = self.run_script()
        if ok:
            self.assertEqual(done.returncode, 0, done.stdout)
            self.assertEqual(self.ups(), ALL_SERVICES)
        else:
            self.assertEqual(done.returncode, 1, done.stdout)
            self.assertEqual(self.ups(), ["postgis"])

    def test_67_migrations_is_one_short(self) -> None:
        self.check_threshold("67 1359193", ok=False)

    def test_68_migrations_is_enough(self) -> None:
        self.check_threshold("68 1359193", ok=True)

    def test_999999_segments_is_one_short(self) -> None:
        self.check_threshold("68 999999", ok=False)

    def test_a_million_segments_is_enough(self) -> None:
        self.check_threshold("68 1000000", ok=True)

    def test_postgis_never_healthy_aborts(self) -> None:
        (self.fake / "never_healthy").write_text("")
        done = self.run_script()
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("not healthy", done.stdout)
        self.assertEqual(self.ups(), ["postgis"])

    def test_racy_postgis_running_empty_is_recovered_not_trusted(self) -> None:
        # Docker auto-started postgis on a phantom path: running, healthy, empty.
        (self.fake / "ps.txt").write_text("postgis running healthy\napi running healthy\n")
        (self.fake / "psql.out").write_text("0 0")
        (self.fake / "psql.rc").write_text("0")
        # After the force-recreate the real cluster answers.
        write_exec(
            self.fake / "docker",
            FAKE_DOCKER.replace(
                '    [ -e "$FAKE_DIR/psql.hang" ]',
                '    [ -e "$FAKE_DIR/recreated" ] && echo "68 1359193" >"$FAKE_DIR/psql.out"\n'
                '    [ -e "$FAKE_DIR/psql.hang" ]',
            ).replace("  up)\n", '  up)\n    touch "$FAKE_DIR/recreated"\n'),
        )
        done = self.run_script()
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("mode: COLD", done.stdout)
        self.assertIn("bind-race signature", done.stdout)

    def test_a_hung_psql_is_bounded(self) -> None:
        (self.fake / "ps.txt").write_text("postgis running healthy\n")
        (self.fake / "psql.hang").write_text("")
        started = time.monotonic()
        done = self.run_script(BOOT_EXEC_TIMEOUT_S="1")
        self.assertLess(time.monotonic() - started, 25)
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("psql failed", done.stdout)

    def execs(self) -> list[str]:
        return [c for c in self.calls() if c.startswith("compose") and " exec " in c]

    def test_a_slow_first_query_after_the_recreate_is_retried(self) -> None:
        # Cold page cache right after a reboot: the first two queries fail.
        (self.fake / "psql.fail_n").write_text("2")
        done = self.run_script()
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("try 2 of 3", done.stdout)
        self.assertEqual(self.ups(), ALL_SERVICES)
        self.assertEqual(len(self.execs()), 3)

    def test_an_empty_cluster_after_the_recreate_fails_every_try(self) -> None:
        (self.fake / "psql.out").write_text("0 0")
        done = self.run_script()
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("EMPTY", done.stdout)
        self.assertEqual(len(self.execs()), 3, "all three tries are spent before the abort")
        self.assertEqual(self.ups(), ["postgis"])
        self.assertNotIn("postgis running", (self.fake / "ps.txt").read_text())

    def test_a_mutating_call_that_times_out_dies_clearly(self) -> None:
        (self.fake / "up.hang_caddy").write_text("")
        started = time.monotonic()
        done = self.run_script(BOOT_COMPOSE_TIMEOUT_S="1")
        self.assertLess(time.monotonic() - started, 25)
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("did not finish within 1s", done.stdout)
        self.assertIn("_routemaker-", done.stdout)
        self.assertNotIn("unexpected error", done.stdout)
        self.assertEqual(
            self.ups(), ["postgis", "caddy"], "nothing after the timed-out call is started"
        )
        self.assertTrue(self.status().startswith("FAILED"))
        self.assertIn("did not finish", self.status())

    def test_the_routers_and_photon_get_the_longer_limit(self) -> None:
        # Read the limit each `up` was given off the fake's parent, the `timeout`
        # that runs it, rather than racing a short limit against a sleep, so a
        # busy runner cannot flake. (The script puts the system dirs first on
        # PATH, so a `timeout` shim would not be picked up.)
        logged = 'echo "$*" >>"$FAKE_DIR/calls.log"\n'
        parent = 'tr "\\0" " " </proc/$PPID/cmdline >>"$FAKE_DIR/parent.log"\n'
        parent += 'echo >>"$FAKE_DIR/parent.log"\n'
        write_exec(self.fake / "docker", FAKE_DOCKER.replace(logged, logged + parent))
        done = self.run_script(BOOT_COMPOSE_TIMEOUT_S="111", BOOT_SLOW_COMPOSE_TIMEOUT_S="333")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(self.ups(), ALL_SERVICES)
        limits = {}
        for line in (self.fake / "parent.log").read_text().splitlines():
            words = line.split()
            if " up -d " in line:
                self.assertEqual(Path(words[0]).name, "timeout", line)
                limits[words[-1]] = words[1]
        slow = {
            "valhalla-standard",
            "valhalla-no-trail",
            "valhalla-ebike",
            "valhalla-weekend",
            "photon",
        }
        self.assertEqual(limits, {svc: "333" if svc in slow else "111" for svc in ALL_SERVICES})

    def test_the_other_services_keep_the_short_limit(self) -> None:
        (self.fake / "up.sleep_api").write_text("3")
        done = self.run_script(BOOT_COMPOSE_TIMEOUT_S="1", BOOT_SLOW_COMPOSE_TIMEOUT_S="6")
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("up -d --no-deps --force-recreate api' did not finish within 1s", done.stdout)

    def test_a_timed_out_stop_on_the_abort_path_keeps_the_abort_message(self) -> None:
        (self.fake / "psql.out").write_text("0 0")
        write_exec(
            self.fake / "docker",
            FAKE_DOCKER.replace("  up)\n", '  up)\n    touch "$FAKE_DIR/stop.hang"\n'),
        )
        done = self.run_script(BOOT_COMPOSE_TIMEOUT_S="1")
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("EMPTY", done.stdout)
        self.assertIn("stopping postgis failed", done.stdout)
        self.assertIn("EMPTY", self.status())

    # ---- warm path

    def test_warm_stack_is_left_alone(self) -> None:
        self.warm()
        done = self.run_script()
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("mode: WARM", done.stdout)
        self.assertEqual(self.mutating(), [])

    def test_warm_stack_starts_only_what_is_down(self) -> None:
        self.warm()
        text = (
            (self.fake / "ps.txt")
            .read_text()
            .replace("photon running healthy\n", "photon exited \n")
        )
        (self.fake / "ps.txt").write_text(text)
        done = self.run_script()
        self.assertEqual(done.returncode, 0, done.stdout)
        ups = [c for c in self.calls() if " up " in c]
        self.assertEqual(len(ups), 1)
        self.assertTrue(ups[0].endswith("up -d --no-deps photon"), ups[0])
        self.assertNotIn("--force-recreate", ups[0])

    def test_a_transient_sanity_failure_on_a_warm_stack_is_retried(self) -> None:
        self.warm()
        (self.fake / "psql.fail_n").write_text("2")
        done = self.run_script()
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("mode: WARM", done.stdout)
        self.assertIn("try 2 of 3", done.stdout)
        self.assertEqual(self.mutating(), [])

    def test_cold_is_refused_while_rebuild_runs(self) -> None:
        self.warm()
        (self.fake / "psql.fail_n").write_text("3")
        done = self.run_script()
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("rebuild is running", done.stdout)
        self.assertEqual(self.mutating(), [])
        self.assertEqual([c for c in self.calls() if c.startswith("run ")], [])
        self.assertTrue(self.status().startswith("FAILED"))

    def test_cold_with_rebuild_running_needs_force(self) -> None:
        self.warm()
        (self.fake / "psql.fail_n").write_text("3")
        done = self.run_script("--force-recreate-all")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("mode: COLD", done.stdout)
        self.assertEqual(self.ups(), ALL_SERVICES)

    # ---- a failed `compose ps` is never "nothing running"

    def test_ps_failing_twice_while_rebuild_runs_mutates_nothing(self) -> None:
        self.warm()
        (self.fake / "ps.fail_n").write_text("2")
        done = self.run_script()
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("ps failed (try 2 of 3)", done.stdout)
        self.assertIn("mode: WARM", done.stdout)
        self.assertEqual(self.mutating(), [])
        self.assertEqual([c for c in self.calls() if c.startswith("run ")], [])

    def test_ps_failing_twice_still_lets_the_rebuild_guard_see_rebuild(self) -> None:
        # Sanity fails too, so the mode is COLD: the guard must still fire.
        self.warm()
        (self.fake / "ps.fail_n").write_text("2")
        (self.fake / "psql.fail_n").write_text("3")
        done = self.run_script()
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("rebuild is running", done.stdout)
        self.assertEqual(self.mutating(), [])

    def test_the_mode_comes_from_the_ps_that_succeeded(self) -> None:
        # One good ps, then failures: no second ps may decide the mode.
        self.warm()
        text = (self.fake / "ps.txt").read_text().replace("rebuild running \n", "rebuild exited \n")
        (self.fake / "ps.txt").write_text(text)
        (self.fake / "ps.seq").write_text("ok fail fail fail fail")
        done = self.run_script()
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("mode: WARM", done.stdout)
        self.assertEqual(self.ups(), ["rebuild"])
        self.assertNotIn("stop", " ".join(self.mutating()))

    def test_persistent_ps_failure_on_a_warm_stack_mutates_nothing(self) -> None:
        self.warm()
        (self.fake / "ps.fail_always").write_text("")
        done = self.run_script()
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("cannot read stack state", done.stdout)
        self.assertNotIn("mode:", done.stdout)
        self.assertEqual(self.mutating(), [])
        self.assertEqual([c for c in self.calls() if c.startswith("run ")], [])
        self.assertEqual(
            len([c for c in self.calls() if c.startswith("compose") and " ps " in c]), 3
        )
        self.assertTrue(self.status().startswith("FAILED"))
        self.assertIn("running", (self.fake / "ps.txt").read_text())

    def test_persistent_ps_failure_with_warm_only_is_the_same(self) -> None:
        self.warm()
        (self.fake / "ps.fail_always").write_text("")
        done = self.run_script("--warm-only")
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("cannot read stack state", done.stdout)
        self.assertEqual(self.mutating(), [])

    def test_a_failed_ps_while_waiting_for_healthy_keeps_polling(self) -> None:
        write_exec(
            self.fake / "docker",
            FAKE_DOCKER.replace(
                "  up)\n", '  up)\n    [ "${*: -1}" = postgis ] && echo 2 >"$FAKE_DIR/ps.fail_n"\n'
            ),
        )
        done = self.run_script(BOOT_POSTGIS_HEALTHY_S="10")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("postgis state unknown, still waiting", done.stdout)
        self.assertEqual(self.ups(), ALL_SERVICES)

    # ---- --warm-only (for a later watchdog)

    def test_warm_only_starts_only_what_is_stopped(self) -> None:
        self.warm()
        text = (self.fake / "ps.txt").read_text().replace("worker running \n", "worker exited \n")
        (self.fake / "ps.txt").write_text(text)
        done = self.run_script("--warm-only")
        self.assertEqual(done.returncode, 0, done.stdout)
        ups = [c for c in self.calls() if " up " in c]
        self.assertEqual([u.split()[-1] for u in ups], ["worker"])
        self.assertNotIn("--force-recreate", ups[0])
        self.assertTrue(self.status().startswith("OK"))
        self.assertIn("WARM-ONLY", self.status())

    def test_warm_only_never_takes_the_cold_path(self) -> None:
        (self.fake / "ps.txt").write_text("postgis exited \n")
        done = self.run_script("--warm-only")
        self.assertEqual(done.returncode, 3, done.stdout)
        self.assertEqual(self.mutating(), [])
        self.assertEqual([c for c in self.calls() if c.startswith("run ")], [])

    def test_warm_only_and_force_contradict(self) -> None:
        done = self.run_script("--warm-only", "--force-recreate-all")
        self.assertEqual(done.returncode, 64)
        self.assertEqual(self.calls(), [])

    # ---- project name

    def test_refuses_when_env_names_no_project(self) -> None:
        self.write_env(project=None)
        done = self.run_script()
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("COMPOSE_PROJECT_NAME", done.stdout)
        self.assertEqual(self.calls(), [])

    def test_refuses_a_project_override_that_disagrees_with_env(self) -> None:
        done = self.run_script(COMPOSE_PROJECT="other")
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertEqual(self.calls(), [])
        done = self.run_script(COMPOSE_PROJECT_NAME="other")
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertEqual(self.calls(), [])

    def test_the_project_name_comes_from_env(self) -> None:
        self.write_env(project="rmx")
        done = self.run_script()
        self.assertEqual(done.returncode, 0, done.stdout)
        for c in self.calls():
            if c.startswith("compose"):
                self.assertIn("--project-name rmx", c)

    def test_single_quoted_env_values_are_read(self) -> None:
        self.env_file.write_text(
            f"COMPOSE_PROJECT_NAME='routemaker'\nDATA_ROOT='{self.data}'\nRESTART_POLICY=no\n"
        )
        done = self.run_script()
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn(f"DATA_ROOT={self.data} project=routemaker", done.stdout)

    # ---- smoke and dry-run

    def test_smoke_failure_exits_2_after_the_stack_is_up(self) -> None:
        (self.fake / "code_geocode").write_text("502")
        done = self.run_script()
        self.assertEqual(done.returncode, 2, done.stdout)
        self.assertIn("geocode=502", done.stdout)
        self.assertTrue(self.status().startswith("FAILED"))

    def test_a_failing_route_fails_the_smoke(self) -> None:
        (self.fake / "code_route").write_text("500")
        done = self.run_script()
        self.assertEqual(done.returncode, 2, done.stdout)
        self.assertIn("route=500", done.stdout)

    def test_a_failing_tile_fails_the_smoke(self) -> None:
        (self.fake / "code_tile").write_text("404")
        done = self.run_script()
        self.assertEqual(done.returncode, 2, done.stdout)
        self.assertIn("tile=404", done.stdout)

    def test_an_empty_tile_fails_the_smoke(self) -> None:
        (self.fake / "size_tile").write_text("0")
        done = self.run_script()
        self.assertEqual(done.returncode, 2, done.stdout)
        self.assertIn("tile=200 (0 bytes)", done.stdout)

    def test_dry_run_changes_nothing_and_skips_smoke(self) -> None:
        done = self.run_script("--dry-run")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(self.mutating(), [])
        self.assertIn(
            "DRYRUN: docker compose up -d --no-deps --force-recreate postgis", done.stdout
        )
        self.assertFalse((self.fake / "curl.log").exists())
        self.assertFalse((self.logs / "last-status").exists())
        self.assertFalse((self.data / ".boot-token").exists())

    # ---- lock and status

    def test_a_second_concurrent_run_is_refused_and_writes_nothing(self) -> None:
        self.logs.mkdir()
        (self.logs / "last-status").write_text("OK earlier mode=COLD\n")
        (self.logs / "previous.log").write_text("")
        os.symlink(self.logs / "previous.log", self.logs / "latest.log")
        holder = subprocess.Popen(
            [BASH, "-c", f"exec 9>'{self.logs}/.lock'; flock 9; exec sleep 10"]
        )
        self.addCleanup(holder.wait)
        self.addCleanup(holder.kill)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            probe = subprocess.run(["flock", "-n", str(self.logs / ".lock"), "true"], check=False)
            if probe.returncode != 0:
                break
            time.sleep(0.05)
        done = self.run_script()
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("refused", done.stdout)
        self.assertEqual(self.status(), "OK earlier mode=COLD\n")
        self.assertEqual(os.readlink(self.logs / "latest.log"), str(self.logs / "previous.log"))
        self.assertEqual(list(self.logs.glob("start-stack-*.log")), [])
        self.assertEqual(self.calls(), [])

    def test_sigterm_records_failed_not_the_old_status(self) -> None:
        (self.fake / "docker_up").unlink()
        self.logs.mkdir()
        (self.logs / "last-status").write_text("OK earlier mode=COLD\n")
        proc = subprocess.Popen(
            [BASH, str(SCRIPT)],
            env=self.env(BOOT_WAIT_PREREQ_S="30"),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not self.status().startswith("RUNNING"):
            time.sleep(0.05)
        self.assertTrue(self.status().startswith("RUNNING"), self.status())
        proc.send_signal(signal.SIGTERM)
        out, _ = proc.communicate(timeout=20)
        self.assertEqual(proc.returncode, 143, out)
        self.assertTrue(self.status().startswith("FAILED"), self.status())
        self.assertIn("SIGTERM", self.status())


@unittest.skipUnless(BASH, "bash is required")
class PolicyTests(FakeHost):
    def policy(self, *args: str, **overrides: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [BASH, str(INSTALL), "policy", *args],
            env=self.env(**overrides),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def updates(self) -> list[str]:
        return [c for c in self.calls() if c.startswith("update ")]

    def test_only_the_projects_containers_and_never_migrate(self) -> None:
        done = self.policy("unless-stopped")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.updates(), ["update --restart=unless-stopped aaa111 bbb222"])
        listing = [c for c in self.calls() if c.startswith("ps ")]
        self.assertIn("label=com.docker.compose.project=routemaker", listing[0])

    def test_policy_no(self) -> None:
        done = self.policy("no")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.updates(), ["update --restart=no aaa111 bbb222"])

    def test_rejects_any_other_value(self) -> None:
        for bad in ("always", "on-failure", ""):
            done = self.policy(bad) if bad else self.policy()
            self.assertEqual(done.returncode, 64, bad)
        self.assertEqual(self.calls(), [])

    def test_refuses_without_a_project_name(self) -> None:
        self.write_env(project=None)
        done = self.policy("no")
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(self.updates(), [])


class StaticChecks(unittest.TestCase):
    def test_script_waits_for_every_data_root_bind_in_compose(self) -> None:
        compose = (REPO / "compose.yaml").read_text()
        bound = set(re.findall(r"\$\{DATA_ROOT\}/([A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)?)", compose))
        script = SCRIPT.read_text()
        block = re.search(r"REQUIRED_DIRS=\((.*?)\)", script, re.S)
        assert block is not None
        listed = set(block.group(1).split())
        self.assertEqual(
            sorted(bound - listed), [], "compose binds dirs the boot script does not wait for"
        )

    def test_start_order_covers_every_resident_service(self) -> None:
        import yaml

        services = yaml.safe_load((REPO / "compose.yaml").read_text())["services"]
        resident = {
            name
            for name, svc in services.items()
            if name not in {"migrate", "postgis"} and not svc.get("profiles")
        }
        script = SCRIPT.read_text()
        order = re.search(r"START_ORDER=\((.*?)\)", script, re.S)
        assert order is not None
        self.assertEqual(resident, set(order.group(1).split()))

    def test_no_plain_up_or_docker_desktop_reset_in_the_scripts(self) -> None:
        for path in (SCRIPT, INSTALL):
            code = "\n".join(
                line for line in path.read_text().splitlines() if not line.lstrip().startswith("#")
            )
            executed = "\n".join(
                line for line in code.splitlines() if not line.lstrip().startswith(("echo", "log"))
            )
            self.assertNotRegex(executed, r"\bsudo\b", path.name)
            self.assertNotRegex(code, r"wsl(\.exe)?\s+--(shutdown|terminate)", path.name)
            self.assertNotRegex(code, r"(taskkill|Docker Desktop\.exe)", path.name)
            self.assertNotRegex(code, r"compose[^\n]*\bdown\b", path.name)
            for line in code.splitlines():
                if re.search(r"\bup\b\s+-d", line):
                    self.assertIn("--no-deps", line, line)

    def test_unit_template_is_a_boot_oneshot(self) -> None:
        text = UNIT_IN.read_text()
        self.assertIn("WantedBy=default.target", text)
        self.assertIn("Type=oneshot", text)
        self.assertIn("ExecStart=@REPO@/scripts/boot/start-stack.sh", text)
        self.assertNotRegex(text, r"(?m)^User=")  # a user unit; User= would be refused

    def test_unit_timeout_is_above_the_scripts_worst_case(self) -> None:
        script = SCRIPT.read_text()

        def default(name: str) -> int:
            m = re.search(rf"\$\{{BOOT_{name}:-(\d+)\}}", script)
            assert m is not None, name
            return int(m.group(1))

        def array(name: str) -> list[str]:
            m = re.search(rf"{name}=\((.*?)\)", script, re.S)
            assert m is not None, name
            return m.group(1).split()

        start = array("START_ORDER")
        slow = [s for s in start if s in array("SLOW_SERVICES")]
        self.assertTrue(slow)
        sanity = default("SANE_TRIES") * default("EXEC_TIMEOUT_S") + (
            default("SANE_TRIES") - 1
        ) * default("SANE_GAP_S")
        worst = (
            # shared budget, a 60 s `docker info` past its end, one full bind check
            default("WAIT_PREREQ_S")
            + 60
            + 3 * 60
            + default("POLL_S")
            + default("SNAP_TRIES") * 30
            + (default("SNAP_TRIES") - 1) * default("SNAP_GAP_S")
            + sanity  # before the mode
            + 2 * default("COMPOSE_TIMEOUT_S")  # stop clients, postgis
            + (len(start) - len(slow)) * default("COMPOSE_TIMEOUT_S")
            + len(slow) * default("SLOW_COMPOSE_TIMEOUT_S")
            + default("POSTGIS_HEALTHY_S")
            + 30
            + default("POLL_S")
            + sanity  # after the recreate
            + default("SMOKE_S")
            + 3 * 90
            + default("POLL_S")
        )
        unit = UNIT_IN.read_text()
        timeout = int(re.search(r"(?m)^TimeoutStartSec=(\d+)$", unit).group(1))
        self.assertGreater(timeout, worst)
        total = int(re.search(r"#\s+total\s+(\d+)", unit).group(1))
        self.assertGreaterEqual(total, worst, "the unit's worst-case tally is out of date")

    def test_compose_restart_policy_is_overridable(self) -> None:
        text = (REPO / "compose.yaml").read_text()
        self.assertIn("restart: ${RESTART_POLICY:-unless-stopped}", text)


if __name__ == "__main__":
    unittest.main()
