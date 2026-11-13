"""The routing presets the public planner offers, held against PLAN.md's
Routing model table.

Each assertion is a property the plan states about a modality - which variant it
routes on, which dials it raises or lowers relative to Default, that it names its
`bicycle_type` - rather than a pinned number, so a retuned value that still says
what the table says passes and one that contradicts it fails.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.conf import settings

from core import presets
from pipeline.variants import Variant

# The contract's three, Cargo Bike (the owner, 2026-09-27: "Also another
# popular option in our city would be cargo bikes.") and the rest of PLAN's
# table ("Add the other presets too, like trailmaxxing").
CONTRACT_PRESETS = {
    "default",
    "trailmaxxing",
    "group-ride",
    "mass-ride",
    "mountain-goat",
    "gravel",
    "fast",
    "cargo",
    "ebike",
    # FOLLOWUP-BIKESHARE (OWNER-DECISIONS 243-245, 299).
    "bikeshare",
    # Novice and Nervous (v0.7.0), in Riding with kids' place (OWNER-DECISIONS 240 (B)).
    "novice",
    # docs/MTB-TOPO-PLAN.md, slice 6 (OWNER-DECISIONS 90, 111, 148, 454).
    "mountain-bike",
    # TRANSIT-ASSIST (Stephen, 2026-10-12): the two transit ride types.
    "bike-transit",
    "bikeshare-transit",
    # Walk and Walk + 🚆🚌 (Stephen, 2026-11-02: "add a walk mode and a walk+transit mode").
    "walk",
    "walk-transit",
    # REBALANCE-RIDE (Stephen, 2026-10-12): Rebalance Ride.
    "rebalance",
    # Road Bike (Stephen, 2026-11-02), in the Avoid gravel box's place.
    "road-bike",
    # Run (Stephen, 2026-11-02): on foot, on Walk's map (core.run_plan).
    "run",
    # Tandem (Stephen, 2026-11-08): a bicycle built for two.
    "tandem",
}

# The factor dials Valhalla reads on a 0..1 scale; outside it the service
# clamps or refuses, and either way the preset would not mean what it says.
UNIT_DIALS = ("use_roads", "use_hills", "avoid_bad_surfaces", "use_living_streets")

# Every dial the plan's layer 2 names. PLAN: "Every dial exists on every
# preset", so none of them is left to Valhalla's default by omission.
LAYER_2_DIALS = {
    "bicycle_type",
    "use_roads",
    "use_hills",
    "avoid_bad_surfaces",
    "use_living_streets",
    "maneuver_penalty",
    "gate_cost",
    "gate_penalty",
    "private_access_penalty",
    "country_crossing_cost",
    "country_crossing_penalty",
}

MPH_TO_KMH = 1.609344


def options(name: str) -> dict:
    return presets.PRESETS[name].costing_options


def test_the_contract_presets_are_exactly_the_ones_offered() -> None:
    assert set(presets.PRESETS) == CONTRACT_PRESETS


@pytest.mark.parametrize("name", sorted(CONTRACT_PRESETS))
def test_every_preset_routes_on_a_variant_the_deployment_serves(name: str) -> None:
    variant = presets.PRESETS[name].variant
    assert variant in {v.value for v in Variant}
    assert variant in settings.VALHALLA_UPSTREAMS


def test_mass_ride_routes_on_the_no_trail_variant() -> None:
    """PLAN Routing model, Mass Ride L1: the no-trail variant. A field of
    hundreds does not fit on a trail, which is a capacity fact, not a dial."""
    assert presets.PRESETS["mass-ride"].variant == Variant.NO_TRAIL.value


@pytest.mark.parametrize("name", ["default", "group-ride"])
def test_the_trail_allowing_presets_route_on_the_standard_variant(name: str) -> None:
    """Default has no layer 1 entry; Group Ride ships with its trail toggle on,
    which is the standard variant."""
    assert presets.PRESETS[name].variant == Variant.STANDARD.value


@pytest.mark.parametrize("name", sorted(CONTRACT_PRESETS))
def test_every_preset_states_every_layer_2_dial(name: str) -> None:
    assert LAYER_2_DIALS <= set(options(name))


@pytest.mark.parametrize("name", sorted(CONTRACT_PRESETS))
def test_no_preset_penalises_crossing_a_state_line(name: str) -> None:
    """Owner decision (State crossing penalty): both options are sent as zero
    on every preset, because Valhalla's default of 600 s would otherwise apply
    at every border control node."""
    assert options(name)["country_crossing_cost"] == 0
    assert options(name)["country_crossing_penalty"] == 0


@pytest.mark.parametrize("name", sorted(CONTRACT_PRESETS))
def test_every_factor_dial_is_on_valhallas_scale(name: str) -> None:
    for dial in UNIT_DIALS:
        assert 0.0 <= options(name)[dial] <= 1.0, dial


@pytest.mark.parametrize("name", sorted(CONTRACT_PRESETS))
def test_no_preset_arms_the_hard_surface_exclusion(name: str) -> None:
    """PLAN Presets: the exclusion arms only at exactly 1.0, and none of these
    three is a preset that arms it deliberately."""
    assert options(name)["avoid_bad_surfaces"] < 1.0


def test_the_bicycle_types_are_the_ones_the_plan_names() -> None:
    """PLAN Presets: Default and Mass Ride are Hybrid, Group Ride is Cross so
    that the rural references' gravel is cheap rather than merely permitted."""
    assert options("default")["bicycle_type"] == "Hybrid"
    assert options("mass-ride")["bicycle_type"] == "Hybrid"
    assert options("group-ride")["bicycle_type"] == "Cross"


