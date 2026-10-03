"""POST /api/route's intersections, calm search and detour (OWNER-DECISIONS items
163-172), through the real view, the real segment table and a stand-in router.

The world: a quiet street (way 101, LTS 2) runs east along a parallel of
latitude and crosses a four-lane arterial (way 202, LTS 4, 40 mph) at the third
vertex. The router's answers carry what the live standard router's do:
headings, `use`, road class and the other roads at each node on
`/trace_attributes`; and on `/locate` at the node, every directed edge there
(arriving at the node, `percent_along` 1, or leaving it, 0) with its way, its
heading, its car access and the stop, yield and signal flags of its end, and
the node itself.
"""

from __future__ import annotations

import pytest
from django.db import connection
from test_route_api import (
    VERTICES,
    FakeRouter,
    encode_polyline6,
    good_body,
    post,
    route_answer,
)

from core import junctions, presets, routing

# A route test plans a weekday ride unless it says otherwise: the weekend router
# is chosen by the day the suite runs on (conftest `weekday_clock`).
pytestmark = pytest.mark.usefixtures("weekday_clock")


db = pytest.mark.django_db(transaction=True)

JUNCTION = VERTICES[2]  # (-77.035, 38.9)
IN_EDGE = 5_550_001


@pytest.fixture
def router(monkeypatch):
    def install(fake: FakeRouter) -> FakeRouter:
        monkeypatch.setattr(routing, "_transport", fake)
        return fake

    return install


def line(*points) -> str:
    return "LINESTRING(" + ", ".join(f"{lon} {lat}" for lon, lat in points) + ")"


def add_segments(live: str, rows) -> None:
    with connection.cursor() as cursor:
        for way, ordinal, tier, wkt, speed, lanes, oneway in rows:
            cursor.execute(
                f"INSERT INTO {live}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                "stress_rule, road_speed_mph, road_lanes, road_oneway) "
                "VALUES (%s, %s, ST_GeomFromText(%s, 4326), %s, 'test', %s, %s, %s)",
                [way, ordinal, wkt, tier, speed, lanes, oneway],
            )
    junctions._has_trait_columns_seen = False


@pytest.fixture
def arterial(segment_schemas):
    """The quiet street, and the arterial across it at the junction."""
    live, _staging = segment_schemas
    add_segments(
        live,
        [
            (101, 0, 2, line(*VERTICES[0:3]), 25, 1, False),
            (101, 1, 2, line(*VERTICES[2:5]), 25, 1, False),
            (202, 0, 4, line((JUNCTION[0], JUNCTION[1] - 0.003), JUNCTION), 40, 2, False),
            (202, 1, 4, line(JUNCTION, (JUNCTION[0], JUNCTION[1] + 0.003)), 40, 2, False),
        ],
    )
    return live


def trace_edges(vertices, junction_index: int, cross_class="primary", out_use="road"):
    """Two edges of way 101 meeting at `junction_index`, with the arterial at the node."""
    first = {
        "way_id": 101,
        "begin_shape_index": 0,
        "end_shape_index": junction_index,
        "length": 0.9,
        "begin_heading": 90,
        "end_heading": 90,
        "road_class": "residential",
        "use": "road",
        "id": {"value": IN_EDGE},
        "end_node": {
            "intersecting_edges": [
                {"use": "road", "road_class": cross_class, "driveability": "both"},
                {"use": "road", "road_class": cross_class, "driveability": "both"},
            ]
        },
    }
    second = {
        "way_id": 101,
        "begin_shape_index": junction_index,
        "end_shape_index": len(vertices) - 1,
        "length": 1.8,
        "begin_heading": 90,
        "end_heading": 90,
        "road_class": "residential",
        "use": out_use,
        "id": {"value": IN_EDGE + 1},
    }
    return [first, second]


NODE = 9_000_001


def _edge(edge_id, way, end_node, along, heading, stop=False, names=()):
    return {
        "edge_id": {"value": edge_id},
        "percent_along": along,
        "heading": heading,
        "correlated_lon": JUNCTION[0],
        "correlated_lat": JUNCTION[1],
        "edge": {
            "end_node": {"value": end_node},
            "classification": {"use": "road", "link": False},
            "access": {"car": True},
            "stop_sign": stop,
            "yield_sign": False,
            "traffic_signal": False,
        },
        "edge_info": {"way_id": way, "names": list(names)},
    }


