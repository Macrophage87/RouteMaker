"""The time a rider loses at junctions, which the router's own time leaves out.

Valhalla's bicycle costing (3.9.1, `BicycleCost::TransitionCost`) times a junction as its
`stopimpact` (0 to 7, from the classes of the roads that meet) times a turn cost of 0.15 s
going straight: about a second at most for a straight crossing, whatever controls it. A
real stop costs a rider more. So a line through twenty stop signs was timed as if it had
none, and a route on a grid of all-way stops was both timed too quick and preferred over a
trail of the same length.

Who stops, and for how long (one reading with the price; the independent review of
2026-11-13). `routemaker.intersections` prices each junction's stress, and the same answers
time it:

- WHO stops is `intersections.give_way` (`has_way`: the signs the map has on either side,
  and with none mapped the roads' traffic), in both directions: a stop sign on the rider's
  side is a timed stop whatever the roads' classes, and a rider with the right of way (the
  cross traffic has the sign; a clearly bigger road; a side path holding its road's
  priority, at a quiet mouth too) is timed none.
- HOW LONG is a stop sign's STOP_SIGN_S plus `intersections.wait_s`, the wait for a gap in
  the traffic given way to: the very seconds the price weighs, capped the same way
  (`read_wait`). A right turn onto a road waits for its near direction only; a left off a
  busy road waits for its oncoming traffic and has no stop sign.
- A divided road's two carriageways are one crossing with one two-stage wait
  (`intersections.divided_pairs`), however wide the median.

The caller hands those readings in (`waits`' `given_way`, from `intersections.give_ways`).
Where the junction model has none (it reads only the junctions it asks the router's
`/locate` about, and has no answer where two quiet streets meet with nothing mapped), the
trace's own classes say who gives way (`delay_at`, `trace_junctions.junctions_of_trace`):

- a junction with a traffic signal on the node or the rider's approach
  (`RawJunction.signal`), or one the junction model reads as signalised (`signals`), is a
  signal (`signal_wait`);
- one where the rider, going straight on, crosses a road as busy as their own or busier
  (an arm on each side), turns onto such a road where their own does not go on ahead, or
  crosses or comes out onto any road from a path, gives way: a stop sign's STOP_SIGN_S,
  plus the wait for a gap in the typical road of that class (`give_way_wait`);
- one where the rider is on the busier road, or only meets driveways, parking aisles and
  service roads, costs nothing.

`delay_at`'s seconds (STOP_DELAY_S, GIVE_WAY_DELAY_S) are that class reading, never a time
shown or ranked. There is no District rule: until 2026-11-13 a stop at a quiet street in
the District was a slow-and-roll at half the figure, a rule of one city.

The wait at a junction with no signal is its expected real time and nothing else, for the
time shown and for the ranking (the owner, 2026-11-13: "If there's a better call go with
that"; rules that work in any city). Riders choosing routes weigh a stop sign at about its
clock time (Broach, Dill and Gliebe 2012, Table 3), and what they dislike about crossing a
busy road with no signal is charged, in feet, by `routemaker.intersections`: the ranking
counts the larger of that price and this wait at one junction, never both
(`core.refine.junction_over_cap_m`).

Junctions that cost something and lie within MERGE_M of the first of them along the route
are one stop (a signal's stop line and its junction): the dearest of them counts, or the
signal's wait where one of them is a signal; two signals within SIGNAL_MERGE_M are one
wait. Both are the junction model's own reach for one junction
(`intersections.MERGE_WITHIN_M`). Junctions that cost nothing (a driveway, a way split)
neither start nor stretch such a run.

Signals (measured; PR #1240's figures, not re-tuned here). The owner, 2026-11-08: "along
stroads that you'd find in many of the suburbs, the light cycles are a lot longer than
what you'd find in DC". On recorded rides in this region the stopped time at a red was a
median of 19 s at 4 signals on the cities' grids, 52 s at 21 suburban signals, and 66 s
(mean 68 s) at the 16 where the rider crossed a big suburban road; arrivals on green do
not show, so the wait per arrival there is inferred at about 45 to 55 s. He chose
(`signal_wait`), outside the District, Baltimore City, Alexandria and Arlington (the
caller's `suburban`):

- crossing or turning onto a trunk or primary road, or one the junction model reads with 4
  or more lanes or a speed of 40 mph or more (`big`), SUBURBAN_BIG_SIGNAL_S;
- any other signal, a secondary road crossed and riding along the big road through its own
  signals included, SUBURBAN_SIGNAL_S ("I don't think there are many 15 second suburban
  signals. ... 30 is probably more realistic. Cities do have quicker signal changes.").

In the cities the wait comes from the busiest road at the signal, the one the rider rides
along included ("Use the values from real data"): CITY_BIG_SIGNAL_S at a big road,
CITY_SECONDARY_SIGNAL_S at a secondary one, and CITY_SIGNAL_S at any other.

Those are the waits at a red. Counting every pass through a signal in a year of recorded
rides (about 9,000 passes; "sometimes the light is green"), the rider stopped at 29% of
the cities' big-road signals, 16% of their others, and 24 to 43% of the suburbs', so the
wait a ride meets on average is far below the red's. He chose (2026-11-08, "Averages for
time, reds for choice"): the time shown is the average per pass, the cities' by the
ride-time setting (`when`), CITY_PASS_S and SUBURBAN_PASS_S; the ranking keeps the waits
at a red, a suburban one counted SUBURBAN_SIGNAL_WEIGHT times ("a 2x penalty ... There's a
'pain' factor to waiting at busy roads").

A signal never ranks dearer than a stop sign across the same road, at any wait weight
(`ranked_s`, `Wait.stop_s`): Broach et al. and Furth both order them so. The stop sign is
the junction model's price for that road with a stop sign in the signal's place, or its
expected wait where that is more: that model's figures for that road, not a class figure.
So the suburban 2x stands only up to that stop sign's price.

Beg buttons (the owner: "They aren't very common in DC, but they are definitely frustrating
elsewhere"). A suburban signal where the rider crosses or turns onto a big or secondary road
from a path, a sidepath, a trail or a minor road (unclassified, residential, service) is read
as actuated, and so is any signal whose crossing the map tags `button_operated=yes` where the
rider is on the crossing or the path (`buttons`, the ways' OSM ids). Such a crossing ranks as
BUTTON_RANKED_S of waiting ("something like a 2 minute wait, still not as bad as a stop sign
across the same road"), held below that stop sign; its time shown stays the signal's.
Since 2026-11-10 none of this is priced (`BUTTONS_PRICED` is off): the owner, "Remove the
'push button' to cross. It generally only gets the ones that are on timers", then chose to
drop the ranking's penalty too. A button crossing ranks as the plain signal it is read as.
On Road Bike's weight it counts ROAD_BIKE_BUTTON_S, held below two-thirds of that stop sign
(the owner: "Call that 10 minutes on a road bike in pain level. ... Just make sure it's less
than half a stop sign against an uncontrolled busy road", then, told half a stop sign could
fall under a plain signal, "make it 2/3 of one"); the order stays a plain signal, then the
button, then that stop sign. Tandem takes that price too, by the owner's decision
(2026-11-08: "That should be at the 10x."): the ride types are named
(`presets.ROAD_BIKE_BUTTON_RIDES`, passed in as `road_bike_buttons`); any other ride type
ranks a button by the usual stacked rule (at 2x, held at 5x the wait at a red).

Known limit: the signal pass tables (CITY_PASS_S, SUBURBAN_PASS_S) were made with a stop
counted at STOP_DELAY_S (8 s) for the share of passes that stopped, and a stop sign is now
timed at STOP_SIGN_S (3 s). The tables are measured figures and are left as they were.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass, replace

from .intersections import (
    MERGE_WITHIN_M,
    TYPICAL_BIG_ROAD,
    TYPICAL_BUSY_ROAD,
    GiveWay,
    Movement,
    Road,
    wait_s,
)
from .trace_junctions import NOT_A_ROAD_USES, PATH_USES, RawJunction

# What `delay_at` answers where the rider gives way to a quiet street: since 2026-11-13 a
# reading ("a stop sign"), no longer the time shown or ranked there (`give_way_wait`,
# STOP_SIGN_S). It still stands for a stop's seconds in the signal figures below. It was
# derived as "7.6 s a stop, rounded" from Fajans and Curry, which divided the lost time by
# every stop on the slower street; per extra stop the paper gives 9.5 s.
STOP_DELAY_S = 8.0
# A signal: the average wait for a rider arriving at random, red squared over twice the
# cycle (Webster's uniform delay with no queue), at a 100 s cycle with 50 s of red, is
# 12.5 s, and the half of arrivals that meet red also lose a stop (half of STOP_DELAY_S):
# about 16.5 s, rounded down to 15. The junction model's own price; the wait at a signal is
# `signal_wait`'s.
SIGNAL_DELAY_S = 15.0
# The wait at a red in DC, Baltimore City, Alexandria or Arlington, as the ranking counts it,
# by the busiest road there (see the docstring; measured on recorded city rides): a big road
# (trunk or primary, or 4+ lanes, or 40 mph+), a secondary road, and any other.
CITY_BIG_SIGNAL_S = 30.0
CITY_SECONDARY_SIGNAL_S = 15.0
CITY_SIGNAL_S = 20.0
# The time shown at a signal: the average per pass in a year of recorded rides in this
# region (green passes included, the stops over 4 minutes left out as breaks), plus
# STOP_DELAY_S for the share of passes that stopped, rounded, as (big, secondary, other).
# The cities' by the ride-time setting (`routemaker.ridetime`), None where the setting is
# not known (every pass); the suburbs' did not differ by hour, so one set.
CITY_PASS_S = {
    None: (12.0, 5.0, 4.0),
    "night": (9.0, 4.0, 2.0),
    "weekday_rush": (15.0, 6.0, 6.0),
    "weekday_offpeak": (14.0, 6.0, 4.0),
    "weekend": (11.0, 4.0, 4.0),
}
SUBURBAN_PASS_S = (24.0, 15.0, 10.0)
# The wait at a red outside the major cities, as the ranking counts it before the suburban
# weight (see the docstring; recorded rides, and the owner's choices of 2026-11-08):
# crossing or turning onto a big road (trunk or primary, or 4+ lanes, or 40 mph+), and every
# other suburban signal, riding along the big road included ("I don't think there are many
# 15 second suburban signals. Never really encountered one. 30 is probably more realistic.
# Cities do have quicker signal changes.").
SUBURBAN_BIG_SIGNAL_S = 45.0
SUBURBAN_SIGNAL_S = 30.0
# How many times a suburban red's wait counts when routes are ranked: the owner's "pain"
# factor at busy roads. A city's red counts once.
SUBURBAN_SIGNAL_WEIGHT = 2.0
# The most a wait counts in the ranking, the ride type's wait weight and the suburban weight
# (or a button's two minutes) stacked, as a multiple of the wait at a red (a signal's) or of
# the wait shown (any other): Road Bike's 3x on a suburban signal's 2x would be 6x (the
# owner, 2026-11-08: "Maybe go to 5. People prefer free flow on road bikes."). A city signal
# stays at Road Bike's 3x.
MAX_STACKED_WEIGHT = 5.0
# Whether a beg-button crossing is priced at all (see the docstring). Off since the owner's
# word of 2026-11-10: the buttons read (inferred, and the map's `button_operated` tags) were
# mostly signals on timers ("It generally only gets the ones that are on timers"), so the
# ranking's penalty went with Ride's cue, and every such crossing ranks as a plain signal.
# The rule below is kept, switched off, in case better button data turns up.
BUTTONS_PRICED = False

# A crossing read as needing a beg button (see the docstring), as the ranking counts it: two
# minutes of waiting, held below a stop sign across the same road (`signal_wait`).
BUTTON_RANKED_S = 120.0
# How far below that stop sign's price a button crossing is held (seconds of waiting).
BUTTON_BELOW_STOP_S = 1.0
# A button crossing at Road Bike's wait weight (`ranked_s`), as weighted seconds of waiting
# (the 3x included, in place of BUTTON_RANKED_S and the 5x stacked cap): the owner,
# 2026-11-08, "Call that 10 minutes on a road bike in pain level. Most people are clipped
# in and riding on the road so it would really suck. Just make sure it's less than half a
# stop sign against an uncontrolled busy road." Run shares Road Bike's wait weight, and so
# this. Tandem takes it too, at its own 2x (the owner, 2026-11-08: "That should be at the 10x.
# It's really obnoxious to try to navigate to a button on a tandem."). Which ride types take it
# is named (`presets.ROAD_BIKE_BUTTON_RIDES`), never read from the wait weight.
ROAD_BIKE_BUTTON_S = 600.0
# The share of the stop sign across the same road, at that weight, a Road Bike button is
# held below (the owner, 2026-11-08, told half a stop sign could fall under a plain signal:
# "make it 2/3 of one"). Where that share is no dearer than the plain light, the light is
# held 2 s below it and the button 1 s below it (`ranked_s`).
ROAD_BIKE_BUTTON_STOP_SHARE = 2.0 / 3.0
# The classes a suburban signal's big-road wait is for, and the secondary road a beg button is
# also read at (ranks).
BIG_SIGNAL_MAX_RANK = 2
SECONDARY_SIGNAL_RANK = 3
# A rider arriving on a road this quiet or quieter (unclassified, residential, a service road,
# a path) at a suburban signal on a big or secondary road is read as needing its button.
BUTTON_MIN_OWN_RANK = 5
# Giving way to a road busier than a neighbourhood street, which does not stop for the
# rider, by the busiest such road's rank (`ROAD_RANK`): the wait for a gap in its traffic
# and the stop. The Highway Capacity Manual's levels of service for a two-way-stop
# approach (HCM 6th ed., Exhibit 20-2: A up to 10 s of control delay, B 10-15, C 15-25,
# D 25-35) put a minor street meeting light traffic near 10 s and one meeting an arterial
# at its busier hours at 25 s or more; these are one value per class, through the day.
# Our default, unmeasured. Since 2026-11-13 these are `delay_at`'s reading of which class
# of road the rider gives way to, never a time shown or ranked (`give_way_wait`).
GIVE_WAY_DELAY_S = {0: 30.0, 1: 30.0, 2: 30.0, 3: 20.0, 4: 12.0}
# How far off the rider's own heading another road may leave the node and still be their
# own road going on ahead (degrees).
AHEAD_DEG = 30.0
# Junctions this close along the route are one stop (metres): the junction model's own
# reach for one junction's nodes (`intersections.MERGE_WITHIN_M`), one number for the price
# and for the wait (it was 35 m here and 45 m there). A divided road's two carriageways
# with no signal are one wait however far apart (`intersections.divided_pairs`).
MERGE_M = MERGE_WITHIN_M
# Two signals this close along the route are one wait (metres): the same reach.
SIGNAL_MERGE_M = MERGE_WITHIN_M

# Valhalla's road classes from the busiest down. A class not listed (None, a path's
# "service_other") ranks below every road.
ROAD_RANK = {
    "motorway": 0,
    "trunk": 1,
    "primary": 2,
    "secondary": 3,
    "tertiary": 4,
    "unclassified": 5,
    "residential": 6,
}
# A road the rider meets that never makes them give way: driveways, alleys and parking
# aisles are Valhalla's "service_other" class.
_NO_RANK = len(ROAD_RANK)


def _rank(road_class: str | None) -> int:
    return ROAD_RANK.get(road_class or "", _NO_RANK)


def delay_at(junction: RawJunction, beacon: bool = False) -> float:
    """Who gives way at one junction, read from the roads' classes and the junction's
    shape, as seconds that stand for the reading (0: the rider does not give way;
    STOP_DELAY_S: to a quiet street; GIVE_WAY_DELAY_S: to a busier road of that class;
    SIGNAL_DELAY_S: a signal). The time is `waits`'. `beacon`: the map's signal there is a
    known flashing beacon, so the rider gives way as at a stop sign."""
    arms = [
        _rank(cls)
        for (use, _one_way), cls in zip(junction.others, junction.other_classes, strict=False)
        if use not in NOT_A_ROAD_USES and _rank(cls) < _NO_RANK
    ]
    from_path = junction.in_use in PATH_USES
    to_path = junction.out_use in PATH_USES
    out = _NO_RANK if to_path else _rank(junction.out_class)
    if junction.signal and not beacon and junction.others:
        # Before the arms: a signal whose only other arms are a service road's or a trail's
        # (a shopping-centre entrance, a trail crossing the rider's road) stops the rider on
        # the road as any signal does. Read after them, the rider along a suburban stroad was
        # timed through every signalised entrance for nothing (the 2026-11-08 hunt, J2-5).
        return SIGNAL_DELAY_S
    if not arms:
        # No road crosses here: a way's end, or only driveways, paths and service roads
        # meet the route. A path coming out onto a road still gives way to it.
        return _stop(out) if from_path and out < _NO_RANK else 0.0
    if from_path:
        # A path crossing a road or coming out onto one gives way to it.
        return _stop(min(out, *arms))
    own = _rank(junction.in_class)
    straight_on = junction.movement is Movement.STRAIGHT and (
        junction.in_way == junction.out_way or junction.in_class == junction.out_class
    )
    if straight_on:
        # Straight on along one road (OSM often splits a street into ways at a junction):
        # the rider gives way only where a road as busy as their own or busier crosses it,
        # an arm on each side; a side road joining from one side (a T) does not stop them.
        given_way = [rank for rank in arms if rank <= own]
        if len(given_way) < 2:
            return 0.0
        return _stop(min(given_way))
    # A turn, or straight on onto another road: giving way where the road joined is as
    # busy as the rider's own or busier; turning off onto a quieter one costs nothing here.
    if out > own:
        return 0.0
    if out == own and not _crossed(junction, own):
        # Turning off a road that goes on ahead onto one no busier, with nothing else
        # as busy at the node (a T): the rider is on the through road and does not stop.
        return 0.0
    return _stop(min(out, *arms))


def _crossed(junction: RawJunction, own: int) -> bool:
    """Whether a road as busy as the rider's own, other than their own going on ahead,
    meets the node: a junction whose roads carry no headings counts as crossed."""
    if len(junction.other_headings) != len(junction.others) or junction.in_heading is None:
        return True
    for (use, _one_way), cls, heading in zip(
        junction.others, junction.other_classes, junction.other_headings, strict=False
    ):
        if use in NOT_A_ROAD_USES or _rank(cls) > own:
            continue
        if heading is None:
            return True
        off = abs((heading - junction.in_heading + 180.0) % 360.0 - 180.0)
        if not (off <= AHEAD_DEG and _rank(cls) == own):
            return True
    return False


def _stop(busiest_rank: int) -> float:
    """Giving way where the busiest road given way to has this rank, as `delay_at`'s
    reading: GIVE_WAY_DELAY_S where it is busier than a neighbourhood street, else
    STOP_DELAY_S."""
    return GIVE_WAY_DELAY_S.get(busiest_rank, STOP_DELAY_S)


# --- Junctions with no signal: the expected real delay --------------------------------
#
# One published delay function and the map's data about the road (its count, lanes and
# speed). Every figure is a TIME, shown and ranked alike; nothing here is a region's.

# A stop sign with nothing coming: what riders choosing routes weigh one at, 0.9% of a
# mile, 48 ft, about 3 s of riding (Broach, Dill and Gliebe 2012, Table 3; Portland, where
# the law then asked for a full stop). Literature. A full stop and back to speed takes
# 9.5 s (Fajans and Curry 2001: 10.9 mph with a stop every 530 ft against 14.2 mph with one
# every 2,800 ft is 76.8 s a mile more for 8.07 more stops), but riders mostly do not make
# one: full stops were 2% and 3% of passes with nothing coming, 9% and 57% with cross
# traffic (Jackson et al., NHTSA DOT HS 813 641, 2024, Table 2). The same everywhere: the
# District's stop-as-yield law (Safer Streets Amendment Act of 2022, D.C. bill B24-0673)
# makes lawful what the figure already describes. It was 8 s, and 4 s in the District.
STOP_SIGN_S = 3.0
# The wait for a gap in a road's traffic is the junction model's ONE function and ONE
# number, `intersections.wait_s`: the Highway Capacity Manual 2000's formula for a
# pedestrian at an unsignalised crossing as NCHRP Report 562 prints it, fed the road's
# count, lanes and speed and the hour's share of the day's traffic, at most
# `intersections.GAP_WAIT_MAX_S`; the figures and their sources are there. The junction's
# stress price weighs the same seconds (`intersections.gap_ft`).


def gap_wait_s(road: Road, when: str | None = None) -> float:
    """The seconds a rider is expected to wait for a gap in `road`'s traffic where no
    signal stops it: `intersections.wait_s`, the wait the junction's price weighs too."""
    return wait_s(road, when)


