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
  power is slower or faster, down to walking pace in low gears, and never faster up a steeper
  grade than a gentler one. The extra seconds over the flat cost the same as that many seconds
  of flat riding.
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
- **Steeper never costs less** (routing hunt 4, T4-1): for the same rise, a steeper window
  costs at least what that rise costs at any gentler grade on the same climb; the shortfall
  is added to the penalty (`window_cost_s`, `_rise_floor`).
  A critical-power W' balance (Skiba et al. 2012) was tried for past FTP and dropped: the
  exponential curve reaches the same "sharp increase" with one model.

**Electric assist** (the owner's Bikeshare e-bike start, `core.presets`: "the motor takes the
climb"). An assisted ride's flat speed is the motor's pace, not the rider's, so timing its
climbs at the rider's own power and taking the time at that faster flat speed off priced an
e-bike's climb dearer than a plain bike's (hunt finding E2, 2026-11-08). With `assist_w` the
climb is ridden at the rider's power plus ASSIST_W from the motor, never slower than without
it and never faster than the flat speed, so the motor takes most of the extra time. The
steepness penalty is still the slider's alone, worked out for the standard rider as before:
an e-bike's slider start (E-bike 50, Bikeshare e-bike -20) says how much a long steep grade
still counts (the battery and the rider's nerve).

Descents add nothing here (`routemaker.climbs.descent_cost_s` still prices riding the brakes).
Pure: no database, no router.

LT1 is the first ventilatory threshold, the talk-test intensity (Foster and Porcari, ACE,
2010); the owner's 75% of FTP is the top of Coggan's Zone 2 (Allen and Coggan, "Training and
Racing with a Power Meter").
"""

from __future__ import annotations

import math
import threading
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
# An electric assist's steady help up a climb, watts at the wheel's side of the pedals: the
# 250 W continuous rating of an EU pedelec, about what a US class 1 or 2 mid-drive or a share
# e-bike's hub motor holds up a long grade (their 500 to 750 W peaks do not last a climb).
ASSIST_W = 250.0


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


# The step of grade a rider other than the standard one is timed at (`_ride_ms`): 0.1%.
GRADE_STEP = 0.001
_ride_lock = threading.Lock()


def _own_speed_ms(grade: float, mass: float, flat_ms: float, lt1_grade: float) -> float:
    """A rider of `mass` up `grade`, at the power the standard rider puts out there, no
    faster than the flat speed and no slower than pushing."""
    climb_ms = _climb_ms(grade, flat_ms, lt1_grade)
    need = power_needed_w(grade, effort.MASS_KG, climb_ms)
    return min(flat_ms, max(_speed_ms(round(grade, 4), mass, round(need, 1)), push_ms(grade)))


@lru_cache(maxsize=256)
def _ride_floor(mass: float, flat_ms: float, lt1_grade: float) -> list[float]:
    """`_ride_ms`'s speeds for one rider, by GRADE_STEP, filled as far as asked."""
    return []


def _ride_ms(steps: int, mass: float, flat_ms: float, lt1_grade: float) -> float:
    """A rider of `mass` up `steps` GRADE_STEPs of grade: the slowest of `_own_speed_ms` at
    this grade and every step below it. Where the standard rider is held at V_MIN_MS, the power
    it puts out rises with the grade, and a lighter rider at that power would climb a steeper
    grade faster (a heavier one, near the hold, too); a steeper climb never costs less."""
    floor = _ride_floor(mass, flat_ms, lt1_grade)
    with _ride_lock:
        while len(floor) <= steps:
            own = _own_speed_ms(len(floor) * GRADE_STEP, mass, flat_ms, lt1_grade)
            floor.append(min(own, floor[-1]) if floor else own)
        return floor[steps]


def _ridden_s(
    run_m: float,
    grade: float,
    mass: float,
    flat_ms: float,
    lt1_grade: float,
    lasting_s: float,
    assist_w: float,
) -> tuple[float, float]:
    """(extra seconds, penalty seconds) for riding `run_m` metres at `grade`, weighed over a
    climb of `lasting_s` seconds, for a rider of `mass` (clamped). Linear in `run_m`."""
    std = effort.MASS_KG
    pace = endurance_power_w(lt1_grade, std, flat_ms)
    ftp = lt1_power_w(lt1_grade, std) / ZONE2_TOP
    climb_ms = _climb_ms(grade, flat_ms, lt1_grade)
    need = power_needed_w(grade, std, climb_ms)
    past = (need / (1.0 + W_PRIME_S / lasting_s) - pace) / ftp
    # (A hair over 0 is the speed's bisection, not an overload.)
    penalty_s = run_m / climb_ms * steepness_rate(past) if past > 1e-6 else 0.0
    # The rider's own speed at that power, at their weight, never faster up this grade than
    # up a gentler one (`_ride_ms`).
    ride_ms = climb_ms
    if mass != std:
        ride_ms = _ride_ms(math.floor(round(grade / GRADE_STEP, 6)), mass, flat_ms, lt1_grade)
    if assist_w > 0:
        # The motor's watts beside the rider's: the rider's power up this grade is the
        # standard rider's (`need`), the bike's speed what both hold at the rider's weight.
        assisted_ms = _speed_ms(round(grade, 4), mass, round(need + assist_w, 1))
        ride_ms = min(flat_ms, max(ride_ms, assisted_ms))
    return run_m / ride_ms - run_m / flat_ms, penalty_s


def _pushed_s(run_m: float, grade: float, flat_ms: float) -> tuple[float, float]:
    """(extra seconds, penalty seconds) for pushing `run_m` metres up `grade`: its time, plus
    WALK_PENALTY a second."""
    push_s = run_m / push_ms(grade)
    return push_s - run_m / flat_ms, push_s * WALK_PENALTY


def _ridden_or_pushed_s(
    run_m: float,
    grade: float,
    mass: float,
    flat_ms: float,
    lt1_grade: float,
    lasting_s: float,
    assist_w: float,
) -> tuple[float, float]:
    """`window_cost_s` before its floor (`_rise_floor`): ridden, or pushed where riding
    would cost more."""
    ridden = _ridden_s(run_m, grade, mass, flat_ms, lt1_grade, lasting_s, assist_w)
    pushed = _pushed_s(run_m, grade, flat_ms)
    return pushed if sum(pushed) < sum(ridden) else ridden


def _top_up(floor_s: float, cost_s: float) -> float:
    """What brings `cost_s` up to `floor_s` (a rounding hair over it is not a top-up)."""
    return floor_s - cost_s if floor_s > cost_s * (1.0 + 1e-9) + 1e-9 else 0.0


# The floor's climbs (`_rise_floor`) are sized by their rise, rounded up to a step of
# RISE_BUCKET (1%) in a geometric series, so that the floor's tables are shared between
# climbs of nearly the same height. Claude's default, not measured: rounding up only makes a
# gentler grade's climb last a little longer, so the floor is never under the true cost.
RISE_BUCKET = 0.01
_rise_lock = threading.Lock()


@lru_cache(maxsize=1024)
def _rise_table(flat_ms: float, lt1_grade: float, bucket: float) -> list[float]:
    """`_rise_floor`'s costs per metre of rise for the standard rider at one flat speed,
    LT1 grade and climb, by GRADE_STEP, filled as far as asked."""
    return []


def _rise_floor(steps: int, flat_ms: float, lt1_grade: float, bucket: float) -> float:
    """The most a metre of rise costs the standard rider without assist (time plus penalty,
    ridden or pushed) at any grade from one GRADE_STEP up to `steps` of them, on a climb of
    `RISE_BUCKET`-step `bucket` (its rise is (1 + RISE_BUCKET) ** bucket metres; math.inf: a
    climb long enough that W' adds nothing) climbed at that grade."""
    table = _rise_table(flat_ms, lt1_grade, bucket)
    with _rise_lock:
        while len(table) <= steps:
            k = len(table)
            if k == 0:
                table.append(0.0)
                continue
            gentler = k * GRADE_STEP
            run = 1.0 / gentler
            if math.isinf(bucket):
                lasting = math.inf
            else:
                rise = (1.0 + RISE_BUCKET) ** bucket
                lasting = rise / gentler / _climb_ms(gentler, flat_ms, lt1_grade)
            cost = sum(
                _ridden_or_pushed_s(run, gentler, effort.MASS_KG, flat_ms, lt1_grade, lasting, 0.0)
            )
            table.append(max(cost, table[-1]))
        return table[steps]


def window_cost_s(
    run_m: float,
    grade: float,
    mass_kg: float,
    flat_ms: float,
    lt1_grade: float,
    climb_s: float | None = None,
    assist_w: float = 0.0,
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
    ("mostly a hidden calculation, less so for the actual time").

    **Steeper never costs less** (routing hunt 4, T4-1). A metre of rise costs at least what
    it costs at any gentler grade (by GRADE_STEP) on the same climb, that is the same rise
    climbed at that grade, so it lasts longer (`_rise_floor`); anything short of that is added
    to the penalty. The floor is the standard rider's without assist, as the penalty is, so
    the top-up is the same at every weight (a heavier rider's own time per metre of rise can
    still fall with the grade: time, not price). Without it a pushed window cost its time,
    which hardly grows with the grade, so the same rise packed into a steeper, shorter pitch
    cost less, and at the avoid end 'avoid hills' chose a 15% wall over a 5% climb; and where
    the rider is held at V_MIN_MS, or a shorter climb gets more of W', a steeper ridden window
    cost a little less.

    With `assist_w` (an electric assist, ASSIST_W) the motor's watts join the rider's, so the
    climb takes less time, never more than without them and never less than at the flat
    speed; the penalty is unchanged (the module's "Electric assist")."""
    if run_m <= 0 or flat_ms <= 0 or grade <= 0:
        return 0.0, 0.0
    mass = effort.clamp_mass_kg(mass_kg)
    climb_ms = _climb_ms(grade, flat_ms, lt1_grade)
    lasting_s = climb_s if climb_s else run_m / climb_ms
    # The climb's rise, were it all at this grade, which the gentler grades climb instead.
    climb_rise = lasting_s * climb_ms * grade
    bucket = (
        math.inf
        if math.isinf(climb_rise)
        else float(math.ceil(round(math.log(climb_rise) / math.log1p(RISE_BUCKET), 6)))
    )
    steps = math.floor(round(grade / GRADE_STEP, 6))
    floor_s = run_m * grade * _rise_floor(steps, flat_ms, lt1_grade, bucket)
    # The slider's top-up, worked out for the standard rider as the penalty is, so it is
    # the same at every weight: on riding, what brings the standard rider's cost up to the
    # floor; on pushing (the same at every weight), what brings the push itself up to it.
    std_s = sum(
        _ridden_or_pushed_s(run_m, grade, effort.MASS_KG, flat_ms, lt1_grade, lasting_s, 0.0)
    )
    ride_t, ride_p = _ridden_s(run_m, grade, mass, flat_ms, lt1_grade, lasting_s, assist_w)
    ride_p += _top_up(floor_s, std_s)
    push_t, push_p = _pushed_s(run_m, grade, flat_ms)
    push_p += _top_up(floor_s, push_t + push_p)
    if push_t + push_p < ride_t + ride_p:
        return push_t, push_p
    return ride_t, ride_p


def profile_cost_s(
    profile: Sequence[tuple[float, float | None]],
    mass_kg: float,
    flat_ms: float,
    hills: int,
    assist_w: float = 0.0,
) -> tuple[float, float]:
    """A profile's (`core.routing.grade_profile`) climbing time and steepness penalty,
    seconds, over its rising windows (`window_cost_s`), at the LT1 grade the hills slider
    sets. Each window is weighed over the time its whole climb takes. `assist_w`: an
    electric assist's watts (ASSIST_W), which shorten the climbing time only."""
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
        t, p = window_cost_s(run, rise / run, mass_kg, flat_ms, lt1, climb_s or None, assist_w)
        time_s += t
        penalty_s += p
    return time_s, penalty_s


def hill_cost_m(
    profile: Sequence[tuple[float, float | None]],
    mass_kg: float,
    flat_ms: float,
    hills: int,
    assist_w: float = 0.0,
) -> float:
    """What a profile's climbs cost, in metres of flat riding at `flat_ms`: their extra time
    plus their steepness penalty (`assist_w`: an electric assist's watts, `profile_cost_s`)."""
    time_s, penalty_s = profile_cost_s(profile, mass_kg, flat_ms, hills, assist_w)
    return (time_s + penalty_s) * flat_ms
