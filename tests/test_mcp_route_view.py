"""The connector's route view (the owner, 2026-11-10: "Is it possible for the MCP server to return a
map and the various relevant graphs?"; picked an interactive view with a text fallback): the MCP
Apps page, the tools that name it, the data it draws sent beside the answer and never in it, and the
base map tool it calls."""

from __future__ import annotations

import base64
import json
import zlib

import pytest
from test_mcp_server import STATIONS, StandIn, mcp, rpc, stand_in  # noqa: F401 - fixture
from test_preview_basemap import _tile, write_archive

from core import preview_basemap, route_view_map

VIEW_TOOLS = {"plan_route", "revise_route", "open_link", "plan_metro_loop"}


def _key(draft_id: str) -> str:
    return f"key-for-{draft_id}"


def _server(stand_in, tmp_path, basemap=None):  # noqa: F811 - the fixture's value
    return mcp.Server(
        lambda: mcp.Api(stand_in),
        STATIONS,
        out_dir=tmp_path,
        basemap=basemap,
        view_key=_key if basemap else None,
    )


MAP_ARGS = {
    "draft_id": "d1",
    "key": _key("d1"),
    "centre": [-77.03, 38.904],
    "scale": 256 * 2**12,
    "width": 300,
    "height": 200,
}


def test_the_drafting_tools_name_the_view_and_nothing_else_does(stand_in, tmp_path) -> None:  # noqa: F811
    listed = rpc(_server(stand_in, tmp_path), "tools/list")["result"]["tools"]
    named = {t["name"] for t in listed if (t.get("_meta") or {}).get("ui")}
    assert named == VIEW_TOOLS
    for tool in listed:
        if tool["name"] in VIEW_TOOLS:
            assert tool["_meta"]["ui"]["resourceUri"] == mcp.VIEW_URI
            # The extension's older, flat spelling, which some assistant apps still read.
            assert tool["_meta"]["ui/resourceUri"] == mcp.VIEW_URI
    # The tool list itself is unchanged: the view rides on its own copy of each entry.
    assert all("_meta" not in t for t in mcp.TOOLS)
    # No base map here (a rider's own computer): no base map tool either.
    assert "route_view_map" not in {t["name"] for t in listed}
    assert rpc(_server(stand_in, tmp_path), "tools/call", {"name": "route_view_map"})["error"]


def test_the_base_map_tool_is_the_views_alone(stand_in, tmp_path) -> None:  # noqa: F811
    server = _server(stand_in, tmp_path, basemap=lambda *a: None)
    # Without a key to give the view, no tool (and no key in the view).
    keyless = mcp.Server(lambda: mcp.Api(stand_in), STATIONS, basemap=lambda *a: None)
    assert "route_view_map" not in {t["name"] for t in keyless.tools()}
    tool = next(t for t in server.tools() if t["name"] == "route_view_map")
    # Hidden from the model by an assistant app that shows MCP Apps (visibility "app").
    assert tool["_meta"]["ui"]["visibility"] == ["app"]
    assert tool["annotations"]["readOnlyHint"] is True


def test_the_view_is_a_resource_that_needs_no_other_site(stand_in, tmp_path) -> None:  # noqa: F811
    server = _server(stand_in, tmp_path)
    listed = rpc(server, "resources/list")["result"]["resources"]
    assert [(r["uri"], r["mimeType"]) for r in listed] == [
        (mcp.VIEW_URI, "text/html;profile=mcp-app")
    ]
    read = rpc(server, "resources/read", {"uri": mcp.VIEW_URI})["result"]["contents"][0]
    assert read["mimeType"] == "text/html;profile=mcp-app"
    page = read["text"]
    assert page.startswith("<!doctype html>") and mcp.VIEW_META_KEY in page
    # Asks for nothing from anywhere: the host's default policy loads no script, style, font or
    # picture from any other site, so the page must not need one.
    assert read["_meta"]["ui"]["csp"] == {}
    for loads in ('src="http', "src='http", 'href="http', "@import", "url(http"):
        assert loads not in page
    assert rpc(server, "resources/read", {"uri": "ui://elsewhere"})["error"]["code"] == -32002


