"""The beta's release agent (OWNER-DECISIONS 431): scripts/beta/auto-release.sh and the
decisions it acts on, scripts/beta/cd_logic.py (docs/BETA-RUNBOOK.md, "Continuous deployment").

The logic is tested directly: the strict semver picker, the GitHub check-run verdict, the gate
(what may deploy by itself and what needs the owner), and the rollback plan. The shell agent is
run against a throwaway git origin with stub docker, curl, compose and smoke-test, so nothing
here touches a stack, a server, GitHub or the network.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
BETA = REPO / "scripts" / "beta"
AGENT = BETA / "auto-release.sh"
sys.path.insert(0, str(BETA))
import cd_logic  # noqa: E402

needs_git = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("bash") is None, reason="needs git and bash"
)


# --- the semver picker ---


@pytest.mark.parametrize(
    "tag, expected",
    [
        ("v0.1.0", (0, 1, 0)),
        ("v1.20.300", (1, 20, 300)),
        ("v10.0.0", (10, 0, 0)),
        ("0.1.0", None),
        ("v0.1", None),
        ("v0.1.0.1", None),
        ("v01.1.0", None),
        ("v0.01.0", None),
        ("v1.2.3-rc1", None),
        ("v1.2.3+build", None),
        ("V1.2.3", None),
        ("v1.2.3\n", None),
        (" v1.2.3", None),
        ("v1.2.x", None),
        ("release-1.2.3", None),
        ("v1.2.3.", None),
    ],
)
def test_only_a_strict_vxyz_is_a_release(tag: str, expected) -> None:
    assert cd_logic.parse_semver(tag) == expected


def test_the_highest_newer_release_is_picked_numerically_not_by_text() -> None:
    tags = ["v0.1.0", "v0.2.0", "v0.10.0", "v0.9.9", "v1.0.0-rc1", "v01.0.0", "junk"]
    assert cd_logic.pick_release(tags, "v0.1.0") == "v0.10.0"
    assert cd_logic.pick_release(tags, "v0.10.0") is None
    assert cd_logic.pick_release(["v0.1.0"], "v0.1.0") is None
    # an older tag is never offered, whatever else is there
    assert cd_logic.pick_release(["v0.0.9", "v0.1.0"], "v0.2.0") is None


def test_a_deployed_tag_that_is_not_strict_is_refused() -> None:
    with pytest.raises(ValueError):
        cd_logic.pick_release(["v0.2.0"], "v0.1")


# --- the GitHub check run ---

SHA = "a" * 40


def run_(**fields) -> dict:
    base = {
        "id": 1,
        "name": "test",
        "head_sha": SHA,
        "status": "completed",
        "conclusion": "success",
        "app": {"slug": "github-actions"},
    }
    base.update(fields)
    return base


@pytest.mark.parametrize(
    "runs, verdict",
    [
        ([run_()], "green"),
        ([run_(conclusion="failure")], "red"),
        ([run_(conclusion="cancelled")], "red"),
        ([run_(conclusion="skipped")], "red"),
        ([run_(status="in_progress", conclusion=None)], "pending"),
        ([run_(status="queued", conclusion=None)], "pending"),
        ([], "pending"),
        # not this check, not this commit, not GitHub Actions: none of them count
        ([run_(name="lint")], "pending"),
        ([run_(head_sha="b" * 40)], "pending"),
        ([run_(app={"slug": "someone-else"})], "pending"),
        # a re-run supersedes the earlier result, both ways
        ([run_(id=1, conclusion="failure"), run_(id=2)], "green"),
        ([run_(id=2, conclusion="failure"), run_(id=1)], "red"),
        ([run_(id=1), run_(id=2, status="in_progress", conclusion=None)], "pending"),
    ],
)
def test_the_ci_verdict(runs: list, verdict: str) -> None:
    assert cd_logic.ci_verdict({"check_runs": runs}, SHA) == verdict


def test_a_malformed_check_run_answer_is_pending_not_green() -> None:
    assert cd_logic.ci_verdict({}, SHA) == "pending"
    assert cd_logic.ci_verdict({"check_runs": None}, SHA) == "pending"
    done = subprocess.run(
        [sys.executable, str(BETA / "cd_logic.py"), "ci-verdict", "--sha", SHA],
        input="not json",
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.stdout.strip() == "pending"


# --- the gate ---

VALHALLA = {
    "mjolnir": {"max_cache_size": 100, "hierarchy": True, "tile_extract": "/data/x.tar"},
    "loki": {"logging": {"long_request": 100}},
    "service_limits": {"bicycle": {"max_distance": 500000}},
    "additional_data": {"elevation": "/data/elevation"},
}


def _vjson(**changes) -> str:
    data = json.loads(json.dumps(VALHALLA))
    for dotted, value in changes.items():
        node = data
        *parents, leaf = dotted.split("__")
        for key in parents:
            node = node[key]
        node[leaf] = value
    return json.dumps(data)


@pytest.mark.parametrize(
    "changes, kind",
    [
        ({}, "none"),
        ({"loki__logging__long_request": 3600000}, "runtime"),
        ({"service_limits__bicycle__max_distance": 1}, "runtime"),
        ({"mjolnir__max_cache_size": 200}, "runtime"),
        ({"mjolnir__hierarchy": False}, "build"),
        ({"mjolnir__tile_extract": "/data/y.tar"}, "build"),
        ({"additional_data__elevation": "/data/z"}, "build"),
        ({"mjolnir__max_cache_size": 200, "mjolnir__hierarchy": False}, "build"),
        ({"brand_new_section": {"a": 1}}, "build"),
    ],
)
def test_a_valhalla_config_change_is_runtime_only_when_every_key_is(changes, kind) -> None:
    assert cd_logic.valhalla_change(_vjson(), _vjson(**changes))[0] == kind


def test_a_valhalla_config_added_removed_or_broken_is_a_build_change() -> None:
    assert cd_logic.valhalla_change(None, _vjson())[0] == "build"
    assert cd_logic.valhalla_change(_vjson(), None)[0] == "build"
    assert cd_logic.valhalla_change(_vjson(), "{")[0] == "build"


def _gate(files: dict[str, tuple[str | None, str | None]], compose_diff: str = "") -> dict:
    changes = [("M", path) for path in files]
    return cd_logic.gate(
        changes, lambda side, path: files[path][0 if side == "old" else 1], compose_diff
    )


def test_a_code_only_release_deploys_with_no_optional_steps() -> None:
    result = _gate({"src/core/api.py": ("a", "b"), "docs/BETA-RUNBOOK.md": ("a", "b")})
    assert result["verdict"] == "deploy" and result["reasons"] == []
    assert not any(result[k] for k in ("frontend", "migrations", "routers_restart"))
    assert result["changed_files"] == 1  # the doc does not count


def test_documentation_and_ci_alone_change_nothing_on_the_server() -> None:
    result = _gate({"PLAN.md": ("a", "b"), ".github/workflows/ci.yml": ("a", "b")})
    assert result["verdict"] == "deploy" and result["changed_files"] == 0


@pytest.mark.parametrize(
    "path",
    [
        "deploy/beta/nginx-routemaker.conf.template",
        "deploy/beta/401.html",
        "deploy/beta/env.beta.template",
        "scripts/prepare_data_root.sh",
        "lua/graph.lua",
        "lua/routemaker_remap.lua",
        "valhalla/vendor/VERSION",
        "src/pipeline/schema.py",
        "src/pipeline/variants.py",
        "src/pipeline/tiles.py",
    ],
)
def test_a_release_that_needs_the_owner_stops(path: str) -> None:
    result = _gate({path: ("a", "b")})
    assert result["verdict"] == "stop"
    assert any(path in reason for reason in result["reasons"])


@pytest.mark.parametrize("path", ["src/core/stress_tiles.py", "src/core/mass_tiles.py"])
def test_a_new_tile_format_deploys_and_asks_for_the_predraw(path: str) -> None:
    old = "X = 1\nFORMAT_VERSION = 5\n"
    bumped = _gate({path: (old, old.replace("5", "6"))})
    assert bumped["verdict"] == "deploy" and bumped["predraw"]
    assert any("FORMAT_VERSION changed (5 to 6)" in note for note in bumped["notes"])
    other = _gate({path: (old, old + "Y = 2\n")})
    assert other["verdict"] == "deploy" and not other["predraw"]


def test_the_predraw_flag_is_off_for_anything_else() -> None:
    result = _gate({"src/core/api.py": ("a", "b"), "src/core/tile_cache.py": ("a", "b")})
    assert result["verdict"] == "deploy" and not result["predraw"]


def test_the_offroad_router_config_never_restarts_the_beta_routers() -> None:
    path = "valhalla/valhalla-offroad.json"
    runtime = _gate({path: (_vjson(), _vjson(loki__logging__long_request=1))})
    assert runtime["verdict"] == "deploy" and not runtime["routers_restart"]
    build = _gate({path: (_vjson(), _vjson(mjolnir__hierarchy=False))})
    assert build["verdict"] == "stop"


def test_valhalla_runtime_settings_restart_the_routers_and_build_settings_stop() -> None:
    path = "valhalla/valhalla-standard.json"
    runtime = _gate({path: (_vjson(), _vjson(loki__logging__long_request=1))})
    assert runtime["verdict"] == "deploy" and runtime["routers_restart"]
    build = _gate({path: (_vjson(), _vjson(mjolnir__hierarchy=False))})
    assert build["verdict"] == "stop" and not build["routers_restart"]


def test_migrations_run_unless_they_name_the_live_schema_or_one_is_removed() -> None:
    path = "src/core/migrations/0010_x.py"
    plain = _gate({path: (None, "operations = [AddField('a', 'b')]\n")})
    assert plain["verdict"] == "deploy" and plain["migrations"]
    live = _gate({path: (None, "RunSQL('alter table live.segment add x int')\n")})
    assert live["verdict"] == "stop"
    removed = _gate({path: ("operations = []\n", None)})
    assert removed["verdict"] == "stop"


def test_a_front_end_change_asks_for_a_build_and_notes_a_new_lockfile() -> None:
    plain = _gate({"frontend/src/App.svelte": ("a", "b")})
    assert plain["verdict"] == "deploy" and plain["frontend"] and not plain["lockfile_changed"]
    lock = _gate({"frontend/package-lock.json": ("a", "b")})
    assert lock["frontend"] and lock["lockfile_changed"]


@pytest.mark.parametrize(
    "diff, stops",
    [
        (
            "-    image: ghcr.io/valhalla/valhalla:3.5.1\n"
            "+    image: ghcr.io/valhalla/valhalla:3.6.0\n",
            True,
        ),
        ("+      - ${DATA_ROOT}/newthing:/data/newthing\n", True),
        ("-      - ${DATA_ROOT}/old:/data/old\n", False),
        ("-        limits: { memory: 1450M }\n+        limits: { memory: 1400M }\n", False),
        ("--- a/compose.yaml\n+++ b/compose.yaml\n", False),
    ],
)
def test_compose_image_changes_and_new_data_paths_stop(diff: str, stops: bool) -> None:
    result = _gate({"compose.beta.yaml": ("a", "b")}, diff)
    assert result["compose_changed"]
    assert (result["verdict"] == "stop") is stops


def test_a_change_to_the_agent_itself_is_noted() -> None:
    assert _gate({"scripts/beta/auto-release.sh": ("a", "b")})["agent_changed"]


# --- the rollback plan ---


@pytest.mark.parametrize(
    "done, plan",
    [
        ([], []),
        (["stopped"], ["stop-app", "start-app", "smoke"]),
        (["stopped", "snapshot", "index_saved"], ["stop-app", "start-app", "smoke"]),
        (
            ["stopped", "snapshot", "index_saved", "checkout", "tag_set"],
            ["stop-app", "checkout-old", "tag-old", "gate", "start-app", "smoke"],
        ),
        (
            ["stopped", "snapshot", "index_saved", "checkout", "tag_set", "migrate"],
            [
                "stop-app",
                "checkout-old",
                "tag-old",
                "gate",
                "restore-db",
                "start-app",
                "predraw",
                "smoke",
            ],
        ),
        (
            ["stopped", "snapshot", "index_saved", "checkout", "tag_set", "frontend", "started"],
            [
                "stop-app",
                "checkout-old",
                "tag-old",
                "gate",
                "restore-index",
                "start-app",
                "smoke",
            ],
        ),
        (
            ["stopped", "snapshot", "checkout", "tag_set", "started", "routers"],
            [
                "stop-app",
                "checkout-old",
                "tag-old",
                "gate",
                "start-app",
                "restart-routers",
                "smoke",
            ],
        ),
        (
            ["stopped", "snapshot", "checkout", "tag_set", "started", "services"],
            [
                "stop-app",
                "checkout-old",
                "tag-old",
                "gate",
                "start-app",
                "recreate-services",
                "restart-routers",
                "smoke",
            ],
        ),
    ],
)
def test_the_rollback_plan(done: list, plan: list) -> None:
    assert cd_logic.rollback_plan(done) == plan


def test_the_database_is_restored_only_when_a_migration_ran() -> None:
    every = [s for s in cd_logic.STEPS if s != "migrate"]
    assert "restore-db" not in cd_logic.rollback_plan(every)
    assert "restore-db" in cd_logic.rollback_plan([*every, "migrate"])


def test_a_migration_without_a_snapshot_or_an_unknown_step_is_refused() -> None:
    with pytest.raises(ValueError):
        cd_logic.rollback_plan(["stopped", "migrate"])
    with pytest.raises(ValueError):
        cd_logic.rollback_plan(["stopped", "made-up"])


# --- the gate over real git history ---


def git(cwd: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    done = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, env=env, check=True
    )
    return done.stdout.strip()


def commit(repo: Path, files: dict[str, str], message: str = "change") -> str:
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        if name.endswith(".sh"):
            path.chmod(0o755)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@needs_git
def test_the_gate_reads_git_history(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    old = commit(repo, {"src/core/a.py": "x\n", "valhalla/valhalla-standard.json": _vjson()})
    new = commit(repo, {"valhalla/valhalla-standard.json": _vjson(loki__logging__long_request=9)})
    result = cd_logic.git_gate(str(repo), old, new)
    assert result["verdict"] == "deploy" and result["routers_restart"]
    newer = commit(repo, {"deploy/beta/401.html": "<p>x</p>\n"})
    assert cd_logic.git_gate(str(repo), old, newer)["verdict"] == "stop"


# --- the agent, end to end against stubs ---

STUB_COMPOSE = """#!/bin/sh
# a stand-in for beta-compose.sh: records its arguments, starts nothing. With STUB_RUNNING=postgis
# it answers what receive-data.sh asks of a healthy postgis; STUB_PENDING=1 makes one migration
# pending until `migrate --noinput` has run.
echo "$*" >> "$STUB_LOG"
case "$*" in
  "ps --status running --services") [ -n "${STUB_RUNNING:-}" ] && printf '%s\\n' $STUB_RUNNING ;;
  *"--format {{.Health}}"*) echo healthy ;;
  *pg_dump*) echo "PGDMP a fake dump" ;;
  *django_migrations*) echo t ;;
  *pg_stat_activity*) echo 0 ;;
  *"migrate --check"*) [ -n "${STUB_PENDING:-}" ] && [ ! -f "$STUB_MIGRATED" ] && exit 1 ;;
  *"migrate --noinput"*) touch "$STUB_MIGRATED" ;;
  *predraw_stress_tiles*) exit "${STUB_PREDRAW_RC:-0}" ;;
