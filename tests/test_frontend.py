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


def test_the_built_licence_notices_leave_no_package_without_text() -> None:
    """BSD-3-Clause's second clause asks for the notice to travel with a
    minified copy, and two of the bundled packages ship no LICENSE file
    (frontend/src/licences/notices.mjs fills them). CI builds the front end
    before pytest, so there this reads what would be published."""
    notices = FRONTEND / "dist" / "licenses.txt"
    if not notices.exists():
        if os.environ.get("CI"):
            pytest.fail("CI built the front end but dist/licenses.txt is missing")
        pytest.skip("front end not built here")
    lines = notices.read_text().splitlines()
    heading = re.compile(r"^## (\S+) - \S+ \(.+\)$")
    names = [m.group(1) for line in lines if (m := heading.match(line))]
    assert {"pmtiles", "@protomaps/basemaps", "maplibre-gl", "@maplibre/mlt"} <= set(names), names
    empty = []
    for i, line in enumerate(lines):
        if heading.match(line):
            rest = [text for text in lines[i + 1 :] if text.strip()]
            if not rest or heading.match(rest[0]):
                empty.append(line)
    assert not empty, empty


def caddyfile_csp() -> dict[str, list[str]]:
    """The app's Content-Security-Policy as the Caddyfile sets it, by directive."""
    text = (REPO / "Caddyfile").read_text()
    found = re.findall(r'^\s*header\s+Content-Security-Policy\s+"([^"]*)"', text, re.M)
    assert len(found) == 1, found
    return {part.split()[0]: part.split()[1:] for part in found[0].split(";") if part.strip()}


def test_the_apps_content_security_policy_is_asserted_where_ci_runs() -> None:
    """PLAN.md:246: default-src 'self', asserted in CI. The Caddy-run edge
    test reads the header off a live response but skips where the image is
    absent, which is CI; this reads the one line that sets it."""
    policy = caddyfile_csp()
    assert policy.get("default-src") == ["'self'"], policy
    assert policy.get("frame-ancestors") == ["'none'"], policy
    assert policy.get("object-src") == ["'none'"], policy
    for directive in ("script-src", "connect-src"):
        assert policy.get(directive) == ["'self'"], policy


def test_no_directive_lets_in_a_wildcard_or_another_host() -> None:
    """Every request the app makes is to this site (PLAN.md:15), so no source
    list names a host, a scheme that reaches one, or `*`. `data:` and `blob:`
    are local; `'unsafe-inline'` is for MapLibre's inline styles only."""
    allowed = {"'self'", "'none'", "data:", "blob:"}
    for directive, sources in caddyfile_csp().items():
        inline = {"'unsafe-inline'"} if directive == "style-src" else set()
        extra = set(sources) - allowed - inline
        assert not extra, f"{directive} allows {sorted(extra)}"


def test_ci_typechecks_tests_and_builds_the_front_end_before_pytest() -> None:
    """The front-end step in CI, read from ci.yml: removing it, or its
    typecheck or build, would leave the bundle unchecked with CI green."""
    import yaml

    steps = yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml").read_text())["jobs"]["test"][
        "steps"
    ]
    front = [i for i, s in enumerate(steps) if s.get("working-directory") == "frontend"]
    assert len(front) == 1, steps
    commands = [part.strip() for part in steps[front[0]]["run"].split("&&")]
    assert commands == ["npm ci", "npm run typecheck", "npm test", "npm run build"], commands
    pytest_at = [i for i, s in enumerate(steps) if str(s.get("run", "")).startswith("pytest")]
    assert pytest_at and front[0] < pytest_at[0], "the front end is built after pytest reads it"
    node = [s for s in steps if str(s.get("uses", "")).startswith("actions/setup-node")]
    assert node and str(node[0]["with"]["node-version"]).split(".")[0] == "22", node
