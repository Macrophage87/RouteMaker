"""The beta's alerts (review OPS-1): scripts/beta/alert.sh, and the release agent's calls to it
(docs/BETA-RUNBOOK.md, "Alerts").

Run against stub curl, compose and smoke-test, so nothing here touches a server or the network.
The stub curl records the body it would post and, separately, whether the webhook address ever
reached its command line (it must not: it goes in on standard input).
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
ALERT = REPO / "scripts" / "beta" / "alert.sh"
HOOK = "https://discord.com/api/webhooks/123/secret-token"

STUB_CURL = """#!/bin/sh
# records each posted body (one JSON per line) and fails the test run if the address is an argument
for a in "$@"; do
  case "$a" in *secret-token*) echo LEAKED >> "$STUB_DIR/leaks" ;; esac
  case "$a" in @*) cat "${a#@}" >> "$STUB_DIR/posts"; echo >> "$STUB_DIR/posts" ;; esac
done
cat > "$STUB_DIR/config"
printf '%s' "${STUB_CODE:-204}"
"""
STUB_SMOKE = """#!/bin/sh
if [ -f "$STUB_DIR/smoke-fails" ]; then cat "$STUB_DIR/smoke-fails"; exit 1; fi
echo "PASS  healthz (200)"
"""
STUB_COMPOSE = """#!/bin/sh
echo "$*" >> "$STUB_DIR/compose.log"
if [ -f "$STUB_DIR/ops-fails" ]; then cat "$STUB_DIR/ops-fails"; exit 1; fi
echo "ok"
"""


class Box:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.state = tmp / "state"
        self.state.mkdir()
        self.vars = self.state / "vars.sh"
        self.vars.write_text(
            f"export RM_STATE={self.state}\nexport RM_SRC={tmp}\nexport RM_PY={sys.executable}\n"
        )
        self.vars.chmod(0o600)
        for name, text in (("curl", STUB_CURL), ("smoke", STUB_SMOKE), ("compose", STUB_COMPOSE)):
            (tmp / name).write_text(text)
            (tmp / name).chmod(0o755)

    def run(self, *args: str, stdin: str = "", **env: str) -> subprocess.CompletedProcess:
        full = {
            "PATH": os.environ["PATH"],
            "HOME": str(self.tmp),
            "RM_VARS": str(self.vars),
            "CURL": str(self.tmp / "curl"),
            "RM_ALERT_SMOKE": str(self.tmp / "smoke"),
            "RM_ALERT_COMPOSE": str(self.tmp / "compose"),
            "STUB_DIR": str(self.tmp),
            "TMPDIR": str(self.tmp),
            **env,
        }
        return subprocess.run(
            ["bash", str(ALERT), *args],
            input=stdin,
            capture_output=True,
            text=True,
            env=full,
            check=False,
        )

    def hook(self) -> None:
        done = self.run("set-webhook", stdin=HOOK + "\n")
        assert done.returncode == 0, done.stderr

    def posts(self) -> list[str]:
        path = self.tmp / "posts"
        if not path.exists():
            return []
        return [json.loads(line)["content"] for line in path.read_text().splitlines() if line]


@pytest.fixture
def box(tmp_path: Path) -> Box:
    if shutil.which("flock") is None or shutil.which("sha256sum") is None:
        pytest.skip("needs flock and sha256sum")
    return Box(tmp_path)


def test_without_a_webhook_nothing_is_posted_and_nothing_fails(box: Box) -> None:
    done = box.run("send", "deploy", "broken", "broken: a rollback failed")
    assert done.returncode == 0
    assert "no webhook set" in done.stdout
    assert box.posts() == []


def test_the_webhook_is_kept_private_and_never_an_argument(box: Box) -> None:
    box.hook()
    hook_file = box.state / "alert-webhook"
    assert oct(hook_file.stat().st_mode & 0o777) == "0o600"
    done = box.run("test")
    assert done.returncode == 0
    assert box.posts() == [
        "RouteMaker beta: test message from alert.sh test; alerts reach this channel"
    ]
    assert not (box.tmp / "leaks").exists()
    assert HOOK in (box.tmp / "config").read_text()
    assert HOOK not in done.stdout + done.stderr


def test_a_webhook_that_is_not_plain_https_is_refused(box: Box) -> None:
    done = box.run("set-webhook", stdin="http://example.org/hook\n")
    assert done.returncode == 2
    assert not (box.state / "alert-webhook").exists()


def test_the_same_problem_is_posted_once_and_a_new_one_again(box: Box) -> None:
    box.hook()
    box.run("send", "deploy", "held v0.2.0", "held: v0.2.0: needs data from home")
    box.run("send", "deploy", "held v0.2.0", "held: v0.2.0: needs data from home")
    assert len(box.posts()) == 1
    box.run("send", "deploy", "failed v0.3.0", "rolled-back: v0.3.0 failed")
    assert len(box.posts()) == 2


def test_clearing_posts_only_after_an_alert(box: Box) -> None:
    box.hook()
    box.run("clear", "deploy", "working again")
    assert box.posts() == []
    box.run("send", "deploy", "broken", "broken: x")
    box.run("clear", "deploy", "working again")
    assert box.posts()[-1] == "RouteMaker beta: working again"
    box.run("clear", "deploy", "working again")
    assert len(box.posts()) == 2


def test_a_failed_post_is_tried_again_next_time(box: Box) -> None:
    box.hook()
    box.run("send", "deploy", "broken", "broken: x", STUB_CODE="500")
    box.run("send", "deploy", "broken", "broken: x")
    assert len(box.posts()) == 2


def test_watch_posts_a_failure_seen_twice_then_the_recovery(box: Box) -> None:
    box.hook()
    assert box.run("watch").returncode == 0
    assert box.posts() == []
    assert "exec -T worker ./manage.py check_operations" in (box.tmp / "compose.log").read_text()
    fails = "PASS  healthz (200)\nFAIL  a route: expected 200, got 502\n"
    (box.tmp / "smoke-fails").write_text(fails)
    box.run("watch")
    assert box.posts() == []  # once could be a router restarting
    box.run("watch")
    box.run("watch")
    posts = box.posts()
    assert len(posts) == 1
    assert "FAIL  a route: expected 200, got 502" in posts[0]
    assert "PASS" not in posts[0]
    (box.tmp / "smoke-fails").unlink()
    box.run("watch")
    assert box.posts()[-1] == "RouteMaker beta: working again: the local smoke tests pass"


def test_watch_posts_what_check_operations_reports(box: Box) -> None:
    box.hook()
    (box.tmp / "ops-fails").write_text("transit: the schedule runs out on 2026-11-27\n")
    box.run("watch")
    box.run("watch")
    assert box.posts() == [
        "RouteMaker beta: check_operations reports:\ntransit: the schedule runs out on 2026-11-27"
    ]


def test_a_single_failure_that_clears_is_never_posted(box: Box) -> None:
    box.hook()
    (box.tmp / "smoke-fails").write_text("FAIL  healthz: expected 200, got 502\n")
    box.run("watch")
    (box.tmp / "smoke-fails").unlink()
    box.run("watch")
    (box.tmp / "smoke-fails").write_text("FAIL  healthz: expected 200, got 502\n")
    box.run("watch")
    assert box.posts() == []


def test_watch_stands_aside_while_a_deploy_pass_holds_the_lock(box: Box) -> None:
    box.hook()
    (box.tmp / "smoke-fails").write_text("FAIL  healthz: expected 200, got 502\n")
    cd = box.state / "cd"
    cd.mkdir()
    lock = cd / "lock"
    lock.touch()
    holder = subprocess.Popen(["flock", str(lock), "sleep", "30"])
    try:
        for _ in range(50):
            if subprocess.run(["flock", "-n", str(lock), "true"], check=False).returncode:
                break
        for _ in range(3):
            assert "deploy pass is running" in box.run("watch").stdout
    finally:
        holder.kill()
        holder.wait()
    assert box.posts() == []


def test_a_long_message_is_cut_to_what_discord_takes(box: Box) -> None:
    box.hook()
    box.run("note", "x" * 5000)
    assert len(box.posts()[0]) <= 2000


def test_a_report_whose_numbers_change_is_still_the_same_failure(box: Box) -> None:
    """check_operations says "running for 610s", then "620s": one failure, posted once."""
    box.hook()
    for seconds in (600, 610, 620, 630):
        (box.tmp / "ops-fails").write_text(
            f"job 12 has been running for {seconds}s, past its budget\n7.5 GiB free\n"
        )
        box.run("watch")
    posts = box.posts()
    assert len(posts) == 1
    assert "running for 610s" in posts[0]
