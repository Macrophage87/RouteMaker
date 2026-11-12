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
import time
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
cat "$STUB_DIR/config" >> "$STUB_DIR/configs"
# STUB_FAIL_AFTER=N: the first N posts are taken, the rest refused (a partial failure)
if [ -n "${STUB_FAIL_AFTER:-}" ]; then
  n=$(cat "$STUB_DIR/count" 2>/dev/null || echo 0); echo $((n + 1)) > "$STUB_DIR/count"
  if [ "$n" -ge "$STUB_FAIL_AFTER" ]; then
    sed -i '$d' "$STUB_DIR/posts"; printf 500; exit 0
  fi
fi
printf '%s' "${STUB_CODE:-204}"
"""
STUB_SMOKE = """#!/bin/sh
if [ -f "$STUB_DIR/smoke-fails" ]; then cat "$STUB_DIR/smoke-fails"; exit 1; fi
echo "PASS  healthz (200)"
"""
STUB_COMPOSE = """#!/bin/sh
echo "$*" >> "$STUB_DIR/compose.log"
case "$*" in
  logs*) cat "$STUB_DIR/api-log" 2>/dev/null; exit 0 ;;
  *" ps "*) cat "$STUB_DIR/ps" 2>/dev/null; exit 0 ;;
esac
if [ -f "$STUB_DIR/ops-fails" ]; then cat "$STUB_DIR/ops-fails"; exit 1; fi
echo "ok"
"""
STUB_DOCKER = """#!/bin/sh
case "$1" in
  inspect) cat "$STUB_DIR/inspect" 2>/dev/null ;;
  info) echo /var/lib/docker ;;
esac
"""
STUB_DF = """#!/bin/sh
echo "Filesystem 1048576-blocks Used Available Capacity Mounted on"
echo "/dev/root 100000 50000 $(cat "$STUB_DIR/df-free" 2>/dev/null || echo 50000) 50% $2"
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
        (tmp / "meminfo").write_text("MemTotal: 9000000 kB\nMemAvailable: 2000000 kB\n")
        for name, text in (
            ("curl", STUB_CURL),
            ("smoke", STUB_SMOKE),
            ("compose", STUB_COMPOSE),
            ("docker", STUB_DOCKER),
            ("df", STUB_DF),
        ):
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
            "RM_ALERT_DOCKER": str(self.tmp / "docker"),
            "RM_ALERT_DF": str(self.tmp / "df"),
            "RM_ALERT_MEMINFO": str(self.tmp / "meminfo"),
            "RM_ALERT_OPENSSL": str(self.tmp / "no-openssl"),
            "STUB_DIR": str(self.tmp),
            "TMPDIR": str(self.tmp),
            "RM_ALERT_CHUNK_SLEEP": "0",
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

    def bodies(self) -> list[dict]:
        path = self.tmp / "posts"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line]

    def posts(self) -> list[str]:
        return [body["content"] for body in self.bodies()]


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


def test_watch_reports_a_pc_backup_copy_that_has_stopped_then_its_return(box: Box) -> None:
    box.hook()
    box.run("watch")
    assert box.posts() == []  # no PC copy set up: nothing said
    mark = box.state / "pc-backup-pull"
    mark.write_text("routemaker-20261101T070000Z.dump.age\n")
    box.run("watch")
    assert box.posts() == []  # fresh
    old = mark.stat().st_mtime - 37 * 3600
    os.utime(mark, (old, old))
    box.run("watch")
    box.run("watch")
    posts = box.posts()
    assert len(posts) == 1, posts  # once, not at every check
    assert "the PC has not copied the beta's backups for over 36 h" in posts[0]
    assert "routemaker-20261101T070000Z.dump.age" in posts[0]
    mark.write_text("routemaker-20261103T070000Z.dump.age\n")
    box.run("watch")
    assert box.posts()[-1].startswith("RouteMaker beta: the PC is copying the beta's backups again")


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


RELEASE_HOOK = "https://discord.com/api/webhooks/456/release-token"


def release_hook(box: Box) -> None:
    done = box.run("set-release-webhook", stdin=RELEASE_HOOK + "\n")
    assert done.returncode == 0, done.stderr


def configs(box: Box) -> list[str]:
    path = box.tmp / "configs"
    return [line for line in path.read_text().splitlines() if line] if path.exists() else []


