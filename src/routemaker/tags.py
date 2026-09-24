"""Parsing OpenStreetMap tag values into the quantities the classifier reads.

Every parser here returns `None` rather than a guess when a tag is missing or
unreadable. The defaulting happens once, in `stress`, where the rule is to err
toward the higher-stress reading; scattering defaults through the parsers would
hide which values were measured and which were assumed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .geo import METRES_PER_FOOT

MPH_PER_KMH = 0.621371

# Posted speeds that OSM expresses as a country default rather than a number.
# Conservative readings: a US urban default is 25 mph in most of this region, and
# anything unrecognised is treated as unknown rather than as slow.
IMPLICIT_MAXSPEED_MPH = {
    "US:urban": 25.0,
    "US:residential": 25.0,
    "DC:urban": 20.0,
    "DC:residential": 20.0,
    "MD:urban": 30.0,
    "VA:urban": 25.0,
    "US:rural": 55.0,
    "walk": 5.0,
}

_SPEED = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(mph|km/h|kmh|kph)?\s*$", re.I)


def maxspeed_is_unitless(value: str | None) -> bool:
    """Whether a `maxspeed` value is a bare number with no unit.

    Kept separate from the parse so the classifier can record the unit as an
    assumption: the number was surveyed, the unit was not.
    """
    if not value or value in IMPLICIT_MAXSPEED_MPH:
        return False
    match = _SPEED.match(value)
    return bool(match) and not match.group(2)


def parse_maxspeed_mph(value: str | None) -> float | None:
    """Posted speed in mph.

    A bare number is read as **mph**, not as km/h. That is the opposite of the
    OSM convention, and it is deliberate for this deployment. The coverage area
    is a single US metro, where the number on the sign is in miles per hour and
    `maxspeed=45` is a US mapper omitting the unit rather than a 45 km/h zone -
    which does not exist here. Reading it as km/h turned 45 into 28 mph and
    dropped a 45 mph arterial to LTS2, which is the lower-stress reading of an
    ambiguous tag; the plan's rule for every ambiguous input is to err toward the
    higher-stress reading. The unit is recorded as an assumption so a reviewer
    can see which tier rested on it.

    If the coverage area ever leaves the United States this has to change with
    it, which is why it is one function and one comment rather than a constant.
    """
    if not value:
        return None
    if value in IMPLICIT_MAXSPEED_MPH:
        return IMPLICIT_MAXSPEED_MPH[value]
    match = _SPEED.match(value)
    if not match:
        return None
    number = float(match.group(1))
    unit = (match.group(2) or "").lower()
    return number * MPH_PER_KMH if unit in {"km/h", "kmh", "kph"} else number


def parse_int(value: str | None) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


# The width forms OSM actually carries here, and the one place they are read.
# Whitespace is stripped first, as in the Lua, so "3 ft" and "3ft" are one case.
_WIDTH_COMMA = re.compile(r"^(\d+),(\d+)$")
_WIDTH_FEET_INCHES = re.compile(r"^(\d+\.?\d*)'(\d+\.?\d*)\"?$")
_WIDTH_FEET = re.compile(r"^(\d+\.?\d*)(?:'|ft|feet)$")
_WIDTH_METRES = re.compile(r"^(\d+\.?\d*)m?$")


def parse_width_m(value: str | None) -> float | None:
    """Width in metres, or None when the value cannot be read.

    Deliberately the same grammar as `M.parse_width_m` in
    `lua/routemaker_remap.lua`, value for value, and pinned against the same
    table of cases that the Lua suite uses. The two parsers read the same OSM
    tags on the same extract - this one for `shoulder:*:width` and
    `cycleway:*:width`, the Lua one for a bollard's `maxwidth` - and while they
    disagreed the disagreement ran in the dangerous direction both ways:
    `"8 feet"` came back as 8.0 *metres* here, a twenty-six-foot shoulder, which
    clears Furth's widest criterion and rates a road low-stress on a tag that
    says nothing of the kind; while `"2.4m"`, `"1,5"` and `5'6"` came back as
    None here and parsed correctly in the Lua, so a surveyed width was silently
    an unsurveyed one on this side of the pipeline.

    The module's rule holds: anything this cannot read is None, never a guess.
    A bare number is metres, which is OSM's convention for `width` and is the
    opposite of the `maxspeed` decision one function up - `maxspeed` has a US
    sign behind it and width does not.
    """
    if not value:
        return None
    text = "".join(str(value).lower().split())

    # Comma as the decimal separator: "1,5" is one and a half metres. Only when
    # it separates digits and appears once, so a list like "1,5,2" is refused
    # rather than guessed at.
    if comma := _WIDTH_COMMA.match(text):
        text = f"{comma.group(1)}.{comma.group(2)}"

    # Feet, with or without inches: 5'6", 3', 3ft, 3feet.
    if match := _WIDTH_FEET_INCHES.match(text):
        return (
            float(match.group(1)) * METRES_PER_FOOT + float(match.group(2)) * METRES_PER_FOOT / 12
        )
    if match := _WIDTH_FEET.match(text):
        return float(match.group(1)) * METRES_PER_FOOT

    # Metres, with or without the unit spelled out.
    match = _WIDTH_METRES.match(text)
    return float(match.group(1)) if match else None


def is_oneway(tags: dict[str, str]) -> bool:
    return tags.get("oneway") in {"yes", "1", "-1", "true"}


DIRECTIONAL_LANE_KEYS = ("lanes:forward", "lanes:backward")


def lanes_per_direction(tags: dict[str, str]) -> int | None:
    """Through lanes in the direction of travel.

    `lanes` counts both directions on a two-way road, so comparing a raw `lanes`
    value against a Furth table built on per-direction counts reads every two-way
    street as one class worse than it is.

    Where both directional keys are present the *larger* of the two is returned,
    rather than whichever of them is read first. They are not alternatives, they
    are the two directions, and a way is scored once for both: one tier is
    stored per way and a rider uses the way in either direction. So
    `lanes=4, lanes:forward=1, lanes:backward=3` is a road that carries three
    lanes one way round, and returning the forward 1 read it as a single-lane
    street - LTS3 on the mixed-traffic table where its mirror image, the same
    road with the two values swapped, came out LTS4. Taking the maximum is this
    module's rule of erring toward the higher-stress reading of an ambiguous
    input, and it is what makes the tier independent of which side a mapper
    happened to tag first.
    """
    directional = [
        value for key in DIRECTIONAL_LANE_KEYS if (value := parse_int(tags.get(key))) is not None
    ]
    if directional:
        return max(1, max(directional))
    total = parse_int(tags.get("lanes"))
    if total is None:
        return None
    if is_oneway(tags):
        return max(1, total)
    return max(1, total // 2)


def has_parking_lane(tags: dict[str, str]) -> bool | None:
    """Whether on-street parking runs alongside, which changes the bike-lane table.

    Returns None when nothing in the tags speaks to it, since absence of a
    `parking:*` tag is not evidence that parking is absent.
    """
    # Only the schemes that actually describe a parking lane. `parking:condition:*`
    # is not evidence that parking exists.
    prefixes = ("parking:lane", "parking:left", "parking:right", "parking:both")
    values = [v for k, v in tags.items() if k.startswith(prefixes)]
    if not values:
        return None
    # `no_parking`, `no_stopping` and `no_standing` all say parking is absent.
    # Reading them as present flipped the bike-lane width threshold from 1.7 m to
    # 4.1 m and, worse, removed "parking" from the assumed list - so the result
    # claimed the input was measured while reading it backwards.
    absent = {"no", "none", "separate", "no_parking", "no_stopping", "no_standing"}
    return any(v not in absent for v in values)


# The `cycleway` values that describe a facility *on this way*, split by how much
# separation the facility gives, because the two sets score on different tables.
# They live here rather than in `stress` because `cycleway_provision` has to rank
# one side of a road against the other before the classifier sees either, and
# ranking needs to know which values are facilities and how much they give;
# `stress` imports both names and reads them at the facility step.
#
# `separate` is deliberately absent from both, and its absence is the whole of
# the rule these sets encode: a cycleway value has to describe a facility this
# way carries. `cycleway=separate` says the opposite - that the facility is
# mapped as a way of its own, somewhere off to the side - so it is a pointer to
# another OSM object and says nothing whatever about the carriageway. Reading it
# as a separated track here rated the roadway by the facility next to it: a
# 45 mph six-lane primary tagged `cycleway=separate` came out LTS1, where the
# same road bare comes out LTS4, and it shut the volume gate too because a
# cycleway value counts as a provision. The separate way is in the extract and
# is classified on its own merits - it is trail-class, so it returns LTS1 at the
# top of `classify` - so the low-stress reading is already in the graph, on the
# object that earned it. The roadway is scored as the roadway it is.
#
# `has_parking_lane` reads the same OSM idiom the same way: `parking:*=separate`
# is in its `absent` set, because there too the value means "recorded
# elsewhere", not "present here".
#
# `left` and `right` are absent for a related reason: they are key suffixes
# (`cycleway:left=lane`), never values, and the side record only ever holds the
# value half of a tag. Listing them here could only ever match a way tagged
# `cycleway=left`, which is not a thing a mapper writes.
SEPARATED_CYCLEWAY = frozenset({"track", "opposite_track"})
PAINTED_CYCLEWAY = frozenset({"lane", "opposite_lane", "buffered_lane"})

SIDES = ("left", "right")

# The key forms that speak for one side of the road, most specific first. The
# order is the precedence and it is the whole of the side model: a side key
# answers for its side alone, `:both` answers for each side the side key leaves
# unsaid, and the bare key answers for whatever is left. `cycleway=track` with
# `cycleway:right=no` is therefore a track on the left and nothing on the right
# - the mapper's refinement of the general tag - and never "a track, somewhere".
#
# `lua/routemaker_remap.lua` carries the same table as `M.CYCLEWAY_SIDE_KEYS`,
# and `tests/test_lua_remap.py` holds the two to one another.
CYCLEWAY_SIDE_KEYS = {side: (f"cycleway:{side}", "cycleway:both", "cycleway") for side in SIDES}
CYCLEWAY_SIDE_WIDTH_KEYS = {
    side: (f"cycleway:{side}:width", "cycleway:both:width", "cycleway:width") for side in SIDES
}
# Every key form a cycleway value arrives in, for readers that ask about the
# way as a whole rather than about one side of it.
CYCLEWAY_KEYS = ("cycleway", "cycleway:both", "cycleway:left", "cycleway:right")


def _first(tags: dict[str, str], keys: tuple[str, ...]) -> str | None:
    """The value of the most specific key present, read in precedence order."""
    for key in keys:
        if value := tags.get(key):
            return value
    return None


def _first_width(tags: dict[str, str], keys: tuple[str, ...]) -> float | None:
    """The most specific surveyed width, read in precedence order."""
    for key in keys:
        if (width := parse_width_m(tags.get(key))) is not None:
            return width
    return None


def _facility_rank(value: str | None) -> int:
    """How much separation one side's value gives. Higher is better."""
    if value in SEPARATED_CYCLEWAY:
        return 2
    if value in PAINTED_CYCLEWAY:
        return 1
    return 0


