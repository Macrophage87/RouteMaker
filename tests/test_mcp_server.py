"""The MCP server (mcp/routemaker_mcp.py; the owner, 2026-10-18): its protocol, its Metro check and
loop builder against a stand-in planner. Saving to My routes is the site connector's
(tests/test_connector.py); on a rider's own computer save_route writes a GPX file."""

from __future__ import annotations

import importlib.util
import io
import json
import math
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

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
            "carrying": body.get("carrying"),
            "assist": bool(body.get("assist")),
            "hills": body.get("hills", 0),
        },
        "loop": {"overlap_pct": 4.0} if body.get("loop") else None,
    }


class StandIn(BaseHTTPRequestHandler):
    routes: list[dict] = []
    shared: dict[str, dict] = {}
    headers_seen: list[dict] = []
    fail: bool = False

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
        StandIn.headers_seen.append({k.lower(): v for k, v in self.headers.items()})
        if self.path == "/api/route":
            StandIn.routes.append(body)
            if StandIn.fail:
                return self._answer(503, {"error": "took too long", "code": "long_ride_timed_out"})
            return self._answer(200, straight_answer(body))
        if self.path == "/api/shared-routes":
            StandIn.shared[body["id"]] = body
            return self._answer(201, {"id": body["id"]})
        self._answer(404, {"error": "not here"})

    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path == "/sign-in-page":
            # What a wrong address or a captive portal answers: a page, with 200.
            page = b"<html><body>Sign in</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            return
        if url.path.startswith("/api/shared-routes/"):
            kept = StandIn.shared.get(url.path.rsplit("/", 1)[1])
            return self._answer(200, kept) if kept else self._answer(404, {"error": "gone"})
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
    StandIn.shared = {}
    StandIn.headers_seen = []
    StandIn.fail = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), StandIn)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture
