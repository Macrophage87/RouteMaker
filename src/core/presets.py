"""The routing presets the public planner offers, and the one place they are defined.

Each preset is a tile variant (layer 1) and a set of per-request bicycle
costing options (layer 2) from PLAN.md's Routing model table. Layers 3 and 4 -
the costing fork, candidate search and ranking - do not exist yet, so what a
preset does today is exactly what is written here, and the view that proxies to
Valhalla reads nothing else.

The stress and hills sliders (PUBLIC-DIALS, owner requests of 2026-09-27)
set `use_roads` and `use_hills` per request; each preset below states where
they start, and the other dials stay the preset's own:

- **Default**: stress 70 (`use_roads` 0.10), the owner's "90" of 2026-09-27 on the
  scale before the rescale of 2026-10-01 (below); hills at the
  middle of the slider. The owner, 2026-09-27: "For hilliness, we can go from
  a default which is basically fastest time for most people in the middle, to
  hill avoidant, and even hill seeking." Mapping that middle to `use_hills` 1.0
  (Valhalla's hills weight off) is an implementation choice.
- **Group Ride**: "L1: standard variant, trails allowed" (its trails toggle ships on; the
  "Keep to roads, not trails" switch, offered on every ride type, turns it off:
  `variant_for_ride`); "L2: Cross,
  mid use_roads, high maneuver_penalty, high gate_cost". Cross rather than
  Hybrid so that the rural references' gravel is cheap rather than merely
  permitted (PLAN, Presets).
- **Mass Ride**: "L1: no-trail variant"; "L2: use_roads at max, use_hills near
  zero, high maneuver_penalty"; Hybrid (PLAN, Presets). Its stress slider is
  locked at 0 (the owner's "Lock at 0 (Recommended)"). Its planning speed is 6 mph, the
  default of the mass ride speed band, so the duration it reports is moving
  time at parade pace rather than at Hybrid's 18 km/h. The no-trail graph also
  has no contraflow (the owner, 2026-10-02: "contraflow lanes are not for group
  rides or mass rides"; `pipeline.variants.close_contraflow`), so a Mass Ride
  never rides a one-way street against its traffic.

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

No preset arms the hard surface exclusion, which only engages when
`avoid_bad_surfaces` is exactly 1.0 (PLAN, Presets).
"""

from __future__ import annotations

import copy
import math
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

# Default's starting position on the stress slider, after the rescale of
# 2026-10-01 (below): 70 is where the old 90 sits. The owner, 2026-09-27:
# "It seems that the current default is probably a bit too traffic tolerant
# for most people. For instance my route to work, would typically be about
# 2 hrs on full trails. Instead it puts me on a set of roads where almost a
# quarter are LTS4." and, of the faster road route, "It is faster, but not
# worth it for most people." Chosen from the trip measurements in
# docs/DEVELOPMENT.md, "The stress and hills sliders". The owner's answer of
# 2026-09-27 to "Keep Default at 75, or 90?": "90" - on the scale of that day.
# `use_roads_for` keeps that route: 70 now plans exactly what 90 did.
DEFAULT_STRESS = 70

