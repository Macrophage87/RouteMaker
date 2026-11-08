"""Mountain-bike singletrack, which no current ride type routes over.

OWNER-DECISIONS 90, 91 and 111: "There's several mountain bike trails too, I
wouldn't route bikes on them either unless that's specifically looked for",
"Gravel is different. Most bikes can handle gravel, few would want to route
through singletrack", and "We will need a whole dedicated MTB mode. There's a
whole set of criteria there." So every ride type avoided singletrack - Gravel
and Mountain Goat included - until the Mountain Bike ride type (docs/MTB-TOPO-PLAN.md,
slice 6) and, since the owner's choice of 2026-10-19 ("Rated, MTB and Gravel"), the
off-road graph reopened the rated singletrack the trail layer draws
(`pipeline.trail_closures.offroad_graph_keeps`).

Singletrack is read from the tags mountain bikers map it with: a trail-class way
rated one or more on either MTB difficulty scale (`mtb:scale`, 0-6, or
`mtb:scale:imba`, 0-4). A zero on either is a trail anyone rides, and gravel,
dirt and ground surfaces are not singletrack on their own: the C&O Canal
towpath above lock 21 is `highway=path`, `bicycle=designated`, `surface=dirt`,
`mtb:scale:imba=0` (way 191655404), and below it `highway=cycleway`,
`surface=fine_gravel`, and both stay the off-road path they are
(OWNER-DECISIONS 93).

The rebuild marks such a way `rm:no_bicycle=singletrack` and the transform
closes it to bicycles on every graph (`lua/routemaker_remap.lua`). A cost would
have been kinder to a ride that starts on one, but no cost reaches a trail:
upstream sets a trail's use from its highway class, so the tier-5 entry charge
does not apply, and the remap may not rewrite `highway`.
"""

from __future__ import annotations

import re

from . import surfaces
from .classes import TRAIL_CLASS_HIGHWAY

SCALE_KEYS = ("mtb:scale", "mtb:scale:imba")
NO_BICYCLE = "singletrack"
_GRADE = re.compile(r"^\s*(\d+)")


# Road paving only, not every hard surface (OWNER-DECISIONS 440): a rated
# wooden ladder, berm or skinny is a mountain-bike feature and stays closed,
# whatever its class or bicycle tag (`routemaker.surfaces`, `is_sealed`).
PAVED_SURFACES = surfaces.SEALED_SURFACES


def is_paved(tags: dict[str, str]) -> bool:
    """Whether a rating no longer makes the way singletrack: road paving."""
    return surfaces.is_sealed(tags)


def grade(value: str | None) -> int | None:
    """The number an MTB scale value starts with (`2+`, `1-` read as 2, 1)."""
    if value is None:
        return None
    match = _GRADE.match(value)
    return int(match.group(1)) if match else None


# The hardest level the off-road graph (Gravel, Mountain Goat) rides on rated singletrack
# the trail layer draws (`pipeline.trail_closures.offroad_graph_keeps`): the owner chose
# "Rated, MTB and Gravel" on 2026-10-19, and "Up to Green (1)" for the cap the same day.
# Harder trails stay the Mountain Bike ride type's.
OFFROAD_MAX_LEVEL = 1


