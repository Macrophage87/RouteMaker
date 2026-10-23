"""What a climb costs a rider: its real extra time, plus a steepness penalty past LT1.

The owner, 2026-10-23: "I'm thinking for hill stress to always assume time equivalent, but
the slider should determine a further penalty for steepness. We could have the penalty start
around the max steepness someone can ride an extended period without labored breating (LT1
threshold essentially)"; "Below LT1 you can basically downshift and chill, so it's
essentially the same as a slightly longer flat piece. Above that, fatigue can set in. Above
FTP, fatigue is even higher, so a higher penalty. Let's mainly try to focus on one metric and
extrapolate. Simplicity is better."; "Just do a standard model ... nobody wants to put in 50
parameters"; and "You can use the slider standards for the levels. Maybe 0-15% is a
reasonable range for most people", "More for fast, less for cargo, etc.", "or 1-15, if 0
woild mess with the math"; and of the slider's help: "have the rider estimate the steepest
they can climb for several minutes without any labored breating using their lowest gears. If
they are metric people then say upper end of Zone 2 Power (75% FTP)", "And just leave as is
and adjust if not sure", and "The curve should probably start around 65% of FTP as thats a
casual endurance pace", "Basically start at a small penalty at 65% which grows until FTP,
with a sharp increase after", "Exponential growth curve".

The owner, 2026-10-23: "Just make it clear that while we're using an FTP model, were just
basing it on a comfortable climb grade. It's unlikely that a precise number would change
routing much." FTP is only the shape of the curve; the rider sets one thing.

So the one metric is the rider's LT1 grade, which the hills slider sets (`lt1_grade_for`):
LT1_GRADE_MIN at full avoid to LT1_GRADE_MAX at its far end, in a straight line, so each ride
type's own start on the slider is its standard rider. The rest follows from the effort
model's forces (`routemaker.effort`, Martin et al. 1998) for a standard rider and bike of
effort.MASS_KG, so the penalty is the slider's alone; the request's system weight only sets
how long the climb takes at that power:

- **LT1 power** is what holds V_MIN_MS (a hybrid's lowest gear at an easy cadence) on the LT1
  grade: the top of Zone 2, ZONE2_TOP of FTP. The rider's casual endurance pace is ENDURANCE
  of FTP, and never less than what holds the flat speed on the flat.
- **Time, always.** Over each of the effort model's rising windows (at least 300 m, so a short
  kick averages out as a sprint would) the rider climbs at up to the endurance pace, never
  faster than their flat speed and never slower than V_MIN_MS; at the rider's own weight that
  power is slower or faster, down to walking pace in low gears. The extra seconds over the flat
  cost the same as that many seconds of flat riding.
- **Steepness, past the endurance pace.** Where holding V_MIN_MS takes more, the penalty is
  the window's seconds times (e^(d / FTP_EFOLD) - 1) / (e^((1 - ENDURANCE) / FTP_EFOLD) - 1),
  with d the power needed past the endurance pace as a share of FTP: small just past 65%,
  one second a second at FTP, and growing e-fold with each further FTP_EFOLD of FTP. Where
  riding a window costs more than walking it, it is walked (time only).
- **Past FTP** ("go much more rapidly after FTP"; "with a sharp increase after") the same
  curve keeps growing, 1.8 s a second at 110% and 3.1 at 120%. **Pushing is a last resort**
  (the owner: "if you are having to push a bike up a hill it's going to be a last resort"):
  where riding a window would cost more than pushing it, it is pushed at `push_ms`
  (Tobler's hiking function, slowed for the bike), which costs its time plus WALK_PENALTY
  seconds a second pushed, so a route that needs pushing loses to almost any ridable one,
  and the curve never runs away on a grade far past the rider.
  A critical-power W' balance (Skiba et al. 2012) was tried for past FTP and dropped: the
  exponential curve reaches the same "sharp increase" with one model.

Descents add nothing here (`routemaker.climbs.descent_cost_s` still prices riding the brakes).
Pure: no database, no router.

LT1 is the first ventilatory threshold, the talk-test intensity (Foster and Porcari, ACE,
2010); the owner's 75% of FTP is the top of Coggan's Zone 2 (Allen and Coggan, "Training and
Racing with a Power Meter").
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from functools import lru_cache

from routemaker import climbs, effort

# The LT1 grade (where LT1 power holds V_MIN_MS) at the hills slider's two ends, rise over run.
LT1_GRADE_MIN = 0.01
LT1_GRADE_MAX = 0.15
HILLS_MIN, HILLS_MAX = -100, 100
# LT1 power as a share of FTP: the top of Zone 2 (the owner, 2026-10-23: "upper end of Zone 2
# Power (75% FTP)"); and where the penalty starts, a casual endurance pace ("start around 65%
# of FTP"). The penalty grows e-fold with each FTP_EFOLD of FTP past it ("Exponential growth
# curve"): 0.06 s a second at 70%, 0.24 at 80%, 0.52 at 90%, 1 at FTP, 1.8 at 110%, close to
# the table the owner approved ("That table looks about right": 0.08, 0.33, 0.66, 1, 2.4).
ZONE2_TOP = 0.75
ENDURANCE = 0.65
FTP_EFOLD = 0.20
# The slowest steady climbing speed: a hybrid's lowest gear at an easy cadence, 5 mph; and
# walking a bike up, 2.5 mph.
V_MIN_MS = 8.0 / 3.6
# Pushing a bike up: Tobler's hiking function (Tobler 1993, "Three presentations on
# geographical analysis and modeling", NCGIA 93-1), 6 e^(-3.5 |grade + 0.05|) km/h, times
# PUSH_SHARE for the bike beside you (the owner, 2026-10-23: "pushing a bike up a steep hill
# is still pretty challenging. 2.5 mph is probably fast"): 1.9 mph (3.1 km/h) at 6%, 1.7 mph
# (2.7 km/h) at 10%, 1.4 mph (2.2 km/h) at 15%. WALK_MS is the fastest it gets.
WALK_MS = 4.0 / 3.6
PUSH_SHARE = 0.75
# W', the work a rider can do past critical power (taken as FTP), as seconds of FTP: about
# 17 kJ at 240 W; cyclists in the recovery studies averaged 18 to 23 kJ (Weigend et al.,
# arXiv 2108.04510, 2021). On a climb of t seconds the power-duration curve (Monod and
# Scherrer 1965; Skiba et al. 2012) lets a rider hold FTP x (1 + W_PRIME_S / t), so a short
# climb weighs as the gentler sustained effort it equals: the owner, 2026-09-28, "10% can be
# done for 100m of riding, people would just sprint before it. If continued over
# kilometers, that becomes a hike-a-bike", and 2026-10-23, "more long term stamina than
# short term".
W_PRIME_S = 70.0
# The penalty per second of pushing the bike: as dear as riding at about 125% of FTP, so
# 0.6 mi (1 km) pushed at 10% costs about 1.5 hours more than its time.
WALK_PENALTY = 4.0
# Power reaching the wheel.
DRIVETRAIN = 0.95


def push_ms(grade: float) -> float:
    """Pushing a bike up `grade` (Tobler's hiking function times PUSH_SHARE), m/s, never
    faster than WALK_MS."""
    return min(WALK_MS, PUSH_SHARE * 6.0 / 3.6 * math.exp(-3.5 * abs(grade + 0.05)))


def lt1_grade_for(hills: int) -> float:
    """The LT1 grade at a hills slider position: LT1_GRADE_MIN at full avoid to
    LT1_GRADE_MAX at the far end, in a straight line (8% at the detent)."""
    share = (min(max(hills, HILLS_MIN), HILLS_MAX) - HILLS_MIN) / (HILLS_MAX - HILLS_MIN)
    return LT1_GRADE_MIN + (LT1_GRADE_MAX - LT1_GRADE_MIN) * share


def power_needed_w(grade: float, mass_kg: float, speed_ms: float = V_MIN_MS) -> float:
    """The pedal power that holds `speed_ms` on `grade`: the effort model's rolling, drag
    and climbing forces, through the drivetrain."""
    angle = math.atan(grade)
    force = (
        effort.CRR * mass_kg * effort.GRAVITY * math.cos(angle)
        + 0.5 * effort.AIR_DENSITY * effort.CDA * speed_ms**2
        + mass_kg * effort.GRAVITY * math.sin(angle)
    )
    return force * speed_ms / DRIVETRAIN


def lt1_power_w(lt1_grade: float, mass_kg: float) -> float:
    """The rider's LT1 power, the top of Zone 2: what holds V_MIN_MS on the LT1 grade."""
    return power_needed_w(lt1_grade, mass_kg)


def endurance_power_w(lt1_grade: float, mass_kg: float, flat_ms: float) -> float:
    """The rider's casual endurance pace, ENDURANCE of FTP, where the penalty starts, and never
    less than what holds the flat speed on the flat."""
    pace = lt1_power_w(lt1_grade, mass_kg) * ENDURANCE / ZONE2_TOP
    return max(pace, power_needed_w(0.0, mass_kg, flat_ms))


@lru_cache(maxsize=4096)
def _speed_ms(grade: float, mass_kg: float, power_w: float) -> float:
    """The steady speed `power_w` at the pedals holds on `grade` (bisection: power rises
    with speed)."""
    lo, hi = 0.0, 30.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if power_needed_w(grade, mass_kg, mid) > power_w:
            hi = mid
        else:
            lo = mid
    return lo


def steepness_rate(past: float) -> float:
    """Penalty seconds per second climbed `past` (a share of FTP) beyond the endurance pace:
    exponential, 0 at the pace and 1 at FTP."""
    if past <= 0:
        return 0.0
    return math.expm1(past / FTP_EFOLD) / math.expm1((1.0 - ENDURANCE) / FTP_EFOLD)


def _climb_ms(grade: float, flat_ms: float, lt1_grade: float) -> float:
    """The standard rider's speed up `grade` at the endurance pace, between V_MIN_MS and the
    flat speed."""
    pace = endurance_power_w(lt1_grade, effort.MASS_KG, flat_ms)
    return min(flat_ms, max(_speed_ms(round(grade, 4), effort.MASS_KG, round(pace, 1)), V_MIN_MS))


def window_cost_s(
    run_m: float,
    grade: float,
    mass_kg: float,
    flat_ms: float,
    lt1_grade: float,
    climb_s: float | None = None,
) -> tuple[float, float]:
    """(extra seconds over the flat, steepness penalty seconds) for `run_m` metres at `grade`,
    on a climb that takes `climb_s` seconds in all (None: this window's own time). The
    effort is weighed as the sustained effort it equals over that climb (W_PRIME_S), so a
    short pitch costs little and a long one its full rate.

    The effort, and so the penalty, is the slider's alone: it is worked out for the standard
    rider and bike (effort.MASS_KG) whose LT1 grade the slider sets, at `steepness_rate`. The
    time is the rider's: the same power moves `mass_kg` up the grade, no faster than the flat
    speed and, in a loaded bike's low gears, no slower than pushing it (the owner, 2026-10-23:
    "Weight should only really affect the extra time component, as heavily loaded touring
    bikes tend to have good climbing gears. Penalty is by slider."). Where riding costs more
    than pushing, it is pushed: its time, plus WALK_PENALTY a second, a last resort. The flat
    and downhill cost nothing. The penalty is for choosing routes only, never a shown time
    ("mostly a hidden calculation, less so for the actual time")."""
    if run_m <= 0 or flat_ms <= 0 or grade <= 0:
        return 0.0, 0.0
    push = push_ms(grade)
    std = effort.MASS_KG
    pace = endurance_power_w(lt1_grade, std, flat_ms)
    ftp = lt1_power_w(lt1_grade, std) / ZONE2_TOP
    climb_ms = _climb_ms(grade, flat_ms, lt1_grade)
    need = power_needed_w(grade, std, climb_ms)
    lasting_s = climb_s if climb_s else run_m / climb_ms
    past = (need / (1.0 + W_PRIME_S / lasting_s) - pace) / ftp
    # (A hair over 0 is the speed's bisection, not an overload.)
    penalty_s = run_m / climb_ms * steepness_rate(past) if past > 1e-6 else 0.0
    # The rider's own speed at that power, at their weight.
    mass = effort.clamp_mass_kg(mass_kg)
    ride_ms = climb_ms
    if mass != std:
        ride_ms = min(flat_ms, max(_speed_ms(round(grade, 4), mass, round(need, 1)), push))
    extra_s = run_m / ride_ms - run_m / flat_ms
    push_s = run_m / push
    if push_s - run_m / flat_ms + push_s * WALK_PENALTY < extra_s + penalty_s:
        return push_s - run_m / flat_ms, push_s * WALK_PENALTY
    return extra_s, penalty_s


def profile_cost_s(
    profile: Sequence[tuple[float, float | None]],
    mass_kg: float,
    flat_ms: float,
    hills: int,
) -> tuple[float, float]:
    """A profile's (`core.routing.grade_profile`) climbing time and steepness penalty,
    seconds, over its rising windows (`window_cost_s`), at the LT1 grade the hills slider
    sets. Each window is weighed over the time its whole climb takes."""
    lt1 = lt1_grade_for(hills)
    windows = [(s, e, r) for s, e, r in effort.windows_along(profile) if e > s]
    # Each window's climb: the riding time of the rising windows around it, until the road
    # drops more than climbs.DIP_M below the climb's top or runs two windows without rising
    # (so a few centimetres of elevation noise or a via point do not split one climb
    # into kicks, and a descent or a long flat between two kicks does).
    climb_of: list[float] = [0.0] * len(windows)
    run_start, run_s, below_top, level_m = 0, 0.0, math.inf, 0.0
    for i, (start, end, rise) in enumerate(windows):
        level_m = 0.0 if rise > 0 else level_m + end - start
        if below_top < math.inf:
            below_top = max(0.0, below_top - rise)
        elif rise > 0:
            below_top = 0.0
        if below_top > climbs.DIP_M or level_m > effort.WINDOW_M * 1.5:
            for k in range(run_start, i):
                climb_of[k] = run_s
            run_start, run_s, below_top, level_m = i, 0.0, math.inf, 0.0
        if rise > 0:
            run_s += (end - start) / _climb_ms(rise / (end - start), flat_ms, lt1)
    for k in range(run_start, len(windows)):
        climb_of[k] = run_s
    time_s = penalty_s = 0.0
    for (start, end, rise), climb_s in zip(windows, climb_of, strict=True):
        run = end - start
        t, p = window_cost_s(run, rise / run, mass_kg, flat_ms, lt1, climb_s or None)
        time_s += t
        penalty_s += p
    return time_s, penalty_s


def hill_cost_m(
    profile: Sequence[tuple[float, float | None]],
    mass_kg: float,
    flat_ms: float,
    hills: int,
) -> float:
    """What a profile's climbs cost, in metres of flat riding at `flat_ms`: their extra time
    plus their steepness penalty."""
    time_s, penalty_s = profile_cost_s(profile, mass_kg, flat_ms, hills)
    return (time_s + penalty_s) * flat_ms