def test_the_route_view_rides_beside_the_answer_not_in_it(stand_in, tmp_path) -> None:  # noqa: F811
    server = _server(stand_in, tmp_path)
    answer = rpc(
        server,
        "tools/call",
        {"name": "plan_route", "arguments": {"points": ["Union Market", "Takoma"]}},
    )["result"]
    assert not answer["isError"]
    view = answer["_meta"][mcp.VIEW_META_KEY]
    # The model's answer (the text and the structured copy) is as before: no view in it.
    text = answer["content"][-1]["text"]
    assert mcp.VIEW_PRIVATE not in text and mcp.VIEW_PRIVATE not in answer["structuredContent"]
    assert [c["type"] for c in answer["content"]] == ["text"]
    draft = answer["structuredContent"]
    assert view["draft_id"] == draft["draft_id"] and view["link"] == draft["link"]
    # The line, as the router drew it, to a metre.
    line = mcp.decode_polyline(view["line"], view["line_precision"])
    drawn = server.drafts.get(draft["draft_id"]).plan.line
    assert len(line) == len(drawn)
    assert all(
        abs(a[0] - b[0]) < 1e-5 and abs(a[1] - b[1]) < 1e-5
        for a, b in zip(line, drawn, strict=True)
    )
    # Stress by mile, end to end, on the route's own miles.
    spans = view["spans"]
    assert spans[0][0] == 0 and spans[-1][1] == pytest.approx(view["miles"], abs=0.01)
    assert [s[2] for s in spans[:3]] == [3, 1, 4]
    # The profile in miles and feet.
    assert view["profile"][0] == [0, round(10.0 * mcp.FEET_PER_METRE)]
    assert view["points"][0]["lon_lat"] == draft["points"][0] and not view["points"][0]["via"]
    assert view["figures"]["distance"] == draft["summary"]["distance"]


def test_tools_that_draft_nothing_send_no_view(stand_in, tmp_path) -> None:  # noqa: F811
    answer = rpc(
        _server(stand_in, tmp_path), "tools/call", {"name": "metro_stations", "arguments": {}}
    )["result"]
    assert "_meta" not in answer


def test_a_half_step_is_drawn_as_its_half_and_a_long_profile_is_thinned() -> None:
    answer = {
        "distance_m": 2000.0,
        "geometry": {"coordinates": [[-77.0, 38.9], [-76.98, 38.9]]},
        "stress_spans": [
            {"from_m": 0, "to_m": 1000, "tier": 3, "half": True, "facility": "lane"},
            {"from_m": 1000, "to_m": 2000, "tier": None, "facility": None},
        ],
        "profile": {
            "m": list(range(0, 2000, 2)),
            "elevation_m": [None, *([5.0] * 498), 60.0, *([5.0] * 500)],
        },
    }
    plan = mcp.Plan([(-77.0, 38.9), (-76.98, 38.9)], [], "default", answer, None, {})
    view = mcp.route_view(plan, {}, "A")
    assert view["spans"][0][2:] == [3.5, "lane"] and view["spans"][1][2:] == [None, None]
    assert len(view["profile"]) <= mcp.VIEW_PROFILE_POINTS + 2
    # The summit survives the thinning.
    assert max(ft for _mi, ft in view["profile"]) == round(60.0 * mcp.FEET_PER_METRE)


@pytest.fixture
def basemap(tmp_path, settings):
    path = tmp_path / "region.pmtiles"
    write_archive(path, _tile())
    settings.BASEMAP_PMTILES = path
    preview_basemap._archive.cache_clear()
    yield path
    preview_basemap._archive.cache_clear()


def test_the_base_map_is_drawn_from_the_box_alone(stand_in, tmp_path, basemap) -> None:  # noqa: F811
    server = _server(stand_in, tmp_path, basemap=route_view_map.draw)
    answer = rpc(server, "tools/call", {"name": "route_view_map", "arguments": MAP_ARGS})["result"]
    assert not answer["isError"]
    image = answer["content"][0]
    assert image["type"] == "image" and image["mimeType"] == "image/png"
    png = base64.b64decode(image["data"])
    assert png.startswith(b"\x89PNG") and png[16:24] == (300).to_bytes(4, "big") + (200).to_bytes(
        4, "big"
    )
    raw = zlib.decompress(png[png.index(b"IDAT") + 4 : png.index(b"IEND") - 8])
    assert len(raw) == 200 * (300 * 3 + 1)
    # The lake at the centre is water.
    middle = 100 * (300 * 3 + 1) + 1 + 150 * 3
    assert tuple(raw[middle : middle + 3]) == preview_basemap.WATER
    # The picture is not in the model's text, and the town names come as words to draw.
    assert "data" not in json.loads(answer["content"][-1]["text"])
    assert answer["structuredContent"]["drawn"] is True
    # Nothing is kept for it: no file written.
    assert not list(tmp_path.glob("*.png"))