@dataclass(frozen=True)
class CyclewaySide:
    """What one side of the road carries: one value and one width.

    `value` is the tag value the precedence settles on, or None when no key
    speaks for the side. `width_m` is the side's own surveyed width, read with
    the same precedence, and it is dropped when the side declares something that
    is not a facility: a side saying `no` has nothing, so it has no lane to be
    wide. A side nobody has spoken for keeps a width somebody surveyed, since the
    survey is the only fact about it.
    """

    value: str | None
    width_m: float | None

    @property
    def rank(self) -> int:
        return _facility_rank(self.value)


def cycleway_sides(tags: dict[str, str]) -> dict[str, CyclewaySide]:
    """The two sides of the road, each resolved on its own by the precedence."""
    sides = {}
    for side in SIDES:
        value = _first(tags, CYCLEWAY_SIDE_KEYS[side])
        width = _first_width(tags, CYCLEWAY_SIDE_WIDTH_KEYS[side])
        if value is not None and _facility_rank(value) == 0:
            width = None
        sides[side] = CyclewaySide(value, width)
    return sides


@dataclass(frozen=True)
class Provision:
    """The facility on the worst direction a rider may be made to use.

    `values` are the resolved values of the sides that set it and `width_m` the
    narrowest surveyed width among those sides, or None if none is surveyed.
    """

    rank: int
    values: frozenset[str]
    width_m: float | None


