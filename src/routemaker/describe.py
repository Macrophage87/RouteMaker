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
  untraced one is never folded, nor a jog's middle (`_jog`): a named street,
  not a roundabout or circle, at least JOG_MIN_M long, other than both neighbours,
  entered and left by a turn or a bear ("Right onto 6th Street" then "Bear left
  onto Rhode Island Avenue" is two turns the rider makes, which folding would read
  as one or none: the owner, 2026-10-16, on Q Street). Where the street after is
  the street before, a middle under MATCH_M or one whose turns cancel is a
  divided road or an offset crossing, folded as any other.
- A change of street SLIGHT_MIN_DEG (20 degrees) to BEAR_MAX_DEG (60 degrees) off
  straight is a bear ("Bear right onto ..."); under it, straight on; past it, a
  left or a right. A bend along one street is never a turn. (The routing model's
  own STRAIGHT_MAX_DEG, `intersections.movement_of`, is not this.)
- Nor is the street a leg ends on, under TINY_M, where it is turned onto
  (`_last_turn`): the turn onto the destination's street is said before the
  arrival.
- A fork (`fork_movement`) is a turn even on one street or straight on: where
  another rideable way at the node is as near straight ahead as the route's, or
  nearer, the rider is told which to take ("Bear right to stay on Paint Branch
  Trail": the owner, 2026-10-18, "missing some important turns, especially when it
  seems straight is the default"). A stretch begun at a fork is never folded away.
- A clear turn is said too (`_said_turns`), as a fork is: along one street, a turn of
  more than ALONG_TURN_DEG (45 degrees) at a node where another way meets it ("Left
  to stay on Metropolitan Branch Trail" off the trail onto its side path: the owner,
  2026-10-23, "It missed a clear left turn"); onto any way, a turn of HAIRPIN_DEG or
  more (a turnaround: "Another sharp turnaround missed"). Nodes within JUNCTION_M of
  one another are one junction, and only the sharpest of them is said. Every turn
  and a fork's own way are read from the route's own line over LINE_SPAN_M either
  side of the node, short of the next node (`Atom.turn`), where it was read, not
  from the edges' headings, which a tiny edge at a junction can tilt: a gentle bend
  is never said as a left (Sligo Creek Trail).
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
- A stretch says its surface where the segments say it is unpaved
  (OWNER-DECISIONS 280): ", unpaved" where at least half of it is, ", partly
  unpaved" where at least PARTLY_UNPAVED_M (0.1 mi) is. A change of surface alone
  does not start a stretch.
- A painted lane on LTS 4 or Avoid is worded twice (OWNER-DECISIONS 275): `text`
  calls it a bike lane and `text_lanes_hidden` does not, for the client's "Show
  bike lanes on high-stress roads" switch.
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
from dataclasses import dataclass, replace

from .intersections import (
    STRAIGHT_MAX_DEG,
    Control,
    CrossingGroup,
    Movement,
    crossing_groups,
)

METRES_PER_MILE = 1609.344
FEET_PER_METRE = 3.28084

# A stretch shorter than 300 ft is not worth a line of its own.
TINY_M = 300.0 / FEET_PER_METRE
# Below a tenth of a mile the range would read "0.3 to 0.3 mi": say the length.
SHORT_M = METRES_PER_MILE / 10
# The overview merges stretches under a quarter of a mile (OWNER-DECISIONS 226).
OVERVIEW_M = METRES_PER_MILE / 4
# A change of street this far off straight on, up to BEAR_MAX_DEG (past which it
# is a left or a right), is a bear: the rider leaves the street they were on with
# a lean worth saying (the owner, 2026-10-16: "complex turns which aren't
# announced" on Q Street, where the L'Enfant diagonals leave the grid at 20 to 35
# degrees). The description's own band: the routing model's STRAIGHT_MAX_DEG is
# left as it is.
SLIGHT_MIN_DEG = 20.0
BEAR_MAX_DEG = 60.0
# A jog's middle is at least this long: a shorter piece of another street between
# two turns is a median or a carriageway crossed, not a street ridden.
JOG_MIN_M = 15.0
# A roundabout or circle by its name ("Dupont Circle Northwest"): never a jog's
# middle; the turn is read across it, as the net movement.
CIRCLE_NAME = re.compile(r"\b(?:circle|roundabout)\b", re.IGNORECASE)
# The ways off a circle that are counted as its exits (`circle_exit`): streets.
EXIT_USES = frozenset({"road", "living_street"})
# The words for a turn's movement, where it is one.
TURN_WORDS = {
    "left": "Left",
    "right": "Right",
    "bear_left": "Bear left",
    "bear_right": "Bear right",
}
# A fork: another rideable way at a node within FORK_AHEAD_DEG of straight ahead is
# one a rider could take for the way on, unless the route's own way is nearer
# straight by at least FORK_CLEAR_DEG (then straight on is plainly the route).
FORK_AHEAD_DEG = 45.0
FORK_CLEAR_DEG = 20.0
# Where the route's own way bends off too, a choice up to FORK_CLEAR_DEG beyond it, as far
# as FORK_WIDE_MAX_DEG, is as much the way on: a Y whose two branches each lean 60 degrees
# (the owner, 2026-10-20, on Rock Creek Trail by Norbeck Road: "It missed a trail fork").
# Only on a trail, and only for another trail-like way: a street that curves at a side
# street, or a sidepath at a footway, is no question.
FORK_WIDE_MAX_DEG = 90.0
TRAIL_USES = frozenset({"cycleway", "footway", "path", "mountain_bike", "bridleway", "track"})
# A turn this sharp, read from Valhalla's headings (each over the edge's first or last 30 m
# or so), may have come out the wrong side of straight back: the side is read from the
# route's own line at the node (`turn_between`; the owner, 2026-10-20, on a ramp up to a
# bridge by Veirs Mill Road: "This is a right turn up onto a bridge").
HAIRPIN_DEG = 120.0
# A turn along one street this far off straight, at a node another way meets, is said
# (`_said_turns`): the owner, 2026-10-23, on the Metropolitan Branch Trail, where it
# turns off onto its side path along a road, "It missed a clear left turn".
ALONG_TURN_DEG = 45.0
# The route's own line is read this far either side of a node for its turn there
# (`Atom.turn`, `core.routing._line_headings`).
LINE_SPAN_M = 20.0
# Nodes nearer one another than this are one junction (a kerb or crossing node beside the
# corner): the line is read on past them, and only the sharpest is said (`_said_turns`).
# The line stops at a node further off, so a turn there never tilts this one.
JUNCTION_M = 5.0
# A short path stretch between two turns that crosses a road (a junction event across it,
# or a crosswalk) is said as the crossing: "Cross Redland Road, then left onto Redland Road
# bike lane" (the owner, 2026-10-20: "It should have told me to cross the street and turn
# left"), not as a bear to stay on the path. The event may lie a little either side of it.
CROSS_MAX_M = 50.0
CROSS_NEAR_M = 10.0
CROSS_KINDS = frozenset({"crossing", "left_across", "along"})
CROSSING_USE = "pedestrian_crossing"
CROSS_UNNAMED = "the road"
# Other ways at a node that never look like the way on: a driveway or a parking
# aisle off a road, steps, a lift.
FORK_IGNORED_USES = frozenset(
    {
        "driveway",
        "parking_aisle",
        "drive_through",
        "steps",
        "elevator",
        "escalator",
        "rest_area",
        "service_area",
        # A crosswalk is a way across a road, not a way on.
        "pedestrian_crossing",
    }
)
# The ride card's junction diagram (`junction_shape`): a branch more than this off
# straight on, a left or a right makes a junction unusual; ways nearer one another
# than SHAPE_MERGE_DEG are drawn as one; a sidewalk beside the road is never drawn.
SHAPE_SQUARE_DEG = 20.0
SHAPE_MERGE_DEG = 20.0
# A way within 30 degrees of the way back would be drawn on the way in: not drawn.
SHAPE_BACK_DEG = 150.0
SHAPE_IGNORED_USES = frozenset({"sidewalk"})
# A turn onto a service road beside a main road draws the main road too, across the
# way in where the route crossed it within SHAPE_NEAR_M before the turn, else across the
# way ahead (the owner, 2026-10-20: "In the service road case you'd be going further than
# the main road ... If making a left ... or shorter if making a right"). A main road is
# one of MAIN_CLASSES, read as the one beside where it runs within SHAPE_PARALLEL_DEG of
# the service road.
SHAPE_NEAR_M = 60.0
SHAPE_PARALLEL_DEG = 30.0
MAIN_CLASSES = frozenset({"motorway", "trunk", "primary", "secondary", "tertiary"})
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
# A path with no name of its own is just "path" (the owner, 2026-10-15: not "unnamed
# path"); one beside a named street is that street's bike lane, named at the rebuild
# (`routemaker.facility.side_street_names`) and handed in as the piece's name.
UNNAMED_PATH = "path"
# The street a stretch gets when its pieces have no name (a road) or were not traced. The
# client reads these as unnamed (frontend/src/lib/federalStops.ts, held equal by
# tests/test_describe.py TestFrontEndAgrees).
UNNAMED_ROAD = "unnamed road"
UNTRACED_STREET = "this part of the route"
# What an unnamed service way is called, by Valhalla's `use` (the owner, 2026-10-20, on a
# frontage road beside East-West Highway: "When going on a service road, especially next
# to a major road, say so"). A service way is never folded into an unnamed road as one
# street (`_same_street`), so the turn onto it is said.
SERVICE_WORDS = {
    "service_road": "service road",
    "driveway": "service road",
    "drive_through": "service road",
    "alley": "alley",
    "parking_aisle": "parking aisle",
}
# An unnamed service road, path or sidewalk beside a major road is named after it at plan
# time (`core.beside_roads`, `beside_words`): "service road beside East-West Highway".
BESIDE = " beside "
# The words a sentence says "the" before: "Left onto the service road beside ...".
_COMMON_WAY = re.compile(r"^(?:path|sidewalk|service road|alley|parking aisle)\b")
PATH_WORDS = "traffic-free path"
FACILITY_WORDS = {"protected": "protected bike lane", "lane": "painted bike lane"}
# The tiers on which a painted lane is not called a bike lane while the client's
# "Show bike lanes on high-stress roads" switch is off (OWNER-DECISIONS 275):
# LTS 4 and Avoid, frontend/src/stressStyle.js HIGH_STRESS_LANE_MIN_TIER
# (tests/test_describe.py, TestFrontEndAgrees, holds the two equal). Each
# stretch carries its text both ways (`text_lanes_hidden`), so the client never
# edits the wording.
HIGH_STRESS_LANE_TIERS = frozenset({"4", "5"})
# A stretch's surface (OWNER-DECISIONS 280): the dotted mark on the map is not
# all a screen-reader rider has. "unpaved" where at least half of the stretch is,
# "partly unpaved" where less is but at least PARTLY_UNPAVED_M.
SURFACE_UNPAVED = "unpaved"
SURFACE_PARTLY = "partly unpaved"
PARTLY_UNPAVED_M = METRES_PER_MILE / 10


class RelationName(str):
    """A way's name taken from its trail's route relation, not the way itself
    (`core.routing.sidepath_names_of`): a stretch named only so is flagged
    `relation_name`, and the ride never cues "Continue onto" it."""


class BesideName(str):
    """A way's name from the major road it runs beside (`core.beside_roads`,
    `beside_words`): "service road beside East-West Highway". It takes the place of the
    way's own name too, where a service road is mapped with the road's name."""


# A national or international route's name (the East Coast Greenway, a US Bicycle
# Route, a national scenic or memorial trail): never a way's name on the move.
NATIONAL_ROUTE_NAME = re.compile(
    r"east coast greenway|\bus ?bike ?route\b|\bu\.?s\.? bicycle route\b|\busbr\b"
    r"|national (?:scenic|historic|memorial) trail|\beurovelo\b",
    re.IGNORECASE,
)

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
    # The segment's surface: True unpaved, False paved, None not known.
    unpaved: bool | None = None
    # On a roundabout or circular junction (Valhalla's `edge.roundabout`).
    roundabout: bool = False
    # Where the piece begins at a fork the route leaves the straight-ahead way by
    # (`fork_movement`): the movement to say there, else None.
    fork: str | None = None
    # Where the piece begins a traced edge: the other ways at the node it leaves,
    # each (its compass heading away from the node, Valhalla's `use`, and its road
    # class where the router gave it); None on every other piece, and from a trace that
    # has none (`junction_shape`).
    others: tuple | None = None
    # The other ways, as `others`, at the junctions within SHAPE_NEAR_M short of that
    # node; None where there are none.
    prior: tuple | None = None
    # The piece's own compass bearing, unwrapped along the trace (`core.routing.Piece`):
    # two pieces' difference is how far, and to which side, the route turned between.
    bearing: float | None = None
    # Where the piece begins a traced edge: the turn the route's own line makes at that
    # node, clockwise positive, read over LINE_SPAN_M either side; None elsewhere.
    turn: float | None = None
    # Whether another way a bicycle may ride away on meets that node (not a sidewalk, a
    # driveway or a crosswalk); False elsewhere.
    choice: bool = False


def beside_words(use: str, road: str) -> str | None:
    """An unnamed way's name from the major road it runs beside (`core.beside_roads`):
    "service road beside East-West Highway", "sidewalk beside ...", "path beside ...";
    None for a way that is neither a service way nor a path (or an alley or a parking
    aisle, which are not said to run beside anything)."""
    if SERVICE_WORDS.get(use) == "service road":
        kind = "service road"
    elif use == "sidewalk":
        kind = "sidewalk"
    elif use in PATH_USES:
        kind = UNNAMED_PATH
    else:
        return None
    return f"{kind}{BESIDE}{road}"


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
    unpaved_m: float = 0.0
    # An unnamed service way's word (`SERVICE_WORDS`), else None.
    service: str | None = None
    # A short stretch of another street folded in at its end (`_join`) or its start
    # (`_absorb_tiny`): the turn there spans two nodes, so no junction is drawn.
    folded_end: bool = False
    folded_start: bool = False


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
        unpaved_m=atom.metres if atom.unpaved else 0.0,
        service=None if atom.names else SERVICE_WORDS.get(atom.use),
    )