# A gravel trail built for bicycles, rated easy, is the gravel trail it is and not
# singletrack (the hunt of 2026-11-08, A4): mappers put `mtb:scale=1` on crushed-stone
# rail-trails, and the rule closed a bicycle-designated one (or a cycleway, which is one by
# its class) on every graph but the off-road and Mountain Bike ones, though the MTB-class
# rule spares the same trail (`routemaker.trailaccess`). The owner, OWNER-DECISIONS 91:
# "Gravel is different. Most bikes can handle gravel, few would want to route through
# singletrack", and 2026-11-01, "All gravel everywhere" is priced as packed gravel
# (lua/routemaker_remap.lua `strip_easy_gravel_ratings` takes the same easy rating off
# before the parser reads it as a surface). A harder rating (2 and up) is still singletrack.
PACKED_GRAVEL_SURFACES = frozenset({"gravel", "fine_gravel", "compacted"})
EASY_GRAVEL_MAX = 1
# The ratings read here: the two difficulty scales, and `mtb:scale:uphill`, which the Lua
# rule reads too (lua/routemaker_remap.lua `M.SURFACE_RATING_KEYS`: the parser sets a
# surface from it). Terrain hunt 2, T2: with the uphill rating left out here, a gravel
# cycleway rated `mtb:scale=1` and `mtb:scale:uphill=2` was a gravel trail open on every
# graph, while the Lua rule, seeing the uphill 2, kept `mtb:scale=1` for the parser, which
# priced the trail as the gravel class "All gravel everywhere" (2026-11-01) had priced out.
# Both rules now read the same keys: a harder rating (2 and up) on any of them is
# technical ground, as the Lua comment has it, and the trail stays singletrack.
EASY_GRAVEL_KEYS = (*SCALE_KEYS, "mtb:scale:uphill")


def is_built_gravel_trail(tags: dict[str, str]) -> bool:
    """A cycleway, or a trail designated for bicycles, on gravel, fine gravel or compacted,
    rated no harder than `EASY_GRAVEL_MAX` on either scale and uphill (`EASY_GRAVEL_KEYS`)."""
    if tags.get("surface") not in PACKED_GRAVEL_SURFACES:
        return False
    if tags.get("highway") != "cycleway" and tags.get("bicycle") != "designated":
        return False
    grades = [grade(tags.get(key)) for key in EASY_GRAVEL_KEYS if tags.get(key) is not None]
    return all(g is not None and g <= EASY_GRAVEL_MAX for g in grades)


def is_singletrack(tags: dict[str, str]) -> bool:
    if tags.get("highway") not in TRAIL_CLASS_HIGHWAY:
        return False
    # A paved trail is not singletrack whatever its rating: Upper Rock Creek,
    # Northwest Branch, Muddy Branch, Gunpowder Falls and the Cross County
    # Trail carry an mtb:scale on asphalt (review r1).
    if is_paved(tags):
        return False
    if is_built_gravel_trail(tags):
        return False
    return any((g := grade(tags.get(key))) is not None and g >= 1 for key in SCALE_KEYS)


# The difficulty levels the map draws a mountain-bike trail in (OWNER-DECISIONS 456,
# 456a-c; docs/MTB-TOPO-PLAN.md, slice 2): one scale, set by the higher of the two
# ratings. Level 1 is S1 or IMBA 1 (green), 2 is S2 or IMBA 2 (blue), 3 is S3 or IMBA 3
# (black) and 4 is S4 or above or IMBA 4 or above (red).
MTB_LEVELS = (1, 2, 3, 4)
# The highest grade each scale has; a larger number (7 on `mtb:scale`, 5 on IMBA) is read as
# the top, so a closed trail rated off the scale is still drawn as the hardest level, never
# as the unrated grey that says Gravel and Mountain Goat may use it (review of slice 2).
SCALE_TOP = {"mtb:scale": 6, "mtb:scale:imba": 4}
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def scale_grade(value: str | None, top: int) -> int | None:
    """The hardest grade an MTB scale value names: `2+` 2, `1-` 1, `0` 0, a range or list
    (`1-2`, `1;2`) its higher end, `S2` 2, `1.5` 1, a number past the scale's `top` the
    top. None for no value or no number in it.

    Unlike `grade` (the singletrack closure's reading, the number a value starts with), a
    range's higher end is taken: the map should not draw a trail easier than its mapper
    rated any part of it."""
    if value is None:
        return None
    grades = [int(float(number)) for number in _NUMBER.findall(value)]
    return min(max(grades), top) if grades else None


