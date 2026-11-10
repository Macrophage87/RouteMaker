"""The phone cue images (core.cue_cards, the connector's cue_cards tool): the owner, 2026-11-10,
"some people perfer to just navigate by a static image can you make a series of turn cues that are
sized for a phone from the mcp and also exportable from plan. Basically show the arrows"; "make
sure stops are listed"."""

from __future__ import annotations

import base64

from test_mcp_server import STATIONS, mcp, rpc, stand_in  # noqa: F401 - fixture

from core import cue_cards

MI = 1609.344


def _stretch(at_m: float, street: str, movement: str | None = None, **turn) -> dict:
    return {
        "kind": "stretch",
        "from_m": at_m,
        "to_m": at_m + 50,
        "street": street,
        "severity": None,
        "turn": None if movement is None else {"movement": movement, "onto": street, **turn},
    }


def _answer(entries: list[dict], distance_m: float = 5000.0) -> dict:
    return {"distance_m": distance_m, "climb_m": 30, "description": entries}


def test_rows_are_start_turns_stops_and_finish_in_order() -> None:
    answer = _answer(
        [
            _stretch(0, "North Capitol Street Northwest"),
            _stretch(400, "K Street Northwest", "right"),
            {"kind": "via", "from_m": 900, "to_m": 900, "via": 1},
            {"kind": "via", "from_m": 1500, "to_m": 1500, "via": 2},
            _stretch(1600, "Q Street Northwest", "left", across="16th Street Northwest"),
            {"kind": "avoid", "from_m": 2000, "to_m": 2000, "street": "New York Avenue"},
            {"kind": "walk", "from_m": 2500, "to_m": 2600, "street": None},
            _stretch(3000, "Rock Creek Trail", "uturn"),
        ]
    )
    rows = cue_cards.cue_rows(answer, vias=[1], names={2: "Dupont Circle"})
    assert [(r["turn"], r["road"]) for r in rows] == [
        ("Start", "North Capitol St NW"),
        ("Right", "K St NW"),
        # Point 1 is a through point, no cue; point 2 is the first stop, by its name.
        ("Dupont Circle", ""),
        ("Left", "Q St NW"),
        ("Caution", "New York Ave"),
        ("Walk", ""),
        ("U-turn", "Rock Creek Trl"),
        ("Finish", ""),
    ]
    stop = rows[2]
    assert stop["arrow"] == {"kind": "stop", "number": 1} and stop["reason"] == "Stop 1"
    assert rows[3]["arrow"] == {"kind": "turn", "moves": ["left"], "across": True}
    assert rows[4]["reason"] == "Avoid-rated"
    unnamed = cue_cards.cue_rows(answer, vias=[1])
    assert unnamed[2]["turn"] == "Stop 1" and unnamed[2]["reason"] == ""


def test_a_jog_is_one_row_and_one_arrow_through_its_turns() -> None:
    answer = _answer(
        [
            _stretch(0, "P Street"),
            _stretch(500, "6th Street Northwest", "right"),
            _stretch(560, "Q Street Northwest", "bear_left"),
            # Too far after the last: a row of its own.
            _stretch(900, "7th Street Northwest", "left"),
        ]
    )
    rows = cue_cards.cue_rows(answer)
    assert [r["turn"] for r in rows] == ["Start", "Right", "Left", "Finish"]
    assert rows[1]["then"] == "then bear left onto Q St NW"
    assert rows[1]["arrow"]["moves"] == ["right", "bear_left"]


def test_every_picture_fits_its_box_and_points_its_way() -> None:
    for arrow in (
        {"kind": "turn", "moves": ["left"], "across": False},
        {"kind": "turn", "moves": ["right", "left", "right"], "across": False},
        {"kind": "turn", "moves": ["uturn"], "across": False},
        {"kind": "turn", "moves": ["bear_right"], "across": True},
        {"kind": "cross"},
        {"kind": "walk"},
        {"kind": "start"},
        {"kind": "finish"},
        {"kind": "stop", "number": 3},
        {"kind": "caution"},
        {"kind": "note"},
    ):
        shape = cue_cards.arrow_shape(arrow)
        points = [
            p for group in ("strokes", "thin", "fills") for line in shape[group] for p in line
        ]
        assert all(0 <= x <= 100 and 0 <= y <= 100 for x, y in points), arrow
    left = cue_cards.arrow_shape({"kind": "turn", "moves": ["left"], "across": False})
    right = cue_cards.arrow_shape({"kind": "turn", "moves": ["right"], "across": False})
    # The head's tip is the arrow's leftmost point for a left, rightmost for a right.
    assert left["fills"][0][0][0] == min(x for x, _ in left["fills"][0] + left["strokes"][0])
    assert right["fills"][0][0][0] == max(x for x, _ in right["fills"][0] + right["strokes"][0])
    assert cue_cards.arrow_shape({"kind": "stop", "number": 3})["label"] == "3"
    # The same numbers as the browser's (frontend/src/lib/cueArrow.test.ts).
    head = [(round(x, 1), round(y, 1)) for x, y in left["fills"][0]]
    assert head == [(28, 35.3), (60.3, 6), (60.3, 64.7)]