def test_release_notes_without_their_webhook_post_nothing(box: Box) -> None:
    box.hook()
    notes = box.tmp / "v0.9.1.md"
    notes.write_text("**Fixed**\n- a thing\n")
    done = box.run("release-notes", "v0.9.1", str(notes))
    assert done.returncode == 0
    assert "no release webhook set" in done.stdout
    assert box.posts() == []


def test_release_notes_go_to_their_own_channel_once_per_tag(box: Box) -> None:
    box.hook()
    release_hook(box)
    assert oct((box.state / "release-webhook").stat().st_mode & 0o777) == "0o600"
    notes = box.tmp / "v0.9.1.md"
    notes.write_text("**Fixed**\n- Planning no longer sticks at keyboard height.\n")
    assert box.run("release-notes", "v0.9.1", str(notes)).returncode == 0
    assert box.posts() == [
        "**RouteMaker v0.9.1 is on beta**\n\n"
        "**Fixed**\n- Planning no longer sticks at keyboard height."
    ]
    assert configs(box) == [f'url = "{RELEASE_HOOK}"']
    box.run("release-notes", "v0.9.1", str(notes))
    assert len(box.posts()) == 1
    assert not (box.tmp / "leaks").exists()
    # The alerts channel keeps its own webhook.
    box.run("test")
    assert configs(box)[-1] == f'url = "{HOOK}"'


def test_a_hand_stored_release_webhook_is_read_as_is(box: Box) -> None:
    """The owner may write $RM_STATE/release-webhook himself (umask 077); a CR is dropped."""
    (box.state / "release-webhook").write_text(RELEASE_HOOK + "\r\n")
    assert box.run("release-test").returncode == 0
    assert configs(box) == [f'url = "{RELEASE_HOOK}"']
    assert box.posts() == ["RouteMaker: test message; release notes reach this channel"]


def test_a_tag_without_notes_posts_its_title(box: Box) -> None:
    release_hook(box)
    box.run("release-notes", "v0.9.2", str(box.tmp / "missing.md"))
    assert box.posts() == ["**RouteMaker v0.9.2 is on beta**"]


def test_long_release_notes_are_split_at_line_ends(box: Box) -> None:
    release_hook(box)
    lines = [f"- change number {n} " + "x" * 80 for n in range(60)]
    notes = box.tmp / "v1.0.0.md"
    notes.write_text("\n".join(lines) + "\n")
    box.run("release-notes", "v1.0.0", str(notes))
    posts = box.posts()
    assert len(posts) > 1
    assert all(len(p) <= 2000 for p in posts)
    body = "\n".join(posts).splitlines()
    assert [line for line in body if line.startswith("- ")] == lines


def test_a_failed_release_post_is_tried_again(box: Box) -> None:
    release_hook(box)
    box.run("release-notes", "v0.9.3", STUB_CODE="500")
    assert box.run("release-notes", "v0.9.3").returncode == 0
    assert len(box.posts()) == 2
    box.run("release-notes", "v0.9.3")
    assert len(box.posts()) == 2


def test_release_notes_refuse_a_tag_that_is_not_a_version(box: Box) -> None:
    release_hook(box)
    assert box.run("release-notes", "../../etc").returncode == 2
    assert box.posts() == []


def test_release_notes_keep_any_text_and_never_mention(box: Box) -> None:
    release_hook(box)
    text = "Quotes \"x\" and 'y', a back\\slash, a\ttab, café 🚲, and @everyone <@&123>"
    notes = box.tmp / "v0.9.4.md"
    notes.write_text(text + "\n", encoding="utf-8")
    box.run("release-notes", "v0.9.4", str(notes))
    (body,) = box.bodies()
    assert body["content"] == "**RouteMaker v0.9.4 is on beta**\n\n" + text
    assert body["allowed_mentions"] == {"parse": []}


def test_a_line_longer_than_a_message_is_cut_by_characters(box: Box) -> None:
    release_hook(box)
    line = "é🚲" * 2000  # 4,000 characters, each more than one byte
    notes = box.tmp / "v0.9.5.md"
    notes.write_text(line + "\n", encoding="utf-8")
    assert box.run("release-notes", "v0.9.5", str(notes)).returncode == 0
    posts = box.posts()
    assert len(posts) == 4  # the title, then three pieces of the line
    assert all(len(p) <= 1900 for p in posts)
    assert "".join(posts[1:]) == line


def test_a_bad_release_address_is_not_recorded_as_posted(box: Box) -> None:
    (box.state / "release-webhook").write_text("http://example.org/hook\n")
    done = box.run("release-notes", "v0.9.6")
    assert done.returncode == 0
    assert box.posts() == []
    posted = box.state / "alerts" / "release-posted"
    assert not posted.exists() or "v0.9.6" not in posted.read_text()