esac
exit 0
"""
STUB_SMOKE = """#!/bin/sh
echo "smoke $*" >> "$STUB_LOG"
echo "PASS  healthz (200)"
"""
STUB_SMOKE_FAILS = """#!/bin/sh
echo "smoke-new $*" >> "$STUB_LOG"
echo "FAIL  a route: expected 200, got 500"
exit 1
"""
STUB_CHECKER = """print("beta compose: ok")
"""
STUB_DOCKER = """#!/bin/sh
echo "docker $*" >> "$STUB_LOG"
case "$*" in
  "image inspect"*) [ -n "${STUB_HAS_IMAGES:-}" ] && exit 0; exit 1 ;;
  build*) exit "${STUB_BUILD_RC:-0}" ;;
esac
exit 0
"""
STUB_CURL = """#!/bin/sh
# GitHub's check-runs answer from $STUB_CI (a JSON file) with code $STUB_CI_CODE; 200 otherwise
out=""; url=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out=$2; shift 2 ;;
    -w|-H|--max-time) shift 2 ;;
    -*) shift ;;
    *) url=$1; shift ;;
  esac
done
echo "curl $url" >> "$STUB_LOG"
case "$url" in
  https://api.github.com/*)
    [ -n "$out" ] && cat "$STUB_CI" > "$out"
    printf '%s' "${STUB_CI_CODE:-200}" ;;
  *) [ -n "$out" ] && [ "$out" != /dev/null ] && echo ok > "$out"; printf 200 ;;
