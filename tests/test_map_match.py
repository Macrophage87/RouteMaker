"""Snapping an opened GPX track to the map's ways (PLAN.md, Import: map matching): POST /api/match.

The router is replaced at its one network function (`core.routing._transport`), as the route
API's and Nearest's tests do: what the endpoint asks the router for, its size limits, how it
answers when the matcher finds no way, and that it counts toward the routing minute.
"""

from __future__ import annotations

import json

import pytest
from django.conf import settings
from test_nearest import client_slots
from test_ratelimit import in_one_window
from test_route_api import FakeRouter, db, encode_polyline6, hold_slots

from core import map_match, presets, ratelimit, routing

pytestmark = pytest.mark.usefixtures("weekday_clock")

PATH = "/api/match"
TRACK = [[-77.0365, 38.8977], [-77.0331, 38.8990], [-77.0300, 38.9010], [-77.0271, 38.9030]]
SNAPPED = [(-77.03652, 38.89771), (-77.03311, 38.89902), (-77.02705, 38.90301)]


def trace(kinds=("matched", "matched", "interpolated", "unmatched")) -> dict:
    return {
        "shape": encode_polyline6(SNAPPED),
        "matched_points": [{"type": k, "lon": 0, "lat": 0} for k in kinds],
    }


@pytest.fixture
def router(monkeypatch):
    def install(fake: FakeRouter) -> FakeRouter:
        monkeypatch.setattr(routing, "_transport", fake)
        return fake

    return install


def post(client, body, **extra):
    return client.post(PATH, data=json.dumps(body), content_type="application/json", **extra)