def test_default_is_more_stress_averse_than_mid_and_rides_the_fastest_hills() -> None:
    """Superseding the table's "mid use_roads, mid use_hills" for Default. The
    owner, 2026-09-27: the old default was "a bit too traffic tolerant for most
    people" and a faster road route "not worth it for most people"; and the
    hills slider's middle is "basically fastest time for most people", which is
    `use_hills` 1.0 (no grade penalty; Valhalla's grade-speed model only)."""
    assert options("default")["use_roads"] < options("group-ride")["use_roads"]
    assert options("default")["use_roads"] <= 0.1
    assert options("default")["use_hills"] == 1.0
    assert presets.PRESETS["default"].hills == 0


def test_cargo_is_hill_averse_slow_and_gate_shy() -> None:
    """PLAN Cargo: "No narrow gaps, gentle grades | L2: high gate_cost, low
    use_hills"; the owner: "They tend not to be great on hills"."""
    assert options("cargo")["use_hills"] < options("default")["use_hills"]
    assert options("cargo")["use_hills"] <= 0.5
    # What a gate costs Cargo is `gate_cost + gate_penalty`: since 2026-11-08 most of it is
    # penalty, which is cost alone, and `gate_cost`, which is also time, is a 30 s slow-down
    # (hunt C4). Until then this compared `gate_cost` alone.
    assert _gate_charge("cargo") > _gate_charge("group-ride")
    assert options("cargo")["cycling_speed"] < 18.0
    assert options("cargo")["avoid_bad_surfaces"] > options("default")["avoid_bad_surfaces"]
    assert options("cargo")["bicycle_type"] == "Hybrid"


def test_tandem_keeps_out_of_narrow_gaps_turns_less_and_climbs_gently() -> None:
    """The owner, 2026-11-08: "Build a tandem ride type"; the large gate penalty "was intended
    just for Tandem, and possibly cargo too". A long, heavy bike for two (core.presets,
    "Tandem")."""
    tandem = options(presets.TANDEM)
    assert _gate_charge(presets.TANDEM) == _gate_charge("cargo") >= 600
    assert tandem["gate_cost"] <= 30
    assert tandem["maneuver_penalty"] == presets.HIGH_MANEUVER_PENALTY_S
    assert tandem["use_hills"] < options("default")["use_hills"]
    assert tandem["avoid_bad_surfaces"] > options("default")["avoid_bad_surfaces"]
    # Faster on the flat than Default's hybrid: two riders, one bike's drag.
    assert tandem["cycling_speed"] > presets.VALHALLA_DEFAULT_SPEED_KMH["Hybrid"]
    # The stoker is not in control (OWNER-DECISIONS 221, 241): Cargo with passengers' start
    # and exposure.
    assert presets.stress_start(presets.TANDEM) == presets.stress_start("cargo", "people") == 80
    assert presets.exposure_for(presets.TANDEM) == presets.EXPOSURE_NOT_IN_CONTROL
    assert presets.wait_weight_for(presets.TANDEM) == 2.0
    assert presets.wait_weight_for(presets.TANDEM) < presets.wait_weight_for(presets.ROAD_BIKE)
    assert presets.variant_for_ride(presets.TANDEM, "weekday_offpeak") == Variant.STANDARD.value
    assert presets.variant_for_ride(presets.TANDEM, "weekend") == Variant.WEEKEND.value
    assert presets.rider_speed(presets.TANDEM, 30.0) == 30.0


def test_tandem_plans_climbs_at_two_riders_weight_unless_the_rider_set_one() -> None:
    from routemaker import effort

    assert presets.system_weight_for(presets.TANDEM) == effort.TANDEM_MASS_KG
    assert effort.TANDEM_MASS_KG > effort.PASSENGERS_MASS_KG > effort.MASS_KG
    assert presets.system_weight_for(presets.TANDEM, chosen=150) == 150


def test_carrying_cargo_is_default_and_people_the_top_of_the_slider() -> None:
    """The owner, 2026-09-28: "Same as Default, 90 (Recommended)" for carrying
    cargo; carrying people stays calmer, at the old top of the slider - 80 now
    that the slider runs on to 100 (OWNER-DECISIONS 163)."""
    people = presets.stress_start("cargo", presets.CARRYING_PEOPLE)
    cargo = presets.stress_start("cargo", presets.CARRYING_CARGO)
    assert cargo == presets.DEFAULT_STRESS == presets.stress_start("default")
    assert people == presets.STRESS_TODAYS_TOP > cargo
    assert presets.stress_start("cargo") == cargo


DIALS_TS = Path(__file__).resolve().parents[1] / "frontend" / "src" / "lib" / "dials.ts"


def _front_end_starts() -> dict[str, dict]:
    """dials.ts's STARTS table, read as data: one row per preset."""
    import re

    text = DIALS_TS.read_text()
    table = text[text.index("export const STARTS") :]
    table = table[: table.index("\n};") + 3]
    starts = {}
    for name, body in re.findall(r'^\s*"?([a-z-]+)"?: \{(.*)\},$', table, re.MULTILINE):
        row = {}
        for key in ("stress", "hills", "stressMax"):
            found = re.search(rf"\b{key}: (-?\d+)", body)
            if found:
                row[key] = int(found.group(1))
        row["seek"] = "seek: true" in body
        row["climbs"] = "climbs: true" in body
        row["assist"] = "assist: true" in body
        carrying = re.search(r"carrying: \{ cargo: (\d+), people: (\d+) \}", body)
        if carrying:
            row["carrying"] = {"cargo": int(carrying.group(1)), "people": int(carrying.group(2))}
        starts[name] = row
    return starts


