"""The public JSON API, under /api/.

Django Ninja, as PLAN.md's Backend section has it: Pydantic request and response
models and an OpenAPI schema, served at /api/openapi.json, which is what the
front end's TypeScript types are generated from. The interactive docs page is
off: it loads its script from a third-party CDN, which the planned
Content-Security-Policy of `default-src 'self'` would refuse, and the schema is
all a client needs.

No endpoint here needs a sign-in. The owner's decision of 2026-09-26 is that
the map and route planning work signed out, and that a signed-out plan is not
saved; so POST /api/route reads the routers and the segment table and writes
nothing but its rate-limit count. What stands in for the sign-in is the per-IP
limit (`core.ratelimit.ROUTING`), applied before the body is read.

Every error POST /api/route answers is `{"error": "..."}` with the status the
shared contract names (another method on the path is Django's own 405, and
not JSON):
400 for input this API will not route (including a request too long to be
worth routing), 409 with `"code": "confirm_long"` when a signed-out long ride
has not been confirmed, 422 when the router finds no route, 429 with
Retry-After when the client's budget is spent or its routes are in flight, 502 when
the router does not answer, 503 with Retry-After when the deployment's routing
slots are all busy or the request's time budget ran out (a long ride's with
`"code": "long_ride_timed_out"`, not to be resent unasked), and 500 for anything
else - never a traceback, whatever DEBUG says.

The checks run in this order, outermost first: the content type and declared
body size, then the per-minute count, then the in-flight slots, then Ninja's
parse and validation. The content type comes before the count on purpose: a
cross-site page can send a `text/plain` or form POST without a preflight, and
counting those would let any page a visitor opens spend that visitor's budget.
A malformed JSON body is counted, because only a script can send one.
"""

from __future__ import annotations

import logging
from functools import wraps
from typing import Annotated, Literal

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from ninja import Field, NinjaAPI, Query, Schema, Status
from ninja.decorators import decorate_view
from ninja.errors import HttpError, ValidationError
from pydantic import ConfigDict, StrictBool, StrictInt, field_validator, model_validator

from routemaker import effort, ridetime
from routemaker.geo import Point, haversine

from . import geocode, nearest, presets, ratelimit, routing, segment_info, stoporder

logger = logging.getLogger(__name__)

# The largest body worth parsing. Twenty-five points with generous precision
# and whitespace is well under 2 KB; Django's own ceiling is 2.5 MB, which is a
# thousand times what this endpoint can use and all of it parsed before the
# point count is checked.
MAX_BODY_BYTES = 8 * 1024

MIN_POINTS = 2
MAX_POINTS = 25

# A request's span: the sum of the straight-line distances between consecutive
# points. A route's cost grows with its length - the /route search, then one
# /trace_attributes per leg, then the stress join over every vertex - and the
# operations probe put a 25-point zig-zag across the box at 590 km and 15 s on
# its own, with five of them from one client holding all five of the stack's
# gunicorn workers for 22-43 s and /healthz unanswered for 21 s.
#
# Two figures, from the owner's decision of 2026-09-26 ("I'm on a 160 km ride
# right now. Maybe ask to confirm that a long ride is intended", then "Actually
# do that with anonymous visitors only"):
#
# - Past CONFIRM_SPAN_M a request is a long ride. A signed-out request must say
#   it means one (`confirm_long: true`) or gets 409 with code "confirm_long"
#   and the span, and the router is not called; a signed-in request does not
#   have to. Every long ride, signed in or not, also takes a long in-flight slot
#   (`ratelimit.LONG_ROUTING_IN_FLIGHT`: one per client, one in the deployment;
#   those two figures are the implementation's choice, not the owner's), and
#   has the long time limits (`routing.LONG_PLAN_BUDGET_S`, 50 s in all, the
#   owner's answer of 2026-09-26).
# - Past MAX_SPAN_M nothing is planned: 400 "too long". 200 km is the owner's
#   answer of 2026-09-26 to "What's the longest ride anyone may plan?".
CONFIRM_SPAN_M = 150_000
MAX_SPAN_M = 200_000


# Human sentences give US customary first, metric in brackets (the owner,
# 2026-09-27: "This is a US-based map, so people are more used to miles over
# km. Have both, but metric should be secondary."; OWNER-DECISIONS 85). The
# fields (`span_km`, every `_m`) stay metric.
METRES_PER_MILE = 1609.344


def too_long() -> str:
    """The refusal past MAX_SPAN_M, naming the figure so a rider knows the limit."""
    return (
        f"the route is longer than {round(MAX_SPAN_M / METRES_PER_MILE)} mi "
        f"({MAX_SPAN_M // 1000} km) in straight lines, which is too "
        "long to plan in one request; split it into shorter parts"
    )


# The router's own request limits can refuse a route under MAX_SPAN_M, so this
# one names no figure.
ROUTER_TOO_LONG = (
    "the route is too long for the router to plan in one request; split it into shorter parts"
)

# The Retry-After on a 503 for a request whose time budget ran out.
DEADLINE_RETRY_S = 30

# The `code` on a long ride's 503 when its own budget ran out. A client that
# resends a 503 after its Retry-After should not resend this one by itself:
# the same ride may well take its whole budget again, holding the one long
# slot every time (front-end re-check, 2026-09-27). It is still a 503 with
# Retry-After, so a rider who asks again waits that out first.
LONG_RIDE_TIMED_OUT = "long_ride_timed_out"

api = NinjaAPI(
    title="RouteMaker",
    version="1",
    description="Public route planning for the RouteMaker region. No sign-in.",
    docs_url=None,
    urls_namespace="api",
)


class ErrorOut(Schema):
    error: str


Coordinate = Annotated[float, Field(allow_inf_nan=False)]
LonLat = Annotated[list[Coordinate], Field(min_length=2, max_length=2)]
PresetName = Literal[tuple(presets.PRESETS)]  # type: ignore[valid-type]
WhenName = Literal[ridetime.WHENS]  # type: ignore[valid-type]
CarryingName = Literal[presets.CARRYING_CARGO, presets.CARRYING_PEOPLE]


