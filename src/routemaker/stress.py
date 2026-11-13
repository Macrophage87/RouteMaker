"""Level of Traffic Stress classification.

The tables are published ones, written here from the sources and read as published:

- Streets and roads in mixed traffic, and painted bike lanes: P. G. Furth, "Level of Traffic
  Stress Criteria for Road Segments, version 2.2 (May, 2022)", Northeastern University,
  https://bpb-us-e1.wpmucdn.com/sites.northeastern.edu/dist/e/618/files/2014/05/LTS-Tables-v2.2.pdf
  (fetched and read 2026-11-13). `MIXED_TRAFFIC_ROWS` is its "Bikes in mixed traffic" table
  cell for cell. (Until 2026-11-13 this docstring said "Furth 2017" and the bands were the
  2012 ones of Mekuria, Furth and Nixon, with a stack of local count steps on top.)
- Rural two-lane roads at 45 mph or more: Oregon DOT, Analysis Procedures Manual version 2,
  chapter 14 (07/2025), Exhibit 14-17, https://www.oregon.gov/odot/Planning/Documents/APMv2_Ch14.pdf
  (fetched and read 2026-11-13). `RURAL_LEVELS` is that exhibit cell for cell.
- A road nobody counted is read at the usual count of its class and setting, through the
  same tables (`CLASS_COUNT`, measured on this region's counted roads), as Oregon's
  Exhibits 14-6 and 14-7 read "functional class if ADT is not available".

LOGIC AND LOCAL DATA. Nothing in the rules names a road, a place or an agency. What is
local is data, fed in through arguments and small tables: the speed the law sets where
nothing is posted (`SPEED_LAW`, one entry a jurisdiction, chosen by `jurisdiction`; a new
state is a new entry and no code), the usual count of a class (`CLASS_COUNT`),
whether the way is inside a census urban area (`urban`), and a traffic count (`aadt`). An
agency's own stress rating is recorded beside this one for comparison and never sets the
level (`agency_lts.COMPARISON_ONLY`). An approved override row (`pipeline.overrides`)
outranks this module's level on the ways it names.

Where this module is not the published table, and why (each is at the code):

- OSM does not record a centerline, so the road class stands in for it: local streets read
  Furth's "unlaned" row, collectors and arterials his "centerline" row (`UNLANED_HIGHWAY`);
  `lane_markings=yes/no` decides where it is tagged. Our default, unmeasured.
- Furth's column is the prevailing speed; this module reads the posted limit, or the law's
  default. A narrow or winding rural lane is read at a lower speed
  (`NARROW_RURAL_ROAD_MPH`): the owner's choice, unmeasured. This is the module's main
  known limit: a limit, posted or statutory, is not the speed traffic travels at.
- Levels above 4: 4.5 for a rural expressway, a fast multi-lane highway and a very busy
  two-lane rural highway, and 5 ("legal but avoid") for an urban expressway. The owner's.
- The bike-lane table is stricter than v2.2 in a few cells (`_bike_lane_tier`); a lane
  never rates a street worse than the same street without one (v2.2's note 4).
- Service roads at LTS 1 are 1.5 (`service_road_step`, the owner's).

The order of the steps in `_classify`:

1. Speed: the posted limit, else the law's default for the place and class.
2. The road with no bike provision: Furth's mixed-traffic table; outside urban areas at
   45 mph or more, Oregon's rural table.
3. The provision: a separated track, a painted lane or a rideable paved shoulder, each
   never worse than step 2's answer (Furth v2.2, note 4 under both bike-lane tables).
4. Caps: restricted motor traffic, rough surface.

A painted bike lane and a rideable paved shoulder are the same provision and are scored on
the same table, so a shoulder never rates a road worse than a lane read the same way. A
road with no parking tags cannot have a parking lane beside its shoulder, so the shoulder
is measured against the no-parking width while a lane on the same road is measured,
conservatively, against the wider one; a road that declares a parking lane has said its
outermost strip is occupied, and the shoulder there is measured beside parking too.

Both provisions are read on the worst side a rider may be made to use: on a two-way street
a facility on one side only is mixed traffic for a rider heading the other way, and where
both sides carry one the narrower counts. On a one-way street either side answers.

Surface is last and nearly inert: maintained gravel moves nothing. It only floors LTS 1,
the level that claims a child could ride it, against a surface that would shed one.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field, replace
from enum import IntEnum

from . import surfaces
from .classes import MOTOR_ONLY_HIGHWAY, TRAIL_CLASS_HIGHWAY, trail_kind
from .facility import (
    USE_SIDEPATH,
    closed_to_motor_traffic,
    has_side_path_on_the_road,
    is_use_sidepath_road,
    painted_lane_on_road,
)
from .geo import Point, haversine
from .shape import sinuosity
from .tags import (
    PAINTED_CYCLEWAY,
    SEPARATED_CYCLEWAY,
    cycleway_provision,
    cycleway_shoulder,
    cycleway_sides,
    cycleway_values,
    cycleway_width_m,
    has_parking_lane,
    has_shoulder,
    is_oneway,
    lanes_per_direction,
    maxspeed_is_unitless,
    open_to_buses,
    parse_maxspeed_mph,
    parse_width_m,
    posted_maxspeed,
    provision_sides,
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

# What is read when a tag is absent. Recorded on the result (`StressResult.assumed`) so a
# level derived from assumptions is distinguishable from one derived from tags. They do
# NOT all err toward higher stress, as this comment said until 2026-11-13. Each, by kind:
#
# - Speed, nothing posted: LAW where the state is known and its statute covers the road
#   (`SPEED_LAW`, `default_speed`), in the same class as a sign; else the class tables
#   below, which are OUR DEFAULTS, unmeasured. The result says which
#   (`StressResult.speed_source`).
# - Speed, the unit missing: mph (higher-stress, and the only unit on a US sign).
# - Lanes: one each way (LOWER-stress; our default, unmeasured. A four-lane 25 mph street
#   with no `lanes` tag is rated as a two-lane one).
# - Count, none: the usual count of the road's class and setting (`CLASS_COUNT`), read
#   through the same table as a counted road.
# - Parking beside a painted lane, not mapped: the more stressful of Furth's two lane
#   tables (`_bike_lane_tier`). Beside a shoulder: absent.
# - Lane or shoulder width: narrow (higher-stress).
# - Shoulder on a rural road: unknown, read as none for the level (higher-stress) and
#   never written as "no shoulder".
# The rule (the owner, 2026-11-13): missing data never LOWERS a level. Where a tag is
# unknown and two published readings apply, the more stressful one is taken.
# The class tables: OUR DEFAULTS, unmeasured. Split by setting, not by highway class alone:
# the same `unclassified` tag covers a 25 mph city side street and a 50 mph country through
# road with no shoulder.
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

# Rural defaults where nothing is posted, by class. OUR DEFAULTS, unmeasured: read where the
# state is not known, and for service roads, tracks and living streets everywhere. Where
# the state is known its statute is read instead (`default_speed`).
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


# --- Statutory speeds: DATA, one entry a jurisdiction ----------------------------------------
# What the law sets where nothing is posted. This table is the only place a jurisdiction is
# named for speed; the functions below read it and name none. Adding a state (Pennsylvania,
# say) is one entry here with its citation, and no code.
@dataclass(frozen=True)
class SpeedLaw:
    """One jurisdiction's statutory speed limits. Every figure is LAW, from `citation`,
    except `urban_major`, which is OUR DEFAULT."""

    citation: str
    # (undivided, divided) mph in a business or residence district, and elsewhere.
    district: tuple[float, float]
    elsewhere: tuple[float, float]
    # The statute's lower figure on a road that is not hard surfaced, where it has one.
    unpaved: float | None = None
    # By the way's `service` value (an alley).
    by_service: dict[str, float] = field(default_factory=dict)
    # True where the statute's figure holds on every street whatever its class, so no
    # "is this a district?" question arises.
    every_street: bool = False
    # OUR DEFAULTS, unmeasured, by class, inside urban areas: the classes too major to
    # assume they lie in a business or residence district. Reading the district figure
    # there would lower the level on missing data.
    urban_major: dict[str, float] = field(default_factory=dict)


# The urban arterial figure where the statute's district cannot be assumed: MDOT's imputation
# for unposted major roads (MDOT LTS methodology), used in every state (OWNER-DECISIONS 112).
_URBAN_MAJOR = {"secondary": 35.0, "secondary_link": 35.0, "primary": 35.0, "primary_link": 35.0}
SPEED_LAW: dict[str, SpeedLaw] = {
    "DC": SpeedLaw(
        # "On all streets and highways, unless otherwise designated in accordance with
        # § 2200.2, the maximum lawful speed shall be twenty miles per hour (20 mph)" (as
        # amended by DDOT's rulemaking adopted 2020-06-01, read 2026-11-13 at
        # https://ddot.dc.gov/sites/default/files/dc/sites/ddot/publication/attachments/NEPRM%2020MPH.pdf).
        # Alleys 15 mph: DDOT, "Speeding laws, fines and safety tips",
        # https://ddot.dc.gov/page/speeding-laws-fines-and-safety-tips (the DCMR subsection
        # was not opened). The owner, 2026-11-13: "DC 20 mph default is the DC code. It's
        # just a fact."; OWNER-DECISIONS 108.
        citation="18 DCMR 2200.6",
        district=(20.0, 20.0),
        elsewhere=(20.0, 20.0),
        by_service={"alley": 15.0},
        every_street=True,
    ),
    "MD": SpeedLaw(
        # Business district 30; residential district 30 undivided, 35 divided; elsewhere 50
        # undivided, 55 divided (as MDOT SHA states it,
        # https://roads.maryland.gov/mdotsha/pages/Index.aspx?PageId=295; the statute's own
        # text was not opened). Until 2026-11-13 a residential street here was read at
        # MDOT's imputed 25, not the statute's 30 (the owner, 2026-11-13: law is law).
        citation="Md. Code, Transportation 21-801.1",
        district=(30.0, 35.0),
        elsewhere=(50.0, 55.0),
        urban_major=_URBAN_MAJOR,
    ),
    "VA": SpeedLaw(
        # 25 in business and residence districts, 55 elsewhere, 35 on a highway that is not
        # surface treated (as VDOT states it,
        # https://www.vdot.virginia.gov/about/our-system/highways/speed-limits/; the
        # sections' own text was not opened).
        citation="Code of Virginia 46.2-870 to 46.2-878",
        district=(25.0, 25.0),
        elsewhere=(55.0, 55.0),
        unpaved=35.0,
        urban_major=_URBAN_MAJOR,
    ),
    "WV": SpeedLaw(
        # 25 in a business or residence district, 55 on open country highways, with no
        # separate figure for an unpaved road (cited from the project's record of
        # 2026-10-31; not re-opened).
        citation="W. Va. Code 17C-6-1(b)",
        district=(25.0, 25.0),
        elsewhere=(55.0, 55.0),
        urban_major=_URBAN_MAJOR,
    ),
}
# The classes a statute's business-or-residence-district figure is read on: inside an urban
# area, the local streets and minor through roads; outside one, a residential street only
# (its class is the only evidence of a district the map gives there). A district is the
# statutes' own term; "inside an urban area" is our reading of it.
DISTRICT_HIGHWAY_URBAN = frozenset({"residential", "unclassified", "tertiary", "tertiary_link"})
DISTRICT_HIGHWAY_RURAL = frozenset({"residential"})
# Where the unposted speed came from (`StressResult.speed_source`).
SPEED_FROM_STATUTE = "statute"
SPEED_FROM_CLASS = "class default"
SPEED_FROM_NARROW_ROAD = "narrow road rule"


def statutory_default_mph(
    tags: dict[str, str], zone: str | None, urban: bool, divided: bool
) -> float | None:
    """The speed limit the law sets where none is posted (`SPEED_LAW`), reading "a business
    or residence district" as inside an urban area, or None where the state is not known.
    The junction model prices an unposted road at it (OWNER-DECISIONS 469, 469a)."""
    law = SPEED_LAW.get(zone or "")
    if law is None:
        return None
    return _statute_mph(law, tags, urban, divided)


def _statute_mph(law: SpeedLaw, tags: dict[str, str], district: bool, divided: bool) -> float:
    service = law.by_service.get(tags.get("service", ""))
    if service is not None:
        return service
    mph = (law.district if district else law.elsewhere)[divided]
    if law.unpaved is not None and is_unpaved(tags):
        mph = min(mph, law.unpaved)
    return mph


def default_speed(
    tags: dict[str, str], zone: str | None, urban: bool, divided: bool
) -> tuple[float, str]:
    """The speed an unposted way is read at, and where it came from: the statute
    (`SPEED_FROM_STATUTE`) where the state is known and its law covers the road, else the
    class tables (`SPEED_FROM_CLASS`, our defaults)."""
    highway = tags.get("highway", "")
    law = SPEED_LAW.get(zone or "")
    if law is not None:
        if law.every_street:
            return _statute_mph(law, tags, urban, divided), SPEED_FROM_STATUTE
        if urban and highway in law.urban_major:
            return law.urban_major[highway], SPEED_FROM_CLASS
        if highway in (DISTRICT_HIGHWAY_URBAN if urban else DISTRICT_HIGHWAY_RURAL):
            return _statute_mph(law, tags, True, divided), SPEED_FROM_STATUTE
    table = DEFAULT_MAXSPEED_MPH_URBAN if urban else DEFAULT_MAXSPEED_MPH_RURAL
    unknown = DEFAULT_MAXSPEED_MPH_UNKNOWN_URBAN if urban else DEFAULT_MAXSPEED_MPH_UNKNOWN_RURAL
    mph = table.get(highway, unknown)
    if law is not None and not urban and mph >= RURAL_TABLE_MIN_MPH:
        # An open-country through road: the statute's own figure.
        return _statute_mph(law, tags, False, divided), SPEED_FROM_STATUTE
    return mph, SPEED_FROM_CLASS


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

# A shoulder narrower than this, 4 ft, is not somewhere a rider can sit (Oregon DOT, APM
# chapter 14, 07/2025: "Paved shoulders less than four feet in width are not considered
# rideable"; Furth v2.2's minimum bike lane is 4 ft at a curb).
RIDEABLE_SHOULDER_M = 1.2
RIDEABLE_FT = 4

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
# with nothing parked beside it is measured on its own, 6 ft [1.83 m]: v2.2 "6+ ft" against
# "less than 6 ft", MTI 11-19 "6 ft or more". Until 2026-11-13 this was 1.7 m, commented
# "5.5 ft", which is the top of MTI 11-19's NARROW bin and not 1.7 m either. Named rather
# than written inline at the comparison because a reviewer replaced them with
# 2.1 and 0.7 - half and a third of the published figures - and the whole
# suite stayed green.
FURTH_LANE_BESIDE_PARKING_FT = 15
FURTH_LANE_ALONE_FT = 6
FURTH_LANE_BESIDE_PARKING_M = FURTH_LANE_BESIDE_PARKING_FT * 0.3048
FURTH_LANE_ALONE_M = FURTH_LANE_ALONE_FT * 0.3048
# LITERATURE. Furth v2.2's minimums, note 2 under each lane table (opened 2026-11-13):
# "Minimum bike lane width is 4 ft next to a curb and 3.5 ft next to a road edge or
# discontinuous gutter seam. For narrower bike lanes, use Mixed Traffic criteria." and
# "Minimum bike lane reach is 12 ft. For narrower reach, use Mixed Traffic criteria." OSM
# does not say curb or road edge, so 4 ft is read (the higher-stress of the two). A lane
# under them earns no lane credit: the road is rated as if it had none. The reach is
# checked only where an agency's record gives the parking lane's width.
FURTH_LANE_MIN_FT = 4
FURTH_REACH_MIN_FT = 12
# How far under a width criterion a measured width may fall and still meet it:
# half a centimetre. A width in feet converted to metres and a sum of two such
# widths land a hair either side of a criterion that is itself a conversion
# (review SF2: a 5 ft lane beside a 10 ft parking lane is exactly Furth's 15 ft
# reach, and read at 1.52 m it fell 4 mm short and to the narrow row). OSM's
# widths are tagged to the centimetre at best.
WIDTH_TOLERANCE_M = 0.005


def lane_width_m(tags: dict[str, str]) -> float | None:
    """The surveyed width of the painted lane a way is scored on (`tags.cycleway_width_m`),
    except that on a two-way street a lane side with no surveyed width makes the width
    unknown: that side's rider has a lane nobody measured, and missing data never lowers a
    level. (`cycleway_width_m` leaves an unsurveyed side out of the comparison, so a 2 m
    lane on one side spoke for an unmeasured lane on the other.)"""
    width = cycleway_width_m(tags)
    if width is None or is_oneway(tags):
        return width
    sides = cycleway_sides(tags)
    if any(sides[name].width_m is None for name in provision_sides(tags)):
        return None
    return width


def meets_width(width_m: float, feet: float) -> bool:
    """Whether a mapped width meets a published criterion written in feet. The tables are
    in feet and OSM widths are metres to one decimal, so a 6 ft lane is mapped 1.8 m and a
    4 ft shoulder 1.2 m: the criterion is the exact conversion or its one-decimal rounding,
    whichever is smaller, less `WIDTH_TOLERANCE_M`. (Before 2026-11-13 6 ft was compared as
    1.8288 m, which a lane mapped "1.8" missed, while 4 ft was already compared as 1.2.)"""
    exact = feet * 0.3048
    return width_m + WIDTH_TOLERANCE_M >= min(exact, round(exact, 1))


# The owner's narrow-road rule (2026-10-13, for v0.7.0): "narrow windy roads that
# are unlikely to see people travelling at 35 on" - Berryville Road, West Old
# Baltimore Road and Davis Mill Road in upcounty Montgomery, which the 50 mph rural
# default above put at LTS 4 and Montgomery Planning rates LTS 1. A rural minor
# road with no posted limit and no traffic count that shows it is narrow (no
# centre line, or a surveyed width of one car each way at most) or winding is read
# at 25 mph instead of the statutory default. By the tables that is LTS 1 on an uncounted
# unclassified road (unlaned row, low band) and LTS 2 on an uncounted tertiary (centerline
# row, 1,001 to 1,500 a day); the rural minimum (`RURAL_MIN_LEVEL`) makes both 2, which is
# what the owner's rule intends. Region-wide ("We can do region
# wide. The goal is also to find the long distance quiet roads"). A posted limit
# always outranks it, and so does a count above VOLUME_QUIET. A quiet count no longer
# switches it off (the Virginia review's R4, the owner, 2026-10-31: "Let's go with all
# these"): VDOT counts nearly every state secondary, so a count showing a narrow road is
# quiet had left it at LTS 3 (the 50 mph default's 4, eased a step by the count) while
# its uncounted twins were LTS 2 - about 324 mi of Fauquier, Culpeper, Orange and west
# Loudoun roads under 500 a day.
NARROW_RURAL_ROAD_MPH = 25.0
NARROW_ROAD_HIGHWAY = frozenset({"unclassified", "tertiary", "tertiary_link", "road"})
# 18 ft: two 9 ft lanes, the narrowest two-lane road with room to pass a rider
# without crossing the centre.
NARROW_ROAD_MAX_WIDTH_M = 5.5
# Path length over straight-line distance, over a stretch long enough that one
# bend at a junction does not count (`winding`). To be calibrated against the
# owner's three roads on the extract before the rule merges.
WINDING_SINUOSITY = 1.2
WINDING_MIN_LENGTH_M = 400.0
# Measured stretch by stretch, not end to end: a straight road that turns one
# corner reads 1.41 end to end (an L with equal legs), and the v0.7.0 staging
# rebuild read 421 mi of such rural roads at 25 mph (LTS 4 to 2). A way winds
# where at least this many of its `WINDING_MIN_LENGTH_M` stretches do, and they
# make up at least half its length; one bend can bend one stretch only. A way too
# short for two stretches is read end to end as before, but must also turn both
# ways (a turn of at least `WINDING_TURN_DEG` to the left and one to the right):
# a corner, however it is drawn, turns one way only.
WINDING_MIN_STRETCHES = 2
WINDING_TURN_DEG = 20.0
NARROW_ROAD_RULE = "narrow rural road"

# --- Traffic counts ------------------------------------------------------------------------
# Counts are vehicles a day in both directions together, normalized to that before the
# classifier reads them. Every count break in this module is the first count of the busier
# band ("this many or more"), taken from the published table it belongs to: Furth v2.2's
# "751-1500", "1501-3000", "3001+", "1001-1500", "8001+" and Oregon's rural bins. Before
# 2026-11-13 there were also local steps at 5,000, 8,000 (on one-lane streets), 9,000,
# 12,000 and 20,000 a day, calibrated on a handful of streets; no published table has them
# and they are gone.
#
# The top of the quiet band, as a count: "1,500 a day or fewer" (Furth's break on both
# single-lane rows). The narrow-road rule reads it.
VOLUME_QUIET = 1_500

# A road with no count is read at an estimated count for its class and setting, through
# the SAME table as a counted road: no separate reading and no floor (the owner,
# 2026-11-13). So a count moves a road either way from the estimate, and no count however
# large reads calmer than the estimate of a quieter road.
#
# MEASURED ON OUR DATA: each figure is the mile-weighted median count of this region's
# counted miles of that class, setting and width (the 2026-11 region sweep,
# reports/region-sweep: every way of the map with its count, 2 significant figures). Counted
# roads are not a random sample of a class (agencies count the busier ones first: 19% of
# urban residential miles are counted, 86% of urban secondary), so on local streets the
# figure leans high, which is the higher-stress way. Columns: (one lane each way, two or
# more), urban then rural. None: fewer than 5 counted miles; the one-lane figure is read.
# LITERATURE for the idea: Oregon DOT's APM chapter 14 reads "functional class if ADT is
# not available" (Exhibits 14-6, 14-7) and allows "a mid-range value" (section 14.5).
# Links read their parent class and service roads, tracks and living streets the
# residential figure (too few are counted to measure: OUR DEFAULT).
CLASS_COUNT: dict[str, tuple[tuple[int, int | None], tuple[int, int | None]]] = {
    "residential": ((380, 2_500), (180, None)),
    "unclassified": ((1_800, 3_400), (220, None)),
    "tertiary": ((4_400, 6_900), (1_300, None)),
    "secondary": ((9_300, 14_000), (3_200, 8_200)),
    "primary": ((14_000, 25_000), (7_500, 16_000)),
    "trunk": ((18_000, 39_000), (13_000, 25_000)),
}
CLASS_COUNT_AS = {
    "living_street": "residential",
    "service": "residential",
    "track": "residential",
    "road": "unclassified",
    "tertiary_link": "tertiary",
    "secondary_link": "secondary",
    "primary_link": "primary",
    "trunk_link": "trunk",
}
# A class in neither table (OSM has many rare `highway` values) is read as a secondary: the
# higher-stress reading of an unknown. Our default.
CLASS_COUNT_UNKNOWN = "secondary"
# An unpaved rural road with no count is read as a rural local street whatever its class:
# gravel there is a low-traffic choice (the owner, 2026-10-12: "We shouldn't overrate
# sparsely used rural roads"). Our default, unmeasured. In town the class figure stands.
UNPAVED_RURAL_COUNT_AS = "residential"

# The road classes read as arterials (the rule text and the road panel name them).
ARTERIAL_HIGHWAY = frozenset(
    {"trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link"}
)
# The classes read on Furth's "unlaned 2-way street (no centerline)" row where
# `lane_markings` does not say: local streets. Collectors and arterials read his centerline
# row. OSM seldom records the centerline itself; the class is the proxy. Our default,
# unmeasured.
UNLANED_HIGHWAY = frozenset(
    {"residential", "living_street", "unclassified", "service", "track", "road"}
)
# Where the count the tables read came from (`StressResult.count_source`).
COUNT_FROM_CLASS = "class estimate"
COUNT_FROM_CALLER = "supplied estimate"

# The general quantity each entry of `StressResult.assumed` stands for, in plain words
# (`StressResult.evidence`).
QUANTITY_OF_ASSUMED = {
    "maxspeed": "travel speed (nothing posted)",
    "maxspeed unit": "travel speed (unit not mapped, read as mph)",
    "lanes": "lanes (read as one each way)",
    "traffic count": "traffic (no count)",
    "parking": "parking beside the lane (not mapped: the more stressful of the two lane tables)",
    "cycleway width": "bike lane width (read as narrow)",
    "shoulder": "shoulder (not mapped, read as under 4 ft)",
    "shoulder width": "shoulder width (not mapped)",
}
# The same, said more exactly where the result records the source.
SPEED_SOURCE_WORDS = {
    SPEED_FROM_STATUTE: "travel speed (the statute's default, nothing posted)",
    SPEED_FROM_CLASS: "travel speed (class default, our default; nothing posted)",
    SPEED_FROM_NARROW_ROAD: "travel speed (the narrow-road rule's 25 mph, nothing posted)",
}
COUNT_SOURCE_WORDS = {
    COUNT_FROM_CLASS: "traffic (the usual count of the road's class and setting, no count)",
    COUNT_FROM_CALLER: "traffic (a supplied estimate for this road, no count)",
}

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
    # A half step (OWNER-DECISIONS 441i-441l): the way is rated half a level above
    # `tier` (1.5 to 4.5; never above Avoid). Stored as the lower level plus this flag,
    # so every reader of the integer tier keeps working.
    half: bool = False
    # Whether the way stood half a level above `computed_tier` before the adjustment (an
    # agency's 2.5, the service-road step's 1.5): `direction` compares the two steps, so a
    # row of 1.5 on an alley already at 1.5 is `same`, and a row of 2 on a 2.5 road is `down`.
    computed_half: bool = False

    @property
    def step(self) -> float:
        """The level as a number: 1, 1.5, 2, ... 4.5, 5."""
        return int(self.tier) + (0.5 if self.half else 0.0)

    @property
    def computed_step(self) -> float:
        """The way's level before the adjustment, half step included."""
        return int(self.computed_tier) + (0.5 if self.computed_half else 0.0)

    @property
    def direction(self) -> str:
        if self.step > self.computed_step:
            return ADJUSTMENT_UP
        if self.step < self.computed_step:
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
    # (`dc-roadway-block`, `baltimore-centerline`, `alexandria-transport-streets`)
    # where its value took precedence, `osm` where the way's own tag stood,
    # `default` where neither said and the classifier assumed. Empty on a way no
    # agency layer reached.
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
    # Where nothing was posted, the jurisdiction's statutory default
    # (`statutory_default_mph`), or the speed the classifier assumed where the
    # state is not known. None where a speed was read.
    # Never said to a rider; the junction model prices an unposted road at it
    # (OWNER-DECISIONS 469: "use each jurisdiction's statutory default").
    default_speed_mph: float | None = None
    # The tier the classifier gave on the agency's own count, where the street's
    # median (`pipeline.aadt_smoothing`) lowered it; None everywhere else, and
    # dropped by anything that sets the tier afresh (an override row, a named
    # corridor, a closure to motor traffic). The link reads `tier`; the junction
    # model reads this, because the owner accepted lower-only smoothing on the
    # ground that a count bunched at an intersection is charged there
    # (OWNER-DECISIONS 303: "we don't want to double count"), so it must still
    # be charged there (ARTERIAL review r0, SF1).
    unsmoothed_tier: Stress | None = None
    # A half step set by an agency's rating (`routemaker.agency_lts`) or by the
    # rural-expressway rule (`rural_expressway`): the way is rated half a level
    # above `tier`, as an owner row's `StressAdjustment.half`.
    half: bool = False
    # Where an agency's rating replaced the classifier's tier: what the
    # classifier said, and every agency rating held for the way, most local
    # first, for the road panel (the owner, 2026-10-13: "put all the relevant
    # information in the tab when viewing the road"). Empty where none did.
    formula_tier: Stress | None = None
    formula_rule: str | None = None
    # Whether the formula's own level (`formula_tier`) was a half step above it.
    formula_half: bool = False
    agency_ratings: tuple = ()
    # On a road with a separated track on its own way (`cycleway=track`): the level the
    # roadway beside the track would have with no provision, half step included. The track
    # itself is LTS 1 here whatever the road; the side-path rules
    # (`beside_busy_road_step`) may read this to rate a track beside a busy road as they
    # rate a separately mapped side path. None on every other way.
    road_level: float | None = None
    # The measured travel speed the tables read in place of the limit, where the caller
    # gave one (`classify`). None on nearly every way: no speed dataset is wired in yet.
    observed_speed_mph: float | None = None
    # Where an unposted speed came from (`SPEED_FROM_STATUTE`, `SPEED_FROM_CLASS`,
    # `SPEED_FROM_NARROW_ROAD`) and where an uncounted road's traffic did
    # (`COUNT_FROM_CLASS`, `COUNT_FROM_CALLER`). None where posted, or counted.
    speed_source: str | None = None
    count_source: str | None = None
    # The classifier's own verdict that this is a rural road the rural minimum holds at
    # LTS 2 (`RURAL_MIN_LEVEL`): what the rebuild's check of the built table reads
    # (`pipeline.lts_sentinels`), so the check cannot read the way differently.
    rural_minimum: bool = False

    @property
    def evidence(self) -> str:
        """A plain note of how much of the rating stands on evidence: which of the general
        quantities (travel speed, traffic, lanes, the facility's width and parking, the
        shoulder) were estimated because the road has no record of them. A confidence
        note for the reader; it changes no level."""
        if self.speed_mph is None and self.default_speed_mph is None and not self.assumed:
            # A trail or a motor-only class: no table was read.
            return "not rated from road inputs"
        words = dict(QUANTITY_OF_ASSUMED)
        if self.speed_source is not None:
            words["maxspeed"] = SPEED_SOURCE_WORDS[self.speed_source]
        if self.count_source is not None:
            words["traffic count"] = COUNT_SOURCE_WORDS[self.count_source]
        # Parking matters only beside a painted lane.
        names = [n for n in self.assumed if n != "parking" or "bike lane" in self.rule]
        estimated = list(dict.fromkeys(words.get(name, name) for name in names))
        if self.observed_speed_mph is None and not any(
            e.startswith("travel speed") for e in estimated
        ):
            # A limit is not a measurement of how fast traffic goes.
            estimated.insert(0, "travel speed (the posted limit, not measured)")
        if not estimated:
            return "every input measured or mapped"
        return "estimated: " + "; ".join(estimated)

    @property
    def is_top_tier(self) -> bool:
        """LTS 4 and up: what the road-exposure report keys on."""
        return self.tier >= Stress.LTS4


