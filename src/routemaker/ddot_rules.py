"""How the map reads DDOT's 2020 LTS: the owner's rules over DDOT's own level.

The owner, 2026-10-30, after the Q, R and 1st Street NW review: "Take a look at all DC
roads and see what might be improperly rated. I think it's just that 6 year old data is too
stale to rely on." and "My neighborhood had something like 1/5 the population then. DC
changes fast", with skeptic agents that "will try to refute that. In many cases it's
probably reliable for 2020, just stale", half steps in the proposals, calibration from the
data ("The agents should have a good idea based on the available data what constitutes
each") and "Also flag under-ratings too". A review (thread "Fix Q and R Street ratings";
the project's reports/dc-ratings-audit/) read 3,553 random DC blocks from the road panel,
learned what each level looks like where DDOT and the formula agree, and had a skeptic
agent argue for DDOT on each group where they disagree. The rules that survived are below;
the owner, 2026-10-31: "I agree with these".

Each rule reads only what the formula read on the way (`StressResult`): its tier, the
traffic count (DC's own, `volume_aadt`), the through lanes and whether it is one-way, and
whether a painted lane or a protected lane or path is mapped. A block with no count keeps
DDOT's level except where a painted lane decides it: a missing count is no evidence either
way, and the owner's rule is to under-rate only with clear reasons. Where DDOT and the
formula agree, nothing changes.

Pure: nothing here reads a file or the network.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from routemaker.stress import BUSY_PAINTED_LANE_AADT

AGENCY = "ddot"

# The rules, by id, with the words the road panel shows after "read as LTS n:". No commas:
# the stress rule's commas separate its reasons (`agency_lts.apply`).
RULE_WORDS = {
    "painted-lane": "a painted lane rated by the traffic beside it",
    "quiet-counted": "a counted street under 1200 cars a day",
    "street-under-3000": "a street with no bike lane under 3000 cars a day",
    "street-3000-8000": "a street with no bike lane carrying 3000 to 8000 cars a day",
    "street-over-8000": "a street with no bike lane over 8000 cars a day",
    "arterial-by-count": "a four- or five-lane road rated by its traffic count",
    "two-lane-by-count": "a two- or three-lane road rated by its traffic count",
    "busy-road-at-1": "a busy roadway DDOT rated with the path or lane beside it",
    "counted-street-at-1": "a counted street too busy for LTS 1",
    "busy-two-lane": "a street with no bike lane over 4500 cars a day",
    "busy-multilane": "a four-lane road over 10000 cars a day",
}

# Which rules the map uses. Each can be struck on its own, as Maryland's can.
ENABLED = frozenset(RULE_WORDS)


@dataclass(frozen=True)
class Block:
    """What a DC way's rules read: DDOT's level, the formula's (half steps included), the
    count, the through lanes both ways together, and the bike facility mapped on it."""

    ddot: float
    formula: float
    aadt: int | None
    lanes: int | None
    painted_lane: bool = False
    protected: bool = False


def total_lanes(lanes_a_direction: int | None, oneway: bool | None) -> int | None:
    """Both directions' through lanes from the formula's lanes a direction."""
    if lanes_a_direction is None:
        return None
    return lanes_a_direction if oneway else 2 * lanes_a_direction


def painted_lane_level(aadt: int | None, lanes: int | None) -> float:
    """A painted lane's level by the traffic beside it. Calibration: where DDOT and the
    formula agree a painted lane is LTS 2 (71 of 80 blocks); the owner's R Street call
    (2026-10-30, painted blocks to 2) and his "make the higher cars/day ones, 2.5" above it.
    The skeptics: 2.5 beside 9,000 a day or more on two lanes (12th St NW), and on three or
    more lanes 2.5, then 3 from 9,000 (Maryland Ave NE, 4th St NE) and 3.5 from 15,000
    (11th St SE at the bridge, Thomas Circle). The formula reads a painted lane at the
    same level whatever the traffic, which this corrects."""
    a = aadt or 0
    if (lanes or 0) >= 3:
        return 2.5 if a < BUSY_PAINTED_LANE_AADT else 3.0 if a < 15_000 else 3.5
    return 2.0 if a < BUSY_PAINTED_LANE_AADT else 2.5


def _rule(b: Block) -> tuple[float, str] | None:
    found = _by_whole_level(b)
    if found is None or found[1] == "painted-lane":
        return found
    level, rule = found
    d, f = b.ddot, b.formula
    # The rules were calibrated on the formula's whole levels; a half step (a busy street at
    # 2.5, `stress`) takes its whole level's rule, and the reading stays between DDOT's level
    # and the formula's half step (a painted lane's returned above, by its traffic). (On whole levels a rule may read past the formula, as at
    # Memorial Bridge; a half step is already the formula's busier reading, so not past it.)
    if d > f:
        level = min(max(level, f), d)
    elif f != math.floor(f):
        level = min(level, f)
    return level, rule


def _by_whole_level(b: Block) -> tuple[float, str] | None:
    d, a, lanes = b.ddot, b.aadt, b.lanes
    f = b.formula
    fw = math.floor(f)
    if d == f or d >= 5 or f >= 5 or b.protected:
        # A protected lane or path on the way: the formula already decides where DDOT is
        # higher (`agency_lts.SUPERSEDED_WHERE_FACILITY`), and DDOT's calmer level stands.
        return None
    if b.painted_lane:
        # Between the two ratings, by the traffic beside the lane.
        level = painted_lane_level(a, lanes)
        # Never above DDOT where DDOT is the higher; never below DDOT where it is calmer.
        level = min(max(level, f), d) if d > f else max(level, d)
        if d > f and level == f:
            # The formula's own level: the facility set-aside already gives it.
            return None
        return level, "painted-lane"
    if a is None:
        return None
    if d > f:
        if d == 2 and fw == 1:
            # Quiet two-way streets: DDOT's 2 stands (LTS 1 is "something kids can go on",
            # 2026-10-13, and the formula's 1 comes mostly from no count), but a measured
            # quiet street is half a step calmer.
            return (1.5, "quiet-counted") if a <= 1_200 else None
        if d >= 3 and fw <= 2:
            # DDOT 3 or 4 on a street the formula reads 2 or calmer: by count (the owner's
            # 1st Street rule, 2026-10-30).
            if a >= 8_000:
                return 3.0, "street-over-8000"
            if a >= 3_000:
                return 2.5, "street-3000-8000"
            return 2.0, "street-under-3000"
        if d == 4 and fw == 3 and lanes is not None:
            if lanes >= 6:
                return None if a >= 10_000 else (3.0, "arterial-by-count")
            if lanes >= 4:
                if a >= 15_000:
                    return None
                return (3.5 if a >= 8_000 else 3.0), "arterial-by-count"
            if a >= 20_000 or (lanes == 3 and a >= 15_000):
                return None
            return (3.5 if a >= 15_000 else 3.0), "two-lane-by-count"
        return None
    # DDOT calmer than the formula.
    if d == 1 and fw >= 3:
        if a >= 30_000:
            return 4.0, "busy-road-at-1"
        if a >= 15_000 and (lanes or 0) >= 3:
            return 3.5, "busy-road-at-1"
        if a >= 6_000:
            return 3.0, "busy-road-at-1"
        return 2.5, "busy-road-at-1"
    if d == 1 and fw == 2:
        if a >= 9_000 or ((lanes or 0) >= 3 and a >= 6_000):
            return 2.5, "counted-street-at-1"
        return (2.0, "counted-street-at-1") if a >= 3_000 else None
    if d == 2 and f > 2:
        # Formula 2.5 too (capped at 2.5 in `_rule`): DDOT's 2 under a busy street.
        if (lanes or 0) >= 4 and a >= 10_000:
            return 3.5, "busy-multilane"
        if a >= 8_000:
            return 3.0, "busy-two-lane"
        return (2.5, "busy-two-lane") if a >= 4_500 else None
    # Elsewhere DDOT's calmer level stands: the review proposed no rule for DDOT 3 under a
    # formula 4, and lowering the formula's 4 there could pull Connecticut Ave NW (the owner's
    # LTS 4) down to 3.5.
    return None


def read_as(b: Block, enabled: Iterable[str] | None = None) -> tuple[float, str] | None:
    """The level DDOT's rating is read as and the rule's id, or None where DDOT's own level
    stands. Where DDOT is above the formula, a painted lane's reading is kept even at DDOT's
    own level: it decides the way, so the facility set-aside (`agency_lts.apply`) must not."""
    found = _rule(b)
    if found is None or found[1] not in set(ENABLED if enabled is None else enabled):
        return None
    if found[0] == b.ddot and not (found[1] == "painted-lane" and b.ddot > b.formula):
        return None
    return found


def words(rule: str, level: float, block: Block | None = None) -> str:
    """The road panel's note: the rule and the facts it read on this block (the owner,
    2026-10-31: "cite the logic in the decision"), e.g. "read as LTS 4: a busy roadway DDOT
    rated with the path or lane beside it (DDOT 2020 LTS 1 and formula LTS 3 on 45334 cars a
    day and 4 through lanes)". No commas (`agency_lts.apply`)."""
    text = f"read as LTS {level:g}: {RULE_WORDS[rule]}"
    if block is None:
        return text
    facts = [f"DDOT 2020 LTS {block.ddot:g} and formula LTS {block.formula:g}"]
    if block.aadt is not None:
        facts.append(f"{block.aadt} cars a day")
    if block.lanes is not None:
        facts.append(f"{block.lanes} through lane{'s' if block.lanes != 1 else ''}")
    if block.painted_lane:
        facts.append("a painted bike lane")
    return (
        f"{text} ({facts[0]} on {' and '.join(facts[1:])})" if facts[1:] else f"{text} ({facts[0]})"
    )
