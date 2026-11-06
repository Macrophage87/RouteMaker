"""Reach in the MCP server (Stephen, 2026-11-04: "This could also be added to the mcp server"):
`reach` (the rings' areas and places, no shapes, and a link that opens them) and `compare_places`
(riding minutes from each place considered to each place the rider goes, a matrix row a place)."""

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

HERE = [-77.05, 38.90]
THERE = [-77.03, 38.90]
WORK = [-77.00, 38.89]


def ring(minutes, sq_mi):
    return {
        "minutes": minutes,
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
        "area_sq_mi": sq_mi,
        "area_km2": round(sq_mi * 2.59, 2),
        "places": {"metro": 1, "racks": 2, "food": 3, "sights": 4},
    }


class FakeApi:
    base = "https://routes.example"

    def __init__(self):
        self.reached: list[dict] = []
        self.nearest_asked: list[dict] = []

    def reach(self, body):
        self.reached.append(body)
        group = {"point": None, "rings": [ring(m, m / 2) for m in body["minutes"]]}
        group["metro_stations"] = ["Dupont Circle"]
        return {
            "preset": body["preset"],
            "minutes": body["minutes"],
            "direction": body["direction"],
            "combine": body["combine"],
            "stress_used": body.get("stress", 70),
            "groups": [group],
            "calm": {"stress": 80, "groups": [group]} if body["calm"] else None,
            "unplaced": [],
        }

    def nearest(self, body):
        self.nearest_asked.append(body)
        start = body["points"][0]
        calm = body.get("stress") == 80
        # Further east is quicker; the calm way is a third longer.
        seconds = round((1 - (start[0] + 77.06) * 10) * 600 * (4 / 3 if calm else 1))
        return {
            "by": "riding",
            "places": [{"distance_m": 3000, "time_s": seconds} for _ in body["points"][1:]],
        }


@pytest.fixture
def api():
    return FakeApi()


@pytest.fixture
def tools(api):
    return mcp.Server(lambda: api, stations=[], out_dir=None)


def test_reach_answers_areas_and_places_without_shapes_and_a_link(tools, api) -> None:
    out = tools.call("reach", {"points": [HERE], "preset": "fast", "stress": 20})
    body = api.reached[0]
    assert body["minutes"] == [15, 30, 45, 60] and body["calm"] is True
    assert body["preset"] == "fast" and body["stress"] == 20
    (group,) = out["groups"]
    assert [r["minutes"] for r in group["rings"]] == [15, 30, 45, 60]
    assert "geometry" not in group["rings"][0]
    assert group["rings"][1]["places"]["metro"] == 1
    assert out["calm"]["stress"] == 80
    assert out["link"].startswith("https://routes.example/#p=-77.05000,38.90000")
    assert "preset=fast" in out["link"] and out["link"].endswith("reach=from.any.calm")


def test_reach_from_several_points_to_them(tools, api) -> None:
    out = tools.call(
        "reach",
        {"points": [HERE, THERE], "direction": "to", "combine": "all", "calm": False},
    )
    assert api.reached[0]["direction"] == "to" and api.reached[0]["combine"] == "all"
    assert out["combine"] == "all" and "calm" not in out
    assert out["link"].endswith("reach=to.all")


def test_reach_refuses_transit_and_too_many_points(tools) -> None:
    with pytest.raises(mcp.ToolError):
        tools.call("reach", {"points": [HERE], "preset": "bike-transit"})
    with pytest.raises(mcp.ToolError):
        tools.call("reach", {"points": [HERE] * 6})


def test_reach_on_a_run_sends_the_pace(tools, api) -> None:
    tools.call("reach", {"points": [HERE], "preset": "run", "pace_mph": 6})
    assert api.reached[0]["run_pace_kmh"] == 9.7
    assert "cycling_speed_kmh" not in api.reached[0]


def test_compare_places_ranks_by_limits_met_then_minutes(tools, api) -> None:
    out = tools.call(
        "compare_places",
        {
            "places": [HERE, THERE],
            "destinations": [{"place": WORK, "max_minutes": 7}],
            "preset": "default",
        },
    )
    # One row at the rider's setting and one at Low-stress, a place.
    assert len(api.nearest_asked) == 4
    assert api.nearest_asked[1]["stress"] == 80
    first, second = out["places"]
    assert first["place"] == THERE and first["limits_met"] == 1
    assert second["limits_met"] == 0
    trip = first["trips"][0]
    assert trip["minutes"] < trip["calm_minutes"]
    assert trip["miles"] == pytest.approx(1.86, abs=0.01)
    assert first["reach_link"].endswith("reach=from.any.calm")


def test_compare_places_at_low_stress_already_asks_once(tools, api) -> None:
    out = tools.call(
        "compare_places",
        {"places": [HERE, THERE], "destinations": [{"place": WORK}], "stress": 90},
    )
    assert len(api.nearest_asked) == 2
    assert all("calm_minutes" not in t for row in out["places"] for t in row["trips"])


def test_compare_places_is_for_bike_ride_types(tools) -> None:
    with pytest.raises(mcp.ToolError):
        tools.call(
            "compare_places",
            {"places": [HERE, THERE], "destinations": [{"place": WORK}], "preset": "walk"},
        )


def test_compare_places_on_a_mass_ride_asks_no_calm_row(tools, api) -> None:
    """Mass Ride's slider is locked, so a Low-stress figure would say nothing."""
    out = tools.call(
        "compare_places",
        {"places": [HERE, THERE], "destinations": [{"place": WORK}], "preset": "mass-ride"},
    )
    assert len(api.nearest_asked) == 2
    assert all("calm_minutes" not in t for row in out["places"] for t in row["trips"])