def test_a_partly_posted_release_resumes_where_it_stopped(box: Box) -> None:
    release_hook(box)
    lines = [f"- change number {n} " + "x" * 80 for n in range(40)]  # three messages
    notes = box.tmp / "v0.9.7.md"
    notes.write_text("\n".join(lines) + "\n")
    done = box.run("release-notes", "v0.9.7", str(notes), STUB_FAIL_AFTER="2")
    assert done.returncode == 1
    assert len(box.posts()) == 2
    assert (box.state / "alerts" / "release-posted").read_text() == "v0.9.7:2\n"
    assert box.run("release-notes", "v0.9.7", str(notes)).returncode == 0
    posts = box.posts()
    assert len(posts) == 3
    assert [line for line in "\n".join(posts).splitlines() if line.startswith("- ")] == lines
    assert (box.state / "alerts" / "release-posted").read_text() == "v0.9.7\n"


def test_no_alerts_webhook_still_counts_as_done_for_the_owners_channel(box: Box) -> None:
    """post_to's "not sent" is the release channel's to see; the owner's checks behave as before."""
    done = box.run("note", "deployed v0.9.0")
    assert done.returncode == 0


# --- the off-host uptime check (alert.sh heartbeat; Healthchecks.io, the owner 2026-10-29) ---

PING = "https://hc-ping.example/0b1c2d3e-placeholder"
STUB_HEALTH_CURL = """#!/bin/sh
# the api's /healthz answers from $STUB_DIR/healthz (absent: refused); a ping records its config
for a in "$@"; do
  case "$a" in *placeholder*) echo LEAKED >> "$STUB_DIR/leaks" ;; esac
  case "$a" in
    */healthz) echo "$*" >> "$STUB_DIR/health-calls"
      [ -f "$STUB_DIR/healthz" ] || exit 7
      cat "$STUB_DIR/healthz"; exit 0 ;;
  esac
done
cat >> "$STUB_DIR/pings"
printf '%s' "${STUB_CODE:-200}"
"""


def heartbeat_box(box: Box, env_lines: str) -> None:
    (box.tmp / "hc-curl").write_text(STUB_HEALTH_CURL)
    (box.tmp / "hc-curl").chmod(0o755)
    (box.tmp / ".env").write_text(env_lines)


def pings(box: Box) -> str:
    path = box.tmp / "pings"
    return path.read_text() if path.exists() else ""


def beat(box: Box) -> subprocess.CompletedProcess:
    done = box.run("heartbeat", CURL=str(box.tmp / "hc-curl"))
    assert done.returncode == 0, done.stderr
    return done


def test_the_heartbeat_pings_while_the_api_is_healthy(box: Box) -> None:
    heartbeat_box(
        box, f"RM_BETA_HOST=beta.example\nBETA_API_PORT=8099\nHEALTHCHECK_PING_URL='{PING}'\n"
    )
    (box.tmp / "healthz").write_text("ok\n")
    done = beat(box)
    assert pings(box) == f'url = "{PING}"\n', done.stdout
    calls = (box.tmp / "health-calls").read_text()
    assert "http://127.0.0.1:8099/healthz" in calls and "Host: beta.example" in calls
    assert not (box.tmp / "leaks").exists(), "the ping address reached curl's command line"


@pytest.mark.parametrize("answer", [None, "degraded\n"])
def test_the_heartbeat_stays_silent_while_the_api_is_down(box: Box, answer: str | None) -> None:
    heartbeat_box(box, f"RM_BETA_HOST=beta.example\nHEALTHCHECK_PING_URL={PING}\n")
    if answer is not None:
        (box.tmp / "healthz").write_text(answer)
    done = beat(box)
    assert pings(box) == ""
    assert "not pinged" in done.stdout


def test_without_a_ping_address_the_heartbeat_does_nothing(box: Box) -> None:
    heartbeat_box(
        box, "RM_BETA_HOST=beta.example\n#HEALTHCHECK_PING_URL=https://hc-ping.example/x\n"
    )
    (box.tmp / "healthz").write_text("ok\n")
    done = beat(box)
    assert pings(box) == "" and not (box.tmp / "health-calls").exists()
    assert "no HEALTHCHECK_PING_URL" in done.stdout