@pytest.mark.django_db
class TestMatch:
    def test_the_track_comes_back_snapped_with_its_matched_share(self, client, router) -> None:
        fake = router(FakeRouter({"trace_attributes": trace()}))
        response = post(client, {"points": TRACK, "preset": "default"})
        assert response.status_code == 200
        assert response.json() == {"line": [list(p) for p in SNAPPED], "matched_share": 0.75}
        assert fake.endpoints() == ["trace_attributes"]
        url, payload = fake.calls[0]
        # On the ride type's own graph and costing, by map snap, with the track as sent.
        assert payload["shape_match"] == "map_snap"
        assert payload["costing_options"] == presets.costing("default")
        assert payload["shape"][0] == {"lon": TRACK[0][0], "lat": TRACK[0][1]}
        assert len(payload["shape"]) == len(TRACK)
        assert "matched.type" in payload["filters"]["attributes"]

    def test_a_track_the_matcher_cannot_follow_is_said_in_words(self, client, router) -> None:
        router(FakeRouter({"trace_attributes": routing.RouterRefused(400, 444, "no path")}))
        response = post(client, {"points": TRACK, "preset": "default"})
        assert response.status_code == 422
        assert "No street or path along the track" in response.json()["error"]

    def test_a_twin_graph_not_answering_falls_back_to_the_standard_graph(
        self, client, router
    ) -> None:
        fake = router(
            FakeRouter({"trace_attributes": [routing.RouterUnavailable("down"), trace()]})
        )
        response = post(client, {"points": TRACK, "preset": "gravel"})
        assert response.status_code == 200
        urls = [url for url, _ in fake.calls]
        assert urls[0].startswith(settings.VALHALLA_UPSTREAMS["offroad"])
        assert urls[1].startswith(settings.VALHALLA_UPSTREAMS["standard"])

    def test_keep_to_roads_and_assist_snap_on_the_ride_s_own_graph(self, client, router) -> None:
        fake = router(FakeRouter({"trace_attributes": lambda _payload: trace()}))
        # "Keep to roads, not trails" snaps to the no-trail graph, never onto a trail; it does
        # not fall back to a graph with trails either.
        assert (
            post(client, {"points": TRACK, "preset": "gravel", "trails_off": True}).status_code
            == 200
        )
        assert fake.calls[-1][0].startswith(settings.VALHALLA_UPSTREAMS["no-trail"])
        assert post(client, {"points": TRACK, "preset": "cargo", "assist": True}).status_code == 200
        url, payload = fake.calls[-1]
        assert url.startswith(settings.VALHALLA_UPSTREAMS["ebike"])
        assert payload["costing_options"] == presets.costing("cargo", assist=True)
        # Assist on a ride type without it is the ride type's own graph.
        assert (
            post(client, {"points": TRACK, "preset": "default", "assist": True}).status_code == 200
        )
        assert fake.calls[-1][0].startswith(settings.VALHALLA_UPSTREAMS["standard"])
        refused = post(client, {"points": TRACK, "preset": "default", "trails_off": "yes"})
        assert refused.status_code == 400

    def test_a_shape_with_a_jump_comes_back_as_the_matcher_gave_it(self, client, router) -> None:
        # map_snap across a gap in the track: two matched runs in one shape, joined by a jump.
        jumped = [*SNAPPED[:2], (-77.0100, 38.9100), (-77.0095, 38.9104)]
        router(
            FakeRouter(
                {
                    "trace_attributes": {
                        "shape": encode_polyline6(jumped),
                        "matched_points": [{"type": "matched"}] * 2
                        + [{"type": "unmatched"}, {"type": "matched"}],
                    }
                }
            )
        )
        response = post(client, {"points": TRACK, "preset": "default"})
        assert response.status_code == 200
        assert response.json() == {"line": [list(p) for p in jumped], "matched_share": 0.75}

    def test_an_all_unmatched_answer_is_a_share_of_none(self, client, router) -> None:
        router(FakeRouter({"trace_attributes": trace(("unmatched",) * 4)}))
        response = post(client, {"points": TRACK, "preset": "default"})
        # The browser does not use a snap below half (lib/gpxMatch.ts MATCH_MIN_SHARE).
        assert response.status_code == 200 and response.json()["matched_share"] == 0.0
        router(FakeRouter({"trace_attributes": {"shape": "", "matched_points": []}}))
        assert post(client, {"points": TRACK, "preset": "default"}).status_code == 422

    def test_a_body_longer_than_it_declares_is_refused(self, client, router) -> None:
        fake = router(FakeRouter({"trace_attributes": trace()}))
        body = json.dumps({"points": TRACK, "preset": "default", "pad": "x" * map_match.MAX_BYTES})
        response = client.post(
            PATH, data=body, content_type="application/json", CONTENT_LENGTH="10"
        )
        assert response.status_code == 400
        assert fake.calls == []

    def test_a_router_that_does_not_answer_is_503(self, client, router) -> None:
        router(FakeRouter({"trace_attributes": routing.RouterUnavailable("down")}))
        response = post(client, {"points": TRACK, "preset": "default"})
        assert response.status_code == 503 and response["Retry-After"]

    @pytest.mark.parametrize(
        "body",
        [
            {"points": TRACK[:1], "preset": "default"},
            {"points": [[-77.0, "38.9"], [-77.1, 38.9]], "preset": "default"},
            {"points": [[-80.5, 40.0], [-80.6, 40.1]], "preset": "default"},
            {"points": TRACK, "preset": "strava"},
            {"points": TRACK, "preset": "default", "name": "Thursday ride"},
            {"points": [[-77.0, 38.9 + i * 1e-6] for i in range(map_match.MAX_POINTS + 1)]},
            # Past the router's trace limit of 124 mi (200 km).
            {"points": [[-77.4, 38.6], [-76.6, 39.3], [-77.4, 38.6], [-76.6, 39.3]]},
        ],
    )
    def test_a_bad_track_is_refused_before_the_router_is_asked(self, client, router, body) -> None:
        fake = router(FakeRouter({"trace_attributes": trace()}))
        response = post(client, body)
        assert response.status_code == 400 and response.json()["error"]
        assert fake.calls == []

    def test_a_body_past_the_byte_cap_is_refused(self, client, router) -> None:
        fake = router(FakeRouter({"trace_attributes": trace()}))
        body = json.dumps({"points": TRACK, "preset": "default", "pad": "x" * map_match.MAX_BYTES})
        response = client.post(PATH, data=body, content_type="application/json")
        assert response.status_code == 400
        assert fake.calls == []

    def test_it_needs_a_json_body(self, client, router) -> None:
        router(FakeRouter({"trace_attributes": trace()}))
        response = client.post(PATH, data="points", content_type="text/plain")
        assert response.status_code == 400

    def test_it_counts_toward_the_routing_minute(self, client, router) -> None:
        router(FakeRouter({"trace_attributes": lambda _payload: trace()}))

        def attempt(n):
            headers = {"HTTP_X_FORWARDED_FOR": f"198.51.100.{31 + 100 * n}"}
            body = {"points": TRACK, "preset": "default"}
            statuses = [
                post(client, body, **headers).status_code for _ in range(ratelimit.ROUTING.requests)
            ]
            return statuses, post(client, body, **headers)

        statuses, refused = in_one_window(ratelimit.ROUTING.window_s, attempt)
        assert statuses == [200] * ratelimit.ROUTING.requests
        assert refused.status_code == 429


