"""Mountain-bike singletrack, which no current ride type routes over.

OWNER-DECISIONS 90, 91 and 111: "There's several mountain bike trails too, I
wouldn't route bikes on them either unless that's specifically looked for",
"Gravel is different. Most bikes can handle gravel, few would want to route
through singletrack", and "We will need a whole dedicated MTB mode. There's a
whole set of criteria there." So every ride type avoids singletrack - Gravel
and Mountain Goat included - and a mode that seeks it is the backlog's.

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


def is_singletrack(tags: dict[str, str]) -> bool:
    if tags.get("highway") not in TRAIL_CLASS_HIGHWAY:
        return False
    # A paved trail is not singletrack whatever its rating: Upper Rock Creek,
    # Northwest Branch, Muddy Branch, Gunpowder Falls and the Cross County
    # Trail carry an mtb:scale on asphalt (review r1).
    if is_paved(tags):
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
    rating (an ordinary unpaved path, or the grey dots of an unrated mountain-bike trail).
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
