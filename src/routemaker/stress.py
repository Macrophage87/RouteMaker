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
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

from .classes import MOTOR_ONLY_HIGHWAY, TRAIL_CLASS_HIGHWAY
from .tags import (
    cycleway_values,
    has_parking_lane,
    has_shoulder,
    lanes_per_direction,
    parse_maxspeed_mph,
    parse_width_m,
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
    "service": 20.0,
}
DEFAULT_MAXSPEED_MPH = DEFAULT_MAXSPEED_MPH_URBAN
DEFAULT_LANES_PER_DIRECTION = 1

# Volume thresholds in vehicles per day, as a modifier on two-lane roads only.
# Normalized to one definition before the classifier reads them: VDOT publishes
# bidirectional counts, the District publishes AADT, and Maryland's is embedded
# in a finished score.
# A shoulder narrower than this is not somewhere a rider can sit.
SEPARATED_CYCLEWAY = frozenset({"track", "separate", "opposite_track"})
PAINTED_CYCLEWAY = frozenset({"lane", "opposite_lane", "buffered_lane", "left", "right"})

RIDEABLE_SHOULDER_M = 1.2

# Virginia's statutory default where a highway is not surface treated.
UNPAVED_RURAL_DEFAULT_MPH = 35.0

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
    speed_mph: float, lanes: int, width_m: float | None, parking: bool | None
) -> tuple[Stress, str]:
    """Furth bike-lane criteria. A narrow lane beside parking is a door zone."""
    # Treat unknown parking as present and unknown width as narrow: both are the
    # higher-stress reading, and both are common in this region's tagging.
    beside_parking = parking is not False
    narrow = width_m is None or width_m < (4.1 if beside_parking else 1.7)

    if speed_mph >= 40:
        return Stress.LTS4, "bike lane, 40 mph or above"
    if speed_mph >= 35:
        return Stress.LTS3, "bike lane, 35 mph"
    if speed_mph >= 30 or lanes > 1:
        return (
            (Stress.LTS3, "bike lane, narrow or multilane at 30 mph")
            if narrow
            else (
                Stress.LTS2,
                "bike lane, adequate width at 30 mph",
            )
        )
    if narrow:
        return Stress.LTS2, "bike lane, narrow at 25 mph or below"
    return Stress.LTS1, "bike lane, adequate width at 25 mph or below"


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
    if speed_mph is None:
        table = DEFAULT_MAXSPEED_MPH_URBAN if urban else DEFAULT_MAXSPEED_MPH_RURAL
        speed_mph = table.get(highway, 30.0 if urban else 50.0)
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
    # A tag asserting the *absence* of a facility is not a facility. Testing the
    # raw value set let `cycleway=no`, which is common here, skip the volume
    # modifier the rural position depends on.
    has_facility = bool(cycleways & (SEPARATED_CYCLEWAY | PAINTED_CYCLEWAY))
    parking = has_parking_lane(tags)
    if parking is None:
        assumed.append("parking")

    # Facility, in descending order of separation.
    if cycleways & SEPARATED_CYCLEWAY:
        tier, rule = Stress.LTS1, "separated track alongside"
    elif cycleways & PAINTED_CYCLEWAY:
        # Only the cycleway's own width. Reading the roadway `width` tag made a
        # four-lane arterial *lower* stress the moment someone surveyed its
        # carriageway, which is backwards.
        width = parse_width_m(
            tags.get("cycleway:width")
            or tags.get("cycleway:both:width")
            or tags.get("cycleway:left:width")
            or tags.get("cycleway:right:width")
        )
        if width is None:
            assumed.append("cycleway width")
        tier, rule = _bike_lane_tier(speed_mph, lanes, width, parking)
    else:
        tier, rule = _mixed_traffic_tier(speed_mph, lanes)
        # Shoulder credit matters most at speed, not least: a 45 mph road with a
        # wide paved shoulder is a different proposition from the same road with
        # a rumble strip and a ditch, and on a rural group ride that is the most
        # useful discrimination available. Gated on a width that can actually be
        # ridden, since a six-inch shoulder is not a refuge; an untagged width is
        # read as narrow.
        if has_shoulder(tags) and tier > Stress.LTS1:
            shoulder_width = parse_width_m(
                tags.get("shoulder:width") or tags.get("shoulder:both:width")
            )
            if shoulder_width is None:
                assumed.append("shoulder width")
            if shoulder_width is not None and shoulder_width >= RIDEABLE_SHOULDER_M:
                tier, rule = Stress(tier - 1), rule + ", rideable shoulder"

    # Volume, as a modifier on two-lane roads only, and never upward past the
    # tier speed already set.
    volume_source = aadt_source if aadt is not None else None
    if aadt is not None and lanes <= 1 and not has_facility:
        # A guessed speed may not be improved by a guess, but a measured count is
        # evidence: the conservative rule is about missing evidence, not about
        # refusing what is there. So a real AADT relieves an assumed speed, while
        # an absent one leaves the assumption standing.
        if aadt <= VOLUME_QUIET and tier > Stress.LTS1 and speed_mph <= 35:
            tier, rule = Stress(tier - 1), rule + ", low volume"
        elif aadt >= VOLUME_BUSY and tier < Stress.LTS4:
            tier, rule = Stress(tier + 1), rule + ", high volume"

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
