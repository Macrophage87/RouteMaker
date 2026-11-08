"""How closures reach the router as strips (hunt K1-K5, Q1-Q3, 2026-11-08).

- The strips' perimeter is measured as Valhalla 3.9.1 measures it, and packed under its cap
  with a margin; a refusal for the polygons' limits (167, 176) is retried with fewer closures.
- A closure near a rider's point is left out beyond the point, not let in whole.
- A strip is cut where a way crosses it (a cross street, a bridge over, a tunnel under).
- A refusal for no path (442) lets in only the rings at the destination's and vias' edges first.
- A route that rides through a road the rider marked closed is planned again the other way.

Pure: no database, no router (the router's answers are stand-ins).
"""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime

import pytest

from routemaker import workzones as wz

AT = datetime(2026, 11, 8, 15, tzinfo=UTC)
M_LAT = 1 / 111_195  # one metre of latitude


def valhalla_length(rings) -> float:
    """Valhalla 3.9.1's own count (loki/polygon_search.cc `edges_in_rings`): haversine on
    6,378,160.187 m, summed over each ring's segments (hunt/qrepro/q_perimeter.py)."""
    total = 0.0
    for ring in rings:
        for (lon1, lat1), (lon2, lat2) in zip(ring, ring[1:], strict=False):
            p1, p2 = math.radians(lat1), math.radians(lat2)
            dphi, dl = p2 - p1, math.radians(lon2 - lon1)
            h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
            total += 6_378_160.187 * 2 * math.asin(math.sqrt(min(1, max(0, h))))
    return total


def closed(zone_id: str, line, source: str = "md") -> wz.Zone:
    return wz.Zone(zone_id, source, wz.CLOSED, 0, tuple(line), "Road", None, None, None)


class TestThePerimeterIsTheRoutersOwn:
    def test_a_ring_is_measured_as_valhalla_measures_it(self) -> None:
        ring = wz.polygon(closed("z", ((-77.03, 38.90), (-77.03, 38.91))))
        assert wz.ring_perimeter_m(ring) == pytest.approx(valhalla_length([ring]), rel=1e-12)

    def test_a_busy_weeks_plan_is_never_past_the_routers_cap(self) -> None:
        """Before: 24 of 50 budget-filled plans came out over 50,000 m by Valhalla's count
        (error 167, then no route). Now none does, with room to spare."""
        random.seed(1)
        for trial in range(20):
            zones = []
            for i in range(150):
                lon = -77.05 + random.random() * 0.1
                lat = 38.88 + random.random() * 0.1
                length = random.choice([0.0008, 0.002, 0.004, 0.008])
                zones.append(closed(f"z{trial}-{i}", ((lon, lat), (lon, lat + length))))
            plan = wz.for_plan(zones, AT, [(-77.05, 38.88), (-76.95, 38.98)], {"md": "current"})
            assert plan.unexcluded  # more than fit: the budget is full
            assert valhalla_length(plan.exclude) <= wz.MAX_PERIMETER_M * 0.995

    def test_the_margin_stays_under_the_cap_the_configs_set(self) -> None:
        assert wz.PERIMETER_BUDGET_M < wz.MAX_PERIMETER_M
        assert wz.over_budget([[[0.0, 0.0]] * (wz.MAX_VERTICES + 1)])


class TestNearAPointPlaced:
    def test_the_rings_leave_out_the_part_by_the_point_only(self) -> None:
        line = ((-77.03, 38.9500), (-77.03, 38.9530))
        whole = wz.line_rings(line, wz.TRIM_M)
        assert whole == [wz.line_ring(line, wz.TRIM_M)]
        start = (-77.03, 38.9500 + 150 * M_LAT)
        south, north = wz.line_rings(line, wz.TRIM_M, points=[start])
        assert max(lat for _, lat in south) < start[1] - 45 * M_LAT
        assert min(lat for _, lat in north) > start[1] + 45 * M_LAT

    def test_a_closure_by_a_destination_or_via_is_warned_of_whole(self) -> None:
        """Review of K3: at a stop the rest of the strip would still meet the stop's edge, so
        only the start leaves the part by it in."""
        line = ((-77.03, 38.9500), (-77.03, 38.9530))
        zone = closed("z", line)
        dest = (-77.03, 38.9500 + 150 * M_LAT)
        plan = wz.for_plan([zone], AT, [(-77.05, 38.95), dest], {"md": "current"})
        assert plan.exclude == [] and [z.zone_id for z in plan.unexcluded] == ["z"]