def give_way_wait(reading: float, when: str | None = None) -> float:
    """The seconds a rider is expected to lose giving way at a junction the junction model
    has not read, from `delay_at`'s `reading` of the roads' classes: the stop sign
    (STOP_SIGN_S) plus the wait for a gap in the typical road of that class
    (`intersections.TYPICAL_BIG_ROAD` for a trunk or primary road, `TYPICAL_BUSY_ROAD`
    for a secondary or tertiary one; none at a quiet street). Shown and ranked alike."""
    traffic = _TYPICAL_BY_READING.get(reading)
    if traffic is None:
        return STOP_SIGN_S
    return round(STOP_SIGN_S + wait_s(traffic, when), 1)


def read_wait(reading: GiveWay) -> float:
    """The seconds a rider is expected to lose at a junction the junction model has read
    (`intersections.give_way`): nothing where they have the right of way; else the stop
    sign (STOP_SIGN_S; not at a left off a road, which only waits) plus the model's wait
    for a gap, the same seconds its price weighs."""
    if not reading.stops:
        return 0.0
    return round((STOP_SIGN_S if reading.stop_sign else 0.0) + reading.wait_s, 1)


# `delay_at`'s answers that mean a busy road, by its class: trunk or primary, and
# secondary or tertiary.
_TYPICAL_BY_READING = {
    seconds: TYPICAL_BIG_ROAD if seconds == GIVE_WAY_DELAY_S[2] else TYPICAL_BUSY_ROAD
    for seconds in GIVE_WAY_DELAY_S.values()
}


