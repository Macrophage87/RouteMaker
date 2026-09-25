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


def prepare_with(tmp_path: Path, arguments: list[str], data_root: str | None):
    """Run the script with DATA_ROOT set to `data_root` (or unset) in the
    environment and `arguments` on the command line, from inside `tmp_path`, so
    a relative path would land somewhere this test can see."""
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir(exist_ok=True)
    log = tmp_path / "chowned"
    chown = stub_dir / "chown"
    chown.write_text(f'#!/bin/sh\nprintf "%s\n" "$3" >> {log}\n')
    chown.chmod(0o755)
    environment = {
        key: value
        for key, value in {**os.environ, "PATH": f"{stub_dir}:{os.environ['PATH']}"}.items()
        if key != "DATA_ROOT"
    }
    if data_root is not None:
        environment["DATA_ROOT"] = data_root
    work = tmp_path / "cwd"
    work.mkdir(exist_ok=True)
    result = subprocess.run(
        ["sh", str(PREPARE), *arguments],
        capture_output=True,
        text=True,
        cwd=work,
        env=environment,
    )
    chowned = log.read_text().splitlines() if log.exists() else []
    return result, chowned, work


@pytest.mark.parametrize(
    "data_root",
    [None, "", "relative/data", "./data", "~/data"],
    ids=["unset", "empty", "relative", "dot-relative", "tilde"],
)
def test_it_refuses_a_data_root_that_is_not_an_absolute_path(tmp_path, data_root) -> None:
    """The script ends in a `chown -R` per directory it owns. With DATA_ROOT
    unset or empty each argument is rooted at `/`, and relative it is the
    working directory's; so anything but an absolute path is refused before a
    directory is made or an owner changed. Each case is one bad value and no
    env file, run from an empty directory, and the answer is read off that
    directory and the chown stand-in. This used to be a grep of the script for
    `${DATA_ROOT:?` and the wording of its error."""
    result, chowned, work = prepare_with(tmp_path, [], data_root)
    assert result.returncode != 0, (
        f"the script accepted DATA_ROOT={data_root!r}: {result.stdout} {result.stderr}"
    )
    assert not chowned, f"the script chowned {chowned} under DATA_ROOT={data_root!r}"
    assert not list(work.iterdir()), (
        f"the script made {sorted(p.name for p in work.iterdir())} in its working "
        f"directory under DATA_ROOT={data_root!r}"
    )


def test_the_same_run_with_an_absolute_data_root_is_accepted(tmp_path) -> None:
    """The control for the refusals above: the one thing they vary is the
    value, and an absolute one prepares the tree."""
    root = tmp_path / "root"
    result, chowned, _work = prepare_with(tmp_path, [], str(root))
    assert_prepared_under(root, result, chowned)


def test_the_other_values_in_the_file_are_not_run(tmp_path) -> None:
    """A password beside `DATA_ROOT=` is a string to compose, whatever is in it,
    and a script that sourced the file would run it. The file carries a
    command substitution and a backtick that would each create a marker; the
    run has to prepare the tree and leave both markers absent."""
    root = tmp_path / "root"
    substituted, backticked = tmp_path / "substituted", tmp_path / "backticked"
    result, chowned = prepare(
        tmp_path,
        f"PGPASSWORD=$(touch {substituted})\n"
        f"DJANGO_SECRET_KEY=`touch {backticked}`\n"
        f"DATA_ROOT={root}\n",
    )
    assert_prepared_under(root, result, chowned)
    assert not substituted.exists() and not backticked.exists(), (
        "reading DATA_ROOT out of the env file ran a command written in another value"
    )
