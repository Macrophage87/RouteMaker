"""What a plan's answer says the route rides (mcp/routemaker_mcp.py `route_details`; the owner,
2026-10-25: "The goal would be for a new user to be able to make routes like this."): its roads
with their stress and scenic designations, its busy stretches and junctions, its small
detours, and place names searched near the route's other points."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

if "routemaker_mcp" in sys.modules:
    mcp = sys.modules["routemaker_mcp"]
else:
    _spec = importlib.util.spec_from_file_location(
        "routemaker_mcp", Path(__file__).resolve().parents[1] / "mcp" / "routemaker_mcp.py"
    )
    mcp = importlib.util.module_from_spec(_spec)
    sys.modules["routemaker_mcp"] = mcp
    _spec.loader.exec_module(mcp)

MI = mcp.METRES_PER_MILE
# Peach Tree Road, near Barnesville: a degree of longitude is about 53.7 mi here.
ORIGIN = (-77.40, 39.17)
LON_MI = 1 / 53.7
LAT_MI = 1 / 69.0


def stretch(street, from_mi, to_mi, tier, facility=None):
    return {
        "kind": "stretch",
        "street": street,
        "from_mi": from_mi,
        "to_mi": to_mi,
        "from_m": round(from_mi * MI),
        "to_m": round(to_mi * MI),
        "tier": tier,
        "facility": facility,
    }


def answer_of(entries, **extra):
    distance = entries[-1]["to_mi"] * MI
    return {
        "distance_m": distance,
        "description": entries,
        "stress_spans": [{"from_m": 0, "to_m": round(distance)}],
        "intersections": [],
        **extra,
    }


def at(east_mi, north_mi=0.0):
    return [ORIGIN[0] + east_mi * LON_MI, ORIGIN[1] + north_mi * LAT_MI]


# --- The road list ---------------------------------------------------------------------------


def test_the_roads_are_listed_in_order_with_miles_stress_and_scenic_designation() -> None:
    answer = answer_of(
        [
            stretch("C&O Canal Towpath", 0.0, 20.0, 1, "path"),
            stretch("path", 20.0, 20.1, 1, "path"),
            stretch("Peach Tree Road", 20.1, 22.0, 4),
            stretch("Moore Road", 22.0, 23.0, 2),
            stretch("path", 23.0, 23.1, 1, "path"),  # a break in one road: no row
            stretch("Moore Road", 23.1, 24.5, 2),
            stretch("Bucklodge Road", 24.5, 26.0, 2),
            stretch("Bucklodge Road", 26.0, 26.3, 3),
        ],
        scenic_roads=[
            {
                "from_m": round(20.1 * MI),
                "to_m": round(24.5 * MI),
                "road": "Peach Tree Road",
                "designation": "Rustic Road (Montgomery County)",
            }
        ],
    )
    roads = mcp.road_list(answer)["roads"]
    assert [(r["road"], r["miles"], r["lts"]) for r in roads] == [
        ("C&O Canal Towpath", 20.0, 1),
        ("path", 0.1, 1),
        ("Peach Tree Road", 1.9, 4),
        ("Moore Road", 2.5, 2),
        ("Bucklodge Road", 1.8, 2),
    ]
    assert roads[0]["facility"] == "path"
    assert roads[2]["scenic"] == roads[3]["scenic"] == "Rustic Road (Montgomery County)"
    assert "scenic" not in roads[4]
    assert roads[4]["worst_lts"] == 3 and roads[4]["miles_lts_3_up"] == 0.3


def test_a_long_list_groups_each_run_of_short_links_into_one_row() -> None:
    entries, at_mi = [], 0.0
    for block in range(30):
        entries.append(stretch(f"Trail {block}", at_mi, at_mi + 1.0, 1, "path"))
        at_mi += 1.0
        for link in range(4):
            entries.append(stretch(f"Street {block}-{link}", at_mi, at_mi + 0.1, 2))
            at_mi += 0.1
    roads = mcp.road_list(answer_of(entries))["roads"]
    # 30 trails and 30 groups of links: past the aim, but a mile of trail keeps its row.
    assert len(roads) == 60
    assert roads[1]["road"].startswith("4 short links: Street 0-0, Street 0-1")
    # Nothing is lost: the rows cover the whole route.
    assert sum(r["miles"] for r in roads) == pytest.approx(at_mi, abs=1.0)


def test_no_description_no_road_list() -> None:
    assert mcp.road_list({"distance_m": 1000.0}) is None


# --- Busy stretches and junctions -------------------------------------------------------------


def test_busy_stretches_join_neighbours_and_keep_short_lts_4() -> None:
    answer = answer_of(
        [
            stretch("Quiet Lane", 0.0, 1.0, 1),
            stretch("Darnestown Road", 1.0, 1.3, 3),
            stretch("River Road", 1.3, 1.5, 4),
            stretch("Quiet Lane", 1.5, 2.0, 2),
            stretch("Short Busy Street", 2.0, 2.05, 3),  # LTS 3 under 0.1 mi: left out
            stretch("Quiet Lane", 2.05, 3.0, 1),
            stretch("Seneca Road", 3.0, 3.03, 4),  # LTS 4 is said however short
            stretch("Quiet Lane", 3.03, 4.0, 1),
        ]
    )
    busy = mcp.busy_stretches(answer)
    assert [(b["from_mi"], b["to_mi"], b["lts"], b["roads"]) for b in busy] == [
        (1.0, 1.5, 4, ["Darnestown Road", "River Road"]),
        (3.0, 3.0, 4, ["Seneca Road"]),
    ]


def test_very_high_junctions_are_listed_and_higher_ones_counted() -> None:
    answer = answer_of(
        [stretch("Quiet Lane", 0.0, 1.0, 1), stretch("Darnestown Road", 1.0, 2.0, 3)],
        intersections=[
            {"m": round(1.5 * MI), "severity": "red", "reason": "Left across 4 lanes"},
            {"m": round(0.5 * MI), "severity": "orange", "reason": "Crossing"},
        ],
    )
    out = mcp.risky_junctions(answer)
    assert out["higher_count"] == 1
    assert [(j["at_mi"], j["road"], j["reason"]) for j in out["very_high"]] == [
        (1.5, "Darnestown Road", "Left across 4 lanes")
    ]


# --- Small detours ----------------------------------------------------------------------------


def _farm_lane_loop():
    """East along Peach Tree Road, a loop up a farm lane at 0.5 mi, back to the road at 0.52."""
    line = [at(x / 20) for x in range(11)]  # 0 to 0.5 mi east
    line += [at(0.5, 0.1), at(0.52, 0.1), at(0.52)]  # up the lane and back
    line += [at(0.52 + x / 20) for x in range(1, 11)]
    entries = [
        stretch("Peach Tree Road", 0.0, 0.5, 4),
        stretch("unnamed road", 0.5, 0.72, 2),
        stretch("Peach Tree Road", 0.72, 1.22, 4),
    ]
    return line, answer_of(entries)


def test_a_loop_off_a_road_and_back_onto_it_is_a_small_detour() -> None:
    line, answer = _farm_lane_loop()
    found = mcp.small_detours(line, (), mcp._street_finder(answer), 1.22)
    assert len(found) == 1
    detour = found[0]
    assert 0.4 <= detour["from_mi"] <= 0.5 and 0.7 <= detour["to_mi"] <= 0.8
    assert detour["extra_mi"] >= 0.15
    assert detour["farthest_point"][1] > ORIGIN[1] + 0.08 * LAT_MI


def test_a_hairpin_on_one_trail_is_not_a_detour() -> None:
    line, _ = _farm_lane_loop()
    answer = answer_of([stretch("Seneca Creek Trail", 0.0, 1.22, 1, "path")])
    assert mcp.small_detours(line, (), mcp._street_finder(answer), 1.22) == []


def test_a_detour_to_a_stop_is_the_point_of_the_trip() -> None:
    line, answer = _farm_lane_loop()
    stop = tuple(at(0.51, 0.1))
    assert mcp.small_detours(line, [stop], mcp._street_finder(answer), 1.22) == []


def test_a_straight_route_has_no_detours() -> None:
    line = [at(x / 10) for x in range(51)]
    assert mcp.small_detours(line) == []


def test_the_details_say_it_all_in_one_answer() -> None:
    line, answer = _farm_lane_loop()
    answer["geometry"] = {"coordinates": line}
    answer["scenic_roads"] = [
        {"from_m": 0, "to_m": round(0.5 * MI), "road": "Peach Tree Road", "designation": "Rustic"}
    ]
    plan = mcp.Plan([tuple(line[0]), tuple(line[-1])], [], "trailmaxxing", answer, None, {})
    out = mcp.route_details(plan)
    assert {"roads", "busy_stretches", "junctions", "scenic_roads", "small_detours"} <= set(out)
    assert out["scenic_roads"] == [
        {"road": "Peach Tree Road", "designation": "Rustic", "miles": 0.5}
    ]


# --- Place names near the route ---------------------------------------------------------------

BOYDS = {"name": "Moore Road", "label": "Moore Road, Boyds, MD", "lon": -77.3703, "lat": 39.1785}
CENTREVILLE = {
    "name": "Moore Road",
    "label": "Moore Road, Centreville, VA",
    "lon": -77.45,
    "lat": 38.84,
}
LEWIS_ORCHARDS = (-77.38755, 39.168773)


def test_a_name_in_two_places_takes_the_one_near_the_route_and_says_the_other() -> None:
    chosen, others = mcp.pick_place("Moore Road", [CENTREVILLE, BOYDS], [LEWIS_ORCHARDS])
    assert chosen is BOYDS and others == [CENTREVILLE]


def test_a_name_in_two_places_far_from_the_route_is_asked_back() -> None:
    with pytest.raises(mcp.ToolError, match="Ask the rider") as asked:
        mcp.pick_place("Moore Road", [CENTREVILLE, BOYDS], [(-76.6, 39.3)])
    assert "Centreville" in str(asked.value) and "Boyds" in str(asked.value)
    # With nothing to go by, the search's first match, and the other said.
    assert mcp.pick_place("Moore Road", [CENTREVILLE, BOYDS], []) == (CENTREVILLE, [BOYDS])


def test_one_place_is_taken_however_far_from_the_route() -> None:
    penn = {
        "name": "Penn Station",
        "label": "Penn Station, Baltimore",
        "lon": -76.6155,
        "lat": 39.307,
    }
    assert mcp.pick_place("Penn Station", [penn], [(-77.0074, 38.8978)]) == (penn, [])
    with pytest.raises(mcp.ToolError, match="no place found"):
        mcp.pick_place("Nowhere", [], [])


class _Places:
    """A site whose place search knows two Moore Roads and records where it searched."""

    base = "http://stand-in"

    def __init__(self):
        self.near = []
        self.routes = []

    def geocode(self, query, near=None):
        self.near.append(near)
        return [CENTREVILLE, BOYDS]

    def route(self, body):
        self.routes.append(body)
        line = [list(p) for p in body["points"]]
        return {"geometry": {"coordinates": line}, "distance_m": 1000.0 * len(self.routes)}

    def share(self, body):
        raise mcp.ToolError("not kept")


def test_plan_route_searches_a_name_near_the_points_given_as_coordinates() -> None:
    places = _Places()
    server = mcp.Server(lambda: places, mcp.load_stations(), out_dir=Path("."))
    out = server.call(
        "plan_route",
        {"points": [list(LEWIS_ORCHARDS), "Moore Road", "Shady Grove"], "via_points": [1]},
    )
    # Searched around the point before it; Shady Grove is a station, never searched.
    assert places.near == [LEWIS_ORCHARDS]
    taken = out["points_taken_as"]
    moore = next(t for t in taken if t["asked"] == "Moore Road")
    assert moore["taken_as"] == "Moore Road, Boyds, MD"
    assert moore["also_matches"][0]["label"] == "Moore Road, Centreville, VA"
    assert places.routes[0]["points"][1] == [-77.3703, 39.1785]


def test_a_via_reached_by_an_out_and_back_is_moved_and_planned_again(monkeypatch) -> None:
    places = _Places()
    server = mcp.Server(lambda: places, [], out_dir=Path("."))
    moved = {"done": False}

    def once(plan):
        if moved["done"]:
            return None
        moved["done"] = True
        return [plan.points[0], (-77.3, 39.1), plan.points[-1]], [1], 1

    monkeypatch.setattr(mcp, "without_spurs", once)
    out = server.call(
        "plan_route", {"points": [[-77.4, 39.1], [-77.3, 39.2], [-77.2, 39.1]], "via_points": [1]}
    )
    # The second plan is longer in this stand-in, so the first is kept and nothing is said.
    assert len(places.routes) == 2
    assert not any("out-and-back" in note for note in out.get("notes", []))
    places.routes.clear()
    moved["done"] = False
    places.route = lambda body: {
        "geometry": {"coordinates": [list(p) for p in body["points"]]},
        "distance_m": 2000.0 if body["points"][1] == [-77.3, 39.2] else 1500.0,
    }
    out = server.call(
        "plan_route", {"points": [[-77.4, 39.1], [-77.3, 39.2], [-77.2, 39.1]], "via_points": [1]}
    )
    assert out["points"][1] == [-77.3, 39.1]
    assert any("out-and-back" in note for note in out["notes"])
    moved["done"] = False
    out = server.call(
        "plan_route",
        {
            "points": [[-77.4, 39.1], [-77.3, 39.2], [-77.2, 39.1]],
            "via_points": [1],
            "trim_spurs": False,
        },
    )
    assert out["points"][1] == [-77.3, 39.2]


def test_a_draft_planned_without_trimming_is_revised_without_it(monkeypatch) -> None:
    places = _Places()
    places.route = lambda body: {
        "geometry": {"coordinates": [list(p) for p in body["points"]]},
        "distance_m": 2000.0 if body["points"][1] == [-77.3, 39.2] else 1500.0,
    }
    server = mcp.Server(lambda: places, [], out_dir=Path("."))
    monkeypatch.setattr(
        mcp,
        "without_spurs",
        lambda plan: ([plan.points[0], (-77.3, 39.1), plan.points[-1]], [1], 1),
    )
    first = server.call(
        "plan_route",
        {
            "points": [[-77.4, 39.1], [-77.3, 39.2], [-77.2, 39.1]],
            "via_points": [1],
            "trim_spurs": False,
        },
    )
    revised = server.call("revise_route", {"draft_id": first["draft_id"], "stress": 90})
    assert revised["points"][1] == [-77.3, 39.2]
    trimmed = server.call("revise_route", {"draft_id": first["draft_id"], "trim_spurs": True})
    assert trimmed["points"][1] == [-77.3, 39.1]
    assert any("point 1 from [-77.3, 39.2] to [-77.3, 39.1]" in n for n in trimmed["notes"])


def test_when_every_point_is_a_name_the_first_is_searched_again_near_the_others() -> None:
    places = _Places()
    server = mcp.Server(lambda: places, [], out_dir=Path("."))
    lewis = {"name": "Lewis Orchards", "label": "Lewis Orchards, Dickerson, MD"}
    lewis.update(lon=LEWIS_ORCHARDS[0], lat=LEWIS_ORCHARDS[1])
    places.geocode = lambda query, near=None: (
        [CENTREVILLE, BOYDS] if query == "Moore Road" else [lewis]
    )
    out = server.call("plan_route", {"points": ["Moore Road", "Lewis Orchards"]})
    moore = next(t for t in out["points_taken_as"] if t["asked"] == "Moore Road")
    assert moore["taken_as"] == "Moore Road, Boyds, MD"
    assert moore["why"] == "the match nearest the route's other points"
    assert len(out["points_taken_as"]) == 2
