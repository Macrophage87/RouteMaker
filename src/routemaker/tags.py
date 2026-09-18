"""Parsing OpenStreetMap tag values into the quantities the classifier reads.

Every parser here returns `None` rather than a guess when a tag is missing or
unreadable. The defaulting happens once, in `stress`, where the rule is to err
toward the higher-stress reading; scattering defaults through the parsers would
hide which values were measured and which were assumed.
"""

from __future__ import annotations

import re

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
# They live here rather than in `stress` because `cycleway_values` has to rank
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
# (`cycleway:left=lane`), never values, and `cycleway_values` only ever yields
# the value half of a tag. Listing them here could only ever match a way tagged
# `cycleway=left`, which is not a thing a mapper writes.
SEPARATED_CYCLEWAY = frozenset({"track", "opposite_track"})
PAINTED_CYCLEWAY = frozenset({"lane", "opposite_lane", "buffered_lane"})

# The two key forms that speak for both sides of the road at once, and the two
# that speak for one side each. `cycleway=X` and `cycleway:both=X` are not a
# third and fourth side; each says that *each* side carries X.
CYCLEWAY_BOTH_SIDES_KEYS = ("cycleway", "cycleway:both")
CYCLEWAY_KEYS = (*CYCLEWAY_BOTH_SIDES_KEYS, "cycleway:left", "cycleway:right")


def _facility_rank(values: set[str]) -> int:
    """How much separation the best value in `values` gives. Higher is better."""
    if values & SEPARATED_CYCLEWAY:
        return 2
    if values & PAINTED_CYCLEWAY:
        return 1
    return 0


def _side_values(tags: dict[str, str], side: str) -> set[str]:
    """Every cycleway value that speaks for one side of the road."""
    keys = (*CYCLEWAY_BOTH_SIDES_KEYS, f"cycleway:{side}")
    return {tags[k] for k in keys if tags.get(k)}


def cycleway_values(tags: dict[str, str]) -> set[str]:
    """The cycleway values describing the provision a rider may be made to use.

    Not the union of the four key forms, which is what this was and which made
    provisioning the second side of a road a penalty. The union asked "is there
    a facility anywhere on this way" while `cycleway_width_m` right below asks
    "how wide is the worst side" - so `cycleway:left=lane` at 2.0 m beside
    `cycleway:right=no` scored LTS1 on a 25 mph secondary, the same street with
    `cycleway:both=lane` at 2.0 m and 1.2 m scored LTS2, and the same street
    bare scored LTS2. Building the lane on the second side raised the stress of
    the road. Worse, `cycleway:left=track` with `cycleway:right=no` on a 35 mph
    four-lane two-way secondary came out LTS1, three tiers below the bare road,
    because the `no` was discarded by the union while the `track` was kept.

    One rule, the same one `cycleway_width_m` and `shoulder_width_m` keep:
    **score the worst side a rider may be made to use.**

    On a two-way street each side is a direction. A rider heading one way is on
    the left-hand side and heading the other way is on the right, and one tier
    is stored per way, so the way's provision is the *weaker* of its two sides.
    A side with no facility - the key absent, or present and saying `no` - is no
    facility, and a one-sided lane on a two-way street is therefore mixed
    traffic for the direction that does not have it. That is the road as Furth
    scores it: a rider riding away from the lane is in the traffic lane.

    On a one-way street there is only one direction of travel, so a facility on
    either side is the facility of the only trip anyone makes on the way, and
    the union is the right reading. That is not a carve-out for symmetry's sake
    - it is most of the District's protected network, where `cycleway:left=
    opposite_lane` and `cycleway:left=track` on a one-way street are how a
    contraflow lane is tagged, and the one-sided reading is the correct one
    there because there is no second direction to strand.

    Returns the weaker side's values, so an absent or `no` side answers with
    what it says rather than with the other side's facility.
    """
    if is_oneway(tags):
        return {tags[k] for k in CYCLEWAY_KEYS if tags.get(k)}
    sides = (_side_values(tags, "left"), _side_values(tags, "right"))
    return min(sides, key=_facility_rank)


# One width key per cycleway key form, in the same order as `cycleway_values`
# reads them.
CYCLEWAY_WIDTH_KEYS = (
    "cycleway:width",
    "cycleway:both:width",
    "cycleway:left:width",
    "cycleway:right:width",
)


def cycleway_width_m(tags: dict[str, str]) -> float | None:
    """The narrowest surveyed painted-lane width, or None if none is tagged.

    `shoulder_width_m`'s rule, for the same reason and with the same shape. The
    four keys are not a fallback chain to be walked until one of them answers:
    `cycleway:left:width` and `cycleway:right:width` are the two sides of the
    road, a rider is on whichever side the route uses, and the tile build does
    not know which - one tier is stored per way. Taking the first key present
    made a road with `cycleway:left:width=2.0` and `cycleway:right:width=1.2`
    read as a 2.0 m lane, LTS1 and "adequate", while the same road carrying only
    the 1.2 m right-hand lane read LTS2 - so surveying the wider side *lowered*
    the stress of a road whose narrow side had not changed. The narrower of the
    two is the higher-stress reading and the one a rider can be made to use.

    `cycleway:width` and `cycleway:both:width` are not a third and fourth side.
    Each states the width of the lane on *each* side, so such a value enters the
    comparison as itself and no key outranks another: whichever surveyed width
    is smallest is the answer, whatever key carries it.
    """
    widths = [w for key in CYCLEWAY_WIDTH_KEYS if (w := parse_width_m(tags.get(key))) is not None]
    return min(widths) if widths else None


