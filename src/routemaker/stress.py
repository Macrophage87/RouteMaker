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
*worse* than a bike lane read the same way, at any speed or lane count. It does
not keep a shoulder from rating one better, and two things separate them.

The first is the door zone, and it separates them only where nobody has said
whether the road has parking: a road with no parking tags cannot have a parking
lane beside its shoulder, so the shoulder is measured against Furth's no-parking
width while a bike lane on the same road is measured, conservatively, against
the wider one. That is a difference in what is known about the road, not a
difference in the credit the provision earns - and it lasts exactly as long as
the ignorance does. A road that *declares* a parking lane has said that its
outermost strip is occupied, so the shoulder there is measured against the
beside-parking width like any other provision on it.

The second is a floor, and it is this module's own rule rather than Furth's: a
shoulder is never scored worse than the same road with no provision at all,
while a bike lane is scored on Furth's table without that floor. So on a calm
street the two can genuinely part - a 20 mph two-lane residential street with
`parking:both=no` is LTS1 bare, LTS1 with a 1.3 m shoulder and LTS2 with 1.3 m
of paint, because Furth's table rates a lane narrower than his criterion LTS2 at
any speed while mixed traffic at 20 mph is LTS1. The floor is deliberate and the
asymmetry with it: a strip of asphalt at the edge of a quiet street cannot make
it more hostile than no strip would, and painted lanes are not given the same
relief because a narrow lane really does put a rider in a worse place than an
unmarked calm street does - it invites traffic past at the width the paint
claims. `test_a_bike_lane_is_scored_on_furths_table_without_the_shoulders_floor`
pins the case; the divergence is one tier, never reaches `is_top_tier`, and is
recorded as an owner decision in the review log rather than closed by putting
the floor on both branches.

Both provisions are read on the worst side a rider may be made to use. A
painted lane and a paved shoulder can each be tagged per side, and on a two-way
street the two sides are the two directions of travel while one tier is stored
per way - so a facility on one side only is mixed traffic for a rider heading
the other way, and where both sides carry one it is the narrower that counts. On
a one-way street there is one direction and one side in use, so either side
answers for the way, which is what keeps the District's contraflow lanes
(`cycleway:left=opposite_lane` on a one-way street) reading as the facility they
are. Presence and width had disagreed about this - presence was "any side" and
width was "the worst side" - and the disagreement made building the second half
of a facility a penalty: a 25 mph secondary with a 2.0 m lane on the left and
`cycleway:right=no` was LTS1, the same street with 2.0 m and 1.2 m lanes on both
sides was LTS2, and the same street bare was LTS2.

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

from dataclasses import dataclass, field, replace
from enum import IntEnum

