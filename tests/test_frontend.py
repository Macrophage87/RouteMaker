"""Run the frontend's own tests as part of the Python suite.

The stress overlay's rules - nothing encoded in colour alone, lightness ordered
so greyscale keeps the ordering, the basemap served from our own disk - are
assertions about data that happen to live in JavaScript. Running them here keeps
one suite and one CI signal rather than two that can drift.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def test_frontend_suite_passes() -> None:
    if NODE is None:
        # A skip is the right answer on a machine without Node and the wrong one
        # in CI, where an image that lost the runtime would report green with the
        # whole JavaScript suite - the colour-ordering and contrast assertions
        # included - never having run.
        if os.environ.get("CI"):
            pytest.fail("CI image has no Node runtime; the frontend suite did not run")
        pytest.skip("no Node runtime available")
    result = subprocess.run(
        [NODE, "--test", "frontend/src/stressStyle.test.mjs"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "# fail 0" in result.stdout
