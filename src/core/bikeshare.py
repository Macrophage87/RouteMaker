"""The bikeshare plan: walk to a dock, ride dock to dock, walk to the destination.

FOLLOWUP-BIKESHARE (OWNER-DECISIONS 243-245, 299, 300, 301, 466, 466a). Nothing here is
saved and nothing is tied to a visitor: the plan reads the operator's live feeds
through `core.gbfs` (one copy for the deployment, about 60 s old at most; no history
is kept) and the routers, and answers.

Nearest stations (466, 466a): `nearby_stations` lists three stations near a point
that are at least 3/4 full (to pick a bike up) or at most 1/4 full (to return one),
from the live feed alone. The rider chooses, and a chosen station is passed to `plan`
(`pickup_station`, `dropoff_station`) to be used for that end of the ride. A station
that has not reported for 30 minutes is unavailable everywhere here.

Stations on your way first (the owner, 2026-10-11: "we should prioritize the stations
that would be in the direction of the route"). One rule, used by the station lists,
the plan's choice of docks and its route options: a station costs **its walk plus
the extra riding it adds**. The extra riding is how much farther the station is
from the other end of the trip than the rider's own point is, and never less than
nothing (`extra_riding_m`):

- picking up near the start, a station behind the rider (farther from the
  destination than the start is) adds that much riding; one toward the
  destination adds none;
- returning near the destination, a station past it (farther from the start than
  the destination is) adds that much riding; one on the way in adds none.

So a station on your way is ranked by its walk alone, and one behind you as if it
were its walk plus the extra ride farther away: a dock 100 m behind ranks with one
200 m ahead. Straight lines throughout, so the rule can be checked with a ruler.
A station that adds under `ON_THE_WAY_M` (165 ft (50 m)) is said to be "on your
way"; any other says how much riding it adds. Without the other end (only a start
placed) the list is by distance alone, as before.

The plan
--------
1. Docks that can start the ride: those whose status says the chosen bike type
   is there (a classic is `num_bikes_available - num_ebikes_available`; an
   e-bike is `num_ebikes_available`) and that are renting. For an E-bike, free-
   floating e-bikes near the start count as starts too (245).
2. Docks that can end it: returning, with a free slot.
3. The few best of each by the direction rule above (walk plus extra riding,
   straight lines) are walked for real (Valhalla pedestrian costing on the
   standard graph), and the quickest pair is chosen: the real walks plus the
   ride estimated by the straight line and a detour factor at the bike's pace
   (ties by the walks plus extra riding). The direction rule picks which docks
   are walked; the time picks among them, because it also counts how much a
   dock ahead shortens the ride, which the rule (never below zero) does not:
   picking the pair by the rule alone made about a quarter of simulated
   trips slower (the worst by over 3 minutes) for almost no gain in docks on
   the way (review of PR #94, 2026-10-11). A dock behind still lengthens
   the ride, so the time counts it against. Only the winner is routed as a
   ride (`routing.plan`, so the leg has the stress order, the presets' hills
   and everything else a ride has).
   The answer's `options` are the quickest pairs, up to `OPTION_COUNT`, the
   first being the plan's own.
4. Fallback: a nearer dock that has no such bike, or no free slot, is passed
   over with a note. With no availability feed every dock counts and the
   notes say availability is unknown.
5. E-bike endings (244): the plan ends at a dock, and also offers ending at the
   destination outside a dock where that is allowed: where the operator
   publishes geofencing zones and the destination is in none that bar ending a
   ride. With no zone data, only docks are offered, and the answer says why.
   The out-of-dock fee is read from the operator's pricing plans, never
   assumed; where no plan names one the answer says so. Fees are the
   operator's information, not a quote.

Rebalance Ride (REBALANCE-RIDE; Stephen, 2026-10-12)
----------------------------------------------------
The same plan with `rebalance=True`: the docks are the station lists' own (`nearby_stations`),
so the start is a crowded station (at least 3/4 full, e-bikes counted) near the start that
has a bike of the chosen type, and the end a station that needs bikes (at most 1/4 full) near
the destination; the top `NEARBY_COUNT` of each by the direction rule, with no distance cap.
There is no public feed of the operator's reward points, so fill (bikes / capacity) from the
station status this module already reads stands in for them, and no points are shown. No
free-floating e-bike (it is not at a crowded station) and no ending outside a dock.

Pace and walking: a rider on foot is planned at `WALK_SPEED_KMH`, 3 mph, an
unhurried pace with a bike to collect, rather than Valhalla's 5.1 km/h.

Every sentence is US units first with metric in brackets (OWNER-DECISIONS 85),
and the steps are worded here so that a screen reader and the page read the
same words.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Protocol

from routemaker.geo import Point, haversine
from routemaker.lang import t

from . import gbfs, presets

LonLat = list[float]

METRES_PER_MILE = 1609.344
FEET_PER_METRE = 3.28084

BIKES = (presets.BIKE_CLASSIC, presets.BIKE_EBIKE)
ENDING_DOCK = "dock"
ENDING_OUTSIDE = "outside_dock"
ENDINGS = (ENDING_DOCK, ENDING_OUTSIDE)

# How many of the nearest docks (and of the free-floating e-bikes) are walked for
# real before the pair is chosen. Each is one pedestrian route.
START_DOCKS = 3
START_FREE_BIKES = 2
END_DOCKS = 3
# Nothing farther than this in a straight line is offered: 1.9 mi.
SEARCH_RADIUS_M = 3000.0
# A walk past this is said to be long (1.0 mi).
LONG_WALK_M = 1609.0
# The ride from straight line: a street route is about this much longer.
RIDE_DETOUR = 1.3
# 3 mph. Valhalla's default is 5.1 km/h.
WALK_SPEED_KMH = 4.8
# A walk this short is "at the dock".
AT_DOCK_M = 25.0
# A station that adds less riding than this is "on your way": 165 ft (50 m), so a dock
# a little to one side of a long trip still counts.
ON_THE_WAY_M = 50.0
# How many route options a plan offers (start dock and end dock pairs).
OPTION_COUNT = 3


class NoBikeshare(Exception):
    """No bikeshare plan can be made; the message says why, in words for a rider."""


@dataclass(frozen=True)
class WalkLeg:
    coordinates: list[LonLat]
    distance_m: float
    duration_s: float


class Services(Protocol):
    """What the planner asks of the routers: a pedestrian route (None: no way on
    foot), and the ride leg as the route API's body."""

    def walk(self, a: LonLat, b: LonLat) -> WalkLeg | None: ...

    def ride(self, a: LonLat, b: LonLat) -> dict: ...


