"""Walk pricing (Stephen, 2026-11-02): "Make sure to note crosswalks and prefer signalled
crossings", "Add some penalty for more dangerous crossings, especially sliplanes", "Signalled
only against busy roads, similar to how it's done by bike", "Also penalize walking along a road
without a sidewalk, especially a busier one". `core.walk_pricing` on hand-made traces."""

from __future__ import annotations

from core import routing, walk_pricing, walk_turns
from core.dedodge import encode_polyline6
from core.walk_pricing import BUSY, MEDIUM, QUIET, SEVERE

ROAD = {"use": "road", "driveability": "both"}


def edge(
    use="footway",
    km=0.05,
    cls="service_other",
    names=None,
    sidewalk=None,
    signal=False,
    node_signal=False,
    roads=(),
    lanes=None,
    speed=None,
):
    """One traced edge (lengths in km) ending at a node with `roads`: (class, use) pairs."""
    out = {"use": use, "length": km, "road_class": cls, "names": names or []}
    if sidewalk:
        out["sidewalk"] = sidewalk
    if signal:
        out["traffic_signal"] = True
    if lanes is not None:
        out["lane_count"] = lanes
    if speed is not None:
        out["speed_limit"] = speed
    out["end_node"] = {
        "traffic_signal": node_signal,
        "intersecting_edges": [
            {"road_class": c, "use": u, "driveability": "both"} for c, u in roads
        ],
    }
    return out


def trace(*edges):
    """A trace of `edges` along a straight line, each edge one step east."""
    shape = [(-77.0 + i * 0.0005, 38.9) for i in range(len(edges) + 1)]
    for i, e in enumerate(edges):
        e["begin_shape_index"], e["end_shape_index"] = i, i + 1
    return {"edges": list(edges), "shape": encode_polyline6(shape)}


SPM = 0.75  # seconds a metre: 4.8 km/h


class TestLevels:
    def test_a_road_to_walk_along_is_busy_by_class_speed_or_lanes(self) -> None:
        assert walk_pricing.roadside_level({"road_class": "residential"}) == QUIET
        assert walk_pricing.roadside_level({"road_class": "tertiary"}) == MEDIUM
        assert (
            walk_pricing.roadside_level({"road_class": "residential", "speed_limit": 40}) == MEDIUM
        )
        assert walk_pricing.roadside_level({"road_class": "primary"}) == BUSY
        assert walk_pricing.roadside_level({"road_class": "tertiary", "lane_count": 2}) == BUSY
        assert walk_pricing.roadside_level({"road_class": "residential", "speed_limit": 56}) == BUSY
        assert walk_pricing.roadside_level({"road_class": "trunk"}) == SEVERE

    def test_a_crossing_is_as_busy_as_its_busiest_road(self) -> None:
        assert walk_pricing.crossing_level(["residential", "service_other"]) == QUIET
        assert walk_pricing.crossing_level(["tertiary"]) == MEDIUM
        assert walk_pricing.crossing_level(["residential", "secondary"]) == BUSY
        assert walk_pricing.crossing_level(["primary", "trunk"]) == SEVERE