def tools(stand_in, tmp_path):
    return mcp.Server(lambda: mcp.Api(stand_in), STATIONS, out_dir=tmp_path)


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
    # On a rider's own computer it has no site address to name icons from.
    assert hello["result"]["serverInfo"]["title"] == "RouteMaker"
    assert "icons" not in hello["result"]["serverInfo"]
    # An unknown version is answered with the newest it speaks, for the client to decide.
    assert (
        rpc(tools, "initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"]
        == mcp.PROTOCOL_VERSIONS[0]
    )
    assert mcp.handle(tools, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    names = [t["name"] for t in rpc(tools, "tools/list")["result"]["tools"]]
    assert names == [
        "find_place",
        "metro_stations",
        "scenic_roads_near",
        "climbs_near",
        "closures_near",
        "plan_route",
        "plan_metro_loop",
        "open_link",
        "revise_route",
        "save_route",
        "gpx_route",
    ]
    # Only save_route changes anything: the rest plan drafts.
    tools_listed = rpc(tools, "tools/list")["result"]["tools"]
    writers = [t["name"] for t in tools_listed if not t["annotations"]["readOnlyHint"]]
    assert writers == ["save_route"]
    assert rpc(tools, "nope")["error"]["code"] == -32601
    # An unknown tool is the caller's mistake in the request, not a tool's refusal.
    assert rpc(tools, "tools/call", {"name": "nope"})["error"]["code"] == -32602
    # Neither is a message that is no request at all (a batch, say): answered, not fatal.
    assert (
        mcp.handle(tools, [{"jsonrpc": "2.0", "id": 1, "method": "ping"}])["error"]["code"]
        == -32600
    )


def test_a_missing_argument_is_a_tool_error(tools) -> None:
    out = rpc(tools, "tools/call", {"name": "find_place", "arguments": {}})
    assert out["result"]["isError"] is True and "query" in out["result"]["content"][0]["text"]


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
        {},
    )
    # As frontend/src/lib/planHash.ts encodePlan writes it, so the page opens the same plan.
    assert fragment == (
        "#p=-77.03651,38.89768;-77.02101,38.90455;-77.03651,38.89768&via=1&preset=default"
        "&v=2&stress=80&hills=0&trailsoff=1&loop=1"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node for the page's own code")
@pytest.mark.parametrize(
    ("preset", "dials", "sent", "expected"),
    [
        (
            "default",
            {"stress": 85, "hills": -40, "loop": True, "avoid_gravel": True},
            {"when": "weekend"},
            {"stress": 85, "hills": -40, "loop": True, "avoidGravel": True, "when": "weekend"},
        ),
        (
            "trailmaxxing",
            {"stress": 100, "hills": 0, "target_distance_m": 160934},
            {},
            {"stress": 100, "targetDistanceM": 160934},
        ),
        (
            "cargo",
            {"stress": 75, "hills": -60, "carrying": "people", "assist": True},
            {},
            {"carrying": "people", "assist": True},
        ),
        (
            "mountain-bike",
            {"stress": 70, "hills": 0},
            {"mtb_level": 3, "mtb_preferred": 1},
            {"mtbLevel": 3, "mtbPreferred": 1},
        ),
        (
            "bikeshare",
            {"stress": 80, "hills": -20},
            {"bike": "ebike", "ending": "outside_dock"},
            {"bike": "ebike", "ending": "outside_dock"},
        ),
        ("bike-transit", {"stress": 70, "hills": 0}, {"novice_legs": True}, {"noviceLegs": True}),
    ],
)
def test_the_page_reads_the_link_as_the_plan_it_was(tmp_path, preset, dials, sent, expected):
    """The page's own decodePlan, run on the link: same points, via points, ride type and
    settings, so the link opens the route that was planned."""
    points = [(-77.03651, 38.89768), (-77.00911, 38.88990), (-77.02101, 38.90455)]
    if preset in mcp.TWO_POINT_PRESETS:
        points = points[:2]
    vias = [1] if len(points) == 3 else []
    fragment = mcp.plan_fragment(points, vias, preset, dials, sent)
    script = tmp_path / "decode.mts"
    plan_hash = Path(__file__).resolve().parents[1] / "frontend/src/lib/planHash.ts"
    script.write_text(
        f"import {{ decodePlan }} from {json.dumps(str(plan_hash))};\n"
        "console.log(JSON.stringify(decodePlan(process.argv[2])));\n"
    )
    done = subprocess.run(
        ["node", str(script), fragment], capture_output=True, text=True, timeout=60, check=True
    )
    plan = json.loads(done.stdout.strip().splitlines()[-1])
    assert plan["points"] == [list(p) for p in points]
    assert plan["vias"] == vias and plan["preset"] == preset
    for key, value in expected.items():
        assert plan["dials"].get(key) == value, (key, plan["dials"])
    # And the saved route's dials say the same.
    kept = mcp.page_dials(dials, sent)
    for key, value in expected.items():
        assert kept.get(key) == value, (key, kept)


# --- Planning against the stand-in ----------------------------------------------------------


def test_plan_route_answers_a_draft_and_keeps_nothing(tools, stand_in, tmp_path) -> None:
    out = tools.call(
        "plan_route",
        {"points": ["Union Market", "Takoma"], "stress": 80, "max_miles_from_metro": 5},
    )
    sent = StandIn.routes[-1]
    assert sent["confirm_long"] is True and sent["stress"] == 80 and sent["preset"] == "default"
    assert out["summary"]["traffic_stress"]["LTS 1"].startswith("60%")
    assert out["metro_check"]["ok"]
    assert out["link"].startswith(stand_in + "/s/") and "#p=" in out["link"]
    # A draft: nothing saved and no file written until the rider says so.
    assert out["draft_id"] in tools.drafts and out["saved"] is False
    assert not list(tmp_path.iterdir())
    kept = tools.call(
        "save_route",
        {"draft_id": out["draft_id"], "name": "Takoma"},
    )
    gpx = Path(kept["gpx_file"])
    assert gpx.parent == tmp_path and "<trkpt" in gpx.read_text() and "saved" not in kept


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


def test_saving_on_the_rider_s_computer_writes_a_file_and_says_where_my_routes_is(
    tools, tmp_path
) -> None:
    draft = tools.call("plan_route", {"points": [[-77.03, 38.9], [-77.02, 38.91]]})
    out = tools.call("save_route", {"draft_id": draft["draft_id"], "name": "Lunch ride"})
    assert Path(out["gpx_file"]).parent == tmp_path and "saved" not in out
    assert "connector" in out["notes"][0]
    save = next(t for t in tools.tools() if t["name"] == "save_route")
    assert set(save["inputSchema"]["properties"]) == {"draft_id", "name"}


def test_the_assistant_picks_the_ride_type_and_any_setting(tools) -> None:
    """The owner, 2026-10-18: "Allow the MCP server to pick whatever mode makes sense for this
    and to adjust any parameters"."""
    names = {t["name"]: t for t in mcp.TOOLS}
    offered = names["plan_route"]["inputSchema"]["properties"]
    assert set(offered["preset"]["enum"]) == set(mcp.PRESETS)
    assert "bike-transit" in mcp.PRESETS and "rebalance" in mcp.PRESETS
    for setting in mcp.PASSED_OPTIONS:
        assert setting in offered, setting
    tools.call(
        "plan_route",
        {
            "points": [[-77.03, 38.9], [-77.02, 38.91]],
            "preset": "mountain-bike",
            "hills": 40,
            "when": "weekend",
            "mtb_level": 3,
            "mtb_preferred": 2,
            "rider_weight_lb": 200,
            "trails_off": False,
        },
    )
    sent = StandIn.routes[-1]
    assert sent["preset"] == "mountain-bike" and sent["hills"] == 40 and sent["when"] == "weekend"
    assert sent["mtb_level"] == 3 and sent["mtb_preferred"] == 2
    assert sent["system_weight_kg"] == 91 and "trails_off" not in sent


def test_a_two_point_ride_type_is_refused_more_points_before_asking(tools) -> None:
    out = rpc(
        tools,
        "tools/call",
        {
            "name": "plan_route",
            "arguments": {
                "points": [[-77.03, 38.9], [-77.02, 38.91], [-77.01, 38.92]],
                "preset": "bike-transit",
            },
        },
    )
    assert out["result"]["isError"] and not StandIn.routes


def test_the_loop_keeps_another_ride_type_s_own_stress(tools) -> None:
    tools.call("plan_metro_loop", {"target_miles": 30, "preset": "trailmaxxing", "max_plans": 1})
    assert "stress" not in StandIn.routes[0] and StandIn.routes[0]["preset"] == "trailmaxxing"


def test_a_loop_whose_first_plan_fails_says_why(tools) -> None:
    StandIn.fail = True
    out = rpc(tools, "tools/call", {"name": "plan_metro_loop", "arguments": {"target_miles": 100}})
    assert out["result"]["isError"] is True
    assert "plan it in two halves" in out["result"]["content"][0]["text"]


def test_a_cancelled_call_is_not_answered_and_saves_nothing(tools, tmp_path) -> None:
    draft = tools.call("plan_route", {"points": [[-77.03, 38.9], [-77.02, 38.91]]})
    # main() registers the call before its thread starts, so a cancellation read straight
    # after it still reaches it.
    calls = {9: mcp.Call()}
    mcp.handle(
        tools,
        {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 9}},
        calls=calls,
    )
    out = mcp.handle(
        tools,
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "save_route",
                "arguments": {"draft_id": draft["draft_id"], "name": "x"},
            },
        },
        calls=calls,
    )
    assert out is None and not calls
    assert not list(tmp_path.glob("*.gpx"))