# --- Words ----------------------------------------------------------------------


def miles(metres: float) -> str:
    """US first, metric in brackets: "0.2 mi (0.3 km)"; "300 ft (90 m)" when short."""
    if metres < 160.0:
        feet = metres * FEET_PER_METRE
        feet = round(feet, -1) if feet >= 100 else round(feet)
        short_m = round(metres, -1) if metres >= 100 else round(metres)
        return f"{feet:.0f} ft ({short_m:.0f} m)"
    return f"{metres / METRES_PER_MILE:.1f} mi ({metres / 1000:.1f} km)"


def minutes(seconds: float) -> str:
    whole = max(1, round(seconds / 60))
    return f"{whole} min"


# --- Candidates -------------------------------------------------------------------


@dataclass
class Pick:
    """One place a leg starts or ends."""

    kind: str  # "dock", "free_bike" or "outside_dock"
    name: str
    lon: float
    lat: float
    station_id: str | None = None
    status: gbfs.StationStatus | None = None
    known: bool = False  # availability read from the feed
    stale: bool = False  # the station has not reported for 30 minutes: unavailable

    @property
    def point(self) -> LonLat:
        return [self.lon, self.lat]


def _distance(a: LonLat, b: LonLat) -> float:
    return haversine(Point(*a), Point(*b))


def _dock_pick(station: gbfs.Station, snapshot: gbfs.Snapshot) -> Pick:
    status = None if snapshot.status is None else snapshot.status.get(station.station_id)
    return Pick(
        "dock",
        station.name,
        station.lon,
        station.lat,
        station.station_id,
        status,
        known=status is not None,
        stale=status is not None and snapshot.reporting_stale(status),
    )


def _nearest(snapshot: gbfs.Snapshot, around: LonLat) -> list[tuple[float, gbfs.Station]]:
    near = [
        (_distance(around, [s.lon, s.lat]), s)
        for s in snapshot.stations
        if abs(s.lat - around[1]) < 0.05 and abs(s.lon - around[0]) < 0.07
    ]
    return sorted(
        ((d, s) for d, s in near if d <= SEARCH_RADIUS_M), key=lambda t: (t[0], t[1].name)
    )


def _by_distance(snapshot: gbfs.Snapshot, around: LonLat) -> list[tuple[float, gbfs.Station]]:
    """Every station, nearest first: the station lists have no distance cap (the owner,
    2026-10-10: "no distance cap, always show the top 3")."""
    return sorted(
        ((_distance(around, [s.lon, s.lat]), s) for s in snapshot.stations),
        key=lambda t: (t[0], t[1].name),
    )


def extra_riding_m(station: LonLat, point: LonLat, other_end: LonLat | None) -> float:
    """The riding a station adds to the trip, in straight-line metres: how much farther it
    is from `other_end` (the destination, picking up; the start, returning) than `point`
    (the start, picking up; the destination, returning) is, and never below zero. None
    for `other_end`: nothing to measure against, so nothing is added."""
    if other_end is None:
        return 0.0
    return max(0.0, _distance(station, other_end) - _distance(point, other_end))


def station_cost_m(station: LonLat, point: LonLat, other_end: LonLat | None) -> float:
    """The one ranking rule: the walk to the station plus the extra riding it adds."""
    return _distance(point, station) + extra_riding_m(station, point, other_end)


def _ranked(
    stations: list[tuple[float, gbfs.Station]], point: LonLat, other_end: LonLat | None
) -> list[tuple[float, gbfs.Station]]:
    """`stations` (distance, station) best first by `station_cost_m`; ties by distance, then
    name."""
    return sorted(
        stations,
        key=lambda t: (
            station_cost_m([t[1].lon, t[1].lat], point, other_end),
            t[0],
            t[1].name,
        ),
    )


def on_the_way(extra_m: float) -> bool:
    return extra_m < ON_THE_WAY_M


def way_words(extra_m: float) -> str:
    """ "on your way", or "adds 0.2 mi (0.3 km) of riding": the reason, in words."""
    return "on your way" if on_the_way(extra_m) else f"adds {miles(extra_m)} of riding"


def _can_start(pick: Pick, bike: str, snapshot: gbfs.Snapshot) -> bool:
    if snapshot.status is None:
        return True  # unknown: the nearest are used and the plan says so
    return (
        pick.status is not None
        and not pick.stale
        and pick.status.can_rent
        and pick.status.bikes_of(bike) > 0
    )


def _can_end(pick: Pick, snapshot: gbfs.Snapshot) -> bool:
    if snapshot.status is None:
        return True
    return pick.status is not None and not pick.stale and pick.status.can_return


STALE_WORDS = "has not reported in over 30 minutes, so its count cannot be trusted"


def _why_not_start(pick: Pick, bike: str) -> str:
    kind = "e-bikes" if bike == presets.BIKE_EBIKE else "classic bikes"
    st = pick.status
    if st is None:
        return "has no availability reading"
    if pick.stale:
        return STALE_WORDS
    if not st.installed:
        return "is not in service"
    if not st.renting:
        return "is not renting bikes right now"
    return f"has no {kind} right now"


def _why_not_end(pick: Pick) -> str:
    st = pick.status
    if st is None:
        return "has no availability reading"
    if pick.stale:
        return STALE_WORDS
    if not st.installed:
        return "is not in service"
    if not st.returning:
        return "is not taking bikes back right now"
    return "has no free slots right now"


