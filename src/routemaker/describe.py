"""The route as words: a stretch-by-stretch description, for a rider who reads
or hears the route rather than seeing the map (OWNER-DECISIONS 220: many blind
cyclists ride as tandem stokers).

Everything here is pure: it reads what the planner already has - the traced
pieces with their street names, headings, stress tier and facility class, and
the junction events - and adds no router call and no query. `core.routing.plan`
hands it the pieces; `describe` answers a list of entries, each with its
distances (metres and miles), street, tier, facility, how the rider turns into
it, and one `text` sentence.

The rules:

- Consecutive pieces on one street (a name in common, or both unnamed) with one
  tier and one facility are one stretch. A new street, tier or facility is a new
  stretch; a turn is never merged away.
- A stretch under TINY_M (300 ft) is folded into a neighbour (on its own street
  if there is one, else the longer). One of LTS 3 or worse goes only into a
  neighbour at least as stressful, so it is never hidden or understated; an
  untraced one is never folded.
- A leg boundary (a via point) is its own entry, and a stretch never spans it.
- A turn names the street it turns onto and, where the junction model has read
  the junction, its control ("at a signal") and, where it flagged it, its
  severity ("Higher stress junction" / "Very high stress junction"). Where the
  model did not read a junction nothing is claimed about its control.
- Flagged junctions that are not a change of street (crossing a busy road) are
  entries of their own.
- Distances are scaled so the last stretch ends at the route's length.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .intersections import Control, Movement, movement_of

METRES_PER_MILE = 1609.344
FEET_PER_METRE = 3.28084

# A stretch shorter than 300 ft is not worth a line of its own.
TINY_M = 300.0 / FEET_PER_METRE
# Below a tenth of a mile the range would read "0.3 to 0.3 mi": say the length.
SHORT_M = METRES_PER_MILE / 10
# How far from a change of street an event still is that junction.
MATCH_M = 30.0
# Tiers that are never folded into a neighbour.
NEVER_HIDDEN = frozenset({"3", "4", "5"})

SEVERITY_WORDS = {"orange": "Higher stress", "red": "Very high stress"}

# The legend's own words (frontend/src/stressStyle.js, routeColours.ts), plain.
TIER_WORDS = {
    "1": "low stress (LTS 1)",
    "2": "fairly low stress (LTS 2)",
    "3": "busy road (LTS 3)",
    "4": "heavy traffic (LTS 4)",
    "5": "Avoid (legal, but best avoided)",
}
UNRATED_WORDS = "stress not rated"
UNNAMED_PATH = "unnamed path"
PATH_WORDS = "traffic-free path"
FACILITY_WORDS = {"protected": "protected bike lane", "lane": "painted bike lane"}

# Valhalla's `use` of an edge that is a path rather than a road.
PATH_USES = frozenset(
    {"cycleway", "footway", "path", "mountain_bike", "sidewalk", "pedestrian", "bridleway", "track"}
)

CONTROL_PHRASES = {
    Control.SIGNAL: " at a signal",
    Control.STOP: " at a stop sign",
    Control.ALL_STOP: " at an all-way stop",
    Control.CROSS_STOP: " where cross traffic stops",
}

# "MD 355", "US-29", "I 495", "VA 7": a route number rather than a street name.
_ROUTE_NUMBER = re.compile(r"^(?:[A-Z]{1,3})[ -]?\d+[A-Z]?$")
# What stays in capitals when a lower-case street name is made readable.
_CAPITALS = frozenset(
    {"nw", "ne", "sw", "se", "md", "va", "dc", "us", "mlk", "jr", "sr", "ii", "iii"}
)


def street_label(names: tuple[str, ...] | list[str] | frozenset[str]) -> str | None:
    """The name to say for a road's names: the first that is not a route number
    ("Rockville Pike", not "MD 355"), or the first. None where it has none."""
    ordered = list(names)
    for name in ordered:
        if not _ROUTE_NUMBER.match(name.strip()):
            return name.strip()
    return ordered[0].strip() if ordered else None


def readable(name: str) -> str:
    """A lower-case street name (the junction model keeps them so) in capitals
    a reader can say: "wisconsin avenue" is "Wisconsin Avenue". A name that has
    capitals already is left alone."""
    if name != name.lower():
        return name
    words = []
    for word in name.split():
        words.append(word.upper() if word in _CAPITALS else word[:1].upper() + word[1:])
    return " ".join(words)


@dataclass(frozen=True)
class Atom:
    """One piece of the traced route, as this module reads it."""

    metres: float
    tier: str  # "1".."5" or "unknown"
    facility: str  # "path", "protected", "lane", "none" or "unknown"
    names: tuple[str, ...] = ()
    use: str = ""
    heading_in: float | None = None
    heading_out: float | None = None


@dataclass
class _Run:
    """A stretch being built."""

    metres: float
    tier: str
    facility: str
    names: frozenset[str]
    label: str | None
    first: Atom | None
    last: Atom | None
    path: bool
    untraced: bool = False
    leg: int = 0


def _run_of(atom: Atom, leg: int) -> _Run:
    return _Run(
        metres=atom.metres,
        tier=atom.tier,
        facility=atom.facility,
        names=frozenset(n.lower() for n in atom.names),
        label=street_label(atom.names),
        first=atom,
        last=atom,
        path=atom.use in PATH_USES,
        leg=leg,
    )


def _same_street(a: _Run, b: _Run) -> bool:
    if not a.names and not b.names:
        return True
    return bool(a.names & b.names)


def _same(a: _Run, b: _Run) -> bool:
    return a.tier == b.tier and a.facility == b.facility and _same_street(a, b)


def _join(a: _Run, b: _Run) -> None:
    """Fold `b`, which follows `a`, into `a`."""
    a.metres += b.metres
    a.names |= b.names
    a.label = a.label or b.label
    a.last = b.last
    a.path = a.path or b.path


def _coalesce(runs: list[_Run]) -> list[_Run]:
    """Join neighbours of one street, tier and facility. One leg's runs: a leg
    is folded and joined on its own, so nothing spans a via point."""
    out: list[_Run] = []
    for run in runs:
        if out and _same(out[-1], run):
            _join(out[-1], run)
        else:
            out.append(run)
    return out


def _rank(run: _Run) -> int:
    """How stressful a stretch is for the folding rule: its tier, 0 if unrated."""
    return int(run.tier) if run.tier.isdigit() else 0


def _absorb_tiny(runs: list[_Run]) -> list[_Run]:
    """Fold each stretch under TINY_M of one traced leg into a neighbour: the one
    on its own street if there is one, else the longer (the earlier on a tie). A
    stretch of LTS 3 or worse goes only into a neighbour at least as stressful, so
    the description never says less than the route is. (An untraced leg is one
    run and is never given to this.)"""
    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(runs):
            run = runs[i]
            if run.metres >= TINY_M:
                i += 1
                continue
            before = runs[i - 1] if i > 0 else None
            after = runs[i + 1] if i + 1 < len(runs) else None
            options = [n for n in (before, after) if n is not None]
            if run.tier in NEVER_HIDDEN:
                options = [n for n in options if _rank(n) >= _rank(run)]
            if not options:
                i += 1
                continue
            options.sort(key=lambda n: (not _same_street(run, n), -n.metres, n is after))
            target = options[0]
            if target is before:
                _join(before, run)
            else:
                # The tiny one's start becomes the neighbour's: its heading in.
                target.metres += run.metres
                target.names |= run.names
                target.label = target.label or run.label
                target.first = run.first
                target.path = target.path or run.path
            del runs[i]
            changed = True
        coalesced = _coalesce(runs)
        if len(coalesced) != len(runs):
            changed = True
        runs = coalesced
    return runs


def tier_words(tier: str, facility: str) -> str:
    """How the stretch's traffic is said: the legend's words, the facility after."""
    if facility == "path":
        return PATH_WORDS
    words = TIER_WORDS.get(tier, UNRATED_WORDS)
    extra = FACILITY_WORDS.get(facility)
    return f"{words}, {extra}" if extra else words


def _miles(metres: float) -> str:
    return f"{metres / METRES_PER_MILE:.1f}"


def _km(metres: float) -> str:
    return f"{metres / 1000:.1f}"


def _feet(metres: float) -> int:
    value = metres * FEET_PER_METRE
    return int(round(value, -1)) if value >= 100 else int(round(value))


def range_words(start_m: float, end_m: float) -> str:
    """ "0.0 to 1.2 mi (0.0 to 1.9 km)": miles first, the metric once, "to" and not a
    dash, which a screen reader may say as "dash" or not at all."""
    if end_m - start_m < SHORT_M:
        return (
            f"{_miles(start_m)} mi ({_km(start_m)} km), for {_feet(end_m - start_m)} ft "
            f"({round(end_m - start_m)} m)"
        )
    return f"{_miles(start_m)} to {_miles(end_m)} mi ({_km(start_m)} to {_km(end_m)} km)"


def point_words(at_m: float) -> str:
    return f"{_miles(at_m)} mi ({_km(at_m)} km)"


def _event_name(event) -> str | None:
    """The road an event is about, in capitals; None where the router had no name."""
    names = sorted(n for n in event.road_names if not n.startswith("way "))
    label = street_label(names)
    return readable(label) if label else None


def _crossed(tier: int | None) -> str:
    return {3: " (LTS 3)", 4: " (LTS 4)", 5: " (Avoid)"}.get(tier or 0, "")


def _control_words(control, flagged: bool) -> str:
    phrase = CONTROL_PHRASES.get(control)
    if phrase is not None:
        return phrase
    # Nothing in the data. Said only where the junction was flagged: that is
    # when "no signal mapped" is what the rider needs to know.
    return ", no signal mapped" if flagged else ""


def _severity_suffix(severity: str | None) -> str:
    return f" ({SEVERITY_WORDS[severity]} junction)" if severity in SEVERITY_WORDS else ""


_POINT_VERBS = {
    "crossing": "Cross",
    "slip_lane": "Cross a slip lane off",
    "left_across": "Left turn across",
    "left_from": "Left turn across",
    "right_from": "Right turn off",
    "left_onto": "Left turn onto",
    "right_onto": "Right turn onto",
    "straight_onto": "Join",
    "along": "Pass side streets along",
}


def _point_sentence(event, at_m: float) -> str:
    name = _event_name(event)
    verb = _POINT_VERBS.get(event.kind, "Pass a junction with")
    what = (
        (name + _crossed(event.crossed_tier))
        if name
        else "a busy road" + _crossed(event.crossed_tier)
    )
    return (
        f"At {point_words(at_m)}: {verb} {what}"
        f"{_control_words(event.control, True)}{_severity_suffix(event.severity)}."
    )


@dataclass
class _Turn:
    movement: str | None
    event: object | None = None


def _movement_between(before: _Run, after: _Run) -> str | None:
    a = before.last.heading_out if before.last else None
    b = after.first.heading_in if after.first else None
    if a is None or b is None:
        return None
    return movement_of(a, b).value


def _street_words(run: _Run) -> str:
    if run.untraced:
        return "this part of the route"
    if run.label:
        return run.label
    return UNNAMED_PATH if run.facility in ("path", "protected") or run.path else "unnamed road"


def _stretch_sentence(
    run: _Run, start_m: float, end_m: float, turn: _Turn | None, same_street_continues: bool
) -> str:
    street = _street_words(run)
    where = range_words(start_m, end_m)
    if run.untraced:
        return f"{where}: no street details for this part of the route, {UNRATED_WORDS}."
    event = turn.event if turn else None
    if turn is not None:
        movement = turn.movement
        if movement == "left":
            lead = f"Left onto {street}"
        elif movement == "right":
            lead = f"Right onto {street}"
        else:
            lead = f"Continue onto {street}"
        if event is not None:
            lead += _control_words(event.control, event.flagged)
            lead += _severity_suffix(event.severity if event.flagged else None)
    elif same_street_continues:
        lead = f"Continue on {street}"
    else:
        lead = street
    words = tier_words(run.tier, run.facility)
    if words == PATH_WORDS and street == UNNAMED_PATH:
        words = "traffic-free"
    return f"{where}: {lead}, {words}."


def _nearest_event(events: list, at_m: float, used: set[int]):
    best, best_gap = None, MATCH_M + 1e-9
    for index, event in enumerate(events):
        if index in used:
            continue
        gap = abs(event.m - at_m)
        if gap < best_gap:
            best, best_gap = index, gap
    return best


def describe(
    legs: list[list[Atom] | float],
    events: list | None = None,
    total_m: float | None = None,
) -> list[dict]:
    """The route's description, in route order.

    `legs` has one item per leg, in order: the leg's atoms, or the length in
    metres of a leg that could not be traced. `events` are the junction events
    (`routemaker.intersections.Event`), flagged or not, or None. `total_m` is the
    route's length as the router states it: distances are scaled so the
    description ends there (a trace measures a little differently). Each entry
    is a dict: `kind` ("stretch", "junction" or "via"), `from_m` and `to_m`
    (whole metres), `from_mi` and `to_mi` (miles to a hundredth), `street`,
    `tier` (1-5 or None), `facility` or None, `turn` (None or a dict), `severity`
    ("orange", "red" or None), `via` (the point's number, for a "via"), `text`.
    """
    runs: list[_Run] = []
    for leg, content in enumerate(legs):
        if isinstance(content, (int, float)):
            if content > 0:
                runs.append(
                    _Run(
                        float(content),
                        "unknown",
                        "unknown",
                        frozenset(),
                        None,
                        None,
                        None,
                        False,
                        True,
                        leg,
                    )
                )
            continue
        leg_runs = _coalesce([_run_of(atom, leg) for atom in content if atom.metres > 0])
        runs.extend(_absorb_tiny(leg_runs))
    traced = sum(run.metres for run in runs)
    scale = total_m / traced if total_m and total_m > 0 and traced > 0 else 1.0
    events = sorted(events or [], key=lambda e: e.m)

    # Positions along the route, as the pieces measure them: the junction events
    # are placed in the same measure; both are scaled for display after.
    starts: list[float] = []
    at = 0.0
    for run in runs:
        starts.append(at)
        at += run.metres

    used: set[int] = set()
    turns: dict[int, _Turn] = {}
    for i, run in enumerate(runs):
        if i == 0 or runs[i - 1].leg != run.leg:
            continue
        before = runs[i - 1]
        if before.untraced or run.untraced or _same_street(before, run):
            continue
        found = _nearest_event(events, starts[i], used)
        if found is not None:
            used.add(found)
        movement = _movement_between(before, run)
        event = events[found] if found is not None else None
        if movement is None and event is not None:
            movement = event.movement.value
        turns[i] = _Turn(movement, event)

    entries: list[tuple[tuple[float, int, int], dict]] = []
    for i, run in enumerate(runs):
        start, end = starts[i] * scale, (starts[i] + run.metres) * scale
        if i == 0 or runs[i - 1].leg != run.leg:
            if i > 0:
                number = run.leg
                entries.append(
                    (
                        (start, 0, i),
                        _entry(
                            "via",
                            start,
                            start,
                            f"Via {number}: stop at {point_words(start)}.",
                            via=number,
                        ),
                    )
                )
        turn = turns.get(i)
        # A stretch that follows another of its leg without a turn is the same street
        # at a new tier or facility.
        continues = i > 0 and runs[i - 1].leg == run.leg
        text = _stretch_sentence(run, start, end, turn, continues)
        severity = None
        if turn is not None and turn.event is not None and turn.event.flagged:
            severity = turn.event.severity
        entries.append(
            (
                (start, 1, i),
                _entry(
                    "stretch",
                    start,
                    end,
                    text,
                    street=_street_words(run),
                    tier=int(run.tier) if run.tier.isdigit() else None,
                    facility=None if run.facility in ("unknown", "none") else run.facility,
                    turn=None
                    if turn is None
                    else {
                        "movement": turn.movement,
                        "onto": _street_words(run),
                        "control": turn.event.control.value if turn.event is not None else None,
                        "severity": severity,
                    },
                    severity=severity,
                ),
            )
        )
    for index, event in enumerate(events):
        if index in used or not event.flagged:
            continue
        at_m = event.m * scale
        entries.append(
            (
                (at_m, 2, index),
                _entry(
                    "junction",
                    at_m,
                    at_m,
                    _point_sentence(event, at_m),
                    street=_event_name(event),
                    severity=event.severity,
                    turn={
                        "movement": event.movement.value,
                        "onto": None,
                        "control": event.control.value,
                        "severity": event.severity,
                    },
                ),
            )
        )
    entries.sort(key=lambda pair: pair[0])
    return [entry for _key, entry in entries]


def _entry(kind: str, start: float, end: float, text: str, **fields) -> dict:
    entry = {
        "kind": kind,
        "from_m": round(start),
        "to_m": round(end),
        "from_mi": round(start / METRES_PER_MILE, 2),
        "to_mi": round(end / METRES_PER_MILE, 2),
        "street": None,
        "tier": None,
        "facility": None,
        "turn": None,
        "severity": None,
        "via": None,
        "text": text,
    }
    entry.update(fields)
    return entry


def plain_text(entries: list[dict]) -> str:
    """The description as a text cue sheet, one entry to a line."""
    return "\n".join(entry["text"] for entry in entries)


__all__ = [
    "Atom",
    "Control",
    "Movement",
    "describe",
    "plain_text",
    "range_words",
    "readable",
    "street_label",
    "tier_words",
]
