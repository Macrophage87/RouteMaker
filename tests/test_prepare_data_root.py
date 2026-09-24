"""`scripts/prepare_data_root.sh --env-file`, run rather than read.

The script takes one value out of compose's environment file without
evaluating it, and its parser has four rules: the last uncommented assignment
wins, a commented one is not an assignment, a trailing CR from a file edited on
Windows is not part of the value, and a matching pair of quotes is compose's
syntax rather than part of the path. Only the refusal to source the file was
pinned, by reading the script's text. Each rule here gets an env file that
breaks exactly that rule and no other, and the answer is read off the
filesystem: where the directories were made.

`chown` is stood in for on PATH, because the script hands the directories to
uid 10001 and this runs unprivileged; the stand-in records what it was asked to
chown, which is the other half of where the script thinks DATA_ROOT is.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PREPARE = REPO / "scripts" / "prepare_data_root.sh"


def prepare(tmp_path: Path, env_text: str) -> tuple[subprocess.CompletedProcess, list[str]]:
    """Run the script against an env file holding `env_text`, exactly as bytes."""
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir(exist_ok=True)
    log = tmp_path / "chowned"
    chown = stub_dir / "chown"
    chown.write_text(f'#!/bin/sh\nprintf "%s\\n" "$3" >> {log}\n')
    chown.chmod(0o755)
    env_file = tmp_path / "env"
    env_file.write_bytes(env_text.encode())
    result = subprocess.run(
        ["sh", str(PREPARE), "--env-file", str(env_file)],
        capture_output=True,
        text=True,
        env={
            key: value
            for key, value in {**os.environ, "PATH": f"{stub_dir}:{os.environ['PATH']}"}.items()
            if key != "DATA_ROOT"
        },
    )
    chowned = log.read_text().splitlines() if log.exists() else []
    return result, chowned


def assert_prepared_under(root: Path, result, chowned) -> None:
    assert result.returncode == 0, result.stderr
    assert (root / "tiles" / "standard" / "current").is_dir(), (
        f"nothing was made under {root}: {result.stdout} {result.stderr}"
    )
    assert chowned, "the script chowned nothing"
    assert all(Path(path).parent == root for path in chowned), chowned


def test_the_last_uncommented_assignment_wins(tmp_path) -> None:
    """Compose's own reader takes the last one, so an operator who appended a
    corrected line below the example's gets the corrected one from both."""
    first, last = tmp_path / "first", tmp_path / "last"
    result, chowned = prepare(tmp_path, f"DATA_ROOT={first}\nPGUSER=x\nDATA_ROOT={last}\n")
    assert_prepared_under(last, result, chowned)
    assert not first.exists(), "the earlier assignment was used"


def test_a_commented_assignment_is_not_one(tmp_path) -> None:
    """`.env.example` carries commented alternatives, and the local block is
    exactly that: a `# DATA_ROOT=` after the live line must not win."""
    live, commented = tmp_path / "live", tmp_path / "commented"
    result, chowned = prepare(tmp_path, f"DATA_ROOT={live}\n# DATA_ROOT={commented}\n")
    assert_prepared_under(live, result, chowned)
    assert not commented.exists()


def test_a_trailing_carriage_return_is_not_part_of_the_path(tmp_path) -> None:
    """A file saved on Windows ends every line in CR LF. Kept, the CR makes a
    sibling directory whose name ends in an invisible character, and the stack
    binds the real path, which nothing prepared."""
    root = tmp_path / "root"
    result, chowned = prepare(tmp_path, f"DATA_ROOT={root}\r\n")
    assert_prepared_under(root, result, chowned)
    assert not (tmp_path / "root\r").exists()


@pytest.mark.parametrize("quote", ['"', "'"])
def test_a_matching_pair_of_quotes_is_the_parsers_not_the_paths(tmp_path, quote) -> None:
    """Compose's dotenv reader removes them, so they are not in the value
    compose binds; kept here, the path would be relative (it would begin with a
    quote) and the absolute-path check refuses it."""
    root = tmp_path / "root"
    result, chowned = prepare(tmp_path, f"DATA_ROOT={quote}{root}{quote}\n")
    assert_prepared_under(root, result, chowned)


def test_the_value_is_not_evaluated(tmp_path) -> None:
    """The reason the option exists: `$` in the file is compose's string and
    never the shell's. A value naming `$HOME` is a directory called `$HOME`."""
    root = tmp_path / "$HOME"
    result, chowned = prepare(tmp_path, f"DATA_ROOT={root}\n")
    assert_prepared_under(root, result, chowned)
