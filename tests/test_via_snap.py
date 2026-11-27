# ruff: noqa: F811 (the route tests' fixtures, imported by name)
"""Via points pass over sidewalks and crosswalks to the way beside them (Stephen, 2026-11-27:
"the issue isn't the jog, but where you put the via"): a via dropped on R St NW at 17th St sat
0.2 m from the sidewalk and 9.8 m from R St, and the route left R St for an LTS 4 sidewalk stub."""

from __future__ import annotations

import pytest
from test_route_api import (  # noqa: F401 (fixtures)
    VERTICES,
    FakeRouter,
    post,
    route_answer,
    router,
    segments,
    trace_answer,
)

from core import routing

pytestmark = pytest.mark.usefixtures("weekday_clock")


def edge(distance, use, lon, lat, names=()):
    return {
        "distance": distance,
        "correlated_lon": lon,
        "correlated_lat": lat,
        "edge": {"classification": {"use": use}},
        "edge_info": {"names": list(names)},
    }


SIDEWALK = edge(0.2, "sidewalk", -77.03860, 38.91270)
CROSSWALK = edge(2.4, "pedestrian_crossing", -77.03861, 38.91272)
R_ST = edge(9.8, "road", -77.03862, 38.91279, ["R Street Northwest"])


class TestViaTarget:
    def test_a_via_on_a_sidewalk_moves_to_the_street_beside_it(self) -> None:
        assert routing._via_target([SIDEWALK, CROSSWALK, R_ST]) == (-77.03862, 38.91279)

    def test_a_via_nearest_a_street_stays(self) -> None:
        on_street = edge(1.0, "road", -77.0415, 38.91265, ["R Street Northwest"])
        assert routing._via_target([on_street, CROSSWALK]) is None

    def test_a_via_on_a_trail_beside_a_road_stays_on_the_trail(self) -> None:
        trail = edge(0.5, "cycleway", -77.0, 38.9, ["Custis Trail"])
        assert routing._via_target([trail, R_ST]) is None

    def test_a_named_footway_is_a_trail_and_stays(self) -> None:
        trail = edge(0.5, "footway", -77.0, 38.9, ["Rock Creek Trail"])
        assert routing._via_target([trail, R_ST]) is None

    def test_an_unnamed_footway_is_passed_over(self) -> None:
        corner = edge(0.2, "footway", -77.0386, 38.9127)
        assert routing._via_target([corner, R_ST]) == (-77.03862, 38.91279)

    def test_with_no_ridden_way_near_the_via_stays(self) -> None:
        far = edge(routing.VIA_SNAP_RADIUS_M + 1, "road", -77.0, 38.9, ["R Street Northwest"])
        assert routing._via_target([SIDEWALK, far]) is None
        assert routing._via_target([]) is None


def plan_router(located) -> FakeRouter:
    return FakeRouter(
        {
            "route": route_answer([(VERTICES[0:3], 1.3, [10.0, 20.0])]),
            "height": lambda payload: {"height": [25.0] * len(payload["shape"])},
            "trace_attributes": lambda payload: trace_answer(
                routing.decode_polyline6(payload["encoded_polyline"]),
                [(101, 0, len(routing.decode_polyline6(payload["encoded_polyline"])) - 1, 1.0)],
            ),
            # A list is FakeRouter's answers in turn: the one answer, a list, is returned whole.
            "locate": located if isinstance(located, Exception) else (lambda payload: located),
        }
    )


def bike_routes(fake: FakeRouter) -> list[dict]:
    return [p for url, p in fake.calls if url.endswith("/route") and p["costing"] == "bicycle"]


@pytest.mark.django_db
class TestPlan:
    def test_the_route_is_asked_through_the_street_not_the_sidewalk(
        self, client, segments, router
    ) -> None:
        fake = router(plan_router([{"edges": [SIDEWALK, CROSSWALK, R_ST]}]))
        points = [list(VERTICES[i]) for i in (0, 1, 2)]
        post(client, {"points": points, "preset": "default", "via_points": [1]})
        locates = [p for url, p in fake.calls if url.endswith("/locate")]
        assert len(locates) == 1
        assert [(loc["lon"], loc["lat"]) for loc in locates[0]["locations"]] == [tuple(VERTICES[1])]
        via = bike_routes(fake)[0]["locations"][1]
        assert (via["lon"], via["lat"]) == (-77.03862, 38.91279)
        assert via["radius"] == routing.VIA_RADIUS_M

    def test_without_via_points_nothing_is_located(self, client, segments, router) -> None:
        fake = router(plan_router([]))
        points = [list(VERTICES[i]) for i in (0, 2)]
        post(client, {"points": points, "preset": "default"})
        assert not [url for url, _ in fake.calls if url.endswith("/locate")]

    def test_a_router_that_cannot_locate_leaves_the_via_where_it_was(
        self, client, segments, router
    ) -> None:
        fake = router(plan_router(routing.RouterRefused(400, 171, "no edges")))
        points = [list(VERTICES[i]) for i in (0, 1, 2)]
        body = post(client, {"points": points, "preset": "default", "via_points": [1]})
        assert body.status_code == 200
        via = bike_routes(fake)[0]["locations"][1]
        assert [via["lon"], via["lat"]] == list(VERTICES[1])
