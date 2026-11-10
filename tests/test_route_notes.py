"""Route notes from the connector (the owner, 2026-11-10: "Allow for notes to be added through the
mcp. Such as a dangerous intersection or a point of interest"): the route_notes tool, the link's
`nt=` written as the app writes it (frontend/src/lib/routeNotes.ts), and the notes as rows of the
phone cue images and marks of the route view and picture."""

from __future__ import annotations

from test_mcp_server import STATIONS, mcp, rpc, stand_in  # noqa: F401 - fixture

from core import cue_cards, route_picture


def _server(stand_in, tmp_path):  # noqa: F811
    return mcp.Server(lambda: mcp.Api(stand_in), STATIONS, out_dir=tmp_path)


def _plan(server) -> dict:
    planned = rpc(
        server,
        "tools/call",
        {"name": "plan_route", "arguments": {"points": [[-77.00, 38.90], [-77.00, 38.95]]}},
    )["result"]
    return planned["structuredContent"]


def _notes(server, draft_id: str, notes: list) -> dict:
    args = {"draft_id": draft_id, "notes": notes}
    return rpc(server, "tools/call", {"name": "route_notes", "arguments": args})["result"]


def test_the_link_writes_and_reads_notes_as_the_app_does() -> None:
    values = mcp.encode_notes(
        [
            {
                "kind": "caution",
                "lon": -77.041912,
                "lat": 38.900181,
                "text": " Busy  crossing, no light ",
            }
        ]
    )
    # encodeNotes: kind letter, five decimals, the words last (a comma in them kept).
    assert values == ["c,-77.04191,38.90018,Busy crossing, no light"]
    fragment = mcp.plan_fragment(
        [(-77.05, 38.9), (-77.0, 38.9)],
        [],
        "default",
        {"stress": 50, "hills": 0},
        {},
        notes=[{"kind": "interest", "lon": -77.02, "lat": 38.9, "text": "Mural"}],
    )
    assert "&nt=i,-77.02000,38.90000,Mural&" in fragment
    _, _, _, options = mcp.parse_fragment(fragment)
    assert options["route_notes"] == [
        {"kind": "interest", "lon": -77.02, "lat": 38.9, "text": "Mural"}
    ]
    # One that does not read is left out; the words are capped as the page caps them.
    assert mcp.decode_notes(["x,1,2,Hi", "c,-77,38.9,", "c,-77,138.9,Hi"]) == []
    assert len(mcp.clean_note_text("x" * 200)) == mcp.NOTE_TEXT_MAX


def test_notes_are_kept_on_a_new_draft_and_its_link(stand_in, tmp_path) -> None:  # noqa: F811
    server = _server(stand_in, tmp_path)
    planned = _plan(server)
    result = _notes(
        server,
        planned["draft_id"],
        [
            {"kind": "caution", "text": "Busy crossing", "at": [-77.0, 38.92]},
            {"kind": "interest", "text": "Great view", "at_mile": 1.0},
        ],
    )
    assert not result["isError"], result
    out = result["structuredContent"]
    assert out["draft_id"] != planned["draft_id"] and out["revised_from"] == planned["draft_id"]
    assert [(n["kind"], n["text"]) for n in out["route_notes"]] == [
        ("caution", "Busy crossing"),
        ("interest", "Great view"),
    ]
    assert out["route_notes"][1]["mi"] == 1.0
    assert "nt=c,-77.00000,38.92000,Busy+crossing" in out["link"]
    kept = server.drafts.get(out["draft_id"])
    assert len(kept.options["route_notes"]) == 2
    # The route view draws them (route_notes is a view tool).
    view = result["_meta"]["routemaker/route-view"]
    assert [n["kind"] for n in view["notes"]] == ["caution", "interest"]
    # A revision keeps them, and an empty list takes them away.
    revised = rpc(
        server,
        "tools/call",
        {"name": "revise_route", "arguments": {"draft_id": out["draft_id"], "preset": "road-bike"}},
    )["result"]["structuredContent"]
    assert len(revised["route_notes"]) == 2
    cleared = _notes(server, out["draft_id"], [])["structuredContent"]
    assert cleared["route_notes"] == [] and "nt=" not in cleared["link"]


def test_a_note_off_the_route_is_put_on_it_or_refused(stand_in, tmp_path) -> None:  # noqa: F811
    server = _server(stand_in, tmp_path)
    draft_id = _plan(server)["draft_id"]
    # About 170 m east of the line: put on it, and said so.
    near = _notes(
        server, draft_id, [{"kind": "caution", "text": "Pothole", "at": [-76.998, 38.92]}]
    )
    out = near["structuredContent"]
    assert out["route_notes"][0]["lon"] == -77.0 and any("put on it" in n for n in out["notes"])
    # About 2 mi off: refused.
    far = _notes(server, draft_id, [{"kind": "caution", "text": "Far", "at": [-76.96, 38.92]}])
    assert far["isError"] and "from the route" in far["content"][0]["text"]
    bad = _notes(server, draft_id, [{"kind": "danger", "text": "x", "at_mile": 1}])
    assert bad["isError"]