def _same_way(a: Atom, b: Atom) -> bool:
    """Whether two pieces are one street, as `_same_street` reads two stretches."""
    if not a.names and not b.names:
        return SERVICE_WORDS.get(a.use) == SERVICE_WORDS.get(b.use)
    return bool({n.lower() for n in a.names} & {n.lower() for n in b.names})


def _said_turns(atoms: list[Atom]) -> list[Atom]:
    """`atoms` with each clear turn the fork rule missed marked as one (`Atom.fork`), so
    it is said and never folded away: a turnaround (HAIRPIN_DEG or more) onto any way,
    and a turn of more than ALONG_TURN_DEG along one street where another way a bicycle
    may take meets the node (`Atom.choice`; a bend with nothing to choose is no question).
    Read from the line (`Atom.turn`); of nodes within JUNCTION_M of one another, only
    the sharpest is marked, as the line is read through all of them."""
    at = 0.0
    marks: list[tuple[float, int]] = []
    for i, atom in enumerate(atoms):
        if i > 0 and atom.fork is None and atom.turn is not None and not atom.roundabout:
            turn = abs(atom.turn)
            if turn >= HAIRPIN_DEG or (
                turn > ALONG_TURN_DEG and atom.choice and _same_way(atoms[i - 1], atom)
            ):
                marks.append((at, i))
        at += atom.metres
    out = list(atoms)
    for at, i in marks:
        sharpest = max(
            (j for m, j in marks if abs(m - at) < JUNCTION_M),
            key=lambda j: (abs(atoms[j].turn), -j),
        )
        if sharpest != i:
            continue
        turn = atoms[i].turn
        side = "right" if turn > 0 else "left"
        out[i] = replace(atoms[i], fork=side if abs(turn) > BEAR_MAX_DEG else f"bear_{side}")
    return out


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
            and not atom.fork
            and (atom.names or SERVICE_WORDS.get(atom.use) == SERVICE_WORDS.get(previous.use))
        ):
            run = runs[-1]
            run.metres += atom.metres
            run.unpaved_m += atom.metres if atom.unpaved else 0.0
            run.last = atom
            run.path = run.path or atom.use in PATH_USES
        else:
            runs.append(_run_of(atom, leg))
        previous = atom
    return runs