def _directions(tags: dict[str, str], sides: dict[str, CyclewaySide]) -> list[list[CyclewaySide]]:
    """The directions of bicycle travel, each as the sides that can serve it.

    On a two-way street each side is one direction. On a one-way street there
    is one direction and either side serves it.
    """
    left, right = sides["left"], sides["right"]
    if not is_oneway(tags):
        return [[left], [right]]
    return [[left, right]]


def cycleway_provision(tags: dict[str, str]) -> Provision:
    """The cycleway provision the way is scored on: **the worst direction**.

    Each direction takes the best facility among the sides that serve it, and
    the way takes the weakest direction, because one tier is stored per way and
    a rider uses it either way round. The width is the narrowest surveyed width
    among the sides that set the provision - the sides the rider is on - so a
    track's width on one side never rates the painted lane on the other.

    Measured, before this, on a 35 mph four-lane two-way secondary where the
    bare road is LTS4: `cycleway=track` with `cycleway:right=no` came out LTS1,
    because the general key was unioned into the right side and the best value
    kept. The right side says `no`, and the side key is the more specific tag.
    """
    ranked = []
    for candidates in _directions(tags, cycleway_sides(tags)):
        best = max((s.rank for s in candidates), default=0)
        ranked.append((best, [s for s in candidates if s.rank == best]))
    rank = min(best for best, _ in ranked)
    used = [s for best, candidates in ranked if best == rank for s in candidates]
    widths = [s.width_m for s in used if s.width_m is not None]
    return Provision(
        rank,
        frozenset(s.value for s in used if s.value is not None),
        min(widths) if widths else None,
    )