def test_a_cancellation_reaches_the_call_it_names(tools) -> None:
    running = mcp.Call()
    calls = {4: running}
    mcp.handle(
        tools,
        {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 4}},
        calls=calls,
    )
    assert running.cancelled.is_set()


def test_a_password_gated_site_gets_its_password(tools, stand_in, monkeypatch) -> None:
    monkeypatch.setenv("ROUTEMAKER_BASIC_AUTH", "rider:secret")
    api = mcp.Api(stand_in)
    api.route({"points": [[-77.03, 38.9], [-77.02, 38.91]], "preset": "default"})
    for seen in StandIn.headers_seen:
        assert seen["authorization"] == "Basic cmlkZXI6c2VjcmV0"


def test_the_password_goes_only_over_https_or_to_this_computer(monkeypatch) -> None:
    monkeypatch.setenv("ROUTEMAKER_BASIC_AUTH", "rider:secret")
    with pytest.raises(mcp.ToolError, match="https://"):
        mcp.Api("http://routes.example.org")
    for base in (
        "https://routes.example.org",
        "http://localhost",
        "http://127.0.0.1:8080",
        "http://[::1]",
    ):
        assert mcp.Api(base).basic == "Basic cmlkZXI6c2VjcmV0"
    monkeypatch.delenv("ROUTEMAKER_BASIC_AUTH")
    assert mcp.Api("http://routes.example.org").basic is None


def test_a_page_that_is_not_json_is_a_setup_problem_not_a_wrong_argument(stand_in) -> None:
    with pytest.raises(
        mcp.ToolError, match="did not answer as a RouteMaker site .*ROUTEMAKER_BASE_URL"
    ):
        mcp.Api(stand_in)._request("GET", "/sign-in-page")


@pytest.mark.parametrize("miles", ["1e999", "inf", "nan", float("inf")])
def test_a_number_out_of_range_is_a_wrong_argument_not_a_crash(tools, miles) -> None:
    for name, args in (
        ("plan_route", {"points": [[-77.03, 38.9], [-77.02, 38.91]], "target_miles": miles}),
        ("plan_metro_loop", {"target_miles": miles}),
    ):
        with pytest.raises(mcp.ToolError, match="not in the expected form"):
            tools.call(name, args)


# --- Drafts: revise, open from a link, save ------------------------------------------------


