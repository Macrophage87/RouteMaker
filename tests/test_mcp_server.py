"""The MCP server (mcp/routemaker_mcp.py; the owner, 2026-10-18): its protocol, its Metro check and
loop builder against a stand-in planner, and its save against the site's real keyed endpoint."""

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
            "carrying": body.get("carrying"),
            "assist": bool(body.get("assist")),
            "hills": body.get("hills", 0),
        },
        "loop": {"overlap_pct": 4.0} if body.get("loop") else None,
    }


class StandIn(BaseHTTPRequestHandler):
    routes: list[dict] = []
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
    StandIn.headers_seen = []
    StandIn.fail = False
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
    assert names == [
        "find_place",
        "metro_stations",
        "plan_route",
        "plan_metro_loop",
        "open_link",
        "revise_route",
        "save_route",
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
    assert out["link"].startswith(stand_in + "/#p=")
    # A draft: nothing saved and no file written until the rider says so.
    assert out["draft_id"] in tools.drafts and out["saved"] is False
    assert not list(tmp_path.iterdir())
    kept = tools.call(
        "save_route",
        {"draft_id": out["draft_id"], "name": "Takoma", "my_routes": False, "gpx_file": True},
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


def test_saving_without_a_key_says_how_to_get_one(tools) -> None:
    out = rpc(
        tools,
        "tools/call",
        {
            "name": "save_route",
            "arguments": {
                "draft_id": tools.call("plan_route", {"points": [[-77.03, 38.9], [-77.02, 38.91]]})[
                    "draft_id"
                ],
                "name": "Lunch ride",
            },
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
    draft = server.call(
        "plan_route",
        {"points": [[-77.0365, 38.8977], [-77.0091, 38.8899]], "loop": True, "stress": 75},
    )
    assert not SavedRoute.objects.exists()
    out = server.call("revise_route", {"draft_id": draft["draft_id"], "stress": 80})
    assert not SavedRoute.objects.exists()
    saved = server.call("save_route", {"draft_id": out["draft_id"], "name": "MCP loop"})
    assert saved["saved"]["name"] == "MCP loop"
    row = SavedRoute.objects.get(user=user)
    assert row.name == "MCP loop" and row.source == "plan"
    assert row.inputs["hash"] == out["link"][len(live_server.url) + 1 :]
    assert row.inputs["dials"]["stress"] == 80 and row.inputs["dials"]["loop"] is True
    assert row.answer["candidates"] is None
    # The rider sees it in My routes, and opens it as the page opens any saved route.
    listed = client.get("/api/me/routes").json()["routes"]
    assert [r["name"] for r in listed] == ["MCP loop"]


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
    class Saving(mcp.Api):
        def save(self, body):  # pragma: no cover - must not be reached
            raise AssertionError("saved after the client gave up")

    draft = tools.call("plan_route", {"points": [[-77.03, 38.9], [-77.02, 38.91]]})
    tools._api = Saving(tools.api.base, save_key="rmk_x")
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
                "arguments": {"draft_id": draft["draft_id"], "name": "x", "gpx_file": True},
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


def test_a_password_gated_site_gets_its_password_and_the_key_its_own_header(
    tools, stand_in, monkeypatch
) -> None:
    monkeypatch.setenv("ROUTEMAKER_BASIC_AUTH", "rider:secret")
    api = mcp.Api(stand_in, save_key="rmk_abc")
    with pytest.raises(mcp.ToolError):
        api.save({"name": "x"})  # the stand-in has no save endpoint
    api.route({"points": [[-77.03, 38.9], [-77.02, 38.91]], "preset": "default"})
    for seen in StandIn.headers_seen:
        assert seen["authorization"] == "Basic cmlkZXI6c2VjcmV0"
    assert StandIn.headers_seen[0]["x-routemaker-key"] == "rmk_abc"
    assert "x-routemaker-key" not in StandIn.headers_seen[1]


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
    assert (
        out["draft_id"] != first["draft_id"] and out["link"].split("#")[1] == edited.split("#")[1]
    )


def test_a_shared_route_s_link_is_opened_by_its_plan(tools, monkeypatch) -> None:
    asked = []

    def shared(route_id):
        asked.append(route_id)
        return "#p=-77.03000,38.90000;-77.02000,38.91000&preset=gravel&v=2&stress=50&hills=0"

    monkeypatch.setattr(tools.api, "shared_fragment", shared)
    tools.call("open_link", {"link": "https://routes.example.org/s/Ab12Cd34"})
    assert asked == ["Ab12Cd34"]
    assert StandIn.routes[-1]["preset"] == "gravel" and StandIn.routes[-1]["stress"] == 50


def test_a_link_with_no_route_is_refused(tools) -> None:
    out = rpc(tools, "tools/call", {"name": "open_link", "arguments": {"link": "https://x/#at=1"}})
    assert out["result"]["isError"] and not StandIn.routes


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