def cycleway_values(tags: dict[str, str]) -> set[str]:
    """The cycleway values describing the provision a rider may be made to use.

    One rule, the same one `cycleway_width_m`, `has_shoulder` and
    `shoulder_width_m` keep: **score the worst side a rider may be made to use.**

    On a two-way street each side is a direction. A rider heading one way is on
    the left-hand side and heading the other way is on the right, and one tier
    is stored per way, so the way's provision is the *weaker* of its two sides.
    A side with no facility - no key speaking for it, or the most specific key
    that does saying `no` - is no facility, and a one-sided lane on a two-way
    street is therefore mixed traffic for the direction that does not have it.

    On a one-way street there is only one direction of travel, so a facility on
    either side is the facility of the only trip anyone makes on the way. That
    is most of the District's protected network, where `cycleway:left=
    opposite_lane` and `cycleway:left=track` on a one-way street are how a
    contraflow lane is tagged.

    Returns the weaker direction's values, so an absent or `no` side answers
    with what it says rather than with the other side's facility.
    """
    return set(cycleway_provision(tags).values)


def cycleway_width_m(tags: dict[str, str]) -> float | None:
    """The narrowest surveyed width on the sides the provision is scored on.

    A width belongs to its side: `cycleway:left:width` is the left lane's,
    `cycleway:both:width` each side's unless that side has its own, and
    `cycleway:width` whatever is left. The sides compared are the ones that set
    the provision, so the narrower of two painted lanes is the answer - a rider
    is on whichever side the route uses, and the tile build does not know which
    - while a track's width never stands in for the painted lane opposite it.
    A side with no surveyed width does not enter the comparison.
    """
    return cycleway_provision(tags).width_m


# The shoulder keys, split into levels the way the cycleway keys are, most
# specific first: each level is a presence key and its width key.
SHOULDER_SIDE_LEVELS = {
    side: (
        (f"shoulder:{side}", f"shoulder:{side}:width"),
        ("shoulder:both", "shoulder:both:width"),
        ("shoulder", "shoulder:width"),
    )
    for side in SIDES
}

SHOULDER_ABSENT = frozenset({"no", "none"})


