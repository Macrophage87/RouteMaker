"""The bikeshare plan: walk to a dock, ride dock to dock, walk to the destination.

FOLLOWUP-BIKESHARE (OWNER-DECISIONS 243-245, 299, 300, 301, 466, 466a). Nothing here is
saved and nothing is tied to a visitor: the plan reads the operator's live feeds
through `core.gbfs` (one copy for the deployment, about 60 s old at most; no history
is kept) and the routers, and answers.

Nearest stations (466, 466a): `nearby_stations` lists the three stations nearest a
point that are at least 3/4 full (to pick a bike up) or at most 1/4 full (to return
one), from the live feed alone. They are listed by distance and nothing else: the
rider chooses, and a chosen station is passed to `plan` (`pickup_station`,
`dropoff_station`) to be used for that end of the ride. A station that has not
reported for 30 minutes is unavailable everywhere here.

The plan
--------
1. Docks that can start the ride: those whose status says the chosen bike type
   is there (a classic is `num_bikes_available - num_ebikes_available`; an
   e-bike is `num_ebikes_available`) and that are renting. For an E-bike, free-
   floating e-bikes near the start count as starts too (245).
2. Docks that can end it: returning, with a free slot.
3. The few nearest of each, by straight line, are walked for real
   (Valhalla pedestrian costing on the standard graph), and the pair with the
   shortest walk + ride is chosen. The ride is estimated for that choice by
   the straight line and a detour factor at the bike's pace; only the winner
   is routed as a ride (`routing.plan`, so the leg has the stress order, the
   presets' hills and everything else a ride has).
4. Fallback: a nearer dock that has no such bike, or no free slot, is passed
   over with a note, and the next-nearest is used. With no availability feed
   the nearest docks are used and the notes say availability is unknown.
5. E-bike endings (244): the plan ends at a dock, and also offers ending at the
   destination outside a dock where that is allowed: where the operator
   publishes geofencing zones and the destination is in none that bar ending a
   ride. With no zone data, only docks are offered, and the answer says why.
   The out-of-dock fee is read from the operator's pricing plans, never
   assumed; where no plan names one the answer says so. Fees are the
   operator's information, not a quote.

Pace and walking: a rider on foot is planned at `WALK_SPEED_KMH`, 3 mph, an
unhurried pace with a bike to collect, rather than Valhalla's 5.1 km/h.

Every sentence is US units first with metric in brackets (OWNER-DECISIONS 85),
and the steps are worded here so that a screen reader and the page read the
same words.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from routemaker.geo import Point, haversine

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


def bike_words(bike: str) -> str:
    return "an e-bike" if bike == presets.BIKE_EBIKE else "a classic bike"


def _plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


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


def start_candidates(origin: LonLat, bike: str, snapshot: gbfs.Snapshot, notes: list[str]):
    """The nearest docks (and free e-bikes) that can start a ride, nearest first,
    with a note for each nearer dock passed over."""
    picks: list[tuple[float, Pick]] = []
    passed: list[tuple[float, Pick]] = []
    for distance, station in _nearest(snapshot, origin):
        pick = _dock_pick(station, snapshot)
        if _can_start(pick, bike, snapshot):
            picks.append((distance, pick))
            if len(picks) == START_DOCKS:
                break
        elif not picks:
            passed.append((distance, pick))
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
        near = sorted(
            (_distance(origin, [b.lon, b.lat]), b)
            for b in snapshot.free_bikes
            if abs(b.lat - origin[1]) < 0.05 and abs(b.lon - origin[0]) < 0.07
        )
        for distance, found in near[:START_FREE_BIKES]:
            if distance <= SEARCH_RADIUS_M:
                free.append(
                    (distance, Pick("free_bike", "an e-bike outside a dock", found.lon, found.lat))
                )
    return picks, free


def end_candidates(dest: LonLat, snapshot: gbfs.Snapshot, notes: list[str]):
    picks: list[tuple[float, Pick]] = []
    passed: list[tuple[float, Pick]] = []
    for distance, station in _nearest(snapshot, dest):
        pick = _dock_pick(station, snapshot)
        if _can_end(pick, snapshot):
            picks.append((distance, pick))
            if len(picks) == END_DOCKS:
                break
        elif not picks:
            passed.append((distance, pick))
    for distance, pick in passed[:2]:
        notes.append(
            f"The dock nearest your destination, {pick.name}, {miles(distance)} away, "
            f"{_why_not_end(pick)}; the plan ends at a farther one."
            if pick is passed[0][1]
            else f"The next dock, {pick.name}, {miles(distance)} away, {_why_not_end(pick)}."
        )
    return picks


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


def nearby_stations(point: LonLat, action: str, snapshot: gbfs.Snapshot) -> list[NearbyStation]:
    """The `NEARBY_COUNT` stations nearest `point` that fit the action, nearest first, from the
    live feed alone (nothing stored, nothing ranked beyond distance: the rider chooses).

    pickup: installed, renting, reporting in the last 30 minutes, and at least 3/4 full.
    dropoff: installed, returning, reporting in the last 30 minutes, and at most 1/4 full.
    Out to `SEARCH_RADIUS_M` in a straight line. With no availability feed there is nothing
    to list (the caller says availability is unknown)."""
    if action not in ACTIONS:
        raise ValueError(f"not an action: {action}")
    if snapshot.status is None:
        return []
    found: list[NearbyStation] = []
    for distance, station in _nearest(snapshot, point):
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
        if not fits:
            continue
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
            )
        )
        if len(found) == NEARBY_COUNT:
            break
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


def _start_step(pick: Pick, bike: str, walk: WalkLeg, snapshot: gbfs.Snapshot) -> str:
    if pick.kind == "free_bike":
        return (
            f"Walk {miles(walk.distance_m)} to an e-bike parked outside a dock, "
            "and unlock it with the operator's app."
        )
    st = pick.status
    kind = "e-bike" if bike == presets.BIKE_EBIKE else "classic bike"
    article = "an" if kind == "e-bike" else "a"
    if st is None:
        count = "availability unknown"
    else:
        count = f"{st.bikes_of(bike)} available"
    lead = (
        f"Start at the dock at {pick.name}"
        if walk.distance_m < AT_DOCK_M
        else f"Walk {miles(walk.distance_m)} to the dock at {pick.name}"
    )
    return f"{lead}, take {article} {kind} ({count})."


def _end_step(pick: Pick, ride_m: float, bike: str) -> str:
    if pick.kind == "outside_dock":
        return (
            f"Ride {miles(ride_m)} to your destination and leave the e-bike there, outside a dock."
        )
    st = pick.status
    slots = "availability unknown" if st is None else _plural(st.docks, "free slot", "free slots")
    return f"Ride {miles(ride_m)} to the dock at {pick.name} ({slots})."


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
) -> dict:
    """The route API's body for a bikeshare plan: the ride leg's own body, with the
    walks, docks, availability, fee and notes under `bikeshare`. A chosen `pickup_station`
    or `dropoff_station` (a station id) is used for that end in place of the nearest docks.

    Raises NoBikeshare where there is no dock to start or end at, no way on foot, or
    nothing to ride; routing's own errors pass through from the ride.
    """
    notes: list[str] = []
    offer = outside_offer(bike, snapshot, dest)
    use_outside = ending == ENDING_OUTSIDE and offer["offered"]
    if ending == ENDING_OUTSIDE and not use_outside:
        notes.append(OUTSIDE_REASON_WORDS[offer["reason"]] + " The plan ends at a dock.")

    if pickup_station:
        docks, free = pinned_start(origin, pickup_station, bike, snapshot)
    else:
        docks, free = start_candidates(origin, bike, snapshot, notes)
    kind_word = "e-bike" if bike == presets.BIKE_EBIKE else "classic bike"
    if not docks and not free:
        raise NoBikeshare(
            f"No dock within {miles(SEARCH_RADIUS_M)} of the start has a {kind_word} "
            "right now. Try the other bike type, or move the start."
        )
    ends: list[tuple[float, Pick]] = []
    if not use_outside:
        if dropoff_station:
            ends = pinned_end(dest, dropoff_station, snapshot)
        else:
            ends = end_candidates(dest, snapshot, notes)
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
                "There is no way on foot from a dock with a free slot to the destination."
            )

    best = None
    for s_pick, s_walk in starts:
        for e_pick, e_walk in finishes:
            if s_pick.station_id is not None and s_pick.station_id == e_pick.station_id:
                continue
            if _distance(s_pick.point, e_pick.point) < 50.0:
                continue
            total = (
                s_walk.duration_s
                + _ride_s(s_pick.point, e_pick.point, speed_kmh)
                + (e_walk.duration_s if e_walk else 0.0)
            )
            if best is None or total < best[0]:
                best = (total, s_pick, s_walk, e_pick, e_walk)
    if best is None:
        raise NoBikeshare(
            "The nearest docks to the start and to the destination are the same, so there is "
            "nothing to ride. Walking is the way."
        )
    _, start, walk_start, end, walk_end = best

    # What was passed over, said once the choice is made.
    if docks and start.kind == "dock" and start is not docks[0][1]:
        notes.append(
            f"The nearest dock with {'an' if bike == presets.BIKE_EBIKE else 'a'} {kind_word}, "
            f"{docks[0][1].name}, is closer; this plan starts at {start.name} because the walk "
            "plus the ride is shorter."
        )
    if start.kind == "free_bike":
        nearest_dock = docks[0][0] if docks else None
        notes.append(
            "The plan starts at an e-bike parked outside a dock, near you"
            + (
                f", rather than the nearest dock with one, {miles(nearest_dock)} away: "
                "the walk plus the ride is shorter."
                if nearest_dock is not None
                else "."
            )
        )
    if not use_outside and ends and end is not ends[0][1]:
        notes.append(
            f"The dock nearest your destination with a free slot, {ends[0][1].name}, is closer; "
            f"this plan ends at {end.name} because the walk plus the ride is shorter."
        )

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
    if direct is not None and direct.duration_s <= walk_s + ride_s:
        notes.append(
            f"Walking the whole way, {miles(direct.distance_m)} in about "
            f"{minutes(direct.duration_s)}, is as quick as this plan."
        )

    steps = [{"kind": "walk", "text": _start_step(start, bike, walk_start, snapshot)}]
    steps.append({"kind": "ride", "text": _end_step(end, ride_m, bike)})
    if walk_end is not None:
        steps.append(
            {
                "kind": "walk",
                "text": (
                    f"Return the bike, then walk {miles(walk_end.distance_m)} to your destination."
                ),
            }
        )
    total_s = walk_s + ride_s
    summary = f"Bikeshare, {kind_word}: about {minutes(total_s)} in all. " + " ".join(
        step["text"] for step in steps
    )

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
    if bike == presets.BIKE_EBIKE:
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
        "credit": gbfs.CREDIT,
    }
    body["attribution"] = [*ride.get("attribution", []), gbfs.CREDIT]
    return body


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