@dataclass(frozen=True)
class SignalWait:
    """A signal's wait (`signal_wait`): the seconds shown, the seconds the ranking counts,
    and whether the rider is read as needing to press its button."""

    seconds: float
    ranked_s: float
    button: bool = False
    # The wait at a red, which MAX_STACKED_WEIGHT is a multiple of.
    red_s: float | None = None
    # A stop sign across the same road, as the ranking counts it at 1x: the junction
    # model's price for it over the signal's (`signal_wait`'s `stop_extra_s`), or its own
    # expected wait where that is more (`stop_wait_s`); None where that is not known.
    stop_s: float | None = None
    # The signal's own ranked wait, as if it needed no button (`ranked_s` on Road Bike).
    signal_ranked_s: float | None = None
    # A light a button is read at for some rider (a suburban crossing of a big or secondary
    # road, or a rider on a crossing or a path), where a plain light ranks below the button
    # on Road Bike (`_signal`).
    button_light: bool = False


# Valhalla's `use` of the ways a rider on a crossing or a path is on (`buttons`).
_CROSSING_USES = PATH_USES | {"pedestrian_crossing"}


def _own_rank(junction: RawJunction) -> int:
    """The rank of the way the rider arrives on: a path, a trail or a crossing ranks below
    every road."""
    if junction.in_use in _CROSSING_USES:
        return _NO_RANK
    return _rank(junction.in_class)