def test_the_front_ends_starts_are_the_apis() -> None:
    """The UI always sends `stress` and `hills`, so a start that differs from
    the API's plans every ride of that type somewhere else (review, 2026-09-28:
    E-bike planned at 75 against the API's 90)."""
    starts = _front_end_starts()
    assert set(starts) == set(CONTRACT_PRESETS)
    for name in sorted(CONTRACT_PRESETS):
        preset = presets.PRESETS[name]
        row = starts[name]
        assert row["stress"] == presets.stress_start(name), name
        assert row["hills"] == preset.hills, name
        assert row["seek"] == preset.hills_seek, name
        assert row["climbs"] == (not preset.hills_tolerate), name
        assert row.get("stressMax", presets.STRESS_MAX) == preset.stress_max, name
        assert row["assist"] == (preset.assist_speed_kmh is not None), name
        if preset.carrying is None:
            assert "carrying" not in row, name
        else:
            assert row["carrying"] == {
                load: presets.stress_start(name, load) for load in ("cargo", "people")
            }, name


def test_only_mass_ride_stops_the_hills_slider_at_the_detent() -> None:
    assert {name for name, p in presets.PRESETS.items() if not p.hills_seek} == {"mass-ride"}


@pytest.mark.parametrize("name", sorted(CONTRACT_PRESETS))
def test_the_starts_are_inside_the_sliders(name: str) -> None:
    preset = presets.PRESETS[name]
    assert presets.STRESS_MIN <= preset.stress <= presets.STRESS_MAX
    assert presets.HILLS_MIN <= preset.hills <= (presets.HILLS_MAX if preset.hills_seek else 0)


def test_mass_ride_wants_the_roadway_and_avoids_hills() -> None:
    """L2: use_roads at max, use_hills near zero."""
    assert options("mass-ride")["use_roads"] == 1.0
    assert options("mass-ride")["use_hills"] < options("default")["use_hills"]
    assert options("mass-ride")["use_hills"] <= 0.1


def test_group_ride_keeps_mid_use_roads() -> None:
    assert 0.25 < options("group-ride")["use_roads"] < 0.75


@pytest.mark.parametrize("name", ["group-ride", "mass-ride"])
def test_the_group_presets_raise_the_maneuver_penalty(name: str) -> None:
    assert options(name)["maneuver_penalty"] > options("default")["maneuver_penalty"]


def _gate_charge(name: str) -> int:
    """The cost Valhalla adds at an untagged gate (sif/dynamiccost.h: gate_cost + gate_penalty)."""
    return options(name)["gate_cost"] + options(name)["gate_penalty"]


def test_group_ride_pays_a_small_gate_charge_like_default() -> None:
    """The owner, 2026-11-08: the large gate penalty "was intended just for Tandem, and
    possibly cargo too. Basically, bollards aren't huge deterrents in most cases." Until then
    this test pinned Group Ride's higher gate cost (120 s, and 420 s with the penalty)."""
    assert _gate_charge("group-ride") == _gate_charge("default") == 30


# The owner, 2026-11-08: the large charge is "for Tandem, and possibly cargo too".
GATE_SHY = frozenset({"cargo", presets.TANDEM})


@pytest.mark.parametrize("name", sorted(presets.PRESETS))
def test_only_cargo_and_tandem_pay_a_large_gate_charge(name: str) -> None:
    """Every other ride type pays a small slow-down at a gate, cycle barrier or narrow
    bollard: Valhalla's 30 s and no penalty. Before 2026-11-08: 330 s (420 s for Group Ride
    and Road Bike, 900 s for the share bikes, Walk and Run) (hunt T1, H3)."""
    if name in GATE_SHY:
        assert _gate_charge(name) >= 600
    else:
        assert _gate_charge(name) == presets.GATE_COST_S == 30
        assert options(name)["gate_penalty"] == 0


@pytest.mark.parametrize("name", sorted(presets.PRESETS))
def test_a_gate_adds_no_more_than_half_a_minute_to_the_time(name: str) -> None:
    """`gate_cost` is time as well as cost; `gate_penalty` is cost alone (sif/dynamiccost.h).
    Cargo's gate cost of 300 s put five minutes per barrier on its arrival times and the
    share bikes' legs to docks and stations (hunt C4, 2026-11-08)."""
    assert options(name)["gate_cost"] <= 30


def test_every_preset_states_the_private_barrier_penalty() -> None:
    for name in presets.PRESETS:
        assert options(name)["private_access_penalty"] == presets.VALHALLA_PRIVATE_ACCESS_PENALTY_S


def _living_street_entry_s(value: float) -> float:
    """Valhalla's living-street entry charge (sif/dynamiccost.cc at 3.9.1)."""
    return 500 * (1 - 2 * value) if value < 0.5 else 0.0


@pytest.mark.parametrize("name", ["fast", presets.ROAD_BIKE])
def test_fast_and_road_bike_dislike_a_living_street_mildly(name: str) -> None:
    """Their comment's "a shared street is slow for a road bike": about a minute of cost per
    entry, not the 300 s their 0.2 charged (hunt C5, 2026-11-08)."""
    assert 0 < _living_street_entry_s(options(name)["use_living_streets"]) <= 60


def test_mass_ride_plans_inside_the_speed_band() -> None:
    """The mass ride speed band: 5 to 9 mph, planned at 6 by default. The
    duration a Mass Ride reports is moving time at that pace, not at Valhalla's
    Hybrid default of 18 km/h."""
    speed = options("mass-ride")["cycling_speed"]
    assert 5 * MPH_TO_KMH <= speed <= 9 * MPH_TO_KMH


def test_mass_ride_plans_at_the_bands_default_of_six() -> None:
    """ "Planning speed for Mass Ride therefore defaults to 6 miles per hour"."""
    assert options("mass-ride")["cycling_speed"] == pytest.approx(6 * MPH_TO_KMH, abs=0.1)


@pytest.mark.parametrize("name", ["default", "group-ride"])
def test_the_other_presets_leave_the_speed_to_the_bicycle_type(name: str) -> None:
    """No planning speed is named for them, so the type's own default applies."""
    assert "cycling_speed" not in options(name)


