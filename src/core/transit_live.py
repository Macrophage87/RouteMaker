"""Live values on the transit plans and station cards (v0.7.0): WMATA's next trains, its rail
incidents and its elevator outages (`core.wmata_live`), laid over the timetable's answer.

A plan is searched on the schedule (`core.transit`). For a plan leaving now, a Metro step's
departure is then WMATA's next train the step's way that the rider can reach in time
(`with_live_trains`, every option, so the ranking sees it), and on the chosen trip a Metrobus
step's is its next bus (`with_live_buses`): the wait is to that train or bus, the time on board
stays the timetable's (WMATA predicts arrivals at the boarding station only), and the step says
"live". A step with no prediction it can catch keeps its timetable time and says "scheduled".
Where a live reading is to hand, the plan and the station card also add, each marked "live" and
credited "Data: WMATA":

- the next trains at a Metro step's boarding station, the way the step goes ("Live: Red Line
  toward Shady Grove in 3 min, 11 min");
- the next buses at a Metrobus step's boarding stop, the way the step goes ("Live: bus 52 in 4
  min, 13 min"; v0.9.0, core.wmata_bus);
- WMATA's rail incidents on the lines the trip uses;
- an elevator out at a station where the rider takes their own bike: "Elevator out at Gallery
  Place: carry your bike on the stairs." It is a warning, not an avoidance (the owner,
  2026-10-13 11:17 UTC: "many people can walk their bike upstairs"). Where no other street
  elevator is known to work there (`blocked_stations`), a trip taking its bike in or out there is
  ranked `ELEVATOR_OUT_S` (15 min) down in the search itself (core.transit.with_elevators_out;
  Stephen, 2026-10-21: "Most cyclists would just ride from the next station over"), and the
  times the rider sees are unchanged; one with a spare elevator is said, never ranked down.

With no live reading (no key, or WMATA not answering) nothing is added: the timetable's answer
is the fallback, and it says "scheduled" as before.
"""

from __future__ import annotations

import math
import time
from dataclasses import replace
from datetime import UTC, datetime

from . import presets, transit, wmata_bus, wmata_live, wmata_trains

# The ranking cost of an elevator out on the way (15 min; core.transit.ELEVATOR_OUT_S).
ELEVATOR_OUT_S = transit.ELEVATOR_OUT_S
METRO = "Metro"
METROBUS = wmata_bus.METROBUS
# Trains shown per direction.
TRAINS_SHOWN = 2


def _metro_ends(leg: transit.Leg, live: wmata_live.Snapshot):
    """A Metro leg's boarding and alighting stations, as WMATA names them (or None)."""
    if not leg.transit or leg.system != METRO or not leg.coordinates:
        return None, None
    return live.station_near(leg.coordinates[0]), live.station_near(leg.coordinates[-1])


# A WMATA station is the map's (core/transitdata/metro-typical.json) within this.
STREET_MATCH_M = 400.0


def street_elevators(station: wmata_live.Station) -> int:
    """The street elevators the map knows at a WMATA station (`street_elevators` in the typical
    timetable's stations, from DC's and OpenStreetMap's elevators); 0 where none is known."""
    rows = transit._typical_doc().get("stations") or []
    near = [(wmata_live._metres((station.lon, station.lat), tuple(r["point"])), r) for r in rows]
    near = [(d, r) for d, r in near if d <= STREET_MATCH_M]
    return int(min(near, key=lambda t: t[0])[1].get("street_elevators", 0)) if near else 0


def _blocked(station: wmata_live.Station, live: wmata_live.Snapshot) -> bool | None:
    """Whether the elevators out leave the bike no way through the station: True, False where
    another street elevator is known to work (Stephen, 2026-10-21: "several of these have
    redundant elevators, so if one is down, it's not penalized"), None with none out. A
    platform elevator out always counts: the platform's is the only one."""
    out = live.elevators_out(station)
    if not out:
        return None
    street = [o for o in out if "street" in o.where.lower()]
    if len(street) < len(out):
        return True
    return len(street) >= max(1, street_elevators(station))


def blocked_stations(live: wmata_live.Snapshot | None) -> list[wmata_live.Station]:
    """The WMATA stations whose elevators out leave a bike no way through (`_blocked`), one
    per station (its other platforms' codes left out)."""
    if live is None:
        return []
    out: list[wmata_live.Station] = []
    for station in live.stations.values():
        if any(o.name == station.name for o in out):
            continue
        if _blocked(station, live):
            out.append(station)
    return out


