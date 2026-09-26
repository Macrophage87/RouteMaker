"""POST /api/route: signed-out route planning, per the shared API contract.

The router is replaced by a fake at the one function that touches the network
(`core.routing._transport`), so these tests see exactly what the API would have
sent to Valhalla and control exactly what comes back. The segment table is real
(a live schema from the `segment_schemas` fixture), because the stress join is
a PostGIS query and a stand-in would test nothing about it. The transport
itself is tested against a real local HTTP server at the bottom.
"""

from __future__ import annotations

import http.server
import json
import math
import socket
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.db import connection

from core import presets, routing

db = pytest.mark.django_db(transaction=True)

ROUTE_PATH = "/api/route"
CONTRACT_KEYS = {
    "preset",
    "variant",
    "geometry",
    "distance_m",
    "duration_s",
    "climb_m",
    "descent_m",
    "stress_m",
    "attribution",
}
STRESS_KEYS = {"1", "2", "3", "4", "unknown"}

LAT = 38.9
# Five vertices along one parallel, equally spaced, so every stretch between two
# of them has the same ground length.
VERTICES = [(-77.05, LAT), (-77.04, LAT), (-77.035, LAT), (-77.03, LAT), (-77.02, LAT)]


def encode_polyline6(coordinates) -> str:
    out = []
    prev_lat = prev_lon = 0
    for lon, lat in coordinates:
        for value, prev in ((round(lat * 1e6), prev_lat), (round(lon * 1e6), prev_lon)):
            delta = value - prev
            delta = ~(delta << 1) if delta < 0 else delta << 1
            while delta >= 0x20:
                out.append(chr((0x20 | (delta & 0x1F)) + 63))
                delta >>= 5
            out.append(chr(delta + 63))
        prev_lat, prev_lon = round(lat * 1e6), round(lon * 1e6)
    return "".join(out)


def route_answer(legs) -> dict:
    """A Valhalla /route body. `legs` is [(vertices, length_km, elevations)]."""
    return {
        "trip": {
            "legs": [
                {
                    "shape": encode_polyline6(vertices),
                    "summary": {"length": length_km, "time": 100.0 * length_km},
                    "elevation": elevations,
                    "elevation_interval": 30,
                }
                for vertices, length_km, elevations in legs
            ],
            "summary": {
                "length": sum(length for _v, length, _e in legs),
                "time": 100.0 * sum(length for _v, length, _e in legs),
            },
            "units": "kilometers",
        }
    }


def trace_answer(vertices, edges) -> dict:
    """A Valhalla /trace_attributes body. `edges` is [(way_id, begin, end, km)]."""
    return {
        "units": "kilometers",
        "shape": encode_polyline6(vertices),
        "edges": [
            {"way_id": way, "begin_shape_index": b, "end_shape_index": e, "length": km}
            for way, b, e, km in edges
        ],
    }


class FakeRouter:
    """Records every call; answers from `answers[endpoint]` (a body, a list of
    bodies consumed in order, or an exception to raise)."""

    def __init__(self, answers: dict) -> None:
        self.answers = answers
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, payload: dict, timeout: float) -> dict:
        self.calls.append((url, payload))
        endpoint = url.rsplit("/", 1)[1]
        answer = self.answers[endpoint]
        if isinstance(answer, list):
            answer = answer.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def endpoints(self) -> list[str]:
        return [url.rsplit("/", 1)[1] for url, _ in self.calls]


# One leg over all five vertices: way 101 (one segment, tier 3), way 202 (two
# segments: tier 1 on its first half, tier 4 on its second), way 303 (no
# segment row at all).
STANDARD_EDGES = [(101, 0, 1, 0.9), (202, 1, 3, 0.8), (303, 3, 4, 0.5)]
STANDARD_EXPECTED = {"1": 400.0, "2": 0.0, "3": 900.0, "4": 400.0, "unknown": 500.0}


def standard_router() -> FakeRouter:
    return FakeRouter(
        {
            "route": route_answer([(VERTICES, 2.2, [10.0, 20.0, 15.0, 30.0])]),
            "trace_attributes": trace_answer(VERTICES, STANDARD_EDGES),
        }
    )


