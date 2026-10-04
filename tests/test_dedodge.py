"""FOLLOWUP-DEDODGE (OWNER-DECISIONS 272, 273): no weaving through side streets beside
a busier road unless it buys a meaningful length of calm (`core.dedodge`).

The Konterra Drive regression is the live routers' own answers, recorded read-only
(tests/data/dedodge_konterra.json). The rest lays routes out on a small synthetic
graph: a road, and side streets that leave it and rejoin it, with the router and the
reading of its routes replaced as in test_refine.
"""

from __future__ import annotations

import dataclasses
import json
import math
from pathlib import Path

import pytest
from test_refine import analysis, context, event
from test_route_api import encode_polyline6 as reference_encode

from core import dedodge, refine, routing
from routemaker.geo import Point, bearing, haversine

DATA = Path(__file__).parent / "data" / "dedodge_konterra.json"
MILE = 1609.344
LON0, LAT0 = -77.0, 38.9
FT = 0.3048


# --- A small graph ------------------------------------------------------------------------


def at(x: float, y: float) -> tuple[float, float]:
    """A point `x` metres east and `y` metres north of the origin, on the micro-degree grid."""
    lon = LON0 + x / (111_194.93 * math.cos(math.radians(LAT0)))
    lat = LAT0 + y / 111_194.93
    return (round(lon, 6), round(lat, 6))


def go(point: tuple[float, float], heading: float, metres: float) -> tuple[float, float]:
    """The point `metres` from `point` on a compass heading."""
    h = math.radians(heading)
    dx = metres * math.sin(h) / (111_194.93 * math.cos(math.radians(LAT0)))
    dy = metres * math.cos(h) / 111_194.93
    return (round(point[0] + dx, 6), round(point[1] + dy, 6))


def key(p) -> tuple[int, int]:
    return (round(p[0] * 1e6), round(p[1] * 1e6))


class Graph:
    """Straight one-segment edges between points: what a trace of a shape reads."""

    def __init__(self) -> None:
        self.edges: dict = {}
        self.tiers: dict[int, str] = {}

    def add(self, a, b, names, way, tier="2", use="road") -> None:
        self.edges[(key(a), key(b))] = {"names": list(names), "way": way, "use": use}
        self.tiers[way] = tier

    def trace(self, shape: str) -> dict:
        points = routing.decode_polyline6(shape)
        edges = []
        for i, (a, b) in enumerate(zip(points, points[1:], strict=False)):
            got = self.edges[(key(a), key(b))]
            heading = bearing(Point(*a), Point(*b))
            edges.append(
                {
                    "way_id": got["way"],
                    "length": haversine(Point(*a), Point(*b)) / 1000.0,
                    "begin_shape_index": i,
                    "end_shape_index": i + 1,
                    "names": got["names"],
                    "use": got["use"],
                    "begin_heading": heading,
                    "end_heading": heading,
                }
            )
        return {"units": "kilometers", "shape": shape, "edges": edges}


def metres_of(points) -> float:
    return sum(haversine(Point(*a), Point(*b)) for a, b in zip(points, points[1:], strict=False))


def leg_of(points, elevation=None) -> dict:
    km = metres_of(points) / 1000.0
    leg = {
        "shape": reference_encode(points),
        "summary": {"length": km, "time": 240.0 * km, "cost": 300.0 * km},
    }
    if elevation is not None:
        leg["elevation"] = elevation
    return leg


def trip_of(*legs: dict) -> dict:
    return {
        "legs": list(legs),
        "summary": {k: sum(leg["summary"][k] for leg in legs) for k in ("length", "time", "cost")},
    }


class Unit:
    """One dodge on a road, laid out on a graph: the road from `start` north 400 m to
    B, a side street (`reach` m out at 60 degrees and `reach` m back at 300, one street,
    so two turns) to D, and the road north on 400 m to E. The route taken is
    A B C D E; the road's own way from B to D (the direct stretch) is `reach` m."""

    def __init__(self, graph: Graph, start, reach=600.0, side="3", main="3", ways=1, cross=False):
        self.reach = reach
        a = start
        self.a = a
        self.b = go(a, 0, 400)
        if cross:
            # Three side streets, four turns: a cross street, the street, a cross street.
            c1 = go(self.b, 90, 50)
            c2 = go(c1, 0, reach)
            self.d = go(c2, 270, 50)
            self.side = [self.b, c1, c2, self.d]
            graph.add(self.b, c1, ["Cross A"], ways + 1, side)
            graph.add(c1, c2, ["Side St"], ways + 2, side)
            graph.add(c2, self.d, ["Cross B"], ways + 3, side)
        else:
            c = go(self.b, 60, reach)
            self.d = go(c, 300, reach)
            self.side = [self.b, c, self.d]
            graph.add(self.b, c, ["Side St"], ways + 1, side)
            graph.add(c, self.d, ["Side St"], ways + 2, side)
        self.e = go(self.d, 0, 400)
        graph.add(a, self.b, ["Main St"], ways, "2")
        graph.add(self.d, self.e, ["Main St"], ways + 4, "2")
        graph.add(self.b, self.d, ["Main St"], ways + 5, main)
        self.dodge_route = [a, *self.side, self.e]
        self.direct = [a, self.b, self.d, self.e]
        # What the router answers between the dodge's ends.
        self.between = [self.b, self.d]


class World:
    """The router, the traces and the readings of one pass, in one place."""

    def __init__(self, monkeypatch, graph: Graph, units=(), events=None) -> None:
        self.graph = graph
        self.calls: list[tuple[str, str, dict]] = []
        self.answers: dict = {}
        self.events = events or (lambda pieces: [])
        self.after_call = lambda: None
        for unit in units:
            self.answers[(key(unit.b), key(unit.d))] = unit.between
        monkeypatch.setattr(routing, "_trace", self.trace)
        monkeypatch.setattr(routing, "_call", self.call)
        monkeypatch.setattr(refine, "analyse", self.analyse)

    def trace(self, variant, costing, shape, deadline, traces=None):
        return self.graph.trace(shape)

    def call(self, variant, endpoint, payload, deadline):
        self.calls.append((variant, endpoint, payload))
        assert endpoint == "route"
        here, there = payload["locations"]
        answer = self.answers[(key((here["lon"], here["lat"])), key((there["lon"], there["lat"])))]
        self.after_call()
        if isinstance(answer, Exception):
            raise answer
        leg = leg_of(answer, elevation=[1.0, 2.0, 3.0])
        return {"trip": {"legs": [leg], "summary": leg["summary"]}}

    def analyse(self, trip, ctx, deadline, with_events=True):
        pieces = []
        for leg in trip["legs"]:
            pieces.extend(routing.pieces_of_trace(self.graph.trace(leg["shape"])))
        tiers = [self.graph.tiers[p.way_id] for p in pieces]
        return dataclasses.replace(
            analysis("r", events=self.events(pieces) if with_events else None),
            pieces=pieces,
            classes=[(t, "none") for t in tiers],
            lts3_m=sum(p.metres for p, t in zip(pieces, tiers, strict=True) if t == "3"),
            lts4_m=sum(p.metres for p, t in zip(pieces, tiers, strict=True) if t in "45"),
            length_m=float(trip["summary"]["length"]) * 1000.0,
        )


def ctx_for(maxcalm: bool = False, **kw) -> refine.Context:
    """A plan's context: below the top of the slider (the 0.25 mi rule) unless `maxcalm`."""
    ctx = context(rate=100.0 if maxcalm else 10.0, maxcalm=maxcalm, **kw)
    ctx.request = {
        "locations": [{"lon": LON0, "lat": LAT0}, {"lon": LON0, "lat": LAT0 + 0.1}],
        "costing": "bicycle",
        "costing_options": {"bicycle": {"use_roads": 0.1}},
        "alternates": 3,
        "exclude_locations": [{"lon": 1.0, "lat": 2.0}],
        "elevation_interval": 30,
        "date_time": {"type": 3, "value": "2026-10-06T12:00"},
    }
    return ctx


def one_dodge(monkeypatch, **kw):
    graph = Graph()
    unit = Unit(graph, at(0, 0), **kw)
    world = World(monkeypatch, graph, [unit])
    elevation = [float(i) for i in range(int(metres_of(unit.dodge_route) / 30) + 1)]
    trip = trip_of(leg_of(unit.dodge_route, elevation=elevation))
    return unit, world, trip


# --- Finding dodges ------------------------------------------------------------------------


def lay(specs, start=None):
    """A trace of a route laid out from `specs`: (names, heading, metres, use)."""
    start = start or at(0, 0)
    points = [start]
    edges = []
    for i, spec in enumerate(specs):
        names, heading, metres = spec[0], spec[1], spec[2]
        use = spec[3] if len(spec) > 3 else "road"
        points.append(go(points[-1], heading, metres))
        edges.append(
            {
                "way_id": 100 + i,
                "length": metres / 1000.0,
                "begin_shape_index": i,
                "end_shape_index": i + 1,
                "names": names,
                "use": use,
                "begin_heading": float(heading) % 360,
                "end_heading": float(heading) % 360,
            }
        )
    trace = {"units": "kilometers", "shape": reference_encode(points), "edges": edges}
    return trace, points


def dodges_of(specs):
    trace, shape = lay(specs)
    return dedodge.find_dodges(dedodge.edges_of(trace, shape), shape)


MAIN = (["Main St"], 0, 400)