class RouteIn(Schema):
    model_config = ConfigDict(extra="forbid")

    points: list[LonLat] = Field(
        min_length=MIN_POINTS,
        max_length=MAX_POINTS,
        description="[lon, lat] pairs, start first, each inside the coverage area.",
    )
    preset: PresetName
    confirm_long: StrictBool = Field(
        default=False,
        description=(
            "Set true to plan a signed-out request longer than 93 mi (150 km) of straight line."
        ),
    )
    stress: StrictInt | None = Field(
        default=None,
        ge=presets.STRESS_MIN,
        le=presets.STRESS_MAX,
        description=(
            "The traffic-stress slider, rescaled on 2026-10-01: 0 is traffic tolerant (the"
            " planner warns at 10 or below; it is not the fastest route), 70 is Default, 80"
            " keeps to low-stress ways unless avoiding them takes much longer (the old top),"
            " and above 80 a calm detour search accepts longer routes to avoid LTS 3, 4 and"
            " Avoid roads, rising to about 10 mi of extra riding for every mile of LTS 3 at"
            " 99. At 100 there is no rate: the search finds the least stressful route towards"
            " the target distance (`target_distance_m`), planning a long trip leg by leg"
            " (`calm_search`, `detour` in the answer). Absent: the preset's own start."
        ),
    )
    hills: StrictInt | None = Field(
        default=None,
        ge=presets.HILLS_MIN,
        le=presets.HILLS_MAX,
        description=(
            "The hills slider: -100 avoids climbing, 0 is the fastest time, above 0 looks for"
            " climbs among the router's alternatives (two-point plans up to 31 mi (50 km) of"
            " straight line). Absent: the"
            " preset's own start. Mass Ride does not seek climbs."
        ),
    )
    when: WhenName | None = Field(
        default=None,
        description=(
            "When the ride is: weekend, weekday_rush (Mon-Fri 07-10 and 16-19), weekday_offpeak"
            " or night (21-07 any day). Absent: the setting of the moment the plan is made, in"
            " the region's time."
        ),
    )
    carrying: CarryingName | None = Field(
        default=None,
        description=(
            "Cargo Bike only: what the bike carries - `cargo`, or `people` for Cargo with "
            "passengers (people or pets) - which sets the stress slider's start."
        ),
    )
    assist: StrictBool = Field(
        default=False,
        description=(
            "Cargo Bike only: electric assist. Routes under e-bike rules at a somewhat faster"
            " pace; the hills slider keeps Cargo Bike's start."
        ),
    )
    avoid_gravel: StrictBool = Field(
        default=False,
        description="Steer off unpaved surfaces where there is a paved way round. Any ride type.",
    )
    trails_off: StrictBool = Field(
        default=False,
        description=(
            'The "Keep to roads, not trails" switch: plan on roadways only, with no bike'
            " paths, trails, footways or stairs, and the Key Bridge and Arlington Memorial"
            " Bridge roadways allowed. Any ride type, e-bike rides included. Mass Ride"
            " always rides this way, whatever is sent."
        ),
    )
    system_weight_kg: StrictInt | None = Field(
        default=None,
        description=(
            "The rider's total system weight in kilograms, rider plus bike plus load"
            " (OWNER-DECISIONS 264). The routing is designed for 25 to 700 (about 55 to 1,543 lb,"
            " 337, 352); a total outside that is accepted and planned at the nearer limit,"
            " silently, which the answer's dials echo (338, 352). Optional, and used only at"
            " the top of the stress"
            " slider, where the Hills slider weighs effort-equivalent distance by it: a heavier"
            " system pays more for a climb. Absent: 90, or 120 for Cargo with passengers."
        ),
    )
    debug_junctions: StrictBool = Field(
        default=False,
        description=(
            "Debug (OWNER-DECISIONS 468): add `junctions_debug` to the answer, listing every"
            " junction event of the route with its cost in calm miles, flagged or not. Off by"
            " default; it holds only facts about the route."
        ),
    )
    loop: StrictBool = Field(
        default=False,
        description=(
            "Make it a loop (OWNER-DECISIONS 266): plan start to destination, then back to the"
            " start by a different way. A ride whose last point is its first is a loop whether"
            " or not this is set. The way back prefers roads the way out did not use, and the"
            " answer's `loop` says how much it shares. Not on Mass Ride."
        ),
    )
    target_distance_m: StrictInt | None = Field(
        default=None,
        ge=presets.TARGET_DISTANCE_MIN_M,
        le=presets.TARGET_DISTANCE_MAX_M,
        description=(
            "The rider's target distance, in metres (OWNER-DECISIONS 256, 271), for the top"
            " of the stress slider (100) only, and ignored below it. A soft goal: the search"
            " finds the least stressful route (LTS 4 and Avoid metres plus very high stress"
            " junctions first, then LTS 3 plus higher stress junctions, then distance) at or"
            " under it, and goes past it only where the extra miles buy enough stress (a"
            " stricter bar than below it, OWNER-DECISIONS 268), never past 1.25 times it."
            " `calm_search.over_target_m` says how far over it the route is. Where no route"
            " is that short, the least stressful one found is answered, flagged. Absent: no"
            " target; the ceiling is 1.6 times the router's own route (at least a mile more),"
            " and each extra mile must buy enough stress."
        ),
    )

    @model_validator(mode="after")
    def dials_fit_the_preset(self):
        preset = presets.PRESETS[self.preset]
        if self.hills is not None and self.hills > 0 and not preset.hills_seek:
            raise ValueError(
                "Mass Ride does not look for climbs: a field that slows below balance speed on a"
                " climb walks, so the hills slider stops at the fastest time"
            )
        if self.carrying is not None and preset.carrying is None:
            raise ValueError("carrying applies to the Cargo Bike ride type only")
        if self.carrying is not None and self.carrying not in preset.carrying:
            # The type already says so; this keeps a load the preset has no
            # start for from reaching `presets.stress_start` as a KeyError
            # (mutation review r1, A11).
            raise ValueError("carrying is cargo or people")
        if self.stress is not None and self.stress > preset.stress_max:
            raise ValueError(
                "Mass Ride keeps to the most direct roadway: a field that takes the road is not"
                " steered onto side streets, so the traffic slider stays at its lowest"
            )
        if self.assist and preset.assist_speed_kmh is None:
            raise ValueError("assist applies to the Cargo Bike ride type only")
        return self

    @field_validator("system_weight_kg")
    @classmethod
    def _weight_at_the_nearer_limit(cls, value: int | None) -> int | None:
        """OWNER-DECISIONS 338, 352: a weight outside the range is planned at the
        nearer limit, silently, not refused."""
        if value is None:
            return None
        return int(effort.clamp_mass_kg(value))

    @field_validator("points")
    @classmethod
    def inside_coverage(cls, points: list[list[float]]) -> list[list[float]]:
        west, south, east, north = settings.COVERAGE_BBOX
        for index, (lon, lat) in enumerate(points):
            if not (west <= lon <= east and south <= lat <= north):
                raise ValueError(f"point {index} is outside the area this map covers")
        if span_m(points) > MAX_SPAN_M:
            raise ValueError(too_long())
        return points


def span_m(points: list[list[float]]) -> float:
    """The sum of the straight-line distances between consecutive points."""
    return sum(haversine(Point(*a), Point(*b)) for a, b in zip(points, points[1:], strict=False))


def signed_in(request) -> bool:
    """Whether the request carries a current session of an account in standing.

    Reading the session here changes nothing about CSRF: the endpoint changes
    no state, and a cross-site page cannot send it `application/json` without a
    preflight, which is never granted. A forged or stale cookie is simply no
    session - Django finds no row for it, and `SessionEpochMiddleware` signs
    out a session issued under an old epoch - so it is treated as anonymous.
    """
    user = getattr(request, "user", None)
    return bool(user is not None and user.is_authenticated and getattr(user, "is_active", False))


class ConfirmLongOut(Schema):
    error: str
    code: Literal["confirm_long"]
    span_km: int


class BusyOut(Schema):
    error: str
    code: Literal["long_ride_timed_out"] | None = Field(
        default=None,
        description=(
            "Present only when a long ride ran out of its time budget: show it, and do not"
            " resend it without the rider asking."
        ),
    )


class LineString(Schema):
    type: Literal["LineString"]
    coordinates: list[list[float]]


class StressOut(Schema):
    model_config = ConfigDict(populate_by_name=True)

    tier_1: float = Field(alias="1")
    tier_2: float = Field(alias="2")
    tier_3: float = Field(alias="3")
    tier_4: float = Field(alias="4")
    tier_5: float = Field(alias="5", description="Legal but avoid.")
    unknown: float


class FacilityOut(Schema):
    """Metres on each of the owner's facility classes; they sum to the distance."""

    path: float = Field(description="Traffic-free: off-road paths, and roads closed to cars.")
    protected: float = Field(description="Protected lanes, on the roadway or beside it.")
    lane: float = Field(description="Painted lanes.")
    none: float = Field(description="Ordinary streets, sharrows included.")
    unknown: float


class StressSpanOut(Schema):
    """One coloured section of the route (OWNER-DECISIONS item 81: "Could we
    also get a color on the route for what LTS it is?"), in whole metres along
    the route's traced length, in route order. Sections of one class are
    merged, and a section under 10 m is folded into its neighbour; `stress_m`
    and `facility_m` stay the exact totals. A leg that could not be traced,
    and every section of a plan whose joins ran past the budget, is one
    section with tier and facility null."""

    from_m: int
    to_m: int
    tier: int | None = Field(description="1-4, or 5 (legal but avoid); null: unknown.")
    facility: Literal["path", "protected", "lane", "none"] | None = Field(
        description="The facility class; null: unknown."
    )
    unpaved: bool | None = Field(
        default=None,
        description=(
            "Whether the section's segments are unpaved (OWNER-DECISIONS 302: the route"
            " line draws it in the brown ramp); null: not known."
        ),
    )
    rpm: int | None = Field(
        default=None,
        description=(
            "A Mass Ride's only (OWNER-DECISIONS 325-327, 387): the lowest carrying capacity "
            "along the section, in riders per minute on the flat at 6-8 mph, from the segment "
            "table's mass_usable_width_m. Sections of a Mass Ride end where the capacity changes "
            "band (under 60, 60-120, 120-200, 200 and up), and a stretch marked Avoid is one "
            "section with null. Null on every section of any other ride type, and of a Mass "
            "Ride on a table built before the column, which the map then draws by stress."
        ),
    )


class DialsOut(Schema):
    """The slider positions and ride time the route was planned with."""

    stress: int
    hills: int
    when: WhenName
    carrying: CarryingName | None
    assist: bool
    avoid_gravel: bool = False
    trails_off: bool = False
    target_distance_m: int | None = Field(
        default=None,
        description="The rider's target distance the route was planned towards, if set.",
    )
    system_weight_kg: int | None = Field(
        default=None,
        description="The rider total system weight the effort was weighed with, if set.",
    )
    loop: bool = Field(default=False, description="Whether the route was planned as a loop.")


class HillsSeekOut(Schema):
    """Present when the hills slider was past its detent."""

    candidates: int = Field(description="Routes compared, the direct one included.")
    chosen: int = Field(description="Which was kept; 0 is the direct route.")
    extra_climb_m: float
    extra_distance_m: float
    limited: Literal["two_points", "long_ride", "timed_out", "calm_first"] | None = Field(
        description=(
            "Why no alternatives were compared, if none were. `calm_first`: at the top of"
            " the stress slider, where seeking hills keeps the stress order and the target"
            " and only prefers climbing between equally calm routes (OWNER-DECISIONS 298(3))."
        )
    )


class StressAdjustmentOut(Schema):
    """A curated stress adjustment the route rides over (the owner, 2026-09-27:
    "Only provide the warnings if the route goes over the road"). The why is
    present only for a public adjustment whose words the owner approved."""

    adjustment_id: str = Field(description="Stable across rebuilds; one per stretch.")
    tier: int = Field(description="The tier the route rode the stretch at.")
    adjusted: Literal[True]
    length_m: float
    direction: Literal["up", "down", "same"] | None = None
    category: (
        Literal[
            "speed",
            "road_conditions",
            "driver_behaviour",
            "intersection",
            "sightlines",
            "better_among_alternatives",
            "other",
        ]
        | None
    ) = None
    public_note: str | None = None
    display: Literal["route_only", "map"] | None = None