def start_candidates(
    origin: LonLat,
    bike: str,
    snapshot: gbfs.Snapshot,
    notes: list[str],
    dest: LonLat | None = None,
):
    """The docks (and free e-bikes) that can start a ride, best first by the walk plus the
    extra riding each adds toward `dest`, with a note for each nearer dock passed over for
    having no bike. Also the nearest dock that can start it, (distance, pick) or None, for
    the note that says why a farther one was chosen."""
    near = _nearest(snapshot, origin)
    passed: list[tuple[float, Pick]] = []
    nearest: tuple[float, Pick] | None = None
    for distance, station in near:
        pick = _dock_pick(station, snapshot)
        if _can_start(pick, bike, snapshot):
            nearest = (distance, pick)
            break
        passed.append((distance, pick))
    picks: list[tuple[float, Pick]] = []
    for distance, station in _ranked(near, origin, dest):
        pick = _dock_pick(station, snapshot)
        if _can_start(pick, bike, snapshot):
            picks.append((distance, pick))
            if len(picks) == START_DOCKS:
                break
    for distance, pick in passed[:2]:
        notes.append(
            f"The nearest dock, {pick.name}, {miles(distance)} away, "
            f"{_why_not_start(pick, bike)}; the plan uses a farther one."
            if pick is passed[0][1]
            else f"The next dock, {pick.name}, {miles(distance)} away, "
            f"{_why_not_start(pick, bike)}."
        )
    free: list[tuple[float, Pick]] = []
    if bike == presets.BIKE_EBIKE and snapshot.free_bikes:
        floating = sorted(
            (
                station_cost_m([b.lon, b.lat], origin, dest),
                _distance(origin, [b.lon, b.lat]),
                index,
            )
            for index, b in enumerate(snapshot.free_bikes)
            if abs(b.lat - origin[1]) < 0.05 and abs(b.lon - origin[0]) < 0.07
        )
        for _, distance, index in floating:
            if distance > SEARCH_RADIUS_M:
                continue
            found = snapshot.free_bikes[index]
            free.append(
                (distance, Pick("free_bike", "an e-bike outside a dock", found.lon, found.lat))
            )
            if len(free) == START_FREE_BIKES:
                break
    return picks, free, nearest


def end_candidates(
    dest: LonLat, snapshot: gbfs.Snapshot, notes: list[str], origin: LonLat | None = None
):
    """The docks that can end the ride, best first by the walk plus the extra riding each
    adds past `dest` (measured from `origin`), the notes for nearer docks passed over, and
    the nearest dock that can end it (or None)."""
    near = _nearest(snapshot, dest)
    passed: list[tuple[float, Pick]] = []
    nearest: tuple[float, Pick] | None = None
    for distance, station in near:
        pick = _dock_pick(station, snapshot)
        if _can_end(pick, snapshot):
            nearest = (distance, pick)
            break
        passed.append((distance, pick))
    picks: list[tuple[float, Pick]] = []
    for distance, station in _ranked(near, dest, origin):
        pick = _dock_pick(station, snapshot)
        if _can_end(pick, snapshot):
            picks.append((distance, pick))
            if len(picks) == END_DOCKS:
                break
    for distance, pick in passed[:2]:
        notes.append(
            f"The dock nearest your destination, {pick.name}, {miles(distance)} away, "
            f"{_why_not_end(pick)}; the plan ends at a farther one."
            if pick is passed[0][1]
            else f"The next dock, {pick.name}, {miles(distance)} away, {_why_not_end(pick)}."
        )
    return picks, nearest


# --- The rider's own choice of dock (OWNER-DECISIONS 466a) ---------------------------


def _pinned(station_id: str, around: LonLat, snapshot: gbfs.Snapshot) -> tuple[float, Pick]:
    for station in snapshot.stations:
        if station.station_id == station_id:
            return _distance(around, [station.lon, station.lat]), _dock_pick(station, snapshot)
    raise NoBikeshare(
        "The dock you chose is no longer in the operator's list. Choose another, or let the "
        "plan choose."
    )


def pinned_start(origin: LonLat, station_id: str, bike: str, snapshot: gbfs.Snapshot):
    """The dock the rider chose to take a bike from, in place of the nearest ones. It must
    still be able to start the ride, or the rider is told why not."""
    distance, pick = _pinned(station_id, origin, snapshot)
    if not _can_start(pick, bike, snapshot):
        raise NoBikeshare(
            f"The dock you chose, {pick.name}, {_why_not_start(pick, bike)}. Choose another, or "
            "let the plan choose."
        )
    return [(distance, pick)], []


def pinned_end(dest: LonLat, station_id: str, snapshot: gbfs.Snapshot):
    distance, pick = _pinned(station_id, dest, snapshot)
    if not _can_end(pick, snapshot):
        raise NoBikeshare(
            f"The dock you chose, {pick.name}, {_why_not_end(pick)}. Choose another, or let the "
            "plan choose."
        )
    return [(distance, pick)]


# --- The nearest stations to pick up from or return to (OWNER-DECISIONS 466, 466a) -----

PICKUP = "pickup"
DROPOFF = "dropoff"
ACTIONS = (PICKUP, DROPOFF)
# How many are listed, and how full a station is to be listed: to take a bike, at least 3/4
# full; to return one, at most 1/4 full (bikes / (bikes + free docks)).
NEARBY_COUNT = 3
FULL_AT_LEAST = 0.75
EMPTY_AT_MOST = 0.25


@dataclass(frozen=True)
class NearbyStation:
    station_id: str
    name: str
    lon: float
    lat: float
    percent_full: int
    distance_m: float
    bikes: int
    ebikes: int
    docks: int
    # The riding the station adds (`extra_riding_m`) and whether that is "on your way";
    # None for both when the list has no other end to measure against.
    extra_m: float | None = None
    on_the_way: bool | None = None


def _fitting(
    point: LonLat,
    action: str,
    snapshot: gbfs.Snapshot,
    toward: LonLat | None,
    also=None,
) -> list[tuple[float, gbfs.Station, gbfs.StationStatus, float]]:
    """The `NEARBY_COUNT` stations near `point` that fit the action (`nearby_stations`), best
    first, as (distance, station, status, fullness); `also(status)`, where given, must hold
    too (Rebalance Ride: a bike of the chosen type). No distance cap."""
    assert snapshot.status is not None
    fitting: list[tuple[float, gbfs.Station, gbfs.StationStatus, float]] = []
    for distance, station in _by_distance(snapshot, point):
        status = snapshot.status.get(station.station_id)
        if status is None or snapshot.reporting_stale(status):
            continue
        fullness = status.fullness
        if fullness is None:
            continue
        if action == PICKUP:
            fits = status.can_rent and fullness >= FULL_AT_LEAST
        else:
            fits = status.can_return and fullness <= EMPTY_AT_MOST
        if not fits or (also is not None and not also(status)):
            continue
        fitting.append((distance, station, status, fullness))
        # By distance, the cost (distance + extra) of the stations still to come is at least
        # their distance; once three fit and the next is farther than the third-best cost so
        # far, none can rank higher.
        if len(fitting) >= NEARBY_COUNT:
            costs = sorted(station_cost_m([s.lon, s.lat], point, toward) for _, s, _, _ in fitting)
            if distance > costs[NEARBY_COUNT - 1]:
                break
    return sorted(
        fitting,
        key=lambda t: (station_cost_m([t[1].lon, t[1].lat], point, toward), t[0], t[1].name),
    )[:NEARBY_COUNT]