def test_the_request_costing_is_a_copy() -> None:
    """A caller that adjusts the options it was handed must not retune the
    preset for every later request in the same worker."""
    first = presets.costing("default")
    first["bicycle"]["use_roads"] = 0.99
    assert presets.costing("default")["bicycle"]["use_roads"] == options("default")["use_roads"]


def test_an_unknown_preset_is_refused() -> None:
    with pytest.raises(KeyError):
        presets.costing("night")


def test_trailmaxxing_is_more_stress_averse_than_default() -> None:
    """ "Lowest stress ride, directness secondary | L2: use_roads near zero,
    living streets on, low surface avoidance"."""
    assert options("trailmaxxing")["use_roads"] < options("default")["use_roads"]
    assert options("trailmaxxing")["use_roads"] == 0.0
    # Inert above 0.5 in bicycle costing (`presets._LIVING_STREETS`): what makes a living
    # street cheap on Trailmaxxing is its use_roads of 0. Kept as PLAN's "living streets on".
    assert options("trailmaxxing")["use_living_streets"] > options("default")["use_living_streets"]
    assert options("trailmaxxing")["avoid_bad_surfaces"] < options("default")["avoid_bad_surfaces"]


def test_fast_is_direct_turn_shy_and_smooth() -> None:
    """ "L2: high use_roads, high maneuver_penalty, high surface avoidance"."""
    # The old Fast was `use_roads` 0.90; on the slider's steps of five the
    # nearest is 10, 0.871 (5 would be 0.936). Still the most direct of the
    # ride types that are not traffic tolerant.
    assert options("fast")["use_roads"] == pytest.approx(0.871)
    assert options("fast")["maneuver_penalty"] > options("default")["maneuver_penalty"]
    assert options("default")["avoid_bad_surfaces"] < options("fast")["avoid_bad_surfaces"] < 1.0


def test_mountain_goat_starts_at_seek() -> None:
    assert presets.PRESETS["mountain-goat"].hills == presets.HILLS_MAX
    assert presets.PRESETS["mountain-goat"].hills_seek


def test_gravel_has_no_surface_avoidance() -> None:
    assert options("gravel")["avoid_bad_surfaces"] == 0.0


def test_ebike_routes_on_the_ebike_variant() -> None:
    """ "L1: e-bike variant"; its hills slider starts toward "fine with hills" (242), where
    `use_hills` stays at the detent's 1.0."""
    assert presets.PRESETS["ebike"].variant == Variant.EBIKE.value
    assert presets.PRESETS["ebike"].hills == presets.EBIKE_HILLS > 0
    assert options("ebike")["use_hills"] == 1.0
    assert options("ebike")["cycling_speed"] > 18.0


def test_only_mountain_goat_seeks_climbs() -> None:
    """FOLLOWUP-HILLS-TOLERATE (242): the right half is "fine with hills" on every ride
    type but Mountain Goat."""
    assert {n for n, p in presets.PRESETS.items() if not p.hills_tolerate} == {"mountain-goat"}


@pytest.mark.parametrize(("hills", "weight"), [(-50, 0.0), (0, 0.0), (50, 0.5), (100, 1.0)])
def test_the_tolerate_weight_is_the_right_half_over_100(hills: int, weight: float) -> None:
    assert presets.tolerate_weight(hills) == weight


@pytest.mark.parametrize("name", ["trailmaxxing", "mountain-goat", "gravel"])
def test_the_off_road_presets_are_cross_or_mountain(name: str) -> None:
    """PLAN, Presets: "Trailmaxxing, Bikepacking, and Mountain Goat are Cross
    or Mountain"; Gravel's row says the same. (Bikepacking is not offered.)"""
    assert options(name)["bicycle_type"] in {"Cross", "Mountain"}


@pytest.mark.parametrize("name", ["fast", "cargo", "mass-ride"])
def test_the_roadway_presets_are_hybrid(name: str) -> None:
    """PLAN, Presets: "Mass Ride, Fast, Beginner, Recovery, and Cargo are Hybrid"."""
    assert options(name)["bicycle_type"] == "Hybrid"


@pytest.mark.parametrize("name", ["night", "bikepacking", "beginner", "recovery"])
def test_the_dropped_presets_are_not_offered(name: str) -> None:
    """The owner dropped them, 2026-09-27 (PLAN.md, Owner amendments)."""
    assert name not in presets.PRESETS


def test_default_starts_at_the_owners_ninety() -> None:
    """The owner's answer of 2026-09-27: "90" - which is 70 on the slider since
    the rescale of 2026-10-01, with the same `use_roads` (tests/test_calm_slider.py)."""
    assert presets.PRESETS["default"].stress == 70
    assert presets.PRESETS["default"].costing_options["use_roads"] == 0.1


def test_the_weekend_graphs_twin_only_the_standard_and_paved_graphs() -> None:
    """The standard graph's weekend twin, and Road Bike's (the owner, 2026-11-08, "New weekend
    graph"); every other graph keeps its weekend rides."""
    twins = {"standard": "weekend", "paved": "paved-weekend"}
    for name, preset in presets.PRESETS.items():
        weekend = presets.variant_for_ride(name, "weekend")
        weekday = presets.variant_for_ride(name, "weekday_rush")
        if name in presets.OFFROAD_PRESETS:
            # Gravel and Mountain Goat ride the off-road graph, which has no
            # weekend twin (OWNER-DECISIONS 291(2)).
            assert weekday == weekend == "offroad"
            assert weekend in settings.VALHALLA_UPSTREAMS
            continue
        assert weekday == preset.variant
        assert weekend == twins.get(preset.variant, preset.variant)
        assert weekend in settings.VALHALLA_UPSTREAMS


