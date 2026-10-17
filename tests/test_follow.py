# ruff: noqa: F811 (the route tests' fixtures, imported by name)
"""Following an opened file's line exactly (core.follow; POST /api/route `follow`).

Stephen 2026-10-17: "it's still not possible to add in a gpx identical route". With the file's
line sent, the plan's router call is a `/trace_route` of that line on the ride type's graph, and
the route is what it matched; gaps where the ride type cannot ride the line are joined by the
router's own route. The router is the fake of tests/test_route_api.py.
"""

from __future__ import annotations

import json

import pytest
from test_route_api import (  # noqa: F401 (fixtures)
    VERTICES,
    FakeRouter,
    encode_polyline6,
    post,
    route_answer,
    router,
    segments,
    trace_answer,
)

from core import api, follow, routing

pytestmark = pytest.mark.usefixtures("weekday_clock")
db = pytest.mark.django_db(transaction=True)

BBOX = (-78.0, 38.0, -76.0, 40.0)


def leg(vertices, km, heights=None, maneuvers=None) -> dict:
    out = {"shape": encode_polyline6(vertices), "summary": {"length": km, "time": 100.0 * km}}
    if heights is not None:
        out["elevation"] = heights
    if maneuvers is not None:
        out["maneuvers"] = maneuvers
    return out


def shape_of(leg_body: dict) -> list:
    return routing.decode_polyline6(leg_body["shape"])


class TestTheLine:
    def test_a_line_is_checked_and_decoded(self) -> None:
        encoded = encode_polyline6(VERTICES)
        assert follow.checked_line(encoded, BBOX) == pytest.approx(VERTICES)
        with pytest.raises(follow.LineProblem, match="fewer than two"):
            follow.checked_line(encode_polyline6(VERTICES[:1]), BBOX)
        with pytest.raises(follow.LineProblem, match="outside"):
            follow.checked_line(encode_polyline6([(-79.0, 38.9), (-77.0, 38.9)]), BBOX)
        with pytest.raises(follow.LineProblem, match="more than 5,000"):
            follow.checked_line(
                encode_polyline6([(-77.0 + i * 1e-6, 38.9) for i in range(5001)]), BBOX
            )
        with pytest.raises(follow.LineProblem, match="longer than 124 mi"):
            follow.checked_line(encode_polyline6([(-77.9, 38.1), (-76.1, 39.9)]), BBOX)
        with pytest.raises(follow.LineProblem, match="precision 6"):
            follow.checked_line("~", BBOX)

    def test_the_plans_points_split_the_line_in_order_never_at_its_ends(self) -> None:
        line = VERTICES
        points = [VERTICES[0], (-77.0351, 38.9001), (-77.0301, 38.9), VERTICES[-1]]
        assert follow.split_indices(line, points) == [2, 3]
        # A point that would go back along the line, or sits on an end, is left out.
        assert follow.split_indices(line, [VERTICES[0], VERTICES[3], VERTICES[1], VERTICES[4]]) == [
            3
        ]
        assert follow.split_indices(line, [VERTICES[0], VERTICES[0], VERTICES[4]]) == [1]
        assert follow.split_indices(line, VERTICES[:1] + VERTICES[-1:]) == []

    def test_the_trace_request_is_the_plans_own_with_the_line_as_its_shape(self) -> None:
        plan_request = {
            "locations": [{"lon": 0, "lat": 0}],
            "costing": "bicycle",
            "costing_options": {"bicycle": {"use_roads": 0.2}},
            "elevation_interval": 30,
            "directions_type": "maneuvers",
            "alternates": 2,
            "exclude_polygons": [[[0, 0]]],
        }
        asked = follow.request_for(VERTICES, [VERTICES[0], VERTICES[2], VERTICES[-1]], plan_request)
        assert "locations" not in asked and "alternates" not in asked
        assert "exclude_polygons" not in asked
        assert asked["costing_options"] == {"bicycle": {"use_roads": 0.2}}
        assert asked["elevation_interval"] == 30 and asked["shape_match"] == "map_snap"
        assert asked["trace_options"] == {"search_radius": follow.SEARCH_RADIUS_M}
        assert [p.get("type") for p in asked["shape"]] == [None, None, "break_through", None, None]