def rebalance_starts(
    origin: LonLat, dest: LonLat, bike: str, snapshot: gbfs.Snapshot
) -> list[tuple[float, Pick]]:
    """Rebalance Ride's docks to start from: crowded stations near the start (the pick-up
    list's), each with a bike of the chosen type, best first toward `dest`."""
    if snapshot.status is None:
        return []
    found = _fitting(origin, PICKUP, snapshot, dest, also=lambda st: st.bikes_of(bike) > 0)
    return [(distance, _dock_pick(station, snapshot)) for distance, station, _, _ in found]


def rebalance_ends(
    dest: LonLat, origin: LonLat, snapshot: gbfs.Snapshot
) -> list[tuple[float, Pick]]:
    """Rebalance Ride's docks to end at: stations that need bikes near the destination (the
    drop-off list's), best first on the way in from `origin`."""
    if snapshot.status is None:
        return []
    found = _fitting(dest, DROPOFF, snapshot, origin)
    return [(distance, _dock_pick(station, snapshot)) for distance, station, _, _ in found]


def _fill_words(pick: Pick, rounding) -> str:
    fullness = None if pick.status is None else pick.status.fullness
    if fullness is None:
        return "its fill can't be read"
    return f"{rounding(fullness * 100)}% full"


def rebalance_pinned_start(picks: list[tuple[float, Pick]]) -> None:
    """A dock the rider chose to start a Rebalance Ride from must be crowded (at least 3/4
    full), as the pick-up list's are, or the rider is told why not."""
    for _, pick in picks:
        fullness = None if pick.status is None else pick.status.fullness
        if fullness is None or fullness < FULL_AT_LEAST:
            # Rounded down, so a station just short of 3/4 never reads "75% full".
            raise NoBikeshare(
                f"{pick.name} isn't crowded right now ({_fill_words(pick, math.floor)}), so it "
                "can't start a Rebalance Ride. Choose another, or let the plan choose."
            )


def rebalance_pinned_end(picks: list[tuple[float, Pick]]) -> None:
    """A dock the rider chose to end a Rebalance Ride at must need bikes (at most 1/4 full),
    as the drop-off list's do, or the rider is told why not."""
    for _, pick in picks:
        fullness = None if pick.status is None else pick.status.fullness
        if fullness is None or fullness > EMPTY_AT_MOST:
            # Rounded up, so a station just over 1/4 never reads "25% full".
            raise NoBikeshare(
                f"{pick.name} doesn't need bikes right now ({_fill_words(pick, math.ceil)}), so "
                "it can't end a Rebalance Ride. Choose another, or let the plan choose."
            )


def nearby_stations(
    point: LonLat, action: str, snapshot: gbfs.Snapshot, toward: LonLat | None = None
) -> list[NearbyStation]:
    """The `NEARBY_COUNT` stations near `point` that fit the action, best first, from the live
    feed alone (nothing stored).

    pickup: installed, renting, reporting in the last 30 minutes, and at least 3/4 full.
    dropoff: installed, returning, reporting in the last 30 minutes, and at most 1/4 full.
    Ranked by the walk plus the extra riding each adds (the module's docstring): `toward` is
    the other end of the trip, the destination for a pick-up and the start for a drop-off.
    Without it, by distance alone. No distance cap: the three that fit, however far (the
    owner, 2026-10-10). With no availability feed there is nothing to list (the caller says
    availability is unknown)."""
    if action not in ACTIONS:
        raise ValueError(f"not an action: {action}")
    if snapshot.status is None:
        return []
    best = _fitting(point, action, snapshot, toward)
    found: list[NearbyStation] = []
    for distance, station, status, fullness in best:
        extra = (
            None if toward is None else extra_riding_m([station.lon, station.lat], point, toward)
        )
        found.append(
            NearbyStation(
                station_id=station.station_id,
                name=station.name,
                lon=round(station.lon, 6),
                lat=round(station.lat, 6),
                percent_full=round(fullness * 100),
                distance_m=round(distance, 1),
                bikes=status.bikes,
                ebikes=min(status.ebikes, status.bikes),
                docks=status.docks,
                extra_m=None if extra is None else round(extra, 1),
                on_the_way=None if extra is None else on_the_way(extra),
            )
        )
    return found


# --- E-bike endings ---------------------------------------------------------------


def outside_offer(bike: str, snapshot: gbfs.Snapshot, dest: LonLat) -> dict:
    """Whether a ride may end outside a dock at `dest`, and what the operator says it
    costs. Only an E-bike can end outside a dock (244), and only where zone data says
    so: with none, only docks are offered."""
    if bike != presets.BIKE_EBIKE:
        return {"offered": False, "reason": "classic_bikes_end_at_docks", "fee": None}
    if snapshot.zones is None:
        reason = "zones_unreadable" if "geofencing_zones" in snapshot.failed else "no_zone_data"
        return {"offered": False, "reason": reason, "fee": None}
    if not snapshot.zones.allows_ending(dest[0], dest[1]):
        return {"offered": False, "reason": "no_parking_zone", "fee": None}
    plan = gbfs.out_of_dock_fee(snapshot.pricing or [])
    fee = None
    if plan is not None:
        fee = {
            "name": plan.name,
            "price": plan.price,
            "currency": plan.currency,
            "description": plan.description,
        }
    return {"offered": True, "reason": None, "fee": fee}


# The operator's own page on e-bike parking rules, given as text and a link (OWNER-DECISIONS 305:
# the no-parking zones exist only inside the operator's app, with no public map or feed, so using
# them would breach the data licence; the plan stays docks-only).
EBIKE_PAGE = "https://capitalbikeshare.com/how-it-works/ebike"

