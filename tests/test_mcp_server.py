"""The MCP server (mcp/routemaker_mcp.py; the owner, 2026-10-18): its protocol, its Metro check and
loop builder against a stand-in planner, and its save against the site's real keyed endpoint."""

from __future__ import annotations

import importlib.util
import io
import json
import math
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from test_accounts import send, signed_in

from core.models import SavedRoute

_spec = importlib.util.spec_from_file_location(
    "routemaker_mcp", Path(__file__).resolve().parents[1] / "mcp" / "routemaker_mcp.py"
)
mcp = importlib.util.module_from_spec(_spec)
sys.modules["routemaker_mcp"] = mcp
_spec.loader.exec_module(mcp)

STATIONS = mcp.load_stations()
ANSWER = json.loads((Path(__file__).parent / "data" / "route_answer.json").read_text())


def straight_answer(body: dict) -> dict:
    """A planner's answer whose line runs straight through the points (and back to the start on
    a loop), 30% longer on the road than in straight lines."""
    points = [tuple(p) for p in body["points"]]
    if body.get("loop") and points[0] != points[-1]:
        points.append(points[0])
    line, ends = [list(points[0])], []
    for a, b in zip(points, points[1:], strict=False):
        steps = max(1, math.ceil(mcp.haversine_mi(a, b) / 0.5))
        for i in range(1, steps + 1):
            line.append([a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps])
        ends.append(len(line) - 1)
    miles = sum(mcp.haversine_mi(tuple(p), tuple(q)) for p, q in zip(line, line[1:], strict=False))
    distance = miles * mcp.METRES_PER_MILE * 1.3
    return {
        **ANSWER,
        "geometry": {"type": "LineString", "coordinates": line},
        "leg_ends": ends,
        "distance_m": distance,
        "duration_s": distance / 4.5,
        "stress_m": {
            "1": distance * 0.6,
            "2": distance * 0.3,
            "3": distance * 0.1,
            "4": 0.0,
            "5": 0.0,
            "unknown": 0.0,
        },
        "dials": {
            **ANSWER["dials"],
            "stress": body.get("stress", 70),
            "loop": bool(body.get("loop")),
        },
        "loop": {"overlap_pct": 4.0} if body.get("loop") else None,
    }


class StandIn(BaseHTTPRequestHandler):
    routes: list[dict] = []

    def log_message(self, *args) -> None:
        pass

    def _answer(self, status: int, payload) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/route":
            StandIn.routes.append(body)
            return self._answer(200, straight_answer(body))
        self._answer(404, {"error": "not here"})

    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path == "/api/geocode":
            q = parse_qs(url.query)["q"][0]
            return self._answer(
                200,
                {
                    "results": [
                        {
                            "name": q,
                            "label": f"{q}, Washington",
                            "lon": -77.0091,
                            "lat": 38.8899,
                            "kind": "house",
                        }
                    ],
                    "attribution": [],
                },
            )
        self._answer(404, {"error": "not here"})


@pytest.fixture
def stand_in():
    StandIn.routes = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), StandIn)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture
def tools(stand_in, tmp_path):
    return mcp.Server(lambda: mcp.Api(stand_in, save_key=""), STATIONS, out_dir=tmp_path)


def rpc(server, method, params=None, msg_id=1):
    return mcp.handle(
        server, {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}}
    )


# --- Protocol -------------------------------------------------------------------------------


def test_it_introduces_itself_and_lists_its_tools(tools) -> None:
    hello = rpc(
        tools,
        "initialize",
        {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "any", "version": "1"},
        },
    )
    assert hello["result"]["protocolVersion"] == "2025-03-26"
    assert hello["result"]["capabilities"] == {"tools": {"listChanged": False}}
    # An unknown version is answered with the newest it speaks, for the client to decide.
    assert (
        rpc(tools, "initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"]
        == mcp.PROTOCOL_VERSIONS[0]
    )
    assert mcp.handle(tools, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    names = [t["name"] for t in rpc(tools, "tools/list")["result"]["tools"]]
    assert names == ["find_place", "metro_stations", "plan_route", "plan_metro_loop"]
    assert rpc(tools, "nope")["error"]["code"] == -32601


def test_a_refusal_is_a_tool_error_not_a_crash(tools) -> None:
    out = rpc(
        tools, "tools/call", {"name": "plan_route", "arguments": {"points": [[0, 0], [1, 1]]}}
    )
    assert out["result"]["isError"] is True
    assert "outside the map's area" in out["result"]["content"][0]["text"]


def test_the_stdio_loop_answers_line_by_line(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ROUTEMAKER_BASE_URL", "http://127.0.0.1:9")
    lines = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        "not json",
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "metro_stations", "arguments": {}},
            }
        ),
    ]
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join(lines) + "\n"))
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    mcp.main()
    answers = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [a.get("id") for a in answers] == [1, None, 2]
    assert answers[1]["error"]["code"] == -32700
    assert len(answers[2]["result"]["structuredContent"]["stations"]) == 98