def signal_crossed_rank(junction: RawJunction) -> int | None:
    """The rank of the busiest road the rider crosses or turns onto at a signal, of the
    roads as busy as their own or busier, their own road going on ahead left out; None
    where they ride along the busier road (a side road joining, a turn off it onto a
    quieter one) or meet no road."""
    own = _own_rank(junction)
    headed = len(junction.other_headings) == len(junction.others)
    ranks: list[int] = []
    for i, ((use, _one_way), cls) in enumerate(
        zip(junction.others, junction.other_classes, strict=False)
    ):
        rank = _rank(cls)
        if use in NOT_A_ROAD_USES or rank >= _NO_RANK or rank > own:
            continue
        heading = junction.other_headings[i] if headed else None
        if rank == own and heading is not None and junction.in_heading is not None:
            off = abs((heading - junction.in_heading + 180.0) % 360.0 - 180.0)
            if off <= AHEAD_DEG:
                # The rider's own road going on ahead.
                continue
        ranks.append(rank)
    straight_on = junction.movement is Movement.STRAIGHT and (
        junction.in_way == junction.out_way or junction.in_class == junction.out_class
    )
    out = _NO_RANK if junction.out_use in _CROSSING_USES else _rank(junction.out_class)
    if not straight_on and out <= own and out < _NO_RANK:
        ranks.append(out)
    return min(ranks) if ranks else None