# Cargo Bike. The owner, 2026-09-27: "Also another popular option in our city
# would be cargo bikes. People use cargo bikes in our region quite often. They
# tend not to be great on hills. Also have a button to differentiate carrying
# cargo vs carrying children, which have different levels of traffic stress
# tolerance." And later the same day, to be more inclusive: the choice is
# carrying cargo or carrying passengers (OWNER-DECISIONS 241: "Let's also call it
# passengers, as people bring dogs too"; the id stays "people").
# PLAN's Cargo row: "No narrow gaps, gentle grades | L2: high gate_cost, low
# use_hills". Hybrid, as PLAN's Presets list it.
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
# - Stress: carrying cargo starts where Default does (the owner, 2026-09-28:
#   "Same as Default, 90 (Recommended)"); cargo with passengers where the top of the
#   slider was that day, where a tier 3 or 4 way costs several times its
#   length and a path or protected lane wins unless avoiding it takes much
#   longer. That is STRESS_TODAYS_TOP (80) after the rescale, so Cargo Bike
#   plans what it did. It stays there below the new top (the owner,
#   2026-10-02, item 194: Trailmaxxing moves to 100 and cargo with passengers stays
#   at 80); the new top can go many times the straight line.
# - Electric assist (the owner, 2026-09-27: "Cargo bikes with E assist still
#   have problems on hills. They tend to be very heavy. The assist doesn't
#   cancel out the hill in many cases. People with more powerful motors can
#   increase hill tolerance. We want to be more novice friendly."): e-bike
#   legality (the e-bike graph) and a somewhat faster pace, and the same
#   hill-averse start; a rider with a strong motor moves the hills slider.
CARRYING_CARGO = "cargo"
CARRYING_PEOPLE = "people"
# Carrying cargo tracks Default; cargo with passengers is the old top, 80 (item 194).
# The rider-visible name is "Cargo with passengers" (item 241); the id, "people", is the
# one links, saved plans and the API use, so it does not change.
CARGO_CARRYING_STRESS = {CARRYING_CARGO: DEFAULT_STRESS, CARRYING_PEOPLE: 80}
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

# "Legal but avoid" (stress tier 5): the transform gives those roadways
# upstream's alley use, and Valhalla charges `alley_penalty` - this many
# seconds of cost, no time - each time a route enters one from something that
# is not an alley (sif/dynamiccost.h, base_transition_cost). It does not depend
# on use_roads, so it reaches every preset, Mass Ride at the direct end of the
# stress slider included, and the way stays routable when it is the only one.
# This is 1,800 s of cost, not 30 minutes of riding. An edge costs its time
# times a factor of 1 or more (1 + grade + accommodation * roadway stress,
# more on bad surfaces; sif/bicyclecost.cc), so a detour's extra cost is more than its extra time:
# the penalty alone buys under 30 minutes of detour (4.8 km at Mass Ride's
# parade pace, 9 km at Hybrid's 18 km/h, only at a factor of 1), and less the
# hillier or busier the detour. What the router weighs is the penalty plus
# the tier-5 way's own LTS 4 cost against the detour's cost. Only
# tier-5 ways pay it (the owner, 2026-09-27: "Only tier-5 roads"): OSM's own
# alleys are service roads in the graph, and `destination_only_penalty` is not
# sent, so OSM's destination-only and private-for-cars ways pay Valhalla's
# own 600 s exactly as before.
AVOID_ENTRY_PENALTY_S = 1800

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

# The stress slider's rescale (the owner, 2026-10-01, item 163): "I'd actually
# like to see the slider for traffic stress to have a lot more available
# penalty for higher LTS roads. There are times that I want to go for a ride
# and I'm willing to add 10 or 20 miles to my trip just so it's more relaxing.
# Clearly there's times where you'd be willing to handle more stressful roads
# for a shorter trip, but for a relaxing weekend ride where the point is in
# many cases to do miles, a higher distance tradeoff could make sense." and
# item 164: "The 10-20 miles is just an example, but the upper end could be much
# greater than straight line distance, just warn people."
#
# Valhalla's `use_roads` runs 0 to 1 and no further, and at 0 the pinned
# router's stress price on an LTS 3 way is already at its ceiling (about 5 to
# 13 times the way's time, docs/DEVELOPMENT.md, "Graded stress"). So the old
# 0-100 slider hit its top at 90 (`use_roads` 0.10) and the last ten points
# changed almost nothing (measured on the live router, 2026-10-01: Bethesda to
# the Capitol and Falls Church to Union Station plan the same route at 90 and
# 100). The rescale keeps every position's old route and makes room above it:
#
# - 0 to STRESS_DEFAULT_AT (70) is the old 0 to 90, `use_roads` 1.0 to 0.10;
# - 70 to STRESS_TODAYS_TOP (80) is the old 90 to 100, `use_roads` 0.10 to 0;
# - 80 to 100 is new. `use_roads` stays 0 and the calm detour search
#   (`core.routing.calm_search`) takes over, pricing a metre of LTS 3, twice
#   that of LTS 4 and three times that of Avoid at `calm_rate_for` metres of
#   detour, rising exponentially to CALM_RATE_MAX at 100. There is no cap on
#   the detour: a warning (`routemaker.detour`) says how much longer it is.
#
# Turn costs and hill costs are not part of this: they are costing options sent
# at every position, so a relaxed ride is not a zig-zag over a hill.
STRESS_DEFAULT_AT = 70
STRESS_TODAYS_TOP = 80
# The old scale's positions at those two points, which `use_roads` is read at.
_OLD_DEFAULT_POSITION = 90
_OLD_TOP_POSITION = 100