def test_a_ping_address_that_is_not_plain_https_is_not_used(box: Box) -> None:
    heartbeat_box(box, "RM_BETA_HOST=beta.example\nHEALTHCHECK_PING_URL=http://hc-ping.example/x\n")
    (box.tmp / "healthz").write_text("ok\n")
    done = beat(box)
    assert pings(box) == ""
    assert "not a plain https://" in done.stderr


def test_install_writes_the_heartbeat_timer_beside_the_checks(box: Box) -> None:
    if os.geteuid() == 0:
        pytest.skip("install refuses root")
    config = box.tmp / "config"
    done = box.run("install", "--no-enable", XDG_CONFIG_HOME=str(config))
    assert done.returncode == 0, done.stderr
    units = config / "systemd" / "user"
    timer = (units / "routemaker-beta-heartbeat.timer").read_text()
    assert "OnUnitActiveSec=5min" in timer
    assert 'alert.sh" heartbeat' in (units / "routemaker-beta-heartbeat.service").read_text()
    assert (units / "routemaker-beta-alert.timer").exists()
    assert "no HEALTHCHECK_PING_URL" in done.stdout


# scripts/route_scorecard.py as alert.sh calls it: `nightly` writes a run (and swaps a map in
# the middle when asked), `findings` prints what the test put there.
STUB_SCORECARD = """import os, sys, pathlib, time
stub = pathlib.Path(os.environ["STUB_DIR"])
args = sys.argv[1:]
(stub / "scorecard.log").open("a").write(" ".join(args) + "\\n")
if args[0] == "nightly" and (stub / "crash").exists():
    sys.exit("Traceback: something broke")
if args[0] == "nightly":
    folder = pathlib.Path(args[args.index("--dir") + 1])
    n = len(list(folder.glob("run-*"))) + 1
    (folder / f"run-2026111{n}T0800Z.json").write_text("{}")
    if (stub / "swap").exists():
        link = stub / "data" / "tiles" / "standard" / "current"
        link.unlink()
        link.symlink_to("build-2")
elif args[0] == "findings":
    f = stub / "findings"
    if f.exists():
        sys.stdout.write(f.read_text())
"""


def scorecard_box(box: Box) -> dict:
    (box.tmp / "scripts").mkdir(exist_ok=True)
    (box.tmp / "scripts" / "route_scorecard.py").write_text(STUB_SCORECARD)
    tiles = box.tmp / "data" / "tiles" / "standard"
    tiles.mkdir(parents=True)
    (tiles / "current").symlink_to("build-1")
    return {"RM_BETA_HOST": "beta.test", "RM_SCORECARD_DATA_ROOT": str(box.tmp / "data")}


def test_the_scorecard_posts_what_moved_once_and_nothing_when_nothing_moved(box: Box) -> None:
    box.hook()
    env = scorecard_box(box)
    done = box.run("scorecard", **env)
    assert done.returncode == 0, done.stderr
    assert "nothing moved" in done.stdout
    assert box.posts() == []
    log = (box.tmp / "scorecard.log").read_text()
    assert "nightly --base-url http://127.0.0.1:8087 --host beta.test --dir" in log

    found = "route scorecard 20261112T0800Z: 1 changes\nmall · default · base: miles 2.00 -> 3.00"
    (box.tmp / "findings").write_text("20261112T0800Z\n" + found + "\n")
    box.run("scorecard", **env)
    box.run("scorecard", **env)
    assert box.posts() == ["RouteMaker beta: " + found]
    (box.tmp / "findings").write_text("20261113T0800Z\n" + found + "\n")
    box.run("scorecard", **env)
    assert len(box.posts()) == 2


def test_a_scorecard_run_that_saw_a_map_swap_is_kept_as_mixed_and_says_nothing(box: Box) -> None:
    box.hook()
    env = scorecard_box(box)
    (box.tmp / "findings").write_text("20261111T0800Z\nsomething moved\n")
    (box.tmp / "swap").write_text("")
    done = box.run("scorecard", **env)
    assert "kept as mixed" in done.stdout
    assert box.posts() == []
    kept = sorted(p.name for p in (box.state / "scorecard").iterdir())
    assert kept == ["run-20261111T0800Z.mixed.json"]
    assert "findings" not in (box.tmp / "scorecard.log").read_text()