def signal_wait(
    junction: RawJunction,
    suburban: bool = False,
    big: bool = False,
    tagged_button: bool = False,
    stop_extra_s: float | None = None,
    when: str | None = None,
    own_big: bool = False,
    stop_wait_s: float | None = None,
    signal_own_s: float = 0.0,
) -> SignalWait:
    """The wait at one signal (see the module docstring). `suburban`: it lies outside the
    District, Baltimore City, Alexandria and Arlington; `big`: the junction model reads a
    road crossed or joined there with 4 lanes or more or at 40 mph or more
    (`intersections.big_signal_points`); `tagged_button`: the map tags a way the rider
    arrives or leaves on `button_operated=yes`; `stop_extra_s`: what the junction model
    charges the ranking for a stop sign there over the signal, as seconds of waiting
    (None: not known, and the button crossing is not held below it); `when`: the ride-time
    setting (`routemaker.ridetime`), which the cities' time shown is read by; `own_big`: the
    junction model reads the rider's own road there with 4 lanes or more or at 40 mph or
    more (`intersections.own_big_signal_points`), which counts in the busiest road the time
    is read by, never in the suburban big-road red (which is for crossing or joining one);
    `stop_wait_s`: the seconds a stop sign across the same road would be timed at
    (`read_wait` of the junction model's reading with a stop sign in the signal's place);
    `signal_own_s`: what the junction model charges the ranking for the junction with its
    signal, in the same seconds (`intersections.signal_own_ft`).

    The ranked wait here is the signal's own; `ranked_s` holds it below the stop sign
    across the same road (`SignalWait.stop_s`) at every wait weight."""
    crossed = signal_crossed_rank(junction)
    # Crossing or turning onto a big road, or onto a secondary one: the crossings a beg
    # button is read at, where the rider comes from a path or a minor road.
    onto_big = crossed is not None and (crossed <= BIG_SIGNAL_MAX_RANK or big)
    onto_busy = onto_big or crossed == SECONDARY_SIGNAL_RANK
    busiest = _busiest(junction, crossed, big or own_big)
    if suburban:
        red = SUBURBAN_BIG_SIGNAL_S if onto_big else SUBURBAN_SIGNAL_S
        seconds = SUBURBAN_PASS_S[busiest]
        ranked = red * SUBURBAN_SIGNAL_WEIGHT
    else:
        red = (CITY_BIG_SIGNAL_S, CITY_SECONDARY_SIGNAL_S, CITY_SIGNAL_S)[busiest]
        seconds = CITY_PASS_S.get(when, CITY_PASS_S[None])[busiest]
        ranked = red
    stop = None
    if stop_extra_s is not None and crossed is not None:
        # A stop sign across the same road, as the ranking counts one: the junction
        # model's price for it over the signal's (a junction with no signal counts the
        # larger of its price and its wait, `core.refine.junction_over_cap_m`), so never
        # less than its own expected wait. Both are the junction model's figures for that
        # road; until 2026-11-13 the wait was a class figure of the retired model (30, 20
        # or 12 s). Only where the rider crosses or joins a road: riding along the busier
        # road (a turn off it, a side road joining) there is no stop sign across a road to
        # hold the light below (the 2026-11-08 hunt, J3-1).
        # The ranking adds the signal's own price to its wait, so the wait is held below
        # the stop sign's whole (the larger of its price and its wait) less that price.
        stop = max(stop_extra_s, (stop_wait_s or 0.0) - signal_own_s)
    if not BUTTONS_PRICED:
        # A plain signal: no button, and no Road Bike hold below one (`_signal`).
        return SignalWait(seconds, ranked, False, red, stop, ranked, False)
    inferred = suburban and onto_busy and _own_rank(junction) >= BUTTON_MIN_OWN_RANK
    on_crossing = junction.in_use in _CROSSING_USES or junction.out_use in _CROSSING_USES
    button_light = (suburban and onto_busy) or on_crossing
    if not (inferred or (tagged_button and on_crossing)):
        return SignalWait(seconds, ranked, False, red, stop, ranked, button_light)
    pressed = BUTTON_RANKED_S
    if stop is not None:
        pressed = min(pressed, stop - BUTTON_BELOW_STOP_S)
    # Never below the signal's own wait as ranked: a button does not make a light quicker.
    return SignalWait(seconds, max(pressed, ranked), True, red, stop, ranked, True)


