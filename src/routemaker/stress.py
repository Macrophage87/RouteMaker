"""Level of Traffic Stress classification.

An implementation of the Furth 2017 LTS criteria, written from the published
tables rather than copied from an existing classifier, so that nothing here
carries another project's licence.

Tiers run 1 to 4 on the Furth scale, where 1 is tolerable to most adults and
children and 4 is tolerable only to the "strong and fearless". One scale,
computed the same way everywhere from the same tables: an agency's finished
score is never imported in place of this, because Maryland's runs 0 to 5 and
"top-tier stress" would then mean different things on either side of the
District line, while the Beginner invariant and the road-exposure report both
key on it.

The ordering is speed, then facility, then volume, then surface. Volume is a
modifier on two-lane roads rather than a primary variable: what makes a road
hostile to a bicycle is the speed differential of the traffic passing it, so a
quiet two-lane road posted at 50 is high stress at almost any volume while a
congested downtown grid posted at 25 is not.

Three consequences of that ordering are easy to get backwards, so they are
stated here as well as at the code that implements them.

A painted bike lane and a rideable paved shoulder are the same provision and are
scored on the same table, which is what keeps a shoulder from ever rating a road
safer than a bike lane read the same way. The one thing that separates them is
the door zone, and it separates them only where nobody has said whether the road
has parking: a road with no parking tags cannot have a parking lane beside its
shoulder, so the shoulder is measured against Furth's no-parking width while a
bike lane on the same road is measured, conservatively, against the wider one.
That is a difference in what is known about the road, not a difference in the
credit the provision earns - and it lasts exactly as long as the ignorance does.
A road that *declares* a parking lane has said that its outermost strip is
occupied, so the shoulder there is measured against the beside-parking width
like any other provision on it.

One provision earns one credit. Volume is a modifier on roads with *no*
provision, so a road that has taken the bike-lane table's credit does not also
take the volume credit - and "has a provision" has to mean the same thing at the
facility step and at the volume gate, or the hierarchy inverts through the gap
between them. It did: the gate asked only about cycleway tags, so a rideable
shoulder took both credits and a painted lane took one, and a shouldered road
came out a tier *better* than the same road with a bike lane below `VOLUME_QUIET`
and a tier *worse* above `VOLUME_BUSY` - the second putting a well-shouldered
arterial into `is_top_tier`. The gate is therefore asked about the provision,
not about the tag that happens to record it.

That is the order this module keeps rather than running volume before the
facility step, which is the other way to close the same gap: the facility step
*sets* a tier from a table while the volume step *moves* one by a tier, so
running the modifier first means the facility table immediately overwrites it,
and recovering the volume reading afterwards means keeping a second candidate
tier around and combining the two by hand. Excluding provisioned roads from the
gate says the same thing in one line, at the gate, where a reader asking "why did
this road not get the low-volume relief" is already looking.

And surface is last and nearly inert: it never sets a tier and a maintained
gravel road moves nothing, because gravel here is a low-traffic choice rather
than a hazard - it only floors LTS1, the tier that claims a child could ride it,
against a surface that would shed one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

from .classes import MOTOR_ONLY_HIGHWAY, TRAIL_CLASS_HIGHWAY
from .tags import (
    cycleway_values,
    cycleway_width_m,
    has_parking_lane,
    has_shoulder,
    lanes_per_direction,
    maxspeed_is_unitless,
    parse_maxspeed_mph,
    shoulder_width_m,
)


class Stress(IntEnum):
    """Furth Level of Traffic Stress. Higher is worse."""

    LTS1 = 1
    LTS2 = 2
    LTS3 = 3
    LTS4 = 4


# Re-exported from the shared module so there is one definition, not two.
TRAIL_CLASS = TRAIL_CLASS_HIGHWAY
MOTOR_ONLY = MOTOR_ONLY_HIGHWAY

# Defaults applied when a tag is absent, each erring toward the higher-stress
# reading. Recorded on the result so a tier derived from assumptions is
# distinguishable from one derived from tags.
# Split by context, not by highway class alone. The same `unclassified` tag
# covers a 25 mph District side street and a 50 mph Loudoun through road with no
# shoulder, and assuming the urban figure everywhere put Snickersville Turnpike
# and Mountain Road at LTS1.
DEFAULT_MAXSPEED_MPH_URBAN = {
    "residential": 25.0,
    "living_street": 15.0,
    "track": 15.0,
    "unclassified": 30.0,
    "tertiary": 30.0,
    "tertiary_link": 30.0,
    "secondary": 35.0,
    "secondary_link": 35.0,
    "primary": 40.0,
    "primary_link": 40.0,
    # US-1, US-50 and New York Avenue NE are `trunk` here and are routinely
    # bicycle-legal, so they go through the ordinary path rather than being
    # short-circuited to top tier - but they are the fastest surface roads in
    # the region, so an untagged one may not be read as a 30 mph street. The
    # figure is the conservative one for an urban trunk, above `primary`.
    "trunk": 45.0,
    "trunk_link": 45.0,
    "service": 20.0,
}

# Statutory rural defaults where nothing is posted. Virginia 55, Maryland 50;
# the higher of the two is taken where the jurisdiction is unknown, because the
# rule is to err toward the higher-stress reading.
DEFAULT_MAXSPEED_MPH_RURAL = {
    "residential": 25.0,
    "living_street": 15.0,
    # A farm track is not a 50 mph road. Falling through to the rural default
    # rated Loudoun gravel at maximum stress, which is the opposite of the
    # position the rural references establish.
    "track": 15.0,
    "unclassified": 50.0,
    "tertiary": 50.0,
    "tertiary_link": 50.0,
    "secondary": 55.0,
    "secondary_link": 55.0,
    "primary": 55.0,
    "primary_link": 55.0,
    "trunk": 55.0,
    "trunk_link": 55.0,
    "service": 20.0,
}
DEFAULT_MAXSPEED_MPH = DEFAULT_MAXSPEED_MPH_URBAN

# What an unposted way whose `highway` value is in neither table is read at.
# `highway=road` is OSM for "a road, class unknown", and there is no way to be
# conservative about an unknown class except by number: outside an urban area
# that is the statutory rural default, so a way nobody has classified is read at
# the speed of the roads around it rather than at a residential 25. Named rather
# than left as a literal in the `dict.get` call so that the two figures can be
# pinned and cannot be transposed.
DEFAULT_MAXSPEED_MPH_UNKNOWN_URBAN = 30.0
DEFAULT_MAXSPEED_MPH_UNKNOWN_RURAL = 50.0

DEFAULT_LANES_PER_DIRECTION = 1

# The `cycleway` values that describe a facility *on this way*, split by how much
# separation the facility gives, because the two sets score on different tables.
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
# `tags.has_parking_lane` reads the same OSM idiom the same way: `parking:*
# =separate` is in its `absent` set, because there too the value means "recorded
# elsewhere", not "present here".
#
# `left` and `right` are absent for a related reason: they are key suffixes
# (`cycleway:left=lane`), never values, and `cycleway_values` only ever yields
# the value half of a tag. Listing them here could only ever match a way tagged
# `cycleway=left`, which is not a thing a mapper writes.
SEPARATED_CYCLEWAY = frozenset({"track", "opposite_track"})
PAINTED_CYCLEWAY = frozenset({"lane", "opposite_lane", "buffered_lane"})

# A shoulder narrower than this is not somewhere a rider can sit.
RIDEABLE_SHOULDER_M = 1.2

# Furth's two bike-lane width criteria, in metres, and the only thing separating
# a door-zone stripe from a lane a rider can use. Furth, "Level of Traffic Stress
# Criteria for Road Segments, version 2.0" (2017), the bike-lane table: a lane
# running alongside a parking lane is measured as the bike lane *plus* the
# parking lane, 13.5 ft; a lane with nothing parked beside it is measured on its
# own, 5.5 ft. Named rather than written inline at the comparison because a
# reviewer replaced them with 2.1 and 0.7 - half and a third of the published
# figures - and the whole suite stayed green.
FURTH_LANE_BESIDE_PARKING_M = 4.1
FURTH_LANE_ALONE_M = 1.7

# An unsurveyed unpaved rural lane. Deliberately below the 35 mph boundary at
# which mixed traffic becomes LTS4, rather than exactly on it: Virginia's
# statutory default for a highway that is not surface treated is 35, and reading
# it as exactly 35 put every gravel road in Loudoun at maximum stress. The roads
# the rural references actually ride - Hibbs Bridge, Featherbed, Mountain Road -
# are tagged `unclassified` or `tertiary` with `surface=gravel`, not as farm
# tracks, so the `track` carve-out did not reach them. This club chooses gravel
# because it carries less traffic, and an overlay that paints those roads as
# arterials inverts the meaning of the map on a rural route.
UNPAVED_RURAL_DEFAULT_MPH = 30.0

# Volume thresholds in vehicles per day, as a modifier on two-lane roads only.
# Normalized to one definition before the classifier reads them: VDOT publishes
# bidirectional counts, the District publishes AADT, and Maryland's is embedded
# in a finished score.
VOLUME_QUIET = 1_500
VOLUME_BUSY = 8_000

# Surfaces a road bike will not hold a line on. Surface never sets the tier on
# its own: gravel here is usually a low-traffic choice rather than a hazard, and
# treating it as stress would reject half a rural club's calendar.
ROUGH_SURFACES = frozenset({"dirt", "earth", "grass", "mud", "sand", "ground", "woodchips"})
ROUGH_TRACKTYPES = frozenset({"grade4", "grade5"})
ROUGH_SMOOTHNESS = frozenset({"very_bad", "horrible", "very_horrible", "impassable"})


@dataclass(frozen=True)
class StressResult:
    """A tier plus the provenance of the inputs that produced it.

    Provenance is not decoration: a reviewer comparing a tier against crash
    history needs to know whether the speed was posted or assumed, and the
    published derivative needs to know which segments were influenced by a
    conditionally licensed source.
    """

    tier: Stress
    rule: str
    assumed: tuple[str, ...] = field(default_factory=tuple)
    volume_source: str | None = None

    @property
    def is_top_tier(self) -> bool:
        """What the Beginner invariant and the road-exposure report key on."""
        return self.tier is Stress.LTS4


def _mixed_traffic_tier(speed_mph: float, lanes: int) -> tuple[Stress, str]:
    """Furth mixed-traffic criteria: speed first, then lane count."""
    if speed_mph >= 35:
        return Stress.LTS4, "mixed traffic, 35 mph or above"
    if speed_mph >= 30:
        return (
            (Stress.LTS3, "mixed traffic, 30 mph, single lane")
            if lanes <= 1
            else (
                Stress.LTS4,
                "mixed traffic, 30 mph, multilane",
            )
        )
    if speed_mph > 20:
        return (
            (Stress.LTS2, "mixed traffic, 25 mph, single lane")
            if lanes <= 1
            else (
                Stress.LTS3,
                "mixed traffic, 25 mph, multilane",
            )
        )
    return (
        (Stress.LTS1, "mixed traffic, 20 mph or below, single lane")
        if lanes <= 1
        else (
            Stress.LTS2,
            "mixed traffic, 20 mph or below, multilane",
        )
    )


def _bike_lane_tier(
    speed_mph: float,
    lanes: int,
    width_m: float | None,
    parking: bool | None,
    facility: str = "bike lane",
) -> tuple[Stress, str]:
    """Furth bike-lane criteria. A narrow lane beside parking is a door zone.

    `facility` names the provision in the rule text. It exists because this one
    table serves both a painted bike lane and a paved shoulder: Furth scores the
    two identically, and giving a shoulder its own ladder is what inverted the
    provision hierarchy (see `classify`).

    `parking` is whether a parking lane runs alongside *this provision*, which is
    the question Furth's two width criteria turn on and not quite the question
    "does this road have parking on it". The shoulder call passes False only
    where the road's parking is unknown or declared absent (see `classify`); the
    bike-lane call passes what the tags say, with unknown read as present.
    """
    # Treat unknown parking as present and unknown width as narrow: both are the
    # higher-stress reading, and both are common in this region's tagging.
    beside_parking = parking is not False
    threshold = FURTH_LANE_BESIDE_PARKING_M if beside_parking else FURTH_LANE_ALONE_M
    narrow = width_m is None or width_m < threshold

    if speed_mph >= 40:
        return Stress.LTS4, f"{facility}, 40 mph or above"
    if speed_mph >= 35:
        return Stress.LTS3, f"{facility}, 35 mph"
    if speed_mph >= 30 or lanes > 1:
        return (
            (Stress.LTS3, f"{facility}, narrow or multilane at 30 mph")
            if narrow
            else (
                Stress.LTS2,
                f"{facility}, adequate width at 30 mph",
            )
        )
    if narrow:
        return Stress.LTS2, f"{facility}, narrow at 25 mph or below"
    return Stress.LTS1, f"{facility}, adequate width at 25 mph or below"


def classify(
    tags: dict[str, str],
    aadt: int | None = None,
    aadt_source: str | None = None,
    urban: bool = True,
) -> StressResult:
    """Classify one way. `aadt` is bidirectional vehicles per day, already normalized.

    `urban` selects which speed defaults apply where nothing is posted. It comes
    from the coverage polygon's urban-area layer at preprocessing time; the
    default is the conservative one for the District, where most of the
    deployment's traffic is.
    """
    highway = tags.get("highway", "")
    assumed: list[str] = []

    if highway in TRAIL_CLASS:
        return StressResult(Stress.LTS1, f"trail-class way ({highway})")

    if highway in MOTOR_ONLY:
        return StressResult(Stress.LTS4, f"motor-only classification ({highway})")

    speed_mph = parse_maxspeed_mph(tags.get("maxspeed"))
    if speed_mph is not None and maxspeed_is_unitless(tags.get("maxspeed")):
        # The number was surveyed; the unit was not. Read as mph, which is the
        # higher-stress reading and the only one that exists on a US sign.
        assumed.append("maxspeed unit")
    if speed_mph is None:
        table = DEFAULT_MAXSPEED_MPH_URBAN if urban else DEFAULT_MAXSPEED_MPH_RURAL
        unknown = (
            DEFAULT_MAXSPEED_MPH_UNKNOWN_URBAN if urban else DEFAULT_MAXSPEED_MPH_UNKNOWN_RURAL
        )
        speed_mph = table.get(highway, unknown)
        if not urban and is_unpaved(tags):
            # Virginia's statutory default on a highway that is not surface
            # treated is 35, not 55, and an unpaved lane is not a through road
            # whatever its classification says.
            speed_mph = min(speed_mph, UNPAVED_RURAL_DEFAULT_MPH)
        assumed.append("maxspeed")

    lanes = lanes_per_direction(tags)
    if lanes is None:
        lanes = DEFAULT_LANES_PER_DIRECTION
        assumed.append("lanes")

    cycleways = cycleway_values(tags)
    parking = has_parking_lane(tags)
    if parking is None:
        assumed.append("parking")

    # Resolved here rather than inside the facility branch below, because the
    # volume gate has to ask the same question and get the same answer. A
    # shoulder earns the bike-lane table's credit only when it is wide enough to
    # sit in and someone has surveyed the width; a shoulder of unknown or
    # unrideable width earns nothing, so it is not a provision for the volume
    # gate either, and such a road is scored exactly like a road with no
    # shoulder at all.
    shoulder_present = bool(has_shoulder(tags))
    shoulder_width = shoulder_width_m(tags) if shoulder_present else None
    rideable_shoulder = shoulder_width is not None and shoulder_width >= RIDEABLE_SHOULDER_M

    # A tag asserting the *absence* of a facility is not a facility. Testing the
    # raw value set let `cycleway=no`, which is common here, skip the volume
    # modifier the rural position depends on.
    has_cycleway = bool(cycleways & (SEPARATED_CYCLEWAY | PAINTED_CYCLEWAY))
    # Set by the shoulder branch below when the bike-lane table is what produced
    # the tier. See `has_facility`, after the facility step.
    shoulder_credited = False

    # Facility, in descending order of separation.
    if cycleways & SEPARATED_CYCLEWAY:
        tier, rule = Stress.LTS1, "separated track alongside"
    elif cycleways & PAINTED_CYCLEWAY:
        # Only the cycleway's own width. Reading the roadway `width` tag made a
        # four-lane arterial *lower* stress the moment someone surveyed its
        # carriageway, which is backwards.
        #
        # And the narrowest of the cycleway's own width keys, not the first one
        # present - `shoulder_width_m`'s rule, for the reason written at
        # `cycleway_width_m`: the left and right keys are two sides of one road
        # and the tile build does not know which side the route uses.
        width = cycleway_width_m(tags)
        if width is None:
            assumed.append("cycleway width")
        tier, rule = _bike_lane_tier(speed_mph, lanes, width, parking)
    else:
        tier, rule = _mixed_traffic_tier(speed_mph, lanes)
        # A rideable paved shoulder is scored on the *bike-lane* table, not by
        # subtracting a tier from mixed traffic.
        #
        # Furth treats a paved shoulder and a bike lane as the same provision -
        # one table covers "bike lane or paved shoulder" - and the earlier
        # one-tier credit ran down a ladder of its own with no ceiling, so it
        # reached across the bike-lane table and inverted the provision
        # hierarchy: an eight-foot shoulder on a 55 mph eight-lane arterial came
        # out LTS3 while a painted lane on the same road came out LTS4. A
        # shoulder is the weaker provision of the two, and `is_top_tier` is what
        # Beginner's zero-top-tier-distance invariant and the road-exposure
        # report key on, so the inversion routed Beginner onto Leesburg Pike and
        # River Road and reported nothing.
        #
        # Scoring it on the one table is what makes the hierarchy hold by
        # construction rather than by a floor bolted on beside it: the shoulder
        # tier can never come out below the tier the same road would get with a
        # painted lane of the same width read the same way, at any speed or lane
        # count. "Read the same way" is not a hedge - it is the door zone, and it
        # is the one thing that separates the two provisions; see the comment on
        # the `parking=False` argument below.
        #
        # Two conditions survive from the old credit. The width has to be one a
        # rider can actually sit in, since a six-inch shoulder is not a refuge
        # and an untagged width is read as narrow. And the result may not be
        # *worse* than the same road with no shoulder at all, which is what the
        # comparison below is for: a shoulder narrower than Furth's criterion
        # scores LTS2 on the table while a 20 mph street with nothing at all
        # scores LTS1, and a strip of asphalt at the edge of a quiet street does
        # not make it more hostile than no strip of asphalt would.
        if shoulder_present:
            if shoulder_width is None:
                assumed.append("shoulder width")
            elif rideable_shoulder:
                # `False` where the road's parking is unknown or declared
                # absent, and the road's own value where parking is declared
                # *present*. The two halves of that are separate arguments and
                # only the first one survives a road that says it has parking.
                #
                # Where nothing is tagged, or parking is tagged absent: a
                # parking lane cannot run beside a shoulder. A shoulder is the
                # outermost strip of the carriageway, so a car parked on it is
                # parked *on* the shoulder rather than beside it, and Furth's
                # door-zone criterion - the one that measures the bike lane plus
                # the parking lane it runs next to - has nothing to measure.
                # Reading an untagged road as "parking present" here made the
                # credit inert below 35 mph on almost every road it was written
                # for: parking is untagged on essentially every rural road, and
                # an eight-foot shoulder then had to clear 4.1 m to count as
                # anything but narrow. Snickersville Turnpike with a surveyed
                # 8 ft shoulder scored the same as Snickersville Turnpike with
                # none. That argument is about what is *unknown* about the road,
                # and it is pinned by name in
                # `test_a_shoulder_is_measured_against_furths_no_parking_width`.
                #
                # Where the road declares a parking lane, the argument runs out.
                # A road tagged `parking:both=parallel` *and* `shoulder:width`
                # has told us cars stand on that strip: the outermost strip is
                # the parking lane, so what the width tag measures is the
                # parking lane, the door zone beside it, or the two together -
                # which is exactly the quantity Furth's beside-parking criterion
                # is written against, the bike lane plus the parking lane at
                # 13.5 ft. So the road's own value is passed and the wider
                # criterion applies. Furth is followed rather than the credit
                # simply denied because his table already has the right reading
                # for this case: a strip wide enough to hold a parked car *and*
                # a rider still earns the table, and a 2.4 m strip does not.
                #
                # Measured, before this: a residential 25 mph street with
                # `parking:both=parallel` and `shoulder:width=2.4` came out LTS1,
                # a tier below the same street with `cycleway=lane` at the same
                # width, and the Lua remap then wrote `cycleway=track` onto a
                # street that declares a parking lane.
                shoulder_parking = parking if parking is True else False
                shoulder_tier, shoulder_rule = _bike_lane_tier(
                    speed_mph,
                    lanes,
                    shoulder_width,
                    shoulder_parking,
                    facility="paved shoulder",
                )
                if shoulder_tier < tier:
                    tier, rule = shoulder_tier, shoulder_rule
                    shoulder_credited = True

    # What "this road has a provision" means, in one place, for both the step
    # above and the gate below - one provision earns one credit. A painted lane
    # always takes the bike-lane table, so a cycleway tag always counts. A
    # shoulder takes that table only when it beats plain mixed traffic, and a
    # shoulder that does not - too narrow to clear Furth's width criterion, or
    # on a street already quieter than any bike lane would make it - has earned
    # nothing, so the road is scored exactly as one with no provision at all,
    # volume gate included.
    #
    # Keeping the exemption without taking the table is the inversion arriving
    # by its subtler route: a 20 mph street at AADT 12,000 took the mixed-traffic
    # LTS1, declined the table's LTS2, and then skipped the high-volume bump that
    # the same street with no shoulder and the same street with a bike lane both
    # took, so a narrow shoulder rated a busy street a tier below either.
    has_facility = has_cycleway or shoulder_credited

    # Volume, as a modifier on two-lane roads with no provision of their own,
    # and never upward past the tier speed already set. `has_facility` is the
    # one definition of "has a provision", shared with the facility step above
    # so that one provision earns exactly one credit; see the module docstring
    # for what happened while the two steps disagreed about a paved shoulder.
    volume_source = aadt_source if aadt is not None else None
    if aadt is not None and lanes <= 1 and not has_facility:
        # A guessed speed may not be improved by a guess, but a measured count is
        # evidence: the conservative rule is about missing evidence, not about
        # refusing what is there. So a real AADT relieves an assumed speed, while
        # an absent one leaves the assumption standing.
        #
        # That is what the code now does. It previously gated the relief on
        # `speed_mph <= 35` alone, reading whichever speed was in hand - and on a
        # rural road with nothing posted that is the assumed 50, which can never
        # be <= 35. So on exactly the roads the sentence was written for, a real
        # VDOT count could only ever hurt: Snickersville Turnpike at AADT 900
        # stayed LTS4, while the same road with a posted 35 came down to LTS3.
        # Evidence that only moves one way is not evidence.
        #
        # The two gates are therefore different questions. A *posted* speed at or
        # below 35 is a measured fact about the road, and the relief applies on
        # top of it. An *assumed* speed is the class default standing in for the
        # missing tag, and a count is better evidence about this particular road
        # than the default is, so the relief applies there too. A posted speed
        # above 35 is the one case where it does not: speed outranks volume, and
        # a quiet two-lane road posted at 50 is hostile at almost any count.
        speed_was_measured = "maxspeed" not in assumed
        relief_applies = speed_mph <= 35 or not speed_was_measured
        if aadt <= VOLUME_QUIET and tier > Stress.LTS1 and relief_applies:
            tier, rule = Stress(tier - 1), rule + ", low volume"
        # The bump has no speed gate, deliberately and not by oversight. It moves
        # in the conservative direction, so an assumed speed cannot be laundered
        # by it, and Furth's mixed-traffic table carries a volume threshold in
        # every speed band rather than only in the low ones.
        elif aadt >= VOLUME_BUSY and tier < Stress.LTS4:
            tier, rule = Stress(tier + 1), rule + ", high volume"

    # A surface that sheds riders is not tolerable to a child, which is what
    # LTS1 asserts, so it floors at LTS2. This is narrower than treating surface
    # as stress, which the module deliberately does not do: maintained gravel
    # still moves nothing, because it is a low-traffic choice rather than a
    # hazard. What it closes is a grade5 dirt farm track classifying LTS1
    # through the `track: 15.0` speed default - the exact reading `classes.py`
    # keeps `track` out of TRAIL_CLASS to prevent, arrived at by another route,
    # with `is_rough` computed beside it and touching nothing.
    #
    # Trail-class ways return above and are not floored: there the tier is a
    # statement about separation from traffic, a dirt singletrack is what a
    # Trailmaxxing rider came for, and the surface floor that belongs on it is
    # Group Ride's ridability dial at layer 4.
    if tier is Stress.LTS1 and is_rough(tags):
        tier, rule = Stress.LTS2, rule + ", rough surface"

    return StressResult(tier, rule, tuple(assumed), volume_source)


def is_rough(tags: dict[str, str]) -> bool:
    """Whether the surface would shed riders, as distinct from being unpaved.

    `surface` alone cannot tell a maintained gravel road that twenty people can
    ride two abreast from a rutted farm track, which is why `tracktype` and
    `smoothness` are read alongside it and why Group Ride keeps a quality floor
    even when surface avoidance is relaxed.
    """
    return (
        tags.get("surface") in ROUGH_SURFACES
        or tags.get("tracktype") in ROUGH_TRACKTYPES
        or tags.get("smoothness") in ROUGH_SMOOTHNESS
    )


def is_unpaved(tags: dict[str, str]) -> bool | None:
    """Unpaved but not necessarily rough: the rural gravel case.

    Returns None when `surface` is absent rather than False. Untagged rural
    gravel is common in Loudoun, and reading absence as paved understates the
    unpaved share that the Gravel and rural Group Ride ranking keys on; the
    caller decides what to do with an unknown.
    """
    surface = tags.get("surface")
    if surface is None:
        return None
    return surface not in {"asphalt", "concrete", "paved", "paving_stones", "chipseal"}