def test_a_draft_is_revised_point_by_point_and_setting_by_setting(tools) -> None:
    first = tools.call(
        "plan_route",
        {
            "points": [[-77.03, 38.90], [-77.00, 38.95], [-77.02, 38.91]],
            "via_points": [1],
            "stress": 70,
            "when": "weekend",
            "loop": True,
            # The stand-in's straight lines make a sharp V at a via point look like a spur.
            "trim_spurs": False,
        },
    )
    out = tools.call(
        "revise_route",
        {
            "draft_id": first["draft_id"],
            "add_points": [{"point": "Union Market", "after": 0}],
            "move_points": [{"index": 2, "to": [-77.01, 38.96]}],
            "stress": 90,
            "clear_settings": ["when"],
            "trim_spurs": False,
        },
    )
    sent = StandIn.routes[-1]
    assert out["revised_from"] == first["draft_id"] and out["draft_id"] != first["draft_id"]
    # Moved before the insert's shift: point 2 of the draft, now point 3.
    assert sent["points"] == [
        [-77.03, 38.90],
        [-77.0091, 38.8899],
        [-77.00, 38.95],
        [-77.01, 38.96],
    ]
    assert sent["via_points"] == [1, 2]
    assert sent["stress"] == 90 and "when" not in sent and sent["loop"] is True
    # The first draft is still there to go back to.
    back = tools.call("revise_route", {"draft_id": first["draft_id"], "remove_points": [1]})
    assert StandIn.routes[-1]["points"] == [[-77.03, 38.90], [-77.02, 38.91]]
    assert "via_points" not in StandIn.routes[-1] and StandIn.routes[-1]["stress"] == 70
    assert back["revised_from"] == first["draft_id"]


def test_an_unknown_draft_says_so(tools) -> None:
    out = rpc(tools, "tools/call", {"name": "revise_route", "arguments": {"draft_id": "d99"}})
    assert out["result"]["isError"] and "no draft d99" in out["result"]["content"][0]["text"]


def test_a_link_the_rider_changed_in_the_app_becomes_a_draft(tools) -> None:
    """The owner, 2026-10-18: "clicking on the link ... they can make changes and save or they
    can tell the server to adjust, possibly from that saved change"."""
    first = tools.call(
        "plan_route",
        {
            "points": [[-77.03, 38.9], [-77.02, 38.91]],
            "preset": "cargo",
            "carrying": "people",
            "stress": 60,
        },
    )
    # The rider opens it, adds a stop in the app, and pastes the page's address back.
    edited = first["link"].replace(
        "p=-77.03000,38.90000;", "p=-77.03000,38.90000;-77.01000,38.93000;"
    )
    out = tools.call("open_link", {"link": edited})
    sent = StandIn.routes[-1]
    assert sent["points"] == [[-77.03, 38.9], [-77.01, 38.93], [-77.02, 38.91]]
    assert sent["preset"] == "cargo" and sent["carrying"] == "people" and sent["stress"] == 60

    def plan_of(link):
        return link.split("#")[1].rsplit("&route=", 1)[0]

    assert out["draft_id"] != first["draft_id"] and plan_of(out["link"]) == plan_of(edited)


def test_a_shared_route_s_link_is_opened_by_its_plan(tools, monkeypatch) -> None:
    asked = []

    def shared(route_id):
        asked.append(route_id)
        hash_ = "#p=-77.03000,38.90000;-77.02000,38.91000&preset=gravel&v=2&stress=50&hills=0"
        return {"inputs": {"hash": hash_}, "answer": None}

    monkeypatch.setattr(tools.api, "shared_route", shared)
    tools.call("open_link", {"link": "https://routes.example.org/s/Ab12Cd34"})
    assert asked == ["Ab12Cd34"]
    assert StandIn.routes[-1]["preset"] == "gravel" and StandIn.routes[-1]["stress"] == 50


def test_a_link_with_no_route_is_refused(tools) -> None:
    out = rpc(tools, "tools/call", {"name": "open_link", "arguments": {"link": "https://x/#at=1"}})
    assert out["result"]["isError"] and not StandIn.routes


# --- The stops' short form (`q=`, frontend/src/lib/linkCode.ts; shorter ride links, 2026-10-29) --


# Written by linkCode.ts `encodePoints` (node, 2026-10-29) and read back by its `decodePoints`.
Q_VECTORS = [
    (
        "nmm2OwmttHqrFtwBu-tCukuC",
        [(-77.03652, 38.89768), (-77.00911, 38.88993), (-76.61, 39.29)],
    ),
    (
        "_n0qiB_jqlRgwo1kCgo0qiB_n0qiB_jqlRBCworrCp152It79hRoqnkQ",
        [(-180, -90), (180, 90), (0, 0), (-0.00001, 0.00001), (12.34567, -45.67892), (-77.1, 38.9)],
    ),
    ("hi_1O-lhuHritG7n8E", [(-77.00001, 38.99999), (-78.04999, 38.20001)]),
]