def _busiest(junction: RawJunction, crossed: int | None, big: bool) -> int:
    """The busiest road at a signal, the rider's own included, as the passes were counted
    by it: 0 big, 1 secondary, 2 any other. `big`: a road there, the rider's own included
    (`signal_wait`'s `big` or `own_big`), has 4 lanes or more or a speed of 40 mph or more."""
    busiest = _own_rank(junction) if crossed is None else min(crossed, _own_rank(junction))
    if big or busiest <= BIG_SIGNAL_MAX_RANK:
        return 0
    return 1 if busiest == SECONDARY_SIGNAL_RANK else 2


@dataclass(frozen=True)
class Wait:
    """One run's wait (`waits`): where along the traced route it begins (metres) and its
    node, the seconds shown and the seconds the ranking counts, and whether the rider is
    read as needing to press a signal's button there."""

    m: float
    lon: float
    lat: float
    seconds: float
    ranked_s: float
    button: bool = False
    # A signal's wait at a red (`SignalWait.red_s`); None: the wait shown is the base.
    red_s: float | None = None
    # The run's signal's stop sign across the same road and own ranked wait
    # (`SignalWait.stop_s`, `signal_ranked_s`), for `ranked_s`.
    stop_s: float | None = None
    signal_ranked_s: float | None = None
    # The run's signal is a light a button is read at for some rider (`SignalWait`).
    button_light: bool = False
    # Where along the route, and at which node, the run's button signal is (metres, lon,
    # lat): `m`, `lon` and `lat` are the run's first junction, which can be a stop line or
    # the other carriageway short of it (the signal review of 2026-11-08). None: no button.
    button_at: tuple[float, float, float] | None = None


