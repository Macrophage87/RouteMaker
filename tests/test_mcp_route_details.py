"""What a plan's answer says the route rides (mcp/routemaker_mcp.py `route_details`; the owner,
2026-10-25: "The goal would be for a new user to be able to make routes like this."): its roads
with their stress and scenic designations, its busy stretches and junctions, its small
detours, and place names searched near the route's other points."""

from __future__ import annotations

import importlib.util
import itertools
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


def test_scenic_roads_near_asks_the_site_within_its_reach() -> None:
    places = _Places()
    asked = []

    def scenic_roads(near, miles, designation=""):
        asked.append((near, miles, designation))
        return [
            {"road": "Moore Road", "designation": "Exceptional Rustic Road (Montgomery County)"}
        ]

    places.scenic_roads = scenic_roads
    server = mcp.Server(lambda: places, [], out_dir=Path("."))
    out = server.call(
        "scenic_roads_near",
        {"near": list(LEWIS_ORCHARDS), "within_miles": 40, "designation": "rustic"},
    )
    assert asked == [(LEWIS_ORCHARDS, 15.0, "rustic")]
    assert [r["road"] for r in out["roads"]] == ["Moore Road"]


# --- Interval training ------------------------------------------------------------------------


def _interval_answer(miles, events=(), grades=None, entries=None, loop=False):
    """A straight east route `miles` long, with junction events and a profile every 0.1 mi."""
    samples = [round(k * 0.1 * MI) for k in range(int(miles * 10) + 1)]
    grades = grades or (lambda mile: 0.0)
    heights, height = [], 100.0
    for k, m in enumerate(samples):
        if k:
            height += grades(m / MI) / 100 * 0.1 * MI
        heights.append(height)
    answer = answer_of(entries or [stretch("Beach Drive", 0.0, miles, 1)])
    answer["junctions_debug"] = [
        {"m": round(mile * MI), "control": control, "crossed_tier": tier}
        for mile, control, tier in events
    ]
    answer["profile"] = {
        "m": samples,
        "grade_pct": [grades(m / MI) for m in samples],
        "elevation_m": heights,
    }
    line = [at(0.0), at(miles / 3), at(miles / 6, miles / 3), at(0.0)]  # round a triangle
    answer["geometry"] = {"coordinates": line if loop else [at(0.0), at(miles / 2), at(miles)]}
    return answer


def test_efforts_go_where_nothing_breaks_them() -> None:
    # 6 mi: a stop sign at 1.0, a signal at 4.0. At 18 mph an effort is 1.5 mi.
    answer = _interval_answer(6.0, [(1.0, "stop", 2), (4.0, "signal", 3), (2.0, "cross_stop", 2)])
    ask = {"on_minutes": 5, "off_minutes": 3, "sets": 5}
    out = mcp.interval_check(answer, ask, mcp._roads_between(answer))
    assert out["breaks"] == {"stop sign": 1, "signal": 1}
    efforts = [(e["from_mi"], e["to_mi"]) for e in out["efforts"]]
    # The cross street's stop sign is theirs, not the rider's: the effort runs through it.
    # Started late enough, the first effort's rest ends just past the signal for a second.
    assert efforts[0][1] <= 3.95 and efforts[1][0] == pytest.approx(4.05, abs=0.01)
    assert out["sets_in_one_session"] == 2 and "lap" not in out["efforts"][0]
    assert out["efforts"][1]["rest_min"] <= 3 * mcp.REST_SLACK
    assert out["longest_clear"][0]["roads"] == ["Beach Drive"]


def test_a_loop_is_ridden_again_until_the_sets_fit() -> None:
    answer = _interval_answer(3.3, loop=True)  # Hains Point: one long clear loop
    out = mcp.interval_check(answer, {"on_minutes": 5, "off_minutes": 3, "sets": 5})
    assert out["sets_in_one_session"] == 5
    assert out["efforts"][-1]["lap"] >= 3
    # Ridden out and back, the turn at the start breaks an effort that would run through it.
    assert all(e["rest_min"] == pytest.approx(3.0, abs=0.1) for e in out["efforts"][1:])
    through = [e for e in out["efforts"] if e.get("through_start")]
    assert through and all(e["to_mi"] < e["from_mi"] for e in through)
    assert all(0 <= e["from_mi"] < 3.3 and 0 < e["to_mi"] <= 3.3 for e in out["efforts"])
    # The same with a point every 10 m, as a real line has: still a loop.
    dense = []
    for p, q in itertools.pairwise(answer["geometry"]["coordinates"]):
        dense += [
            [p[0] + (q[0] - p[0]) * k / 180, p[1] + (q[1] - p[1]) * k / 180] for k in range(180)
        ]
    answer["geometry"]["coordinates"] = dense + [answer["geometry"]["coordinates"][-1]]
    assert mcp.interval_check(answer, {"sets": 5})["sets_in_one_session"] == 5
    assert (
        mcp.interval_check({"distance_m": 5000, "loop": True}, {"sets": 3})["sets_in_one_session"]
        == 3
    )


