"""scripts/beta/backup-pull-gate.sh: the forced command that limits the PC's backup-pull key to
the pull's own commands (docs/OPERATIONS.md, "A key that can only pull backups").

The real pull script runs against the gate through a stub ssh that does what sshd does with a
forced command: the asked-for command goes into SSH_ORIGINAL_COMMAND and the gate runs instead.
Nothing here touches a server or the network.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GATE = REPO / "scripts" / "beta" / "backup-pull-gate.sh"
PULL = REPO / "scripts" / "pc" / "pull-beta-backups.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")

STUB_SSH = r"""#!/usr/bin/env bash
while [ $# -gt 0 ]; do
	case "$1" in -o) shift 2 ;; -*) shift ;; *) break ;; esac
done
shift
SSH_ORIGINAL_COMMAND="$*" exec bash "$GATE_COPY"
"""

STUB_SUDO = r"""#!/usr/bin/env bash
[ "$1" = -n ] && shift
exec "$@"
"""


def dump_name(hours_ago: float) -> str:
    t = datetime.now(UTC) - timedelta(hours=hours_ago)
    return f"routemaker-{t:%Y%m%dT%H%M%SZ}.dump.age"


@pytest.fixture()
def beta(tmp_path: Path):
    backups = tmp_path / "data" / "backups"
    backups.mkdir(parents=True)
    home = tmp_path / "home"
    (home / "routemaker-beta-state").mkdir(parents=True)
    gate = tmp_path / "gate.sh"
    gate.write_text(
        GATE.read_text().replace("BACKUPS=/data/routemaker/backups", f"BACKUPS={backups}", 1)
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for stub, text in {"ssh": STUB_SSH, "sudo": STUB_SUDO}.items():
        (bin_dir / stub).write_text(text)
        (bin_dir / stub).chmod(0o755)
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(home),
        "GATE_COPY": str(gate),
    }
    return {"backups": backups, "home": home, "gate": gate, "env": env, "tmp": tmp_path}


def ask(beta: dict, command: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(beta["gate"])],
        env={**beta["env"], "SSH_ORIGINAL_COMMAND": command},
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_the_real_pull_works_through_the_gate_and_copies_whole_dumps(beta) -> None:
    names = [dump_name(2), dump_name(26)]
    for n in names:
        (beta["backups"] / n).write_bytes(os.urandom(3000))
    dest = beta["tmp"] / "pc-copies"
    run = subprocess.run(
        ["bash", str(PULL)],
        env={
            **beta["env"],
            "RM_BETA_SSH": "beta-backup",
            "RM_BACKUP_DIR": str(dest),
            "RM_BETA_BACKUPS": str(beta["backups"]),
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    for n in names:
        assert (dest / n).read_bytes() == (beta["backups"] / n).read_bytes()
    last = (dest / "pull-beta-backups.log").read_text().splitlines()[-1]
    assert "via=copy" in last and "marked=yes" in last
    marker = beta["home"] / "routemaker-beta-state" / "pc-backup-pull"
    assert marker.read_text() == f"{names[0]}\n"


@pytest.mark.parametrize(
    "command",
    [
        "",
        "id",
        "bash -i",
        "sudo -n cat -- '/etc/shadow'",
        "sudo -n cat -- '{b}/../../etc/routemaker-20260101T000000Z.dump.age'",
        "sudo -n cat -- '{b}/routemaker-20260101T000000Z.dump.age'; id",
        "sudo -n cat -- '{b}/routemaker-20260101T000000Z.dump.age' '/etc/shadow'",
        "sudo -n find '/' -maxdepth 1 -type f -printf '%f %s\\n'",
        "rsync --server --sender -t . {b}/routemaker-20260101T000000Z.dump.age",
        "cd && [ -d 'routemaker-beta-state' ] && umask 077 && printf '%s\\n' "
        "'routemaker-20260101T000000Z.dump.age' >'.ssh/authorized_keys'",
    ],
)
def test_anything_but_the_pulls_own_commands_is_refused(beta, command: str) -> None:
    out = ask(beta, command.replace("{b}", str(beta["backups"])))
    assert out.returncode == 126
    assert out.stdout == ""
    assert "refused" in out.stderr


def test_it_never_offers_rsync(beta) -> None:
    listing = (
        "if command -v rsync >/dev/null 2>&1; then echo rsync=1; else echo rsync=0; fi; "
        f"sudo -n find '{beta['backups']}' -maxdepth 1 -type f -name 'routemaker-*.dump.age' "
        "-printf '%f %s\\n'"
    )
    out = ask(beta, listing)
    assert out.returncode == 0 and out.stdout.splitlines()[0] == "rsync=0"


def test_install_adds_the_key_once_as_a_forced_command(beta) -> None:
    key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyBlob0123456789abcdefABCDEF rm-backup-pull"
    for _ in range(2):
        out = subprocess.run(
            ["bash", str(GATE), "--install"],
            input=key + "\n",
            env=beta["env"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert out.returncode == 0, out.stderr
    gate = beta["home"] / "bin" / "backup-pull-gate"
    lines = (beta["home"] / ".ssh" / "authorized_keys").read_text().splitlines()
    assert lines == [f'restrict,command="{gate}" {key}']
    assert os.access(gate, os.X_OK)
    assert gate.read_text() == GATE.read_text()


def test_install_refuses_anything_but_one_public_key(beta) -> None:
    bad = 'ssh-ed25519 AAAA rm" ,command="bash'
    out = subprocess.run(
        ["bash", str(GATE), "--install"],
        input=bad + "\n",
        env=beta["env"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert out.returncode == 1
    assert not (beta["home"] / ".ssh" / "authorized_keys").exists()