OUTSIDE_REASON_WORDS = {
    "classic_bikes_end_at_docks": "A classic bike is returned to a dock.",
    "no_zone_data": (
        "Ending outside a dock isn't offered because no-parking zones aren't published; see "
        f"the operator's e-bike page for current parking rules: {EBIKE_PAGE}"
    ),
    "zones_unreadable": (
        "Ending outside a dock isn't offered because no-parking zones could not be read just "
        f"now; see the operator's e-bike page for current parking rules: {EBIKE_PAGE}"
    ),
    "no_parking_zone": (
        "Ending an e-bike outside a dock is not offered here: the destination is in a zone "
        "where the operator does not allow it or asks for a dock."
    ),
}


def fee_words(fee: dict | None) -> str:
    if fee is None:
        return (
            "The operator's data does not state the out-of-dock fee; check the operator's own "
            "information before leaving a bike outside a dock."
        )
    price = f"{fee['price']} {fee['currency']}"
    said = fee["description"] or fee["name"]
    return f"The operator's data lists {fee['name']}: {price}. {said}".strip()


def pricing_note(snapshot: gbfs.Snapshot, bike: str) -> str | None:
    """The operator's e-bike price information, as its words, for information only."""
    if bike != presets.BIKE_EBIKE or not snapshot.pricing:
        return None
    parts = [p.description or f"{p.name}: {p.price} {p.currency}" for p in snapshot.pricing]
    return (
        "Operator's price information: "
        + " ".join(parts)
        + " This is shown from the operator's data, not as a quote."
    )


# --- The plan ---------------------------------------------------------------------


def _ride_s(a: LonLat, b: LonLat, speed_kmh: float) -> float:
    return _distance(a, b) * RIDE_DETOUR / (speed_kmh / 3.6)


def _stop_out(pick: Pick, bike: str, snapshot: gbfs.Snapshot) -> dict:
    st = pick.status
    return {
        "kind": pick.kind,
        "name": pick.name,
        "lon": round(pick.lon, 6),
        "lat": round(pick.lat, 6),
        "station_id": pick.station_id,
        "availability": "known" if pick.known or pick.kind != "dock" else "unknown",
        "bikes_available": None if st is None else st.bikes_of(bike),
        "classic_available": None if st is None else st.classic,
        "ebikes_available": None if st is None else min(st.ebikes, st.bikes),
        "docks_available": None if st is None else st.docks,
    }


def _walk_out(leg: WalkLeg | None, to_name: str) -> dict | None:
    if leg is None:
        return None
    return {
        "geometry": {
            "type": "LineString",
            "coordinates": [[round(lon, 6), round(lat, 6)] for lon, lat in leg.coordinates],
        },
        "distance_m": round(leg.distance_m, 1),
        "duration_s": round(leg.duration_s, 1),
        "to": to_name,
    }


def _start_step(
    pick: Pick, bike: str, walk: WalkLeg, snapshot: gbfs.Snapshot, rebalance: bool = False
) -> str:
    # In the language in force (`routemaker.lang`; routing audit D30); English as it was.
    if pick.kind == "free_bike":
        return t(
            "Walk {distance} to an e-bike parked outside a dock, "
            "and unlock it with the operator's app.",
            distance=miles(walk.distance_m),
        )
    st = pick.status
    if st is None:
        count = t("availability unknown")
    else:
        n = st.bikes_of(bike)
        count = t("1 available") if n == 1 else t("{n} available", n=n)
    lead = (
        t("Start at the dock at {place}", place=pick.name)
        if walk.distance_m < AT_DOCK_M
        else t(
            "Walk {distance} to the dock at {place}",
            distance=miles(walk.distance_m),
            place=pick.name,
        )
    )
    crowded = t(", which is crowded") if rebalance else ""
    if bike == presets.BIKE_EBIKE:
        return t(
            "{lead}{crowded}, take an e-bike ({count}).", lead=lead, crowded=crowded, count=count
        )
    return t(
        "{lead}{crowded}, take a classic bike ({count}).", lead=lead, crowded=crowded, count=count
    )


def _end_step(pick: Pick, ride_m: float, bike: str, rebalance: bool = False) -> str:
    if pick.kind == "outside_dock":
        return t(
            "Ride {distance} to your destination and leave the e-bike there, outside a dock.",
            distance=miles(ride_m),
        )
    st = pick.status
    if st is None:
        slots = t("availability unknown")
    else:
        slots = t("1 free slot") if st.docks == 1 else t("{n} free slots", n=st.docks)
    needs = t(", which needs bikes") if rebalance else ""
    return t(
        "Ride {distance} to the dock at {place}{needs} ({slots}).",
        distance=miles(ride_m),
        place=pick.name,
        needs=needs,
        slots=slots,
    )