class HillsAvoidOut(Schema):
    """Present when the hills slider was below its detent: sustained climbs and
    brake-riding descents weighed among the router's alternatives."""

    candidates: int = Field(description="Routes compared, the router's own included.")
    chosen: int = Field(description="Which was kept; 0 is the router's own route.")
    weight: float = Field(description="How much the sustained-grade cost counted: -hills/100.")
    brake_grade: float | None = Field(
        description="The ride type's grade past which a descent costs; null: never."
    )
    grade_cost_s: float = Field(description="The kept route's sustained climb and descent cost.")
    direct_grade_cost_s: float
    extra_distance_m: float
    limited: Literal["two_points", "long_ride", "timed_out"] | None = Field(
        description="Why no alternatives were compared, if none were."
    )
    kept_middle: bool = Field(
        description=(
            "The route is the hills slider's middle one, because the hill-avoiding route "
            "was busier (the owner: traffic wins)."
        )
    )


class IntersectionOut(Schema):
    """One stressful junction of the route (OWNER-DECISIONS item 172: "put
    markers on intersections in a route, such as an orange marker for higher
    stress intersections and a red one for very high stress intersections.
    That way people know where to watch out or reroute."). Only flagged ones
    are here: a neighbourhood stop sign is never flagged, and a junction below
    the thresholds (`routemaker.intersections.ORANGE_MIN_FT`, `RED_MIN_FT`) is
    not either. On a Mass Ride the colour is the crossed road's tier (item
    138), orange for LTS 3 and red for LTS 4 or Avoid."""

    m: int = Field(description="Metres along the route's traced length.")
    lon: float
    lat: float
    severity: Literal["orange", "red"]
    reason: str = Field(
        description='What a click shows, US units first: "Left turn across a 4-lane 35 mph '
        '(56 km/h) road, no signal".'
    )
    crossed_tier: int | None = Field(description="The busy road's LTS, 3-5; null if unknown.")
    movement: Literal["left", "straight", "right"]
    control: Literal["signal", "stop", "cross_stop", "all_stop", "none"]
    kind: str
    cost_ft: int = Field(description="The model's cost, in feet of equivalent quiet riding.")
    calm_mi: float | None = Field(
        default=None,
        description="The same cost in calm miles, 2 places (467); `calm_km` is the metric.",
    )
    calm_km: float | None = None
    group: int | None = Field(
        default=None,
        description=(
            "Mass Ride only: the number, from 1, of the group of signalized crossings this "
            "junction is one of (`intersection_groups`); null if it is in none. Every "
            "junction stays in the list and on the map."
        ),
    )


class JunctionDebugOut(Schema):
    """One junction event of the route, for the debug list (`debug_junctions`)."""

    m: int
    lon: float
    lat: float
    kind: str
    movement: Literal["left", "straight", "right"]
    control: Literal["signal", "stop", "cross_stop", "all_stop", "none"]
    crossed_tier: int | None
    cost_ft: int
    calm_mi: float
    calm_km: float
    text: str = Field(description='"0.55 calm mi (0.88 calm km)".')
    severity: Literal["orange", "red"] | None
    flagged: bool
    time_factor: float = Field(description="The ride-time factor applied (468a, 469c-469e).")
    assumed_speed: bool = Field(
        description=(
            "The cost read a speed the map does not give: the jurisdiction's statutory"
            " default (469), or 45 mph for an LTS 4 or Avoid road on an older table."
        )
    )
    reason: str


class IntersectionGroupOut(Schema):
    """A Mass Ride's run of signalized crossings, each within a quarter mile of the one
    before (OWNER-DECISIONS 233, 234), as the junction list shows it: one row that
    opens onto its members. Additive: absent from an older API, and null off a Mass
    Ride."""

    group: int = Field(description="Its number, from 1, as `intersections[].group`.")
    from_m: int = Field(description="Metres along the route to its first crossing.")
    to_m: int = Field(description="... to its last.")
    count: int = Field(description="How many crossings, at least 2.")
    lts4: int = Field(description="How many of the crossed roads are LTS 4 or Avoid.")
    streets: list[str] = Field(description="The first three streets crossed, as mapped.")
    more: int = Field(description="How many more streets than `streets` has.")
    severity: Literal["orange", "red"] = Field(description="Its worst member's.")
    members: list[int] = Field(description="Positions in `intersections` of its crossings.")
    text: str = Field(
        description='One phrase, US units first: "1.0 to 1.6 mi (1.6 to 2.6 km): 6 crossings '
        "with traffic signals (17th Street Northwest, 15th Street Northwest, 14th Street "
        'Northwest and 3 more), 2 of them heavy-traffic roads (LTS 4)". No severity: the row '
        "shows that. Never spans a stop (OWNER-DECISIONS 247)."
    )


class SeekOut(Schema):
    """What the trail seek did (`core.trailseek`, OWNER-DECISIONS 194): how many
    corridors of trail and protected lane it found beside the route, how many
    proposals through them it asked the router for, whether one was kept, and why it
    stopped short (`points`, `span`, `time`, `table`; null when it ran to its
    end). `tried` has one row for each route asked for: the corridors it went
    through, the exposure (weighted metres of LTS 3 and worse) the corridors
    replaced and the detour they added as the seek estimated them, the route's
    length and exposure, and `outcome`: `taken`, `not_better`, `busier`,
    `more_lts4` (more LTS 4 and Avoid metres than the router's first route, on
    Trailmaxxing and Cargo with passengers: OWNER-DECISIONS 250), `unread` or
    `no_route`."""

    corridors: int
    asked: int
    routes: int | None = Field(
        default=None,
        description=(
            "How many routes the router was asked for: `asked` counts the proposals,"
            " and a proposal asked again without the search's exclusions is two routes."
        ),
    )
    taken: bool
    limited: str | None = None
    whole_trip: str | None = Field(
        default=None,
        description=(
            "On a plan with stops whose legs were spliced: `taken`, `busier` (past the"
            " whole trip's Traffic-wins allowance), `more_lts4` (more LTS 4 than the"
            " router's first route, OWNER-DECISIONS 250) or `unread`; null where nothing was"
            " spliced. Shown even where `limited` names an earlier stop, such as `time`."
        ),
    )
    tried: list[dict] = Field(default_factory=list)
    legs: int | None = Field(
        default=None,
        description=(
            "How many legs (stretches between consecutive locations) the seek ran over"
            " (OWNER-DECISIONS 203); each `tried` row names its `leg`."
        ),
    )


class LongSearchOut(Schema):
    """A trip past the calm search's working span, planned leg by leg
    (OWNER-DECISIONS 256): how many legs it was cut into, how many were searched
    and how many the time did not reach, the legs in each of the plan's own legs,
    and what was answered (`legs`, or the router's own `router` route where the
    legs were no calmer)."""

    legs: int
    searched: int
    skipped: int
    stops: list[int]
    answered: str | None = None
    per_leg: list[dict] = Field(
        default_factory=list,
        description=(
            "Each leg, in route order: its length, its LTS 4 and LTS 3 metres before and after,"
            " whether it was searched, the longest it was allowed, and why its search stopped."
        ),
    )


class AlternatesOut(Schema):
    """The router's own alternative routes the calm search ranked with its own
    (OWNER-DECISIONS 435, docs/DEVELOPMENT.md, "The router's own alternatives")."""

    given: int = Field(
        description="Routes the router gave other than the one the search started from."
    )
    ranked: int = Field(
        description=(
            "Of those, the ones read and ranked: not busier than the router's first route,"
            " within the LTS 4 hold and the ceiling, their junctions read."
        )
    )
    taken: bool = Field(description="Whether one ranked first and the search started from it.")
    limited: str | None = Field(
        default=None,
        description="`time`: the ask for them or a reading ran out of its time; null otherwise.",
    )