class TestFindingDodges:
    def test_a_side_street_that_leaves_a_road_and_rejoins_it_is_a_dodge(self) -> None:
        found = dodges_of([MAIN, (["Side St"], 60, 500), (["Side St"], 300, 500), MAIN])
        assert len(found) == 1
        assert found[0].street == "main st"
        assert found[0].metres == pytest.approx(1000.0, abs=1.0)
        assert [e.names for e in found[0].edges] == [frozenset({"side st"})] * 2

    def test_a_route_that_stays_on_the_road_has_none(self) -> None:
        assert dodges_of([MAIN, MAIN, MAIN]) == []

    def test_a_turn_off_the_road_that_does_not_come_back_is_not_one(self) -> None:
        assert dodges_of([MAIN, (["Side St"], 60, 500), (["Other St"], 120, 500)]) == []

    def test_the_names_are_compared_by_case_and_spacing_alone(self) -> None:
        found = dodges_of([(["Main St"], 0, 400), (["Side St"], 45, 140), (["main  st"], 0, 400)])
        assert len(found) == 1

    def test_a_road_with_two_names_is_one_road_by_either(self) -> None:
        found = dodges_of(
            [
                (["Konterra Drive", "MD 206"], 0, 400),
                (["Side St"], 60, 300),
                (["Side St"], 300, 300),
                (["MD 206"], 0, 400),
            ]
        )
        assert len(found) == 1 and found[0].street == "konterra drive"

    def test_two_dodges_of_one_road_are_two(self) -> None:
        side = [(["Side St"], 60, 300), (["Side St"], 300, 300)]
        found = dodges_of([MAIN, *side, MAIN, *side, MAIN])
        assert len(found) == 2
        assert found[0].after is found[1].before or found[0].after.edges == found[1].before.edges

    def test_unnamed_streets_are_not_a_road_to_leave_or_to_rejoin(self) -> None:
        assert (
            dodges_of([([], 0, 400), (["Side St"], 60, 300), (["Side St"], 300, 300), ([], 0, 400)])
            == []
        )

    def test_a_dodge_is_streets_only(self) -> None:
        """A trail, a crossing or steps between the road's two stretches is a route
        that crosses or joins a trail, not a weave through side streets."""
        for use in ("footway", "cycleway", "path", "pedestrian_crossing", "steps", "ramp"):
            assert (
                dodges_of([MAIN, (["Trail"], 60, 300, use), (["Trail"], 300, 300, use), MAIN]) == []
            ), use
        # A trail among the streets too.
        assert dodges_of([MAIN, (["Side St"], 60, 300), (["Path"], 300, 300, "path"), MAIN]) == []

    @pytest.mark.parametrize(
        "use",
        ["road", "living_street", "service_road", "alley", "culdesac", "turn_channel", "driveway"],
    )
    def test_these_are_streets(self, use) -> None:
        assert (
            len(dodges_of([MAIN, (["Side"], 60, 300, use), (["Side"], 300, 300, use), MAIN])) == 1
        )

    @pytest.mark.parametrize("use", ["cycleway", "footway", "path", "service_road", "ramp"])
    def test_the_road_a_dodge_leaves_is_a_road(self, use) -> None:
        """A trail named like a road, or a service road, is not a busier road."""
        road = (["Main St"], 0, 400, use)
        assert dodges_of([road, (["Side"], 60, 300), (["Side"], 300, 300), road]) == []

    def test_a_stub_is_not_a_road(self) -> None:
        """The road must be MAIN_MIN_M long on each side."""
        side = [(["Side"], 60, 300), (["Side"], 300, 300)]
        assert dedodge.MAIN_MIN_M == 30.0
        assert dodges_of([(["Main St"], 0, 29), *side, MAIN]) == []
        assert dodges_of([MAIN, *side, (["Main St"], 0, 29)]) == []
        assert len(dodges_of([(["Main St"], 0, 31), *side, (["Main St"], 0, 31)])) == 1
        assert len(dodges_of([(["Main St"], 0, 250), *side, (["Main St"], 0, 250)])) == 1

    def test_a_dodge_is_at_most_about_a_mile(self) -> None:
        def length(metres):
            half = metres / 2
            return [MAIN, (["Side"], 60, half), (["Side"], 300, half), MAIN]

        assert len(dodges_of(length(dedodge.DODGE_MAX_M - 5))) == 1
        assert len(dodges_of(length(dedodge.DODGE_MAX_M + 20))) == 0

    def test_the_same_road_must_go_on_in_the_direction_it_was_left(self) -> None:
        def rejoin(heading):
            return dodges_of(
                [MAIN, (["Side"], 60, 300), (["Side"], 300, 300), (["Main St"], heading, 400)]
            )

        assert len(rejoin(0)) == 1
        assert len(rejoin(dedodge.SAME_ROAD_HEADING_DEG - 5)) == 1
        assert rejoin(dedodge.SAME_ROAD_HEADING_DEG + 15) == []
        # Back the way it came: a turn round, not a dodge.
        assert rejoin(180) == []

    def test_a_rejoin_behind_the_start_is_not_a_dodge(self) -> None:
        """A block that comes back to the road behind where it was left."""
        assert (
            dodges_of(
                [MAIN, (["Side"], 90, 100), (["Side"], 180, 100), (["Main St"], 270, 100), MAIN]
            )
            == []
        )

    def test_a_road_that_changes_name_and_runs_on_is_the_same_corridor(self) -> None:
        def rejoin(heading, offset):
            """Main St, a side street that comes back to a differently named road
            `offset` m to the side of the first road's line, heading `heading`."""
            shift = [(["Side"], 90, offset), (["Side"], 0, 300)]
            trace, shape = lay([MAIN, *shift, (["Oak St"], heading, 400)])
            return dedodge.find_dodges(dedodge.edges_of(trace, shape), shape)

        assert len(rejoin(0, 100)) == 1
        assert len(rejoin(0, 140)) == 1
        assert rejoin(0, 170) == [] and rejoin(0, 400) == []
        assert len(rejoin(30, 100)) == 1
        assert rejoin(45, 100) == [] and rejoin(90, 100) == []

    def test_the_same_road_comes_before_one_that_runs_on_beside_it(self) -> None:
        """Konterra Drive, Virginia Manor Road and Konterra Drive: Virginia Manor Road
        runs on in Konterra Drive's direction, but the dodge is the whole of the way
        to where Konterra Drive itself comes back."""
        found = dodges_of(
            [
                (["Konterra Drive"], 0, 400),
                ([], 90, 30),
                (["Virginia Manor Road"], 0, 400),
                (["Konterra Drive"], 0, 400),
            ]
        )
        assert len(found) == 1
        assert found[0].after.names == frozenset({"konterra drive"})
        assert found[0].metres == pytest.approx(430.0, abs=1.0)

    def test_without_headings_only_the_name_decides(self) -> None:
        trace, shape = lay([MAIN, (["Side"], 60, 300), (["Side"], 300, 300), MAIN])
        for edge in trace["edges"]:
            del edge["begin_heading"], edge["end_heading"]
        assert len(dedodge.find_dodges(dedodge.edges_of(trace, shape), shape)) == 1
        trace, shape = lay([MAIN, (["Side"], 60, 300), (["Side"], 300, 300), (["Oak St"], 0, 400)])
        for edge in trace["edges"]:
            del edge["begin_heading"], edge["end_heading"]
        assert dedodge.find_dodges(dedodge.edges_of(trace, shape), shape) == []

    def test_a_trace_without_use_has_no_dodges(self) -> None:
        trace, shape = lay([MAIN, (["Side"], 60, 300), (["Side"], 300, 300), MAIN])
        for edge in trace["edges"]:
            del edge["use"]
        assert dedodge.find_dodges(dedodge.edges_of(trace, shape), shape) == []


class TestRoads:
    def e(self, names, use="road", way=1):
        return dedodge.Edge(way, frozenset(names), 100.0, use, 0, 1, 0.0, 0.0)

    def test_edges_that_share_a_name_are_one_road(self) -> None:
        got = dedodge.stretches_of([self.e({"a", "b"}), self.e({"b"}), self.e({"b", "c"})])
        assert len(got) == 1 and got[0].names == frozenset({"a", "b", "c"})
        assert got[0].metres == 300.0

    def test_edges_that_share_none_are_two(self) -> None:
        assert len(dedodge.stretches_of([self.e({"a"}), self.e({"b"})])) == 2

    def test_an_unnamed_edge_is_a_road_of_its_own(self) -> None:
        got = dedodge.stretches_of([self.e({"a"}), self.e(set()), self.e(set()), self.e({"a"})])
        assert [len(s.edges) for s in got] == [1, 1, 1, 1]

    def test_a_road_is_all_road(self) -> None:
        mixed = dedodge.Stretch((self.e({"a"}), self.e({"a"}, "path")), frozenset({"a"}), 200.0)
        assert not dedodge.is_road(mixed)
        assert dedodge.is_road(dedodge.Stretch((self.e({"a"}),), frozenset({"a"}), 100.0))
        assert not dedodge.is_road(dedodge.Stretch((self.e(set()),), frozenset(), 100.0))

    def test_streets_are_all_streets(self) -> None:
        mixed = dedodge.Stretch((self.e({"a"}), self.e({"a"}, "path")), frozenset({"a"}), 200.0)
        assert not dedodge.is_streets(mixed)
        assert dedodge.is_streets(dedodge.Stretch((self.e({"a"}, "alley"),), frozenset({"a"}), 1.0))

    def test_a_rejoin_at_the_point_left_is_not_ahead(self) -> None:
        trace, shape = lay([MAIN, MAIN])
        e0, e1 = dedodge.edges_of(trace, shape)
        before = dedodge.Stretch((e0,), e0.names, 400.0)
        after = dedodge.Stretch((e1,), e1.names, 400.0)
        # The second begins where the first ends: a stretch on, not a rejoin ahead of anything.
        assert (e0.end, e1.begin) == (1, 1)
        assert dedodge.corridor_kind(before, after, shape) is None
        assert dedodge.corridor_kind(after, before, shape) is None


class TestTheEdges:
    def test_they_are_the_edges_the_pieces_are_cut_from(self) -> None:
        """Edges that `routing.pieces_of_trace` skips are skipped here too."""
        trace, shape = lay([MAIN, (["Side"], 60, 300), MAIN])
        trace["edges"].insert(1, {**trace["edges"][1], "length": 0.0})
        trace["edges"].insert(2, {**trace["edges"][1], "length": 0.1, "end_shape_index": 99})
        trace["edges"].append({**trace["edges"][1], "length": 0.1, "begin_shape_index": None})
        edges = dedodge.edges_of(trace, shape)
        pieces = routing.pieces_of_trace(trace)
        assert len(edges) == 3
        assert sum(e.metres for e in edges) == pytest.approx(sum(p.metres for p in pieces))

    def test_a_trace_in_miles_is_read_in_metres(self) -> None:
        trace, shape = lay([MAIN])
        trace["units"] = "miles"
        trace["edges"][0]["length"] = 0.25
        assert dedodge.edges_of(trace, shape)[0].metres == pytest.approx(0.25 * MILE)

    def test_headings_and_names_are_kept(self) -> None:
        trace, shape = lay([(["Main St", "MD 1"], 90, 400)])
        (edge,) = dedodge.edges_of(trace, shape)
        assert edge.names == frozenset({"main st", "md 1"})
        assert edge.heading_in == edge.heading_out == 90.0
        assert edge.use == "road" and (edge.begin, edge.end) == (0, 1)


# --- The rule --------------------------------------------------------------------------------


def chain(length: float, turns: int) -> list[routing.Piece]:
    """A route of `length` metres with `turns` turns: a piece to a street, each at right
    angles to the one before."""
    n = turns + 1
    return [
        routing.Piece(
            i + 1,
            LON0,
            LAT0,
            length / n,
            names=(f"street {i}",),
            heading_in=0.0 if i % 2 == 0 else 90.0,
            heading_out=0.0 if i % 2 == 0 else 90.0,
        )
        for i in range(n)
    ]


def read(length=1000.0, turns=0, lts3=0.0, lts4=0.0, red=(), orange=(), events=True, effort=None):
    evs = [event(100.0 + 10 * i, c) for i, c in enumerate([*red, *orange])] if events else None
    return dataclasses.replace(
        analysis("r", events=evs),
        pieces=chain(length, turns),
        lts3_m=lts3,
        lts4_m=lts4,
        length_m=length,
        effort_m=length if effort is None else effort,
    )


# Below the top of the slider (the 0.25 mi rule), and at the top (the tie step).
CTX = context(rate=10.0)
TOP = context(rate=100.0, maxcalm=True)


@pytest.fixture
def quarter_mile_rule(monkeypatch):
    """272's quarter mile + turn charge, which `TIE_RULE_ALL_PRESETS` off restores
    (OWNER-DECISIONS 298(1) put every preset on the tie step)."""
    monkeypatch.setattr(dedodge, "TIE_RULE_ALL_PRESETS", False)


def verdict(dodge, direct, ctx=CTX, original=None):
    return dedodge.judge(dodge, direct, ctx, original)


class TestTurns:
    def test_a_turn_is_a_change_of_street_and_of_heading(self) -> None:
        assert dedodge.turn_count(chain(1000.0, 0)) == 0
        assert dedodge.turn_count(chain(1000.0, 3)) == 3

    def test_a_split_way_is_not_a_turn_whatever_its_name(self) -> None:
        a = routing.Piece(1, LON0, LAT0, 100.0, names=("A",), heading_in=0.0, heading_out=0.0)
        b = routing.Piece(1, LON0, LAT0, 100.0, names=("B",), heading_in=90.0, heading_out=90.0)
        assert dedodge.turn_count([a, b]) == 0

    def test_a_bend_in_one_street_is_not_a_turn(self) -> None:
        a = routing.Piece(1, LON0, LAT0, 100.0, names=("Main St",), heading_in=0.0, heading_out=0.0)
        b = routing.Piece(
            2, LON0, LAT0, 100.0, names=("main st",), heading_in=90.0, heading_out=90.0
        )
        assert dedodge.turn_count([a, b]) == 0

    def test_a_way_split_in_one_straight_road_is_not_a_turn(self) -> None:
        a = routing.Piece(1, LON0, LAT0, 100.0, names=("A",), heading_in=0.0, heading_out=0.0)
        b = routing.Piece(2, LON0, LAT0, 100.0, names=("B",), heading_in=10.0, heading_out=10.0)
        assert dedodge.turn_count([a, b]) == 0

    def test_a_change_of_heading_is_a_turn_from_the_turn_angle(self) -> None:
        def turned(degrees):
            a = routing.Piece(1, LON0, LAT0, 100.0, names=("A",), heading_in=0.0, heading_out=0.0)
            b = routing.Piece(
                2, LON0, LAT0, 100.0, names=("B",), heading_in=degrees, heading_out=degrees
            )
            return dedodge.turn_count([a, b])

        assert turned(dedodge.TURN_DEGREES - 1) == 0
        assert turned(dedodge.TURN_DEGREES) == 1
        assert turned(360 - dedodge.TURN_DEGREES) == 1
        assert turned(360 - dedodge.TURN_DEGREES + 1) == 0

    def test_without_headings_each_change_of_street_is_a_turn(self) -> None:
        a = routing.Piece(1, LON0, LAT0, 100.0, names=("A",))
        b = routing.Piece(2, LON0, LAT0, 100.0, names=("B",))
        c = routing.Piece(3, LON0, LAT0, 100.0, names=("B",))
        assert dedodge.turn_count([a, b, c]) == 1


