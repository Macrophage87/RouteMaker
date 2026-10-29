"""Mass Ride routing by road capacity (`routemaker.mass_route`, `core.routing.choose_by_capacity`),
the answer's `mass_capacity` and the assistants' tool's reading of it.

Pure: no router, no database.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest

from core import routing
from routemaker import flow, mass_route

MILE = 1609.344
# The width of a road carrying `rpm` riders a minute on the level.
PER_M = flow.level_riders_per_min(1.0)


def width_for(rpm: float) -> float:
    return rpm / PER_M


def road(metres: float, rpm: float | None, note: str | None = None, name: str | None = None):
    return (metres, None if rpm is None else width_for(rpm), note, name)


# ---- The price ---------------------------------------------------------------------------------


def test_the_need_is_the_ride_size_over_a_five_minute_hold_as_the_chart_draws_it():
    assert mass_route.need_per_min(500) == 100
    assert mass_route.need_per_min(510) == 102
    assert mass_route.need_per_min(2000) == 400
    assert mass_route.fit_ride_size(None) == 500
    assert mass_route.fit_ride_size(50) == 100
    assert mass_route.fit_ride_size(9000) == 2000


def test_a_road_wide_enough_for_the_ride_costs_nothing():
    priced = mass_route.price([road(2000, 200)], 500)
    assert priced.total_s == 0
    assert priced.below_need_m == 0
    assert priced.narrowest_riders_per_min == pytest.approx(200)


def test_a_road_too_narrow_for_the_ride_costs_its_time_at_cruise_times_the_shortfall():
    priced = mass_route.price([road(1000, 50)], 500)  # need 100, carries 50: twice too narrow
    assert priced.narrow_s == pytest.approx(1000 / flow.CRUISE_PACE_MS * 1.0)
    assert priced.below_need_m == 1000
    # The same road is fine for 200 riders (need 40): "fine for 100 riders and a problem for
    # 1,500" (PLAN item 128).
    assert mass_route.price([road(1000, 50)], 200).narrow_s == 0
    # The shortfall is capped, and a stretch marked Avoid pays the cap.
    capped = mass_route.price([road(100, 1)], 500).narrow_s
    assert capped == pytest.approx(100 / flow.CRUISE_PACE_MS * mass_route.NARROW_RATIO_CAP)
    avoid = mass_route.price([(100, None, "avoid")], 500)
    assert avoid.narrow_s == pytest.approx(capped)
    assert avoid.narrowest_riders_per_min == 0
    # Not known (untraced, outside DC): no price either way.
    assert mass_route.price([(100, None, "untraced"), (100, None, "outside_dc")], 500).total_s == 0


def test_a_change_of_capacity_costs_the_square_of_its_size_and_stepping_down_more():
    down = mass_route.price([road(500, 200), road(500, 100)], 500)
    up = mass_route.price([road(500, 100), road(500, 200)], 500)
    assert down.transitions == up.transitions == 1
    assert down.transition_s == pytest.approx(mass_route.STEP_DOWN_S * 0.25)
    assert up.transition_s == pytest.approx(mass_route.STEP_UP_S * 0.25)
    # Halving costs four times what a quarter drop costs (item 123).
    quarter = mass_route.price([road(500, 200), road(500, 150)], 500)
    assert down.transition_s == pytest.approx(4 * quarter.transition_s)
    # A steady road and a small wobble cost nothing; a junction's few metres are not a change.
    assert mass_route.price([road(500, 200), road(500, 190)], 500).transitions == 0
    assert mass_route.price([road(500, 200), road(10, 100), road(500, 200)], 500).transitions == 0


def test_a_route_that_keeps_narrowing_and_widening_scores_worse_than_a_steady_one():
    steady = mass_route.price([road(300, 150)] * 4, 500)
    wobbly = mass_route.price([road(300, 150), road(300, 300)] * 2, 500)
    assert steady.narrowest_riders_per_min == wobbly.narrowest_riders_per_min
    assert wobbly.total_s > steady.total_s


def test_the_change_price_grows_with_the_ride_size_between_half_and_three_times():
    pair = [road(500, 400), road(500, 200)]
    small = mass_route.price(pair, 100).transition_s
    base = mass_route.price(pair, 500).transition_s
    big = mass_route.price(pair, 2000).transition_s
    assert small == pytest.approx(base * 0.5)
    assert big == pytest.approx(base * 3.0)


def test_the_narrow_stretches_merge_on_one_street_and_name_it():
    stretches = [
        road(300, 200, name="16th St NW"),
        road(200, 60, name="P St NW"),
        road(100, 40, name="P St NW"),
        road(300, 200, name="16th St NW"),
        (80, None, "avoid", "Bridge"),
    ]
    rows = mass_route.narrow_stretches(stretches, 100)
    assert rows == [
        {"from_m": 300, "to_m": 600, "street": "P St NW", "riders_per_min": 40, "avoid": False},
        {"from_m": 900, "to_m": 980, "street": "Bridge", "riders_per_min": 0, "avoid": True},
    ]


# ---- The corker load, held to the front end's (frontend/src/lib/corkerLoad.test.ts) ----------

PACE = 7 * 0.44704
LEVEL_22FT = 197.98
G = (500 / (LEVEL_22FT / 60)) * PACE


def junction(m, corkers=True, street=None, oneway=None, **extra):
    return {
        "m": m,
        "street": street or f"{round(m)} St",
        "control": "signal",
        "corkers_needed": corkers,
        "oneway": oneway,
        **extra,
    }


def profile_with(crossings, length=3 * MILE, **extra):
    n = round(length / 30) + 1
    m = [min(i * 30, length) for i in range(n)]
    body = {
        "m": m,
        "level_riders_per_min": [LEVEL_22FT] * n,
        "flow": {"cruise_pace_ms": PACE, "default_level_riders_per_min": LEVEL_22FT},
        "unchecked": [],
        "crossings": crossings,
        "crossings_complete": None if crossings is None else True,
    }
    body.update(extra)
    return body


def test_corkers_per_junction_as_the_front_end_counts_them():
    assert mass_route.corkers_for({"control": "signal"}) == 2
    assert mass_route.corkers_for({"control": "signal", "oneway": True}) == 1
    assert mass_route.corkers_for({"control": "signal", "oneway": True, "divided": True}) == 2
    assert mass_route.corkers_for({"control": "stop", "approach_lanes": 2}) == 4
    assert mass_route.corkers_for({"control": "stop", "oneway": True, "approach_lanes": 3}) == 3
    assert mass_route.corkers_for({"control": "stop", "approach_lanes": None}) == 2
    assert mass_route.corkers_for({"control": "signal", "approach_lanes": 3}) == 2


def test_the_headline_is_the_most_held_at_once_times_two():
    four = mass_route.corker_load(profile_with([junction(1000), junction(1400)]), 3 * MILE, 500)
    assert four["most_at_once"] == 4
    assert four["most_at_once_m"] == 1400
    assert four["headline"] == 8
    three = mass_route.corker_load(
        profile_with([junction(1000, oneway=True), junction(1200)]), 3 * MILE, 500
    )
    assert three["headline"] == 6
    apart = mass_route.corker_load(
        profile_with([junction(1000), junction(1000 + G + 5)]), 3 * MILE, 500
    )
    assert apart["headline"] == 4
    none = mass_route.corker_load(profile_with([]), 3 * MILE, 500)
    assert none["headline"] == 0
    assert none["most_at_once_m"] is None


def test_a_group_longer_than_the_route_holds_every_junction_at_its_end():
    total = 600
    profile = profile_with(
        [junction(100), junction(300), junction(500, street="One Way", oneway=True)], total
    )
    load = mass_route.corker_load(profile, total, 2000)
    assert load["most_at_once"] == 5
    assert load["headline"] == 10
    assert [j["corkers"] for j in load["junctions"]] == [2, 2, 1]


def test_a_partial_or_unchecked_list_is_at_least_and_not_checked_is_none():
    partial = profile_with([junction(1000)], crossings_complete=False)
    assert mass_route.corker_load(partial, 3 * MILE, 500)["at_least"] is True
    gap = profile_with([junction(1000)], unchecked=[{"from_m": 3000, "to_m": 3500}])
    assert mass_route.corker_load(gap, 3 * MILE, 500)["at_least"] is True
    assert (
        mass_route.corker_load(profile_with([junction(1000)]), 3 * MILE, 500)["at_least"] is False
    )
    assert mass_route.corker_load(profile_with(None), 3 * MILE, 500) is None
    older = profile_with([junction(1000)], flow={})
    assert mass_route.corker_load(older, 3 * MILE, 500) is None


def test_the_constants_match_the_front_ends():
    lib = Path(__file__).resolve().parents[1] / "frontend" / "src" / "lib"
    dials = (lib / "dials.ts").read_text()
    chart = (lib / "profileChart.ts").read_text()
    assert f"RIDE_SIZE_MIN = {mass_route.RIDE_SIZE_MIN};" in dials
    assert "RIDE_SIZE_MAX = 2_000;" in dials and mass_route.RIDE_SIZE_MAX == 2000
    assert f"RIDE_SIZE_DEFAULT = {mass_route.RIDE_SIZE_DEFAULT};" in dials
    assert f"RIDE_HOLD_MINUTES = {mass_route.HOLD_MINUTES};" in chart
    assert f"ROTATION_FACTOR = {mass_route.ROTATION_FACTOR};" in chart


# ---- The route choice ----------------------------------------------------------------------


def trip(cost: float, name: str) -> dict:
    return {"summary": {"cost": cost}, "legs": [{"shape": name}], "name": name}


@pytest.fixture
def stretches_of(monkeypatch):
    found: dict[str, list | None] = {}

    def fake(variant, costing, one, when, deadline, traces=None, names=False):
        value = found[one["name"]]
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(routing, "capacity_stretches", fake)
    monkeypatch.setattr(routing, "prefetch_traces", lambda *a, **k: None)
    return found


def choose(trips, riders=500, hill=lambda t: 0.0):
    deadline = routing.Deadline(math.inf, 10)
    return routing.choose_by_capacity(trips, hill, riders, "no_trail", {}, "now", deadline, None)


def test_a_wider_alternative_wins_where_the_routers_own_is_too_narrow_for_the_ride(stretches_of):
    stretches_of["own"] = [road(2000, 60)]
    stretches_of["wide"] = [road(2200, 200)]
    chosen, info = choose([trip(1000, "own"), trip(1100, "wide")])
    assert chosen == 1
    assert info["chosen"] == 1
    assert [row["route"] for row in info["routes_weighed"]] == [0, 1]
    assert info["routes_weighed"][1]["capacity_s"] == 0


def test_a_stretch_outside_dc_is_measured_not_priced():
    assert mass_route.OUTSIDE_DC_NOTE == routing.STRETCH_OUTSIDE_DC
    out = mass_route.price([road(1000, None, routing.STRETCH_OUTSIDE_DC)], 500)
    assert out.outside_m == 1000 and out.total_s == 0
    assert mass_route.price([road(1000, None, routing.STRETCH_UNTRACED)], 500).outside_m == 0


def test_a_route_that_stays_in_dc_wins_whatever_its_price(stretches_of):
    # The owner, 2026-10-29: "Don't leave DC on a mass ride." The router's own route crosses into
    # Maryland; the alternative stays in DC on a street far too narrow for 1500 riders, and wins.
    stretches_of["out"] = [road(1500, 400), road(1500, None, routing.STRETCH_OUTSIDE_DC)]
    stretches_of["in"] = [road(3000, 60)]
    chosen, info = choose([trip(1000, "out"), trip(1400, "in")], riders=1500)
    assert chosen == 1
    assert [row["outside_dc_m"] for row in info["routes_weighed"]] == [1500, 0]


def test_a_few_metres_over_the_line_decide_nothing(stretches_of):
    stretches_of["own"] = [road(2000, 400), road(20, None, routing.STRETCH_OUTSIDE_DC)]
    stretches_of["narrow"] = [road(2000, 60)]
    assert choose([trip(1000, "own"), trip(1000, "narrow")], riders=1500)[0] == 0


def test_the_ride_size_decides_the_same_two_routes(stretches_of):
    stretches_of["own"] = [road(2000, 60)]
    stretches_of["wide"] = [road(2200, 200)]
    # 200 riders need 40 a minute: the narrow road carries them, and the router's own stays.
    assert choose([trip(1000, "own"), trip(1100, "wide")], riders=200)[0] == 0
    assert choose([trip(1000, "own"), trip(1100, "wide")], riders=1500)[0] == 1


def test_the_climbing_still_counts(stretches_of):
    stretches_of["own"] = [road(2000, 200)]
    stretches_of["hilly"] = [road(2000, 200)]
    hills = {"own": 0.0, "hilly": 500.0}
    chosen, _ = choose([trip(1000, "own"), trip(900, "hilly")], hill=lambda t: hills[t["name"]])
    assert chosen == 0


def test_an_unreadable_route(stretches_of):
    # The router's own unreadable: the caller chooses as before.
    stretches_of["own"] = None
    stretches_of["wide"] = [road(2000, 200)]
    assert choose([trip(1000, "own"), trip(900, "wide")]) == (0, None)
    # An alternative unreadable, or out of time: passed over.
    stretches_of["own"] = [road(2000, 60)]
    stretches_of["wide"] = routing.DeadlineExceeded()
    chosen, info = choose([trip(1000, "own"), trip(900, "wide")])
    assert chosen == 0
    assert [row["route"] for row in info["routes_weighed"]] == [0]


def test_the_answers_summary():
    stretches = [road(1000, 200, name="Pennsylvania Ave"), road(400, 60, name="C St SE")]
    body = routing._mass_capacity(
        stretches, profile_with([junction(500)], 1400), 1400, 500, {"chosen": 0}
    )
    assert body["need_riders_per_min"] == 100
    assert body["narrowest_riders_per_min"] == 60
    assert body["narrowest_m"] == 1000
    assert body["below_need_m"] == 400
    assert body["capacity_changes"] == 1
    assert body["narrow_stretches"][0]["street"] == "C St SE"
    assert body["corkers"]["headline"] == 4
    assert body["choice"] == {"chosen": 0}


def test_the_api_takes_the_ride_size_and_describes_the_summary():
    from core import api

    assert "ride_size" in api.RouteIn.model_fields
    assert "mass_capacity" in api.RouteOut.model_fields
    body = routing._mass_capacity(
        [road(400, 60)], profile_with([junction(100)], 400), 400, 500, None
    )
    api.MassCapacityOut.model_validate(body)


# ---- The assistants' tool ------------------------------------------------------------------


def _mcp():
    if "routemaker_mcp" in sys.modules:
        return sys.modules["routemaker_mcp"]
    path = Path(__file__).resolve().parents[1] / "mcp" / "routemaker_mcp.py"
    spec = importlib.util.spec_from_file_location("routemaker_mcp", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["routemaker_mcp"] = module
    spec.loader.exec_module(module)
    return module


def test_the_tool_says_the_capacity_and_corkers_in_miles():
    mcp = _mcp()
    body = routing._mass_capacity(
        [road(1609.344, 200, name="A St"), road(1609.344, 60, name="B St")],
        profile_with([junction(500)], 2 * MILE),
        2 * MILE,
        500,
        None,
    )
    said = mcp.mass_capacity({"mass_capacity": body})
    assert said["needs_riders_per_min"] == 100
    assert said["miles_below_need"] == 1.0
    assert said["narrow_stretches"][0] == {
        "from_mi": 1.0,
        "to_mi": 2.0,
        "street": "B St",
        "riders_per_min": 60,
    }
    assert said["corkers"]["about"] == 4
    assert said["corkers"]["junctions"][0]["street"] == "500 St"
    assert mcp.mass_capacity({"mass_capacity": None}) is None
    assert "ride_size" in mcp.PASSED_OPTIONS


def test_the_tools_link_carries_the_ride_size_on_a_mass_ride_only():
    mcp = _mcp()
    dials = {"stress": 0, "hills": -95}
    link = mcp.plan_fragment(
        [(-77.0, 38.9), (-77.01, 38.91)], [], "mass-ride", dials, {"ride_size": 1200}
    )
    assert "riders=1200" in link
    other = mcp.plan_fragment(
        [(-77.0, 38.9), (-77.01, 38.91)], [], "default", dials, {"ride_size": 1200}
    )
    assert "riders=" not in other


# ---- The answer, through the API -------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestTheAnswer:
    @pytest.fixture
    def planned(self, monkeypatch, segment_schemas):
        from django.test import Client
        from test_avoid_junctions import PlanRouter, body_for
        from test_route_api import post as plan

        monkeypatch.setattr(routing, "_transport", PlanRouter(detour_cost=600.0))
        return lambda preset, **extra: plan(Client(), {**body_for(preset), **extra}).json()

    def test_the_api_chooses_the_wider_alternative_for_a_big_ride_only(
        self, monkeypatch, segment_schemas
    ):
        """Through the planner, not the choice alone: the router offers its own route (too
        narrow for 1500 riders) and a wider alternative; the plan rides the wider one for 1500
        and keeps the router's own for 200 (the v0.15.0 end review: nothing tested the plan)."""
        from django.test import Client
        from test_avoid_junctions import DETOUR, body_for, trace_for
        from test_route_api import VERTICES, route_answer
        from test_route_api import post as plan

        own_shape = route_answer([(VERTICES, 2.2, [])])["trip"]["legs"][0]["shape"]

        def router(url, payload, timeout):
            endpoint = url.rsplit("/", 1)[1]
            if endpoint == "trace_attributes":
                return trace_for(payload)
            if endpoint == "locate":
                return []
            answer = route_answer([(VERTICES, 2.2, [])])
            answer["trip"]["summary"]["cost"] = 500.0
            if "alternates" in payload:
                wide = route_answer([(DETOUR, 2.4, [])])["trip"]
                wide["summary"]["cost"] = 560.0
                answer["alternates"] = [{"trip": wide}]
            return answer

        def stretches(variant, costing, one, when, deadline, traces=None, names=False):
            narrow = one["legs"][0]["shape"] == own_shape
            return [road(2200, 60 if narrow else 400)]

        monkeypatch.setattr(routing, "_transport", router)
        monkeypatch.setattr(routing, "capacity_stretches", stretches)
        big = plan(Client(), {**body_for("mass-ride"), "ride_size": 1500}).json()
        small = plan(Client(), {**body_for("mass-ride"), "ride_size": 200}).json()
        assert big["mass_capacity"]["choice"]["chosen"] == 1, big["mass_capacity"]
        assert small["mass_capacity"]["choice"]["chosen"] == 0, small["mass_capacity"]
        assert big["geometry"] != small["geometry"]

    def test_a_mass_ride_with_a_point_outside_dc_is_refused_and_says_why(self, planned):
        # The owner, 2026-10-29: "Don't leave DC on a mass ride", then: refuse points outside DC.
        from test_avoid_junctions import body_for

        inside = body_for("mass-ride")["points"]
        arlington = [-77.0910, 38.8800]
        refused = planned("mass-ride", points=[inside[0], arlington])
        assert refused.get("code") == "mass_ride_outside_dc", refused
        assert refused["error"] == routing.MASS_RIDE_OUTSIDE_DC
        assert (
            planned("default", points=[inside[0], arlington]).get("code") != "mass_ride_outside_dc"
        )
        assert "mass_capacity" in planned("mass-ride")

    def test_a_mass_ride_says_its_capacity_for_the_ride_size_and_no_other_does(self, planned):
        body = planned("mass-ride")["mass_capacity"]
        assert body["riders"] == 500 and body["need_riders_per_min"] == 100
        assert planned("mass-ride", ride_size=1200)["mass_capacity"]["need_riders_per_min"] == 240
        assert planned("default")["mass_capacity"] is None
        assert planned("default", ride_size=1200)["mass_capacity"] is None