@db
def test_a_client_with_its_routing_slots_taken_is_429(client, router) -> None:
    router(FakeRouter({"trace_attributes": trace()}))
    other = hold_slots(client_slots("198.51.100.41"))
    try:
        refused = post(
            client, {"points": TRACK, "preset": "default"}, HTTP_X_FORWARDED_FOR="198.51.100.41"
        )
    finally:
        other.close()
    assert refused.status_code == 429


def test_it_is_in_the_openapi_schema(client) -> None:
    operation = client.get("/api/openapi.json").json()["paths"][PATH]["post"]
    assert {"200", "400", "422", "429", "503"} <= set(operation["responses"])


# A track snapped round a corner's crosswalks (Stephen 2026-11-01, "several phantom LTS4 unnamed
# roads"): south along one street to the crosswalk's node 7 m before the corner, round the
# corner on two crosswalk edges, then west along the other street (synthetic).
LAT = 38.9
ON_SOUTH = [(-77.0, LAT + 0.001), (-77.0, LAT + 0.000063)]
ROUND = [(-77.00008, LAT + 0.00006)]
ON_WEST = [(-77.00008, LAT), (-77.001, LAT)]
TANGLED = ON_SOUTH + ROUND + ON_WEST
CORNER = (-77.0, LAT)


def edge(use: str, metres: float, begin: int, end: int) -> dict:
    return {
        "use": use,
        "length": metres / 1000.0,
        "begin_shape_index": begin,
        "end_shape_index": end,
    }


TANGLED_EDGES = [
    edge("road", 104.0, 0, 1),
    edge("pedestrian_crossing", 7.0, 1, 2),
    edge("pedestrian_crossing", 6.0, 2, 3),
    edge("road", 80.0, 3, 4),
]


class TestUntangle:
    def test_a_corner_cut_over_the_crosswalks_goes_back_on_the_road(self) -> None:
        asked = []

        def road(a, b):
            asked.append((a, b))
            return [a, CORNER, b]

        line = map_match.untangle(TANGLED, TANGLED_EDGES, road)
        assert asked == [(ON_SOUTH[1], ON_WEST[0])]
        assert line == [*ON_SOUTH, CORNER, *ON_WEST]

    def test_a_loop_back_to_where_it_left_is_cut_out(self) -> None:
        out_and_back = [
            (-77.0, LAT + 0.001),
            CORNER,
            (-77.00008, LAT),
            CORNER,
            (-77.0, LAT - 0.001),
        ]
        edges = [
            edge("road", 111.0, 0, 1),
            edge("pedestrian_crossing", 7.0, 1, 2),
            edge("pedestrian_crossing", 7.0, 2, 3),
            edge("road", 111.0, 3, 4),
        ]
        line = map_match.untangle(out_and_back, edges, lambda a, b: pytest.fail("no route"))
        assert line == [(-77.0, LAT + 0.001), CORNER, (-77.0, LAT - 0.001)]

    def test_scraps_of_road_between_crosswalks_go_with_them(self) -> None:
        # A rider waiting at the corner: crosswalk, a few metres of road, crosswalk again.
        edges = [
            edge("road", 104.0, 0, 1),
            edge("pedestrian_crossing", 7.0, 1, 2),
            edge("road", 7.0, 2, 2),
            edge("sidewalk", 6.0, 2, 3),
            edge("road", 80.0, 3, 4),
        ]
        assert map_match._tangles(edges) == [(1, 3)]

    def test_a_real_ride_on_a_sidewalk_or_onto_a_path_is_kept(self) -> None:
        def never(a, b):
            raise AssertionError("not asked")

        # Longer than FOOT_MAX_M of sidewalk: ridden on purpose.
        long_walk = [*TANGLED_EDGES]
        long_walk[1] = edge("sidewalk", map_match.FOOT_MAX_M + 1.0, 1, 2)
        assert map_match.untangle(TANGLED, long_walk, never) == TANGLED
        # A crossing at the track's end (onto a path, or where it starts) has no road after it.
        assert map_match._tangles(TANGLED_EDGES[:3]) == []

    def test_a_way_back_much_longer_than_the_tangle_or_none_keeps_it(self) -> None:
        far = [ON_SOUTH[1], (-77.0, LAT + 0.01), ON_WEST[0]]
        assert map_match.untangle(TANGLED, TANGLED_EDGES, lambda a, b: far) == TANGLED
        assert map_match.untangle(TANGLED, TANGLED_EDGES, lambda a, b: None) == TANGLED
        # A tangle whose shape indexes run past the line changes nothing.
        good = [ON_SOUTH[1], CORNER, ON_WEST[0]]
        stale = [*TANGLED_EDGES[:2], edge("pedestrian_crossing", 6.0, 2, 9), TANGLED_EDGES[3]]
        assert map_match.untangle(TANGLED, stale, lambda a, b: good) == TANGLED

    def test_two_tangles_in_one_track_are_both_put_back(self) -> None:
        # TANGLED, then on along the second street and round a second corner the same way.
        on, cut, off = (
            (-77.00108, LAT - 0.00006),
            (-77.00116, LAT - 0.00012),
            (-77.0012, LAT - 0.001),
        )
        line = [*TANGLED, on, cut, off]
        edges = [
            *TANGLED_EDGES,
            edge("road", 8.0, 4, 5),
            edge("pedestrian_crossing", 7.0, 5, 6),
            edge("road", 100.0, 6, 7),
        ]
        bend = (-77.0012, LAT - 0.00006)

        def road(a, b):
            return [a, CORNER if a == ON_SOUTH[1] else bend, b]

        assert map_match.untangle(line, edges, road) == [
            *ON_SOUTH,
            CORNER,
            *ON_WEST,
            on,
            bend,
            cut,
            off,
        ]

    def test_a_trail_crossing_a_street_is_ridden_as_mapped(self) -> None:
        trail = [edge("cycleway", 104.0, 0, 1), *TANGLED_EDGES[1:3], edge("cycleway", 80.0, 3, 4)]
        assert map_match._tangles(trail) == []