def locate_answer(stop=False, signal=False):
    """The crossroads at the junction: way 101 east-west through it (the route
    arrives from the west by IN_EDGE and leaves east by IN_EDGE + 1), way 202
    north-south through it."""

    def locate(payload):
        return [
            {
                "nodes": [
                    {
                        "node_id": {"value": NODE},
                        "traffic_signal": signal,
                        "lon": JUNCTION[0],
                        "lat": JUNCTION[1],
                    }
                ],
                "edges": [
                    _edge(IN_EDGE, 101, NODE, 1.0, 90.0, stop=stop),
                    _edge(IN_EDGE + 1, 101, 801, 0.0, 90.0),
                    _edge(IN_EDGE + 2, 101, 802, 0.0, 270.0),
                    _edge(IN_EDGE + 3, 101, NODE, 1.0, 270.0),
                    _edge(IN_EDGE + 4, 202, 803, 0.0, 0.0, names=["Arterial"]),
                    _edge(IN_EDGE + 5, 202, NODE, 1.0, 180.0, names=["Arterial"]),
                    _edge(IN_EDGE + 6, 202, 804, 0.0, 180.0, names=["Arterial"]),
                    _edge(IN_EDGE + 7, 202, NODE, 1.0, 0.0, names=["Arterial"]),
                ],
            }
            for _ in payload["locations"]
        ]

    return locate


class Router(FakeRouter):
    """A FakeRouter whose `/locate` is a function of the request."""

    def __init__(self, answers: dict, locate=None) -> None:
        super().__init__(answers)
        self.locate = locate or locate_answer()

    def __call__(self, url: str, payload: dict, timeout: float):
        if url.endswith("/locate"):
            self.calls.append((url, payload))
            return self.locate(payload)
        return super().__call__(url, payload, timeout)


def world(length_km=2.7, locate=None, **kwargs) -> Router:
    vertices = VERTICES
    return Router(
        {
            "route": route_answer([(vertices, length_km, [1.0] * 5)]),
            "trace_attributes": {
                "units": "kilometers",
                "shape": encode_polyline6(vertices),
                "edges": trace_edges(vertices, 2, **kwargs),
            },
        },
        locate=locate,
    )


