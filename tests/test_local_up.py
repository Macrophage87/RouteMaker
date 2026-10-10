"""scripts/local-up.sh, the one-command local start, against a fake `docker` and `curl`.

Nothing here touches Docker or a real DATA_ROOT: the script gets a temporary
.env path, a temporary DATA_ROOT and shims on LOCAL_UP_DOCKER / LOCAL_UP_CURL /
LOCAL_UP_START_STACK that record every call. The fake `docker run` does the one
thing each helper container leaves behind (the data root's directories, the base
map file, the published front end and its stamp), so a second run sees a first
run's results.
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
SCRIPT = REPO / "scripts" / "local-up.sh"
BASH = shutil.which("bash")

FAKE_DOCKER = r"""#!/usr/bin/env bash
printf '%s|RESTART_POLICY=%s\n' "$*" "${RESTART_POLICY-<unset>}" >>"$FAKE_DIR/calls.log"
case "$1" in
  info) [ -e "$FAKE_DIR/docker_down" ] && exit 1; exit 0 ;;
  ps)
    case "$*" in
      *service=rebuild*) cat "$FAKE_DIR/rebuild_running" 2>/dev/null ;;
      *) cat "$FAKE_DIR/ps_owners" 2>/dev/null ;;
    esac
    exit 0 ;;
  compose)
    [ "$2" = version ] && { cat "$FAKE_DIR/compose_version" 2>/dev/null || echo 2.29.1; exit 0; }
    exit 0 ;;
  run)
    all="$*"
    last="${@: -1}"
    case "$all" in
      *prepare_data_root.sh*)
        dirs=$(sed -n '/^DIRECTORIES="/,/^"/p' "$REPO/scripts/prepare_data_root.sh" | sed '1d;$d')
        for d in $dirs; do
          mkdir -p "$DATA_ROOT_T/$d"
        done ;;
      *fetch_basemap.sh*) : >"$DATA_ROOT_T/basemap/region.pmtiles" ;;
      *local-up-source*)
        : >"$DATA_ROOT_T/frontend/index.html"
        printf '%s\n' "$last" >"$DATA_ROOT_T/frontend/.local-up-source" ;;
    esac
    exit 0 ;;
esac
exit 0
"""

FAKE_CURL = r"""#!/usr/bin/env bash
# health_seq: one answer per line, used up in order; then health; then 200.
if [ -s "$FAKE_DIR/health_seq" ]; then
  head -n1 "$FAKE_DIR/health_seq" | tr -d '\n'
  sed -i 1d "$FAKE_DIR/health_seq"
  exit 0
fi
cat "$FAKE_DIR/health" 2>/dev/null || printf 200
"""

# A stand-in for git, for the front-end stamp: the tree id comes from git_tree
# (or git fails when there is none), and frontend/ is dirty while git_dirty exists.
FAKE_GIT = r"""#!/usr/bin/env bash
case "$*" in
  *rev-parse*) cat "$FAKE_DIR/git_tree" 2>/dev/null || exit 128 ;;
  *status*) [ -e "$FAKE_DIR/git_dirty" ] && echo " M frontend/src/main.ts" ;;