def road_lon(metres: float, lon0: float = -77.03, lat: float = 38.90) -> float:
    return lon0 + metres / (111_195 * math.cos(math.radians(lat)))


class TestStripsAreCutWhereAWayCrosses:
    """Hunt K4/Q2 (hunt/qrepro/q_crossing.py): a 400 m closure on an east-west road. Before,
    the trail under it, the cross street's block and a sidepath 5 m off were all left out."""

    LAT = 38.90
    LINE = ((-77.03, 38.90), (road_lon(400), 38.90))
    MID = road_lon(200)
    TRAIL = [(MID, LAT - 400 * M_LAT), (MID, LAT + 400 * M_LAT)]  # under the road, 800 m edge
    CROSS = [(MID, LAT), (MID, LAT + 150 * M_LAT)]  # the block north of the junction
    # The closed road's own two edges, either side of the junction.
    WEST = [(-77.03, LAT), (MID, LAT)]
    EAST = [(MID, LAT), (road_lon(400), LAT)]

    def clipped(self, way):
        """The way where it lies in the strip, as the map's query clips it."""
        (lon_a, lat_a), (lon_b, lat_b) = way
        lo, hi = (
            max(min(lat_a, lat_b), self.LAT - 6 * M_LAT),
            min(max(lat_a, lat_b), self.LAT + 6 * M_LAT),
        )
        return [(lon_a, lo), (lon_a, hi)]

    def test_a_way_across_the_line_is_a_cut_and_one_along_it_is_not(self) -> None:
        sidepath = [(-77.03, self.LAT + 5 * M_LAT), (road_lon(400), self.LAT + 5 * M_LAT)]
        cuts = wz.crossing_cuts(self.LINE, [self.clipped(self.TRAIL), sidepath, self.WEST])
        assert len(cuts) == 1 and cuts[0] == pytest.approx(200, abs=2)

    def test_the_crossing_ways_keep_their_edges_and_the_closed_road_does_not(self) -> None:
        before = [wz.polygon(closed("z", self.LINE))]
        assert any(wz.line_meets_ring(self.TRAIL, r) for r in before)
        assert any(wz.line_meets_ring(self.CROSS, r) for r in before)
        cuts = wz.crossing_cuts(self.LINE, [self.clipped(self.TRAIL), self.clipped(self.CROSS)])
        rings = wz.zone_rings(closed("z", self.LINE), crossings=cuts)
        assert len(rings) == 2
        assert not any(wz.line_meets_ring(self.TRAIL, r) for r in rings)
        assert not any(wz.line_meets_ring(self.CROSS, r) for r in rings)
        assert any(wz.line_meets_ring(self.WEST, r) for r in rings)
        assert any(wz.line_meets_ring(self.EAST, r) for r in rings)

    def test_a_cut_never_leaves_a_short_closure_with_nothing_left_out(self) -> None:
        short = ((-77.03, self.LAT), (road_lon(70), self.LAT))
        (ring,) = wz.line_rings(short, wz.TRIM_M, crossings=[35.0])
        assert ring == wz.line_ring(short, wz.TRIM_M)

    def test_a_plan_cuts_its_closures_where_it_is_told_ways_cross(self) -> None:
        zone = closed("z", self.LINE)
        points = [(-77.03, 38.92), (-77.00, 38.92)]
        cuts = {"z": wz.crossing_cuts(self.LINE, [self.clipped(self.TRAIL)])}
        plan = wz.for_plan([zone], AT, points, {"md": "current"}, crossings=lambda zones: cuts)
        assert len(plan.exclude) == 2 and plan.rings["z"] == plan.exclude
        assert plan.closure_ring_count() == 2