def test_an_out_and_back_s_turn_breaks_an_effort_and_each_lap_starts_at_its_start() -> None:
    answer = _interval_answer(2.15)
    answer["geometry"]["coordinates"] = [at(0.0), at(1.075), at(0.0)]
    out = mcp.interval_check(answer, {"sets": 5})
    assert out["sets_in_one_session"] == 5
    for e in out["efforts"]:
        assert 0 <= e["from_mi"] < e["to_mi"] <= 2.15 and "through_start" not in e


def test_descents_sharp_turns_and_lts_4_break_an_effort() -> None:
    entries = [
        stretch("Klingle Valley Trail", 0.0, 1.0, 1, "path"),
        {**stretch("Porter Street", 1.0, 1.5, 4), "turn": {"movement": "left"}},
        stretch("Quiet Street", 1.5, 3.0, 2),
    ]
    answer = _interval_answer(3.0, grades=lambda mile: -4.0 if mile > 2.0 else 0.0, entries=entries)
    out = mcp.interval_check(answer, {"on_minutes": 5})
    assert {"LTS 4 road", "sharp turn", "descent"} <= set(out["breaks"])
    assert out["sets_in_one_session"] == 0


def test_a_climb_is_a_repeat_ridden_up_for_the_effort_and_down_to_recover() -> None:
    # A 5% climb is slower: 5 minutes covers less than a mile, so a short hill holds it.
    answer = _interval_answer(1.2, grades=lambda mile: 5.0)
    out = mcp.interval_check(answer, {"on_minutes": 5, "off_minutes": 3, "sets": 5})
    repeat = out["repeats"][0]
    assert repeat["to_mi"] - repeat["from_mi"] < 1.0
    assert repeat["avg_grade_pct"] == pytest.approx(5.0, abs=0.5) and repeat["climb_ft"] > 200
    flat = mcp.interval_check(_interval_answer(1.2), {"on_minutes": 5})
    assert flat["repeats"] == []


def test_plan_route_reads_every_junction_for_intervals_and_a_revise_keeps_them() -> None:
    places = _Places()
    server = mcp.Server(lambda: places, [], out_dir=Path("."))
    out = server.call(
        "plan_route",
        {"points": [[-77.4, 39.1], [-77.3, 39.1]], "intervals": {"on_minutes": 5, "sets": 5}},
    )
    assert places.routes[-1]["debug_junctions"] is True
    assert out["intervals"]["asked"].startswith("5 x 5 min on")
    revised = server.call("revise_route", {"draft_id": out["draft_id"], "stress": 90})
    assert places.routes[-1]["debug_junctions"] is True and "intervals" in revised
    plain = server.call("revise_route", {"draft_id": out["draft_id"], "intervals": None})
    assert "debug_junctions" not in places.routes[-1] and "intervals" not in plain
    with pytest.raises(mcp.ToolError, match="intervals.sets"):
        server.call(
            "plan_route", {"points": [[-77.4, 39.1], [-77.3, 39.1]], "intervals": {"sets": 99}}
        )


def test_sets_far_apart_are_not_one_session() -> None:
    # Clear 2 mi stretches 8 mi apart, signals every half mile between: an effort fits in
    # each, but the rest between them would be half an hour.
    events = [(k / 2, "signal", 3) for k in range(60) if (k / 2) % 8 > 2.0]
    out = mcp.interval_check(_interval_answer(30.0, events), {"sets": 5})
    assert out["sets_in_one_session"] == 1
    assert out["longest_clear"][0]["effort_minutes"] > 5