def mtb_level(tags: dict[str, str]) -> int | None:
    """The way's mountain-bike difficulty level, 1 to 4, or None (OWNER-DECISIONS 456,
    456a-c): the higher of `mtb:scale` and `mtb:scale:imba`, S1-S3 to 1-3 and S4-S6 to 4
    (IMBA 1-4 are 1-4 already).

    A rating of 0 is the easiest grade on both scales, and it is no level here: a way rated
    0 on its scale or scales, and not 1 or more on the other, is a gravel trail, not an MTB
    level (456b), so it is None, like an unrated way, and keeps the look it has without a
    rating (an ordinary unpaved path, or the grey dashes of an unrated mountain-bike trail).
    A way rated 0 on one scale and 1 or more on the other takes the other's level.

    The rebuild writes it only on rated singletrack (`segment.mtb_level`;
    `pipeline.trail_closures.mtb_level`), so a level always means a trail closed on every
    graph: `is_singletrack` reads a value's leading number alone, and this reading would
    give a level to a way it does not call singletrack (`S2`, `0-2`), which the off-road
    graph may open. A paved trail that carries a rating (Upper Rock Creek, the Cross County
    Trail) is not singletrack either, and gets none."""
    grades = [
        g for key in SCALE_KEYS if (g := scale_grade(tags.get(key), SCALE_TOP[key])) is not None
    ]
    hardest = max(grades, default=0)
    return min(hardest, MTB_LEVELS[-1]) if hardest >= 1 else None


def mtb_scale_words(tags: object) -> str | None:
    """Which scale set a rated trail's level, in words (the owner, 2026-10-28: "say which
    rating type triggered the rating and if they are rated on both scales say that"), from
    its kept `mtb:scale` and `mtb:scale:imba` (`segment.trail_tags`): 'S2', 'IMBA 2', 'S2 and
    IMBA 2 (rated on both scales)', or, where the two differ, the one that set the level
    first, 'IMBA 3 (also rated S2, easier)'. None where
    neither is kept (a table built before the scales were kept), so the caller says both.
    The front end's copy is `mtbScaleWords` in frontend/src/lib/featureHover.ts."""
    if not isinstance(tags, dict):
        return None
    grades = {}
    for key in SCALE_KEYS:
        value = tags.get(key)
        grade = scale_grade(value, SCALE_TOP[key]) if isinstance(value, str) else None
        if grade is not None:
            grades[key] = grade
    named = {
        "mtb:scale": f"S{grades.get('mtb:scale')}",
        "mtb:scale:imba": f"IMBA {grades.get('mtb:scale:imba')}",
    }
    if len(grades) == 2:
        s_level = min(grades["mtb:scale"], MTB_LEVELS[-1])
        imba_level = min(grades["mtb:scale:imba"], MTB_LEVELS[-1])
        if s_level == imba_level:
            return f"{named['mtb:scale']} and {named['mtb:scale:imba']} (rated on both scales)"
        harder, other = (
            ("mtb:scale", "mtb:scale:imba")
            if s_level > imba_level
            else ("mtb:scale:imba", "mtb:scale")
        )
        return f"{named[harder]} (also rated {named[other]}, easier)"
    return next((named[key] for key in SCALE_KEYS if key in grades), None)


# The tags a mountain-bike trail's name is read from, first found wins (the owner,
# 2026-10-10: "Also, for mountain bikes, try to make sure trail names are added in if they
# are available."): the way's own name, then the name mountain bikers give it, then its
# reference last, since a bare `ref` ("12") on the map could be read as a level.
NAME_KEYS = ("name", "mtb:name", "ref")


def mtb_name(tags: dict[str, str]) -> str | None:
    """The name the map labels a mountain-bike trail with: `name`, else `mtb:name`, else
    `ref`, trimmed; None when none of them has one. The rebuild writes it on the
    mountain-bike-only ways (`segment.mtb_name`)."""
    for key in NAME_KEYS:
        value = (tags.get(key) or "").strip()
        if value:
            return value
    return None