def waits(
    junctions: Iterable[RawJunction],
    beacon: Callable[[float, float], bool] | None = None,
    signals: Collection[tuple[float, float]] = (),
    suburban: Callable[[float, float], bool] | None = None,
    big: Collection[tuple[float, float]] = (),
    buttons: Collection[int] = (),
    stop_extra_s: Mapping[tuple[float, float], float] | None = None,
    when: str | None = None,
    own_big: Collection[tuple[float, float]] = (),
    given_way: Mapping[tuple[float, float, int, int], GiveWay] | None = None,
    signal_own_s: Mapping[tuple[float, float], float] | None = None,
) -> list[Wait]:
    """Each run's wait: the costing junctions within MERGE_M of the first of a run counted
    once, at the dearest or, where one of them is a signal, at the signal's wait
    (`signal_wait`; the run's dearest signal as ranked). `beacon(lon, lat)` says where a
    mapped signal is a known flashing beacon (the junction model's beacon list),
    `suburban(lon, lat)` where a signal lies outside the major cities
    (`core.city_limits`); None: nowhere. Each is asked only where its answer can change
    the cost. `signals`: the points of the junctions the junction model reads as
    signalised (`intersections.signal_points` of the route's events), a signal there as on
    the node; `big`: those it reads a big road at (`intersections.big_signal_points`);
    `buttons`: the OSM ways the map tags `button_operated=yes`; `stop_extra_s`: by signal
    point, what a stop sign there would cost the ranking over the signal, as seconds of
    waiting (`intersections.stop_extra_ft`), and `signal_own_s` what the junction costs it
    with its signal (`intersections.signal_own_ft`); `when`: the ride-time setting the cities'
    signal times are read by (`signal_wait`); `own_big`: the signal points where it reads
    the rider's own road as a big one (`intersections.own_big_signal_points`). A signal
    within SIGNAL_MERGE_M of a run with a signal joins it: the junction model's one
    junction (`intersections.MERGE_WITHIN_M`). The ride's arrival times place each wait
    where it is (`routemaker.time_marks`).

    A junction with no signal, `given_way`: by (lon, lat, way in, way out), the junction
    model's reading of it (`intersections.give_ways`), which is the one answer to who
    stops, for the price and for the time, both ways: where it says the rider gives way a
    stop is timed (`read_wait`) whatever the roads' classes say, and where it says the
    rider has the right of way none is. Where the model has no reading (a junction it did
    not read, two quiet streets with nothing mapped), the classes and the junction's shape
    are read (`delay_at`) and a busy road is timed as the typical road of its class
    (`give_way_wait`). The same seconds are shown and ranked."""
    out: list[Wait] = []
    run: Wait | None = None
    run_signal: SignalWait | None = None
    # Where along the route the run's latest signal is (metres): SIGNAL_MERGE_M is measured
    # from it, not from the run's first junction, which can be a costing junction short of
    # the signal (the 2026-11-08 hunt, J3-3: a path coming out 15 m short of a divided
    # road's first carriageway had split its two signals into two waits and two button cues).
    run_signal_m = 0.0

    def signal_run(run: Wait, signal: SignalWait) -> Wait:
        return replace(
            run,
            seconds=signal.seconds,
            ranked_s=signal.ranked_s,
            red_s=signal.red_s,
            stop_s=signal.stop_s,
            signal_ranked_s=signal.signal_ranked_s,
            button_light=signal.button_light,
        )

    for junction in sorted(junctions, key=lambda j: j.m):
        here = (junction.lon, junction.lat)
        if not junction.signal and here in signals:
            junction = replace(junction, signal=True)
        is_beacon = junction.signal and beacon is not None and beacon(*here)
        cost = delay_at(junction, is_beacon)
        reading = (given_way or {}).get((*here, junction.in_way, junction.out_way))
        signalised = junction.signal and not is_beacon and cost > 0
        signal = None
        if signalised:
            stop_sign = reading if reading is not None and reading.at_signal else None
            signal = signal_wait(
                junction,
                suburban=suburban is not None and suburban(*here),
                big=here in big,
                tagged_button=bool(buttons)
                and (junction.in_way in buttons or junction.out_way in buttons),
                stop_extra_s=(stop_extra_s or {}).get(here),
                when=when,
                own_big=here in own_big,
                stop_wait_s=None if stop_sign is None else read_wait(stop_sign),
                signal_own_s=(signal_own_s or {}).get(here, 0.0),
            )
        elif reading is not None and not reading.at_signal:
            # The junction model's answer, whichever way it differs from the classes'.
            cost = read_wait(reading)
        elif cost > 0:
            cost = give_way_wait(cost, when)
        if cost <= 0:
            continue
        button_at = (junction.m, *here) if signal is not None and signal.button else None
        if run is not None and (
            junction.m - run.m <= MERGE_M
            # A divided road's two carriageways, both signalised, whose nodes lie 35-45 m
            # apart along the trace: one crossing, as the junction model reads it (the
            # 2026-11-08 hunt, J2-2: two waits of 24 s shown and 120 ranked, and two
            # "Light may need a button press" cues, for one crossing of a suburban road).
            or (
                signal is not None
                and run_signal is not None
                and junction.m - run_signal_m <= SIGNAL_MERGE_M
            )
        ):
            if signal is not None:
                run_signal_m = junction.m
            if signal is not None and (
                run_signal is None
                or (signal.ranked_s, signal.seconds) > (run_signal.ranked_s, run_signal.seconds)
            ):
                run_signal = signal
            if run.button_at is None and button_at is not None:
                run = replace(run, button=True, button_at=button_at)
            if run_signal is not None:
                run = signal_run(run, run_signal)
            elif signal is None and cost > run.seconds:
                run = replace(run, seconds=cost, ranked_s=cost)
            continue
        if run is not None:
            out.append(run)
        run_signal = signal
        run_signal_m = junction.m
        run = Wait(junction.m, *here, cost, cost)
        if signal is not None:
            run = replace(signal_run(run, signal), button=signal.button, button_at=button_at)
    if run is not None:
        out.append(run)
    return out


def delay_runs(
    junctions: Iterable[RawJunction],
    beacon: Callable[[float, float], bool] | None = None,
    signals: Collection[tuple[float, float]] = (),
    **reading,
) -> list[tuple[float, float]]:
    """Each run's wait as (metres along the traced route where it begins, seconds shown):
    `waits`, whose other arguments `reading` passes on."""
    return [(w.m, w.seconds) for w in waits(junctions, beacon, signals, **reading)]


def delay_s(
    junctions: Iterable[RawJunction],
    beacon: Callable[[float, float], bool] | None = None,
    signals: Collection[tuple[float, float]] = (),
    **reading,
) -> float:
    """The route's junction delay in seconds shown: the sum of its runs' waits (`waits`)."""
    return float(sum(w.seconds for w in waits(junctions, beacon, signals, **reading)))