@pytest.mark.parametrize(("text", "points"), Q_VECTORS)
def test_the_short_form_reads_as_the_page_reads_it(text, points) -> None:
    assert mcp.decode_points(text) == [(float(x), float(y)) for x, y in points]


def test_the_short_form_stops_where_the_link_does() -> None:
    text, points = Q_VECTORS[0]
    for cut in range(len(text) + 1):
        back = mcp.decode_points(text[:cut])
        assert back == points[: len(back)], cut
    assert mcp.decode_points("") == [] and mcp.decode_points(",;!") == []
    # A character outside the form ends it; a number over 53 bits is no coordinate.
    assert mcp.decode_points(text[:10] + "!" + text[10:]) == points[:1]
    assert mcp.decode_points("_" * 18) == []


def test_the_short_form_agrees_with_the_page_s_own_code(tmp_path) -> None:
    """linkCode.ts `encodePoints` on many points, read here: the same numbers the page reads."""
    link_code = Path(__file__).resolve().parents[1] / "frontend/src/lib/linkCode.ts"
    script = tmp_path / "encode.mts"
    script.write_text(
        f"import {{ encodePoints, decodePoints }} from {json.dumps(str(link_code))};\n"
        "let seed = 11;\n"
        "const next = () => (seed = (seed * 1103515245 + 12345) % 2 ** 31) / 2 ** 31;\n"
        "const out = [];\n"
        "for (let n = 0; n < 200; n += 1) {\n"
        "  const pts = Array.from({ length: 1 + (n % 25) },"
        " () => [-78.05 + next() * 2.03, 38.2 + next() * 1.52]);\n"
        "  const q = encodePoints(pts);\n"
        "  out.push([q, decodePoints(q)]);\n"
        "}\n"
        "console.log(JSON.stringify(out));\n"
    )
    done = subprocess.run(
        ["node", str(script)], capture_output=True, text=True, timeout=60, check=True
    )
    for text, points in json.loads(done.stdout.strip().splitlines()[-1]):
        assert [list(p) for p in mcp.decode_points(text)] == points, text


def test_a_link_the_app_wrote_with_short_stops_is_opened(tools) -> None:
    text, _ = Q_VECTORS[0]
    key = "A" * 22
    link = f"https://routes.example.org/#q={text}&preset=group-ride&v=2&stress=50&k={key}"
    out = tools.call("open_link", {"link": link})
    sent = StandIn.routes[-1]
    assert sent["points"] == [[-77.03652, 38.89768], [-77.00911, 38.88993], [-76.61, 39.29]]
    assert sent["preset"] == "group-ride" and sent["stress"] == 50
    assert parse_qs(out["link"].split("#", 1)[1]).get("k") == [key]


def test_a_shared_route_kept_with_short_stops_is_opened_by_its_plan(tools, monkeypatch) -> None:
    text, _ = Q_VECTORS[2]

    def shared(route_id):
        return {"inputs": {"hash": f"#q={text}&preset=gravel&v=2&stress=50"}, "answer": None}

    monkeypatch.setattr(tools.api, "shared_route", shared)
    tools.call("open_link", {"link": "https://routes.example.org/s/Ab12Cd34"})
    sent = StandIn.routes[-1]
    assert sent["points"] == [[-77.00001, 38.99999], [-78.04999, 38.20001]]
    assert sent["preset"] == "gravel" and sent["stress"] == 50


def test_short_stops_that_hold_nothing_fall_back_to_the_older_form() -> None:
    points, _vias, _preset, _options = mcp.parse_fragment(
        "#q=!!&p=-77.03000,38.90000;-77.02000,38.91000&preset=default"
    )
    assert points == [(-77.03, 38.9), (-77.02, 38.91)]
    assert mcp.has_plan_points("#q=abc") and mcp.has_plan_points("preset=x&p=1,2")
    assert not mcp.has_plan_points("#loop=1&preset=default")
    assert not mcp.has_plan_points("#q=")


def test_points_added_and_removed_together_are_named_by_the_draft_s_numbers(tools) -> None:
    first = tools.call(
        "plan_route",
        {
            "points": [[-77.03, 38.90], [-77.00, 38.95], [-77.01, 38.96], [-77.02, 38.91]],
            "via_points": [1],
        },
    )
    tools.call(
        "revise_route",
        {
            "draft_id": first["draft_id"],
            "add_points": [{"point": [-77.05, 38.92], "after": 0, "via": False}],
            "remove_points": [2],
        },
    )
    sent = StandIn.routes[-1]
    # Point 2 of the draft goes; the via point B stays a via point, one place on.
    assert sent["points"] == [[-77.03, 38.90], [-77.05, 38.92], [-77.00, 38.95], [-77.02, 38.91]]
    assert sent["via_points"] == [2]