class CalmSearchOut(Schema):
    """What the search over the router's routes did (`core.refine`): the calm
    detour at the top of the stress slider and the avoidance of the worst
    crossings. `limited` says why it stopped short, or why it did not run:
    `time`, `no_route` (every way out was excluded), `untraceable`,
    `excludes` (the router's limit on exclusions was reached),
    `ceiling` (the routes the next round found were all past `ceiling_m`: a calmer,
    longer route may exist, and the route answered may well be within the target),
    `target_distance` (no route within the target distance was found: the least
    stressful one found is answered, `no_fit` true),
    `not_worth` (a spliced route's extra miles did not buy enough stress),
    `split` (a long trip could not be cut into legs), `span`,
    `long_ride`, `points`, `seeking`, `mass_ride`; null when it ran to its
    end. The planner says `time`, `untraceable`, `span`, `long_ride` and
    `seeking` to the rider in plain words where the rider asked for the calm
    detour (frontend/src/lib/summary.ts, `calmSearchNote`)."""

    rate: float = Field(description="Metres of detour accepted per metre of LTS 3 avoided.")
    rounds: int
    excluded: int
    limited: str | None
    original_m: float | None = None
    extra_distance_m: float | None = None
    exposure_before_m: float | None = None
    exposure_after_m: float | None = None
    seek: SeekOut | None = None
    alternates: AlternatesOut | None = Field(
        default=None,
        description=(
            "The router's own alternatives ranked with the search's routes (OWNER-DECISIONS"
            " 435); null where none were asked for (no calm search, stops, a loop, a long"
            " calm plan, or no time)."
        ),
    )
    target_distance_m: float | None = Field(
        default=None,
        description=(
            "At the top of the stress slider (OWNER-DECISIONS 271): the rider's target distance,"
            " in metres; null where they set none."
        ),
    )
    target_distance_set: bool | None = Field(
        default=None, description="Whether the rider set `target_distance_m`."
    )
    ceiling_m: float | None = Field(
        default=None,
        description=(
            "The longest the search would go, in metres: 1.25 times the target distance, or"
            " with no target 1.6 times the router's own route (OWNER-DECISIONS 268, 271)."
        ),
    )
    fits: bool | None = Field(
        default=None,
        description=(
            "Whether the route is within `target_distance_m` (null with no target). False"
            " where the extra miles bought enough stress, or where no route that short was"
            " found (`no_fit` is then true)."
        ),
    )
    no_fit: bool | None = Field(
        default=None,
        description=(
            "True only where no route within `target_distance_m` was found: the least"
            " stressful route found is answered, flagged by `over_target_m`, and `limited` is"
            " `target_distance` (OWNER-DECISIONS 267, 298(2); within the ceiling where one"
            " was, else the least stressful of all found). False where one was found; null"
            " with no target."
        ),
    )
    over_target_m: float | None = Field(
        default=None,
        description=(
            "How far past the target distance the route is, in metres (0 within it; null"
            " with no target). The planner always says it, miles first (OWNER-DECISIONS 271)."
        ),
    )
    fitted_at: int | None = Field(
        default=None,
        description=(
            "Where the router's own route was past the target distance, the traffic position"
            " (0-100) of the first route that fits it: a busier route than the ride type's own."
        ),
    )
    long: LongSearchOut | None = None
    lts4_m_before: float | None = None
    lts4_m_after: float | None = None
    lts3_m_before: float | None = None
    lts3_m_after: float | None = None
    lts4_before_m: float | None = Field(
        default=None,
        description=(
            "Trailmaxxing and Cargo with passengers only (OWNER-DECISIONS 250): metres of"
            " LTS 4 and Avoid on the router's own route, which the search never exceeds."
        ),
    )
    lts4_after_m: float | None = Field(
        default=None, description="... and on the route the search kept."
    )


class DetourOut(Schema):
    """How much longer the route is than the most direct legal one
    (`routemaker.detour`; OWNER-DECISIONS item 164: "just warn people"). `level`
    is null within the allowance of the larger of 1.25 times or 0.33 mi, then
    `note` up to 1.5 times, `warning` above, `strong` above 2 times. `basis` is
    what it was compared with: `direct_route`, or `straight_line` where the
    direct route could not be had (then only a route twice as long and 3 km more
    says `warning`)."""

    basis: Literal["direct_route", "straight_line"]
    reference_m: float
    ratio: float | None
    extra_m: float
    level: Literal["note", "warning", "strong"] | None
    avoided_m: float | None = Field(
        default=None, description="Metres of LTS 3 and worse the detour avoids, where known."
    )


class DescriptionTurnOut(Schema):
    """How the rider comes into a described stretch, or what a junction entry
    is: the movement, the street turned onto, who has the right of way where
    the junction model read the junction, and its severity where it flagged it."""

    movement: Literal["left", "straight", "right"] | None = Field(
        description="Null where the router gave no headings and no junction event did."
    )
    onto: str | None = Field(description="The street turned onto; null on a junction entry.")
    control: Literal["signal", "stop", "cross_stop", "all_stop", "none"] | None = Field(
        description="Null where the junction model did not read the junction."
    )
    severity: Literal["orange", "red"] | None = Field(
        description='"Higher stress" (orange) or "Very high stress" (red), where flagged.'
    )


class DescriptionCrossingOut(Schema):
    """One crossing of a group, as a sub-entry of the full description
    (OWNER-DECISIONS 248: "a group lists its crossings with their mile markers")."""

    from_m: int = Field(description="Metres along the route, scaled as the entries are.")
    from_mi: float
    street: str | None = Field(description="The crossed street, as mapped; null if unnamed.")
    severity: Literal["orange", "red"] | None = None
    crossed_tier: int | None = None
    text: str = Field(
        description='One sentence: "At 1.1 mi (1.8 km): Cross 17th Street Northwest (LTS 4) '
        'at a signal (Very high stress junction)."'
    )


class DescriptionGroupOut(Schema):
    number: int = Field(description="As `intersections[].group`.")
    count: int
    lts4: int = Field(description="How many of the crossed roads are LTS 4 or Avoid.")
    streets: list[str] = Field(description="The first three streets crossed, as mapped.")
    more: int
    crossings: list[DescriptionCrossingOut] | None = Field(
        default=None,
        description=(
            "Every crossing of the group, in route order, in the full description "
            "(OWNER-DECISIONS 248); null in the overview, which keeps one line per group."
        ),
    )


class DescriptionEntryOut(Schema):
    """One entry of the route's description (`routemaker.describe`; OWNER-DECISIONS
    220: blind cyclists, many riding as tandem stokers, need the route in words).
    Stretches, one street at one stress tier and facility, run end to end from 0;
    a `junction` is a flagged junction that is not a turn, at a point, and a
    `via` is where a via point is reached (`Stop 1`, as the points list calls it);
    a `walk` is a short stretch to walk the bicycle over (a kept
    `bicycle=dismount` connector; OWNER-DECISIONS 291(5)).
    Distances are along the route, scaled to `distance_m`. `text` is one plain
    sentence, US units first with the metric once, for reading aloud; the other
    fields are the same facts for a client that words them itself. Additive:
    older clients ignore it, and it is null where it could not be built."""

    kind: Literal["stretch", "junction", "via", "walk"]
    from_m: int
    to_m: int
    from_mi: float
    to_mi: float
    street: str | None = Field(
        description='The street, or "unnamed path" or "unnamed road"; null on a `via` and '
        "where a junction's road has no name."
    )
    tier: int | None = Field(description="1-5 on a stretch; null: not rated, or not a stretch.")
    facility: Literal["path", "protected", "lane"] | None = Field(
        description='The bike facility, where there is one; "none" and unknown are null.'
    )
    turn: DescriptionTurnOut | None = Field(
        description="How the stretch is entered, where it begins at a change of street."
    )
    severity: Literal["orange", "red"] | None = None
    via: int | None = Field(default=None, description="On a `via`: its number, from 1.")
    group: DescriptionGroupOut | None = Field(
        default=None,
        description=(
            "On a Mass Ride's entry for a group of signalized crossings "
            "(OWNER-DECISIONS 233, 234): what it says, as fields."
        ),
    )
    surface: Literal["unpaved", "partly unpaved"] | None = Field(
        default=None,
        description=(
            "On a stretch: unpaved where at least half of it is, partly unpaved where "
            "at least 0.1 mi is (OWNER-DECISIONS 280); null: paved or not known."
        ),
    )
    text: str
    text_lanes_hidden: str | None = Field(
        default=None,
        description=(
            "On a stretch: `text` with painted lanes on LTS 4 and Avoid not called bike "
            'lanes, for the client switch "Show bike lanes on high-stress roads" '
            "(OWNER-DECISIONS 275); null where that is `text`."
        ),
    )


class MovedPointOut(Schema):
    """A trip point the planner moved (OWNER-DECISIONS 291(4)): one inside the
    National Zoo goes to its bike racks, so a route to the Zoo ends there."""

    index: int = Field(description="The point's place in `points`, from 0.")
    asked: list[float] = Field(description="[lon, lat] as asked.")
    routed: list[float] = Field(description="[lon, lat] as routed.")
    reason: Literal["zoo_racks"]
    note: str = Field(description="One plain sentence to show the rider.")


class ProfileClimbOut(Schema):
    """One sustained climb of the profile, for the chart's climbs table
    (OWNER-DECISIONS 322; on a Mass Ride also 328(c): the capacity it costs)."""

    from_m: int = Field(description="Metres along the route where it starts.")
    to_m: int
    gain_m: float
    avg_grade_pct: float
    max_grade_pct: float
    tier: int | None = Field(description="The highest LTS tier (1-5) of the sections it rides.")
    capacity_drop_pct: int | None = Field(
        default=None,
        description="Mass Ride only: the most the climb takes off a stretch's riders a minute.",
    )
    min_riders_per_min: int | None = Field(
        default=None, description="Mass Ride only: the least the climb carries."
    )


class ProfileFlowOut(Schema):
    narrowest_riders_per_min: int | None
    narrowest_m: int | None = Field(description="Metres along the route to the narrowest sample.")
    typical_riders_per_min: int | None = Field(description="The median over the route.")


class ProfileCrossingOut(Schema):
    """A Mass Ride's major junction (OWNER-DECISIONS 333, 396): one that crosses or joins a
    road of LTS 3 or higher, whatever its control, or any junction with a stress rating."""

    m: int
    street: str | None = Field(description="The cross street as mapped; null if unnamed.")
    severity: Literal["orange", "red"] | None = Field(
        description=(
            "The planner's junction marker (triangle, diamond); null where the junction is"
            " major only for the busy road it crosses or joins (a dot)."
        )
    )
    control: Literal["signal", "stop", "cross_stop", "all_stop", "none"]
    lanes: int | None = Field(description="Lanes of the street, both directions, if known.")
    crossed_tier: int | None = Field(
        description="The tier of the road that makes it major: crossed, or joined (`kind`)."
    )
    kind: Literal["flagged", "crossing", "joining"] = Field(
        default="flagged",
        description=(
            "Why it is major: a junction the planner flags, a busy road crossed (riding"
            " along a busy road past a busy cross street included), or a busy road joined."
        ),
    )
    corkers_needed: bool = Field(
        description=(
            "Corkers hold it (OWNER-DECISIONS 142, 400): the crossed or joined road is LTS 3"
            " or worse; a left or right turn onto such a road needs them as a crossing does."
        )
    )