# A PROPOSAL for the owner: how many metres of detour a rider at the top of the
# slider accepts to avoid one metre of LTS 3 (LTS 4 counts twice, Avoid three
# times). 10 is "a mile of busy road is worth ten miles more riding"; at 100 a
# 3 mi LTS 3 corridor is worth a 30 mi detour. And the steepness of the rise:
# each step of 5 points multiplies the rate by about 1.4 near the bottom.
CALM_RATE_MAX = 10.0
CALM_CURVE = 3.0


def use_roads_for(stress: int) -> float:
    """Valhalla's `use_roads` for a slider position (see the rescale above)."""
    if stress <= STRESS_DEFAULT_AT:
        old = stress * _OLD_DEFAULT_POSITION / STRESS_DEFAULT_AT
    elif stress <= STRESS_TODAYS_TOP:
        old = _OLD_DEFAULT_POSITION + (stress - STRESS_DEFAULT_AT)
    else:
        old = _OLD_TOP_POSITION
    return round(1.0 - old / 100, 3)


def calm_rate_for(stress: int) -> float:
    """Metres of detour accepted per metre of LTS 3 avoided at a slider
    position: 0 up to STRESS_TODAYS_TOP, then exponential to CALM_RATE_MAX."""
    if stress <= STRESS_TODAYS_TOP:
        return 0.0
    t = (min(stress, STRESS_MAX) - STRESS_TODAYS_TOP) / (STRESS_MAX - STRESS_TODAYS_TOP)
    return round(CALM_RATE_MAX * math.expm1(CALM_CURVE * t) / math.expm1(CALM_CURVE), 3)


# The target distance (OWNER-DECISIONS 256, 257, 268 and 271, FOLLOWUP-LONG-CALM). At
# the top of the traffic slider the search does not price a metre of busy road at a
# rate of detour any more: it minimises stress, in this order (`core.refine.MAXCALM_STEPS`):
# LTS 4 and Avoid metres plus the red junctions' cost, then LTS 3 metres plus the orange
# junctions' cost, then the distance the Hills slider weighs. There is no trail credit
# (257 supersedes 202: "a quiet street counts the same as a trail").
#
# How far it may go (271: "Change the name from max distance to target distance,
# because it can get longer"):
# - The rider's "Target distance" (the request's `target_distance_m`) is a soft goal:
#   the planner aims at or under it, the miles up to it at half the default's price
#   (`core.refine.WORTH_UP_TO_TARGET`, OWNER-DECISIONS 435), and goes past it only where
#   the extra miles buy enough stress (`core.refine.WORTH_OVER_TARGET`, a stricter bar),
#   and never past TARGET_CEILING_RATIO times it (the hard ceiling). The answer says
#   how far over it is.
# - With no target, the ceiling is DEFAULT_CEILING_RATIO times the router's own route
#   (the use_roads 0 route this ride type plans without a search), and never less than
#   DEFAULT_CEILING_EXTRA_M more than it; inside it each extra mile must buy enough
#   stress (268, `core.refine.WORTH_DEFAULT`).
# These are documented assumptions, tunable (docs/DEVELOPMENT.md, "Long calm trips").
DEFAULT_CEILING_RATIO = 1.6
DEFAULT_CEILING_EXTRA_M = 1609.344
TARGET_CEILING_RATIO = 1.25
# What the API takes for a rider's target distance (metres): 0.6 mi to 620 mi.
TARGET_DISTANCE_MIN_M = 1_000
TARGET_DISTANCE_MAX_M = 1_000_000


