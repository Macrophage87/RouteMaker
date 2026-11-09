"""Ride's "End mountain biking" (the owner, 2026-11-08: "a button under the trail closure for 'i
don't want to mountain bike anymore' ... that will route you off mtb trails and onto something
easier"): a ride's re-plan with `mtb_done` leaves the Mountain Bike and off-road graphs for the
standard one, with Easy MTB trails off and no dirt trail ridden."""

from __future__ import annotations

import pytest

from core import presets


@pytest.mark.parametrize("name", ["mountain-bike", "gravel", "mountain-goat"])
def test_the_mtb_graphs_give_way_to_the_standard_one(name) -> None:
    assert presets.variant_for_ride(name, "weekday_offpeak", mtb_done=True) == "standard"
    assert presets.variant_for_ride(name, "weekend", mtb_done=True) == "weekend"
    assert not presets.weekend_too(name, "weekend", mtb_done=True)


def test_easy_mtb_trails_go_off() -> None:
    assert presets.variant_for_ride("default", "weekday_offpeak", easy_mtb=True, mtb_done=True) == (
        "standard"
    )
    assert presets.variant_for_ride("trailmaxxing", "weekend", easy_mtb=True, mtb_done=True) == (
        "weekend"
    )


def test_other_graphs_are_left_as_they_are() -> None:
    assert presets.variant_for_ride("default", "weekday_offpeak", mtb_done=True) == "standard"
    assert presets.variant_for_ride("default", "weekend", trails_off=True, mtb_done=True) == (
        "no-trail"
    )
    assert presets.variant_for_ride("road-bike", "weekday_offpeak", mtb_done=True) == (
        presets.variant_for_ride("road-bike", "weekday_offpeak")
    )


# Through the API: tests/test_dirt_trail_touch.py, TestDoneWithMtb.