def test_a_repeat_is_the_climbiest_window_and_needs_a_real_grade() -> None:
    # Flat for a mile, then 6% for a mile: the repeat starts on the climb, not the flat.
    answer = _interval_answer(2.0, grades=lambda mile: 6.0 if mile > 1.0 else 0.0)
    repeat = mcp.interval_check(answer, {"on_minutes": 5})["repeats"][0]
    assert repeat["from_mi"] >= 0.9 and repeat["avg_grade_pct"] > 4.5
    gentle = _interval_answer(2.0, grades=lambda mile: 1.0)
    assert mcp.interval_check(gentle, {"on_minutes": 5})["repeats"] == []


def test_a_trail_going_on_under_its_name_is_no_turn_and_a_bend_is_none() -> None:
    entries = [
        stretch("Metropolitan Branch Trail", 0.0, 1.0, 1, "path"),
        {
            **stretch("Metropolitan Branch Trail", 1.0, 2.0, 1, "path"),
            "turn": {"movement": "left"},
        },
        {**stretch("Fort Totten Trail", 2.0, 3.0, 1, "path"), "turn": {"shape": {"out": 30}}},
    ]
    out = mcp.interval_check(_interval_answer(3.0, entries=entries), {"on_minutes": 5})
    assert "sharp turn" not in out["breaks"]


def test_a_descent_is_read_from_the_heights_not_a_thinned_sample_grade() -> None:
    answer = _interval_answer(3.0)
    # A thinned profile keeps a window's steepest grade: one -8% sample on level ground.
    answer["profile"]["grade_pct"] = [-8.0] * len(answer["profile"]["m"])
    assert "descent" not in mcp.interval_check(answer, {"on_minutes": 5})["breaks"]


def test_intervals_asked_takes_defaults_and_refuses_words() -> None:
    assert mcp._intervals_asked({}) is not None
    assert mcp._intervals_asked(None) is None
    with pytest.raises(mcp.ToolError, match="intervals.sets"):
        mcp._intervals_asked({"sets": "five"})


def test_a_sharp_angle_on_one_trail_is_a_turn_and_starts_line_up_with_the_rests() -> None:
    entries = [
        stretch("Paint Branch Trail", 0.0, 1.5, 1, "path"),
        {
            **stretch("Paint Branch Trail", 1.5, 3.0, 1, "path"),
            "turn": {"movement": "left", "shape": {"out": -96}},
        },
    ]
    out = mcp.interval_check(_interval_answer(3.0, entries=entries), {"on_minutes": 5})
    assert out["breaks"] == {"sharp turn": 1}
    # Starting late in the first stretch lines the second effort up after a 3-minute rest.
    signals = [(m, "signal", 3) for m in (3.1, 3.3, 3.5, 3.7)]
    two = mcp.interval_check(_interval_answer(6.0, signals), {"sets": 2})
    assert two["sets_in_one_session"] == 2


def test_rolling_ground_is_no_hill_repeat() -> None:
    answer = _interval_answer(3.0)
    answer["profile"]["elevation_m"] = [
        100.0 + 4.0 * (k % 2) for k in range(len(answer["profile"]["m"]))
    ]
    assert mcp.interval_check(answer, {"on_minutes": 5})["repeats"] == []


# --- Climbs near a point -----------------------------------------------------------------------


def _climb(name, miles, grade, **extra):
    return {
        "id": name[:4],
        "name": name,
        "category": "5",
        "miles": miles,
        "gain_ft": round(miles * grade / 100 * 5280),
        "grade_pct": grade,
        "foot": at(0.0),
        "summit": at(miles),
        "through": [at(miles / 2)],
        "surface": "road",
        "busy": False,
        "away_mi": 0.5,
        **extra,
    }