from .classes import MOTOR_ONLY_HIGHWAY, TRAIL_CLASS_HIGHWAY, trail_kind
from .tags import (
    PAINTED_CYCLEWAY,
    SEPARATED_CYCLEWAY,
    cycleway_values,
    cycleway_width_m,
    has_parking_lane,
    has_shoulder,
    is_oneway,
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
    # Not a Furth tier: a road a bicycle may legally ride that this map would
    # rather nobody were sent onto - the owner's "Maybe make a 5th category for
    # legal but to be avoided" (2026-09-27). Assigned by `legal_but_avoid` and
    # by curated overrides, never by the Furth tables.
    AVOID = 5


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

# The District's statutory default (OWNER-DECISIONS 108: "the default speed
# limit in DC on all streets and highways is 20 mph, or 15 mph in alleys";
# DDOT, "Speeding laws, fines and safety tips",
# https://ddot.dc.gov/page/speeding-laws-fines-and-safety-tips). Inside the
# District a way with no posted limit is read at these, whatever its class.
# Maryland's and Virginia's follow.
DC_DEFAULT_MPH = 20.0
DC_ALLEY_MPH = 15.0

# Maryland's and Virginia's, in their urban areas (OWNER-DECISIONS 112: "Use MD
# and VA defaults there"): 25 mph on residential streets, 30 on minor through
# roads, 35 on major roads - MDOT's own imputation for local roads and
# collectors (MDOT LTS methodology), as the literature review proposed. Other
# classes, and every class outside the urban areas, keep the tables above: the
# rural figures are the states' statutory ones, which the rural references
# depend on, and the owner's answer was about the urban roads in question.
MD_VA_URBAN_DEFAULT_MPH = {
    "residential": 25.0,
    "unclassified": 30.0,
    "tertiary": 30.0,
    "tertiary_link": 30.0,
    "secondary": 35.0,
    "secondary_link": 35.0,
    "primary": 35.0,
    "primary_link": 35.0,
}
# The keys a mapper records the legal basis of a limit in (OSM's
# `maxspeed:type`, and its older `source:maxspeed`), as `US-DC:urban` and the
# like: where one names the District it is read as the District's default, as
# the jurisdiction is.
SPEED_ZONE_KEYS = ("maxspeed:type", "source:maxspeed")


def speed_zone(tags: dict[str, str], jurisdiction: str | None) -> str | None:
    """Whose statutory default an unposted way takes: a zone tag naming a
    state, else the state the way lies in."""
    for key in SPEED_ZONE_KEYS:
        value = tags.get(key) or ""
        if value.upper().startswith("US-"):
            return value[3:5].upper()
    return jurisdiction


# `SEPARATED_CYCLEWAY` and `PAINTED_CYCLEWAY` are defined in `tags` and
# re-exported here, where the facility step reads them. They moved because
# `tags.cycleway_values` has to rank one side of a road against the other before
# this module sees either side, and ranking needs to know which values are
# facilities and how much separation each gives; the comment explaining what is
# in the sets and what is deliberately not - `separate` above all - is on them
# there.

# A shoulder narrower than this is not somewhere a rider can sit.
RIDEABLE_SHOULDER_M = 1.2

# Furth's two bike-lane width criteria, in metres, and the only thing separating
# a door-zone stripe from a lane a rider can use. A lane running alongside a
# parking lane is measured by its *reach*, the bike lane plus the parking lane
# (and any marked buffer), and is adequate at 15 ft [4.57 m] or more: Mekuria,
# Furth & Nixon, "Low-Stress Bicycling and Network Connectivity", MTI Report
# 11-19 (2012), Table 2, p.18 - reach 15 ft or more LTS 1, 14 or 14.5 ft LTS 2,
# 13.5 ft or less LTS 3 - and the same 15 ft line in Furth's LTS v2.0 (2017) and
# v2.2 (2022) tables (the literature notes, research_notes/"Bicycle traffic
# stress methods"/core_methods.md). Review r1 found this at 13.5 ft, the top of
# the narrow bin, which once an agency's parking width was added rated a 5 ft
# lane beside a 9 ft parking lane LTS 1 where Furth gives it LTS 2. Below 15 ft
# the table here gives LTS 2 up to 25 mph and LTS 3 at 30, which is the
# stricter of the published readings and is kept as such: it reads every reach
# under 15 ft as MTI 11-19's "13.5 ft or less" bin (LTS 3 at 30 mph), where the
# 14-14.5 ft bin there, v2.0's 12-14 ft row and v2.2's "< 15 ft" row all give
# LTS 2 at 30 mph (v2.2 up to 33.5 mph; review r2 corrected an earlier comment
# that credited this reading to v2.2). A lane
# with nothing parked beside it is measured on its own, 5.5 ft. Named rather
# than written inline at the comparison because a reviewer replaced them with
# 2.1 and 0.7 - half and a third of the published figures - and the whole
# suite stayed green.
FURTH_LANE_BESIDE_PARKING_M = 15 * 0.3048
FURTH_LANE_ALONE_M = 1.7
# How far under a width criterion a measured width may fall and still meet it:
# half a centimetre. A width in feet converted to metres and a sum of two such
# widths land a hair either side of a criterion that is itself a conversion
# (review SF2: a 5 ft lane beside a 10 ft parking lane is exactly Furth's 15 ft
# reach, and read at 1.52 m it fell 4 mm short and to the narrow row). OSM's
# widths are tagged to the centimetre at best.
WIDTH_TOLERANCE_M = 0.005

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
# The speed at and below which a count between the two is a tier (v2.2).
MID_VOLUME_MAX_MPH = 20.0
# The road classes OWNER-DECISIONS 141 floors at LTS 3 without a facility.
ARTERIAL_HIGHWAY = frozenset(
    {"trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link"}
)
# The road classes OWNER-DECISIONS 176 floors at LTS 2 without a facility.
COLLECTOR_HIGHWAY = frozenset({"tertiary", "tertiary_link"})

# Surfaces a road bike will not hold a line on. Surface never sets the tier on
# its own: gravel here is usually a low-traffic choice rather than a hazard, and
# treating it as stress would reject half a rural club's calendar.
ROUGH_SURFACES = frozenset({"dirt", "earth", "grass", "mud", "sand", "ground", "woodchips"})
ROUGH_TRACKTYPES = frozenset({"grade4", "grade5"})
ROUGH_SMOOTHNESS = frozenset({"very_bad", "horrible", "very_horrible", "impassable"})


# A curated stress adjustment (the owner, 2026-09-27: "we could have something
# clickable as a link to why we'd consider a particular stretch of road level 5,
# or also why a particular stretch of road might be adjusted, perhaps hidden.
# For instance we could deviate from the typical LTS because of road
# conditions, known aggressive drivers, problematic intersections, etc. Also we
# could down adjust a road if this is the better route among similar routes.").
# Why a stretch deviates from the tier its tags give it, in words a rider may
# read. The owner's own quoted reason is not part of it: that stays in the
# override row and its audit trail and is never shown.
ADJUSTMENT_CATEGORIES = (
    "speed",
    "road_conditions",
    "driver_behaviour",
    "intersection",
    "sightlines",
    "better_among_alternatives",
    "other",
)
ADJUSTMENT_VISIBILITIES = ("public", "hidden")
# Where a public note may be shown. The owner, 2026-09-27: "In many cases
# there's an acceptable trail. Only provide the warnings if the route goes over
# the road." `route_only`: in the summary of a route that uses the stretch, and
# nowhere else. `map`: also when a rider clicks the stretch on the map.
ADJUSTMENT_DISPLAYS = ("route_only", "map")
# Whether the owner has approved the category and note, as distinct from the
# tier: a note this repository proposed is carried and never shown.
ANNOTATION_STATUSES = ("proposed", "approved")
ADJUSTMENT_UP, ADJUSTMENT_DOWN, ADJUSTMENT_SAME = "up", "down", "same"


@dataclass(frozen=True)
class StressAdjustment:
    """One curated adjustment, as it applies to one way.

    `adjustment_id` is stable across rebuilds and shared by every way of one
    stretch, so a tile or a route answer can name the stretch and a card can
    explain it once. `computed_tier` is what the classifier gave the way before
    the adjustment, and `direction` follows from it: a curated tier below it is
    a down-adjustment, which is allowed ("down adjust a road if this is the
    better route among similar routes").
    """

    adjustment_id: str
    tier: Stress
    computed_tier: Stress
    category: str
    visibility: str
    annotation_status: str
    public_note: str | None = None
    display: str = "route_only"

    @property
    def direction(self) -> str:
        if self.tier > self.computed_tier:
            return ADJUSTMENT_UP
        if self.tier < self.computed_tier:
            return ADJUSTMENT_DOWN
        return ADJUSTMENT_SAME

    @property
    def is_shown(self) -> bool:
        """Public and approved: only then may a rider read why."""
        return self.visibility == "public" and self.annotation_status == "approved"

    def exposed(self) -> dict:
        """What may leave the rebuild: a hidden or unapproved adjustment is its
        id and the fact of an adjustment, and nothing else."""
        if not self.is_shown:
            return {"adjustment_id": self.adjustment_id, "adjusted": True}
        return {
            "adjustment_id": self.adjustment_id,
            "adjusted": True,
            "direction": self.direction,
            "computed_tier": int(self.computed_tier),
            "category": self.category,
            "public_note": self.public_note,
            "display": self.display,
        }


@dataclass(frozen=True)
class StressResult:
    """A tier plus the provenance of the inputs that produced it.

    Provenance is not decoration: a reviewer comparing a tier against crash
    history needs to know whether the speed was posted or assumed, and the
    published derivative needs to know which segments were influenced by a
    conditionally licensed source.

    `volume_source` is the **publishing agency** - `ddot`, `vdot`, `mdot-sha` -
    and never the precedence tier. It held the tier for a while, which is to say
    it held "state" for every count Virginia and Maryland published alike, and
    the claim in the paragraph above was false while it did: a derivative built
    on a conditionally licensed Maryland layer could not be told from one built
    on VDOT's. `conflation.AgencyFeature` carries both facts and they are not
    interchangeable; the tier stays in `conflation` where the ranking is.

    `volume_aadt` and `volume_year` are the count itself and its vintage, kept
    for the same reason and set whenever a count was in hand - whether or not
    the volume gate moved the tier, because the question the derivative asks is
    which segments a source *touched*, not which ones it changed. A count with
    no year is a count nobody can date, so the field is nullable and its
    emptiness is a fact about the source rather than a default.
    """

    tier: Stress
    rule: str
    assumed: tuple[str, ...] = field(default_factory=tuple)
    volume_source: str | None = None
    volume_aadt: int | None = None
    volume_year: int | None = None
    # The curated adjustment that set this tier, if one did.
    adjustment: StressAdjustment | None = None
    # Where each input the classifier read came from, as (attribute, source)
    # pairs, on a way an agency's street layer was matched to: `maxspeed`,
    # `lanes`, `oneway`, `bike`, `parking` and `aadt` each name the agency
    # (`dc-roadway-block`, `baltimore-centerline`) where its value took
    # precedence, `osm` where the way's own tag stood, `default` where neither
    # said and the classifier assumed. Empty on a way no agency layer reached.
    attr_sources: tuple[tuple[str, str], ...] = ()
    # What the classifier read the road at, kept for the intersection model
    # (`routemaker.intersections`; OWNER-DECISIONS 165-167): the speed and the
    # through lanes a direction as read (the way's tags, an agency's record
    # overlaid on them, a curated speed), and whether it is one-way. None where
    # the classifier assumed them (a class default is not a fact the junction
    # reasons may state), and where the way is a trail or a motor-only class.
    speed_mph: float | None = None
    lanes: int | None = None
    # `oneway` is the classifier's reading for item 109's one-way relief: a
    # carriageway of a divided road is not a one-way street there, as the other
    # direction's traffic is across the median. `graph_oneway` is the way's own
    # direction, as the routing graph has it (`tags.is_oneway` of the tags read,
    # a roundabout included), carriageway or not: what the segment table's
    # `road_oneway` says to the junction model, which would otherwise price a
    # divided road's carriageway as a two-way road (no median-refuge credit,
    # its lanes doubled, oncoming traffic on a left off it; correctness re-check
    # of 2b0cf00, blocker 1).
    oneway: bool | None = None
    graph_oneway: bool | None = None
    # The tier the classifier gave on the agency's own count, where the street's
    # median (`pipeline.aadt_smoothing`) lowered it; None everywhere else, and
    # dropped by anything that sets the tier afresh (an override row, a named
    # corridor, a closure to motor traffic). The link reads `tier`; the junction
    # model reads this, because the owner accepted lower-only smoothing on the
    # ground that a count bunched at an intersection is charged there
    # (OWNER-DECISIONS 303: "we don't want to double count"), so it must still
    # be charged there (ARTERIAL review r0, SF1).
    unsmoothed_tier: Stress | None = None

    @property
    def is_top_tier(self) -> bool:
        """LTS 4 and up: what the road-exposure report keys on."""
        return self.tier >= Stress.LTS4


# Lane count inside an urban area (OWNER-DECISIONS 87 and 101: "Multi-lane in a
# city isn't nearly that problematic", "We should change the rules, those are
# wrong"). Furth's mixed-traffic table makes a second through lane each way worth
# a full tier at every speed, which put a 30 mph two-lane one-way District street
# at LTS 4 on its lane count alone. Inside the urban-area layer
# (reference/urban-areas.json) the lane count is not scored: the street is read
# on the single-lane row, and its speed and its volume decide - the volume gate,
# which Furth applies to two-lane roads, applies there too, so a multi-lane city
# street carrying more than VOLUME_BUSY still comes out a tier higher. Outside
# urban areas the multilane rule stands.
URBAN_SCORED_LANES = 1

# One-way and two-way are not the same street (OWNER-DECISIONS 109: "we
# shouldn't have the same criteria for 2 way traffic vs 1 way. 1 Way is
# typically lower stress at similar characteristics"; and of Connecticut Avenue
# NW, "definitely 3, and possibly 4").
#
# - A two-way multi-lane city street is at least LTS 3, as Furth's v2.2 table
#   rates two lanes a direction at every speed up to 38.5 mph (Furth, "Level of
#   Traffic Stress Criteria for Road Segments", v2.2, 2022), and LTS 4 from 30
#   mph where the count is over URBAN_TWO_WAY_BUSY_AADT - v2.2's own threshold
#   for the step to LTS 4 from 28.5 mph. At 35 mph and more mixed traffic is
#   LTS 4 anyway.
# - A one-way city street with up to URBAN_ONEWAY_MAX_LANES is read on the
#   single-lane row, speed and volume deciding: no oncoming traffic, and San
#   Francisco's comfort index (SFMTA 2017) counts lanes against a one-way only
#   from three where it counts them against a two-way street from two. Furth's
#   v2.0 went the other way, reading a one-way's ADT at 1.5 times; v2.2
#   dropped that, and the owner's steer is followed here. A wider one-way takes
#   the two-way floor.
URBAN_ONEWAY_MAX_LANES = 2
URBAN_TWO_WAY_BUSY_AADT = 8_000


def urban_two_way_floor(
    tier: Stress, rule: str, speed_mph: float, aadt: int | None, kind: str = "two-way"
) -> tuple[Stress, str]:
    """A two-way (or three-lane one-way) multi-lane city street: LTS 3 at
    least, LTS 4 from 30 mph over URBAN_TWO_WAY_BUSY_AADT. `kind` names which
    in the rule text ("two-way", or "wide one-way")."""
    if (
        speed_mph >= 30
        and aadt is not None
        and aadt > URBAN_TWO_WAY_BUSY_AADT
        and tier < Stress.LTS4
    ):
        return Stress.LTS4, rule + f", {kind} busy"
    if tier < Stress.LTS3:
        return Stress.LTS3, rule + f", {kind} floor"
    return tier, rule


def _mixed_traffic_tier(
    speed_mph: float, lanes: int, urban_multilane: bool = False
) -> tuple[Stress, str]:
    """Furth mixed-traffic criteria: speed first, then lane count.

    `urban_multilane` names the row in the rule text: a multi-lane urban street
    is read on the single-lane row (`URBAN_SCORED_LANES`), and says so."""
    if urban_multilane:
        tier, rule = _mixed_traffic_tier(speed_mph, URBAN_SCORED_LANES)
        return tier, rule.replace("single lane", "urban multilane")
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

    What this function returns is Furth's reading and nothing else - in
    particular it is not floored against the mixed-traffic tier for the same
    road, so it can and does rate a narrow lane on a calm street a tier worse
    than no provision at all. That floor exists on the shoulder call only, and
    it is applied by the caller rather than here; see `classify`.

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
    narrow = width_m is None or width_m < threshold - WIDTH_TOLERANCE_M

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


# A decent painted lane (OWNER-DECISIONS 83, 84 and 101: MD 450 near Annapolis,
# 40 mph with a painted lane, "I'd probably say that's LTS3. Perhaps reduce it
# by 1 or so."). Furth's bike-lane table gives no credit at all at 40 mph and
# above, where mixed traffic is LTS 4; a decent lane there is one tier below it,
# LTS 3. Montgomery County's revised table (Montgomery Planning, Bicycle Master
# Plan Appendix D, 2017; OWNER-DECISIONS 105) reads a lane the same way at 40
# mph - level 3 on two or three lanes, and on four or five with a raised median
# - and gives none from 45 mph, so the credit stops at DECENT_LANE_MAX_MPH: at
# 45 mph and more a painted lane stays LTS 4, and an expressway posted 50 or
# more is "legal but avoid" whatever it carries (`legal_but_avoid`). Below 40
# mph Furth's table already reads a lane at least a tier below mixed traffic.
#
# "Decent" is read from the tags the lane carries, as far as they go: a buffered
# lane (`cycleway*=buffered_lane`, or a `cycleway*:buffer` other than no), or a
# lane whose surveyed width is at least DECENT_LANE_MIN_M (5 ft, the usual
# minimum for a lane beside a curb). A lane with no width tagged is decent: the
# owner's example, MD 450, is tagged `cycleway:right=lane` and nothing more,
# and he calls it wide. A lane tagged narrower than 5 ft is not.
DECENT_LANE_MAX_MPH = 40.0
# Where Furth's bike-lane table stops giving a lane any credit (`_bike_lane_tier`).
FURTH_LANE_NO_CREDIT_MPH = 40.0
DECENT_LANE_MIN_M = 1.5
# From this many through lanes a direction a decent lane earns nothing.
DECENT_LANE_MAX_LANES = 3
BUFFER_KEYS = (
    "cycleway:buffer",
    "cycleway:both:buffer",
    "cycleway:left:buffer",
    "cycleway:right:buffer",
)


def lane_is_buffered(tags: dict[str, str], cycleways: set[str]) -> bool:
    """A painted lane with a buffer: `buffered_lane`, or a buffer tag that is not "no"."""
    if "buffered_lane" in cycleways:
        return True
    return any(tags.get(key) not in (None, "no", "none", "0") for key in BUFFER_KEYS)


def decent_lane(tags: dict[str, str], cycleways: set[str], width_m: float | None) -> bool:
    """Whether a painted lane is decent (see DECENT_LANE_MIN_M): buffered, or not
    tagged narrower than 5 ft."""
    return lane_is_buffered(tags, cycleways) or width_m is None or width_m >= DECENT_LANE_MIN_M


# "Legal but avoid", by rule. OSM's `expressway=yes` is a divided highway with
# partial access control; at a posted 50 mph or more it is the road the owner's
# US 340 question was about - legal for a bicycle, and nothing a planner should
# send one onto while another way exists. Measured over the region's source
# extract (2026-09-27, road-km with divided carriageways counted once):
# expressway=yes on trunk/primary bicycles may ride is 738 km, of which 425 km
# is posted 55 mph or more and 133 km 50 mph; the rule takes those 558 km
# (US 15 James Madison Highway and Catoctin Mountain Highway, US 29 Lee
# Highway, VA 3 Germanna Highway, Fairfax County Parkway at 50, ...) and leaves
# the urban expressways posted 45 or less (Whitney Young Bridge at 35) to the
# Furth tables and to curated overrides.
AVOID_HIGHWAY = frozenset({"trunk", "trunk_link", "primary", "primary_link"})
AVOID_MIN_POSTED_MPH = 50.0


def legal_but_avoid(tags: dict[str, str]) -> str | None:
    """Why a way is "legal but avoid", or None. Posted speed only: never assumed."""
    if tags.get("highway") not in AVOID_HIGHWAY or tags.get("expressway") != "yes":
        return None
    posted = parse_maxspeed_mph(tags.get("maxspeed"))
    if posted is None or posted < AVOID_MIN_POSTED_MPH:
        return None
    return f"legal but avoid: expressway posted {posted:g} mph"


def trail_rule(highway: str, kind: str | None = None) -> str:
    """The rule recorded on a trail-class way of `highway` and `kind`
    (`classes.trail_kind`). The tier is LTS 1 whatever the kind.

    THIS TEXT IS JOINED AGAINST STORED DATA. The rebuild writes it into
    `segment.stress_rule`, and on a table without the facility column the
    stress tiles select the zoomed-out paths and derive the facility by
    comparing that column with these strings (`pipeline.schema`'s PATH_RULES,
    trails_predicate and TRAIL_NETWORK_FACILITY, and the overview's partial
    index). Changing a word here silently drops every trail from the
    zoomed-out map until the next rebuild writes the new text - and
    the tests, which build their expectations from this function, will not
    notice. Add a new text beside the old one (as PATH_RULES keeps the
    cycleway's text from before `kind` existed) rather than editing one.
    """
    if kind is not None:
        return f"trail-class way ({highway}, {kind})"
    return f"trail-class way ({highway})"


def classify(
    tags: dict[str, str],
    aadt: int | None = None,
    aadt_source: str | None = None,
    urban: bool = True,
    aadt_year: int | None = None,
    jurisdiction: str | None = None,
    divided: bool = False,
    separate_facility: bool = False,
    parking_width_m: float | None = None,
) -> StressResult:
    """Classify one way: its Furth tier, or "legal but avoid" where the rule says so.

    `jurisdiction` is the state the way lies in ("DC", "MD", "VA"), for the
    speed a way with no posted limit is read at (`default_speed_mph`).
    `divided` says a one-way way is one carriageway of a two-way road
    (`routemaker.divided`): it is scored as the two-way road it is.
    `separate_facility` says the road's bike facility is mapped as its own way
    and lies beside it (`routemaker.facility.separate_pairs`), which the
    arterial floor counts as bike infrastructure.

    `parking_width_m` is the width of one parking lane where an agency's street
    record gives it (`routemaker.agency_roads`). Furth measures a bike lane
    beside parking as the lane *plus* the parking lane, 15 ft, and OSM's
    `cycleway:width` is the lane alone, so without it the criterion is read
    against the lane's own width and almost no lane beside parking passes. With
    it the two are added where a lane runs beside parking, for the table only:
    whether a lane is decent (`decent_lane`) is about the lane itself."""
    result = _classify(
        tags,
        aadt,
        aadt_source,
        urban,
        aadt_year,
        jurisdiction,
        divided,
        separate_facility,
        parking_width_m,
    )
    reason = legal_but_avoid(tags)
    if reason is None:
        return result
    return replace(result, tier=Stress.AVOID, rule=f"{reason} (Furth: {result.rule})")


def _classify(
    tags: dict[str, str],
    aadt: int | None = None,
    aadt_source: str | None = None,
    urban: bool = True,
    aadt_year: int | None = None,
    jurisdiction: str | None = None,
    divided: bool = False,
    separate_facility: bool = False,
    parking_width_m: float | None = None,
) -> StressResult:
    """Classify one way by the Furth tables.

    `aadt` is bidirectional vehicles per day, already normalized.

    `aadt_source` is the publishing agency, not its precedence tier - see
    `StressResult` - and `aadt_year` is the count's vintage. Both are recorded
    on the result whenever `aadt` is given, and both are the derivative's only
    route back to which agency's data is in a segment.

    `urban` selects which speed defaults apply where nothing is posted. It comes
    from the coverage polygon's urban-area layer at preprocessing time; the
    default is the conservative one for the District, where most of the
    deployment's traffic is.
    """
    highway = tags.get("highway", "")
    assumed: list[str] = []

    if highway in TRAIL_CLASS:
        return StressResult(Stress.LTS1, trail_rule(highway, trail_kind(tags)))

    if highway in MOTOR_ONLY:
        return StressResult(Stress.LTS4, f"motor-only classification ({highway})")

    speed_mph = parse_maxspeed_mph(tags.get("maxspeed"))
    if speed_mph is not None and maxspeed_is_unitless(tags.get("maxspeed")):
        # The number was surveyed; the unit was not. Read as mph, which is the
        # higher-stress reading and the only one that exists on a US sign.
        assumed.append("maxspeed unit")
    zone = speed_zone(tags, jurisdiction) if speed_mph is None else None
    if zone == "DC":
        speed_mph = DC_ALLEY_MPH if tags.get("service") == "alley" else DC_DEFAULT_MPH
        assumed.append("maxspeed")
    elif zone in ("MD", "VA") and urban and highway in MD_VA_URBAN_DEFAULT_MPH:
        speed_mph = MD_VA_URBAN_DEFAULT_MPH[highway]
        assumed.append("maxspeed")
    elif speed_mph is None:
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
    # The lane count the tables read (see URBAN_SCORED_LANES): inside an urban
    # area a multi-lane street is read on the single-lane row.
    # A carriageway of a divided road is not a one-way street: the other
    # direction's traffic is across the median (`routemaker.divided`).
    oneway = is_oneway(tags) and not divided
    # Inside an urban area a one-way street with up to URBAN_ONEWAY_MAX_LANES
    # is read on the single-lane row; a two-way multi-lane street, or a wider
    # one-way, keeps a floor of LTS 3 (`urban_two_way_floor`, below).
    urban_multilane = urban and lanes > URBAN_SCORED_LANES
    oneway_relief = urban_multilane and oneway and lanes <= URBAN_ONEWAY_MAX_LANES
    scored_lanes = URBAN_SCORED_LANES if urban_multilane else lanes

    # The provision on the *worst side a rider may be made to use*, not every
    # value tagged anywhere on the way. On a two-way street the sides are the
    # two directions and one tier is stored per way, so a lane on one side only
    # is mixed traffic for the other direction; on a one-way street there is one
    # side in use and either side answers. The same rule runs through
    # `cycleway_width_m`, `has_shoulder` and `shoulder_width_m`, and it is what
    # keeps building the second side of a facility from *raising* a road's
    # stress. See `tags.cycleway_values`.
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
    # The bike-lane table's tier for a rideable shoulder, credited or not.
    shoulder_table_tier: Stress | None = None

    # Facility, in descending order of separation.
    if cycleways & SEPARATED_CYCLEWAY:
        tier, rule = Stress.LTS1, "separated track alongside"
    elif cycleways & PAINTED_CYCLEWAY:
        # Only the cycleway's own width. Reading the roadway `width` tag made a
        # four-lane arterial *lower* stress the moment someone surveyed its
        # carriageway, which is backwards.
        #
        # And the narrowest width among the sides the provision is on, each
        # side's own - `shoulder_width_m`'s rule, for the reason written at
        # `cycleway_width_m`: the left and right keys are two sides of one road
        # and the tile build does not know which side the route uses, while a
        # width on a side without the painted lane is not the lane's.
        width = cycleway_width_m(tags)
        if width is None:
            assumed.append("cycleway width")
        # Furth's criterion beside parking is the lane plus the parking lane; the
        # decent-lane test below stays on the lane's own width.
        table_width = width
        if width is not None and parking is True and parking_width_m:
            table_width = width + parking_width_m
        tier, rule = _bike_lane_tier(speed_mph, scored_lanes, table_width, parking)
        if (
            FURTH_LANE_NO_CREDIT_MPH <= speed_mph <= DECENT_LANE_MAX_MPH
            and lanes < DECENT_LANE_MAX_LANES
            and decent_lane(tags, cycleways, width)
        ):
            # Mixed traffic is LTS 4 at these speeds on any lane count, and so
            # is Furth's table for the lane: a tier below it. Not from three
            # lanes a direction, where Montgomery's Appendix D keeps LTS 4
            # whatever the lane (review r1).
            tier = Stress.LTS3
            rule = f"bike lane, decent, {speed_mph:g} mph: a tier below mixed traffic"
    else:
        tier, rule = _mixed_traffic_tier(speed_mph, scored_lanes, urban_multilane)
        if urban_multilane and not oneway_relief:
            kind = "wide one-way" if oneway else "two-way"
            tier, rule = urban_two_way_floor(tier, rule, speed_mph, aadt, kind)
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
        # tier can never come out *above* the tier the same road would get with
        # a painted lane of the same width read the same way, at any speed or
        # lane count. "Read the same way" is not a hedge - it is the door zone,
        # and it is one of the two things that separate the two provisions; see
        # the comment on the `parking=False` argument below.
        #
        # Two conditions survive from the old credit. The width has to be one a
        # rider can actually sit in, since a six-inch shoulder is not a refuge
        # and an untagged width is read as narrow. And the result may not be
        # *worse* than the same road with no shoulder at all, which is what the
        # comparison below is for: a shoulder narrower than Furth's criterion
        # scores LTS2 on the table while a 20 mph street with nothing at all
        # scores LTS1, and a strip of asphalt at the edge of a quiet street does
        # not make it more hostile than no strip of asphalt would.
        #
        # That floor is the other thing that separates the two, and it is the
        # one this module adds rather than reads out of Furth: the bike-lane
        # branch above has no such floor, so on that same 20 mph street a 1.3 m
        # painted lane comes out LTS2 where a 1.3 m shoulder comes out LTS1.
        # Furth's table really does score a narrow lane at LTS2 where calm mixed
        # traffic is LTS1, and the deviation here is the floor, kept on the
        # weaker provision only. Adding it to the bike-lane branch as well is
        # what `test_a_bike_lane_is_scored_on_furths_table_without_the_shoulders_floor`
        # refuses.
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
                # 15 ft. So the road's own value is passed and the wider
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
                    scored_lanes,
                    shoulder_width,
                    shoulder_parking,
                    facility="paved shoulder",
                )
                shoulder_table_tier = shoulder_tier
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
    # Recorded from the presence of a count, not from the gate firing: a
    # segment a source touched is a segment that source influenced, whether or
    # not the modifier below moved the tier.
    volume_source = aadt_source if aadt is not None else None
    volume_year = aadt_year if aadt is not None else None
    # A two-way multi-lane city street has had its busy volume read by
    # `urban_two_way_floor` (v2.2's own threshold) and is not bumped again here;
    # a quiet one keeps the low-volume relief, but not below the floor - v2.2
    # rates two lanes a direction LTS 3 to 38.5 mph at a low count, so a quiet
    # 35 mph four-lane street is LTS 3, as it was before item 109.
    two_way_floored = urban_multilane and not oneway_relief and not has_facility
    if two_way_floored and aadt is not None and aadt <= VOLUME_QUIET and tier > Stress.LTS3:
        speed_was_measured = "maxspeed" not in assumed
        if speed_mph <= 35 or not speed_was_measured:
            tier, rule = Stress(tier - 1), rule + ", low volume"
    if aadt is not None and scored_lanes <= 1 and not has_facility and not two_way_floored:
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
        # Furth v2.2's middle band at the lowest speeds: below 23.5 mph a
        # street is LTS 1 only under 1,000-1,500 vehicles a day, so between
        # VOLUME_QUIET and VOLUME_BUSY it is LTS 2 (review r1, B2; the
        # District's 20 mph put 61 mi of such streets at LTS 1).
        elif speed_mph <= MID_VOLUME_MAX_MPH and aadt > VOLUME_QUIET and tier is Stress.LTS1:
            tier, rule = Stress.LTS2, rule + ", mid volume"

    # Arterials (OWNER-DECISIONS 141: "Make arterials LTS 3 or greater unless
    # there s bike infrastructure"): a trunk, primary or secondary road, or its
    # link, is LTS 3 at least unless it carries a painted, buffered or
    # protected lane, or its facility is mapped as its own way beside it. The
    # District's 20 mph had put 23 mi of unposted arterials with no count at
    # LTS 1. Everywhere, not only in the District. A rideable paved shoulder
    # the bike-lane table credited counts as a provision here too
    # (`has_facility`; the owner, item 145: "Yes, count it"): Furth scores the
    # two as one, and the floor must not
    # rate a road with a shoulder worse than the same road with a lane.
    # Collectors (OWNER-DECISIONS 176: "At least LTS 2 (Recommended)"): a
    # tertiary street or its link without bike infrastructure is LTS 2 at
    # least; a count may push it higher. The District's 20 mph had left 51 mi
    # of them at LTS 1, most with no count.
    floor = (
        (Stress.LTS3, "arterial floor")
        if highway in ARTERIAL_HIGHWAY
        else (Stress.LTS2, "collector floor")
        if highway in COLLECTOR_HIGHWAY
        else None
    )
    if floor is not None and tier < floor[0] and not (has_facility or separate_facility):
        if rideable_shoulder and shoulder_table_tier is not None:
            # A rideable shoulder is bike infrastructure (item 145), whether or
            # not the table credited it: on a 20 mph road mixed traffic is LTS
            # 1 already and the shoulder never is. Such a road takes the tier
            # the bike-lane table gives its shoulder - the tier the same road
            # with a lane of that width would have - so the floor neither rates
            # it worse than the lane nor better (review r2).
            if shoulder_table_tier > tier:
                tier, rule = shoulder_table_tier, rule + ", shoulder read as a lane"
        else:
            tier, rule = floor[0], rule + ", " + floor[1]

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

    # The road's traits as the intersection model will state them: only what
    # was read, never the class default the tables fell back on (review r1: an
    # assumed speed or lane count would be told to a rider as fact, "2-lane 25
    # mph road", and an assumed single lane would zero the merge cost the model
    # otherwise assumes by tier).
    return StressResult(
        tier,
        rule,
        tuple(assumed),
        volume_source,
        aadt,
        volume_year,
        speed_mph=None if "maxspeed" in assumed else speed_mph,
        lanes=None if "lanes" in assumed else lanes,
        oneway=oneway,
        graph_oneway=is_oneway(tags),
    )


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


def inferred_unpaved(tags: dict[str, str]) -> bool | None:
    """`is_unpaved` as the map and the segment table carry it: a way tagged
    `highway=track` with no `surface` is read as unpaved, unless its
    `tracktype` is `grade1` (paved or nearly so). OWNER-DECISIONS 376 (park
    trails with no surface tag, PARK-TRAILS-investigation.md, part C): a track
    is a farm, forest or park access way and is gravel or dirt in nearly every
    case, so it draws brown, with the unpaved mark, and stays open to bicycles.

    Only the stored column, and so the map, the unpaved ranking and the trail
    seek, read it; the classifier's own speed cap for an unpaved rural lane keeps
    reading `is_unpaved`, so no tier changes. An explicit `surface` always wins,
    and any other way with no surface stays unknown (None).
    """
    unpaved = is_unpaved(tags)
    if unpaved is None and tags.get("highway") == "track" and tags.get("tracktype") != "grade1":
        return True
    return unpaved
