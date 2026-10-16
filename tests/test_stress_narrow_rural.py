"""The owner's narrow-road rule and rural floor (2026-10-13, v0.7.0 LTS redo)."""

from __future__ import annotations

import math

from routemaker.stress import (
    NARROW_ROAD_RULE,
    RURAL_FLOOR_RULE,
    Stress,
    classify,
    rural_floor,
    winding,
)

# Davis Mill Road as OSM has it: rural, unclassified, nothing posted, no count.
DAVIS_MILL = {"highway": "unclassified", "name": "Davis Mill Road"}


def rural(tags, **kwargs):
    return classify(tags, urban=False, **kwargs)


def zigzag(n=12, step_deg=0.001, amplitude_deg=0.0006):
    """A line ~1 km long that swings side to side: sinuosity well above 1.2."""
    return [(-77.2 + i * step_deg, 39.2 + (amplitude_deg if i % 2 else 0.0)) for i in range(n)]


def straight(n=12, step_deg=0.001):
    return [(-77.2 + i * step_deg, 39.2) for i in range(n)]


class TestWinding:
    def test_a_zigzag_road_winds(self):
        assert winding(zigzag())

    def test_a_straight_road_does_not(self):
        assert not winding(straight())

    def test_a_short_way_says_nothing(self):
        assert not winding(zigzag(n=3))

    def test_a_closed_ring_is_not_read_as_winding(self):
        ring = [(-77.2 + 0.003 * math.cos(a), 39.2 + 0.003 * math.sin(a)) for a in range(0, 7)]
        ring.append(ring[0])
        assert not winding(ring)


class TestNarrowRoadRule:
    def test_the_unposted_rural_default_is_lts4_without_it(self):
        result = rural(DAVIS_MILL)
        assert result.tier is Stress.LTS4

    def test_a_winding_unposted_rural_road_is_read_at_25(self):
        result = rural(DAVIS_MILL, winding=True)
        assert result.tier is Stress.LTS2
        assert NARROW_ROAD_RULE in result.rule
        # Still an assumption, never told to a rider as a posted speed.
        assert "maxspeed" in result.assumed
        assert result.speed_mph is None

    def test_no_centre_line_is_narrow(self):
        assert rural({**DAVIS_MILL, "lane_markings": "no"}).tier is Stress.LTS2

    def test_a_surveyed_narrow_width_is_narrow(self):
        assert rural({**DAVIS_MILL, "width": "5"}).tier is Stress.LTS2
        assert rural({**DAVIS_MILL, "width": "7"}).tier is Stress.LTS4

    def test_a_posted_limit_outranks_it(self):
        assert rural({**DAVIS_MILL, "maxspeed": "40 mph"}, winding=True).tier is Stress.LTS4

    def test_a_count_outranks_it(self):
        busy = rural(DAVIS_MILL, winding=True, aadt=9_000)
        assert NARROW_ROAD_RULE not in busy.rule
        assert busy.tier is Stress.LTS4

    def test_not_inside_an_urban_area(self):
        result = classify(DAVIS_MILL, urban=True, winding=True)
        assert NARROW_ROAD_RULE not in result.rule

    def test_not_on_secondary_roads(self):
        result = rural({"highway": "secondary"}, winding=True)
        assert result.tier is Stress.LTS4

    def test_tertiary_lands_on_lts2_too(self):
        assert rural({"highway": "tertiary"}, winding=True).tier is Stress.LTS2


class TestRuralFloor:
    def test_a_quiet_rural_road_is_lts2_at_best(self):
        lane = rural({"highway": "residential"})
        assert lane.tier is Stress.LTS2
        farm_lane = rural({"highway": "service"})
        assert farm_lane.tier is Stress.LTS1
        floored = rural_floor(farm_lane, {"highway": "service"}, urban=False)
        assert floored.tier is Stress.LTS2
        assert RURAL_FLOOR_RULE in floored.rule

    def test_not_inside_an_urban_area(self):
        street = classify({"highway": "service"}, urban=True)
        assert rural_floor(street, {"highway": "service"}, urban=True) is street

    def test_trails_are_exempt(self):
        tags = {"highway": "cycleway"}
        path = rural(tags)
        assert rural_floor(path, tags, urban=False).tier is Stress.LTS1

    def test_a_separated_track_is_exempt(self):
        tags = {"highway": "tertiary", "maxspeed": "25 mph", "cycleway": "track"}
        result = rural(tags)
        assert result.tier is Stress.LTS1
        assert rural_floor(result, tags, urban=False).tier is Stress.LTS1

    def test_closed_to_cars_is_exempt(self):
        for value in ("no", "agricultural", "forestry"):
            tags = {"highway": "track", "motor_vehicle": value}
            result = rural(tags)
            assert rural_floor(result, tags, urban=False).tier is Stress.LTS1, value

    def test_private_access_is_floored(self):
        tags = {"highway": "service", "access": "private"}
        result = rural(tags)
        assert rural_floor(result, tags, urban=False).tier is Stress.LTS2

    def test_higher_tiers_are_untouched(self):
        tags = {"highway": "secondary"}
        result = rural(tags)
        assert rural_floor(result, tags, urban=False) is result