@pytest.fixture
def segments(segment_schemas):
    live, _staging = segment_schemas
    rows = [
        (101, 0, 3, VERTICES[0:2]),
        (202, 0, 1, VERTICES[1:3]),
        (202, 1, 4, VERTICES[2:4]),
    ]
    with connection.cursor() as cursor:
        for way, ordinal, tier, line in rows:
            wkt = "LINESTRING(" + ", ".join(f"{lon} {lat}" for lon, lat in line) + ")"
            cursor.execute(
                f"INSERT INTO {live}.segment (osm_way_id, ordinal, geometry, stress_tier, "
                "stress_rule) VALUES (%s, %s, ST_GeomFromText(%s, 4326), %s, 'test')",
                [way, ordinal, wkt, tier],
            )
    return live


@pytest.fixture
def router(monkeypatch):
    def install(fake: FakeRouter) -> FakeRouter:
        monkeypatch.setattr(routing, "_transport", fake)
        return fake

    return install


def post(client, body, content_type: str = "application/json", **extra):
    data = body if isinstance(body, (str, bytes)) else json.dumps(body)
    return client.post(ROUTE_PATH, data=data, content_type=content_type, **extra)


def good_body(preset: str = "default") -> dict:
    return {"points": [list(VERTICES[0]), list(VERTICES[-1])], "preset": preset}


@db
class TestAnswer:
    def test_a_route_carries_every_contract_field(self, client, segments, router) -> None:
        router(standard_router())
        response = post(client, good_body())
        assert response.status_code == 200
        body = response.json()
        assert set(body) == CONTRACT_KEYS
        assert set(body["stress_m"]) == STRESS_KEYS
        assert body["geometry"]["type"] == "LineString"
        assert body["preset"] == "default"
        assert body["variant"] == presets.PRESETS["default"].variant

    def test_the_geometry_is_lon_lat(self, client, segments, router) -> None:
        router(standard_router())
        coordinates = post(client, good_body()).json()["geometry"]["coordinates"]
        assert coordinates == [list(v) for v in VERTICES]

    def test_distance_and_duration_are_the_routers_in_metres_and_seconds(
        self, client, segments, router
    ) -> None:
        router(standard_router())
        body = post(client, good_body()).json()
        assert body["distance_m"] == pytest.approx(2200.0)
        assert body["duration_s"] == pytest.approx(220.0)

    def test_climb_and_descent_use_the_hysteresis_definition(
        self, client, segments, router
    ) -> None:
        """10 -> 20 -> 15 -> 30: gain 10 then 15 from the dip's bottom; the one
        descent, 5 m, clears the 3 m hysteresis."""
        router(standard_router())
        body = post(client, good_body()).json()
        assert body["climb_m"] == pytest.approx(25.0)
        assert body["descent_m"] == pytest.approx(5.0)

    def test_nothing_about_the_request_needs_or_makes_a_session(
        self, client, segments, router
    ) -> None:
        """Owner decision of 2026-09-26: planning works signed out, and a
        signed-out plan is not saved."""
        router(standard_router())
        response = post(client, good_body())
        assert response.status_code == 200
        assert settings.SESSION_COOKIE_NAME not in response.cookies

    def test_the_answer_carries_the_public_tier_attribution(self, client, segments, router) -> None:
        router(standard_router())
        credits = " | ".join(post(client, good_body()).json()["attribution"])
        assert "OpenStreetMap" in credits and "ODbL" in credits
        assert "CC BY 4.0" in credits
        assert "Virginia" in credits

    def test_multi_leg_geometry_is_one_line_with_no_repeated_joint(
        self, client, segments, router
    ) -> None:
        first, second = VERTICES[:3], VERTICES[2:]
        router(
            FakeRouter(
                {
                    "route": route_answer([(first, 1.0, [1.0]), (second, 1.0, [1.0])]),
                    "trace_attributes": [
                        trace_answer(first, [(101, 0, 2, 1.0)]),
                        trace_answer(second, [(303, 0, 2, 1.0)]),
                    ],
                }
            )
        )
        body = {"points": [list(VERTICES[0]), list(VERTICES[2]), list(VERTICES[4])]}
        answer = post(client, {**body, "preset": "default"}).json()
        assert answer["geometry"]["coordinates"] == [list(v) for v in VERTICES]