def system_weight_for(
    preset_name: str, carrying: str | None = None, chosen: int | None = None
) -> float:
    """The total system weight (kg) the effort model reads (OWNER-DECISIONS 264):
    the rider's, held to the model's range (338: the nearer limit, never refused),
    else Cargo with passengers' own default, else the model's 90."""
    from routemaker import effort

    if chosen is not None:
        return effort.clamp_mass_kg(chosen)
    if carrying_of(preset_name, carrying) == CARRYING_PEOPLE:
        return effort.PASSENGERS_MASS_KG
    return effort.MASS_KG


def maxcalm_for(stress: int) -> bool:
    """Whether a slider position is the top, where the search minimises stress
    towards a target distance instead of pricing busy road at a rate."""
    return calm_rate_for(stress) >= CALM_RATE_MAX


def default_ceiling_m(first_m: float) -> float:
    """The longest a plan may go where the rider set no target, from the length of
    the router's own route (OWNER-DECISIONS 268: the 1.6x stays the ceiling)."""
    return max(first_m * DEFAULT_CEILING_RATIO, first_m + DEFAULT_CEILING_EXTRA_M)


def target_ceiling_m(target_m: float) -> float:
    """The longest a plan may go past a rider's target distance (OWNER-DECISIONS 271):
    TARGET_CEILING_RATIO times it, whatever stress the extra would save."""
    return target_m * TARGET_CEILING_RATIO


# What a metre of each busy tier counts in the calm search's exposure (`core.refine`:
# its score and its Traffic-wins guard), as a preset field (`Preset.exposure`).
#
# OWNER-DECISIONS 250, 2026-10-03: "For trail maxxing, weight LTS4 roads as a much
# higher penalty. It's putting me on dangerous roads just for a little more trails."
# On the stress-averse rides - Trailmaxxing, and Cargo with passengers (item 241: a
# rider who is not in control of the ride is stress-averse) - a metre of LTS 4 is
# eight of LTS 3 and a metre of Avoid sixteen, and the search never takes a route
# with more LTS 4 and Avoid metres than the router's own first route, leg by leg
# and for the whole trip (`hold_lts4`), whatever trail it gains. Every other ride
# keeps 1, 2 and 3 and no such hold.
@dataclass(frozen=True)
class Exposure:
    lts3: float = 1.0
    lts4: float = 2.0
    avoid: float = 3.0
    # Refuse a candidate with more LTS 4 and Avoid metres than the router's first
    # route (each leg's, and the whole trip's).
    hold_lts4: bool = False

    @property
    def weights(self) -> dict[str, float]:
        """By tier, as the segment classes name them."""
        return {"3": self.lts3, "4": self.lts4, "5": self.avoid}


EXPOSURE_STANDARD = Exposure()
EXPOSURE_STRESS_AVERSE = Exposure(lts3=1.0, lts4=8.0, avoid=16.0, hold_lts4=True)


def exposure_for(preset_name: str, carrying: str | None = None) -> Exposure:
    """The exposure weights a plan's search reads: the carrying choice's where
    the preset gives one (`Preset.carrying_exposure`), else the preset's."""
    preset = PRESETS[preset_name]
    chosen = carrying_of(preset_name, carrying)
    if preset.carrying_exposure and chosen in preset.carrying_exposure:
        return preset.carrying_exposure[chosen]
    return preset.exposure


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
    # The grade past which a sustained descent costs (`BRAKE_GRADES`).
    brake_grade: float | None = None
    # Whether a plan far past the calm search's working span is planned leg by leg
    # (`core.refine.refine_long`, OWNER-DECISIONS 256): Trailmaxxing's alone.
    long_calm: bool = False
    # The calm search's exposure weights (`Exposure`, OWNER-DECISIONS 250), and,
    # where a carrying choice has its own, that choice's.
    exposure: Exposure = EXPOSURE_STANDARD
    carrying_exposure: MappingProxyType | None = None


