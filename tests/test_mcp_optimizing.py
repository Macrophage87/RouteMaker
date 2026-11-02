"""What an assistant needs to optimize a route (mcp/routemaker_mcp.py; the owner, 2026-11-02:
"We'd want to make sure that an llm would be able to revise a call and would have access to
routing data for optimization", for long trips and rides done often, such as a commute): the
rider's pace, roads to avoid, whether a revision helped, alternatives, the route stretch by
stretch, its legs, light and weather at the ride's time, and the rider's own saved routes."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, date, datetime
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
# Along a parallel through DC: a degree of longitude is about 53.9 mi here.
LON_MI = 1 / 53.9
START = (-77.05, 38.90)


def east(miles: float) -> list[float]:
    return [round(START[0] + miles * LON_MI, 6), START[1]]


def stretch(street, a, b, tier, facility=None, surface=None, oneway=None):
    return {
        "kind": "stretch",
        "street": street,
        "from_mi": a,
        "to_mi": b,
        "from_m": round(a * MI),
        "to_m": round(b * MI),
        "tier": tier,
        "facility": facility,
        "surface": surface,
        "oneway": oneway,
    }


ENTRIES = [
    stretch("Rock Creek Trail", 0.0, 2.0, 1, "path"),
    stretch("Rock Creek Trail", 2.0, 2.5, 1, "path", "unpaved"),
    stretch("Connecticut Avenue", 2.5, 3.0, 4),
    stretch("Connecticut Avenue", 3.0, 3.1, 4),  # the same again: one segment
    stretch("Porter Street", 3.1, 4.0, 2, "lane", oneway=True),
]


def answer_for(body: dict, entries=ENTRIES, **extra) -> dict:
    """A planner's answer for the body: a straight line east, as long as the entries, the
    points reached at their place on it."""
    miles = entries[-1]["to_mi"]
    points = body["points"]
    steps = 40
    line = [east(miles * i / steps) for i in range(steps + 1)]
    # Each point is reached where the line passes it.
    ends = [round((p[0] - START[0]) / LON_MI / miles * steps) for p in points[1:]]
    stress = {"1": 2.5 * MI, "2": 0.9 * MI, "3": 0.0, "4": 0.6 * MI, "5": 0.0}
    answer = {
        "geometry": {"type": "LineString", "coordinates": line},
        "leg_ends": ends,
        "distance_m": miles * MI,
        "duration_s": 24 * 60,
        "climb_m": 30.0,
        "descent_m": 10.0,
        "junction_delay_s": 90.0,
        "time_marks": [[0.0, 0.0], [0.5, 600.0], [1.0, 1440.0]],
        "stress_m": stress,
        "facility_m": {"path": 2.5 * MI, "lane": 0.9 * MI, "none": 0.6 * MI},
        "stress_spans": [{"from_m": 0, "to_m": round(miles * MI)}],
        "description": entries,
        "intersections": [
            {
                "m": round(2.55 * MI),
                "lon": -77.0,
                "lat": 38.9,
                "severity": "red",
                "reason": "6 lanes",
            },
            {
                "m": round(3.6 * MI),
                "lon": -77.0,
                "lat": 38.9,
                "severity": "orange",
                "reason": "35 mph",
            },
        ],
        # Flat to mile 3, then 2% up to the end.
        "profile": {
            "interval_m": 30,
            "m": [0, round(3.0 * MI), round(4.0 * MI)],
            "elevation_m": [10.0, 10.0, 10.0 + 0.02 * MI],
            "grade_pct": [0.0, 0.0, 2.0],
            "climbs": [],
        },
        "steep_grades": [
            {
                "from_m": round(3.5 * MI),
                "to_m": round(3.6 * MI),
                "direction": "up",
                "level": "steep",
                "grade_pct": 9,
                "text": "x",
            }
        ],
        "road_hazards": [
            {
                "from_m": round(3.2 * MI),
                "to_m": round(3.3 * MI),
                "kinds": ["rails"],
                "road": "Porter Street",
                "text": "x",
            }
        ],
        "dials": {"stress": body.get("stress", 70), "hills": 0},
        "attribution": [],
    }
    answer.update(extra)
    return answer


class FakeApi:
    """The site, answering in this process: plans, links and the rider's own My routes."""

    base = "https://routes.example"

    def __init__(self):
        self.routes: list[dict] = []
        self.weather: list[list] = []
        self.saved: dict[int, dict] = {}
        self.candidates: list[dict] = []

    def route(self, body: dict) -> dict:
        self.routes.append(body)
        out = answer_for(body)
        if body.get("candidates"):
            out["candidates"] = self.candidates
        return out

    def share(self, body: dict) -> str:
        return body["id"]

    def geocode(self, query, near=None):
        return [{"name": query, "label": query, "lon": START[0], "lat": START[1]}]

    def closures_map(self, box, permits):
        return []

    def weather_check(self, points):
        self.weather.append(points)
        return {
            "alerts": [
                {
                    "id": "a",
                    "event": "Wind Advisory",
                    "severity": "Moderate",
                    "url": "https://forecast.weather.gov/x",
                }
            ],
            "rain": {
                "index": 1,
                "offset_s": 600,
                "starts_in_s": 900,
                "inches": 0.02,
                "heavy": False,
            },
            "unchecked": [],
        }

    def saved_routes(self):
        return [
            {k: v for k, v in r.items() if k not in ("inputs", "answer")}
            for r in self.saved.values()
        ]

    def saved_route(self, route_id):
        return self.saved[route_id]