class TestWhatItMustAvoid:
    def test_a_quarter_of_a_mile(self) -> None:
        assert dedodge.MIN_AVOIDED_M == pytest.approx(402.336)
        assert dedodge.needed_m(0) == dedodge.needed_m(2) == pytest.approx(0.25 * MILE)

    def test_each_turn_past_the_two_every_dodge_has_adds_a_charge(self) -> None:
        assert dedodge.BASE_TURNS == 2 and dedodge.TURN_CHARGE_M == 80.0
        assert dedodge.needed_m(3) == pytest.approx(0.25 * MILE + 80.0)
        assert dedodge.needed_m(6) == pytest.approx(0.25 * MILE + 320.0)

    def test_fewer_turns_than_a_dodge_must_have_ask_less_of_nothing(self) -> None:
        assert dedodge.needed_m(-4) == dedodge.needed_m(1) == pytest.approx(0.25 * MILE)

    def test_the_stress_avoided_is_the_figures_the_main_road_has_more_of(self) -> None:
        dodge = read(lts3=100.0, lts4=10.0)
        direct = read(lts3=400.0, lts4=60.0)
        assert dedodge.avoided_m(dodge, direct) == pytest.approx(300.0 + 50.0)

    def test_a_calmer_main_road_is_avoided_nothing(self) -> None:
        assert dedodge.avoided_m(read(lts3=400.0, lts4=50.0), read(lts3=0.0, lts4=0.0)) == 0.0
        assert dedodge.avoided_m(read(lts3=400.0), read(lts3=0.0, lts4=50.0)) == pytest.approx(50.0)

    def test_the_cost_of_junctions_counts_as_stress(self) -> None:
        """A red junction as LTS 4 and an orange one as LTS 3, in their own cost."""
        red = 3000.0
        orange = 1500.0
        assert dedodge.avoided_m(read(), read(red=[red])) == pytest.approx(red * FT)
        assert dedodge.avoided_m(read(), read(orange=[orange])) == pytest.approx(orange * FT)


class TestTheVerdict:
    def test_a_dodge_that_avoids_nothing_is_removed(self) -> None:
        got = verdict(read(length=1500.0, turns=2, lts3=900.0), read(length=1000.0, lts3=900.0))
        assert got.remove and got.reason == "no_stress_gain"
        assert got.avoided_m == 0.0 and got.turns_saved == 2 and got.extra_m == pytest.approx(500.0)

    @pytest.mark.usefixtures("quarter_mile_rule")
    def test_it_is_kept_if_it_avoids_a_quarter_of_a_mile(self) -> None:
        need = dedodge.MIN_AVOIDED_M
        kept = verdict(read(turns=2, lts3=0.0), read(lts3=need))
        assert not kept.remove and kept.reason == "stress", "exactly enough is enough"
        gone = verdict(read(turns=2, lts3=0.0), read(lts3=need - 1.0))
        assert gone.remove

    def test_what_it_avoids_may_be_lts3_or_lts4(self) -> None:
        assert not verdict(read(turns=2), read(lts4=dedodge.MIN_AVOIDED_M)).remove
        # LTS 4 avoided is kept whatever its amount (below).
        assert not verdict(read(turns=2), read(lts4=50.0)).remove

    @pytest.mark.usefixtures("quarter_mile_rule")
    def test_each_extra_turn_raises_what_it_must_avoid(self) -> None:
        base = dedodge.MIN_AVOIDED_M
        # Two turns: a quarter of a mile is enough; four: 160 m more.
        assert not verdict(read(turns=2), read(lts3=base)).remove
        assert verdict(read(turns=4), read(lts3=base + 159.0)).remove
        assert not verdict(read(turns=4), read(lts3=base + 160.0)).remove
        assert not verdict(read(turns=4), read(lts3=base + 161.0)).remove

    @pytest.mark.usefixtures("quarter_mile_rule")
    def test_a_main_road_with_more_turns_charges_nothing(self) -> None:
        got = verdict(read(turns=0), read(turns=4, lts3=dedodge.MIN_AVOIDED_M - 1.0))
        assert got.remove and got.turns_saved == -4
        assert not verdict(read(turns=0), read(turns=4, lts3=dedodge.MIN_AVOIDED_M)).remove

    def test_it_is_never_removed_where_the_top_figure_rises(self) -> None:
        """The order of 258-262 and the hold of 250: LTS 4, Avoid and red junction cost
        never go up, whatever else is gained."""
        top = dedodge.TOP_SLACK_M
        assert top == refine.LTS4_SLACK_M == 1.0
        got = verdict(read(turns=2, lts4=0.0), read(lts4=top + 1.0))
        assert not got.remove and got.reason == "top"
        # Within the hold's own slack of a metre, it is the stress that decides.
        assert verdict(read(turns=2, lts4=0.0), read(lts4=top)).remove

    def test_the_top_figure_includes_red_junctions(self) -> None:
        got = verdict(read(turns=2), read(red=[3000.0]))
        assert not got.remove and got.reason == "top"

    def test_an_orange_junction_is_second_figure_stress(self) -> None:
        """Avoided at the second figure, not the top: kept by its cost, not by the guard."""
        small = verdict(read(turns=2), read(orange=[500.0]))
        assert small.remove
        big = verdict(read(turns=2), read(orange=[1500.0]))
        assert not big.remove and big.reason == "stress"

    def test_it_is_never_removed_for_a_longer_route(self) -> None:
        """The target distance and the ceiling only get easier (267-271)."""
        longer = verdict(read(length=1000.0, turns=2), read(length=1000.0 + 5.0))
        assert not longer.remove and longer.reason == "longer"
        assert verdict(read(length=1000.0, turns=2), read(length=1000.0 + 0.5)).remove
        assert verdict(read(length=1000.0, turns=2), read(length=900.0)).remove

    def test_it_is_never_removed_for_a_worse_blended_distance(self) -> None:
        ctx = context(rate=10.0, maxcalm=True)
        ctx.hills_weight = 1.0
        steeper = verdict(
            read(length=1000.0, turns=2, effort=1000.0), read(length=900.0, effort=1100.0), ctx
        )
        assert not steeper.remove and steeper.reason == "hills"
        ctx.hills_weight = 0.0
        assert verdict(
            read(length=1000.0, turns=2, effort=1000.0), read(length=900.0, effort=1100.0), ctx
        ).remove

    def test_junctions_read_for_one_and_not_the_other_cannot_be_weighed(self) -> None:
        a = verdict(read(turns=2, events=False), read())
        b = verdict(read(turns=2), read(events=False))
        assert not a.remove and a.reason == "events"
        assert not b.remove and b.reason == "events"
        assert verdict(read(turns=2, events=False), read(events=False)).remove

    @pytest.mark.usefixtures("quarter_mile_rule")
    def test_the_figures_are_reported(self) -> None:
        got = verdict(read(length=1300.0, turns=3, lts3=100.0), read(length=1000.0, lts3=500.0))
        assert got.avoided_m == pytest.approx(400.0)
        assert got.needed_m == pytest.approx(dedodge.MIN_AVOIDED_M + 80.0)
        assert got.turns_saved == 3 and got.extra_m == pytest.approx(300.0)


# --- Splicing ----------------------------------------------------------------------------------


class TestEncoding:
    def test_it_is_the_inverse_of_decoding(self) -> None:
        points = [
            (-77.123456, 38.654321),
            (-77.0, 38.9),
            (-76.999999, 38.900001),
            (0.0, 0.0),
            (179.9, -85.5),
        ]
        assert routing.decode_polyline6(dedodge.encode_polyline6(points)) == pytest.approx(points)

    def test_it_agrees_with_an_independent_encoder(self) -> None:
        points = [(-77.05, 38.9), (-77.04, 38.9), (-77.035, 38.9004), (-77.03, 38.8996)]
        assert dedodge.encode_polyline6(points) == reference_encode(points)

    def test_an_empty_shape_is_empty(self) -> None:
        assert dedodge.encode_polyline6([]) == ""


def dodge_of(trace, shape):
    edges = dedodge.edges_of(trace, shape)
    return edges, dedodge.find_dodges(edges, shape)[0]


class TestSplicing:
    def setup_method(self) -> None:
        graph = Graph()
        self.unit = Unit(graph, at(0, 0), reach=600.0)
        self.graph = graph
        self.elevation = [float(i) for i in range(int(metres_of(self.unit.dodge_route) / 30) + 1)]
        self.leg = leg_of(self.unit.dodge_route, elevation=self.elevation)
        self.trace = graph.trace(self.leg["shape"])
        self.shape = routing.decode_polyline6(self.leg["shape"])
        self.edges, self.dodge = dodge_of(self.trace, self.shape)
        self.sub = leg_of(self.unit.between, elevation=[10.0, 11.0, 12.0])

    def splice(self, sub=None):
        return dedodge.splice_leg(
            self.leg, self.shape, self.edges, self.dodge, sub or self.sub, 30.0
        )

    def test_the_dodge_is_cut_out_and_the_router_s_stretch_put_in(self) -> None:
        new = self.splice()
        got = routing.decode_polyline6(new["shape"])
        assert got == pytest.approx([self.unit.a, self.unit.b, self.unit.d, self.unit.e])

    def test_the_length_is_the_legs_less_the_dodges_plus_the_stretchs(self) -> None:
        new = self.splice()
        want = (metres_of(self.unit.direct)) / 1000.0
        assert new["summary"]["length"] == pytest.approx(want, rel=1e-3)
        cut = self.dodge.metres / 1000.0
        assert new["summary"]["length"] == pytest.approx(
            self.leg["summary"]["length"] - cut + self.sub["summary"]["length"]
        )

    def test_time_and_cost_lose_the_dodges_share_of_the_leg(self) -> None:
        new = self.splice()
        share = self.dodge.metres / sum(e.metres for e in self.edges)
        for key_ in ("time", "cost"):
            assert new["summary"][key_] == pytest.approx(
                self.leg["summary"][key_] * (1 - share) + self.sub["summary"][key_]
            )

    def test_the_elevation_is_the_legs_around_the_routers(self) -> None:
        new = self.splice()
        start = round(400.0 / 30.0)
        end = round((400.0 + self.dodge.metres) / 30.0)
        assert new["elevation"] == [
            *self.elevation[:start],
            10.0,
            11.0,
            12.0,
            *self.elevation[end + 1 :],
        ], "the rejoin's sample is the stretch's last, not repeated (re-check N1)"

    def test_a_stretch_without_elevation_keeps_the_legs(self) -> None:
        """Review r0: the leg's heights are kept, the router's stretch drawn in a straight
        line between the heights where the dodge left and came back."""
        no_sub = {k: v for k, v in self.sub.items() if k != "elevation"}
        new = self.splice(no_sub)
        start = round(400.0 / 30.0)
        end = round((400.0 + self.dodge.metres) / 30.0)
        n = round(self.sub["summary"]["length"] * 1000.0 / 30.0) + 1
        middle = new["elevation"][start : start + n]
        assert new["elevation"][:start] == self.elevation[:start]
        assert new["elevation"][start + n :] == self.elevation[end + 1 :], (
            "no repeated sample at the rejoin (N1)"
        )
        assert middle[0] == self.elevation[start] and middle[-1] == self.elevation[end]
        assert middle == pytest.approx(sorted(middle)) and len(middle) == n

    def test_heights_unknown_at_the_ends_are_unknown(self) -> None:
        assert dedodge._between([None, None, None], 0, 2, 0.06, 30.0) == [None] * 3
        assert dedodge._between([5.0, None, None], 0, 2, 0.06, 30.0) == [5.0] * 3
        assert dedodge._between([1.0, 2.0, 3.0], 0, 9, 0.0, 30.0) == [1.0, 3.0]

    def test_without_the_legs_elevation_it_has_none(self) -> None:
        leg = {k: v for k, v in self.leg.items() if k != "elevation"}
        new = dedodge.splice_leg(leg, self.shape, self.edges, self.dodge, self.sub, 30.0)
        assert "elevation" not in new

    def test_other_leg_fields_are_kept(self) -> None:
        self.leg["elevation_interval"] = 30
        assert self.splice()["elevation_interval"] == 30

    def test_the_input_is_not_changed(self) -> None:
        before = json.dumps(self.leg)
        self.splice()
        assert json.dumps(self.leg) == before

    def test_a_stretch_that_does_not_start_where_the_dodge_does_is_refused(self) -> None:
        far = leg_of([go(self.unit.b, 90, dedodge.SNAP_M + 20), self.unit.d])
        assert self.splice(far) is None

    def test_a_stretch_that_does_not_end_where_the_dodge_does_is_refused(self) -> None:
        far = leg_of([self.unit.b, go(self.unit.d, 90, dedodge.SNAP_M + 20)])
        assert self.splice(far) is None

    def test_ends_within_the_snap_are_taken(self) -> None:
        near = leg_of(
            [go(self.unit.b, 90, dedodge.SNAP_M - 5), go(self.unit.d, 90, dedodge.SNAP_M - 5)]
        )
        assert self.splice(near) is not None

    def test_a_stretch_of_one_point_is_refused(self) -> None:
        assert self.splice({"shape": reference_encode([self.unit.b]), "summary": {}}) is None
        assert self.splice({"summary": {}}) is None


