"""scripts/pc/pull-beta-backups.sh: the PC's nightly copy of the beta's encrypted dumps
(docs/OPERATIONS.md, "Off-box copies of beta backups").

Run with stub ssh, rsync, scp and sudo on PATH: the stub ssh runs the "remote" command locally
against a temporary folder standing in for the beta's backups folder, so nothing here touches a
server or the network.
"""

from __future__ import annotations

import os
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


def name(hours_ago: float) -> str:
    t = datetime.now(UTC) - timedelta(hours=hours_ago)
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
            "RM_BETA_SSH": "chubby",
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
    assert len(log) == 1 and " ok host=chubby copied=3 " in log[0] and "via=rsync" in log[0]
    # On the beta: one listing, then rsync copies; nothing else.
    calls = env["log"].read_text().splitlines()
    remote_cmds = [line for line in calls if line.startswith("chubby\t")]
    assert len(remote_cmds) == 1 and "find " in remote_cmds[0] and "rm " not in remote_cmds[0]

    again = run(env)
    assert again.returncode == 0, again.stderr
    assert " copied=0 " in (env["dest"] / "pull-beta-backups.log").read_text().splitlines()[-1]


def test_retention_keeps_the_newest_14_and_touches_nothing_else(env) -> None:
    for h in range(20, 20 + 24 * 16, 24):  # 16 older copies already here
        put(env["dest"], name(h))
    put(env["dest"], "notes.txt")
    new = [name(2), name(3)]
    for n in new:
        put(env["remote"], n)
    put(env["remote"], name(24 * 30))  # older than every kept copy: not pulled back

    result = run(env)

    assert result.returncode == 0, result.stderr
    dumps = sorted(n for n in files(env["dest"]) if n.endswith(".dump.age"))
    every = sorted([*new, *(name(h) for h in range(20, 20 + 24 * 16, 24))], reverse=True)
    assert dumps == sorted(every[:14])
    assert "notes.txt" in files(env["dest"])
    assert not any(n.endswith(".part") for n in files(env["dest"]))


def test_a_copy_that_breaks_off_leaves_no_part_and_deletes_nothing(env) -> None:
    old = [name(h) for h in range(30, 30 + 24 * 15, 24)]  # 15: one over the keep
    for n in old:
        put(env["dest"], n)
    put(env["remote"], name(2), size=4000)

    result = run(env, STUB_TRUNCATE="1")

    assert result.returncode == 1
    assert "did not copy whole" in result.stderr
    assert files(env["dest"]) == set(old) | {"pull-beta-backups.log"}
    assert "FAILED" in (env["dest"] / "pull-beta-backups.log").read_text()


def test_a_failing_ssh_exits_non_zero_and_leaves_the_copies_alone(env) -> None:
    old = [name(h) for h in range(30, 30 + 24 * 16, 24)]
    for n in old:
        put(env["dest"], n)
    before = {n: (env["dest"] / n).read_bytes() for n in old}
    put(env["remote"], name(2))

    result = run(env, STUB_SSH_FAIL="1")

    assert result.returncode != 0
    assert "ssh chubby did not connect" in result.stderr
    assert {n: (env["dest"] / n).read_bytes() for n in old} == before
    assert files(env["dest"]) == set(old) | {"pull-beta-backups.log"}
    log = (env["dest"] / "pull-beta-backups.log").read_text()
    assert "FAILED ssh chubby did not connect" in log


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