def test_notes_near_the_line_are_rows_of_the_cue_images() -> None:
    answer = {
        "distance_m": 2000.0,
        "geometry": {"type": "LineString", "coordinates": [[-77.0, 38.9], [-77.0, 38.918]]},
        "description": [
            {"kind": "stretch", "from_m": 0, "to_m": 2000, "street": "1st Street", "turn": None}
        ],
    }
    notes = [
        {"kind": "interest", "lon": -77.0, "lat": 38.91, "text": "Café mural"},
        {"kind": "caution", "lon": -77.0002, "lat": 38.905, "text": "Rails in the road"},
        # About 430 m off the line: on the map only.
        {"kind": "caution", "lon": -76.995, "lat": 38.91, "text": "Far"},
    ]
    along = mcp.notes_along(answer, notes)
    assert [n["text"] for n in along] == ["Rails in the road", "Café mural"]
    rows = cue_cards.cue_rows(answer, notes=along)
    assert [(r["turn"], r["road"], r["arrow"]["kind"]) for r in rows] == [
        ("Start", "1st St", "start"),
        ("Caution", "Rails in the road", "caution"),
        ("Note", "Café mural", "note"),
        ("Finish", "", "finish"),
    ]
    # The images lay them out (the words folded to the glyphs' ASCII).
    assert cue_cards.count(answer, "Test", notes=along) == 1


def test_the_picture_draws_the_notes() -> None:
    view = {
        "line": "",
        "points": [],
        "spans": [],
        "notes": [{"lon_lat": [-77.0, 38.91], "kind": "caution", "text": "x", "mi": 0.5}],
    }
    line = [[-77.0, 38.9], [-77.0, 38.92]]
    with_note = route_picture.draw(view, line)
    without = route_picture.draw({**view, "notes": []}, line)
    assert with_note and without and with_note != without


def test_a_note_s_icon_travels_in_the_link_and_the_view(stand_in, tmp_path) -> None:  # noqa: F811
    # The owner, 2026-11-10: "have that note appear on the map with a choice of icon".
    assert mcp.encode_notes(
        [{"kind": "caution", "lon": -77.0, "lat": 38.9, "text": "Hole", "icon": "pothole"}]
    ) == ["c.pothole,-77.00000,38.90000,Hole"]
    assert mcp.decode_notes(["i.coffee,-77,38.9,Cafe", "i.nope,-77,38.9,X"]) == [
        {"kind": "interest", "lon": -77.0, "lat": 38.9, "text": "Cafe", "icon": "coffee"},
        {"kind": "interest", "lon": -77.0, "lat": 38.9, "text": "X"},
    ]
    server = _server(stand_in, tmp_path)
    draft_id = _plan(server)["draft_id"]
    result = _notes(
        server,
        draft_id,
        [{"kind": "interest", "text": "Coffee", "at_mile": 1, "icon": "coffee"}],
    )
    assert "nt=i.coffee," in result["structuredContent"]["link"]
    assert result["_meta"]["routemaker/route-view"]["notes"][0]["icon"] == "☕"
    bad = _notes(server, draft_id, [{"kind": "caution", "text": "x", "at_mile": 1, "icon": "x"}])
    assert bad["isError"]


def test_bad_notes_are_refused_and_a_note_only_link_keeps_its_line(stand_in, tmp_path) -> None:  # noqa: F811
    server = _server(stand_in, tmp_path)
    draft_id = _plan(server)["draft_id"]
    for wrong in (
        ["not a note"],
        [{"kind": "caution", "text": "x", "at_mile": -1}],
        [{"kind": "caution", "text": "x", "at_mile": 99}],
        [{"kind": "caution", "text": "z" * 80, "at_mile": 0.1 * n} for n in range(20)],
    ):
        assert _notes(server, draft_id, wrong)["isError"], wrong
    # The link's notes are not its plan: a note added in the app keeps a kept route's line.
    plain = "#p=-77.00000,38.90000;-77.00000,38.95000&preset=default"
    noted = plain + "&nt=c,-77.00000,38.92000,Busy"
    assert mcp.plan_params(plain) == mcp.plan_params(noted)
    # A link's notes stay under the server's limit, however long their words.
    values = mcp.encode_notes(
        [{"kind": "caution", "lon": -77, "lat": 38.9, "text": "注意" * 40}] * mcp.MAX_NOTES
    )
    assert sum(len(mcp.urllib.parse.urlencode({"nt": v})) + 1 for v in values) <= mcp.NOTES_LINK_MAX


def test_a_stop_s_icon_travels_in_the_link_and_a_revision(stand_in, tmp_path) -> None:  # noqa: F811
    # The owner, 2026-11-10: "Stops can have icons too" (pointKinds.ts encodeStopIcons).
    fragment = mcp.plan_fragment(
        [(-77.05, 38.9), (-77.03, 38.9), (-77.02, 38.9), (-77.0, 38.9)],
        [2],
        "default",
        {"stress": 50, "hills": 0},
        {},
        icons={1: "coffee", 2: "water", 3: "pin", 0: "food"},
    )
    # A stop's only: never a via point's, the start's or (not a loop) the end's.
    assert "&si=1%3Acoffee&" in fragment and "si=2" not in fragment and "si=3" not in fragment
    _, _, _, options = mcp.parse_fragment(fragment + "&si=1%3Anosuch")
    assert options["stop_icons"] == {1: "coffee"}
    server = _server(stand_in, tmp_path)
    planned = rpc(
        server,
        "tools/call",
        {
            "name": "plan_route",
            "arguments": {"points": [[-77.00, 38.90], [-77.00, 38.92], [-77.00, 38.95]]},
        },
    )["result"]["structuredContent"]

    def revise(**args):
        call = {"name": "revise_route", "arguments": {"draft_id": planned["draft_id"], **args}}
        return rpc(server, "tools/call", call)["result"]

    out = revise(stop_icons={"1": "coffee"})["structuredContent"]
    assert "si=1%3Acoffee" in out["link"]
    assert server.drafts.get(out["draft_id"]).options["stop_icons"] == {1: "coffee"}
    assert revise(stop_icons={"0": "coffee"})["isError"]
    assert revise(stop_icons={"1": "nosuch"})["isError"]