def ranked_s(
    found: Iterable[Wait], wait_weight: float = 1.0, *, road_bike_buttons: bool = False
) -> float:
    """The waits as the ranking counts them (`Wait.ranked_s`): a suburban signal's
    SUBURBAN_SIGNAL_WEIGHT times, a button crossing's at BUTTON_RANKED_S. With a ride type's
    `wait_weight` (`presets.wait_weight_for`: Road Bike's 3), each wait times it, the two
    stacked never past MAX_STACKED_WEIGHT times the wait at a red (a signal's; any other
    wait's shown), nor below the wait as ranked at 1x. At every weight a signal never ranks
    past the stop sign across the same road at that weight (`Wait.stop_s`, less
    BUTTON_BELOW_STOP_S; the 2026-11-08 hunt, J2-4, and the review of 2026-11-13: the
    suburban 2x had sent riders across busy roads at stop signs a block from the light).
    So a suburban signal keeps its 2x only up to that stop sign's price: AN OWNER-DECIDED
    NUMBER LIMITED (his 2026-11-08 "2x penalty"), for the order the sources give. With
    `road_bike_buttons` (the ride types
    `presets.ROAD_BIKE_BUTTON_RIDES` names: Road Bike, Run and, by the owner's decision,
    Tandem) and a wait weight above 1, a button crossing counts ROAD_BIKE_BUTTON_S, held below
    two-thirds of that stop sign, and a plain signal ranks below the button there
    (`_road_bike_button`). Without it a button crossing is weighted as any other wait (the
    stacked rule). The sum is given back divided by `wait_weight`, as
    `refine.Analysis.score` multiplies it by that again."""
    if wait_weight <= 0:
        return 0.0
    road_bike = road_bike_buttons and wait_weight > 1.0
    total = 0.0
    for w in found:
        if road_bike and w.button:
            total += _road_bike_button(w, wait_weight)
            continue
        total += _signal(w, w.ranked_s, wait_weight, road_bike)
    return float(total / wait_weight)


def _weighted(w: Wait, ranked: float, wait_weight: float) -> float:
    """A wait ranked at `ranked` (at 1x), at `wait_weight`: the stacked cap, then the stop
    sign across the same road (see `ranked_s`)."""
    weighted = wait_weight * ranked
    if wait_weight > 1.0:
        base = w.seconds if w.red_s is None else w.red_s
        weighted = min(weighted, max(MAX_STACKED_WEIGHT * base, ranked))
    if w.stop_s is not None:
        # At every wait weight: a signal never ranks dearer than a stop sign across the
        # same road (1 s below it at most). LITERATURE for the order: Broach, Dill and
        # Gliebe 2012, Table 3 (a signal 2.1-3.6% of a mile, an unsignalised crossing 7.2%
        # and up); Furth: a signalised crossing is "not usually a barrier". It was held
        # only above 1x (hunt J2-4), which left a suburban signal's 2x ranking above the
        # stop sign across most roads under 20,000 a day once that stop sign took its
        # published price (the independent review of 2026-11-13, finding 1).
        weighted = min(weighted, max(wait_weight * w.stop_s - BUTTON_BELOW_STOP_S, 0.0))
    return weighted


def _button_hold(w: Wait, wait_weight: float) -> float | None:
    """ROAD_BIKE_BUTTON_STOP_SHARE of the stop sign across the same road at `wait_weight`,
    as weighted seconds; None where that stop sign is not priced."""
    if w.stop_s is None:
        return None
    return ROAD_BIKE_BUTTON_STOP_SHARE * wait_weight * w.stop_s


def _signal(w: Wait, ranked: float, wait_weight: float, road_bike: bool = True) -> float:
    """A plain signal (or any other wait) ranked at `ranked` (at 1x), at `wait_weight`:
    `_weighted`, and above 1x at a light a button is read at for some rider
    (`Wait.button_light`), where two-thirds of the stop sign across the same road is no
    more than 1 s above the light, the light held 2 s below it, so that a button there
    (`_road_bike_button`, 1 s below it) still ranks above the same light with no button.
    That hold is part of Road Bike's button rule (`road_bike`); without it, `_weighted` alone."""
    weighted = _weighted(w, ranked, wait_weight)
    hold = (
        _button_hold(w, wait_weight) if road_bike and wait_weight > 1.0 and w.button_light else None
    )
    if hold is not None and weighted > hold - 2.0 * BUTTON_BELOW_STOP_S:
        weighted = max(hold - 2.0 * BUTTON_BELOW_STOP_S, 0.0)
    return weighted


def _road_bike_button(w: Wait, wait_weight: float) -> float:
    """A button crossing at Road Bike's wait weight, as weighted seconds of waiting: the
    owner, 2026-11-08: "Call that 10 minutes on a road bike in pain level. Most people are
    clipped in and riding on the road so it would really suck. Just make sure it's less than
    half a stop sign against an uncontrolled busy road", then, told half a stop sign could
    fall under a plain signal, "make it 2/3 of one". So ROAD_BIKE_BUTTON_S, at least 1 s
    above the same light with no button (`_signal`), and held BUTTON_BELOW_STOP_S below
    two-thirds of the stop sign across the same road at that weight where it is priced (that
    hold wins over the floor: it is the owner's; the light is held 2 s below it there)."""
    plain = w.signal_ranked_s if w.signal_ranked_s is not None else w.ranked_s
    light = _signal(w, plain, wait_weight)
    weighted = max(ROAD_BIKE_BUTTON_S, light + BUTTON_BELOW_STOP_S)
    hold = _button_hold(w, wait_weight)
    if hold is not None:
        weighted = min(weighted, max(hold - BUTTON_BELOW_STOP_S, 0.0))
    return weighted