def _same_street(a: _Run, b: _Run) -> bool:
    if not a.names and not b.names:
        return a.service == b.service
    return bool(a.names & b.names)


def _forks(run: _Run) -> bool:
    """Whether `run` begins at a fork (`fork_movement`): its start is a turn to say."""
    return run.first is not None and run.first.fork is not None


def _same(a: _Run, b: _Run) -> bool:
    return a.tier == b.tier and a.facility == b.facility and _same_street(a, b) and not _forks(b)


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
    else:
        a.folded_end = True
    a.metres += b.metres
    a.unpaved_m += b.unpaved_m


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


def _circle(run: _Run) -> bool:
    """Whether `run` is a roundabout or a circle, by the map or by its name."""
    on = any(atom is not None and atom.roundabout for atom in (run.first, run.last))
    return on or any(CIRCLE_NAME.search(name) for name in run.names)


def _last_turn(before: _Run | None, run: _Run, after: _Run | None) -> bool:
    """Whether `run` is the street a leg ends on, turned onto: another street than
    the one before, at least JOG_MIN_M long, entered by a turn or a bear. Folded
    away, the turn would go unsaid and the ride would say only the arrival (the
    owner, 2026-10-18, at Berwyn Road and at Baltimore Avenue: "Same with
    destinations")."""
    if before is None or after is not None or run.metres < JOG_MIN_M:
        return False
    if _same_street(before, run):
        return False
    return _movement_between(before, run) in TURN_WORDS