def plan(
    origin: LonLat,
    dest: LonLat,
    bike: str,
    ending: str,
    snapshot: gbfs.Snapshot,
    services: Services,
    speed_kmh: float,
    pickup_station: str | None = None,
    dropoff_station: str | None = None,
    rebalance: bool = False,
) -> dict:
    """The route API's body for a bikeshare plan: the ride leg's own body, with the
    walks, docks, availability, fee and notes under `bikeshare`. A chosen `pickup_station`
    or `dropoff_station` (a station id) is used for that end in place of the nearest docks.
    `rebalance`: Rebalance Ride, from a crowded station to one that needs bikes (the module's
    docstring); always a dock at each end.

    Raises NoBikeshare where there is no dock to start or end at, no way on foot, or
    nothing to ride; routing's own errors pass through from the ride.
    """
    notes: list[str] = []
    if rebalance and snapshot.status is None:
        raise NoBikeshare(
            "Station availability can't be read right now, so there is no telling which "
            "stations are crowded. Try Bikeshare, or try again shortly."
        )
    offer = outside_offer(bike, snapshot, dest)
    if rebalance:
        ending = ENDING_DOCK
    use_outside = ending == ENDING_OUTSIDE and offer["offered"]
    if ending == ENDING_OUTSIDE and not use_outside:
        notes.append(OUTSIDE_REASON_WORDS[offer["reason"]] + " The plan ends at a dock.")

    nearest_start: tuple[float, Pick] | None = None
    nearest_end: tuple[float, Pick] | None = None
    if pickup_station:
        docks, free = pinned_start(origin, pickup_station, bike, snapshot)
        if rebalance:
            rebalance_pinned_start(docks)
    elif rebalance:
        docks, free = rebalance_starts(origin, dest, bike, snapshot), []
    else:
        docks, free, nearest_start = start_candidates(origin, bike, snapshot, notes, dest)
    kind_word = "e-bike" if bike == presets.BIKE_EBIKE else "classic bike"
    if rebalance and not docks:
        raise NoBikeshare(
            f"No station has {kind_word}s to spare right now (none is at least 3/4 full). "
            "Try the other bike type, or plain Bikeshare."
        )
    if not docks and not free:
        raise NoBikeshare(
            f"No dock within {miles(SEARCH_RADIUS_M)} of the start has a {kind_word} "
            "right now. Try the other bike type, or move the start."
        )
    ends: list[tuple[float, Pick]] = []
    if not use_outside:
        if dropoff_station:
            ends = pinned_end(dest, dropoff_station, snapshot)
            if rebalance:
                rebalance_pinned_end(ends)
        elif rebalance:
            ends = rebalance_ends(dest, origin, snapshot)
            if not ends:
                raise NoBikeshare(
                    "No station needs bikes right now (none is at most 1/4 full). Try plain "
                    "Bikeshare."
                )
        else:
            ends, nearest_end = end_candidates(dest, snapshot, notes, origin)
        if not ends:
            raise NoBikeshare(
                f"No dock within {miles(SEARCH_RADIUS_M)} of the destination has a free slot "
                "right now. Move the destination."
            )

    starts: list[tuple[Pick, WalkLeg]] = []
    for _, pick in [*docks, *free]:
        leg = services.walk(origin, pick.point)
        if leg is not None:
            starts.append((pick, leg))
    if not starts:
        raise NoBikeshare("There is no way on foot from the start to a dock that has a bike.")
    finishes: list[tuple[Pick, WalkLeg | None]] = []
    if use_outside:
        finishes.append((Pick("outside_dock", "your destination", dest[0], dest[1]), None))
    else:
        for _, pick in ends:
            leg = services.walk(pick.point, dest)
            if leg is not None:
                finishes.append((pick, leg))
        if not finishes:
            raise NoBikeshare(
                "There is no way on foot from a station that needs bikes to the destination."
                if rebalance
                else "There is no way on foot from a dock with a free slot to the destination."
            )

    # Every pair, quickest first: the real walks plus the estimated ride. Ties by the walks
    # plus the extra riding each end adds (straight lines). The docks walked were already
    # chosen by that rule; the time also credits a dock ahead for the riding it saves.
    pairs = []
    for s_pick, s_walk in starts:
        s_extra = extra_riding_m(s_pick.point, origin, dest)
        for e_pick, e_walk in finishes:
            if s_pick.station_id is not None and s_pick.station_id == e_pick.station_id:
                continue
            if _distance(s_pick.point, e_pick.point) < 50.0:
                continue
            e_extra = 0.0 if e_walk is None else extra_riding_m(e_pick.point, dest, origin)
            cost = s_walk.distance_m + s_extra + (e_walk.distance_m if e_walk else 0.0) + e_extra
            total = (
                s_walk.duration_s
                + _ride_s(s_pick.point, e_pick.point, speed_kmh)
                + (e_walk.duration_s if e_walk else 0.0)
            )
            pairs.append((cost, total, s_pick, s_walk, s_extra, e_pick, e_walk, e_extra))
    if not pairs and rebalance:
        raise NoBikeshare(
            "The crowded stations and the ones that need bikes are within a few steps of each "
            "other, so there is no Rebalance Ride to make. Try plain Bikeshare."
        )
    if not pairs:
        raise NoBikeshare(
            "The nearest docks to the start and to the destination are the same, so there is "
            "nothing to ride. Walking is the way."
        )
    pairs.sort(key=lambda p: (p[1], p[0]))
    _, _, start, walk_start, start_extra, end, walk_end, end_extra = pairs[0]

    # What was passed over, said once the choice is made.
    if (
        nearest_start is not None
        and start.kind == "dock"
        and start.station_id != nearest_start[1].station_id
    ):
        near_d, near_pick = nearest_start
        lead = (
            f"The nearest dock with {'an' if bike == presets.BIKE_EBIKE else 'a'} {kind_word}, "
            f"{near_pick.name}, is closer, {miles(near_d)} away"
        )
        notes.append(
            _passed_words(
                lead, extra_riding_m(near_pick.point, origin, dest), "starts at", start, start_extra
            )
        )
    if start.kind == "free_bike":
        nearest_dock = nearest_start[0] if nearest_start else None
        notes.append(
            "The plan starts at an e-bike parked outside a dock, near you"
            + (
                f", rather than the nearest dock with one, {miles(nearest_dock)} away: "
                "the walk plus the ride is quicker."
                if nearest_dock is not None
                else "."
            )
        )
    if not use_outside and nearest_end is not None and end.station_id != nearest_end[1].station_id:
        near_d, near_pick = nearest_end
        lead = (
            f"The dock nearest your destination with a free slot, {near_pick.name}, is closer, "
            f"{miles(near_d)} away"
        )
        notes.append(
            _passed_words(
                lead, extra_riding_m(near_pick.point, dest, origin), "ends at", end, end_extra
            )
        )
    options = _options(pairs, bike, use_outside, snapshot)

    ride = services.ride(start.point, end.point)

    # Availability and data notes.
    if snapshot.status is None:
        notes.append(
            "The operator's availability data could not be read, so whether a dock has a bike "
            "or a free slot is unknown; docks were chosen by distance alone."
        )
    if snapshot.stale:
        notes.append(
            "The operator's feeds did not answer just now; availability is from a minute or two "
            "ago and may have changed."
        )
    if bike == presets.BIKE_EBIKE and snapshot.free_bikes is None:
        notes.append("Free-floating e-bikes could not be checked, so only docks were considered.")
    for alert in (snapshot.alerts or [])[:2]:
        notes.append(f"The operator reports: {alert}")
    for leg, label in ((walk_start, "start"), (walk_end, "destination")):
        if leg is not None and leg.distance_m > LONG_WALK_M:
            notes.append(
                f"The walk {'from the start' if label == 'start' else 'to the destination'} is "
                f"long, {miles(leg.distance_m)}."
            )

    ride_m = float(ride.get("distance_m", 0.0))
    ride_s = float(ride.get("duration_s", 0.0))
    walk_s = (walk_start.duration_s if walk_start else 0.0) + (
        walk_end.duration_s if walk_end else 0.0
    )
    walk_m = (walk_start.distance_m if walk_start else 0.0) + (
        walk_end.distance_m if walk_end else 0.0
    )

    # Is the whole walk about as quick? One more pedestrian route says so.
    direct = services.walk(origin, dest)
    walk_note = _walk_note(direct, walk_s + ride_s)
    if walk_note:
        notes.append(walk_note)

    steps = [{"kind": "walk", "text": _start_step(start, bike, walk_start, snapshot, rebalance)}]
    steps.append({"kind": "ride", "text": _end_step(end, ride_m, bike, rebalance)})
    if walk_end is not None:
        steps.append(
            {
                "kind": "walk",
                "text": t(
                    "Return the bike, then walk {distance} to your destination.",
                    distance=miles(walk_end.distance_m),
                ),
            }
        )
    total_s = walk_s + ride_s
    title = "Rebalance Ride" if rebalance else "Bikeshare"
    kind_said = t("e-bike") if bike == presets.BIKE_EBIKE else t("classic bike")
    about = t("about {time} in all", time=minutes(total_s))
    summary = f"{title}, {kind_said}: {about}. " + " ".join(step["text"] for step in steps)

    endings = [
        {
            "kind": ENDING_DOCK,
            "offered": True,
            "chosen": not use_outside,
            "reason": None,
            "reason_text": None,
            "fee": None,
            "fee_text": None,
            "walk_m": None if use_outside else round(walk_end.distance_m, 1) if walk_end else None,
            "text": (
                f"End at the dock at {end.name}, then walk {miles(walk_end.distance_m)} to your "
                "destination."
                if not use_outside and walk_end
                else "End at the nearest dock with a free slot."
            ),
        }
    ]
    # Rebalance Ride ends where a bike is needed, a dock: no outside ending is offered.
    if bike == presets.BIKE_EBIKE and not rebalance:
        endings.append(
            {
                "kind": ENDING_OUTSIDE,
                "offered": offer["offered"],
                "chosen": use_outside,
                "reason": offer["reason"],
                "reason_text": None if offer["offered"] else OUTSIDE_REASON_WORDS[offer["reason"]],
                "fee": offer["fee"],
                "fee_text": fee_words(offer["fee"]) if offer["offered"] else None,
                "walk_m": None,
                "text": (
                    "End at your destination, outside a dock. " + fee_words(offer["fee"])
                    if offer["offered"]
                    else OUTSIDE_REASON_WORDS[offer["reason"]]
                ),
            }
        )

    pricing = []
    if bike == presets.BIKE_EBIKE:
        pricing = [
            {
                "name": p.name,
                "price": p.price,
                "currency": p.currency,
                "description": p.description,
            }
            for p in snapshot.pricing or []
        ]
    availability = "unknown" if snapshot.status is None else ("stale" if snapshot.stale else "live")
    body = dict(ride)
    body["bikeshare"] = {
        "bike": bike,
        "rebalance": rebalance,
        "ending": ENDING_OUTSIDE if use_outside else ENDING_DOCK,
        "start": _stop_out(start, bike, snapshot),
        "end": _stop_out(end, bike, snapshot),
        "walk_start": _walk_out(walk_start, start.name),
        "walk_end": _walk_out(walk_end, "your destination"),
        "ride_m": round(ride_m, 1),
        "ride_s": round(ride_s, 1),
        "walk_m": round(walk_m, 1),
        "walk_s": round(walk_s, 1),
        "total_s": round(total_s, 1),
        "availability": availability,
        "endings": endings,
        "pricing": pricing,
        "pricing_note": pricing_note(snapshot, bike),
        "steps": steps,
        "summary": summary,
        "notes": notes,
        "options": options,
        "credit": gbfs.CREDIT,
    }
    # The chosen option carries the routed ride's own figures, not the estimate.
    if options:
        options[0]["ride_m"] = round(ride_m, 1)
        options[0]["total_s"] = round(total_s, 1)
        options[0]["estimated"] = False
        options[0]["text"] = _option_text(options[0])
    body["attribution"] = [*ride.get("attribution", []), gbfs.CREDIT]
    # The standard way through a closure (v0.8.2) is a bike plan's: a share bike's ride
    # leg sits between walks it does not carry.
    body["closure_through"] = None
    if body.get("avoid_alternate"):
        # The way round an Avoid-rated junction (335) is shown in place of the ride
        # leg, so it carries the same walks and docks (its ride and totals its own)
        # and the operator's credit (the review of 351e65b).
        around = dict(body["avoid_alternate"])
        around["bikeshare"] = alternate_block(body["bikeshare"], around, direct)
        around["attribution"] = [*around.get("attribution", []), gbfs.CREDIT]
        body["avoid_alternate"] = around
    return body