class ProfileRangeOut(Schema):
    """A stretch of the profile, metres along the route, from where the stretch begins to
    where it ends (the route's own stretches, not the samples)."""

    from_m: int
    to_m: int


class ProfileCalmStepOut(Schema):
    """One stretch of the route at its own multiplier: the faint step line behind the
    rolling score."""

    from_m: int
    to_m: int
    ratio: float | None = Field(
        description="Calm miles a mile of it counts for; null where it is not rated."
    )
    tier: int | None


class ProfileCalmPointOut(Schema):
    """Calm metres counted at one place: a flagged junction, or an entry into Avoid. Every
    other junction counts in `ratio` and the total but is not listed."""

    m: int
    calm_m: int = Field(description="The calm (quiet-street) metres it counts for.")
    kind: Literal["junction", "avoid_entry"]
    severity: Literal["orange", "red"] | None = Field(
        default=None, description="A flagged junction's marker; null for the others."
    )


class ProfileCalmOut(Schema):
    """The rolling stress score (OWNER-DECISIONS 460.12, 461, 461a-e, 469b; `routemaker.calm`):
    calm miles per actual mile over the window centred on each sample (cut at the route's
    ends), each junction's cost at the ride's intersection weight counted once in every
    window that holds them (at the top of the slider, the worth rule's exchange). 1.0 is
    all quiet-street riding; a path or a protected lane counts below it. Every ride type
    but Mass Ride."""

    window_m: int = Field(description="The window's length, metres (461e: about a mile).")
    ratio: list[float | None] = Field(
        description="At each of `profile.m`; null where the window holds nothing rated."
    )
    steps: list[ProfileCalmStepOut]
    points: list[ProfileCalmPointOut]
    total_calm_m: int = Field(description="The route's calm metres, junctions included.")
    rated_m: int = Field(description="The rated metres they are over.")
    junctions_counted: bool = Field(
        description="False where the junctions could not be read, so none are counted."
    )
    bands: list[float] = Field(
        description=(
            "Where the words change: the 2.5 and 3.5 half-step midpoints at this ride's"
            " slider position (LTS 1-2 below the first, LTS 3 to the second, LTS 4 above)."
        )
    )
    estimate: bool = Field(
        description=(
            "True while each tier's cost is the middle of its modelled range, not the"
            " road's own speed and lanes."
        )
    )


class ProfileOut(Schema):
    """The route's elevation along its distance, for the route chart (OWNER-DECISIONS
    322, 323; Mass Ride 328, 332, 333, 396). Parallel arrays, one entry a router sample, in
    the order ridden: the router samples every `interval_m` along each leg, so `m` is the
    leg's start plus that spacing, never past the leg's end (a joint is two samples at one
    place; a leg with no elevation is a null height at each end). A route over about 60 km
    is thinned to close to 2,000 samples (`routemaker.profile.thin`: each window keeps its
    steepest grade, its highest and lowest heights, its lowest riders figure and its gaps),
    after every figure is worked out on every sample. On a Mass Ride there are riders
    samples too at each place the width changes (a pair at one distance, one each side)
    and along a leg with no elevation (a null height). `elevation_m` is null where the
    router had none, and `grade_pct` is read across four samples (`routemaker.profile`),
    signed, positive uphill."""

    interval_m: float
    m: list[int]
    elevation_m: list[float | None]
    grade_pct: list[float | None]
    climbs: list[ProfileClimbOut]
    riders_per_min: list[int | None] | None = Field(
        default=None,
        description=(
            "Mass Ride only: the grade-adjusted riders a minute at each sample"
            " (`routemaker.flow`, OWNER-DECISIONS 328); null where the width is unknown or"
            " the stretch is marked Avoid (325: no carrying capacity)."
        ),
    )
    flow: ProfileFlowOut | None = None
    crossings: list[ProfileCrossingOut] | None = Field(
        default=None,
        description=(
            "Mass Ride only: the major junctions, in route order. Null where they were not"
            " checked (the junctions could not be read in time); an empty list is none."
        ),
    )
    crossings_complete: bool | None = Field(
        default=None,
        description=(
            "Mass Ride only: false where only the flagged junctions could be read (finding"
            " the busy-road ones failed), so `crossings` may be incomplete; null with"
            " `crossings` null."
        ),
    )
    avoid: list[ProfileRangeOut] | None = Field(
        default=None,
        description="Mass Ride only: the stretches marked Avoid (325), which carry no figure.",
    )
    unchecked: list[ProfileRangeOut] | None = Field(
        default=None,
        description=(
            "Mass Ride only: the stretches on a leg that could not be traced, where neither"
            " the width nor the junctions are known."
        ),
    )
    calm: ProfileCalmOut | None = Field(
        default=None,
        description=(
            "The rolling stress score, calm miles per mile (every ride type but Mass Ride);"
            " null on a Mass Ride or where it could not be built."
        ),
    )


class RouteBody(Schema):
    preset: PresetName
    variant: Literal["standard", "no-trail", "ebike", "weekend", "offroad"]
    geometry: LineString
    distance_m: float
    duration_s: float
    climb_m: float
    descent_m: float
    stress_m: StressOut
    facility_m: FacilityOut
    stress_adjustments: list[StressAdjustmentOut]
    stress_spans: list[StressSpanOut]
    # The elevation along the route for the route chart (OWNER-DECISIONS 322, 323), and on
    # a Mass Ride its riders a minute and major junctions (328, 333). Additive: null where
    # no leg had elevation.
    profile: ProfileOut | None = None
    dials: DialsOut
    hills_seek: HillsSeekOut | None
    hills_avoid: HillsAvoidOut | None
    attribution: list[str]
    # Index in geometry.coordinates of each leg's last vertex, one per leg
    # (points - 1); a leg starts where the one before it ends.
    leg_ends: list[int]
    # The route's stressful junctions, in route order; null where they could not
    # be read in time (the route is answered all the same).
    intersections: list[IntersectionOut] | None
    # A Mass Ride's groups of signalized crossings (OWNER-DECISIONS 233, 234): additive,
    # empty or null elsewhere.
    intersection_groups: list[IntersectionGroupOut] | None = None
    # Every junction event with its cost, only when the request asks (`debug_junctions`).
    junctions_debug: list[JunctionDebugOut] | None = None
    calm_search: CalmSearchOut | None
    detour: DetourOut | None
    # Side-street dodges found and what was done with them (OWNER-DECISIONS 272): null
    # on a loop, which keeps its way back as made, and on each of the routes to choose
    # from, which are answered as the search found them.
    dodges: DodgesOut | None = None
    # The route in words, stretch by stretch (OWNER-DECISIONS 220). Additive:
    # absent or null where it could not be built.
    description: list[DescriptionEntryOut] | None = None
    # The same route with stretches under a quarter of a mile merged into their
    # neighbours (OWNER-DECISIONS 226): never fewer busy stretches or flagged
    # junctions, never across a stop. Both lists are sent so the client switches
    # without a second request and the merged sentences are worded in one place.
    description_overview: list[DescriptionEntryOut] | None = None
    moved_points: list[MovedPointOut] = Field(default_factory=list)
    loop: LoopOut | None = Field(
        default=None, description="Present on a loop: how much of the way back is the way out."
    )
    effort_m: float | None = Field(
        default=None,
        description=(
            "The route's effort-equivalent distance in metres (OWNER-DECISIONS 262-264): its"
            " length weighted by the grade it rides, for the rider's system weight. Where the"
            " route was read for it (the top of the stress slider)."
        ),
    )


class DodgeOut(Schema):
    """One leave-and-rejoin of a road through side streets (OWNER-DECISIONS 272)."""

    street: str = Field(description="The road the route left and rejoined (lower case).")
    via: list[str] = Field(description="The streets it went through, by name.")
    lon: float
    lat: float
    length_m: float = Field(description="How far the dodge went, metres.")
    action: str | None = Field(
        description=(
            "`removed` (the main road's stretch replaced it), `kept`, `skipped` (no weave:"
            " not checked) or `unchecked` (the pass stopped first)."
        )
    )
    reason: str | None = Field(
        description=(
            "Why: `no_stress_gain` (removed), `stress` (it avoids enough), `top` (it avoids"
            " LTS 4, Avoid or a red junction), `longer`, `hills`, `events`, `no_route`,"
            " `no_splice`, `no_exclusion` or `untraceable` (kept); `short` (under 50 m) or"
            " `straight` (fewer than two turns) (skipped)."
        )
    )
    avoided_m: float | None = Field(
        description="The higher-stress metres the dodge avoids against the main road."
    )
    needed_m: float | None = Field(
        description=(
            "What it had to avoid to be kept: 0.25 mi plus 80 m a turn past two; at the"
            " top of the stress slider, more than 50 m whatever the turns."
        )
    )
    turns_saved: int | None = Field(description="Turns the main road saves over the dodge.")
    extra_m: float | None = Field(
        description="Metres the dodge adds over the main road (negative: it is shorter)."
    )


