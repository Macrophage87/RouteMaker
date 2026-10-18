"""Live values on the transit plans and station cards (v0.7.0): WMATA's next trains, its rail
incidents and its elevator outages (`core.wmata_live`), laid over the timetable's answer.

Nothing here replaces the timetable. A plan is still searched and timed on the schedule
(`core.transit`), and every time it gives still says "scheduled". Where a live reading is to
hand, the plan and the station card add, each marked "live" and credited "Data: WMATA":

- the next trains at a Metro step's boarding station, the way the step goes ("Live: Red Line
  toward Shady Grove in 3 min, 11 min");
- the next buses at a Metrobus step's boarding stop, the way the step goes ("Live: bus 52 in 4
  min, 13 min"; v0.9.0, core.wmata_bus);
- WMATA's rail incidents on the lines the trip uses;
- an elevator out at a station where the rider takes their own bike: "Elevator out at Gallery
  Place: carry your bike on the stairs." It is a warning, not an avoidance (the owner,
  2026-10-13 11:17 UTC: "many people can walk their bike upstairs"); the trip costs
  `ELEVATOR_OUT_S` more when the options are ranked, so a station whose elevator works wins a
  near-tie, and the times the rider sees are unchanged.

With no live reading (no key, or WMATA not answering) nothing is added: the timetable's answer
is the fallback, and it says "scheduled" as before.
"""

from __future__ import annotations

import math
import time
from dataclasses import replace

from . import presets, transit, wmata_bus, wmata_live, wmata_trains

# The ranking cost of an elevator out on the way (2 min): enough to break a near-tie.
ELEVATOR_OUT_S = 120.0
METRO = "Metro"
METROBUS = wmata_bus.METROBUS
# Trains shown per direction.
TRAINS_SHOWN = 2


def _metro_ends(leg: transit.Leg, live: wmata_live.Snapshot):
    """A Metro leg's boarding and alighting stations, as WMATA names them (or None)."""
    if not leg.transit or leg.system != METRO or not leg.coordinates:
        return None, None
    return live.station_near(leg.coordinates[0]), live.station_near(leg.coordinates[-1])


def _outage_stations(option: transit.Option, live: wmata_live.Snapshot) -> list[str]:
    """The stations, in trip order, where the rider's own bike needs an elevator that is out."""
    out: list[str] = []
    for leg in option.legs:
        if not leg.bike:
            continue
        for station in _metro_ends(leg, live):
            if station is not None and live.elevators_out(station) and station.name not in out:
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


def rank(plan: transit.Plan, live: wmata_live.Snapshot | None) -> transit.Plan:
    """The plan's options ranked again with `ELEVATOR_OUT_S` added to a trip that takes the
    rider's own bike through a station whose elevator is out (Own Bike + 🚆🚌 only). The times
    are unchanged; only the order may move."""
    if live is None or plan.mode != presets.BIKE_TRANSIT or not plan.options:
        return plan
    cost = {o.key: ELEVATOR_OUT_S * len(_outage_stations(o, live)) for o in plan.options}
    if not any(cost.values()):
        return plan
    chosen = plan.options[plan.chosen].key

    def key(o: transit.Option):
        total = o.total_s + cost[o.key]
        return (transit.minutes(total), sum(leg.transit for leg in o.legs), total, o.key)

    options = sorted(plan.options, key=key)
    index = 0 if plan.chosen == 0 else next(i for i, o in enumerate(options) if o.key == chosen)
    return replace(plan, options=options, chosen=index)


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


def step_live(leg: transit.Leg, live: wmata_live.Snapshot) -> dict | None:
    """A Metro step's next trains now, its way: {"text", "minutes"}, or None."""
    board, alight = _metro_ends(leg, live)
    if board is None:
        return None
    lines = set(leg.lines)
    trains = [
        t
        for t in live.trains_at(board)
        if (not lines or any(wmata_live.same_line(t.line, line) for line in lines))
        and _toward(t, board, alight, live)
    ]
    trains.sort(key=lambda t: t.minutes if t.minutes is not None else 99)
    trains = [t for t in trains if t.minutes is not None]
    if not trains:
        return None
    first = trains[0]
    return {
        "text": f"Live: {first.line} toward {first.destination} in {_when(trains)}.",
        "minutes": [t.minutes for t in trains[:TRAINS_SHOWN]],
        "source": "live",
    }


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