@db
class TestStressBreakdown:
    def test_each_tier_gets_the_metres_ridden_on_it(self, client, segments, router) -> None:
        router(standard_router())
        stress = post(client, good_body()).json()["stress_m"]
        assert stress == pytest.approx(STANDARD_EXPECTED, abs=0.2)

    def test_the_breakdown_accounts_for_the_whole_trace(self, client, segments, router) -> None:
        router(standard_router())
        stress = post(client, good_body()).json()["stress_m"]
        assert sum(stress.values()) == pytest.approx(1000 * sum(e[3] for e in STANDARD_EDGES))

    def test_an_out_and_back_counts_both_traversals(self, client, segments, router) -> None:
        """PLAN, Preprocessing pipeline: the join is per traversal instance, so
        riding a way twice reports twice its length."""
        there_and_back = [VERTICES[0], VERTICES[1], VERTICES[0]]
        router(
            FakeRouter(
                {
                    "route": route_answer([(there_and_back, 1.8, [1.0])]),
                    "trace_attributes": trace_answer(
                        there_and_back, [(101, 0, 1, 0.9), (101, 1, 2, 0.9)]
                    ),
                }
            )
        )
        body = {"points": [list(VERTICES[0]), list(VERTICES[1]), list(VERTICES[0])]}
        stress = post(client, {**body, "preset": "default"}).json()["stress_m"]
        assert stress["3"] == pytest.approx(1800.0, abs=0.2)

    def test_a_trace_the_router_refuses_to_edge_walk_falls_back_to_map_snap(
        self, client, segments, router
    ) -> None:
        fake = router(
            FakeRouter(
                {
                    "route": route_answer([(VERTICES, 2.2, [1.0])]),
                    "trace_attributes": [
                        routing.RouterRefused(400, 443, "no edge walk"),
                        trace_answer(VERTICES, STANDARD_EDGES),
                    ],
                }
            )
        )
        stress = post(client, good_body()).json()["stress_m"]
        matches = [p["shape_match"] for url, p in fake.calls if url.endswith("trace_attributes")]
        assert matches == ["edge_walk", "map_snap"]
        assert stress == pytest.approx(STANDARD_EXPECTED, abs=0.2)

    def test_a_leg_that_cannot_be_traced_is_unknown_not_guessed(
        self, client, segments, router
    ) -> None:
        router(
            FakeRouter(
                {
                    "route": route_answer([(VERTICES, 2.2, [1.0])]),
                    "trace_attributes": [
                        routing.RouterRefused(400, 443, "no"),
                        routing.RouterRefused(400, 444, "no"),
                    ],
                }
            )
        )
        response = post(client, good_body())
        assert response.status_code == 200
        stress = response.json()["stress_m"]
        assert stress["unknown"] == pytest.approx(2200.0)
        assert sum(v for k, v in stress.items() if k != "unknown") == 0


@db
class TestWhatIsSentToTheRouter:
    @pytest.mark.parametrize("name", sorted(presets.PRESETS))
    def test_every_call_goes_to_the_presets_variant(self, name, client, segments, router) -> None:
        """PLAN, Stats source: the trace goes to the same variant and costing
        as the route that produced the shape."""
        fake = router(standard_router())
        assert post(client, good_body(name)).status_code == 200
        base = settings.VALHALLA_UPSTREAMS[presets.PRESETS[name].variant]
        assert fake.endpoints() == ["route", "trace_attributes"]
        assert all(url.startswith(base + "/") for url, _ in fake.calls)
        assert all(p["costing_options"] == presets.costing(name) for _, p in fake.calls)
        assert all(p["costing"] == "bicycle" for _, p in fake.calls)

    def test_the_points_are_sent_in_order_as_lon_lat(self, client, segments, router) -> None:
        fake = router(standard_router())
        post(client, good_body())
        locations = fake.calls[0][1]["locations"]
        assert [(loc["lon"], loc["lat"]) for loc in locations] == [VERTICES[0], VERTICES[-1]]

    def test_the_route_asks_for_elevation_and_an_invariant_planning_time(
        self, client, segments, router
    ) -> None:
        fake = router(standard_router())
        post(client, good_body())
        request = fake.calls[0][1]
        assert request["elevation_interval"] > 0
        assert request["date_time"]["type"] == 3
        assert request["date_time"]["value"] == routing.planning_time()