class DodgesOut(Schema):
    """What the pass that takes out pointless side-street dodges did (`core.dedodge`,
    OWNER-DECISIONS 272). `limited` says why it stopped short: `time` or `checks`."""

    found: int
    removed: int
    kept: int
    skipped: int = Field(
        default=0, description="Found and not checked: under 50 m, or fewer than two turns."
    )
    checked: int
    saved_m: float = Field(description="The metres the replacements took off the route.")
    limited: str | None
    items: list[DodgeOut]


class LoopOut(Schema):
    """What a loop's way back shares with its way out (OWNER-DECISIONS 266)."""

    overlap_pct: float | None = Field(
        default=None,
        description="Percent of the way back, by length, on a way the way out also rides.",
    )
    shared_m: float | None = None
    return_m: float | None = None
    excluded: int = Field(default=0, description="Points along the way out the way back avoided.")
    tried: int = Field(default=0, description="Routes asked for the way back.")
    fallback: str | None = Field(
        default=None,
        description=(
            "`out_and_back` where the way back is the way out whatever is avoided (one corridor:"
            " the router's own route is kept); `time`, `untraceable` or `points` where it could"
            " not be tried."
        ),
    )


class CandidateOut(RouteBody):
    """Another route to choose from (OWNER-DECISIONS 265): a whole route body of its own,
    so the client draws and describes it as it does the answer."""

    rank: int = Field(description="2 or more: its place in the order of the stress levels.")
    over_target_m: float | None = Field(
        default=None,
        description=(
            "How far past the rider's target distance this route is, in metres (0 within it;"
            " null with no target), OWNER-DECISIONS 271."
        ),
    )


class RouteOut(RouteBody):
    rank: int | None = Field(
        default=None, description="1 where `candidates` has others: the answer's own place."
    )
    candidates: list[CandidateOut] | None = Field(
        default=None,
        description=(
            "At the top of the stress slider (OWNER-DECISIONS 265), up to three other routes"
            " to choose from, ranked after this one by the same order (LTS 4 and Avoid plus"
            " very high stress junctions, then LTS 3 plus higher stress junctions, then the"
            " distance the Hills slider weighs): each within the ceiling, no further past the"
            " target distance than this one, no more than a near-tie worse than it, and"
            " meaningfully different from it and from each other (less than 70% of the same"
            " road, or 5 mi of different road). Null where"
            " there are none: a trip with one obvious corridor has one route. Nothing scores"
            " scenery; the rider judges that from the map."
        ),
    )


# What Pydantic puts before the text of a ValueError raised in a validator.
VALUE_ERROR_PREFIX = "Value error, "


def _error(status: int, message: str) -> JsonResponse:
    return JsonResponse({"error": message}, status=status)


@api.exception_handler(ValidationError)
def invalid_input(request, exc: ValidationError):
    """Ninja's 422 for a body it cannot validate is the contract's 400.

    A refusal raised by one of RouteIn's own validators is a sentence this API
    wrote for a rider ("the route is longer than 200 km ..."), so it goes out as
    it was written: without the field path and Pydantic's "Value error, ",
    which the front end showed as "Points: Value error, the route ...". Pydantic's
    own messages ("Input should be ...") keep the field they are about.
    """
    problems = []
    for error in exc.errors[:5]:
        msg = error.get("msg", "invalid")
        if error.get("type") == "value_error":
            problems.append(msg.removeprefix(VALUE_ERROR_PREFIX))
            continue
        where = ".".join(str(part) for part in error.get("loc", ()) if part != "body")
        problems.append(f"{where}: {msg}" if where else msg)
    return _error(400, "; ".join(p for p in problems if p) or "invalid request")


@api.exception_handler(HttpError)
def http_error(request, exc: HttpError):
    """Ninja raises this itself for a body that is not JSON at all; the contract
    wants the same `{"error"}` shape as every other refusal."""
    return _error(exc.status_code, str(exc))


@api.exception_handler(Exception)
def unexpected(request, exc: Exception):
    """Anything else is a 500 with a fixed sentence and the traceback in the log.

    Ninja's own handler re-raises to Django, which under DJANGO_DEBUG=1 - the
    documented posture of a local stack on :80 - renders the full debug page:
    SQL, paths and settings, to anyone who can make a request fail.
    """
    logger.exception("unhandled error in %s %s", request.method, request.path)
    if request.path.startswith(GEOCODE_PATHS):
        return _error(500, "Something went wrong looking up the place.")
    return _error(500, "Something went wrong planning this route.")


# The place-search endpoints, whose unexpected failure is not a route's.
GEOCODE_PATHS = ("/api/geocode", "/api/reverse")