def test_a_new_ride_type_starts_from_its_own_settings(tools) -> None:
    first = tools.call(
        "plan_route",
        {
            "points": [[-77.03, 38.9], [-77.02, 38.91]],
            "preset": "mountain-bike",
            "mtb_level": 3,
            "stress": 100,
            "when": "weekend",
        },
    )
    tools.call("revise_route", {"draft_id": first["draft_id"], "preset": "fast"})
    sent = StandIn.routes[-1]
    assert sent["preset"] == "fast" and sent["when"] == "weekend"
    assert "mtb_level" not in sent and sent.get("stress") is None


@pytest.mark.parametrize(
    "fragment, stress, hills",
    [
        # An old (v1) link's stress moves onto the new slider, as the page's stressFromV1.
        ("p=-77.03,38.9;-77.02,38.91&preset=trailmaxxing&stress=100", 80, None),
        ("p=-77.03,38.9;-77.02,38.91&stress=45", 35, None),
        # A ride type since renamed opens at the new one's own start.
        ("p=-77.03,38.9;-77.02,38.91&preset=kids&v=2&stress=85&hills=-40", None, None),
        ("p=-77.03,38.9;-77.02,38.91&v=2&stress=inf", None, None),
    ],
)
def test_old_and_renamed_links_open_as_the_page_opens_them(fragment, stress, hills) -> None:
    points, _, preset, options = mcp.parse_fragment(fragment)
    assert options["stress"] == stress and options["hills"] == hills
    assert len(points) == 2


def test_a_call_with_a_deadline_stops_planning_while_another_plan_would_not_fit(
    tools, monkeypatch
) -> None:
    """The site's own connector answers inside one web request (core.connector): the loop plans
    once more only while a long plan still fits, and says it stopped."""
    clock = iter(range(0, 10_000, 10))
    monkeypatch.setattr(mcp.time, "monotonic", lambda: next(clock))
    call = mcp.Call(deadline=45)  # less than one long plan (48 s) is left after the first
    out = tools.call("plan_metro_loop", {"target_miles": 200, "max_plans": 3}, call)
    assert len(StandIn.routes) == 1
    assert mcp.OUT_OF_TIME in out["notes"]
    assert mcp.Call().time_for_another_plan()  # no deadline: a computer of the rider's own


# --- The independent tester's findings (2026-10-19) -----------------------------------------


@pytest.mark.parametrize(
    "said, station",
    [
        ("Navy Yard", "Navy Yard-Ballpark"),
        ("navy yard metro", "Navy Yard-Ballpark"),
        ("Union Station", "Union Station"),
        ("Gallery Place", "Gallery Pl-Chinatown"),
        ("Mount Vernon Square", "Mt Vernon Sq 7th St-Convention Center"),
        ("Ronald Reagan", "Ronald Reagan Washington National Airport"),
        ("Farragut", None),  # North or West: place search decides
        ("Adams Morgan", None),  # a neighbourhood, not Woodley Park's station
    ],
)
def test_a_station_is_found_by_the_name_riders_use(said, station) -> None:
    found = mcp.find_station(said, STATIONS)
    assert (found.name if found else None) == station


def test_the_answer_says_what_each_named_point_was_taken_as(tools) -> None:
    out = tools.call("plan_route", {"points": ["Navy Yard", "Union Market"]})
    assert [t["taken_as"] for t in out["points_taken_as"]] == [
        "Navy Yard-Ballpark Metro",
        "Union Market, Washington",
    ]
    revised = tools.call(
        "revise_route",
        {"draft_id": out["draft_id"], "add_points": [{"after": 0, "point": "Takoma"}]},
    )
    assert revised["points_taken_as"][0]["taken_as"] == "Takoma Metro"


def test_a_server_error_with_no_message_says_what_to_try() -> None:
    text = mcp.refusal(500, None)
    assert "None" not in text and "time limit" in text and "shorter" in text
    assert mcp.refusal(400, "too long") == "the site refused the route (400): too long"


def test_the_loop_s_length_is_not_sent_as_the_calm_search_target(tools) -> None:
    tools.call("plan_metro_loop", {"target_miles": 60, "preset": "trailmaxxing", "max_plans": 1})
    assert "target_distance_m" not in StandIn.routes[0]