def _shoulder_levels(tags: dict[str, str], side: str) -> list[tuple[str | None, float | None]]:
    """One side's (presence, width) at each level, most specific first.

    The bare `shoulder` key also takes a side as its value (`shoulder=right`),
    and then it speaks for the named side only, and says `no` for the other.
    """
    levels = []
    for presence_key, width_key in SHOULDER_SIDE_LEVELS[side]:
        value, width = tags.get(presence_key) or None, parse_width_m(tags.get(width_key))
        if presence_key == "shoulder" and value in SIDES and value != side:
            value, width = "no", None
        levels.append((value, width))
    return levels


def _shoulder_on_side(tags: dict[str, str], side: str) -> tuple[bool | None, float | None]:
    """Whether one side of the road has a shoulder, and how wide it is.

    The first level that says anything about the side answers for it - a
    presence key or a surveyed width, and the width is presence on its own. So
    `shoulder=yes` + `shoulder:width=2.4` + `shoulder:right=no` has no shoulder
    on the right: the side key is the more specific tag, and the general width
    measured the shoulder that exists, on the left. Within one level a width
    beats a `no`; see `has_shoulder`. A side found present takes the most
    specific width surveyed for it at that level or below.

    Returns (None, None) when nothing speaks for the side.
    """
    levels = _shoulder_levels(tags, side)
    for index, (value, width) in enumerate(levels):
        if width is None and value is None:
            continue
        if width is None and value in SHOULDER_ABSENT:
            return False, None
        below = [w for _, w in levels[index:] if w is not None]
        return True, below[0] if below else None
    return None, None


def _shoulder_directions(tags: dict[str, str]) -> list[list[tuple[bool | None, float | None]]]:
    left, right = (_shoulder_on_side(tags, side) for side in SIDES)
    if is_oneway(tags):
        return [[left, right]]
    return [[left], [right]]


def has_shoulder(tags: dict[str, str]) -> bool | None:
    """Whether a rider going either way along the road has a shoulder to sit in.

    Each side is read on its own and the sides are then combined by
    `cycleway_provision`'s rule, which is this module's one rule for a provision
    that can be tagged per side: **score the worst side a rider may be made to
    use.** On a two-way street the two sides are the two directions of travel,
    one tier is stored per way, and a shoulder on the right only is nothing at
    all to a rider heading the other way - so both sides have to have one. On a
    one-way street there is one direction and one side in use, so either side
    answers for the way.

    Returns None only when nothing in the tags speaks to shoulders at all, since
    absence of a `shoulder:*` tag is not evidence that shoulders are absent. A
    way that says something about one side and nothing about the other has
    spoken, and the answer for the way is False.

    Within a side the keys are a general tag and refinements of it, and the most
    specific one that speaks answers: a way carrying `shoulder=no` *and*
    `shoulder:right=yes` has a shoulder on the right, and a way carrying
    `shoulder=yes` and `shoulder:right=no` has none there.

    A surveyed width counts as presence on its own. `shoulder:width=2.4` with no
    presence key is a mapper who measured the shoulder and did not separately
    assert that it exists; reading that as "no shoulder tagged" threw away the
    only measurement on the way, and it is the measurement, not the presence
    key, that the bike-lane table needs.

    That includes the contradictory pair at one level, and deliberately:
    `shoulder=no` together with `shoulder:width` reads as **present**. The two
    tags disagree, and the width is the survey - somebody went and measured a
    shoulder, which is not a thing to do to a road that has none. It errs toward
    the lower-stress reading on a contradiction, which is the one place in this
    module that happens, and it is bounded - the width still has to clear
    `RIDEABLE_SHOULDER_M` before `stress` credits anything for it. A `no` on a
    *more specific* key than the width is not a contradiction but a refinement,
    and the side has nothing.
    """
    directions = _shoulder_directions(tags)
    if all(present is None for sides in directions for present, _ in sides):
        return None
    return all(any(present for present, _ in sides) for sides in directions)


def shoulder_width_m(tags: dict[str, str]) -> float | None:
    """The narrowest surveyed width among the shoulders the way is scored on.

    The narrowest rather than the first: a way with a shoulder on each side has
    a rider on whichever side the route uses, and the tile build does not know
    which. A width belongs to its side, so a side with no shoulder contributes
    none, and a side with no surveyed width does not enter the comparison.
    """
    widths = [
        width
        for sides in _shoulder_directions(tags)
        for present, width in sides
        if present and width is not None
    ]
    return min(widths) if widths else None