class TestJoining:
    def test_the_routers_way_across_a_gap_keeps_the_ride_types_rules(self, monkeypatch) -> None:
        calls = []
        two_pieces = {
            "trip": {"legs": [leg(VERTICES[0:2], 0.9)]},
            "alternates": [{"trip": {"legs": [leg(VERTICES[2:5], 1.3)]}}],
        }

        def fake(variant, endpoint, payload, deadline):
            calls.append((endpoint, payload))
            if endpoint == "trace_route":
                return two_pieces
            if endpoint == "route":
                return {"trip": {"legs": [leg(VERTICES[1:3], 0.4)]}}
            return {"edges": []}

        monkeypatch.setattr(routing, "_call", fake)
        asked = follow.request_for(
            VERTICES,
            VERTICES[:1] + VERTICES[-1:],
            {"costing_options": {"bicycle": dict(follow.IGNORED)}},
        )
        answer = routing._followed("standard", asked, routing.Deadline(1e12, 10))
        route = [p for endpoint, p in calls if endpoint == "route"]
        assert len(route) == 1 and route[0]["costing_options"] == {"bicycle": {}}
        assert "shape" not in route[0] and len(route[0]["locations"]) == 2
        assert answer["against_traffic"] == []
        assert routing._trip_line(answer["trip"]) == pytest.approx(VERTICES)

    def test_legs_merge_with_their_shared_vertex_once(self) -> None:
        a = leg(VERTICES[0:2], 0.9, [10.0, 11.0], [{"type": 1}, {"type": 4}])
        b = leg(VERTICES[1:3], 0.4, [11.0, 12.0], [{"type": 1, "begin_shape_index": 0}])
        merged = follow.merge_legs(a, b, 30)
        assert shape_of(merged) == pytest.approx(VERTICES[0:3])
        assert merged["summary"]["length"] == pytest.approx(1.3)
        assert merged["elevation"] == [10.0, 11.0, 12.0]
        # The first leg's arrival goes; the second's manoeuvres move along the joined shape.
        assert merged["maneuvers"] == [{"type": 1}, {"type": 1, "begin_shape_index": 1}]
        # A leg with no heights gets none for its length.
        plain = follow.merge_legs(
            leg(VERTICES[0:2], 0.06, [1.0, 2.0, 3.0]), leg(VERTICES[1:3], 0.06), 30
        )
        assert plain["elevation"] == [1.0, 2.0, 3.0, None, None]

    def test_a_break_in_the_match_is_joined_by_the_routers_route(self) -> None:
        answer = {
            "trip": {"legs": [leg(VERTICES[0:2], 0.9)], "summary": {"length": 0.9}},
            "alternates": [{"trip": {"legs": [leg(VERTICES[2:5], 1.3)]}}],
        }
        asked = []

        def route_between(a, b):
            asked.append((a, b))
            return leg([a, b], 0.4)

        trip = follow.joined(answer, VERTICES, route_between, 30)["trip"]
        assert asked == [(pytest.approx(VERTICES[1]), pytest.approx(VERTICES[2]))]
        assert len(trip["legs"]) == 1
        assert shape_of(trip["legs"][0]) == pytest.approx(VERTICES)
        assert trip["summary"]["length"] == pytest.approx(2.6)

    def test_a_break_with_no_route_across_is_a_refusal(self) -> None:
        answer = {
            "trip": {"legs": [leg(VERTICES[0:2], 0.9)]},
            "alternates": [{"trip": {"legs": [leg(VERTICES[2:5], 1.3)]}}],
        }
        with pytest.raises(routing.RouterRefused):
            follow.joined(answer, VERTICES, lambda a, b: None, 30)

    def test_a_match_short_of_the_files_ends_is_joined_to_them(self) -> None:
        answer = {"trip": {"legs": [leg(VERTICES[1:4], 0.8)]}}
        trip = follow.joined(answer, VERTICES, lambda a, b: leg([a, b], 0.9), 30)["trip"]
        assert shape_of(trip["legs"][0]) == pytest.approx(VERTICES)
        # Where no route reaches an end, the match is kept as it is.
        trip = follow.joined(answer, VERTICES, lambda a, b: None, 30)["trip"]
        assert shape_of(trip["legs"][0]) == pytest.approx(VERTICES[1:4])