@db
class TestIntersectionsInTheAnswer:
    def test_an_unsignalised_crossing_of_the_arterial_is_a_red_marker_with_its_reason(
        self, client, arterial, router
    ) -> None:
        router(world())
        body = post(client, good_body()).json()
        (junction,) = body["intersections"]
        assert junction["severity"] == "red"
        assert junction["crossed_tier"] == 4
        assert junction["movement"] == "straight" and junction["kind"] == "crossing"
        assert junction["control"] == "none"
        assert junction["reason"] == "Crossing a 4-lane 40 mph (64 km/h) road, no signal mapped"
        assert (junction["lon"], junction["lat"]) == pytest.approx(JUNCTION)
        assert junction["m"] == 900  # the first edge's length
        assert junction["cost_ft"] >= 2000

    def test_a_stop_sign_on_the_riders_side_is_said(self, client, arterial, router) -> None:
        fake = world()
        fake.locate = locate_answer(stop=True)
        router(fake)
        (junction,) = post(client, good_body()).json()["intersections"]
        assert junction["control"] == "stop"
        assert junction["reason"].endswith("stop sign on your side")

    def test_a_traffic_signal_makes_it_cheap_and_unmarked(self, client, arterial, router) -> None:
        fake = world()
        fake.locate = locate_answer(signal=True)
        router(fake)
        body = post(client, good_body()).json()
        assert body["intersections"] == []

    def test_the_router_is_asked_about_the_junction_by_its_node(
        self, client, arterial, router
    ) -> None:
        fake = router(world())
        post(client, good_body())
        asked = [p for url, p in fake.calls if url.endswith("/locate")]
        assert asked and asked[0]["verbose"] is True and asked[0]["costing"] == "bicycle"
        location = asked[0]["locations"][0]
        assert (location["lon"], location["lat"]) == pytest.approx(JUNCTION)
        assert location["radius"] == 1
        traced = [p for url, p in fake.calls if url.endswith("/trace_attributes")][0]
        wanted = traced["filters"]["attributes"]
        for attribute in (
            "edge.id",
            "edge.begin_heading",
            "edge.end_heading",
            "node.intersecting_edge.use",
        ):
            assert attribute in wanted

    def test_a_quiet_cross_street_is_never_flagged_and_asks_the_router_nothing(
        self, client, segment_schemas, router
    ) -> None:
        live, _staging = segment_schemas
        add_segments(
            live,
            [
                (101, 0, 2, line(*VERTICES[0:5]), 25, 1, False),
                (
                    202,
                    0,
                    1,
                    line((JUNCTION[0], JUNCTION[1] - 0.003), (JUNCTION[0], JUNCTION[1] + 0.003)),
                    25,
                    1,
                    False,
                ),
            ],
        )
        fake = router(world(cross_class="residential"))
        body = post(client, good_body()).json()
        assert body["intersections"] == []
        assert not [1 for url, _ in fake.calls if url.endswith("/locate")]

    def test_a_way_beside_the_route_that_shares_no_node_is_not_crossed(
        self, client, segment_schemas, router
    ) -> None:
        """A sidepath three metres from a carriageway: the router has no road edge
        at the node, so nothing is crossed however close the segment is."""
        live, _staging = segment_schemas
        add_segments(
            live,
            [
                (101, 0, 1, line(*VERTICES[0:5]), None, None, None),
                (
                    202,
                    0,
                    4,
                    line(
                        (JUNCTION[0] + 0.00002, JUNCTION[1] - 0.003),
                        (JUNCTION[0] + 0.00002, JUNCTION[1] + 0.003),
                    ),
                    40,
                    2,
                    False,
                ),
            ],
        )
        fake = world()
        fake.answers["trace_attributes"]["edges"][0]["end_node"] = {"intersecting_edges": []}
        router(fake)
        assert post(client, good_body()).json()["intersections"] == []

    def test_a_trace_without_headings_has_an_empty_list_not_a_failure(
        self, client, arterial, router
    ) -> None:
        fake = world()
        for edge in fake.answers["trace_attributes"]["edges"]:
            for key in ("begin_heading", "end_heading", "id", "end_node", "use", "road_class"):
                edge.pop(key, None)
        router(fake)
        response = post(client, good_body())
        assert response.status_code == 200
        assert response.json()["intersections"] == []

    def test_a_table_before_the_traits_still_names_the_road(
        self, client, segment_schemas, router
    ) -> None:
        live, _staging = segment_schemas
        with connection.cursor() as cursor:
            for column in ("road_speed_mph", "road_lanes", "road_oneway"):
                cursor.execute(f"ALTER TABLE {live}.segment DROP COLUMN {column}")
            for way, tier, pts in (
                (101, 2, VERTICES[0:5]),
                (202, 4, [(JUNCTION[0], JUNCTION[1] - 0.003), (JUNCTION[0], JUNCTION[1] + 0.003)]),
            ):
                cursor.execute(
                    f"INSERT INTO {live}.segment "
                    "(osm_way_id, ordinal, geometry, stress_tier, stress_rule) "
                    "VALUES (%s, 0, ST_GeomFromText(%s, 4326), %s, 'test')",
                    [way, line(*pts), tier],
                )
        junctions._has_trait_columns_seen = False
        router(world())
        (junction,) = post(client, good_body()).json()["intersections"]
        assert junction["reason"] == "Crossing a heavy-traffic road (LTS 4), no signal mapped"


@db
class TestEveryRideType:
    @pytest.mark.parametrize("name", sorted(presets.PRESETS))
    def test_every_ride_type_has_the_list(self, name, client, arterial, router) -> None:
        router(world())
        body = post(client, good_body(name)).json()
        assert isinstance(body["intersections"], list)
        assert len(body["intersections"]) == 1

    def test_a_mass_ride_is_coloured_by_the_roads_tier(self, client, arterial, router) -> None:
        """Item 138: orange for LTS 3, red for LTS 4 or Avoid."""
        fake = world()
        fake.locate = locate_answer(signal=True)
        router(fake)
        (junction,) = post(client, good_body("mass-ride")).json()["intersections"]
        assert junction["severity"] == "red"
        assert junction["control"] == "signal", (
            "a busy crossing with a light is still marked for a group"
        )

    def test_every_junction_row_says_which_group_it_is_in_none_on_a_lone_crossing(
        self, client, arterial, router
    ) -> None:
        """Items 233, 234: additive. A Mass Ride's lone signalized crossing is no group; the
        list of groups is there and empty, and every other ride type has the same."""
        fake = world()
        fake.locate = locate_answer(signal=True)
        router(fake)
        for name in ("mass-ride", "default"):
            body = post(client, good_body(name)).json()
            assert all(row["group"] is None for row in body["intersections"])
            assert body["intersection_groups"] == []
            if name == "mass-ride":
                assert len(body["intersections"]) == 1

    def test_a_mass_ride_does_not_search(self, client, arterial, router) -> None:
        fake = router(world())
        body = post(client, good_body("mass-ride")).json()
        assert body["calm_search"] is None
        # (Mass Ride's hills slider asks for a second route of its own; none is a search.)
        assert not [
            p for url, p in fake.calls if url.endswith("/route") and "exclude_locations" in p
        ]