def refused_before_the_router(client, router, body, **kwargs) -> dict:
    fake = router(standard_router())
    response = post(client, body, **kwargs)
    assert response.status_code == 400, response.content
    assert fake.calls == []
    return response.json()


@db
class TestRefusedInput:
    """Each body is wrong for exactly one reason, and none reaches the router."""

    def test_one_point(self, client, router) -> None:
        assert "error" in refused_before_the_router(
            client, router, {"points": [list(VERTICES[0])], "preset": "default"}
        )

    def test_twenty_six_points(self, client, router) -> None:
        points = [[-77.05 + i * 0.001, LAT] for i in range(26)]
        refused_before_the_router(client, router, {"points": points, "preset": "default"})

    def test_twenty_five_points_are_accepted(self, client, segments, router) -> None:
        router(standard_router())
        points = [[-77.05 + i * 0.001, LAT] for i in range(25)]
        assert post(client, {"points": points, "preset": "default"}).status_code == 200

    @pytest.mark.parametrize(
        "point",
        [
            [settings.COVERAGE_BBOX[0] - 0.01, LAT],
            [-77.0, settings.COVERAGE_BBOX[1] - 0.01],
            [settings.COVERAGE_BBOX[2] + 0.01, LAT],
            [-77.0, settings.COVERAGE_BBOX[3] + 0.01],
        ],
        ids=["west", "south", "east", "north"],
    )
    def test_a_point_outside_the_coverage_box(self, point, client, router) -> None:
        refused_before_the_router(
            client, router, {"points": [list(VERTICES[0]), point], "preset": "default"}
        )

    def test_the_coverage_edges_are_inside(self, client, segments, router) -> None:
        router(standard_router())
        west, south, east, north = settings.COVERAGE_BBOX
        body = {"points": [[west, south], [east, north]], "preset": "default"}
        assert post(client, body).status_code == 200

    def test_lat_lon_order_is_refused_not_misread(self, client, router) -> None:
        """[lat, lon] for a DC point is far outside the box in both axes."""
        refused_before_the_router(
            client, router, {"points": [[LAT, -77.05], [LAT, -77.02]], "preset": "default"}
        )

    def test_an_unknown_preset(self, client, router) -> None:
        refused_before_the_router(client, router, {**good_body(), "preset": "trailmaxxing"})

    def test_a_missing_preset(self, client, router) -> None:
        refused_before_the_router(client, router, {"points": good_body()["points"]})

    def test_a_point_with_three_numbers(self, client, router) -> None:
        points = [[*VERTICES[0], 10.0], list(VERTICES[-1])]
        refused_before_the_router(client, router, {"points": points, "preset": "default"})

    def test_not_a_number(self, client, router) -> None:
        """Python's json module reads NaN; it must not reach the router."""
        body = '{"points": [[NaN, 38.9], [-77.02, 38.9]], "preset": "default"}'
        refused_before_the_router(client, router, body)

    def test_an_unexpected_field(self, client, router) -> None:
        refused_before_the_router(client, router, {**good_body(), "save": True})

    def test_malformed_json(self, client, router) -> None:
        refused_before_the_router(client, router, '{"points": [[-77.05, 38.9], ')

    def test_a_body_that_is_not_an_object(self, client, router) -> None:
        refused_before_the_router(client, router, "[1, 2]")

    def test_an_oversized_body(self, client, router) -> None:
        body = json.dumps(good_body()) + " " * 9000
        refused_before_the_router(client, router, body)

    def test_a_body_that_is_not_json_typed(self, client, router) -> None:
        refused_before_the_router(
            client, router, json.dumps(good_body()), content_type="text/plain"
        )

    def test_a_refusal_names_the_problem_field(self, client, router) -> None:
        error = refused_before_the_router(client, router, {**good_body(), "preset": "x"})["error"]
        assert "preset" in error


