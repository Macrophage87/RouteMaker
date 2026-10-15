"""Live values on the transit plans and station cards (v0.7.0): WMATA's next trains, its rail
incidents and its elevator outages (`core.wmata_live`), laid over the timetable's answer.

Nothing here replaces the timetable. A plan is still searched and timed on the schedule
(`core.transit`), and every time it gives still says "scheduled". Where a live reading is to
hand, the plan and the station card add, each marked "live" and credited "Data: WMATA":

- the next trains at a Metro step's boarding station, the way the step goes ("Live: Red Line
  toward Shady Grove in 3 min, 11 min");
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

from dataclasses import replace

from . import presets, transit, wmata_live

# The ranking cost of an elevator out on the way (2 min): enough to break a near-tie.
ELEVATOR_OUT_S = 120.0
METRO = "Metro"
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


def annotate(block: dict, plan: transit.Plan, live: wmata_live.Snapshot | None) -> dict:
    """The route answer's `transit` block with the live values added (in place, and returned):
    each Metro step's `live` (or null), and `live` on the block: the elevator warnings, WMATA's
    incidents on the lines used, the credit and the reading's time; null with no reading."""
    for step in block.get("steps", []):
        step.setdefault("live", None)
    block["live"] = None
    if live is None:
        return block
    option = plan.option
    warnings = [wmata_live.elevator_words(name) for name in _outage_stations(option, live)]
    used: list[str] = []
    for index, leg in enumerate(option.legs):
        if index < len(block["steps"]) and leg.transit and leg.system == METRO:
            block["steps"][index]["live"] = step_live(leg, live)
            used += [line for line in leg.lines if line not in used]
    alerts = [i.text for i in live.incidents_on(used)]
    shown = warnings or alerts or any(s.get("live") for s in block["steps"])
    if not shown:
        return block
    block["live"] = {
        "warnings": warnings,
        "alerts": list(dict.fromkeys(alerts)),
        "credit": wmata_live.CREDIT,
        "as_of": wmata_live.as_of_iso(live),
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