@pytest.fixture
def api():
    return FakeApi()


@pytest.fixture
def tools(api):
    return mcp.Server(lambda: api, stations=[], out_dir=None)


def plan(tools, **extra):
    return tools.call("plan_route", {"points": [east(0), east(4)], "trim_spurs": False, **extra})


# --- Revising: pace, roads to avoid, whether it helped ----------------------------------------


def test_the_rider_s_pace_times_the_route_and_can_be_set_back(tools, api) -> None:
    first = plan(tools, pace_mph=12)
    assert api.routes[-1]["cycling_speed_kmh"] == pytest.approx(19.3)
    tools.call("revise_route", {"draft_id": first["draft_id"], "stress": 80})
    assert api.routes[-1]["cycling_speed_kmh"] == pytest.approx(19.3)  # kept as revised
    tools.call("revise_route", {"draft_id": first["draft_id"], "clear_settings": ["pace_mph"]})
    assert "cycling_speed_kmh" not in api.routes[-1]
    with pytest.raises(mcp.ToolError, match="pace_mph is 5 to 31"):
        plan(tools, pace_mph=60)


def test_a_road_the_draft_rides_is_avoided_by_name_and_stays_avoided(tools, api) -> None:
    first = plan(tools)
    out = tools.call(
        "revise_route", {"draft_id": first["draft_id"], "avoid": [{"road": "connecticut avenue"}]}
    )
    lines = api.routes[-1]["blocked_lines"]
    assert len(lines) == 1
    # Miles 2.5 to 3.1, cut back at each end so the junctions joining it stay open.
    assert lines[0][0][0] == pytest.approx(east(2.52)[0], abs=1e-4)
    assert lines[0][-1][0] == pytest.approx(east(3.08)[0], abs=1e-4)
    assert len(lines[0]) <= mcp.AVOID_LINE_POINTS
    assert any(
        "Connecticut" not in n and "connecticut avenue miles 2.5 to 3.1" in n for n in out["notes"]
    )
    # Revised again, the road is still left out; forgotten only when asked.
    again = tools.call("revise_route", {"draft_id": out["draft_id"], "stress": 90})
    assert api.routes[-1]["blocked_lines"] == lines
    tools.call("revise_route", {"draft_id": again["draft_id"], "clear_settings": ["avoid"]})
    assert "blocked_lines" not in api.routes[-1]


def test_a_mile_range_or_a_line_is_avoided_and_a_road_not_ridden_is_refused(tools, api) -> None:
    first = plan(tools)
    tools.call(
        "revise_route",
        {"draft_id": first["draft_id"], "avoid": [{"from_mi": 1.0, "to_mi": 2.0}]},
    )
    assert len(api.routes[-1]["blocked_lines"]) == 1
    with pytest.raises(mcp.ToolError, match="does not ride 'Elm Street'"):
        tools.call(
            "revise_route", {"draft_id": first["draft_id"], "avoid": [{"road": "Elm Street"}]}
        )
    # A new plan has no draft to read roads from: lines only.
    with pytest.raises(mcp.ToolError, match="plan first"):
        plan(tools, avoid=[{"road": "Connecticut Avenue"}])
    plan(tools, avoid=[{"line": [east(2.6), east(3.0)]}])
    assert api.routes[-1]["blocked_lines"] == [[east(2.6), east(3.0)]]