# --- The mixed-traffic table (Furth v2.2, "Bikes in mixed traffic") -------------------------
# Furth's speed columns, by the top of each prevailing-speed band; the last is everything
# above (his "43.5-48.5" and "48.5+" columns are the same in every row of this table).
SPEED_COLUMN_MAX_MPH = (23.5, 28.5, 33.5, 38.5, 43.5)
SPEED_COLUMN_WORDS = (
    "20 mph or below",
    "25 mph",
    "30 mph",
    "35 mph",
    "40 mph",
    "45 mph or above",
)
# Each row of the table: the rule's words for it, the first count of each band after the
# first, and one tuple of levels (by speed column) per band. Cell for cell from the source.
ROW_UNLANED, ROW_SINGLE, ROW_TWO_LANES, ROW_THREE_LANES = (
    "unlaned",
    "single lane",
    "2 lanes each way",
    "3 or more lanes each way",
)
MIXED_TRAFFIC_ROWS: dict[str, tuple[tuple[int, ...], tuple[tuple[int, ...], ...]]] = {
    # "Unlaned 2-way street (no centerline)": 0-750, 751-1500, 1501-3000, 3001+.
    ROW_UNLANED: (
        (751, 1_501, 3_001),
        (
            (1, 1, 2, 2, 3, 3),
            (1, 1, 2, 3, 3, 3),
            (2, 2, 2, 3, 3, 4),
            (2, 2, 3, 3, 4, 4),
        ),
    ),
    # "2-way with 1 lane per direction and centerline, or wide 1-way, 1-lane": 0-1000,
    # 1001-1500, 1501+. (His "narrow one-way, 1-lane" row has the same levels with breaks at
    # 601 and 1,001; OSM seldom gives a street's width, so a one-way is read as wide.)
    ROW_SINGLE: (
        (1_001, 1_501),
        (
            (1, 1, 2, 2, 3, 3),
            (2, 2, 2, 3, 3, 4),
            (2, 3, 3, 3, 4, 4),
        ),
    ),
    # "2 thru lanes per direction": 0-8000, 8001+.
    ROW_TWO_LANES: ((8_001,), ((3, 3, 3, 3, 4, 4), (3, 3, 4, 4, 4, 4))),
    # "3+ thru lanes per direction": any ADT.
    ROW_THREE_LANES: ((), ((3, 3, 4, 4, 4, 4),)),
}
# The rule's words for a count band, by how many bands the row has and which one it is.
# THESE TEXTS ARE READ BACK by `core.segment_info` (`_MIXED_PARTS`).
COUNT_BAND_WORDS = {
    1: ("any volume",),
    2: ("low volume", "high volume"),
    3: ("low volume", "mid volume", "high volume"),
    4: ("low volume", "low volume", "mid volume", "high volume"),
}
# Appended where the count was not measured but read from the road's class and setting
# (`CLASS_COUNT`), or from a caller's estimate for the road. THE FIRST IS READ BACK by
# `core.segment_info`.
CLASS_COUNT_RULE = "no count: traffic read from the road's class"
ESTIMATE_COUNT_RULE = "no count: traffic from an estimate for this road"