def _jog(before: _Run | None, run: _Run, after: _Run | None) -> bool:
    """Whether `run` is a jog's middle: a named street, not a roundabout or circle,
    at least JOG_MIN_M long, other than both neighbours, entered and left by a turn
    or a bear. Folded away, its two turns would be read as one across it (a right
    then a left as straight on), so it is kept. Back onto the street it left, a
    middle under MATCH_M, or one whose turns cancel (within STRAIGHT_MAX_DEG of
    straight on), is a divided road or an offset crossing, and is folded."""
    if before is None or after is None or not run.names or run.metres < JOG_MIN_M:
        return False
    if _circle(run) or _same_street(before, run) or _same_street(run, after):
        return False
    if _same_street(before, after):
        if run.metres < MATCH_M:
            return False
        a = before.last.heading_out if before.last else None
        b = after.first.heading_in if after.first else None
        if a is not None and b is not None and abs(_turn_deg(a, b)) <= STRAIGHT_MAX_DEG:
            return False
    return (
        _movement_between(before, run) in TURN_WORDS and _movement_between(run, after) in TURN_WORDS
    )


def _absorb_tiny(runs: list[_Run]) -> list[_Run]:
    """Fold each stretch under TINY_M of one traced leg into a neighbour: the one
    on its own street if there is one, else the longer (the earlier on a tie). A
    stretch of LTS 3 or worse goes only into a neighbour at least as stressful, so
    the description never says less than the route is, and a jog's middle (`_jog`)
    is kept. (An untraced leg is one run and is never given to this.)"""
    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(runs):
            run = runs[i]
            before = runs[i - 1] if i > 0 else None
            after = runs[i + 1] if i + 1 < len(runs) else None
            # A stretch begun at a fork is kept: folded, its fork would go unsaid.
            if (
                run.metres >= TINY_M
                or _forks(run)
                or _jog(before, run, after)
                or _last_turn(before, run, after)
            ):
                i += 1
                continue
            # Nor is a tiny one folded into a stretch begun at a fork, which would
            # then begin where the tiny one does; but at a leg's start, with nothing
            # before it, it is, the fork kept as that stretch's turn.
            options = [
                n
                for n in (before, after)
                if n is not None and not (n is after and _forks(n) and before is not None)
            ]
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
                    if not _forks(target):
                        target.first = run.first
                else:
                    target.folded_start = True
                target.metres += run.metres
                target.unpaved_m += run.unpaved_m
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


def surface_of(run: _Run) -> str | None:
    """The stretch's surface as said: SURFACE_UNPAVED, SURFACE_PARTLY, or None
    (paved, not known, or too little of it unpaved to say)."""
    if run.untraced or run.unpaved_m <= 0 or run.metres <= 0:
        return None
    if run.unpaved_m >= run.metres / 2:
        return SURFACE_UNPAVED
    return SURFACE_PARTLY if run.unpaved_m >= PARTLY_UNPAVED_M else None


def _lanes_hidden(run: _Run, members: list[_Run] | None = None) -> _Run | None:
    """The stretch as worded with painted lanes on LTS 4 and Avoid not called bike
    lanes (HIGH_STRESS_LANE_TIERS), or None where that changes nothing: a lane
    stretch whose every part is on one of those tiers. An overview stretch that
    merges an LTS 3 lane with an LTS 4 one keeps its lane."""
    if run.facility != "lane":
        return None
    if any(m.tier not in HIGH_STRESS_LANE_TIERS for m in (members or [run])):
        return None
    return replace(run, facility="none")


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


def street_name_of(event) -> str | None:
    """The street an event or a major junction is about, as mapped; None where unnamed."""
    return _event_name(event)


def _crossed(tier: int | None) -> str:
    return {3: " (LTS 3)", 4: " (LTS 4)", 5: " (Avoid)"}.get(tier or 0, "")


def _control_words(control, flagged: bool, beacon: bool = False) -> str:
    if beacon:
        # The map's signal is a flashing beacon (`intersections.with_beacons`).
        phrase = CONTROL_PHRASES.get(control, "")
        return f"{phrase}, flashing light, not a signal" if flagged or phrase else phrase
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
    control = _control_words(event.control, True, getattr(event, "beacon", False))
    return f"At {point_words(at_m)}: {verb} {what}{control}{_severity_suffix(event.severity)}."


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
    # A fork along one street: "Bear right to stay on ...".
    stay: bool = False
    # An unusual junction's shape for the ride card's diagram (`junction_shape`).
    shape: dict | None = None
    # The way off a circle (`circle_exit`): {"number": its exit, "circle": its name}.
    exit: dict | None = None
    # A short path across a road between two turns: the road crossed, said in place of
    # the turn ("Cross Redland Road"; CROSS_UNNAMED where the road has no name).
    cross: str | None = None


def _turn_deg(heading_in: float, heading_out: float) -> float:
    """The turn from one compass heading to another, -180 to 180, clockwise positive."""
    return (heading_out - heading_in + 540.0) % 360.0 - 180.0