class TestTheRingsTheRouterLeavesOut:
    def test_the_port_of_line_intersects_ring(self) -> None:
        ring = wz.polygon(closed("z", ((-77.03, 38.90), (road_lon(400), 38.90))))
        across = [(road_lon(200), 38.90 - 50 * M_LAT), (road_lon(200), 38.90 + 50 * M_LAT)]
        inside = [(road_lon(150), 38.90), (road_lon(160), 38.90)]
        apart = [(road_lon(150), 38.90 + 8 * M_LAT), (road_lon(160), 38.90 + 8 * M_LAT)]
        assert wz.line_meets_ring(across, ring)
        assert wz.line_meets_ring(inside, ring)
        assert not wz.line_meets_ring(apart, ring)


# --- The router's side (core): no database, the router stood in for -------------------


@pytest.fixture
def two_closures():
    """A plan with two closures and a road the rider marked closed: one closure by the
    destination, one far from it."""
    from core import workzones as core_zones

    dest = (-77.00, 38.95)
    # About 220 ft (67 m) up the destination's own edge: past `NEAR_POINT_M`, so it is left
    # out, and its strip still meets that edge (hunt K2's case).
    by_dest = closed("by-dest", ((-77.00, 38.9506), (-77.00, 38.9530)))
    far = closed("far", ((-77.05, 38.9300), (-77.05, 38.9330)))
    points = [(-77.05, 38.95), dest]
    plan = wz.for_plan([by_dest, far], AT, points, {"md": "current"})
    marked = core_zones.rules.line_ring(((-77.02, 38.96), (-77.02, 38.961)))
    plan.blocked = [marked]
    plan.exclude = list(plan.exclude) + [marked]
    request = {
        "locations": [{"lon": p[0], "lat": p[1], "radius": 15} for p in points],
        "costing": "bicycle",
        "costing_options": {"bicycle": {}},
        "exclude_polygons": list(plan.exclude),
    }
    return plan, request, points


class TestOnlyTheClosuresAtTheStopsAreLetIn:
    def test_the_closures_meeting_the_stops_edges_are_found(self, two_closures) -> None:
        from core import workzones as core_zones

        plan, request, _points = two_closures
        # The destination's edge runs north along the road into the closure.
        edge = [[-77.00, 38.9490], [-77.00, 38.9600]]
        ids, rings = core_zones.at_stops([edge], plan, request)
        assert ids == ["by-dest"] and rings == []

    def test_dropping_one_keeps_the_others_and_the_riders_roads(self, two_closures) -> None:
        from core import workzones as core_zones

        plan, request, _points = two_closures
        far_ring = plan.rings["far"]
        marked = plan.blocked[0]
        dropped = core_zones.drop_closures(request, plan, ["by-dest"])
        assert [z.zone_id for z in dropped] == ["by-dest"]
        assert [z.zone_id for z in plan.excluded] == ["far"]
        assert "by-dest" in {z.zone_id for z in plan.unexcluded}
        assert request["exclude_polygons"] == far_ring + [marked] == plan.exclude

    def test_the_farther_half_goes_first_past_the_routers_limits(self, two_closures) -> None:
        from core import workzones as core_zones

        plan, request, points = two_closures
        # "far" lies about 1.2 mi (1.9 km) off the line through the stops, "by-dest" on it.
        dropped = core_zones.drop_farthest(request, plan, points)
        assert [z.zone_id for z in dropped] == ["far"]
        assert [z.zone_id for z in plan.excluded] == ["by-dest"]

    def test_a_442_lets_in_only_the_closure_at_the_destination(self, two_closures, monkeypatch):
        """Hunt K2/Q3: before, a closure on the destination's edge let every closure back in."""
        from core import routing
        from core.dedodge import encode_polyline6

        plan, request, points = two_closures
        asked = []

        def route(variant, req, deadline):
            asked.append(list(req.get("exclude_polygons") or []))
            return {"trip": {"legs": [{"shape": ""}]}}, False

        shape = encode_polyline6([(-77.00, 38.9490), (-77.00, 38.9600)])
        located = [{"edges": [{"edge_info": {"shape": shape}}]}]
        monkeypatch.setattr(routing, "_route", route)
        monkeypatch.setattr(routing, "_call", lambda variant, endpoint, payload, deadline: located)
        refusal = routing.RouterRefused(400, 442, "No path could be found for input")
        deadline = routing.Deadline(routing.clock() + 30, 10)
        routing._round_the_closures("standard", request, refusal, plan, points, deadline,
                                    lambda r: r)  # fmt: skip
        (sent,) = asked
        assert sent == plan.rings["far"] + plan.blocked
        assert [z.zone_id for z in plan.excluded] == ["far"]

    def test_a_167_is_asked_again_with_fewer_closures(self, two_closures, monkeypatch) -> None:
        """Hunt Q1: before, Valhalla's 167 (the polygons' perimeter past its cap) was a plain
        no route."""
        from core import routing

        plan, request, points = two_closures
        answers = [routing.RouterRefused(400, 167, "Exceeded max perimeter"), None]
        asked = []

        def route(variant, req, deadline):
            asked.append(len(req.get("exclude_polygons") or []))
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return {"trip": {"legs": [{}]}}, False

        monkeypatch.setattr(routing, "_route", route)
        refusal = routing.RouterRefused(400, 167, "Exceeded max perimeter")
        deadline = routing.Deadline(routing.clock() + 30, 10)
        answer, _ = routing._round_the_closures(
            "standard", request, refusal, plan, points, deadline, lambda r: r
        )
        assert answer["trip"]["legs"] and asked == [2, 1]
        assert plan.excluded == [] and plan.exclude == plan.blocked
        assert routing.EXCLUDE_LIMIT_CODES >= {167, 176}

    def test_a_refusal_for_anything_else_is_no_route(self, two_closures) -> None:
        from core import routing

        plan, request, points = two_closures
        refusal = routing.RouterRefused(400, 171, "No suitable edges")
        deadline = routing.Deadline(routing.clock() + 30, 10)
        with pytest.raises(routing.NoRoute):
            routing._round_the_closures("standard", request, refusal, plan, points, deadline,
                                        lambda r: r)  # fmt: skip


