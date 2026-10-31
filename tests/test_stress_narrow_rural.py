"""The owner's narrow-road rule and rural floor (2026-10-13, v0.7.0 LTS redo)."""

from __future__ import annotations

import math
import random

import pytest

from routemaker.geo import Point, haversine
from routemaker.stress import (
    NARROW_ROAD_RULE,
    RURAL_FLOOR_RULE,
    Stress,
    bends_slow_traffic,
    classify,
    rural_floor,
    tight_bends,
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

    def test_one_corner_on_a_straight_road_does_not(self):
        # An L, 1 km each leg: 1.41 end to end, which read the whole way as winding
        # (the v0.7.0 staging rebuild's 421 mi of rural LTS 4 at 25 mph).
        leg = [(-77.2 + i * 0.001, 39.2) for i in range(12)]
        corner = leg[-1]
        north = [(corner[0], corner[1] + i * 0.001) for i in range(1, 10)]
        assert not winding(leg + north)

    def test_a_long_winding_road_with_a_straight_end_still_winds(self):
        wiggle = zigzag(n=30)
        tail = [(wiggle[-1][0] + i * 0.001, wiggle[-1][1]) for i in range(1, 6)]
        assert winding(wiggle + tail)

    @pytest.mark.parametrize("n, metres", [(5, 450), (7, 650), (8, 750)])
    def test_a_short_zigzag_too_short_for_two_stretches_still_winds(self, n, metres):
        line = zigzag(n=n)
        length = sum(haversine(Point(*a), Point(*b)) for a, b in zip(line, line[1:], strict=False))
        assert abs(length - metres) < 25 and length < 2 * 400
        assert winding(line)

    def test_a_short_l_does_not(self):
        # 600 m: one corner, 1.41 end to end, one stretch.
        leg = [(-77.2 + i * 0.001, 39.2) for i in range(4)]
        north = [(leg[-1][0], 39.2 + i * 0.001) for i in range(1, 4)]
        assert not winding(leg + north)
        # The same corner drawn as a rounded bend of several vertices.
        bend = [(leg[-1][0] + 0.0002, 39.2 + 0.00005), (leg[-1][0] + 0.0003, 39.2 + 0.0002)]
        assert not winding(leg + bend + [(p[0] + 0.0003, p[1]) for p in north])

    @pytest.mark.parametrize("seed", range(40))
    def test_the_drawing_direction_does_not_matter(self, seed):
        rng = random.Random(seed)
        lon, lat, heading = -77.2, 39.2, rng.uniform(0, 2 * math.pi)
        line = [(lon, lat)]
        for _ in range(rng.randint(4, 40)):
            heading += rng.gauss(0, 0.6)
            step = rng.uniform(0.0002, 0.0015)
            lon, lat = lon + step * math.cos(heading), lat + step * math.sin(heading)
            line.append((lon, lat))
        assert winding(line) == winding(line[::-1])

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


def _bendy(bends: int, leg_m: float = 300.0, radius_m: float = 40.0):
    """A road of straight legs joined by `bends` rounded turns of `radius_m`,
    alternating left and right, ~60 degrees each."""
    lon, lat, heading = -77.2, 39.2, 0.0
    kx = 111_320.0 * math.cos(math.radians(lat))
    line = [(lon, lat)]

    def step(dist):
        nonlocal lon, lat
        lon += dist * math.cos(heading) / kx
        lat += dist * math.sin(heading) / 110_540.0
        line.append((lon, lat))

    step(leg_m)
    for i in range(bends):
        turn = math.radians(60) * (1 if i % 2 else -1)
        pieces = 6
        arc = radius_m * abs(turn)
        for _ in range(pieces):
            heading += turn / pieces
            step(arc / pieces)
        step(leg_m)
    return line


GRAVEL = {"highway": "unclassified", "surface": "gravel", "name": "Featherbed Lane"}


class TestGravelBends:
    """Gravel with turns reads at 25 mph; straight gravel stays at 30 (the owner,
    2026-10-30, after the gravel-speed literature search)."""

    def test_counts_each_tight_bend_once(self):
        assert tight_bends(_bendy(3)) == 3

    def test_a_gentle_bend_is_not_tight(self):
        assert tight_bends(_bendy(3, radius_m=300.0)) == 0

    def test_a_straight_road_has_none(self):
        assert tight_bends(straight()) == 0

    def test_gravel_with_tight_bends_reads_at_25(self):
        line = _bendy(3)
        assert not winding(line)
        result = rural(GRAVEL, winding=bends_slow_traffic(line, GRAVEL))
        assert result.tier is Stress.LTS2
        assert NARROW_ROAD_RULE in result.rule

    def test_straight_gravel_stays_at_30(self):
        result = rural(GRAVEL, winding=bends_slow_traffic(straight(), GRAVEL))
        assert result.tier is Stress.LTS3

    def test_one_corner_on_straight_gravel_does_not_count(self):
        assert not bends_slow_traffic(_bendy(1, leg_m=900.0), GRAVEL)

    def test_bends_far_apart_do_not_count(self):
        assert not bends_slow_traffic(_bendy(2, leg_m=1500.0), GRAVEL)

    def test_paved_road_with_the_same_bends_does_not_count(self):
        paved = {**GRAVEL, "surface": "asphalt"}
        assert not bends_slow_traffic(_bendy(3), paved)

    def test_one_lane_gravel_reads_at_25(self):
        result = rural({**GRAVEL, "lanes": "1"})
        assert result.tier is Stress.LTS2
        assert NARROW_ROAD_RULE in result.rule

    def test_a_count_still_outranks_the_bends(self):
        result = rural(GRAVEL, aadt=4000, winding=bends_slow_traffic(_bendy(3), GRAVEL))
        assert NARROW_ROAD_RULE not in result.rule

    def test_the_limit_is_100_m(self):
        assert tight_bends(_bendy(3, radius_m=80.0)) == 3
        assert tight_bends(_bendy(3, radius_m=130.0)) == 0

    def test_one_long_sweeper_is_one_bend_however_it_is_drawn(self):
        # A 270 degree curve near the limit, drawn with a vertex every 13 m: its
        # windows dip over and under the limit vertex by vertex.
        kx = 111_320.0 * math.cos(math.radians(39.2))
        for radius in (95.0, 99.0, 101.0):
            n = round(radius * math.radians(270) / 13.0)
            arc = [
                (
                    -77.2 + radius * math.cos(math.radians(270) * i / n) / kx,
                    39.2 + radius * math.sin(math.radians(270) * i / n) / 110_540.0,
                )
                for i in range(n + 1)
            ]
            assert tight_bends(arc) <= 1
            assert not bends_slow_traffic(arc, GRAVEL)

    def test_one_corner_on_a_short_gravel_way_does_not_count(self):
        line = _bendy(1, leg_m=200.0)
        assert tight_bends(line) == 1
        assert not bends_slow_traffic(line, GRAVEL)