def test_compare_places_ranks_a_place_with_no_way_there_last(tools, api) -> None:
    """Before: a trip the router could not make counted as 0 minutes and ranked that place first."""
    real = api.nearest

    def nearest(body):
        got = real(body)
        if body["points"][0] == THERE:
            got["places"] = [{"distance_m": None, "time_s": None} for _ in got["places"]]
        return got

    api.nearest = nearest
    out = tools.call(
        "compare_places",
        {"places": [THERE, HERE], "destinations": [{"place": WORK}], "stress": 90},
    )
    assert [row["place"] for row in out["places"]] == [HERE, THERE]
    assert out["places"][1]["unreachable"] == 1


def test_a_bikeshare_e_bike_reach_link_opens_the_share_e_bike_in_the_app(tools, api) -> None:
    """The app's Bikeshare takes the e-bike as its bike choice (`bike=ebike`): an `assist=1` link
    opened as the classic (frontend lib/reach.test.ts reads this link back)."""
    out = tools.call("reach", {"points": [HERE], "preset": "bikeshare", "assist": True})
    assert api.reached[0]["assist"] is True
    assert "bike=ebike" in out["link"] and "assist=1" not in out["link"]
    cargo = tools.call("reach", {"points": [HERE], "preset": "cargo", "assist": True})
    assert "assist=1" in cargo["link"] and "bike=" not in cargo["link"]


def test_reach_says_mountain_bike_rings_take_every_trail_level(tools, api) -> None:
    real = api.reach
    api.reach = lambda body: {**real(body), "trail_level_applied": False}
    out = tools.call("reach", {"points": [HERE], "preset": "mountain-bike"})
    assert "every level" in out["trail_level"]
    api.reach = lambda body: {**real(body), "trail_level_applied": None}
    assert "trail_level" not in tools.call("reach", {"points": [HERE]})


def test_reach_with_only_some_rings_links_to_just_those(tools, api) -> None:
    out = tools.call("reach", {"points": [HERE], "minutes": [45, 15]})
    assert api.reached[0]["minutes"] == [15, 45]
    assert out["link"].endswith("reach=from.any.calm.15.45")


def test_reach_at_minutes_the_app_does_not_draw_says_what_the_link_opens(tools, api) -> None:
    out = tools.call("reach", {"points": [HERE], "minutes": [20, 45]})
    assert out["link_rings"] == [45]
    assert out["link"].endswith("reach=from.any.calm.45")
    assert tools.call("reach", {"points": [HERE], "minutes": [10]})["link_rings"] == [
        15,
        30,
        45,
        60,
    ]
    assert "link_rings" not in tools.call("reach", {"points": [HERE]})


def test_compare_places_on_novice_asks_one_row_a_place(tools, api) -> None:
    """Novice starts at the top of the slider, past Low-stress: its own minutes are the calm
    ones, so no second row is asked and the reach link offers no calm layer."""
    out = tools.call(
        "compare_places",
        {"places": [HERE, THERE], "destinations": [{"place": WORK}], "preset": "novice"},
    )
    assert len(api.nearest_asked) == 2
    assert all("stress" not in body for body in api.nearest_asked)
    assert all("calm_minutes" not in t for row in out["places"] for t in row["trips"])
    assert all(row["reach_link"].endswith("reach=from.any") for row in out["places"])


def test_compare_places_on_a_cargo_bike_carrying_people_asks_one_row_a_place(tools, api) -> None:
    tools.call(
        "compare_places",
        {
            "places": [HERE, THERE],
            "destinations": [{"place": WORK}],
            "preset": "cargo",
            "carrying": "people",
        },
    )
    assert len(api.nearest_asked) == 2


def test_the_calm_rule_is_the_site_s_own() -> None:
    """compare_places offers a calm figure exactly where the site's reach offers calm rings."""
    from core import presets, reach, routing

    for name in presets.PRESETS:
        if name in reach.NOT_YET or name in reach.ON_FOOT:
            continue
        assert mcp.STRESS_START[name] == presets.stress_start(name), name
        for carrying in [None, *(presets.PRESETS[name].carrying or [])]:
            for stress in (None, 0, 40, 70, 79, 80, 90, 100):
                site = reach.calm_offered(name, routing.Dials(stress=stress, carrying=carrying))
                ours = mcp.calm_offered(name, {"stress": stress, "carrying": carrying})
                assert ours is site, (name, carrying, stress)
    assert mcp.CARGO_STRESS_START == dict(presets.PRESETS["cargo"].carrying)
    assert mcp.CALM_STRESS == reach.CALM_STRESS


def test_compare_places_out_of_time_says_which_places_were_not_compared(tools, api) -> None:
    """A place begun with too little of the call's time left would come back in straight lines
    and rank as unreachable: it is listed as not compared instead."""
    call = mcp.Call(deadline=mcp.time.monotonic() + 600)
    real = api.nearest

    def nearest(body):
        # The first place takes the rest of the call's time.
        call.deadline = mcp.time.monotonic() + 1
        return real(body)

    api.nearest = nearest
    out = tools.call(
        "compare_places",
        {"places": [HERE, THERE], "destinations": [{"place": WORK}], "stress": 90},
        call,
    )
    assert [row["place"] for row in out["places"]] == [HERE]
    assert out["not_compared"] == [THERE]
    assert "ran out of time after 1 of 2 places" in out["notes"][0]