class TestRead:
    def test_walking_a_road_with_no_sidewalk_costs_more_the_busier_it_is(self) -> None:
        quiet = walk_pricing.read(trace(edge("road", 0.1, "residential")), SPM)
        busy = walk_pricing.read(trace(edge("road", 0.1, "primary")), SPM)
        sidewalk = walk_pricing.read(trace(edge("road", 0.1, "primary", sidewalk="both")), SPM)
        path = walk_pricing.read(trace(edge("footway", 0.1)), SPM)
        assert quiet.roadside_s == round(100 * SPM * walk_pricing.ROADSIDE_FACTORS[QUIET], 1)
        assert busy.roadside_s == round(100 * SPM * walk_pricing.ROADSIDE_FACTORS[BUSY], 1)
        assert busy.roadside_s > quiet.roadside_s > 0
        assert sidewalk.roadside_s == path.roadside_s == 0

    def test_a_crosswalk_across_a_busy_road_with_a_signal_costs_nothing(self) -> None:
        signalled = trace(
            edge("footway"),
            edge("pedestrian_crossing", 0.01, roads=[("primary", "road")] * 2, node_signal=True),
            edge("pedestrian_crossing", 0.01),
            edge("footway"),
        )
        reading = walk_pricing.read(signalled, SPM)
        [crossing] = reading.crossings
        assert (crossing.signal, crossing.marked, crossing.level) == (True, True, BUSY)
        assert crossing.control == "signal" and crossing.said
        assert reading.penalty_s == 0

    def test_a_busy_road_crossed_with_no_signal_costs_minutes_more_with_no_crosswalk(self) -> None:
        crosswalk = trace(
            edge("footway"),
            edge("pedestrian_crossing", 0.01, roads=[("primary", "road")] * 2),
            edge("pedestrian_crossing", 0.01),
            edge("footway"),
        )
        unmarked = trace(edge("footway", roads=[("primary", "road")] * 2), edge("footway"))
        severe = trace(edge("footway", roads=[("trunk", "road")] * 2), edge("footway"))
        assert walk_pricing.read(crosswalk, SPM).penalty_s == walk_pricing.UNSIGNALLED_S[BUSY]
        assert walk_pricing.read(unmarked, SPM).penalty_s == (
            walk_pricing.UNSIGNALLED_S[BUSY] + walk_pricing.UNMARKED_S
        )
        assert walk_pricing.read(severe, SPM).penalty_s == (
            walk_pricing.UNSIGNALLED_S[SEVERE] + walk_pricing.UNMARKED_S
        )
        [said] = walk_pricing.read(crosswalk, SPM).crossings
        assert said.control == "crosswalk"

    def test_a_quiet_street_is_crossed_anywhere_for_nothing_and_only_a_crosswalk_said(self) -> None:
        unmarked = walk_pricing.read(
            trace(edge("footway", roads=[("residential", "road")] * 2), edge("footway")), SPM
        )
        [crossing] = unmarked.crossings
        assert unmarked.penalty_s == 0 and not crossing.said
        marked = walk_pricing.read(
            trace(
                edge("footway"),
                edge("pedestrian_crossing", 0.01, roads=[("residential", "road")] * 2),
                edge("pedestrian_crossing", 0.01),
                edge("footway"),
            ),
            SPM,
        )
        [crossing] = marked.crossings
        assert marked.penalty_s == 0 and crossing.said and crossing.control == "crosswalk"

    def test_a_slip_lane_costs_more_and_is_never_merged_with_its_road(self) -> None:
        reading = walk_pricing.read(
            trace(
                edge("footway"),
                edge("pedestrian_crossing", 0.005, roads=[("primary", "turn_channel")]),
                edge("pedestrian_crossing", 0.005),
                edge("footway", 0.01),
                edge("pedestrian_crossing", 0.005, roads=[("primary", "road")] * 2),
                edge("pedestrian_crossing", 0.005),
                edge("footway"),
            ),
            SPM,
        )
        slip, road = reading.crossings
        assert slip.slip and not road.slip
        assert slip.penalty_s == walk_pricing.UNSIGNALLED_S[BUSY] + walk_pricing.SLIP_LANE_S
        assert road.penalty_s == walk_pricing.UNSIGNALLED_S[BUSY]

    def test_a_divided_road_is_one_crossing_signalled_where_either_half_is(self) -> None:
        reading = walk_pricing.read(
            trace(
                edge("footway", roads=[("primary", "road")]),
                edge("footway", 0.012, roads=[("primary", "road")], node_signal=True),
                edge("footway"),
            ),
            SPM,
        )
        [crossing] = reading.crossings
        assert crossing.signal and reading.penalty_s == 0

    def test_along_a_carriageway_only_a_side_road_passed_straight_on_is_crossed(self) -> None:
        straight = walk_pricing.read(
            trace(
                edge("road", 0.05, "residential", names=["F St"], roads=[("primary", "road")] * 2),
                edge("road", 0.05, "residential", names=["F St"]),
            ),
            SPM,
        )
        assert [c.level for c in straight.crossings] == [BUSY]
        assert straight.crossings[0].own == frozenset({"F St"})
        turning = walk_pricing.read(
            trace(
                edge("road", 0.05, "residential", names=["F St"], roads=[("primary", "road")]),
                edge("road", 0.05, "residential", names=["3rd St"]),
            ),
            SPM,
        )
        assert turning.crossings == ()

    def test_a_footway_meeting_only_paths_is_no_crossing(self) -> None:
        reading = walk_pricing.read(
            trace(edge("footway"), edge("footway")),
            SPM,
        )
        assert reading.crossings == () and reading.penalty_s == 0


def leg(seconds: float, metres: float, shape="abc") -> dict:
    return {"shape": shape, "summary": {"time": seconds, "length": metres / 1000}}