def _outage_stations(
    option: transit.Option, live: wmata_live.Snapshot, blocked: bool = True
) -> list[str]:
    """The stations, in trip order, where the rider's own bike needs an elevator that is out
    and no other known one serves (`_blocked`); with `blocked` False, those where another
    street elevator still works."""
    out: list[str] = []
    for leg in option.legs:
        if not leg.bike:
            continue
        for station in _metro_ends(leg, live):
            if station is None or station.name in out:
                continue
            if _blocked(station, live) is blocked:
                out.append(station.name)
    return out


# A closed station this near a Metro leg's drawn line is on it: the train passes it.
CLOSED_ON_LINE_M = 120.0


def _near_line(point, coordinates) -> bool:
    """Whether `point` ([lon, lat]) is within `CLOSED_ON_LINE_M` of the drawn line."""
    lat0 = math.radians(point[1])
    kx, ky = 111_320.0 * math.cos(lat0), 110_540.0

    def xy(p):
        return ((p[0] - point[0]) * kx, (p[1] - point[1]) * ky)

    pts = [xy(p) for p in coordinates]
    if len(pts) == 1:
        return math.hypot(*pts[0]) <= CLOSED_ON_LINE_M
    for (ax, ay), (bx, by) in zip(pts, pts[1:], strict=False):
        dx, dy = bx - ax, by - ay
        length = dx * dx + dy * dy
        t = 0.0 if length == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / length))
        if math.hypot(ax + t * dx, ay + t * dy) <= CLOSED_ON_LINE_M:
            return True
    return False


def closed_on(option: transit.Option, live: wmata_live.Snapshot) -> list[str]:
    """The closed stations (WMATA's incidents, `Snapshot.closed`) a trip's Metro legs board at,
    leave at or pass through with the rider's own bike, in trip order."""
    closed = live.closed()
    if not closed:
        return []
    out: list[str] = []
    for leg in option.legs:
        if not leg.bike or not leg.transit or leg.system != METRO or not leg.coordinates:
            continue
        for code in closed:
            station = live.stations.get(code)
            if station is None or station.name in out:
                continue
            if _near_line((station.lon, station.lat), leg.coordinates):
                out.append(station.name)
    return out


def skip_closed(plan: transit.Plan, live: wmata_live.Snapshot | None) -> transit.Plan:
    """Own Bike + 🚆🚌 without the trips that take the bike through a station WMATA says is
    closed. The owner, 2026-10-18: "typically the shuttles don't allow bikes, so own bike is
    affected" and "There is the option to ride through the closure as well": the direct ride is
    always an option, so a plan is never left empty. Bikeshare + 🚶🚆🚌 keeps its trips (a rider
    without a bike can take the shuttle); the step's WMATA alert says so."""
    if live is None or plan.mode != presets.BIKE_TRANSIT or not plan.options:
        return plan
    kept = [o for o in plan.options if not closed_on(o, live)]
    if len(kept) == len(plan.options):
        return plan
    names = list(dict.fromkeys(n for o in plan.options for n in closed_on(o, live)))
    one = len(names) == 1
    said = f"{_and(names)} {'is' if one else 'are'} closed (WMATA)"
    if not kept:
        # Nothing else to offer: the trips stay, and the rider is told.
        return replace(
            plan,
            notes=[*plan.notes, f"{said}: every trip here takes a bike through {_it(one)}."],
        )
    chosen = plan.options[plan.chosen].key
    index = next((i for i, o in enumerate(kept) if o.key == chosen), 0)
    note = f"{said}: trips taking a bike through {'it' if one else 'them'} are left out."
    return replace(plan, options=kept, chosen=index, notes=[*plan.notes, note])


def _it(one: bool) -> str:
    return "it" if one else "them"