# --- The pass ------------------------------------------------------------------------------------


class TestThePass:
    def test_a_dodge_that_buys_nothing_is_replaced_by_the_main_road(self, monkeypatch) -> None:
        unit, world, trip = one_dodge(monkeypatch, side="3", main="3")
        ctx = ctx_for()
        new, info = dedodge.apply(trip, ctx)
        assert routing.decode_polyline6(new["legs"][0]["shape"]) == pytest.approx(unit.direct)
        assert (info["found"], info["removed"], info["kept"], info["checked"]) == (1, 1, 0, 1)
        assert info["limited"] is None
        (item,) = info["items"]
        assert item["action"] == "removed" and item["reason"] == "no_stress_gain"
        assert item["street"] == "main st" and item["via"] == ["side st"]
        assert item["length_m"] == pytest.approx(2 * unit.reach, abs=1.5)
        assert item["avoided_m"] == 0.0 and item["extra_m"] == pytest.approx(unit.reach, abs=1.5)

    def test_the_trip_s_summary_follows(self, monkeypatch) -> None:
        unit, world, trip = one_dodge(monkeypatch)
        new, _ = dedodge.apply(trip, ctx_for())
        want = metres_of(unit.direct) / 1000.0
        assert new["summary"]["length"] == pytest.approx(want, rel=2e-3)
        assert new["legs"][0]["summary"]["length"] == new["summary"]["length"]
        assert new["summary"]["length"] < trip["summary"]["length"]

    def test_the_trip_given_is_not_changed(self, monkeypatch) -> None:
        unit, world, trip = one_dodge(monkeypatch)
        before = json.dumps(trip)
        dedodge.apply(trip, ctx_for())
        assert json.dumps(trip) == before

    @pytest.mark.usefixtures("quarter_mile_rule")
    def test_a_dodge_that_avoids_a_quarter_of_a_mile_is_kept(self, monkeypatch) -> None:
        # The main road's 700 m is LTS 3, the side street's LTS 1.
        unit, world, trip = one_dodge(monkeypatch, reach=700.0, side="1", main="3")
        new, info = dedodge.apply(trip, ctx_for())
        assert new is trip
        (item,) = info["items"]
        assert item["action"] == "kept" and item["reason"] == "stress"
        assert item["avoided_m"] == pytest.approx(700.0, abs=1.5)
        assert (info["removed"], info["kept"]) == (0, 1)

    @pytest.mark.usefixtures("quarter_mile_rule")
    def test_one_metre_short_of_enough_is_removed(self, monkeypatch) -> None:
        unit, world, trip = one_dodge(
            monkeypatch, reach=dedodge.MIN_AVOIDED_M - 5.0, side="1", main="3"
        )
        new, info = dedodge.apply(trip, ctx_for())
        assert info["removed"] == 1 and new is not trip
        unit, world, trip = one_dodge(
            monkeypatch, reach=dedodge.MIN_AVOIDED_M + 5.0, side="1", main="3"
        )
        new, info = dedodge.apply(trip, ctx_for())
        assert info["kept"] == 1 and new is trip

    @pytest.mark.usefixtures("quarter_mile_rule")
    def test_four_turns_ask_for_more(self, monkeypatch) -> None:
        """Three side streets are four turns: 160 m more than a quarter of a mile."""
        reach = dedodge.MIN_AVOIDED_M + 60.0
        unit, world, trip = one_dodge(monkeypatch, reach=reach, side="1", main="3", cross=True)
        new, info = dedodge.apply(trip, ctx_for())
        assert info["items"][0]["turns_saved"] == 4
        assert info["items"][0]["needed_m"] == pytest.approx(dedodge.MIN_AVOIDED_M + 160.0, abs=0.1)
        assert info["removed"] == 1
        unit, world, trip = one_dodge(
            monkeypatch, reach=dedodge.MIN_AVOIDED_M + 200.0, side="1", main="3", cross=True
        )
        new, info = dedodge.apply(trip, ctx_for())
        assert info["kept"] == 1

    def test_a_dodge_that_avoids_lts4_is_kept_however_short(self, monkeypatch) -> None:
        unit, world, trip = one_dodge(monkeypatch, reach=120.0, side="3", main="4")
        new, info = dedodge.apply(trip, ctx_for())
        assert new is trip
        assert info["items"][0]["reason"] == "top" and info["kept"] == 1

    def test_it_applies_on_every_ride_not_just_the_top_of_the_slider(self, monkeypatch) -> None:
        for kw in ({}, {"rate": 10.0}, {"maxcalm": True, "rate": 100.0}, {"group": True}):
            unit, world, trip = one_dodge(monkeypatch)
            ctx = context(**{"rate": 0.0, **kw})
            ctx.request = ctx_for().request
            new, info = dedodge.apply(trip, ctx)
            assert info["removed"] == 1, kw

    def test_the_request_is_the_plans_own_between_the_dodges_ends(self, monkeypatch) -> None:
        unit, world, trip = one_dodge(monkeypatch)
        ctx = ctx_for()
        ctx.variant = "no_trail"
        before = json.dumps(ctx.request)
        dedodge.apply(trip, ctx)
        ((variant, endpoint, payload),) = world.calls
        assert (variant, endpoint) == ("no_trail", "route")
        assert json.dumps(ctx.request) == before, "the plan's request is not changed"
        assert payload["costing"] == "bicycle"
        assert payload["costing_options"] == ctx.request["costing_options"]
        assert payload["date_time"] == ctx.request["date_time"]
        assert payload["elevation_interval"] == 30
        assert "alternates" not in payload
        here, there = payload["locations"]
        assert (here["lon"], here["lat"]) == pytest.approx(unit.b)
        assert (there["lon"], there["lat"]) == pytest.approx(unit.d)
        assert here["type"] == there["type"] == "break"
        assert here["heading"] == round(bearing(Point(*unit.a), Point(*unit.b))) % 360
        assert there["heading"] == round(bearing(Point(*unit.d), Point(*unit.e))) % 360

    def test_where_no_path_is_found_facing_the_way_it_goes_it_is_asked_without(
        self, monkeypatch
    ) -> None:
        unit, world, trip = one_dodge(monkeypatch)
        real = world.call

        def call(variant, endpoint, payload, deadline):
            if "heading" in payload["locations"][0]:
                world.calls.append((variant, endpoint, payload))
                raise routing.RouterRefused(400, 442, "no path")
            return real(variant, endpoint, payload, deadline)

        monkeypatch.setattr(routing, "_call", call)
        new, info = dedodge.apply(trip, ctx_for())
        assert info["removed"] == 1
        assert len(world.calls) == 2
        assert all("heading" not in loc for loc in world.calls[-1][2]["locations"])
        assert world.calls[-1][2]["exclude_locations"] == world.calls[0][2]["exclude_locations"]

    def test_refused_either_way_keeps_the_dodge(self, monkeypatch) -> None:
        unit, world, trip = one_dodge(monkeypatch)
        world.answers[(key(unit.b), key(unit.d))] = routing.RouterRefused(400, 442, "no path")
        new, info = dedodge.apply(trip, ctx_for())
        assert new is trip and len(world.calls) == 2
        assert info["items"][0]["reason"] == "no_route"

    def test_each_street_of_the_dodge_is_excluded_and_the_road_is_not(self, monkeypatch) -> None:
        unit, world, trip = one_dodge(monkeypatch)
        dedodge.apply(trip, ctx_for())
        (_v, _e, payload) = world.calls[0]
        excluded = [(p["lon"], p["lat"]) for p in payload["exclude_locations"]]
        assert (1.0, 2.0) not in excluded, "the plan's own exclusions are not carried"
        want = [
            ((unit.side[0][0] + unit.side[1][0]) / 2, (unit.side[0][1] + unit.side[1][1]) / 2),
            ((unit.side[1][0] + unit.side[2][0]) / 2, (unit.side[1][1] + unit.side[2][1]) / 2),
        ]
        assert excluded == pytest.approx(want, abs=2e-6)

    def test_a_short_edge_is_not_excluded_for_its_nodes_sake(self, monkeypatch) -> None:
        graph = Graph()
        unit = Unit(graph, at(0, 0), cross=True)
        # The cross streets are 50 m; shorten the second to 3 m.
        edges, dodge = dodge_of(graph.trace(reference_encode(unit.dodge_route)), unit.dodge_route)
        short = dataclasses.replace(dodge.off[0].edges[0], metres=5.0)
        dodge2 = dataclasses.replace(
            dodge, off=(dataclasses.replace(dodge.off[0], edges=(short,)), *dodge.off[1:])
        )
        got = dedodge.excludes_of(dodge2, unit.dodge_route)
        assert len(got) == len(dodge.edges) - 1

    def test_the_exclusions_are_bounded(self, monkeypatch) -> None:
        trace, shape = lay([MAIN, *[(["Side"], 60 if i % 2 else 300, 10) for i in range(60)], MAIN])
        # A zig-zag of 60 short streets: still one dodge.
        edges = dedodge.edges_of(trace, shape)
        (dodge,) = dedodge.find_dodges(edges, shape)
        assert len(dodge.edges) == 60
        assert len(dedodge.excludes_of(dodge, shape)) == dedodge.MAX_EXCLUDES == 40

    def test_no_route_without_the_dodge_keeps_it(self, monkeypatch) -> None:
        unit, world, trip = one_dodge(monkeypatch)
        world.answers[(key(unit.b), key(unit.d))] = routing.RouterRefused(400, 442, "no path")
        new, info = dedodge.apply(trip, ctx_for())
        assert new is trip
        assert info["items"][0]["action"] == "kept" and info["items"][0]["reason"] == "no_route"

    def test_an_answer_of_several_legs_is_not_a_stretch(self, monkeypatch) -> None:
        unit, world, trip = one_dodge(monkeypatch)
        leg = leg_of(unit.between)
        monkeypatch.setattr(
            routing, "_call", lambda *a: {"trip": {"legs": [leg, leg], "summary": leg["summary"]}}
        )
        new, info = dedodge.apply(trip, ctx_for())
        assert new is trip and info["items"][0]["reason"] == "no_route"

    def test_a_stretch_that_does_not_join_the_dodges_ends_keeps_it(self, monkeypatch) -> None:
        unit, world, trip = one_dodge(monkeypatch)
        world.graph.add(go(unit.b, 90, 200), unit.d, ["Main St"], 90)
        world.answers[(key(unit.b), key(unit.d))] = [go(unit.b, 90, 200), unit.d]
        new, info = dedodge.apply(trip, ctx_for())
        assert new is trip and info["items"][0]["reason"] == "no_splice"

    def test_an_unreadable_route_keeps_the_dodge(self, monkeypatch) -> None:
        unit, world, trip = one_dodge(monkeypatch)
        orig = trip["legs"][0]["shape"]
        monkeypatch.setattr(
            refine,
            "analyse",
            lambda t, ctx, deadline, with_events=True: (
                world.analyse(t, ctx, deadline, with_events)
                if t["legs"][0]["shape"] == orig
                else None
            ),
        )
        new, info = dedodge.apply(trip, ctx_for())
        assert new is trip and info["items"][0]["reason"] == "untraceable"

    def test_a_trip_that_cannot_be_traced_is_left_alone(self, monkeypatch) -> None:
        unit, world, trip = one_dodge(monkeypatch)
        monkeypatch.setattr(routing, "_trace", lambda *a, **k: None)
        new, info = dedodge.apply(trip, ctx_for())
        assert new is trip and info["found"] == 0 and world.calls == []

    def test_a_route_without_dodges_asks_the_router_nothing(self, monkeypatch) -> None:
        graph = Graph()
        a, b = at(0, 0), at(0, 800)
        graph.add(a, b, ["Main St"], 1)
        world = World(monkeypatch, graph)
        trip = trip_of(leg_of([a, b]))
        new, info = dedodge.apply(trip, ctx_for())
        assert new is trip and world.calls == []
        assert info == dedodge.empty_info()

    def test_it_never_raises(self, monkeypatch) -> None:
        unit, world, trip = one_dodge(monkeypatch)
        monkeypatch.setattr(
            dedodge, "find_dodges", lambda *a: (_ for _ in ()).throw(RuntimeError("x"))
        )
        new, info = dedodge.apply(trip, ctx_for())
        assert new is trip and info["removed"] == 0

    def test_a_router_that_goes_down_leaves_the_route_as_it_was(self, monkeypatch) -> None:
        unit, world, trip = one_dodge(monkeypatch)
        world.answers[(key(unit.b), key(unit.d))] = routing.RouterUnavailable("down")
        new, info = dedodge.apply(trip, ctx_for())
        assert new is trip and info["limited"] == "time"

    def test_a_route_of_unnamed_streets_has_no_dodges(self, monkeypatch) -> None:
        graph = Graph()
        unit = Unit(graph, at(0, 0))
        for edge in graph.edges.values():
            edge["names"] = []
        world = World(monkeypatch, graph, [unit])
        trip = trip_of(leg_of(unit.dodge_route))
        new, info = dedodge.apply(trip, ctx_for())
        assert new is trip and info["found"] == 0 and world.calls == []