def turn_between(before: Atom | None, after: Atom | None) -> float | None:
    """The turn from the piece `before` into the piece `after`, clockwise positive:
    Valhalla's headings at the junction, but past HAIRPIN_DEG on the side the route's
    own line turns (`Atom.bearing`), so a hairpin right that its headings make a
    little more than straight back reads as the right it is (+190, not -170). None
    where a heading is not known."""
    a = before.heading_out if before else None
    b = after.heading_in if after else None
    if a is None or b is None:
        return None
    turn = _turn_deg(a, b)
    if abs(turn) >= HAIRPIN_DEG and before.bearing is not None and after.bearing is not None:
        # The bearings run on unbroken along the trace, so their difference is how the
        # route turned between the two pieces; never a turn past 360 - HAIRPIN_DEG.
        line = after.bearing - before.bearing
        sides = [t for t in (turn, turn - 360.0, turn + 360.0) if abs(t) <= 360.0 - HAIRPIN_DEG]
        turn = min(sides, key=lambda t: abs(t - line))
    return turn


def _turn_at(before: _Run, after: _Run) -> float | None:
    """The turn from `before` into `after`: the route's own line at the node (`Atom.turn`)
    where it was read and the two meet at one node, else `turn_between`'s headings."""
    line = after.first.turn if after.first is not None else None
    if line is not None and not before.folded_end and not after.folded_start:
        return line
    return turn_between(before.last, after.first)


def _movement_between(before: _Run, after: _Run) -> str | None:
    """ "left", "right", "bear_left", "bear_right" or "straight" from `before` into
    `after`, from the turn at the junction (`_turn_at`); None where it is not
    known. A bear is a turn of SLIGHT_MIN_DEG to BEAR_MAX_DEG; past it, a left or a
    right, by the side it turns to."""
    turn = _turn_at(before, after)
    if turn is None:
        return None
    if abs(turn) < SLIGHT_MIN_DEG:
        return "straight"
    if abs(turn) <= BEAR_MAX_DEG:
        return "bear_right" if turn > 0 else "bear_left"
    return "right" if turn > 0 else "left"


def fork_movement(
    heading_in: float | None,
    heading_out: float | None,
    others: list[tuple[float | None, str | None, str | None]],
    trail: bool = False,
) -> str | None:
    """The movement to say where the route leaves a node that is a fork, else None.

    `heading_in` is the compass heading the route arrives on, `heading_out` the one
    it leaves on, and `others` each other way at the node: (its heading away from
    the node, Valhalla's `use`, its `cyclability` away from the node, or None where
    the router did not say). A way a bicycle may not ride away on, or one of
    FORK_IGNORED_USES, is not a choice. The node is a fork where a choice lies
    within FORK_AHEAD_DEG of straight ahead and the route's own way is not nearer
    straight by FORK_CLEAR_DEG; on a trail (`trail`: the route's way is one of
    TRAIL_USES) whose way bends off itself, another trail-like way within
    FORK_CLEAR_DEG beyond it (to FORK_WIDE_MAX_DEG) is a fork too (a Y of two leaning
    branches); where the route's way is itself within
    SLIGHT_MIN_DEG of straight, only a choice straighter still makes a fork (a spur
    a little off a trail carried straight on is no question). A way whose
    cyclability the router did not give (an older router) is taken as a choice.
    Then: past BEAR_MAX_DEG the route's way is a left
    or a right; else it is a bear to the side the route's way lies of the nearest
    choice ("bear_right" where it is the right-hand branch of a Y)."""
    if heading_in is None or heading_out is None:
        return None
    ours = _turn_deg(heading_in, heading_out)
    choices = [
        (_turn_deg(heading_in, heading), use)
        for heading, use, cyclability in others
        if heading is not None
        and use not in FORK_IGNORED_USES
        and cyclability not in ("none", "backward")
    ]
    wide = min(abs(ours) + FORK_CLEAR_DEG, FORK_WIDE_MAX_DEG) if trail else FORK_AHEAD_DEG
    ahead = [
        d
        for d, use in choices
        if abs(d) <= FORK_AHEAD_DEG or (abs(d) <= wide and use in TRAIL_USES)
    ]
    if not ahead:
        return None
    nearest = min(ahead, key=abs)
    if abs(ours) < SLIGHT_MIN_DEG and abs(nearest) > abs(ours):
        return None
    if abs(ours) + FORK_CLEAR_DEG <= abs(nearest):
        return None
    if abs(ours) > BEAR_MAX_DEG:
        return "right" if ours > 0 else "left"
    return "bear_right" if ours > nearest else "bear_left"


def _branches(heading_in: float, keep: list[float], others) -> list[float]:
    """The other ways worth drawing at a node, as turns from `heading_in`: see
    `junction_shape`. `keep` is the route's own ways there, never drawn twice."""
    branches: list[float] = []
    for heading, use, *_class in others or ():
        if heading is None or use in FORK_IGNORED_USES or use in SHAPE_IGNORED_USES:
            continue
        turn = _turn_deg(heading_in, heading)
        if any(abs(_turn_deg(b, turn)) < SHAPE_MERGE_DEG for b in [*keep, *branches]):
            continue
        if abs(turn) > SHAPE_BACK_DEG:
            continue
        branches.append(turn)
    return branches


