"""The Mountain Bike ride type's rules, pure (docs/MTB-TOPO-PLAN.md, slice 6).

OWNER-DECISIONS 90, 111, 148 and 454: "We will need a whole dedicated MTB mode. There's a
whole set of criteria there."; "Mountain Goat and Mountain Bike are separate modes." The
criteria were listed for the owner on 2026-10-11 and approved as they stand ("Those work for
me.", 7:45 am; /mnt/project-files/plans/v0.5.0-plan.md, "Stephen's answers
(2026-10-11)"):

- hardest trail level 2 (blue, IMBA 2), with a choice of 1-4 (`DEFAULT_MAX_LEVEL`, `LEVELS`);
- unrated mountain-bike trails open as level 2 (`UNRATED_LEVEL`);
- strong trail seeking: a trail mile counts about half a road mile (`TRAIL_WEIGHT`);
- connecting roads up to LTS 2, with LTS 3 for gaps under 0.5 mi (`CONNECTOR_MAX_TIER`,
  `GAP_TIER`, `GAP_MAX_M`);
- hills dial at "fine with hills" (`core.presets`);
- loop from a trailhead on (`core.presets`, the front end);
- about 6 mph (10 km/h) on singletrack (`SINGLETRACK_SPEED_KMH`), for time estimates;
- mountain-bike and contour layers on (the front end);
- one-way trails followed; bike-banned and hiking-only trails stay closed (the graph:
  `pipeline.variants.Variant.MTB` opens only what nothing but a rating closes, and Valhalla
  follows `oneway`);
- wet closures not routed on (`closed_when_wet`); the trail page links to MORE's conditions
  (`routemaker.more_links`);
- one MORE link per trail system where MORE has a page, else one general link.

The graph opens every level; the rider's hardest level is held here and in `core.mtb`, on the
router's routes, so one graph serves every choice.

Second pass (the owner, 2026-10-11): "two options for difficulty: preferred difficulty and max
difficulty. Basically it would try to find routes near that intended difficulty and avoid routes
past max difficulty." The hardest level above is the max; the preferred level (default 2, never
above the max: `preferred_level`) prices the trails up to it in the ranking, a level away from
it costing LEVEL_STEP more of a road metre (`LEVEL_STEP`, `Reading.weighted_m`).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

LEVELS = (1, 2, 3, 4)
DEFAULT_MAX_LEVEL = 2
# An unrated mountain-bike trail (the mountain-bike class with no level) counts as this level.
UNRATED_LEVEL = 2

# The rider's preferred level (the second pass): trails at it cost least. An old link or request
# with only the hardest level prefers min(DEFAULT_PREFERRED_LEVEL, hardest).
DEFAULT_PREFERRED_LEVEL = 2
# Each level a trail is away from the preferred one, easier or harder, adds this much of a road
# metre to its trail metre: at TRAIL_WEIGHT 0.5, a trail one level off counts 0.65 of a road
# metre, three levels off 0.95, still below a road, so the preference never sends a route from a
# trail onto a road; it picks among the trails.
LEVEL_STEP = 0.15

# A metre of trail counts this much of a metre of road in the ranking (the owner's "a trail
# mile counts about half a road mile").
TRAIL_WEIGHT = 0.5

# Connecting roads: LTS 1 and 2 freely; LTS 3 only for a gap shorter than GAP_MAX_M (0.5 mi);
# LTS 4 and Avoid (5) never, where a route without them exists.
CONNECTOR_MAX_TIER = 2
GAP_TIER = 3
GAP_MAX_M = 0.5 * 1609.344

# About 6 mph (10 km/h) on singletrack and mountain-bike trails, for the time shown.
SINGLETRACK_SPEED_KMH = 10.0


def effective_level(mtb_only: bool, mtb_level: int | None) -> int | None:
    """The level a way counts as for the hardest-level choice: its own (1-4) on a rated
    trail, UNRATED_LEVEL on an unrated mountain-bike trail, None on any other way (a road,
    an ordinary path or trail), which no level choice closes."""
    if mtb_level in LEVELS:
        return int(mtb_level)
    if mtb_only:
        return UNRATED_LEVEL
    return None


def over_level(mtb_only: bool, mtb_level: int | None, max_level: int) -> bool:
    level = effective_level(mtb_only, mtb_level)
    return level is not None and level > max_level


def clamp_level(level: int | None) -> int:
    """The rider's choice, or the default; held to 1-4."""
    if level is None:
        return DEFAULT_MAX_LEVEL
    return min(max(int(level), LEVELS[0]), LEVELS[-1])


def preferred_level(preferred: int | None, max_level: int | None) -> int:
    """The rider's preferred level, or the default; held to 1-4 and never above the hardest
    level (`clamp_level(max_level)`): a link with only the old level reads min(2, that level)."""
    top = clamp_level(max_level)
    if preferred is None:
        return min(DEFAULT_PREFERRED_LEVEL, top)
    return min(clamp_level(preferred), top)


# --- wet closures -----------------------------------------------------------------------

# The conditional keys a wet closure is mapped on (OSM wiki, "Conditional restrictions":
# `access:conditional=no @ wet`, read 2026-10-11).
WET_KEYS = tuple(
    f"{mode}{side}:conditional"
    for mode in ("access", "vehicle", "bicycle", "mtb")
    for side in ("", ":forward", ":backward")
)
CLOSED_VALUES = frozenset({"no", "private", "dismount"})
_WET = re.compile(r"\bwet\b", re.IGNORECASE)