class TestGoRound:
    """Hunt K1: Valhalla lets a left-out edge be the route's first, so a re-plan from a rider
    on a long edge rode straight through the stretch the rider had just marked closed."""

    START = (-77.03, 38.90)
    MARKED = ((-77.03, 38.90 + 30 * M_LAT), (-77.03, 38.90 + 180 * M_LAT))

    def body(self, coordinates) -> dict:
        return {
            "geometry": {"type": "LineString", "coordinates": [list(c) for c in coordinates]},
            "distance_m": 400.0,
            "description": [],
            "description_overview": [],
        }

    def test_a_route_through_the_marked_road_is_planned_again_the_other_way(
        self, monkeypatch
    ) -> None:
        from core import routing

        ahead = self.body([self.START, (-77.03, 38.90 + 400 * M_LAT)])
        back = self.body([self.START, (-77.03, 38.90 - 400 * M_LAT)])
        headings = []
        monkeypatch.setattr(routing, "_plan_onward", lambda *a, **k: ahead)

        def plan(points, preset_name, dials=None, **asked):
            headings.append(dials.heading)
            return back

        monkeypatch.setattr(routing, "plan", plan)
        dials = routing.Dials(blocked=(self.MARKED,), ride_replan=True)
        answer = routing.plan_onward([list(self.START), [-77.02, 38.91]], "standard", dials=dials)
        assert answer is back
        (heading,) = headings
        assert heading == pytest.approx(180.0, abs=1)  # setting off south, away from it

    def test_where_no_way_round_is_found_the_route_says_so(self, monkeypatch) -> None:
        from core import routing

        ahead = self.body([self.START, (-77.03, 38.90 + 400 * M_LAT)])
        monkeypatch.setattr(routing, "_plan_onward", lambda *a, **k: ahead)

        def plan(*a, **k):
            raise routing.NoRoute("none")

        monkeypatch.setattr(routing, "plan", plan)
        dials = routing.Dials(blocked=(self.MARKED,), ride_replan=True)
        answer = routing.plan_onward([list(self.START), [-77.02, 38.91]], "standard", dials=dials)
        (said,) = [e for e in answer["description"] if e["kind"] == "workzone"]
        assert said["severity"] == "red" and "marked closed" in said["text"]

    def test_a_sidepath_beside_the_marked_road_is_not_through_it(self, monkeypatch) -> None:
        """Review of K1: a route 10 m (33 ft) off a marked road is not riding it."""
        from core import routing

        lon = -77.03 + 10 / (111_195 * math.cos(math.radians(38.90)))
        beside = self.body([(lon, 38.90), (lon, 38.90 + 400 * M_LAT)])
        monkeypatch.setattr(routing, "_plan_onward", lambda *a, **k: beside)
        monkeypatch.setattr(routing, "plan", lambda *a, **k: pytest.fail("planned again"))
        dials = routing.Dials(blocked=(self.MARKED,), ride_replan=True)
        answer = routing.plan_onward([list(self.START), [-77.02, 38.91]], "standard", dials=dials)
        assert answer is beside and answer["description"] == []

    def test_a_far_longer_way_the_other_way_is_not_kept(self, monkeypatch) -> None:
        from core import routing

        ahead = self.body([self.START, (-77.03, 38.90 + 400 * M_LAT)])
        back = {**self.body([self.START, (-77.03, 38.90 - 400 * M_LAT)]), "distance_m": 9_000.0}
        monkeypatch.setattr(routing, "_plan_onward", lambda *a, **k: ahead)
        monkeypatch.setattr(routing, "plan", lambda *a, **k: back)
        dials = routing.Dials(blocked=(self.MARKED,), ride_replan=True)
        answer = routing.plan_onward([list(self.START), [-77.02, 38.91]], "standard", dials=dials)
        assert answer is ahead
        assert any(e["kind"] == "workzone" for e in answer["description"])

    def test_a_route_clear_of_the_marked_road_is_left_alone(self, monkeypatch) -> None:
        from core import routing

        clear = self.body([self.START, (-77.03 + 0.004, 38.90)])
        monkeypatch.setattr(routing, "_plan_onward", lambda *a, **k: clear)
        monkeypatch.setattr(routing, "plan", lambda *a, **k: pytest.fail("planned again"))
        dials = routing.Dials(blocked=(self.MARKED,), ride_replan=True)
        assert routing.plan_onward([list(self.START), [-77.02, 38.91]], "standard",
                                   dials=dials) is clear  # fmt: skip


