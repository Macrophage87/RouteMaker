"""Stations on your way first (the owner, 2026-10-11: "we should prioritize the stations that
would be in the direction of the route").

The rule (core.bikeshare's docstring): a station costs its walk plus the extra riding it adds,
the extra being how much farther it is from the trip's other end than the rider's own point
is, never below zero. The docks are on one parallel (`east`), so every figure is arithmetic:
the start at 0 m, the destination 4,000 m east, unless a test says otherwise.

Each ranking test here fails on the old rule (nearest first and nothing else).
"""

from __future__ import annotations

import pytest
from test_bikeshare import FakeServices, east, run, street

from core import bikeshare

START = east(0)
GOAL = east(4000)


def full(name, at, ebikes=0):
    """A dock 90% full: listed to pick up from, and able to start a ride."""
    return (name, at, 9, ebikes, 1)


def empty(name, at):
    """A dock with no bikes and nine free slots: listed to return to, and able to end a ride."""
    return (name, at, 0, 0, 9)


def names(found) -> list[str]:
    return [s.name for s in found]


# --- The rule itself ------------------------------------------------------------------------


def test_a_station_toward_the_destination_adds_no_riding_and_one_behind_adds_its_distance() -> None:
    assert bikeshare.extra_riding_m(east(150), START, GOAL) == 0.0
    assert bikeshare.extra_riding_m(east(-100), START, GOAL) == pytest.approx(100, abs=1)
    assert bikeshare.station_cost_m(east(-100), START, GOAL) == pytest.approx(200, abs=1)
    assert bikeshare.station_cost_m(east(150), START, GOAL) == pytest.approx(150, abs=1)


def test_without_the_other_end_the_cost_is_the_distance() -> None:
    assert bikeshare.extra_riding_m(east(-100), START, None) == 0.0
    assert bikeshare.station_cost_m(east(-100), START, None) == pytest.approx(100, abs=1)


def test_the_reason_is_in_words() -> None:
    assert bikeshare.way_words(0.0) == "on your way"
    assert bikeshare.way_words(49.0) == "on your way"
    assert bikeshare.way_words(320.0) == "adds 0.2 mi (0.3 km) of riding"
    assert bikeshare.way_words(100.0) == "adds 330 ft (100 m) of riding"


# --- The station lists ------------------------------------------------------------------------


def test_pickup_puts_a_station_toward_the_destination_ahead_of_a_nearer_one_behind() -> None:
    snap = street(full("Behind", -100), full("Ahead", 150), full("Far ahead", 600))
    found = bikeshare.nearby_stations(START, bikeshare.PICKUP, snap, toward=GOAL)
    # Old rule: Behind (100 m), Ahead, Far ahead.
    assert names(found) == ["Ahead", "Behind", "Far ahead"]
    assert [s.on_the_way for s in found] == [True, False, True]
    assert found[0].extra_m == 0.0
    assert found[1].extra_m == pytest.approx(100, abs=1)


def test_dropoff_puts_a_station_before_the_destination_ahead_of_a_nearer_one_past_it() -> None:
    snap = street(full("Start", 0), empty("Past", 4100), empty("Before", 3850), empty("Far", 3300))
    found = bikeshare.nearby_stations(GOAL, bikeshare.DROPOFF, snap, toward=START)
    # Old rule: Past (100 m), Before (150 m), Far (700 m). Past costs 100 + 100 = 200 m.
    assert names(found) == ["Before", "Past", "Far"]
    assert [s.on_the_way for s in found] == [True, False, True]


def test_a_station_well_behind_still_fills_the_three_no_distance_cap() -> None:
    """Always three (the owner, 2026-10-10): a station behind is ranked lower, not dropped."""
    snap = street(full("Behind", -300), full("Ahead", 200), full("Far ahead", 9000))
    found = bikeshare.nearby_stations(START, bikeshare.PICKUP, snap, toward=GOAL)
    assert names(found) == ["Ahead", "Behind", "Far ahead"]
    assert len(found) == bikeshare.NEARBY_COUNT


def test_a_far_station_on_the_way_does_not_jump_a_near_one_behind() -> None:
    """Behind 100 m costs 200 m; a station 250 m ahead costs 250 m, so behind is still first."""
    snap = street(full("Behind", -100), full("Ahead", 250))
    found = bikeshare.nearby_stations(START, bikeshare.PICKUP, snap, toward=GOAL)
    assert names(found) == ["Behind", "Ahead"]


def test_without_the_other_end_the_list_is_by_distance_and_carries_no_reason() -> None:
    snap = street(full("Behind", -100), full("Ahead", 150), full("Far ahead", 600))
    found = bikeshare.nearby_stations(START, bikeshare.PICKUP, snap)
    assert names(found) == ["Behind", "Ahead", "Far ahead"]
    assert all(s.extra_m is None and s.on_the_way is None for s in found)


def test_the_list_keeps_its_fullness_rule_and_e_bike_counts() -> None:
    snap = street(
        ("Half full ahead", 50, 5, 0, 5),  # 50%: not listed to pick up from, as before
        ("Empty ahead", 60, 0, 0, 9),
        full("Behind", -100, ebikes=3),
        full("Ahead", 150, ebikes=2),
    )
    found = bikeshare.nearby_stations(START, bikeshare.PICKUP, snap, toward=GOAL)
    assert names(found) == ["Ahead", "Behind"]
    assert [s.ebikes for s in found] == [2, 3]


