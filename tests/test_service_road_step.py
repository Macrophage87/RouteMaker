"""The owner's service-road step (2026-11-01): alleys, driveways, parking aisles and other
service roads at LTS 1 are LTS 1.5; quiet residential streets at LTS 1 stay at 1."""

from __future__ import annotations

import json

import pytest

from core import segment_info
from pipeline import writers
from routemaker import agency_lts
from routemaker.agency_lts import AgencyRating
from routemaker.stress import (
    SERVICE_ROAD_RULE,
    Stress,
    StressAdjustment,
    StressResult,
    classify,
    rural_floor,
    service_road_step,
)

QUIET = StressResult(Stress.LTS1, "mixed traffic, 20 mph or below, single lane")


@pytest.mark.parametrize("kind", [None, "alley", "driveway", "parking_aisle", "drive-through"])
def test_a_service_road_at_lts_1_is_lts_1_5(kind):
    tags = {"highway": "service", **({"service": kind} if kind else {})}
    stepped = service_road_step(QUIET, tags)
    assert (stepped.tier, stepped.half) == (Stress.LTS1, True)
    assert stepped.rule.endswith(SERVICE_ROAD_RULE)


def test_a_quiet_residential_street_at_lts_1_stays_at_1():
    tags = {"highway": "residential"}
    assert service_road_step(QUIET, tags) is QUIET


def test_a_service_road_above_lts_1_is_left_alone():
    two = StressResult(Stress.LTS2, "mixed traffic, 25 mph")
    assert service_road_step(two, {"highway": "service"}) is two
    already = StressResult(Stress.LTS1, "agency rating: x LTS 1.5", half=True)
    assert service_road_step(already, {"highway": "service"}) is already


def test_a_service_road_closed_to_cars_stays_a_path():
    tags = {"highway": "service", "motor_vehicle": "no"}
    assert service_road_step(QUIET, tags) is QUIET


def test_an_owner_row_on_the_way_wins():
    adjustment = StressAdjustment(
        "owner-row", Stress.LTS1, Stress.LTS1, "other", "public", "approved"
    )
    owned = StressResult(Stress.LTS1, "override", adjustment=adjustment)
    assert service_road_step(owned, {"highway": "service"}) is owned


def test_the_step_applies_over_an_agency_level_1():
    rated = agency_lts.apply(QUIET, [AgencyRating("mdot-sha", 1)])
    tags = {"highway": "service"}
    stepped = service_road_step(rural_floor(rated, tags, urban=True), tags)
    assert (stepped.tier, stepped.half) == (Stress.LTS1, True)


def test_a_rural_service_road_takes_the_floor_not_the_step():
    tags = {"highway": "service"}
    stepped = service_road_step(rural_floor(QUIET, tags, urban=False), tags)
    assert (stepped.tier, stepped.half) == (Stress.LTS2, False)


def test_the_road_panel_says_why():
    words = segment_info.rule_words(service_road_step(QUIET, {"highway": "service"}).rule)
    assert "alley or service road" in words


def test_the_classifier_alone_does_not_step():
    # The step is the rebuild's, after any agency rating, like the rural floor.
    result = classify({"highway": "service", "service": "alley"}, jurisdiction="DC")
    assert SERVICE_ROAD_RULE not in result.rule


def test_a_private_drive_open_to_bikes_is_stepped():
    # Private cars still use it: "all service roads 1.5" (the owner, 2026-11-01).
    tags = {"highway": "service", "access": "private", "bicycle": "designated"}
    assert service_road_step(QUIET, tags).half is True


def test_the_road_panel_names_the_step_as_the_rating_used():
    rated = agency_lts.apply(QUIET, [AgencyRating("mdot-sha", 1)])
    stepped = service_road_step(rated, {"highway": "service"})
    held = json.loads(writers._ratings_json(stepped))
    assert held["used"] == "service road"
    assert "service road" in segment_info._USED_WORDS["service road"]
