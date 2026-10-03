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
- A leg boundary (a via point, named "Stop N") is its own entry, and a stretch
  never spans it.
- A turn names the street it turns onto and, where the junction model has read
  the junction, its control ("at a signal") and, where it flagged it, its
  severity ("Higher stress junction" / "Very high stress junction"). Where the
  model did not read a junction nothing is claimed about its control.
- Flagged junctions that are not a change of street (crossing a busy road) are
  entries of their own, except on a Mass Ride, where signalized crossings that run
  within a quarter mile of one another are one entry (OWNER-DECISIONS 233 and 234):
  its span, how many, the first three streets crossed and how many are LTS 4. It is
  worded in both the full list and the overview (`group_sentence`); the full list
  also names each crossing of it, with its mile marker (`group_crossings`,
  OWNER-DECISIONS 248). A group never spans a stop (item 247,
  `intersections.number_groups`).
- Distances are scaled so the last stretch ends at the route's length.
- The overview (OWNER-DECISIONS 226) is the same route with stretches under
  OVERVIEW_M (0.25 mi) merged into a neighbour of their own leg, so it never
  spans a stop. It never hides or understates: a stretch of LTS 3 or worse merges
  only into a neighbour at least as stressful, a calm stretch (LTS 1-2) is never
  merged with a busy one, a merged stretch is worded at its most stressful tier,
  a stretch that begins at a flagged junction is never merged away, and the stops
  and the separate flagged-junction entries are the full description's, unchanged.
  `describe_both` answers both lists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .intersections import Control, CrossingGroup, Movement, crossing_groups, movement_of

METRES_PER_MILE = 1609.344
FEET_PER_METRE = 3.28084

# A stretch shorter than 300 ft is not worth a line of its own.
TINY_M = 300.0 / FEET_PER_METRE
# Below a tenth of a mile the range would read "0.3 to 0.3 mi": say the length.
SHORT_M = METRES_PER_MILE / 10
# The overview merges stretches under a quarter of a mile (OWNER-DECISIONS 226).
OVERVIEW_M = METRES_PER_MILE / 4
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


def _runs_of(atoms: list[Atom], leg: int) -> list[_Run]:
    """A leg's runs: atoms that are the same edge (the trace cuts one edge at
    every shape vertex) are one run without being made into a run each."""
    runs: list[_Run] = []
    previous: Atom | None = None
    for atom in atoms:
        if atom.metres <= 0:
            continue
        if (
            previous is not None
            and atom.names == previous.names
            and atom.tier == previous.tier
            and atom.facility == previous.facility
        ):
            run = runs[-1]
            run.metres += atom.metres
            run.last = atom
            run.path = run.path or atom.use in PATH_USES
        else:
            runs.append(_run_of(atom, leg))
        previous = atom
    return runs


def _same_street(a: _Run, b: _Run) -> bool:
    if not a.names and not b.names:
        return True
    return bool(a.names & b.names)


def _same(a: _Run, b: _Run) -> bool:
    return a.tier == b.tier and a.facility == b.facility and _same_street(a, b)


def _join(a: _Run, b: _Run) -> None:
    """Fold `b`, which follows `a`, into `a`. `b`'s names, and the heading `a` is
    left on, are `a`'s only where `b` is `a`'s street: a short stretch of another
    street folded in must not make the two one street, and the turn onto the next
    stretch is still read from the street `a` is."""
    if _same_street(a, b):
        a.names |= b.names
        a.label = a.label or b.label
        a.path = a.path or b.path
        a.last = b.last
    a.metres += b.metres


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
                if _same_street(run, target):
                    target.names |= run.names
                    target.label = target.label or run.label
                    target.path = target.path or run.path
                    # The turn into the stretch is where its own street begins.
                    target.first = run.first
                target.metres += run.metres
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
    """The road an event is about, as it is mapped ("MacArthur Boulevard", "I-395");
    None where the router had no name. An event made without the mapped names
    (`road_display`) has the lower-case keys, made readable."""
    shown = [n for n in event.road_display if not n.startswith("way ")]
    if shown:
        return street_label(shown)
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


MAX_NAMED_STREETS = 3


def group_streets(group: CrossingGroup) -> list[str]:
    """The streets a group crosses, as mapped, in route order and each once."""
    seen: set[str] = set()
    streets: list[str] = []
    for event in group.members:
        name = _event_name(event)
        if name and name.lower() not in seen:
            seen.add(name.lower())
            streets.append(name)
    return streets


