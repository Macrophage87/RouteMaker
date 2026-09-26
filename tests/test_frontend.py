"""Run the frontend's own tests as part of the Python suite.

The stress overlay's rules - nothing encoded in colour alone, lightness ordered
so greyscale keeps the ordering, the basemap served from our own disk - are
assertions about data that happen to live in JavaScript. Running them here keeps
one suite and one CI signal rather than two that can drift.
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from django.conf import settings

REPO = Path(__file__).resolve().parents[1]
FRONTEND = REPO / "frontend"
NODE = shutil.which("node")

# The planner's pure logic is TypeScript run by Node's own type stripping,
# which is on by default from Node 22.18. The globs are package.json's.
TEST_GLOBS = ["src/**/*.test.mjs", "src/**/*.test.ts"]


def node_strips_types() -> bool:
    out = subprocess.run([NODE, "--version"], capture_output=True, text=True, check=False)
    major, minor = (int(part) for part in out.stdout.strip().lstrip("v").split(".")[:2])
    return (major, minor) >= (22, 18)


def test_frontend_suite_passes() -> None:
    if NODE is None:
        # A skip is the right answer on a machine without Node and the wrong one
        # in CI, where an image that lost the runtime would report green with the
        # whole JavaScript suite - the colour-ordering and contrast assertions
        # included - never having run.
        if os.environ.get("CI"):
            pytest.fail("CI image has no Node runtime; the frontend suite did not run")
        pytest.skip("no Node runtime available")
    if not node_strips_types():
        if os.environ.get("CI"):
            pytest.fail("CI image's Node cannot run the TypeScript tests (needs 22.18 or later)")
        pytest.skip("this Node predates default type stripping (22.18)")
    result = subprocess.run(
        [NODE, "--test", *TEST_GLOBS],
        cwd=FRONTEND,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "# fail 0" in result.stdout
    # A glob that matched only the old stress test would still say "fail 0".
    passed = int(re.search(r"# pass (\d+)", result.stdout).group(1))
    assert passed >= 50, result.stdout


def test_the_node_command_here_is_the_one_package_json_runs() -> None:
    """One list of test files, not two that drift."""
    import json

    script = json.loads((FRONTEND / "package.json").read_text())["scripts"]["test"]
    assert script == "node --test " + " ".join(f'"{glob}"' for glob in TEST_GLOBS)


def test_the_planners_coverage_box_is_the_settings_one() -> None:
    """The map refuses clicks outside this box and pads its bounds from it; a
    region change in settings that left it behind would refuse Baltimore."""
    source = (FRONTEND / "src" / "lib" / "geo.ts").read_text()
    found = re.search(r"COVERAGE_BBOX[^=]*=\s*(\[[^\]]*\])", source)
    assert found, "frontend/src/lib/geo.ts no longer declares COVERAGE_BBOX"
    assert tuple(ast.literal_eval(found.group(1))) == tuple(settings.COVERAGE_BBOX)


def test_the_page_sets_no_referrer_policy_of_its_own() -> None:
    """The base map is served only to requests whose Referer is a page on this
    site. A `<meta name="referrer">` in the page would override the edge's
    same-origin policy, and `no-referrer` there is a blank map."""
    page = (FRONTEND / "index.html").read_text().lower()
    assert 'name="referrer"' not in page and "referrerpolicy" not in page
