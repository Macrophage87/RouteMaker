"""Work zones from the WZDx feeds, read for the planner (FOLLOWUP-WORKZONES, 341-349).

The fixture is hand-made in the WZDx v4.1 shape (tests/data/workzones): neither feed
could be reached from where this was written, so nothing here is agency data.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path

import pytest

from routemaker import workzones as wz

SAMPLE = Path(__file__).resolve().parent / "data" / "workzones" / "wzdx-v4-sample.geojson"
AT = datetime(2026, 10, 11, 14, 0, tzinfo=UTC)


def zones() -> dict[str, wz.Zone]:
    return {z.zone_id: z for z in wz.parse_feed(json.loads(SAMPLE.read_text()), "md")}


class TestTheFeed:
    def test_work_zones_with_a_line_are_read_and_nothing_else(self) -> None:
        assert sorted(zones()) == [
            "md-wz-closed-bikes",
            "md-wz-closed-unknown",
            "md-wz-flagger",
            "md-wz-lane",
            "md-wz-shoulder",
        ]

    def test_the_fields_the_planner_uses(self) -> None:
        zone = zones()["md-wz-closed-bikes"]
        assert zone.road == "Example Road northbound"
        assert zone.description.startswith("Bridge deck replacement")
        assert zone.start == datetime(2026, 10, 1, tzinfo=UTC)
        assert zone.end == datetime(2026, 12, 1, tzinfo=UTC)
        assert zone.line == ((-77.03, 38.95), (-77.03, 38.953))

    def test_a_multipoint_is_the_line_between_its_ends(self) -> None:
        assert zones()["md-wz-shoulder"].line == ((-77.05, 38.97), (-77.05, 38.973))

    def test_an_unknown_direction_is_not_said(self) -> None:
        assert zones()["md-wz-lane"].road == "Test Street"

    def test_something_that_is_not_a_feed_is_refused(self) -> None:
        with pytest.raises(ValueError):
            wz.parse_feed({"features": []}, "md")

    def test_a_zone_survives_the_round_trip_through_the_stored_copy(self) -> None:
        for zone in zones().values():
            assert wz.Zone.from_json(json.loads(json.dumps(zone.to_json()))) == zone


class TestTheReading:
    """342(3) and 342(4)."""

    def test_closed_to_bicycles_only_when_the_feed_says_so(self) -> None:
        z = zones()
        assert (z["md-wz-closed-bikes"].kind, z["md-wz-closed-bikes"].penalty_s) == (wz.CLOSED, 0)
        # Every lane closed, bicycles not mentioned: penalised, not excluded.
        assert z["md-wz-closed-unknown"].kind == wz.UNKNOWN
        assert z["md-wz-closed-unknown"].penalty_s == wz.UNKNOWN_PENALTY_S

    @pytest.mark.parametrize(
        ("properties", "penalty"),
        [
            (
                {
                    "vehicle_impact": "all-lanes-open",
                    "lanes": [{"type": "shoulder", "status": "closed"}],
                },
                60,
            ),
            ({"vehicle_impact": "all-lanes-open"}, 60),
            ({"vehicle_impact": "some-lanes-closed"}, 120),
            ({"vehicle_impact": "unknown"}, 120),
            ({}, 120),
            ({"vehicle_impact": "alternating-one-way"}, 180),
            ({"vehicle_impact": "flagging"}, 180),
            ({"lanes": [{"type": "general", "status": "alternating-flow"}]}, 180),
            ({"vehicle_impact": "some-lanes-closed-merge-left"}, 120),
        ],
    )
    def test_the_owners_penalties(self, properties, penalty) -> None:
        kind, seconds, why = wz.classify(properties)
        assert (kind, seconds) == (wz.PENALTY, penalty) and why

    def test_all_lanes_closed_with_a_bike_lane_still_open_is_not_closed_to_bicycles(self) -> None:
        kind, _, _ = wz.classify(
            {
                "vehicle_impact": "all-lanes-closed",
                "lanes": [
                    {"type": "general", "status": "closed"},
                    {"type": "bike-lane", "status": "open"},
                ],
            }
        )
        assert kind == wz.UNKNOWN

    def test_the_window(self) -> None:
        lane = zones()["md-wz-lane"]  # 2026-10-10 13:00 to 21:00 UTC
        assert wz.active(lane, datetime(2026, 10, 10, 15, tzinfo=UTC))
        assert not wz.active(lane, datetime(2026, 10, 10, 12, tzinfo=UTC))
        assert not wz.active(lane, datetime(2026, 10, 10, 21, tzinfo=UTC))
        # No end: in force until the feed says otherwise.
        assert wz.active(zones()["md-wz-shoulder"], datetime(2030, 1, 1, tzinfo=UTC))


# A route north along x = -77.0300 through the closed zone, and one along y = 38.9600
# through the unknown-access closure.
NORTH = [(-77.0300, 38.9450), (-77.0300, 38.9580)]
EAST = [(-77.0450, 38.9600), (-77.0300, 38.9600)]


class TestThePlan:
    def test_a_closure_is_excluded_as_a_strip_trimmed_at_both_ends(self) -> None:
        plan = wz.for_plan(zones().values(), AT, NORTH, {"md": "current"})
        assert [z.zone_id for z in plan.excluded] == ["md-wz-closed-bikes"]
        (ring,) = plan.exclude
        assert ring[0] == ring[-1]
        lats = [lat for _, lat in ring]
        # Trimmed 20 m (about 0.00018 degrees) from each end of 38.9500-38.9530.
        assert 38.9501 < min(lats) and max(lats) < 38.9529
        lons = [lon for lon, _ in ring]
        # About 6 m either side.
        assert max(lons) - min(lons) == pytest.approx(12 / 86_700, rel=0.1)

    def test_the_other_zones_are_passable(self) -> None:
        plan = wz.for_plan(zones().values(), AT, NORTH + EAST, {"md": "current"})
        assert {z.zone_id for z in plan.passable} == {
            "md-wz-closed-unknown",
            "md-wz-shoulder",
            "md-wz-flagger",
        }  # the lane closure's window is over at AT

    def test_a_closure_by_a_placed_point_is_warned_of_not_excluded(self) -> None:
        start_inside = [(-77.0300, 38.9515), (-77.0300, 38.9700)]
        plan = wz.for_plan(zones().values(), AT, start_inside, {"md": "current"})
        assert plan.exclude == []
        assert [z.zone_id for z in plan.unexcluded] == ["md-wz-closed-bikes"]

    def test_a_closure_far_from_the_ride_is_not_sent(self) -> None:
        plan = wz.for_plan(
            zones().values(), AT, [(-76.5, 39.3), (-76.49, 39.31)], {"md": "current"}
        )
        assert not plan.any

    def test_the_routers_limits_are_kept(self) -> None:
        many = [
            wz.Zone(f"md-{n}", "md", wz.CLOSED, 0, line, None, None, None, None)
            for n in range(40)
            for line in [((-77.0 + n * 0.001, 38.9), (-77.0 + n * 0.001, 38.903))]
        ]
        plan = wz.for_plan(many, AT, [(-77.0, 38.9), (-76.96, 38.903)], {"md": "current"})
        perimeter, vertices = wz.budget_used(plan.exclude)
        assert vertices <= wz.MAX_VERTICES and perimeter <= wz.MAX_PERIMETER_M
        assert plan.excluded and plan.unexcluded
        assert len(plan.excluded) + len(plan.unexcluded) == 40


class TestAlong:
    def test_a_zone_the_route_runs_along_is_found_with_its_metres(self) -> None:
        (passage,) = wz.along(NORTH, [zones()["md-wz-closed-bikes"]])
        # The zone starts about 556 m up the route, and is trimmed 20 m at each end.
        assert 560 < passage.from_m < 590 and 860 < passage.to_m < 890

    def test_a_street_the_route_only_crosses_is_not_along_it(self) -> None:
        assert wz.along(EAST, [zones()["md-wz-closed-bikes"]]) == []
        crossing = [(-77.0320, 38.9515), (-77.0280, 38.9515)]
        assert wz.along(crossing, [zones()["md-wz-closed-bikes"]]) == []


def _along_every_segment(coordinates, zones):
    """`along` as it was before audit round 3, S27: each zone's box tested against every
    segment of the route. The grid must give exactly what this gives."""
    if len(coordinates) < 2:
        return []
    lat0 = coordinates[0][1]
    route = [wz._xy(c[0], c[1], lat0) for c in coordinates]
    cumulative = [0.0]
    for a, b in zip(route, route[1:], strict=False):
        cumulative.append(cumulative[-1] + math.dist(a, b))
    xs = [p[0] for p in route]
    ys = [p[1] for p in route]
    box = (min(xs) - 100, min(ys) - 100, max(xs) + 100, max(ys) + 100)
    found = []
    for zone in zones:
        points = [wz._xy(lon, lat, lat0) for lon, lat in zone.line]
        if not any(box[0] <= x <= box[2] and box[1] <= y <= box[3] for x, y in points):
            continue
        if wz._length(points) < 1.0:
            continue
        samples = wz._samples(wz._trim(points, wz.TRIM_M))
        zx = [x for x, _ in points]
        zy = [y for _, y in points]
        near_box = (
            min(zx) - wz.ALONG_M,
            min(zy) - wz.ALONG_M,
            max(zx) + wz.ALONG_M,
            max(zy) + wz.ALONG_M,
        )
        nearby = [
            i
            for i in range(len(route) - 1)
            if min(xs[i], xs[i + 1]) <= near_box[2]
            and max(xs[i], xs[i + 1]) >= near_box[0]
            and min(ys[i], ys[i + 1]) <= near_box[3]
            and max(ys[i], ys[i + 1]) >= near_box[1]
        ]
        if not nearby:
            continue
        near = []
        for s in samples:
            best, at = math.inf, 0.0
            for i in nearby:
                a, b = route[i], route[i + 1]
                d = wz._to_segment(s, a, b)
                if d < best:
                    seg = math.dist(a, b)
                    t = (
                        0.0
                        if seg == 0
                        else max(
                            0.0,
                            min(
                                1.0,
                                ((s[0] - a[0]) * (b[0] - a[0]) + (s[1] - a[1]) * (b[1] - a[1]))
                                / seg**2,
                            ),
                        )
                    )
                    best, at = d, cumulative[i] + t * seg
            if best <= wz.ALONG_M:
                near.append(at)
        if near and len(near) >= wz.ALONG_SHARE * len(samples):
            found.append(wz.Passage(zone, min(near), max(near)))
    return sorted(found, key=lambda p: (p.from_m, p.zone.zone_id))


def _reference_route(name: str) -> list[tuple[float, float]]:
    import re

    text = (
        Path(__file__).resolve().parent.parent / "fixtures" / "reference-routes" / name
    ).read_text()
    return [
        (float(lon), float(lat))
        for lat, lon in re.findall(r'<trkpt lat="([-0-9.]+)" lon="([-0-9.]+)"', text)
    ]


@pytest.mark.parametrize(
    "name",
    [
        "2026-04-dcbp.gpx",
        "group-crit-mass-jan.gpx",
        "trail-bethesda-loop.gpx",
        "rural-group-tnl.gpx",
    ],
)
def test_along_on_the_grid_finds_exactly_what_every_segment_found(name: str) -> None:
    """Audit round 3, S27(a): `along` looks only at the route's segments in the grid cells round
    each zone. On the reference routes, with zones laid along them, beside them, across them
    and away from them, it finds the same passages, metre for metre, in the same order."""
    import random

    route = _reference_route(name)
    assert len(route) > 50
    rng = random.Random(name)
    found_zones = list(zones().values())
    for n in range(300):
        i = rng.randrange(len(route) - 1)
        j = min(len(route) - 1, i + rng.randrange(1, 30))
        # Along the route (offset a little, up to past ALONG_M), across it, or anywhere near.
        dx, dy = rng.uniform(-0.0004, 0.0004), rng.uniform(-0.0004, 0.0004)
        kind = n % 3
        if kind == 0:
            line = tuple((lon + dx, lat + dy) for lon, lat in route[i : j + 1])
        elif kind == 1:
            lon, lat = route[i]
            line = ((lon - 0.002, lat + dy), (lon + 0.002, lat - dy))
        else:
            lon, lat = route[i]
            line = ((lon + dx * 20, lat + dy * 20), (lon + dx * 25, lat - dy * 25))
        found_zones.append(wz.Zone(f"z{n}", "dc", wz.CLOSED, 0.0, line, None, None, None, None))
    fast = wz.along(route, found_zones)
    assert fast == _along_every_segment(route, found_zones)
    assert len(fast) > 20, "the zones laid along the route are found"


def test_along_looks_only_at_the_segments_round_each_zone(monkeypatch) -> None:
    """Audit round 3, S27(a): the route is put on the grid once per call, and each zone near it
    is box-tested against the segments in its cells, not every segment of the line."""
    route = _reference_route("rural-group-tnl.gpx")
    built, looked = [], []
    real_init, real_segments = wz.RouteGrid.__init__, wz.RouteGrid.segments

    def init(self, coordinates):
        built.append(len(coordinates))
        real_init(self, coordinates)

    def segments(self, *box):
        found = real_segments(self, *box)
        looked.append(len(found))
        return found

    monkeypatch.setattr(wz.RouteGrid, "__init__", init)
    monkeypatch.setattr(wz.RouteGrid, "segments", segments)
    middle = route[len(route) // 2 : len(route) // 2 + 10]
    zone_list = [
        wz.Zone(f"z{n}", "dc", wz.CLOSED, 0.0, tuple(middle), None, None, None, None)
        for n in range(3)
    ]
    assert len(wz.along(route, zone_list)) == 3
    assert built == [len(route)]
    assert len(looked) == 3 and all(0 < n < (len(route) - 1) / 4 for n in looked), looked


class TestTheWords:
    def test_one_short_line_said_and_the_source_in_small_print(self) -> None:
        # The owner, 2026-10-17: "the statement is way too verbose. We can cite our sources
        # without all that extra noise." No ": " either, which Ride would cut at.
        zone = zones()["md-wz-closed-unknown"]
        text = wz.heads_up(zone)
        assert text == "Sample Avenue eastbound has every lane closed ahead; bike access unclear."
        assert wz.heads_up(zones()["md-wz-closed-bikes"]).endswith(" marked closed ahead.")
        assert (
            wz.citation(zone) == "Source: Maryland DOT SHA work zones (WZDx, CC0), until Nov 30."
        )  # 00:00 UTC, in Eastern time

    def test_where_the_detour_leaves_the_standard_way(self) -> None:
        assert wz.split_words(zones()["md-wz-closed-bikes"]).endswith(
            " marked closed. Detour posted."
        )
        assert wz.split_words(None) == "The road ahead marked closed. Detour posted."

    def test_a_closure_is_red_and_a_penalty_orange(self) -> None:
        z = zones()
        assert wz.severity(z["md-wz-closed-bikes"]) == "red"
        assert wz.severity(z["md-wz-closed-unknown"]) == "red"
        assert wz.severity(z["md-wz-shoulder"]) == "orange"


def test_the_map_s_nearness_matches_measuring_every_segment_and_is_quick() -> None:
    """core.workzones._RouteIndex (the MCP tester, 2026-10-19): a 100 mi loop's map pass took
    the plan past the web server's 60 s. The index gives the same distance for every zone within
    the map's reach, and inf only for zones beyond it."""
    import random
    import time as clock

    from core import workzones as site
    from routemaker import workzones as zrules

    rng = random.Random(7)
    # A loop round DC: about 100 mi of line in 20 m steps' worth of vertices.
    loop = [
        (
            -77.03 + 0.12 * math.cos(t / 4000 * 2 * math.pi),
            38.9 + 0.1 * math.sin(t / 4000 * 2 * math.pi),
        )
        for t in range(4001)
    ]
    zones = []
    for n in range(600):
        lon, lat = -77.03 + rng.uniform(-0.16, 0.16), 38.9 + rng.uniform(-0.14, 0.14)
        line = ((lon, lat), (lon + rng.uniform(-0.003, 0.003), lat + rng.uniform(-0.003, 0.003)))
        zones.append(zrules.Zone(f"z{n}", "dc", zrules.CLOSED, 0.0, line, None, None, None, None))

    def every_segment(zone):
        lat0 = zone.line[0][1]
        route = [zrules._xy(c[0], c[1], lat0) for c in loop]
        return min(zrules._distance_to_line(zrules._xy(x, y, lat0), route) for x, y in zone.line)

    started = clock.monotonic()
    index = site._RouteIndex(loop, site.MAP_NEAR_M)
    fast = [index.near(zone) for zone in zones]
    took = clock.monotonic() - started
    for zone, near in zip(zones, fast, strict=True):
        slow = every_segment(zone)
        if slow <= site.MAP_NEAR_M:
            assert near == pytest.approx(slow), zone.zone_id
        else:
            assert near > site.MAP_NEAR_M, zone.zone_id
    assert took < 2.0, took
