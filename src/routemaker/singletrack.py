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

from .classes import TRAIL_CLASS_HIGHWAY

SCALE_KEYS = ("mtb:scale", "mtb:scale:imba")
NO_BICYCLE = "singletrack"
_GRADE = re.compile(r"^\s*(\d+)")


def grade(value: str | None) -> int | None:
    """The number an MTB scale value starts with (`2+`, `1-` read as 2, 1)."""
    if value is None:
        return None
    match = _GRADE.match(value)
    return int(match.group(1)) if match else None


def is_singletrack(tags: dict[str, str]) -> bool:
    if tags.get("highway") not in TRAIL_CLASS_HIGHWAY:
        return False
    return any((g := grade(tags.get(key))) is not None and g >= 1 for key in SCALE_KEYS)