def test_at_most_ten_roads_are_avoided_the_latest_kept(tools, api) -> None:
    draft = plan(tools)
    for k in range(12):
        draft = tools.call(
            "revise_route",
            {
                "draft_id": draft["draft_id"],
                "avoid": [{"from_mi": 0.1 + 0.3 * k, "to_mi": 0.3 + 0.3 * k}],
            },
        )
    assert len(api.routes[-1]["blocked_lines"]) == mcp.MAX_AVOID
    assert any("earliest were let go" in n for n in draft["notes"])


def test_a_revision_says_each_figure_before_and_after(tools, api) -> None:
    first = plan(tools)
    out = tools.call("revise_route", {"draft_id": first["draft_id"], "stress": 90})
    change = out["changed_from_previous"]
    assert set(change) >= {
        "miles",
        "minutes",
        "climb_ft",
        "miles_lts_3_up",
        "unpaved_mi",
        "very_high_junctions",
        "junction_wait_minutes",
    }
    assert change["miles_lts_4_up"] == {"before": 0.6, "after": 0.6, "change": 0.0}


def test_a_line_the_rider_has_is_followed_until_points_reshape_it(tools, api) -> None:
    polyline = "_p~iF~ps|U_ulLnnqC_mqNvxq`@"  # Google's example line, precision 5 read as 6
    line = mcp.decode_polyline(polyline)
    out = tools.call("plan_route", {"follow": {"polyline": polyline, "exact": True}})
    sent = api.routes[-1]
    assert sent["follow"] == polyline and sent["follow_exact"] is True
    assert sent["points"] == [line[0], line[-1]]
    with pytest.raises(mcp.ToolError, match="leave points"):
        tools.call("plan_route", {"follow": {"polyline": polyline}, "points": [east(0), east(1)]})
    moved = tools.call(
        "revise_route",
        {"draft_id": out["draft_id"], "add_points": [{"point": east(2), "after": 0}]},
    )
    assert "follow" not in api.routes[-1]
    assert any("no longer along the followed line" in n for n in moved["notes"])


# --- Routing data ---------------------------------------------------------------------------


def test_alternatives_come_back_as_drafts_of_their_own(tools, api) -> None:
    calm = answer_for({"points": [east(0), east(4)], "stress": 95})
    api.candidates = [{**calm, "rank": 2, "extra_distance_m": 0.4 * MI, "extra_duration_s": 180}]
    out = plan(tools, alternatives=True)
    assert api.routes[0]["candidates"] is True
    alt = out["alternatives"]["routes"][0]
    assert alt["stress"] == 95 and alt["extra_miles"] == 0.4 and alt["extra_minutes"] == 3.0
    assert alt["figures"]["miles"] == 4.0 and alt["main_roads"][0] == "Rock Creek Trail"
    # Its own draft, read and revised as any other, at its own stress.
    assert tools.call("route_segments", {"draft_id": alt["draft_id"]})["segments"]
    tools.call("revise_route", {"draft_id": alt["draft_id"], "hills": -50})
    assert api.routes[-1]["stress"] == 95 and api.routes[-1]["candidates"] is False


def test_the_summary_and_road_list_say_unpaved_miles_and_junction_waits(tools) -> None:
    out = plan(tools)
    assert out["summary"]["unpaved"].startswith("0.5 mi")
    assert out["summary"]["junction_waits"] == "2 min"
    trail = next(r for r in out["roads"] if r["road"] == "Rock Creek Trail")
    assert trail["unpaved_mi"] == 0.5
    assert out["steep_grades"][0]["grade_pct"] == 9
    assert out["road_hazards"][0]["kinds"] == ["rails"]


def test_the_route_is_read_stretch_by_stretch(tools) -> None:
    draft = plan(tools)
    out = tools.call("route_segments", {"draft_id": draft["draft_id"]})
    roads = [(s["road"], s["from_mi"], s["to_mi"]) for s in out["segments"]]
    assert roads == [
        ("Rock Creek Trail", 0.0, 2.0),
        ("Rock Creek Trail", 2.0, 2.5),
        ("Connecticut Avenue", 2.5, 3.1),
        ("Porter Street", 3.1, 4.0),
    ]
    trail, unpaved, avenue, porter = out["segments"]
    assert unpaved["surface"] == "unpaved" and "surface" not in trail
    assert avenue["lts"] == 4 and avenue["facility"] == "street"
    assert porter["facility"] == "lane" and porter["one_way"] is True
    assert porter["grade_pct"] == pytest.approx(2.0, abs=0.1)
    assert porter["climb_ft"] == pytest.approx(0.02 * 0.9 * MI * mcp.FEET_PER_METRE, abs=2)
    # The site's own clock: 10 min to mile 2, 14 more to mile 4.
    assert trail["minutes"] == pytest.approx(10.0, abs=0.1)
    assert [j["level"] for j in out["junctions"]] == ["very high", "higher"]
    assert out["junctions"][0]["road"] == "Connecticut Avenue"
    assert "next_from_mi" not in out