# Where a sustained descent starts to cost, per ride type, on the avoid half
# of the hills slider (routemaker.climbs). The owner, 2026-09-28: "I'd say a
# descent over about 2-3% might actually want to be penalized. There's a point
# where it's a fun downhill and a point where you're riding the breaks." -
# and, asked where it should start, "Depends on ride type" (the option read:
# "Gentler threshold for Cargo (heavy, braking matters most), higher for
# others."). The table below was proposed here and approved by the owner on
# 2026-09-28 ("Approve the table"); None never charges a descent. Below a
# threshold a descent costs nothing, so the gentle ones stay a reward:
# Valhalla already times them faster.
BRAKE_GRADES = MappingProxyType(
    {
        # The owner's 2-3%: a loaded cargo bike brakes hard on any real hill.
        "cargo": 0.03,
        # PLAN's Mass Ride: low grade tolerance, a field that cannot brake as
        # one, and descents over the cap flagged as sharply as climbs.
        "mass-ride": 0.04,
        # A group brakes earlier than a rider alone, to keep together.
        "group-ride": 0.05,
        # Most riders start braking in earnest somewhere past 6%.
        "default": 0.06,
        "trailmaxxing": 0.06,
        "gravel": 0.06,
        "ebike": 0.06,
        # Riders who choose these want the descent.
        "mountain-goat": None,
        "fast": None,
    }
)


def _preset(
    name: str,
    variant: Variant,
    stress: int,
    hills: int,
    hills_seek: bool = True,
    carrying: dict[str, int] | None = None,
    stress_max: int = 100,
    assist_speed_kmh: float | None = None,
    long_calm: bool = False,
    exposure: Exposure = EXPOSURE_STANDARD,
    carrying_exposure: dict[str, Exposure] | None = None,
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
                "alley_penalty": AVOID_ENTRY_PENALTY_S,
                **_NO_STATE_CROSSING_PENALTY,
            }
        ),
        stress=stress,
        hills=hills,
        hills_seek=hills_seek,
        carrying=MappingProxyType(carrying) if carrying else None,
        stress_max=stress_max,
        assist_speed_kmh=assist_speed_kmh,
        brake_grade=BRAKE_GRADES[name],
        long_calm=long_calm,
        exposure=exposure,
        carrying_exposure=MappingProxyType(carrying_exposure) if carrying_exposure else None,
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
                # is the stress slider at its maximum; and 2026-10-02 (item 194,
                # after 187's "Trailmaxxing is about relaxation, not
                # commuting"), the new maximum, STRESS_MAX, where the calm
                # detour search runs at CALM_RATE_MAX. Hills stay the rider's.
                stress=STRESS_MAX,
                hills=0,
                # Items 256, 257 and 271: the least stressful route towards the
                # rider's target distance, however long the trip; no bonus for trail.
                long_calm=True,
                # Item 250: LTS 4 eight times LTS 3, Avoid sixteen, and never more
                # LTS 4 than the router's own route for a little more trail.
                exposure=EXPOSURE_STRESS_AVERSE,
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
                # Where the table puts it: mid use_roads and mid use_hills
                # (50 of the old scale; 40 is within two points of that).
                stress=40,
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
                # "Near zero" rather than zero (PLAN's Mass Ride row), and
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
                stress=40,
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
                stress=40,
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
                # The old 10 was `use_roads` 0.90. On the slider's steps of
                # five, 10 gives 0.871 and 5 gives 0.936: 10 is the nearer
                # (review r1; 8 would give 0.897 but is not a step), and plans
                # a little less directly than before.
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
                # Item 250 for Cargo with passengers; carrying cargo keeps 1, 2, 3.
                carrying_exposure={CARRYING_PEOPLE: EXPOSURE_STRESS_AVERSE},
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


# The presets that ride the off-road graph, where the mountain-bike class is
# open (OWNER-DECISIONS 291(2): "Closed for Default, open for Gravel/Goat").
# The off-road graph has no weekend twin, so these rides stay on it at the
# weekend.
OFFROAD_PRESETS = frozenset({"gravel", "mountain-goat"})