def speed_column(speed_mph: float) -> int:
    """The column of the mixed-traffic table a speed falls in."""
    return bisect.bisect_left(SPEED_COLUMN_MAX_MPH, speed_mph)


def class_count(tags: dict[str, str], lanes: int = 1, urban: bool = True) -> int:
    """The count a road with none is read at: the usual count of its class, setting and
    width (`CLASS_COUNT`)."""
    highway = tags.get("highway", "")
    name = CLASS_COUNT_AS.get(highway, highway)
    if not urban and is_unpaved(tags):
        name = UNPAVED_RURAL_COUNT_AS
    one, wide = CLASS_COUNT.get(name, CLASS_COUNT[CLASS_COUNT_UNKNOWN])[0 if urban else 1]
    return wide if lanes > 1 and wide is not None else one


def mixed_traffic_row(tags: dict[str, str], lanes: int, oneway: bool) -> str:
    """Which row of Furth's table a road reads: by its through lanes each way, and for one
    lane by whether it has a centerline (`lane_markings`, else its class)."""
    if lanes >= 3:
        return ROW_THREE_LANES
    if lanes == 2:
        return ROW_TWO_LANES
    marked = tags.get("lane_markings")
    if oneway or marked == "yes":
        return ROW_SINGLE
    if marked == "no" or tags.get("highway", "") in UNLANED_HIGHWAY:
        return ROW_UNLANED
    return ROW_SINGLE


def mixed_traffic_level(speed_mph: float, aadt: int, row: str = ROW_SINGLE) -> tuple[float, str]:
    """The level and rule of a road with no bike provision: Furth v2.2's mixed-traffic
    table, from its speed, its count and its row (`mixed_traffic_row`)."""
    rungs, bands = MIXED_TRAFFIC_ROWS[row]
    column = speed_column(speed_mph)
    band = bisect.bisect_right(rungs, aadt)
    words = COUNT_BAND_WORDS[len(bands)][band]
    rule = f"mixed traffic, {SPEED_COLUMN_WORDS[column]}, {row}, {words}"
    return float(bands[band][column]), rule


