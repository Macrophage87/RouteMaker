"""The boot scripts' wait and abort logic, against a fake `docker` and `curl`.

Nothing here touches Docker, the live stack or the real DATA_ROOT: the script is
pointed at a temporary DATA_ROOT, a temporary log directory and two shims on
BOOT_DOCKER / BOOT_CURL that record every call and answer from files.

These are unittest cases so they run under pytest (CI) and under plain
`python3 -m unittest tests.test_boot_scripts` on a host without pytest.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "boot" / "start-stack.sh"
INSTALL = REPO / "scripts" / "boot" / "install-boot-unit.sh"
UNIT_IN = REPO / "scripts" / "boot" / "routemaker-boot.service.in"
BASH = shutil.which("bash")

FAKE_DOCKER = r"""#!/usr/bin/env bash
# Fake docker. State lives in $FAKE_DIR: ps.txt ("service state health" lines),
# psql.out, psql.rc, docker_up (exists = answers), never_healthy (exists).
echo "$*" >>"$FAKE_DIR/calls.log"
[ "$1" = info ] && { [ -e "$FAKE_DIR/docker_up" ]; exit; }
[ "$1" = run ] && { [ ! -e "$FAKE_DIR/no_pg_visible" ]; exit; }
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
  ps) cat "$FAKE_DIR/ps.txt" ;;
  config) echo "docker.io/library/caddy:2.8-alpine"; echo "docker.io/postgis/postgis:16-3.4" ;;
  exec) cat "$FAKE_DIR/psql.out" 2>/dev/null; exit "$(cat "$FAKE_DIR/psql.rc" 2>/dev/null || echo 0)" ;;
  up)
    svc=${*: -1}
    sed -i "/^$svc /d" "$FAKE_DIR/ps.txt"
    if [ "$svc" = postgis ] && [ -e "$FAKE_DIR/never_healthy" ]; then
      echo "postgis running starting" >>"$FAKE_DIR/ps.txt"
    elif [ "$svc" = postgis ]; then
      echo "postgis running healthy" >>"$FAKE_DIR/ps.txt"
    else
      echo "$svc running " >>"$FAKE_DIR/ps.txt"
    fi ;;
  stop) for s in "$@"; do sed -i "/^$s /d" "$FAKE_DIR/ps.txt"; done ;;
esac
exit 0
"""

FAKE_CURL = r"""#!/usr/bin/env bash
echo "$*" >>"$FAKE_DIR/curl.log"
case "$*" in
  *api/route*) cat "$FAKE_DIR/code_route" 2>/dev/null || printf 200 ;;
  *api/geocode*) cat "$FAKE_DIR/code_geocode" 2>/dev/null || printf 200 ;;
  *) printf 200 ;;
