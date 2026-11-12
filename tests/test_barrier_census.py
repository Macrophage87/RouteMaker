"""The barrier coverage census (scripts/barrier_census.py, backlog 2026-11-12 item 12).

The width reader must read exactly what the remap's `M.parse_width_m` reads, so the census
counts what the build will see; the run over a small made-up extract checks the counts.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "barrier_census.py"
FIXTURE = REPO / "fixtures" / "barriers" / "tiny.osm"

spec = importlib.util.spec_from_file_location("barrier_census", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["barrier_census"] = mod
spec.loader.exec_module(mod)


@pytest.mark.parametrize(
    "value, metres",
    [
        ("1.2", 1.2),
        ("1,5", 1.5),
        ("1.2 m", 1.2),
        ("3'", 3 * 0.3048),
        ("3ft", 3 * 0.3048),
        ("5'6\"", 5.5 * 0.3048),
        ("1,5,2", None),
        ("narrow", None),
        (None, None),
    ],
)
def test_width_reads_as_the_remap_does(value, metres) -> None:
    got = mod.parse_width_m(value)
    assert got == pytest.approx(metres) if metres is not None else got is None


def test_the_remap_constants_match_the_lua() -> None:
    lua = (REPO / "lua" / "routemaker_remap.lua").read_text()
    assert "M.NARROW_GAP_M = 1.5" in lua
    assert "M.HARD_BARRIERS = { kissing_gate = true, stile = true, turnstile = true }" in lua
    assert mod.NARROW_GAP_M == 1.5
    assert mod.HARD_BARRIERS == {"kissing_gate", "stile", "turnstile"}


@pytest.mark.parametrize(
    "tags, kind",
    [
        ({"highway": "residential"}, "road"),
        ({"highway": "path"}, "trail"),
        ({"highway": "steps", "bicycle": "no"}, "steps"),
        ({"highway": "footway", "access": "private"}, None),
        ({"highway": "footway", "access": "private", "bicycle": "yes"}, "trail"),
        ({"highway": "cycleway", "bicycle": "no"}, None),
        ({"highway": "motorway"}, None),
        ({"highway": "pedestrian", "area": "yes"}, None),
        ({"building": "yes"}, None),
    ],
)
def test_way_class(tags, kind) -> None:
    assert mod.way_class(tags) == kind


@pytest.mark.parametrize(
    "tags, reading",
    [
        ({"barrier": "stile"}, "hard barrier, made a gate"),
        ({"barrier": "bollard"}, "bollard, width unmapped: free"),
        ({"barrier": "bollard", "maxwidth": "1.2"}, "bollard under 1.5 m, made a gate"),
        ({"barrier": "bollard", "maxwidth": "2"}, "bollard 1.5 m or wider: free"),
        ({"barrier": "cycle_barrier"}, "cycle barrier, made a gate"),
        ({"kerb": "raised"}, "kerb"),
    ],
)
def test_remap_reading(tags, reading) -> None:
    assert mod.remap_reading(tags) == reading


def test_census_over_a_made_up_extract() -> None:
    pytest.importorskip("osmium")
    census = mod.run(str(FIXTURE))
    rows = {r["osm_node_id"]: r for r in census.barrier_rows()}
    # The kissing gate is on a private footway only: off the network.
    assert set(rows) == {2, 3, 4, 5, 8}
    assert rows[3]["maxwidth_m"] == 1.2
    assert rows[5]["maxwidth_m"] is None and rows[5]["other_width_m"] == 0.9
    assert rows[8]["on"] == "road"
    # Trail way 100 ends at node 6 on the residential way: one access point, and node 5
    # next to it is a bollard, so it is flagged.
    assert census.access_points == {6}
    text = census.report()
    assert "| bollard | 3 |" in text
    assert "Trail ends that meet a road: 1." in text
    assert "1 ways" in text  # one flight of steps, one walk stretch
    assert "with `ramp:bicycle`: 1 (100.0%)" in text