# --- The rural table (Oregon DOT, APM chapter 14, Exhibit 14-17) ---------------------------
# "BLTS Rural Segment Criteria with posted speeds 45 mph or greater", section 14.4.8 of the
# Analysis Procedures Manual version 2 (last updated 07/2025),
# https://www.oregon.gov/odot/Planning/Documents/APMv2_Ch14.pdf (fetched and read
# 2026-11-13). Cell for cell:
#
#   vehicles a day   shoulder under 4 ft   4 to under 6 ft   6 ft or more
#   under 400        R2                    R2                R2
#   400-1,500        R3                    R2                R2
#   1,500-7,000      R4                    R3                R2
#   over 7,000       R4                    R4                R3
#
# Oregon rates a rural road under 45 mph by its ordinary (Furth-derived) tables with an R
# suffix, which allow level 1; R2 is the lowest cell of THIS table only. It also says its R
# levels are not the urban ones ("an urban BLTS 2 is not the same experience as a rural BLTS
# R2") and that frequent sharp curves "can increase the stress level" (footnote 2); neither
# is modelled here.
# Until 2026-11-13 the map applied a half-step reading of this table through override rows
# (the owner's pick of 2026-11-09: 2, 2.5, 3, then 4 from 3,000 a day; a 4 ft shoulder one
# level lower); the published cells are used now. Oregon's bins share their edges; a count
# of exactly 400 is read in the busier band, 1,500 and 7,000 in the calmer.
RURAL_COUNT_RUNGS = (400, 1_501, 7_001)
RURAL_BAND_WORDS = (
    "under 400 a day",
    "400 to 1,500 a day",
    "1,501 to 7,000 a day",
    "over 7,000 a day",
)
# What is known of a rural road's shoulder (`rural_shoulder`). "Unknown" is the usual case
# (well under 1% of rural miles carry a shoulder tag): it is read on the narrow column, the
# higher-stress reading, and never written as "no shoulder".
SHOULDER_WIDE, SHOULDER_RIDEABLE, SHOULDER_NARROW, SHOULDER_NONE, SHOULDER_UNKNOWN = (
    "wide",
    "rideable",
    "narrow",
    "none",
    "unknown",
)
RURAL_SHOULDER_WORDS = {
    SHOULDER_WIDE: "paved shoulder 6 ft or wider",
    SHOULDER_RIDEABLE: "paved shoulder 4 ft or wider",
    SHOULDER_NARROW: "shoulder under 4 ft",
    SHOULDER_NONE: "no shoulder",
    SHOULDER_UNKNOWN: "shoulder unknown",
}
_RURAL_NARROW = (2, 3, 4, 4)
RURAL_LEVELS = {
    SHOULDER_WIDE: (2, 2, 2, 3),
    SHOULDER_RIDEABLE: (2, 2, 3, 4),
    SHOULDER_NARROW: _RURAL_NARROW,
    SHOULDER_NONE: _RURAL_NARROW,
    SHOULDER_UNKNOWN: _RURAL_NARROW,
}
# Oregon's table is for 45 mph or more (LITERATURE), and at those speeds its lowest cell,
# R2, is the lowest level. Below 45 mph two things here are NOT Oregon's:
# - the minimum of 2 on a rural road open to cars is THE OWNER'S CHOICE (2026-11-13: "the
#   rural table's minimum is the floor"; reason on record: LTS 1 is for children), except
#   on a town street (`built_up` at `BUILT_UP_MAX_MPH` or less), which reads the city table;
# - a rural road under 45 mph takes the lower of the city table and the rural table, so a
#   lower limit never makes the same road more stressful. OUR DEFAULT, unmeasured.
RURAL_TABLE_MIN_MPH = 45.0
RURAL_MIN_LEVEL = 2.0
WIDE_SHOULDER_FT = 6
WIDE_SHOULDER_M = WIDE_SHOULDER_FT * 0.3048
# The rural table applies by setting and speed, not by a list of road classes. What is left
# out is what is not a road through the country: driveways and lots, farm tracks, shared
# streets (each has its own low default speed and rule).
RURAL_NOT_ROADS = frozenset({"service", "track", "living_street"})
RURAL_TABLE_RULE = "rural road"
RURAL_MIN_RULE = "rural roads rate LTS 2 at least"
# A rural road posted at this or less where the map shows a built-up place is a town street
# and is rated as one (it may be LTS 1). The only built-up signals OSM gives outside the
# census urban areas: the way is a residential street, or it has a sidewalk mapped.
BUILT_UP_MAX_MPH = 25.0
SIDEWALK_KEYS = ("sidewalk", "sidewalk:both", "sidewalk:left", "sidewalk:right")
SIDEWALK_PRESENT = frozenset({"both", "left", "right", "yes", "separate"})


def rural_minimum_applies(tags: dict[str, str], jurisdiction: str | None = None) -> bool:
    """Whether the classifier holds a rural way with these tags at LTS 2 at least
    (`StressResult.rural_minimum`): it asks the classifier, so the two cannot disagree. For
    callers with tags and no result (`pipeline.lts_sentinels` falls back to it)."""
    return _classify(tags, urban=False, jurisdiction=jurisdiction).rural_minimum


def built_up(tags: dict[str, str]) -> bool:
    """Whether the map shows a built-up place along a way (`BUILT_UP_MAX_MPH`)."""
    if tags.get("highway") in {"residential", "living_street"}:
        return True
    return any(tags.get(key) in SIDEWALK_PRESENT for key in SIDEWALK_KEYS)


def rural_shoulder(tags: dict[str, str]) -> str:
    """What OSM says of the strip a rider has beside a rural road's traffic, for the rural
    table: a surveyed width on the worst side picks the column, whether the strip is mapped
    as a shoulder or marked as a bike lane (a marked lane is never read worse than an
    unmarked shoulder of the same width); `cycleway=shoulder` (OSM's tag for a shoulder a
    bicycle can use) on both sides of a two-way road with no width is read as 4 ft;
    `shoulder=no` is none; anything else, a strip tagged with no width included, is
    unknown."""
    present = has_shoulder(tags)
    widths = [shoulder_width_m(tags) if present else None]
    cycleways = cycleway_values(tags)
    if cycleways & PAINTED_CYCLEWAY and not cycleways & SEPARATED_CYCLEWAY:
        widths.append(lane_width_m(tags))
    known = [width for width in widths if width is not None]
    if known:
        width = max(known)
        if meets_width(width, WIDE_SHOULDER_FT):
            return SHOULDER_WIDE
        return SHOULDER_RIDEABLE if meets_width(width, RIDEABLE_FT) else SHOULDER_NARROW
    if cycleway_shoulder(tags):
        return SHOULDER_RIDEABLE
    return SHOULDER_NONE if present is False else SHOULDER_UNKNOWN


def rural_road_level(aadt: int, shoulder: str) -> tuple[float, str]:
    """Oregon's rural level and the rule for a two-lane road carrying `aadt` a day, with
    what is known of its shoulder (`rural_shoulder`)."""
    band = bisect.bisect_right(RURAL_COUNT_RUNGS, aadt)
    rule = f"{RURAL_TABLE_RULE}, {RURAL_BAND_WORDS[band]}, {RURAL_SHOULDER_WORDS[shoulder]}"
    return float(RURAL_LEVELS[shoulder][band]), rule


# Furth v2.2's two bike-lane tables, cell for cell. Columns are his prevailing-speed bands.
LANE_SPEED_MAX_MPH = (28.5, 33.5, 38.5, 43.5, 48.5)
# "Conventional bike lanes, advisory bike lanes, and shoulders not adjacent to a parking
# lane", by through lanes each way (1, 2, 3 or more) and (6 ft or wider, narrower).
LANE_LEVELS = (
    ((1, 1, 2, 3, 3, 3), (2, 2, 2, 3, 3, 4)),
    ((2, 2, 2, 3, 3, 3), (2, 2, 2, 3, 4, 4)),
    ((3, 3, 3, 4, 4, 4), (3, 3, 3, 4, 4, 4)),
)
# "... alongside a parking lane", by lanes and (reach of 15 ft or more, less); his last
# column is 38.5 mph and above. His "1-way multilane" and "2-way, 2 lanes per direction"
# rows are the same, so a one-way street of any width reads the second row at most;
# "other 2-way multilane" is LTS 3 throughout.
LANE_BESIDE_PARKING_LEVELS = (
    ((1, 2, 2, 3, 3, 3), (2, 2, 3, 3, 3, 3)),
    ((2, 3, 3, 3, 3, 3), (3, 3, 3, 3, 3, 3)),
    ((3, 3, 3, 3, 3, 3), (3, 3, 3, 3, 3, 3)),
)
LANE_SPEED_WORDS = ("25 mph or below", "30 mph", "35 mph", "40 mph", "45 mph", "50 mph or above")


PARKING_NOT_MAPPED_RULE = "parking not mapped"


def _bike_lane_tier(
    speed_mph: float,
    lanes: int,
    width_m: float | None,
    parking: bool | None,
    facility: str = "bike lane",
    oneway: bool = False,
) -> tuple[Stress, str]:
    """Furth v2.2's bike-lane tables, for a painted lane and a rideable paved shoulder
    alike (`LANE_LEVELS`, `LANE_BESIDE_PARKING_LEVELS`). Until 2026-11-13 this was the 2012
    table (no credit at 35 mph or above) with local rules on top to give some of it back.

    What this returns is the table's reading alone. The caller takes the lower of it and
    the same road with no provision (v2.2's note 4, `NOTE_4_RULE`).

    `facility` names the provision in the rule text. `parking` is whether a parking lane
    runs alongside *this provision*: the shoulder call passes False where the road's
    parking is unknown or declared absent (see `_classify`); the bike-lane call passes
    what the tags say. Where it is None (not mapped) BOTH tables are read and the more
    stressful level is taken: beside-parking is the worse reading up to 35 mph and the
    better one from 40 mph, where Furth's beside-parking table stops at 3 and his other
    table goes on to 4, so reading unknown parking as present rated a 45 mph six-lane road
    with a lane calmer than the bare road and calmer than the same lane with `parking=no`
    (review r1, finding 1). Unknown width is read as narrow. Furth's notes on blocked lanes
    and on buffers and turn lanes added to the width are not modelled; leaving a buffer
    out is the higher-stress reading.
    """
    column = bisect.bisect_left(LANE_SPEED_MAX_MPH, speed_mph)

    def read(beside_parking: bool) -> tuple[int, list[str]]:
        feet = FURTH_LANE_BESIDE_PARKING_FT if beside_parking else FURTH_LANE_ALONE_FT
        narrow = width_m is None or not meets_width(width_m, feet)
        table = LANE_BESIDE_PARKING_LEVELS if beside_parking else LANE_LEVELS
        row = min(lanes, 2 if beside_parking and oneway else 3) - 1
        words = [facility, "narrow" if narrow else "adequate width", LANE_SPEED_WORDS[column]]
        if beside_parking:
            words.insert(1, "beside parking")
        return table[row][narrow][column], words

    if parking is None:
        # The more stressful of the two; the rule says the parking is not mapped, not
        # which table decided.
        (level, _), (other, words) = read(True), read(False)
        level = max(level, other)
        if width_m is None or not meets_width(width_m, FURTH_LANE_BESIDE_PARKING_FT):
            words[1] = "narrow"
        words.insert(1, PARKING_NOT_MAPPED_RULE)
    else:
        level, words = read(parking)
    if lanes > 1:
        words.append("multilane")
    return Stress(level), ", ".join(words)


# A painted lane on a two-way street with this many through lanes each way or
# more is LTS 3 at least (review RL-3; the owner, 2026-10-16), and so is one on a
# one-way street wider than two lanes (review 2026-10-29). Since 2026-11-13 the
# classifier reads Furth's own multi-lane rows instead; these name the roads for the
# painted-lane report only (`pipeline.run`). The words are the mixed-traffic floor's,
# which `core.segment_info` already says in plain words.
PAINTED_LANE_FLOOR_LANES = 2
PAINTED_LANE_FLOOR = "two-way floor"
PAINTED_LANE_ONEWAY_FLOOR = "wide one-way floor"


def multilane_floor(oneway: bool, lanes: int) -> str | None:
    """The RL-3 floor's words for a street with a painted lane (or a credited
    shoulder) and `lanes` through lanes a direction, or None where it has none.
    `oneway` is false on a carriageway of a divided road."""
    if oneway:
        return PAINTED_LANE_ONEWAY_FLOOR if lanes > PAINTED_LANE_FLOOR_LANES else None
    return PAINTED_LANE_FLOOR if lanes >= PAINTED_LANE_FLOOR_LANES else None


def painted_lane_multilane(
    tags: dict[str, str], divided: bool = False, lanes: int | None = None
) -> bool:
    """Whether a way is a painted lane on a two-way street with
    `PAINTED_LANE_FLOOR_LANES` or more through lanes each way, or on a one-way
    street with more: the roads review RL-3 named. A carriageway of a divided road is
    two-way. `lanes` is the count
    the classifier read, where it has one; an untagged count is one lane, which
    never qualifies."""
    if tags.get("highway", "") in TRAIL_CLASS or tags.get("highway") in MOTOR_ONLY:
        return False
    values = cycleway_values(tags)
    if values & PAINTED_CYCLEWAY and not values & SEPARATED_CYCLEWAY:
        if lanes is None:
            lanes = lanes_per_direction(tags) or DEFAULT_LANES_PER_DIRECTION
        return multilane_floor(is_oneway(tags) and not divided, lanes) is not None
    return False


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
# Furth tables and to curated overrides. Outside urban areas the same roads are
# LTS 4.5, not Avoid (`rural_expressway`; the owner, 2026-10-17).
AVOID_HIGHWAY = frozenset({"trunk", "trunk_link", "primary", "primary_link"})
AVOID_MIN_POSTED_MPH = 50.0


