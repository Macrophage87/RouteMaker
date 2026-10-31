"""A junction reads a road by its traffic (the owner, 2026-10-31: "a protected bike lane on
a busy road is just as hard to cross", "Traffic only, everywhere"). For one through lane a
direction that reading is the classifier's own mixed-traffic reading, from the facts the
segment table keeps (`stress.single_lane_traffic_level`): pinned here against `classify`,
so a change to the classifier's single-lane rules shows up at the junctions too."""

from __future__ import annotations

import itertools

import pytest

from routemaker.stress import classify, single_lane_traffic_level

SPEEDS = (20, 25, 30, 35, 40, 45, 50)
COUNTS = (None, 1_000, 1_501, 3_000, 5_000, 7_999, 8_000, 11_999, 12_000, 19_999, 20_000)


@pytest.mark.parametrize(
    ("speed", "aadt", "oneway", "urban"),
    list(itertools.product(SPEEDS, COUNTS, (False, True), (True, False))),
)
def test_the_single_lane_reading_is_the_classifiers(speed, aadt, oneway, urban) -> None:
    tags = {"highway": "residential", "maxspeed": f"{speed} mph", "surface": "asphalt"}
    tags |= {"oneway": "yes", "lanes": "1"} if oneway else {"lanes": "2"}
    result = classify(tags, aadt=aadt, urban=urban)
    assert single_lane_traffic_level(speed, oneway, aadt, urban) == (result.tier, result.half)


@pytest.mark.parametrize("aadt", [None, 1_000, 9_000])
def test_a_protected_lane_is_not_in_the_reading(aadt) -> None:
    # The same street with a protected lane rates calmer to ride along, never to cross.
    base = {"highway": "residential", "maxspeed": "35 mph", "lanes": "2"}
    ridden = classify(base | {"cycleway:both": "track"}, aadt=aadt)
    crossed = single_lane_traffic_level(35, False, aadt, True)
    assert crossed >= (ridden.tier, ridden.half)