@db
class TestTheSearchInTheAnswer:
    def test_a_default_ride_over_a_red_crossing_asks_the_router_once_more_without_the_approach(
        self, client, arterial, router
    ) -> None:
        fake = router(world())
        body = post(client, good_body()).json()
        routes = [p for url, p in fake.calls if url.endswith("/route")]
        assert len(routes) == 2
        assert "exclude_locations" not in routes[0]
        (excluded,) = routes[1]["exclude_locations"]
        assert excluded["lon"] < JUNCTION[0], "a point on the edge the route arrives by"
        assert body["calm_search"]["rate"] == 0.0
        assert body["calm_search"]["rounds"] == 1

    def test_the_top_of_the_slider_has_a_calm_rate(self, client, arterial, router) -> None:
        router(world())
        body = post(client, {**good_body(), "stress": 100}).json()
        assert body["calm_search"]["rate"] == presets.CALM_RATE_MAX
        assert body["dials"]["stress"] == 100

    def test_the_trail_seek_runs_from_the_top_of_the_old_slider(
        self, client, arterial, router
    ) -> None:
        """FOLLOWUP-TRAIL-SEEK: at 100 (rate 10) the search also looks for trail
        corridors, and says so; below that it does not."""
        router(world())
        top = post(client, {**good_body(), "stress": 100}).json()["calm_search"]
        assert set(top["seek"]) == {
            "corridors",
            "asked",
            "routes",
            "taken",
            "limited",
            "whole_trip",
            "tried",
            "legs",
        }
        assert top["seek"]["legs"] == 1
        below = post(client, {**good_body(), "stress": 95}).json()["calm_search"]
        assert below["seek"] is None

    def test_no_ride_has_a_trail_credit_and_the_answer_says_none(
        self, client, arterial, router
    ) -> None:
        """OWNER-DECISIONS 257 supersedes 202: a quiet street counts the same as a trail, so the
        answer has no credit to report, on Trailmaxxing or any ride type, at any position."""
        router(world())
        for name in ("trailmaxxing", "default", "group-ride"):
            for stress in (100, 90):
                found = post(client, {**good_body(name), "stress": stress}).json()["calm_search"]
                assert not {"trail_credit", "trail_before_m", "trail_after_m"} & set(found), name

    def test_a_ride_on_the_no_trail_graph_is_searched_as_roadway_only(
        self, client, arterial, router, monkeypatch
    ) -> None:
        """Mutation review F14: the plan's search context says a ride on the
        no-trail graph is roadway-only, which its stress reading and the seek's
        early exit read (a seek for trails on a graph that has none). Mass Ride
        is the one preset on that graph today; its search has rules of its own,
        so the context is caught where the plan builds it."""
        from core import refine

        built: list = []
        real = refine.Context

        def capture(*args, **kwargs):
            context = real(*args, **kwargs)
            built.append(context)
            return context

        monkeypatch.setattr(refine, "Context", capture)
        router(world())
        assert post(client, good_body("mass-ride")).status_code == 200
        assert post(client, good_body("group-ride")).status_code == 200
        assert [(c.variant, c.roadway_only) for c in built] == [
            ("no-trail", True),
            ("standard", False),
        ]

    def test_a_long_ride_says_why_the_calm_search_did_not_run(
        self, client, arterial, router
    ) -> None:
        router(world())
        response = post(
            client, {**good_body(), "stress": 100, "points": [[-77.0, 38.9], [-76.4, 38.9]]}
        )
        assert response.status_code == 200
        search = response.json()["calm_search"]
        assert (
            search["limited"] == "span"
            and search["rate"] == presets.CALM_RATE_MAX
            and search["rounds"] == 0
        )

    def test_nothing_is_said_where_no_calm_search_was_asked_for(
        self, client, arterial, router
    ) -> None:
        router(world())
        response = post(client, {**good_body(), "points": [[-77.0, 38.9], [-76.4, 38.9]]})
        assert response.json()["calm_search"] is None

    def test_a_ride_with_a_via_is_searched_too(self, client, arterial, router) -> None:
        router(world())
        body = post(
            client,
            {**good_body(), "points": [list(VERTICES[0]), list(VERTICES[2]), list(VERTICES[4])]},
        )
        assert body.status_code == 200