def narrow_by_tags(tags: dict[str, str]) -> bool:
    """A road its tags say is narrow: no centre line, or a surveyed carriageway
    width of `NARROW_ROAD_MAX_WIDTH_M` or less. An untagged road is not narrow
    by default; only its line can say it winds (`winding`)."""
    if tags.get("lane_markings") == "no":
        return True
    width = parse_width_m(tags.get("width:carriageway") or tags.get("width"))
    return width is not None and width <= NARROW_ROAD_MAX_WIDTH_M


def _stretches(points: list[Point], min_length_m: float) -> list[tuple[list[Point], float]]:
    """The line cut at vertices into stretches of at least `min_length_m`, the
    last short piece joined to the stretch before it."""
    stretches: list[tuple[list[Point], float]] = []
    current, length = [points[0]], 0.0
    for a, b in zip(points, points[1:], strict=False):
        current.append(b)
        length += haversine(a, b)
        if length >= min_length_m:
            stretches.append((current, length))
            current, length = [b], 0.0
    if length > 0 and stretches:
        last, last_length = stretches.pop()
        stretches.append((last + current[1:], last_length + length))
    return stretches


def _bent(line: list[Point]) -> bool:
    ratio = sinuosity(line)
    return ratio != float("inf") and ratio >= WINDING_SINUOSITY


def _stretches_wind(points: list[Point], min_length_m: float) -> bool | None:
    """The stretch test from one end, or None where the way has fewer than two."""
    stretches = _stretches(points, min_length_m)
    if len(stretches) < WINDING_MIN_STRETCHES:
        return None
    total = sum(length for _, length in stretches)
    bent = [length for line, length in stretches if _bent(line)]
    return len(bent) >= WINDING_MIN_STRETCHES and sum(bent) * 2 >= total


def _turns_both_ways(points: list[Point]) -> bool:
    """A turn of at least `WINDING_TURN_DEG` each way along the line."""
    cos_lat = math.cos(math.radians(points[0].lat))
    headings = [
        math.atan2(b.lat - a.lat, (b.lon - a.lon) * cos_lat)
        for a, b in zip(points, points[1:], strict=False)
        if (a.lon, a.lat) != (b.lon, b.lat)
    ]
    sides = set()
    for h1, h2 in zip(headings, headings[1:], strict=False):
        turn = math.degrees((h2 - h1 + math.pi) % (2 * math.pi) - math.pi)
        if abs(turn) >= WINDING_TURN_DEG:
            sides.add(turn > 0)
    return len(sides) == 2


def winding(coordinates, min_length_m: float = WINDING_MIN_LENGTH_M) -> bool:
    """Whether a line of (lon, lat) points bends enough to keep traffic slow.

    A way long enough for two stretches of `min_length_m` is cut into them
    (`_stretches`) and winds where at least `WINDING_MIN_STRETCHES` have a
    sinuosity (`shape.sinuosity`) of `WINDING_SINUOSITY` or more, together at
    least half its length, cut from either end: the answer does not depend on
    which way the way was drawn. A shorter one, at least `min_length_m` long, is
    read end to end and must turn both ways (`_turns_both_ways`). One corner on a
    straight road does not count either way. A way under `min_length_m` says
    nothing and is read as not winding, and so is a closed ring, whose ratio has
    no meaning."""
    points = [Point(c[0], c[1]) for c in coordinates]
    if len(points) < 3:
        return False
    if sum(haversine(a, b) for a, b in zip(points, points[1:], strict=False)) < min_length_m:
        return False
    forward = _stretches_wind(points, min_length_m)
    backward = _stretches_wind(points[::-1], min_length_m)
    if forward is not None and backward is not None:
        return forward and backward
    return _bent(points) and _turns_both_ways(points)


# Gravel with turns (the owner, 2026-10-30, after a search of measured gravel
# speeds, reports/gravel-speeds/literature-2026-10-30.md in the project files):
# on straight gravel drivers still run 35-40 mph (Kansas, Michigan), and paving
# adds only a mile an hour or so (VTI), but a bend is what slows them. FHWA-RD-99-171
# puts the 85th percentile near 20 mph on a 50 m bend and 40 mph on a 100 m one,
# even on pavement. So an unpaved rural road whose line has tight bends, often
# enough that they are not one corner on a straight road, reads as winding for the
# narrow-road rule (25 mph); straight gravel keeps its default speed and is read in the
# lowest count band (`UNPAVED_RURAL_COUNT_AS`).
TIGHT_BEND_RADIUS_M = 100.0
# The arc the radius is read over, and the spacing the line is resampled at.
TIGHT_BEND_ARC_M = 50.0
TIGHT_BEND_STEP_M = 10.0
# At least two bends, and at least one per this many metres of road.
GRAVEL_MIN_TIGHT_BENDS = 2
GRAVEL_BEND_SPACING_M = 800.0


def _resampled(coordinates, step_m: float) -> list[tuple[float, float]]:
    """The line as local x/y metres, a point every `step_m` along it."""
    lon0, lat0 = coordinates[0][0], coordinates[0][1]
    kx = 111_320.0 * math.cos(math.radians(lat0))
    xy = [((c[0] - lon0) * kx, (c[1] - lat0) * 110_540.0) for c in coordinates]
    out = [xy[0]]
    carry = 0.0
    for (x1, y1), (x2, y2) in zip(xy, xy[1:], strict=False):
        seg = math.hypot(x2 - x1, y2 - y1)
        d = step_m - carry
        while d <= seg:
            t = d / seg
            out.append((x1 + (x2 - x1) * t, y1 + (y2 - y1) * t))
            d += step_m
        carry = seg - (d - step_m)
    return out


def tight_bends(coordinates) -> int:
    """How many separate bends of radius under `TIGHT_BEND_RADIUS_M` the line
    has, each read as the turn over a `TIGHT_BEND_ARC_M` arc. A sharp corner is
    one bend, however many vertices draw it."""
    if len(coordinates) < 3:
        return 0
    points = _resampled(coordinates, TIGHT_BEND_STEP_M)
    headings = [
        math.atan2(b[1] - a[1], b[0] - a[0]) for a, b in zip(points, points[1:], strict=False)
    ]
    turns = [
        (h2 - h1 + math.pi) % (2 * math.pi) - math.pi
        for h1, h2 in zip(headings, headings[1:], strict=False)
    ]
    window = max(1, round(TIGHT_BEND_ARC_M / TIGHT_BEND_STEP_M))
    limit = TIGHT_BEND_ARC_M / TIGHT_BEND_RADIUS_M
    # A bend ends only where the line has run straighter than the limit for a
    # whole arc: a long curve near the limit, whose windows dip over and under it
    # vertex by vertex, is one bend, not one per vertex.
    bends, straight_run = 0, window
    for i in range(max(0, len(turns) - window + 1)):
        if abs(sum(turns[i : i + window])) > limit:
            if straight_run >= window:
                bends += 1
            straight_run = 0
        else:
            straight_run += 1
    return bends


def bends_slow_traffic(coordinates, tags: dict[str, str]) -> bool:
    """The line test the narrow-road rule reads (`winding`), plus, on an unpaved
    road, tight bends often enough to keep drivers slow (`tight_bends`)."""
    if winding(coordinates):
        return True
    if not is_unpaved(tags):
        return False
    points = [Point(c[0], c[1]) for c in coordinates]
    length = sum(haversine(a, b) for a, b in zip(points, points[1:], strict=False))
    bends = tight_bends(coordinates)
    return bends >= GRAVEL_MIN_TIGHT_BENDS and bends * GRAVEL_BEND_SPACING_M >= length


# The owner's service-road step (2026-11-01, the region rating review: "Apply your DC
# alley pick to service roads across the whole region?" - "Yes, all service roads 1.5").
# An alley, driveway, parking aisle or other `highway=service` way at LTS 1 is LTS 1.5:
# few cars and low speed, but delivery trucks, backing cars and blind garage and driveway
# exits. Quiet residential streets at LTS 1 stay at 1. Applied by the rebuild, after
# any agency rating. THIS TEXT IS READ BACK by
# `core.segment_info` and `pipeline.writers`.
SERVICE_ROAD_RULE = "service road step"


def service_road_step(result: StressResult, tags: dict[str, str]) -> StressResult:
    """The owner's service-road step (`SERVICE_ROAD_RULE`) over a way's tier: a
    `highway=service` way open to cars at a flat LTS 1 goes to LTS 1.5. An owner row on the
    way itself (`result.adjustment`) is the more specific call and is left alone, and a way
    closed to cars (rated as a path) is exempt."""
    if getattr(result, "adjustment", None) is not None:
        return result
    if result.tier is not Stress.LTS1 or result.half or tags.get("highway") != "service":
        return result
    if closed_to_motor_traffic(tags):
        return result
    restriction = motor_restriction(tags)
    if restriction is not None and restriction[0] <= Stress.LTS1:
        return result
    return replace(result, half=True, rule=f"{result.rule}, {SERVICE_ROAD_RULE}")


# A side path or protected lane beside a busy road (the owner, 2026-11-12, of the marked
# protected lanes along Old Georgetown Road: "While they are fine for experienced cyclists,
# they might not be LTS 1."). A bike way the rebuild finds running along a named street by
# its geometry (`facility.side_streets`; named or not), or a protected lane tagged on the
# road itself (`facility.on_road_tracks`), takes a level from that street: 1.5 beside a road
# at LTS 3 or 3.5, 2 beside one at LTS 4 or 4.5, 2.5 beside Avoid. Between junctions a rider
# there still meets driveways, turning cars and the traffic beside them. Not measured. An
# owner row on the way itself is the more specific call. The whole rule is written up in
# docs/stress/side-paths.md. THIS TEXT IS READ BACK by `core.segment_info.rule_words` and
# by the rebuild's `rm:beside_busy_road` tag (PR #1242): keep the prefix.
BESIDE_BUSY_ROAD_RULE = "path beside a busy road"
# Where the path starts before its crossings: half of what the road is above
# BESIDE_CALM_ROAD_LEVEL, down to a half step. So 1 beside a road at 2.5 (its crossings still
# count: 2.5 is where the junction model starts to call a road busy,
# `intersections.Road.busy`), 1.5 beside 3 or 3.5, 2 beside 4 or 4.5, 2.5 beside Avoid. One
# line in place of a table; it sits inside the published levels for protected lanes and side
# paths (Maryland DOT 2022: 1 to 3; Montgomery County 2017, Appendix D: 1 to 2.5;
# docs/stress/side-paths.md). Our defaults, not measured.
BESIDE_CALM_ROAD_LEVEL = 2.0
BESIDE_BUSY_ROAD_SHARE = 0.5
# The share of a path's length beside one of the street's ways for that way's level to count,
# so a few metres along a busier carriageway's end do not set the whole path. Our default.
BESIDE_BUSY_ROAD_MIN_SHARE = 0.3
# Half a level more for every CROSSING_FT_PER_HALF_STEP a mile of mouths along the path's
# run that the junction model does not price at route time (`facility.side_path_crossings`:
# each in feet of quiet riding, that model's own price for passing it on a path beside a
# road, `facility.crossing_point_ft`; a way it does price and a slip lane are junctions it
# charges when a route rides through, and are not counted twice: the owner, decision 303,
# "we don't want to double count").
#
# The step is DERIVED, not chosen: it is what riding one mile half a level higher costs
# in the ranking, in the same feet of quiet riding. When the mouths along a mile cost as
# much as riding that mile half a level worse, the path is half a level worse. The
# ranking's own figures give it (`routemaker.calm.multiplier`, the calm metres a metre of
# each level counts for, at the Default ride's position on the slider,
# `CROSSING_STEP_USE_ROADS`): a mile at LTS 2.5 counts 1.67 calm miles more than a mile at
# LTS 2, so 8,802 ft a mile. The costing prices the level pairs differently (1 to 1.5 and
# 1.5 to 2 cost nothing more, 3 to 3.5 costs 5.0 miles a mile); the 2 to 2.5 step is the
# one used, the first step that costs anything and the one most side paths stand at. One
# value for every ride type and slider position, since a way has one level.
#
# It replaces 5,280 ft ("a calm mile of crossings for every mile of path"), our default,
# first fitted to a retired points rule and then left unfitted when the mouth's price
# changed (the independent review of 2026-11-13, finding 5). Nothing here is fitted to a
# road. At today's prices a half step takes 33 LTS 2 mouths or 65 driveways a mile, so the
# step is rare on a long run; the mouths below a step are not charged at all (the level
# moves in half steps), which is the known limit of charging them through the level.
CROSSING_STEP_USE_ROADS = 0.10


def _half_step_ft_per_mile() -> float:
    from . import calm

    pricing = calm.Pricing(use_roads=CROSSING_STEP_USE_ROADS)
    low = calm.multiplier(2, None, pricing)
    high = calm.multiplier(2, None, pricing, half=True)
    return (high - low) * 5280.0