esac
"""


class Beta:
    """A throwaway origin, a beta checkout of it at v0.1.0, and a state directory."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.origin = tmp / "origin"
        self.origin.mkdir()
        git(self.origin, "init", "-q", "-b", "main")
        self.v1 = commit(
            self.origin,
            {
                "scripts/beta/beta-compose.sh": STUB_COMPOSE,
                "scripts/beta/smoke-test.sh": STUB_SMOKE,
                "scripts/check_beta_compose.py": STUB_CHECKER,
                "src/core/a.py": "x = 1\n",
                "src/core/stress_tiles.py": "FORMAT_VERSION = 7\n",
                "src/core/mass_tiles.py": "FORMAT_VERSION = 2\n",
                "frontend/package-lock.json": "{}\n",
            },
        )
        self.tag("v0.1.0")
        self.src = tmp / "src"
        git(tmp, "clone", "-q", str(self.origin), str(self.src))
        git(self.src, "checkout", "-q", "--detach", "v0.1.0")
        self.data = tmp / "data"
        (self.data / "frontend").mkdir(parents=True)
        (self.data / "frontend" / "index.html").write_text("<html>old</html>\n")
        (self.src / ".env").write_text(
            f"COMPOSE_PROJECT_NAME=routemaker-beta\nDATA_ROOT={self.data}\nTAG={self.v1[:12]}\n"
        )
        (self.src / ".git" / "info" / "exclude").write_text(".env\n")
        self.state = tmp / "state"
        self.cd = self.state / "cd"
        (self.cd / "bin").mkdir(parents=True)
        for name in ("cd_logic.py", "receive-data.sh"):
            shutil.copy2(BETA / name, self.cd / "bin" / name)
        (self.cd / "deployed-tag").write_text("v0.1.0\n")
        (self.cd / "deployed-sha").write_text(self.v1 + "\n")
        (self.cd / "report-url").write_text("\n")
        self.vars = self.state / "vars.sh"
        self.vars.write_text(
            f"export RM_STATE={self.state}\nexport RM_SRC={self.src}\n"
            f"export RM_DATA={self.data}\nexport RM_PY={sys.executable}\n"
        )
        self.vars.chmod(0o600)
        self.bin = tmp / "bin"
        self.bin.mkdir()
        for name, text in (("docker", STUB_DOCKER), ("curl", STUB_CURL)):
            (self.bin / name).write_text(text)
            (self.bin / name).chmod(0o755)
        self.log = tmp / "calls.log"
        self.ci = tmp / "ci.json"
        self.green()

    def tag(self, name: str, annotated: bool = True) -> None:
        if annotated:
            git(self.origin, "tag", "-a", name, "-m", name)
        else:
            git(self.origin, "tag", name)

    def release(self, name: str, files: dict[str, str], annotated: bool = True) -> str:
        sha = commit(self.origin, files)
        self.tag(name, annotated)
        self.sha = sha
        self.green()
        return sha

    def green(self, conclusion: str = "success", status: str = "completed") -> None:
        sha = getattr(self, "sha", self.v1)
        runs = [
            {
                "id": 7,
                "name": "test",
                "head_sha": sha,
                "status": status,
                "conclusion": conclusion,
                "app": {"slug": "github-actions"},
            }
        ]
        self.ci.write_text(json.dumps({"check_runs": runs}))

    def agent(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        full = {
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "HOME": str(self.tmp),
            "RM_VARS": str(self.vars),
            "STUB_LOG": str(self.log),
            "STUB_CI": str(self.ci),
            "STUB_MIGRATED": str(self.tmp / "migrated"),
            "RM_CD_SMOKE_RETRY_S": "0",
            "DOCKER": str(self.bin / "docker"),
            "CURL": str(self.bin / "curl"),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            **env,
        }
        return subprocess.run(
            ["bash", str(AGENT), *args], capture_output=True, text=True, env=full, check=False
        )

    def status(self) -> str:
        return (self.cd / "status").read_text()

    def calls(self) -> str:
        return self.log.read_text() if self.log.exists() else ""


@pytest.fixture
def beta(tmp_path: Path) -> Beta:
    if shutil.which("git") is None or shutil.which("flock") is None:
        pytest.skip("needs git and flock")
    return Beta(tmp_path)


def test_nothing_newer_is_up_to_date(beta: Beta) -> None:
    done = beta.agent("run")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "up-to-date: v0.1.0" in beta.status()
    assert "api.github.com" not in beta.calls()


def test_a_green_code_release_would_deploy_and_a_dry_run_changes_nothing(beta: Beta) -> None:
    sha = beta.release("v0.2.0", {"src/core/a.py": "x = 2\n"})
    done = beta.agent("run", "--dry-run")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "would deploy v0.2.0" in done.stdout
    assert f"/commits/{sha}/check-runs" in beta.calls()
    assert not (beta.cd / "status").exists()
    assert git(beta.src, "rev-parse", "HEAD") == beta.v1
    assert "stop api worker" not in beta.calls()


def test_the_highest_release_is_the_candidate(beta: Beta) -> None:
    beta.release("v0.2.0", {"src/core/a.py": "x = 2\n"})
    beta.release("v0.10.0", {"src/core/a.py": "x = 10\n"})
    assert "candidate: v0.10.0" in beta.agent("run", "--dry-run").stdout


def test_a_lightweight_tag_is_held_and_not_retried(beta: Beta) -> None:
    beta.release("v0.2.0", {"src/core/a.py": "x = 2\n"}, annotated=False)
    beta.agent("run")
    assert "held" in beta.status() and "annotated" in beta.status()
    assert (beta.cd / "hold" / "v0.2.0").exists()
    beta.log.unlink(missing_ok=True)
    beta.agent("run")
    assert "held" in beta.status()
    assert "api.github.com" not in beta.calls()
    assert "may be tried again" in beta.agent("retry", "v0.2.0").stdout
    assert not (beta.cd / "hold" / "v0.2.0").exists()


def test_a_tag_off_main_is_held(beta: Beta) -> None:
    git(beta.origin, "checkout", "-q", "-b", "side")
    beta.release("v0.2.0", {"src/core/a.py": "x = 2\n"})
    git(beta.origin, "checkout", "-q", "main")
    beta.agent("run")
    assert "not on main" in beta.status()


def test_ci_pending_or_rate_limited_waits_and_red_holds(beta: Beta) -> None:
    beta.release("v0.2.0", {"src/core/a.py": "x = 2\n"})
    beta.green(status="in_progress", conclusion="")
    beta.agent("run")
    assert "waiting" in beta.status() and not (beta.cd / "hold" / "v0.2.0").exists()
    beta.green()
    beta.agent("run", STUB_CI_CODE="403")
    assert "waiting" in beta.status() and "rate limit" in beta.status()
    beta.green(conclusion="failure")
    beta.agent("run")
    assert "held" in beta.status() and (beta.cd / "hold" / "v0.2.0").exists()


def test_a_release_needing_the_owner_is_held_with_the_reason(beta: Beta) -> None:
    beta.release("v0.2.0", {"deploy/beta/nginx-routemaker.conf.template": "server {}\n"})
    beta.agent("run")
    assert "held" in beta.status()
    held = (beta.cd / "hold" / "v0.2.0").read_text()
    assert "deploy/beta/nginx-routemaker.conf.template" in held
    assert "mark-deployed v0.2.0" in held
    assert "stop api worker" not in beta.calls()


def test_a_front_end_change_waits_for_the_node_image_or_node_modules(beta: Beta) -> None:
    beta.release("v0.2.0", {"frontend/src/x.ts": "export {}\n"})
    beta.agent("run")
    assert "waiting" in beta.status() and "node image" in beta.status()
    beta.agent("run", STUB_HAS_IMAGES="1")
    assert "waiting" in beta.status() and "node_modules" in beta.status()


def test_paused_does_nothing_and_resume_undoes_it(beta: Beta) -> None:
    beta.release("v0.2.0", {"src/core/a.py": "x = 2\n"})
    beta.agent("pause", "owner", "is", "shipping")
    beta.agent("run")
    assert "paused" in beta.status() and "shipping" in beta.status()
    assert "api.github.com" not in beta.calls()
    assert "PAUSED:" in beta.agent("status").stdout
    beta.agent("resume")
    assert "PAUSED:" not in beta.agent("status").stdout
    beta.agent("run", "--dry-run")
    assert "would deploy v0.2.0" in beta.agent("run", "--dry-run").stdout


def test_a_checkout_changed_by_hand_stops_the_agent(beta: Beta) -> None:
    (beta.src / "src" / "core" / "a.py").write_text("edited by hand\n")
    beta.agent("run")
    assert "drift" in beta.status()


def test_a_build_failure_changes_nothing_and_marks_the_tag_failed(beta: Beta) -> None:
    beta.release("v0.2.0", {"src/core/a.py": "x = 2\n"})
    done = beta.agent("run", STUB_BUILD_RC="1")
    assert done.returncode == 1
    assert "failed" in beta.status() and "nothing was changed" in beta.status()
    assert (beta.cd / "failed" / "v0.2.0").exists()
    assert git(beta.src, "rev-parse", "HEAD") == beta.v1
    assert "stop api worker" not in beta.calls()


def test_a_failure_after_the_stop_rolls_back_and_starts_the_old_release(beta: Beta) -> None:
    # The image is "there", so the deploy goes on to stop the app; the snapshot then fails
    # (the stub compose reports no postgis running) and the agent rolls back.
    beta.release("v0.2.0", {"src/core/a.py": "x = 2\n"})
    done = beta.agent("run", STUB_HAS_IMAGES="1")
    assert done.returncode == 1, done.stdout
    assert "rolled-back" in beta.status(), done.stdout
    calls = beta.calls()
    assert calls.index("stop api worker") < calls.index("up -d api worker")
    assert "smoke --local" in calls
    assert "restore-dump" not in calls and "migrate" not in calls
    assert git(beta.src, "rev-parse", "HEAD") == beta.v1
    assert (beta.cd / "deployed-tag").read_text().strip() == "v0.1.0"
    assert (beta.cd / "failed" / "v0.2.0").exists()


def _order(calls: str, *needles: str) -> None:
    at = [calls.index(n) for n in needles]
    assert at == sorted(at), list(zip(needles, at, strict=True))


def test_a_green_code_release_is_deployed_by_the_runbooks_steps(beta: Beta) -> None:
    sha = beta.release("v0.2.0", {"src/core/a.py": "x = 2\n"})
    done = beta.agent("run", STUB_HAS_IMAGES="1", STUB_RUNNING="postgis", STUB_PENDING="1")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "deployed: v0.2.0" in beta.status(), done.stdout
    assert git(beta.src, "rev-parse", "HEAD") == sha
    assert f"TAG={sha[:12]}\n" in (beta.src / ".env").read_text()
    assert (beta.cd / "deployed-tag").read_text().strip() == "v0.2.0"
    assert (beta.cd / "previous-tag").read_text().strip() == "v0.1.0"
    assert len(list((beta.cd / "backups").glob("pre-release-*.dump"))) == 1
    assert len(list((beta.cd / "backups").glob("index.html.pre-release-*"))) == 1
    _order(
        beta.calls(),
        "stop api worker",
        "pg_dump",
        "migrate ./manage.py migrate --check",
        "migrate ./manage.py migrate --noinput",
        "up -d api worker",
        "exec -T api ./manage.py collectstatic --noinput",
        "smoke --local",
    )
    assert "restart valhalla" not in beta.calls()
    beta.agent("run")
    assert "up-to-date: v0.2.0" in beta.status()
    # the deploy's report outlives the idle pass after it
    assert "result: deployed: v0.2.0" in (beta.cd / "last-release-report.txt").read_text()


@pytest.mark.parametrize(
    "path, text",
    [
        ("src/core/stress_tiles.py", "FORMAT_VERSION = 8\n"),
        ("src/core/mass_tiles.py", "FORMAT_VERSION = 3\n"),
    ],
)
def test_a_tile_format_release_deploys_and_then_runs_the_predraw(
    beta: Beta, path: str, text: str
) -> None:
    sha = beta.release("v0.2.0", {path: text})
    done = beta.agent("run", STUB_HAS_IMAGES="1", STUB_RUNNING="postgis")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "deployed: v0.2.0" in beta.status(), done.stdout
    assert not (beta.cd / "hold" / "v0.2.0").exists()
    assert git(beta.src, "rev-parse", "HEAD") == sha
    _order(
        beta.calls(),
        "up -d api worker",
        "smoke --local",
        "exec -T worker ./manage.py predraw_stress_tiles",
    )
    assert beta.calls().count("predraw_stress_tiles") == 1
    assert "predraw exit 0" in (beta.state / "predraw.log").read_text()


def test_a_predraw_that_fails_after_a_tile_format_deploy_warns_and_does_not_roll_back(
    beta: Beta,
) -> None:
    sha = beta.release("v0.2.0", {"src/core/stress_tiles.py": "FORMAT_VERSION = 8\n"})
    done = beta.agent(
        "run", STUB_HAS_IMAGES="1", STUB_RUNNING="postgis", STUB_PREDRAW_RC="1"
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "deployed: v0.2.0" in beta.status()
    assert git(beta.src, "rev-parse", "HEAD") == sha
    assert not (beta.cd / "failed" / "v0.2.0").exists()
    assert "WARNING: the pre-draw did not finish cleanly" in done.stdout
    assert "predraw exit 1" in (beta.state / "predraw.log").read_text()
    assert beta.calls().count("up -d api worker") == 1  # no rollback restart


def test_a_code_release_runs_no_predraw(beta: Beta) -> None:
    beta.release("v0.2.0", {"src/core/a.py": "x = 2\n"})
    beta.agent("run", STUB_HAS_IMAGES="1", STUB_RUNNING="postgis")
    assert "deployed: v0.2.0" in beta.status()
    assert "predraw" not in beta.calls()


def test_a_failed_smoke_test_after_a_migration_restores_the_snapshot(beta: Beta) -> None:
    beta.release(
        "v0.2.0", {"src/core/a.py": "x = 2\n", "scripts/beta/smoke-test.sh": STUB_SMOKE_FAILS}
    )
    done = beta.agent("run", STUB_HAS_IMAGES="1", STUB_RUNNING="postgis", STUB_PENDING="1")
    assert done.returncode == 1
    assert "rolled-back" in beta.status(), done.stdout
    calls = beta.calls()
    _order(
        calls,
        "migrate ./manage.py migrate --noinput",
        "smoke-new --local",
        "pg_restore",
        "predraw_stress_tiles",
        "smoke --local",
    )
    assert calls.count("up -d api worker") == 2
    assert git(beta.src, "rev-parse", "HEAD") == beta.v1
    assert f"TAG={beta.v1[:12]}\n" in (beta.src / ".env").read_text()
    assert (beta.cd / "deployed-tag").read_text().strip() == "v0.1.0"
    failed = (beta.cd / "failed" / "v0.2.0").read_text()
    assert "rollback: restore-db" in failed and "FAIL  a route" in failed
    assert "predraw exit 0" in (beta.state / "predraw.log").read_text()


def test_a_failure_without_a_migration_leaves_the_database_alone(beta: Beta) -> None:
    beta.release(
        "v0.2.0", {"src/core/a.py": "x = 2\n", "scripts/beta/smoke-test.sh": STUB_SMOKE_FAILS}
    )
    beta.agent("run", STUB_HAS_IMAGES="1", STUB_RUNNING="postgis")
    assert "rolled-back" in beta.status()
    calls = beta.calls()
    assert "pg_restore" not in calls and "migrate --noinput" not in calls
    assert "predraw" not in calls


def test_mark_deployed_records_a_release_shipped_by_hand(beta: Beta) -> None:
    sha = beta.release("v0.2.0", {"deploy/beta/401.html": "<p>x</p>\n"})
    beta.agent("run")
    assert (beta.cd / "hold" / "v0.2.0").exists()
    git(beta.src, "checkout", "-q", "--detach", sha)
    env = (beta.src / ".env").read_text().replace(beta.v1[:12], sha[:12])
    (beta.src / ".env").write_text(env)
    done = beta.agent("mark-deployed", "v0.2.0")
    assert done.returncode == 0, done.stderr
    assert (beta.cd / "deployed-tag").read_text().strip() == "v0.2.0"
    assert not (beta.cd / "hold" / "v0.2.0").exists()
    beta.agent("run")
    assert "up-to-date: v0.2.0" in beta.status()


def test_a_tag_held_by_hand_is_not_deployed_until_retried(beta: Beta) -> None:
    beta.release("v0.2.0", {"src/core/a.py": "x = 2\n"})
    assert beta.agent("hold", "v0.2.0", "rolled", "back").returncode == 0
    beta.agent("run")
    assert "held" in beta.status() and "rolled back" in beta.status()
    beta.agent("retry", "v0.2.0")
    assert "would deploy v0.2.0" in beta.agent("run", "--dry-run").stdout


def test_mark_deployed_refuses_a_tag_the_checkout_is_not_at(beta: Beta) -> None:
    beta.release("v0.2.0", {"src/core/a.py": "x = 2\n"})
    beta.agent("run", "--dry-run")
    done = beta.agent("mark-deployed", "v0.2.0")
    assert done.returncode != 0 and "not v0.2.0" in done.stderr


def test_the_logs_carry_no_secret_from_dot_env(beta: Beta) -> None:
    secret = "f" * 48
    with (beta.src / ".env").open("a") as env:
        env.write(f"PGPASSWORD={secret}\nDJANGO_SECRET_KEY={secret}\n")
    beta.release("v0.2.0", {"src/core/a.py": "x = 2\n"})
    beta.agent("run", STUB_HAS_IMAGES="1")
    for path in beta.cd.rglob("*"):
        if path.is_file() and path.suffix != ".py" and path.name != "receive-data.sh":
            assert secret not in path.read_text(errors="replace"), path


def test_a_world_writable_vars_file_is_refused(beta: Beta) -> None:
    beta.vars.chmod(0o666)
    done = beta.agent("status")
    assert done.returncode == 2 and "writable by others" in done.stderr


# --- receive-data.sh's no-sudo backups directory ---


def _receive(tmp: Path, *args: str) -> subprocess.CompletedProcess:
    data = tmp / "data"
    data.mkdir(exist_ok=True)
    env_file = tmp / ".env"
    env_file.write_text(f"COMPOSE_PROJECT_NAME=routemaker-beta\nDATA_ROOT={data}\n")
    # A docker that fails, so the one that gets past its checks stops at "postgis is not
    # running" without asking a real engine anything.
    env = {**os.environ, "DOCKER": shutil.which("false") or "/bin/false"}
    return subprocess.run(
        ["bash", str(BETA / "receive-data.sh"), "--env-file", str(env_file), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


@needs_git
def test_receive_data_backups_dir_must_be_private_absolute_and_outside_data_root(
    tmp_path: Path,
) -> None:
    private = tmp_path / "backups"
    private.mkdir(mode=0o700)
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o777)
    inside = tmp_path / "data" / "mine"
    inside.mkdir(parents=True)
    cases = [
        (["--backups-dir", "relative", "snapshot-db", "--label", "x"], "not absolute"),
        (["--backups-dir", str(tmp_path / "nope"), "snapshot-db", "--label", "x"], "not a dir"),
        (["--backups-dir", str(shared), "snapshot-db", "--label", "x"], "writable by others"),
        (["--backups-dir", str(inside), "snapshot-db", "--label", "x"], "inside DATA_ROOT"),
        (["--backups-dir", str(private), "--bundle", str(tmp_path), "verify"], "is for"),
    ]
    for args, message in cases:
        done = _receive(tmp_path, *args)
        assert done.returncode == 2 and message in done.stderr, (args, done.stderr)
    # A good one gets past its own checks (and stops at the missing postgis).
    done = _receive(tmp_path, "--backups-dir", str(private), "snapshot-db", "--label", "x")
    assert done.returncode == 2 and "postgis is not running" in done.stderr, done.stderr


# --- the runbook ---


def test_the_runbook_documents_continuous_deployment() -> None:
    text = (REPO / "docs" / "BETA-RUNBOOK.md").read_text()
    section = text.split("## Continuous deployment", 1)[1].split("\n## ", 1)[0]
    for needle in (
        "auto-release.sh install",
        "enable-linger",
        '"$A" pause',
        '"$A" status',
        '"$A" mark-deployed',
        '"$A" hold',
        "RM_CD_NPM",
        "git tag -a",
        "restore-dump",
        "OWNER-DECISIONS 431",
    ):
        assert needle in section, needle