@db
class TestRouterOutcomes:
    def test_no_path_is_422(self, client, router) -> None:
        router(FakeRouter({"route": routing.RouterRefused(400, 442, "No path could be found")}))
        response = post(client, good_body())
        assert response.status_code == 422
        assert response.json()["error"]

    def test_a_no_trail_no_route_says_why(self, client, router) -> None:
        """PLAN, Routing model: a no-route result on the no-trail variant
        reports the disconnection rather than failing blankly."""
        router(FakeRouter({"route": routing.RouterRefused(400, 442, "No path could be found")}))
        standard = post(client, good_body("default")).json()["error"]
        router(FakeRouter({"route": routing.RouterRefused(400, 442, "No path could be found")}))
        no_trail = post(client, good_body("mass-ride")).json()["error"]
        assert no_trail != standard
        assert no_trail.startswith(standard)

    def test_any_other_refusal_is_still_no_route(self, client, router) -> None:
        router(FakeRouter({"route": routing.RouterRefused(400, 154, "exceeds max distance")}))
        assert post(client, good_body()).status_code == 422

    def test_an_answer_with_no_legs_is_no_route(self, client, router) -> None:
        router(FakeRouter({"route": {"trip": {"legs": []}}}))
        assert post(client, good_body()).status_code == 422

    def test_a_router_that_does_not_answer_is_502(self, client, router) -> None:
        router(FakeRouter({"route": routing.RouterUnavailable("connection refused")}))
        response = post(client, good_body())
        assert response.status_code == 502
        assert response.json()["error"]

    def test_a_router_that_fails_mid_trace_is_502(self, client, segments, router) -> None:
        router(
            FakeRouter(
                {
                    "route": route_answer([(VERTICES, 2.2, [1.0])]),
                    "trace_attributes": routing.RouterUnavailable("gone"),
                }
            )
        )
        assert post(client, good_body()).status_code == 502


@db
class TestRateLimit:
    def test_the_sixty_first_request_in_a_minute_is_429(self, client, segments, router) -> None:
        from core.ratelimit import ROUTING

        fake = router(standard_router())
        fake.answers["route"] = [fake.answers["route"]] * (ROUTING.requests + 5)
        fake.answers["trace_attributes"] = [fake.answers["trace_attributes"]] * (
            ROUTING.requests + 5
        )
        headers = {"HTTP_X_FORWARDED_FOR": "198.51.100.7"}
        statuses = [
            post(client, good_body(), **headers).status_code for _ in range(ROUTING.requests)
        ]
        assert statuses == [200] * ROUTING.requests
        calls_before = len(fake.calls)

        refused = post(client, good_body(), **headers)
        assert refused.status_code == 429
        assert 1 <= int(refused["Retry-After"]) <= ROUTING.window_s
        assert refused.json()["error"]
        assert len(fake.calls) == calls_before

        other = post(client, good_body(), HTTP_X_FORWARDED_FOR="198.51.100.8")
        assert other.status_code == 200

    def test_invalid_requests_spend_the_budget_too(self, client, router) -> None:
        """Otherwise a flood of bad bodies is free. Bodies refused before
        parsing - the wrong content type - are counted as well, which is what
        the limit being the outermost check means."""
        from core.ratelimit import ROUTING

        router(standard_router())
        headers = {"HTTP_X_FORWARDED_FOR": "198.51.100.9"}
        for _ in range(ROUTING.requests):
            post(client, "{", content_type="text/plain", **headers)
        assert post(client, good_body(), **headers).status_code == 429


def test_the_route_is_in_the_openapi_schema(client) -> None:
    """PLAN, Backend: the front end's TypeScript types are generated from it."""
    schema = client.get("/api/openapi.json").json()
    operation = schema["paths"][ROUTE_PATH]["post"]
    assert {"200", "400", "422", "429", "502"} <= set(operation["responses"])
    assert settings.ADMIN_PATH.strip("/") not in json.dumps(schema)