CROSSING_FT_PER_HALF_STEP = _half_step_ft_per_mile()
# Nothing is Avoid (the owner, 2026-11-12): the top of the scale below it.
BESIDE_BUSY_ROAD_MAX = 4.5


def beside_busy_road_base(road_level: float) -> float:
    """Where a path beside a road at `road_level` starts, before its crossings
    (`BESIDE_CALM_ROAD_LEVEL`, `BESIDE_BUSY_ROAD_SHARE`), to the half step below."""
    above = max(road_level - BESIDE_CALM_ROAD_LEVEL, 0.0) * BESIDE_BUSY_ROAD_SHARE
    return 1.0 + math.floor(above * 2) / 2


def level_of(result) -> float:
    """A way's level as it stands, half step included: an owner row's half where a row set
    the tier (`StressResult.adjustment`), else the result's own (an agency's, a rule's)."""
    adjustment = getattr(result, "adjustment", None)
    half = getattr(adjustment, "half", False) if adjustment is not None else result.half
    return int(result.tier) + (0.5 if half else 0.0)


def beside_busy_road_step(
    result: StressResult,
    road_level: float | None,
    *,
    crossing_ft_per_mile: float | None = None,
    contraflow: bool = False,
    ceiling: float | None = None,
) -> StressResult:
    """The side-path step (`BESIDE_BUSY_ROAD_RULE`) over a bike way at a flat LTS 1, from the
    level of the street it runs beside (None where it runs beside none), and half a level
    more for every `CROSSING_FT_PER_HALF_STEP` a mile of driveways and quiet-street mouths
    along its run (the owner, 2026-11-12: "If there are lots of intersections, especially
    sliplanes it could get an even larger bump"; busy streets and slip lanes are priced as
    junctions by the junction model, once, not here). A way an owner row set
    (`result.adjustment`) and a way already
    above LTS 1 are left alone.

    Never above 4.5 (the owner: "no upper limit", "nothing is avoid"), and never above the
    street's own level, the level of a rider in the roadway there: OUR CLAMP (2026-11-13), for
    the owner to confirm. `ceiling` is a second limit where the caller has one (a sidewalk's
    last-resort level; the painted-lane level of a lane behind posts). `contraflow` only says
    why in the rule's words: it is already in the crossing cost."""
    if road_level is None or getattr(result, "adjustment", None) is not None:
        return result
    if result.tier is not Stress.LTS1 or result.half:
        return result
    # 2.5 is the first level the junction model calls busy; below it nothing is asked.
    if road_level < BESIDE_CALM_ROAD_LEVEL + 0.5:
        return result
    base = beside_busy_road_base(road_level)
    why = ["road rated Avoid" if road_level >= 5 else f"road at LTS {road_level:g}"]
    # Half a level for every CROSSING_FT_PER_HALF_STEP, with no cap of its own (the owner,
    # 2026-11-12: "no upper limit. There could be some really terrible bike paths"); never
    # past 4.5 ("nothing is avoid").
    cost = crossing_ft_per_mile or 0.0
    steps = int(cost // CROSSING_FT_PER_HALF_STEP)
    if steps:
        why.append(f"crossings cost {round(cost):d} ft a mile")
        if contraflow:
            why.append("ridden against the traffic beside it")
    level = min(BESIDE_BUSY_ROAD_MAX, base + steps * 0.5)
    limit = min(road_level, ceiling) if ceiling is not None else road_level
    if level > limit:
        # Down to a half step, and never below the start for the road alone.
        level = max(math.floor(limit * 2) / 2, min(base, BESIDE_BUSY_ROAD_MAX))
        why.append("held at the level of the road beside it")
    if level <= 1.0:
        return result
    return replace(
        result,
        tier=Stress(int(level)),
        half=level % 1 == 0.5,
        rule=f"{BESIDE_BUSY_ROAD_RULE} ({'; '.join(why)}), {result.rule}",
    )


# The rule on a `bicycle=use_sidepath` road with a side path mapped beside it (review RL-1).
# The owner, 2026-10-16: "It's very much not recommended, but I believe still legal", and
# "For the use-sidepath roads, make sure there's a sidepath marked." THIS TEXT IS READ BACK
# by `core.segment_info.rule_words`.
USE_SIDEPATH_RULE = "legal but avoid: riders asked to use the side path"
# The rule on a `bicycle=use_sidepath` road whose only side path is on its own way and is a
# sidewalk open to bicycles, or a track that serves one direction only (the hunt 3 stress
# review, finding 5): LTS 4.5, not Avoid and not the bare LTS 4 its sidewalk earns no tier
# over. The owner, round 3, 2026-11-08: "Make them LTS 4.5. They might be the only way
# there." THIS TEXT IS READ BACK by `core.segment_info.rule_words`.
USE_SIDEPATH_ON_ROAD_RULE = (
    "riders asked to use the side path, on the road as a sidewalk or a one-sided track"
)


# The provision rank of a separated track (`tags.cycleway_provision`, `SEPARATED_CYCLEWAY`).
_TRACK_RANK = 2


# A motorway a bicycle may ride (review RL-6): rare here, and the road the
# expressway rule is about at its most extreme, so it is "legal but avoid" too
# rather than an ordinary LTS 4. Open by an explicit grant only: a motorway is
# closed to bicycles by default, and unclear access is closed.
MOTORWAY_AVOID_RULE = "legal but avoid: motorway open to bicycles"
MOTORWAY_OPEN_BICYCLE = frozenset({"yes", "designated", "permissive", "official"})

# A rural expressway is LTS 4.5, not Avoid (the owner, 2026-10-17: "The rural road
# LTS 5s should be LTS4.5 they might be high stress, but there's often no way to
# avoid them."). The same roads as the expressway rule (`AVOID_HIGHWAY`, posted
# `AVOID_MIN_POSTED_MPH` or more), outside the urban-area layer: tier LTS 4 with the
# half step (`StressResult.half`), never Avoid, whatever the road carries. Inside an
# urban area the expressway stays "legal but avoid"; so do a motorway open to
# bicycles, a `use_sidepath` road with its side path, and every curated row. THIS
# TEXT IS READ BACK by `core.segment_info.rule_words`; it does not begin "legal but
# avoid", which the road panel reads as Avoid.
RURAL_EXPRESSWAY_PREFIX = "rural expressway posted"

# The owner's urban 55 mph rule (2026-10-30: "Urban 55 mph are generally either avoid or
# 4.5 unless there's a specific reason to keep them") on a highway OSM has not tagged
# `expressway=yes`: four or more lanes, or a divided carriageway, posted 55 or more, is
# LTS 4.5 in town or out, as MDOT SHA's `rural-expressway` rule already reads Maryland's
# (the owner, 2026-10-31: the same rule everywhere). A tagged expressway keeps the rules
# above. THIS TEXT IS READ BACK like `RURAL_EXPRESSWAY_PREFIX`.
FAST_MULTILANE_PREFIX = "multilane highway posted"
FAST_MULTILANE_MIN_MPH = 55.0


def fast_multilane(
    tags: dict[str, str], divided: bool = False, separate_facility: bool = False
) -> str | None:
    """Why an untagged fast multilane highway is LTS 4.5 (`FAST_MULTILANE_PREFIX`), or None.
    A road with a separated track, on it or mapped beside it, is the owner's "specific
    reason" and keeps its own rating; so does a one-way road that is not a carriageway
    of a divided highway (a ramp)."""
    if tags.get("highway") not in AVOID_HIGHWAY or tags.get("expressway") == "yes":
        return None
    if separate_facility or cycleway_values(tags) & SEPARATED_CYCLEWAY:
        return None
    posted = parse_maxspeed_mph(posted_maxspeed(tags))
    if posted is None or posted < FAST_MULTILANE_MIN_MPH:
        return None
    per_direction = lanes_per_direction(tags)
    if not divided and (is_oneway(tags) or per_direction is None or per_direction < 2):
        return None
    return f"{FAST_MULTILANE_PREFIX} {round(posted):g} mph"


def _fast_expressway_mph(tags: dict[str, str]) -> float | None:
    """The posted speed of an expressway the expressway rule takes, or None.
    Posted speed only: never assumed."""
    if tags.get("highway") not in AVOID_HIGHWAY or tags.get("expressway") != "yes":
        return None
    posted = parse_maxspeed_mph(posted_maxspeed(tags))
    if posted is None or posted < AVOID_MIN_POSTED_MPH:
        return None
    return posted


def legal_but_avoid(tags: dict[str, str], urban: bool = True) -> str | None:
    """Why a way is "legal but avoid", or None. Posted speed only: never assumed.
    A rural expressway (`urban` false) is not: it is LTS 4.5 (`rural_expressway`)."""
    if tags.get("highway") in MOTOR_ONLY and tags.get("bicycle") in MOTORWAY_OPEN_BICYCLE:
        return MOTORWAY_AVOID_RULE
    posted = _fast_expressway_mph(tags)
    if posted is None or not urban:
        return None
    return f"legal but avoid: expressway posted {posted:g} mph"


def rural_expressway(tags: dict[str, str], urban: bool) -> str | None:
    """Why a way is LTS 4.5 as a rural expressway (`RURAL_EXPRESSWAY_PREFIX`), or None."""
    posted = None if urban else _fast_expressway_mph(tags)
    if posted is None:
        return None
    return f"{RURAL_EXPRESSWAY_PREFIX} {posted:g} mph, often no way around"


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
    winding: bool = False,
    side_path: bool = False,
    estimated_aadt: int | None = None,
    observed_speed_mph: float | None = None,
) -> StressResult:
    """Classify one way: its Furth tier, or "legal but avoid" where the rule says so.

    `jurisdiction` is the code of the state the way lies in (a key of `SPEED_LAW`), for
    the speed a way with no posted limit is read at (`default_speed`).
    `divided` says a one-way way is one carriageway of a two-way road
    (`routemaker.divided`): it is scored as the two-way road it is.
    `separate_facility` says the road's bike facility is mapped as its own way
    and lies beside it (`routemaker.facility.separate_pairs`), which the fast
    multi-lane rule counts as bike infrastructure (`fast_multilane`).

    `parking_width_m` is the width of one parking lane where an agency's street
    record gives it (`routemaker.agency_roads`). Furth measures a bike lane
    beside parking as the lane *plus* the parking lane, 15 ft, and OSM's
    `cycleway:width` is the lane alone, so without it the criterion is read
    against the lane's own width and almost no lane beside parking passes. With
    it the two are added where a lane runs beside parking.

    `winding` says the way's own line bends enough to keep traffic slow
    (`winding`, computed from its geometry by the caller), for the owner's
    narrow-road rule (`NARROW_RURAL_ROAD_MPH`).

    `side_path` says a side path is mapped beside the way
    (`routemaker.facility.use_sidepath_paths`): a road tagged `bicycle=use_sidepath`
    with one is "legal but avoid" (`USE_SIDEPATH_RULE`; review RL-1, the owner,
    2026-10-16). With none it is rated on its own merits, and so is one whose side
    path is mapped on its own way (`facility.has_side_path_on_the_road`; hunt 2, S1).

    `estimated_aadt` is a caller's estimate of the traffic on a way nobody counted (a
    modelled volume, say), read in place of the class's usual traffic (`CLASS_COUNT`) and
    said to be an estimate in the rule and the evidence note; a real count (`aadt`)
    outranks it.

    `observed_speed_mph` is the speed traffic actually travels at on the way, where a
    caller has a measurement (an 85th-percentile speed from a public speed dataset, behind
    its own adapter). The tables are written for the prevailing speed (Furth: "speed limit,
    if it matches actual speeds"), so it is read in place of the limit; the limit is still
    what the result reports. With none, the limit is read, which is this module's main
    known limit: streets where drivers go faster than the sign are rated too calm. This is
    the general slot for "drivers rarely obey the speed limit here"; a rider-reported
    input (driver behaviour, close passes) would be a second such field on the way, fed the
    same way, and is not built: no data source exists yet.

    Outside an urban area (`urban` false) an expressway the "legal but avoid" rule
    would take is LTS 4.5 instead (`rural_expressway`; the owner, 2026-10-17)."""
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
        winding,
        estimated_aadt,
        observed_speed_mph,
    )
    reason = legal_but_avoid(tags, urban)
    # Not where the side path is mapped on the road's own way (a track or a
    # bicycle-open sidewalk in its tags, `has_side_path_on_the_road`; hunt 2, S1,
    # 2026-11-08). `use_sidepath_paths` counts such a road as having its side path,
    # which is right for the panel's words, but the graph has one edge for road and
    # path together, so Avoid there priced the very facility the rider is asked to
    # use: `highway=primary` at 40 mph with `cycleway:both=track` came out Avoid
    # where its Furth tier is LTS 1. The road keeps the tier its track earns where the
    # track serves both directions (`cycleway_provision`, the weakest direction, a track).
    # Where the side path on the road is a sidewalk open to bicycles, or a track on one
    # side of a two-way road, the road is LTS 4.5 (`USE_SIDEPATH_ON_ROAD_RULE`; the owner,
    # round 3, 2026-11-08: "Make them LTS 4.5. They might be the only way there."): before,
    # such a road was the bare Furth tier, LTS 4 at 40 mph, its sidewalk earning nothing.
    # A painted lane on the road beside `bicycle=use_sidepath` is a mapping error: the lane is
    # there for bicycles, so they are explicitly allowed on the road. The owner, round 3,
    # 2026-11-08: "If it has a painted lane and requires a sidepath then it's an OSM error"
    # and "Bikes would be explicitly allowed". Such a road is rated on its own merits, its
    # lane included, as if the use_sidepath tag were not there.
    use_sidepath = (
        reason is None
        and side_path
        and is_use_sidepath_road(tags)
        and not painted_lane_on_road(tags)
    )
    if use_sidepath and not has_side_path_on_the_road(tags):
        reason = USE_SIDEPATH_RULE
    if reason is not None:
        rule = f"{reason} (Furth: {result.rule})"
        return replace(result, tier=Stress.AVOID, half=False, rule=rule)
    if use_sidepath and cycleway_provision(tags).rank < _TRACK_RANK:
        rule = f"{USE_SIDEPATH_ON_ROAD_RULE} (Furth: {result.rule})"
        return replace(result, tier=Stress.LTS4, half=True, rule=rule)
    rural = rural_expressway(tags, urban)
    if rural is not None:
        # LTS 4.5 (the owner, 2026-10-17): the rural minimum never reaches it (LTS 1
        # only), and the smoothing and agency steps replace the result whole.
        rule = f"{rural} (Furth: {result.rule})"
        return replace(result, tier=Stress.LTS4, half=True, rule=rule)
    fast = fast_multilane(tags, divided, separate_facility)
    if fast is not None and (result.tier < Stress.LTS4 or not result.half):
        return replace(result, tier=Stress.LTS4, half=True, rule=f"{fast} (Furth: {result.rule})")
    return busy_road_steps(result, tags, urban, separate_facility)