def _passed_words(
    lead: str, near_extra: float, verb: str, chosen: Pick, chosen_extra: float
) -> str:
    """The note for a nearer dock passed over: why the chosen one is used instead."""
    if on_the_way(near_extra):
        return (
            f"{lead} in a straight line; this plan {verb} {chosen.name} because the walk plus "
            "the ride is quicker."
        )
    return (
        f"{lead}, but {way_words(near_extra)}; this plan {verb} {chosen.name}, "
        f"{way_words(chosen_extra)}, because the walk plus the ride is quicker."
    )


def _option_end(pick: Pick, walk: WalkLeg | None, extra: float, bike: str, snapshot) -> dict:
    out = _stop_out(pick, bike, snapshot)
    out["walk_m"] = round(walk.distance_m, 1) if walk else 0.0
    out["walk_s"] = round(walk.duration_s, 1) if walk else 0.0
    out["extra_m"] = round(extra, 1)
    out["on_the_way"] = on_the_way(extra)
    out["way_text"] = way_words(extra)
    return out


def _option_text(option: dict) -> str:
    """One option in plain words, US units first, for the button and a screen reader."""
    pickup, dropoff = option["pickup"], option["dropoff"]
    if pickup["kind"] == "free_bike":
        first = f"Pick up an e-bike outside a dock, {miles(pickup['walk_m'])} walk"
    else:
        first = f"Pick up at {pickup['name']}, {miles(pickup['walk_m'])} walk"
    first += f", {pickup['way_text']}."
    if dropoff["kind"] == "outside_dock":
        second = "Leave the e-bike at your destination, outside a dock."
    else:
        second = (
            f"Return at {dropoff['name']}, {miles(dropoff['walk_m'])} walk, {dropoff['way_text']}."
        )
    return f"{first} {second} About {minutes(option['total_s'])} in all."