esac
"""

REQUIRED = [
    "backups basemap caddy elevation extracts frontend photon postgres rebuild "
    "reference static tiles tiles/standard tiles/no-trail tiles/ebike tiles/weekend"
][0].split()


def write_exec(path: Path, text: str) -> None:
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@unittest.skipUnless(BASH, "bash is required")
class StartStackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="boot-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.data = self.tmp / "data"
        self.fake = self.tmp / "fake"
        self.logs = self.tmp / "logs"
        self.fake.mkdir()
        for d in REQUIRED:
            (self.data / d).mkdir(parents=True)
        (self.fake / "docker_up").write_text("")
        (self.fake / "ps.txt").write_text("")
        (self.fake / "psql.out").write_text("68 1359193")
        write_exec(self.fake / "docker", FAKE_DOCKER)
        write_exec(self.fake / "curl", FAKE_CURL)
        self.env_file = self.tmp / ".env"
        self.env_file.write_text(f"DATA_ROOT={self.data}\nRESTART_POLICY=no\n")

    def run_script(self, *args: str, **overrides: str) -> subprocess.CompletedProcess:
        env = {
            **os.environ,
            "FAKE_DIR": str(self.fake),
            "BOOT_DOCKER": str(self.fake / "docker"),
            "BOOT_CURL": str(self.fake / "curl"),
            "BOOT_ENV_FILE": str(self.env_file),
            "BOOT_LOG_DIR": str(self.logs),
            "BOOT_POLL_S": "0.2",
            "BOOT_WAIT_PREREQ_S": "1",
            "BOOT_POSTGIS_HEALTHY_S": "1",
            "BOOT_SMOKE_S": "1",
            **overrides,
        }
        return subprocess.run(
            [BASH, str(SCRIPT), *args],
            env=env, capture_output=True, text=True, timeout=60, check=False,
        )

    def calls(self) -> list[str]:
        path = self.fake / "calls.log"
        return path.read_text().splitlines() if path.exists() else []

    def mutating(self) -> list[str]:
        return [c for c in self.calls() if re.search(r" (up|stop|down|rm|restart|kill) ", f" {c} ")]

    def status(self) -> str:
        return (self.logs / "last-status").read_text()

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
        (self.fake / "no_pg_visible").write_text("")
        done = self.run_script()
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("PG_VERSION", done.stdout)
        self.assertEqual([c for c in self.calls() if " up " in c], [])

    def test_the_cluster_check_runs_in_a_throwaway_read_only_container(self) -> None:
        self.run_script()
        runs = [c for c in self.calls() if c.startswith("run ")]
        self.assertEqual(len(runs), 1)
        self.assertIn("--pull never", runs[0])
        self.assertIn("--network none", runs[0])
        self.assertIn(":/pgcheck:ro", runs[0])

    def test_waits_for_paths_that_appear_late(self) -> None:
        shutil.rmtree(self.data / "tiles" / "weekend")
        late = subprocess.Popen(
            [BASH, "-c", f"sleep 1; mkdir -p '{self.data}/tiles/weekend'"]
        )
        self.addCleanup(late.wait)
        done = self.run_script(BOOT_WAIT_PREREQ_S="10", BOOT_SMOKE_S="2")
        self.assertEqual(done.returncode, 0, done.stdout)

    def test_refuses_without_an_env_file(self) -> None:
        self.env_file.unlink()
        done = self.run_script()
        self.assertEqual(done.returncode, 1)
        self.assertIn("no env file", done.stdout)
        self.assertEqual(self.calls(), [])

    # ---- the bind-race abort

    def test_cold_start_orders_postgis_first_then_the_rest(self) -> None:
        done = self.run_script()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        ups = [c for c in self.calls() if " up " in c]
        names = [c.split()[-1] for c in ups]
        self.assertEqual(
            names,
            ["postgis", "caddy", "valhalla-standard", "valhalla-no-trail", "valhalla-ebike",
             "valhalla-weekend", "api", "worker", "rebuild", "photon"],
        )
        for line in ups:
            self.assertIn("--no-deps", line)
            self.assertIn("--force-recreate", line)
            self.assertIn("-d", line.split())
        stops = [c for c in self.calls() if " stop " in c]
        self.assertTrue(stops and stops[0].endswith("stop api worker rebuild"))
        self.assertLess(self.calls().index(stops[0]), self.calls().index(ups[0]))
        self.assertTrue(self.status().startswith("OK"))

    def test_every_compose_call_names_the_env_file_and_project(self) -> None:
        self.run_script()
        compose = [c for c in self.calls() if c.startswith("compose")]
        self.assertTrue(compose)
        for c in compose:
            self.assertIn(f"--env-file {self.env_file}", c)
            self.assertIn("--project-name routemaker", c)

    def test_never_a_plain_up(self) -> None:
        self.run_script()
        for c in self.calls():
            if " up " in c:
                self.assertIn("--no-deps", c, c)
        self.assertNotIn("down", " ".join(self.calls()).split())
        self.assertNotIn("migrate", " ".join(self.calls()))

    def test_empty_postgis_aborts_and_starts_nothing_else(self) -> None:
        (self.fake / "psql.out").write_text("ERROR:  relation \"django_migrations\" does not exist")
        (self.fake / "psql.rc").write_text("1")
        done = self.run_script()
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("ABORTED", done.stdout)
        self.assertIn("EMPTY", done.stdout)
        ups = [c.split()[-1] for c in self.calls() if " up " in c]
        self.assertEqual(ups, ["postgis"])
        self.assertTrue(self.status().startswith("FAILED"))
        self.assertNotIn("postgis running", (self.fake / "ps.txt").read_text())

    def test_short_segment_table_is_the_same_abort(self) -> None:
        (self.fake / "psql.out").write_text("68 60")
        done = self.run_script()
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertEqual([c.split()[-1] for c in self.calls() if " up " in c], ["postgis"])

    def test_too_few_migrations_aborts(self) -> None:
        (self.fake / "psql.out").write_text("0 1359193")
        done = self.run_script()
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertEqual([c.split()[-1] for c in self.calls() if " up " in c], ["postgis"])

    def test_postgis_never_healthy_aborts(self) -> None:
        (self.fake / "never_healthy").write_text("")
        done = self.run_script()
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("not healthy", done.stdout)
        self.assertEqual([c.split()[-1] for c in self.calls() if " up " in c], ["postgis"])

    def test_racy_postgis_running_empty_is_recovered_not_trusted(self) -> None:
        # Docker auto-started postgis on a phantom path: running, healthy, empty.
        (self.fake / "ps.txt").write_text("postgis running healthy\napi running healthy\n")
        (self.fake / "psql.out").write_text("0 0")
        (self.fake / "psql.rc").write_text("0")
        # After the force-recreate the real cluster answers.
        write_exec(
            self.fake / "docker",
            FAKE_DOCKER.replace(
                '  exec) cat',
                '  exec) [ -e "$FAKE_DIR/recreated" ] && echo "68 1359193" >"$FAKE_DIR/psql.out"; cat',
            ).replace('  up)\n', '  up)\n    touch "$FAKE_DIR/recreated"\n'),
        )
        done = self.run_script()
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("mode: COLD", done.stdout)
        self.assertIn("bind-race signature", done.stdout)

    # ---- warm path

    def warm(self) -> None:
        (self.fake / "ps.txt").write_text(
            "postgis running healthy\napi running healthy\nworker running \n"
            "rebuild running \ncaddy running \nvalhalla-standard running \n"
            "valhalla-no-trail running \nvalhalla-ebike running \n"
            "valhalla-weekend running \nphoton running healthy\nmigrate exited \n"
        )

    def test_warm_stack_is_left_alone(self) -> None:
        self.warm()
        done = self.run_script()
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("mode: WARM", done.stdout)
        self.assertEqual(self.mutating(), [])

    def test_warm_stack_starts_only_what_is_down(self) -> None:
        self.warm()
        text = (self.fake / "ps.txt").read_text().replace("photon running healthy\n", "photon exited \n")
        (self.fake / "ps.txt").write_text(text)
        done = self.run_script()
        self.assertEqual(done.returncode, 0, done.stdout)
        ups = [c for c in self.calls() if " up " in c]
        self.assertEqual(len(ups), 1)
        self.assertTrue(ups[0].endswith("up -d --no-deps photon"), ups[0])
        self.assertNotIn("--force-recreate", ups[0])

    # ---- smoke and dry-run

    def test_smoke_failure_exits_2_after_the_stack_is_up(self) -> None:
        (self.fake / "code_geocode").write_text("502")
        done = self.run_script()
        self.assertEqual(done.returncode, 2, done.stdout)
        self.assertIn("geocode=502", done.stdout)
        self.assertTrue(self.status().startswith("FAILED"))

    def test_dry_run_changes_nothing_and_skips_smoke(self) -> None:
        done = self.run_script("--dry-run")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(self.mutating(), [])
        self.assertIn("DRYRUN: docker compose up -d --no-deps --force-recreate postgis", done.stdout)
        self.assertFalse((self.fake / "curl.log").exists())
        self.assertFalse((self.logs / "last-status").exists())

    def test_a_second_concurrent_run_is_refused(self) -> None:
        self.logs.mkdir()
        holder = subprocess.Popen(
            [BASH, "-c", f"exec 9>'{self.logs}/.lock'; flock -n 9; sleep 5"]
        )
        self.addCleanup(holder.kill)
        subprocess.run(["sleep", "0.5"], check=True)
        done = self.run_script()
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("already running", done.stdout)


class StaticChecks(unittest.TestCase):
    def test_script_waits_for_every_data_root_bind_in_compose(self) -> None:
        compose = (REPO / "compose.yaml").read_text()
        bound = set(re.findall(r"\$\{DATA_ROOT\}/([A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)?)", compose))
        script = SCRIPT.read_text()
        block = re.search(r"REQUIRED_DIRS=\((.*?)\)", script, re.S)
        assert block is not None
        listed = set(block.group(1).split())
        self.assertEqual(sorted(bound - listed), [], "compose binds dirs the boot script does not wait for")

    def test_start_order_covers_every_resident_service(self) -> None:
        import yaml

        services = yaml.safe_load((REPO / "compose.yaml").read_text())["services"]
        resident = {
            name for name, svc in services.items()
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

    def test_compose_restart_policy_is_overridable(self) -> None:
        text = (REPO / "compose.yaml").read_text()
        self.assertIn("restart: ${RESTART_POLICY:-unless-stopped}", text)


if __name__ == "__main__":
    unittest.main()