def variant_for_ride(name: str, when: str, assist: bool = False, trails_off: bool = False) -> str:
    """The graph a ride routes on.

    A ride with trails off (the rider's "Keep to roads, not trails" switch,
    offered on every ride type: OWNER-DECISIONS 463, 463b, "Every type,
    roadways ok") takes the no-trail graph, as Mass Ride always does, whatever
    else the ride asks: the other choices below are then moot. An e-bike ride
    (the E-bike ride type, or electric assist) with it on takes the no-trail
    graph too, with no lock (OWNER-DECISIONS 463a, "Most ebikes are allowed on
    multiuse trails"); it keeps the assist pace, and it does not get the e-bike
    graph's bar (`pipeline.variants.bars_electric_bicycle`). With the trails
    gone that bar matters only on a road that bars e-bikes, and the extract of
    2026-10-09 has none: no way in the coverage carries `electric_bicycle=no`
    (docs/DEVELOPMENT.md, "Trails off"). A Gravel or Mountain Goat ride gives
    up the off-road graph's mountain-bike class, whose trails are the ones it
    is turning off. Any trails-off ride may use the Key Bridge and Memorial
    Bridge roadways, which only this graph keeps.

    Electric assist (Cargo Bike) takes the e-bike graph. Gravel and Mountain
    Goat take the off-road graph (`OFFROAD_PRESETS`). A weekend ride on the
    standard graph takes its weekend twin, where roads closed to cars at the
    weekend are off-road paths (`Variant.WEEKEND`); the e-bike and no-trail
    graphs have no weekend twin, so their weekend rides stay on them.
    """
    preset = PRESETS[name]
    if trails_off:
        return Variant.NO_TRAIL.value
    if assist and preset.assist_speed_kmh is not None:
        return Variant.EBIKE.value
    if name in OFFROAD_PRESETS and preset.variant == Variant.STANDARD.value:
        return Variant.OFFROAD.value
    if preset.variant == Variant.STANDARD.value and when == WEEKEND:
        return Variant.WEEKEND.value
    return preset.variant


# "Avoid gravel" (OWNER-DECISIONS 91, 92, 111: "We can have an 'avoid gravel'
# check"; off by default on every ride type, Cargo Bike included - "Cargo tends
# to have pretty wide tires"). Valhalla's `avoid_bad_surfaces` at this value
# prices every surface worse than the bicycle type's own minimum steeply without
# making it impassable, so a ride that starts or ends on gravel is still
# planned, and a preset already avoiding more keeps its own value.
AVOID_GRAVEL_SURFACES = 0.9
# Valhalla's default cycling speed by bicycle type (km/h; Road 15.5 mph,
# Cross 12.4, Hybrid 11.2, Mountain 9.9), which a ride takes when its preset
# names none; kept when the box switches the type to Road.
VALHALLA_DEFAULT_SPEED_KMH = {"Road": 25.0, "Cross": 20.0, "Hybrid": 18.0, "Mountain": 16.0}


def costing(
    name: str,
    stress: int | None = None,
    hills: int | None = None,
    assist: bool = False,
    avoid_gravel: bool = False,
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
    if avoid_gravel:
        options["avoid_bad_surfaces"] = max(options["avoid_bad_surfaces"], AVOID_GRAVEL_SURFACES)
        # The dial prices only surfaces worse than the bicycle type's own
        # minimum, and Cross admits gravel, Hybrid dirt (PLAN, "Every preset
        # states its bicycle_type"), so on those types the box steered off
        # nothing it was asked to (review r1, S1). Road admits compacted and
        # better, so the box rides as Road; the preset's own speed is kept, so
        # the time estimate does not jump to Road's default.
        kind = options.get("bicycle_type", "Hybrid")
        if kind != "Road":
            options.setdefault("cycling_speed", VALHALLA_DEFAULT_SPEED_KMH[kind])
            options["bicycle_type"] = "Road"
    return {"bicycle": options}