def _options(pairs: list, bike: str, use_outside: bool, snapshot: gbfs.Snapshot) -> list[dict]:
    """Up to `OPTION_COUNT` start-and-end pairs, quickest first (the first is the plan's own).
    An option can be asked for again with its `pickup_station` and `dropoff_station` (and
    `ending`), so a free-floating e-bike, which has no id to ask for, is offered only when it
    is the plan's own start."""
    out: list[dict] = []
    for index, (_, total, s_pick, s_walk, s_extra, e_pick, e_walk, e_extra) in enumerate(pairs):
        if index > 0 and s_pick.kind == "free_bike":
            continue
        option = {
            "rank": len(out) + 1,
            "chosen": index == 0,
            "pickup": _option_end(s_pick, s_walk, s_extra, bike, snapshot),
            "dropoff": _option_end(e_pick, e_walk, e_extra, bike, snapshot),
            "pickup_station": s_pick.station_id,
            "dropoff_station": None if use_outside else e_pick.station_id,
            "ending": ENDING_OUTSIDE if use_outside else ENDING_DOCK,
            "ride_m": round(_distance(s_pick.point, e_pick.point) * RIDE_DETOUR, 1),
            "total_s": round(total, 1),
            "estimated": True,
            "cost_m": round(
                (s_walk.distance_m if s_walk else 0.0)
                + s_extra
                + (e_walk.distance_m if e_walk else 0.0)
                + e_extra,
                1,
            ),
        }
        option["text"] = _option_text(option)
        out.append(option)
        if len(out) == OPTION_COUNT:
            break
    return out


def _walk_note(direct: WalkLeg | None, total_s: float) -> str | None:
    """The note that walking the whole way is as quick, where it is (`direct`, the
    pedestrian route from the start to the destination, against the plan's `total_s`)."""
    if direct is None or direct.duration_s > total_s:
        return None
    return (
        f"Walking the whole way, {miles(direct.distance_m)} in about "
        f"{minutes(direct.duration_s)}, is as quick as this plan."
    )


def alternate_block(block: dict, around: dict, direct: WalkLeg | None = None) -> dict:
    """A bikeshare plan's `bikeshare` for its way round an Avoid-rated junction: the
    same walks, docks, availability, endings and notes, with the ride's length and time,
    the total, the ride step and the summary for the way round. Whether walking the whole
    way (`direct`) is as quick is asked again against the way round's own total."""
    out = copy.deepcopy(block)
    old_ride_m = float(block.get("ride_m") or 0.0)
    old_total_s = float(block.get("total_s") or 0.0)
    ride_m = float(around.get("distance_m") or 0.0)
    ride_s = float(around.get("duration_s") or 0.0)
    total_s = float(block.get("walk_s") or 0.0) + ride_s
    out["ride_m"] = round(ride_m, 1)
    out["ride_s"] = round(ride_s, 1)
    out["total_s"] = round(total_s, 1)
    notes = [n for n in out.get("notes") or [] if n != _walk_note(direct, old_total_s)]
    walk_note = _walk_note(direct, total_s)
    if walk_note:
        notes.append(walk_note)
    out["notes"] = notes
    summary = str(out.get("summary") or "")
    # The words as the plan wrote them, in the request's language (routing audit D30).
    summary = summary.replace(
        t("about {time} in all", time=minutes(old_total_s)),
        t("about {time} in all", time=minutes(total_s)),
        1,
    )
    for step in out.get("steps") or []:
        if step.get("kind") != "ride":
            continue
        before = step["text"]
        # The ride step opens with its length, whatever the language: the first one is it.
        step["text"] = before.replace(miles(old_ride_m), miles(ride_m), 1)
        summary = summary.replace(before, step["text"], 1)
    out["summary"] = summary
    for option in out.get("options") or []:
        if option.get("chosen"):
            option["ride_m"] = round(ride_m, 1)
            option["total_s"] = round(total_s, 1)
            option["text"] = _option_text(option)
    return out


class RoutingServices:
    """The real routers: pedestrian routes on the standard graph, and the ride leg
    through `routing.plan` as the plan's preset says."""

    def __init__(self, deadline, plan_ride) -> None:
        self._deadline = deadline
        self._plan_ride = plan_ride

    def walk(self, a: LonLat, b: LonLat) -> WalkLeg | None:
        from . import routing

        if _distance(a, b) < 5.0:
            return WalkLeg([a, b], 0.0, 0.0)
        payload = {
            "locations": [{"lon": p[0], "lat": p[1], "type": "break"} for p in (a, b)],
            "costing": "pedestrian",
            "costing_options": {"pedestrian": {"walking_speed": WALK_SPEED_KMH}},
            "directions_type": "none",
            "units": "kilometers",
        }
        try:
            answer = routing._call("standard", "route", payload, self._deadline)
        except routing.RouterRefused as refusal:
            if refusal.code not in routing.NO_PATH_CODES | routing.NO_EDGE_CODES:
                routing.logger.warning("a pedestrian route was refused: %s", refusal)
            return None
        legs = (answer.get("trip") or {}).get("legs") or []
        if not legs:
            return None
        summary = legs[0].get("summary") or {}
        shape = routing.decode_polyline6(legs[0].get("shape", ""))
        return WalkLeg(
            [list(p) for p in shape],
            float(summary.get("length", 0.0)) * 1000.0,
            float(summary.get("time", 0.0)),
        )

    def ride(self, a: LonLat, b: LonLat) -> dict:
        return self._plan_ride([a, b])