class TestBounds:
    def test_a_plan_with_no_time_left_does_nothing(self, monkeypatch) -> None:
        unit, world, trip = one_dodge(monkeypatch)
        ctx = ctx_for()
        ctx.deadline = routing.Deadline(routing.clock() + 6.0 + 2.5, 35)
        new, info = dedodge.apply(trip, ctx)
        assert new is trip and info["limited"] == "time" and world.calls == []
        ctx.deadline = routing.Deadline(routing.clock() + 6.0 + 3.5, 35)
        new, info = dedodge.apply(trip, ctx)
        assert info["limited"] is None and info["removed"] == 1

    def test_the_pass_stops_before_the_answers_own_work(self, monkeypatch) -> None:
        """Whatever it is given, it ends REFINE_TRACE_RESERVE_S before the plan's deadline."""
        unit, world, trip = one_dodge(monkeypatch)
        ctx = ctx_for()
        seen = []
        real = routing.Deadline

        def spy(at_, per):
            seen.append((at_, per))
            return real(at_, per)

        monkeypatch.setattr(routing, "Deadline", spy)
        ctx.deadline = real(routing.clock() + 40.0, 35)
        dedodge.apply(trip, ctx)
        at_, per = seen[0]
        assert at_ == pytest.approx(routing.clock() + dedodge.BUDGET_S, abs=0.5)
        assert per == dedodge.CALL_TIMEOUT_S
        ctx.deadline = real(routing.clock() + 10.0, 35)
        seen.clear()
        dedodge.apply(trip, ctx)
        at_, _per = seen[0]
        assert at_ == pytest.approx(ctx.deadline.at - refine.REFINE_TRACE_RESERVE_S, abs=0.5)

    def test_a_call_may_take_no_longer_than_the_plans_own(self, monkeypatch) -> None:
        unit, world, trip = one_dodge(monkeypatch)
        ctx = ctx_for()
        ctx.deadline = routing.Deadline(routing.clock() + 40.0, 3.0)
        seen = []
        real = routing.Deadline
        monkeypatch.setattr(routing, "Deadline", lambda a, p: seen.append(p) or real(a, p))
        dedodge.apply(trip, ctx)
        assert seen[0] == 3.0

    def test_the_clock_running_out_between_dodges_stops_the_pass(self, monkeypatch) -> None:
        graph = Graph()
        a = at(0, 0)
        units = []
        for i in range(2):
            units.append(Unit(graph, a, ways=10 * (i + 1)))
            a = units[-1].e
        world = World(monkeypatch, graph, units)
        route = [units[0].dodge_route[0]]
        for u in units:
            route += u.dodge_route[1:]
        trip = trip_of(leg_of(route))
        now = [routing.clock()]
        monkeypatch.setattr(routing, "clock", lambda: now[0])
        ctx = ctx_for()
        ctx.deadline = routing.Deadline(now[0] + 40.0, 35)
        # 4 s a call: the first is read in the 5 s budget, the second past it.
        world.after_call = lambda: now.__setitem__(0, now[0] + 4.0)
        new, info = dedodge.apply(trip, ctx)
        assert info["limited"] == "time"
        # The last first: the second was taken out, the first is left unchecked.
        assert info["checked"] == 2 and [i["action"] for i in info["items"]] == [
            "unchecked",
            "removed",
        ]
        assert len(world.calls) == 2

    def test_a_pass_that_ran_out_of_time_goes_no_further_down_the_trip(self, monkeypatch) -> None:
        graph = Graph()
        u1 = Unit(graph, at(0, 0), ways=10)
        u2 = Unit(graph, at(5000, 0), ways=20)
        world = World(monkeypatch, graph, [u1, u2])
        trip = trip_of(leg_of(u1.dodge_route), leg_of(u2.dodge_route))
        now = [routing.clock()]
        monkeypatch.setattr(routing, "clock", lambda: now[0])
        ctx = ctx_for()
        ctx.deadline = routing.Deadline(now[0] + 40.0, 35)
        # 4 s a call: the first is read in the 5 s budget, the second past it.
        world.after_call = lambda: now.__setitem__(0, now[0] + 4.0)
        new, info = dedodge.apply(trip, ctx)
        # The first leg's dodge was taken out and the clock then ran out in the second's.
        assert info["limited"] == "time" and len(world.calls) == 2
        assert [i["action"] for i in info["items"]] == ["removed", "unchecked"]
        assert info["found"] == 2 == len(info["items"])

    def test_a_limit_reached_in_one_leg_stops_the_pass_before_the_next(self, monkeypatch) -> None:
        graph = Graph()
        u1 = Unit(graph, at(0, 0), ways=10)
        u2 = Unit(graph, u1.e, ways=20)
        u3 = Unit(graph, at(5000, 0), ways=30)
        world = World(monkeypatch, graph, [u1, u2, u3])
        trip = trip_of(leg_of([*u1.dodge_route, *u2.dodge_route[1:]]), leg_of(u3.dodge_route))
        now = [routing.clock()]
        monkeypatch.setattr(routing, "clock", lambda: now[0])
        ctx = ctx_for()
        ctx.deadline = routing.Deadline(now[0] + 40.0, 35)
        # 4 s a call: the first is read in the 5 s budget, the second past it.
        world.after_call = lambda: now.__setitem__(0, now[0] + 4.0)
        new, info = dedodge.apply(trip, ctx)
        assert info["limited"] == "time" and len(world.calls) == 2
        assert [i["action"] for i in info["items"]] == ["unchecked", "removed"]
        assert info["found"] == 2, "the second leg was not looked at"

    def test_at_most_max_checks_are_made(self, monkeypatch) -> None:
        graph = Graph()
        a = at(0, 0)
        units = []
        for i in range(dedodge.MAX_CHECKS + 2):
            units.append(Unit(graph, a, reach=500.0, ways=10 * (i + 1)))
            a = units[-1].e
        world = World(monkeypatch, graph, units)
        route = [units[0].dodge_route[0]]
        for u in units:
            route += u.dodge_route[1:]
        trip = trip_of(leg_of(route))
        new, info = dedodge.apply(trip, ctx_for(), budget_s=60.0)
        assert dedodge.MAX_CHECKS == 8
        assert info["found"] == 10
        assert info["checked"] == 8 and len(world.calls) == 8
        assert info["limited"] == "checks"
        assert info["removed"] == 8
        # Every dodge found is listed, in the route's order; the last ones first, so the
        # first two are the ones left.
        assert [i["action"] for i in info["items"]] == ["unchecked"] * 2 + ["removed"] * 8

    def test_each_pass_reads_the_leg_as_it_now_is(self, monkeypatch) -> None:
        """Two dodges on one leg: the second is replaced in the route the first left."""
        graph = Graph()
        u1 = Unit(graph, at(0, 0), ways=10)
        u2 = Unit(graph, u1.e, ways=20)
        World(monkeypatch, graph, [u1, u2])
        route = [*u1.dodge_route, *u2.dodge_route[1:]]
        trip = trip_of(leg_of(route))
        new, info = dedodge.apply(trip, ctx_for())
        assert info["removed"] == 2
        assert routing.decode_polyline6(new["legs"][0]["shape"]) == pytest.approx(
            [*u1.direct, *u2.direct[1:]]
        )
        want = metres_of([*u1.direct, *u2.direct[1:]]) / 1000.0
        assert new["summary"]["length"] == pytest.approx(want, rel=3e-3)

    @pytest.mark.usefixtures("quarter_mile_rule")
    def test_each_dodge_is_judged_by_itself_not_against_the_route_before_the_last_was_removed(
        self, monkeypatch
    ) -> None:
        """Two dodges of 300 m, each calmer than the road: neither avoids a quarter of a
        mile. Read against the route as it was before the first was removed, the second
        would seem to avoid 600 m."""
        graph = Graph()
        u1 = Unit(graph, at(0, 0), reach=300.0, side="1", main="3", ways=10)
        u2 = Unit(graph, u1.e, reach=300.0, side="1", main="3", ways=20)
        World(monkeypatch, graph, [u1, u2])
        trip = trip_of(leg_of([*u1.dodge_route, *u2.dodge_route[1:]]))
        new, info = dedodge.apply(trip, ctx_for())
        assert [i["action"] for i in info["items"]] == ["removed", "removed"]
        assert info["items"][0]["avoided_m"] == pytest.approx(300.0, abs=1.5)

    def test_a_kept_dodge_does_not_stop_the_next(self, monkeypatch) -> None:
        graph = Graph()
        u1 = Unit(graph, at(0, 0), reach=800.0, side="1", main="3", ways=10)
        u2 = Unit(graph, u1.e, reach=400.0, side="3", main="3", ways=20)
        World(monkeypatch, graph, [u1, u2])
        route = [*u1.dodge_route, *u2.dodge_route[1:]]
        trip = trip_of(leg_of(route))
        new, info = dedodge.apply(trip, ctx_for())
        assert [i["action"] for i in info["items"]] == ["kept", "removed"]
        assert routing.decode_polyline6(new["legs"][0]["shape"]) == pytest.approx(
            [*u1.dodge_route, *u2.direct[1:]]
        )


