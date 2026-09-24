"""The interpreter running the suite has the packages the images install.

`requirements-dev.txt` is loose on purpose and `docker/requirements.txt` is the
exact pin both images build from. A native venv made from the loose file alone
resolves whatever is newest: on a fresh Ubuntu 26.04 host that was Django 6.1,
under which a guild admin's write to another guild's row in the admin answered
302 instead of 403/404 - a failure of the code under a Django the stack does not
run, reported as a failure of the code. The suite is only evidence about the
images when it runs against their versions, so it says so before anything else
does.
"""

from __future__ import annotations

import re
from importlib import metadata
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
IMAGE_PINS = REPO / "docker" / "requirements.txt"

# `name==version`, ignoring comments, markers and `-r` includes.
PIN = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*([^\s;#]+)")


def image_pins() -> dict[str, str]:
    pins = {}
    for line in IMAGE_PINS.read_text().splitlines():
        match = PIN.match(line)
        if match:
            pins[match.group(1)] = match.group(2)
    return pins


def test_the_image_pins_are_read() -> None:
    """The check below is vacuous if the parser finds nothing to check."""
    pins = image_pins()
    assert "Django" in pins, f"no Django pin found in {IMAGE_PINS.name}: {pins}"


def test_the_suite_runs_on_the_versions_the_images_install() -> None:
    mismatched = {}
    for name, pinned in image_pins().items():
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError:
            installed = None
        if installed != pinned:
            mismatched[name] = (pinned, installed)
    assert not mismatched, (
        "this interpreter is not the images' package set "
        f"(name: (docker/requirements.txt, installed)): {mismatched}; "
        "install with -r docker/requirements.txt -r requirements-dev.txt "
        "(docs/DEVELOPMENT.md, 'The native loop')"
    )
