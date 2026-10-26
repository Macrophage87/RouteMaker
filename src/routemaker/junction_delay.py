"""The time a rider loses at junctions, which the router's own time leaves out.

Valhalla's bicycle costing (3.9.1, `BicycleCost::TransitionCost`) times a junction as its
`stopimpact` (0 to 7, from the classes of the roads that meet) times a turn cost of 0.15 s
going straight: about a second at most for a straight crossing, whatever controls it. A
real stop costs a rider far more. Fajans and Curry measured riders at a steady effort on
two parallel San Francisco streets: one stop every 530 ft (California St) against one every
2,800 ft (Sacramento St) cut the average speed from 14.2 to 10.9 mph, about 7.6 s for each
extra stop ("Why Bicyclists Hate Stop Signs", ACCESS 18, 2001,
https://www.accessmagazine.org/spring-2001/bicyclists-hate-stop-signs). So a line through
twenty stop signs was timed as if it had none, and a route on a grid of all-way stops was
both timed too quick and preferred over a trail of the same length (the owner's ride of
2026-10-20: the grid line he was sent took 11 minutes longer than his usual, flatter
way, which the router had timed 3 minutes slower).

The delay is read from the route's own trace (`trace_junctions.junctions_of_trace`), at
every node where the rider crosses or joins a road, not only at the busy junctions the
junction model asks `/locate` about. Stop and yield signs reach the router only through
`/locate`, so this model does not see them; it reads who gives way from the roads' classes:

- a junction with a traffic signal on the node or the rider's approach (`RawJunction.signal`)
  costs SIGNAL_DELAY_S;
- one where the rider, going straight on, crosses a road as busy as their own or busier
  (an arm on each side), turns onto such a road where their own does not go on ahead, or
  crosses or comes out onto any road from a path, makes the rider give way: on the
  District's and Maryland's residential grids most such crossings are stop signs. Giving
  way to a neighbourhood street costs STOP_DELAY_S; to a busier road, which does not stop
  for the rider, more (GIVE_WAY_DELAY_S), the wait for a gap in its traffic (the owner,
  2026-10-20: "a stop sign against a busy street without one probably costs more");
- one where the rider is on the busier road (a side road joining from one side, a turn off
  their own road onto a street no busier at a T, a turn off onto a quieter street), or
  only meets driveways, parking aisles and service roads, costs nothing.

In the District a rider may treat a stop sign as a yield sign (the owner, 2026-10-20: "in
low stress neighborhood roads in DC, bikes aren't required to stop at stop signs if there's
no cross traffic"; DC's Safer Streets Amendment Act of 2022), so where the road given way to
is a neighbourhood street (unclassified or residential) and the junction is in the District
(the caller's `rolls`), the stop is a slow-and-roll at YIELD_DELAY_S. Maryland has no such
rule, and a busier road crossed in the District is a full stop: there is cross traffic.

Junctions that cost something and lie within MERGE_M of the first of them along the route
are one stop (a divided road's two carriageways, a signal's stop line and its junction):
the dearest of them counts, or the signal's wait where one of them is a signal (a divided
road's second carriageway is not mapped with a signal of its own). Junctions that cost
nothing (a driveway, a way split) neither start nor stretch such a run, so a street with a
driveway every few metres still counts each of its stop signs.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from .intersections import Movement
from .trace_junctions import NOT_A_ROAD_USES, PATH_USES, RawJunction

# One full stop and the speed built up again: Fajans and Curry's 14.2 to 10.9 mph at one
# stop every 530 ft against one every 2,800 ft (see the docstring) is 7.6 s a stop, rounded.
STOP_DELAY_S = 8.0
# A signal: the average wait for a rider arriving at random, red squared over twice the
# cycle (Webster's uniform delay with no queue), at a 100 s cycle with 50 s of red is
# 12.5 s, and the half of arrivals that meet red also lose a stop (half of STOP_DELAY_S):
# about 16.5 s, rounded down to 15 because many of the region's signals run shorter cycles
# on the side street a rider crosses from. Inferred, not measured.
SIGNAL_DELAY_S = 15.0
# Giving way to a road busier than a neighbourhood street, which does not stop for the
# rider, by the busiest such road's rank (`ROAD_RANK`): the wait for a gap in its traffic
# and the stop. The Highway Capacity Manual's levels of service for a two-way-stop
# approach (HCM 6th ed., Exhibit 20-2: A up to 10 s of control delay, B 10-15, C 15-25,
# D 25-35) put a minor street meeting light traffic near 10 s and one meeting an arterial
# at its busier hours at 25 s or more; these are one value per class, through the day.
# Inferred from those bands, not measured on riders.
GIVE_WAY_DELAY_S = {0: 30.0, 1: 30.0, 2: 30.0, 3: 20.0, 4: 12.0}
# How far off the rider's own heading another road may leave the node and still be their
# own road going on ahead (degrees).
AHEAD_DEG = 30.0
# A stop taken as a yield: slowing from about 12 to 5 mph and back loses about 1.7 s by the
# kinematics alone (1.5 m/s/s braking, 0.8 m/s/s pick-up), and Fajans and Curry's energy
# count (rolling through at 5 mph saves about a quarter of a full stop's energy) puts it
# near 6 s at a steady effort; between the two. Inferred, not measured.
YIELD_DELAY_S = 4.0
# The quietest road a District stop is still a full stop for: busier than this is cross
# traffic (Valhalla's tertiary and up).
ROLL_MAX_BUSY_RANK = 5
# Junctions this close along the route are one stop (metres): a divided road's median is
# rarely wider, and a signal's stop line sits 7 to 30 m before its junction.
MERGE_M = 35.0

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


def delay_at(junction: RawJunction, rolls: bool = False, beacon: bool = False) -> float:
    """The seconds a rider loses at one junction (see the module docstring); `rolls`: a
    stop sign there may be taken as a yield (the District); `beacon`: the map's signal
    there is a known flashing beacon, so the rider gives way as at a stop sign."""
    arms = [
        _rank(cls)
        for (use, _one_way), cls in zip(junction.others, junction.other_classes, strict=False)
        if use not in NOT_A_ROAD_USES and _rank(cls) < _NO_RANK
    ]
    from_path = junction.in_use in PATH_USES
    to_path = junction.out_use in PATH_USES
    out = _NO_RANK if to_path else _rank(junction.out_class)
    if not arms:
        # No road crosses here: a way's end, or only driveways, paths and service roads
        # meet the route. A path coming out onto a road still gives way to it.
        return _stop(out, rolls) if from_path and out < _NO_RANK else 0.0
    if junction.signal and not beacon:
        return SIGNAL_DELAY_S
    if from_path:
        # A path crossing a road or coming out onto one gives way to it.
        return _stop(min(out, *arms), rolls)
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
        return _stop(min(given_way), rolls)
    # A turn, or straight on onto another road: giving way where the road joined is as
    # busy as the rider's own or busier; turning off onto a quieter one costs nothing here.
    if out > own:
        return 0.0
    if out == own and not _crossed(junction, own):
        # Turning off a road that goes on ahead onto one no busier, with nothing else
        # as busy at the node (a T): the rider is on the through road and does not stop.
        return 0.0
    return _stop(min(out, *arms), rolls)


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


def _stop(busiest_rank: int, rolls: bool) -> float:
    """Giving way where the busiest road given way to has this rank: the wait for a gap
    where it is busier than a neighbourhood street (GIVE_WAY_DELAY_S), else a yield in the
    District and a full stop elsewhere."""
    if busiest_rank in GIVE_WAY_DELAY_S:
        return GIVE_WAY_DELAY_S[busiest_rank]
    return YIELD_DELAY_S if rolls and busiest_rank >= ROLL_MAX_BUSY_RANK else STOP_DELAY_S


def delay_runs(
    junctions: Iterable[RawJunction],
    rolls: Callable[[float, float], bool] | None = None,
    beacon: Callable[[float, float], bool] | None = None,
) -> list[tuple[float, float]]:
    """Each run's wait as (metres along the traced route where it begins, seconds): each
    junction's `delay_at`, the costing junctions within MERGE_M of the first of a run counted
    once, at the dearest or, where one of them is a signal, at the signal's wait.
    `rolls(lon, lat)` says where a stop sign may be taken as a yield, `beacon(lon, lat)`
    where a mapped signal is a known flashing beacon (the junction model's beacon list);
    None: nowhere. Each is asked only where its answer can change the cost. The ride's
    arrival times place each wait where it is (`routemaker.time_marks`)."""
    runs: list[tuple[float, float]] = []
    run_start: float | None = None
    run_cost = 0.0
    run_signal = False
    for junction in sorted(junctions, key=lambda j: j.m):
        here = (junction.lon, junction.lat)
        is_beacon = junction.signal and beacon is not None and beacon(*here)
        cost = delay_at(junction, False, is_beacon)
        if cost == STOP_DELAY_S and rolls is not None and rolls(*here):
            cost = delay_at(junction, True, is_beacon)
        if cost <= 0:
            continue
        signal = junction.signal and not is_beacon
        if run_start is not None and junction.m - run_start <= MERGE_M:
            run_signal = run_signal or signal
            run_cost = SIGNAL_DELAY_S if run_signal else max(run_cost, cost)
        else:
            if run_start is not None:
                runs.append((run_start, run_cost))
            run_start, run_cost, run_signal = junction.m, cost, signal
    if run_start is not None:
        runs.append((run_start, run_cost))
    return runs


def delay_s(
    junctions: Iterable[RawJunction],
    rolls: Callable[[float, float], bool] | None = None,
    beacon: Callable[[float, float], bool] | None = None,
) -> float:
    """The route's junction delay in seconds: the sum of its runs' waits (`delay_runs`)."""
    return float(sum(cost for _m, cost in delay_runs(junctions, rolls, beacon)))
