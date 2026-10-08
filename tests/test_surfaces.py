"""Which surfaces are paved (OWNER-DECISIONS 440; `routemaker.surfaces`).

Hard surfaces count as paved: wood boardwalks and trail bridges, metal decks,
brick, sett, tartan, rubber and the `concrete:*` / `paving_stones:*` variants;
cobblestone is paved but rough. Access does not widen: a rated wooden MTB
feature stays singletrack, and a wooden footbridge on a hiking path keeps its
no-bike-path closure.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from routemaker import singletrack, surfaces, trailaccess
from routemaker.stress import classify, inferred_unpaved, is_rough, is_unpaved

REPO = Path(__file__).resolve().parents[1]

HARD = [
    "asphalt",
    "concrete",
    "paved",
    "paving_stones",
    "chipseal",
    "wood",
    "boardwalk",
    "metal",
    "metal_grid",
    "brick",
    "bricks",
    "sett",
    "tartan",
    "rubber",
    "cobblestone",
    "unhewn_cobblestone",
    "concrete:plates",
    "concrete:lanes",
    "paving_stones:lanes",
    "asphalt:lanes",
]
NOT_HARD = [
    "unpaved",
    "gravel",
    "fine_gravel",
    "compacted",
    "dirt",
    "ground",
    "grass",
    "woodchips",
    "grass_paver",
    "pebblestone",
    "asphalt;unpaved",
]


@pytest.mark.parametrize("surface", HARD)
def test_every_hard_surface_is_paved(surface) -> None:
    assert surfaces.is_paved({"surface": surface})
    assert is_unpaved({"surface": surface}) is False
    assert inferred_unpaved({"highway": "footway", "surface": surface}) is False


@pytest.mark.parametrize("surface", NOT_HARD)
def test_loose_and_natural_surfaces_stay_unpaved(surface) -> None:
    assert not surfaces.is_paved({"surface": surface})
    assert is_unpaved({"surface": surface}) is True


def test_no_surface_stays_unknown() -> None:
    assert is_unpaved({}) is None
    assert not surfaces.is_paved({})


@pytest.mark.parametrize("surface", ["cobblestone", "unhewn_cobblestone"])
def test_cobblestone_is_paved_but_rough(surface) -> None:
    tags = {"highway": "residential", "surface": surface}
    assert is_unpaved(tags) is False
    assert is_rough(tags)
    # Rough floors a road at LTS 2, as it does for dirt.
    assert int(classify({**tags, "maxspeed": "20 mph"}, jurisdiction="DC").tier) == 2


@pytest.mark.parametrize("surface", ["wood", "brick", "bricks", "sett", "metal", "concrete:plates"])
def test_the_other_hard_surfaces_are_not_rough(surface) -> None:
    assert not is_rough({"highway": "residential", "surface": surface})


# The ways the owner named (2026-10-06), as the 2026-10-03 extract tags them.
RIVERWALK = {
    "highway": "footway",
    "surface": "wood",
    "bicycle": "designated",
    "name": "Anacostia Riverwalk Trail",
}
HENSON_BRIDGE = {
    "highway": "cycleway",
    "surface": "wood",
    "bridge": "yes",
    "name": "Matthew Henson Trail",
}
UNPAVED_PATH = {"highway": "path", "surface": "unpaved"}  # w1088041985


def test_the_riverwalk_and_matthew_henson_decks_are_paved() -> None:
    assert inferred_unpaved(RIVERWALK) is False
    assert inferred_unpaved(HENSON_BRIDGE) is False
    assert inferred_unpaved(UNPAVED_PATH) is True


def _lua_table(name: str) -> str:
    source = (REPO / "lua" / "routemaker_remap.lua").read_text()
    body = re.search(rf"^M\.{name}\s*=\s*\{{(.*?)\}}", source, re.MULTILINE | re.DOTALL)
    assert body, f"the remap no longer declares M.{name}"
    return body.group(1)


def test_the_lua_paved_set_is_the_python_one() -> None:
    """Python and the graph's remap cannot share a constant: the parity test."""
    lua = set(re.findall(r"([A-Za-z_]+)\s*=\s*true", _lua_table("PAVED_SURFACES")))
    assert lua == set(surfaces.PAVED_SURFACES)
    prefixes = tuple(re.findall(r'"([^"]+)"', _lua_table("PAVED_PREFIXES")))
    assert prefixes == surfaces.SEALED_PREFIXES


def test_the_lua_graph_surfaces_are_paved_ones() -> None:
    """Only a paved surface is handed to the graph as paving stones."""
    mapped = dict(re.findall(r'([A-Za-z_]+)\s*=\s*"([^"]+)"', _lua_table("GRAPH_SURFACE")))
    assert set(mapped) == {"wood", "boardwalk", "brick", "bricks"}
    assert all(surfaces.is_paved_surface(key) for key in mapped)
    assert set(mapped.values()) == {"paving_stones"}


# Access: nothing widens.