def test_many_stations_far_off_do_not_hide_a_better_one_and_the_search_stops_early() -> None:
    # Stations behind, then one ahead farther than all of them: the ahead one must win even
    # though three fit before it is reached by distance.
    snap = street(
        full("B1", -60), full("B2", -70), full("B3", -80), full("Ahead", 100), full("Far", 5000)
    )
    found = bikeshare.nearby_stations(START, bikeshare.PICKUP, snap, toward=GOAL)
    assert names(found) == ["Ahead", "B1", "B2"]


# --- The plan's choice of docks ----------------------------------------------------------------


def test_the_plan_considers_a_dock_ahead_even_when_three_nearer_ones_are_behind() -> None:
    # Old rule: only the three nearest (all behind) were walked, so the plan started behind.
    snap = street(
        ("B1", -150, 5, 0, 5),
        ("B2", -160, 5, 0, 5),
        ("B3", -170, 5, 0, 5),
        ("Ahead", 200, 5, 0, 5),
        ("Goal dock", 4000, 0, 0, 9),
    )
    body, _ = run(START, GOAL, snap=snap)
    plan = body["bikeshare"]
    assert plan["start"]["name"] == "Ahead"
    assert any("B1" in n and "adds" in n and "Ahead" in n for n in plan["notes"])


def test_the_plan_ends_at_a_dock_on_the_way_in_rather_than_nearer_ones_past_it() -> None:
    snap = street(
        ("Start dock", 0, 5, 0, 5),
        ("P1", 4150, 0, 0, 9),
        ("P2", 4160, 0, 0, 9),
        ("P3", 4170, 0, 0, 9),
        ("Before", 3800, 0, 0, 9),
    )
    plan = run(START, GOAL, snap=snap)[0]["bikeshare"]
    assert plan["end"]["name"] == "Before"
    assert any("P1" in n and "Before" in n for n in plan["notes"])


def test_only_the_few_best_docks_are_walked() -> None:
    snap = street(
        *((f"B{i}", -100 - 10 * i, 5, 0, 5) for i in range(6)), ("Goal dock", 4000, 0, 0, 9)
    )
    services = FakeServices()
    run(START, GOAL, snap=snap, services=services)
    assert len(services.walks) <= bikeshare.START_DOCKS + bikeshare.END_DOCKS + 1


# --- Route options ------------------------------------------------------------------------


def option_world():
    return street(
        ("Behind", -100, 5, 2, 5),
        ("Ahead", 150, 5, 1, 5),
        ("Side", 300, 5, 0, 5),
        ("Before", 3850, 0, 0, 9),
        ("Past", 4100, 0, 0, 9),
    )


def test_a_plan_offers_three_options_best_first_and_the_first_is_the_plan() -> None:
    plan = run(START, GOAL, snap=option_world())[0]["bikeshare"]
    options = plan["options"]
    assert len(options) == bikeshare.OPTION_COUNT
    assert [o["rank"] for o in options] == [1, 2, 3]
    assert [o["chosen"] for o in options] == [True, False, False]
    first = options[0]
    assert (first["pickup"]["name"], first["dropoff"]["name"]) == ("Ahead", "Before")
    assert (first["pickup"]["name"], first["dropoff"]["name"]) == (
        plan["start"]["name"],
        plan["end"]["name"],
    )
    assert first["estimated"] is False and first["total_s"] == plan["total_s"]
    assert all(o["estimated"] for o in options[1:])
    costs = [o["cost_m"] for o in options]
    assert costs == sorted(costs)


def test_an_option_can_be_asked_for_again_by_its_station_ids() -> None:
    snap = option_world()
    second = run(START, GOAL, snap=snap)[0]["bikeshare"]["options"][1]
    again = bikeshare.plan(
        START,
        GOAL,
        "classic",
        second["ending"],
        snap,
        FakeServices(),
        13.0,
        pickup_station=second["pickup_station"],
        dropoff_station=second["dropoff_station"],
    )["bikeshare"]
    assert again["start"]["station_id"] == second["pickup_station"]
    assert again["end"]["station_id"] == second["dropoff_station"]


def test_an_option_says_why_in_words_and_carries_e_bike_counts() -> None:
    options = run(START, GOAL, snap=option_world())[0]["bikeshare"]["options"]
    first = options[0]
    assert first["pickup"]["way_text"] == "on your way"
    assert first["pickup"]["on_the_way"] is True
    assert first["pickup"]["ebikes_available"] == 1
    assert first["text"].startswith("Pick up at Ahead, ")
    assert "on your way" in first["text"]
    assert "Return at Before, " in first["text"]
    assert " mi (" in first["text"] or " ft (" in first["text"]
    behind = [o for o in options if o["pickup"]["name"] == "Behind"]
    for option in behind:
        assert option["pickup"]["on_the_way"] is False
        assert "adds 330 ft (100 m) of riding" in option["text"]


def test_a_chosen_station_plan_lists_only_that_pair() -> None:
    snap = option_world()
    plan = bikeshare.plan(
        START, GOAL, "classic", "dock", snap, FakeServices(), 13.0,
        pickup_station="s0", dropoff_station="s3",
    )["bikeshare"]  # fmt: skip
    assert len(plan["options"]) == 1
    assert plan["options"][0]["pickup_station"] == "s0"
    assert plan["options"][0]["chosen"] is True


def test_the_way_round_an_avoided_junction_updates_the_chosen_option() -> None:
    plan = run(START, GOAL, snap=option_world())[0]["bikeshare"]
    around = bikeshare.alternate_block(plan, {"distance_m": 6000.0, "duration_s": 1800.0})
    chosen = around["options"][0]
    assert chosen["ride_m"] == 6000.0
    assert chosen["total_s"] == pytest.approx(plan["walk_s"] + 1800.0, abs=0.2)
    assert plan["options"][0]["ride_m"] != 6000.0