def _streets_words(streets: list[str]) -> str:
    """ " (A, B, C and 3 more)": the first MAX_NAMED_STREETS, then how many are left."""
    if not streets:
        return ""
    shown = streets[:MAX_NAMED_STREETS]
    more = len(streets) - len(shown)
    if more > 0:
        listed = ", ".join(shown) + f" and {more} more"
    elif len(shown) > 1:
        listed = ", ".join(shown[:-1]) + " and " + shown[-1]
    else:
        listed = shown[0]
    return f" ({listed})"


# The legend's words for LTS 4 (TIER_NOUNS in `routemaker.intersections`), with
# the number after them, as the rest of the description says a tier.
LTS4_ROAD = "heavy-traffic road (LTS 4)"
LTS4_ROADS = "heavy-traffic roads (LTS 4)"


def _lts4_words(lts4: int, count: int) -> str:
    """How many of a group's crossed roads are LTS 4 (or Avoid), in words: ", 1 of
    them a heavy-traffic road (LTS 4)", ", 2 of them heavy-traffic roads (LTS 4)",
    ", all of them heavy-traffic roads (LTS 4)"; nothing where none."""
    if lts4 <= 0:
        return ""
    if lts4 == 1:
        return f", 1 of them a {LTS4_ROAD}"
    return f", all of them {LTS4_ROADS}" if lts4 == count else f", {lts4} of them {LTS4_ROADS}"


# What a group is, in plain US English ("signalized" was UK spelling, and the
# rest of the copy says "at a signal"; spec and a11y re-checks of 2b0cf00).
GROUP_NOUN = "crossings with traffic signals"


def group_words(group: CrossingGroup, start_m: float, end_m: float) -> str:
    """A group of signalized crossings as one phrase, with no severity and no full
    stop: "1.0 to 1.6 mi (1.6 to 2.6 km): 6 crossings with traffic signals (17th
    Street Northwest, 15th Street Northwest, 14th Street Northwest and 3 more), 2 of
    them heavy-traffic roads (LTS 4)". `start_m` and `end_m` are where the first and
    the last crossing are, in whatever measure the caller shows."""
    return (
        f"{range_words(start_m, end_m)}: {group.count} {GROUP_NOUN}"
        f"{_streets_words(group_streets(group))}{_lts4_words(group.lts4, group.count)}"
    )


def group_crossings(group: CrossingGroup, scale: float = 1.0) -> list[dict]:
    """A group's crossings one by one, for the full description and the text and
    GPX cue sheets (OWNER-DECISIONS 248: "a group lists its crossings with their
    mile markers as sub-entries"): where each is, its street, its severity and the
    crossed road's tier, and one sentence, worded as a junction entry is ("At 1.1 mi
    (1.8 km): Cross 17th Street Northwest (LTS 4) at a signal (Very high stress
    junction)."). Every street of the group is named here, so none is said only as
    "and 3 more"."""
    rows = []
    for event in group.members:
        at_m = event.m * scale
        rows.append(
            {
                "from_m": round(at_m),
                "from_mi": round(at_m / METRES_PER_MILE, 2),
                "street": _event_name(event),
                "severity": event.severity,
                "crossed_tier": event.crossed_tier,
                "text": _point_sentence(event, at_m),
            }
        )
    return rows


def group_sentence(group: CrossingGroup, start_m: float, end_m: float) -> str:
    """The group as a description entry: its phrase, then its severity in words, so
    a colour is never the only way to hear it ("Very high stress junctions")."""
    return f"{group_words(group, start_m, end_m)} ({SEVERITY_WORDS[group.severity]} junctions)."


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
    run: _Run,
    start_m: float,
    end_m: float,
    turn: _Turn | None,
    same_street_continues: bool,
    then: str = "",
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
    return f"{where}: {lead}{then}, {words}."


MAX_NAMED_TURNS = 3


def _then_words(streets: list[tuple[str, str | None]]) -> str:
    """ ", then left on A, B and right on C and 2 more turns": the other streets
    a merged stretch runs along, each with its turn where it is a left or a right
    (a street straight on is just named), at most MAX_NAMED_TURNS of them."""
    if not streets:
        return ""
    pieces = []
    for street, movement in streets[:MAX_NAMED_TURNS]:
        pieces.append(f"{movement} on {street}" if movement in ("left", "right") else street)
    more = len(streets) - MAX_NAMED_TURNS
    if more > 0:
        listed = ", ".join(pieces) + f" and {more} more turn{'s' if more > 1 else ''}"
    elif len(pieces) == 1:
        listed = pieces[0]
    else:
        listed = ", ".join(pieces[:-1]) + " and " + pieces[-1]
    return f", then {listed}"


def _flagged_turn(turns: dict[int, _Turn], i: int) -> bool:
    turn = turns.get(i)
    return turn is not None and turn.event is not None and bool(turn.event.flagged)