class TestChoose:
    def test_the_way_with_the_least_time_and_charges_is_taken(self) -> None:
        # The router's first way crosses a busy road with no signal; its second walks 60 s
        # further to cross at the signal.
        answer = {
            "trip": {"legs": [leg(600, 800, "first")]},
            "alternates": [{"trip": {"legs": [leg(660, 880, "second")]}}],
        }
        unsignalled = trace(edge("footway", roads=[("primary", "road")] * 2), edge("footway"))
        signalled = trace(
            edge("footway", roads=[("primary", "road")] * 2, node_signal=True), edge("footway")
        )
        traces = {"first": unsignalled, "second": signalled}
        asked = []

        def ask(action, payload):
            asked.append((action, payload))
            return traces[payload["encoded_polyline"]]

        chosen = walk_pricing.choose(answer, ask, {"pedestrian": {"walking_speed": 4.8}})
        assert chosen.leg["shape"] == "second"
        assert [i for i, _s in chosen.scores] == [0, 1]
        assert all(a == "trace_attributes" for a, _p in asked)
        assert asked[0][1]["costing_options"] == {"pedestrian": {"walking_speed": 4.8}}

    def test_a_way_not_worth_its_extra_time_is_not_taken(self) -> None:
        answer = {
            "trip": {"legs": [leg(600, 800, "first")]},
            "alternates": [{"trip": {"legs": [leg(1200, 1600, "second")]}}],
        }
        unsignalled = trace(edge("footway", roads=[("primary", "road")] * 2), edge("footway"))
        quiet = trace(edge("footway"), edge("footway"))
        traces = {"first": unsignalled, "second": quiet}
        chosen = walk_pricing.choose(answer, lambda _a, p: traces[p["encoded_polyline"]])
        assert chosen.leg["shape"] == "first"

    def test_a_trace_not_answered_leaves_the_routers_way(self) -> None:
        answer = {
            "trip": {"legs": [leg(600, 800, "first")]},
            "alternates": [{"trip": {"legs": [leg(300, 400, "second")]}}],
        }
        chosen = walk_pricing.choose(answer, lambda _a, _p: None)
        assert chosen.leg["shape"] == "first" and chosen.crossings == ()
        assert walk_pricing.choose({"trip": {"legs": []}}, lambda _a, _p: None) is None


class TestCrossingTurns:
    def test_the_crossings_said_are_named_by_the_road_crossed_never_the_one_walked(self) -> None:
        reading = walk_pricing.read(
            trace(
                edge("road", 0.05, "residential", names=["F St"], roads=[("primary", "road")] * 2),
                edge("road", 0.05, "residential", names=["F St"]),
            ),
            SPM,
        )
        located = [
            {
                "edges": [
                    {
                        "distance": 0.0,
                        "edge": {"classification": {"use": "road"}},
                        "edge_info": {"names": ["F St"]},
                    },
                    {
                        "distance": 0.0,
                        "edge": {"classification": {"use": "road"}},
                        "edge_info": {"names": ["Pratt St"]},
                    },
                ]
            }
        ]
        asked = []

        def ask(action, payload):
            asked.append((action, payload))
            return located

        [turn] = walk_pricing.crossing_turns(reading.crossings, ask)
        assert turn["movement"] == "cross" and turn["street"] == "Pratt St"
        assert (turn["control"], turn["busy"], turn["slip"]) == ("none", True, False)
        assert asked[0][0] == "locate" and asked[0][1]["costing"] == "auto"
        # Nothing to say, nothing asked.
        assert walk_pricing.crossing_turns((), ask) == [] and len(asked) == 1

    def test_a_crossing_unnamed_where_the_router_cannot_say(self) -> None:
        reading = walk_pricing.read(
            trace(edge("footway", roads=[("primary", "road")] * 2), edge("footway")), SPM
        )
        [turn] = walk_pricing.crossing_turns(reading.crossings, lambda _a, _p: None)
        assert turn["street"] is None


class TestWalkTurns:
    def test_crossings_fall_among_the_turns_where_they_are_along_the_line(self) -> None:
        shape = [(-77.0, 38.9), (-77.0, 38.901), (-77.0, 38.902), (-77.001, 38.902)]
        maneuvers = [
            {"type": 1, "begin_shape_index": 0, "length": 0.2},
            {"type": 15, "begin_shape_index": 2, "length": 0.1, "street_names": ["G St"]},
        ]
        crossing = {"movement": "cross", "street": "F St", "point": [-77.0, 38.901]}
        turns = walk_turns.turns_of({"maneuvers": maneuvers}, shape, [crossing])
        assert [t["movement"] for t in turns] == ["cross", "left"]

    def test_a_directions_request_asks_for_the_routers_other_ways(self) -> None:
        payload = walk_turns.directions({"costing": "pedestrian"})
        assert payload["alternates"] == walk_pricing.ALTERNATES


def test_the_router_asker_gives_none_where_the_router_does_not_answer(monkeypatch) -> None:
    def refuse(*_args):
        raise routing.RouterRefused(400, 442, "no route")

    monkeypatch.setattr(routing, "_call", refuse)
    ask = routing.walk_asker(routing.Deadline(routing.clock() + 30, 5))
    assert ask("trace_attributes", {}) is None
    late = routing.walk_asker(routing.Deadline(routing.clock() + 0.1, 5))
    assert late("trace_attributes", {}) is None
