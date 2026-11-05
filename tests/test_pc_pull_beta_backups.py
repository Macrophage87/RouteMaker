"""scripts/pc/pull-beta-backups.sh: the PC's nightly copy of the beta's encrypted dumps
(docs/OPERATIONS.md, "Off-box copies of beta backups").

Run with stub ssh, rsync, scp and sudo on PATH: the stub ssh runs the "remote" command locally
against a temporary folder standing in for the beta's backups folder, so nothing here touches a
server or the network.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "pc" / "pull-beta-backups.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")

STUB_SSH = r"""#!/usr/bin/env bash
# skip ssh options, take the host, run the rest here
while [ $# -gt 0 ]; do
	case "$1" in -o) shift 2 ;; -*) shift ;; *) break ;; esac
done
host=$1; shift
printf '%s\t%s\n' "$host" "$*" >>"$STUB_LOG"
if [ -n "${STUB_SSH_FAIL:-}" ]; then
	echo "ssh: connect to host $host: Connection timed out" >&2
	exit 255
fi
exec bash -c "$*"
"""

# rsync/scp: copy host:path to the destination (the last two arguments). STUB_TRUNCATE copies
# only half, as a dropped connection would.
STUB_COPY = r"""#!/usr/bin/env bash
src=${@: -2:1}; dst=${@: -1}
printf '%s\t%s\n' "$(basename "$0")" "$*" >>"$STUB_LOG"
path=${src#*:}
if [ -n "${STUB_TRUNCATE:-}" ]; then
	head -c "$(( $(stat -c %s "$path") / 2 ))" "$path" >"$dst"
	exit 12
fi
cp "$path" "$dst"
"""

STUB_SUDO = r"""#!/usr/bin/env bash
[ "$1" = -n ] && shift
exec "$@"
"""


_clock: dict[str, datetime] = {}


@pytest.fixture(autouse=True)
def _one_clock_per_test():
    """Every name a test makes is stamped from one clock reading, taken as the test starts, so a
    name made again after the script has run is the same name, whichever second it is now."""
    _clock["now"] = datetime.now(UTC)
    yield
    _clock.clear()


def name(hours_ago: float) -> str:
    t = _clock["now"] - timedelta(hours=hours_ago)
    return f"routemaker-{t:%Y%m%dT%H%M%SZ}.dump.age"


@pytest.fixture()
def env(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stubs = {"ssh": STUB_SSH, "rsync": STUB_COPY, "scp": STUB_COPY, "sudo": STUB_SUDO}
    for stub, text in stubs.items():
        (bin_dir / stub).write_text(text)
        (bin_dir / stub).chmod(0o755)
    remote = tmp_path / "beta-backups"
    remote.mkdir()
    dest = tmp_path / "Documents" / "beta-backups"
    return {
        "bin": bin_dir,
        "remote": remote,
        "dest": dest,
        "log": tmp_path / "stub.log",
        "env": {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "STUB_LOG": str(tmp_path / "stub.log"),
            "RM_BETA_SSH": "beta-host",
            "RM_BACKUP_DIR": str(dest),
            "RM_BETA_BACKUPS": str(remote),
        },
    }


def run(env: dict, **extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env={**env["env"], **extra},
        capture_output=True,
        text=True,
        timeout=60,
    )


def put(folder: Path, file_name: str, size: int = 1000) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / file_name
    path.write_bytes(os.urandom(size))
    return path


def files(folder: Path) -> set[str]:
    return {p.name for p in folder.iterdir()} if folder.exists() else set()


def test_the_pc_and_beta_names_come_from_the_environment_or_a_local_file_never_the_repo(env, tmp_path) -> None:
    put(env["remote"], name(6), size=5000)
    bare = {k: v for k, v in env["env"].items() if k not in ("RM_BETA_SSH", "RM_BACKUP_DIR")}
    missing = subprocess.run(["bash", str(SCRIPT)], env=bare, capture_output=True, text=True, timeout=60)
    assert missing.returncode == 1 and "set RM_BETA_SSH and RM_BACKUP_DIR" in missing.stderr
    local = tmp_path / ".config" / "routemaker" / "pull-beta-backups.env"
    local.parent.mkdir(parents=True)
    local.write_text(f"RM_BETA_SSH=beta-host\nRM_BACKUP_DIR={env['dest']}\n")
    ok = subprocess.run(["bash", str(SCRIPT)], env=bare, capture_output=True, text=True, timeout=60)
    assert ok.returncode == 0, ok.stderr
    assert (env["dest"] / name(6)).exists()


def test_only_the_encrypted_dumps_are_copied_whole(env) -> None:
    wanted = {name(30), name(6), name(54)}
    for n in wanted:
        put(env["remote"], n, size=5000)
    # Beside them on the beta: plain dumps, a half-written one, the recipients file.
    put(env["remote"], "pre-release-20261101T030000Z.dump")
    put(env["remote"], name(1).removesuffix(".age"))
    put(env["remote"], name(0.5) + ".part")
    put(env["remote"], "age-recipients.txt")

    result = run(env)

    assert result.returncode == 0, result.stderr
    assert files(env["dest"]) == wanted | {"pull-beta-backups.log"}
    for n in wanted:
        assert (env["dest"] / n).read_bytes() == (env["remote"] / n).read_bytes()
    log = (env["dest"] / "pull-beta-backups.log").read_text().splitlines()
    assert len(log) == 1 and " ok host=beta-host copied=3 " in log[0] and "via=rsync" in log[0]
    # On the beta: one listing, the rsync copies, then the run is recorded; nothing else.
    calls = env["log"].read_text().splitlines()
    remote_cmds = [line for line in calls if line.startswith("beta-host\t")]
    assert len(remote_cmds) == 2, remote_cmds
    assert "find " in remote_cmds[0] and "pc-backup-pull" in remote_cmds[1]
    assert not any("rm " in c for c in remote_cmds)

    again = run(env)
    assert again.returncode == 0, again.stderr
    assert " copied=0 " in (env["dest"] / "pull-beta-backups.log").read_text().splitlines()[-1]


def test_retention_keeps_the_newest_7_and_touches_nothing_else(env) -> None:
    older = [name(h) for h in range(20, 20 + 24 * 16, 24)]  # 16 older copies already here
    for n in older:
        put(env["dest"], n)
    put(env["dest"], "notes.txt")
    new = [name(2), name(3)]
    for n in new:
        put(env["remote"], n)
    put(env["remote"], name(24 * 30))  # older than every kept copy: not pulled back

    result = run(env)

    assert result.returncode == 0, result.stderr
    dumps = sorted(n for n in files(env["dest"]) if n.endswith(".dump.age"))
    every = sorted([*new, *older], reverse=True)
    assert dumps == sorted(every[:7])
    assert "notes.txt" in files(env["dest"])
    assert not any(n.endswith(".part") for n in files(env["dest"]))


def test_a_copy_that_breaks_off_leaves_no_part_and_keeps_the_past_weeks_copies(env) -> None:
    hours = range(30, 30 + 24 * 8, 24)  # 8 copies, 30 h to 198 h old
    old = [name(h) for h in hours]
    for n in old:
        put(env["dest"], n)
    put(env["remote"], name(2), size=4000)

    result = run(env, STUB_TRUNCATE="1")

    assert result.returncode == 1
    assert "did not copy whole" in result.stderr
    week = {n for h, n in zip(hours, old, strict=True) if h <= 156}
    assert files(env["dest"]) == week | {"pull-beta-backups.log"}
    assert "FAILED" in (env["dest"] / "pull-beta-backups.log").read_text()


def test_a_failing_ssh_exits_non_zero_and_still_drops_copies_past_the_week(env) -> None:
    old = [name(h) for h in range(30, 30 + 24 * 16, 24)]
    for n in old:
        put(env["dest"], n)
    put(env["remote"], name(2))

    result = run(env, STUB_SSH_FAIL="1")

    assert result.returncode != 0
    assert "ssh beta-host did not connect" in result.stderr
    assert "Is the beta (beta-host) reachable" in result.stderr
    # 30 h to 150 h old stay (six copies, under the keep); 174 h and older go.
    young = {n for h, n in zip(range(30, 30 + 24 * 16, 24), old, strict=True) if h <= 156}
    assert files(env["dest"]) == young | {"pull-beta-backups.log"}
    log = (env["dest"] / "pull-beta-backups.log").read_text()
    assert "FAILED ssh beta-host did not connect" in log
    assert "(removed 10 by age or count)" in log
    # A failed run is not recorded on the beta, so the beta's alert sees the copy go stale.
    assert not (Path(env["env"]["HOME"]) / "routemaker-beta-state").exists()


def test_a_long_run_of_failures_leaves_only_the_newest_copy(env) -> None:
    old = [name(h) for h in (24 * 10, 24 * 11, 24 * 12, 24 * 13)]
    for n in old:
        put(env["dest"], n)

    result = run(env, STUB_SSH_FAIL="1")

    assert result.returncode == 1
    assert files(env["dest"]) == {old[0], "pull-beta-backups.log"}


def test_copies_past_the_week_go_once_the_beta_answers_again(env) -> None:
    """The beta's backups failed for ten days: it now holds one fresh dump, and the copies here
    from before the gap are dropped by age, not kept because there are fewer than seven."""
    stale = [name(24 * d) for d in range(10, 17)]
    for n in stale:
        put(env["dest"], n)
    fresh = name(3)
    put(env["remote"], fresh)

    result = run(env)

    assert result.returncode == 0, result.stderr
    assert files(env["dest"]) == {fresh, "pull-beta-backups.log"}
    assert " removed=7 " in (env["dest"] / "pull-beta-backups.log").read_text()


def test_an_ok_run_is_recorded_in_the_beta_state_folder_for_its_alert(env) -> None:
    state = Path(env["env"]["HOME"]) / "routemaker-beta-state"
    n = name(5)
    put(env["remote"], n)

    # No state folder there: nothing is created, and the run is still ok.
    first = run(env)
    assert first.returncode == 0, first.stderr
    assert not state.exists()
    assert "marked=no" in (env["dest"] / "pull-beta-backups.log").read_text()

    state.mkdir()
    second = run(env)
    assert second.returncode == 0, second.stderr
    assert (state / "pc-backup-pull").read_text() == n + "\n"
    assert oct((state / "pc-backup-pull").stat().st_mode & 0o777) == "0o600"
    assert "marked=yes" in (env["dest"] / "pull-beta-backups.log").read_text().splitlines()[-1]


@pytest.mark.skipif(
    any(Path(d, "rsync").exists() for d in ("/usr/bin", "/bin")),
    reason="a real rsync on PATH would be found",
)
@pytest.mark.parametrize(("sudo", "via"), [("sudo -n", "ssh"), ("", "scp")])
def test_without_rsync_it_copies_by_ssh_or_scp(env, sudo: str, via: str) -> None:
    (env["bin"] / "rsync").unlink()
    n = name(4)
    put(env["remote"], n, size=3000)

    result = run(env, RM_BETA_SUDO=sudo)

    assert result.returncode == 0, result.stderr
    assert (env["dest"] / n).read_bytes() == (env["remote"] / n).read_bytes()
    assert "via=copy" in (env["dest"] / "pull-beta-backups.log").read_text()
    calls = env["log"].read_text()
    if via == "scp":
        assert "scp\t" in calls
    else:
        assert f"sudo -n cat -- '{env['remote']}/{n}'" in calls


def test_a_beta_whose_backups_stopped_is_reported(env) -> None:
    put(env["remote"], name(24 * 3))

    result = run(env)

    assert result.returncode == 1
    assert "nightly backup has stopped" in result.stderr
    assert len(files(env["dest"])) == 2  # the copy is still made, and the log


def test_the_nightly_task_runs_only_in_a_distro_that_is_already_running() -> None:
    """The distro that serves the home stack starts the stack when it boots, and the stack must not
    come up by itself, so the scheduled task never starts a distro: it asks which are running
    first, and the only `wsl.exe -d` comes after that check."""
    ps1 = (REPO / "scripts" / "pc" / "install-backup-pull-task.ps1").read_text()
    action = ps1[ps1.index("New-ScheduledTaskAction") :].split("\n", 2)[:2]
    assert "'powershell.exe'" in action[0] and "-EncodedCommand $encoded" in action[1]
    command = ps1[ps1.index('$command = @"') : ps1.index('"@')]
    check = command.index("wsl.exe -l --running")
    start = command.index("wsl.exe -d")
    assert check < start
    assert "-notcontains $(Quote $Distro)) { exit 3 }" in command[check:start]
    assert command.count("wsl.exe -d") == 1


def test_the_test_restore_runs_the_stacks_own_postgis_image_with_no_network() -> None:
    """The test-restore container receives a decrypted dump: it runs the exact image the stack
    runs (compose.yaml, by digest), and has no network."""
    compose = (REPO / "compose.yaml").read_text()
    image = re.search(r"image: (docker\.io/postgis/postgis:\S+@sha256:[0-9a-f]{64})", compose)
    assert image
    ops = (REPO / "docs" / "OPERATIONS.md").read_text()
    runs = [line for line in ops.splitlines() if "docker run" in line and "rm-restore-test" in line]
    assert len(runs) == 1, runs
    assert image.group(1) in runs[0]
    assert "--network none" in runs[0]