def _overview_groups(runs: list[_Run], turns: dict[int, _Turn]) -> list[list[int]]:
    """Which runs the overview makes one entry: contiguous index ranges [first,
    last]. A group under OVERVIEW_M folds into the neighbour of its own leg (never
    across a stop) that keeps the wording true: a stretch of LTS 3 or worse only
    into one at least as stressful; never an untraced one (a leg of its own), nor
    one rated against one not rated; nor a calm stretch (LTS 1-2) with a busy one; nothing that
    begins at a flagged junction is folded away, and nothing is folded in front
    of one (its turn would no longer begin the entry)."""
    groups: list[list[int]] = [[i, i] for i in range(len(runs))]

    def metres(group: list[int]) -> float:
        return sum(runs[k].metres for k in range(group[0], group[1] + 1))

    def rank(group: list[int]) -> int:
        return max(_rank(runs[k]) for k in range(group[0], group[1] + 1))

    def facilities(group: list[int]) -> set[str]:
        return {runs[k].facility for k in range(group[0], group[1] + 1)}

    def tiers(group: list[int]) -> set[str]:
        return {runs[k].tier for k in range(group[0], group[1] + 1)}

    def joinable(a: list[int], b: list[int]) -> bool:
        ra, rb = runs[a[0]], runs[b[0]]
        return (
            # An untraced leg is one run of a leg of its own: the leg rule keeps it
            # out of every merge.
            ra.leg == rb.leg
            and (ra.tier == "unknown") == (rb.tier == "unknown")
            # A calm stretch is never worded as busy, nor a busy one as calm.
            and (rank(a) >= 3) == (rank(b) >= 3)
        )

    while True:
        candidates = [
            (metres(g), n)
            for n, g in enumerate(groups)
            if metres(g) < OVERVIEW_M and not _flagged_turn(turns, g[0])
        ]
        folded = False
        for _size, n in sorted(candidates):
            group = groups[n]
            before = groups[n - 1] if n > 0 else None
            after = groups[n + 1] if n + 1 < len(groups) else None
            options = []
            if before is not None and joinable(before, group):
                options.append(before)
            if after is not None and joinable(group, after) and not _flagged_turn(turns, after[0]):
                options.append(after)
            # LTS 3 has no calmer busy neighbour: only LTS 4 and Avoid need this.
            if rank(group) > 3:
                options = [o for o in options if rank(o) >= rank(group)]
            if not options:
                continue

            def preference(o: list[int], group=group, after=after) -> tuple:
                same_kind = tiers(o) == tiers(group) and facilities(o) == facilities(group)
                same_street = _same_street(runs[o[0]], runs[group[0]])
                return (not same_kind, not same_street, -metres(o), o is after)

            options.sort(key=preference)
            target = options[0]
            if target is before:
                before[1] = group[1]
            else:
                after[0] = group[0]
            del groups[n]
            folded = True
            break
        if not folded:
            return groups


def _group_run(
    runs: list[_Run], group: list[int], turns: dict[int, _Turn] | None = None
) -> tuple[_Run, str]:
    """A merged group as one run to word, and its ", then ..." clause: the most
    stressful tier of its members, a facility only if they share one, the street
    it begins on and the other streets in order, each with the turn onto it."""
    members = runs[group[0] : group[1] + 1]
    first = members[0]
    if len(members) == 1:
        return first, ""
    worst = max(members, key=_rank)
    facilities = {m.facility for m in members}
    merged = _Run(
        metres=sum(m.metres for m in members),
        tier=worst.tier,
        facility=first.facility if len(facilities) == 1 else "none",
        names=first.names,
        label=first.label,
        first=first.first,
        last=members[-1].last,
        path=first.path,
        leg=first.leg,
    )
    own = _street_words(first)
    streets: list[tuple[str, str | None]] = []
    for k, m in zip(range(group[0] + 1, group[1] + 1), members[1:], strict=True):
        if m.label and m.label != own and m.label not in (s for s, _m in streets):
            turn = (turns or {}).get(k)
            streets.append((m.label, turn.movement if turn else None))
    return merged, _then_words(streets)


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
    """The route's full description (see `describe_both`)."""
    return describe_both(legs, events, total_m)[0]