def test_a_long_route_is_read_in_pages(tools) -> None:
    draft = plan(tools)
    first = tools.call("route_segments", {"draft_id": draft["draft_id"], "max_rows": 5})
    assert len(first["segments"]) == 4 and "next_from_mi" not in first
    part = tools.call(
        "route_segments", {"draft_id": draft["draft_id"], "from_mi": 2.6, "to_mi": 3.4}
    )
    assert [s["road"] for s in part["segments"]] == ["Connecticut Avenue", "Porter Street"]
    assert part["segments"][0]["from_mi"] == 2.6 and part["segments"][-1]["to_mi"] == 3.4
    assert part["road_hazards"] and "steep_grades" not in part
    with pytest.raises(mcp.ToolError, match="to_mi is past from_mi"):
        tools.call("route_segments", {"draft_id": draft["draft_id"], "from_mi": 2, "to_mi": 1})


def test_rows_are_cut_into_pages_with_where_the_next_starts() -> None:
    entries = [stretch(f"Street {k}", k * 0.1, (k + 1) * 0.1, 2) for k in range(30)]
    p = mcp.Plan(
        [tuple(east(0)), tuple(east(3))],
        [],
        "default",
        answer_for({"points": [east(0), east(3)]}, entries),
        None,
        {},
    )
    out = mcp.route_segments(p, 0.0, None, 10)
    assert len(out["segments"]) == 10 and out["next_from_mi"] == pytest.approx(1.0)
    assert out["to_mi"] == pytest.approx(1.0)


def test_legs_run_between_stops_not_via_points(tools) -> None:
    out = tools.call(
        "plan_route",
        {"points": [east(0), east(1), east(2), east(4)], "via_points": [1], "trim_spurs": False},
    )
    legs = out["legs"]
    assert [(leg["from_point"], leg["to_point"]) for leg in legs] == [(0, 2), (2, 3)]
    assert sum(leg["miles"] for leg in legs) == pytest.approx(4.0, abs=0.1)
    assert legs[1]["miles_lts_3_up"] == pytest.approx(0.6, abs=0.05)
    # No stops between the ends: no legs.
    assert "legs" not in plan(tools)


# --- Light and weather ----------------------------------------------------------------------


def test_dawn_and_dusk_in_dc_are_civil_twilight() -> None:
    dawn, dusk = mcp.twilight(date(2026, 11, 3), -77.04, 38.9)
    # Sunrise about 6:37 and sunset about 5:03 EST that day; civil twilight some 28 minutes
    # either side, to the equation's minute or two.
    assert mcp.eastern(dawn)[-5:] in {f"06:{m:02d}" for m in range(4, 15)}
    assert mcp.eastern(dusk)[-5:] in {f"17:{m:02d}" for m in range(26, 37)}


def test_a_time_with_no_zone_is_new_york_s() -> None:
    assert mcp.parse_depart("2026-11-03T05:30") == datetime(2026, 11, 3, 10, 30, tzinfo=UTC)
    assert mcp.parse_depart("2026-07-03T05:30") == datetime(2026, 7, 3, 9, 30, tzinfo=UTC)
    assert mcp.parse_depart("2026-11-03T05:30Z") == datetime(2026, 11, 3, 5, 30, tzinfo=UTC)
    with pytest.raises(mcp.ToolError, match="ISO 8601"):
        mcp.parse_depart("tomorrow")


def test_new_york_s_clock_without_tz_data_follows_the_us_rule(monkeypatch) -> None:
    import zoneinfo

    def missing(_name):
        raise zoneinfo.ZoneInfoNotFoundError("no data")

    monkeypatch.setattr(zoneinfo, "ZoneInfo", missing)
    assert mcp.eastern(datetime(2026, 11, 3, 10, 30, tzinfo=UTC)) == "2026-11-03 05:30"
    assert mcp.eastern(datetime(2026, 7, 3, 10, 30, tzinfo=UTC)) == "2026-07-03 06:30"