def test_climbs_near_lists_the_steep_ones_long_enough_and_checks_them() -> None:
    places = _Places()
    asked = []

    def climbs_near(near, miles, **filters):
        asked.append(filters)
        return [
            _climb("Gentle Road", 2.0, 2.0),
            _climb("Short Street", 0.2, 9.0),
            _climb("Steep Hill", 0.9, 7.0),
        ]

    places.climbs_near = climbs_near
    # Up Steep Hill: a stop sign 0.2 mi up leaves 0.65 mi clear, under 5 minutes at 7%.
    up = _interval_answer(0.9, [(0.2, "stop", 2)], grades=lambda mile: 7.0)
    places.route = lambda body: (places.routes.append(body), up)[1]
    server = mcp.Server(lambda: places, [], out_dir=Path("."))
    out = server.call("climbs_near", {"near": [-77.05, 38.94], "on_minutes": 5})
    # The site is asked for paved, quiet climbs long enough, steepest first, before its cut.
    assert asked[0]["paved_only"] and asked[0]["quiet_only"] and asked[0]["steepest"]
    assert asked[0]["on_minutes"] == 5 and asked[0]["pace_mph"] == 18
    # The short one cannot hold 5 minutes; steepest first.
    assert [c["name"] for c in out["climbs"]] == ["Steep Hill", "Gentle Road"]
    assert out["climbs"][0]["effort_minutes"] > 5 and out["checked"] == 2
    body = places.routes[0]
    assert body["points"][0] == at(0.0) and body["via_points"] == [1]
    assert body["debug_junctions"] is True and "stress" not in body
    steep = out["climbs"][0]["clear"]
    assert steep["checked"] and not steep["effort_fits"] and steep["breaks"] == {"stop sign": 1}
    assert steep["longest_clear_minutes"] < 5
    # Gentle Road's plan (0.9 mi) is not its 2 mi: off the climb, said so.
    assert out["climbs"][1]["clear"]["checked"] is False
    listed = server.call("climbs_near", {"near": [-77.05, 38.94], "include_busy": True})
    assert asked[-1]["quiet_only"] is False and listed["checked"] == 0
    with pytest.raises(mcp.ToolError, match="pace_mph"):
        server.call("climbs_near", {"near": [-77.05, 38.94], "pace_mph": -10})


def test_climb_minutes_slow_with_the_grade() -> None:
    assert mcp.climb_minutes(1.5, 0.0, 18) == pytest.approx(5.0)
    assert mcp.climb_minutes(0.75, 5.0, 18) == pytest.approx(4.0, abs=0.1)


# --- Checkpoint order ----------------------------------------------------------------------------


def test_the_best_order_is_the_shortest_round_the_checkpoints() -> None:
    import random

    rng = random.Random(7)
    points = [at(rng.uniform(0, 5), rng.uniform(0, 5)) for _ in range(9)]
    best = mcp.best_orders(points, tries=1)[0]
    middle = range(1, len(points) - 1)
    shortest = min(
        ([0, *p, len(points) - 1] for p in itertools.permutations(middle)),
        key=lambda order: mcp._round_mi(points, order),
    )
    assert mcp._round_mi(points, best) == pytest.approx(mcp._round_mi(points, shortest))
    orders = mcp.best_orders(points)
    assert len(orders) == 3 and len({tuple(o) for o in orders}) == 3
    assert all(o[0] == 0 and o[-1] == len(points) - 1 for o in orders)
    assert all(sorted(o) == list(range(len(points))) for o in orders)
    # Past the exact search: nearest neighbour and 2-opt, still every checkpoint once.
    many = [at(rng.uniform(0, 5), rng.uniform(0, 5)) for _ in range(20)]
    (order,) = mcp.best_orders(many, tries=1)
    assert sorted(order) == list(range(20)) and order[0] == 0 and order[-1] == 19


def test_plan_route_rides_the_checkpoints_in_the_quickest_order() -> None:
    places = _Places()
    # A row east: the start at 0, the finish at 4, checkpoints given 3, 1, 2.
    points = [at(0.0), at(3.0), at(1.0), at(2.0), at(4.0)]
    timed = []

    def route(body):
        places.routes.append(body)
        line = [list(p) for p in body["points"]]
        # The straight-line best (1, 2, 3) is slow (a river, say); the next is quicker.
        slow = line == [at(0.0), at(1.0), at(2.0), at(3.0), at(4.0)]
        timed.append(slow)
        return {
            "geometry": {"coordinates": line},
            "distance_m": 6000.0,
            "duration_s": 3000.0 if slow else 1500.0,
        }

    places.route = route
    server = mcp.Server(lambda: places, [], out_dir=Path("."))
    out = server.call("plan_route", {"points": points, "best_order": True, "trim_spurs": False})
    assert timed[0] is True and len(timed) == 3  # three orders tried, the quickest kept as is
    kept = places.routes[-1]["points"]
    assert kept[0] == at(0.0) and kept[-1] == at(4.0) and kept != places.routes[0]["points"]
    assert [row["point_given"] for row in out["checkpoint_order"]][0] == 0
    with pytest.raises(mcp.ToolError, match="via_points"):
        server.call("plan_route", {"points": points, "best_order": True, "via_points": [1]})
    with pytest.raises(mcp.ToolError, match="start again as the last point"):
        server.call("plan_route", {"points": points, "best_order": True, "loop": True})


