"""The routers restart after a map swap (the owner, 2026-10-29): scripts/beta/restart-routers.sh.

valhalla_service reads its tiles only at start, so a router that started before its variant's
`current` link last moved serves the old build. The hook restarts it once the link has been still
for the settle time. Run against stub compose and docker, so nothing here touches a server.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "scripts" / "beta" / "restart-routers.sh"

# ps -q NAME prints the id in running/NAME (absent: not running); restart NAME is logged and
# fails when $STUB_DIR/restart-fails exists.
STUB_COMPOSE = """#!/bin/sh
echo "$*" >> "$STUB_DIR/compose.log"
[ "$1" = --profile ] && shift 2
case "$1" in
  ps) cat "$STUB_DIR/running/$3" 2>/dev/null; exit 0 ;;
  restart) [ -f "$STUB_DIR/restart-fails" ] && exit 1; echo "$2" >> "$STUB_DIR/restarted"; exit 0 ;;
esac
exit 3
"""
STUB_DOCKER = """#!/bin/sh
[ "$1" = inspect ] || exit 3
cat "$STUB_DIR/started/$4"
"""


class Host:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.state = tmp / "state"
        self.data = tmp / "data"
        for d in (self.state, tmp / "running", tmp / "started"):
            d.mkdir()
        self.vars = self.state / "vars.sh"
        self.vars.write_text(
            f"export RM_STATE={self.state}\nexport RM_SRC={tmp}\nexport RM_DATA={self.data}\n"
        )
        self.vars.chmod(0o600)
        for name, text in (("compose", STUB_COMPOSE), ("docker", STUB_DOCKER)):
            (tmp / name).write_text(text)
            (tmp / name).chmod(0o755)

    def tiles(self, variant: str, moved_ago: float) -> None:
        """`tiles/<variant>/current` at a build, the link last changed `moved_ago` s ago."""
        base = self.data / "tiles" / variant
        (base / "20261027T080000Z").mkdir(parents=True, exist_ok=True)
        link = base / "current"
        if link.is_symlink():
            link.unlink()
        link.symlink_to("20261027T080000Z")
        when = time.time() - moved_ago
        os.utime(link, (when, when), follow_symlinks=False)

    def router(self, name: str, started_ago: float) -> None:
        cid = f"id-{name}"
        (self.tmp / "running" / name).write_text(cid + "\n")
        started = datetime.fromtimestamp(time.time() - started_ago, UTC)
        (self.tmp / "started" / cid).write_text(
            started.strftime("%Y-%m-%dT%H:%M:%S.123456789Z") + "\n"
        )

    def run(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        full = {
            "PATH": os.environ["PATH"],
            "HOME": str(self.tmp),
            "RM_VARS": str(self.vars),
            "RM_ROUTER_COMPOSE": str(self.tmp / "compose"),
            "DOCKER": str(self.tmp / "docker"),
            "STUB_DIR": str(self.tmp),
            **env,
        }
        return subprocess.run(
            ["bash", str(HOOK), *args], capture_output=True, text=True, env=full, check=False
        )

    def restarted(self) -> list[str]:
        path = self.tmp / "restarted"
        return path.read_text().split() if path.exists() else []


@pytest.fixture
def host(tmp_path: Path) -> Host:
    if shutil.which("flock") is None:
        pytest.skip("needs flock")
    return Host(tmp_path)


def test_a_router_started_before_its_map_moved_is_restarted(host: Host) -> None:
    host.tiles("standard", moved_ago=600)
    host.router("valhalla-standard", started_ago=7200)
    done = host.run("check")
    assert done.returncode == 0, done.stderr
    assert host.restarted() == ["valhalla-standard"]


def test_a_router_started_after_its_map_moved_is_left_alone(host: Host) -> None:
    host.tiles("standard", moved_ago=7200)
    host.router("valhalla-standard", started_ago=600)
    done = host.run("check")
    assert done.returncode == 0, done.stderr
    assert host.restarted() == []


def test_a_map_that_just_moved_waits_for_the_settle_time(host: Host) -> None:
    """A swap that fails undoes itself within seconds: no restart onto a link still moving."""
    host.tiles("standard", moved_ago=30)
    host.router("valhalla-standard", started_ago=7200)
    done = host.run("check")
    assert done.returncode == 0, done.stderr
    assert host.restarted() == []
    assert "once it has been still" in done.stdout
    assert host.run("check", RM_ROUTER_SETTLE_S="10").returncode == 0
    assert host.restarted() == ["valhalla-standard"]


def test_a_router_that_is_not_running_is_not_started(host: Host) -> None:
    host.tiles("ebike", moved_ago=600)
    done = host.run("check")
    assert done.returncode == 0, done.stderr
    assert host.restarted() == []
    assert "restart" not in (host.tmp / "compose.log").read_text()


def test_trail_routers_count_only_where_their_tiles_are(host: Host) -> None:
    host.tiles("mtb", moved_ago=600)
    host.router("valhalla-mtb", started_ago=7200)
    host.router("valhalla-offroad", started_ago=7200)  # no tiles/offroad/current here
    done = host.run("check")
    assert done.returncode == 0, done.stderr
    assert host.restarted() == ["valhalla-mtb"]
    assert all(
        line.startswith("--profile offroad ")
        for line in (host.tmp / "compose.log").read_text().splitlines()
    )


def test_each_stale_router_is_restarted_one_at_a_time(host: Host) -> None:
    for variant in ("standard", "no-trail", "ebike", "weekend"):
        host.tiles(variant, moved_ago=600)
        host.router(f"valhalla-{variant}", started_ago=7200)
    done = host.run("check")
    assert done.returncode == 0, done.stderr
    assert host.restarted() == [
        "valhalla-standard",
        "valhalla-no-trail",
        "valhalla-ebike",
        "valhalla-weekend",
    ]


def test_a_failed_restart_fails_the_pass(host: Host) -> None:
    host.tiles("standard", moved_ago=600)
    host.router("valhalla-standard", started_ago=7200)
    (host.tmp / "restart-fails").write_text("")
    done = host.run("check")
    assert done.returncode == 1
    assert "the restart failed" in done.stderr


def test_the_hook_stands_aside_while_a_deploy_pass_holds_the_lock(host: Host) -> None:
    host.tiles("standard", moved_ago=600)
    host.router("valhalla-standard", started_ago=7200)
    cd = host.state / "cd"
    cd.mkdir()
    lock = cd / "lock"
    lock.write_text("")
    holder = subprocess.Popen(["flock", str(lock), "sleep", "30"])
    try:
        deadline = time.time() + 5
        while time.time() < deadline:
            probe = subprocess.run(["flock", "-n", str(lock), "true"], check=False)
            if probe.returncode != 0:
                break
            time.sleep(0.05)
        done = host.run("check")
    finally:
        holder.kill()
        holder.wait()
    assert done.returncode == 0, done.stderr
    assert "deploy pass is running" in done.stdout
    assert host.restarted() == []


def test_install_writes_a_two_minute_timer(host: Host) -> None:
    if os.geteuid() == 0:
        pytest.skip("install refuses root")
    config = host.tmp / "config"
    done = host.run("install", "--no-enable", XDG_CONFIG_HOME=str(config))
    assert done.returncode == 0, done.stderr
    units = config / "systemd" / "user"
    assert "OnUnitInactiveSec=2min" in (units / "routemaker-beta-routers.timer").read_text()
    assert 'restart-routers.sh" check' in (units / "routemaker-beta-routers.service").read_text()
    assert (host.state / "cd" / "bin" / "restart-routers.sh").exists()