def test_a_dark_commute_says_so_and_checks_the_weather_along_it(tools, api) -> None:
    draft = plan(tools)
    soon = datetime.now(UTC).replace(microsecond=0)
    # An hour before dawn today, if that is still ahead; the check works either way.
    out = tools.call(
        "ride_conditions", {"draft_id": draft["draft_id"], "depart_at": soon.isoformat()}
    )
    assert out["start"]["light"] in ("light", "dark") and out["finish"]["dawn"]
    points = api.weather[-1]
    assert 2 <= len(points) <= mcp.WEATHER_POINTS
    assert [p[2] for p in points] == sorted(p[2] for p in points)
    assert points[-1][2] == pytest.approx(24 * 60, abs=5)
    weather = out["weather"]
    assert weather["checked"] and weather["alerts"][0]["event"] == "Wind Advisory"
    assert weather["first_rain"]["at_mi"] == pytest.approx(4.0 / (len(points) - 1), abs=0.1)


def test_a_ride_in_the_dark_asks_for_lights(tools, api) -> None:
    draft = plan(tools)
    out = tools.call(
        "ride_conditions", {"draft_id": draft["draft_id"], "depart_at": "2030-01-15T05:00"}
    )
    assert out["start"]["light"] == "dark" and "lights" in out["lights_needed"]
    # Past the forecasts: no weather asked.
    assert out["weather"]["checked"] is False and not api.weather


# --- My routes ------------------------------------------------------------------------------


def saved(route_id: int, name: str, kept_answer=True) -> dict:
    ends = f"{east(0)[0]:.5f},{START[1]:.5f};{east(4)[0]:.5f},{START[1]:.5f}"
    fragment = f"#p={ends}&preset=default&v=2&stress=80&hills=0"
    return {
        "id": route_id,
        "name": name,
        "source": "plan",
        "distance_m": 4 * MI,
        "preset": "default",
        "updated_at": "2026-11-01T10:00:00+00:00",
        "closure_alerts": [],
        "inputs": {"hash": fragment},
        "answer": answer_for({"points": [east(0), east(4)]}) if kept_answer else None,
    }


def test_my_routes_lists_and_opens_one_by_name_without_planning_it(tools, api) -> None:
    api.saved = {7: saved(7, "Morning commute"), 8: saved(8, "Saturday loop")}
    listed = tools.call("my_routes", {})
    assert [r["name"] for r in listed["routes"]] == ["Morning commute", "Saturday loop"]
    assert listed["routes"][0]["miles"] == 4.0
    out = tools.call("my_routes", {"name": "commute"})
    assert out["opened_from"]["route_id"] == 7 and out["draft_id"]
    assert not api.routes  # its exact line, as kept
    tools.call("revise_route", {"draft_id": out["draft_id"], "stress": 90})
    assert api.routes[-1]["stress"] == 90


def test_my_routes_asks_which_when_a_name_matches_several(tools, api) -> None:
    api.saved = {1: saved(1, "Commute in"), 2: saved(2, "Commute home")}
    out = tools.call("my_routes", {"name": "commute"})
    assert "draft_id" not in out and len(out["routes"]) == 2 and "ask the rider" in out["note"]
    assert tools.call("my_routes", {"route_id": 2})["opened_from"]["name"] == "Commute home"
    with pytest.raises(mcp.ToolError, match="no saved route by that name"):
        tools.call("my_routes", {"name": "Baltimore"})


def test_my_routes_is_refused_where_the_rider_never_allowed_it(api) -> None:
    api.saved = {1: saved(1, "Commute")}
    server = mcp.Server(lambda: api, stations=[], routes_read=False)
    with pytest.raises(mcp.ToolError, match="connects again"):
        server.call("my_routes", {})


def test_on_the_rider_s_computer_my_routes_points_to_the_site_s_connector(monkeypatch) -> None:
    site = mcp.Api("https://routes.example")
    monkeypatch.setattr(site, "_request", lambda *a, **k: (401, {"error": "sign in"}, {}))
    with pytest.raises(mcp.ToolError, match="RouteMaker's own connector"):
        site.saved_routes()


def test_the_new_tools_only_read() -> None:
    names = {"route_segments", "ride_conditions", "my_routes"}
    for tool in mcp.TOOLS:
        if tool["name"] in names:
            assert tool["annotations"]["readOnlyHint"] is True