def test_the_scorecard_waits_for_the_lock_and_skips_a_long_deploy(box: Box) -> None:
    env = scorecard_box(box)
    cd = box.state / "cd"
    cd.mkdir()
    (cd / "lock").write_text("")
    # A watch pass holding the lock briefly: the scorecard waits, then runs.
    holder = subprocess.Popen(["flock", str(cd / "lock"), "sleep", "2"])
    try:
        time.sleep(0.3)
        done = box.run("scorecard", RM_SCORECARD_LOCK_WAIT_S="30", **env)
    finally:
        holder.kill()
    assert "nightly" in (box.tmp / "scorecard.log").read_text()
    # A deploy holding it past the wait: the night is skipped.
    (box.tmp / "scorecard.log").unlink()
    holder = subprocess.Popen(["flock", str(cd / "lock"), "sleep", "10"])
    try:
        time.sleep(0.3)
        done = box.run("scorecard", RM_SCORECARD_LOCK_WAIT_S="1", **env)
    finally:
        holder.kill()
    assert "scorecard skipped tonight" in done.stdout
    assert not (box.tmp / "scorecard.log").exists()


def test_a_scorecard_run_that_fails_is_posted_once_a_day(box: Box) -> None:
    box.hook()
    env = scorecard_box(box)
    (box.tmp / "crash").write_text("")
    box.run("scorecard", **env)
    box.run("scorecard", **env)
    (only,) = box.posts()
    assert "the nightly route scorecard did not run" in only

# --- what a tester sees (backlog 2026-11-12, "Ready for a dozen testers") ---------------------


def test_watch_plans_on_the_trail_graphs_unless_switched_off(box: Box) -> None:
    (box.tmp / "smoke").write_text('#!/bin/sh\necho "$*" >> "$STUB_DIR/smoke.log"\n')
    box.run("watch")
    box.run("watch", RM_ALERT_TRAILS="0")
    assert (box.tmp / "smoke.log").read_text().splitlines() == ["--local --trails", "--local"]


def log_line(path: str, status: int, micros: int) -> str:
    return f'[12/Nov/2026:20:00:00 +0000] "POST {path}" {status} 120 {micros} "Mozilla/5.0"\n'


def test_server_errors_in_the_api_log_are_posted_then_cleared(box: Box) -> None:
    box.hook()
    (box.tmp / "api-log").write_text(log_line("/api/route", 500, 1000) * 2)
    box.run("watch")
    assert box.posts() == []  # two is under our default of three
    three = log_line("/api/route", 500, 1000) * 2 + log_line("/api/geocode", 502, 9)
    (box.tmp / "api-log").write_text(three)
    box.run("watch")
    posts = box.posts()
    assert len(posts) == 1
    assert "3 requests with a server error" in posts[0]
    assert "POST /api/route 500" in posts[0]
    assert "--since 10m api" in (box.tmp / "compose.log").read_text()
    (box.tmp / "api-log").write_text(log_line("/api/route", 200, 1000))
    box.run("watch")
    assert "server errors are back under" in box.posts()[-1]


def test_slow_route_plans_are_posted(box: Box) -> None:
    box.hook()
    lines = log_line("/api/route", 200, 31_000_000) * 3
    lines += log_line("/tiles/stress/:zxy", 200, 60_000_000) * 5
    (box.tmp / "api-log").write_text(lines)
    box.run("watch")
    posts = box.posts()
    assert len(posts) == 1
    assert "3 route plans took over 30 s" in posts[0]


def test_a_restart_or_memory_kill_is_posted_once(box: Box) -> None:
    box.hook()
    (box.tmp / "ps").write_text("abc123\ndef456\n")
    (box.tmp / "inspect").write_text("/beta-api-1 0 false\n/beta-photon-1 2 false\n")
    box.run("watch")
    assert box.posts() == []  # the first check only records the counts
    (box.tmp / "inspect").write_text("/beta-api-1 1 true\n/beta-photon-1 2 false\n")
    box.run("watch")
    posts = box.posts()
    assert len(posts) == 1
    assert "beta-api-1 restarted 1 time(s), killed for memory" in posts[0]
    assert "photon" not in posts[0]
    box.run("watch")
    assert len(box.posts()) == 1
    # a deploy recreates containers and their counts start again: no alert
    (box.tmp / "inspect").write_text("/beta-api-1 0 false\n/beta-photon-1 0 false\n")
    box.run("watch")
    assert len(box.posts()) == 1


def test_low_memory_and_disk_are_posted_when_seen_twice(box: Box) -> None:
    box.hook()
    (box.tmp / "meminfo").write_text("MemAvailable: 200000 kB\n")
    (box.tmp / "df-free").write_text("1500")
    box.run("watch")
    assert box.posts() == []
    box.run("watch")
    posts = box.posts()
    assert any("only 195 MiB of memory available" in p for p in posts)
    short = "short of disk: / (1500 MiB free) /var/lib/docker (1500 MiB free)"
    assert any(short in p for p in posts)
    (box.tmp / "meminfo").write_text("MemAvailable: 2000000 kB\n")
    (box.tmp / "df-free").write_text("50000")
    box.run("watch")
    assert any("memory is back" in p for p in box.posts())
    assert any("enough disk again" in p for p in box.posts())