def test_a_calm_loop_s_first_ring_allows_for_winding_roads() -> None:
    assert mcp.road_factor(None) == mcp.ROAD_FACTOR == mcp.road_factor(40)
    assert mcp.road_factor(80) == mcp.CALM_ROAD_FACTOR == mcp.road_factor(100)


def test_a_long_loop_is_kept_inside_what_the_site_plans(tools) -> None:
    asked = {"target_miles": 200, "stress": 40, "max_miles_from_metro": 10, "max_plans": 1}
    out = tools.call("plan_metro_loop", asked)
    points = [tuple(p) for p in StandIn.routes[0]["points"]]
    span = sum(mcp.haversine_mi(a, b) for a, b in zip(points, points[1:], strict=False))
    assert span <= mcp.LOOP_SPAN_MI
    assert any("at most 124 mi" in note for note in out["notes"])


def test_a_loop_with_no_start_says_where_it_starts(tools) -> None:
    out = tools.call("plan_metro_loop", {"target_miles": 60, "max_plans": 1})
    assert out["notes"][0].startswith("no start was given") and "Metro" in out["notes"][0]


def test_the_answer_leaves_out_empty_rows_and_internal_flags(tools) -> None:
    answer = {"distance_m": 1609.344, "stress_m": {"1": 1600.0, "2": 9.344}, "facility_m": {}}
    assert list(mcp.summary(answer)["traffic_stress"]) == ["LTS 1"]
    out = tools.call("plan_route", {"points": ["Union Market", "Takoma"]})
    used = out["settings_used"]
    assert "confirm_long" not in used and "candidates" not in used
    assert {"stress", "hills"} <= set(used)


def test_a_draft_becomes_a_gpx_file_on_the_rider_s_computer(tools, tmp_path) -> None:
    out = tools.call("plan_route", {"points": ["Union Market", "Takoma"]})
    gpx = tools.call("gpx_route", {"draft_id": out["draft_id"], "name": "To Takoma"})
    text = Path(gpx["gpx_file"]).read_text()
    assert "<trkpt" in text and "To Takoma" in text and gpx["gpx_file"].endswith("to-takoma.gpx")


def test_an_out_and_back_to_a_loop_waypoint_is_found_and_moved_to_its_junction() -> None:
    # East along a street, then 0.5 mi north up a dead end and back, then on east.
    east = [[-77.0 + i * 0.001, 38.9] for i in range(20)]
    up = [[east[-1][0], 38.9 + j * 0.0005] for j in range(1, 15)]
    line = (
        east
        + up
        + up[-2::-1]
        + [[east[-1][0], 38.9]]
        + [[east[-1][0] + i * 0.001, 38.9] for i in range(1, 20)]
    )
    length, junction = mcp.spur_at(line, tuple(up[-1]))
    assert 0.4 <= length <= 0.5
    assert mcp.haversine_mi(junction, tuple(east[-1])) < 0.03
    through, _ = mcp.spur_at(line, tuple(east[5]))
    assert through < mcp.SPUR_MI


def test_the_link_opens_the_exact_route_and_reads_back_unplanned(tools) -> None:
    out = tools.call("plan_route", {"points": ["Union Market", "Takoma"]})
    route_id = out["link"].rsplit("route=", 1)[1]
    assert f"/s/{route_id}#p=" in out["link"]
    kept = StandIn.shared[route_id]
    assert kept["answer"]["geometry"]["coordinates"] and kept["inputs"]["hash"].startswith("#p=")
    # The link goes with the draft: deleted after the next day at the latest, not kept a year.
    assert kept["keep"] == "until"
    assert kept["delete_after"] == mcp.draft_link_keep()["delete_after"]
    planned = len(StandIn.routes)
    opened = tools.call("open_link", {"link": out["link"]})
    assert len(StandIn.routes) == planned  # kept as it is, not planned again
    assert opened["summary"]["distance_mi"] == out["summary"]["distance_mi"]


def test_a_draft_link_is_deleted_after_the_next_day_at_the_latest() -> None:
    import datetime

    assert mcp.draft_link_keep(datetime.date(2026, 10, 20)) == {
        "keep": "until",
        "delete_after": "2026-10-21",
    }


def test_a_link_still_comes_back_when_the_exact_route_is_not_kept(tools, monkeypatch) -> None:
    def refuse(_body):
        raise mcp.ToolError("the exact route was not kept (429): slow down")

    monkeypatch.setattr(tools.api, "share", refuse)
    out = tools.call("plan_route", {"points": ["Union Market", "Takoma"]})
    assert out["link"].startswith(tools.api.base + "/#p=")
    assert "plans the route again" in out["notes"][-1]


# --- Ride keys (the owner, 2026-10-29: "All rides should have a key.") ------------------------