def _and(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _toward(train: wmata_live.Train, board, alight, live: wmata_live.Snapshot) -> bool:
    """Whether a train at the boarding station goes the step's way: its last stop is nearer the
    alighting station than the boarding one."""
    end = live.stations.get(train.destination_code or "")
    if end is None or alight is None:
        return False
    here = (end.lon, end.lat)
    return wmata_live._metres(here, (alight.lon, alight.lat)) < wmata_live._metres(
        here, (board.lon, board.lat)
    )


def _when(trains: list[wmata_live.Train]) -> str:
    return ", ".join(wmata_live.train_minutes(t) for t in trains[:TRAINS_SHOWN])


def _coming(leg: transit.Leg, live: wmata_live.Snapshot) -> list[wmata_live.Train]:
    """A Metro step's next trains at its boarding station, its line and its way, soonest first."""
    board, alight = _metro_ends(leg, live)
    if board is None:
        return []
    lines = set(leg.lines)
    trains = [
        t
        for t in live.trains_at(board)
        if t.minutes is not None
        and (not lines or any(wmata_live.same_line(t.line, line) for line in lines))
        and _toward(t, board, alight, live)
    ]
    return sorted(trains, key=lambda t: t.minutes)


def step_live(leg: transit.Leg, live: wmata_live.Snapshot) -> dict | None:
    """A Metro step's next trains now, its way: {"text", "minutes"}, or None."""
    trains = _coming(leg, live)
    if not trains:
        return None
    first = trains[0]
    return {
        "text": f"Live: {first.line} toward {first.destination} in {_when(trains)}.",
        "minutes": [t.minutes for t in trains[:TRAINS_SHOWN]],
        "source": "live",
    }


# --- Live departures (v0.10.0) --------------------------------------------------------------
#
# The owner, 2026-10-19: "Can live metro data be used". A plan for now takes WMATA's predicted
# departures where they cover a step. A reading older than `LIVE_FRESH_S`, or kept past its time
# (`Snapshot.stale`), times nothing; nor does a plan for more than `NOW_S` from now.
LIVE_FRESH_S = 180.0
NOW_S = 120.0
# The clock the plan's moment is checked against (a test pins it).
_wall = time.time


def _minute(moment: transit.Moment, wall: float) -> float:
    """An epoch time as the moment's service-day minute."""
    at = datetime.fromtimestamp(wall, UTC) - transit.day_zero(moment.service_day)
    return at.total_seconds() / 60.0


def _for_now(moment: transit.Moment, as_of: float | None, now: float) -> bool:
    if as_of is None or now - as_of > LIVE_FRESH_S:
        return False
    return abs(_minute(moment, now) - moment.minute) * 60.0 <= NOW_S


def _caught(leg: transit.Leg, reach: float, departs: list[float]) -> transit.Leg | None:
    """The step timed on the first predicted departure the rider reaches the stop for (`reach`,
    service-day minutes), the rest seen after it kept for a rider who misses it; None where the
    predictions run out before the rider gets there."""
    catch = sorted(t for t in departs if reach - 1e-6 <= t <= reach + transit.MAX_WAIT_MIN)
    if not catch:
        return None
    rest = tuple(catch[1:])
    return replace(
        leg,
        depart=catch[0],
        after=rest[0] if rest else None,
        later=rest,
        wait_s=(catch[0] - reach) * 60.0,
        first=None,
        live=True,
    )


def _timed(option: transit.Option, moment: transit.Moment, departs_for) -> transit.Option:
    """The option with each step `departs_for(index, leg)` predicts (departures as service-day
    minutes, or None) timed live, and every later timetable departure worked out again from when
    the rider now gets there. Unchanged where nothing is predicted or the trip no longer holds.
    A step after a frequent service's estimated wait (half the interval) is not timed live: the
    rider's time at its stop is a guess, too rough to name one train."""
    legs = list(option.legs)
    at = moment.minute
    changed = False
    exact = True
    for index, leg in enumerate(legs):
        departs = departs_for(index, leg) if leg.transit and exact else None
        if departs:
            caught = _caught(leg, at, departs)
            if caught is not None:
                legs[index] = leg = caught
                changed = True
        exact = exact and (not leg.transit or leg.depart is not None)
        at += leg.total_s / 60.0
    if not changed:
        return option
    retimed, _notes = transit._retimed(moment.minute, legs)
    return option if retimed is None else replace(option, legs=tuple(retimed))


def with_live_trains(
    plan: transit.Plan, live: wmata_live.Snapshot | None, now: float | None = None
) -> transit.Plan:
    """The plan with every option's Metro steps timed on WMATA's next trains, where the reading
    is fresh and the plan is for now, ranked again on the new totals."""
    if live is None or live.stale or not plan.options:
        return plan
    now = _wall() if now is None else now
    if not _for_now(plan.moment, live.as_of, now):
        return plan

    def timed_live(option: transit.Option) -> transit.Option:
        moment = option.moment or plan.moment

        def departs_for(_index, leg):
            if leg.system != METRO:
                return None
            return [_minute(moment, live.as_of + t.minutes * 60.0) for t in _coming(leg, live)]

        return _timed(option, moment, departs_for)

    timed = [timed_live(option) for option in plan.options]
    if all(a is b for a, b in zip(timed, plan.options, strict=True)):
        return plan
    chosen = plan.option.key
    ranked = sorted(timed, key=transit.rank_key)
    index = 0 if plan.chosen == 0 else next(i for i, o in enumerate(ranked) if o.key == chosen)
    return replace(plan, options=ranked, chosen=index)


def with_live_buses(
    plan: transit.Plan, buses: wmata_bus.StepLives | None, now: float | None = None
) -> transit.Plan:
    """The plan with its chosen trip's Metrobus steps timed on their next buses (the step lives
    `bus_legs` asked for), where the reading is fresh and the plan is for now."""
    if buses is None or not buses.steps:
        return plan
    now = _wall() if now is None else now
    moment = plan.when
    if not _for_now(moment, buses.as_of, now):
        return plan

    def departs_for(index, leg):
        said = buses.steps.get(index)
        if leg.system != METROBUS or not said:
            return None
        return [_minute(moment, buses.as_of + m * 60.0) for m in said.get("minutes", ())]

    option = _timed(plan.option, moment, departs_for)
    if option is plan.option:
        return plan
    options = list(plan.options)
    options[plan.chosen] = option
    return replace(plan, options=options)


def bus_legs(plan: transit.Plan) -> list[tuple[int, str, tuple, tuple]]:
    """The chosen trip's Metrobus steps, for their live lines: (index, route, boarding stop,
    alighting stop), at most `wmata_bus.MAX_STOPS`. The other options are not asked for: only
    the chosen one's steps are shown, and picking another plans it (and asks) again."""
    out = []
    for index, leg in enumerate(plan.option.legs):
        if leg.transit and leg.system == METROBUS and leg.lines and len(leg.coordinates) >= 2:
            out.append((index, leg.lines[0], leg.coordinates[0], leg.coordinates[-1]))
    return out[: wmata_bus.MAX_STOPS]


def annotate(
    block: dict,
    plan: transit.Plan,
    live: wmata_live.Snapshot | None,
    buses: wmata_bus.StepLives | None = None,
) -> dict:
    """The route answer's `transit` block with the live values added (in place, and returned):
    each Metro and Metrobus step's `live` (or null), and `live` on the block: the elevator
    warnings, WMATA's incidents on the lines used, the credit and the reading's time; null with
    no reading."""
    steps = block.get("steps", [])
    for step in steps:
        step.setdefault("live", None)
    block["live"] = None
    bus_steps = buses.steps if buses is not None else {}
    for index, words in bus_steps.items():
        if index < len(steps):
            steps[index]["live"] = words
    if live is None and not bus_steps:
        return block
    warnings: list[str] = []
    alerts: list[str] = []
    if live is not None:
        option = plan.option
        warnings = [wmata_live.elevator_words(name) for name in _outage_stations(option, live)]
        warnings += [
            wmata_live.spare_elevator_words(name)
            for name in _outage_stations(option, live, blocked=False)
        ]
        used: list[str] = []
        for index, leg in enumerate(option.legs):
            if index < len(steps) and leg.transit and leg.system == METRO:
                steps[index]["live"] = step_live(leg, live)
                used += [line for line in leg.lines if line not in used]
        alerts = [i.text for i in live.incidents_on(used)]
    shown = warnings or alerts or any(s.get("live") for s in steps)
    if not shown:
        return block
    if live is not None:
        as_of = wmata_live.as_of_iso(live)
    else:
        as_of = wmata_live.wall_iso(buses.as_of if buses and buses.as_of else time.time())
    block["live"] = {
        "warnings": warnings,
        "alerts": list(dict.fromkeys(alerts)),
        "credit": wmata_live.CREDIT,
        "as_of": as_of,
    }
    return block


def station(point, live: wmata_live.Snapshot | None) -> dict | None:
    """A map station's live values for its card: the next trains by line and way, the elevators
    out, and WMATA's incidents on its lines; None where it is no WMATA station or nothing is
    live."""
    if live is None:
        return None
    found = live.station_near(point)
    if found is None:
        return None
    groups: dict[tuple[str, str], list[wmata_live.Train]] = {}
    for t in live.trains_at(found):
        if t.minutes is None or not t.destination:
            continue
        groups.setdefault((t.line, t.destination), []).append(t)
    trains = []
    for (line, toward), group in groups.items():
        group.sort(key=lambda t: t.minutes)
        trains.append(
            {
                "line": line,
                "toward": toward,
                "minutes": [t.minutes for t in group[:TRAINS_SHOWN]],
                "when": _when(group),
            }
        )
    trains.sort(key=lambda t: (t["line"], t["minutes"][0], t["toward"]))
    lines = live.lines_at(found)
    elevators = [
        {"words": wmata_live.elevator_words(found.name), "where": o.where}
        for o in live.elevators_out(found)
    ][:1]
    return {
        "station": found.name,
        "trains": trains,
        "elevators": elevators,
        "alerts": list(dict.fromkeys(i.text for i in live.incidents_on(lines))),
        "credit": wmata_live.CREDIT,
        "as_of": wmata_live.as_of_iso(live),
    }


# --- Where the next vehicle is, while a rider waits (v0.9.0) -------------------------------

# A bus stop in the timetable this near a step's end is that stop.
STOP_MATCH_M = 40.0
# A bus this near a stop before the boarding one is "at" it, for the stops back.
BUS_NEAR_STOP_M = 300.0


def bus_stops_back(schedule: transit.Schedule | None, route: str, board, alight):
    """A function of a bus's point: how many stops it is before the boarding stop on the
    route's pattern that runs from `board` on to `alight` (the timetable's stop sequence), or
    None where that is not known. None with no timetable."""
    if schedule is None:
        return None
    system = next((s.index for s in schedule.systems if s.name == METROBUS), None)
    if system is None:
        return None

    def stops_at(point) -> set[int]:
        return {
            stop.index for _d, stop in schedule.near(point, STOP_MATCH_M) if stop.system == system
        }

    boarding, alighting = stops_at(board), stops_at(alight)
    found: list[tuple[transit.Pattern, int]] = []
    for stop in boarding:
        for pattern_index, pos in schedule.at_stop.get(stop, ()):
            pattern = schedule.patterns[pattern_index]
            if not wmata_bus.same_route(pattern.route, route):
                continue
            if any(s in alighting for s in pattern.stops[pos + 1 :]):
                found.append((pattern, pos))
    if not found:
        return None

    def back(point) -> int | None:
        best: tuple[float, int] | None = None
        for pattern, pos in found:
            for j in range(pos + 1):
                stop = schedule.stops[pattern.stops[j]]
                d = wmata_live._metres(point, stop.point)
                # At the rider's own stop only when there; a stop before it within reach.
                near = STOP_MATCH_M if j == pos else BUS_NEAR_STOP_M
                if d <= near and (best is None or d < best[0]):
                    best = (d, pos - j)
        return None if best is None else best[1]

    return back


def train_where(
    live: wmata_live.Snapshot | None, board_point, alight_point, line: str, trains
) -> dict | None:
    """Where the next train of `line` the step's way is: {"text", "point", "away", "as_of"}, or
    None (no reading, no station matched, no train coming)."""
    if live is None or trains is None:
        return None
    board = live.station_near(board_point)
    alight = live.station_near(alight_point)
    if board is None or alight is None or board.code == alight.code:
        return None
    approach = wmata_trains.next_train(
        trains, line, set(live.codes(board)), set(live.codes(alight))
    )
    if approach is None:
        return None
    said = wmata_trains.words(approach, live)
    if said is None:
        return None
    text, point = said
    return {"text": text, "point": point, "away": approach.away, "as_of": trains.as_of}


def vehicle_out(kind: str, found: dict | None) -> dict | None:
    """The answer's `vehicle`: the words, the map point and the mark's name, the count to say
    again only when it changes, the credit and the reading's time."""
    if found is None:
        return None
    noun = "bus" if kind == "bus" else "train"
    return {
        "kind": kind,
        "text": found["text"],
        # A train's words already say "Next Red Line train ..."; a bus's start "Bus 52 is ...".
        "label": f"{'Next bus: ' if noun == 'bus' else ''}{found['text'].rstrip('.')}"
        f" ({wmata_live.CREDIT}, live)",
        "point": found["point"],
        "away": found["away"],
        "credit": wmata_live.CREDIT,
        "source": "live",
        "as_of": wmata_live.wall_iso(found["as_of"]),
    }