def test_a_failed_later_try_keeps_the_orders_already_planned() -> None:
    places = _Places()
    points = [at(0.0), at(3.0), at(1.0), at(2.0), at(4.0)]
    calls = []

    def route(body):
        calls.append(body)
        if len(calls) == 2:
            raise mcp.ToolError("the site is busy")
        line = [list(p) for p in body["points"]]
        return {"geometry": {"coordinates": line}, "distance_m": 6000.0, "duration_s": 1500.0}

    places.route = route
    server = mcp.Server(lambda: places, [], out_dir=Path("."))
    out = server.call("plan_route", {"points": points, "best_order": True, "trim_spurs": False})
    assert len(calls) == 2 and out["draft_id"]
    assert any("a later try failed" in note for note in out.get("notes", []))


def test_no_more_orders_are_tried_than_time_allows(monkeypatch) -> None:
    places = _Places()
    points = [at(0.0), at(3.0), at(1.0), at(2.0), at(4.0)]
    clock = {"now": 0.0}
    monkeypatch.setattr(mcp.time, "monotonic", lambda: clock["now"])

    def route(body):
        clock["now"] += 30.0  # each plan takes 30 s
        places.routes.append(body)
        line = [list(p) for p in body["points"]]
        return {"geometry": {"coordinates": line}, "distance_m": 6000.0, "duration_s": 1500.0}

    places.route = route
    server = mcp.Server(lambda: places, [], out_dir=Path("."))
    call = mcp.Call(deadline=55.0)
    plan, ordered = server._best_order(call, points, [], "default", {}, None, [])
    assert len(places.routes) == 1 and "no time to try more" in ordered["note"]
    assert plan.answer["duration_s"] == 1500.0


# --- Closures --------------------------------------------------------------------------------
#
# The owner, 2026-10-25 (Lake Frank): "make sure that the MCP server has access to the closure
# list". A connector route ran along the closed Lakeside Trail to reach a via point only that
# trail goes past; the site's answer said so, the summary did not.

LAKE_FRANK = "https://montgomeryparks.org/lake-frank"


def closure(
    part, effect, from_mi=None, to_mi=None, title="Lakeside Trail: closed", line=None, pk=4
):
    return {
        "id": f"reviewer-{pk}-{part}",
        "source": "reviewer",
        "source_name": "Confirmed by a RouteMaker reviewer",
        "url": LAKE_FRANK,
        "kind": "closed",
        "title": title,
        "when_text": "Closed through Dec 20",
        "effect": effect,
        "effect_text": "On your route" if effect == "on_route" else "No effect on your route",
        "delay_s": None,
        "from_m": None if from_mi is None else round(from_mi * MI),
        "to_m": None if to_mi is None else round(to_mi * MI),
        "point": at(0.0),
        "line": line or [at(0.0), at(0.1)],
    }


def _closure_plan(rows, via_mi):
    line = [at(x / 10) for x in range(31)]
    answer = {
        "distance_m": 3.0 * MI,
        "geometry": {"coordinates": line},
        "leg_ends": [round(via_mi * 10), 30],
        "work_zones": {"closures": rows},
    }
    return mcp.Plan(
        [tuple(line[0]), tuple(at(via_mi, 0.1)), tuple(line[-1])], [1], "default", answer, None, {}
    )


def test_closures_on_the_route_are_said_one_row_each() -> None:
    rows = [
        closure(0, "on_route", 1.0, 1.4),
        closure(1, "on_route", 1.4, 1.8),
        closure(2, "none"),
        closure(0, "routed_round", title="Connector: closed", pk=3),
    ]
    out = mcp.route_details(_closure_plan(rows, via_mi=1.5))
    # The two ways of one closure are one row, from its first mile to its last.
    on, round_ = out["closures"]
    assert on["what"] == "Lakeside Trail: closed" and on["effect"] == "on_route"
    assert (on["from_mi"], on["to_mi"]) == (1.0, 1.8) and on["url"] == LAKE_FRANK
    assert round_["effect"] == "routed_round"
    # The via point is reached on the closed stretch: named, so it can be moved.
    assert "point 1 (Lakeside Trail: closed, Closed through Dec 20)" in out["closure_warning"]