# --- Points, the Metro check and the link ---------------------------------------------------


def test_points_from_pairs_station_names_and_place_search(tools) -> None:
    api = tools.api
    assert mcp.as_point([-77.0, 38.9], api, STATIONS)[0] == (-77.0, 38.9)
    assert mcp.as_point({"lon": -77.0, "lat": 38.9}, api, STATIONS)[0] == (-77.0, 38.9)
    point, said = mcp.as_point("shady grove metro", api, STATIONS)
    assert said == "Shady Grove Metro" and point[1] > 39.1
    assert mcp.as_point("Union Market", api, STATIONS)[1] == "Union Market, Washington"
    with pytest.raises(mcp.ToolError, match="swapped"):
        mcp.as_point([38.9, -77.0], api, STATIONS)


def test_the_metro_check_finds_the_stretch_past_the_limit() -> None:
    # From Shady Grove 12 mi north-west to Sugarloaf country and back: far from any station.
    shady = next(s for s in STATIONS if s.name == "Shady Grove").point
    far = mcp.destination(shady, 300, 12)
    check = mcp.metro_check([list(shady), list(far), list(shady)], 5, STATIONS)
    assert not check["ok"]
    assert len(check["stretches_over_limit"]) == 1
    stretch = check["stretches_over_limit"][0]
    assert 4.5 < stretch["from_mi"] < 6 and 18 < stretch["to_mi"] < 19.5
    assert 11.5 < check["farthest_mi"] <= 12.05
    # Within the limit all the way: nothing to report.
    near = mcp.destination(shady, 120, 3)
    assert mcp.metro_check([list(shady), list(near)], 5, STATIONS)["ok"]


def test_the_link_is_the_page_s_own_fragment() -> None:
    fragment = mcp.plan_fragment(
        [(-77.036512, 38.89768), (-77.02101, 38.90455), (-77.036512, 38.89768)],
        [1],
        "default",
        {"stress": 80, "hills": 0, "loop": True, "trails_off": True},
    )
    # As frontend/src/lib/planHash.ts encodePlan writes it, so the page opens the same plan.
    assert fragment == (
        "#p=-77.03651,38.89768;-77.02101,38.90455;-77.03651,38.89768&via=1&preset=default"
        "&v=2&stress=80&hills=0&trailsoff=1&loop=1"
    )


# --- Planning against the stand-in ----------------------------------------------------------


def test_plan_route_summarises_links_and_writes_a_gpx(tools, stand_in, tmp_path) -> None:
    out = tools.call(
        "plan_route",
        {"points": ["Union Market", "Takoma"], "stress": 80, "max_miles_from_metro": 5},
    )
    sent = StandIn.routes[-1]
    assert sent["confirm_long"] is True and sent["stress"] == 80 and sent["preset"] == "default"
    assert out["summary"]["traffic_stress"]["LTS 1"].startswith("60%")
    assert out["metro_check"]["ok"]
    assert out["link"].startswith(stand_in + "/#p=")
    gpx = Path(out["gpx_file"])
    assert gpx.parent == tmp_path and "<trkpt" in gpx.read_text()
    assert "saved" not in out


def test_plan_route_fixes_a_stray_by_way_of_the_nearest_station(tools) -> None:
    named = {s.name: list(s.point) for s in STATIONS}
    # Vienna to Shady Grove in a straight line passes almost 6 mi from any station, about
    # halfway between Spring Hill and North Bethesda.
    out = tools.call(
        "plan_route",
        {
            "points": [named["Vienna/Fairfax-GMU"], named["Shady Grove"]],
            "max_miles_from_metro": 3,
            "fix_metro_rounds": 2,
        },
    )
    again = StandIn.routes[1]
    added = next(name for name, point in named.items() if point == again["points"][1])
    assert added in ("Spring Hill", "North Bethesda") and again["via_points"] == [1]
    assert out["notes"][0].startswith(f"added {added} as a via point: 6.3 -> ")
    # The repaired route is the one answered: less of it is over the limit.
    assert out["metro_check"]["miles_over_limit"] < 6.3 and len(out["points"]) > 2