def test_the_rides_that_keep_the_mtb_class_plan_on_the_weekend_graph_too() -> None:
    """The owner, 2026-11-08: "We can do the plan twice." (`routing._plan_twice`)."""
    twice = {name for name in presets.PRESETS if presets.weekend_too(name, "weekend")}
    # E-bike too (round 3, 2026-11-08, "Yes"): the e-bike graph has no weekend twin.
    assert twice == {"gravel", "mountain-goat", presets.MOUNTAIN_BIKE, "ebike"}
    twice.discard("ebike")
    for name in presets.EASY_MTB_PRESETS:
        assert presets.weekend_too(name, "weekend", easy_mtb=True)
        assert not presets.weekend_too(name, "weekend")
    for name in (*twice, *presets.EASY_MTB_PRESETS):
        for when in ("weekday_rush", "weekday_offpeak", "night"):
            assert not presets.weekend_too(name, when, easy_mtb=True)
        # Trails off wins: the no-trail graph alone.
        assert not presets.weekend_too(name, "weekend", trails_off=True, easy_mtb=True)
        # The ride's own graph is still what `variant_for_ride` names.
        assert presets.variant_for_ride(name, "weekend", easy_mtb=True) != "weekend"


def test_weekend_ebike_rides_plan_on_the_weekend_graph_too() -> None:
    """The owner, round 3, 2026-11-08, asked whether weekend E-bike, Cargo with assist and
    share e-bike rides should plan twice like the off-road rides: "Yes"."""
    for name, assist in (("ebike", False), ("cargo", True), ("bikeshare", True)):
        assert presets.variant_for_ride(name, "weekend", assist=assist) == Variant.EBIKE.value
        assert presets.weekend_too(name, "weekend", assist=assist)
        for when in ("weekday_rush", "weekday_offpeak", "night"):
            assert not presets.weekend_too(name, when, assist=assist)
        # Trails off wins: the no-trail graph alone.
        assert not presets.weekend_too(name, "weekend", assist=assist, trails_off=True)
    # Without assist, Cargo and a classic share bike take the standard graph's weekend twin.
    assert not presets.weekend_too("cargo", "weekend")
    assert not presets.weekend_too("bikeshare", "weekend")


def test_cargo_assist_is_the_ebike_graph_at_any_time() -> None:
    for when in ("weekend", "weekday_rush", "weekday_offpeak"):
        assert presets.variant_for_ride("cargo", when, assist=True) == Variant.EBIKE.value
    assert presets.variant_for_ride("default", "weekday_rush", assist=True) == "standard"
    assert (
        presets.costing("cargo", assist=True)["bicycle"]["cycling_speed"]
        < options("ebike")["cycling_speed"]
    )


@pytest.mark.parametrize("name", sorted(presets.PRESETS))
@pytest.mark.parametrize("when", ["weekend", "weekday_rush", "weekday_offpeak"])
@pytest.mark.parametrize("assist", [False, True])
def test_trails_off_is_the_no_trail_graph_on_every_ride_type(name, when, assist):
    """OWNER-DECISIONS 463: offered on every type; off-road included, and e-bike rides
    with no lock (463a: "Most ebikes are allowed on multiuse trails")."""
    assert presets.variant_for_ride(name, when, assist, trails_off=True) == Variant.NO_TRAIL.value


@pytest.mark.parametrize("assist", [False, True])
def test_mass_ride_is_on_the_no_trail_graph_with_the_switch_off(assist):
    assert presets.variant_for_ride("mass-ride", "weekend", assist, trails_off=False) == "no-trail"


def test_every_ride_types_brake_grade_is_the_owners_approved_table() -> None:
    """Pinned, unlike the dials above: the owner approved these numbers as a
    table on 2026-09-28 ("Approve the table"), so a retuned value is a change
    to what he approved, not a tuning (mutation review r1, PR7-PR11)."""
    approved = {
        "cargo": 0.03,
        "mass-ride": 0.04,
        "group-ride": 0.05,
        "default": 0.06,
        "trailmaxxing": 0.06,
        "gravel": 0.06,
        "ebike": 0.06,
        # Bikeshare's is the implementation's proposal, not the owner's table: a heavy
        # share bike brakes early (core.presets, "Bikeshare").
        "bikeshare": 0.04,
        # Novice and Nervous: the implementation's proposal too (core.presets, "Novice and
        # Nervous"), a share bike's 4%.
        "novice": 0.04,
        # The transit ride types' bike legs brake as the ride types they are built on
        # (core.presets, "The transit ride types"): Default's and Bikeshare's.
        "bike-transit": 0.06,
        "bikeshare-transit": 0.04,
        # Walk and Walk + 🚆🚌 ride nothing: Bikeshare + 🚶🚆🚌's, never used.
        "walk": 0.04,
        "walk-transit": 0.04,
        # Run is planned on foot (core.run_plan): no descent charged.
        "run": None,
        # Rebalance Ride rides a share bike, as Bikeshare (core.presets, "Rebalance Ride").
        "rebalance": 0.04,
        "mountain-goat": None,
        # Mountain Bike (slice 6): a rider who chose it wants the descent, as Mountain Goat.
        "mountain-bike": None,
        "fast": None,
        # Road Bike (2026-11-02): a road bike descends fast, as Fast's rider does.
        "road-bike": None,
        # Tandem (2026-11-08): the implementation's proposal, a group's 5% (core.presets,
        # "Tandem"): two riders' weight on one set of brakes.
        "tandem": 0.05,
    }
    assert dict(presets.BRAKE_GRADES) == approved
    for name, preset in presets.PRESETS.items():
        assert preset.brake_grade == approved[name], name


