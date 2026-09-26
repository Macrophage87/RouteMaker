"""The routing presets the public planner offers, held against PLAN.md's
Routing model table.

Each assertion is a property the plan states about a modality - which variant it
routes on, which dials it raises or lowers relative to Default, that it names its
`bicycle_type` - rather than a pinned number, so a retuned value that still says
what the table says passes and one that contradicts it fails.
"""

from __future__ import annotations

import pytest
from django.conf import settings

from core import presets
from pipeline.variants import Variant

CONTRACT_PRESETS = {"default", "group-ride", "mass-ride"}

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


def test_default_sits_mid_scale_on_roads_and_hills() -> None:
    assert 0.25 < options("default")["use_roads"] < 0.75
    assert 0.25 < options("default")["use_hills"] < 0.75


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
        presets.costing("trailmaxxing")