def junction_shape(
    heading_in: float | None,
    heading_out: float | None,
    others: tuple[tuple[float | None, str | None], ...] | list | None,
    service: bool = False,
    main: str | None = None,
) -> dict | None:
    """The shape of an unusual junction, for the ride card to draw in place of its plain
    arrow (the owner, 2026-10-20: "if there's a left turn on a service road show the
    non-picked intersections dashed. Likewise with 5 way intersections"), else None.

    `heading_in` is the compass heading the route arrives on, `heading_out` the one it
    leaves on, `others` each other way at the node (its heading away from the node,
    Valhalla's `use`). A way of FORK_IGNORED_USES (a driveway, a crosswalk) or a sidewalk
    is not drawn; ways within SHAPE_MERGE_DEG of one another are one branch, one within
    it of the route's way is not drawn, nor one past SHAPE_BACK_DEG (on the way in).
    `main` is where a service road's main road lies (`main_road_side`), drawn across the
    way in ("before") or the way ahead ("after").

    Answers {"out": the route's turn, "others": the other branches' turns, and "main"
    where given}, in degrees from straight ahead, clockwise positive, -180 to 180, where
    the junction is unusual: more than two other branches, a branch more than
    SHAPE_SQUARE_DEG off straight, left or right, two in one of those three directions,
    or a turn onto a service road or alley with any other branch. A plain crossroads or
    T keeps the plain arrow; so does a junction whose ways the router did not give. The
    words said and read stay as they are: the diagram is a picture of the junction,
    never its only telling."""
    if heading_in is None or heading_out is None:
        return None
    out = _turn_deg(heading_in, heading_out)
    branches = _branches(heading_in, [out], others)
    if not branches and main is None:
        return None
    every = [out, *branches]

    def slot(turn: float) -> float | None:
        for square in (-90.0, 0.0, 90.0):
            if abs(turn - square) <= SHAPE_SQUARE_DEG:
                return square
        return None

    slots = [slot(t) for t in every]
    plain = len(branches) <= 2 and None not in slots and len(set(slots)) == len(slots)
    if plain and not service and main is None:
        return None
    shape = {"out": round(out), "others": sorted(round(b) for b in branches)}
    if main is not None:
        shape["main"] = main
    return shape


def _parallel_main(heading_out: float, ways) -> bool:
    """Whether a main road (MAIN_CLASSES) among `ways` runs alongside `heading_out`."""
    for heading, _use, *road_class in ways or ():
        if heading is None or not road_class or road_class[0] not in MAIN_CLASSES:
            continue
        off = abs(_turn_deg(heading_out, heading))
        if min(off, 180.0 - off) <= SHAPE_PARALLEL_DEG:
            return True
    return False


def main_road_side(heading_out: float | None, others, prior) -> str | None:
    """Where the main road beside a service road lies for a turn onto it: "before" where
    the route crossed it within SHAPE_NEAR_M of the turn (a left across it, as a rule),
    None where it meets the turn's own junction (drawn there already) or the turn's way
    is not known, else "after", ahead across the way on (a right short of it)."""
    if heading_out is None or _parallel_main(heading_out, others):
        return None
    return "before" if _parallel_main(heading_out, prior) else "after"


def ordinal(number: int) -> str:
    """1st, 2nd, 3rd, 4th, ... 11th, 12th, 13th, ... 21st."""
    if number % 100 in (11, 12, 13):
        return f"{number}th"
    return f"{number}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(number % 10, 'th') }"


def exit_words(number: int, street: str, circle: str | None) -> str:
    """ "Take the 3rd exit onto P Street Northwest at Dupont Circle Northwest"; "... at the
    roundabout" where it has no name. The exit first, so the ride card shows it whole."""
    return f"Take the {ordinal(number)} exit onto {street} at {circle or 'the roundabout'}"


def _on_circle(atom: Atom) -> bool:
    """On a ring by the map's own flag (Valhalla's `edge.roundabout`): a name is not
    enough for exits, for "Oak Circle" is as often a loop street as a ring."""
    return atom.roundabout


def circle_exit(entry: Atom, ring: list[Atom], way_off: Atom) -> dict | None:
    """The way off a circle (the owner, 2026-10-20, chose "Ring picture + exit number"):
    {"number": the exit the route takes, counting the streets off the ring it passes;
    "circle": the circle's name, or None; "shape": the ring for the ride card}, or None
    where a heading is not known.

    An exit is another way at a ring node the route passes (not the node it comes onto
    the ring at) that is a street (EXIT_USES) a car may drive away on: a slip lane, a
    service lane, a path or a way only into the ring is not counted, so the count is the
    streets a rider sees leave. The shape is {"out", "others", "ring"}: the way off and
    the exits passed, as turns from the heading in (where each leaves the ring, near
    enough, for a street leaves a ring about square), and "right" where the route bears
    right onto the ring (round it anticlockwise, as in the US) or "left"."""
    heading_in = entry.heading_out
    if heading_in is None or way_off.heading_in is None or ring[0].heading_in is None:
        return None
    passed: list[float] = []
    for atom in ring[1:]:
        for heading, use, *rest in atom.others or ():
            drive = rest[1] if len(rest) > 1 else None
            if heading is None or use not in EXIT_USES or drive in ("backward", "none"):
                continue
            passed.append(_turn_deg(heading_in, heading))
    names = next((atom.names for atom in ring if atom.names), ())
    side = "right" if _turn_deg(heading_in, ring[0].heading_in) >= 0 else "left"
    return {
        "number": len(passed) + 1,
        "circle": street_label(names),
        "shape": {
            "out": round(_turn_deg(heading_in, way_off.heading_in)),
            "others": [round(t) for t in passed],
            "ring": side,
        },
    }


def _circle_exits(atoms: list[Atom]) -> dict[int, dict]:
    """`circle_exit` for each time a leg's atoms go onto a circle and off it again, by
    the id of the atom the way off begins with."""
    found: dict[int, dict] = {}
    i = 0
    while i < len(atoms):
        if not _on_circle(atoms[i]):
            i += 1
            continue
        j = i
        while j < len(atoms) and _on_circle(atoms[j]):
            j += 1
        if i > 0 and j < len(atoms):
            way = circle_exit(atoms[i - 1], atoms[i:j], atoms[j])
            if way is not None:
                found[id(atoms[j])] = way
        i = j
    return found