def describe_both(
    legs: list[list[Atom] | float],
    events: list | None = None,
    total_m: float | None = None,
) -> tuple[list[dict], list[dict]]:
    """The route's full description and its overview, each in route order.

    `legs` has one item per leg, in order: the leg's atoms, or the length in
    metres of a leg that could not be traced. `events` are the junction events
    (`routemaker.intersections.Event`), flagged or not, or None. `total_m` is the
    route's length as the router states it: distances are scaled so the
    description ends there (a trace measures a little differently). Each entry
    is a dict: `kind` ("stretch", "junction" or "via"), `from_m` and `to_m`
    (whole metres), `from_mi` and `to_mi` (miles to a hundredth), `street`,
    `tier` (1-5 or None), `facility` or None, `turn` (None or a dict), `severity`
    ("orange", "red" or None), `via` (the point's number, for a "via"), `group` (a
    dict - `number`, `count`, `lts4`, `streets`, `more`, and `crossings`, each
    crossing's `group_crossings` row in the full list and None in the overview -
    on the entry for a Mass Ride's group of signalized crossings, else None),
    `text`.
    The overview has the same entries with the short stretches merged (see the
    module's rules); its stops and junction entries are the full ones.
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
        leg_runs = _coalesce(_runs_of(content, leg))
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
    shared: list[tuple[tuple[float, int, int], dict]] = []
    for i, run in enumerate(runs):
        start, end = starts[i] * scale, (starts[i] + run.metres) * scale
        if i == 0 or runs[i - 1].leg != run.leg:
            if i > 0:
                number = run.leg
                shared.append(
                    (
                        (start, 0, i),
                        _entry(
                            "via",
                            start,
                            start,
                            f"Stop {number} at {point_words(start)}.",
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
    by_group = {g.number: g for g in crossing_groups(events)}
    said: set[int] = set()
    # A group's entry in each list: the full one with its crossings (item 248).
    full_only: list[tuple[tuple[float, int, int], dict]] = []
    short_only: list[tuple[tuple[float, int, int], dict]] = []
    for index, event in enumerate(events):
        if index in used or not event.flagged:
            continue
        if event.group in by_group:
            # A group of signalized crossings (items 233 and 234) is one entry, at
            # its first crossing, which counts every crossing of it, a crossing
            # that is also the turn into a stretch included.
            if event.group in said:
                continue
            said.add(event.group)
            group = by_group[event.group]
            from_at, to_at = group.from_m * scale, group.to_m * scale
            streets = group_streets(group)
            summary = {
                "number": group.number,
                "count": group.count,
                "lts4": group.lts4,
                "streets": streets[:MAX_NAMED_STREETS],
                "more": max(len(streets) - MAX_NAMED_STREETS, 0),
            }
            # The full list names each crossing under the group (item 248); the
            # overview keeps one line per group.
            for target, crossings in (
                (full_only, group_crossings(group, scale)),
                (short_only, None),
            ):
                target.append(
                    (
                        (from_at, 2, index),
                        _entry(
                            "junction",
                            from_at,
                            to_at,
                            group_sentence(group, from_at, to_at),
                            severity=group.severity,
                            group={**summary, "crossings": crossings},
                        ),
                    )
                )
            continue
        at_m = event.m * scale
        shared.append(
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
    overview: list[tuple[tuple[float, int, int], dict]] = []
    for first, last in _overview_groups(runs, turns):
        run, then = _group_run(runs, [first, last], turns)
        start = starts[first] * scale
        end = (starts[last] + runs[last].metres) * scale
        turn = turns.get(first)
        continues = first > 0 and runs[first - 1].leg == runs[first].leg
        severity = None
        if turn is not None and turn.event is not None and turn.event.flagged:
            severity = turn.event.severity
        overview.append(
            (
                (start, 1, first),
                _entry(
                    "stretch",
                    start,
                    end,
                    _stretch_sentence(run, start, end, turn, continues, then),
                    street=_street_words(runs[first]),
                    tier=int(run.tier) if run.tier.isdigit() else None,
                    facility=None if run.facility in ("unknown", "none") else run.facility,
                    turn=None
                    if turn is None
                    else {
                        "movement": turn.movement,
                        "onto": _street_words(runs[first]),
                        "control": turn.event.control.value if turn.event is not None else None,
                        "severity": severity,
                    },
                    severity=severity,
                ),
            )
        )
    full = sorted(entries + shared + full_only, key=lambda pair: pair[0])
    short = sorted(overview + shared + short_only, key=lambda pair: pair[0])
    return [e for _k, e in full], [e for _k, e in short]


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
        "group": None,
        "text": text,
    }
    entry.update(fields)
    return entry


def plain_text(entries: list[dict]) -> str:
    """The description as a text cue sheet, one entry to a line, and a group's
    crossings (full detail, item 248) each on a line of its own under it, set in."""
    lines = []
    for entry in entries:
        lines.append(entry["text"])
        for crossing in (entry.get("group") or {}).get("crossings") or ():
            lines.append(f"    {crossing['text']}")
    return "\n".join(lines)


__all__ = [
    "Atom",
    "Control",
    "Movement",
    "OVERVIEW_M",
    "describe",
    "describe_both",
    "group_crossings",
    "group_sentence",
    "group_words",
    "plain_text",
    "range_words",
    "readable",
    "street_label",
    "tier_words",
]