class TestPlanningTime:
    ZONE = ZoneInfo("America/New_York")

    @pytest.mark.parametrize(
        "now",
        [
            datetime(2026, 9, 26, 8, 59, tzinfo=ZONE),  # Saturday, before nine
            datetime(2026, 9, 26, 9, 0, tzinfo=ZONE),  # Saturday, at nine
            datetime(2026, 9, 27, 12, 0, tzinfo=ZONE),  # Sunday
            datetime(2026, 10, 2, 23, 30, tzinfo=ZONE),  # Friday night
            datetime(2026, 11, 1, 1, 30, tzinfo=ZONE),  # the autumn clock change
        ],
    )
    def test_it_is_the_next_saturday_at_nine_local(self, now) -> None:
        value = datetime.strptime(routing.planning_time(now), "%Y-%m-%dT%H:%M").replace(
            tzinfo=self.ZONE
        )
        assert value.weekday() == 5
        assert (value.hour, value.minute) == (9, 0)
        assert now < value <= now + timedelta(days=7)


class TestPolyline:
    def test_it_decodes_what_valhalla_encodes(self) -> None:
        line = [(-77.043400, 38.909700), (-77.0091, 38.8899), (-76.612, 39.29)]
        assert routing.decode_polyline6(encode_polyline6(line)) == pytest.approx(line)

    def test_the_empty_shape_is_no_points(self) -> None:
        assert routing.decode_polyline6("") == []


class _Handler(http.server.BaseHTTPRequestHandler):
    status = 200
    body = b"{}"

    def do_POST(self) -> None:  # noqa: N802 - the stdlib's name
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def server():
    started = []

    def start(status: int, body: bytes):
        handler = type("H", (_Handler,), {"status": status, "body": body})
        httpd = http.server.HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        started.append(httpd)
        return f"http://127.0.0.1:{httpd.server_port}/route"

    yield start
    for httpd in started:
        httpd.shutdown()


class TestTransport:
    def test_a_success_is_its_json(self, server) -> None:
        url = server(200, b'{"trip": {}}')
        assert routing._transport(url, {"a": 1}, 5) == {"trip": {}}

    def test_a_client_error_is_a_refusal_with_valhallas_code(self, server) -> None:
        url = server(400, b'{"error_code": 442, "error": "No path could be found"}')
        with pytest.raises(routing.RouterRefused) as refused:
            routing._transport(url, {}, 5)
        assert (refused.value.status, refused.value.code) == (400, 442)

    def test_a_server_error_is_unavailable(self, server) -> None:
        with pytest.raises(routing.RouterUnavailable):
            routing._transport(server(500, b"oops"), {}, 5)

    def test_a_body_that_is_not_json_is_unavailable(self, server) -> None:
        with pytest.raises(routing.RouterUnavailable):
            routing._transport(server(200, b"<html>"), {}, 5)

    def test_nobody_listening_is_unavailable(self) -> None:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        with pytest.raises(routing.RouterUnavailable):
            routing._transport(f"http://127.0.0.1:{port}/route", {}, 5)

    def test_a_router_that_hangs_is_unavailable(self) -> None:
        with socket.socket() as silent:
            silent.bind(("127.0.0.1", 0))
            silent.listen()
            port = silent.getsockname()[1]
            with pytest.raises(routing.RouterUnavailable):
                routing._transport(f"http://127.0.0.1:{port}/route", {}, 0.5)


def test_climb_of_a_flat_profile_is_zero() -> None:
    assert routing.climb_and_descent([12.0] * 50) == (0.0, 0.0)


def test_missing_elevations_are_skipped_not_zeroed() -> None:
    """A null sample read as 0 m would add the whole height back as climb."""
    climb, descent = routing.climb_and_descent([100.0, None, 101.0, None, 100.0])
    assert (climb, descent) == (0.0, 0.0)
    assert not math.isnan(climb)
