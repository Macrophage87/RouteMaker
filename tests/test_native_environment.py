"""The interpreter running the suite has the packages the images install.

`requirements-dev.txt` is loose on purpose and `docker/requirements.txt` is the
exact pin both images build from. A native venv made from the loose file alone
resolves whatever is newest: on a fresh Ubuntu 26.04 host that was Django 6.1,
under which a guild admin's write to another guild's row in the admin answered
302 instead of 403/404 - a failure of the code under a Django the stack does not
run, reported as a failure of the code. The suite is only evidence about the
images when it runs against their versions, so this file fails, naming each pin
the interpreter does not have, alongside whatever else fails because of it.
"""

from __future__ import annotations

import re
from importlib import metadata
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
IMAGE_PINS = REPO / "docker" / "requirements.txt"

# `name==version` or `name[extras]==version`, with an optional `; marker`.
PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*==\s*([^\s;,]+)\s*(?:;.*)?$")


def read_pins(text: str) -> tuple[dict[str, str], list[str]]:
    """The pins in a requirements file, and every line that is not one.

    A line the parser cannot read is returned rather than dropped, so a pin
    written in a form it does not know is a failure, not a pin nobody checks.
    """
    pins, unread = {}, []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        match = PIN.match(line)
        if match:
            pins[match.group(1)] = match.group(2)
        else:
            unread.append(raw)
    return pins, unread


def test_the_image_pins_are_read() -> None:
    """The check below is vacuous if the parser finds nothing, or skips a line."""
    pins, unread = read_pins(IMAGE_PINS.read_text())
    assert not unread, f"lines in {IMAGE_PINS.name} that are not name==version: {unread}"
    assert "Django" in pins, f"no Django pin found in {IMAGE_PINS.name}: {pins}"


def test_the_parser_reports_what_it_cannot_read() -> None:
    pins, unread = read_pins(
        "\n".join(
            [
                "a==1.0",
                "b[x,y]==2.0 ; python_version >= '3.11'  # comment",
                "c>=3.0",
                "-r other.txt",
                "d==4.0 junk",
                "e==5.0,<6",
                "# only a comment",
                "",
            ]
        )
    )
    assert pins == {"a": "1.0", "b": "2.0"}
    assert unread == ["c>=3.0", "-r other.txt", "d==4.0 junk", "e==5.0,<6"]


def test_the_suite_runs_on_the_versions_the_images_install() -> None:
    mismatched = {}
    pins, _ = read_pins(IMAGE_PINS.read_text())
    for name, pinned in pins.items():
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