def test_a_stray_with_its_nearest_station_already_a_point_is_left_as_it_is(tools) -> None:
    shady = next(s for s in STATIONS if s.name == "Shady Grove").point
    far = mcp.destination(shady, 300, 10)
    out = tools.call(
        "plan_route",
        {
            "points": [list(shady), list(far), list(shady)],
            "max_miles_from_metro": 3,
            "fix_metro_rounds": 2,
        },
    )
    assert len(StandIn.routes) == 1 and not out["metro_check"]["ok"]


def test_the_metro_loop_goes_round_dc_inside_the_limit(tools) -> None:
    out = tools.call("plan_metro_loop", {"target_miles": 100, "max_miles_from_metro": 5})
    first = StandIn.routes[0]
    assert first["stress"] == 80 and first["loop"] is True
    assert first["points"][0] == first["points"][-1]
    assert first["via_points"] == list(range(1, len(first["points"]) - 1))
    assert len(first["points"]) <= mcp.MAX_POINTS
    # Every waypoint is within the limit with room to spare.
    for point in first["points"]:
        assert mcp.nearest_station(tuple(point), STATIONS)[1] <= 0.6 * 5 + 0.01
    # It goes all the way round: waypoints in every quarter of the compass.
    quarters = {int(mcp.bearing_deg(mcp.DC_CENTRE, tuple(p)) // 90) for p in first["points"]}
    assert quarters == {0, 1, 2, 3}
    assert out["metro_check"]["limit_mi"] == 5
    assert 80 <= out["summary"]["distance_mi"] <= 120
    assert "loop=1" in out["link"]


def test_the_metro_loop_starts_where_asked(tools) -> None:
    tools.call("plan_metro_loop", {"target_miles": 60, "start": "Union Market", "max_plans": 1})
    sent = StandIn.routes[0]
    assert sent["points"][0] == [-77.0091, 38.8899] == sent["points"][-1]
    assert len(StandIn.routes) == 1


def test_progress_is_reported_when_the_client_asks(tools) -> None:
    sent = []
    out = mcp.handle(
        tools,
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "plan_metro_loop",
                "_meta": {"progressToken": "p1"},
                "arguments": {"target_miles": 40, "max_plans": 2},
            },
        },
        send=sent.append,
    )
    assert out["result"]["isError"] is False
    assert sent and all(m["method"] == "notifications/progress" for m in sent)
    assert sent[0]["params"]["progressToken"] == "p1"


def test_saving_without_a_key_says_how_to_get_one(tools) -> None:
    out = rpc(
        tools,
        "tools/call",
        {
            "name": "plan_route",
            "arguments": {"points": [[-77.03, 38.9], [-77.02, 38.91]], "save_as": "Lunch ride"},
        },
    )
    assert out["result"]["isError"] is True
    assert "Settings > AI assistant key" in out["result"]["content"][0]["text"]


# --- Saving, end to end against the site ----------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_a_planned_route_lands_in_my_routes(live_server, stand_in, tmp_path) -> None:
    client, user, csrf = signed_in()
    secret = send(client, "post", "/api/me/assistant-key", {}, csrf).json()["secret"]

    class Both(mcp.Api):
        """Plans on the stand-in and saves on the live site."""

        def __init__(self):
            super().__init__(live_server.url, save_key=secret)

        def route(self, body):
            return mcp.Api(stand_in, save_key="").route(body)

    server = mcp.Server(Both, STATIONS, out_dir=tmp_path)
    out = server.call(
        "plan_route",
        {
            "points": [[-77.0365, 38.8977], [-77.0091, 38.8899]],
            "loop": True,
            "stress": 80,
            "save_as": "MCP loop",
        },
    )
    assert out["saved"]["name"] == "MCP loop"
    row = SavedRoute.objects.get(user=user)
    assert row.name == "MCP loop" and row.source == "plan"
    assert row.inputs["hash"] == out["link"][len(live_server.url) + 1 :]
    assert row.inputs["dials"]["stress"] == 80 and row.inputs["dials"]["loop"] is True
    assert row.answer["candidates"] is None
    # The rider sees it in My routes, and opens it as the page opens any saved route.
    listed = client.get("/api/me/routes").json()["routes"]
    assert [r["name"] for r in listed] == ["MCP loop"]