def test_the_public_address_and_its_certificate(box: Box) -> None:
    box.hook()
    (box.tmp / ".env").write_text("RM_BETA_HOST=beta.example.org\n")
    # the stub curl answers 204 with no body: not the api's "ok"
    box.run("watch")
    box.run("watch")
    assert any("the public address does not answer" in p and "HTTP 204" in p for p in box.posts())
    openssl = box.tmp / "openssl"
    openssl.write_text(
        "#!/bin/sh\n"
        'case "$1" in x509) '
        "echo \"notAfter=$(date -u -d '+5 days' '+%b %d %H:%M:%S %Y GMT')\";; esac\n"
    )
    openssl.chmod(0o755)
    box.run("watch", RM_ALERT_OPENSSL=str(openssl))
    assert any("certificate ends in" in p for p in box.posts())
    for post in box.posts():
        assert "beta.example.org" not in post  # the address stays out of Discord


def status_of(box: Box) -> dict | None:
    path = box.tmp / "data" / "status" / "status.json"
    return json.loads(path.read_text()) if path.exists() else None


def test_riders_see_updating_during_a_deploy_and_nothing_after(box: Box) -> None:
    (box.tmp / "data" / "status").mkdir(parents=True)
    env = {"RM_DATA": str(box.tmp / "data")}
    assert box.run("status", "updating", **env).returncode == 0
    assert status_of(box) == {"state": "updating"}
    path = box.tmp / "data" / "status" / "status.json"
    assert oct(path.stat().st_mode & 0o777) == "0o644"  # nginx reads it
    assert box.run("status", "done", **env).returncode == 0
    assert status_of(box) is None  # all well: no file, the app's 404


def test_riders_see_what_is_down_once_it_is_seen_twice(box: Box) -> None:
    (box.tmp / "data" / "status").mkdir(parents=True)
    env = {"RM_DATA": str(box.tmp / "data")}
    (box.tmp / "smoke-fails").write_text(
        "FAIL  a mountain-bike route is planned on the mtb graph: no match\n"
        "FAIL  place search finds Union Station: no match\n"
    )
    box.run("watch", **env)
    assert status_of(box) is None  # once could be a router restarting
    box.run("watch", **env)
    assert status_of(box) == {"state": "degraded", "parts": ["trails", "search"]}
    # a deploy's "updating" wins while it lasts
    box.run("status", "updating", **env)
    assert status_of(box) == {"state": "updating"}
    box.run("status", "done", **env)
    assert status_of(box)["state"] == "degraded"
    (box.tmp / "smoke-fails").unlink()
    box.run("watch", **env)
    assert status_of(box) is None


def test_no_status_directory_writes_nothing(box: Box) -> None:
    assert box.run("status", "updating", RM_DATA=str(box.tmp / "data")).returncode == 0
    assert not (box.tmp / "data").exists()


def test_restarts_in_back_to_back_checks_are_each_posted(box: Box) -> None:
    """The review of #1197: the alert's own record must not overwrite the counts it compares."""
    box.hook()
    (box.tmp / "ps").write_text("abc123\n")
    inspect = box.tmp / "inspect"
    for count in range(4):
        inspect.write_text(f"/beta-api-1 {count} true\n")
        box.run("watch")
    assert len([p for p in box.posts() if "beta-api-1 restarted" in p]) == 3


def test_the_planners_busy_503_is_not_a_server_error(box: Box) -> None:
    box.hook()
    (box.tmp / "api-log").write_text(log_line("/api/route", 503, 1000) * 6)
    box.run("watch")
    assert not any("server error" in p for p in box.posts())


def test_riders_see_the_fault_even_when_discord_refuses_the_alert(box: Box) -> None:
    (box.tmp / "data" / "status").mkdir(parents=True)
    env = {"RM_DATA": str(box.tmp / "data")}
    box.hook()
    (box.tmp / "smoke-fails").write_text("FAIL  place search finds Union Station: no match\n")
    box.run("watch", STUB_CODE="500", **env)
    box.run("watch", STUB_CODE="500", **env)
    assert status_of(box) == {"state": "degraded", "parts": ["search"]}