def errors_as_json(view):
    """The outermost wrapper: the same fixed 500 for anything the limits raise.

    `decorate_view` wraps Ninja's `run`, whose exception handlers cover the
    parse and the view but not these decorators; without this a database that
    fails in the rate limiter - the first thing a request touches - reached
    Django's error page, which under DJANGO_DEBUG=1 is the debug page.
    """

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        # The request's time budget (`routing.plan`'s `started`) runs from
        # `core.middleware.RequestClockMiddleware`, the first middleware, so
        # the other middleware, the count and the slots are inside it. Only a
        # request that reached here without it is stamped now.
        if getattr(request, "routing_started", None) is None:
            request.routing_started = routing.clock()
        try:
            return view(request, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - every failure gets the one answer
            return unexpected(request, exc)

    return wrapped


def json_body_only(view):
    """Refuse a non-JSON or oversized body before anything counts or parses it.

    Requiring `application/json` also means a cross-site page cannot fire this
    endpoint from a plain form or `text/plain` fetch: a JSON content type is
    not CORS-safelisted, so the browser has to preflight it and no CORS header
    is ever granted here.
    """

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        content_type = request.META.get("CONTENT_TYPE", "").split(";")[0].strip().lower()
        if content_type != "application/json":
            return _error(400, "send the body as application/json")
        try:
            declared = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            return _error(400, "invalid Content-Length")
        # The declared length is the whole check: under WSGI Django reads at
        # most CONTENT_LENGTH bytes of the body, so a body longer than it
        # declares is never seen, and gunicorn refuses one with no length.
        if declared > MAX_BODY_BYTES:
            return _error(400, f"the body is larger than {MAX_BODY_BYTES} bytes")
        return view(request, *args, **kwargs)

    return wrapped


@api.post(
    "/route",
    response={
        200: RouteOut,
        400: ErrorOut,
        409: ConfirmLongOut,
        422: ErrorOut,
        429: ErrorOut,
        500: ErrorOut,
        502: ErrorOut,
        503: BusyOut,
    },
    summary="Plan a route through two to twenty-five points on a preset",
    by_alias=True,
)
# Ninja wraps these innermost first, so the order written is the reverse of the
# order they run in: the error guard, the content-type check, the count, the slots.
@decorate_view(
    ratelimit.in_flight_limited(ratelimit.ROUTING_IN_FLIGHT),
    ratelimit.rate_limited(ratelimit.ROUTING),
    json_body_only,
    errors_as_json,
)
def route(request, body: RouteIn, response: HttpResponse):
    # A loop is as long as its way back too.
    loop = routing.loop_wanted(body.points, body.loop, body.preset)
    span = span_m(routing.loop_points(body.points, loop))
    if span > MAX_SPAN_M:
        return Status(400, {"error": too_long()})
    if span <= CONFIRM_SPAN_M:
        if not loop and routing.long_calm_for(
            body.preset,
            body.points,
            _stress_of(body),
            long_ride=False,
            trails_off=body.trails_off,
        ):
            # A long calm plan (OWNER-DECISIONS 256) has the long ride's time
            # limit, so it takes the long ride's in-flight slot as well: one at a
            # time in the deployment. It needs no confirmation: it is not a long
            # ride in straight lines.
            held, refusal = ratelimit.acquire(request, ratelimit.LONG_ROUTING_IN_FLIGHT)
            if refusal is not None:
                return refusal
            try:
                return _plan(request, body, response, long_ride=False, long_calm=True)
            finally:
                ratelimit.release(held)
        return _plan(request, body, response, long_ride=False)
    if not body.confirm_long and not signed_in(request):
        return Status(
            409,
            {
                "error": (
                    f"This is a long ride, about {round(span / METRES_PER_MILE)} mi "
                    f"({round(span / 1000)} km) in straight lines. "
                    "Planning it takes longer; send the request again with confirm_long "
                    "set to plan it."
                ),
                "code": "confirm_long",
                "span_km": round(span / 1000),
            },
        )
    held, refusal = ratelimit.acquire(request, ratelimit.LONG_ROUTING_IN_FLIGHT)
    if refusal is not None:
        return refusal
    try:
        return _plan(request, body, response, long_ride=True)
    finally:
        ratelimit.release(held)


def _stress_of(body: RouteIn) -> int:
    """The traffic slider's position a request plans at."""
    if body.stress is not None:
        return body.stress
    return presets.stress_start(body.preset, body.carrying)


def _plan(request, body: RouteIn, response: HttpResponse, long_ride: bool, long_calm: bool = False):
    started = getattr(request, "routing_started", None)
    try:
        dials = routing.Dials(
            stress=body.stress,
            hills=body.hills,
            when=body.when,
            carrying=body.carrying,
            assist=body.assist,
            avoid_gravel=body.avoid_gravel,
            trails_off=body.trails_off,
            target_distance_m=body.target_distance_m,
            system_weight_kg=body.system_weight_kg,
            loop=body.loop,
            debug_junctions=body.debug_junctions,
        )
        return Status(
            200,
            routing.plan(
                body.points, body.preset, long_ride=long_ride, started=started, dials=dials
            ),
        )
    except routing.TooLong:
        return Status(400, {"error": ROUTER_TOO_LONG})
    except routing.NoRoute as no_route:
        message = "No route joins these points on this preset."
        if no_route.no_path and presets.PRESETS[body.preset].variant == "no-trail":
            # PLAN, Routing model: a no-route result on the no-trail variant
            # reports the disconnection rather than failing blankly.
            message += (
                " A Mass Ride routes only on roadways, and removing trails can leave"
                " no roadway-legal connection between two points."
            )
        elif no_route.no_path and body.trails_off:
            # The same for a ride with "Keep to roads, not trails" on, in its words.
            message += (
                ' With "Keep to roads, not trails" on, this ride uses only roadways, and'
                " there may be no roadway-legal connection between two points."
            )
        return Status(422, {"error": message})
    except routing.RouterUnavailable:
        return Status(502, {"error": "The router is not answering; try again shortly."})
    except routing.DeadlineExceeded:
        # A JsonResponse rather than Status, so an ordinary 503 stays exactly
        # {"error"} instead of carrying "code": null.
        if long_ride or long_calm:
            refusal = JsonResponse(
                {
                    "error": (
                        "Planning this long ride ran out of time. Try again in"
                        f" {DEADLINE_RETRY_S} seconds, or split it into shorter parts."
                    ),
                    "code": LONG_RIDE_TIMED_OUT,
                },
                status=503,
            )
        else:
            refusal = _error(503, "Planning this route took too long; try again shortly.")
        refusal["Retry-After"] = str(DEADLINE_RETRY_S)
        return refusal


class StopOrderOut(Schema):
    order: list[int] = Field(
        description=(
            "The rider's points in the best order, as indices into `points`: the start first,"
            " the destination last unless the ride is a loop the rider chose, every point once."
        )
    )
    changed: bool = Field(description="Whether `order` differs from the order sent.")
    by: Literal["route_cost", "riding_time", "straight_line"] | None = Field(
        description=(
            "What chose the order: the router's cost on the ride's own graph and settings,"
            " riding time with stress and hills priced in, as any route is chosen (up to 10"
            " stops); its riding times alone (more stops, or when it gave no leg costs);"
            " straight-line distance when the router gave neither; or null when there was"
            " nothing to choose (fewer than two stops)."
        )
    )
    exact: bool = Field(
        description="Whether the order is proven the best (up to 13 stops) or only improved."
    )
    before_s: int | None = Field(description="Riding time of the order sent, seconds.")
    after_s: int | None = Field(description="Riding time of `order`, seconds.")
    before_m: int | None = Field(description="Length of the order sent, metres.")
    after_m: int | None = Field(description="Length of `order`, metres.")


@api.post(
    "/stop-order",
    response={
        200: StopOrderOut,
        400: ErrorOut,
        429: ErrorOut,
        500: ErrorOut,
        503: BusyOut,
    },
    summary="The order of a ride's stops that rides best (OWNER-DECISIONS 449)",
    by_alias=True,
)
@decorate_view(
    ratelimit.in_flight_limited(ratelimit.ROUTING_IN_FLIGHT),
    ratelimit.rate_limited(ratelimit.ROUTING),
    json_body_only,
    errors_as_json,
)
def stop_order(request, body: RouteIn, response: HttpResponse):
    """Stops in any order: the body is the route request's, and the answer is the order
    to put the points in. The start stays first and the destination last (in a loop
    the rider chose, every point after the start may move). Nothing is planned: the
    page reorders its points and asks for the route as usual. `confirm_long` and
    `target_distance_m` are accepted and play no part: past 93 mi (150 km) of straight
    line the order is by straight line, and the router is not asked."""
    if body.preset == "mass-ride":
        # OWNER-DECISIONS 449: hidden and off for Mass Ride, whose field rides the
        # route in the order the organiser set.
        return Status(400, {"error": "Mass Ride keeps its stops in the order given"})
    # A loop is as long as its way back too, as for /route.
    loop = routing.loop_wanted(body.points, body.loop, body.preset)
    if span_m(routing.loop_points(body.points, loop)) > MAX_SPAN_M:
        return Status(400, {"error": too_long()})
    dials = routing.Dials(
        stress=body.stress,
        hills=body.hills,
        when=body.when,
        carrying=body.carrying,
        assist=body.assist,
        avoid_gravel=body.avoid_gravel,
        loop=body.loop,
    )
    started = getattr(request, "routing_started", None)
    try:
        return Status(200, stoporder.order(body.points, body.preset, dials, started=started))
    except routing.DeadlineExceeded:
        refusal = _error(503, "Finding the best order took too long; try again shortly.")
        refusal["Retry-After"] = str(DEADLINE_RETRY_S)
        return refusal


class NearestIn(RouteIn):
    """The route request's body, with `points` the rider's position and then the places."""

    points: list[LonLat] = Field(
        min_length=2,
        max_length=1 + nearest.MAX_PLACES,
        description=(
            "[lon, lat] pairs: where the rider is first, then one to"
            f" {nearest.MAX_PLACES} places, each inside the coverage area."
        ),
    )

    @field_validator("points")
    @classmethod
    def inside_coverage(cls, points: list[list[float]]) -> list[list[float]]:
        # Coverage only: the places are not a ride from one to the next, so the
        # route's span limit does not apply; one far off is measured in a straight line.
        west, south, east, north = settings.COVERAGE_BBOX
        for index, (lon, lat) in enumerate(points):
            if not (west <= lon <= east and south <= lat <= north):
                raise ValueError(f"point {index} is outside the area this map covers")
        return points


class NearestPlaceOut(Schema):
    distance_m: int | None = Field(
        description=(
            "How far the place is, metres: by bike along the router's route, or in a straight"
            " line when `by` says so; null where the router found no way there."
        )
    )
    time_s: int | None = Field(
        description="Riding time there, seconds; null by straight line or with no way there."
    )


class NearestOut(Schema):
    by: Literal["riding", "straight_line"] = Field(
        description=(
            "How the distances were measured: by bike on the ride's own graph and settings,"
            " or in straight lines when the router gave none (or a place is over 93 mi"
            " (150 km) away)."
        )
    )
    places: list[NearestPlaceOut] = Field(
        description="One entry per place, in the order sent (`points` after the first)."
    )


@api.post(
    "/nearest",
    response={
        200: NearestOut,
        400: ErrorOut,
        429: ErrorOut,
        500: ErrorOut,
        503: BusyOut,
    },
    summary="How far a few places are to ride from the rider (nearest water, restroom, Metro)",
    by_alias=True,
)
@decorate_view(
    ratelimit.in_flight_limited(ratelimit.ROUTING_IN_FLIGHT),
    ratelimit.rate_limited(ratelimit.ROUTING),
    json_body_only,
    errors_as_json,
)
def nearest_places(request, body: NearestIn, response: HttpResponse):
    """The nearest water, restroom or Metro station (owner, 2026-10-10): the page sends
    where the rider is and the few nearest places in straight lines, with the ride's
    preset and dials; the answer is how far each is by bike on the ride's own graph, so
    the page offers the three nearest. Nothing is planned. `loop`, `confirm_long`,
    `target_distance_m` and `system_weight_kg` are accepted and play no part."""
    dials = routing.Dials(
        stress=body.stress,
        hills=body.hills,
        when=body.when,
        carrying=body.carrying,
        assist=body.assist,
        avoid_gravel=body.avoid_gravel,
    )
    started = getattr(request, "routing_started", None)
    try:
        return Status(200, nearest.distances(body.points, body.preset, dials, started=started))
    except routing.DeadlineExceeded:
        refusal = _error(503, "Finding the nearest places took too long; try again shortly.")
        refusal["Retry-After"] = str(DEADLINE_RETRY_S)
        return refusal


class CoverageGeometry(Schema):
    type: Literal["Polygon"]
    coordinates: list[list[list[float]]]


class CoverageOut(Schema):
    type: Literal["Feature"]
    geometry: CoverageGeometry
    properties: dict


# How long a client may keep the coverage area. It changes only with the
# settings, which is a deploy.
COVERAGE_MAX_AGE_S = 3600


def coverage_ring() -> list[list[float]]:
    """The area this API routes in, as a closed ring, counter-clockwise.

    The same `settings.COVERAGE_BBOX` that `RouteIn.inside_coverage` refuses
    points outside of; the front end greys out everything beyond it, so what
    it shows as covered is what the API accepts.
    """
    west, south, east, north = settings.COVERAGE_BBOX
    return [[west, south], [east, south], [east, north], [west, north], [west, south]]


@api.get(
    "/coverage",
    response={200: CoverageOut, 429: ErrorOut, 500: ErrorOut},
    summary="The area routes may be planned in, as a GeoJSON polygon",
)
@decorate_view(ratelimit.rate_limited(ratelimit.COVERAGE), errors_as_json)
def coverage(request, response: HttpResponse):
    response["Cache-Control"] = f"public, max-age={COVERAGE_MAX_AGE_S}"
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [coverage_ring()]},
        "properties": {},
    }