@pytest.mark.parametrize(
    "tags",
    [
        # The Boss Trail's "Rollercoaster Wooden Feature" (way 808882074).
        {
            "highway": "cycleway",
            "surface": "wood",
            "bridge": "yes",
            "bicycle": "yes",
            "mtb:scale": "3",
            "mtb:scale:imba": "3",
        },
        # A North Holly Loop Jump Line ramp (way 1359123039).
        {
            "highway": "path",
            "surface": "wood",
            "bridge": "yes",
            "bicycle": "designated",
            "mtb:scale": "3",
            "mtb:scale:imba": "3",
        },
        # A Split Decision Roller boardwalk (way 1157936969).
        {
            "highway": "path",
            "surface": "wood",
            "bridge": "boardwalk",
            "bicycle": "designated",
            "mtb:scale:imba": "1",
        },
        {"highway": "path", "surface": "metal", "mtb:scale": "2"},
        {"highway": "path", "surface": "brick", "mtb:scale": "1"},
        # Cobblestone is paved but rough (440): a rated rock garden stays singletrack.
        {"highway": "path", "surface": "cobblestone", "mtb:scale": "1"},
        {"highway": "path", "surface": "unhewn_cobblestone", "mtb:scale": "2"},
    ],
)
def test_a_rated_hard_mtb_feature_stays_singletrack(tags) -> None:
    assert surfaces.is_paved(tags)
    assert not surfaces.is_sealed(tags)
    assert singletrack.is_singletrack(tags)


def test_a_wooden_bridge_on_a_paved_trail_is_not_singletrack() -> None:
    """A Rock Creek Trail bridge (way 156659889): rated 0, open, and paved."""
    tags = {
        "highway": "cycleway",
        "surface": "wood",
        "bridge": "yes",
        "bicycle": "designated",
        "mtb:scale": "0",
    }
    assert not singletrack.is_singletrack(tags)
    assert inferred_unpaved(tags) is False


def test_a_wooden_footbridge_on_a_hiking_path_keeps_its_closure() -> None:
    """Wood is paved for the map, but not a hard-surface exemption off a bike path."""
    footbridge = {"highway": "path", "surface": "wood", "bridge": "yes", "foot": "designated"}
    assert trailaccess.verdict(footbridge) == trailaccess.FOOT_DESIGNATED
    hiking = trailaccess.WayRoutes(hiking=True)
    plain = {"highway": "path", "surface": "wood", "bridge": "yes"}
    assert trailaccess.verdict(plain, hiking) == trailaccess.HIKING_ROUTE
    assert trailaccess.verdict({**plain, "sac_scale": "hiking"}) == trailaccess.SAC_SCALE
    # The other hard surfaces were exempt before 440 and still are.
    assert trailaccess.verdict({**footbridge, "surface": "metal"}) is None


def test_a_wooden_bridge_on_a_bike_path_counts_hard_for_access() -> None:
    designated = {
        "highway": "path",
        "surface": "wood",
        "bridge": "yes",
        "bicycle": "designated",
        "smoothness": "bad",
    }
    assert surfaces.is_hard_for_access(designated)
    assert not trailaccess.is_mtb_class(designated)
    # The same deck off a bridge, or on a path not signed for bikes, does not.
    assert not surfaces.is_hard_for_access({k: v for k, v in designated.items() if k != "bridge"})
    assert not surfaces.is_hard_for_access({**designated, "bicycle": "yes"})


@pytest.mark.parametrize(
    "tags",
    [
        # A cycleway's wooden bridge, with no bicycle tag: the class makes it a bike path.
        {"highway": "cycleway", "surface": "wood", "bridge": "yes"},
        # A boardwalk deck, mapped with `boardwalk=yes` and no bridge tag.
        {"highway": "path", "surface": "wood", "boardwalk": "yes", "bicycle": "designated"},
        # A boardwalk mapped as `bridge=boardwalk`, and a viaduct.
        {"highway": "path", "surface": "wood", "bridge": "boardwalk", "bicycle": "designated"},
        {"highway": "cycleway", "surface": "wood", "bridge": "viaduct"},
    ],
)
def test_every_bike_paths_wooden_deck_counts_hard_for_access(tags) -> None:
    assert surfaces.is_bridge_or_boardwalk(tags)
    assert surfaces.is_bike_bridge(tags)
    assert surfaces.is_hard_for_access(tags)


@pytest.mark.parametrize(
    "tags",
    [
        {"highway": "path", "surface": "wood", "bridge": "no", "bicycle": "designated"},
        {"highway": "path", "surface": "wood", "boardwalk": "no", "bicycle": "designated"},
        {"highway": "footway", "surface": "wood", "bridge": "yes"},
    ],
)
def test_a_wooden_deck_that_is_no_bike_bridge_does_not(tags) -> None:
    assert not surfaces.is_hard_for_access(tags)


def test_singletrack_reads_only_road_paving() -> None:
    assert singletrack.PAVED_SURFACES == surfaces.SEALED_SURFACES
    assert not (surfaces.SEALED_SURFACES & {"wood", "metal", "brick", "sett", "cobblestone"})