def _branches(value: str) -> Iterable[tuple[str, str]]:
    """(value, condition) pairs of an OSM conditional: `no @ wet; yes @ (Sa,Su)`."""
    depth, start, parts = 0, 0, []
    for i, char in enumerate(value):
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(depth - 1, 0)
        elif char == ";" and depth == 0:
            parts.append(value[start:i])
            start = i + 1
    parts.append(value[start:])
    for part in parts:
        if "@" not in part:
            continue
        head, _, condition = part.partition("@")
        yield head.strip().lower(), condition.strip()


def closed_when_wet(tags: dict[str, str]) -> bool:
    """Whether a way is mapped closed when wet (`bicycle:conditional=no @ wet` and the like).
    The graph cannot know the ground, so the Mountain Bike graph treats it as closed, and the
    trail page sends the rider to MORE for the day's conditions (the owner's defaults of
    2026-10-11: "wet closures not routed on")."""
    for key in WET_KEYS:
        value = tags.get(key)
        if not value:
            continue
        for head, condition in _branches(value):
            if head in CLOSED_VALUES and _WET.search(condition):
                return True
    return False


# --- a route's reading -------------------------------------------------------------------


@dataclass(frozen=True)
class Stretch:
    """One piece of a route as the ranking reads it: its length, stress tier (1-5, or None
    for unknown), whether it is trail (a mountain-bike trail, or an unpaved trail-class way),
    whether it is singletrack (a mountain-bike-only way), and its level for the choice."""

    metres: float
    tier: int | None
    trail: bool
    singletrack: bool
    level: int | None


@dataclass(frozen=True)
class Reading:
    length_m: float
    trail_m: float
    singletrack_m: float
    # Metres on trails above the rider's hardest level.
    over_level_m: float
    # Connecting roads past the rule: LTS 3 runs of GAP_MAX_M or longer (their whole length),
    # and every metre of LTS 4 and Avoid.
    long_lts3_m: float
    lts4_m: float
    # Metres on trails up to the hardest level but easier, or harder, than the preferred one.
    easier_m: float = 0.0
    harder_m: float = 0.0
    # The preference's price: LEVEL_STEP of a road metre per level away, summed over them.
    level_extra_m: float = 0.0

    @property
    def weighted_m(self) -> float:
        """The ranking's length: a trail metre counts TRAIL_WEIGHT of a road metre, and
        LEVEL_STEP more for each level it is away from the preferred one."""
        return self.length_m - self.trail_m + TRAIL_WEIGHT * self.trail_m + self.level_extra_m

    @property
    def breach_m(self) -> float:
        return self.long_lts3_m + self.lts4_m


def read(stretches: Sequence[Stretch], max_level: int, preferred: int | None = None) -> Reading:
    """A route's figures for the ranking, from its stretches in riding order. `preferred`
    None: no preferred level, every trail up to the hardest level alike (the first pass).
    Only a way with a level is priced by it: a road, or an ordinary unpaved path (rated 0,
    no MTB level: 456b), keeps its weight whatever the preference."""
    length = trail = single = over = lts4 = 0.0
    easier = harder = extra = 0.0
    long_lts3 = 0.0
    run = 0.0

    def close_run() -> float:
        return run if run >= GAP_MAX_M else 0.0

    for s in stretches:
        length += s.metres
        if s.trail:
            trail += s.metres
        if s.singletrack:
            single += s.metres
        if s.level is not None and s.level > max_level:
            over += s.metres
        elif s.level is not None and preferred is not None and s.level != preferred:
            if s.level < preferred:
                easier += s.metres
            else:
                harder += s.metres
            extra += LEVEL_STEP * abs(s.level - preferred) * s.metres
        if s.tier is not None and s.tier >= 4 and not s.trail:
            lts4 += s.metres
        if s.tier == GAP_TIER and not s.trail:
            run += s.metres
        elif s.metres > 0:
            long_lts3 += close_run()
            run = 0.0
    long_lts3 += close_run()
    return Reading(length, trail, single, over, long_lts3, lts4, easier, harder, extra)


def better(a: Reading, b: Reading) -> bool:
    """Whether route `a` ranks above route `b`: fewer metres above the rider's level first
    (a hard rule the search tries to clear), then fewer metres of connecting road past the
    rule (beyond 50 m of slack, so a crossing does not decide it), then the shorter weighted
    length (trail at half, more for a trail away from the preferred level)."""
    if abs(a.over_level_m - b.over_level_m) > 1.0:
        return a.over_level_m < b.over_level_m
    if abs(a.breach_m - b.breach_m) > 50.0:
        return a.breach_m < b.breach_m
    return a.weighted_m < b.weighted_m


def best(readings: Sequence[Reading]) -> int:
    """The index of the best-ranked route (the first on a tie)."""
    chosen = 0
    for i in range(1, len(readings)):
        if better(readings[i], readings[chosen]):
            chosen = i
    return chosen


def duration_s(router_s: float, length_m: float, singletrack_m: float) -> float:
    """The time shown: the router's time for the rest of the route, in proportion, and
    SINGLETRACK_SPEED_KMH on the singletrack. The router times a trail as it times a
    smooth path; a rider on singletrack goes about 6 mph (10 km/h). Never less than the
    router's own time: a steep trail it already times slower keeps its time."""
    if length_m <= 0 or singletrack_m <= 0:
        return router_s
    singletrack_m = min(singletrack_m, length_m)
    share = router_s * singletrack_m / length_m
    return router_s - share + max(share, singletrack_m / (SINGLETRACK_SPEED_KMH / 3.6))