def test_the_riders_marked_roads_are_trimmed_and_fit_together(monkeypatch) -> None:
    """Hunt K4/Q2: a marked road was left out whole, untrimmed, taking the cross streets at
    both ends with it; now it is trimmed as a closure is."""
    from core import workzones as core_zones

    monkeypatch.setattr(core_zones, "crossings", lambda lines, schema=None: [() for _ in lines])
    line = ((-77.03, 38.90), (-77.03, 38.90 + 150 * M_LAT))
    (ring,) = core_zones.blocked_rings([line])
    assert ring == wz.line_ring(line, wz.TRIM_M)
    lats = [lat for _, lat in ring]
    assert min(lats) > 38.90 + 19 * M_LAT and max(lats) < 38.90 + 131 * M_LAT


def test_the_delays_ask_without_each_closures_own_rings(two_closures) -> None:
    """`measure_delays` with closures of more than one ring: the closures' rings are taken out
    together, the rider's roads kept."""
    from core import workzones as core_zones

    plan, request, _points = two_closures
    # Split "far" into two rings, as a point or a crossing would.
    far = next(z for z in plan.excluded if z.zone_id == "far")
    pieces = wz.zone_rings(far, crossings=[150.0])
    assert len(pieces) == 2
    plan.rings["far"] = pieces
    plan.exclude = [r for z in plan.excluded for r in plan.rings_of(z)] + plan.blocked
    request["exclude_polygons"] = list(plan.exclude)
    asked = []

    def reroute(trial):
        asked.append(list(trial.get("exclude_polygons") or []))
        return {"trip": {"legs": [{"shape": ""}], "summary": {"time": 100}}}

    answer = {"trip": {"legs": [{"shape": ""}], "summary": {"time": 120}}}
    core_zones.measure_delays(answer, request, plan, reroute, lambda: 60.0)
    assert asked[0] == plan.blocked