@pytest.mark.django_db
def test_a_route_the_router_refuses_keeps_the_tangle(client, router) -> None:
    matched = {
        "shape": encode_polyline6(TANGLED),
        "matched_points": [{"type": "matched", "lon": 0, "lat": 0}] * 4,
        "edges": TANGLED_EDGES,
    }
    router(FakeRouter({"trace_attributes": matched, "route": routing.RouterRefused(400, 442, "")}))
    response = post(client, {"points": TRACK, "preset": "default"})
    assert response.status_code == 200
    assert response.json()["line"] == [[round(x, 6), round(y, 6)] for x, y in TANGLED]


@pytest.mark.django_db
def test_after_a_twin_falls_back_the_way_back_is_routed_on_the_standard_graph(
    client, router
) -> None:
    matched = {
        "shape": encode_polyline6(TANGLED),
        "matched_points": [{"type": "matched", "lon": 0, "lat": 0}] * 4,
        "edges": TANGLED_EDGES,
    }
    road = {"trip": {"legs": [{"shape": encode_polyline6([ON_SOUTH[1], CORNER, ON_WEST[0]])}]}}
    fake = router(
        FakeRouter(
            {"trace_attributes": [routing.RouterUnavailable("down"), matched], "route": road}
        )
    )
    response = post(client, {"points": TRACK, "preset": "gravel"})
    assert response.status_code == 200
    urls = [url for url, _ in fake.calls]
    assert urls[2].startswith(settings.VALHALLA_UPSTREAMS["standard"])


@pytest.mark.django_db
def test_the_endpoint_untangles_on_the_ride_types_graph(client, router) -> None:
    matched = {
        "shape": encode_polyline6(TANGLED),
        "matched_points": [{"type": "matched", "lon": 0, "lat": 0}] * 4,
        "edges": TANGLED_EDGES,
    }
    road = {"trip": {"legs": [{"shape": encode_polyline6([ON_SOUTH[1], CORNER, ON_WEST[0]])}]}}
    fake = router(FakeRouter({"trace_attributes": matched, "route": road}))
    response = post(client, {"points": TRACK, "preset": "default"})
    assert response.status_code == 200
    expected = [[round(lon, 6), round(lat, 6)] for lon, lat in [*ON_SOUTH, CORNER, *ON_WEST]]
    assert response.json()["line"] == expected
    assert fake.endpoints() == ["trace_attributes", "route"]
    payload = fake.calls[1][1]
    assert payload["costing_options"] == presets.costing("default")
    asked = [(p["lon"], p["lat"]) for p in payload["locations"]]
    assert asked == [pytest.approx(ON_SOUTH[1]), pytest.approx(ON_WEST[0])]
    assert "edge.use" in fake.calls[0][1]["filters"]["attributes"]