# The busy rural highway (the Virginia ratings review's P7; agreed by the owner, 2026-10-31):
# outside urban areas a two-lane primary or trunk road carrying BUSY_RURAL_HIGHWAY_AADT or
# more is LTS 4.5, as the rural expressways are. OUR DEFAULT: the figure was read off three
# roads (US-15 north of Leesburg, VA-9, US-340), not measured, and no published table has a
# level above 4. Kept because the 4.5 level itself is the owner's; flagged for review.
BUSY_RURAL_HIGHWAY_AADT = 18_000
BUSY_RURAL_HIGHWAY = frozenset({"primary", "trunk"})
BUSY_RURAL_HIGHWAY_RULE = "busy two-lane rural highway"

# Every count at which the classifier can move a way, as the first count on the
# busier side. `pipeline.aadt_smoothing` reads it to say when a street's median
# moved the level; a new count gate goes here too.
VOLUME_GATES = tuple(
    sorted(
        {
            *(rung for rungs, _ in MIXED_TRAFFIC_ROWS.values() for rung in rungs),
            *RURAL_COUNT_RUNGS,
            BUSY_RURAL_HIGHWAY_AADT,
        }
    )
)


def tier_and_half(level: float) -> tuple[Stress, bool]:
    """A level (1, 1.5, ... 4.5, 5) as the stored tier and its half-step flag."""
    return Stress(int(level)), level % 1 != 0


def busy_road_steps(
    result: StressResult,
    tags: dict[str, str],
    urban: bool,
    separate_facility: bool = False,
) -> StressResult:
    """The busy rural highway step (`BUSY_RURAL_HIGHWAY_RULE`) over a way at LTS 4 with no
    bike provision."""
    aadt = result.volume_aadt
    if aadt is None or urban or result.oneway or not result.rule.startswith(NO_PROVISION_RULES):
        return result
    lanes = result.lanes or DEFAULT_LANES_PER_DIRECTION
    if (
        result.tier is Stress.LTS4
        and not result.half
        and tags.get("highway") in BUSY_RURAL_HIGHWAY
        and lanes <= 1
        and aadt >= BUSY_RURAL_HIGHWAY_AADT
    ):
        return replace(result, half=True, rule=f"{result.rule}, {BUSY_RURAL_HIGHWAY_RULE}")
    return result


# How the rule of a road rated with no bike provision begins (`busy_road_steps`).
NO_PROVISION_RULES = ("mixed traffic", RURAL_TABLE_RULE)
# Furth v2.2, note 4 under both bike-lane tables: "Use mixed traffic criteria if it would
# result in lower LTS." The words appended where it decided. THIS TEXT IS READ BACK by
# `core.segment_info`.
NOTE_4_RULE = "its bike lane makes it no worse"
LANE_TOO_NARROW_RULE = "bike lane under the published minimum width: no lane credit"


def rural_table_applies(
    tags: dict[str, str],
    urban: bool,
    lanes: int,
    divided: bool,
    limit_mph: float | None = None,
) -> bool:
    """Whether a way is a rural road for the rural table and its minimum: outside the urban
    areas, a two-way road of one lane each way (Oregon's table is for two-lane roads), of
    any class but `RURAL_NOT_ROADS`, and not a town street: one whose limit, posted or the
    default it is read at, is BUILT_UP_MAX_MPH or less where the map shows a built-up place
    (`built_up`). A sign that says what the default says changes nothing."""
    if limit_mph is not None and limit_mph <= BUILT_UP_MAX_MPH and built_up(tags):
        return False
    return (
        not urban
        and tags.get("highway") not in RURAL_NOT_ROADS
        and lanes <= 1
        and not divided
        and not is_oneway(tags)
    )


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
    winding: bool = False,
    estimated_aadt: int | None = None,
    observed_speed_mph: float | None = None,
) -> StressResult:
    """Classify one way by the tables.

    `aadt` is bidirectional vehicles per day, already normalized.

    `aadt_source` is the publishing agency, not its precedence tier - see
    `StressResult` - and `aadt_year` is the count's vintage. Both are recorded
    on the result whenever `aadt` is given, and both are the derivative's only
    route back to which agency's data is in a segment.

    `urban` selects which speed defaults apply where nothing is posted, and whether the
    rural table is read. It comes from the coverage polygon's urban-area layer at
    preprocessing time.
    """
    highway = tags.get("highway", "")
    assumed: list[str] = []
    narrow_road = False

    if highway in TRAIL_CLASS:
        return StressResult(Stress.LTS1, trail_rule(highway, trail_kind(tags)))

    if highway in MOTOR_ONLY:
        return StressResult(Stress.LTS4, f"motor-only classification ({highway})")

    # --- 1. Speed ---------------------------------------------------------------------
    posted = posted_maxspeed(tags)
    speed_mph = parse_maxspeed_mph(posted)
    if speed_mph is not None and maxspeed_is_unitless(posted):
        # The number was surveyed; the unit was not. Read as mph, which is the
        # higher-stress reading and the only one that exists on a US sign.
        assumed.append("maxspeed unit")
    zone = speed_zone(tags, jurisdiction) if speed_mph is None else None
    speed_source: str | None = None
    if speed_mph is None:
        speed_mph, speed_source = default_speed(tags, zone, urban, divided)
        if (
            not urban
            # A quiet count is no evidence against a slow lane: the rule held only
            # where nothing was counted, so a counted quiet lane rated a level worse than
            # the same lane uncounted (the owner, 2026-10-31).
            and (aadt is None or aadt <= VOLUME_QUIET)
            and highway in NARROW_ROAD_HIGHWAY
            and (
                winding
                or narrow_by_tags(tags)
                # A one-lane gravel road (the owner, 2026-10-30).
                or (is_unpaved(tags) and tags.get("lanes") == "1")
            )
            and speed_mph > NARROW_RURAL_ROAD_MPH
        ):
            speed_mph, speed_source = NARROW_RURAL_ROAD_MPH, SPEED_FROM_NARROW_ROAD
            narrow_road = True
        assumed.append("maxspeed")
    speed_posted = "maxspeed" not in assumed
    # The limit, posted or the law's, which the junction model and the road panel are told.
    # The tables below read the speed traffic was measured at, where a caller has one.
    limit_mph = speed_mph
    if observed_speed_mph is not None:
        speed_mph = observed_speed_mph

    lanes = lanes_per_direction(tags)
    if lanes is None:
        lanes = DEFAULT_LANES_PER_DIRECTION
        assumed.append("lanes")
    # A carriageway of a divided road is not a one-way street: the other
    # direction's traffic is across the median (`routemaker.divided`).
    oneway = is_oneway(tags) and not divided
    # The count the tables read: the measured one, else the caller's estimate for this
    # road, else the usual count of its class and setting (`CLASS_COUNT`). All three go
    # through the same tables.
    count = aadt
    count_source: str | None = None
    count_rule = ""
    if count is None:
        if estimated_aadt is not None:
            count, count_source, count_rule = estimated_aadt, COUNT_FROM_CALLER, ESTIMATE_COUNT_RULE
        else:
            count, count_source = class_count(tags, lanes, urban), COUNT_FROM_CLASS
            count_rule = CLASS_COUNT_RULE
        count_rule = f", {count_rule}"
        assumed.append("traffic count")

    # --- 2. The road with no bike provision -----------------------------------------------
    # Worked out for every road, provision or not: a lane or shoulder is never rated worse
    # than this (Furth v2.2, note 4), and a separated track's road keeps it for the side-path
    # rules (`StressResult.road_level`).
    bare, bare_rule = mixed_traffic_level(speed_mph, count, mixed_traffic_row(tags, lanes, oneway))
    bare_rule += count_rule

    # A rural road. At 45 mph or more (posted, or the default it is read at) Oregon's rural
    # table rates it (literature). Below that the ordinary table above does, as Oregon has
    # it, but never worse than the rural table would (our default): a lower limit cannot
    # make the same road more stressful. Either way it is LTS 2 at least: Oregon's lowest
    # cell at 45 mph or more, the owner's choice below (`RURAL_MIN_LEVEL`).
    rural_rated = rural_table_applies(
        tags, urban, lanes, divided, None if narrow_road else limit_mph
    )
    if rural_rated:
        shoulder = rural_shoulder(tags)
        if shoulder == SHOULDER_UNKNOWN:
            assumed.append("shoulder")
        rural, rural_rule = rural_road_level(count, shoulder)
        if speed_mph >= RURAL_TABLE_MIN_MPH or rural < bare:
            bare, bare_rule = rural, rural_rule + count_rule
        if bare < RURAL_MIN_LEVEL:
            bare, bare_rule = RURAL_MIN_LEVEL, f"{bare_rule}, {RURAL_MIN_RULE}"

    # --- 3. The provision -------------------------------------------------------------------
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
    # A shoulder earns the bike-lane table's credit only when it is wide enough to
    # sit in and someone has surveyed the width.
    shoulder_present = bool(has_shoulder(tags))
    shoulder_width = shoulder_width_m(tags) if shoulder_present else None
    rideable_shoulder = shoulder_width is not None and meets_width(shoulder_width, RIDEABLE_FT)
    # A tag asserting the *absence* of a facility (`cycleway=no`) is not a facility.
    painted = bool(cycleways & PAINTED_CYCLEWAY) and not (cycleways & SEPARATED_CYCLEWAY)
    road_level: float | None = None

    level, rule = bare, bare_rule
    if cycleways & SEPARATED_CYCLEWAY:
        level, rule = 1.0, "separated track alongside"
        road_level = bare
    elif painted:
        # Only the cycleway's own width, and the narrowest among the sides the provision
        # is on (`cycleway_width_m`): reading the roadway `width` made a four-lane
        # arterial lower stress the moment someone surveyed its carriageway.
        width = lane_width_m(tags)
        if width is None:
            assumed.append("cycleway width")
        # The parking beside the lane scored, not anywhere on the road (hunt 2,
        # S3, 2026-11-08): a one-way's left-side lane with `parking:left=no` and
        # `parking:right=lane` is no door-zone lane.
        lane_parking = has_parking_lane(tags, provision_sides(tags))
        if lane_parking is None and "parking" not in assumed:
            assumed.append("parking")
        # Furth's criterion beside parking is the lane plus the parking lane.
        table_width = width
        if width is not None and lane_parking is True and parking_width_m:
            table_width = width + parking_width_m
        lane_tier, lane_rule = _bike_lane_tier(
            speed_mph, lanes, table_width, lane_parking, oneway=oneway
        )
        level, rule = float(lane_tier), lane_rule
        # Under Furth's minimums the stripe is not a lane for his tables: no lane credit.
        too_narrow = width is not None and (
            not meets_width(width, FURTH_LANE_MIN_FT)
            or (
                lane_parking is True
                and bool(parking_width_m)
                and not meets_width(table_width, FURTH_REACH_MIN_FT)
            )
        )
        if too_narrow:
            level, rule = bare, f"{bare_rule}, {LANE_TOO_NARROW_RULE}"
        elif bare < level:
            # Furth v2.2, note 4. Before 2026-11-13 a painted lane made a quiet counted
            # street a level worse (25 mph, 1,500 a day: 1 bare, 2 with a lane).
            level, rule = bare, f"{bare_rule}, {NOTE_4_RULE}"
    elif shoulder_present:
        if shoulder_width is None:
            assumed.append("shoulder width")
        elif rideable_shoulder:
            # A rideable paved shoulder is scored on the bike-lane table (Furth's table is
            # for "bike lanes ... and shoulders"), so it never rates a road better than a
            # lane of its width read the same way. `False` for parking where the road's
            # parking is unknown or declared absent: a parking lane cannot run beside a
            # shoulder, the outermost strip (pinned by
            # `test_a_shoulder_is_measured_against_furths_no_parking_width`). Where the
            # road declares a parking lane the strip is the parking lane or the door zone
            # beside it, and Furth's beside-parking reach applies.
            shoulder_parking = parking if parking is True else False
            shoulder_tier, shoulder_rule = _bike_lane_tier(
                speed_mph,
                lanes,
                shoulder_width,
                shoulder_parking,
                facility="paved shoulder",
            )
            # Note 4 again: the shoulder's table against the road with no shoulder, the
            # count included, whichever is lower. (Before 2026-11-13 a credited shoulder
            # switched the count off: at 30 mph and 8,000 a day a 1.6 m shoulder was 4 and
            # a 1.7 m one was 2.)
            if shoulder_tier < level:
                level, rule = float(shoulder_tier), shoulder_rule

    # A rural road with a lane or shoulder is still a rural road (`RURAL_MIN_LEVEL`).
    if rural_rated and road_level is None and level < RURAL_MIN_LEVEL:
        level, rule = RURAL_MIN_LEVEL, f"{rule}, {RURAL_MIN_RULE}"

    volume_source = aadt_source if aadt is not None else None
    volume_year = aadt_year if aadt is not None else None

    # --- 4. Caps and steps ----------------------------------------------------------------
    # A road closed or restricted to motor traffic carries little of it, so the
    # class-default speed does not set its tier (`motor_restriction`; the WB&A Trail's
    # Bragers Road, way 11507607). It only ever lowers the tier, never where a traffic
    # count says what the road carries, and never touches access.
    restriction = motor_restriction(tags) if aadt is None else None
    capped = False
    if restriction is not None:
        cap, what = restriction
        posted_mph = limit_mph if speed_posted else None
        if posted_mph is not None and posted_mph > RESTRICTED_POSTED_MPH:
            cap = Stress(cap + 1)
        if level > cap:
            # The default speed the tables read is not stated as the reason.
            limited = f"{MOTOR_RESTRICTED_RULE} ({what}), LTS {int(cap)} at most"
            rule = limited if posted_mph is None else f"{limited}, posted {posted_mph:g} mph"
            level = float(cap)
            capped = level < RURAL_MIN_LEVEL

    # A surface that sheds riders is not tolerable to a child, which is what
    # LTS1 asserts, so it floors at LTS2. Maintained gravel still moves nothing.
    # Trail-class ways return above and are not floored.
    if level == 1 and is_rough(tags):
        level, rule = 2.0, rule + ", rough surface"

    if narrow_road:
        rule = rule + f", {NARROW_ROAD_RULE}"

    tier, half = tier_and_half(level)
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
        speed_mph=limit_mph if speed_posted else None,
        lanes=None if "lanes" in assumed else lanes,
        half=half,
        oneway=oneway,
        graph_oneway=is_oneway(tags),
        default_speed_mph=(
            None
            if speed_posted
            else (statutory_default_mph(tags, zone, urban, divided) or limit_mph)
        ),
        road_level=road_level,
        observed_speed_mph=observed_speed_mph,
        speed_source=speed_source,
        count_source=count_source,
        rural_minimum=rural_rated and road_level is None and not capped,
    )


