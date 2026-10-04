"""Effort-equivalent distance: how far a route feels, from its elevation profile.

OWNER-DECISIONS 262 and 263 (FOLLOWUP-LONG-CALM). Below the stress levels, a
rider who has moved the Hills slider to avoid climbing wants the route that
costs the least effort, not the one with the least ascent. The effort a rider
spends on a stretch is the work against the forces on the bike, from the
standard cycling power model (Martin, Milliken, Cobb, McCole and Coggan, "Validation
of a mathematical model for road cycling power", Journal of Applied Biomechanics
14, 1998; the same terms as "Bicycle performance" in the Wikipedia article):

    force per metre  F = Crr m g cos(t)  +  1/2 rho CdA v^2  +  m g sin(t)
                         rolling            aerodynamic          climbing

at a steady speed v and a grade whose angle is t. Energy for a stretch is F times
its length, so a stretch's effort is its length times F / F0, where F0 is the force
on the flat. That ratio is the stretch's effort-equivalent distance per metre: 1 on
the flat, about 6.5 at 8% with the constants below.

A descent is floored at the flat cost (F is never taken below F0): it is cheap
but never cheaper than the flat, so it can never offset a climb (item 263). The
grade is taken over windows of WINDOW_M metres, since the elevation samples
(every 30 m) are noisy from one to the next: a 2 m error between neighbours is a
7% grade, and even over 300 m a 2 m error is a 0.7% grade, which at everyday speed
is worth about half again the flat (the flat takes only about 12.7 N, so every
percent of grade adds about 9 N). The comparison between candidate routes carries
the same noise on both, and the floor makes it lean to the cautious side.
Pure: no database, no router.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

# The total system weight, in kilograms: rider, bike and what they carry (item 263:
# "rider + bike ~90 kg"; item 264 makes it the rider's optional input, from about
# 68 kg, a light rider on a UCI-minimum 6.8 kg bike, to about 140 kg, a heavy rider
# on a loaded touring bike). Cargo with passengers defaults heavier: an adult, a
# cargo bike of 30 kg or so and a child or two.
MASS_KG = 90.0
MASS_MIN_KG = 68
MASS_MAX_KG = 140
PASSENGERS_MASS_KG = 120.0
GRAVITY = 9.80665
# Rolling resistance of a hybrid or cross tyre on mixed pavement, from the range
# 0.004 (smooth road) to 0.012 (rough) the power-model literature gives.
CRR = 0.006
# Drag area of an upright rider (m^2): about 0.4 for a hybrid, 0.3 on a road bike
# in the drops (Martin et al. 1998; Wilson, "Bicycling Science").
CDA = 0.40
# Air density at sea level, 15 C (kg/m^3).
AIR_DENSITY = 1.225
# A steady everyday speed (m/s): 20 km/h, 12.4 mph.
SPEED_MS = 20.0 / 3.6
# The profile's grade is read over this many metres at least.
WINDOW_M = 300.0


def flat_force_n(mass_kg: float = MASS_KG) -> float:
    """The force (newtons, which is joules per metre) on the flat at the steady
    speed: rolling resistance scales with the mass, the drag does not."""
    return CRR * mass_kg * GRAVITY + 0.5 * AIR_DENSITY * CDA * SPEED_MS**2


def force_n(grade: float, mass_kg: float = MASS_KG) -> float:
    """The force on a grade (rise over run: 0.08 is 8%): rolling, drag and climbing."""
    angle = math.atan(grade)
    return (
        CRR * mass_kg * GRAVITY * math.cos(angle)
        + 0.5 * AIR_DENSITY * CDA * SPEED_MS**2
        + mass_kg * GRAVITY * math.sin(angle)
    )


def effort_factor(grade: float, mass_kg: float = MASS_KG) -> float:
    """What a metre at this grade is worth, in metres on the flat: the force over the
    flat's, never under 1 (a descent is floored at the flat cost). A heavier system
    pays more for a climb, since the climbing term grows with the mass and the drag
    term does not."""
    return max(force_n(grade, mass_kg) / flat_force_n(mass_kg), 1.0)


def _windows(profile: Sequence[tuple[float, float | None]]) -> list[tuple[float, float]]:
    """The profile as (length, rise) windows of at least WINDOW_M, each from one run
    of samples; a sample with no elevation ends the run (the gap between legs)."""
    out: list[tuple[float, float]] = []
    start: tuple[float, float] | None = None
    last: tuple[float, float] | None = None
    for along, height in profile:
        if height is None:
            if start is not None and last is not None and last[0] > start[0]:
                out.append((last[0] - start[0], last[1] - start[1]))
            start = last = None
            continue
        if start is None:
            start = (along, height)
        last = (along, height)
        if along - start[0] >= WINDOW_M:
            out.append((along - start[0], height - start[1]))
            start = (along, height)
    if start is not None and last is not None and last[0] > start[0]:
        out.append((last[0] - start[0], last[1] - start[1]))
    return out


def effort_equivalent_m(
    profile: Sequence[tuple[float, float | None]],
    length_m: float | None = None,
    mass_kg: float = MASS_KG,
) -> float | None:
    """The effort-equivalent distance of a route, in metres, from its elevation
    profile ((metres along, elevation or None), `routing.grade_profile`), or None
    where there is no profile to read. Where the profile covers less of the route
    than `length_m` (a leg with no samples), the rest counts as flat."""
    windows = _windows(profile)
    if not windows:
        return None
    total = covered = 0.0
    for run, rise in windows:
        covered += run
        total += run * effort_factor(rise / run, mass_kg)
    if length_m is not None and length_m > covered:
        total += length_m - covered
    return total