@pytest.mark.parametrize(
    "args",
    [
        {**MAP_ARGS, "scale": 1e9},
        {**MAP_ARGS, "width": 5000},
        {**MAP_ARGS, "height": 481},
        {**MAP_ARGS, "centre": [-777, 38.904]},
        # Without the view's key (the model never sees it): nothing drawn.
        {**MAP_ARGS, "key": ""},
        {**MAP_ARGS, "draft_id": "d2"},
    ],
)
def test_the_base_map_tool_refuses_a_view_out_of_bounds(stand_in, tmp_path, args) -> None:  # noqa: F811
    drawn = []
    server = _server(stand_in, tmp_path, basemap=lambda *a: drawn.append(a))
    answer = rpc(server, "tools/call", {"name": "route_view_map", "arguments": args})["result"]
    assert answer["isError"] and not drawn


def test_no_base_map_for_the_box_is_said_not_failed(stand_in, tmp_path, settings) -> None:  # noqa: F811
    settings.BASEMAP_PMTILES = tmp_path / "none.pmtiles"
    preview_basemap._archive.cache_clear()
    server = _server(stand_in, tmp_path, basemap=route_view_map.draw)
    answer = rpc(server, "tools/call", {"name": "route_view_map", "arguments": MAP_ARGS})["result"]
    assert not answer["isError"] and answer["structuredContent"] == {"drawn": False}
    assert [c["type"] for c in answer["content"]] == ["text"]
    assert StandIn.routes == []


def test_every_drafting_tool_sends_the_view_and_a_refusal_sends_none(stand_in, tmp_path) -> None:  # noqa: F811
    server = _server(stand_in, tmp_path, basemap=lambda *a: None)

    def call(name, arguments):
        return rpc(server, "tools/call", {"name": name, "arguments": arguments})["result"]

    planned = call("plan_route", {"points": ["Union Market", "Takoma"]})
    view = planned["_meta"][mcp.VIEW_META_KEY]
    draft_id = planned["structuredContent"]["draft_id"]
    # The base map key is the view's: in _meta, never in the model's answer.
    assert view["map_key"] == _key(draft_id)
    assert "map_key" not in planned["content"][-1]["text"]
    revised = call("revise_route", {"draft_id": draft_id, "stress": 90})
    assert (
        revised["_meta"][mcp.VIEW_META_KEY]["draft_id"] == revised["structuredContent"]["draft_id"]
    )
    opened = call("open_link", {"link": planned["structuredContent"]["link"]})
    assert mcp.VIEW_META_KEY in opened["_meta"]
    # A refusal is text alone.
    refused = call("revise_route", {"draft_id": "d0", "stress": 90})
    assert refused["isError"] and "_meta" not in refused


def test_junctions_and_closures_are_placed_on_the_routes_own_miles() -> None:
    # The traced metres (stress spans, junctions) run short of distance_m: the view's miles are
    # the route's, as the answer says them.
    answer = {
        "distance_m": 3218.688,
        "geometry": {"coordinates": [[-77.0, 38.9], [-76.97, 38.9]]},
        "stress_spans": [{"from_m": 0, "to_m": 1000, "tier": 2, "facility": None}],
        "intersections": [{"m": 500, "severity": "red", "reason": "x"}],
    }
    plan = mcp.Plan([(-77.0, 38.9), (-76.97, 38.9)], [], "default", answer, None, {})
    view = mcp.route_view(plan, {"closures": [{"from_mi": 1.2, "what": "Trail closed"}]}, "A")
    assert view["spans"] == [[0, 2.0, 2, None]]
    assert view["junctions"] == [{"mi": 1.0, "level": "very high", "reason": "x"}]
    assert view["closures"] == [{"mi": 1.2, "kind": "closure", "what": "Trail closed"}]