def _key_of(link: str) -> str | None:
    values = parse_qs(link.split("#", 1)[1]).get("k")
    return values[0] if values else None


@pytest.mark.parametrize("preset", ["group-ride", "mass-ride"])
def test_a_ride_link_the_assistant_writes_carries_a_ride_key(tools, preset) -> None:
    out = tools.call("plan_route", {"points": [[-77.03, 38.9], [-77.02, 38.91]], "preset": preset})
    key = _key_of(out["link"])
    assert key and mcp.RIDE_KEY_RE.fullmatch(key)
    route_id = out["link"].rsplit("route=", 1)[1]
    assert _key_of(StandIn.shared[route_id]["inputs"]["hash"]) == key
    # Never sent to the planner.
    assert key not in json.dumps(StandIn.routes[-1])


def test_a_link_that_is_not_a_ride_carries_no_key(tools) -> None:
    out = tools.call("plan_route", {"points": [[-77.03, 38.9], [-77.02, 38.91]]})
    assert _key_of(out["link"]) is None


def test_a_ride_draft_keeps_its_key_as_it_is_revised_and_opened(tools) -> None:
    first = tools.call(
        "plan_route",
        {"points": [[-77.03, 38.9], [-77.02, 38.91]], "preset": "group-ride", "trim_spurs": False},
    )
    key = _key_of(first["link"])
    revised = tools.call(
        "revise_route",
        {"draft_id": first["draft_id"], "move_points": [{"index": 1, "to": [-77.01, 38.92]}]},
    )
    assert _key_of(revised["link"]) == key
    # Another ride type is another ride: Mass Ride gets its own key, a plain ride type none.
    mass = tools.call("revise_route", {"draft_id": first["draft_id"], "preset": "mass-ride"})
    assert _key_of(mass["link"]) not in (None, key)
    plain = tools.call("revise_route", {"draft_id": first["draft_id"], "preset": "fast"})
    assert _key_of(plain["link"]) is None
    # A ride link the rider pastes back keeps the ride the riders are on.
    edited = first["link"].replace("p=-77.03000,38.90000;", "p=-77.03000,38.90000;-77.01,38.93;")
    opened = tools.call("open_link", {"link": edited})
    assert _key_of(opened["link"]) == key


def test_the_fragment_keeps_one_key() -> None:
    fragment = "#p=1,2;3,4&preset=group-ride&k=" + "A" * 43
    assert mcp.with_ride_key(fragment, "B" * 43) == "#p=1,2;3,4&preset=group-ride&k=" + "B" * 43
    assert mcp.with_ride_key(fragment, None) == "#p=1,2;3,4&preset=group-ride"
    assert mcp.ride_key_of(fragment) == "A" * 43 and mcp.ride_key_of("#k=short") is None
    assert mcp.ride_key_for("default", "A" * 43) is None
    assert mcp.ride_key_for("group-ride", "A" * 43) == "A" * 43
    # A new key is 16 bytes, 22 characters (the owner, 2026-10-29); an older link's 43 still is one.
    made = mcp.ride_key_for("mass-ride", None)
    assert len(made) == 22 and mcp.RIDE_KEY_RE.fullmatch(made)


# --- Featured routes posts ------------------------------------------------------------------


def encode_polyline(line, precision: int = 6) -> str:
    """[[lon, lat], ...] as an encoded polyline, the way Valhalla writes one."""
    factor, out, last = 10**precision, [], (0, 0)
    for lon, lat in line:
        here = (round(lat * factor), round(lon * factor))
        for delta in (here[0] - last[0], here[1] - last[1]):
            value = ~(delta << 1) if delta < 0 else delta << 1
            while value >= 0x20:
                out.append(chr((0x20 | (value & 0x1F)) + 63))
                value >>= 5
            out.append(chr(value + 63))
        last = here
    return "".join(out)


def test_a_line_to_follow_decodes_as_it_was_encoded() -> None:
    line = [[-77.00636, 38.89645], [-76.9, 39.0], [-76.6155, 39.30712]]
    assert mcp.decode_polyline(encode_polyline(line)) == line
    with pytest.raises(mcp.ToolError):
        mcp.decode_polyline(encode_polyline(line)[:-1])


def test_the_post_tool_is_offered_only_where_posts_may_be_written(tools) -> None:
    # On a rider's own computer (and on the site for anyone but an instance admin) it is no tool.
    names = [t["name"] for t in tools.tools()]
    assert "draft_route_post" not in names
    out = rpc(tools, "tools/call", {"name": "draft_route_post", "arguments": {}})
    assert out["error"]["code"] == -32602
    admin = mcp.Server(lambda: None, stations=STATIONS, posts=True)
    assert "draft_route_post" in [t["name"] for t in admin.tools()]
