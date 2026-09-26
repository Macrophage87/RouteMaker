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

# Valhalla's bicycle defaults, stated so that "high" below reads against them.
VALHALLA_MANEUVER_PENALTY_S = 5
VALHALLA_GATE_COST_S = 30
VALHALLA_GATE_PENALTY_S = 300

MID = 0.5
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


@dataclass(frozen=True)
class Preset:
    name: str
    label: str
    variant: str
    costing_options: MappingProxyType = field(repr=False)


def _preset(name: str, label: str, variant: Variant, **options: Any) -> Preset:
    return Preset(
        name=name,
        label=label,
        variant=variant.value,
        costing_options=MappingProxyType({**options, **_NO_STATE_CROSSING_PENALTY}),
    )


PRESETS: MappingProxyType = MappingProxyType(
    {
        preset.name: preset
        for preset in (
            _preset(
                "default",
                "Default",
                Variant.STANDARD,
                bicycle_type="Hybrid",
                use_roads=MID,
                use_hills=MID,
                avoid_bad_surfaces=_SURFACE_AVOIDANCE,
                use_living_streets=_LIVING_STREETS,
                maneuver_penalty=VALHALLA_MANEUVER_PENALTY_S,
                gate_cost=VALHALLA_GATE_COST_S,
                gate_penalty=VALHALLA_GATE_PENALTY_S,
            ),
            _preset(
                "group-ride",
                "Group Ride",
                Variant.STANDARD,
                bicycle_type="Cross",
                use_roads=MID,
                use_hills=MID,
                avoid_bad_surfaces=_SURFACE_AVOIDANCE,
                use_living_streets=_LIVING_STREETS,
                maneuver_penalty=HIGH_MANEUVER_PENALTY_S,
                gate_cost=HIGH_GATE_COST_S,
                gate_penalty=VALHALLA_GATE_PENALTY_S,
            ),
            _preset(
                "mass-ride",
                "Mass Ride",
                Variant.NO_TRAIL,
                bicycle_type="Hybrid",
                use_roads=1.0,
                # "Near zero" rather than zero: zero is Recovery's value, and
                # Mass Ride's grade limit is the layer 4 cap, not this dial.
                use_hills=0.05,
                avoid_bad_surfaces=_SURFACE_AVOIDANCE,
                use_living_streets=_LIVING_STREETS,
                maneuver_penalty=HIGH_MANEUVER_PENALTY_S,
                gate_cost=VALHALLA_GATE_COST_S,
                gate_penalty=VALHALLA_GATE_PENALTY_S,
                cycling_speed=MASS_RIDE_PLANNING_SPEED_KMH,
            ),
        )
    }
)


def costing(name: str) -> dict:
    """The `costing_options` block for one preset, as a fresh copy.

    A copy because a caller that adjusts what it was handed - a future slider,
    a test - must not retune the preset for every later request in the worker.
    Raises KeyError for a name that is not a preset.
    """
    return {"bicycle": copy.deepcopy(dict(PRESETS[name].costing_options))}
