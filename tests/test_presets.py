"""The routing presets the public planner offers, held against PLAN.md's
Routing model table.

Each assertion is a property the plan states about a modality - which variant it
routes on, which dials it raises or lowers relative to Default, that it names its
`bicycle_type` - rather than a pinned number, so a retuned value that still says
what the table says passes and one that contradicts it fails.
"""

from __future__ import annotations

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
    assert options("cargo")["gate_cost"] > options("group-ride")["gate_cost"]
    assert options("cargo")["cycling_speed"] < 18.0
    assert options("cargo")["avoid_bad_surfaces"] > options("default")["avoid_bad_surfaces"]
    assert options("cargo")["bicycle_type"] == "Hybrid"


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


def test_group_ride_raises_the_gate_cost() -> None:
    assert options("group-ride")["gate_cost"] > options("default")["gate_cost"]


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
    """ "L1: e-bike variant. L2: mid use_hills"."""
    assert presets.PRESETS["ebike"].variant == Variant.EBIKE.value
    assert options("ebike")["use_hills"] == 0.5
    assert options("ebike")["cycling_speed"] > 18.0


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


def test_the_weekend_graph_only_twins_the_standard_graph() -> None:
    for name, preset in presets.PRESETS.items():
        weekend = presets.variant_for_ride(name, "weekend")
        weekday = presets.variant_for_ride(name, "weekday_rush")
        assert weekday == preset.variant
        assert weekend == ("weekend" if preset.variant == "standard" else preset.variant)
        assert weekend in settings.VALHALLA_UPSTREAMS


def test_cargo_assist_is_the_ebike_graph_at_any_time() -> None:
    for when in ("weekend", "weekday_rush", "weekday_offpeak"):
        assert presets.variant_for_ride("cargo", when, assist=True) == Variant.EBIKE.value
    assert presets.variant_for_ride("default", "weekday_rush", assist=True) == "standard"
    assert (
        presets.costing("cargo", assist=True)["bicycle"]["cycling_speed"]
        < options("ebike")["cycling_speed"]
    )


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
        "mountain-goat": None,
        "fast": None,
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


def test_avoid_gravel_raises_every_presets_surface_avoidance_and_arms_no_exclusion() -> None:
    """OWNER-DECISIONS 91, 92, 111: any ride type, off by default; at most
    AVOID_GRAVEL_SURFACES, never the hard exclusion at 1.0; a preset already
    avoiding more keeps its own."""
    for name in presets.PRESETS:
        plain = presets.costing(name)["bicycle"]["avoid_bad_surfaces"]
        steered = presets.costing(name, avoid_gravel=True)["bicycle"]["avoid_bad_surfaces"]
        assert steered == max(plain, presets.AVOID_GRAVEL_SURFACES), name
        assert steered < 1.0, name
        assert presets.costing(name, avoid_gravel=False) == presets.costing(name), name


def test_avoid_gravel_rides_as_road_at_the_presets_own_speed() -> None:
    """Review r1, S1: the dial prices only surfaces worse than the type's
    minimum, and Cross admits gravel, Hybrid dirt; so the box rides as Road,
    which admits compacted and better, without changing the ride's speed."""
    for name in presets.PRESETS:
        plain = presets.costing(name)["bicycle"]
        steered = presets.costing(name, avoid_gravel=True)["bicycle"]
        assert steered["bicycle_type"] == "Road", name
        own = plain.get("cycling_speed")
        expected = (
            own if own is not None else presets.VALHALLA_DEFAULT_SPEED_KMH[plain["bicycle_type"]]
        )
        assert steered["cycling_speed"] == expected, name
        for key in set(plain) - {"bicycle_type", "cycling_speed", "avoid_bad_surfaces"}:
            assert steered[key] == plain[key], (name, key)
    assistless = presets.costing("cargo", assist=True, avoid_gravel=True)["bicycle"]
    assert assistless["cycling_speed"] == presets.PRESETS["cargo"].assist_speed_kmh