def _street_words(run: _Run) -> str:
    if run.untraced:
        return UNTRACED_STREET
    if run.label:
        return run.label
    if run.service:
        return run.service
    return UNNAMED_PATH if run.facility in ("path", "protected") or run.path else UNNAMED_ROAD


def _in_sentence(street: str) -> str:
    """The street as a sentence names it after "onto" or "on": "the path" for a path
    with no name, "the service road beside East-West Highway", the street itself
    otherwise."""
    return f"the {street}" if _COMMON_WAY.match(street) else street


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
        if turn.exit is not None:
            lead = exit_words(turn.exit["number"], _in_sentence(street), turn.exit["circle"])
        elif turn.cross is not None:
            lead = f"Cross {turn.cross}"
        elif movement in TURN_WORDS and turn.stay:
            lead = f"{TURN_WORDS[movement]} to stay on {_in_sentence(street)}"
        elif movement in TURN_WORDS:
            lead = f"{TURN_WORDS[movement]} onto {_in_sentence(street)}"
        else:
            lead = f"Continue onto {_in_sentence(street)}"
        if event is not None:
            lead += _control_words(event.control, event.flagged, getattr(event, "beacon", False))
            lead += _severity_suffix(event.severity if event.flagged else None)
    elif same_street_continues:
        lead = f"Continue on {_in_sentence(street)}"
    else:
        lead = street[:1].upper() + street[1:] if _COMMON_WAY.match(street) else street
    words = tier_words(run.tier, run.facility)
    if words == PATH_WORDS and _COMMON_WAY.match(street):
        words = "traffic-free"
    elif street.endswith(" bike lane"):
        # A bike lane named for its street ("9th Street Northwest protected bike lane")
        # already says what it is: the facility is not said twice.
        words = "traffic-free" if words == PATH_WORDS else TIER_WORDS.get(run.tier, UNRATED_WORDS)
    surface = surface_of(run)
    if surface:
        words = f"{words}, {surface}"
    return f"{where}: {lead}{then}, {words}."


MAX_NAMED_TURNS = 3


def _then_words(streets: list[tuple[str, str | None]]) -> str:
    """ ", then left on A, B and right on C and 2 more turns": the other streets
    a merged stretch runs along, each with its turn where it is a left or a right
    or a bear (a street straight on is just named), at most MAX_NAMED_TURNS of them."""
    if not streets:
        return ""
    pieces = []
    for street, movement in streets[:MAX_NAMED_TURNS]:
        pieces.append(
            f"{TURN_WORDS[movement].lower()} on {_in_sentence(street)}"
            if movement in TURN_WORDS
            else _in_sentence(street)
        )
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
            if metres(g) < OVERVIEW_M and not _flagged_turn(turns, g[0]) and not _forks(runs[g[0]])
        ]
        folded = False
        for _size, n in sorted(candidates):
            group = groups[n]
            before = groups[n - 1] if n > 0 else None
            after = groups[n + 1] if n + 1 < len(groups) else None
            options = []
            if before is not None and joinable(before, group):
                options.append(before)
            if (
                after is not None
                and joinable(group, after)
                and not _flagged_turn(turns, after[0])
                and not _forks(runs[after[0]])
            ):
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
        unpaved_m=sum(m.unpaved_m for m in members),
    )
    own = _street_words(first)
    streets: list[tuple[str, str | None]] = []
    for k, m in zip(range(group[0] + 1, group[1] + 1), members[1:], strict=True):
        if m.label and m.label != own and m.label not in (s for s, _m in streets):
            turn = (turns or {}).get(k)
            streets.append((m.label, turn.movement if turn else None))
    return merged, _then_words(streets)


def _crossing(
    runs: list[_Run], turns: dict[int, _Turn], starts: list[float], events: list, i: int
) -> str | None:
    """The road `runs[i]` crosses, where it is a short path across a road between two
    turns of one leg: a path under CROSS_MAX_M, turned (or forked) into and turned out
    of, with a junction event across a road (CROSS_KINDS) within CROSS_NEAR_M of it, or
    begun or ended on a crosswalk. The event's road, else CROSS_UNNAMED; None where it
    is not such a stretch."""
    run = runs[i]
    crosswalk = any(atom is not None and atom.use == CROSSING_USE for atom in (run.first, run.last))
    if i + 1 >= len(runs) or runs[i + 1].leg != run.leg or not (run.path or crosswalk):
        return None
    if run.metres > CROSS_MAX_M or run.untraced or _circle(run):
        return None
    into, out = turns.get(i), turns.get(i + 1)
    if into is None or out is None or into.exit or out.exit:
        return None
    if into.movement not in TURN_WORDS or out.movement not in TURN_WORDS:
        return None
    start, end = starts[i], starts[i] + run.metres
    ways = runs[i - 1].names | runs[i + 1].names
    near = [
        event
        for event in events
        if event.kind in CROSS_KINDS
        and start - CROSS_NEAR_M <= event.m <= end + CROSS_NEAR_M
        and (_event_name(event) or "").lower() not in ways
    ]
    if near:
        middle = (start + end) / 2
        name = _event_name(min(near, key=lambda event: abs(event.m - middle)))
        return name or CROSS_UNNAMED
    if crosswalk:
        return CROSS_UNNAMED
    return None


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
    walks: list[tuple[float, float]] | None = None,
) -> list[dict]:
    """The route's full description (see `describe_both`)."""
    return describe_both(legs, events, total_m, walks)[0]


def walk_sentence(start_m: float, end_m: float) -> str:
    """The note for a short stretch a bicycle is walked over (OWNER-DECISIONS
    291(5): a `bicycle=dismount` connector kept, "walk your bike here")."""
    length = end_m - start_m
    return (
        f"At {point_words(start_m)}: walk your bike here, for {_feet(length)} ft "
        f"({round(length)} m)."
    )


