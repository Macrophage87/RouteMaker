"""The routing presets the public planner offers, and the one place they are defined.

Each preset is a tile variant (layer 1) and a set of per-request bicycle
costing options (layer 2) from PLAN.md's Routing model table. Layers 3 and 4 -
the costing fork, candidate search and ranking - do not exist yet, so what a
preset does today is exactly what is written here, and the view that proxies to
Valhalla reads nothing else.

What the table says, and how each value below follows from it:

- **Default**: "L2: Hybrid, mid use_roads, mid use_hills". Mid is the middle of
  Valhalla's 0..1 scale, 0.5.
- **Group Ride**: "L1: standard variant, trails allowed" (its "Allow bike paths
  and trails" toggle ships on, and the toggle is not offered yet); "L2: Cross,
  mid use_roads, high maneuver_penalty, high gate_cost". Cross rather than
  Hybrid so that the rural references' gravel is cheap rather than merely
  permitted (PLAN, Presets).
- **Mass Ride**: "L1: no-trail variant"; "L2: use_roads at max, use_hills near
  zero, high maneuver_penalty"; Hybrid (PLAN, Presets: "Mass Ride, Fast,
  Beginner, Recovery, and Cargo are Hybrid"). Its planning speed is 6 mph, the
  default of the mass ride speed band, so the duration it reports is moving
  time at parade pace rather than at Hybrid's 18 km/h.

The plan names no numbers for "high". The figures here are the first
calibration, stated so that they can be argued with: Valhalla's own bicycle
defaults are 5 s per maneuver and 30 s per gate, and "high" is taken as a
maneuver priced at half a minute and a gate at two, which is enough to buy a
few hundred metres of extra distance to avoid a turn or a gate on a city route
without letting either dominate a rural one. The reference-route invariants in
the Quality bar are what retune them.

Every dial is stated on every preset ("Every dial exists on every preset"), so
nothing is left to whatever the pinned Valhalla release defaults to. In
particular both state-crossing options are sent as zero: the owner decision
under "State crossing penalty" is that the router does not avoid state lines
for any modality, and Valhalla's default of 600 s would otherwise apply at
every border control node the pipeline inserts.

None of the three arms the hard surface exclusion, which only engages when
`avoid_bad_surfaces` is exactly 1.0 (PLAN, Presets).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from pipeline.variants import Variant
from routemaker.ridetime import WEEKEND

# Valhalla's bicycle defaults, stated so that "high" below reads against them.
VALHALLA_MANEUVER_PENALTY_S = 5
VALHALLA_GATE_COST_S = 30
VALHALLA_GATE_PENALTY_S = 300

MID = 0.5

# Default's starting position on the stress slider. The owner, 2026-09-27:
# "It seems that the current default is probably a bit too traffic tolerant
# for most people. For instance my route to work, would typically be about
# 2 hrs on full trails. Instead it puts me on a set of roads where almost a
# quarter are LTS4." and, of the faster road route, "It is faster, but not
# worth it for most people." Chosen from the trip measurements in
# docs/DEVELOPMENT.md, "The stress and hills sliders". The owner's answer of
# 2026-09-27 to "Keep Default at 75, or 90?": "90".
DEFAULT_STRESS = 90

# Cargo Bike. The owner, 2026-09-27: "Also another popular option in our city
# would be cargo bikes. People use cargo bikes in our region quite often. They
# tend not to be great on hills. Also have a button to differentiate carrying
# cargo vs carrying children, which have different levels of traffic stress
# tolerance." And later the same day, to be more inclusive: the choice is
# carrying cargo or carrying people. PLAN's Cargo row: "No narrow gaps, gentle
# grades | L2: high gate_cost, low use_hills". Hybrid, as PLAN's Presets list it.
#
# - Hills: well toward avoid (`use_hills` 0.4).
# - Speed: 14 km/h (8.7 mph), a loaded cargo bike's cruising pace unassisted,
#   against Hybrid's 18; it only changes the times shown and the time-based
#   cost, not which ways are allowed.
# - Narrow gaps: the transform already turns cycle barriers, and bollards
#   whose tagged gap is under 1.5 m, into gates (`NARROW_GAP_M`,
#   lua/routemaker_remap.lua), so a gate cost of five minutes and a penalty of
#   ten keep a cargo route out of them unless there is no other way. Steps are
#   already priced out for every bicycle by Valhalla (1 km/h and its steps
#   factor), and stiles and kissing gates are barriers upstream closes to
#   bicycles.
# - Surface: rough and unpaved weigh more (0.6, still below the 1.0 at which the
#   hard exclusion arms, so a gravel link is dear rather than impossible).
# - Stress: carrying cargo starts at a moderate 75; carrying people at the top
#   of the slider, where a tier 3 or 4 way costs about five times its length
#   and a path or protected lane wins unless there is no other way.
# - Electric assist (the owner, 2026-09-27: "Cargo bikes with E assist still
#   have problems on hills. They tend to be very heavy. The assist doesn't
#   cancel out the hill in many cases. People with more powerful motors can
#   increase hill tolerance. We want to be more novice friendly."): e-bike
#   legality (the e-bike graph) and a somewhat faster pace, and the same
#   hill-averse start; a rider with a strong motor moves the hills slider.
CARRYING_CARGO = "cargo"
CARRYING_PEOPLE = "people"
# Carrying cargo is moderate (the owner's words: "cargo = moderate"), and
# carrying people is the top of the slider, "unless there's no other option".
CARGO_CARRYING_STRESS = {CARRYING_CARGO: 75, CARRYING_PEOPLE: 100}
CARGO_HILLS = -60
CARGO_PLANNING_SPEED_KMH = 14.0
CARGO_GATE_COST_S = 300
CARGO_GATE_PENALTY_S = 600
CARGO_SURFACE_AVOIDANCE = 0.6
CARGO_ASSIST_PLANNING_SPEED_KMH = 18.0

# The rest of PLAN's table (the owner, 2026-09-27: "Add the other presets too,
# like trailmaxxing"), each at layers 1 and 2 only. What a preset's row gives
# layer 4 is not built, and its card says what it does today.
LOW_SURFACE_AVOIDANCE = 0.1
HIGH_SURFACE_AVOIDANCE = 0.75
# An e-bike's cruising speed with assist, 15 mph: the US class 1 and 2 limit is
# 20 mph, and a rider in town cruises well under it.
EBIKE_PLANNING_SPEED_KMH = 24.0
HIGH_MANEUVER_PENALTY_S = 30
HIGH_GATE_COST_S = 120

# The mass ride speed band's default planning speed, 6 mph, in Valhalla's km/h.
MASS_RIDE_PLANNING_SPEED_KMH = round(6 * 1.609344, 1)

# Off everywhere, meaning sent as zero (owner decision, State crossing penalty).
_NO_STATE_CROSSING_PENALTY = {"country_crossing_cost": 0, "country_crossing_penalty": 0}

# Valhalla's own default, and well below the 1.0 at which the surface exclusion
# arms, so surface is a cost multiplier rather than a gate on all three.
_SURFACE_AVOIDANCE = 0.25
_LIVING_STREETS = MID


# --- The two sliders ------------------------------------------------------
#
# The owner, 2026-09-27: "lets have sliders where we can adjust the penalties
# for traffic stress and hilliness. The lowest setting for traffic stress is
# fastest legal route to basically one where low stress routes are used unless
# there's no other option. For hilliness, we can go from a default which is
# basically fastest time for most people in the middle, to hill avoidant, and
# even hill seeking." PLAN:86, "Every dial exists on every preset": a preset
# sets where each slider starts, and the rider may move it on any preset.
#
# Stress, 0 to 100, is `use_roads` run backwards: 0 is `use_roads` 1.0 and
# 100 is 0.0. Valhalla prices every edge at its time times
# `1 + grade + accommodation * roadway stress`; at `use_roads` 1.0 the
# roadway and accommodation terms are at their smallest and the graph's stress
# penalty (`use_sidepath` on LTS 3-4 ways, lua/routemaker_remap.lua) weighs
# `3 * (1 - use_roads)`, nothing; at 0.0 it weighs 3 on top of a doubled road
# factor. The graph carries the tiers and the request carries the weight, so
# one graph serves every position.
#
# Hills, -100 to 100, with its detent at 0. Below 0 it is `use_hills`, 1.0 at
# the detent and 0.0 at -100. `use_hills` 1.0 adds no grade penalty at all, so
# an edge costs its time as Valhalla's grade-speed model has it - the owner's
# "fastest time for most people". Above 0 Valhalla has nothing to offer
# (`use_hills` stops at indifferent), and the request becomes a climb search
# among the router's alternatives (`core.routing`) within the distance budget
# the dial sets (`seek_distance_ratio`).
STRESS_MIN, STRESS_MAX = 0, 100
HILLS_MIN, HILLS_MAX = -100, 100


def use_roads_for(stress: int) -> float:
    return round(1.0 - stress / 100, 3)


def use_hills_for(hills: int) -> float:
    return round(1.0 + min(hills, 0) / 100, 3)


def seek_distance_ratio(hills: int) -> float:
    """How much longer than the direct route a climb search may go: up to half again."""
    return 1.0 + 0.5 * max(hills, 0) / 100


@dataclass(frozen=True)
class Preset:
    name: str
    variant: str
    costing_options: MappingProxyType = field(repr=False)
    # Where the two sliders start on this preset.
    stress: int = 50
    hills: int = 0
    # Whether the hills slider may go past its detent. Not on Mass Ride: PLAN,
    # "On Mass Ride the seek half is disabled with the speed-band explanation".
    hills_seek: bool = True
    # What the bike carries, where the preset asks (Cargo Bike): each choice
    # and the stress slider's start it gives. The first is the default.
    carrying: MappingProxyType | None = None
    # The highest the stress slider may go on this preset. Mass Ride's is 0:
    # the owner's "Lock at 0 (Recommended)" of 2026-09-27, since a field that
    # takes the roadway has no business being steered onto quiet side streets.
    stress_max: int = 100
    # With the rider's electric-assist toggle (Cargo Bike): the variant and
    # the planning speed it gives, or None where the toggle is not offered.
    assist_speed_kmh: float | None = None


def _preset(
    name: str,
    variant: Variant,
    stress: int,
    hills: int,
    hills_seek: bool = True,
    carrying: dict[str, int] | None = None,
    stress_max: int = 100,
    assist_speed_kmh: float | None = None,
    **options: Any,
) -> Preset:
    return Preset(
        name=name,
        variant=variant.value,
        costing_options=MappingProxyType(
            {
                **options,
                "use_roads": use_roads_for(stress),
                "use_hills": use_hills_for(hills),
                **_NO_STATE_CROSSING_PENALTY,
            }
        ),
        stress=stress,
        hills=hills,
        hills_seek=hills_seek,
        carrying=MappingProxyType(carrying) if carrying else None,
        stress_max=stress_max,
        assist_speed_kmh=assist_speed_kmh,
    )


PRESETS: MappingProxyType = MappingProxyType(
    {
        preset.name: preset
        for preset in (
            _preset(
                "default",
                Variant.STANDARD,
                stress=DEFAULT_STRESS,
                hills=0,
                bicycle_type="Hybrid",
                avoid_bad_surfaces=_SURFACE_AVOIDANCE,
                use_living_streets=_LIVING_STREETS,
                maneuver_penalty=VALHALLA_MANEUVER_PENALTY_S,
                gate_cost=VALHALLA_GATE_COST_S,
                gate_penalty=VALHALLA_GATE_PENALTY_S,
            ),
            _preset(
                "trailmaxxing",
                Variant.STANDARD,
                # "Lowest stress ride, directness secondary": use_roads near
                # zero, living streets on, low surface avoidance, Cross. The
                # owner, 2026-09-27, dropping Beginner and Recovery: Trailmaxxing
                # is the stress slider at its maximum; hills stay the rider's.
                stress=STRESS_MAX,
                hills=0,
                bicycle_type="Cross",
                avoid_bad_surfaces=LOW_SURFACE_AVOIDANCE,
                use_living_streets=1.0,
                maneuver_penalty=VALHALLA_MANEUVER_PENALTY_S,
                gate_cost=VALHALLA_GATE_COST_S,
                gate_penalty=VALHALLA_GATE_PENALTY_S,
            ),
            _preset(
                "group-ride",
                Variant.STANDARD,
                # Where the table puts it: mid use_roads and mid use_hills.
                stress=50,
                hills=-50,
                bicycle_type="Cross",
                avoid_bad_surfaces=_SURFACE_AVOIDANCE,
                use_living_streets=_LIVING_STREETS,
                maneuver_penalty=HIGH_MANEUVER_PENALTY_S,
                gate_cost=HIGH_GATE_COST_S,
                gate_penalty=VALHALLA_GATE_PENALTY_S,
            ),
            _preset(
                "mass-ride",
                Variant.NO_TRAIL,
                # use_roads at max: the direct end of the stress slider.
                stress=0,
                # "Near zero" rather than zero: zero is Recovery's value, and
                # Mass Ride's grade limit is the layer 4 cap, not this dial.
                hills=-95,
                hills_seek=False,
                stress_max=0,
                bicycle_type="Hybrid",
                avoid_bad_surfaces=_SURFACE_AVOIDANCE,
                use_living_streets=_LIVING_STREETS,
                maneuver_penalty=HIGH_MANEUVER_PENALTY_S,
                gate_cost=VALHALLA_GATE_COST_S,
                gate_penalty=VALHALLA_GATE_PENALTY_S,
                cycling_speed=MASS_RIDE_PLANNING_SPEED_KMH,
            ),
            _preset(
                "mountain-goat",
                Variant.STANDARD,
                # "The hills dial at seek with everything else permissive":
                # the hills slider starts at its top, which is today's climb
                # search among the router's alternatives (core.routing), not
                # the via-point search the table's L4 describes.
                stress=50,
                hills=HILLS_MAX,
                bicycle_type="Cross",
                avoid_bad_surfaces=LOW_SURFACE_AVOIDANCE,
                use_living_streets=_LIVING_STREETS,
                maneuver_penalty=VALHALLA_MANEUVER_PENALTY_S,
                gate_cost=VALHALLA_GATE_COST_S,
                gate_penalty=VALHALLA_GATE_PENALTY_S,
            ),
            _preset(
                "gravel",
                Variant.STANDARD,
                # "L2: Cross or Mountain, avoid_bad_surfaces zero". Unpaved-share
                # ranking is layer 4 and not built.
                stress=50,
                hills=0,
                bicycle_type="Cross",
                avoid_bad_surfaces=0.0,
                use_living_streets=_LIVING_STREETS,
                maneuver_penalty=VALHALLA_MANEUVER_PENALTY_S,
                gate_cost=VALHALLA_GATE_COST_S,
                gate_penalty=VALHALLA_GATE_PENALTY_S,
            ),
            _preset(
                "fast",
                Variant.STANDARD,
                # "Few stops, few turns, smooth pavement | L2: high use_roads,
                # high maneuver_penalty, high surface avoidance" - high, and
                # still below the 1.0 at which the surface exclusion arms.
                stress=10,
                hills=0,
                bicycle_type="Hybrid",
                avoid_bad_surfaces=HIGH_SURFACE_AVOIDANCE,
                use_living_streets=0.2,
                maneuver_penalty=HIGH_MANEUVER_PENALTY_S,
                gate_cost=VALHALLA_GATE_COST_S,
                gate_penalty=VALHALLA_GATE_PENALTY_S,
            ),
            _preset(
                "cargo",
                Variant.STANDARD,
                stress=CARGO_CARRYING_STRESS[CARRYING_CARGO],
                hills=CARGO_HILLS,
                carrying=CARGO_CARRYING_STRESS,
                assist_speed_kmh=CARGO_ASSIST_PLANNING_SPEED_KMH,
                bicycle_type="Hybrid",
                avoid_bad_surfaces=CARGO_SURFACE_AVOIDANCE,
                use_living_streets=_LIVING_STREETS,
                maneuver_penalty=VALHALLA_MANEUVER_PENALTY_S,
                gate_cost=CARGO_GATE_COST_S,
                gate_penalty=CARGO_GATE_PENALTY_S,
                cycling_speed=CARGO_PLANNING_SPEED_KMH,
            ),
            _preset(
                "ebike",
                Variant.EBIKE,
                # "Grade matters less, path legality matters more | L1: e-bike
                # variant. L2: mid use_hills". The variant bars the ways tagged
                # electric_bicycle=no; nothing here asserts any legality.
                stress=DEFAULT_STRESS,
                hills=-50,
                bicycle_type="Hybrid",
                avoid_bad_surfaces=_SURFACE_AVOIDANCE,
                use_living_streets=_LIVING_STREETS,
                maneuver_penalty=VALHALLA_MANEUVER_PENALTY_S,
                gate_cost=VALHALLA_GATE_COST_S,
                gate_penalty=VALHALLA_GATE_PENALTY_S,
                cycling_speed=EBIKE_PLANNING_SPEED_KMH,
            ),
        )
    }
)


def stress_start(name: str, carrying: str | None = None) -> int:
    """Where the stress slider starts on a preset, for what the bike carries."""
    preset = PRESETS[name]
    if preset.carrying is None:
        return preset.stress
    return preset.carrying[carrying or next(iter(preset.carrying))]


def carrying_of(name: str, carrying: str | None = None) -> str | None:
    """The carrying choice in force: the rider's, the preset's first, or none."""
    preset = PRESETS[name]
    if preset.carrying is None:
        return None
    return carrying or next(iter(preset.carrying))


def variant_for_ride(name: str, when: str, assist: bool = False) -> str:
    """The graph a ride routes on.

    Electric assist (Cargo Bike) takes the e-bike graph. A weekend ride on the
    standard graph takes its weekend twin, where roads closed to cars at the
    weekend are off-road paths (`Variant.WEEKEND`); the e-bike and no-trail
    graphs have no weekend twin, so their weekend rides stay on them.
    """
    preset = PRESETS[name]
    if assist and preset.assist_speed_kmh is not None:
        return Variant.EBIKE.value
    if preset.variant == Variant.STANDARD.value and when == WEEKEND:
        return Variant.WEEKEND.value
    return preset.variant


def costing(
    name: str, stress: int | None = None, hills: int | None = None, assist: bool = False
) -> dict:
    """The `costing_options` block for one preset, as a fresh copy.

    `stress` and `hills` are the sliders' positions; either left out is the
    preset's own. A copy because a caller that adjusts what it was handed must
    not retune the preset for every later request in the worker. Raises
    KeyError for a name that is not a preset.
    """
    options = copy.deepcopy(dict(PRESETS[name].costing_options))
    if stress is not None:
        options["use_roads"] = use_roads_for(stress)
    if hills is not None:
        options["use_hills"] = use_hills_for(hills)
    speed = PRESETS[name].assist_speed_kmh
    if assist and speed is not None:
        options["cycling_speed"] = speed
    return {"bicycle": options}