esac
exit 0
"""

FAKE_START_STACK = r"""#!/usr/bin/env bash
printf 'start-stack %s|%s|%s\n' "$*" "$BOOT_ENV_FILE" "$BOOT_DATA_ROOT" >>"$FAKE_DIR/calls.log"
exit "$(cat "$FAKE_DIR/start_stack_rc" 2>/dev/null || echo 0)"
"""


def _exe(path: Path, text: str) -> Path:
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@unittest.skipIf(BASH is None, "needs bash")
class LocalUpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.fake = self.tmp / "fake"
        self.fake.mkdir()
        self.data_root = self.tmp / "data"
        self.env_file = self.tmp / "dot.env"
        self.docker = _exe(self.fake / "docker", FAKE_DOCKER)
        self.curl = _exe(self.fake / "curl", FAKE_CURL)
        self.start_stack = _exe(self.fake / "start-stack", FAKE_START_STACK)
        self.fake_git_dir = self.tmp / "fakebin"
        self.fake_git_dir.mkdir()
        _exe(self.fake_git_dir / "git", FAKE_GIT)
        self.use_fake_git = False
        self.extra_env: dict[str, str] = {}
        self.root_uid = "4294967294"  # nobody's: the fake prepare's directories are ours

    def run_script(self, *args: str) -> subprocess.CompletedProcess[str]:
        path = os.environ["PATH"]
        if self.use_fake_git:
            path = f"{self.fake_git_dir}{os.pathsep}{path}"
        env = {
            "PATH": path,
            "HOME": str(self.tmp / "home"),
            "FAKE_DIR": str(self.fake),
            "REPO": str(REPO),
            "DATA_ROOT_T": str(self.data_root),
            "LOCAL_UP_ENV_FILE": str(self.env_file),
            "LOCAL_UP_DOCKER": str(self.docker),
            "LOCAL_UP_CURL": str(self.curl),
            "LOCAL_UP_START_STACK": str(self.start_stack),
            "LOCAL_UP_HEALTHY_S": "0",
            "LOCAL_UP_POLL_S": "0",
            "LOCAL_UP_ROOT_UID": self.root_uid,
            **self.extra_env,
        }
        return subprocess.run(
            [BASH, str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=60
        )

    def calls(self) -> list[str]:
        log = self.fake / "calls.log"
        return log.read_text().splitlines() if log.exists() else []

    def env_values(self) -> dict[str, list[str]]:
        values: dict[str, list[str]] = {}
        for line in self.env_file.read_text().splitlines():
            m = re.match(r"^([A-Z_]+)=(.*)$", line)
            if m:
                values.setdefault(m.group(1), []).append(m.group(2))
        return values

    def first_run(self) -> subprocess.CompletedProcess[str]:
        result = self.run_script("--data-root", str(self.data_root))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def frontend_clean(self) -> bool:
        out = subprocess.run(
            ["git", "-C", str(REPO), "status", "--porcelain", "--", "frontend"],
            capture_output=True,
            text=True,
        )
        return out.returncode == 0 and out.stdout == ""

    # --- .env ---------------------------------------------------------------------

    def test_a_first_run_writes_a_local_env_with_fresh_secrets(self) -> None:
        self.first_run()
        values = self.env_values()
        duplicated = {k: v for k, v in values.items() if len(v) > 1}
        self.assertEqual(duplicated, {}, "a key set twice means compose reads only the last")
        one = {k: v[0] for k, v in values.items()}
        self.assertEqual(one["DATA_ROOT"], str(self.data_root))
        self.assertEqual(one["CADDY_SITE_ADDRESS"], ":80")
        self.assertEqual(one["DJANGO_DEBUG"], "1")
        self.assertEqual(one["DJANGO_ALLOWED_HOSTS"], "localhost,127.0.0.1")
        self.assertEqual(one["DJANGO_CSRF_TRUSTED_ORIGINS"], "http://localhost,http://127.0.0.1")
        self.assertEqual(one["DISCORD_REDIRECT_URI"], "http://localhost/auth/callback")
        self.assertEqual(one["COMPOSE_PROJECT_NAME"], "routemaker")
        self.assertEqual(one["RESTART_POLICY"], "no")
        secrets = [
            "DJANGO_SECRET_KEY",
            "PGPASSWORD",
            "KEY_ENCRYPTION_KEY",
            "DISCORD_BOT_TOKEN",
            "BOT_INTERNAL_SECRET",
        ]
        for key in secrets:
            self.assertRegex(one[key], r"^[0-9a-f]{64}$", key)
        self.assertEqual(
            len({one[k] for k in secrets}), len(secrets), "each secret is its own value"
        )
        self.assertEqual(stat.S_IMODE(self.env_file.stat().st_mode), 0o600)

    def test_two_first_runs_get_different_secrets(self) -> None:
        self.first_run()
        before = self.env_values()["KEY_ENCRYPTION_KEY"]
        self.env_file.unlink()
        self.first_run()
        self.assertNotEqual(self.env_values()["KEY_ENCRYPTION_KEY"], before)

    def test_an_existing_env_is_never_rewritten(self) -> None:
        self.env_file.write_text(
            f"DATA_ROOT={self.data_root}\nCOMPOSE_PROJECT_NAME=routemaker\nPGPASSWORD=mine\n"
        )
        before = self.env_file.read_bytes()
        result = self.run_script("--data-root", "/elsewhere")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.env_file.read_bytes(), before)
        self.assertIn("--data-root is ignored", result.stdout)

    def test_an_env_without_a_project_name_is_refused_before_anything_starts(self) -> None:
        self.env_file.write_text(f"DATA_ROOT={self.data_root}\n")
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn("COMPOSE_PROJECT_NAME", result.stderr)
        self.assertFalse(any(c.startswith("compose ") and " up " in c for c in self.calls()))
        self.assertFalse(any(c.startswith("run ") for c in self.calls()))

    def test_a_relative_data_root_is_refused(self) -> None:
        result = self.run_script("--data-root", "rmdata")
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.env_file.exists())

    def test_a_data_root_sed_or_dotenv_would_misread_is_refused(self) -> None:
        for bad in ("/tmp/a&b", "/tmp/a|b", "/tmp/a b", "/tmp/a$b", "/tmp/a#b"):
            result = self.run_script("--data-root", bad)
            self.assertEqual(result.returncode, 1, bad)
            self.assertFalse(self.env_file.exists(), bad)

    # --- An existing stack ---------------------------------------------------------

    def test_a_first_run_refuses_to_take_over_an_existing_stack(self) -> None:
        (self.fake / "ps_owners").write_text("/home/someone/src/RouteMaker\n")
        result = self.run_script("--data-root", str(self.data_root))
        self.assertEqual(result.returncode, 1)
        self.assertIn("already exists", result.stderr)
        self.assertIn("/home/someone/src/RouteMaker", result.stderr)
        self.assertFalse(self.env_file.exists())
        self.assertFalse(any(c.startswith(("run ", "compose --")) for c in self.calls()))

    def test_a_stack_started_from_another_checkout_is_refused(self) -> None:
        self.env_file.write_text(f"DATA_ROOT={self.data_root}\nCOMPOSE_PROJECT_NAME=routemaker\n")
        (self.fake / "ps_owners").write_text(f"/home/someone/wt/t9\n{REPO}\n")
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn("/home/someone/wt/t9", result.stderr)
        self.assertFalse(any(c.startswith(("run ", "compose --")) for c in self.calls()))

    def test_a_stack_started_from_this_checkout_is_started(self) -> None:
        self.env_file.write_text(f"DATA_ROOT={self.data_root}\nCOMPOSE_PROJECT_NAME=routemaker\n")
        (self.fake / "ps_owners").write_text(f"{REPO}\n\n")
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(
            any(
                "ps -a --filter label=com.docker.compose.project=routemaker" in c
                for c in self.calls()
            )
        )

    # --- Docker -------------------------------------------------------------------

    def test_docker_not_answering_stops_it_before_anything_is_written(self) -> None:
        (self.fake / "docker_down").touch()
        result = self.run_script("--data-root", str(self.data_root))
        self.assertEqual(result.returncode, 1)
        self.assertIn("Docker is not answering", result.stderr)
        self.assertFalse(self.env_file.exists())

    def test_compose_v1_is_refused(self) -> None:
        (self.fake / "compose_version").write_text("1.29.2\n")
        result = self.run_script("--data-root", str(self.data_root))
        self.assertEqual(result.returncode, 1)
        self.assertIn("v2 or later", result.stderr)

    # --- The first run, with no routing data ---------------------------------------

    def test_a_first_run_prepares_fetches_builds_and_starts_without_the_routers(self) -> None:
        result = self.first_run()
        calls = self.calls()

        def index(fragment: str) -> int:
            hits = [i for i, c in enumerate(calls) if fragment in c]
            self.assertTrue(hits, f"no call with {fragment!r}: {calls}")
            return hits[0]

        order = [
            index("prepare_data_root.sh"),
            index("fetch_basemap.sh"),
            index("npm ci && npm run build"),
            index("local-up-source"),
            index("compose.yaml build|"),
            index(" up -d --no-build "),
            index("collectstatic"),
        ]
        self.assertEqual(order, sorted(order), calls)
        up = calls[index(" up -d --no-build ")]
        for service in ("postgis", "api", "worker", "rebuild", "caddy", "photon"):
            self.assertIn(f" {service}", up)
        self.assertNotIn("valhalla", up)
        # The project and env file are always named, and nothing restarts at boot.
        for call in calls:
            if call.startswith("compose ") and not call.startswith("compose version"):
                self.assertIn("--project-name routemaker", call)
                self.assertIn(f"--env-file {self.env_file}", call)
                self.assertIn("RESTART_POLICY=no", call)
        self.assertFalse(any(c.startswith("start-stack") for c in calls))
        self.assertIn("scripts/acceptance.py --only A4", result.stdout)

    def test_a_rerun_skips_what_is_already_there(self) -> None:
        self.first_run()
        (self.fake / "calls.log").unlink()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.calls()
        self.assertFalse(any("prepare_data_root.sh" in c for c in calls))
        self.assertFalse(any("fetch_basemap.sh" in c for c in calls))
        built_frontend = any("npm ci" in c for c in calls)
        self.assertEqual(built_frontend, not self.frontend_clean())

    def test_a_changed_front_end_is_published_again(self) -> None:
        self.first_run()
        (self.data_root / "frontend" / ".local-up-source").write_text("an older tree\n")
        (self.fake / "calls.log").unlink()
        self.run_script()
        self.assertTrue(any("npm ci" in c for c in self.calls()))

    def test_a_missing_index_html_is_published_again(self) -> None:
        self.first_run()
        (self.data_root / "frontend" / "index.html").unlink()
        (self.fake / "calls.log").unlink()
        self.run_script()
        self.assertTrue(any("npm ci" in c for c in self.calls()))

    def test_a_dirty_front_end_is_rebuilt_on_every_run(self) -> None:
        self.use_fake_git = True
        (self.fake / "git_tree").write_text("abc123\n")
        (self.fake / "git_dirty").touch()
        self.first_run()
        self.assertEqual(
            (self.data_root / "frontend" / ".local-up-source").read_text().strip(),
            "abc123+dirty",
        )
        (self.fake / "calls.log").unlink()
        self.run_script()
        self.assertTrue(any("npm ci" in c for c in self.calls()))
        # Clean again at the same tree: the next run publishes once more (the
        # stamp still says dirty), and the one after that skips.
        (self.fake / "git_dirty").unlink()
        self.run_script()
        (self.fake / "calls.log").unlink()
        self.run_script()
        self.assertFalse(any("npm ci" in c for c in self.calls()))

    def test_without_git_the_front_end_is_always_rebuilt(self) -> None:
        self.use_fake_git = True  # and no git_tree: rev-parse fails
        self.first_run()
        (self.fake / "calls.log").unlink()
        self.run_script()
        self.assertTrue(any("npm ci" in c for c in self.calls()))

    def test_no_build_skips_the_image_build(self) -> None:
        result = self.run_script("--data-root", str(self.data_root), "--no-build")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(any("compose.yaml build|" in c for c in self.calls()))

    def test_healthz_never_answering_is_exit_2(self) -> None:
        (self.fake / "health").write_text("502")
        result = self.run_script("--data-root", str(self.data_root))
        self.assertEqual(result.returncode, 2)
        self.assertIn("/healthz", result.stderr)
        self.assertIn("--project-name routemaker", result.stderr)

    def test_healthz_answering_late_is_waited_for(self) -> None:
        (self.fake / "health_seq").write_text("502\n000\n502\n")
        self.extra_env = {"LOCAL_UP_HEALTHY_S": "60", "LOCAL_UP_POLL_S": "0"}
        result = self.run_script("--data-root", str(self.data_root))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("waiting up to", result.stdout)
        self.assertEqual((self.fake / "health_seq").read_text(), "")

    def test_a_missing_data_root_directory_prepares_it_again(self) -> None:
        self.first_run()
        (self.data_root / "rebuild").rmdir()  # the last entry in DIRECTORIES
        (self.fake / "calls.log").unlink()
        self.run_script()
        self.assertTrue(any("prepare_data_root.sh" in c for c in self.calls()))

    def test_a_root_owned_data_root_is_prepared_again(self) -> None:
        """Docker made the bind sources as root before the prepare ever ran."""
        self.first_run()
        (self.fake / "calls.log").unlink()
        self.root_uid = str(os.getuid())  # so the directories read as root's
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(any("prepare_data_root.sh" in c for c in self.calls()))

    def test_a_running_rebuild_is_left_alone_and_the_rest_started(self) -> None:
        """A first rebuild in progress survives a rerun after a .env or code change."""
        self.first_run()
        (self.fake / "calls.log").unlink()
        (self.fake / "rebuild_running").write_text("0123456789ab\n")
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        ups = [c for c in self.calls() if c.startswith("compose ") and " up " in c]
        self.assertEqual(len(ups), 1, ups)
        services = ups[0].split("|")[0].split(" up -d --no-build ")[1].split()
        self.assertEqual(services, ["postgis", "api", "worker", "caddy", "photon"])
        self.assertNotIn("--no-recreate", ups[0])

    def test_without_a_running_rebuild_it_is_started_too(self) -> None:
        self.first_run()
        ups = [c for c in self.calls() if c.startswith("compose ") and " up " in c]
        self.assertEqual(len(ups), 1, ups)
        self.assertIn(" rebuild ", ups[0])

    # --- With routing data --------------------------------------------------------

    def with_tiles(self) -> None:
        self.first_run()
        tar = self.data_root / "tiles" / "standard" / "current" / "tiles.tar"
        tar.write_bytes(b"")
        (self.fake / "calls.log").unlink()

    def test_with_routing_data_it_starts_through_start_stack(self) -> None:
        self.with_tiles()
        result = self.run_script("--", "--force-recreate-all")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.calls()
        starts = [c for c in calls if c.startswith("start-stack")]
        self.assertEqual(
            starts, [f"start-stack --force-recreate-all|{self.env_file}|{self.data_root}"]
        )
        self.assertFalse(any(" up " in c for c in calls if c.startswith("compose ")))
        self.assertTrue(any("collectstatic" in c for c in calls))
        self.assertNotIn("acceptance.py", result.stdout)

    def test_a_dry_run_with_routing_data_passes_dry_run_to_start_stack(self) -> None:
        self.with_tiles()
        result = self.run_script("--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.calls()
        starts = [c for c in calls if c.startswith("start-stack")]
        self.assertEqual(len(starts), 1, calls)
        self.assertTrue(starts[0].split("|")[0].endswith(" --dry-run"), starts[0])
        for call in calls:
            self.assertRegex(call, r"^(info|compose version|ps -a |ps -q |start-stack )", call)

    def test_a_failed_start_stack_is_passed_on(self) -> None:
        self.with_tiles()
        (self.fake / "start_stack_rc").write_text("2")
        result = self.run_script()
        self.assertEqual(result.returncode, 2)
        self.assertFalse(any("collectstatic" in c for c in self.calls()))

    # --- Dry run ------------------------------------------------------------------

    def test_a_dry_run_writes_nothing_and_changes_nothing(self) -> None:
        result = self.run_script("--data-root", str(self.data_root), "--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.env_file.exists())
        self.assertFalse(self.data_root.exists())
        for call in self.calls():
            self.assertRegex(call, r"^(info|compose version|ps -a |ps -q )", call)
        for step in ("prepare_data_root.sh", "fetch_basemap.sh", "npm\\ ci", " build", " up -d"):
            self.assertRegex(result.stdout, rf"DRYRUN: .*{re.escape(step)}", step)

    def test_a_dry_run_with_an_env_reads_its_data_root(self) -> None:
        other = self.tmp / "other"
        self.env_file.write_text(f"DATA_ROOT={other}\nCOMPOSE_PROJECT_NAME=routemaker\n")
        result = self.run_script("--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRegex(result.stdout, rf"DRYRUN: .*{re.escape(str(other))}/basemap")
        self.assertNotIn(str(self.tmp / "home" / "rmdata"), result.stdout)
        self.assertFalse(other.exists())

    # --- Another project ----------------------------------------------------------

    def test_an_env_for_another_project_is_refused(self) -> None:
        """The beta's .env, say: this must never start it without its overlay."""
        self.env_file.write_text(
            f"DATA_ROOT={self.data_root}\nCOMPOSE_PROJECT_NAME=routemaker-beta\n"
        )
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn("routemaker-beta", result.stderr)
        calls = self.calls()
        self.assertTrue(
            any("label=com.docker.compose.project=routemaker-beta" in c for c in calls), calls
        )
        self.assertFalse(any(c.startswith(("run ", "compose --")) for c in calls), calls)

    def test_help(self) -> None:
        result = self.run_script("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("Start RouteMaker on this computer", result.stdout)
        self.assertNotIn("set -E", result.stdout)

    def test_an_unknown_argument_is_64(self) -> None:
        self.assertEqual(self.run_script("--bogus").returncode, 64)


@unittest.skipIf(shutil.which("docker") is None, "needs the docker CLI (no daemon)")
class GeneratedEnvRendersTest(unittest.TestCase):
    def test_compose_renders_the_generated_env(self) -> None:
        """The .env a first run writes is one compose accepts, with no unset variable."""
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        fake = tmp / "fake"
        fake.mkdir()
        env_file = tmp / "dot.env"
        env = {
            "PATH": os.environ["PATH"],
            "HOME": str(tmp),
            "FAKE_DIR": str(fake),
            "REPO": str(REPO),
            "DATA_ROOT_T": str(tmp / "data"),
            "LOCAL_UP_ENV_FILE": str(env_file),
            "LOCAL_UP_DOCKER": str(_exe(fake / "docker", FAKE_DOCKER)),
            "LOCAL_UP_CURL": str(_exe(fake / "curl", FAKE_CURL)),
            "LOCAL_UP_HEALTHY_S": "0",
            "LOCAL_UP_POLL_S": "0",
        }
        subprocess.run(
            [BASH, str(SCRIPT), "--data-root", str(tmp / "data")],
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        out = subprocess.run(
            [
                "docker",
                "compose",
                "--project-directory",
                str(REPO),
                "--env-file",
                str(env_file),
                "-f",
                str(REPO / "compose.yaml"),
                "config",
                "--format",
                "json",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            env={"PATH": os.environ["PATH"], "HOME": str(tmp)},
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotIn("is not set", out.stderr)
        self.assertIn(f'"{tmp / "data"}/postgres"', out.stdout)
        self.assertIn('"name": "routemaker"', out.stdout)


if __name__ == "__main__":
    unittest.main()
