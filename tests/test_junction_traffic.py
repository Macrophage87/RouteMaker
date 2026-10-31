"""A junction reads a road by its traffic (the owner, 2026-10-31: "a protected bike lane on
a busy road is just as hard to cross", "Traffic only, everywhere"). For one through lane a
direction that reading is the classifier's own mixed-traffic reading, from the facts the
segment table keeps (`stress.single_lane_traffic_level`): pinned here against `classify`,
so a change to the classifier's single-lane rules shows up at the junctions too."""

from __future__ import annotations

import itertools

import pytest

from routemaker.intersections import Control, Junction, Movement, Road, assess, traffic_level
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


@pytest.mark.parametrize("urban", [True, False])
def test_an_unposted_quiet_street_keeps_its_map_level(urban) -> None:
    # Maryland's statutory 30 in town and 50 out of it are not what the classifier read on a
    # residential street (its own 25), so the junction does not guess: the map stands.
    quiet = Road(1, lanes=1, oneway=False, default_speed_mph=30.0 if urban else 50.0, urban=urban)
    assert traffic_level(quiet) is None
    assert (
        assess(
            Junction(0.0, -77.0, 38.9, Movement.STRAIGHT, Road(1), Road(1), (quiet,), Control.STOP)
        )
        is None
    )