class TestLegs:
    def test_a_dodge_on_a_later_leg_replaces_that_leg_alone(self, monkeypatch) -> None:
        graph = Graph()
        flat = [at(2000, 0), at(2000, 800)]
        graph.add(flat[0], flat[1], ["Elm St"], 7)
        unit = Unit(graph, at(0, 0))
        World(monkeypatch, graph, [unit])
        first = leg_of(flat)
        second = leg_of(unit.dodge_route)
        trip = trip_of(first, second)
        new, info = dedodge.apply(trip, ctx_for())
        assert new["legs"][0] is trip["legs"][0]
        assert routing.decode_polyline6(new["legs"][1]["shape"]) == pytest.approx(unit.direct)
        assert new["summary"]["length"] == pytest.approx(
            first["summary"]["length"] + new["legs"][1]["summary"]["length"]
        )
        assert info["found"] == 1 and info["removed"] == 1

    def test_every_leg_is_looked_at(self, monkeypatch) -> None:
        graph = Graph()
        u1 = Unit(graph, at(0, 0), ways=10)
        u2 = Unit(graph, at(5000, 0), ways=20)
        World(monkeypatch, graph, [u1, u2])
        trip = trip_of(leg_of(u1.dodge_route), leg_of(u2.dodge_route))
        new, info = dedodge.apply(trip, ctx_for())
        assert info["found"] == 2 and info["removed"] == 2
        assert routing.decode_polyline6(new["legs"][0]["shape"]) == pytest.approx(u1.direct)
        assert routing.decode_polyline6(new["legs"][1]["shape"]) == pytest.approx(u2.direct)

    def test_a_trip_with_no_legs_is_left_alone(self, monkeypatch) -> None:
        World(monkeypatch, Graph())
        trip = {"legs": [], "summary": {}}
        new, info = dedodge.apply(trip, ctx_for())
        assert new is trip and info == dedodge.empty_info()


# --- Konterra Drive ------------------------------------------------------------------------------


class Konterra:
    """The live routers' answers for the Konterra Drive dodge."""

    def __init__(self, monkeypatch, tiers=None) -> None:
        self.data = json.loads(DATA.read_text())
        self.tiers = {int(k): v for k, v in self.data["tiers"].items()}
        self.tiers.update(tiers or {})
        self.calls: list[dict] = []
        self.leg = self.data["leg"]
        monkeypatch.setattr(routing, "_trace", self.trace)
        monkeypatch.setattr(routing, "_call", self.call)
        monkeypatch.setattr(refine, "analyse", self.analyse)

    def trace(self, variant, costing, shape, deadline, traces=None):
        return self.data["trace" if shape == self.leg["shape"] else "direct_trace"]

    def call(self, variant, endpoint, payload, deadline):
        assert endpoint == "route"
        self.calls.append(payload)
        return {"trip": self.data["sub"]}

    def analyse(self, trip, ctx, deadline, with_events=True):
        pieces = []
        for leg in trip["legs"]:
            pieces.extend(routing.pieces_of_trace(self.trace(None, None, leg["shape"], None)))
        tiers = [self.tiers[p.way_id] for p in pieces]
        return dataclasses.replace(
            analysis("r", events=[] if with_events else None),
            pieces=pieces,
            classes=[(t, "none") for t in tiers],
            lts3_m=sum(p.metres for p, t in zip(pieces, tiers, strict=True) if t == "3"),
            lts4_m=sum(p.metres for p, t in zip(pieces, tiers, strict=True) if t in "45"),
            length_m=float(trip["summary"]["length"]) * 1000.0,
        )

    def trip(self) -> dict:
        return {"legs": [dict(self.leg)], "summary": dict(self.leg["summary"])}


class TestKonterraDrive:
    """OWNER-DECISIONS 273. North on Konterra Drive (MD 206) a Default, Trailmaxxing or
    Cargo ride leaves it at -76.885651, 39.074958 for Virginia Manor Road, a quarter of a
    mile of LTS 3 (the side street no calmer than the road), and rejoins it; the Fast
    preset stays on Konterra. 1.84 mi, 1.75 mi without the dodge (the live routers, 47c2f52
    graph of 2026-10-03)."""

    def test_the_dodge_is_found_in_the_live_trace(self, monkeypatch) -> None:
        world = Konterra(monkeypatch)
        trace = world.data["trace"]
        shape = routing.decode_polyline6(world.leg["shape"])
        edges = dedodge.edges_of(trace, shape)
        found = dedodge.find_dodges(edges, shape)
        assert len(found) == 1, "the trail crossing of Konterra Drive is not a dodge"
        (dodge,) = found
        assert dodge.street == "konterra drive"
        assert {n for s in dodge.off for n in s.names} == {"virginia manor road"}
        assert dodge.metres == pytest.approx(0.25 * MILE, abs=15.0)
        assert [e.way_id for e in dodge.edges] == [
            6104012,
            6104012,
            235061913,
            1473496057,
            240334415,
            240334415,
            240334415,
        ]
        assert "konterra drive" in dodge.before.names and "konterra drive" in dodge.after.names
        assert [e.way_id for e in dodge.before.edges][-1] == 256386638
        assert dodge.after.first.way_id == 256386638

    def test_it_is_taken_out(self, monkeypatch) -> None:
        world = Konterra(monkeypatch)
        trip = world.trip()
        ctx = ctx_for()
        new, info = dedodge.apply(trip, ctx)
        (item,) = info["items"]
        assert item["action"] == "removed" and item["reason"] == "no_stress_gain"
        assert item["avoided_m"] == 0.0
        assert item["turns_saved"] == 3
        assert item["length_m"] == pytest.approx(408.0, abs=1.0)
        assert item["extra_m"] == pytest.approx(147.0, abs=2.0)
        # 1.84 mi to 1.75 mi.
        assert trip["summary"]["length"] * 1000 / MILE == pytest.approx(1.84, abs=0.01)
        assert new["summary"]["length"] * 1000 / MILE == pytest.approx(1.75, abs=0.01)
        # The route now is the one the router gave for the Fast preset: Konterra's own way.
        direct = routing.decode_polyline6(world.data["direct_trace"]["shape"])
        assert routing.decode_polyline6(new["legs"][0]["shape"]) == pytest.approx(direct, abs=1e-6)

    def test_what_was_asked_of_the_router(self, monkeypatch) -> None:
        world = Konterra(monkeypatch)
        ctx = ctx_for()
        dedodge.apply(world.trip(), ctx)
        (payload,) = world.calls
        here, there = payload["locations"]
        assert (here["lon"], here["lat"]) == pytest.approx((-76.885651, 39.074958), abs=1e-6)
        assert (there["lon"], there["lat"]) == pytest.approx((-76.885976, 39.077253), abs=1e-6)
        assert here["heading"] == 12 and there["heading"] == 332
        assert len(payload["exclude_locations"]) == 7, "each of the dodge's seven edges"

    def test_with_lts4_on_konterra_the_dodge_is_kept(self, monkeypatch) -> None:
        """The same streets, but the road is LTS 4: the dodge avoids it."""
        direct = Konterra(monkeypatch).data["direct_trace"]
        konterra = {e["way_id"] for e in direct["edges"] if "Konterra Drive" in e["names"]}
        world = Konterra(monkeypatch, tiers={w: "4" for w in konterra})
        new, info = dedodge.apply(world.trip(), ctx_for())
        assert info["items"][0]["action"] == "kept" and info["items"][0]["reason"] == "top"

    @pytest.mark.usefixtures("quarter_mile_rule")
    def test_even_calm_side_streets_are_not_kept_for_under_a_quarter_of_a_mile(
        self, monkeypatch
    ) -> None:
        """Virginia Manor Road at LTS 1 against Konterra's LTS 3: the road's stretch
        is 0.16 mi, under the quarter mile, so even then the dodge is not worth its turns."""
        world = Konterra(
            monkeypatch, tiers={235061913: "1", 1473496057: "1", 240334415: "1", 6104012: "1"}
        )
        new, info = dedodge.apply(world.trip(), ctx_for())
        assert info["items"][0]["avoided_m"] == pytest.approx(261.0, abs=2.0)
        assert info["items"][0]["needed_m"] == pytest.approx(dedodge.MIN_AVOIDED_M + 80.0, abs=0.1)
        assert info["items"][0]["action"] == "removed"


# --- Review r0: the top of the slider, the checks worth making, the bounds ------------------


class TestTheTieStepOnEveryPreset:
    """OWNER-DECISIONS 298(1), "Same as Trailmaxxing (Recommended)": on every ride type,
    Default included, a dodge is taken out only where what it avoids is within the
    second level's tie step (50 m), and no turns are charged (it amends 272's quarter
    mile, the rule first built for every plan below the top of the slider)."""

    def test_the_rule_and_its_step(self) -> None:
        assert dedodge.TIE_RULE_ALL_PRESETS is True
        assert dedodge.TIE_STEP_M == refine.MAXCALM_STEPS[1] == 50.0
        assert dedodge.tie_rule()
        assert dedodge.needed_m(0, True) == dedodge.needed_m(9, True) == 50.0

    @pytest.mark.parametrize("ctx", [TOP, CTX], ids=["top", "default"])
    def test_within_the_step_is_a_tie_and_the_main_road_is_taken(self, ctx) -> None:
        got = verdict(read(turns=2), read(lts3=50.0), ctx)
        assert got.remove and got.reason == "no_stress_gain" and got.needed_m == 50.0
        got = verdict(read(turns=2), read(lts3=50.5), ctx)
        assert not got.remove and got.reason == "stress"

    @pytest.mark.parametrize("ctx", [TOP, CTX], ids=["top", "default"])
    def test_no_turns_are_charged(self, ctx) -> None:
        """Six turns asked 0.25 mi + 320 m by 272's rule; by the tie step, 50 m."""
        got = verdict(read(turns=6), read(lts3=60.0), ctx)
        assert not got.remove and got.needed_m == 50.0

    def test_an_orange_junction_counts_at_the_second_level(self) -> None:
        # 700 ft of junction cost (an orange junction is 600 ft or more) is 213 m.
        got = verdict(read(turns=2), read(orange=[700.0]), CTX)
        assert not got.remove and got.avoided_m == pytest.approx(700.0 * FT)

    def test_the_guards_still_hold(self) -> None:
        for ctx in (TOP, CTX):
            assert verdict(read(turns=2), read(lts4=2.0), ctx).reason == "top"
            assert (
                verdict(read(length=1000.0, turns=2), read(length=1005.0), ctx).reason == "longer"
            )

    def test_default_keeps_what_the_quarter_mile_rule_removed(self) -> None:
        """300 m of LTS 3 avoided: 272's rule removed it below the top; 298(1) keeps it."""
        got = verdict(read(turns=2), read(lts3=300.0), CTX)
        assert not got.remove and got.needed_m == 50.0

    def test_the_switch_puts_every_plan_on_the_quarter_mile(self, monkeypatch) -> None:
        monkeypatch.setattr(dedodge, "TIE_RULE_ALL_PRESETS", False)
        for ctx in (TOP, CTX):
            got = verdict(read(turns=2), read(lts3=300.0), ctx)
            assert got.remove and got.needed_m == pytest.approx(dedodge.MIN_AVOIDED_M)

    @pytest.mark.parametrize("maxcalm", [True, False], ids=["top", "default"])
    def test_in_the_pass(self, monkeypatch, maxcalm) -> None:
        # 300 m of LTS 3 avoided through LTS 1 side streets: kept on every ride.
        unit, world, trip = one_dodge(monkeypatch, reach=300.0, side="1", main="3")
        new, info = dedodge.apply(trip, ctx_for(maxcalm=maxcalm))
        assert new is trip and info["items"][0]["reason"] == "stress"
        assert info["items"][0]["needed_m"] == 50.0
        # No calmer: taken out everywhere.
        unit, world, trip = one_dodge(monkeypatch, side="3", main="3")
        new, info = dedodge.apply(trip, ctx_for(maxcalm=maxcalm))
        assert info["removed"] == 1

    @pytest.mark.parametrize("maxcalm", [True, False], ids=["top", "default"])
    def test_konterra_drive_is_taken_out_on_every_ride(self, monkeypatch, maxcalm) -> None:
        world = Konterra(monkeypatch)
        new, info = dedodge.apply(world.trip(), ctx_for(maxcalm=maxcalm))
        (item,) = info["items"]
        assert item["action"] == "removed" and item["avoided_m"] == 0.0
        assert new["summary"]["length"] * 1000 / MILE == pytest.approx(1.75, abs=0.01)

    @pytest.mark.parametrize("maxcalm", [True, False], ids=["top", "default"])
    def test_calm_side_streets_by_konterra_are_kept(self, monkeypatch, maxcalm) -> None:
        """Virginia Manor Road at LTS 1 avoids 261 m of Konterra's LTS 3: more than the
        tie step, so every ride keeps it (272's quarter mile removed it below the top)."""
        world = Konterra(
            monkeypatch, tiers={235061913: "1", 1473496057: "1", 240334415: "1", 6104012: "1"}
        )
        new, info = dedodge.apply(world.trip(), ctx_for(maxcalm=maxcalm))
        assert info["items"][0]["action"] == "kept" and info["items"][0]["reason"] == "stress"


