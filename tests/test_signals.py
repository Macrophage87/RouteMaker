"""Which nodes the rebuild marks as signalised trail crossings (FOLLOWUP-SIGNAL-DERIVE).

`pipeline.signals` finds the nodes where a crossing way tagged as signalised
meets a road, so the transform can make them signals; the node's own tags are
read by the transform itself (tests/lua/test_remap.lua) and the whole path is
checked in real tiles by tests/test_tile_build_signals.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline import signals
from pipeline.extract import Way

ROAD = {"highway": "secondary"}
SIGNALISED_CROSSING = {"highway": "footway", "footway": "crossing", "crossing": "traffic_signals"}


def way(osm_id: int, tags: dict, node_ids: list[int]) -> Way:
    return Way(osm_id=osm_id, tags=tags, node_ids=node_ids)


@pytest.mark.parametrize(
    "tags, expected",
    [
        ({"crossing": "traffic_signals"}, True),
        ({"crossing": "marked", "crossing:signals": "yes"}, True),
        ({"crossing:signals": "yes"}, True),
        ({"crossing": "zebra", "crossing:signals": "yes"}, True),
        ({"crossing": "traffic_signals", "crossing:signals": "no"}, False),
        ({"crossing": "uncontrolled", "crossing:signals": "yes"}, False),
        ({"crossing": "unmarked", "crossing:signals": "yes"}, False),
        ({"crossing": "uncontrolled", "flashing_lights": "button"}, False),
        ({"crossing": "marked"}, False),
        ({}, False),
    ],
)
def test_what_reads_as_signalised(tags, expected) -> None:
    assert signals.is_signalised(tags) is expected


def test_a_signalised_crossing_way_marks_the_node_it_shares_with_the_road() -> None:
    ways = [
        way(1, ROAD, [10, 11, 12]),
        way(2, SIGNALISED_CROSSING, [20, 11, 21]),
    ]
    assert signals.signal_nodes(ways) == {11}


@pytest.mark.parametrize("key", ["footway", "cycleway", "path"])
def test_each_crossing_scheme_counts(key) -> None:
    crossing = {"highway": "cycleway" if key == "cycleway" else "footway", key: "crossing",
                "crossing": "traffic_signals"}  # fmt: skip
    ways = [way(1, ROAD, [10, 11, 12]), way(2, crossing, [20, 11, 21])]
    assert signals.signal_nodes(ways) == {11}


def test_the_far_ends_of_the_crossing_way_are_not_marked() -> None:
    """Where the crossing way meets the sidewalk or the trail is not a signal."""
    ways = [
        way(1, ROAD, [10, 11, 12]),
        way(2, SIGNALISED_CROSSING, [20, 11, 21]),
        way(3, {"highway": "footway", "footway": "sidewalk"}, [30, 20, 31]),
        way(4, {"highway": "cycleway"}, [21, 40]),
    ]
    assert signals.signal_nodes(ways) == {11}


def test_an_unsignalised_crossing_way_marks_nothing() -> None:
    crossing = {**SIGNALISED_CROSSING, "crossing": "uncontrolled"}
    ways = [way(1, ROAD, [10, 11, 12]), way(2, crossing, [20, 11, 21])]
    assert signals.signal_nodes(ways) == frozenset()


def test_a_signalised_way_that_is_not_a_crossing_marks_nothing() -> None:
    """A trail tagged `crossing=traffic_signals` along its length but not mapped as
    the crossing is not read: the tag cannot say which of its road meetings has
    the signal."""
    trail = {"highway": "cycleway", "crossing": "traffic_signals"}
    ways = [way(1, ROAD, [10, 11, 12]), way(2, trail, [20, 11, 21])]
    assert signals.signal_nodes(ways) == frozenset()


@pytest.mark.parametrize(
    "crossed, marked",
    [
        ({"highway": "residential"}, True),
        ({"highway": "service"}, True),
        ({"highway": "trunk"}, True),
        ({"highway": "busway"}, True),
        ({"highway": "motorway"}, False),
        ({"highway": "cycleway"}, False),
        ({"highway": "footway", "footway": "sidewalk"}, False),
        ({"highway": "construction"}, False),
        ({"railway": "rail"}, False),
    ],
)
def test_only_a_road_crossing_is_marked(crossed, marked) -> None:
    ways = [way(1, crossed, [10, 11, 12]), way(2, SIGNALISED_CROSSING, [20, 11, 21])]
    assert (signals.signal_nodes(ways) == {11}) is marked


def test_node_tags_carry_the_mark_the_transform_reads() -> None:
    assert signals.node_tags({11, 12}) == {
        11: {"rm:crossing_signal": "yes"},
        12: {"rm:crossing_signal": "yes"},
    }
    # The same name lua/routemaker_remap.lua reads, and in the namespace
    # lua/graph.lua strips before upstream sees the node.
    remap = (Path(__file__).resolve().parents[1] / "lua" / "routemaker_remap.lua").read_text()
    assert f'M.SIGNAL_MARK = "{signals.NODE_TAG}"' in remap
    assert signals.NODE_TAG.startswith("rm:")