def describe_both(
    legs: list[list[Atom] | float],
    events: list | None = None,
    total_m: float | None = None,
    walks: list[tuple[float, float]] | None = None,
    relation_names: frozenset[str] = frozenset(),
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
    `surface` (on a stretch, `surface_of`: "unpaved", "partly unpaved" or None),
    `text`, and `text_lanes_hidden` (the text with painted lanes on LTS 4 and
    Avoid not called bike lanes, or None where that is `text`).
    `walks` are the stretches to walk a bicycle over, (from, to) in metres in the
    pieces' own measure (before scaling), each a "walk" entry in both lists.
    The overview has the same entries with the short stretches merged (see the
    module's rules); its stops and junction entries are the full ones.
    `relation_names` (lower case) are names taken from a trail's route relation
    alone (`RelationName`): a stretch of one has `relation_name` true.
    """
    runs: list[_Run] = []
    # The ways off circles, by the atom the way off begins with (`_circle_exits`).
    exits: dict[int, dict] = {}
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
        # The ways off circles are read from the marked atoms: the runs begin with them.
        content = _said_turns(content)
        exits.update(_circle_exits(content))
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
        same = _same_street(before, run)
        if before.untraced or run.untraced or (same and not _forks(run)):
            continue
        found = _nearest_event(events, starts[i], used)
        if found is not None:
            used.add(found)
        movement = _movement_between(before, run)
        # At a fork the route's way is said beside the other branch, whatever the
        # street (a bend along one street, or a new name straight on, says nothing);
        # a left or a right there on the side the line turns (`turn_between`).
        if _forks(run):
            movement = run.first.fork
            turn = _turn_at(before, run)
            if movement in ("left", "right") and turn is not None and abs(turn) > BEAR_MAX_DEG:
                movement = "right" if turn > 0 else "left"
        event = events[found] if found is not None else None
        if movement is None and event is not None:
            movement = event.movement.value
        shape = None
        # Only where the heading in and the ways out are read at one node: a short
        # stretch of another street folded in between puts them at two.
        one_node = not before.folded_end and not run.folded_start
        if movement is not None and one_node and before.last is not None and run.first is not None:
            service = run.first.use in SERVICE_WORDS
            main = None
            # A service road beside a main road the route was not on: where the main road is.
            beside = (run.label or "").partition(BESIDE)[2].lower()
            if service and beside and beside not in before.names:
                main = main_road_side(run.first.heading_in, run.first.others, run.first.prior)
            shape = junction_shape(
                before.last.heading_out, run.first.heading_in, run.first.others, service, main
            )
            # A turn said on the line's side (`_turn_at`, a hairpin by `turn_between`)
            # that the diagram's headings would draw the other way is the plain arrow.
            if shape is not None and movement in ("left", "right"):
                if (shape["out"] > 0) != (movement == "right"):
                    shape = None
        circle = exits.get(id(run.first)) if run.first is not None else None
        exit = None
        if circle is not None and movement is not None and not same:
            exit = {"number": circle["number"], "circle": circle["circle"]}
            shape = circle["shape"]
        turns[i] = _Turn(movement, event, same, shape, exit)
    for i, turn in turns.items():
        crossed = _crossing(runs, turns, starts, events, i)
        if crossed is not None:
            turn.cross = crossed
            turn.shape = None

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
        hidden = _lanes_hidden(run)
        text_lanes_hidden = (
            _stretch_sentence(hidden, start, end, turn, continues) if hidden else None
        )
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
                    relation_name=_street_words(run).lower() in relation_names,
                    tier=int(run.tier) if run.tier.isdigit() else None,
                    facility=None if run.facility in ("unknown", "none") else run.facility,
                    surface=surface_of(run),
                    text_lanes_hidden=text_lanes_hidden,
                    turn=None
                    if turn is None
                    else {
                        "movement": turn.movement,
                        "onto": _street_words(run),
                        "control": turn.event.control.value if turn.event is not None else None,
                        "severity": severity,
                        **({"stay": True} if turn.stay else {}),
                        **({"shape": turn.shape} if turn.shape else {}),
                        **({"exit": turn.exit} if turn.exit else {}),
                        **({"cross": turn.cross} if turn.cross else {}),
                    },
                    severity=severity,
                ),
            )
        )
    for number, (walk_from, walk_to) in enumerate(sorted(walks or ())):
        from_at, to_at = walk_from * scale, walk_to * scale
        shared.append(
            (
                (from_at, 3, number),
                _entry("walk", from_at, to_at, walk_sentence(from_at, to_at)),
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
        hidden = _lanes_hidden(run, runs[first : last + 1])
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
                    relation_name=_street_words(runs[first]).lower() in relation_names,
                    tier=int(run.tier) if run.tier.isdigit() else None,
                    facility=None if run.facility in ("unknown", "none") else run.facility,
                    surface=surface_of(run),
                    text_lanes_hidden=(
                        _stretch_sentence(hidden, start, end, turn, continues, then)
                        if hidden
                        else None
                    ),
                    turn=None
                    if turn is None
                    else {
                        "movement": turn.movement,
                        "onto": _street_words(runs[first]),
                        "control": turn.event.control.value if turn.event is not None else None,
                        "severity": severity,
                        **({"stay": True} if turn.stay else {}),
                        **({"shape": turn.shape} if turn.shape else {}),
                        **({"exit": turn.exit} if turn.exit else {}),
                        **({"cross": turn.cross} if turn.cross else {}),
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
        "surface": None,
        "text": text,
        "text_lanes_hidden": None,
        "relation_name": False,
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
    "surface_of",
    "group_crossings",
    "group_sentence",
    "group_words",
    "plain_text",
    "range_words",
    "readable",
    "street_label",
    "tier_words",
]