def straight_world(monkeypatch, middle):
    """Main St north 400 m, then `middle` ((names, heading, metres) edges), then Main St on
    north 400 m: a graph and a World whose router knows no stretch (any call fails)."""
    graph = Graph()
    points = [at(0, 0), go(at(0, 0), 0, 400)]
    graph.add(points[0], points[1], ["Main St"], 1, "3")
    for i, (names, heading, metres) in enumerate(middle):
        points.append(go(points[-1], heading, metres))
        graph.add(points[-2], points[-1], names, 2 + i, "3")
    points.append(go(points[-1], 0, 400))
    graph.add(points[-2], points[-1], ["Main St"], 50, "3")
    world = World(monkeypatch, graph)
    return world, trip_of(leg_of(points))


class TestNotWorthACheck:
    """Review r0 item 4: a detected dodge with fewer than two turns over its own stretch (a
    straight run through an unnamed edge, a way inside one road) or under 50 m is no weave;
    it is not checked, so it spends neither the router nor the cap."""

    def test_the_constants(self) -> None:
        assert dedodge.MIN_DODGE_M == 50.0 and dedodge.BASE_TURNS == 2

    def test_a_straight_run_is_skipped(self) -> None:
        (found,) = dodges_of([MAIN, ([], 0, 200), MAIN])
        assert dedodge.skip_reason(found) == "straight"
        (found,) = dodges_of([MAIN, (["Side"], 30, 300), MAIN])
        assert dedodge.skip_reason(found) == "straight", "a bend under the turn angle"

    def test_one_turn_is_not_a_weave(self) -> None:
        """Off at 60 degrees, back on at 20: one turn."""
        (found,) = dodges_of([MAIN, (["Side"], 60, 200), (["Side"], 20, 200), MAIN])
        assert dedodge.skip_reason(found) == "straight"

    def test_two_turns_are(self) -> None:
        (found,) = dodges_of([MAIN, (["Side"], 60, 300), (["Side"], 300, 300), MAIN])
        assert dedodge.skip_reason(found) is None

    def test_under_50_m_is_skipped(self) -> None:
        (found,) = dodges_of([MAIN, (["Side"], 60, 24), (["Side"], 300, 24), MAIN])
        assert found.metres < 50.0 and dedodge.skip_reason(found) == "short"
        (found,) = dodges_of([MAIN, (["Side"], 60, 26), (["Side"], 300, 26), MAIN])
        assert found.metres > 50.0 and dedodge.skip_reason(found) is None

    def test_unnamed_edges_alone_are_skipped_up_to_60_m(self) -> None:
        assert dedodge.MIN_UNNAMED_DODGE_M == 60.0
        (found,) = dodges_of([MAIN, ([], 60, 29), ([], 300, 29), MAIN])
        assert 50.0 < found.metres < 60.0 and dedodge.skip_reason(found) == "short"
        (found,) = dodges_of([MAIN, ([], 60, 31), ([], 300, 31), MAIN])
        assert found.metres > 60.0 and dedodge.skip_reason(found) is None
        # Named, 58 m is checked.
        (found,) = dodges_of([MAIN, (["Side"], 60, 29), (["Side"], 300, 29), MAIN])
        assert dedodge.skip_reason(found) is None
        (found,) = dodges_of([MAIN, ([], 60, 29), (["Side"], 300, 29), MAIN])
        assert dedodge.skip_reason(found) is None, "one named edge is a street"

    def test_a_skipped_dodge_is_listed_and_asks_the_router_nothing(self, monkeypatch) -> None:
        world, trip = straight_world(monkeypatch, [([], 0, 30)])
        new, info = dedodge.apply(trip, ctx_for())
        assert new is trip and world.calls == []
        assert (info["found"], info["skipped"], info["checked"], info["limited"]) == (1, 1, 0, None)
        (item,) = info["items"]
        assert (item["action"], item["reason"]) == ("skipped", "short")
        world, trip = straight_world(monkeypatch, [([], 0, 200)])
        new, info = dedodge.apply(trip, ctx_for())
        assert world.calls == [] and info["items"][0]["reason"] == "straight"

    def test_a_skipped_dodge_does_not_use_up_a_check(self, monkeypatch) -> None:
        """MAX_CHECKS real dodges after a stub are all checked."""
        graph = Graph()
        stub_a, stub_b, stub_c = at(0, -600), at(0, -470), at(0, -440)
        graph.add(stub_a, stub_b, ["Main St"], 1)
        graph.add(stub_b, stub_c, [], 2)
        graph.add(stub_c, at(0, 0), ["Main St"], 3)
        a = at(0, 0)
        units = []
        for i in range(dedodge.MAX_CHECKS):
            units.append(Unit(graph, a, reach=500.0, ways=10 * (i + 1)))
            a = units[-1].e
        world = World(monkeypatch, graph, units)
        route = [stub_a, stub_b, stub_c, at(0, 0)]
        for u in units:
            route += u.dodge_route[1:]
        new, info = dedodge.apply(trip_of(leg_of(route)), ctx_for(), budget_s=60.0)
        assert info["found"] == dedodge.MAX_CHECKS + 1 and info["skipped"] == 1
        assert info["checked"] == dedodge.MAX_CHECKS == len(world.calls)
        assert info["removed"] == dedodge.MAX_CHECKS and info["limited"] is None


class TestCounting:
    """Review r0: every dodge found is listed once, and is removed, kept, skipped or
    unchecked."""

    def test_the_counts_add_up(self, monkeypatch) -> None:
        graph = Graph()
        a = at(0, 0)
        units = []
        for i in range(dedodge.MAX_CHECKS + 2):
            side = "1" if i % 3 == 0 else "3"
            units.append(Unit(graph, a, reach=500.0, side=side, main="3", ways=10 * (i + 1)))
            a = units[-1].e
        World(monkeypatch, graph, units)
        route = [units[0].dodge_route[0]]
        for u in units:
            route += u.dodge_route[1:]
        new, info = dedodge.apply(trip_of(leg_of(route)), ctx_for(), budget_s=60.0)
        actions = [i["action"] for i in info["items"]]
        assert info["found"] == len(info["items"]) == len(units)
        assert actions.count("removed") == info["removed"]
        assert actions.count("kept") == info["kept"] and info["kept"] >= 1
        assert actions.count("unchecked") == 2
        assert info["found"] == info["removed"] + info["kept"] + info["skipped"] + 2
        assert None not in actions

    def test_a_pass_that_failed_lists_what_it_did_not_judge(self, monkeypatch) -> None:
        unit, world, trip = one_dodge(monkeypatch)

        def broken(*a, **k):
            raise ValueError("unexpected")

        monkeypatch.setattr(dedodge, "_alternative", broken)
        new, info = dedodge.apply(trip, ctx_for())
        assert new is trip and [i["action"] for i in info["items"]] == ["unchecked"]


class TestTheTopFigureAgainstTheLegAsFound:
    """Review r0 nit: the 1 m of slack is the leg's, not each dodge's."""

    def test_in_the_verdict(self) -> None:
        original, now = read(lts4=0.0), read(turns=2, lts4=0.8)
        assert verdict(now, read(lts4=1.6)).remove
        got = verdict(now, read(lts4=1.6), original=original)
        assert not got.remove and got.reason == "top"
        assert verdict(now, read(lts4=0.9), original=original).remove
        # Below the leg as found: the leg as it now is is the bar.
        got = verdict(read(turns=2, lts4=0.0), read(lts4=1.5), original=read(lts4=5.0))
        assert got.reason == "top"

    def test_in_the_pass(self, monkeypatch) -> None:
        """Two dodges whose main road has 0.8 m of LTS 4 each: one may go, not both."""
        graph = Graph()
        u1 = Unit(graph, at(0, 0), ways=10)
        u2 = Unit(graph, u1.e, ways=20)
        world = World(monkeypatch, graph, [u1, u2])
        real = world.analyse
        mains = {15, 25}

        def analyse(trip, ctx, deadline, with_events=True):
            got = real(trip, ctx, deadline, with_events)
            extra = 0.8 * sum(1 for p in got.pieces if p.way_id in mains)
            return dataclasses.replace(got, lts4_m=got.lts4_m + extra)

        monkeypatch.setattr(refine, "analyse", analyse)
        trip = trip_of(leg_of([*u1.dodge_route, *u2.dodge_route[1:]]))
        new, info = dedodge.apply(trip, ctx_for())
        assert [i["action"] for i in info["items"]] == ["kept", "removed"]
        assert info["items"][0]["reason"] == "top"


class TestPinnedBounds:
    """Review r0's surviving mutants: each bound by its value, not by its name."""

    def test_the_budget_is_five_seconds(self, monkeypatch) -> None:
        assert dedodge.BUDGET_S == 5.0
        graph = Graph()
        a = at(0, 0)
        units = []
        for i in range(3):
            units.append(Unit(graph, a, ways=10 * (i + 1)))
            a = units[-1].e
        world = World(monkeypatch, graph, units)
        route = [units[0].dodge_route[0]]
        for u in units:
            route += u.dodge_route[1:]
        now = [routing.clock()]
        monkeypatch.setattr(routing, "clock", lambda: now[0])
        ctx = ctx_for()
        ctx.deadline = routing.Deadline(now[0] + 40.0, 35)
        # Each check takes 2.6 s: two fit in 5 s, a third would not.
        world.after_call = lambda: now.__setitem__(0, now[0] + 2.6)
        new, info = dedodge.apply(trip_of(leg_of(route)), ctx)
        assert info["checked"] == 2 and info["limited"] == "time"

    def test_the_hills_slack_is_a_metre(self) -> None:
        ctx = context(rate=10.0)
        ctx.hills_weight = 1.0
        dodge = read(length=1000.0, turns=2, effort=1000.0)
        got = verdict(dodge, read(length=999.0, effort=1002.0), ctx)
        assert not got.remove and got.reason == "hills"
        assert verdict(dodge, read(length=999.0, effort=1000.9), ctx).remove

    def test_the_same_road_comes_back_within_90_degrees(self) -> None:
        assert dedodge.SAME_ROAD_HEADING_DEG == 90.0

        def rejoin(heading):
            return dodges_of(
                [MAIN, (["Side"], 60, 300), (["Side"], 300, 300), (["Main St"], heading, 400)]
            )

        assert len(rejoin(85)) == 1
        assert rejoin(100) == [] and rejoin(140) == []

    def test_a_turn_is_40_degrees(self) -> None:
        assert dedodge.TURN_DEGREES == 40.0

        def turned(degrees):
            a = routing.Piece(1, LON0, LAT0, 100.0, names=("A",), heading_in=0.0, heading_out=0.0)
            b = routing.Piece(
                2, LON0, LAT0, 100.0, names=("B",), heading_in=degrees, heading_out=degrees
            )
            return dedodge.turn_count([a, b])

        assert turned(45.0) == 1 and turned(55.0) == 1 and turned(35.0) == 0

    def test_a_dodge_is_a_mile_at_most(self) -> None:
        assert dedodge.DODGE_MAX_M == pytest.approx(MILE)

        def length(metres):
            return [MAIN, (["Side"], 60, metres / 2), (["Side"], 300, metres / 2), MAIN]

        assert len(dodges_of(length(0.95 * MILE))) == 1
        assert dodges_of(length(1.2 * MILE)) == [] and dodges_of(length(1.8 * MILE)) == []