@pytest.mark.parametrize(
    ("stress", "use_roads"), [(33, 0.576), (75, 0.05), (5, 0.936), (1, 0.987), (100, 0.0)]
)
def test_use_roads_follows_every_slider_step(stress, use_roads) -> None:
    """Not only at multiples of ten (PR24: rounding to one decimal passed)."""
    assert presets.use_roads_for(stress) == use_roads


@pytest.mark.parametrize(("hills", "use_hills"), [(-33, 0.67), (-95, 0.05), (-5, 0.95), (40, 1.0)])
def test_use_hills_follows_every_slider_step(hills, use_hills) -> None:
    assert presets.use_hills_for(hills) == use_hills


def test_valhallas_default_speeds_are_pinned_by_value() -> None:
    """The speeds a preset with none of its own keeps when the box switches it
    to Road (Valhalla 3.5.1's bicycle defaults, km/h): review r2."""
    assert presets.VALHALLA_DEFAULT_SPEED_KMH == {
        "Road": 25.0,
        "Cross": 20.0,
        "Hybrid": 18.0,
        "Mountain": 16.0,
    }


def test_road_bike_rides_a_road_bicycle_on_its_own_graph_with_fewer_turns() -> None:
    """Stephen, 2026-11-02: Avoid gravel "is intended for road bikes that can't handle gravel or
    dirt"; "Add a road-bike map graph"; "a separate mode that assumes a faster speed and also
    is less tolerant of turns"."""
    road = presets.PRESETS[presets.ROAD_BIKE]
    bicycle = presets.costing(presets.ROAD_BIKE)["bicycle"]
    assert road.variant == Variant.PAVED.value
    assert bicycle["bicycle_type"] == "Road"
    # Valhalla's own Road pace, 15.5 mph, above Default's hybrid 11.2 mph.
    assert "cycling_speed" not in bicycle
    assert presets.VALHALLA_DEFAULT_SPEED_KMH["Road"] > presets.VALHALLA_DEFAULT_SPEED_KMH["Hybrid"]
    # Steeply priced, never the hard exclusion at 1.0 (a ride starting on gravel still plans).
    assert bicycle["avoid_bad_surfaces"] == presets.ROAD_BIKE_SURFACES == 0.9
    assert bicycle["maneuver_penalty"] == presets.HIGH_MANEUVER_PENALTY_S
    assert bicycle["maneuver_penalty"] > options("default")["maneuver_penalty"]
    assert road.stress == presets.ROAD_BIKE_STRESS == 40
    # Its weekend twin at the weekend (the owner, 2026-11-08: "Road bikes absolutely use those
    # parkways on the weekends."; "New weekend graph"), its own graph at every other ride time;
    # trails off is the no-trail graph, at the weekend too.
    assert presets.variant_for_ride(presets.ROAD_BIKE, "weekend") == Variant.PAVED_WEEKEND.value
    for when in ("weekday_rush", "weekday_offpeak", "night"):
        assert presets.variant_for_ride(presets.ROAD_BIKE, when) == Variant.PAVED.value
    assert presets.variant_for_ride(presets.ROAD_BIKE, "weekday_offpeak", trails_off=True) == (
        Variant.NO_TRAIL.value
    )
    assert presets.variant_for_ride(presets.ROAD_BIKE, "weekend", trails_off=True) == (
        Variant.NO_TRAIL.value
    )


def test_the_box_becomes_road_bike_only_on_a_riders_own_bike() -> None:
    assert presets.ROAD_BIKE not in presets.AVOID_GRAVEL_BECOMES
    assert presets.AVOID_GRAVEL_BECOMES <= set(presets.PRESETS)
    kept_types = ("cargo", "ebike", "group-ride", "mass-ride", "bikeshare", "mountain-bike")
    for kept in (*kept_types, "novice", "trailmaxxing"):
        assert kept not in presets.AVOID_GRAVEL_BECOMES
    front = (Path(__file__).resolve().parents[1] / "frontend/src/lib/presets.ts").read_text()
    listed = re.search(r"AVOID_GRAVEL_BECOMES: readonly PresetId\[\] = \[([^\]]*)\]", front)
    assert listed, "the front end's list"
    assert set(re.findall(r'"([a-z-]+)"', listed.group(1))) == set(presets.AVOID_GRAVEL_BECOMES)


class TestTargetDistance:
    """OWNER-DECISIONS 256, 257, 268, 271 (FOLLOWUP-LONG-CALM): at the top of the slider
    the search minimises stress towards a target distance, within a ceiling; there is no
    trail credit."""

    def test_there_is_no_trail_credit(self) -> None:
        """257 supersedes 202: a quiet street counts the same as a trail."""
        assert not hasattr(presets, "TRAIL_CREDIT")
        assert not hasattr(presets, "trail_credit_for")
        for preset in presets.PRESETS.values():
            assert not hasattr(preset, "trail_credit"), preset.name

    def test_only_the_top_of_the_slider_is_maxcalm(self) -> None:
        assert presets.maxcalm_for(presets.STRESS_MAX)
        assert not presets.maxcalm_for(99)
        assert not presets.maxcalm_for(presets.STRESS_TODAYS_TOP)
        assert not presets.maxcalm_for(0)

    def test_the_top_is_where_the_calm_rate_stops_rising(self) -> None:
        assert presets.calm_rate_for(presets.STRESS_MAX) == presets.CALM_RATE_MAX

    def test_only_trailmaxxing_plans_long_trips_leg_by_leg(self) -> None:
        for name, preset in presets.PRESETS.items():
            assert preset.long_calm == (name == "trailmaxxing"), name

    def test_the_default_ceiling_is_1_6_times_the_routers_own_route(self) -> None:
        assert presets.DEFAULT_CEILING_RATIO == 1.6
        assert presets.default_ceiling_m(50_000.0) == pytest.approx(80_000.0)
        assert presets.default_ceiling_m(93_000.0) == pytest.approx(148_800.0)

    def test_a_short_route_has_a_mile_to_spare_at_least(self) -> None:
        # 1.6 x 1 mi is 0.6 mi more: under the floor of a mile more.
        assert presets.default_ceiling_m(1609.344) == pytest.approx(2 * 1609.344)
        assert presets.default_ceiling_m(0.0) == pytest.approx(presets.DEFAULT_CEILING_EXTRA_M)

    def test_the_ceiling_past_a_target_is_1_25_times_it(self) -> None:
        assert presets.TARGET_CEILING_RATIO == 1.25
        assert presets.target_ceiling_m(96_560.0) == pytest.approx(120_700.0)

    def test_the_dials_bounds_are_a_sensible_range(self) -> None:
        assert presets.TARGET_DISTANCE_MIN_M < 1609 < presets.TARGET_DISTANCE_MAX_M
        assert presets.TARGET_DISTANCE_MAX_M >= 200_000  # the longest span a plan may have