class TestAgainstTraffic:
    def test_stretches_against_one_way_traffic_are_said_by_street(self) -> None:
        def edge(name, km, allowed, forward):
            return {
                "names": [name] if name else [],
                "length": km,
                "traversability": allowed,
                "forward": forward,
            }

        edges = [
            edge("Row 0", 0.2, "both", False),
            edge("Row 2", 0.1, "forward", False),
            edge("Row 2", 0.2, "forward", False),
            edge("Row 4", 0.3, "backward", False),
            edge("Col 1", 0.1, "backward", True),
            edge(None, 0.01, "forward", False),
        ]
        asked = []

        def trace_attributes(payload):
            asked.append(payload)
            return {"edges": edges}

        said = follow.against_traffic(VERTICES, trace_attributes, {"bicycle": follow.IGNORED})
        assert said == [
            {"name": "Row 2", "distance_m": 300.0},
            {"name": "Col 1", "distance_m": 100.0},
        ]
        assert asked[0]["costing_options"] == {"bicycle": follow.IGNORED}

    def test_a_walk_refused_is_snapped_and_a_router_gone_says_nothing(self) -> None:
        answers = [routing.RouterRefused(400, 443, "no walk"), {"edges": []}]

        def refusing(payload):
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

        assert follow.against_traffic(VERTICES, refusing, {}) == []

        def gone(payload):
            raise routing.RouterUnavailable("down")

        assert follow.against_traffic(VERTICES, gone, {}) is None

    def test_the_ignored_rules_are_taken_out_for_the_routers_own_way(self) -> None:
        options = {"bicycle": {"use_roads": 0.2, **follow.IGNORED}}
        assert follow.without_ignored(options) == {"bicycle": {"use_roads": 0.2}}


def follow_body(preset: str = "mass-ride", **extra) -> dict:
    return {
        "points": [list(VERTICES[0]), list(VERTICES[2]), list(VERTICES[-1])],
        "preset": preset,
        "follow": encode_polyline6(VERTICES),
        **extra,
    }


def traced_router() -> FakeRouter:
    two_legs = route_answer(
        [(VERTICES[0:3], 1.3, [10.0, 20.0]), (VERTICES[2:5], 0.9, [20.0, 30.0])]
    )
    return FakeRouter(
        {
            "trace_route": two_legs,
            "route": route_answer([(VERTICES, 2.2, [10.0, 20.0, 15.0, 30.0])]),
            "trace_attributes": lambda payload: trace_answer(
                routing.decode_polyline6(payload["encoded_polyline"]),
                [(101, 0, len(routing.decode_polyline6(payload["encoded_polyline"])) - 1, 1.0)],
            ),
        }
    )


@db
class TestFollowedRoute:
    def test_the_route_is_the_trace_of_the_line_split_at_the_points(
        self, client, segments, router
    ) -> None:
        fake = router(traced_router())
        response = post(client, follow_body())
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["follows_file"] is True and body["provisional"] is False
        assert "route" not in fake.endpoints()
        traced = [p for url, p in fake.calls if url.endswith("/trace_route")]
        assert len(traced) == 1
        assert [p.get("type") for p in traced[0]["shape"]] == [
            None,
            None,
            "break_through",
            None,
            None,
        ]
        assert body["leg_ends"] == [2, 4]
        # Matched as ridden: one-ways and turn restrictions are not looped round.
        assert traced[0]["costing_options"]["bicycle"]["ignore_oneways"] is True
        assert body["against_traffic"] == []
        assert body["geometry"]["coordinates"] == [[lon, lat] for lon, lat in VERTICES]
        # Nothing searched beside it: no detour check, calm search or candidates.
        assert body["detour"] is None and body["calm_search"] is None and body["candidates"] is None

    def test_a_first_route_is_not_asked_for_a_followed_line(self, client, segments, router) -> None:
        router(traced_router())
        body = post(client, follow_body("default", quick=True)).json()
        assert body["follows_file"] is True and body["provisional"] is False

    def test_a_line_that_matches_nothing_is_planned_through_the_points(
        self, client, segments, router
    ) -> None:
        fake = router(traced_router())
        fake.answers["trace_route"] = routing.RouterRefused(400, 443, "no match")
        body = post(client, follow_body()).json()
        assert body["follows_file"] is False
        assert fake.endpoints().count("route") >= 1

    def test_without_a_line_the_plan_is_as_before(self, client, segments, router) -> None:
        fake = router(traced_router())
        body = post(client, {k: v for k, v in follow_body().items() if k != "follow"}).json()
        assert body["follows_file"] is False
        assert "trace_route" not in fake.endpoints()

    def test_a_bad_line_is_refused(self, client, segments, router) -> None:
        router(traced_router())
        response = post(
            client, follow_body(follow=encode_polyline6([(-80.0, 38.9), (-77.0, 38.9)]))
        )
        assert response.status_code == 400
        assert "outside" in json.dumps(response.json())

    def test_the_body_may_be_large_enough_for_a_whole_line(self, client, segments, router) -> None:
        router(traced_router())
        line = [(-77.05 + i * 2e-5, 38.9 + (i % 7) * 1e-5) for i in range(follow.MAX_POINTS)]
        body = json.dumps(follow_body(follow=encode_polyline6(line)))
        assert len(body.encode()) > api.MAX_BODY_BYTES
        assert post(client, body).status_code == 200