def _size(png: bytes) -> tuple[int, int]:
    return int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")


def test_a_long_route_runs_to_numbered_phone_sized_images() -> None:
    turns = [_stretch(0, "Start Street")] + [
        _stretch(300 * k, f"Street {k}", "left" if k % 2 else "right") for k in range(1, 30)
    ]
    images = cue_cards.draw(_answer(turns, 9500), "Default route", credit="Route data: test.")
    assert len(images) >= 3
    assert all(png.startswith(b"\x89PNG") and _size(png) == (1179, 2556) for png in images)
    one = cue_cards.draw(_answer(turns[:4], 1000), "Default route")
    assert len(one) == 1


def _site(stand_in, tmp_path, drawn):  # noqa: F811
    def draw(*args):
        drawn.append(args)
        return [b"\x89PNG-1", b"\x89PNG-2"]

    return mcp.Server(
        lambda: mcp.Api(stand_in),
        STATIONS,
        out_dir=tmp_path,
        cue_cards=draw,
        cue_cards_link=lambda draft_id, page: f"https://example.invalid/{draft_id}-cues-{page}.png",
    )


def test_the_tool_returns_the_images_and_a_link_each(stand_in, tmp_path) -> None:  # noqa: F811
    drawn: list = []
    server = _site(stand_in, tmp_path, drawn)
    plain = mcp.Server(lambda: mcp.Api(stand_in), STATIONS, out_dir=tmp_path)
    assert "cue_cards" not in {t["name"] for t in plain.tools()}
    tool = next(t for t in server.tools() if t["name"] == "cue_cards")
    assert tool["description"].startswith("Only when the rider asks")
    planned = rpc(
        server,
        "tools/call",
        {"name": "plan_route", "arguments": {"points": ["Union Market", "Takoma"]}},
    )["result"]
    draft_id = planned["structuredContent"]["draft_id"]
    result = rpc(server, "tools/call", {"name": "cue_cards", "arguments": {"draft_id": draft_id}})[
        "result"
    ]
    assert not result["isError"]
    images = [c for c in result["content"] if c["type"] == "image"]
    assert [base64.b64decode(c["data"]) for c in images] == [b"\x89PNG-1", b"\x89PNG-2"]
    out = result["structuredContent"]
    assert out["draft_id"] == draft_id and out["images"] == 2 and "revised" not in out
    assert out["links"] == [
        f"https://example.invalid/{draft_id}-cues-1.png",
        f"https://example.invalid/{draft_id}-cues-2.png",
    ]
    answer, _title, vias, names, credit = drawn[0]
    assert answer is server.drafts.get(draft_id).plan.answer
    assert names == {} and credit.startswith("Route data: ")
    gone = rpc(server, "tools/call", {"name": "cue_cards", "arguments": {"draft_id": "dnone"}})
    assert gone["result"]["isError"]


def test_stop_names_are_kept_on_a_new_draft(stand_in, tmp_path) -> None:  # noqa: F811
    drawn: list = []
    server = _site(stand_in, tmp_path, drawn)
    planned = rpc(
        server,
        "tools/call",
        {
            "name": "plan_route",
            "arguments": {"points": ["Union Market", "Dupont Circle", "Takoma"]},
        },
    )["result"]
    draft_id = planned["structuredContent"]["draft_id"]
    args = {"draft_id": draft_id, "stop_names": {"1": "Coffee", "7": "No such stop"}}
    result = rpc(server, "tools/call", {"name": "cue_cards", "arguments": args})["result"]
    out = result["structuredContent"]
    assert out["draft_id"] != draft_id and "revised" in out
    kept = server.drafts.get(out["draft_id"])
    assert kept.plan.names == {1: "Coffee"} and kept.revises == draft_id
    assert drawn[0][3] == {1: "Coffee"}
    assert server.drafts.get(draft_id).plan.names == {}


def test_each_stop_starts_an_image_of_its_own() -> None:
    """The owner, 2026-11-10: "Have splits at stops"."""
    entries = [
        _stretch(0, "Start Street"),
        _stretch(300, "First Street", "left"),
        {"kind": "via", "from_m": 600, "to_m": 600, "via": 1},
        _stretch(700, "Second Street", "right"),
    ]
    assert len(cue_cards.draw(_answer(entries, 1000), "Default route")) == 2
    # A through point is no stop: one image.
    assert len(cue_cards.draw(_answer(entries, 1000), "Default route", vias=[1])) == 1