# --- Place search and place names ---------------------------------------------
#
# GET /api/geocode and GET /api/reverse proxy the self-hosted Photon
# (core.geocode), signed out by the owner's decision of 2026-09-27. They are
# GETs, and a GET is what any page on any site can make a visitor's browser
# send - an <img>, a prefetch - without a preflight; counting those would let
# a foreign page spend the visitor's search budget. A browser says where a
# request came from in Sec-Fetch-Site, which a page cannot set, so a request
# that says it is cross-site is refused before it is counted. A client that is
# not a browser sends no such header and is counted like anyone else.

MAX_QUERY_CHARS = 200
MIN_QUERY_CHARS = 2
LanguageName = Literal[tuple(settings.PHOTON_LANGUAGES)]  # type: ignore[valid-type]

# Seconds a browser may reuse an answer. The index changes monthly at most.
SEARCH_MAX_AGE_S = 300
REVERSE_MAX_AGE_S = 3600


def _check_inside(lat: float | None, lon: float | None) -> None:
    if (lat is None) != (lon is None):
        raise ValueError("send both lat and lon, or neither")
    if lat is not None and lon is not None and not geocode.inside(lon, lat):
        raise ValueError("the point is outside the area this map covers")


class GeocodeIn(Schema):
    q: str = Field(description="What to search for: a place, an address or a street.")
    lat: Coordinate | None = Field(default=None, description="Bias results towards this point.")
    lon: Coordinate | None = None
    limit: int = Field(default=geocode.DEFAULT_RESULTS, ge=1, le=geocode.MAX_RESULTS)
    lang: LanguageName = settings.PHOTON_LANGUAGES[0]

    @field_validator("q")
    @classmethod
    def a_real_query(cls, q: str) -> str:
        q = " ".join(q.split())
        if len(q) < MIN_QUERY_CHARS:
            raise ValueError(f"type at least {MIN_QUERY_CHARS} characters to search")
        if len(q) > MAX_QUERY_CHARS:
            raise ValueError(f"a search is at most {MAX_QUERY_CHARS} characters")
        return q

    @model_validator(mode="after")
    def point_inside(self):
        _check_inside(self.lat, self.lon)
        return self


class ReverseIn(Schema):
    lat: Coordinate
    lon: Coordinate
    lang: LanguageName = settings.PHOTON_LANGUAGES[0]

    @model_validator(mode="after")
    def point_inside(self):
        _check_inside(self.lat, self.lon)
        return self


class PlaceOut(Schema):
    name: str = Field(description="A short name: the place, the street or trail, or 'near X'.")
    label: str = Field(description="One line naming it with its neighbourhood or town.")
    lon: float
    lat: float
    kind: str = Field(
        description=(
            "Search: Photon's layer (house, street, city, district, other, ...). Names for a"
            " point: 'street' or 'trail' when named from the route network, 'near' when not."
        )
    )
    osm_type: Literal["N", "W", "R"] | None = Field(
        default=None, description="The OSM element type of the result, when known."
    )
    osm_id: int | None = Field(default=None, description="The OSM element id, when known.")
    osm_key: str | None = Field(
        default=None, description="The OSM tag key that makes it a place (railway, shop, ...)."
    )
    osm_value: str | None = Field(
        default=None, description="That tag's value (station, bicycle, park, cycleway, ...)."
    )


class PlacesOut(Schema):
    results: list[PlaceOut]
    attribution: list[str]


def same_site_only(view):
    """Refuse a request the browser says a foreign page sent, before it is counted."""

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        site = request.META.get("HTTP_SEC_FETCH_SITE", "").strip().lower()
        if site and site not in ("same-origin", "none"):
            return _error(403, "place search answers this site's own pages only")
        return view(request, *args, **kwargs)

    return wrapped


GEOCODE_RESPONSES = {
    200: PlacesOut,
    400: ErrorOut,
    403: ErrorOut,
    429: ErrorOut,
    500: ErrorOut,
    502: ErrorOut,
    503: ErrorOut,
}

GEOCODER_DOWN = "Place search is not available right now; try again shortly."


def _places(response: HttpResponse, found: list[dict], max_age_s: int) -> Status:
    response["Cache-Control"] = f"private, max-age={max_age_s}"
    return Status(200, {"results": found, "attribution": list(geocode.ATTRIBUTION)})


@api.get(
    "/geocode",
    response=GEOCODE_RESPONSES,
    summary="Search for a place inside the coverage area",
)
@decorate_view(
    ratelimit.in_flight_limited(ratelimit.GEOCODE_IN_FLIGHT, ratelimit.search_slots),
    ratelimit.rate_limited(ratelimit.GEOCODE),
    ratelimit.rate_limited(ratelimit.GEOCODE_BURST),
    same_site_only,
    errors_as_json,
)
def geocode_search(request, params: Query[GeocodeIn], response: HttpResponse):
    try:
        found = geocode.search(
            params.q, lat=params.lat, lon=params.lon, limit=params.limit, lang=params.lang
        )
    except geocode.Unavailable as unavailable:
        # Expected while Photon restarts or is being refreshed: one line, no
        # traceback per request.
        logger.warning("place search: the geocoder did not answer: %s", unavailable)
        return Status(502, {"error": GEOCODER_DOWN})
    return _places(response, found, SEARCH_MAX_AGE_S)


@api.get(
    "/reverse",
    response=GEOCODE_RESPONSES,
    summary="Name the place or street at a point inside the coverage area",
)
@decorate_view(
    ratelimit.in_flight_limited(ratelimit.GEOCODE_IN_FLIGHT, ratelimit.name_slots),
    ratelimit.rate_limited(ratelimit.REVERSE),
    ratelimit.rate_limited(ratelimit.REVERSE_BURST),
    same_site_only,
    errors_as_json,
)
def geocode_reverse(request, params: Query[ReverseIn], response: HttpResponse):
    try:
        found = geocode.reverse(params.lat, params.lon, lang=params.lang)
    except geocode.Unavailable as unavailable:
        logger.warning("place name: neither the router nor the geocoder answered: %s", unavailable)
        return Status(502, {"error": GEOCODER_DOWN})
    return _places(response, found, REVERSE_MAX_AGE_S)


# --- What is known about the road at a map spot -------------------------------------
#
# GET /api/segment-info (OWNER-DECISIONS 441, 441a; core.segment_info): read only, signed
# out, counted per client like place names, refused when a foreign page sent it (as the
# place search is), and sharing the place names' router slot. The spot is in the query
# string, which no access log records (OWNER-DECISIONS 395), and is never logged here.

SEGMENT_INFO_MAX_AGE_S = 300


class SegmentInfoIn(Schema):
    lat: Coordinate
    lon: Coordinate

    @model_validator(mode="after")
    def point_inside(self):
        _check_inside(self.lat, self.lon)
        return self


class InfoRowOut(Schema):
    label: str
    value: str
    source: str | None = Field(default=None, description="Where the value came from, in words.")


class InfoSectionOut(Schema):
    id: Literal["road", "stress", "traffic", "riding", "access", "mass"]
    heading: str
    rows: list[InfoRowOut]


class InfoSummaryOut(Schema):
    id: str = Field(description="What the line is: stress, why, speed, lanes, traffic, ...")
    label: str
    value: str


class SegmentInfoOut(Schema):
    found: bool = Field(description="Whether a road or path is within reach of the spot.")
    title: str = Field(
        description="The way's name, 'Unnamed road' or 'Unnamed path', or 'No road here'."
    )
    tier: int | None = Field(default=None, description="Traffic stress, 1-4, or 5 for Avoid.")
    open: bool | None = Field(
        default=None, description="Whether a bicycle may use it; null when not known."
    )
    osm_way_id: int | None = None
    distance_m: float | None = Field(default=None, description="How far the way is from the spot.")
    on_way: list[float] | None = Field(
        default=None,
        description="The nearest point on the way, [lon, lat]: where the Street View link opens.",
    )
    kind: str | None = Field(default=None, description="The kind of way, in a few words.")
    summary: list[InfoSummaryOut] = Field(
        default_factory=list,
        description="The panel's compact lines, one short fact each; sources are in sections.",
    )
    sections: list[InfoSectionOut]
    attribution: list[str]


SEGMENT_INFO_ATTRIBUTION = ("© OpenStreetMap contributors (ODbL)",)


@api.get(
    "/segment-info",
    response={
        200: SegmentInfoOut,
        400: ErrorOut,
        403: ErrorOut,
        429: ErrorOut,
        500: ErrorOut,
        503: ErrorOut,
    },
    summary="What is known about the road or path nearest a spot",
)
@decorate_view(
    ratelimit.in_flight_limited(ratelimit.GEOCODE_IN_FLIGHT, ratelimit.name_slots),
    ratelimit.rate_limited(ratelimit.SEGMENT_INFO),
    ratelimit.rate_limited(ratelimit.SEGMENT_INFO_BURST),
    same_site_only,
    errors_as_json,
)
def road_info(request, params: Query[SegmentInfoIn], response: HttpResponse):
    found = segment_info.segment_info(params.lat, params.lon)
    response["Cache-Control"] = f"private, max-age={SEGMENT_INFO_MAX_AGE_S}"
    return Status(200, {**found, "attribution": list(SEGMENT_INFO_ATTRIBUTION)})