class TestNoviceAndNervous:
    """v0.7.0 plan, "Novice and Nervous ride type" (Stephen 2026-10-13: "assume that each road
    is one LTS higher than typical and coordinate there"). It replaces Riding with kids
    (FOLLOWUP-KIDS-PRESET); the plan's defaults are held here: one-level-up pricing, a 1.4x
    detour ceiling, 11.2 mph, hills -60."""

    def test_it_takes_riding_with_kids_place_and_old_names_open_it(self) -> None:
        assert "kids" not in presets.PRESETS
        assert presets.resolve_preset("kids") == presets.NOVICE
        assert presets.resolve_preset("default") == "default"
        assert presets.PRESETS[presets.NOVICE].name == "novice"

    def test_it_rides_the_existing_graphs(self) -> None:
        """Ranking and costing only: no new graph, no map rebuild."""
        assert presets.PRESETS["novice"].variant == Variant.STANDARD.value
        for when in ("weekend", "weekday_rush", "weekday_offpeak"):
            assert presets.variant_for_ride("novice", when) == presets.variant_for_ride(
                "default", when
            )
        assert presets.variant_for_ride("novice", "weekend", trails_off=True) == "no-trail"
        assert presets.PRESETS["novice"].assist_speed_kmh is None
        assert presets.PRESETS["novice"].carrying is None

    def test_every_road_is_priced_one_level_up(self) -> None:
        """Item 2: LTS 1 as 2, 1.5 as 2.5, 2 as 3, 3 as 4, 4 as Avoid, Avoid stays Avoid."""
        exposure = presets.exposure_for("novice")
        assert exposure.shift == 1
        assert (exposure.lts3, exposure.lts4, exposure.avoid) == (1.0, 8.0, 16.0)
        # The LTS 4 hold reads the shifted LTS 4, so it holds real LTS 3 too.
        assert exposure.hold_lts4
        shifted = {
            (tier, half): presets.shifted_tier(tier, half, 1)
            for tier in ("1", "2", "3", "4", "5")
            for half in (False, True)
        }
        assert shifted[("1", False)] == ("2", False)
        assert shifted[("1", True)] == ("2", True)  # 1.5 as 2.5
        assert shifted[("2", False)] == ("3", False)
        assert shifted[("2", True)] == ("3", True)  # 2.5 as 3.5
        assert shifted[("3", False)] == ("4", False)
        assert shifted[("3", True)] == ("4", True)  # 3.5 as 4.5
        assert shifted[("4", False)] == ("5", False)
        assert shifted[("4", True)] == ("5", False)  # 4.5 as Avoid
        assert shifted[("5", False)] == ("5", False)
        assert presets.shifted_tier("unknown", False, 1) == ("unknown", False)
        # So each real level costs what the next level costs on Trailmaxxing.
        weights = exposure.weights
        assert weights[presets.shifted_tier("2", False, 1)[0]] == 1.0
        assert weights[presets.shifted_tier("3", False, 1)[0]] == 8.0
        assert weights[presets.shifted_tier("4", False, 1)[0]] == 16.0

    def test_junction_colours_go_one_step_up(self) -> None:
        assert presets.shifted_severity("orange", 1) == "red"
        assert presets.shifted_severity("red", 1) == "red"
        assert presets.shifted_severity(None, 1) is None
        assert presets.shifted_severity("orange", 0) == "orange"

    def test_shift_stress_moves_metres_up(self) -> None:
        stress = {"1": 100.0, "2": 50.0, "3": 20.0, "4": 5.0, "5": 1.0, "unknown": 7.0}
        assert presets.shift_stress(stress, 1) == {
            "1": 0.0,
            "2": 100.0,
            "3": 50.0,
            "4": 20.0,
            "5": 6.0,
            "unknown": 7.0,
        }
        assert presets.shift_stress(stress, 0) is stress

    def test_short_detours_not_trailmaxxings_long_ones(self) -> None:
        """Item 3: a ceiling of 1.4x the router's own route, where Trailmaxxing has 1.6x."""
        assert presets.PRESETS["novice"].ceiling_ratio == 1.4
        assert presets.PRESETS["trailmaxxing"].ceiling_ratio == presets.DEFAULT_CEILING_RATIO
        assert presets.default_ceiling_m(10_000, "novice") == pytest.approx(14_000)
        assert presets.default_ceiling_m(10_000, "trailmaxxing") == pytest.approx(16_000)
        assert presets.default_ceiling_m(10_000) == pytest.approx(16_000)
        # Never less than a mile more, as on every ride type.
        assert presets.default_ceiling_m(1_000, "novice") == pytest.approx(2_609.344)
        assert not presets.PRESETS["novice"].long_calm

    def test_the_top_of_the_slider(self) -> None:
        assert presets.PRESETS["novice"].stress == presets.STRESS_MAX
        assert presets.maxcalm_for(presets.stress_start("novice"))
        assert options("novice")["use_roads"] == 0.0

    def test_an_adult_beginners_pace_and_gentle_hills(self) -> None:
        """Item 5: Hybrid's 11.2 mph (18 km/h), hills -60 (Cargo's gentle setting)."""
        assert options("novice")["cycling_speed"] == pytest.approx(11.2 * MPH_TO_KMH, abs=0.05)
        assert options("novice")["cycling_speed"] == presets.VALHALLA_DEFAULT_SPEED_KMH["Hybrid"]
        assert presets.PRESETS["novice"].hills == -60
        assert options("novice")["use_hills"] == options("cargo")["use_hills"]
        assert options("novice")["use_living_streets"] == 1.0
        assert options("novice")["bicycle_type"] == "Hybrid"
        assert presets.PRESETS["novice"].hills_seek


