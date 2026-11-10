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


def _mass_plan() -> mcp.Plan:
    m = mcp.METRES_PER_MILE
    answer = {
        "distance_m": 2 * m,
        "geometry": {"coordinates": [[-77.0, 38.9], [-77.0, 38.93]]},
        "stress_spans": [{"from_m": 0, "to_m": 2 * m, "tier": 2, "facility": None}],
        "profile": {
            "m": [0, 0.5 * m, m, 1.5 * m, 2 * m],
            "elevation_m": [10.0, 11.0, 12.0, 13.0, 14.0],
            "riders_per_min": [130, 130, 72, None, 130],
        },
        "mass_capacity": {
            "need_riders_per_min": 100,
            "corkers": {"junctions": [{"m": round(0.25 * m), "street": "K Street", "corkers": 2}]},
        },
    }
    return mcp.Plan([(-77.0, 38.9), (-77.0, 38.93)], [], "mass-ride", answer, None, {})


def test_a_mass_ride_carries_its_flow_and_corkers() -> None:
    # The owner, 2026-11-10, asked whether the view works on Mass Ride: "Very much so" to its flow
    # graph and corkers.
    view = mcp.route_view(_mass_plan(), {}, "A")
    mass = view["mass"]
    assert mass["need"] == 100
    # Equal neighbours join; a stretch with no figure is left out, not drawn as nothing.
    assert mass["steps"] == [[0, 1.0, 130], [1.0, 1.5, 72]]
    assert mass["corkers"] == [{"mi": 0.25, "street": "K Street", "corkers": 2}]
    # Corkers not checked (no crossings) says so, as None; another ride type has no mass at all.
    plan = _mass_plan()
    plan.answer["mass_capacity"]["corkers"] = None
    assert mcp.route_view(plan, {}, "A")["mass"]["corkers"] is None
    plan.answer["profile"]["riders_per_min"] = None
    assert mcp.route_view(plan, {}, "A")["mass"] is None


def test_a_picture_is_drawn_only_when_asked_and_sent_as_an_image(stand_in, tmp_path) -> None:  # noqa: F811
    drawn = []

    def picture(view, line):
        drawn.append((view, line))
        return b"\x89PNG-picture"

    server = mcp.Server(
        lambda: mcp.Api(stand_in),
        STATIONS,
        out_dir=tmp_path,
        picture=picture,
        picture_link=lambda draft_id: f"https://example.invalid/mcp/gpx/{draft_id}.mac.png",
    )
    # Not on a rider's own computer (no picture), and on the site only when asked for.
    assert "route_picture" not in {t["name"] for t in _server(stand_in, tmp_path).tools()}
    tool = next(t for t in server.tools() if t["name"] == "route_picture")
    assert tool["description"].startswith("Only when the rider asks")
    planned = rpc(
        server,
        "tools/call",
        {"name": "plan_route", "arguments": {"points": ["Union Market", "Takoma"]}},
    )["result"]
    assert not drawn
    draft_id = planned["structuredContent"]["draft_id"]
    assert planned["_meta"][mcp.VIEW_META_KEY]["picture_link"].endswith(f"{draft_id}.mac.png")
    answer = rpc(
        server, "tools/call", {"name": "route_picture", "arguments": {"draft_id": draft_id}}
    )
    result = answer["result"]
    assert not result["isError"]
    image, text = result["content"]
    assert image == {
        "type": "image",
        "data": base64.b64encode(b"\x89PNG-picture").decode(),
        "mimeType": "image/png",
    }
    # The picture is not in the text nor the structured copy; the link is.
    assert (
        image["data"] not in text["text"] and mcp.IMAGES_PRIVATE not in result["structuredContent"]
    )
    assert result["structuredContent"]["picture_link"].endswith(".png")
    view, line = drawn[0]
    assert view["draft_id"] == draft_id and line == server.drafts.get(draft_id).plan.line
    gone = rpc(server, "tools/call", {"name": "route_picture", "arguments": {"draft_id": "dnone"}})
    assert gone["result"]["isError"]


def test_the_picture_draws_the_map_graphs_and_mass_ride(basemap) -> None:
    from core import route_picture

    plan = _mass_plan()
    view = mcp.route_view(plan, {"closures": [{"from_mi": 1.2, "what": "Trail closed"}]}, "A")
    png = route_picture.draw(view, plan.line)
    assert png.startswith(b"\x89PNG")
    width, height = (int.from_bytes(png[16 + 4 * i : 20 + 4 * i], "big") for i in range(2))
    assert width == route_picture.WIDTH
    # The flow graph and corkers make the Mass Ride picture taller than the same route's without.
    plain = dict(view, mass=None)
    plain_png = route_picture.draw(plain, plan.line)
    assert int.from_bytes(plain_png[20:24], "big") < height
    assert route_picture.draw(view, plan.line[:1]) is None


def test_corker_marks_a_few_pixels_apart_are_one_place() -> None:
    from core import route_picture

    marks = [(10, 10, 1), (20, 10, 2), (100, 10, 1)]
    assert route_picture._gathered(marks) == [(10, 10, 3), (100, 10, 1)]


def test_a_mass_ride_view_has_the_corkers_held_at_once_and_its_triage() -> None:
    plan = _mass_plan()
    m = mcp.METRES_PER_MILE
    plan.answer["mass_capacity"]["corkers"] = {
        "headline": 4,
        "most_at_once": 2,
        "rotation_factor": 2,
        "at_least": False,
        "junctions": [
            {
                "m": round(0.25 * m),
                "street": "K Street",
                "corkers": 2,
                "exit_m": round(0.5 * m),
                "lts": 4,
            },
            {
                "m": round(1.0 * m),
                "street": "Elm Street",
                "corkers": 2,
                "exit_m": round(1.2 * m),
                "lts": 3,
            },
        ],
    }
    view = mcp.route_view(plan, {}, "A")["mass"]
    assert view["about"] == 4 and view["most"] == 2
    assert view["held"] == [
        [0, 0.25, 0],
        [0.25, 0.5, 2],
        [0.5, 1.0, 0],
        [1.0, 1.2, 2],
        [1.2, 2.0, 0],
    ]
    triaged = mcp.route_view(plan, {}, "A", {"skip": ["elm"]})["mass"]
    assert [c["street"] for c in triaged["corkers"]] == ["K Street"]
    assert [c["street"] for c in triaged["skipped"]] == ["Elm Street"]
    assert triaged["held"][-1] == [0.5, 2.0, 0]


def test_corking_is_the_tools_own_and_never_sent_to_the_site() -> None:
    assert "corking" in mcp.PASSED_OPTIONS and "corking" in mcp.LINK_ONLY_OPTIONS
    body = mcp.request_body([(0, 0), (1, 1)], [], "mass-ride", {"corking": {"from_lts": 4}})
    assert "corking" not in body