# Motor traffic that is barred or limited (stress-averse default; the owner's
# WB&A Trail report, 2026-10-06: "The WB&A trail has a section that parallels a
# very quiet road, but is marked LTS4 here", logged in OWNER-DECISIONS' "Record of
# owner words used in 444/445"; approved as 444). Closed to motor vehicles, or open only
# to farm and forestry traffic: LTS 1 at most. Open only to the people with a
# right to be there (private, destination, permit, delivery): LTS 2 at most. A
# posted limit above RESTRICTED_POSTED_MPH raises either by one tier.
MOTOR_CLOSED_VALUES = frozenset({"no", "agricultural", "forestry"})
# How the rule of a tier the cap set begins (`pipeline.run.car_free_tier_1` reads it: a
# road closed to motor traffic for good still gets that function's own reason).
MOTOR_RESTRICTED_RULE = "motor traffic restricted"
MOTOR_LIMITED_VALUES = frozenset({"private", "destination", "permit", "delivery"})
RESTRICTED_POSTED_MPH = 30.0
# Most specific first: `motorcar` over `motor_vehicle` over `vehicle`.
MOTOR_RESTRICTION_KEYS = ("motorcar", "motor_vehicle", "vehicle")
# `bicycle` values that keep a way open to bicycles under `access=private/no`.
BICYCLE_ALLOWED_VALUES = frozenset({"yes", "designated", "permissive", "official"})
PUBLIC_ACCESS_VALUES = frozenset({"yes", "permissive", "designated", "official", "public"})


def _restriction_tier(value: str) -> Stress | None:
    if value in MOTOR_CLOSED_VALUES:
        return Stress.LTS1
    if value in MOTOR_LIMITED_VALUES:
        return Stress.LTS2
    return None


def motor_restriction(tags: dict[str, str]) -> tuple[Stress, str] | None:
    """The tier a road's motor-traffic restriction caps it at, and what says so,
    or None for a road open to motor traffic.

    The most specific motor key present decides (`motorcar`, then
    `motor_vehicle`, then `vehicle`): `motor_vehicle=private` + `motorcar=yes`
    is open to cars. With none of them, `access` decides, and only where the
    way's own `bicycle` tag keeps bicycles on it (`access=private` +
    `bicycle=designated`). A road closed to bicycles too has no ride to state
    a stress for (OWNER-DECISIONS 444: skipped where the way is closed to
    bicycles), so it is left as the tables read it: a `bicycle` tag outside
    `BICYCLE_ALLOWED_VALUES` (`no`, `private`, `dismount`, ..., the set
    `routemaker.facility.BICYCLE_ALLOWED` opens; `use_sidepath` is legal, review
    RL-1, and is read as open here), or, with no bicycle
    tag, an `access` or `vehicle` that is not a public value (`vehicle` covers
    bicycles, as `facility.closed_to_motor_traffic` reads it).
    A road open to buses (`tags.open_to_buses`) is not capped: buses are motor
    traffic (FOLLOWUP-BUS-ROADS).
    Stress only: whether a bicycle may ride the way is the access rules' alone.
    """
    if tags.get("highway") in MOTOR_ONLY:
        return None
    bicycle = tags.get("bicycle")
    open_sidepath = bicycle == USE_SIDEPATH and is_use_sidepath_road(tags)
    if bicycle is not None and bicycle not in BICYCLE_ALLOWED_VALUES and not open_sidepath:
        # bicycle=no, private, dismount, ...: closed to bicycles, and use_sidepath
        # where something else closes the road (review RL-1).
        return None
    access = tags.get("access")
    if bicycle is None and any(
        tags.get(key) is not None and tags[key] not in PUBLIC_ACCESS_VALUES
        for key in ("access", "vehicle")
    ):
        # Closed to bicycles as well (access=private or vehicle=no with no
        # bicycle tag): there is no ride to state a stress for.
        return None
    if open_to_buses(tags):
        # Buses are motor traffic (FOLLOWUP-BUS-ROADS): `motor_vehicle=no` +
        # `bus=yes` is a bus road, rated as its class and speed make it.
        return None
    for key in MOTOR_RESTRICTION_KEYS:
        value = tags.get(key)
        if value is not None:
            tier = _restriction_tier(value)
            return None if tier is None else (tier, f"{key}={value}")
    if access is not None:
        tier = _restriction_tier(access)
        if tier is not None:
            return tier, f"access={access}"
    return None


def is_rough(tags: dict[str, str]) -> bool:
    """Whether the surface would shed riders, as distinct from being unpaved.

    `surface` alone cannot tell a maintained gravel road that twenty people can
    ride two abreast from a rutted farm track, which is why `tracktype` and
    `smoothness` are read alongside it and why Group Ride keeps a quality floor
    even when surface avoidance is relaxed.
    """
    # Cobblestone is paved but rough (OWNER-DECISIONS 440, `routemaker.surfaces`).
    return (
        tags.get("surface") in ROUGH_SURFACES
        or surfaces.is_rough_paved(tags)
        or tags.get("tracktype") in ROUGH_TRACKTYPES
        or tags.get("smoothness") in ROUGH_SMOOTHNESS
    )


def is_unpaved(tags: dict[str, str]) -> bool | None:
    """Unpaved but not necessarily rough: the rural gravel case.

    Returns None when `surface` is absent rather than False. Untagged rural
    gravel is common in Loudoun, and reading absence as paved understates the
    unpaved share that the Gravel and rural Group Ride ranking keys on; the
    caller decides what to do with an unknown.

    Paved is every hard surface (OWNER-DECISIONS 440, `routemaker.surfaces`):
    wood boardwalks and bridges, metal decks, brick, sett, `concrete:plates`
    and the rest, not only the five road pavings it once listed.
    """
    surface = tags.get("surface")
    if surface is None:
        return None
    return not surfaces.is_paved_surface(surface)


def is_built_bike_facility(tags: dict[str, str]) -> bool:
    """A path built for bicycles: `highway=cycleway`, or a `path` or `footway` signed
    `bicycle=designated` (OWNER-DECISIONS 448)."""
    highway = tags.get("highway")
    return highway == "cycleway" or (
        highway in ("path", "footway") and tags.get("bicycle") == "designated"
    )


def inferred_unpaved(tags: dict[str, str]) -> bool | None:
    """`is_unpaved` as the map and the segment table carry it: a way tagged
    `highway=track` with no `surface` is read as unpaved, unless its
    `tracktype` is `grade1` (paved or nearly so). OWNER-DECISIONS 376 (park
    trails with no surface tag, PARK-TRAILS-investigation.md, part C): a track
    is a farm, forest or park access way and is gravel or dirt in nearly every
    case, so it draws brown, with the unpaved mark, and stays open to bicycles.

    OWNER-DECISIONS 448 (the Marvin Gaye Trail, 19 of 23 ways `highway=cycleway`
    with no surface, drawn dashed): a built bike facility, `highway=cycleway` or a
    `path` or `footway` with `bicycle=designated`, with no `surface` is read as
    paved (False), like a roadside trail (403). The surface-unknown look stays for
    other trails with no surface: park footpaths and `path` or `footway` without a
    bicycle designation. Access is not read here.

    Only the stored column, and so the map, the unpaved ranking and the trail
    seek, read it; the classifier's own speed cap for an unpaved rural lane keeps
    reading `is_unpaved`, so no tier changes. An explicit `surface` always wins,
    and any other way with no surface stays unknown (None).
    """
    unpaved = is_unpaved(tags)
    if unpaved is None and tags.get("highway") == "track" and tags.get("tracktype") != "grade1":
        return True
    if unpaved is None and is_built_bike_facility(tags):
        return False
    return unpaved