class TestWhyTheSearchDoesNotRun:
    def limit(self, **kwargs):
        defaults = {
            "preset_name": "default",
            "points": [[0, 0], [0.1, 0]],
            "long_ride": False,
            "seeking": False,
            "deadline": routing.Deadline(routing.clock() + 40, 35),
        }
        return routing._refine_limit(**(defaults | kwargs))

    def test_it_runs_for_an_ordinary_plan(self) -> None:
        assert self.limit() is None

    def test_a_mass_ride_has_its_own_rules(self) -> None:
        assert self.limit(preset_name="mass-ride") == "mass_ride"

    @pytest.mark.parametrize(
        ("kwargs", "why"),
        [
            ({"points": [[0, 0]]}, "points"),
            ({"long_ride": True}, "long_ride"),
            ({"seeking": True}, "seeking"),
            ({"points": [[0, 0], [0.5, 0]]}, "span"),
        ],
    )
    def test_the_reasons(self, kwargs, why) -> None:
        assert self.limit(**kwargs) == why

    def test_exactly_the_span_still_runs(self, monkeypatch) -> None:
        from core import refine
        from routemaker.geo import Point, haversine

        points = [[0, 0], [0.1, 0]]
        monkeypatch.setattr(refine, "REFINE_MAX_SPAN_M", haversine(Point(0, 0), Point(0.1, 0)))
        assert self.limit(points=points) is None

    def test_without_the_time_for_a_round(self) -> None:
        assert self.limit(deadline=routing.Deadline(routing.clock() + 3, 35)) == "time"


@db
class TestDetour:
    def test_a_route_within_the_straight_lines_allowance_has_none(
        self, client, arterial, router
    ) -> None:
        router(world(length_km=2.8))
        assert post(client, good_body()).json()["detour"] is None

    def test_a_longer_route_is_compared_with_the_direct_one(self, client, arterial, router) -> None:
        """A direct route at the traffic tolerant end, and the answer's ratio to it."""
        fake = Router(
            {
                "route": [
                    route_answer([(VERTICES, 9.0, [1.0] * 5)]),  # the plan's own route
                    route_answer([(VERTICES, 9.0, [1.0] * 5)]),  # the search's
                    route_answer([(VERTICES, 3.0, [1.0] * 5)]),  # the direct probe
                ],
                "trace_attributes": {
                    "units": "kilometers",
                    "shape": encode_polyline6(VERTICES),
                    "edges": trace_edges(VERTICES, 2),
                },
            }
        )
        router(fake)
        detour = post(client, good_body()).json()["detour"]
        assert detour["basis"] == "direct_route"
        assert detour["reference_m"] == 3000.0
        assert detour["ratio"] == 3.0
        assert detour["extra_m"] == 6000.0
        assert detour["level"] == "strong"
        probe = [p for url, p in fake.calls if url.endswith("/route")][-1]
        assert probe["costing_options"]["bicycle"]["use_roads"] == 1.0
        assert probe["costing_options"]["bicycle"]["use_hills"] == 1.0
        assert "exclude_locations" not in probe and "alternates" not in probe

    def test_a_mass_ride_is_compared_with_the_straight_line(self, client, arterial, router) -> None:
        router(world(length_km=9.0))
        detour = post(client, good_body("mass-ride")).json()["detour"]
        assert detour["basis"] == "straight_line"
        assert detour["level"] == "warning"

    def test_at_default_a_modest_detour_is_not_probed(self, client, arterial, router) -> None:
        """The second route is asked for from just above Default, or where the
        route is twice the straight line: below that the ratio to the direct
        route is at most 1.5 times, a note the rider did not ask a calm detour for."""
        fake = router(world(length_km=4.2))
        detour = post(client, good_body()).json()["detour"]
        probes = [
            p
            for url, p in fake.calls
            if url.endswith("/route") and p["costing_options"]["bicycle"]["use_roads"] == 1.0
        ]
        assert probes == []
        assert detour["basis"] == "straight_line" and detour["level"] is None

    def test_above_default_it_is_probed(self, client, arterial, router) -> None:
        answer = route_answer([(VERTICES, 4.2, [1.0] * 5)])
        fake = router(
            Router(
                {
                    "route": [answer] * 3,
                    "trace_attributes": {
                        "units": "kilometers",
                        "shape": encode_polyline6(VERTICES),
                        "edges": trace_edges(VERTICES, 2),
                    },
                }
            )
        )
        detour = post(client, {**good_body(), "stress": 75}).json()["detour"]
        probes = [
            p
            for url, p in fake.calls
            if url.endswith("/route") and p["costing_options"]["bicycle"]["use_roads"] == 1.0
        ]
        assert len(probes) == 1
        assert detour["basis"] == "direct_route"