# --- After the pass (review r0 items 3 and 5) ----------------------------------------------------


def _top_ctx():
    from test_longcalm import alt_context

    return alt_context(ceiling_m=20_000.0)


def _road(name, ways, tiers=None, km=None, **fields):
    from test_longcalm import road

    trip, got = road(name, ways, tiers, km)
    return trip, dataclasses.replace(got, **fields) if fields else got


def _names(chosen):
    return [trip["legs"][0]["shape"] for trip, _read in chosen]


def _removed(saved_m=600.0):
    info = dedodge.empty_info()
    info.update(removed=1, saved_m=saved_m)
    return info


class TestAfterThePass:
    """`dedodge.settle`: the answer's search figures follow the route as answered, and the
    routes to choose from (which the pass leaves alone) are picked again against it."""

    def test_nothing_taken_out_nothing_changes(self, monkeypatch) -> None:
        ctx = _top_ctx()
        ctx.candidates = [_road("main", [1, 2, 3, 4, 5, 6, 7, 8]), _road("b", list(range(11, 19)))]
        before = list(ctx.candidates)
        refined = {"extra_distance_m": 100.0, "exposure_after_m": 5.0}
        monkeypatch.setattr(refine, "analyse", lambda *a, **k: pytest.fail("read"))
        dedodge.settle({"legs": []}, ctx, refined, dedodge.empty_info())
        assert ctx.candidates == before
        assert refined == {"extra_distance_m": 100.0, "exposure_after_m": 5.0}

    def test_the_search_figures_are_the_answers(self, monkeypatch) -> None:
        ctx = _top_ctx()
        trip, now = _road("now", [1, 2, 3, 4], "1133", exposure_m=2000.0)
        monkeypatch.setattr(refine, "analyse", lambda t, c, d, with_events=True: now)
        refined = {
            "extra_distance_m": 1000.0,
            "exposure_after_m": 1500.0,
            "lts3_m_after": 1500.0,
            "lts4_m_after": 7.0,
            "top_m_after": 7.0,
        }
        dedodge.settle(trip, ctx, refined, _removed(600.0))
        assert refined == {
            "extra_distance_m": 400.0,
            "exposure_after_m": 2000.0,
            "lts3_m_after": 2000.0,
            "lts4_m_after": 0.0,
            "top_m_after": 0.0,
        }

    def test_without_a_search_there_is_nothing_to_say(self, monkeypatch) -> None:
        ctx = _top_ctx()
        trip, now = _road("now", [1, 2, 3, 4])
        monkeypatch.setattr(refine, "analyse", lambda *a, **k: now)
        dedodge.settle(trip, ctx, None, _removed())

    def test_a_candidate_still_offered_is_offered_after_the_new_answer(self, monkeypatch) -> None:
        ctx = _top_ctx()
        ctx.candidates = [_road("old", list(range(1, 9))), _road("b", list(range(11, 19)))]
        new = _road("new", list(range(1, 9)), km=7.5)
        monkeypatch.setattr(refine, "analyse", lambda *a, **k: new[1])
        dedodge.settle(new[0], ctx, None, _removed())
        assert _names(ctx.candidates) == ["new", "b"]
        assert ctx.candidates[0][1] is new[1]

    def test_no_candidate_goes_further_past_the_target_than_the_answer(self, monkeypatch) -> None:
        ctx = _top_ctx()
        ctx.target_m = 8_000.0
        ctx.candidates = [
            _road("old", list(range(1, 9)), km=8.5),
            _road("b", list(range(11, 19)), km=8.5),
        ]
        new = _road("new", list(range(1, 9)), km=8.0)
        monkeypatch.setattr(refine, "analyse", lambda *a, **k: new[1])
        dedodge.settle(new[0], ctx, None, _removed())
        assert _names(ctx.candidates) == ["new"]

    def test_a_route_that_came_to_share_the_answers_road_is_dropped(self, monkeypatch) -> None:
        ctx = _top_ctx()
        ctx.candidates = [_road("old", list(range(1, 9))), _road("b", list(range(11, 19)))]
        new = _road("new", [11, 12, 13, 14, 15, 16, 17, 9])
        monkeypatch.setattr(refine, "analyse", lambda *a, **k: new[1])
        dedodge.settle(new[0], ctx, None, _removed())
        assert _names(ctx.candidates) == ["new"]

    def test_a_candidate_no_longer_a_near_tie_is_dropped(self, monkeypatch) -> None:
        """A main road calmer than the side streets brings the answer's second figure
        down: a candidate within the band of the answer as it was may not be of it now."""
        for now_lts3, want in ((450.0, ["new", "b"]), (100.0, ["new"])):
            ctx = _top_ctx()
            ctx.candidates = [
                _road("old", list(range(1, 9)), lts3_m=500.0),
                _road("b", list(range(11, 19)), lts3_m=1000.0),
            ]
            new = _road("new", list(range(1, 9)), km=7.5, lts3_m=now_lts3)
            monkeypatch.setattr(refine, "analyse", lambda *a, _n=new, **k: _n[1])
            dedodge.settle(new[0], ctx, None, _removed())
            assert _names(ctx.candidates) == want, now_lts3

    def test_the_hold_is_the_one_the_search_picked_them_by(self, monkeypatch) -> None:
        from test_longcalm import AVERSE

        for reference, want in (([1000.0], ["new", "b"]), ([0.0], ["new"])):
            ctx = _top_ctx()
            ctx.exposure = AVERSE
            ctx.first_lts4 = [0.0, 0.0, 0.0]
            ctx.candidate_reference = reference
            ctx.candidates = [
                _road("old", list(range(1, 9)), "11111114"),
                _road("b", list(range(11, 19)), "41111111"),
            ]
            new = _road("new", list(range(1, 9)), "11111114", km=7.5)
            monkeypatch.setattr(refine, "analyse", lambda *a, _n=new, **k: _n[1])
            dedodge.settle(new[0], ctx, None, _removed())
            assert _names(ctx.candidates) == want, reference

    def test_an_answer_that_cannot_be_read_offers_no_candidates(self, monkeypatch) -> None:
        ctx = _top_ctx()
        ctx.candidates = [_road("old", list(range(1, 9))), _road("b", list(range(11, 19)))]
        trip = {"legs": [{"shape": "new"}]}
        monkeypatch.setattr(refine, "analyse", lambda *a, **k: None)
        dedodge.settle(trip, ctx, None, _removed())
        assert len(ctx.candidates) == 1 and ctx.candidates[0][0] is trip

        def late(*a, **k):
            raise routing.DeadlineExceeded("late")

        ctx.candidates = [_road("old", list(range(1, 9))), _road("b", list(range(11, 19)))]
        monkeypatch.setattr(refine, "analyse", late)
        refined = {"extra_distance_m": 700.0, "exposure_after_m": 3.0}
        dedodge.settle(trip, ctx, refined, _removed())
        assert len(ctx.candidates) == 1
        assert refined == {"extra_distance_m": 100.0, "exposure_after_m": 3.0}

    def test_the_answer_is_read_by_the_late_deadline(self, monkeypatch) -> None:
        """Inside the plan's deadline less the answer's reserve (combined correctness
        review, S3), not the plan's whole deadline."""
        ctx = _top_ctx()
        trip, now = _road("now", [1, 2, 3, 4])
        seen = []
        monkeypatch.setattr(refine, "analyse", lambda t, c, d, **k: seen.append(d) or now)
        dedodge.settle(trip, ctx, {}, _removed())
        assert seen == [refine.late_deadline(ctx)]
        assert seen[0].at == ctx.deadline.at - refine.REFINE_TRACE_RESERVE_S

    def test_a_reading_the_clock_cuts_short_offers_no_candidates(self, monkeypatch) -> None:
        ctx = _top_ctx()
        trip, now = _road("now", [1, 2, 3, 4])
        other, other_read = _road("other", [5, 6, 7, 8])
        ctx.candidates = [(trip, now), (other, other_read)]

        def cut(*a, **k):
            raise routing.DeadlineExceeded("cut")

        monkeypatch.setattr(refine, "analyse", cut)
        refined = {"lts3_m_after": 1.0}
        dedodge.settle(trip, ctx, refined, _removed())
        assert ctx.candidates == [(trip, None)] and refined["lts3_m_after"] == 1.0


class TestAReadingCutShort:
    """A reading the pass's clock ran out in may have junctions missing (a `/locate` batch
    the clock cut off is left out, `junctions.nodes_at`): it is neither judged nor kept for
    the answer, and the pass stops. (Measured: on Bowie to Annapolis, Default, a removal
    judged on such a reading answered 1 red and 12 orange junctions fewer.)"""

    def remembering(self, monkeypatch, world, late_on=None):
        """`refine.analyse` that remembers what it reads, as the real one does, and moves
        the clock past the pass's end while reading the `late_on`th trip."""
        real = world.analyse
        count = [0]

        def analyse(trip, ctx, deadline, with_events=True):
            count[0] += 1
            got = real(trip, ctx, deadline, with_events)
            ctx.analyses[tuple(leg["shape"] for leg in trip["legs"])] = got
            if count[0] == late_on:
                self.now[0] = deadline.at + 0.1
            return got

        monkeypatch.setattr(refine, "analyse", analyse)

    def setup_clock(self, monkeypatch):
        self.now = [routing.clock()]
        monkeypatch.setattr(routing, "clock", lambda: self.now[0])

    def test_the_stretch_read_late_is_not_judged_or_kept(self, monkeypatch) -> None:
        self.setup_clock(monkeypatch)
        unit, world, trip = one_dodge(monkeypatch)
        self.remembering(monkeypatch, world, late_on=2)
        ctx = ctx_for()
        ctx.deadline = routing.Deadline(self.now[0] + 40.0, 35)
        new, info = dedodge.apply(trip, ctx)
        assert new is trip and info["limited"] == "time" and info["removed"] == 0
        assert [i["action"] for i in info["items"]] == ["unchecked"]
        assert list(ctx.analyses) == [(trip["legs"][0]["shape"],)], "the stretch is forgotten"

    def test_the_leg_read_late_is_not_judged_by(self, monkeypatch) -> None:
        self.setup_clock(monkeypatch)
        unit, world, trip = one_dodge(monkeypatch)
        self.remembering(monkeypatch, world, late_on=1)
        ctx = ctx_for()
        ctx.deadline = routing.Deadline(self.now[0] + 40.0, 35)
        new, info = dedodge.apply(trip, ctx)
        assert new is trip and info["limited"] == "time" and world.calls == []
        assert info["checked"] == 0 and ctx.analyses == {}

    def test_in_time_it_is_judged_and_kept(self, monkeypatch) -> None:
        self.setup_clock(monkeypatch)
        unit, world, trip = one_dodge(monkeypatch)
        self.remembering(monkeypatch, world)
        ctx = ctx_for()
        ctx.deadline = routing.Deadline(self.now[0] + 40.0, 35)
        new, info = dedodge.apply(trip, ctx)
        assert info["removed"] == 1 and info["limited"] is None
        assert (new["legs"][0]["shape"],) in ctx.analyses

    def test_no_check_is_begun_once_the_time_is_gone(self, monkeypatch) -> None:
        """The clock runs out between two checks (here while the leg is read again after
        the first removal): the second is not asked of the router at all."""
        self.setup_clock(monkeypatch)
        graph = Graph()
        u1 = Unit(graph, at(0, 0), ways=10)
        u2 = Unit(graph, u1.e, ways=20)
        world = World(monkeypatch, graph, [u1, u2])
        traces = [0]
        real_trace = world.trace
        ctx = ctx_for()
        ctx.deadline = routing.Deadline(self.now[0] + 40.0, 35)

        def trace(*a, **k):
            traces[0] += 1
            if traces[0] == 2:
                self.now[0] += 10.0
            return real_trace(*a, **k)

        monkeypatch.setattr(routing, "_trace", trace)
        new, info = dedodge.apply(trip_of(leg_of([*u1.dodge_route, *u2.dodge_route[1:]])), ctx)
        assert len(world.calls) == 1 and info["limited"] == "time"
        assert [i["action"] for i in info["items"]] == ["unchecked", "removed"]
