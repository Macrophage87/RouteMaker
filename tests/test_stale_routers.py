"""`check_operations` flags a router still on an older build after a swap (review 2026-10-29).

valhalla_service does not reload tiles, so after a swap the routers serve the
previous build until something restarts them. These drive the comparison with
fake rows and a fake `/status`, so no database or router is needed.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from core.management.commands.check_operations import ROUTER_RESTART_GRACE, stale_routers

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
PROMOTED_AT = 1_761_000_000


def deployment(tmp_path, variant: str = "standard"):
    build = tmp_path / variant / "20261027T080000Z"
    build.mkdir(parents=True)
    (build / "tiles.tar").write_bytes(b"")
    os.utime(build / "tiles.tar", (PROMOTED_AT, PROMOTED_AT))
    os.symlink("20261027T080000Z", tmp_path / variant / "current")
    return tmp_path


def row(variant: str = "standard", age: timedelta = timedelta(hours=2)):
    return SimpleNamespace(
        variant=variant,
        url=f"http://valhalla-{variant}:8002",
        build_id="20261027T080000Z",
        updated_at=NOW - age,
    )


def test_a_router_that_loaded_the_promoted_tiles_is_fine(tmp_path) -> None:
    tiles = deployment(tmp_path)
    assert stale_routers([row()], tiles, NOW, status=lambda url: PROMOTED_AT) == []


def test_a_router_still_on_the_old_tiles_is_reported(tmp_path) -> None:
    tiles = deployment(tmp_path)
    lines = stale_routers([row()], tiles, NOW, status=lambda url: PROMOTED_AT - 7 * 86400)
    assert len(lines) == 1
    assert "standard is not serving build 20261027T080000Z" in lines[0]
    assert "restart" in lines[0]


def test_inside_the_grace_after_a_swap_nothing_is_said(tmp_path) -> None:
    tiles = deployment(tmp_path)
    recent = row(age=ROUTER_RESTART_GRACE - timedelta(minutes=1))
    assert stale_routers([recent], tiles, NOW, status=lambda url: 1) == []


def test_a_router_that_does_not_answer_is_left_to_the_other_checks(tmp_path) -> None:
    tiles = deployment(tmp_path)
    assert stale_routers([row()], tiles, NOW, status=lambda url: None) == []


def test_tiles_this_container_cannot_see_are_skipped(tmp_path) -> None:
    asked = []
    lines = stale_routers([row("weekend")], tmp_path, NOW, status=asked.append)
    assert lines == [] and asked == [], "it asked a router it had nothing to compare with"