def test_a_route_through_a_closure_with_no_point_on_it_still_warns() -> None:
    out = mcp.route_closures(_closure_plan([closure(0, "on_route", 2.0, 2.5)], via_mi=1.0))
    assert "no way round" in out["closure_warning"] and "point 1" not in out["closure_warning"]


def test_no_closures_said_when_none_touch_the_route() -> None:
    assert mcp.route_closures(_closure_plan([closure(0, "none")], via_mi=1.0)) == {}
    plan = _closure_plan([], via_mi=1.0)
    plan.answer.pop("work_zones")
    assert mcp.route_closures(plan) == {}


def test_a_park_notice_on_the_route_is_said_with_no_closure() -> None:
    # A deer-management closure at the ride's time (v0.12.3): a notice, never routed round.
    plan = _closure_plan([], via_mi=1.0)
    plan.answer["work_zones"]["notices"] = [
        {
            "id": "deer-rocr-deer-2026-12-01",
            "source": "nps_deer",
            "source_name": "NPS, Rock Creek Park deer management",
            "title": "Beach Dr, Bingham Dr and Sherrill Dr may close to bikes at night",
            "text": "Deer management: these car-free roads may be closed to bikes and walkers.",
            "url": "https://www.nps.gov/rocr/",
            "area": "rocr-deer",
            "area_name": "Rock Creek Park",
            "point": at(0.5),
            "category": "Deer management",
            "when_text": "today 6:45 pm to tomorrow 4 am",
        }
    ]
    out = mcp.route_closures(plan)
    [said] = out["check_before_you_go"]
    assert said["where"] == "Rock Creek Park" and said["when"] == "today 6:45 pm to tomorrow 4 am"
    assert said["url"] == "https://www.nps.gov/rocr/"
    assert out["closures"] == [] and "closure_warning" not in out


def test_closures_near_lists_each_closure_once_nearest_first() -> None:
    asked = []

    class Site:
        base = "http://stand-in"

        def closures_map(self, box, permits):
            asked.append((box, permits))
            return [
                closure(0, "none", line=[at(0.5), at(0.6)]),
                closure(1, "none", line=[at(0.6), at(0.8)]),
                closure(
                    0, "none", title="Connector: closed", line=[at(0.0, 0.2), at(0.0, 0.3)], pk=3
                ),
                closure(0, "none", title="Far away: closed", line=[at(5.0), at(5.1)], pk=5),
            ]

    server = mcp.Server(lambda: Site(), [], out_dir=Path("."))
    out = server.call("closures_near", {"near": at(0.0), "within_miles": 1})
    (west, south, east, north), permits = asked[0]
    assert west < ORIGIN[0] < east and south < ORIGIN[1] < north and permits is False
    assert [c["what"] for c in out["closures"]] == ["Connector: closed", "Lakeside Trail: closed"]
    lakeside = out["closures"][1]
    assert lakeside["away_mi"] == 0.5 and lakeside["miles"] == pytest.approx(0.3, abs=0.05)
    assert lakeside["url"] == LAKE_FRANK and "effect" not in lakeside
    server.call("closures_near", {"near": at(0.0), "include_permits": True})
    assert asked[-1][1] is True


def test_a_blocked_bike_lane_is_listed_but_not_warned_about() -> None:
    lane = {**closure(0, "on_route", 1.0, 1.2), "kind": "lane", "title": "Bike lane blocked"}
    out = mcp.route_closures(_closure_plan([lane], via_mi=1.1))
    assert out["closures"][0]["what"] == "Bike lane blocked" and "closure_warning" not in out


def test_closures_near_asks_for_a_view_the_site_takes() -> None:
    boxes = []

    class Site:
        base = "http://stand-in"

        def closures_map(self, box, permits):
            boxes.append(box)
            return []

    server = mcp.Server(lambda: Site(), [], out_dir=Path("."))
    for lat in (38.2, 39.72):
        server.call("closures_near", {"near": [-77.0, lat], "within_miles": 50})
    for west, south, east, north in boxes:
        assert east - west <= 0.4 and north - south <= 0.3