class TestMountainBike:
    """docs/MTB-TOPO-PLAN.md, slice 6: "Mountain Goat and Mountain Bike are separate modes"
    (OWNER-DECISIONS 148), with the defaults the owner approved on 2026-10-11."""

    def test_a_ride_type_of_its_own_on_its_own_graph(self) -> None:
        mtb = presets.PRESETS[presets.MOUNTAIN_BIKE]
        assert mtb.variant == Variant.MTB.value
        assert mtb.variant != presets.PRESETS["mountain-goat"].variant
        for when in ("weekend", "weekday_rush", "weekday_offpeak", "night"):
            assert presets.variant_for_ride(presets.MOUNTAIN_BIKE, when) == Variant.MTB.value
        # Trails off is trails off, on this ride type too.
        assert presets.variant_for_ride(presets.MOUNTAIN_BIKE, "weekend", trails_off=True) == (
            Variant.NO_TRAIL.value
        )
        assert presets.MOUNTAIN_BIKE not in presets.OFFROAD_PRESETS

    def test_it_seeks_trails_and_takes_every_surface(self) -> None:
        mtb = presets.PRESETS[presets.MOUNTAIN_BIKE]
        options = mtb.costing_options
        assert options["bicycle_type"] == "Mountain"
        assert options["avoid_bad_surfaces"] == 0.0
        # Stress 80 (the old top): roads priced well over paths, LTS 3 and 4 kept dear.
        assert mtb.stress == presets.STRESS_TODAYS_TOP
        assert options["use_roads"] <= presets.PRESETS["default"].costing_options["use_roads"]
        assert mtb.exposure == presets.EXPOSURE_STRESS_AVERSE

    def test_fine_with_hills(self) -> None:
        mtb = presets.PRESETS[presets.MOUNTAIN_BIKE]
        assert mtb.hills == presets.MTB_HILLS == 50
        assert mtb.hills_seek
        # A rider who chose it wants the descent, as Mountain Goat's.
        assert mtb.brake_grade is None


def test_with_the_every_setting_charge_turns_cost_the_same_at_every_position() -> None:
    # Owner decision 254, "every preset" (the backlog's "fewer turns" item, 2026-11-12).
    # Before: 5 s at Default's 70, where Go plans; after: 15 s (our default, unmeasured) at
    # every position and on every ride type that charged Valhalla's 5 s; 30 s kept.
    # On: the owner's "Every setting", 2026-11-12, after the scorecard's before/after table.
    assert presets.TURN_CHARGE_EVERY_SETTING is True
    for stress in (0, 40, 70, presets.STRESS_TODAYS_TOP, 90, presets.STRESS_MAX):
        got = presets.costing("default", stress)["bicycle"]["maneuver_penalty"]
        assert got == presets.CALM_MANEUVER_PENALTY_S, stress
    for name, preset in presets.PRESETS.items():
        own = preset.costing_options.get("maneuver_penalty", presets.VALHALLA_MANEUVER_PENALTY_S)
        got = presets.costing(name)["bicycle"]["maneuver_penalty"]
        assert got == max(own, presets.CALM_MANEUVER_PENALTY_S), name
    assert (
        presets.costing("tandem", 70)["bicycle"]["maneuver_penalty"]
        == presets.HIGH_MANEUVER_PENALTY_S
    )


def test_above_the_old_top_the_turn_charge_rises_to_the_calm_charge(monkeypatch) -> None:
    # The owner, 2026-11-10, Trolley Trail commute: fewer fiddly turns at the calm end. Before:
    # Valhalla's 5 s at every position; after: 15 s (our default) above 80, a ride type's own
    # higher charge kept; with no position asked for, the ride type's own start decides.

    # The rule as it stands with the every-setting charge off (the test below reads it on).
    monkeypatch.setattr(presets, "TURN_CHARGE_EVERY_SETTING", False)

    def at(name: str, stress: int) -> int:
        return presets.costing(name, stress)["bicycle"]["maneuver_penalty"]

    assert at("default", 70) == presets.VALHALLA_MANEUVER_PENALTY_S
    assert at("default", presets.STRESS_TODAYS_TOP) == presets.VALHALLA_MANEUVER_PENALTY_S
    assert at("default", 90) == presets.CALM_MANEUVER_PENALTY_S
    assert at("trailmaxxing", presets.STRESS_MAX) == presets.CALM_MANEUVER_PENALTY_S
    assert at("tandem", presets.STRESS_MAX) == presets.HIGH_MANEUVER_PENALTY_S
    assert (
        presets.costing("trailmaxxing")["bicycle"]["maneuver_penalty"]
        == presets.CALM_MANEUVER_PENALTY_S
    )
    assert (
        presets.costing("default")["bicycle"]["maneuver_penalty"]
        == presets.VALHALLA_MANEUVER_PENALTY_S
    )
