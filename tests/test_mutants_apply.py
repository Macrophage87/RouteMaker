"""Every mutation script's mutants still apply to the code (`--check`).

Each `scripts/mutants_*.py` pass is run by hand, and between passes a refactor can rewrite
the line a mutant targets, so that mutant stops testing anything. `--check` is a text
match (each mutant's old text occurs exactly once in its file, no tests run); here it
fails in the change that made a mutant stale, which then re-anchors or drops it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = sorted((REPO / "scripts").glob("mutants_*.py"))


def test_there_are_mutation_scripts() -> None:
    assert len(SCRIPTS) >= 13, SCRIPTS


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.stem)
def test_every_mutant_applies(script: Path) -> None:
    # The a11y pass takes the front end's node_modules first; --check never reads it.
    extra = [str(REPO / "frontend" / "node_modules")] if script.stem == "mutants_a11y" else []
    result = subprocess.run(
        [sys.executable, str(script), *extra, "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