# The shoulder keys, split the way the cycleway keys above are: two that speak
# for both sides of the road and two that speak for one side each.
SHOULDER_BOTH_SIDES_KEYS = ("shoulder", "shoulder:both")
SHOULDER_PRESENCE_KEYS = (*SHOULDER_BOTH_SIDES_KEYS, "shoulder:left", "shoulder:right")

# The width key for every side named above, spelled as OSM spells it. Nothing
# walks the two lists in step any more - `has_shoulder` reads every presence key
# before it answers and `shoulder_width_m` takes the smallest width on the way,
# whichever key carries it - so the order is arbitrary and what matters is that
# no side is missing its width key. A missing one is not cosmetic: while
# `shoulder:right:width` was absent from this list a way tagged
# `shoulder:right=yes` + `shoulder:right:width=2.4` read as a shoulder of
# unknown width, which is read as narrow, so a surveyed eight-foot shoulder
# earned nothing.
SHOULDER_BOTH_SIDES_WIDTH_KEYS = ("shoulder:width", "shoulder:both:width")
SHOULDER_WIDTH_KEYS = (
    *SHOULDER_BOTH_SIDES_WIDTH_KEYS,
    "shoulder:left:width",
    "shoulder:right:width",
)


SHOULDER_ABSENT = frozenset({"no", "none"})


def _shoulder_on_side(tags: dict[str, str], side: str) -> bool | None:
    """Whether one named side of the road has a shoulder, or None if untagged.

    Every rule `has_shoulder` describes, applied to the keys that speak for this
    side: the general keys (`shoulder`, `shoulder:both`) say something about
    every side, the side key says something about this one, and a surveyed width
    on any of them is presence on its own.
    """
    presence = [
        value
        for key in (*SHOULDER_BOTH_SIDES_KEYS, f"shoulder:{side}")
        if (value := tags.get(key)) is not None
    ]
    if any(value not in SHOULDER_ABSENT for value in presence):
        return True
    widths = (*SHOULDER_BOTH_SIDES_WIDTH_KEYS, f"shoulder:{side}:width")
    if any(parse_width_m(tags.get(key)) is not None for key in widths):
        return True
    return False if presence else None


def has_shoulder(tags: dict[str, str]) -> bool | None:
    """Whether a rider going either way along the road has a shoulder to sit in.

    Each side is read on its own and the sides are then combined by
    `cycleway_values`' rule, which is this module's one rule for a provision
    that can be tagged per side: **score the worst side a rider may be made to
    use.** On a two-way street the two sides are the two directions of travel,
    one tier is stored per way, and a shoulder on the right only is nothing at
    all to a rider heading the other way - so both sides have to have one. On a
    one-way street there is one direction and one side in use, so either side
    answers for the way. Measured, before this: a two-way 30 mph secondary with
    a 2.4 m shoulder on one side scored LTS2 while the same road with 2.4 m on
    one side and 1.3 m on the other scored LTS3, because presence was "any side"
    while `shoulder_width_m` was "the worst side" - surfacing the second
    shoulder raised the road's stress.

    Returns None only when nothing in the tags speaks to shoulders at all, since
    absence of a `shoulder:*` tag is not evidence that shoulders are absent. A
    way that says something about one side and nothing about the other has
    spoken, and the answer for the way is False.

    Within a side the keys are not alternatives, they are a general tag and a
    refinement of it: a way carrying `shoulder=no` *and* `shoulder:right=yes`
    has a shoulder on the right, because the more specific tag is the later one
    and the more general one is what a mapper writes first. Every presence key
    for the side is read before any answer is returned.

    A surveyed width counts as presence on its own. `shoulder:width=2.4` with no
    presence key is a mapper who measured the shoulder and did not separately
    assert that it exists; reading that as "no shoulder tagged" threw away the
    only measurement on the way, and it is the measurement, not the presence
    key, that the bike-lane table needs.

    That includes the contradictory pair, and deliberately: `shoulder=no`
    together with a `shoulder:width` reads as **present**. The two tags
    disagree, and the width is the survey - somebody went and measured a
    shoulder, which is not a thing to do to a road that has none, while
    `shoulder=no` is the value a mapper leaves behind after refining the way
    with a more specific tag (the same order of events the side keys above
    describe). Believing the width also keeps this function's answer consistent
    with `shoulder_width_m`, which reads the width whatever the presence keys
    say: the alternative is a way that has no shoulder and a shoulder width,
    which the classifier cannot score. It errs toward the lower-stress reading
    on a contradiction, which is the one place in this module that happens, and
    it is bounded - the width still has to clear `RIDEABLE_SHOULDER_M` before
    `stress` credits anything for it.
    """
    left = _shoulder_on_side(tags, "left")
    right = _shoulder_on_side(tags, "right")
    if is_oneway(tags):
        if left or right:
            return True
        return False if (left is not None or right is not None) else None
    if left and right:
        return True
    if left is None and right is None:
        return None
    return False


def shoulder_width_m(tags: dict[str, str]) -> float | None:
    """The narrowest surveyed shoulder width, or None if none is tagged.

    The narrowest rather than the first: a way carrying both
    `shoulder:left:width` and `shoulder:right:width` has a rider on whichever
    side the route uses, and the tile build does not know which.
    """
    widths = [w for key in SHOULDER_WIDTH_KEYS if (w := parse_width_m(tags.get(key))) is not None]
    return min(widths) if widths else None
